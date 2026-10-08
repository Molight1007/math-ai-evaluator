from __future__ import annotations

# 2026-10-01 开关注册制（审查 A 级第 2 条）：开关统一走 switch_registry，
# 不再裸读 os.environ —— 既保持 env 优先级（行为不变），又能被 diag/报告还原。
# ★ 2026-10-07 架构解耦（阶段 B2）：注册表已下沉到零依赖的 `contracts/`
# ⇒ 本模块直接 import `contracts.switch_registry`，**不再依赖 agent/**。
from contracts.switch_registry import (
    get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)
"""
Lean 验证桥接层（agent/lean_bridge.py）
========================================

把 Lean 4 形式化验证能力封装为与 agent 链解耦的组件，供 SolverAgent 的
证明题通道在 ``enable_lean_verify`` 开关开启时调用。

核心职责：
- 将自然语言推理（NL reasoning）转化为 Lean 4 代码；
- 调用 Lean 编译器做纯编译验证（不依赖任何 LLM client 的编译路径）；
- 编译失败时用注入的 agent 链 client 分析错误根因，映射为 BugReport/Finding；
- 全程受 wall-clock 超时与 Budget 约束；Lean 环境缺失时降级为
  ``verdict='unknown'``，供上层安全降级回退 LLM 验证。

依赖隔离：
- convert / analyze / fix 阶段的 LLM 调用一律使用注入的 client（依赖注入），
  禁止 import ``测试工具/`` 下的 ``get_config()`` / ``LLMClient``。
- 纯编译路径 ``_compile_lean`` 只依赖 Lean 编译器二进制，不依赖任何 LLM 栈，
  可独立复用。

修改影响:
- 被以下文件依赖: agent/lean_gate.py（deep 档硬验证门禁）、tests/test_lean_bridge.py
- 依赖以下文件: agent/base.py（BugReport / Finding / Budget）
- 自举依赖: deploy/setup_lean.sh（Lean 环境缺失时的自动安装脚本）
"""
import contextlib
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Optional

# ★ 2026-10-07 架构解耦（阶段 B1）：BugReport/Finding 为纯数据，下沉到零依赖的
# `contracts/types.py` ⇒ 本模块不再为此依赖 agent。（`BugReport/Finding` 契约不变）
from contracts.types import BugReport, Finding

# ★ 2026-10-08 拆分（lean_bridge.py 上帝类拆分 · 簇 B）：桥接文本后处理/解析簇
# 已搬至 lean_bridge__postproc.py；此处 re-export 保持外部
# `from tools.lean_local.lean_bridge import <name>` 契约不变（签名/行为零变更）。
from tools.lean_local.lean_bridge__postproc import (  # noqa: F401
    _truncate_error_output,
    _normalize_bridge_response,
    _anti_hack_guard,
    _strip_code_fence,
    hint_for_compile_error,
    _analyze_formal_gaps,
    _parse_analysis_json,
    _unwrap_answer,
    _answer_embedded,
)

# ★ 2026-10-08 拆分（lean_bridge.py 上帝类拆分 · 簇 C）：Lean 环境探测 +
# Mathlib import 归一化簇已搬至 lean_bridge__env.py；此处 re-export 保持外部
# `from tools.lean_local.lean_bridge import <name>` 契约不变（签名/行为零变更）。
from tools.lean_local.lean_bridge__env import (  # noqa: F401
    _project_root,
    _repo_closure_roots,
    _detect_lean_executable,
    _detect_lean_project_dir,
    _closure_roots,
    _has_mathlib_tactics,
    _mathlib_tactic_entry_available,
    CORE_MATHLIB_IMPORTS,
    _mathlib_import_block,
    _normalize_lean_imports,
    _prepend_mathlib_import,
)

logger = logging.getLogger("MathPilot")


def _mk_report(verdict: str, findings=None, reason: str = "",
               code: str = "", **extra) -> BugReport:
    """构造带诊断属性的 BugReport（**早退留痕的统一出口**）。

    ★ 2026-10-07（fix-obs-tail · 静默跳过埋点）：原为 `verify_answer` 的**内嵌** `_mk`。
    本函数把它**上提为模块级**（纯移动，零行为变更），供 `verify()` /
    `_analyze_error()` 等**其它早退路径**复用同一口径 —— 使它们的「静默跳过」
    也能带上 `verdict_reason`（`lean_gate` 会把该属性原样带进 `diag.lean_gate` 条目，
    见 `lean_gate.py` 的 `for _dk in ("verdict_reason", ...)`）。
    `verify_answer` 内部改为 `_mk = _mk_report` 别名，调用点一行未改。
    """
    r = BugReport(verdict=verdict, findings=findings or [])
    try:
        setattr(r, "verdict_reason", reason)
        setattr(r, "lean_code", code or "")
        for _k, _v in extra.items():
            setattr(r, _k, _v)
    except Exception:  # noqa: BLE001
        pass
    return r

# =====================================================================
# Lean 编译路径常量（纯编译，与 LLM 栈解耦）
# =====================================================================

_DEFAULT_LEAN_EXECUTABLE = "lake"      # Lean 4 可执行文件名
_DEFAULT_LEAN_TIMEOUT = 60.0           # 单次编译超时（秒）
_LEAN_DETECT_TIMEOUT = 10              # Lean 环境检测超时（秒）



def _cross_check_problem_numbers(problem: str, lean_code: str) -> bool:
    """防自证交叉核对（2026-09-03 老师指令）：验证代码必须引用题目关键数字。

    自证形态：LLM 生成 'example : (X:ℚ) = X := rfl' —— 编译通过但只验 X=X，
    与题目无关（022 v4 实测 answer_valid 但答案 50005000 ≠ 真值 25502500）。
    规则：problem 中 >=3 位的数字至少一个出现在 lean_code 里。完全不引用 =
    验证代码与题目无关联 = 疑似自证。保守排除 0/1/2/10 等通用小整数。
    v17 补丁（084 实测）：题目无 >=3 位数字时原逻辑直接放行 → 残缺答案
    也能 answer_valid（漏洞）。改为：题目无大数字时，退而检查
    **答案里的数字是否进代码**（用调用方传入的 answer 强化——见 verify_answer）。
    """
    try:
        prob_nums = set(re.findall(r"\b(\d{3,})\b", problem or ""))
        code_nums = set(re.findall(r"\b(\d{3,})\b", lean_code or ""))
        if not prob_nums:
            # 题目本身无 >=3 位数字（罕见）→ 无法按题面交叉，
            # 返回 None 表示"需调用方用答案数字二次核对"
            return None
        common = prob_nums & code_nums
        return len(common) >= 1
    except Exception:  # noqa: BLE001  核对失败宁可放行（不误伤）
        return True


def _is_identity_statement(lean_code: str) -> bool:
    """验证代码是否是 `X = X` 形式的**恒等式**（等号两边文本等价 ⇒ 无验证力）。

    ★★ 2026-10-06 新增（**实测铁证：假执行**）：
    题 002 的验证代码是
        `example : (Real.sqrt 5 - 1) / 2 = (Real.sqrt 5 - 1) / 2 := by norm_num`
    它**编译必然通过、与答案对错毫无关系**，却被判 `verdict="answer_valid"`。
    根因：数字交叉核对 `common2 = (ans_nums & code_nums2) - {"0","1","2"}`
    **区分不了「验证命题」与「恒等式」** —— 恒等式里**当然包含答案的数字**
    （答案在等号两边各写了一遍）⇒ 核对通过。
    既有的 `_is_ground_statement` 只在**题面含参数**时触发，覆盖不到本题（题面非参数型）。

    判据：取 `: … := by` 之间的命题体，按**最外层等号**切两半，
    归一化（去类型标注 / 去命名空间前缀 / 去空白括号 `$ \\ {}`）后**文本相等** ⇒ 恒等式。
    保守：只在能明确切出两半且归一化后完全相等时判 True（不误伤真命题）。
    """
    code = str(lean_code or "")
    m = re.search(r":\s*(.+?)\s*:=\s*by", code, re.DOTALL)
    if not m:
        return False
    parts = re.split(r"(?<![<>=≤≥≠])=(?!=)", m.group(1))
    if len(parts) != 2:
        return False

    def _norm(s: str) -> str:
        # ★ 只删**类型标注**、保留其值：`(0:ℚ)` → `0`。
        #   （首版用 `\([^()]*:[^()]*\)` 把整个 `(0:ℚ)` 删掉，连值一起丢了 ⇒
        #    `(0:ℚ) = 0` 被误判为非恒等式。实测回归抓出。）
        s = re.sub(r"\(([^()]*?)\s*:\s*[^()]*?\)", r"\1", s)
        for _p in ("Real.", "Nat.", "Int.", "Rat.", "Complex."):
            s = s.replace(_p, "")
        s = re.sub(r"[\s$\\{}()\[\]]", "", s)
        for _t in ("ℚ", "ℝ", "ℕ", "ℤ", "ℂ"):
            s = s.replace(_t, "")
        return s

    lhs, rhs = _norm(parts[0]), _norm(parts[1])
    return bool(lhs) and lhs == rhs


def _cross_check_problem_symbols(problem: str, lean_code: str) -> bool:
    """按**题面变量符号**交叉核对 —— 数字核对失效时的兜底防线。

    背景（2026-09-13 实测定位）：`_cross_check_problem_numbers` 在「题面无 ≥3 位
    数字」时返回 None，调用方退化为「答案数字核对」；而当答案的数字只有 0/1/2 时
    （如答案就是 `0`），原逻辑 `not ans_nums - {"0","1","2"}` 恒为 True ⇒ **直接
    放行**。实测 010（题面全是一位数、答案 0）因此把
    `example : (0:ℚ) = 0 := by norm_num` 这类**恒真自证**判为 answer_valid。

    本函数补上兜底：从题面抽取**变量符号**，要求验证代码至少引用其中 2 个。
    真验证代码必然引用题目变量（`∀ p q r s : ℝ, ...`）；只验 X=X 的自证代码不会。
    返回 False = 疑似自证。
    """
    try:
        body = problem or ""
        # 题面中的单字母变量（LaTeX 记法常见形式）；排除单字母命令名与噪声
        cands = re.findall(r"(?<![A-Za-z\\])([a-zA-Z])(?![A-Za-z0-9])", body)
        noise = {"e", "i", "d", "n", "x", "a"}   # e/i/d 多为命令名或虚数；x/a 过于通用
        syms = {c for c in cands if c not in noise}
        if len(syms) < 2:
            return True                     # 题面无可核对符号 ⇒ 不误伤
        code = lean_code or ""
        hit = [s for s in syms
               if re.search(r"(?<![A-Za-z])" + re.escape(s) + r"(?![A-Za-z])", code)]
        return len(hit) >= 2
    except Exception:  # noqa: BLE001  核对失败宁可放行（不误伤）
        return True


# ★★ 2026-09-22（用户口径「将错误逻辑改掉」）：**闭式自证**的硬判据。
#   可证的事实：`verify_answer` 里那条"答案数字是否进代码"的交叉核对
#   **在题面含参数时是循环判据** —— 自证式代码的右端**就是答案本身**，
#   故 `common2`（答案数字 ∩ 代码数字）恒非空 ⇒ 该分支永远放行。
#   实测 001：`example : (2 * -2 : ℚ) = -4 := by norm_num` 因含 `-4` 而被判
#   `answer_valid / compiled_and_guards_passed`，而同题两条**含符号参数的
#   正确候选** `-2(m-1)` 因 `convert_to_lean_failed` 被判 `unknown` 遭拒。
#
#   可证的补强：**ground（无自由标识符）命题只能证明某个具体数值恒等式**，
#   它**不可能**形式化一个含参数的题目（题目的断言本身是关于变量的）。
#   ⇒ 题面含参数时的 ground 通过，必然是自证，一律拒绝。
_PARAM_HINT_RES = (
    re.compile(r"∀|\\forall|for\s+all|任取|对任意|任意"),
    # ★ 2026-09-22 补：中文"求所有/全部/每个"型措辞 ⇒ 答案是一个**解族**，
    #   必然依赖参数/索引。实测漏判：`求所有 a_n` 原先判为非参数（见下方 `[a-zA-Z]_`）。
    re.compile(r"所有|全部|每个|每一|任一"),
    re.compile(r"_\{|\^\{"),                        # LaTeX 下标/上标 `a_{n}` ⇒ 有参数或索引
    re.compile(r"[a-zA-Z]_"),                       # ★ 补：纯下标记法 `a_n` / `f_k`（无花括号）
    # ★ 系数带参数 `2m`/`3n`。**必须紧邻**，不可放宽为 `\d\s*[a-zA-Z]` ——
    #   否则英文散文里的「3 and」「4 The」会被误判为参数，导致纯算术题被误拒。
    re.compile(r"\d[a-zA-Z]"),
    re.compile(r"[a-zA-Z]\s*(?:[+\-*/^=]|\\cdot)"),  # x+ / m= ⇒ 参数参与运算
)

_LEAN_KEYWORDS = {
    "example", "theorem", "lemma", "by", "norm_num", "decide", "native_decide",
    "rfl", "ring", "ring_nf", "linarith", "nlinarith", "omega", "simp", "exact",
    "apply", "intro", "have", "show", "calc", "positivity", "field_simp",
    "Nat", "Int", "Rat", "Real", "Complex", "Bool", "Prop", "Type", "True", "False",
    "forall", "exists", "fun", "if", "then", "else", "let", "in", "with",
}


def _problem_is_parametric(problem: str) -> bool:
    """题面是否含**参数 / 变量**（而非纯具体数值计算题）。

    有意避开"抽出单字母"的做法：那个口径有 noise 白名单（e/i/d/n/x/a），
    会把最常见的变量字母误当噪声，导致漏判（003 的 `a_n` 就抽不出符号）。
    这里改判"是否出现**数学语境下的参数形态**"，对纯算术题不误伤。
    """
    s = str(problem or "")
    return any(p.search(s) for p in _PARAM_HINT_RES)


def _is_ground_statement(lean_code: str) -> bool:
    """Lean 语句是否为 **ground（闭式）命题** —— 不含任何自由标识符。

    只取 `:=` 之前的 statement 段（tactic 段不参与判断），剔注释，
    再看除 Lean 关键字/类型名以外是否还有标识符剩下。
    """
    try:
        s = str(lean_code or "")
        s = re.sub(r"--[^\n]*", " ", s)
        s = re.sub(r"/-.*?-/", " ", s, flags=re.S)
        head = s.split(":=")[0]
        # 去掉 `example foo :` / `theorem bar :` 里的**自定义命题名**
        head = re.sub(r"\b(?:example|theorem|lemma)\s+[A-Za-z_][A-Za-z0-9_']*\s*", " ", head)
        toks = re.findall(r"[A-Za-z_][A-Za-z0-9_']*", head)
        return not [t for t in toks if t not in _LEAN_KEYWORDS]
    except Exception:  # noqa: BLE001
        return False          # 判不出就不改变既有行为


# ★★ 2026-10-07（**语义分离**：「形式化不充分」≠「命题为假」）
#   实测依据（results/_cloud/results/results/run_2026-10-06_smoke10_1006_2347.jsonl）：
#     · `lean_gate` 共 **123 条**：proof_invalid **73** / unknown **41** /
#       answer_valid **仅 1** ⇒ 闸门几乎不产出有效判定；
#     · 73 条 proof_invalid 中 **51 条** 的 `verdict_reason == "cross_check_failed"`，
#       而这 51 条**全部 `compiled == true`**（代码在 Lean 下**编译通过**）。
#     · 铁证 official112-004：
#         lean_code = "example : (2025 : ℕ) / 2 = 1012 := by norm_num"
#         compiled  = true
#         verdict   = "proof_invalid" / verdict_reason = "cross_check_failed"
#       命题 `(2025:ℕ)/2 = 1012` 在 ℕ 下**为真**、代码被 Lean 接受，却因
#       `_problem_is_parametric ∧ _is_ground_statement` 命中「闭式自证拦截」
#       (`_cc=False`) 落到 `proof_invalid`。
#   ⇒ 这是把「**形式化不充分**（验证代码没锚定题目条件/只验了自证恒等式）」误当成
#     「**命题为假**」。两者必须分属不同结论：
#       · 命题为假（`sys_verify_conflict` / 真编译报错）→ `proof_invalid`（证明失败）
#       · 形式化不充分（`cross_check_failed` / `ground_self_proof` /
#         `identity_self_proof`）→ `unknown`（**无法核验**，**不等于答案错**）
#   本开关（注册名 `lean_crosscheck_as_unknown`，env `LEAN_CROSSCHECK_AS_UNKNOWN`，
#   默认 True）控制新语义：True = 分开（cross_check 系失败 → `unknown`）；
#   设 `LEAN_CROSSCHECK_AS_UNKNOWN=0`（或 config 字段 False）可回退旧行为
#   （一律 `proof_invalid`）做 A/B 对照。
#   读取走 `switch_registry`（与仓库其它开关**同口径**）：**env > config > 默认值**。
#   四件套已补登（2026-10-07）：agent/switch_registry.py / user_agent.AgentConfig
#   （含 kwargs 覆盖白名单）/ agent/param_usage._SPEC。


def _crosscheck_failure_verdict() -> str:
    """cross_check / 自证拦截命中时的**结论码**（语义分离开关）。

    经 ``switch_registry.get_bool("lean_crosscheck_as_unknown")`` 读取，优先级
    **env(`LEAN_CROSSCHECK_AS_UNKNOWN`) > config(`AgentConfig.lean_crosscheck_as_unknown`)
    > 默认 True**（与仓库其它开关一致，不另造口径）。

    - True（默认）→ ``"unknown"``：形式化不充分 = **无法核验**，非答案错；
    - False       → ``"proof_invalid"``：旧语义（用于 A/B 对照）。

    容错：注册表/配置读取异常时回落**新语义** `unknown`（宁可判"无法核验"，
    也不把"代码已编译通过"的候选误判成"证明失败"）。
    """
    try:
        as_unknown = _sw_bool("lean_crosscheck_as_unknown")
    except Exception:  # noqa: BLE001  注册表不可用 → 按新语义（不误伤答案）
        as_unknown = True
    return "unknown" if as_unknown else "proof_invalid"


def _to_exact_number_safe(v: Any) -> Optional[str]:
    """把答案串转成 Lean 可用的**精确数值字面量**（本地实现，不 import agent.*）。

    为什么不复用 `utils.math_eval.to_exact_number`：`agent` 依赖 `tools`，
    反向导入会引入循环依赖（本项目已因循环导入出过 Lean 通道被静默禁用的事故）。
    保守实现：只接受纯数值 / 简单分数 / `\\boxed{}` 包裹的数值；其余返回 None
    （调用方据此放弃系统验算，不影响原有判定）。
    """
    s = (v or "").strip()
    if not s:
        return None
    # 剥外壳：\boxed{...} / $...$ / 括号 / 逗号分隔符
    s = re.sub(r"\\boxed\s*\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\(?:d|t)?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", s)
    s = s.strip("$ \t{}()[]，,。.、")
    # 含 ASCII 字母（数学变量 / 函数名，如 2*x+y）⇒ 非纯数值答案，保守放弃。
    # 否则会从 "2*x+y" 里抠出 "2" 构造出错误命题（实测发现）。
    if re.search(r"[A-Za-z]", s):
        return None
    m = re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?", s)
    if not m:
        m2 = re.search(r"[-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)?", s)
        if not m2:
            return None
        s = m2.group(0)
    s = s.replace(" ", "")
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            from fractions import Fraction
            f = Fraction(a) / Fraction(b)
        except Exception:  # noqa: BLE001
            return None
        if f.denominator == 1:
            return str(f.numerator)
        return "((%d : ℚ) / (%d : ℚ))" % (f.numerator, f.denominator)
    return s




# =====================================================================
# LLM 提示词模板（Lean 转化 / 错误分析）
# =====================================================================

# 转化阶段：把自然语言推理转成 Lean 4 代码
LEAN_CONVERT_SYSTEM = """你是一位 Lean 4 形式化专家。请把下面的数学推理过程转化为一段 Lean 4 代码（theorem + proof）。

要求：
1. 只输出 Lean 4 代码本身，不要输出解释、Markdown 代码块或额外文字。
2. 用 ``theorem ... : ... := by ...`` 结构表达命题与证明。
3. 优先使用 Mathlib 中已有的定理/引理（如 omega、linarith、ring、norm_num、positivity）。
4. 如果推理中某步无法形式化，用 ``sorry`` 占位并在代码末尾用注释标注：
   ``-- UNFORMALIZED: <该步的原始中文推理>``。
5. 不要修改题目本身，只对给定推理做形式化。"""

LEAN_CONVERT_USER = """## 原题
{problem}

## 待形式化的推理
{reasoning}

请输出对应的 Lean 4 代码。"""

# 答案审核阶段（2026-09-01，用户要求"所有题目都要用到 Lean"）：非证明题
# （解答题/计算题）的轻量答案验证 —— 只把最终答案与推理中的关键计算转成
# example + norm_num/ring 等轻量 tactic 证明，不整题形式化，控制编译开销。
LEAN_ANSWER_VERIFY_SYSTEM = """你是一位 Lean 4 形式化专家。你的任务是把"数学解答的最终答案与关键计算"转化为一段轻量 Lean 4 验证代码，用 norm_num / ring / nlinarith / omega / positivity / simp 等轻量 tactic 自动判定解答中的计算是否正确。

============================================================
要求
============================================================
1. 输出 Lean 4 代码：用 ``example : <命题> := by <轻量tactic>`` 形式表达"解答声称的计算/答案"，并让轻量 tactic 完成证明。
   - 数值计算题：example : (3 : ℚ) = 1 + 2 := by norm_num
   - 化简题：    example : (x + 1) ^ 2 = x ^ 2 + 2 * x + 1 := by ring
   - 不等式题：  example : (2 : ℚ) ≤ 3 := by norm_num
2. 只能形式化**解答中明确声称**的计算与答案，禁止自行补充解答未给出的结论。
3. **禁止 sorry / axiom / admit**，证明必须完全由轻量 tactic 完成。
4. **关键（答案锚定，最重要）**：验证命题的**结论侧必须逐字包含 USER 给出的
   最终答案原值**，左侧放推理中算出的关键计算/中间表达式：
   - 数字答案：example : <关键计算> = <最终答案> := by norm_num
     （如最终答案=7 → example : (1 + 2 * 3 : ℚ) = 7 := by norm_num）
   - 表达式答案：右侧写最终答案，左侧写推理中实际出现的中间表达式。
   - **先剥外壳取数值原值**：最终答案常带 \\boxed{} / 中文说明 / 分数等外壳
     （如 \\boxed{3000}、\\dfrac{2617}{2618}、"最大值为 3000"），锚定的是
     **数值原值**——先把外壳剥掉取出数值（3000 / 2617 / 2618），
     再写 ``example : <关键计算> = <该数值> := by <tactic>``，
     结论侧逐字包含该数值；禁止把不含答案数值的式子当验证。
   - **禁止**把你自己重算的结果当右侧：USER 说最终答案是 4，你就必须写
     ``= 4``，**禁止**写 ``= 3`` 或你算出的任何其他值——否则等于没验证答案。
   - **禁止**恒等式作弊（如 example : (a : ℚ) = a，这验证不了任何计算）。
   - 若最终答案无法逐字嵌入验证命题（纯文字、解集集合、选项字母等），
     按第 5 条输出 error。
5. 若最终答案无法合理形式化（纯文字答案、答案依赖未给出的量、选项字母等），
   输出 JSON：{"error": "无法形式化原因"}，不要硬编。
6. 只输出 JSON，不要输出解释或 Markdown 代码块。

============================================================
输出格式（严格 JSON）
============================================================
```json
{
  "lean_code": "example : (3 : ℚ) = 1 + 2 := by\\n  norm_num",
  "answer_expr": "3",
  "note": "可选说明"
}
```
"""

LEAN_ANSWER_VERIFY_USER = """## 原题
{problem}

## 解答推理（含计算过程）
{reasoning}

## 解答给出的最终答案
{answer}

{answer_hint}请把最终答案与推理中的关键计算转化为轻量 Lean 验证代码（严格按系统提示输出 JSON）。
⚠ 硬性要求：上面「解答给出的最终答案」的原值必须逐字出现在你生成的验证命题结论侧
（example : <关键计算> = <最终答案>）。若你的验证代码没有包含该答案原值，
说明没有验证答案，属于无效输出——请直接输出 error。"""

# 分析阶段：把编译错误映射为可修复/致命缺陷
LEAN_ANALYZE_SYSTEM = """你是一位 Lean 4 与数学推理专家。下面是"自然语言推理"转化出的 Lean 4 代码及其编译错误，请判断错误的根因。

输出 JSON：
{{
  "error_category": "translation_error" | "logic_error" | "both" | "uncertain",
  "repairable": "yes" | "no" | "partial",
  "suggestion": "给修正建议，尽量具体",
  "critical_desc": "若是致命逻辑错误，说明错在哪一步、为什么错；否则留空"
}}

分类说明：
- translation_error：Lean 代码本身的语法/类型问题，或是对推理的形式化表述不当（可通过修改代码修复）；
- logic_error：推理本身的数学逻辑有致命缺陷，即使换一种形式化也无法成立；
- both：两者都有；uncertain：无法判断。"""

LEAN_ANALYZE_USER = """## 原题
{problem}

## 自然语言推理
{reasoning}

## Lean 4 代码
{lean_code}

## 编译错误
{compile_error}

请按 JSON 输出错误根因分析。"""


# =====================================================================
# Lean 环境检测 / 纯编译工具函数（可独立复用，不依赖 LLM 栈）
# =====================================================================

# 进程级一次性自举：Lean 缺失时尝试运行 deploy/setup_lean.sh（仅一次）
_LEAN_SETUP_TRIED = False


def _maybe_auto_setup_lean(lean_executable: str) -> None:
    """Lean 可执行缺失时，尽力运行 deploy/setup_lean.sh 自举环境（幂等）。

    - 仅在 exe 找不到且本进程未尝试过时执行一次（模块级 _LEAN_SETUP_TRIED）；
    - 纯 best-effort：任何失败都吞掉，返回后调用方照旧降级 unknown，绝不影响主流程；
    - 离线安装（--offline）优先，避免评测容器无外网时长时间等待在线安装。
    """
    global _LEAN_SETUP_TRIED
    if _LEAN_SETUP_TRIED or shutil.which(lean_executable):
        return
    _LEAN_SETUP_TRIED = True
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    script = os.path.join(root, "deploy", "setup_lean.sh")
    if not os.path.exists(script):
        return
    try:
        # 评测容器多为 Linux；Windows 本地无 bash 时静默跳过
        subprocess.run(
            ["bash", script, "--offline"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(_LEAN_DETECT_TIMEOUT * 3, 30),
        )
    except Exception:  # noqa: BLE001
        pass


def detect_lean_environment(
    lean_executable: str = _DEFAULT_LEAN_EXECUTABLE,
) -> dict:
    """检测 Lean 4 环境是否可用，返回 {"available": bool, "version": str, "error": str}。

    检测前会尝试一次 lean 自举（见 _maybe_auto_setup_lean），
    使评测环境无需手工预装 Lean 即可自动接入。
    """
    exe = lean_executable or _DEFAULT_LEAN_EXECUTABLE
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_LEAN_DETECT_TIMEOUT,
        )
        if result.returncode == 0:
            version = (result.stdout.strip().split("\n")[0]
                       if result.stdout else "unknown")
            return {"available": True, "version": version, "error": ""}
        return {"available": False, "version": "",
                "error": (result.stderr or result.stdout).strip()[:200]}
    except FileNotFoundError:
        # 尝试自举一次，再重新检测
        _maybe_auto_setup_lean(exe)
        try:
            result = subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_LEAN_DETECT_TIMEOUT,
            )
            if result.returncode == 0:
                version = (result.stdout.strip().split("\n")[0]
                           if result.stdout else "unknown")
                return {"available": True, "version": version, "error": ""}
        except Exception:  # noqa: BLE001
            pass
        return {"available": False, "version": "",
                "error": f"Lean executable not found: {exe}"}
    except subprocess.TimeoutExpired:
        return {"available": False, "version": "",
                "error": f"Lean detection timed out ({_LEAN_DETECT_TIMEOUT}s)"}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "version": "", "error": str(exc)[:200]}






# =====================================================================
# 验证后端开关（2026-09-04 档2：bridge | mcp）
# ---------------------------------------------------------------------
# mcp    = lean-lsp-mcp（LSP 增量诊断 + 行级/目标定位）—— **模块默认**（_LEAN_BACKEND）
# bridge = lake env lean 全量编译（兜底；mcp 不可用 / 门控未过时自动回落）
# 开关优先级：环境变量 LEAN_BACKEND > set_lean_backend() 模块态 > 模块默认 "mcp"。
# ⚠ 门控（2026-09-12 记录）：mcp 仅在 work_dir 为 **lake 工程**时才会被调用
#   （`_is_lake_workdir()`）；closure 闭包 + LEAN_PATH 部署形态下**只会走 bridge**，
#   日志表现为「★ mcp 未生效」（2026-09-12 起显式告警，此前完全静默）。
# 与 lean-lsp-mcp 的通信走子进程代理（agent/lean_mcp_proxy.py，由独立 venv
# python 执行），主进程零 MCP 依赖；mcp 不可用/异常一律回落 bridge。
# =====================================================================
_LEAN_BACKEND = "mcp"
_LEAN_BACKEND_ENV = "LEAN_BACKEND"
_MCP_PROXY_LOCK = threading.Lock()
_MCP_PROXY: Optional["_LeanMcpProxyClient"] = None
# =====================================================================
# MCP **实例池**（2026-09-13）：并行通道，LEAN_MCP_WORKERS>1 时启用
# ---------------------------------------------------------------------
# 事实澄清（勿再重复推断）：串行的**不是 lean-lsp-mcp**，是我们自己的代理层。
# lean_lsp_mcp/client_utils.py 自身就支持并发：
#   · `_project_runtimes`：按工程根缓存 client（一个 MCP server 可同时持有多个工程）
#   · `_MAX_SHARED_CLIENTS = 8`；`CLIENT_LOCK` 是 asyncio.Lock（仅护 client 创建）
#   · `LEAN_MCP_SCRATCH_SLOTS`（默认 1）、`LEAN_LSP_MAX_OPEN_FILES`（默认 4）
#   · `LEAN_MCP_PREWARM_FILES`：启动即预热，把冷启动藏进 agent 的规划阶段
#   · `LEAN_BUILD_CONCURRENCY`：allow / cancel / share
# 串行来自本文件的 `_MCP_PROXY()` 单例 + `_MCP_PROXY_LOCK` 全局锁：一次调用
# 全程独占，多 worker 也退化成排队。
#
# 本池做法：K 个独立 proxy 进程 ⇒ K 个独立 lean-lsp-mcp ⇒ K 个独立 Lean LSP
# server ⇒ 真正的并行。每个实例同一时刻只服务一个请求（沿用一问一答协议）。
# ⚠ K 的上限由**内存**决定，不是 CPU：每个 Lean server 都把 Mathlib 载进内存
#   （实测本机 32 核 / 15.2 GiB ⇒ K 实际只能取 2~4；容器内通常更紧）。
#   ⇒ 想加大并发必须先量一个 Lean server 的 RSS，而不是看核数。
# 开关 LEAN_MCP_WORKERS 默认 1 = 旧的单例+全局锁路径（行为逐字不变，便于 A/B）。
# =====================================================================
# 池按 **work_dir 分桶**：实例创建时就把 work_dir 绑成了 lean-lsp-mcp 的
# LEAN_PROJECT_PATH，跨工程复用会让诊断落在错误的工程根
# （`get_relative_file_path` 解析不到 → 报错或张冠李戴）。
# 因此实例只在**同一工程内**复用；全进程实例总数受 K 约束（内存上界）。
_MCP_POOLS: dict = {}                         # work_dir -> queue.Queue（空闲实例）
_MCP_POOL_MADE: dict = {}                     # work_dir -> 已建实例数（含在用）
_MCP_POOL_TOTAL = 0                           # 全进程实例总数（≤ K）
_MCP_POOL_LOCK = threading.Lock()
# 并行通道下 LeanBridge 会被多线程调用：Lean/MCP 编译可并行，但 LLM 调用必须
# 串行（限流口径按单线程标定；client 非线程安全契约）。K=1 时不加锁。
_LLM_SERIAL_LOCK = threading.Lock()
# os.environ["LEAN_PATH"] 的自增注入是"读-改-写"，并行下必须加锁（防丢更新）
_LEAN_PATH_LOCK = threading.Lock()
# 2026-09-12：mcp 门控未通过的告警去重（每个 work_dir 只报一次，防逐候选刷屏）
_MCP_GATE_WARNED = set()

# 判分语义（档1，2026-09-04）：证明必须完全可核——以下源码构造视为不可信。
# 与 lean_verify 的 sorryAx/axioms 检查对齐（bare lake 对 sorry 只打 warning）。
_UNTRUSTED_SRC_PATTERNS = (
    r"\bsorry\b",          # 占位未证明步骤
    r"\baxiom\b",          # 裸公理声明（任意未证命题）
    r"\bunsafe\b",         # 绕过 kernel 检查
    r"implemented_by",     # 外部实现声明
    r"skipKernelTC",       # debug.skipKernelTC 等内核跳过
)
_UNTRUSTED_MSG = ("编译通过但含不可信构造（sorry/axiom/unsafe/"
                  "implemented_by 等），验证不可完全核")


# 2026-09-04：沙箱 safe-delete 钩子（turn 累计 >50 次删除）会硬杀 os.remove/os.unlink
# （非异常，except BaseException 也拦不住），长跑评测因此被反复打断。
# 实测 os.rename/os.replace 不触发钩子 → 临时 .lean 改用「移入工程 _lean_trash/」替代删除，
# 同盘原子移动、垃圾集中、事后可整体清。
def _trash_lean_file(project_dir: str, lean_file: str) -> None:
    """把临时 Lean 文件收进 project_dir/_lean_trash/（代替 os.remove，防沙箱硬杀）。"""
    try:
        trash = os.path.join(project_dir, "_lean_trash")
        os.makedirs(trash, exist_ok=True)
        os.replace(os.path.join(project_dir, lean_file),
                   os.path.join(trash, lean_file))
    except BaseException:
        # 移动失败（源已不在等）→ 静默：残留无害
        pass


def set_lean_backend(name: str) -> None:
    """设置验证后端（"bridge" | "mcp"）；非法值忽略，保持现状。"""
    global _LEAN_BACKEND
    if name in ("bridge", "mcp"):
        _LEAN_BACKEND = name


def get_lean_backend() -> str:
    """当前生效后端：环境变量 LEAN_BACKEND 优先，其次模块态。"""
    env = (os.environ.get(_LEAN_BACKEND_ENV, "") or "").strip().lower()
    if env in ("bridge", "mcp"):
        return env
    return _LEAN_BACKEND


def _scan_untrusted(code: str) -> bool:
    """源码含不可信构造（sorry/axiom/unsafe/implemented_by/skipKernelTC）。"""
    return any(re.search(p, code or "") for p in _UNTRUSTED_SRC_PATTERNS)


def _has_sorry_warning(text: str) -> bool:
    """编译输出含 `declaration uses 'sorry'` 警告（真实使用 sorry 的声明）。"""
    return re.search(r"uses `sorry`", text or "") is not None


def _is_lake_workdir(work_dir: str) -> bool:
    """work_dir 是否为 lake 工程根（MCP/LSP 需要工程环境解析 import）。"""
    return any(os.path.isfile(os.path.join(work_dir, f))
               for f in ("lakefile.toml", "lakefile.lean", "lake-manifest.json"))


# 最小 lake 工程标记（内容刻意极简：只为让 lean-lsp-mcp 认这是工程根）
_MIN_LAKEFILE_TOML = 'name = "mathlib"\ndefaultTargets = []\n'
_MIN_MANIFEST_JSON = (
    '{"version": "1.1.0", "packagesDir": ".lake/packages", '
    '"packages": [], "name": "mathlib", "lakeDir": ".lake"}\n')
# lean-lsp-mcp 的 require_lean_project_path 还强制要求 `lean-toolchain` 文件，
# 缺失即 ValueError 启动失败（2026-09-12 实测抓到，见 _min_toolchain_content）
_FALLBACK_TOOLCHAIN = "leanprover/lean4:v4.31.0"


def _min_toolchain_content() -> str:
    """`lean-toolchain` 内容：env > 仓根同名文件 > 项目锁定版本兜底。"""
    env = (os.environ.get("LEAN_TOOLCHAIN", "") or "").strip()
    if env:
        return env + "\n"
    try:
        p = os.path.join(_project_root(), "lean-toolchain")
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                t = f.read().strip()
            if t:
                return t + "\n"
    except Exception:  # noqa: BLE001
        pass
    return _FALLBACK_TOOLCHAIN + "\n"


def _is_mcp_project_root(root: str) -> bool:
    """lean-lsp-mcp `require_lean_project_path()` 的等价要求。

    实测（2026-09-12）该库硬性要求：`lean-toolchain` **且**
    （`lakefile.lean` 或 `lakefile.toml`）；缺任一项即启动 ValueError。
    比 `_is_lake_workdir`（三选一）严格 —— 门控必须按这个口径判。
    """
    if not root or not os.path.isdir(root):
        return False
    if not os.path.isfile(os.path.join(root, "lean-toolchain")):
        return False
    return any(os.path.isfile(os.path.join(root, f))
               for f in ("lakefile.toml", "lakefile.lean"))


def _ensure_min_lake_project(root: str) -> bool:
    """Mathlib **闭包**目录缺 lake 工程标记时，补最小工程文件（幂等）。

    背景（2026-09-12，用户要求 mcp 必须可用）：
      平台部署形态是「Mathlib 闭包 + LEAN_PATH」，全仓**没有** lakefile；
      而 `verify()` 在 project_dir 非空时把 **work_dir 设为 project_dir 本身**
      （见 `_compile(code, project_dir, ...)`），于是 mcp 门控恒为 False →
      **lean-lsp-mcp 在平台永不被调用**，连带丢失它的三项高价值错误反馈能力：
      错误行 goal state / multi_attempt 可用策略 / hover 查证 API。

    这里只补**工程标记**（lean-toolchain + lakefile.toml + manifest），不搬动
    任何 olean：Lean 编译仍走 lean.exe + LEAN_PATH 原路径
    （`_compile_lean` 的 is_lake 判定只看可执行文件名），行为不变。

    返回 True 表示该目录现在满足 lean-lsp-mcp 的工程根要求。
    """
    try:
        if not root or not os.path.isdir(root):
            return False
        # 只对「含 Mathlib olean 的闭包目录」动手，避免在任意目录乱写文件
        ml = os.path.join(root, "Mathlib")
        if not os.path.isdir(ml):
            return False
        has_olean = False
        try:
            for i, fn in enumerate(os.listdir(ml)):
                if i > 400:
                    break
                if fn.endswith(".olean"):
                    has_olean = True
                    break
        except OSError:
            return False
        if not has_olean:
            return False
        wrote = []
        for fn, content in (("lakefile.toml", _MIN_LAKEFILE_TOML),
                            ("lake-manifest.json", _MIN_MANIFEST_JSON),
                            ("lean-toolchain", _min_toolchain_content())):
            p = os.path.join(root, fn)
            if not os.path.isfile(p):
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
                wrote.append(fn)
        if wrote:
            logger.info("[LeanBridge] ★ 已为 Mathlib 闭包补最小 lake 工程标记 %s：%s"
                        "（mcp 需要工程根；可用 LEAN_MCP_AUTOLAKE=0 关闭）",
                        root, ", ".join(wrote))
        return _is_mcp_project_root(root)
    except Exception as exc:  # noqa: BLE001  只读挂载/权限不足 → 静默失败
        logger.warning("[LeanBridge] 补 lake 工程标记失败（忽略）: %s", exc)
        return False


def _mcp_gate_ok(work_dir: str) -> bool:
    """mcp 后端门控：work_dir 必须满足 lean-lsp-mcp 的工程根要求。

    2026-09-12 升级：单纯 `_is_lake_workdir` 会让「闭包 + LEAN_PATH」部署形态
    永久不可用（平台实测即如此）。现按 `LEAN_MCP_AUTOLAKE`（**默认 1**，因用户
    明确要求 mcp 必须可用）在闭包目录上补最小工程文件后再判定。
    设 `LEAN_MCP_AUTOLAKE=0` 可恢复旧的严格门控（仅现成 lake 工程才走 mcp）。
    """
    if _is_mcp_project_root(work_dir):
        return True
    if not _sw_bool("lean_mcp_autolake"):
        return False
    return _ensure_min_lake_project(work_dir)


def _detect_mcp_proxy_python() -> str:
    """探测装有 lean-lsp-mcp 的 venv python（代理执行器）。

    优先级：环境变量 LEAN_MCP_PYTHON > ~/leanlsp-venv（win/unix）。
    返回空串表示本地无 mcp 环境（mcp 后端自动回落 bridge）。
    """
    env = (os.environ.get("LEAN_MCP_PYTHON", "") or "").strip()
    if env and os.path.isfile(env):
        return env
    home = os.path.expanduser("~")
    # ① 用户主目录惯例路径（本机开发用）
    for c in (os.path.join(home, "leanlsp-venv", "Scripts", "python.exe"),
              os.path.join(home, "leanlsp-venv", "bin", "python")):
        if os.path.isfile(c):
            return c
    # ② 仓内 venv —— 平台离线安装脚本 scripts/install_mcp_linux.sh 的产出位置
    #    （2026-09-11 补：脚本装到 <repo>/lean-lsp-mcp/venv-linux，而代码原先只找 ~/，
    #     导致平台侧"装了却探测不到" → 静默回落 bridge。此处补齐，避免该错位。）
    try:
        _here = os.path.dirname(os.path.abspath(__file__))      # .../tools/lean_local
        _repo = os.path.dirname(os.path.dirname(_here))          # 仓库根
        for c in (os.path.join(_repo, "lean-lsp-mcp", "venv-linux", "bin", "python"),
                  os.path.join(_repo, "lean-lsp-mcp", "venv", "bin", "python"),
                  os.path.join(_repo, "lean-lsp-mcp", "venv", "Scripts", "python.exe"),
                  os.path.join(_repo, "lean-lsp-mcp", "venv-linux", "Scripts", "python.exe")):
            if os.path.isfile(c):
                return c
    except Exception:  # noqa: BLE001
        pass
    return ""


def _mcp_proxy_script() -> str:
    """agent/lean_mcp_proxy.py 绝对路径（代理脚本随主仓库走）。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "lean_mcp_proxy.py")
    return p if os.path.isfile(p) else ""


def mcp_available() -> bool:
    """MCP 通道是否真可用（venv python + 代理脚本都在）。

    用途：**并行只在 MCP 可用时启用**。理由：MCP 走 LSP 常驻诊断（单次 60s 量级、
    实例间彼此独立 ⇒ 并行收益明确）；而 bridge 是 `lake env lean` 全量编译，
    并行收益未验证，且同工程目录并发跑 lake 有额外风险。
    MCP 不可用时（如比赛平台无 Lean 环境）一切照旧走串行 bridge —— 零行为变化。
    """
    try:
        return bool(_detect_mcp_proxy_python() and _mcp_proxy_script())
    except Exception:  # noqa: BLE001
        return False


class _LeanMcpProxyClient:
    """spawn venv python 跑 lean_mcp_proxy.py，一行 JSON 一问一答。

    - 单实例常驻（lean-lsp-mcp server / lean server 跨请求复用 → 增量秒回）；
    - request 带 wall-clock 读超时；进程退出/无响应抛 RuntimeError（上层回落）；
    - close() 终止子进程。
    """

    def __init__(self, python: str, script: str, project_dir: str):
        env = dict(os.environ)
        env["LEAN_PROJECT_PATH"] = project_dir
        env.setdefault("LEAN_LOG_LEVEL", "NONE")
        # 2026-09-13 修复（诊断能力）：stderr 由 DEVNULL 改为 PIPE + 后台收割。
        # 原因：`lean-lsp-mcp` 启动失败时（典型场景：LEAN_PROJECT_PATH 指向的
        # 目录不是合法 Lean 工程 → app_lifespan 里 require_lean_project_path
        # 抛异常），**子进程是活着的但永不响应任何请求**；原实现把 stderr 丢弃，
        # 且统一报"proxy 无响应（可能崩溃）"，把排查方向带偏（实测误导过一次
        # 完整诊断）。注意必须**持续读取**——PIPE 写满会阻塞子进程。
        try:
            self._proc = subprocess.Popen(
                [python, script],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", env=env, bufsize=1)
        except OSError as exc:
            raise RuntimeError(f"proxy 启动失败: {exc}") from exc
        self._seq = 0
        self._stderr_tail = ""
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stderr(self) -> None:
        """后台收割 stderr，仅保留尾部（供启动失败时给出真实原因）。"""
        try:
            proc = self._proc
            if proc is None or proc.stderr is None:
                return
            for line in iter(proc.stderr.readline, ""):
                if not line:
                    break
                self._stderr_tail = (self._stderr_tail + line)[-4000:]
        except Exception:  # noqa: BLE001
            pass

    def _stderr_hint(self, limit: int = 3) -> str:
        """把 stderr 尾部压成一行附到异常信息里（无内容则返回空串）。"""
        raw = (self._stderr_tail or "").strip()
        if not raw:
            return ""
        lines = [x.strip(" |+") for x in raw.splitlines() if x.strip()]
        return "；stderr 尾部: " + " / ".join(lines[-limit:])[:400]

    def request(self, file_path: str, timeout: float = 150.0,
                goal_line=None, goal_column=None) -> dict:
        """发一次诊断请求（可选带目标行定位），阻塞等响应。"""
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("proxy 进程已退出")
        self._seq += 1
        req = {"id": self._seq, "file": file_path,
               "goal_line": goal_line, "goal_column": goal_column}
        try:
            self._proc.stdin.write(
                json.dumps(req, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"proxy 写入失败: {exc}") from exc
        try:
            # readline 无超时参数 → 用 selectors/线程包装。简单可靠：
            # 以读线程 + join(timeout) 实现 wall-clock 超时。
            import queue
            q: "queue.Queue[str]" = queue.Queue()

            def _reader() -> None:
                try:
                    ln = self._proc.stdout.readline()
                    q.put(ln)
                except Exception:  # noqa: BLE001  pyflakes: exc 未使用，去掉绑定
                    q.put("")

            t = threading.Thread(target=_reader, daemon=True)
            t.start()
            t.join(timeout)
            if t.is_alive():
                raise RuntimeError(f"proxy 响应超时（>{timeout:.0f}s）")
            resp_line = q.get_nowait() if not q.empty() else ""
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"proxy 读响应失败: {exc}") from exc
        if not resp_line:
            # 2026-09-13：区分两种**完全不同**的故障，避免误判（见 __init__ 注释）。
            #   · 进程已退出            → 真崩溃 / 被外部杀掉
            #   · 进程存活但无输出      → MCP 服务启动失败（真实原因在 stderr）
            _rc = self._proc.poll()
            _hint = self._stderr_hint()
            if _rc is not None:
                raise RuntimeError(f"proxy 进程已退出（退出码={_rc}）{_hint}")
            raise RuntimeError(
                "proxy 无输出：进程存活但 MCP 服务未就绪"
                "（常见原因：LEAN_PROJECT_PATH 指向的不是合法 Lean 工程）"
                + _hint)
        try:
            resp = json.loads(resp_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"proxy 响应非 JSON: {resp_line[:120]}") from exc
        return resp

    def call(self, payload: dict, timeout: float = 150.0) -> dict:
        """通用代理请求（2026-09-11）：下发任意 op（run_code/local_search/verify）。

        payload 除 ``id`` 外原样下发；返回代理的 JSON 响应。
        超时/进程退出语义与 request() 一致（抛 RuntimeError，上层回落）。
        """
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("proxy 进程已退出")
        self._seq += 1
        req = {"id": self._seq}
        req.update(payload)
        try:
            self._proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"proxy 写入失败: {exc}") from exc
        import queue
        q: "queue.Queue[str]" = queue.Queue()

        def _reader() -> None:
            try:
                q.put(self._proc.stdout.readline())
            except Exception:  # noqa: BLE001
                q.put("")

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise RuntimeError(f"proxy 响应超时（>{timeout:.0f}s）")
        resp_line = q.get_nowait() if not q.empty() else ""
        if not resp_line:
            # 2026-09-13：区分两种**完全不同**的故障，避免误判（见 __init__ 注释）。
            #   · 进程已退出            → 真崩溃 / 被外部杀掉
            #   · 进程存活但无输出      → MCP 服务启动失败（真实原因在 stderr）
            _rc = self._proc.poll()
            _hint = self._stderr_hint()
            if _rc is not None:
                raise RuntimeError(f"proxy 进程已退出（退出码={_rc}）{_hint}")
            raise RuntimeError(
                "proxy 无输出：进程存活但 MCP 服务未就绪"
                "（常见原因：LEAN_PROJECT_PATH 指向的不是合法 Lean 工程）"
                + _hint)
        try:
            return json.loads(resp_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"proxy 响应非 JSON: {resp_line[:120]}") from exc

    def run_code(self, code: str, timeout: float = 120.0) -> dict:
        """本地执行 Lean 代码片段（计算；不联网）。"""
        return self.call({"op": "run_code", "code": code}, timeout=timeout)

    def local_search(self, query: str, limit: int = 10,
                     timeout: float = 60.0) -> dict:
        """本地 Mathlib 声明检索（找引理；不联网）。"""
        return self.call({"op": "local_search", "query": query,
                          "limit": limit}, timeout=timeout)

    def verify_theorem(self, file_path: str, theorem_name: str,
                       timeout: float = 120.0) -> dict:
        """定理公理/可疑构造检查（检测；不联网）。"""
        return self.call({"op": "verify", "file": file_path,
                          "theorem": theorem_name}, timeout=timeout)

    def multi_attempt(self, file_path: str, line: int, snippets: list,
                      column: int = 0, timeout: float = 120.0) -> dict:
        """在指定行尝试多个 tactic（B4 修复建议；不联网）。"""
        payload = {"op": "multi_attempt", "file": file_path,
                   "line": int(line), "snippets": list(snippets)}
        if column:
            payload["column"] = int(column)
        return self.call(payload, timeout=timeout)

    def hover(self, file_path: str, line: int, column: int,
              timeout: float = 60.0) -> dict:
        """取某位置符号的类型签名/文档（B6 API 校验；不联网）。"""
        return self.call({"op": "hover", "file": file_path,
                          "line": int(line), "column": int(column)},
                         timeout=timeout)

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None


def _total_ram_gb() -> float:
    """物理内存总量（GiB）。取不到 → 按 8.0 保守估（宁小勿大）。"""
    try:
        if os.name == "nt":
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            m = _MS()
            m.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return float(m.ullTotalPhys) / float(1 << 30)
        else:
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return float(line.split()[1]) / (1024.0 * 1024.0)
    except Exception:  # noqa: BLE001
        pass
    return 8.0


def _avail_ram_gb() -> float:
    """当前**可用**物理内存（GiB）。取不到 → 返回一个大值（不做无谓拦截）。"""
    try:
        if os.name == "nt":
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            m = _MS()
            m.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return float(m.ullAvailPhys) / float(1 << 30)
        else:
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return float(line.split()[1]) / (1024.0 * 1024.0)
    except Exception:  # noqa: BLE001
        pass
    return 1e6


# 再建一个 Lean server 的内存门槛（GiB）。低于它就不再扩池，宁可回落 bridge ——
# 单个 Lean+Mathlib 常驻 1.5–4 GB，深夜/繁忙机器上硬开会把整台机器拖垮（OOM = 全盘失败）。
# ★ 2026-09-16 用户要求「统一改为可用内存」。原值 1.5 偏低：1.5 GiB 空闲就放行新建，
#   而单实例实测可占 750 MB ~ 4 GB ⇒ 放行了照样可能 OOM。提到 2.5 GiB。
_MIN_FREE_GIB_FOR_NEW = 2.5
_NO_ROOM_WARNED = False


def _mcp_room_for_new_instance() -> bool:
    """是否还有余量再起一个 Lean server（防 OOM 护栏）。"""
    global _NO_ROOM_WARNED
    ok = _avail_ram_gb() >= _MIN_FREE_GIB_FOR_NEW
    if not ok and not _NO_ROOM_WARNED:
        _NO_ROOM_WARNED = True
        logger.warning(
            "[LeanBridge] 可用内存不足 %.1f GiB → 不再扩充 MCP 实例（回落 bridge）",
             _MIN_FREE_GIB_FOR_NEW)
    return ok


def _auto_workers() -> int:
    """自动并行度：**由可用内存定，其次核数**（每个 Lean server 都把 Mathlib 载进内存）。

    K = clamp(1, min(8, 可用内存GiB//4, max(1, 核数//4)))
    - 硬上限 8：与 lean-lsp-mcp 自身的 `_MAX_SHARED_CLIENTS = 8` 对齐；
    - ``//4``：单个 Lean+Mathlib 常驻约 1.5–4 GB，按 4 GB 留量最保守；
      核数按 4 核/实例（Lean 载入 Mathlib 是多线程的）。

    ★★ 2026-09-16 用户要求「统一改为可用内存」。**此前用 `_total_ram_gb()`（总内存）
    定容，而运行期护栏 `_mcp_room_for_new_instance()` 用可用内存 —— 两个口径打架**：
    本机总 15.2 GiB ⇒ K 恒算成 3，但用户侧常驻 B站 1.5 GB + QQ 0.86 GB +
    WorkBuddy 2.1 GB ⇒ 实际可用常低到 1–3 GB，**K 却仍按 15.2 GB 在算**，
    护栏又只会"不再扩"、**不会把 K 调小** ⇒ 结构性超配、触发 OOM 护栏后回落 bridge。

    例：可用 3.4 GiB / 32 核 ⇒ min(8, 0, 8) → clamp 后 = **1**（保守但不会 OOM）。
    取不到可用内存（哨兵值）时**退回总内存口径**，避免误判成"内存无限"。
    """
    try:
        cores = os.cpu_count() or 2
    except Exception:  # noqa: BLE001
        cores = 2
    avail = _avail_ram_gb()
    if avail >= 1e5:            # `_avail_ram_gb` 取不到时返回 1e6 哨兵
        avail = _total_ram_gb()  # → 退回总量口径（宁可保守，不可误放行）
    by_ram = int(avail // 4)
    by_cpu = max(1, int(cores) // 4)
    return max(1, min(8, by_ram, by_cpu))


_WORKERS_LOGGED = False


def lean_parallelism() -> int:
    """MCP/Lean 并行度（``LEAN_MCP_WORKERS``）。

    - 未设置 / ``auto`` / ``0`` → 按内存与核数自动推算（见 ``_auto_workers``）；
    - 显式正整数 → 用该值（``1`` = 旧的单例 + 全局锁，逐字不变）；
    - 非法值 → 自动。
    """
    global _WORKERS_LOGGED
    raw = (os.environ.get("LEAN_MCP_WORKERS", "") or "").strip().lower()
    if raw in ("", "auto", "0"):
        k = _auto_workers()
        auto = True
    else:
        try:
            k = max(1, int(raw))
            auto = False
        except (TypeError, ValueError):
            k = _auto_workers()
            auto = True
    if not _WORKERS_LOGGED:
        _WORKERS_LOGGED = True
        logger.info(
            "[LeanBridge] MCP 并行度 K=%d（%s；内存 %.1f GiB / %s 核）—— "
            "1 = 单例串行，>1 = 实例池并行",
            k, "auto" if auto else "显式", _total_ram_gb(), os.cpu_count())
    return k


def _mcp_workers() -> int:
    """内部别名（保持旧调用点可读）。"""
    return lean_parallelism()



# =====================================================================
# 并发安全的临时 .lean 文件（MCP 诊断用）
# ---------------------------------------------------------------------
# 调用方用 `%d_%d % (pid, int(monotonic()*1e6))` 或 `%ms` 生成文件名：并发提交时
# 存在**极小概率**撞名（同微秒/同毫秒），一旦撞名两个线程会互相覆盖内容 →
# LSP 诊断张冠李戴（把 A 的错误算到 B 头上）。这里只在本进程内登记"正在使用"，
# 撞名就把内容复制成唯一副本，用完移入 `_lean_trash/`；不改变调用方的写入/清理契约。
# =====================================================================
_MCP_FILE_INUSE: set = set()
_MCP_FILE_LOCK = threading.Lock()


def _mcp_unique_file(lean_file: str) -> tuple:
    """取一个独占的 .lean 路径；返回 ``(路径, 是否副本)``。"""
    key = os.path.normcase(os.path.abspath(lean_file))
    with _MCP_FILE_LOCK:
        if key not in _MCP_FILE_INUSE:
            _MCP_FILE_INUSE.add(key)
            return lean_file, False
    stem, ext = os.path.splitext(lean_file)
    for i in range(1, 10000):
        cand = "%s__w%d%s" % (stem, i, ext)
        ckey = os.path.normcase(os.path.abspath(cand))
        with _MCP_FILE_LOCK:
            if ckey in _MCP_FILE_INUSE:
                continue
            _MCP_FILE_INUSE.add(ckey)
        try:
            shutil.copyfile(lean_file, cand)
        except Exception:  # noqa: BLE001  复制失败 → 退回原名（旧行为）
            with _MCP_FILE_LOCK:
                _MCP_FILE_INUSE.discard(ckey)
            return lean_file, False
        return cand, True
    return lean_file, False


def _mcp_release_file(lean_file: str, is_copy: bool, work_dir: str = "") -> None:
    """释放登记；副本移入 ``_lean_trash/``（不用 os.remove，避开沙箱硬杀钩子）。"""
    with _MCP_FILE_LOCK:
        _MCP_FILE_INUSE.discard(os.path.normcase(os.path.abspath(lean_file)))
    if is_copy and work_dir:
        _trash_lean_file(work_dir, os.path.basename(lean_file))




def _mcp_client_alive(client) -> bool:
    """实例健康判定：进程存在且未退出（已 close() 视为不可用）。"""
    try:
        proc = getattr(client, "_proc", None)
        return proc is not None and proc.poll() is None
    except Exception:  # noqa: BLE001
        return False


# 异常/超时后"必须丢弃"的实例（按 id 登记，避免给对象加属性）。
# 为什么不能只看进程存活：读超时后进程往往还活着，但那次的**响应会迟到**，
# 一旦归还池里被下一个请求读到就会"张冠李戴"（一问一答协议错位）。
_MCP_DROP: set = set()
_MCP_DROP_LOCK = threading.Lock()


def _mcp_mark_drop(client) -> None:
    """标记实例不可复用：下次归还时关闭并释放名额（调用方不再自行 close）。"""
    if client is None:
        return
    with _MCP_DROP_LOCK:
        _MCP_DROP.add(id(client))


def _mcp_take_drop_flag(client) -> bool:
    """取出并清除"需丢弃"标记。"""
    key = id(client)
    with _MCP_DROP_LOCK:
        if key in _MCP_DROP:
            _MCP_DROP.discard(key)
            return True
    return False


# MCP 计时统计（累计）。用途：让"单次 61s / 占总时长 54%"这类结论**可取证** ——
# 此前全仓没有任何 MCP 计时埋点，所有耗时都是用日志时间戳反推的。
_MCP_STATS = {"calls": 0, "ok": 0, "fail": 0, "seconds": 0.0}
_MCP_STATS_LOCK = threading.Lock()


def mcp_stats() -> dict:
    """累计 MCP 诊断调用统计（calls / ok / fail / seconds）。"""
    with _MCP_STATS_LOCK:
        return dict(_MCP_STATS)


def _mcp_note(seconds: float, ok: bool) -> None:
    with _MCP_STATS_LOCK:
        _MCP_STATS["calls"] += 1
        _MCP_STATS["seconds"] += float(seconds)
        _MCP_STATS["ok" if ok else "fail"] += 1


def _wd_key(work_dir: str) -> str:
    """池分桶键：同一工程目录的不同写法必须落到同一桶。"""
    try:
        return os.path.normcase(os.path.abspath(work_dir))
    except Exception:  # noqa: BLE001
        return str(work_dir)


def _pool_drop(wd_key: str) -> None:
    """实例不可用 → 释放名额（下次可重建）并回收空桶。"""
    global _MCP_POOL_TOTAL
    with _MCP_POOL_LOCK:
        _MCP_POOL_TOTAL = max(0, _MCP_POOL_TOTAL - 1)
        n = max(0, _MCP_POOL_MADE.get(wd_key, 0) - 1)
        if n:
            _MCP_POOL_MADE[wd_key] = n
        else:
            _MCP_POOL_MADE.pop(wd_key, None)


@contextlib.contextmanager
def _mcp_acquire(work_dir: str, wait: float = 240.0):
    """借出一个 MCP 代理实例；yield None 表示 mcp 不可用（调用方回落 bridge）。

    - ``LEAN_MCP_WORKERS<=1``：旧路径 —— 单例 + 全局锁（锁跨整个调用持有，行为不变）。
    - ``>1``：实例池 —— **按 work_dir 分桶**，池满则阻塞等待 ``wait`` 秒，
      仍取不到则 yield None（宁可回落 bridge，也不把主链无限期挂住）。
    - 归还时做健康判定：进程已退出 / 已被 close() 的实例**丢弃不归还** ——
      避免"某次读超时、响应迟到"污染下一个请求（一问一答协议错位）。
    """
    global _MCP_PROXY, _MCP_POOL_TOTAL
    py = _detect_mcp_proxy_python()
    sc = _mcp_proxy_script()
    if not (py and sc and work_dir):
        yield None
        return
    if _mcp_workers() <= 1:
        # ---- 旧路径：单例 + 全局锁（逐字保留原语义）----
        _MCP_PROXY_LOCK.acquire()
        try:
            if _MCP_PROXY is None:
                try:
                    _MCP_PROXY = _LeanMcpProxyClient(py, sc, work_dir)
                except Exception:  # noqa: BLE001
                    _MCP_PROXY = None
            yield _MCP_PROXY
        finally:
            if _mcp_take_drop_flag(_MCP_PROXY):
                try:
                    _MCP_PROXY.close()
                except Exception:  # noqa: BLE001
                    pass
                _MCP_PROXY = None          # 出错实例 → 关闭并下次重建
            elif not _mcp_client_alive(_MCP_PROXY):
                _MCP_PROXY = None          # 进程已死 → 下次重建
            _MCP_PROXY_LOCK.release()
        return
    # ---- 池路径：K 个独立实例，可真正并行（严格按 work_dir 分桶）----
    _wd = _wd_key(work_dir)
    with _MCP_POOL_LOCK:
        q = _MCP_POOLS.get(_wd)
        if q is None:
            q = _MCP_POOLS[_wd] = queue.Queue()
    client = None
    try:
        client = q.get_nowait()
    except queue.Empty:
        # 内存护栏（2026-09-13）：首个实例总允许（等价旧单例行为）；
        # 再加实例前先看可用内存，不足则不再扩池（回落 bridge，避免 OOM）。
        _room = _mcp_room_for_new_instance() if _MCP_POOL_TOTAL > 0 else True
        make = False
        with _MCP_POOL_LOCK:
            if _MCP_POOL_TOTAL < _mcp_workers() and (_MCP_POOL_TOTAL == 0 or _room):
                _MCP_POOL_TOTAL += 1
                _MCP_POOL_MADE[_wd] = _MCP_POOL_MADE.get(_wd, 0) + 1
                make = True
        if not make:
            # 名额已满：本工程一时没有空闲实例 → **回收别工程的空闲实例**再新建。
            # 依据：实例创建时把 LEAN_PROJECT_PATH 绑死了工程根，别工程的实例对本
            # 工程毫无用处；而"空等本桶归还"在只有一个活跃工程时等价于死等
            # （实测会挂满 wait 秒）。回收的是**空闲**实例，不打断任何在跑的请求。
            stolen = None
            with _MCP_POOL_LOCK:
                for _k, _q in list(_MCP_POOLS.items()):
                    if _k == _wd:
                        continue
                    try:
                        stolen = (_k, _q.get_nowait())
                        break
                    except queue.Empty:
                        continue
            if stolen is not None:
                try:
                    stolen[1].close()
                except Exception:  # noqa: BLE001
                    pass
                with _MCP_POOL_LOCK:
                    _n = max(0, _MCP_POOL_MADE.get(stolen[0], 0) - 1)
                    if _n:
                        _MCP_POOL_MADE[stolen[0]] = _n
                    else:
                        _MCP_POOL_MADE.pop(stolen[0], None)
                    _MCP_POOL_MADE[_wd] = _MCP_POOL_MADE.get(_wd, 0) + 1
                    # 净值不变：关掉 1 个 + 新建 1 个 ⇒ _MCP_POOL_TOTAL 保持
                make = True
        if make:
            try:
                client = _LeanMcpProxyClient(py, sc, work_dir)
            except Exception:  # noqa: BLE001
                _pool_drop(_wd)
                client = None
        else:
            try:
                # 同工程并发争用：等**本工程**实例归还（不跨工程等待）
                client = q.get(timeout=max(1.0, wait))
            except queue.Empty:
                client = None
    if client is None:
        logger.warning(
            "[LeanBridge] mcp 实例池取用失败（K=%d, work_dir=%s）→ 回落 bridge",
            _mcp_workers(), work_dir)
        yield None
        return
    try:
        yield client
    finally:
        if not _mcp_take_drop_flag(client) and _mcp_client_alive(client):
            q.put(client)                  # 健康实例归还本工程桶
        else:
            try:
                client.close()             # 出错/已死 → 关闭（仅此一处 close）
            except Exception:  # noqa: BLE001
                pass
            _pool_drop(_wd)


def mcp_run_code(code: str, work_dir: str, timeout: float = 120.0) -> dict:
    """模块级：用 lean-lsp-mcp **本地执行**一段 Lean 代码（B1 数值验证用）。

    2026-09-11：为"数值计算验证"提供入口（与 SymPy 互为独立交叉校验）。
    - 全本地 LSP，不联网；mcp 环境缺失/异常 → 返回 {"ok": False, "error": ...}，
      调用方须**静默降级**（不得阻断主链路）。
    - 2026-09-13：改经 ``_mcp_acquire`` 借出实例 —— K=1 时即旧的单例 + 全局锁；
      K>1 时与 ``_compile_via_mcp`` 共享实例池 ⇒ 数值核验与编译核验可并行。
    """
    with _mcp_acquire(work_dir) as proxy:
        if proxy is None:
            return {"ok": False, "error": "mcp-env-missing"}
        try:
            _t0 = time.monotonic()
            out = proxy.run_code(code, timeout=timeout)
            _mcp_note(time.monotonic() - _t0, bool(out.get("ok")))
            logger.info("[LeanBridge] ★ mcp run_code 耗时 %.1fs（ok=%s）",
                        time.monotonic() - _t0, bool(out.get("ok")))
            return out
        except Exception as exc:  # noqa: BLE001
            _mcp_mark_drop(proxy)      # 出错实例丢弃，避免协议错位（归还时统一关闭）
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _compile_via_mcp(lean_file: str, code: str, work_dir: str,
                     timeout: float, allow_sorry: bool) -> Optional[dict]:
    """用 lean-lsp-mcp（经 proxy）做行级诊断验证，verdict 语义与 bridge 对齐。

    返回 {"ok": bool, "error": str}；mcp 不可用/异常返回 None（调用方回落 bridge）。
    2026-09-13：① 改经实例池借出（``LEAN_MCP_WORKERS``，1 = 旧的单例 + 全局锁）；
    ② 并发撞名保护 —— 同名 .lean 被两个线程同时诊断会互相覆盖内容 → 取唯一副本，
    用完移入 ``_lean_trash/``（不改变调用方的写入/清理契约）。
    """
    _qfile, _qcopy = _mcp_unique_file(lean_file)
    try:
        return _compile_via_mcp_locked(_qfile, code, work_dir, timeout,
                                       allow_sorry)
    finally:
        _mcp_release_file(_qfile, _qcopy, work_dir)


def _compile_via_mcp_locked(lean_file: str, code: str, work_dir: str,
                            timeout: float, allow_sorry: bool) -> Optional[dict]:
    """``_compile_via_mcp`` 的实现体（已持有独占 .lean 路径）。"""
    with _mcp_acquire(work_dir) as _px:
        if _px is None:
            logger.warning(
                "[LeanBridge] mcp 后端：无 venv python/代理脚本或实例池取用失败 "
                "→ 回落 bridge")
            return None
        try:
            # 首文件冷启动（lean server 加载 Mathlib）可达 60-90s → 放宽
            # 2026-09-13：本次调用计时入账（这是唯一可信的 MCP 耗时口径；
            # 此前全仓无埋点，耗时要靠日志时间戳反推）
            _t0 = time.monotonic()
            # ★★ 2026-09-16 恢复 MCP 超时地板（还赛期的债）。
            # 历史沿革：2026-09-13 为省时间把地板 150s → 90s（见下方原注释）。
            # 但**本段注释自己就写着**「首文件冷启动（lean server 加载 Mathlib）
            # 可达 60-90s」⇒ Mathlib 冷启动本身就 60–90s，而超时也是 90s，
            # **卡在边界上必然频繁失败**。
            # 实测后果（0916 轮 `results/verify10_0916.log`）：
            #   [LeanBridge] mcp 后端异常（proxy 读响应失败: proxy 响应超时（>90s））
            #     → 回落 bridge        （连续 3 次）
            #   [LeanBridge] mcp 诊断失败（诊断输出非 JSON: Error executing tool
            #     lean_diagnostic_messages: File worker fo…）→ 回落 bridge
            # ⇒ **MCP 从未真正生效，全部退回 bridge**。用户明确要求"用 mcp 不用 bridge"，
            #   而这条超时就是最直接的拦路石。
            # 赛后无时间限制（用户方针：凡依据是时间的条款一律重新审视）⇒ 地板恢复。
            # 可用 `LEAN_MCP_TIMEOUT_FLOOR` 覆盖（默认 300s，覆盖冷启动 90s 有 3 倍余量）。
            try:
                _floor = _sw_num("lean_mcp_timeout_floor")
            except (TypeError, ValueError):
                _floor = 300.0
            try:
                resp = _px.request(lean_file,
                                   timeout=max(timeout + 30.0, _floor))
            except BaseException:
                _mcp_note(time.monotonic() - _t0, False)
                raise
            _mcp_el = time.monotonic() - _t0
            _mcp_note(_mcp_el, bool(resp.get("ok")))
            logger.info("[LeanBridge] ★ mcp 诊断耗时 %.1fs（ok=%s, K=%d）",
                        _mcp_el, bool(resp.get("ok")), _mcp_workers())
            if not resp.get("ok"):
                logger.warning(
                    "[LeanBridge] mcp 诊断失败（%s）→ 回落 bridge",
                    str(resp.get("error"))[:160])
                return None
            items = resp.get("items") or []
            errors = [i for i in items if i.get("severity") == "error"]
            if errors:
                base = os.path.basename(lean_file)
                err_text = "\n".join(
                    "%s:%s:%s: error: %s" % (
                        base, i.get("line") or 0, i.get("column") or 0,
                        (i.get("message") or "")[:300])
                    for i in errors[:25])
                # 定位增强：首个错误行取 goal state（elaboration 后秒回），
                # 喂给 _analyze_error 提升错因质量（003/009/053 型中段错）
                gl = errors[0].get("line")
                # 2026-09-13 默认关闭（"1"→"0"，仍可显式设 1 开回）。
                # 依据：本段结果只 append 到 err_text（:1519-1520），而 err_text
                # 仅用于 :1570-1571 的 {"ok":False,...} 返回；本段位于 if errors:
                # （:1502）内部 ⇒ ok=False 已定，它只影响 _analyze_error 的错因
                # 文本质量，**不改变候选是否被淘汰**。省一次 goal 调用（timeout=45s）。
                if gl and _sw_bool("lean_mcp_goal_loc"):
                    try:
                        gresp = _px.request(
                            lean_file, timeout=45.0, goal_line=int(gl),
                            goal_column=int(errors[0].get("column") or 1))
                        goal = gresp.get("goal")
                        if goal:
                            err_text += ("\n--- [lean-lsp-mcp] 首个错误行目标状态 ---\n"
                                         + str(goal)[:800])
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("[LeanBridge] goal 定位失败（忽略）: %s", exc)
                # ★ B4（2026-09-11）：编译失败时用 multi_attempt 自动试多策略。
                # 价值：把"Lean 判你错"升级为"Lean 给出可行改法"——直接补上
                # "检测到了但模型不会改"的缺口。失败不影响主流程（静默跳过）。
                # 2026-09-13 默认关闭（"1"→"0"，仍可显式设 1 开回）。
                # 依据：本段结果只 append 到 err_text（:1540-1541），同 :1502 内
                # 部 ⇒ ok=False 已定，只影响错因文本质量，**不改变候选淘汰**。
                # 省一次 multi_attempt（timeout=90s，是三者中最贵的一项）。
                if _sw_bool("lean_mcp_multi_attempt"):
                    try:
                        _ln0 = int(errors[0].get("line") or 1)
                        _col0 = int(errors[0].get("column") or 1)
                        _ma = _px.multi_attempt(
                            lean_file, _ln0,
                            ["norm_num", "ring", "linarith", "omega",
                             "simp", "aesop", "positivity"],
                            column=_col0, timeout=90.0)
                        _mraw = str(_ma.get("raw") or "")
                        _ok_lines = [l.strip() for l in _mraw.splitlines()
                                     if ("no goals" in l.lower()
                                         or "success" in l.lower())]
                        if _ok_lines:
                            err_text += ("\n--- [lean-lsp-mcp] multi_attempt 可用策略 ---\n"
                                         + "\n".join(_ok_lines[:5]))
                            logger.info("[LeanBridge] ★ multi_attempt 找到可用策略 %d 条",
                                        len(_ok_lines))
                    except Exception as _me:  # noqa: BLE001
                        logger.debug("[LeanBridge] multi_attempt 跳过: %s", _me)
                # ★ B6（2026-09-11）：对「未知标识符 / invalidField」用 hover 查该符号的
                # 真实信息并回填 —— 直击 preverify 之「臆造 API」主因（如 Finset.Nodup）。
                # 2026-09-13 默认关闭（"1"→"0"，仍可显式设 1 开回）。
                # 依据：本段结果只 append 到 err_text（:1562-1565），同 :1502 内
                # 部 ⇒ ok=False 已定，只影响 _analyze_error 的错因文本质量，
                # **不改变候选淘汰**。省一次 hover（timeout=45s）。
                if _sw_bool("lean_mcp_hover_check"):
                    try:
                        _hln = int(errors[0].get("line") or 1)
                        _hcol = int(errors[0].get("column") or 1)
                        _hmsgs = " ".join(str(e.get("message") or "")
                                          for e in errors[:3])
                        _hm = re.search(
                            r"(?:unknown (?:identifier|constant)|Invalid field)"
                            r"\s*'?([A-Za-z_][\w'.]*)", _hmsgs)
                        if _hm:
                            _hr = _px.hover(lean_file, _hln, _hcol,
                                                   timeout=45.0)
                            _hraw = str(_hr.get("raw") or "")[:400]
                            if _hraw:
                                err_text += (
                                    "\n--- [lean-lsp-mcp] hover 查证"
                                    "（该符号的真实信息，据此纠正 API 名/类型）---\n"
                                    f"符号 {_hm.group(1)}: {_hraw}")
                                logger.info("[LeanBridge] ★ hover 查证: %s",
                                            _hm.group(1))
                    except Exception as _he:  # noqa: BLE001
                        logger.debug("[LeanBridge] hover 跳过: %s", _he)
                return {"ok": False,
                        "error": _truncate_error_output(err_text)}
            if not allow_sorry:
                # 与档1 bridge 判定对齐：源码不可信构造 / sorry 警告 → fail
                has_sorry_warn = any(
                    "uses `sorry`" in (i.get("message") or "") for i in items)
                if _scan_untrusted(code) or has_sorry_warn:
                    return {"ok": False, "error": _UNTRUSTED_MSG}
            # ★ B3（2026-09-11，用户要求"必须保证能检测"）：axiom 检查。
            # 用 lean-lsp-mcp 的 lean_verify 查定理依赖的公理集合——可捕捉
            # **间接引入**的 sorry（如经宏/别名），这是源码扫描 _scan_untrusted
            # 覆盖不到的盲区。检出 sorryAx 即判不可信（与档1 语义一致）。
            if _sw_bool("lean_mcp_verify_axioms"):
                try:
                    # ★★ 2026-09-21 修复（覆盖盲区）：原正则**只匹配 `theorem`**，
                    #   对 `example : ... := by ...` 整体跳过 ⇒ 而 MathPilot 生成的
                    #   验证代码**大量使用 `example`** ⇒ 这道"捕捉间接 sorry"的防线
                    #   实际大面积失效。
                    #   实测证据：`ansverify_880065_88791123086.lean`
                    #   = `example : (2:ℚ)*(-2) = -4 := by norm_num` 编译 ok=True，
                    #   但 axiom 检查**静默跳过**（日志里既无"通过"也无"sorryAx"）。
                    #   修法：先找 theorem/lemma；找不到时把**首个 example** 改写成
                    #   命名 theorem 的副本，**重新诊断**（LSP 才会加载新名字）后按名验证。
                    _vname = None
                    _tm = re.search(
                        r"\b(?:theorem|lemma)\s+([A-Za-z_][\w'.]*)", code or "")
                    if _tm:
                        _vname = _tm.group(1)
                    elif re.search(r"(?m)^[ \t]*example\s*:", code or ""):
                        _vname = "_mp_axcheck"
                        _alt = re.sub(
                            r"(?m)^([ \t]*)example\s*:",
                            r"\1theorem " + _vname + " :",
                            code or "", count=1)
                        if _alt != (code or ""):
                            with open(lean_file, "w", encoding="utf-8") as _fh:
                                _fh.write(_alt)
                            _px.request(lean_file, timeout=max(timeout, 90.0))
                            logger.info(
                                "[LeanBridge] ★ axiom 检查改用 example 改写副本：%s",
                                _vname)
                        else:
                            _vname = None
                    if _vname:
                        _vr = _px.verify_theorem(
                            lean_file, _vname, timeout=45.0)
                        _vraw = str(_vr.get("raw") or "")
                        if "sorryAx" in _vraw:
                            logger.warning(
                                "[LeanBridge] mcp axiom 检查发现 sorryAx：%s",
                                _vname)
                            return {"ok": False, "error": _UNTRUSTED_MSG}
                        logger.info("[LeanBridge] ★ mcp axiom 检查通过：%s",
                                    _vname)
                except Exception as _ve:  # noqa: BLE001
                    logger.debug("[LeanBridge] axiom 检查跳过: %s", _ve)
            return {"ok": True, "error": ""}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LeanBridge] mcp 后端异常（%s）→ 回落 bridge",
                           str(exc)[:160])
            _mcp_mark_drop(_px)        # 出错实例丢弃（超时后响应迟到会污染下一请求）
            return None


def _compile_lean(
    code: str,
    work_dir: str,
    lean_executable: str = _DEFAULT_LEAN_EXECUTABLE,
    timeout: float = _DEFAULT_LEAN_TIMEOUT,
    lean_filename: str = "verify.lean",
    allow_sorry: bool = False,
) -> dict:
    """调用 Lean 编译器编译一段 Lean 代码（纯编译路径，不依赖 LLM 栈）。

    参数:
        code: Lean 4 源码。
        work_dir: 编译工作目录（写入 .lean 文件并执行 lake 的目录）。
        lean_executable: Lean 可执行文件名（默认 "lake"，配合 lean-toolchain）。
        timeout: 编译超时（秒）。
        allow_sorry: 声明模式开关。True 时「编译通过但含 sorry」视为 ok
            （用于题目前置形式化验证：只校验命题声明类型正确，不要求证明完整）；
            默认 False 保持后置证明验证原行为（含 sorry 视为未完全验证）。

    返回:
        {"ok": bool, "error": str}。
    """
    exe = lean_executable or _DEFAULT_LEAN_EXECUTABLE
    # 2026-09-09 平台零配置兜底：work_dir 即 mathlib 闭包（含 Mathlib/Tactic.olean
    # 聚合入口）时，若当前进程 LEAN_PATH 未含它则自动注入——平台 clone 后不跑
    # setup 脚本（无 lean-env.sh）也能让 lean.exe 直编 import Mathlib；LEAN_PATH
    # 已被环境显式设置时尊重原值（调用约定：env 显式最高优先），仅追加缺失闭包。
    _lean_entry = os.path.join(work_dir, "Mathlib", "Tactic.olean")
    if os.path.isfile(_lean_entry):
        # 2026-09-13：并行通道下多线程会同时走到这里 —— os.environ 是进程级共享，
        # 读-改-写必须加锁，否则可能丢更新（LEAN_PATH 漏掉闭包 → bridge 直编失败）。
        with _LEAN_PATH_LOCK:
            _lp = (os.environ.get("LEAN_PATH", "") or "").strip()
            _lp_dirs = [os.path.normpath(d) for d in _lp.split(os.pathsep) if d]
            if os.path.normpath(work_dir) not in _lp_dirs:
                os.environ["LEAN_PATH"] = (
                    (_lp + os.pathsep) if _lp else "") + work_dir
    lean_file = os.path.join(work_dir, lean_filename)
    # 2026-09-11（mcp 可用性修复）：mcp 后端下规范化 imports —— 裸 `import Mathlib`
    # 在本机 Mathlib 布局下会触发 fatalError，导致 mcp 恒报 diagnostics_unavailable。
    if get_lean_backend() == "mcp":
        code = _normalize_lean_imports(code)
    with open(lean_file, "w", encoding="utf-8") as f:
        f.write(code)

    # 档2（2026-09-04）：mcp 后端分发（仅 lake 工程；不可用返回 None 回落 bridge）。
    # 放在写文件之后、跑命令之前：mcp 路径复用同一 .lean 文件做 LSP 诊断。
    if get_lean_backend() == "mcp" and _mcp_gate_ok(work_dir):
        logger.info("[LeanBridge] ★ 走 mcp 后端：%s（后端配置=%s）",
                    os.path.basename(lean_file), get_lean_backend())
        via_mcp = _compile_via_mcp(lean_file, code, work_dir, timeout,
                                   allow_sorry)
        if via_mcp is not None:
            logger.info("[LeanBridge] ★ mcp 返回成功：ok=%s",
                        via_mcp.get("ok"))
            return via_mcp
        logger.warning("[LeanBridge] mcp 返回 None → 回落 bridge：%s",
                       os.path.basename(lean_file))
    elif get_lean_backend() == "mcp":
        # 2026-09-12（平台实测暴露）：mcp 已配置但**门控未通过**（work_dir 非
        # lake 工程，如 closure 闭包 + LEAN_PATH 部署）→ 此前静默走 bridge，
        # 平台侧「★ 走 mcp 后端」恒 0 条且无任何告警，被误判成"没走到 Lean
        # 阶段"。此处显式告警（每个 work_dir 只报一次，避免逐候选刷屏）。
        if work_dir not in _MCP_GATE_WARNED:
            _MCP_GATE_WARNED.add(work_dir)
            logger.warning(
                "[LeanBridge] ★ mcp 未生效：work_dir 非 lake 工程 → 本次走 "
                "bridge（%s）。如需 mcp，请提供带 lakefile 的工程根，或用 "
                "LEAN_PROJECT_PATH 指向 lake 工程。", work_dir)

    # lake 分支（含绝对路径 lake.exe）：lake env lean <file> 正确加载工程
    # LEAN_PATH（注意必须带 "lean"，lake env 的语义是"在 lake 环境下运行命令"）
    is_lake = (exe == "lake"
               or os.path.basename(exe).lower().startswith("lake"))
    cmd = ([exe, "env", "lean", lean_filename] if is_lake
           else [exe, lean_filename])
    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        err = (result.stderr or "") + (result.stdout or "")
        if result.returncode == 0:
            # 编译通过；声明模式（allow_sorry=True）允许 sorry 占位（仅校验声明类型），
            # 否则判分语义要求证明完全可核——任何不可信构造都视为未完全验证（档1扩展）：
            #   1) 源码侧：sorry 占位 / 裸 axiom / unsafe / implemented_by / kernel 跳过
            #   2) 输出侧：`declaration uses 'sorry'` 警告（捕捉经宏/别名间接引入的 sorry，
            #      且不受注释/字符串干扰，与 lean_verify 的 sorryAx 拦截对齐）
            if not allow_sorry:
                untrusted = (_scan_untrusted(code)
                             or _has_sorry_warning(err))
                if untrusted:
                    return {"ok": False, "error": _UNTRUSTED_MSG}
            return {"ok": True, "error": ""}
        return {"ok": False, "error": _truncate_error_output(err)}
    except subprocess.TimeoutExpired:
        return {"ok": False,
                "error": f"Lean 编译超时（>{timeout:.0f}s）"}
    except FileNotFoundError:
        return {"ok": False, "error": f"Lean executable not found: {exe}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _truncate_error_output(str(exc))}


# =====================================================================
# LeanBridge：Lean 验证桥接层（依赖注入 client）
# =====================================================================

class LeanBridge:
    """Lean 验证桥接层，把 Lean 形式化验证能力接入 agent 链。

    - ``client``：注入的 agent 链 LLM 客户端（``BaseAgent.llm()`` 或等价接口），
      用于 convert / analyze 阶段，禁止 import ``测试工具/`` 的 LLM 栈；
    - ``config``：只读配置（含 ``lean_executable`` / ``lean_timeout`` 等），
      缺省用模块默认值；
    - ``verify()`` 同步接口（内部 asyncio.run 包装），供 SolverAgent 直接调用。
    """

    def __init__(self, client, config: Any = None, budget=None):
        self.client = client
        self.config = config
        self.budget = budget
        self._lean_env_cache: Optional[dict] = None
        self._mathlib_ready_cache: Optional[bool] = None
        # 档2（2026-09-04）：config.lean_backend 显式 "mcp" 时切后端（模块态）。
        # 环境变量 LEAN_BACKEND 由 get_lean_backend() 每次读取，无需在此处理；
        # 缺省不动模块态 → 全仓库默认 bridge，mcp 仅按需显式启用。
        try:
            _cfg = getattr(config, "config", config)
            _bk = (getattr(_cfg, "lean_backend", "") or "").strip().lower()
        except Exception:  # noqa: BLE001
            _bk = ""
        if _bk in ("bridge", "mcp"):
            set_lean_backend(_bk)

    # ------------------------------------------------------------------
    # 环境与配置
    # ------------------------------------------------------------------

    @property
    def lean_available(self) -> bool:
        """复用 Lean 环境检测结果（带缓存），Lean 不可用时返回 False。"""
        if self._lean_env_cache is None:
            self._lean_env_cache = detect_lean_environment(
                self._lean_executable)
        return bool(self._lean_env_cache.get("available"))

    @property
    def _lean_executable(self) -> str:
        """取配置中的 Lean 可执行文件名，缺省自动探测（LEAN_EXE env /
        vendor/lean-toolchain / elan 命中即用），都无则回退 "lake"。"""
        cfg = getattr(self.config, "config", self.config)
        exe = (getattr(cfg, "lean_executable", "") or "").strip()
        if not exe:
            # 2026-09-06：探测链认 LEAN_EXE env 与 vendor 挂载，保证
            # lean_available 探测的是真实 lean.exe（而非仅 PATH 上的 lake）。
            exe = _detect_lean_executable() or _DEFAULT_LEAN_EXECUTABLE
        return exe

    @property
    def _lean_timeout(self) -> float:
        """取配置中的 Lean 编译超时（秒），缺省 60s。"""
        cfg = getattr(self.config, "config", self.config)
        return float(getattr(cfg, "lean_timeout", _DEFAULT_LEAN_TIMEOUT)
                     or _DEFAULT_LEAN_TIMEOUT)

    @property
    def _lean_project_dir(self) -> str:
        """取配置中的带 Mathlib 的 Lean 工程目录，缺省自动探测。"""
        cfg = getattr(self.config, "config", self.config)
        pdir = getattr(cfg, "lean_project_dir", "") or _detect_lean_project_dir()
        return pdir

    def _mathlib_ready(self) -> bool:
        """探测 Mathlib 是否已编译就绪（核心 tactic 模块可用）。

        本地工程采用「部分编译」布局：因 v4.31.0 兼容问题，全量 Mathlib 聚合
        无法生成，但核心模块 Mathlib.Tactic（norm_num/ring/omega/linarith 等）
        已编译完成，跑分证明足够。故就绪判定以 Mathlib.Tactic.olean 为准
        （而非全量 Mathlib.olean）。结果按进程缓存。

        比赛环境（无 lake 工程目录）：LEAN_PATH 挂载了 core/full 闭包
        （deploy/mathlib-olean，由 deploy/setup_lean.sh 写入）同样视为就绪，
        否则 lean_gate 硬验证会退回纯核心 Lean 而用不上闭包（2026-09-01 修复）。
        """
        if getattr(self, "_mathlib_ready_cache", None) is not None:
            return self._mathlib_ready_cache
        pdir = self._lean_project_dir
        ready = False
        if pdir:
            candidates = [
                os.path.join(pdir, ".lake", "packages", "mathlib", ".lake",
                             "build", "lib", "lean", "Mathlib", "Tactic.olean"),
                os.path.join(pdir, ".lake", "build", "lib", "lean",
                             "Mathlib", "Tactic.olean"),
                os.path.join(pdir, ".lake", "build", "lib", "lean",
                             "Mathlib.olean"),  # 全量布局兼容
            ]
            if any(os.path.isfile(c) for c in candidates):
                ready = True
            else:
                # 兜底：.lake 子树内找 Mathlib/Tactic.olean 或 Mathlib.olean
                for root, _d, files in os.walk(os.path.join(pdir, ".lake")):
                    if "Tactic.olean" in files or "Mathlib.olean" in files:
                        ready = True
                        break
                # 2026-09-10 平台修复：pdir 本身即闭包根（root 一体化形态
                # <root>/mathlib/closure-full，纯 olean 闭包无 .lake）——此前
                # 误判 False 导致 verify_answer 跳过 _prepend_mathlib_import，
                # JSON 通道 lean_code 无 import → norm_num 等未定义 → 平台
                # 非证明题答案验证整体失效（本地有 lake 工程不暴露）。
                #
                # ★ 2026-09-21 修复（云端「Lean 验证全降级」根因）：判据由
                #   「只认聚合入口 Mathlib/Tactic.olean」放宽为
                #   `_has_mathlib_tactics`（聚合入口 **或** 裁剪闭包的具体
                #   tactic 模块）。云端 deploy/cloud_run.env 为让 MCP 通道生效
                #   把 LEAN_PROJECT_PATH 指向裁剪闭包 deploy/mathlib-olean，
                #   于是 pdir 非空且**恰为裁剪闭包根**、无 Mathlib/Tactic.olean
                #   ⇒ 本分支恒 False ⇒ verify()/verify_answer()/
                #   run_pre_verification()/audit_sketch() 四处全部跳过 import
                #   归一化 ⇒ `import Mathlib.Tactic` 原样送编译 ⇒ 必败 ⇒
                #   verdict 恒 unknown、lean_valid 恒 False。
                #   ⚠️ 下方 else 分支的 NormNum 兜底**早已存在**，本分支此前
                #   缺失 ⇒ 两个分支**不对称**才是真正的缺陷（不是"没写兜底"）。
                if not ready and _has_mathlib_tactics(pdir):
                    ready = True
        else:
            # 无 lake 工程（比赛环境）：LEAN_PATH 或默认部署目录挂载闭包即就绪
            for r in _closure_roots():
                # core 闭包无聚合入口，用具体模块 olean 判定；full 闭包两者皆有
                if _has_mathlib_tactics(r):
                    ready = True
                    break
        # ★ 2026-09-21 统一兜底：pdir 存在但**本身不含** Mathlib，而编译器真正
        # 搜索的 LEAN_PATH / 仓库默认闭包里**有** Mathlib（如 pdir 被设成非闭包
        # 目录、闭包另经 LEAN_PATH 挂载）⇒ 仍必须做 import 归一化，否则同样
        # 落入"归一化被跳过 → import Mathlib.Tactic 编译必然失败"的全降级。
        # 该兜底对「机器上确实没有 Mathlib」的情形返回 False，与原行为一致。
        if not ready:
            ready = any(_has_mathlib_tactics(r) for r in _closure_roots())
        self._mathlib_ready_cache = ready
        return ready

    # ------------------------------------------------------------------
    # LLM 调用（走注入的 client，计入 Budget）
    # ------------------------------------------------------------------

    def _llm_call(self, messages: list, temperature: float,
                  max_tokens: int, prefill: str = "") -> str:
        """用注入的 client 调用一次 LLM（convert/analyze 阶段），计入 Budget。

        prefill 非空时走 **assistant-prefill 解码**（Intern 系列铁律）：
        在消息末尾追加 assistant 种子前缀，让模型进入"续写模式"，
        抑制 `reasoning_content` 思维块（否则思维块吃满 max_tokens，
        JSON/代码被腰斩，finish_reason=length）。种子必须锚定顶层结构，
        如 `'{"lean_code":'` / `'{"formal_spec":'` / `'import Mathlib.Tactic'`。
        返回前用 ``stitch`` 把种子与续写拼接回完整文本（兼容后端
        continuation/echo/ignored 三种形态）。
        """
        # 2026-09-03 审核：原有 `_budget_ok` 预算闸门已删（比赛无次数上限，
        # 恒放行的死分支反而掩盖了"翻译被跳过 → unknown"的历史根因）。
        msgs = messages
        seed = prefill
        stitch = None
        if seed:
            try:
                from utils.prefill import prefill_messages as _pfm, stitch as _st
            except ImportError:
                try:
                    from submit.utils.prefill import (
                        prefill_messages as _pfm, stitch as _st)
                except ImportError:
                    _pfm = _st = None
            if _pfm is not None:
                msgs = _pfm(messages, seed)
                stitch = _st
        _guard = (_LLM_SERIAL_LOCK if _mcp_workers() > 1
                  else contextlib.nullcontext())
        with _guard:
            resp = self.client.chat(
                messages=msgs, temperature=temperature, max_tokens=max_tokens)
        text = _normalize_bridge_response(resp)
        # 响应为空（API 故障/预算耗尽）时不拼接种子——否则种子本身会被当成
        # 结果（如 "import Mathlib.Tactic\n" 恰好是合法 Lean 代码 → 假 proof_valid）。
        if seed and stitch is not None and text:
            text = stitch(seed, text)
        # Anti-hack 预处理（SU-01 §3.3）：格式病理 → safe fallback。
        # 放在 stitch 之后，检查完整文本（含种子拼接后的产物）。
        if text:
            text = _anti_hack_guard(text)
        if self.budget is not None:
            self.budget.spend(1)
        return text

    # ------------------------------------------------------------------
    # 阶段一：NL → Lean 转化
    # ------------------------------------------------------------------

    def _convert_to_lean(self, problem: str, reasoning: str) -> str:
        """把自然语言推理转化为 Lean 4 代码（依赖注入的 client，走 prefill）。"""
        messages = [
            {"role": "system", "content": LEAN_CONVERT_SYSTEM},
            {"role": "user", "content": LEAN_CONVERT_USER.format(
                problem=problem, reasoning=reasoning)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=65536,
                             prefill=_mathlib_import_block() + "\n")
        return _strip_code_fence(raw)

    # ------------------------------------------------------------------
    # 阶段二：编译验证（纯编译路径）
    # ------------------------------------------------------------------

    def _compile(self, code: str, work_dir: str,
                 lean_filename: str = "verify.lean",
                 allow_sorry: bool = False) -> dict:
        """复用纯编译路径 ``_compile_lean`` 对转化出的 Lean 代码做编译验证。

        work_dir 为带 lakefile 的工程目录时强制走 ``lake env lean``
        （正确加载 Mathlib 的 LEAN_PATH）；否则用探测到的 lean.exe 编译
        （纯核心 Lean，临时目录回退路径）。

        lean_filename 仅在使用带 Mathlib 的 Lean 工程目录（避免覆盖工程内已有
        verify.lean）或需并发安全时指定；缺省仍写 verify.lean。
        allow_sorry 透传给 ``_compile_lean``：前置形式化（声明模式）允许 sorry
        占位，后置答案验证（默认）不允许。
        """
        is_lake_project = any(
            os.path.isfile(os.path.join(work_dir, f))
            for f in ("lakefile.toml", "lakefile.lean", "lake-manifest.json"))
        if is_lake_project:
            # 用 elan lake 绝对路径（避免 subprocess PATH 解析问题）
            elan_lake = os.path.expanduser(r"~\.elan\bin\lake.exe")
            exe = elan_lake if os.path.isfile(elan_lake) else "lake"
        else:
            exe = self._lean_executable
            # 非 lake 工程（比赛环境临时目录）：优先用探测到的 lean.exe 直编。
            # 否则 exe 缺省为 "lake"，在无 lakefile 的临时目录跑 `lake env lean`
            # 会报错（找不到 lakefile），导致硬验证全部失败（2026-09-01 修复）。
            detected = _detect_lean_executable()
            if detected:
                exe = detected
        return _compile_lean(code, work_dir,
                             lean_executable=exe,
                             timeout=self._lean_timeout,
                             lean_filename=lean_filename,
                             allow_sorry=allow_sorry)

    # ------------------------------------------------------------------
    # 阶段三：错误分析（映射为 BugReport / Finding）
    # ------------------------------------------------------------------

    def _analyze_error(self, problem: str, reasoning: str,
                       lean_code: str, compile_error: str) -> BugReport:
        """编译失败时分析根因，映射为 BugReport（依赖注入的 client）。

        - 逻辑错误 → Critical Finding，verdict='proof_invalid'；
        - 纯翻译错误 / 无法判断 → verdict='unknown'（供上层降级）。
        """
        messages = [
            {"role": "system", "content": LEAN_ANALYZE_SYSTEM},
            {"role": "user", "content": LEAN_ANALYZE_USER.format(
                problem=problem, reasoning=reasoning,
                lean_code=lean_code, compile_error=compile_error)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=32768,
                             prefill='{"error_category":')
        parsed = _parse_analysis_json(raw)
        if not parsed:
            # ★ 2026-10-07（fix-obs-tail · 静默跳过埋点）：原**静默**返回裸 unknown
            #   （既无 logger 也无 verdict_reason）⇒ "错误分析被跳过"在 diag 里不可见。
            return _mk_report("unknown", reason="analyze_unparsed")

        category = parsed.get("error_category", "uncertain")
        repairable = parsed.get("repairable", "") or ""
        suggestion = parsed.get("suggestion", "") or ""
        critical_desc = parsed.get("critical_desc", "") or ""

        # 2026-09-12：叠加**确定性修法**（由编译器原文特征推断）。
        # 原实现 desc = `critical_desc or suggestion or compile_error[:300]` ——
        # 只要 LLM 给出描述，编译器原文就被丢弃，模型因此拿不到"改哪一行"的信息
        # （与 2.6 实测「2 轮重试 0 成功」同源）。此处把确定性修法**追加在末尾**：
        # 既不破坏 LLM 的业务判断（逻辑错/翻译错的定性），又保证反馈始终可操作。
        _det_hint = hint_for_compile_error(compile_error)
        _base_desc = critical_desc or suggestion or compile_error[:300]
        _desc = (_base_desc + "\n修法提示：" + _det_hint) if _det_hint else _base_desc

        if category in ("logic_error", "both"):
            findings = [Finding(
                location="lean_verify", kind="Critical", severity=5,
                desc=_desc)]
            report = BugReport(findings=findings, verdict="proof_invalid")
        else:
            # 纯翻译错误 / uncertain：视为可修复缺口，但需人工复核 → 降级 unknown
            findings = [Finding(
                location="lean_translate", kind="Gap", severity=1,
                desc=_desc or "Lean 形式化/编译存在问题")] if repairable in ("yes", "partial") else []
            report = BugReport(findings=findings, verdict="unknown")

        # 附加可修复性与修正建议（改造2 新增可选字段，向后兼容）
        report.repairable = repairable
        report.suggestion = suggestion
        return report

    # ------------------------------------------------------------------
    # 对外同步接口
    # ------------------------------------------------------------------

    def verify(self, problem: str, reasoning: str, domain: str = "",
               timeout: float = 60.0) -> Optional[BugReport]:
        """NL 推理 → Lean 形式化验证 → 错误分析 → BugReport（同步接口）。

        - 编译通过且无 sorry → BugReport(verdict='proof_valid')
        - 逻辑错误 → BugReport(findings=[Critical...], verdict='proof_invalid')
        - 纯翻译错误 / Lean 环境缺失 / 超时 → BugReport(verdict='unknown') 供上层降级
        - 全程受 timeout 与 Budget 约束，不抛异常。

        参数:
            problem: 原题。
            reasoning: 待验证的推理文本。
            domain: 题目领域（暂未使用，预留扩展）。
            timeout: 整体 wall-clock 超时（秒）。

        返回:
            BugReport 或 None（内部异常时返回 None，由上层降级）。
        """
        deadline = time.monotonic() + max(1.0, timeout)
        try:
            # 1) Lean 环境缺失 → 降级 unknown
            if not self.lean_available:
                logger.warning("[LeanBridge] Lean 环境不可用，降级为 unknown")
                # ★ 2026-10-07（fix-obs-tail · 静默跳过埋点）：原只写 logger、**不带
                #   任何结构化原因** ⇒ diag.lean_gate 只看到 unknown、不知为何跳。补 verdict_reason。
                return _mk_report("unknown", reason="lean_unavailable")

            # 2) 阶段一：NL → Lean 转化
            if time.monotonic() > deadline:
                return _mk_report("unknown", reason="deadline_before_convert")
            lean_code = self._convert_to_lean(problem, reasoning)
            if not lean_code:
                return _mk_report("unknown", reason="convert_to_lean_failed")

            # 3) 阶段二：编译验证
            if time.monotonic() > deadline:
                return _mk_report("unknown", reason="deadline_before_compile")
            project_dir = self._lean_project_dir
            # Mathlib 就绪判定提前：比赛环境无 lake 工程（_lean_project_dir 为空），
            # 但 LEAN_PATH 已挂载 core/full 闭包（deploy/setup_lean.sh）→ 同样
            # prepend Mathlib import，否则硬验证退回纯核心 Lean 用不上闭包
            # （2026-09-01 修复，比赛环境关键路径）。
            use_mathlib = self._mathlib_ready()
            code_to_compile = (_prepend_mathlib_import(lean_code)
                               if use_mathlib else lean_code)
            comp = None
            if project_dir:
                # 走带 Mathlib 依赖的 Lean 工程目录：Mathlib 真正可用。
                lean_file = "verify_%d_%d.lean" % (
                    os.getpid(), int(time.monotonic() * 1e6))
                comp = self._compile(code_to_compile, project_dir,
                                     lean_filename=lean_file)
                _trash_lean_file(project_dir, lean_file)
            else:
                # 比赛环境回退：单文件临时目录（lean.exe 直编 + LEAN_PATH 挂载闭包）
                with tempfile.TemporaryDirectory(prefix="lean_bridge_") as work_dir:
                    comp = self._compile(code_to_compile, work_dir)

            if comp and comp.get("ok"):
                # 编译通过且无 sorry（_compile_lean 已拦截 sorry）→ proof_valid。
                # 关键修复：此前 project_dir 分支会穿透到 _analyze_error 而把
                # 一次成功的 Mathlib 形式化验证误判为 unknown（与老师要求的
                # "AI解答→Lean形式化(mathlib)→自动判定通过/不通过" 不符）。
                return BugReport(verdict="proof_valid", findings=[])

            # 4) 阶段三：错误分析（project_dir 分支编译失败同样走此路径，
            #    避免 verify() 落空返回 None 导致上层拿不到 BugReport）
            if time.monotonic() > deadline:
                return _mk_report("unknown", reason="deadline_before_error_analysis")
            return self._analyze_error(
                problem, reasoning, lean_code,
                comp.get("error", "编译失败（无详细输出）") if comp else "编译失败（无详细输出）")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LeanBridge] verify 异常（降级 unknown）: %s", exc)
            return _mk_report("unknown",
                              reason="exception_" + type(exc).__name__)

    # ------------------------------------------------------------------
    # 答案审核（轻量路径）：最终答案 norm_num/ring 结果验证（2026-09-01）
    # ------------------------------------------------------------------
    def _convert_answer_to_lean(self, problem: str, reasoning: str,
                                answer: str,
                                answer_hint: str = "") -> Optional[str]:
        """把最终答案 + 推理关键计算转成轻量 Lean example 验证代码。

        用依赖注入的 client 调用书生：输出 ``example : <命题> := by <tactic>``
        形式的验证代码。无法形式化（LLM 返回 error / 解析失败 / 无代码）返回 None，
        由调用方降级 unknown。

        answer_hint 非空时（重试），附加到 USER 提示词强制书生把最终答案
        逐字锚定到验证命题结论侧（修正「书生自己重算、无视 USER 答案」的缺陷）。
        """
        hint = ("\n## 上一轮验证代码没有包含最终答案原值（无效输出）\n"
                + answer_hint.strip() + "\n") if answer_hint else ""
        messages = [
            {"role": "system", "content": LEAN_ANSWER_VERIFY_SYSTEM},
            {"role": "user", "content": LEAN_ANSWER_VERIFY_USER.format(
                problem=problem, reasoning=reasoning, answer=answer,
                answer_hint=hint)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=65536,
                             prefill='{"lean_code":')
        parsed = _parse_analysis_json(raw)
        if not parsed:
            return None
        if parsed.get("error"):
            logger.info("[LeanBridge] 答案无法形式化: %s",
                        str(parsed["error"])[:120])
            return None
        lean_code = _strip_code_fence(str(parsed.get("lean_code", "") or ""))
        if not lean_code:
            return None
        # 数字锚定兜底校验：答案数字（剥 \boxed 壳后）必须出现在 lean_code，
        # 否则视为「没有验证答案」（书生自己重算而非审核 USER 答案），带反馈重试一次。
        if not _answer_embedded(lean_code, answer):
            _anchor = _unwrap_answer(answer) or (answer or "").strip()
            logger.warning(
                "[LeanBridge] 答案 %r 的数值未出现在验证代码（书生自算而非审核答案），重试",
                _anchor[:40])
            retry_hint = ("\n## 上一轮输出无效：你生成的验证代码没有包含最终答案的数值原值 "
                          + _anchor[:60]
                          + "。请重新生成：先把最终答案的数值提取出来（如 \\boxed{3000} "
                            "锚 3000、\\dfrac{2617}{2618} 锚 2617 / 2618），"
                            "再写 example : <关键计算> = <该数值> := by <tactic>，"
                            "结论侧必须逐字包含该数值原值。\n")
            retry_msgs = [
                {"role": "system", "content": LEAN_ANSWER_VERIFY_SYSTEM},
                {"role": "user", "content": LEAN_ANSWER_VERIFY_USER.format(
                    problem=problem, reasoning=reasoning, answer=answer,
                    answer_hint=retry_hint)},
            ]
            raw2 = self._llm_call(retry_msgs, temperature=0.0, max_tokens=65536,
                                  prefill='{"lean_code":')
            parsed2 = _parse_analysis_json(raw2)
            if not parsed2 or parsed2.get("error"):
                return None
            lean_code = _strip_code_fence(str(parsed2.get("lean_code", "") or ""))
            if not lean_code or not _answer_embedded(lean_code, answer):
                return None
        return lean_code

    def _verify_answer_by_system(self, reasoning: str,
                                 answer: str) -> Optional[bool]:
        """**系统侧命题验算** —— 命题不由 LLM 自由发挥，避免"自证放行"。

        背景（2026-09-13 定位）：`verify_answer` 原路径让 LLM 把「答案+推理」写成
        `example : <命题> := by <tactic>`，而 **Lean 只能验证"命题可证"，无法验证
        "命题是否等于题目"**。LLM 只要写恒真式（如 `example : (0:ℚ) = 0`）就必然
        通过 ⇒ 错误答案被判 answer_valid（实测 010 命中）。

        本方法改为：从推理里提取**已带工具标记的算式**（`<calc>...</calc>` 或
        `[计算] ... = ...`），由**系统**构造命题「(算式) = (候选答案数值)」并编译：
          · 编译通过 → True  （答案与自身计算一致，强证据）
          · 编译失败 → False （答案与自己的计算矛盾 ⇒ 答案必错，强信号）
          · 无法提取算式 → None（**不影响**原有判定，纯增量）

        设计原则：**只增加拦截力，不降低原有能力**（返回 None 时调用方按原逻辑走）。
        """
        try:
            want = _to_exact_number_safe(answer)
            if want is None:
                return None
            text = reasoning or ""
            cands = re.findall(r"<calc>\s*(.*?)\s*</calc>", text, re.S)
            if not cands:
                cands = [m.group(1) for m in
                         re.finditer(r"\[\s*计算\s*\]\s*([^\n=]{2,120})=([^\n]{1,60})",
                                     text)]
            # ★ 2026-09-17（L1）：**去 `<calc>` 依赖**的正则回退。
            # 背景：本守卫原先只认 `<calc>…</calc>` 与 `[计算] x = y`，而
            # `enable_calc_tool=False`（2026-09-15 起默认关）⇒ 模型不被要求写 `<calc>`
            # ⇒ 提不到算式 ⇒ **102/102 条记录的 `sys_verify` 全为 None**
            #（本守卫自 2026-09-15 起**结构性不可达**，等于不存在）。
            # ★ 2026-10-01：`<calc>` 板块与 `enable_calc_tool` 已整体删除，
            #   本正则回退成为唯一提取路径（上方历史背景保留）。
            # 回退判据：**整行纯算术等式**（左侧只含数字/运算符/括号、且至少含一个
            # `+ - * / ^`；右侧为数字）⇒ 交给下游构造 `(左) = (答案)` 编译。
            # 0 LLM 成本、不改提示词、不动 calc 链。
            _from_marker = True
            if not cands:
                _from_marker = False
                _rx_fb = re.compile(
                    r"^[ \t]*([0-9+\-*/^(). \t]{5,120})=[ \t]*"
                    r"([-+]?\d+(?:\.\d+)?)[ \t]*$", re.M)
                cands = [m.group(1) for m in _rx_fb.finditer(text)]
                cands = [c for c in cands if any(op in c for op in "+-*/^")]
            exprs = []
            for c in cands[:4]:
                e = (c or "").strip()
                # 取等号左侧作为待验证表达式（右侧是模型自己写的值，不可信）
                if "=" in e:
                    e = e.split("=", 1)[0].strip()
                if e and len(e) <= 160:
                    exprs.append(e)
            if not exprs:
                return None
            # 逐个尝试：只要有一个算式在 Lean 下精确等于答案，即认定一致
            for e in exprs:
                code = (
                    "import Mathlib.Tactic\n"
                    "example : (" + e + ") = (" + want + ") := by norm_num\n")
                if not self._mathlib_ready():
                    return None
                project_dir = self._lean_project_dir
                if not project_dir:
                    return None
                lean_file = "sysverify_%d_%d.lean" % (
                    os.getpid(), int(time.monotonic() * 1e6))
                comp = self._compile(_prepend_mathlib_import(code), project_dir,
                                     lean_filename=lean_file, allow_sorry=False)
                _trash_lean_file(project_dir, lean_file)
                if comp and comp.get("ok"):
                    return True
            # ★ 2026-09-17（L1）：**仅当算式来自显式工具标记时**才允许"矛盾 ⇒ 判错"。
            # 原因：正则回退抓到的等式可能与本题**无关**（推理里任意一行算术都能命中）
            # ⇒ 用它判 `False`（= 答案必错的强信号）会**误拒正确候选**。
            # 故回退来源**只能确认（True），不能否决**，否则返回 None（不作判断）。
            if not _from_marker:
                return None
            # 所有算式都算不出该答案 ⇒ 答案与自身计算矛盾
            return False
        except Exception:  # noqa: BLE001  任何异常都不影响原有判定
            return None

    def verify_answer(self, problem: str, reasoning: str, answer: str,
                      domain: str = "", timeout: float = 60.0) -> Optional[BugReport]:
        """答案审核（轻量路径，非证明题）：最终答案 + 关键计算用 norm_num/ring 验证。

        与 ``verify()``（整题形式化，证明题）的区别：这里只验证解答**声称的计算与
        最终答案**，编译 5-21s 内，不整题形式化，满足用户「证明题+解答题都要过
        Lean」但控制时间开销的要求。

        - 编译通过 → BugReport(verdict='answer_valid')（计算/答案经 Lean 判定正确）
        - 逻辑错误（norm_num 证不出 / 计算与推理矛盾）→ verdict='proof_invalid'
        - 翻译问题 / 答案无法形式化 / 环境缺失 / 超时 → verdict='unknown' 降级放行
        - ★ 2026-10-07（**语义分离**）：**形式化不充分**（验证代码未锚定题目条件 /
          只验了自证恒等式）**不再**判 'proof_invalid'，改判 'unknown'
          —— 代码已编译通过，属**无法核验**、**不等于答案错**。成因经
          `verdict_reason` 区分：`cross_check_failed` / `ground_self_proof` /
          `identity_self_proof`（由 `LEAN_CROSSCHECK_AS_UNKNOWN=0` 可回退旧语义）。
          依据：实测 smoke10 `lean_gate` 123 条中 51 条 `cross_check_failed`
          **全部 compiled=true**，其中 official112-004 的
          `example : (2025 : ℕ) / 2 = 1012` 为真命题却被判 `proof_invalid`。

        返回的 BugReport 附加 ``lean_code`` 属性（供上层埋点提取 import/example）。

        ★ 2026-09-17 可观测性补强：此前**所有早退分支都只返回光秃秃的
        `BugReport(verdict="unknown")`，不带任何原因** —— 实测 003 时
        `diag.lean_gate` 只有 id/verdict/lean_valid/degraded/error，**无 lean_code、
        无守卫依据** ⇒ 完全无法回答"它为什么这样判"。现统一附加：
          · `verdict_reason` —— 本判定的成因（早退原因 / 守卫结论）
          · `lean_code`      —— 实际送编译的代码（全部路径都带，含早退）
          · `cross_check`    —— 守卫①`_cross_check_problem_numbers` 的取值
          · `sys_verify`     —— 守卫②`_verify_answer_by_system` 的取值
          · `compiled`       —— Lean 编译是否通过
        """
        def _mk(verdict: str, findings=None, reason: str = "",
                code: str = "", **extra):
            """构造带诊断属性的 BugReport（早退与正常路径统一走这里）。

            ★ 2026-10-07（fix-obs-tail）：实现已上提为模块级 `_mk_report`（纯移动），
            此处只留别名以保持 `verify_answer` 内调用点一行未改。
            """
            return _mk_report(verdict, findings, reason, code, **extra)

        deadline = time.monotonic() + max(1.0, timeout)
        try:
            # 1) Lean 环境缺失 → 降级 unknown
            if not self.lean_available:
                logger.warning("[LeanBridge] Lean 环境不可用，答案验证降级 unknown")
                return _mk("unknown", reason="lean_unavailable")

            # 2) 无答案 / 选项字母答案（选择题）→ 无法 norm_num 验证，降级放行
            answer = (answer or "").strip()
            if not answer:
                return _mk("unknown", reason="empty_answer")
            if re.fullmatch(r"[A-Da-d][.、)]?|第[一二三四]个|（[A-Da-d]）", answer):
                return _mk("unknown", reason="option_letter_answer")

            # 3) 阶段一：答案 + 关键计算 → 轻量 Lean example
            if time.monotonic() > deadline:
                return _mk("unknown", reason="deadline_before_convert")
            lean_code = self._convert_answer_to_lean(problem, reasoning, answer)
            if not lean_code:
                return _mk("unknown", reason="convert_to_lean_failed")

            # 4) 阶段二：编译验证（不允许 sorry —— 答案必须被 tactic 证出）
            if time.monotonic() > deadline:
                return _mk("unknown", reason="deadline_before_compile", code=lean_code)
            project_dir = self._lean_project_dir
            use_mathlib = self._mathlib_ready()
            code_to_compile = (_prepend_mathlib_import(lean_code)
                               if use_mathlib else lean_code)
            if project_dir:
                lean_file = "ansverify_%d_%d.lean" % (
                    os.getpid(), int(time.monotonic() * 1e6))
                comp = self._compile(code_to_compile, project_dir,
                                     lean_filename=lean_file, allow_sorry=False)
                _trash_lean_file(project_dir, lean_file)
            else:
                with tempfile.TemporaryDirectory(prefix="lean_ansverify_") as work_dir:
                    comp = self._compile(code_to_compile, work_dir,
                                         allow_sorry=False)

            if comp and comp.get("ok"):
                # 2026-09-03 防自证（老师指令）：编译通过 ≠ 真验证。
                # 自证形态：LLM 写 'example : (50005000:ℚ) = 50005000 := rfl'——
                # 代码与题目无关，验 X=X 恒等式（022 v4 实测 answer_valid 但
                # 50005000 ≠ 真值 25502500）。交叉核对：验证代码必须引用
                # **题目关键数字**（>=3 位数且排除通用小整数），无交叉 = 自证嫌疑 → 拒绝。
                # v17 补丁：题目无大数字时退而用"答案数字"核对——答案里的
                # 数字必须进验证代码（拦 '\[ Q(x)' 残缺答案自证）。
                _cc = _cross_check_problem_numbers(problem, lean_code)
                # ★★ 2026-10-07：`_cc_reason` 记录**为什么** `_cc` 被置 False。
                #   此前三个失败成因（数字/符号未交叉 / 闭式自证 / 恒等式自证）**复用
                #   同一条失败分支、产出同一句 desc 与同一 reason**，外部无法区分
                #   （effect_capture #10「恒等式骗过验证」因此**无独立留痕、无法判定**）。
                #   现分设独立 reason，供 diag / cloud_health_report / 效果脚本单独观测。
                _cc_reason = "cross_check_failed"
                # ★★ 2026-09-22：**闭式自证拦截**（补上循环判据的缺口，见上方 helper 注释）。
                #   题面含参数 + 验证代码是 ground 闭式 ⇒ 只证明了 `X = X` 型恒等式，
                #   不可能形式化题目 ⇒ 直接判自证，不再看数字是否"出现在代码里"。
                if (_cc is not False and _problem_is_parametric(problem)
                        and _is_ground_statement(lean_code)):
                    _cc = False
                    _cc_reason = "ground_self_proof"
                # ★★ 2026-10-06 新增（**恒等式必须判自证** —— 实测铁证）：
                #   题 002 的 `example : (√5-1)/2 = (√5-1)/2 := by norm_num` 是**恒等式**，
                #   编译必然通过、与答案对错无关，却被判 `answer_valid` ⇒ 假执行。
                #   根因：下面的 `common2 = (ans_nums & code_nums2) - {...}` 区分不了
                #   「验证命题」与「恒等式」—— 恒等式里当然含答案的数字（写了两遍）。
                #   既有 `_is_ground_statement` 只在**题面含参数**时触发，覆盖不到本题。
                if _cc is not False and _is_identity_statement(lean_code):
                    _cc = False
                    _cc_reason = "identity_self_proof"   # ★ B 项：独立留痕
                if _cc is None:
                    # 题目无 >=3 位数字：① 答案侧数字核对 → ② 仍无区分度则用题面变量核对
                    ans_nums = set(re.findall(r"\b(\d{1,})\b", answer or ""))
                    code_nums2 = set(re.findall(r"\b(\d{1,})\b", lean_code or ""))
                    common2 = (ans_nums & code_nums2) - {"0", "1", "2"}
                    if common2:
                        _cc = True               # 答案里有区分度的数字已进代码
                    elif ans_nums - {"0", "1", "2"}:
                        _cc = False              # 答案有数字却没进代码 ⇒ 自证
                    else:
                        # 答案数字无区分度（如答案本身就是 0）——原实现在此**直接放行**
                        # （`not ans_nums - {"0","1","2"}` 恒为 True），实测被 010 这类
                        # 题利用：LLM 写 `example : (0:ℚ) = 0 := by norm_num` 即通过。
                        # 2026-09-13 修复：改用**题面变量符号**核对（真验证必引题目变量）。
                        _cc = _cross_check_problem_symbols(problem, lean_code)
                if not _cc:
                    # ★★ 2026-10-07（**语义分离**）：本分支的全部成因都是「验证代码
                    #   没锚定题目条件 ⇒ **形式化不充分**」，**不是**「命题为假」。
                    #   实测 official112-004 的代码 `(2025:ℕ)/2 = 1012` 编译通过
                    #   （`compiled=true`）却因闭式自证拦截落到 `proof_invalid` —— 把
                    #   「无法核验」误判成「证明失败」。故结论码改由开关决定：
                    #   默认 → `unknown`（**无法核验**，非答案错）；设
                    #   `LEAN_CROSSCHECK_AS_UNKNOWN=0` 回退旧 `proof_invalid`。
                    _cc_verdict = _crosscheck_failure_verdict()
                    report = BugReport(
                        verdict=_cc_verdict,
                        findings=[Finding(
                            location="answer_verify", kind="Critical",
                            severity=5,
                            # ★★ 2026-10-06 修（**"把非答案问题当成答案错误"**）：
                            #   实测这条 advice 在题 000/001 里各占 **12/15 条**、
                            #   而带定位的结构化 bug report 只占 0~1 条 ⇒ **噪声压过信号**，
                            #   且模型被引向"重写验证代码"，把答案越改越偏
                            #   （题 000：20 → 20971520，标准 20460）。
                            #   本检查本身**是对的**（防 LLM 写恒真式骗过 Lean 认证），
                            #   所以**保留拒绝判定**；但必须讲清楚：
                            #   它说的是**验证产物**没锚定题目数字，**不等于答案错**。
                            desc="【这不是答案错误】Lean 验证代码未引用题目的关键数字/条件"
                                 "（只验了自身恒等式），因此本候选**无法被 Lean 认证** —— "
                                 "但**不能据此判定答案错**。请**保持答案不变**，"
                                 "只把题目条件与答案一起形式化"
                                 "（如 example : 题目约束 → 结论 = 答案），逐字锚定题目数值。")])
                    setattr(report, "lean_code", lean_code)
                    # 独立留痕：区分「数字未交叉」/「闭式自证」/「恒等式自证」三类成因
                    setattr(report, "verdict_reason", _cc_reason)
                    setattr(report, "cross_check", False)
                    setattr(report, "compiled", True)
                    setattr(report, "suggestion",
                            "验证代码必须包含题目中的关键数值与条件，禁止只写 X=X 恒等式")
                    logger.warning(
                        "[LeanBridge] 答案验证形式化不充分（%s），判 %s"
                        "（代码已编译通过 ⇒ 无法核验 ≠ 答案错）",
                        _cc_reason, _cc_verdict)
                    return report
                # 2026-09-13 新增：**系统命题验算**（命题由系统构造，非 LLM 自由发挥）。
                # 动机：Lean 只能验证"命题可证"，无法验证"命题 = 题目"；LLM 写恒真式
                # 即被判 answer_valid（实测 010：错答案 0 被放行）。此处从推理里提取
                # 带工具标记的算式，由系统构造「(算式) = (答案数值)」并编译：
                #   · 编译失败 ⇒ 答案与自身计算矛盾 ⇒ 直接判 proof_invalid（强信号）
                #   · 通过 / 无法构造 ⇒ 不影响原有判定（纯增量，不降低既有能力）
                try:
                    _sys = self._verify_answer_by_system(reasoning, answer)
                except Exception:  # noqa: BLE001
                    _sys = None
                if _sys is False:
                    _r = BugReport(
                        verdict="proof_invalid",
                        findings=[Finding(
                            location="answer_verify", kind="Critical", severity=5,
                            desc="最终答案与推理中的**计算结果矛盾**：系统已用 Lean "
                                 "复算你给出的算式，结果与最终答案不一致。"
                                 "请重新核对计算并修正答案。")])
                    setattr(_r, "lean_code", lean_code)
                    setattr(_r, "verdict_reason", "sys_verify_conflict")
                    setattr(_r, "cross_check", True)
                    setattr(_r, "sys_verify", False)
                    setattr(_r, "compiled", True)
                    setattr(_r, "suggestion",
                            "重算该算式，确保最终答案与之逐字一致")
                    logger.warning(
                        "[LeanBridge] 系统命题验算不通过：答案与算式矛盾 → 拒绝")
                    return _r
                report = BugReport(verdict="answer_valid", findings=[])
                # 附加 lean_code 供上层埋点提取 import/example（BugReport 无此字段）
                # ★ 2026-09-17：同时附加**守卫判定依据**，使"为什么判 valid"可事后核查
                #   —— 实测 003 的 `sys_verify` 恒为 None（calc 工具已关 ⇒ 推理里没有
                #   `<calc>` 标记 ⇒ 该守卫结构性不生效），这一事实此前完全不可见。
                setattr(report, "lean_code", lean_code)
                setattr(report, "verdict_reason", "compiled_and_guards_passed")
                setattr(report, "cross_check", True)
                setattr(report, "sys_verify", _sys)
                setattr(report, "compiled", True)
                return report

            # 5) 阶段三：错误分析（把最终答案并入 reasoning 上下文，定位更准）
            if time.monotonic() > deadline:
                return _mk("unknown", reason="deadline_before_error_analysis",
                           code=lean_code, compiled=False)
            return self._analyze_error(
                problem,
                reasoning + "\n## 最终答案\n" + answer,
                lean_code,
                comp.get("error", "答案验证编译失败（无详细输出）")
                if comp else "答案验证编译失败（无详细输出）")
        except Exception as exc:  # noqa: BLE001
            # 2026-09-13 修复：此处原实现**直接把异常降级为 unknown**，但异常的主因
            # 是翻译阶段的 LLM 调用超时（LLMClient 180s × 重试 1 次 = 360s），被静默
            # 吞掉后 6 个候选 verdict 全为 unknown（既不定正确、也不淘汰错误）。
            # 日志实锤：results/ab_4wrong_0913_open.log:119 →
            #   "verify_answer 异常（降级 unknown）: LLM call failed after 2 attempts:
            #    Request timeout after 180s"
            # 修复思路：异常时先走**不依赖 LLM** 的系统侧命题验算兜底（从 <calc> /
            # [计算] 算式构造命题直接编译），只有它也给不出结论（None / 再抛异常）
            # 才保留原有 unknown 降级。
            try:
                _sys_fallback = self._verify_answer_by_system(reasoning, answer)
            except Exception:  # noqa: BLE001
                _sys_fallback = None
            if _sys_fallback is True:
                # 与上方正常路径的 answer_valid 分支（:2346-2348）返回结构保持一致
                _ok_report = BugReport(verdict="answer_valid", findings=[])
                setattr(_ok_report, "lean_code", locals().get("lean_code", None))
                setattr(_ok_report, "verdict_reason",
                        "llm_exception_but_sys_verify_passed")
                setattr(_ok_report, "sys_verify", True)
                logger.warning(
                    "[LeanBridge] 翻译异常，但系统侧命题验算通过 → 兜底 answer_valid")
                return _ok_report
            if _sys_fallback is False:
                # 与上方正常路径的 proof_invalid 分支（:2333-2345）返回结构保持一致
                _bad_report = BugReport(
                    verdict="proof_invalid",
                    findings=[Finding(
                        location="answer_verify", kind="Critical", severity=5,
                        desc="最终答案与推理中的**计算结果矛盾**：系统已用 Lean "
                             "复算你给出的算式，结果与最终答案不一致。"
                             "请重新核对计算并修正答案。")])
                setattr(_bad_report, "lean_code", locals().get("lean_code", None))
                setattr(_bad_report, "verdict_reason",
                        "llm_exception_and_sys_verify_conflict")
                setattr(_bad_report, "sys_verify", False)
                setattr(_bad_report, "suggestion",
                        "重算该算式，确保最终答案与之逐字一致")
                logger.warning(
                    "[LeanBridge] 翻译异常，但系统侧命题验算判定答案与算式矛盾 → 拒绝")
                return _bad_report
            logger.warning("[LeanBridge] verify_answer 异常（降级 unknown）: %s", exc)
            return _mk("unknown", reason="exception_" + type(exc).__name__,
                       code=locals().get("lean_code") or "")

    # ------------------------------------------------------------------
    # 前置形式化验证：题目 → Lean 定理声明 → 声明模式编译
    # ------------------------------------------------------------------

    def _formalize_to_lean(self, problem: str, domain: str = "",
                           feedback: str = "") -> Optional[dict]:
        """把题目转化为 Lean 定理声明（依赖注入 client），返回 {"formal_spec", "lean_code"}。

        feedback 非空时，把上一次编译错误回传给书生，要求重新理解题目并修正形式化。
        转化失败（LLM 空返回 / JSON 解析失败 / 无 lean_code）返回 None。
        """
        try:
            from tools.lean_local.prompts.lean_pre_verify import (
                LEAN_FORMALIZE_PROBLEM_SYSTEM, LEAN_FORMALIZE_PROBLEM_USER)
        except ImportError:  # 提交包（submit/）路径兜底
            from submit.prompts.lean_pre_verify import (
                LEAN_FORMALIZE_PROBLEM_SYSTEM, LEAN_FORMALIZE_PROBLEM_USER)
        feedback_block = ""
        if feedback:
            feedback_block = ("## 上一次形式化声明编译失败（请重新理解题目并修正）\n"
                              + _truncate_error_output(feedback) + "\n\n")
        messages = [
            {"role": "system", "content": LEAN_FORMALIZE_PROBLEM_SYSTEM},
            {"role": "user", "content": LEAN_FORMALIZE_PROBLEM_USER.format(
                problem=problem, domain=domain or "未知", feedback=feedback_block)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=65536,
                             prefill='{"formal_spec":')
        parsed = _parse_analysis_json(raw)  # 通用 JSON 提取（功能与 analysis 一致）
        if not parsed:
            return None
        lean_code = _strip_code_fence(str(parsed.get("lean_code", "") or ""))
        formal_spec = str(parsed.get("formal_spec", "") or "")
        if not lean_code:
            return None
        return {"formal_spec": formal_spec, "lean_code": lean_code}

    def formalize_problem(self, problem: str, domain: str = "",
                          timeout: Optional[float] = None,
                          feedback: str = "") -> dict:
        """题目前置形式化验证（同步接口，不抛异常）。

        把题目转成 Lean 定理声明（证明 sorry 占位），用声明模式（allow_sorry）编译校验：
        - 声明 well-typed（编译 returncode==0，允许 sorry）→ verdict="ok"
        - 声明类型/语法错误 → verdict="fail"（附编译错误，供修正循环回传）
        - Lean 不可用 / 超时 / 转化失败 → verdict="unknown"（安全降级，不阻断主流程）

        参数:
            problem: 原题文本。
            domain: 题目领域（可选）。
            timeout: 整体 wall-clock 超时（秒），缺省用 self._lean_timeout。
            feedback: 上一次编译错误（非空时回传书生重新理解题目修正）。

        返回:
            {"verdict": "ok"|"fail"|"unknown", "lean_code": str,
             "formal_spec": str, "error": str,
             "gaps": list}  —— gaps 为编译失败抽取的结构化「缺口」
            （缺失定义/引理/模块/类型不匹配），供 SubGoalSolver 直接转化为子目标。
        """
        deadline = time.monotonic() + max(1.0, timeout or self._lean_timeout)
        try:
            # 1) Lean 环境缺失 → 降级 unknown
            if not self.lean_available:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "Lean 环境不可用"}
            if time.monotonic() > deadline:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "前置形式化超时"}

            # 2) 题目 → Lean 定理声明
            converted = self._formalize_to_lean(problem, domain, feedback)
            if not converted:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "题目形式化转化失败"}

            # 3) 声明模式编译（允许 sorry 占位；仅校验命题声明类型正确）
            if time.monotonic() > deadline:
                return {"verdict": "unknown", "lean_code": converted["lean_code"],
                        "formal_spec": converted["formal_spec"], "error": "前置形式化超时"}
            project_dir = self._lean_project_dir
            use_mathlib = self._mathlib_ready()
            code_to_compile = (_prepend_mathlib_import(converted["lean_code"])
                               if use_mathlib else converted["lean_code"])
            if project_dir:
                # 走带 Mathlib 的 Lean 工程目录：证明题真正能用上 Mathlib tactic
                # （norm_num / ring / omega / linarith …）。仅当 Mathlib 已编译就绪
                # 才 import Mathlib，否则退回核心 Lean，避免误判。
                lean_file = "preverify_%d_%d.lean" % (
                    os.getpid(), int(time.monotonic() * 1e6))
                comp = self._compile(code_to_compile, project_dir,
                                     lean_filename=lean_file, allow_sorry=True)
                _trash_lean_file(project_dir, lean_file)
            else:
                with tempfile.TemporaryDirectory(prefix="lean_preverify_") as work_dir:
                    comp = _compile_lean(
                        code_to_compile, work_dir,
                        lean_executable=self._lean_executable,
                        timeout=min(self._lean_timeout,
                                    max(1.0, deadline - time.monotonic())),
                        allow_sorry=True,
                    )
            if comp.get("ok"):
                # 声明 well-typed（允许 sorry）→ 理解正确，无缺口
                return {"verdict": "ok", "lean_code": converted["lean_code"],
                        "formal_spec": converted["formal_spec"], "error": "",
                        "gaps": []}
            # 编译失败：抽取「缺口」供子目标构建（看缺哪些）
            gaps = _analyze_formal_gaps(comp.get("error", ""))
            return {"verdict": "fail", "lean_code": converted["lean_code"],
                    "formal_spec": converted["formal_spec"],
                    "error": comp.get("error", "声明编译失败"),
                    "gaps": gaps}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LeanBridge] formalize_problem 异常（降级 unknown）: %s", exc)
            return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                    "error": str(exc)[:200]}

    # ------------------------------------------------------------------
    # 骨架(sketch) 形式化 + Lean 语法审核（#28）
    # ------------------------------------------------------------------
    def _formalize_sketch_to_lean(self, sketch_nl: str, problem: str = "",
                                  domain: str = "", feedback: str = "") -> Optional[dict]:
        """把 AI 生成的题目骨架(sketch / Proof Body Outline)形式化为 Lean 骨架声明。

        与 ``_formalize_to_lean``（形式化题目命题）不同，这里形式化的是**解题骨架**：
        把骨架里每个子目标转成 ``theorem subgoal_i : <stmt> := by sorry`` 的声明，
        外加最终目标 ``theorem main_goal : <final> := by sorry``。编译这些声明即可用
        Lean 校验「骨架是否 well-typed」——子目标命题本身类型是否正确、彼此是否一致，
        这正是老师要求的「骨架严谨性需 Lean 审核」。

        feedback 非空时回传上一次编译错误，要求重新生成骨架。
        """
        try:
            from tools.lean_local.prompts.lean_pre_verify import (
                LEAN_FORMALIZE_SKETCH_SYSTEM, LEAN_FORMALIZE_SKETCH_USER)
        except ImportError:
            from submit.prompts.lean_pre_verify import (
                LEAN_FORMALIZE_SKETCH_SYSTEM, LEAN_FORMALIZE_SKETCH_USER)
        feedback_block = ""
        if feedback:
            feedback_block = ("## 上一次骨架 Lean 声明编译失败（请修正骨架的形式化）\n"
                              + _truncate_error_output(feedback) + "\n\n")
        messages = [
            {"role": "system", "content": LEAN_FORMALIZE_SKETCH_SYSTEM},
            {"role": "user", "content": LEAN_FORMALIZE_SKETCH_USER.format(
                problem=problem, domain=domain or "未知",
                sketch=sketch_nl, feedback=feedback_block)},
        ]
        raw = self._llm_call(messages, temperature=0.0, max_tokens=65536,
                             prefill='{"formal_spec":')
        parsed = _parse_analysis_json(raw)
        if not parsed:
            return None
        lean_code = _strip_code_fence(str(parsed.get("lean_code", "") or ""))
        formal_spec = str(parsed.get("formal_spec", "") or parsed.get("outline", ""))
        if not lean_code:
            return None
        return {"formal_spec": formal_spec, "lean_code": lean_code}

    def audit_sketch(self, sketch_nl: str, problem: str = "", domain: str = "",
                     timeout: Optional[float] = None,
                     feedback: str = "") -> dict:
        """骨架(sketch) Lean 语法/类型审核（#28）。

        把 AI 生成的骨架形式化为 Lean 骨架声明（子目标 theorem + sorry 占位），
        用声明模式（allow_sorry）编译，仅校验**命题声明是否 well-typed**：
        - 全部声明 well-typed → verdict="ok"（骨架严谨，可进入求解）
        - 某子目标声明类型/语法错误 → verdict="fail"，附结构化 ``gaps``
          （缺失定义/引理/模块/类型不匹配），直接告诉 AI「骨架哪一步不对」
        - Lean 不可用 / 超时 / 转化失败 → verdict="unknown"（安全降级）

        参数:
            sketch_nl: 书生生成的骨架/Proof Body Outline（自然语言或含 Lean 片段）。
            problem/domain: 原题与领域（注入形式化提示，提升骨架形式化质量）。
            timeout: 整体 wall-clock 超时（秒）。
            feedback: 上一次编译错误（非空时回传重新生成骨架）。

        返回:
            {"verdict": "ok"|"fail"|"unknown", "lean_code": str,
             "formal_spec": str, "error": str, "gaps": list}
        """
        deadline = time.monotonic() + max(1.0, timeout or self._lean_timeout)
        try:
            if not self.lean_available:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "Lean 环境不可用", "gaps": []}
            if time.monotonic() > deadline:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "骨架审核超时", "gaps": []}

            converted = self._formalize_sketch_to_lean(sketch_nl, problem, domain, feedback)
            if not converted:
                return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                        "error": "骨架形式化转化失败", "gaps": []}

            if time.monotonic() > deadline:
                return {"verdict": "unknown", "lean_code": converted["lean_code"],
                        "formal_spec": converted["formal_spec"],
                        "error": "骨架审核超时", "gaps": []}

            project_dir = self._lean_project_dir
            use_mathlib = self._mathlib_ready()
            code_to_compile = (_prepend_mathlib_import(converted["lean_code"])
                               if use_mathlib else converted["lean_code"])
            if project_dir:
                lean_file = "sketch_%d_%d.lean" % (
                    os.getpid(), int(time.monotonic() * 1e6))
                comp = self._compile(code_to_compile, project_dir,
                                     lean_filename=lean_file, allow_sorry=True)
                _trash_lean_file(project_dir, lean_file)
            else:
                with tempfile.TemporaryDirectory(prefix="lean_sketch_") as work_dir:
                    comp = _compile_lean(
                        code_to_compile, work_dir,
                        lean_executable=self._lean_executable,
                        timeout=min(self._lean_timeout,
                                    max(1.0, deadline - time.monotonic())),
                        allow_sorry=True,
                    )
            if comp.get("ok"):
                return {"verdict": "ok", "lean_code": converted["lean_code"],
                        "formal_spec": converted["formal_spec"], "error": "",
                        "gaps": []}
            gaps = _analyze_formal_gaps(comp.get("error", ""))
            return {"verdict": "fail", "lean_code": converted["lean_code"],
                    "formal_spec": converted["formal_spec"],
                    "error": comp.get("error", "骨架声明编译失败"),
                    "gaps": gaps}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[LeanBridge] audit_sketch 异常（降级 unknown）: %s", exc)
            return {"verdict": "unknown", "lean_code": "", "formal_spec": "",
                    "error": str(exc)[:200], "gaps": []}


