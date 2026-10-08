"""
子目标求解智能体（SubGoalSolverAgent）
===================================

将数学问题分解为有序子目标，逐步求解后合并结论。

与 SolverAgent 的关系：
- SolverAgent：一次性生成多个候选解答（含蓝图分解在内的一步式求解）
- SubGoalSolverAgent：先规划子目标树，再逐步求解每个子目标，最后合并

流程：
  1. 子目标规划 (plan)  →  结构化 JSON 子目标列表
  2. 逐步求解 (step)    →  按依赖顺序依次求解每个子目标
  3. 结论合并 (merge)   →  组装最终答案并输出 Candidate
"""

# 2026-10-01 开关注册制（审查 A 级第 2 条）：开关统一走 switch_registry，
# 不再裸读 os.environ —— 既保持 env 优先级（行为不变），又能被 diag/报告还原。
try:
    from agent.switch_registry import (
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)
except ImportError:
    from switch_registry import (
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)

# 2026-10-02 中间结果存储层（老师：「每个中间结果都要存」）：子目标结果**即时落盘**。
# 只加不改：写盘失败静默（append_ctx 永不抛异常），不影响求解与合并。
# ⚠ 2026-10-08 批1-B增：`_artifact_append` 的直接消费方已迁到
#   `agent/sub_goal_solver__loop.py`（函数内 `from .sub_goal_solver import
#   _artifact_append` 惰性引用）⇒ **本导入须保留**（单一来源，勿按"未使用"清理）。
try:
    from agent.artifact_store import append_ctx as _artifact_append
except ImportError:
    from artifact_store import append_ctx as _artifact_append

import json
import logging
import re
import time
# ★ 2026-09-30：`_sample_step_consensus` 的返回类型标注用了 `Optional`，
#   而本模块此前**从未导入过它** ⇒ `test_no_undefined_names_in_main_flow`
#   静态检查报 `undefined name 'Optional'`（该类型标注在函数签名里，
#   运行时求值 → 跑批会整轮 NameError）。这正是那条静态检查存在的意义。
from typing import Optional

# 2026-10-07：候选入池门槛 v2 开关改为自 base 引用（去重，单一来源）。
# ⚠ 2026-10-08 批1第三增量：`_pool_gate_v2_on` 的直接消费方已迁到
#   `agent/sub_goal_solver__pool.py::apply_pool_gate`（函数内
#   `from .sub_goal_solver import _pool_gate_v2_on` 惰性引用）⇒ **本导入须保留**
#   （单一来源 = 本模块，勿按"未使用"清理 —— 与 `_artifact_append` 同口径）。
from .base import (
    BaseAgent, TaskContext, Candidate, next_candidate_id, _pool_gate_v2_on)

# 2026-10-08 批1：run 的两段已抽到同包模块（逐字搬）。
from .sub_goal_solver__stage import wire_subgoal_stage_budget  # noqa: F401
from .sub_goal_solver__exhaust import append_exhaust_subgoal  # noqa: F401
from .sub_goal_solver__plan import (  # noqa: F401
    strip_and_mask_plan, finalize_plan_stats, build_plan_summary)
from .sub_goal_solver__loop import solve_subgoals  # noqa: F401
from .sub_goal_solver__pool import apply_pool_gate  # noqa: F401
from . import sub_goal_solver__lean as _sgs_lean  # noqa: F401
from . import sub_goal_solver__review as _sgs_review  # noqa: F401

try:
    from prompts.sub_goal import (
        SUBGOAL_PLAN_SYSTEM,
        SUBGOAL_PLAN_USER_TEMPLATE,
        SUBGOAL_STEP_SYSTEM,
        SUBGOAL_STEP_USER_TEMPLATE,
        SUBGOAL_CONCLUSION_CONTRACT,
        SUBGOAL_MERGE_SYSTEM,
        SUBGOAL_MERGE_USER_TEMPLATE,
        SUBGOAL_CROSSCHECK_SYSTEM,
        SUBGOAL_CROSSCHECK_USER_TEMPLATE,
    )
    from prompts.policy import get_domain_hint
    from utils.extract import extract_final_answer, smart_fallback_answer
    from utils.prefill import prefill_messages, stitch
except ImportError:
    from submit.prompts.sub_goal import (
        SUBGOAL_PLAN_SYSTEM,
        SUBGOAL_PLAN_USER_TEMPLATE,
        SUBGOAL_STEP_SYSTEM,
        SUBGOAL_STEP_USER_TEMPLATE,
        SUBGOAL_CONCLUSION_CONTRACT,
        SUBGOAL_MERGE_SYSTEM,
        SUBGOAL_MERGE_USER_TEMPLATE,
        SUBGOAL_CROSSCHECK_SYSTEM,
        SUBGOAL_CROSSCHECK_USER_TEMPLATE,
    )
    from submit.prompts.policy import get_domain_hint
    from submit.utils.extract import extract_final_answer, smart_fallback_answer
    from submit.utils.prefill import prefill_messages, stitch

# 2026-10-01：`<calc>` 计算工具板块（含子目标链的 <calc> 纪律/回填/裸算打回）
# 已按用户决策整体删除；纯数学求值内核迁至 `utils/math_eval.py`。

logger = logging.getLogger("MathPilot")


# ★★ 2026-09-17（P-20）：规划结论**不得当作已证实事实**注入 merge。
# 实测 10 题中 **5 题的蓝图结论值即与 gold 不符**：
#   025「故最小值为 4」(gold 506) / 013「prove minimal d=50」(gold 48) /
#   070「1/2 is achievable」(gold 5/8) / 002「T=1 is sufficient」(gold 1/2) /
#   086「次数 8」(gold 16)。
# 而 merge 提示词同时注入【蓝图规划结论】与【合并策略】(后者即 blueprint_merge)，
# 二者都内嵌该数值 ⇒ **等于指令模型输出该值**，把蓝图的错误结论锚进最终答案。
# 处理分两层：
#   ① 本函数剥掉最露骨的「答案形态」（\boxed / 「最终答案: …」）；
#   ② 模板侧声明二者均为「待验证假设」（见 prompts/sub_goal.py 的合并纪律段）。
# ⚠ 只收「**明确的形态标记**」，不收自然语句：
#   · `\boxed{…}` 与「最终答案: …」是**答案形态标记**，必剥；
#   · 「答案为 X」属**自然语句**（如规划结论「证明最终答案为 42」），
#     **不得剥** —— 首版纳入该模式导致既有测试失败（合法结论被削掉）。
_ANSWER_FORM_RES = (
    re.compile(r"\\boxed\s*\{[^{}]*\}"),
    re.compile(r"最终答案\s*[:：][^\n]*"),
    re.compile(r"the\s+answer\s+is\b[^\n]{0,80}", re.IGNORECASE),
)


def _strip_answer_forms(text: str) -> str:
    """剥掉文本中的「结论形态」片段，只留策略 / 规划描述（P-20，2026-09-17）。

    **只删最露骨的形态，不删数值本身** —— 策略里出现 `d=50` 属正常规划描述，
    靠模板侧的「待验证假设」声明约束；正则误删会丢失策略信息，故不扩大到数值。
    """
    t = str(text or "")
    if not t:
        return ""
    for pat in _ANSWER_FORM_RES:
        t = pat.sub("", t)
    t = re.sub(r"[（(]\s*[)）]", "", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


# ★★ 2026-09-22（用户口径）：**蓝图不得锁死答案 —— 蓝图只构建数据与信息**。
#   P-20（09-17）只剥"答案形态标记"（`\boxed{}` /「最终答案:」），
#   **故意保留自然语句里的数值**。但实测 32 题自动检错显示：
#   真正把蓝图错值锚进终答的是**自然语句断言**（K11 命中 18/32 = 56%），例如
#     · "Combine n3's value with n4's proof to output single value 2024."
#     · "证明最小值为 4030，故答案为 4030"
#   —— 这些句子会被原样注入下游 merge/求解提示词，等于**指令模型输出该值**。
#
#   本函数与 P-20 的分工：
#     · P-20  `_strip_answer_forms`：删「答案形态标记」（整段形态，不可改）；
#     · 本函数：**不删句**，只把**被断言的数值**换成占位符 ——
#       句子的结构/策略信息完整保留，被剥离的只有"未经证实的那个数"。
#   为什么不像 P-20 首版那样删整句：09-17 实测删「答案为 X」会误杀合法结论
#   （既有测试失败）。只换数不删句，则策略可读性不受损。
_ASSERTED_VALUE_RES = (
    # 中文断言：最小/最大/最终/答案/结果/取值 … + 为/是/等于 + 数值
    re.compile(r"(?:最小|最大|最终|答案|结果|取值|次数|个数|总数为?)"
               r"\s*值?\s*(?:为|是|等于|即为|＝|=)\s*[-+]?\d[\d,]*(?:\.\d+)?"),
    # 英文断言 A：output(s) … value X / minimum is X / equals X
    re.compile(r"(?:outputs?|equals|value\s+is|"
               r"minimum\s+\w*\s*is|maximum\s+\w*\s*is)[^\n]{0,20}?"
               r"[-+]?\b\d[\d,]*(?:\.\d+)?",
               re.IGNORECASE),
    # 英文断言 D：N is achievable and maximal（数量词在前，实测 041 原句）
    re.compile(r"[-+]?\b\d[\d,]*(?:\.\d+)?\s+is\s+(?:achievable\s+and\s+maximal|"
               r"maximal|minimal|optimal)",
               re.IGNORECASE),
    # 英文断言 B：X of N（实测原句 "derive the minimal query count of 324"）
    re.compile(r"(?:count|value|number|answer|total)\s+of\s*[-+]?\b\d[\d,]*(?:\.\d+)?",
               re.IGNORECASE),
    # 英文断言 C：conclude(s) … N
    re.compile(r"concludes?[^\n]{0,24}?[-+]?\b\d[\d,]*(?:\.\d+)?", re.IGNORECASE),
)
_MASK_LOCKED = "[待求解值：由子目标结果现场确定]"


def _mask_asserted_values(text: str) -> tuple:
    """把策略文本里**被断言的数值**换成占位符（不删句）。返回 (新文本, 替换处数)。

    只用于 `merge_strategy` / `problem_analysis` 这类**策略文本**；
    节点 `statement` 不在此处改（由提示词纪律约束，代码不越权改写题目陈述）。
    """
    t = str(text or "")
    if not t:
        return "", 0
    n = 0
    for pat in _ASSERTED_VALUE_RES:
        t, k = pat.subn(_MASK_LOCKED, t)
        n += k
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip(), n


def _conclusion_contract_on() -> bool:
    """子目标**结论契约**开关（`subgoal_conclusion_contract`，默认 True）。

    打开时：step 提示词追加「结论契约」块（prompts/sub_goal.py::
    SUBGOAL_CONCLUSION_CONTRACT），强制每步产出 `本步结论: 值/等式/判定`
    三形态之一 + `本步依据` 行 + 验算段；`_call_step` 解析并把结构化结论、
    推导长度、「是否只有结论」标记写进 trace，供客观判定（B）与
    主求解警示（C）消费。=0 回退旧行为（只给自由文本结论）。
    """
    try:
        return bool(_sw_bool("subgoal_conclusion_contract"))
    except Exception:  # noqa: BLE001  未注册/读取异常 ⇒ 保持修好后的行为
        return True


def _objective_judge_on() -> bool:
    """子目标结论**客观判定**开关（`subgoal_objective_judge`，默认 True）。

    打开时：每个子目标的结论都走一次 0-LLM 客观判定（SymPy 判等式真伪 /
    多候选符号多数 / 判定真假的留痕），并把 `objective_verdict` /
    `objective_reason` / `candidates_verified_index` 写进 trace。
    实测背景：`n_judged = 0/73`（一个都没判定过）——原判定**只在多 agent
    路径**且要求全部候选可解析为数学表达式，结论是自然语言时静默返回 -1。
    =0 回退旧行为（只在多 agent 路径判定、判不出不给原因）。
    """
    try:
        return bool(_sw_bool("subgoal_objective_judge"))
    except Exception:  # noqa: BLE001
        return True


def _k11_mask_on() -> bool:
    """K11 注入点掩码开关（`k11_mask_statement`，默认 True）。读取失败按 True 处理。

    ★ 用 try/except 包裹是刻意的：`switch_registry.get_bool()` 在字段未注册时
    会 `KeyError`，且**不接受默认参数**；而本开关由另一路工人并行登记
    （`user_agent.py` + `agent/switch_registry.py` + `agent/param_usage.py`）。
    本函数必须在**注册完成前后都能跑**，且默认行为一致（都 = 守卫生效）。
    """
    try:
        from .switch_registry import get_bool as _swb
        return bool(_swb("k11_mask_statement"))
    except Exception:  # noqa: BLE001  开关未注册/读取异常 ⇒ 保持守卫生效（研究期安全侧）
        return True


def _itemwise_plan_on() -> bool:
    """子目标**规划**阶段的客观题逐项策略开关（`objective_itemwise_plan`，默认 True）。

    ★ 2026-10-07（fix-tail-gaps）：原实现为裸读 `OBJECTIVE_ITEMWISE_PLAN` 并**取反**
    （`os.environ.get(..., "1") == "0"` 才回退 LLM 规划）。改走注册制后语义为
    `not _sw_bool("objective_itemwise_plan")` —— 未设/`"1"` ⇒ 启用逐项规划（同旧默认），
    `"0"` ⇒ 关（同旧行为）。三态与原 `== "0"` 逐条一致；仅 `""`/`"false"` 等非标准值
    由 registry 统一口径判为「关」，属已文档化的修正。=0 一键回退到 LLM 规划。
    """
    try:
        return bool(_sw_bool("objective_itemwise_plan"))
    except Exception:  # noqa: BLE001  未注册/读取异常 ⇒ 保持修好后的行为（默认启用）
        return True


def _check_protocol_guard_on() -> bool:
    """`<check>` **协议守卫**开关（`check_protocol_guard`，默认 True）。

    针对问题 2.9：实测题 000 大量子目标把**中文句子**塞进 `<check>`（如
    `<check>图 G 是弱连通的</check>`）⇒ 客观判定**一条都出不来**
    （`is_parseable=False`，`n_judged = 0/73` 的直接原因之一）。打开后：
      ① 判定"该 `<check>` 内容是否为**可核验对象**"（纯数学等式）；
      ② 违反 ⇒ **留痕**（trace + sg 字段）并**触发一次定向重问**；
      ③ 重问仍不合规 ⇒ 保留并留痕（绝不静默落 undecided）。
    =0 回退旧行为（只静默跳过、不留痕、不重问）做 A/B。
    """
    try:
        return bool(_sw_bool("check_protocol_guard"))
    except Exception:  # noqa: BLE001  未注册/读取异常 ⇒ 保持修好后的行为
        return True


# ---------------------------------------------------------------------------
# `<check>` 协议校验（2026-10-07，问题 2.9）
# ---------------------------------------------------------------------------
# 协议（`prompts/sub_goal.py::SUBGOAL_STEP_SYSTEM` 第 6 条）要求 `<check>` **只装
# 一个纯数学等式**：仅含数字/变量/运算符（`+ - * / ^ ( )`），恰含一个 `=`，无中文。
# 违反协议（装中文句子/文字/非等式）时**不是"没给出断言"，而是"给了不可核验的东西"**
# ⇒ 必须与"未给断言"区分：前者留痕 + 定向重问，后者正常走 undecided。
_CHECK_INNER_RE = re.compile(r"<check>(.*?)</check>", re.DOTALL)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# ⚠ 2026-10-07 实测修正：初版字符类漏了 `|` ⇒ 把 `|D_8| = 8`（二面体群阶，实测出现
#   8 次）误判为"违反协议"（假阳）。这里补上数学常用符号（`|` 绝对值/阶、`,` 元组、
#   `{}[]` 集合/区间、`!` 阶乘、`'` 导数、`%`、`~`、`\` LaTeX 命令、`<>`）。仍要求
#   "恰含一个 `=`"且不含中文 ⇒ 只拦真正的破坏形态（`<check>图 G 是弱连通的</check>`）。
_CHECK_BODY_ALLOWED_RE = re.compile(r"^[0-9a-zA-Z_+\-*/^().=\s|,{}\[\]<>!%'~\\]+$")


def _is_verifiable_check_body(body: str) -> bool:
    """`<check>` 的 inner 是否是**可核验对象**（一个纯数学等式）。

    ⚠ 本函数只判**语法形态**（"是不是一个纯数学等式"），**不判语义可验性**：
    像 `x = 5` / `s = 265/247` 这类"赋值式"语法上合规（协议第 6 条虽提示不要用，
    但实测模型大量使用），语义"不可验"由 `_sympy_judge` 返回 unknown 放行处理
    —— 若在此也判违规，会对大量正常步骤触发无谓重问（成本风险 > 收益）。
    故本守卫专注拦截**协议真正的破坏形态**：`<check>` 里装中文/文字/非等式
    （实测 `'图 G 是弱连通的'` 就是这一类）。
    """
    b = " ".join(str(body or "").split())
    if not b:
        return False
    if _CJK_RE.search(b):          # 含中文 ⇒ 句子，不是可核验等式
        return False
    if b.count("=") != 1:          # 必须恰含一个 =
        return False
    L, R = (p.strip() for p in b.split("="))
    if not L or not R:             # 两侧都要有内容
        return False
    if not _CHECK_BODY_ALLOWED_RE.match(b):   # 只允许数学字符
        return False
    return True


def _check_protocol_violations(text) -> list:
    """返回**违反 `<check>` 协议**的 inner 文本列表（空 = 无 `<check>` 或全部合规）。

    与 `_extract_check_asserts` 的区别：后者"宁缺毋滥"——不合规的 `<check>`
    **静默 skip**（于是违反协议不可见）；本函数把**同一批 skip 掉的**显式收出来，
    供留痕与定向重问。
    """
    if not text or "<check>" not in str(text):
        return []
    out = []
    for m in _CHECK_INNER_RE.finditer(str(text)):
        body = m.group(1).strip()
        if not _is_verifiable_check_body(body):
            out.append(body or "(空)")
    # 去重保序
    seen, uniq = set(), []
    for b in out:
        if b not in seen:
            seen.add(b)
            uniq.append(b)
    return uniq[:6]


# ★ 2026-09-17（P-9）：穷尽性检查的**固定段落**清单。
# ⚠ 与 `orchestrator._parse_exhaust_result` 的口径必须一致 ——
#   由 tests/test_exhaust_sections_consistency.py 断言，防止两处漂移。
_EXHAUST_SECTIONS = ("解族清单", "逐族判定", "前序结论复核")
_EXHAUST_VERDICT_RE = re.compile(r"EXHAUSTIVE\s*[:：]\s*(yes|no)", re.IGNORECASE)


def _exhaust_missing_sections(text: str) -> list:
    """返回「解族穷尽性检查」输出中缺失的段落名（空列表 = 齐备）。"""
    t = str(text or "")
    miss = [n for n in _EXHAUST_SECTIONS if n not in t]
    if not _EXHAUST_VERDICT_RE.search(t):
        miss.append("EXHAUSTIVE")
    return miss

# 单选信号（2026-09-13）：题干出现这些**明确指向唯一答案**的措辞时，
# 选择题按"单选"汇总（取唯一/最优），否则按多选（全取判真项）。
# ⚠ 不可用“下列正确的是”判断单选——087/093/094 都是该措辞却为**多选**，
#   096 也是该措辞却为**单选**；只有下列措辞才可靠。
_SINGLE_CHOICE_RE = re.compile(
    r"哪一项|哪一种|哪一类|哪一个|最为?合适|最恰当|最符合|最适合"
    r"|分别是?|定义是|通常采用|应采用|应选择|最好采用")



class SubGoalSolverAgent(BaseAgent):
    """子目标逐步求解智能体"""

    name = "SubGoalSolver"

    # ---------- JSON 提取 ----------
    @staticmethod
    def _extract_json(text: str) -> dict | None:
        r"""从 LLM 输出中提取 JSON 对象。

        v2.6 修复：原实现对最外层一对花括号到另一对花括号做贪婪匹配，会被 LaTeX /
        中文解释 / 嵌套 JSON 干扰（LaTeX 里的左花括号、右花括号、解释文字里的成对
        花括号都会被吃进 JSON 段导致解析失败）。改为**平衡括号匹配**：从每个左
        花括号出发，用栈找匹配的右花括号，并正确处理字符串内花括号与反斜杠转义。
        """
        if not text:
            return None
        # 1) 优先 ```json ... ``` 代码块
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass  # 代码块不合法，回退到平衡括号匹配

        # 2) 平衡括号匹配：扫描每个 {，用深度栈找到对应的 }。
        #    关键：正确处理字符串字面量（跳过字符串内的 { 和 }）
        def _try_parse(candidate: str):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # 尝试修复常见错误：尾随逗号
                try:
                    fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    return None

        for i, c in enumerate(text):
            if c != '{':
                continue
            depth, j, in_str, esc = 1, i + 1, False, False
            while j < len(text):
                ch = text[j]
                if esc:
                    esc = False
                elif in_str and ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = not in_str
                elif not in_str:
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            parsed = _try_parse(text[i:j + 1])
                            if parsed is not None:
                                return parsed
                            break  # 该 { 不是合法 JSON 起点，继续找下一个
                j += 1
        return None

    # ---------- P2 子目标类型路由（2026-09-09 老师：计算/推理类型化）----------
    # calc_kind: "terminal"=整体计算型子目标（期望输出=单个数值/表达式 → 专用
    # 模板只翻译表达式，工具回填即结论，模型零计算面）；"inline"=推理/证明型
    # （步骤级 <calc> 截断）。规则启发先行，宁 inline 勿误 terminal（防把推理
    # 子目标截成表达式翻译）。字段总是打标进 trace（0 成本可观测分布）；
    # ★ 2026-10-04 修注释（D32）：原文写「专用模板/校验由 config.subgoal_calc_router
    #   控制（默认关待 A/B）」—— 该配置项**已随 `<calc>` 计算工具板块一并删除**
    #   （见 user_agent.py 的删除留痕），`calc_kind` 现为**纯观测字段**（只进 trace/diag，
    #   不驱动任何分支）。原注释会误导后人以为它仍在生效。
    _TERM_ACTION_KW = ("代入", "求和", "化简", "展开", "求值", "积分",
                       "乘积", "计算", "算得")

    @staticmethod
    def _calc_kind_of(sg_type: str, title: str, expected_output: str) -> str:
        blob = f"{title} {expected_output}".strip()
        if sg_type == "compute":
            if any(k in blob for k in SubGoalSolverAgent._TERM_ACTION_KW):
                return "terminal"
            eo = (expected_output or "").strip()
            # expected_output 为短数值/表达式形态（数字/负号/等号/左括号开头）
            if eo and len(eo) <= 60 and (eo[0].isdigit() or eo[0] in "-=("):
                return "terminal"
        return "inline"

    @staticmethod
    def _parse_subgoal_plan(raw: dict, max_subgoals: int = 6) -> list[dict] | None:
        """验证并规范化子目标规划，返回按拓扑序排列的子目标列表。

        v2.6 宽容性增强：LLM 实际输出常省略字段（如用 step/name/task 代替
        id/title/description）、或把列表字段命名为 plan/steps/subproblems/tasks
        等。本方法兼容多种字段名，单个条目缺失字段时也能构造出可用条目，
        而不再直接放弃。
        """
        # 1) 宽容多种列表字段名
        subgoals = None
        for key in ("subgoals", "subproblems", "sub_problems",
                    "plan", "steps", "tasks", "items"):
            v = raw.get(key)
            if isinstance(v, list) and v:
                subgoals = v
                break
        if subgoals is None:
            # 兜底：找任何非空 list[dict] 字段
            for v in raw.values():
                if (isinstance(v, list) and v
                        and all(isinstance(x, dict) for x in v)):
                    subgoals = v
                    break
        if subgoals is None:
            return None
        # 2026-09-03 老师：子目标是**简化求解**的，不是把题目拆得更复杂。
        # 原上限 10（deep 实测 8 步 × 110s = 882s 吃掉 73% 时间）。
        # 改为可配置 max_subgoals（默认 6）：少而精，每步都是真正必要的
        # 简化步骤；省下的时间留给验证器与 Lean 闸门（老师核心诉求）。
        # 注意：这是"规划时少拆几步"，**不是执行到一半强制中断**——
        # 已规划的子目标一定会跑完（老师："强制结束就等于错误"）。
        # 2026-09-03 审核修复：原实现在 @staticmethod 里写 `self.config` /
        # `self.record(ctx, ...)` → 每次调用必抛 NameError（本方法无 self/ctx），
        # 且该分支无条件执行 = 子目标规划 100% 崩溃。改为**上限走参数**，
        # 调用方从 config 读取后传入，静态方法保持无状态（测试可直接调用）。
        # 2026-09-15：改用与 blueprint 路径**共用**的 cap_subgoals_keep_last。
        # 语义统一（None→默认 / <=0→不截断），且**保留收尾子目标**——
        # 原 `subgoals[:_max_sg]` 盲截拓扑序尾部，会丢掉"合并结论/得出最终
        # 答案"那一步（prompts/sub_goal.py 明写最后一个是合并结论），
        # 导致前面所有子目标白解。两条路径必须同源，故抽成公共函数。
        from .blueprint_planner import cap_subgoals_keep_last
        _n_before = len(subgoals)
        subgoals, _dropped_sg = cap_subgoals_keep_last(subgoals, max_subgoals)
        if _dropped_sg:
            logger.info("SubGoal plan: 子目标 %d 个，截断 %d 个"
                        "（保留收尾子目标；简化求解，非中断）",
                        _n_before, len(_dropped_sg))

        valid_types = {"compute", "prove", "derive", "verify"}
        seen_ids = set()
        parsed = []
        for sg in subgoals:
            # 宽容 id 字段名：id / step / index / number
            raw_id = sg.get("id", sg.get("step", sg.get("index",
                          sg.get("number", len(parsed) + 1))))
            try:
                sg_id = int(raw_id)
            except (TypeError, ValueError):
                sg_id = len(parsed) + 1
            if sg_id in seen_ids:
                continue
            seen_ids.add(sg_id)

            # 宽容 title/description/expected_output/depends_on/type 字段名
            title = str(sg.get("title",
                       sg.get("name",
                       sg.get("step_name",
                       sg.get("task_name", f"子目标{sg_id}")))))
            description = str(sg.get("description",
                            sg.get("task",
                            sg.get("content",
                            sg.get("detail", "")))))
            sg_type = sg.get("type", sg.get("kind", "compute"))
            if sg_type not in valid_types:
                sg_type = "compute"
            deps_raw = sg.get("depends_on",
                       sg.get("deps",
                       sg.get("dependencies", [])))
            if not isinstance(deps_raw, list):
                deps_raw = []
            expected_output = str(sg.get("expected_output",
                                   sg.get("output",
                                   sg.get("expected",
                                   sg.get("result", ""))))).strip()
            # ★ 2026-09-23：把"填了但等于没填"的空话也判为缺失。
            #   实测 96% 为空；提示词虽已要求该字段，但模型常写"一个结果"这类空话
            #   ⇒ 只判 `== ""` 会低估缺口。此标记随 subgoal_trace 一起导出，
            #   供 orchestrator 的 `subgoal_delivery` 统计（"做成了没"的判据）。
            _eo_filler = ("", "结果", "一个结果", "期望的输出形式", "数值/表达式/证明",
                          "数值", "表达式", "无", "n/a", "na", "待定", "答案")
            eo_missing = (expected_output in _eo_filler) or (len(expected_output) < 6)
            parsed.append({
                "id": sg_id,
                "title": title,
                "description": description,
                "type": sg_type,
                "depends_on": [d for d in deps_raw
                               if isinstance(d, int) and d in seen_ids],
                "expected_output": expected_output,
                "expected_output_missing": bool(eo_missing),
                # P2（2026-09-09）：计算/推理类型化标签（宁 inline 勿误 terminal）
                "calc_kind": SubGoalSolverAgent._calc_kind_of(
                    sg_type, title, expected_output),
                "result": "",
            })
        return parsed if parsed else None

    # ---------- 主流程 ----------
    def run(self, ctx: TaskContext) -> TaskContext:
        """执行子目标规划 → 逐步求解 → 结论合并 全流程，结果追加到 ctx.candidates"""
        # 预算闸门：连规划所需的 1 次 LLM 调用都负担不起时，整体跳过、不追加候选
        # 2026-09-06：升级 gen_time_up（生成侧软截止，未设时回退 is_time_critical）
        if ctx.gen_time_up():
            self.record(ctx, "subgoal", "预算耗尽，跳过子目标求解")
            return ctx

        # 2026-09-04 子目标阶段预算（装配细节、依据与取舍见
        # agent/sub_goal_solver__stage.py::wire_subgoal_stage_budget；
        # 2026-10-08 批1：逐字搬，调用点改一行委托）。
        wire_subgoal_stage_budget(self, ctx)

        def _stage_left() -> float:
            """子目标阶段剩余秒数（0 = 未启用阶段预算，返回 inf）"""
            if not ctx._subgoal_stage_end:
                return float("inf")
            return ctx._subgoal_stage_end - time.time()

        # 阶段一：子目标规划
        plan_data = self._plan_subgoals(ctx)
        if plan_data is None:
            self.record(ctx, "subgoal", "子目标规划失败，回退到标准求解")
            return ctx

        subgoals = plan_data.get("subgoals", [])
        # ★ 2026-09-17（Z8）：规划结果为空 ⇒ 后续的逐步求解与 merge 都无从下手，
        #   原实现仍会跑一遍 merge/建候选（纯空转）。此处直接早退。
        if not subgoals:
            self.record(ctx, "subgoal", "子目标规划为空 → 跳过求解与合并（Z8 2026-09-17）")
            return ctx
        merge_strategy, problem_analysis = strip_and_mask_plan(self, ctx, plan_data)
        # ---- 2026-09-14 穷尽性搜索机制（B0 遗留课题）----
        # 2026-10-08 批1：本段逐字搬到 agent/sub_goal_solver__exhaust.py::
        # append_exhaust_subgoal，调用点改一行委托（merge_strategy 由之返回）。
        merge_strategy = append_exhaust_subgoal(self, ctx, subgoals, merge_strategy)

        finalize_plan_stats(self, ctx, subgoals, merge_strategy)

        # 阶段二：逐步求解每个子目标
        subgoal_plan_summary = build_plan_summary(self, ctx, subgoals, merge_strategy)
        results_map = {}  # subgoal_id → result_text
        _ctx_inject_chars = solve_subgoals(
            self, ctx, subgoals, subgoal_plan_summary, results_map)

        # 阶段三：结论合并
        # 2026-09-04 保护：预算已尽且一个子目标都没解出（典型：或chestrator 后续
        # 调用 run() 时预算早已耗尽）→ 空 merge 只产垃圾，直接 return 不追加候选。
        if not results_map and _stage_left() <= 0:
            self.record(ctx, "subgoal",
                        "子目标阶段预算已尽且无已解子目标，跳过空 merge")
            return ctx
        if ctx.gen_time_up():
            # 生成侧软截止/全局逼近 deadline（2026-09-06 升级 gen_time_up；
            # 正常 750s stage_budget 结束于 ~760s < gen_deadline，merge 仍真跑，
            # 只有跑超到 gen_deadline 才兜底）→ 连 1 次 merge LLM 调用都挤不出
            # 时，用最后一个子目标结果兜底（不空手返回）。
            self.record(ctx, "subgoal", "全局预算不足，跳过合并阶段")
            # 使用最后一个子目标的结果作为最终答案
            final_answer = self._fallback_from_last_subgoal(subgoals)
        else:
            # 2026-09-04：即使子目标阶段预算已用尽（_stage_left()<=0），
            # 只要全局未 critical 就**必须真 merge**——这是"强制收尾产出"的关键：
            # 此前阶段预算用尽直接 return / 或 merge 被全局 critical 挤掉，
            # 答案停在子目标枚举（060: S(1)..S(12)）而没合成最终结论。
            final_answer = self._merge_results(ctx, subgoals, subgoal_plan_summary,
                                               results_map, merge_strategy)

        # v2.9：结构化输出最终整合方案
        ctx.subgoal_merge_plan = (
            f"合并策略: {merge_strategy or '将各子目标结果按逻辑顺序组合'}\n"
            f"最终答案: {final_answer}"
        )

        final_answer, _skip_pool = apply_pool_gate(self, ctx, final_answer)
        if _skip_pool:
            return
        # 构造 Candidate（`full_reasoning` 在门槛**之后**构建 ⇒ 与最终入池的
        #   `final_answer` 保持一致；避免抢救替换值后 reasoning 仍写原句）。
        full_reasoning = self._build_full_reasoning(
            subgoals, problem_analysis, final_answer)
        candidate = Candidate(
            id=next_candidate_id(ctx.candidates),
            answer=final_answer,
            reasoning=full_reasoning,
            revised=False,
            # 2026-09-14：选择题走「逐项判定」链路 ⇒ 标记来源，供选取阶段优先采纳。
            # 依据：实测 #107 逐项判定正确得出 D，却被候选池里 5 个整体求解的 C
            # 以 5:1 多数投票淹没。逐项判定是**有依据**的结论，不应输给数量。
            # 置 OBJECTIVE_ITEMWISE_PRIORITY=0 可回退（项目惯例：每项优化一开关）。
            origin=(
                "itemwise"
                if (getattr(ctx, "question_type", "") == "选择题"
                    and _sw_bool("objective_itemwise_priority"))
                else ""
            ),
        )
        ctx.candidates.append(candidate)
        self.record(ctx, "subgoal", "子目标求解完成，已生成候选解答",
                    subgoal_stats=self._subgoal_stats(subgoals),
                    ctx_inject_chars=_ctx_inject_chars)
        # -------- #34 阶段四：DAG 评审 + 整树重生成 --------
        # 老师要求："dag 框架错了要重新构建"。判定标准（DagReviewer）：
        # - reject >= 3 个（绝对阈值）
        # - reject 比例 >= 40%（相对阈值）
        # 满足任一 → 注入失败反馈让 BlueprintPlanner.regenerate_with_feedback 重写 DAG。
        # 硬上限 MAX_REPLAN_ROUNDS 防死循环；预算耗尽或 DAG 不可改进即停。
        # 2026-09-04 阶段预算：replan 是"候选已入池后"的改进环节（评审+重生成
        # 每轮 2-3 次 LLM），budget 用尽时跳过——不影响已产出的 merge 答案，
        # 把时间留给 orchestrator 后续 3_solve/lean 验证/答案闸门。
        # ★ 2026-10-04 修（D18）：原条件为 `enable_dag_replan and _stage_left() > 0`，
        #   是一条纯「**按剩余时间砍方法**」的闸门 —— 750s 之后"蓝图就算错了也不再修"，
        #   与「研究期不限时间、一切为正确率让路」的口径直接冲突。
        #   它还是**跨文件漏网**的实例：不受 `phase_budget_enabled` 管辖，
        #   关掉阶段预算总开关也拦不住它。
        #   现只保留机制开关，删掉时间条件；防挂死由单题硬墙（`is_timed_out`）负责。
        #   注：`getattr` 兜底默认值同步由 True 改为 False，与 `AgentConfig` 一致
        #   （原先两处默认值不一致，属潜在"同一开关两套默认"）。
        if getattr(self.config, "enable_dag_replan", False):
            self._review_and_maybe_replan(ctx, dag=ctx.blueprint)
        return ctx

    _note_dag_replan = _sgs_review._note_dag_replan

    _review_and_maybe_replan = _sgs_review._review_and_maybe_replan

    _review_dag_prepare = _sgs_review._review_dag_prepare

    @staticmethod
    def _is_value_choice(opts: list) -> bool:
        """判断是否为「求值选择型」（C 型）：选项都是**短数值/表达式候选**。

        这类题必须**先整体求解、再与选项比对** —— 逐项判定"选项 5 成立吗"
        是无意义的（选项不是命题，只是候选值）。official112 实测无此类题，
        但比赛题库可能有，故必须支持。

        判据（保守，宁可漏判不可误判）：每个选项 ①不含中文 ②长度 ≤15 ③含数字。
        空列表（提取失败）一律返回 False —— 绝不把"没提取到选项"当成求值型。
        """
        try:
            if not opts:
                return False
            for _l, _t in (opts or []):
                _s = (_t or "").strip()
                if not _s:
                    return False
                if re.search(r"[\u4e00-\u9fff]", _s):   # 含中文 → 命题/文字选项
                    return False
                if len(_s) > 15:                         # 过长 → 非候选取值
                    return False
                if not re.search(r"\d", _s):             # 无数字 → 排除
                    return False
            return True
        except Exception:  # noqa: BLE001
            return False

    def _plan_value_choice(self, ctx: TaskContext, opts: list) -> dict:
        """C 型（求值选择）规划：**先整体求解 → 再与选项比对匹配**。

        与 A/B 型的根本区别：A/B 型的选项是**待判定的命题**，逐项判定即可；
        C 型的选项是**候选数值**，必须先算出结果，再找出与之相等的选项。
        """
        self.record(ctx, "subgoal",
                    "选择题求值型规划：先整体求解 → 再匹配选项（{} 个选项）"
                    .format(len(opts)))
        return {
            "problem_analysis": {
                "question_type": "选择题",
                "subtype": "value_choice",
                "options": [{"label": l, "text": t} for l, t in opts],
            },
            "subgoals": [
                {
                    "id": 0,
                    "title": "整体求解",
                    "description": (
                        "**不要**看选项，先独立把题目要求的量算出来。\n"
                        "要求：写出完整算式与推导，最后一行给出『结果：<值>』。"
                    ),
                    "type": "compute",
                    "depends_on": [],
                    "expected_output": "结果：<值>",
                    "result": "",
                },
                {
                    "id": 1,
                    "title": "匹配选项",
                    "description": (
                        "把【整体求解】得到的结果与下面每个选项逐一比对"
                        "（必要时做数值/符号等价判断）：\n"
                        + "\n".join("  {}. {}".format(l, t) for l, t in opts)
                        + "\n最后一行输出『匹配选项：<字母>』；"
                          "若结果与多个选项等价，则全部写出（如 `AC`）。"
                    ),
                    "type": "verify",
                    "depends_on": [0],
                    "expected_output": "匹配选项：<字母>",
                    "result": "",
                },
            ],
            "merge_strategy": (
                "直接输出【匹配选项】给出的字母（连写，不要逗号/空格/解释）；"
                "若匹配失败，输出与结果最接近的选项字母。"
            ),
        }

    def _plan_choice_by_options(self, ctx: TaskContext) -> dict | None:
        """选择题专用规划：**每个选项一个独立判定子目标**（2026-09-13 用户要求）。

        为什么不让 LLM 规划：096 实测——提示词里早已写了"逐项独立判真"，但模型
        仍然直接综合出 `ACD`（漏判 D 单独成立、误判 A/C）⇒ **提示词不具约束力**。
        故改为代码确定性构造：选项数 N → N 个判定子目标，一个都不能少。

        边界：① 非选择题 → None（走原流程）；② 选项 < 2 → None（判据不足）；
        ③ 选项数 > max_subgoals → None（交回 LLM 规划，避免被截断丢项）。
        """
        try:
            # 独立开关（项目惯例：每项优化一个开关，便于 A/B 与逐项审查）。
            # 默认启用（用户 2026-09-13 明确要求：选择题每个选项都判断）；
            # 置 OBJECTIVE_ITEMWISE_PLAN=0 可一键回退到 LLM 规划。
            # ★ 2026-10-07（fix-tail-gaps）：原裸读 env `== "0"` 已改走注册制
            #   （`_itemwise_plan_on()` → `_sw_bool("objective_itemwise_plan")`，实时读）。
            if not _itemwise_plan_on():
                # ★ 2026-10-07（fix-tail-gaps · 静默跳过埋点）：原**静默** return None。
                self.record(ctx, "subgoal",
                            "选择题逐项判定规划已跳过：开关 OBJECTIVE_ITEMWISE_PLAN=0 "
                            "→ 回退 LLM 规划")
                return None
            if getattr(ctx, "question_type", "") != "选择题":
                self.record(ctx, "subgoal",
                            "选择题逐项判定规划已跳过：题型非『选择题』"
                            "（%r）→ 回退 LLM 规划"
                            % (getattr(ctx, "question_type", "") or "",))
                return None
            from .question_type import extract_options
            opts = extract_options(ctx.problem or "") or []
            if len(opts) < 2:
                self.record(ctx, "subgoal",
                            "选择题逐项判定规划已跳过：可用选项 < 2（%d 个），"
                            "不足以逐项判定 → 回退 LLM 规划" % len(opts))
                return None
            # ★ 2026-09-15：改走按档位分档的上限（见 _subgoal_cap）
            _max_sg = self._subgoal_cap(ctx)
            # 基准子目标(1) + N 个判定子目标(N)；超过上限则回退 LLM 规划
            # `_max_sg <= 0` = 不截断 ⇒ 逐项判定恒可用（2026-09-15 赛后口径）
            if _max_sg > 0 and len(opts) + 1 > _max_sg:
                self.record(ctx, "subgoal",
                            "选择题逐项判定规划已跳过：选项数 %d + 基准 1 > 子目标上限 %d，"
                            "为避免截断丢项 → 回退 LLM 规划"
                            % (len(opts), _max_sg))
                return None
            # ---- 题型子类识别（2026-09-13 用户要求：解题逻辑必须随题型而变）----
            #   A 命题判定型（选项是独立陈述，多选）→ 基准 + 逐项判定 → 全选为真
            #   B 定义/事实选择型（选项是互斥候选，单选）→ 基准 + 逐项判定 → 取唯一
            #   C 求值选择型（选项是短数值候选）→ **必须先整体求解**，再与选项比对
            _q = ctx.problem or ""
            if self._is_value_choice(opts):
                return self._plan_value_choice(ctx, opts)
            _is_single = bool(_SINGLE_CHOICE_RE.search(_q))
            subgoals = []
            # ★ 子目标 0：判断基准 —— **只建一次、全员共享**。
            #   对治用户指出的"ab 项是 cd 项的基础"：若让每个选项各自重新推导基准，
            #   既浪费又易导致判定口径不一致（判 A 用一套理解、判 C 用另一套）。
            subgoals.append({
                "id": 0,
                "title": "建立判断基准",
                "description": (
                    "先**只**建立本题的判断依据，**不要**在这里判定任何选项。\n"
                    "⚠ **严禁**在本步输出 `\\boxed{...}`、『最终答案』『答案是』"
                    "『综上，选』等**最终答案形态**的内容 —— 本步只提供依据，"
                    "最终答案由后续汇总步骤给出。实测 #098 因本步违规吐 `\\boxed{D}`，"
                    "导致该选项判定子目标照抄基准、整个判定链失效。\n"
                    "按题目需要输出以下之一（或多项）：\n"
                    "· 涉及定义/定理 → 写出相关定义或定理的**完整原文**；\n"
                    "· 涉及对应关系（“X 变为 Y”“增大/减小”“系数/常数项”"
                    "“约束/目标”等）→ 写出**完整映射表**，把原对象的每个元素"
                    "与变换后的元素逐项对应；\n"
                    "· 涉及计算 → 先算出**核心结果**（写出算式与结果）；\n"
                    "· 涉及判定标准 → 写出教材/规范中的判定标准原文。\n"
                    "这段基准是后续所有选项判定的**共同依据**，务必准确、可核验。"
                ),
                "type": "derive",
                "depends_on": [],
                "expected_output": "判断依据（定义原文 / 映射表 / 核心结果 / 判定标准）",
                "result": "",
            })
            for _i, (_lab, _txt) in enumerate(opts, 1):
                subgoals.append({
                    "id": _i,
                    "title": "判定选项 {}".format(_lab),
                    "description": (
                        "基于【建立判断基准】得到的定义原文 / 映射表 / 核心结果，"
                        "**只**判定选项 {} 这一个选项的陈述是否成立，不要讨论其他选项。\n"
                        "选项 {}：{}\n\n"
                        "【判定规范 · 必须遵守】\n"
                        "A. 先判断该选项属于哪类陈述，再选对应方法：\n"
                        "   ① 定义/定理类 → 逐词比对定义或定理原文，不得凭印象；\n"
                        "   ② 计算/等式类 → 代入数值或符号**实际验算**，写出算式；\n"
                        "   ③ 存在/构造类 → 给出具体构造，或给出明确反例；\n"
                        "   ④ **对应关系类**（“X 变为 Y”“由 A 得到 B”“增大/减小”"
                        "“左端/右端”“系数/常数项”“约束/目标”“前件/后件”）→ "
                        "**必须先列出映射表**，把原对象的每个元素与变换后的元素逐项"
                        "对应，再核对该选项的表述是否与映射表一致；"
                        "严禁凭“大体相关 / 看起来对”判为正确。\n"
                        "B. 含绝对化措辞（一定/必然/都/仅/只能/唯一/所有）时，"
                        "必须给出**无反例的论证**或**具体反例**，不得只写“不一定”。\n"
                        "C. 依据必须可核验：写出定义/定理名称或原文，或给出算式/反例。\n\n"
                        "【输出格式】开头一行写“结论：正确”或“结论：错误”，"
                        "随后用 1–2 句给出依据。"
                    ).format(_lab, _lab, _txt),
                    "type": "verify",
                    "depends_on": [0],
                    "expected_output": "选项 {}：正确/错误 + 理由".format(_lab),
                    "result": "",
                })
            self.record(ctx, "subgoal",
                        "选择题逐项判定规划：{} 个选项 → {} 个判定子目标"
                        "（代码强制，未走 LLM 规划）".format(len(opts), len(subgoals)))
            return {
                "problem_analysis": {
                    "question_type": "选择题",
                    "options": [{"label": l, "text": t} for l, t in opts],
                },
                "subgoals": subgoals,
                "merge_strategy": (
                    ("【单选型】" if _is_single else "【多选型】")
                    + "逐项汇总（不得跳步）：\n"
                    + (
                        "本题问法指向**单选**（“哪一项 / 最合适 / 定义是 / "
                        "通常采用”等）：在所有『结论：正确』的选项中，选择"
                        "**最准确、最直接回答题干**的一个；若只有一个判对则直接"
                        "输出它；若多个判对，输出最贴合题干的那一个，"
                        "并说明为何排除其余。\n"
                        if _is_single else
                        "本题问法指向**多选**（“哪些 / 正确的有”等）：把所有"
                        "『结论：正确』的选项字母**连写**输出（如 `ABD`），"
                        "不要逗号/空格。\n"
                    )
                    + "复核要求：① 对每个被判『错误』的选项，回看其依据是否真的成立；"
                      "② 对含绝对化措辞却判『正确』的选项，确认确实无反例；"
                      "③ **对应关系类选项**（“X 变为 Y”式）必须已完成映射表核对，"
                      "未核对的不计入正确项；④ **禁止**跳过逐项判定直接给答案。"
                ),
            }
        except Exception as _e:  # noqa: BLE001
            logger.warning("选择题逐项判定规划失败，回退 LLM 规划: %s", _e)
            return None

    # ---------- 阶段一：规划 ----------
    def _subgoal_cap(self, ctx) -> int:
        """当前题的子目标数上限（★ 2026-09-15 新增：按档位分档）。

        取值优先级：
          ① `config.max_subgoals_by_tier[ctx.tier]`（新，按档位）
          ② `config.max_subgoals`（旧，全局单一值，向后兼容）
          ③ 全局兜底 6

        语义：**返回 0 或负数 = 不截断**（与 `cap_subgoals_keep_last` 一致）。

        背景：此前 `max_subgoals` 是全局单一值 6，而蓝图提示词已写明
        "简单 3~5 / 中等 5~12 / **难题 12~30**" ⇒ **提示词与代码矛盾**
        （模型给难题画 12~30 个，代码一律切到 6）。
        现按档位给不同上限：deep 是难题档，题更复杂 → 允许更多子目标。
        """
        tier = str(getattr(ctx, "tier", "") or "")
        by_tier = getattr(self.config, "max_subgoals_by_tier", None)
        if isinstance(by_tier, dict) and tier in by_tier:
            try:
                return int(by_tier[tier])
            except (TypeError, ValueError):
                pass
        v = getattr(self.config, "max_subgoals", 6)
        return 6 if v is None else int(v)

    def _plan_subgoals(self, ctx: TaskContext) -> dict | None:
        """调用 LLM 生成子目标规划 JSON"""
        # 2026-09-13 用户要求「选择题就每个选项都判断」：选择题**不走 LLM 规划**，
        # 由代码确定性构造 N 个判定子目标（每选项一个），一个都不漏。
        # 依据：096 实测——提示词已写"逐项独立判真"，模型仍直接综合出 ACD
        # （漏判 D、误判 A/C）⇒ 提示词不具约束力，必须**代码强制**。
        _choice_plan = self._plan_choice_by_options(ctx)
        if _choice_plan is not None:
            return _choice_plan
        # #27 Blueprint DAG（LEAP Stage 1）：use_blueprint_dag 开启时先由
        # BlueprintPlanner 生成 AND-OR DAG（依赖驱动分解），再转子目标序列；
        # 生成失败回退到原有 LLM 规划（不损失候选来源）。
        if getattr(self.config, "use_blueprint_dag", False) or \
                getattr(self.config, "use_blueprint", False):
            blueprint_plan = self._plan_from_blueprint(ctx)
            if blueprint_plan is not None:
                return blueprint_plan
            self.record(ctx, "blueprint", "Blueprint DAG 规划失败，回退到 LLM 子目标规划")
        domain = ctx.domain or ""
        domain_hint = get_domain_hint(domain) if domain else ""
        # v2.9 遗留：原 Lean 前置形式化注入（formal_spec/formal_gaps/leansearch
        # 定理检索）已随 2026-09-06 去 Lean 化移除——平台无 Lean，注入恒为空。
        problem_text = ctx.problem
        # 2026-09-12 客观题特化（三处同源注入之①：规划阶段）：
        # 子目标主路径 2.7 对**所有档位默认先行**（enable_subgoal_main_path 默认
        # True），客观题的答案完全可能由本路径产出——只在 solver 里注入等于没注入。
        # 拼接位置固定在"题目"占位符内部，**不追加到提示词末尾**（历史教训
        # algebra-075：末尾追加破坏收尾结构 → 模型进入续写模式、泄漏占位符）。
        try:
            from .question_type import objective_injection as _obj_inj
            problem_text = problem_text + _obj_inj(
                ctx.problem or "", getattr(ctx, "question_type", "") or "",
                bool(getattr(self.config, "objective_tactic_enabled", True)))
        except Exception:  # noqa: BLE001
            pass
        # 2026-09-13 B0：答案形态要求**前置注入**（生成阶段就告知，而非事后重问）。
        # 依据：事后闸门在 formatter（流程末段）实测全部"时间不足跳过"——
        # deadline 被 tier_budget 收紧到 1800s，跑到末段必然剩余不足。
        try:
            from .question_type import answer_form_requirement as _afr
            problem_text = problem_text + _afr(
                ctx.problem or "", getattr(ctx, "question_type", "") or "")
        except Exception:  # noqa: BLE001
            pass

        user_msg = SUBGOAL_PLAN_USER_TEMPLATE.format(
            domain_hint=domain_hint,
            problem=problem_text,
        )

        last_resp = None
        for attempt in range(2):  # v2.6.1：3→2 次（解析失败说明 LLM 输出结构异常，
            # 重试成功率低；省下时间给真正有意义的求解步骤）
            # v2.4.1：prefill「{"」引导直接输出规划 JSON，抑制 CoT
            resp = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": SUBGOAL_PLAN_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    '{"',
                ),
                0.2, 32768,
            )
            if resp:
                resp = stitch('{"', resp)
                last_resp = resp
            if resp is None:
                continue
            raw = self._extract_json(resp)
            if raw is None:
                logger.warning("SubGoal plan: JSON parse failed on attempt %d", attempt + 1)
                continue
            # ★ 2026-09-15：改走按档位分档的上限（见 _subgoal_cap）
            _sg_cap = self._subgoal_cap(ctx)
            subgoals = self._parse_subgoal_plan(
                raw, 6 if _sg_cap is None else int(_sg_cap))
            if subgoals is None:
                logger.warning("SubGoal plan: invalid subgoals on attempt %d", attempt + 1)
                continue
            return {
                "problem_analysis": raw.get("problem_analysis", {}),
                "subgoals": subgoals,
                "merge_strategy": raw.get("merge_strategy", ""),
            }

        # v2.6.1 兜底：LLM 反复输出不合规 JSON 时，不再返回 None（损失整个候选来源），
        # 而是构造一个最小可用 plan（单步求解整道题），让 SubGoalSolver 至少产出 1 个
        # 候选；同时把最后一次响应记到 trace 便于排查 LLM 实际输出形态。
        self.record(ctx, "subgoal",
                    f"子目标规划 2 次尝试均失败; 最后响应片段: {(last_resp or '<None>')[:200]};"
                    " 回退到单步求解整道题")
        return {
            "problem_analysis": {},
            "subgoals": [{
                "id": 1,
                "title": "完整求解",
                "description": ctx.problem,
                "type": "compute",
                "depends_on": [],
                "expected_output": "",
                "result": "",
            }],
            "merge_strategy": "直接给出最终答案",
        }

    # ---------- Blueprint DAG 规划（#27）----------
    def _plan_from_blueprint(self, ctx: TaskContext) -> dict | None:
        """用 BlueprintPlanner 生成 AND-OR DAG 并转为子目标规划。"""
        try:
            from .blueprint_planner import BlueprintPlannerAgent
        except Exception as e:  # noqa: BLE001
            logger.warning("BlueprintPlanner 导入失败: %s", e)
            return None
        planner = BlueprintPlannerAgent(self.client, self.config)
        dag = planner.generate_blueprint(ctx)
        if dag is None:
            # ★ 2026-10-07（fix-tail-gaps · 静默跳过埋点）：原**静默** return None。
            self.record(ctx, "blueprint",
                        "Blueprint 路径已跳过：蓝图生成返回空（generate_blueprint=None）"
                        "→ 回退 LLM 子目标规划")
            return None
        # 老师 9/2 建议：骨架编排层 review（求解前规划质量门）。
        # 生成骨架后先提交 LLM 审查：子目标是否不适定 / 求解难度是否 >= 原问题；
        # 有问题 → 带评审反馈重新生成骨架 → 再 review 确认；
        # 通过后才进入下方语法审核（_audit_blueprint_tree）与子目标求解。
        if getattr(self.config, "enable_skeleton_review", True):
            dag = self._skeleton_review_loop(ctx, dag, planner)
            if dag is None:
                self.record(ctx, "blueprint",
                            "Blueprint 路径已跳过：骨架评审循环返回空"
                            "→ 回退 LLM 子目标规划")
                return None
        # 2026-09-08 求解前 DAG 强制评审门——默认关闭（dag_replan_gate=False）。
        # 45 题实证：门"拦得住、修不好"（21/45 触发强制重写、净正确率贡献≈0、
        # 总耗时 +23%、触发组人均 +245s），重写对方向性错误无济于事（comb-058
        # 差1 / geo-068 思路偏，重写 2 轮达硬上限仍错）。蓝图评审-重写循环的
        # 时间让给子目标求解与数值验证。A/B 复测时显式置 dag_replan_gate=True。
        # 门代码与 Lean 升级逻辑保留（_dag_replan_gate / _lean_dag_logic_check），
        # 不开时不产生任何调用开销。
        if getattr(self.config, "dag_replan_gate", True):
            dag = self._dag_replan_gate(ctx, dag)
            if dag is None:
                self.record(ctx, "blueprint",
                            "Blueprint 路径已跳过：求解前 DAG 评审门返回空"
                            "→ 回退 LLM 子目标规划")
                return None
        # 2026-09-15 同源修复：此前不传参 ⇒ 恒用默认 6，**config.max_subgoals
        # （含 0915 新增的 --max_subgoals CLI）对 blueprint 路径完全无效**。
        # 实测 003/074 都走 Blueprint DAG ⇒ 这些题的旋钮是死的。现与 LLM 规划
        # 路径（_parse_subgoal_plan）取同一个 config 字段。
        # ★ 2026-09-15：改走按档位分档的上限（见 _subgoal_cap）
        plan = dag.to_subgoal_plan(
            self._subgoal_cap(ctx),
            with_deps=getattr(self.config, "blueprint_deps_enabled", True),
            or_expand_all=getattr(self.config, "blueprint_or_expand_all", False))
        if not plan.get("subgoals"):
            # 退化情形：整张 DAG 都是前瞻引理（无 required 叶子）。
            # 此时无子目标可解，仍视为规划失败并回退 LLM 规划（不静默产出空解）。
            logger.warning("Blueprint DAG 无可用叶子子目标")
            # ★ 2026-10-07（fix-tail-gaps · 静默跳过埋点）：trace 侧原无记录
            #   （仅 logger.warning，评测零痕迹）→ 补足。
            self.record(ctx, "blueprint",
                        "Blueprint 路径已跳过：DAG 无可用叶子子目标（整树均为前瞻引理）"
                        "→ 回退 LLM 子目标规划")
            return None
        # ★ 前瞻引理规划（LEAP §2.3）：anticipatory 节点不进求解链，
        #   其陈述写入引理记忆（ctx.lemma_repo），供后续子目标提示词的
        #   【已建立的结论】区块引用（见 _solve_subgoal 的 lemma_context）。
        #   ⚠ 用 if 而非无条件赋值：_use_lemma 按领域路由（A/B 实测全开净 0.0pp），
        #   要保持与 _accumulate_lemma 同一开关语义，不做绕过。
        # ★ 2026-09-23：把 LeanSearch 检索到的 Mathlib 定理注入**解题侧**引理记忆。
        #   此前检索结果只喂验证器（`leansearch_inject_verifier`）⇒ 解题器从未见过，
        #   实测 460 条里仅 1% 进入 Lean 代码。必须在**求解前**注入。
        self._inject_mathlib_theorems(ctx)
        self._inject_anticipatory_lemmas(ctx, plan.get("anticipatory_lemmas") or [])
        # 2026-09-06 去 Lean 化：原 LEAP Stage 2 整树 Lean 搭桥审核
        # （_audit_blueprint_tree / lean_translator / lean_refiner）已移除——
        # 平台无 Lean，整树翻译+编译只空转。骨架评审（上方 enable_skeleton_review）
        # 是 LLM 规划质量门，与 Lean 无关，保留。
        self.record(ctx, "blueprint",
                    f"Blueprint DAG → {len(plan['subgoals'])} 个子目标 "
                    f"(根={dag.root_id}, 节点={len(dag.nodes)}, "
                    f"前瞻引理={len(plan.get('anticipatory_lemmas') or [])})")
        return plan

    def _inject_mathlib_theorems(self, ctx: TaskContext) -> int:
        """把 LeanSearch 检索到的 Mathlib 定理写进引理记忆，**让解题器真正看得到**。

        ★ 2026-09-23 新增，回答用户"mathlib 的定理是不是和本题有关、哪些帮上了忙"。

        根因（0923 环节效能审计实测）：460 条检索结果里只有 **4 条（1%）** 出现在
        Lean 代码中。原因不是"定理无关"，而是——
        `verifier._prepare_theorem_context` 把检索结果注入的是**验证器**的提示词
        （`leansearch_inject_verifier`），而**解题器从未收到过这些定理**
        ⇒ 检索在"解题"这个最该用它的环节**完全缺席**。

        本方法在子目标求解**之前**检索一次，并把命中的定理写进 `ctx.lemma_repo`
        （与 `_accumulate_lemma` 同格式），由既有注入通路喂给每个子目标步。

        纪律：异常/超时/后端不可用一律静默返回 0，绝不阻断求解。
        """
        try:
            if not getattr(self.config, "inject_mathlib_to_solver", True):
                # ★ 2026-10-07（fix-tail-gaps · 静默跳过埋点）：原**静默** return 0。
                self.record(ctx, "leansearch",
                            "解题前 Mathlib 注入已跳过：开关 "
                            "inject_mathlib_to_solver=0")
                return 0
            if not getattr(self.config, "use_leansearch", False):
                self.record(ctx, "leansearch",
                            "解题前 Mathlib 注入已跳过：LeanSearch 总开关 "
                            "use_leansearch 未开启（默认关）")
                return 0
            if ctx.is_time_critical():
                self.record(ctx, "leansearch",
                            "解题前 Mathlib 注入已跳过：当前处于时间紧迫区")
                return 0
            if getattr(ctx, "_mathlib_injected", False):
                self.record(ctx, "leansearch",
                            "解题前 Mathlib 注入已跳过：本轮回合已注入过（去重短路）")
                return 0
            cap = int(getattr(self.config, "leansearch_max_calls_per_q", 2) or 0)
            used = int(getattr(ctx, "_leansearch_calls", 0) or 0)
            if cap and used >= cap:
                self.record(ctx, "leansearch",
                            "解题前注入跳过：单题检索次数已用 %d/%d" % (used, cap))
                return 0
            from tools.lean_local.lean_search import MathlibTheoremSearcher
            searcher = getattr(self, "_ls_searcher_solver", None)
            if searcher is None:
                searcher = MathlibTheoremSearcher()
                self._ls_searcher_solver = searcher
            k = max(1, min(10, int(getattr(self.config, "leansearch_top_k", 10) or 10)))
            ctx._leansearch_calls = used + 1
            self.note_mathlib_search(ctx)
            res = searcher.search((getattr(ctx, "problem", "") or "")[:800], limit=k) or {}
            items = res.get("results") or []
            added = 0
            repo = getattr(ctx, "lemma_repo", None)
            if not isinstance(repo, list):
                repo = []
                ctx.lemma_repo = repo
            for it in items:
                nm = ""
                if isinstance(it, dict):
                    nm = str(it.get("name") or it.get("theorem") or it.get("id") or "").strip()
                else:
                    nm = str(it).strip()
                if not nm:
                    continue
                tail = nm.split(".")[-1]
                entry = "Mathlib 定理: %s（可尝试在 Lean 代码中直接引用）" % tail
                if entry not in repo:
                    repo.append(entry)
                    added += 1
            ctx._mathlib_injected = True
            self.record(ctx, "leansearch",
                        "解题前注入 Mathlib 定理 %d/%d 条到引理记忆（此前只喂验证器）"
                        % (added, len(items)))
            return added
        except Exception as e:  # noqa: BLE001
            logger.debug("解题前 Mathlib 注入异常（忽略）: %s", str(e)[:120])
            return 0

    def _inject_anticipatory_lemmas(self, ctx: TaskContext,
                                    lemmas: list) -> int:
        """把前瞻引理写入引理记忆（LEAP §2.3 落地，2026-09-15）。

        前瞻引理 = 蓝图生成时提议的"当前不需要、但后续可能用到"的辅助引理
        （论文 Figure 2 虚线边）。它们**不参与当前 AND 节点求解**，
        只作为可复用的已验证陈述挂到记忆里。

        写入形式与 `_accumulate_lemma` 保持一致（`"标题: 陈述"` 字符串），
        这样 `_solve_subgoal` 的现成注入通路无需任何改动即可消费。

        返回实际写入条数。
        """
        if not lemmas:
            return 0
        if not self._use_lemma(ctx):
            # 领域路由关闭时不注入（与 _accumulate_lemma 同规则，
            # 避免"引理注入只在数论开"这条既有实测结论被悄悄绕过）
            # ★ 2026-10-07（fix-tail-gaps · 静默跳过埋点）：原**静默** return 0。
            self.record(ctx, "blueprint",
                        "前瞻引理注入已跳过：领域路由（_use_lemma）判定本域不做引理注入")
            return 0
        added = 0
        for item in lemmas:
            if isinstance(item, dict):
                stmt = str(item.get("statement") or "").strip()
                nid = str(item.get("id") or "").strip()
            else:
                stmt, nid = str(item or "").strip(), ""
            if not stmt:
                continue
            entry = f"前瞻引理{('[' + nid + ']') if nid else ''}: {stmt}"
            if entry not in ctx.lemma_repo:
                ctx.lemma_repo.append(entry)
                added += 1
        if added:
            self.record(ctx, "blueprint",
                        f"前瞻引理入记忆 {added}/{len(lemmas)} 条（不阻塞求解）")
        return added

    _skeleton_review_loop = _sgs_review._skeleton_review_loop

    # ---------- 求解前 DAG 强制评审门（2026-09-08 改进建议1）----------
    _dag_replan_gate = _sgs_review._dag_replan_gate

    _dag_replan_gate_prepare = _sgs_review._dag_replan_gate_prepare

    # ---------- 求解前门 Lean 逻辑层检测（2026-09-08 门升级，见 _dag_replan_gate）---
    _lean_dag_logic_check = _sgs_lean._lean_dag_logic_check

    _parse_lean_expr_map = staticmethod(_sgs_lean._parse_lean_expr_map)

    _map_lean_errors = staticmethod(_sgs_lean._map_lean_errors)

    _merge_lean_rejects = staticmethod(_sgs_lean._merge_lean_rejects)

    # ---------- 阶段二：逐步求解 ----------
    def _solve_subgoal(self, ctx: TaskContext, sg: dict,
                       plan_summary: str, prev_results: str,
                       extra_hint: str = "") -> str:
        """求解单个子目标，返回结果文本。

        v2.7：计算类子目标（compute/derive）求解后用 AnswerOracle 做客观
        sanity check，若结果明显非法（不可解析为数学表达式），带反馈重解一次，
        实现"每步 oracle 校验"（Plan-and-Execute + oracle-in-the-loop）。

        v2.10（2026-08-29）：use_lemma_accumulation 开启时，把已求得的
        引理列表注入子目标提示词（"已建立的结论"），让后续子目标直接复用，
        避免重复推导（D6 引理积累钥匙的真正落地点）。

        v2.11（2026-09-06 老师建议）：extra_hint 承载 0-LLM 校验（S1-lite）
        的失败反馈——截断/Lean 代码片编译错误，随重解请求带回，让模型
        带反馈修正后重新给出【本步结果】（验证-精炼下沉到子目标级）。
        """
        # 引理注入：已求得的子目标结论作为"前置引理"提供。
        # **必须放在提示词中部（最终指令之前），不能追加在末尾**——
        # 2026-08-29 A/B 实测：追加在末尾会改变提示词收尾结构，使模型
        # 进入"续写模式"，答案泄漏 `[续写]` 占位符（algebra-075 因此从对变错）。
        user_msg = self._prepare_step_prompt(
            ctx, sg, plan_summary, prev_results, extra_hint)

        step_result = self._call_step(ctx, user_msg, sg=sg)

        # ★★ 2026-10-07（问题 2.9）：**`<check>` 协议校验 + 定向重问**。
        #   实测（smoke10 题 000）：大量子目标把**中文句子**塞进 `<check>`
        #   （`<check>图 G 是弱连通的</check>`）⇒ `is_parseable=False` ⇒
        #   客观判定**一条都出不来**（`n_judged = 0/73` 的直接原因之一）。
        #   处理（先读既有契约 `SUBGOAL_CONCLUSION_CONTRACT` 再强化，不另起一套）：
        #     ① 违规定性：`<check>` 内含非可核验对象（中文/文字/非单等式）；
        #     ② **留痕**：trace 记 `check_protocol`（违反内容 + 子目标号），
        #        并把违反项写进 sg，随 `_build_trace_item` 进 diag（可见，不静默）；
        #     ③ **一次定向重问**：把违规内容 + 正确写法（`本步结论: 判定 = 真`
        #        或纯数学等式）作为反馈重发；重问后合规即采用新结果。
        #     ⚠ 不做"重问 N 次"——单步成本高（本项目多次实测：生成侧吃光预算
        #       → 验证阶段饿死）；一次不成就保留并留痕，交由下游处置。
        if (_check_protocol_guard_on() and step_result
                and not step_result.startswith("[子目标")):
            _viol = _check_protocol_violations(step_result)
            if _viol:
                self.record(
                    ctx, "check_protocol",
                    "子目标#%s 违反 <check> 协议：%d 处 <check> 内含非可核验对象"
                    "（应为纯数学等式；装句子 = 该步不可验证）。违反内容示例：%r"
                    % (sg.get("id"), len(_viol), _viol[0][:60]))
                try:
                    sg["check_protocol_violations"] = _viol[:3]
                except Exception:  # noqa: BLE001
                    pass
                if not ctx.gen_time_up():
                    _fix_msg = user_msg + (
                        "\n\n[协议违规：`<check>` 内容不是可核验对象]\n"
                        "你写的 `<check>%s</check>` 里是**文字描述**，系统无法核验。\n"
                        "`<check>` 只允许装**一个纯数学等式**（仅数字/变量/运算符 "
                        "+ - * / ^ ( )，恰含一个 `=`，不得含中文或文字）。\n"
                        "修正方式：\n"
                        "  · 自然语言命题（如「图 G 是弱连通的」）改写为"
                        "【本步结果】首行 `本步结论: 判定 = 真`；\n"
                        "  · `<check>` 只保留真正的数值/代数等式，"
                        "没有可核验等式就**不要写 `<check>`**。\n"
                        "请修正后重新给出【本步结果】。"
                        % (_viol[0][:80],))
                    _retry = self._call_step(ctx, _fix_msg, sg=sg)
                    if (_retry and not _retry.startswith("[子目标")
                            and not _check_protocol_violations(_retry)):
                        self.record(ctx, "check_protocol",
                                    "子目标#%s 定向重问后 <check> 协议合规"
                                    % sg.get("id"))
                        step_result = _retry
                    else:
                        self.record(ctx, "check_protocol",
                                    "子目标#%s 定向重问后仍违规/无改善 → 保留原结果"
                                    "并留痕（不再重问）" % sg.get("id"))

        # 每步 oracle 校验：仅对计算类子目标（预期数值/表达式结果）做客观检查
        # 2026-09-03 老师：子目标是**简化求解**的，不是复杂化的。实测 deep 档
        # 每步 110s（主求解 60s + oracle 10-70s + 重试 60s）→ 8 步吃掉 882s，
        # 验证/Lean 闸门全没时间。oracle 是**同源自评**（价值低、耗时高），
        # 默认关闭（sub_goal_oracle_check=False 开启）。
        # 注意：这里**不是强制结束**——失败重试（_solve_subgoal 的上下文重试）
        # 仍保留，子目标一定会尽力做完（老师："强制结束就等于错误"）。
        sg_type = sg.get("type", "compute")
        if (getattr(self.config, "sub_goal_oracle_check", False)
                and sg_type in ("compute", "derive")
                and step_result
                and not step_result.startswith("[子目标")):
            oracle_fb = self._oracle_check_step(step_result)
            if oracle_fb and not ctx.gen_time_up():
                retry_msg = user_msg + (
                    f"\n\n[上一步结果客观校验未通过] {oracle_fb}\n"
                    f"请修正错误后重新给出【本步结果】。"
                )
                retry_result = self._call_step(ctx, retry_msg, sg=sg)
                if retry_result and not retry_result.startswith("[子目标"):
                    return retry_result
        return step_result

    def _prepare_step_prompt(self, ctx: TaskContext, sg: dict,
                              plan_summary: str, prev_results: str,
                              extra_hint: str) -> str:
        """单步提示词准备段（2026-10-08 批2：从 `_solve_subgoal` 原地拆出）。

        装配已建立结论（lemma_context）/ 客观题特化注入 / 剥离 boxed 指令的题面 /
        title·description 的 K11 断言数值掩码 / `SUBGOAL_STEP_USER_TEMPLATE`
        → 返回 `user_msg`。段体**逐字搬**，record 步序不变。
        """
        lemma_context = ""
        if self._use_lemma(ctx):
            lemmas = list(getattr(ctx, "lemma_repo", []) or [])
            if lemmas:
                lemma_block = "\n".join(f"- {l}" for l in lemmas[-8:])
                lemma_context = (
                    f"\n【已建立的结论（可直接引用，无需重新推导）】\n"
                    f"{lemma_block}\n")

        # ② 原子目标级 leansearch 独立检索（LeanSearch v2 论文）已随
        # 2026-09-06 去 Lean 化移除——平台无外网/无 Lean，检索恒空转。

        # 2026-09-12 客观题特化（三处同源注入之②：子目标逐步求解）——这是子目标
        # 链里**真正产出内容**的一步，客观题答案可能直接来自本步结果。
        _obj_inj = ""
        try:
            from .question_type import objective_injection as _oi
            _obj_inj = _oi(
                ctx.problem or "", getattr(ctx, "question_type", "") or "",
                bool(getattr(self.config, "objective_tactic_enabled", True)))
        except Exception:  # noqa: BLE001
            _obj_inj = ""
        # ★ 2026-09-14（#103「丢 E」真根因修复）：剥离题面的
        #   「Remember to put your final answer within \boxed{}.」指令。
        #   实测该句**112/112 题都有**（题库统一附加），它会随题面进入**每个
        #   中间子目标**的 prompt ⇒ ① 选项判定子目标全都输出 `\boxed{A}`；
        #   ② **最后一个选项**直接吐**最终答案**（#103「判定选项 E」→
        #   `\boxed{ABCD}`）⇒ 聚合层认不出它是 E 的判定 ⇒ 静默丢项。
        #   该指令只对**最终汇总**步骤有效（merge 仍用原题、保留 boxed 要求），
        #   故此处对子目标 prompt 使用剥离版题面。
        try:
            from .question_type import strip_answer_format_directive as _safd
            _prob_for_step = _safd(ctx.problem or "")
        except Exception:  # noqa: BLE001
            _prob_for_step = ctx.problem or ""
        # ★ 2026-10-04（K11 注入点守卫）：本模板 **逐字** 注入的字段必须全部过掩码。
        #   背景：蓝图节点 `statement` 经 `blueprint_planner.to_subgoal_plan`（:302-303）
        #   被原样写成子目标 `title` / `description`，再由本模板送进每步求解提示词
        #   （见 prompts/sub_goal.py:229-231）⇒ 蓝图若写「证明最小值为 4030，故答案为
        #   4030」就等于**指令模型输出 4030**（K11，已数据确认的唯一过半根因 41.4%）。
        #   原守卫只覆盖 merge_strategy / problem_analysis（生产点），此处为最后一道关口。
        #   只改局部变量，**不动 sg 本体**（其它消费者与 trace 不受影响）。
        _desc = str(sg.get("description") or "")
        _title = str(sg.get("title") or "")
        if _k11_mask_on():
            _desc, _n_desc = _mask_asserted_values(_desc)
            _title, _n_title = _mask_asserted_values(_title)
            _n_mask = _n_desc + _n_title
            if _n_mask:
                self.record(ctx, "blueprint_lock_guard",
                            f"子目标注入字段（title/description）内嵌 {_n_mask} 处断言数值"
                            " → 已屏蔽为占位符（K11 注入点守卫）")
        user_msg = SUBGOAL_STEP_USER_TEMPLATE.format(
            problem=_prob_for_step + _obj_inj,
            subgoal_plan_summary=plan_summary,
            previous_results=prev_results,
            lemma_context=lemma_context,
            subgoal_id=sg["id"],
            subgoal_title=_title,
            subgoal_type=sg["type"],
            subgoal_description=_desc,
            subgoal_expected_output=sg["expected_output"],
        )
        # v2.11：0-LLM 校验反馈（S1-lite）追加在提示词末尾；只有校验真没过才带
        # （空串 = 通过）。不追加在开头/中部，避免改变模板收尾结构（2026-08-29
        # 教训：提示词收尾被破坏会让模型进入续写模式、泄漏占位符）。
        if extra_hint:
            user_msg = user_msg + (
                f"\n\n[本步结果校验反馈] {extra_hint}\n"
                f"请修正后重新给出【本步结果】。"
            )
        return user_msg

    def _use_lemma(self, ctx: TaskContext) -> bool:
        """按领域路由 lemma 累积（与 SolverAgent 同规则，2026-08-29）。

        A/B 实测 lemma 全开净 0.0pp、数论 +23pp → 数论域开、其他关。
        """
        if not getattr(self.config, 'use_lemma_accumulation', False):
            return False
        domains = list(getattr(self.config, 'lemma_domains', []) or [])
        if not domains:
            return True
        d = str(getattr(ctx, 'domain', '') or '')
        return any(k in d for k in domains)

    def _accumulate_lemma(self, ctx: TaskContext, sg: dict, result: str) -> None:
        """把已求得的子目标结论存入 ctx.lemma_repo（去重，单题内存）。

        只收有效结果（剔除占位符/失败标记），按「标题: 结论」存储，
        后续子目标与最终求解步骤通过提示词注入复用。
        """
        if not result or result.startswith("[子目标"):
            return
        title = (sg.get("title") or "").strip()
        text = str(result).strip()
        # ★ 2026-10-06（结论契约）：有结构化结论时用结论入引理记忆 ——
        #   引理是"可直接引用、无需重新推导"的前置结论，混入验算正文只会
        #   撑大后续每步提示词。
        _concl = str(sg.get("conclusion") or "").strip()
        if _concl:
            text = _concl
        if not title or not text:
            return
        entry = f"{title}: {text}"
        if entry not in ctx.lemma_repo:
            ctx.lemma_repo.append(entry)

    @staticmethod
    def _strip_tool_residue(text: str) -> str:
        """剥除工具调用 XML 残留（2026-09-17 新增）。

        为什么需要：实测 official112-025 的 6 个候选中 **5 个** `answer` 是字面量
        `</tool_call>`（reasoning 却是完整推理）——根因是几条「把模型原文尾部切片
        当答案/结果」的路径不过剥壳，工具标签原样落盘 ⇒ 该题必然判错。
        `utils.extract` 已有 `_strip_toolcall_markers`，此处统一封装，避免各调用点
        口径漂移（`<calc>` 标记剥壳由 `Candidate.__post_init__` 统一出口处理）。

        惰性 import + try/except：剥壳失败一律退回原文，绝不阻断求解。
        """
        if not text:
            return text
        try:
            from utils.extract import _strip_toolcall_markers
            return _strip_toolcall_markers(str(text))
        except Exception:  # noqa: BLE001  剥壳失败不阻断
            return text

    def _call_step(self, ctx: TaskContext, user_msg: str,
                     sg: dict | None = None) -> str:
        """单步子目标求解调用（prefill「【本步结果】」答案前置，抑制 CoT）。

        2026-10-01：原 2026-09-04 下沉的 `<calc>` 计算纪律（system 追加引导 +
        响应回填）已随计算工具板块整体删除；本方法现在只做提示词拼装与调用。
        """
        _step_system = SUBGOAL_STEP_SYSTEM
        # ★ 2026-09-29（截图 #3+#4）：子目标求解是**用户点名的解题重点环节**，
        # 且它是独立于 solver 的生成路径 —— 定理线索必须在本路径单独注入，
        # 否则"检索到了定理"对子目标推理毫无作用（本项目教训：只改一处=没改）。
        # 放 system 而非 user：user_msg 由上层模板构造，改动面更小、风险更低。
        if getattr(self.config, 'enable_theorem_hint', True):
            _th = (getattr(ctx, 'theorem_hint_block', '') or '').strip()
            if _th:
                _step_system = _step_system + "\n\n" + _th
        # ★★ 2026-10-06（子目标交付重写 A）：结论契约注入（开关
        #   `subgoal_conclusion_contract`，默认开）。放 system 而非 user：
        #   user_msg 的收尾结构有历史教训（2026-08-29：末尾追加会让模型进入
        #   续写模式、泄漏占位符），system 追加无此风险。
        if _conclusion_contract_on():
            _step_system = _step_system + "\n" + SUBGOAL_CONCLUSION_CONTRACT

        # ★ 2026-09-30（截图 #8）：**多 agent 求解子目标**。
        #   用户原话：「多 agent 拿子目标的求解能不能换成多 agent？
        #              那样是不是能提高子目标的正确率？」
        #
        #   实现：对**同一个子目标**独立采 N 个解（同 prompt、不同随机性），
        #   再按「归一化后的关键值一致性」选代表解 —— 即 self-consistency
        #   下沉到子目标粒度。与整体求解层的投票同源，但作用点在中间步骤：
        #   **中间步骤错一个，后面全错**，故此处收益理论上更高。
        #
        #   开关：`enable_subgoal_multi_agent`（默认 False = 与改动前逐字一致）
        #         `subgoal_agents_n`（默认 3）
        #   ⚠ 只在**非时间紧迫**时启用：N 次调用 = N 倍单步成本，
        #     预算不足时必须退回单次，否则会把后续验证阶段饿死
        #     （本项目多次实测的教训：生成侧吃光预算 → 4_verify 全跳）。
        _ma_n = self._multi_agent_n(ctx)
        if _ma_n > 1:
            # 阶段二-1：传入 sg，让「保留全部候选」落到该子目标的 trace 项上
            #（返回值仍是代表解字符串 ⇒ 下游消费零改动）。
            resp = self._sample_step_consensus(ctx, _step_system, user_msg, _ma_n,
                                               sg=sg)
        else:
            resp = self._maybe_tool_llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": _step_system},
                        {"role": "user", "content": user_msg},
                    ],
                    "【本步结果】",
                ),
                0.2, 32768,
            )
            if resp:
                resp = stitch("【本步结果】", resp)
        if resp is None:
            return "[子目标求解失败]"

        # 提取「本步结果」部分
        # 2026-09-17：**切片/返回前先剥壳**。实测 official112-025 的 6 个候选中
        # 5 个 `answer` 是字面量 `</tool_call>`（reasoning 却是完整推理）——根因
        # 就是这里把模型原文尾部（工具调用 XML 残留）原样当成"本步结果"返回，
        # 再经 merge 变成最终答案。剥壳后为空则返回空串，交给上层兜底。
        result_match = re.search(r"【本步结果】\s*\n?(.*?)(?:$|【)", resp, re.DOTALL)
        if result_match:
            step_result = self._strip_tool_residue(result_match.group(1)).strip()
        else:
            # 如果没有标记，取最后 500 字符（同样先剥壳再切片）
            step_result = self._strip_tool_residue(resp).strip()[-500:]
        # ★★ 2026-10-06（子目标交付重写 A/B/C）：把结论契约解析 + 客观判定
        #   落到 sg（trace 由 run() 落盘）。传 resp 供兜底找【推导过程】块。
        if sg is not None and _conclusion_contract_on():
            self._apply_conclusion_contract(sg, step_result, raw_text=resp)
        return step_result

    # ------------------------------------------------------------------
    # 多 agent 子目标求解（2026-09-30，截图 #8）
    # ------------------------------------------------------------------
    def _multi_agent_n(self, ctx: TaskContext) -> int:
        """本子目标该采几个解（1 = 关闭多 agent）。

        ★ 三道闸门，任一不满足即退回 1（**宁少不饿死**）：
          ① 开关 `enable_subgoal_multi_agent`（默认 False ⇒ 行为与改动前一致）；
          ② 时间：`is_time_critical()` 或生成软截止已到 ⇒ 退回 1；
          ③ 预算：剩余调用数不足 N 时退回 1。
        这么设计的原因：多 agent = N 倍单步成本，而单题 1150s 里验证侧
        （3.6+4_verify+4.5+4.6+5+5.5+6+6.5）要吃掉 ~45%。生成侧一旦吃光，
        验证全跳、错解裸奔 —— 本项目已有多次实测教训。
        """
        if not bool(getattr(self.config, "enable_subgoal_multi_agent", False)):
            return 1
        # ⚠ 2026-09-30：**只兜 None / 缺键**，绝不用 `or 3`。
        #   原因：0 与负数在 Python 里是 falsy，`0 or 3` 会**静默变成 3** ——
        #   用户明明把并发数配成 0（意图可能是"先关掉"），系统却按 3 倍成本
        #   跑起来，且日志里看不出任何异常。这是"配置写错反被兜底成危险值"
        #   的典型假安全。此处宁可把它夹到 1（= 退回单次），语义明确可解释。
        _raw = getattr(self.config, "subgoal_agents_n", None)
        if _raw is None:
            _raw = 3
        try:
            n = int(_raw)
        except (TypeError, ValueError):
            n = 3
        n = max(1, min(n, 8))            # 上限 8，防配置写错把预算打爆
        if n <= 1:
            return 1
        try:
            if ctx.is_time_critical() or ctx.gen_time_up():
                return 1
        except Exception:  # noqa: BLE001
            pass
        try:
            # ⚠ 2026-09-30：`Budget.can_spend()` 已于 2026-09-03 删除
            #   （比赛无次数上限，Budget 只记账不阻断）。此处改用
            #   `used_calls` / `max_calls` 直接比较 —— 语义是"**自留余量**"，
            #   不是"系统强制拦截"：多 agent 是可选加速手段，不该把总调用数
            #   花在自己身上，导致后续阶段（验证/自改进）无预算可用。
            _b = getattr(ctx, "budget", None)
            if _b is not None:
                _left = int(getattr(_b, "max_calls", 0) or 0) - int(
                    getattr(_b, "used_calls", 0) or 0)
                if _left < n:
                    return 1
        except Exception:  # noqa: BLE001
            pass
        return n

    def _sample_step_consensus(self, ctx: TaskContext, step_system: str,
                               user_msg: str, n: int,
                               sg: dict | None = None) -> Optional[str]:
        """对同一子目标采 n 个解，返回**最可代表多数**的那一个原文。

        ★ 2026-10-02（阶段二-1：「淘汰」→「保留」）：
          用户原话「那怎么能靠长度选取呢？要按照正确率选取啊」——
          本函数**不再淘汰候选**：把**全部候选原文**写入 `sg["candidates"]`
          （由上层落到 `ctx.subgoal_trace[i]["candidates"]`），供**最终答案层**
          一次性对比判断 / 投票。**返回值语义不变**（仍返回一个代表解字符串）
          ⇒ 下游消费方式**零改动**。
          ⚠ 代表解**不是"唯一真理"**，只是"继续往下推的默认值"；其余候选仍保留。

        选择规则（先到先用，逐级降级 —— 每一级都可解释）：
          ① **关键值一致**：n 个解里，归一化后的「本步结果」出现次数最多者胜
             （self-consistency）。并列时取**更长的原文**（推理更完整）。
          ② 全都不同：取**最长**的一个 —— 短的那个多半是"没做出来"的敷衍。
          ③ 全部为空/失败占位：返回第一个非 None（让上层走既有的失败分支，
             **不在这里伪造成功**）。

        ⚠ 刻意**串行**采样，不用线程：
          · 项目铁律「测试任务级互斥、串行优先」；
          · LLM 客户端未必线程安全；
          · 温度 0.2 下并发采样反而可能拿回近似同解（无多样性收益）。

        埋点：每次采样数量、是否达成多数、代表了多久 —— 供 A/B 归因。
        """
        samples: list = []
        for _i in range(n):
            try:
                _r = self._maybe_tool_llm(
                    ctx,
                    prefill_messages(
                        [
                            {"role": "system", "content": step_system},
                            {"role": "user", "content": user_msg},
                        ],
                        "【本步结果】",
                    ),
                    0.2, 32768,
                )
            except Exception as exc:  # noqa: BLE001  单次失败不放弃整组
                logger.debug("多agent子目标采样 %d/%d 异常: %s: %s",
                             _i + 1, n, type(exc).__name__, exc)
                _r = None
            if _r:
                _r = stitch("【本步结果】", _r)
            samples.append(_r)
            # ★ 2026-10-02 阶段二-2：**移除**「采样中途超时就不凑满 N」
            #   （原 `if ctx.is_time_critical(): break`）——那是"为省时间降质量"
            #   的残留；研究期时间无限、一切为正确率让路（用户口径）。

        picked, key, n_distinct = self._pick_consensus_sample(samples)

        # ★ 阶段二-1：保留全部候选（不再淘汰）。只留**非空原文**，保持采样顺序。
        #   `candidates_picked_index` = 代表解在保留列表中的下标（-1 = 无有效候选）。
        _kept: list = [str(s) for s in samples if s and str(s).strip()]
        _picked_idx = _kept.index(picked) if (picked in _kept) else -1

        # ★ 阶段二-2：子目标层**客观验证**（本轮核心增量）。
        #   `candidate_answers` = 各候选**抽取后的干净答案串**（客观验证的输入——
        #   原文带推理没法算）；客观验证判出"对的那个" ⇒ **用它续推**（"按正确率选"，
        #   而非按长度/字符串多数）；判不出 ⇒ 保留多个、标未定（verified=-1）沿用代表解。
        # ★ 2026-10-06（结论契约）：候选答案取**结构化结论**（值/等式表达式），
        #   而非整段「本步结论+依据+验算」原文 —— 否则客观判定拿到的仍是
        #   不可解析的中文正文（实测 candidate_answers 大量是 <check> 包的中文句
        #   ⇒ `n_judged = 0/73`）。
        _answers: list = [self._answer_from_raw(s) for s in _kept]
        _verified_idx = self._verify_candidates_objective(_answers)
        if 0 <= _verified_idx < len(_kept):
            picked = _kept[_verified_idx]
        if sg is not None:
            try:
                sg["candidates"] = _kept
                sg["candidates_picked_index"] = _picked_idx
                sg["candidate_answers"] = _answers
                sg["candidates_verified_index"] = _verified_idx
            except Exception:  # noqa: BLE001  个别 sg 实现可能禁写
                pass

        try:
            self.record(
                ctx, "subgoal_multi_agent",
                f"多agent子目标求解：采样 {len(samples)}/{n} 个，"
                f"不同结论 {n_distinct} 种，保留候选 {len(_kept)} 条"
                f"（原代表解第 {_picked_idx} 条），"
                f"客观验证{'选中第 ' + str(_verified_idx) + ' 条'
                        if _verified_idx >= 0 else '判不出（沿用代表解）'}，"
                f"{'达成多数一致' if n_distinct < len(samples) else '无多数（取最长）'}",
                n_samples=len(samples), n_distinct=n_distinct,
                n_kept=len(_kept), picked_index=_picked_idx,
                n_answers=len(_answers), verified_index=_verified_idx,
                consensus=(n_distinct < len(samples)))
        except Exception:  # noqa: BLE001
            pass
        return picked

    @staticmethod
    def _pick_consensus_sample(samples: list) -> tuple:
        """从多个采样里选代表解。返回 ``(样本原文, 归一化关键值, 不同值个数)``。

        纯函数（不碰 ctx / 网络），便于单测锁定选择规则 ——
        这是本机制**唯一需要正确的地方**：选错了，多 agent 只会放大错误。
        """
        valid = [s for s in (samples or []) if s and str(s).strip()]
        if not valid:
            # 全部失败：把第一个（可能是 None）原样交回，让上层走失败分支
            return (samples[0] if samples else None), "", 0

        def _key(text: str) -> str:
            """归一化关键值：优先取 \\boxed{}，否则取归一化后的末行。"""
            t = str(text)
            try:
                m = re.search(r"\\boxed\{([^{}]*)\}", t)
                if m:
                    return m.group(1).strip().lower()
            except Exception:  # noqa: BLE001
                pass
            # 去空白/标点后取末尾 60 字符 —— 子目标结果的关键值通常在结尾
            tail = re.sub(r"\s+", "", t)[-60:]
            return tail.lower()

        groups: dict = {}
        for s in valid:
            groups.setdefault(_key(s), []).append(s)
        n_distinct = len(groups)
        # 多数票：组内样本数最多 → 并列时取组内最长原文
        best_key, best = max(
            groups.items(), key=lambda kv: (len(kv[1]), max(len(x) for x in kv[1])))
        # 组内选最长（推理最完整）；并列时取先出现的，保证确定性
        picked = max(best, key=lambda x: len(str(x)))
        return picked, best_key, n_distinct

    # ==================================================================
    # 子目标**结论契约**：解析 / 客观判定 / 落 trace（2026-10-06 重写 A/B/C）
    # ==================================================================
    # 契约（见 prompts/sub_goal.py::SUBGOAL_CONCLUSION_CONTRACT）要求【本步结果】
    # 段内头两行固定为：
    #   本步结论: 值 = <expr> | 等式 = <L> = <R> | 判定 = 真|假|不确定
    #   本步依据: <前序编号 / 题设 / 本步推导>
    # 之后 ≤300 字为关键验算（= "有推导" 的证据）。
    _CONCL_LINE_RE = re.compile(
        r"本步结论\s*[:：]\s*(值|等式|判定)\s*=\s*(.+)")
    _SUPPORT_LINE_RE = re.compile(r"本步依据\s*[:：]\s*(.+)")
    # 「有推导」的最小验算篇幅（字符）：低于此视为"只给结论、未给推导"
    _MIN_DERIVATION_CHARS = 20

    @classmethod
    def _parse_step_contract(cls, section: str) -> dict:
        """解析【本步结果】段内的结论契约。返回结构化字典（永不抛异常）。

        返回字段：
          ok          是否给出合法 `本步结论:` 行（契约是否达成）
          kind        "value" | "equation" | "verdict" | ""
          expr        value→表达式；equation→"L = R"；verdict→真/假/不确定
          lhs / rhs   equation 形态的左右两侧（客观判定输入）
          verdict     verdict 形态的判定词
          support     `本步依据:` 行（空 = 模型没写）
          derivation  头两行之后的验算/论证正文
          has_derivation 验算篇幅 >= `_MIN_DERIVATION_CHARS`
          reason      未达成契约时的**原因**（供 B 留痕，不返回空串）
        """
        out = {"ok": False, "kind": "", "expr": "", "lhs": "", "rhs": "",
               "verdict": "", "support": "", "derivation": "",
               "has_derivation": False, "reason": ""}
        text = str(section or "")
        if not text.strip():
            out["reason"] = "本步结果为空"
            return out
        m = cls._CONCL_LINE_RE.search(text)
        if not m:
            out["reason"] = "未给出结构化结论行（本步结论: 值/等式/判定 = …）"
            # 未达成契约也要把验算正文抽出来（供 C 判"是否有推导"）
            out["derivation"] = cls._tail_after_conclusion(text)
            out["has_derivation"] = (
                len(out["derivation"].strip()) >= cls._MIN_DERIVATION_CHARS)
            return out
        kind_cn, body = m.group(1), m.group(2).strip()
        ms = cls._SUPPORT_LINE_RE.search(text)
        out["support"] = ms.group(1).strip() if ms else ""
        if kind_cn == "值":
            out["kind"], out["expr"] = "value", body
        elif kind_cn == "等式":
            out["kind"] = "equation"
            out["expr"] = body
            parts = body.split("=")
            if len(parts) >= 2:
                out["lhs"], out["rhs"] = parts[0].strip(), "=".join(parts[1:]).strip()
        elif kind_cn == "判定":
            out["kind"] = "verdict"
            _v = body.strip()
            for token in ("不确定", "真", "假"):
                if token in _v:
                    out["verdict"] = token
                    break
            out["expr"] = _v
        # 验算正文：结论行 + 依据行之后的内容
        out["derivation"] = cls._tail_after_conclusion(text)
        out["has_derivation"] = (
            len(out["derivation"].strip()) >= cls._MIN_DERIVATION_CHARS)
        out["ok"] = bool(out["kind"])
        if not out["kind"]:
            out["reason"] = "结论形态无法识别"
        return out

    @staticmethod
    def _extract_derivation_block(raw: str) -> str:
        """从模型原文里取「【推导过程】…（到下一个 【 段头或结尾）」块（无则空串）。"""
        if not raw:
            return ""
        m = re.search(r"【推导过程】\s*\n?(.*?)(?=\n?【|$)", str(raw), re.DOTALL)
        return m.group(1).strip() if m else ""

    @classmethod
    def _tail_after_conclusion(cls, text: str) -> str:
        """去掉 `本步结论:` / `本步依据:` 两行后剩下的正文（= 验算/论证段）。"""
        lines = str(text or "").split("\n")
        kept = []
        for ln in lines:
            if cls._CONCL_LINE_RE.search(ln) or cls._SUPPORT_LINE_RE.search(ln):
                continue
            kept.append(ln)
        return "\n".join(kept).strip()

    def _judge_subgoal_objective(self, sg: dict, contract: dict,
                                 result_text: str,
                                 answers: list,
                                 existing_idx: int = -1) -> tuple:
        """对一个子目标结论做 **0-LLM 客观判定**。

        返回 ``(verified_index, verdict, reason)``：
          · verdict: "correct" | "incorrect" | "undecided"
          · verified_index: >=0 = 客观判定的候选下标；-1 = 判不出
          · reason: **总是**非空说明（判不出时即为"为什么判不出"的留痕）

        客观信号（按可靠性排序，全部本地 SymPy / 0-LLM）：
          ① 契约等式断言：`本步结论: 等式 = L = R` → `_sympy_judge(L, R)`；
          ② 多候选符号多数：同一子目标多采样结果按 SymPy 等价归组取严格多数
             （复用 `_verify_candidates_objective`）；
          ③ `<check>` 协议断言：结果里显式声明的等式（复用 `_extract_check_asserts`）；
          ④ 以上皆不适用 → undecided + **明确原因**（不再静默计 -1）。
        """
        # 已由多 agent 路径判出 → 直接沿用（不重复判、不覆盖）
        if existing_idx is not None and existing_idx >= 0:
            return existing_idx, "correct", "多候选符号多数（多 agent 路径已判定）"
        # ① 契约等式断言
        _chk = []          # [(L, R, info)] 通过的 / 失败的
        if contract.get("kind") == "equation" and contract.get("lhs") \
                and contract.get("rhs"):
            _v, _info = self._sympy_judge(contract["lhs"], contract["rhs"])
            if _v == "fail":
                return (-1, "incorrect",
                        "本步结论等式经 SymPy 客观判定**不成立**"
                        + (f"（{_info}）" if _info else ""))
            if _v == "pass":
                _chk.append(("pass", ""))
        # ③ <check> 协议断言（结论行未给等式时兜底）
        if not _chk:
            for L, R in self._extract_check_asserts(result_text):
                _v, _info = self._sympy_judge(L, R)
                if _v == "fail":
                    return (-1, "incorrect",
                            f"结果中 <check> 断言「{L} = {R}」客观判定不成立"
                            + (f"（{_info}）" if _info else ""))
                if _v == "pass":
                    _chk.append(("pass", ""))
        if _chk:
            return 0, "correct", "等式断言经 SymPy 判定成立（恒等/数值为真）"
        # ② 多候选符号多数
        if answers and len(answers) >= 2:
            _idx = self._verify_candidates_objective(answers)
            if _idx >= 0:
                return _idx, "correct", "多候选符号等价取得严格多数"
            return (-1, "undecided",
                    "多候选可解析但**无严格多数**（意见分歧，无客观依据选边）")
        # ④ 判不出 → 留痕说明原因
        kind = contract.get("kind") or ""
        # ★ 2026-10-07（问题 2.9）：**违反 `<check>` 协议要显式可见**，不能静默
        #   落成与"未给断言"同款的 undecided —— 二者根因与处置完全不同
        #   （前者=格式违约，后者=模型确实没给可核验对象）。
        _viol = _check_protocol_violations(result_text)
        if _viol:
            return (-1, "undecided",
                    "违反 <check> 协议：<check> 内含非可核验对象（%r…），"
                    "无法客观判定（应改写为「本步结论: 判定 = 真」或纯数学等式）"
                    % (_viol[0][:40],))
        if not contract.get("ok"):
            return (-1, "undecided",
                    "未达成结论契约：" + (contract.get("reason") or "无结构化结论"))
        if kind == "verdict":
            return (-1, "undecided",
                    f"结论为『判定 = {contract.get('verdict') or '?'}』型自然语言判定，"
                    "无外部真值可比对，客观手段判不出真伪")
        if kind == "value":
            return (-1, "undecided",
                    f"结论为『值 = {contract.get('expr')}』型单值断言，"
                    "单次求解无可比对对象（多采样时方可按符号多数判定）")
        return (-1, "undecided", "无可用客观判据")

    def _apply_conclusion_contract(self, sg: dict, result_text: str,
                                   raw_text: str = "") -> None:
        """把结论契约结果落到 `sg`（供 `run()` 写进 trace）。异常一律吞掉。

        ★ 只写 `sg`，不改 `result_text` —— 返回给上层的字符串语义保持不变。
        `raw_text`（模型原始响应）仅用于**兜底找推导段**：prefill 会把
        「【本步结果】」钉在开头，模型若仍另外输出「【推导过程】」块，
        该块不在【本步结果】切片内，需从原文补取（否则 C 的「是否有推导」
        会误判为「无推导」）。
        """
        try:
            contract = self._parse_step_contract(result_text)
            if not contract.get("has_derivation") and raw_text:
                _db = self._extract_derivation_block(raw_text)
                if len(_db.strip()) > len(contract.get("derivation") or ""):
                    contract["derivation"] = _db
                    contract["has_derivation"] = (
                        len(_db.strip()) >= self._MIN_DERIVATION_CHARS)
            _ans = list(sg.get("candidate_answers") or [])
            if not _ans and contract.get("kind") == "value" and contract.get("expr"):
                _ans = [contract["expr"]]
            _existing = int(sg.get("candidates_verified_index", -1) or -1)
            if _objective_judge_on():
                idx, verdict, reason = self._judge_subgoal_objective(
                    sg, contract, result_text, _ans, existing_idx=_existing)
            else:
                idx, verdict, reason = _existing, "undecided", ""
            sg["conclusion"] = (
                contract.get("expr") if contract.get("ok") else "")
            sg["conclusion_kind"] = contract.get("kind", "")
            sg["conclusion_support"] = contract.get("support", "")
            sg["conclusion_contract_ok"] = bool(contract.get("ok"))
            sg["conclusion_reason"] = contract.get("reason", "")
            sg["has_derivation"] = bool(contract.get("has_derivation"))
            sg["derivation_chars"] = len(contract.get("derivation") or "")
            sg["objective_verdict"] = verdict
            sg["objective_reason"] = reason
            if _objective_judge_on():
                if idx >= 0:
                    # 单次求解（无多 agent 候选）也要让客观判定**可归因**：
                    # 候选集 = {本步自己的结论}，verified_index 指向它。
                    if not list(sg.get("candidates") or []):
                        sg["candidates"] = [result_text]
                        sg["candidate_answers"] = _ans or [result_text]
                        sg["candidates_picked_index"] = 0
                    sg["candidates_verified_index"] = idx
                else:
                    sg["candidates_verified_index"] = -1
        except Exception as _e:  # noqa: BLE001  契约解析失败绝不影响求解
            logger.debug("结论契约落盘异常（忽略）: %s: %s", type(_e).__name__, _e)

    # 决策缓存需一起跨 run() 复用的契约字段（见 `_build_trace_item` 同名键）。
    _CONTRACT_KEYS = (
        "conclusion", "conclusion_kind", "conclusion_support",
        "conclusion_contract_ok", "has_derivation", "derivation_chars",
        "objective_verdict", "objective_reason",
        "candidates", "candidates_picked_index", "candidate_answers",
        "candidates_verified_index",
    )

    @classmethod
    def _contract_snapshot(cls, sg: dict) -> dict:
        """快照与结论契约/客观判定相关的 sg 字段（供决策缓存跨 run() 复用）。"""
        return {k: sg.get(k) for k in cls._CONTRACT_KEYS if k in sg}

    @classmethod
    def _restore_contract(cls, sg: dict, snap: dict) -> None:
        """把快照写回 sg（只写存在的键，异常吞掉）。"""
        if not isinstance(snap, dict):
            return
        for k in cls._CONTRACT_KEYS:
            if k in snap:
                sg[k] = snap[k]

    def _answer_from_raw(self, raw: str) -> str:
        """从子目标采样原文取**可判定的答案串**（2026-10-06 结论契约）。

        结论契约达成 → 返回结构化结论（`值 =`/`等式 =` 的右半，或 `判定 =` 词），
        这是客观判定（SymPy 等价 / 多数）能直接消费的形态；
        未达成 → 退回既有的「本步结果」切片（保持旧行为）。
        """
        sec = self._extract_step_result(raw)
        c = self._parse_step_contract(sec)
        if c.get("ok") and c.get("expr"):
            return str(c["expr"]).strip()
        return sec

    @staticmethod
    def _extract_step_result(text: str) -> str:
        """从子目标采样原文里抽取「本步结果」**干净答案串**（阶段二-2）。

        与 `_call_step` 的抽取口径**一字不差**（同一条正则 + 同一条剥壳），
        抽不出标记则取尾部 500 字符。空/异常一律返回空串。
        用途：`candidate_answers` —— 客观验证的输入（原文带推理没法算）。
        """
        try:
            if not text:
                return ""
            m = re.search(r"【本步结果】\s*\n?(.*?)(?:$|【)",
                          str(text), re.DOTALL)
            if m:
                return SubGoalSolverAgent._strip_tool_residue(
                    m.group(1)).strip()
            return SubGoalSolverAgent._strip_tool_residue(
                str(text)).strip()[-500:]
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _verify_candidates_objective(answers: list) -> int:
        """子目标层**客观验证**：返回"已验证为对"的候选下标（判不出 = -1）。

        客观信号（**0-LLM，纯本地 SymPy**；只做裁决、不确定一律放行）：
        `AnswerOracle.verify_computational` 的**自洽共识** —— n 个候选答案按
        SymPy **符号等价**归组，只有落在**严格多数簇**里的候选才拿到 `correct`。
        · 恰有一个严格多数簇 ⇒ 该簇即"客观验证存活的那个"（按正确率选，
          **不是按长度/字符串多数**——这才是用户要的"按照正确率选取"）；
        · 判不出（无多数 / 全 unknown / 不可解析 / 异常）⇒ -1 ⇒ 上层沿用原代表解。

        ⚠ 与 `_pick_consensus_sample` 的区别：后者用**字符串化末 60 字**当键
          （`\boxed{5}` 与 `5` 会算成两族）；本方法用 SymPy 等价（同源口径见
          `AnswerOracle.answers_equivalent`），是**更可靠的"按正确率"信号**。
        """
        if not answers or len(answers) < 2:
            return -1
        try:
            try:
                from .answer_oracle import AnswerOracle
            except ImportError:
                from answer_oracle import AnswerOracle
            # ⚠ `verify_computational` 是**实例方法**（内部 `self.is_parseable`）——
            #   必须用实例调用，不能 `AnswerOracle.verify_computational(cand, ...)`
            #   （那会把 cand 当成 self ⇒ AttributeError ⇒ 静默判不出）。
            _oracle = AnswerOracle()
            cands = [type("_C", (), {"answer": a, "reasoning": ""})()
                     for a in answers]
            good: list = []
            for i, a in enumerate(answers):
                if not str(a or "").strip():
                    continue
                try:
                    res = _oracle.verify_computational(cands[i], cands)
                except Exception:  # noqa: BLE001  单候选判定异常不放弃整组
                    continue
                if str(getattr(res, "verdict", "")) == "correct":
                    good.append(i)
            if not good:
                return -1
            # 同簇多个（等价）⇒ 取**原文更长**者（推理更完整；确定性收尾）
            return max(good, key=lambda i: len(str(answers[i])))
        except Exception:  # noqa: BLE001
            return -1

    @staticmethod
    def _oracle_check_step(step_result: str) -> str:
        """用 AnswerOracle 对子目标结果做客观 sanity check，返回反馈（空=通过）。"""
        try:
            from .answer_oracle import AnswerOracle
            # 结果可解析为数学表达式 → 通过；否则视为非法（可能为幻觉/格式错误）
            if not AnswerOracle.is_parseable(step_result):
                return "该步结果无法解析为有效数学表达式"
        except Exception as exc:  # noqa: BLE001
            # 2026-09-04 审核：异常吞掉 = 子目标 sanity check 静默放行。留证据。
            logger.debug("子目标 sanity check 异常（放行）: %s: %s",
                         type(exc).__name__, exc)
        return ""

    # ------------------------------------------------------------------
    # S1-lite：子目标级 0-LLM 校验前移（2026-09-06 老师建议）
    # ------------------------------------------------------------------
    # 老师：lean 校验服务很多要排优先级；子目标宜独立、上下文少 → 校验可前移。
    # 落地形态（全部 0-LLM、秒级~21s、异常/环境缺失一律放行，绝不阻断）：
    #   L0  截断/空结果检查（全档，0 成本）——治"答案腰斩"型错误（L2 截断修复下沉）；
    #   L0P 占位/空转检测（全档，0 成本）——2026-09-07 禁网冒烟实证：PB-002 SG#2
    #       ='（无）'、SG#4='（子目标4 已求解）'、alg-060 SG#1='[计算] 1 = 1'，
    #       LLM 空转输出既非空也非截断、不带 lean 代码 → 旧 L0/L1 全放行流入 merge。
    #       短结果里出现占位词 / 重言式回填 → 视为未真正求解，带反馈重解。
    #   L1 Lean 代码片编译校验（仅 deep 档 + lean 环境可用，0 LLM 5-21s）——
    #     子目标结果若自带 lean 代码（```lean ... ``` 或 import 块），本地编译
    #     抓语法/类型错，禁网下纯本地（lean-lsp-mcp 禁网已验证 0 出网）。
    #     注：2026-09-07 冒烟实测子目标结果多为短结论行、极少带 lean fence，
    #     L1 触发面天然小；价值主要在 L0P 的占位拦截，L1 仅作兜底保留。
    # 不做：LLM 翻译整段子目标结果去 lean 化（翻译成本与整题 6.5 校验重复，列赛后）。

    _LEAN_FENCE = re.compile(
        r"```(?:lean4?|lean)?\s*\n(.*?)```", re.DOTALL)

    # L0P：短结果占位词（≤50 字符内命中才算，长结果里的行文不判）。
    # 只收高置信空转形态（宁漏勿误伤：如"方程无解""待定系数"是真结论）。
    # 2026-09-08：`[计算] X = X` 型**平凡 calc 回填**单列判据（见下）——
    # 旧注释担心 `[计算] 191/192 = 191/192` 是真分数验证无法与空转区分；
    # 但回填格式是 `[计算] expr = result`，**result 与 expr 逐字相同**意味着
    # 模型只是把结论原样丢给 <calc>（<calc>191/192</calc> 无任何运算发生），
    # 属 alg-060 SG#1='[计算] 1 = 1' 同型空转，可可靠判定。真运算（如
    # <calc>comb(50,3)</calc> → [计算] comb(50,3) = 19600）result≠expr 不受影响。
    _PLACEHOLDER_RE = re.compile(
        r"（无）|（略）|暂无|占位|空转|未求解|未给出"
        r"|子目标\s*\d+\s*已(?:求解|完成|给出)"
        r"|^同上$|^见上$"
    )
    # `[计算] X = X` 切分（左右各自归一后比较，见 _looks_placeholder）。
    # 2026-09-08 二次升级：SymPy 符号化简回填带空格（`1/(n + 1)`）或幂记号
    # 差异，旧 `\1` 逐字反引用会漏判"符号复读空转"（模型把 1/(n+1) 原样丢给
    # <calc> 当自证）；改为切出左右两侧后**去空白归一比较**——真运算
    # （comb(50,3) → 19600、integral 结果、sqrt(45) → 3*sqrt(5)）两侧不同，
    # 不受影响；无运算的复读（1/(n+1)=1/(n+1)、0=0）可靠拦截。
    _TRIVIAL_CALC_RE = re.compile(
        r"^\[计算\]\s*(?P<left>.+?)\s*=\s*(?P<right>.+?)\s*$", re.DOTALL)

    @classmethod
    def _looks_placeholder(cls, result: str) -> bool:
        """短结果占位/空转检测：占位词命中 或 平凡 calc 回填（无运算发生）。"""
        if not result:
            return False
        text = result.strip()
        # 平凡 calc 回填：整体就是一行 `[计算] X = X`（结果≤120 字符内判定）
        if len(text) <= 120:
            m = cls._TRIVIAL_CALC_RE.match(text)
            if m and m.group("left").strip():
                left = re.sub(r"\s+", "", m.group("left")).replace("^", "**")
                right = re.sub(r"\s+", "", m.group("right")).replace("^", "**")
                if left == right:          # 去空白后两侧相同 = 无运算发生
                    return True
        if len(text) > 50:            # 长结果视为有内容，不做占位词判定
            return False
        return bool(cls._PLACEHOLDER_RE.search(text))

    @classmethod
    def _extract_lean_code(cls, result: str) -> str:
        """从子目标结果提取 lean 代码片（fence 或裸 import 块）；无则空串。"""
        if not result:
            return ""
        m = cls._LEAN_FENCE.search(result)
        if m and m.group(1).strip():
            return m.group(1).strip()
        # 无 fence：整段以 import 开头（疑似裸 lean 代码）时收整段
        head = result.strip()[:80]
        if head.startswith("import ") or head.startswith("import\n"):
            return result.strip()
        return ""

    def _subgoal_light_check(self, ctx: TaskContext, sg: dict,
                             result: str) -> str:
        """子目标结果 0-LLM 校验，返回反馈文本（空=通过）。异常全部放行。"""
        try:
            if not result or not result.strip():
                return "【本步结果】为空，请给出完整结果。"
            # L0P 占位/空转检测（全档，0 LLM）——2026-09-07 冒烟实证拦截项
            if self._looks_placeholder(result):
                return ("【本步结果】疑似占位/空转：仅给出“（无）”“已求解”等占位词，"
                        "没有真正给出基于题目条件的推导与结论。"
                        "请真正求解：给出基于题目条件的推导与数值/表达式结论。")
            # L0 截断检查（全档，0 LLM）
            from utils.extract import is_truncated_answer as _trunc
            if _trunc(result):
                return ("【本步结果】被截断（超出输出上限），"
                        "请压缩推理、只保留结论与关键计算，完整给出【本步结果】。")
            # ★★ 2026-09-17（P-9）：穷尽性检查的**格式校验提前到循环内**。
            # 原实现只在 `orchestrator._parse_exhaust_result`（事后 `_collect_diag`）
            # 解析 ⇒ 「缺段」这一**可机检**的硬信号来得太晚。实测 003（唯一的
            # 「求所有」题）：`exhaust_diag.appended=true`（子目标 6→7）、
            # `exhaust_result.complete=false`（四段全缺），而答案照旧提交 ——
            # 只给 `2026`、漏了 `2030`。
            # 现缺段 ⇒ 返回反馈 ⇒ 触发既有的「带反馈重解一次」分支。
            if str(sg.get("title", "") or "").strip() == "解族穷尽性检查":
                _miss = _exhaust_missing_sections(result)
                if _miss:
                    self.record(ctx, "subgoal_exhaust_check",
                                "穷尽性检查缺段，打回重解: " + "、".join(_miss))
                    return ("【本步结果】未按要求完成穷尽性检查 —— 缺少段落："
                            + "、".join(_miss)
                            + "。请**严格按固定格式**重写，四段必须具备：\n"
                            "解族清单: …（列出本题所有可能的解族类型）\n"
                            "逐族判定: …（对每一族给『存在 / 不存在』及其依据）\n"
                            "前序结论复核: …（前序找到的解属于哪一族、同族是否还有别的）\n"
                            "结论: EXHAUSTIVE: yes 或 EXHAUSTIVE: no\n"
                            "（若结论为 no，另加一段『遗漏解族: …』）")
        except Exception:  # noqa: BLE001
            pass
        # L1 lean 代码片编译（仅 deep 档 + lean 可用；禁网纯本地）
        try:
            if str(getattr(ctx, "tier", "") or "") != "deep":
                return ""
            if not getattr(self.config, "enable_subgoal_lean_check", True):
                return ""
            code = self._extract_lean_code(result)
            if not code:
                return ""
            from tools.lean_local.lean_bridge import LeanBridge
            from tools.lean_local.lean_bridge import _trash_lean_file
            bridge = LeanBridge(self.client, self.config)
            if not bridge.lean_available:
                return ""
            work_dir = bridge._lean_project_dir or ""
            if not work_dir:
                return ""          # 无 lake 工程 → 不尝试（避免直编找不到 Mathlib）
            fname = f"sg_check_{int(time.time() * 1000) % 1000000}.lean"
            r = bridge._compile(code, work_dir, lean_filename=fname)
            try:
                _trash_lean_file(work_dir, fname)
            except Exception:  # noqa: BLE001
                pass
            if not r.get("ok"):
                err = str(r.get("error", ""))[:200]
                return (f"本步给出的 Lean 代码编译失败（{err}）。"
                        "请修正代码（或改用数学表述，不必强制给 Lean）。")
        except Exception as exc:  # noqa: BLE001  校验失败放行，绝不阻断
            logger.debug("子目标 0-LLM 校验异常（放行）: %s: %s",
                         type(exc).__name__, exc)
        # L2/L3 数值断言验证（2026-09-08 去门后新钩子）：
        # L3 协议版优先——模型 <check> 显式声明的等式（sympy 判 + Lean 背书）；
        # L2 提取式兜底——无 <check> 时 0-LLM 提取纯数值/整式断言。
        # 失败 = 计算未通过验证 → 反馈带真值让 LLM 带错重解。0-LLM 构造；
        # 无数值断言零成本；异常/语法不支持一律放行不误报；每题限额防烧预算。
        try:
            _nv_fb = self._check_assert_verify(ctx, result)
            if not _nv_fb:
                _nv_fb = self._numeric_lean_verify(ctx, result)
            if _nv_fb:
                return _nv_fb
        except Exception:  # noqa: BLE001
            pass
        return ""

    # ---------- L2 数值/代数断言 Lean 验证（2026-09-08）----------
    _L2_EXPR_CHARS = re.compile(r"^[0-9a-zA-Z^*/+\-() ]+$")

    _extract_lean_assert_pairs = _sgs_lean._extract_lean_assert_pairs

    _fix_lean_mul = staticmethod(_sgs_lean._fix_lean_mul)

    _numeric_lean_verify = _sgs_lean._numeric_lean_verify

    # ---------- L3 <check> 协议断言验证（2026-09-08 协议版）----------
    # 模型在【本步结果】用 <check>LHS = RHS</check> 显式声明待验证等式 →
    # 提取零歧义（解决提取式 2.8% 覆盖率问题）。判定：sympy 精确判定为主
    # （expand/simplify，确定性无浮点误差）→ 判"不成立"的再交 Lean
    # norm_num/ring 编译背书（mcp 后端）双确认 → 反馈带标准化简结果
    # （可行动），杜绝"只知道错、不知道对什么"的裸诊断。
    _CHECK_RE = re.compile(r"<check>(.*?)</check>", re.DOTALL)

    _extract_check_asserts = _sgs_lean._extract_check_asserts

    @staticmethod
    def _strip_check_tags(text: str) -> str:
        """剥 <check>...</check> 验证标签：去标签保留内部内容（数学等式文本无害）。

        仅当标签完整闭合时剥除；不闭合的残留 <check> 一并删除防泄漏。
        """
        if not text or "<check>" not in text:
            return text
        t = re.sub(r"<check>(.*?)</check>", r"\1", str(text), flags=re.DOTALL)
        # 兜底：未闭合/孤立标签删除
        t = t.replace("<check>", "").replace("</check>", "")
        return t

    @staticmethod
    def _pow_to_python(s: str) -> str:
        """裸 ^ → **（先保护已有 **）。"""
        s = s.replace("**", "@@P@@")
        s = re.sub(r"\^", "**", s)
        return s.replace("@@P@@", "**")

    _sympy_judge = _sgs_lean._sympy_judge

    _check_assert_verify = _sgs_lean._check_assert_verify

    # P4（2026-09-09 老师"描述即完成/零代码"）：疑似错断言 → 生成**多条策略
    # 尝试**声明（norm_num/norm_num1/ring/ring_nf/nlinarith/omega/grind/aesop
    # 按形态选择），一次编译，组内任一策略闭合 → 剔除（防 sympy 误报）；
    # 组内全部失败 → 双确认该断言不成立。
    _SYNTAX_ERR_KW = ("unknown identifier", "unexpected token",
                      "unknown constant", "invalid")

    _build_auto_proof = _sgs_lean._build_auto_proof

    _lean_backup_fails = _sgs_lean._lean_backup_fails


    # ---------- ③ 子目标交叉核对（2026-09-08 老师建议3）----------
    # 老师建议："子目标交叉核对机制"——不同子目标对同一量给出互相矛盾的结论
    # 时，系统要能发现并打回，而不是让矛盾静默流入最终合并（如 alg-060 型）。
    # 落地两方向（独立开关，可单开/同开做 A/B）：
    #   A 确定性冲突闸（0 LLM，subgoal_conflict_gate）：
    #     汇总全题子目标结果里的 <calc> 回填（[计算] X = v）+ <check> 协议断言
    #     + L2 已提取等式断言，同名单变量 LHS 出现**可判定不同的常数**值
    #     （x=1 vs x=2）→ 判显式矛盾，merge 提示词强制裁决后才许合并。
    #     已知盲区：隐含矛盾（alg-060：xy=25 与 D=2 不共用同一变量名，纯规则
    #     必漏）；非单变量 LHS（x^2=4 含 ± 分支）、近似舍入差异 → 宁漏勿误报。
    #   B LLM 交叉核对轮（merge 前 +1 次小调用，subgoal_crosscheck_llm）：
    #     把各子目标结论行单独抽出交给 LLM 集中裁决矛盾——能看隐含矛盾
    #     （alg-060 这型有机会看出，不保证）。预算不足自动跳过，不阻断 merge。
    _LHS_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    # 行内 [计算] 回填（允许前缀自然语言，如 "解得 [计算] x = 1"）：
    # RHS 截断到行尾或中英文句读/分号，防吞掉后续文字。
    _CALC_INLINE_RE = re.compile(
        r"\[计算\]\s*([^=\n，。；;,]+?)\s*=\s*([^\n，。；;,]+)")
    # 松散 ident = const 片段（纯文本结论 "解得 x = 1"）：前 2 个非空字符
    # 命中情形/条件标记（当/若/情形/情况/分支…）→ 跳过，防分支讨论误报。
    _LOOSE_EQ_RE = re.compile(
        r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\s，。；;,+)(]+)")
    _CASE_MARK = set("当若情形况分")

    @staticmethod
    def _lookback_case_mark(text: str, pos: int) -> bool:
        """LHS 前 2 个非空白字符是否含情形/条件标记（当/若/情形…）。"""
        i = pos - 1
        n = 0
        while i >= 0 and n < 2:
            ch = text[i]
            if not ch.isspace():
                if ch in SubGoalSolverAgent._CASE_MARK:
                    return True
                n += 1
            i -= 1
        return False

    def _collect_claims(self, result: str) -> list:
        """从子目标结果汇总确定性等式断言 [(L, R)]（去重）。

        四来源并集：①<calc> 回填落地行/行内 `[计算] X = v`
        （允许自然语言前缀）；②<check>…=…</check>
        协议块（L3）；③L2 提取式等式断言（_extract_lean_assert_pairs，
        宁缺毋滥）；④松散 `X = 常数` 文本片段（"解得 x = 1"），带情形/
        条件标记（当/若/情形…）的前缀跳过，防分支讨论误报。合并去重。
        """
        pairs: list = []
        if not result:
            return pairs
        text = str(result)
        for m in self._CALC_INLINE_RE.finditer(text):
            L = m.group(1).strip().rstrip("= ")
            R = m.group(2).strip()
            if L and R:
                pairs.append((L, R))
        for L, R in self._extract_check_asserts(text):
            pairs.append((L, R))
        for L, R, *_rest in self._extract_lean_assert_pairs(text):
            pairs.append((L, R))
        # 松散源只在**不含** [计算]/<check> 标记的行上跑（避免与专用源重复，
        # 且函数调用形 RHS（sqrt(…)）会在左括号处被截断成假断言）。
        for ln in text.split("\n"):
            if "[计算]" in ln or "<check>" in ln:
                continue
            for m in self._LOOSE_EQ_RE.finditer(ln):
                if self._lookback_case_mark(ln, m.start()):
                    continue
                L, R = m.group(1).strip(), m.group(2).strip()
                if L and R:
                    pairs.append((L, R))
        seen, uniq = set(), []
        for p in pairs:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        return uniq

    @staticmethod
    def _rhs_const(s: str):
        """RHS 解析为常数则返回 sympy 值对象，否则 None（变量式/不可解析）。

        符号化字符串（`^`/`**` 幂、分数、根式）交给 sympy；带自由符号或
        解析失败 → None（不做常量比较，宁漏勿误报）。
        """
        try:
            from utils.sympy_tools import _try_parse
        except Exception:  # noqa: BLE001
            return None
        try:
            a, _ = _try_parse(s.replace("^", "**"))
        except Exception:  # noqa: BLE001
            return None
        if a is None:
            return None
        try:
            if getattr(a, "free_symbols", None):
                return None
        except Exception:  # noqa: BLE001
            return None
        return a

    def _cross_conflicts(self, subgoals: list[dict],
                         results_map: dict[int, str]) -> list:
        """确定性冲突闸（0 LLM）：同名单变量被给出不同常数 → 返回矛盾清单。

        判同值用 sympy 精确差化简（0.5 与 1/2、3*sqrt(5) 与 sqrt(45) 视为
        同值不报警）；同值不同写法不误报。返回人类可读行（空=无冲突）。
        """
        try:
            import sympy as _sp
        except Exception:  # noqa: BLE001
            return []
        claims: list = []
        for sg in subgoals:
            sid = sg.get("id")
            text = (results_map.get(sid) or sg.get("result") or "")
            for L, R in self._collect_claims(text):
                claims.append((sid, L, R))
        if not claims:
            return []
        var_map: dict = {}          # LHS规范化名 -> [(sid, 值对象, R原文)]
        for sid, L, R in claims:
            Lc = re.sub(r"\s+", "", str(L))
            if not self._LHS_IDENT_RE.match(Lc):
                continue            # 复合 LHS（x^2 / x+1 / S(1)…）不做常量冲突判定
            v = self._rhs_const(str(R))
            if v is None:
                continue
            var_map.setdefault(Lc, []).append((sid, v, str(R).strip()))
        conflicts: list = []
        for Lc, lst in var_map.items():
            groups: list = []       # 值分组（sympy 差化简判同）
            for sid, v, Rs in lst:
                for g in groups:
                    try:
                        if _sp.simplify(g[0][1] - v) == 0:
                            g.append((sid, v, Rs))
                            break
                    except Exception:  # noqa: BLE001  化简失败按不同值处理（宁报）
                        pass
                else:
                    groups.append([(sid, v, Rs)])
            if len(groups) < 2:
                continue
            # 只报**跨子目标**冲突：同一步内对同一量出现多值多为分支枚举
            # （"x=1 或 x=2"）或自我修正，不构成本机制目标（merge 自带矛盾
            # 检查兜底）；跨子目标对同一量的不同常数才是真正流毒信号。
            for g in groups:
                g.sort(key=lambda t: (str(t[0]), len(t[2])))
            base = min(groups, key=lambda g: (str(g[0][0]), len(g[0][2])))
            base_sid, _b_v, b_r0 = base[0]
            other = None
            for g in groups:
                if g is base:
                    continue
                cand = [t for t in g if t[0] != base_sid]
                if cand:
                    other = cand[0]
                    break
            if other is None:
                continue            # 所有不同取值都出自同一子目标 → 不报
            o_sid, _o_v, o_r = other
            conflicts.append(
                f"「{Lc}」在子目标 #{base_sid} 中取 {b_r0}，"
                f"而在子目标 #{o_sid} 中取 {o_r}——同一变量不能同时成立，"
                "必有至少一方错误（含推导/抄写错误），需裁决修正")
        return conflicts[:6]          # 单次最多报 6 条，防提示词膨胀

    def _llm_crosscheck(self, ctx: TaskContext, subgoals: list[dict],
                        results_map: dict[int, str],
                        plan_summary: str) -> str:
        """LLM 交叉核对轮：merge 前 +1 次小调用，返回矛盾裁决报告。

        只裁决矛盾（不求解/不合并/不给答案）；调用失败或预算不足返回空串
        （空串=未跑/无输出，由调用方与"未发现矛盾"区分）。~1-2K token。
        """
        if ctx.gen_time_up():
            return ""
        concl_lines = []
        for sg in subgoals:
            sid = sg.get("id")
            text = (results_map.get(sid) or sg.get("result") or "")
            text = re.sub(r"\s+", " ", str(text)).strip()
            if not text:
                continue
            title = re.sub(r"\s+", " ", str(sg.get("title") or "")).strip()
            concl_lines.append(f"# 子目标 {sid}"
                               + (f"「{title}」" if title else "")
                               + f"：{text[:200]}")
        if not concl_lines:
            return ""
        user_msg = SUBGOAL_CROSSCHECK_USER_TEMPLATE.format(
            problem=(str(getattr(ctx, "problem", "") or "")[:800]),
            subgoal_plan_summary=(str(plan_summary or "")[:600]),
            subgoal_conclusions="\n".join(concl_lines),
        )
        try:
            t0 = time.time()
            resp = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system",
                         "content": SUBGOAL_CROSSCHECK_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                    "【矛盾列表】",
                ),
                # ★ 2026-10-02：2048→8192（DeepSeek 适配方案 A，统一上限）。
                0.0, 8192,
            )
            if resp:
                resp = stitch("【矛盾列表】", resp)
            self.record(ctx, "subgoal_crosscheck",
                        f"LLM 交叉核对轮耗时 {time.time() - t0:.0f}s"
                        + ("" if resp else "，返回空（不注入矛盾提示）"))
            return resp or ""
        except Exception as exc:  # noqa: BLE001  失败不阻断 merge
            logger.debug("LLM 交叉核对轮异常（跳过）: %s: %s",
                         type(exc).__name__, exc)
            return ""


    # ---------- 阶段三：合并 ----------
    def _merge_results(self, ctx: TaskContext, subgoals: list[dict],
                       plan_summary: str, results_map: dict[int, str],
                       merge_strategy: str) -> str:
        """调用 LLM 合并所有子目标结果。

        2026-10-01：原 2026-09-04 下沉的 `<calc>` 合并纪律（引导 + 回填 + 裸算
        打回）已随计算工具板块整体删除。
        2026-09-08 改进建议3+6：①蓝图最终结论注入 user 模板（merge 输出
        必须与蓝图结论对齐，防 alg-009/053/068 输出端数值漂移）；②merge 产出
        空转/占位/平凡 calc 回填（如 [计算] 0 = 0）时带反馈重试一次（alg-009
        merge 计划 = "[计算]0=0" 仍照常入候选的教训）。
        2026-09-08 老师建议3 交叉核对：merge 前先跑子目标交叉核对
        （A 确定性冲突闸 0-LLM + B LLM 交叉核对轮 +1 调用，各自独立开关），
        发现的矛盾强制注入 merge 提示词要求逐条裁决——不让子目标间矛盾
        静默流入最终合并（alg-060 型显式/隐含矛盾）。
        """
        user_msg, _merge_system = self._prepare_merge_prompt(
            ctx, subgoals, plan_summary, results_map, merge_strategy)

        for attempt in range(2):
            # v2.4.1：prefill「【最终答案】」答案前置，抑制 CoT
            resp = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": _merge_system},
                        {"role": "user", "content": user_msg},
                    ],
                    "【最终答案】",
                ),
                0.2, 32768,
            )
            if resp:
                resp = stitch("【最终答案】", resp)
            if resp is None:
                if attempt == 0:
                    self.record(ctx, "subgoal_merge",
                                "合并 LLM 调用失败，带反馈重试一次")
                    user_msg = user_msg + (
                        "\n\n[上一轮合并未返回有效文本] 请完整输出"
                        "【矛盾检查】【结论合并】【最终答案】。")
                    continue
                return self._fallback_from_last_subgoal(subgoals)

            # 优先提取「最终答案」
            answer = extract_final_answer(resp)
            if answer:
                # 2026-09-08：merge 空转（占位词 / [计算] X = X 平凡回填）→
                # 不允许带着空转结论入候选，带反馈重试一次
                if self._looks_placeholder(answer):
                    if attempt == 0:
                        self.record(
                            ctx, "subgoal_merge",
                            f"合并输出为空转/占位（{answer[:60]}），带反馈重试")
                        user_msg = user_msg + (
                            f"\n\n[上一轮合并输出为空转：{answer[:120]}]\n"
                            "你没有真正合并各子目标结果。请：①逐条做矛盾检查；"
                            "②基于各子目标结果与蓝图结论真实推导；"
                            "③基于各子目标结果与蓝图结论真实推导，"
                            "在【最终答案】给出结论。")
                        continue
                    return self._fallback_from_last_subgoal(subgoals)
                return answer
            if attempt == 0:
                self.record(ctx, "subgoal_merge",
                            "合并未提取到【最终答案】，带反馈重试一次")
                user_msg = user_msg + (
                    "\n\n[上一轮未找到【最终答案】段] 请在末尾用【最终答案】"
                    "明确给出结论（一个数值/表达式/集合），不要只给过程。")
                continue
            return smart_fallback_answer(resp) or self._fallback_from_last_subgoal(subgoals)
        return self._fallback_from_last_subgoal(subgoals)

    def _prepare_merge_prompt(self, ctx: TaskContext, subgoals: list[dict],
                               plan_summary: str, results_map: dict[int, str],
                               merge_strategy: str) -> tuple:
        """合并提示词准备段（2026-10-08 批1：从 `_merge_results` 原地拆出）。
        装配 all_results / blueprint_conclusion(K11掩码) / 客观题注入 / user_msg /
        交叉核对 conflict_note / 可信度标记 / _merge_system；返回二元组。
        段体**逐字搬**，record 步序不变。
        """
        all_results = self._format_all_results(results_map, subgoals)
        # 蓝图最终结论（root 节点 statement）：取 ctx.blueprint，兼容 dict/list 两种形态
        # 2026-09-17（P-20）：同上，蓝图根节点结论里若含 \boxed /「最终答案」先剥离
        blueprint_conclusion = _strip_answer_forms(
            self._blueprint_conclusion(ctx))
        # ★ 2026-10-04（K11 注入点守卫）：P-20 只剥「答案形态标记」，自然语句里的
        #   **断言数值**仍会原样注入 merge 提示词（见 prompts/sub_goal.py:286-287）
        #   ⇒ 再掩码一层（不删句，只换被断言的数）。这是 blueprint_conclusion 的
        #   唯一注入点，故在此收口。
        if _k11_mask_on():
            blueprint_conclusion, _n_bc = _mask_asserted_values(blueprint_conclusion)
            if _n_bc:
                self.record(ctx, "blueprint_lock_guard",
                            f"蓝图根结论内嵌 {_n_bc} 处断言数值 → 已屏蔽为占位符"
                            "（K11 merge 注入点守卫）")
        # 2026-09-12 客观题特化（三处同源注入之③：merge 合并）——merge 直接产出
        # 最终答案署名候选，特化纪律必须在这里也在场，否则"检测到了"却"没照做"。
        _obj_inj_m = ""
        try:
            from .question_type import objective_injection as _oi_m
            _obj_inj_m = _oi_m(
                ctx.problem or "", getattr(ctx, "question_type", "") or "",
                bool(getattr(self.config, "objective_tactic_enabled", True)))
        except Exception:  # noqa: BLE001
            _obj_inj_m = ""
        # 2026-09-13 B0：答案形态要求必须在 merge 阶段也在场（merge 直接产出最终答案）
        try:
            from .question_type import answer_form_requirement as _afr_m
            _obj_inj_m += _afr_m(
                ctx.problem or "", getattr(ctx, "question_type", "") or "")
        except Exception:  # noqa: BLE001
            pass
        user_msg = SUBGOAL_MERGE_USER_TEMPLATE.format(
            problem=(ctx.problem or "") + _obj_inj_m,
            subgoal_plan_summary=plan_summary,
            blueprint_conclusion=blueprint_conclusion,
            all_results=all_results,
            merge_strategy=merge_strategy or "将各子目标结果按逻辑顺序组合，得出原题的最终答案。",
        )
        # ③ 子目标交叉核对（2026-09-08 老师建议3）：合并前先核对，矛盾强制
        # 注入提示词要求逐条裁决（A 0-LLM 确定性冲突闸 + B LLM 交叉核对轮）。
        # 二者独立开关可单开/同开 A/B；任何一步失败/预算不足都不阻断 merge。
        conflict_note = ""
        try:
            enable_gate = bool(getattr(
                self.config, "subgoal_conflict_gate", False))
            enable_xllm = bool(getattr(
                self.config, "subgoal_crosscheck_llm", False))
            if enable_gate or enable_xllm:
                parts = []
                if enable_gate:
                    cfl = self._cross_conflicts(subgoals, results_map)
                    if cfl:
                        parts.append(
                            "【确定性冲突闸】系统自动核对各子目标对同一变量"
                            "的取值，发现以下显式矛盾（同名 LHS 出现不同常数"
                            "值，数学上不可能同时成立）：\n"
                            + "\n".join("  - " + c for c in cfl))
                        self.record(
                            ctx, "subgoal_crosscheck",
                            f"确定性冲突闸: 发现 {len(cfl)} 处同名不同值矛盾")
                    else:
                        self.record(
                            ctx, "subgoal_crosscheck",
                            "确定性冲突闸: 未发现显式矛盾")
                if enable_xllm:
                    rep = self._llm_crosscheck(
                        ctx, subgoals, results_map, plan_summary)
                    if rep and rep.strip():
                        # 剥掉"未发现矛盾"类措辞后仍有实质内容 → 视为报了
                        # 矛盾（防"除上述外未发现矛盾"混合措辞漏注入）
                        _resid = re.sub(
                            r"未发现(?:明显|任何)?矛盾|无矛盾|没有矛盾",
                            "", rep, flags=re.IGNORECASE)
                        if len(_resid.strip()) <= 40:
                            self.record(
                                ctx, "subgoal_crosscheck",
                                "LLM 交叉核对轮: 未发现矛盾")
                        else:
                            parts.append(
                                "【LLM 交叉核对】独立评审轮对各子目标结论的"
                                "矛盾裁决报告：\n" + rep.strip()[:800])
                            self.record(
                                ctx, "subgoal_crosscheck",
                                f"LLM 交叉核对轮: 报告潜在矛盾"
                                f"（{rep.strip()[:80]!r}）")
                if parts:
                    conflict_note = (
                        "\n\n【⚠ 系统交叉核对结果（最高优先级，必须先处理）】"
                        "合并前已发现子目标结论间存在潜在矛盾。你必须在"
                        "【矛盾检查】中**逐条裁决**：指出冲突双方各自的主张、"
                        "依据原题条件与推导复核判定哪一方错误、给出"
                        "修正后的取值；若实为不同对象/不同分支并不冲突，请"
                        "逐条说明理由。**禁止不处理矛盾就直接输出【最终答案】"
                        "。**\n" + "\n".join(parts))
        except Exception as exc:  # noqa: BLE001  交叉核对失败不阻断 merge
            logger.debug("子目标交叉核对异常（跳过）: %s: %s",
                         type(exc).__name__, exc)
        if conflict_note:
            user_msg = user_msg + conflict_note
        # ★★ 2026-10-06（子目标交付重写 C）：把"仅断言、无推导"与"客观判定不成立"
        #   的子目标**显式交给合并层裁决**。实测题 official112-007：子目标直接给
        #   结论、无推导，且其中一条是臆造（真值 0 写成 1），而合并层此前**看不到
        #   "哪条没有推导支撑"** —— 只能照抄。现按 trace 打标后注入，要求逐条复核。
        try:
            _weak = []
            for _t in (getattr(ctx, "subgoal_trace", None) or []):
                if not isinstance(_t, dict):
                    continue
                _v = str(_t.get("objective_verdict", "") or "")
                _hd = bool(_t.get("has_derivation", False))
                if _v == "incorrect":
                    _weak.append(
                        f"  · 子目标 #{_t.get('id')}「{_t.get('title', '')}」"
                        f"—— **客观判定不成立**（{_t.get('objective_reason', '')}），"
                        "必须纠正后再合并")
                elif _v != "correct" and not _hd:
                    # 未被客观判定为成立、且无推导支撑 ⇒ 仅断言
                    _weak.append(
                        f"  · 子目标 #{_t.get('id')}「{_t.get('title', '')}」"
                        "—— **仅断言、无推导支撑**（未给出验算），须独立复核")
            if _weak:
                user_msg = user_msg + (
                    "\n\n【⚠ 结论可信度标记（合并前必须逐条处理）】\n"
                    + "\n".join(_weak[:12])
                    + "\n对上述子目标：**不得**直接采用其结论；须用代入 / 另一条路径"
                    "重算 / 与题意对照等方式复核，判定其可信后再合并；"
                    "若复核发现错误，以复核结果为准。")
                self.record(ctx, "subgoal_merge",
                            f"合并前注入可信度标记 {len(_weak)} 条"
                            "（无推导支撑/客观判定不成立）")
        except Exception:  # noqa: BLE001  标记注入失败不阻断 merge
            pass
        _merge_system = SUBGOAL_MERGE_SYSTEM
        # ★ 2026-09-29（截图 #8）：合并阶段是"把子目标答案总结成最终答案"的出口，
        # 是定理线索真正能落到**最终答案**上的最后机会，故同样注入。
        if getattr(self.config, 'enable_theorem_hint', True):
            _th = (getattr(ctx, 'theorem_hint_block', '') or '').strip()
            if _th:
                _merge_system = _merge_system + "\n\n" + _th
        return user_msg, _merge_system

    @staticmethod
    def _blueprint_conclusion(ctx: TaskContext) -> str:
        """从 ctx.blueprint 提取 root 节点结论文本（供 merge 输出对齐）。

        兼容 dict（{root_id, nodes}) 与 list（nodes 为 [ {...} ]）两种形态；
        提取失败返回占位文本（不阻断 merge）。
        """
        try:
            bp = getattr(ctx, "blueprint", None)
            if not bp:
                return "（无——按题目与子目标规划合并）"
            if not isinstance(bp, dict):
                return "（无——按题目与子目标规划合并）"
            root_id = bp.get("root_id") or ""
            nodes = bp.get("nodes") or []
            if isinstance(nodes, dict):
                node = nodes.get(root_id) if root_id else None
            else:  # list 形态：[{"id":..., "statement":...}, ...]
                node = None
                for n in nodes:
                    if isinstance(n, dict) and n.get("id") == root_id:
                        node = n
                        break
            stmt = (node or {}).get("statement") if isinstance(node, dict) else ""
            if stmt and str(stmt).strip():
                return str(stmt).strip()[:400]
            return "（蓝图无显式最终结论——按题目与子目标规划合并）"
        except Exception:  # noqa: BLE001  提取失败不阻断 merge
            return "（无——按题目与子目标规划合并）"

    # ---------- 辅助方法 ----------
    @staticmethod
    def _build_trace_item(sg: dict, step_result: str, reused: bool = False) -> dict:
        """构建一条 `ctx.subgoal_trace` 记录（唯一出口，防两处漂移）。

        2026-10-06（子目标交付重写 A/B/C）：在原有字段基础上补上结论契约与
        客观判定的可归因字段 —— 这些字段进 `diag.subgoal_trace`（结果文件），
        使"这一步到底交付了什么、有没有被客观判定过、有没有推导支撑"**可被
        事后核验**（此前只能看到 `result` 与空的 `expected_output`）。
        """
        item = {
            "id": sg["id"],
            "title": sg["title"],
            "description": sg["description"],
            "type": sg["type"],
            "calc_kind": sg.get("calc_kind", "inline"),
            "depends_on": sg["depends_on"],
            "expected_output": sg["expected_output"],
            "result": step_result,
            # ★ 阶段二-1/二-2：保留全部候选（「淘汰」→「保留」）+ 抽取答案 + 客观验证下标。
            "candidates": list(sg.get("candidates") or []),
            "candidates_picked_index": sg.get("candidates_picked_index", -1),
            "candidate_answers": list(sg.get("candidate_answers") or []),
            "candidates_verified_index": sg.get("candidates_verified_index", -1),
            # ---- 2026-10-06 结论契约（A/C）----
            "conclusion": sg.get("conclusion", ""),
            "conclusion_kind": sg.get("conclusion_kind", ""),
            "conclusion_support": sg.get("conclusion_support", ""),
            "conclusion_contract_ok": sg.get("conclusion_contract_ok", False),
            "has_derivation": sg.get("has_derivation", False),
            "derivation_chars": sg.get("derivation_chars", 0),
            # ---- 2026-10-06 客观判定（B）----
            "objective_verdict": sg.get("objective_verdict", ""),
            "objective_reason": sg.get("objective_reason", ""),
            # ---- 2026-10-07 `<check>` 协议违规（问题 2.9，可见化）----
            "check_protocol_violations": list(
                sg.get("check_protocol_violations") or []),
        }
        if reused:
            item["reused"] = True
        return item

    @staticmethod
    def _subgoal_stats(subgoals: list[dict]) -> dict:
        """S4-lite 独立性指标（老师 9/6：减少子目标数、降低上下文依赖）。

        返回 n_subgoals / dep_edges（依赖边总数）/ avg_indegree（平均入度，
        越小独立性越高，0 = 全独立）/ dep_free（零依赖子目标数）。
        进 diag 供 A/B 对照（S2 deps 模式是否真降了上下文与依赖）。
        """
        n = len(subgoals)
        edges = sum(len(sg.get("depends_on") or []) for sg in subgoals)
        dep_free = sum(
            0 if (sg.get("depends_on") or []) else 1 for sg in subgoals)
        return {
            "n_subgoals": n,
            "dep_edges": edges,
            "avg_indegree": round(edges / n, 2) if n else 0.0,
            "dep_free": dep_free,
        }

    @staticmethod
    def _format_plan_summary(subgoals: list[dict], merge_strategy: str) -> str:
        """格式化子目标规划摘要（用于后续步骤提示）"""
        lines = []
        for sg in subgoals:
            deps = f"依赖: {sg['depends_on']}" if sg["depends_on"] else "无依赖"
            lines.append(
                f"  #{sg['id']} [{sg['type']}] {sg['title']}"
                f"  → {sg['description']} ({deps})"
            )
        if merge_strategy:
            lines.append(f"\n合并策略: {merge_strategy}")
        return "\n".join(lines)

    @staticmethod
    def _format_previous_results(results_map: dict[int, str],
                                 subgoals: list[dict]) -> str:
        """格式化已求解的子目标结果（全量前序，subgoal_ctx_mode="all" 时用）"""
        if not results_map:
            return "（尚无前置结果）"
        lines = []
        for sg in subgoals:
            if sg["id"] in results_map:
                lines.append(f"  子目标 #{sg['id']}「{sg['title']}」结果: {results_map[sg['id']]}")
        return "\n".join(lines) if lines else "（尚无前置结果）"

    @staticmethod
    def _format_dep_results(results_map: dict[int, str],
                            subgoals: list[dict], sg: dict) -> str:
        """按 depends_on 只注入**直接依赖**的结果（老师 9/6 建议：子目标独立性、
        最小上下文依赖）。无依赖 / 依赖未解出 → 返回空串（零前序上下文），
        让独立子目标可并行、不被无关中间量污染。id 缺失容错：依赖未解出跳过。

        与 _format_previous_results 的区别：后者把**所有**已解子目标都塞进
        提示词（O(n²) 上下文膨胀）；本函数只带声明依赖的少数几条。
        """
        deps = [d for d in (sg.get("depends_on") or []) if d in results_map]
        if not deps:
            return ""
        title_map = {s.get("id"): (s.get("title") or "") for s in subgoals}
        lines = []
        for d in deps:
            _txt = str(results_map[d])
            _title = title_map.get(d, "")
            # 2026-09-14 P1：**切断"基准污染"链**。
            # 实测 #098 的基准子目标违规吐 `\boxed{D}`；而 #103 的「判定选项 E」
            # 直接输出 `\boxed{ABCD}`（照抄了基准的答案形态）⇒ 聚合层认不出 E。
            # 故：基准结果里若出现 `\boxed{...}`，注入下游**前**剥离外壳并加显式告警。
            if "基准" in _title and "\\boxed" in _txt:
                _txt = re.sub(r"\\boxed\{([^{}]*)\}", r"\1", _txt)
                _txt = ("（⚠ 本基准曾误输出最终答案，其 `\\boxed` 外壳已被系统剥离；"
                        "请只把它当作**判断依据**，**不要照抄**为任何选项的答案）"
                        + _txt)
            lines.append(f"  子目标 #{d}「{_title}」结果: {_txt}")
        # 2026-09-14 P1：**依赖未产出时的降级**（实测 #110）。
        # #110 的基准子目标求解失败 ⇒ 注入字符数 = 0 ⇒ 依赖它的选项子目标
        # 拿到空上下文、整个判定链断掉（gold A / 模型 D）。
        # 故：声明的依赖**全部未解出**时不再返回空串，而是显式告知下游
        # "共享依据缺失，请独立完成"，避免静默断链。
        _declared = [d for d in (sg.get("depends_on") or [])]
        if _declared and not deps:
            _names = "、".join(
                "#{}「{}」".format(d, title_map.get(d, "")) for d in _declared)
            return ("  （⚠ 前置子目标 {} **未能产出有效结果**，本次无法提供共享依据；"
                    "请**基于题目本身独立完成**本步判定，"
                    "不要因缺少依据而放弃或空转）").format(_names)
        return "\n".join(lines)

    # 选项判定结论解析（2026-09-14 实测 #103/#107/#110 暴露的问题）。
    # 模型**经常不遵守**"开头写『结论：正确/错误』"的格式，实际输出的形态包括：
    #   「结论：正确 依据：…」/「选项 D：正确」/「X = Y」（等价判断，暗示正确）/
    #   直接复述基准（**无任何结论**）。
    # 聚合层若不能识别，就会**丢项**（#103 丢 E）或**误采纳**（#107 判 D 对却输出 C）。
    _VERDICT_PATTERNS = (
        (re.compile(r"结论\s*[:：]\s*(正确|成立|符合|是正确|对的)"), "正确"),
        (re.compile(r"结论\s*[:：]\s*(错误|不成立|不符合|不正确|是错)"), "错误"),
        (re.compile(r"选项\s*[A-E]\s*[:：]\s*(正确|成立|符合)"), "正确"),
        (re.compile(r"选项\s*[A-E]\s*[:：]\s*(错误|不成立|不符合)"), "错误"),
        (re.compile(r"^\s*(正确|成立|符合)\s*$", re.M), "正确"),
        (re.compile(r"^\s*(错误|不成立|不符合)\s*$", re.M), "错误"),
    )

    @classmethod
    def _extract_option_verdict(cls, text: str):
        """从选项子目标的结果里解析出「正确 / 错误」；解析不到返回 None。

        按**优先级**匹配（先"结论："和"选项X："这类强信号，再退到独立词）。
        解析不到 ⇒ 调用方应显式标注"判定缺失"，让合并层单独复核，
        **不得**默认当作"跳过"（那正是 #103 丢 E 的机制）。
        """
        t = str(text or "")
        if not t:
            return None
        # 先看强信号（"结论：" / "选项X："）
        for pat, verdict in cls._VERDICT_PATTERNS[:4]:
            if pat.search(t):
                return verdict
        # 再退到独立词（但同一结果里两种都有 ⇒ 歧义，返回 None）
        has_ok = bool(cls._VERDICT_PATTERNS[4][0].search(t))
        has_no = bool(cls._VERDICT_PATTERNS[5][0].search(t))
        if has_ok and not has_no:
            return "正确"
        if has_no and not has_ok:
            return "错误"
        return None

    @staticmethod
    def _format_all_results(results_map: dict[int, str],
                            subgoals: list[dict]) -> str:
        """格式化所有子目标结果"""
        lines = []
        for sg in subgoals:
            result = results_map.get(sg["id"], "（未求解）")
            _title = str(sg.get("title") or "")
            _txt = str(result)
            # 2026-09-14：聚合层不再依赖模型的格式自觉（实测 #103/#107/#110）——
            # 对「判定选项 X」子目标**解析结论并结构化前置**，使合并层无需理解
            # 自由文本即可汇总；解析不到则显式标注"判定缺失，需单独复核"。
            _m = re.match(r"^判定选项\s*([A-E])\s*$", _title.strip())
            if _m:
                _lab = _m.group(1)
                _v = SubGoalSolverAgent._extract_option_verdict(_txt)
                if _v:
                    _txt = "【系统解析：选项 {} = {}】{}".format(_lab, _v, _txt[:400])
                else:
                    _txt = (
                        "（⚠ 本步**未给出明确结论** —— 既无『结论：正确/错误』"
                        "也无『选项{}：正确/错误』，原文：{}；"
                        "合并时请**单独复核选项 {}**，"
                        "**不得**因其格式不规范而默认排除）"
                    ).format(_lab, _txt[:200], _lab)
            lines.append(f"子目标 #{sg['id']}「{_title}」: {_txt}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_from_last_subgoal(subgoals: list[dict]) -> str:
        """兜底：使用最后一个**剥壳后仍有实质内容**的子目标结果。

        2026-09-17 两处修复（实测 official112-025）：
        ① 返回前剥壳：子目标 result 可能是 `</tool_call>` 这类纯工具残留，
           原样返回会把标签当最终答案（025 的 5/6 候选即此形态）；
        ② 倒序找第一个**剥壳后非空**的结果：原实现只看 `sg.get("result")`
           真值，若最后一个子目标是空壳（纯标签）就被当答案返回，故剥壳后
           为空则继续往前找，避免"空壳顶替真结论"。
        """
        # ★ 2026-10-06（结论契约）：结论契约生效后 `result` 会包含「结论行 +
        #   依据行 + 验算段」，整体当最终答案过于冗长 ⇒ **优先取结构化结论**
        #   （`value`/`equation` 形态可直接作为答案），没有再退回 result。
        for sg in reversed(subgoals):
            _concl = str(sg.get("conclusion") or "").strip()
            if _concl:
                return SubGoalSolverAgent._strip_tool_residue(_concl).strip()
            _res = sg.get("result")
            if not _res:
                continue
            _clean = SubGoalSolverAgent._strip_tool_residue(str(_res)).strip()
            if _clean:
                return _clean
        return "无法求解"

    @staticmethod
    def _build_full_reasoning(subgoals: list[dict],
                              problem_analysis: dict,
                              final_answer: str) -> str:
        """构建完整的推理过程文本（用于展示和回溯）"""
        lines = ["# 子目标分解求解过程\n"]
        if problem_analysis:
            lines.append(f"## 问题分析\n领域: {problem_analysis.get('domain', 'N/A')}")
            lines.append(f"目标: {problem_analysis.get('core_objective', 'N/A')}\n")
        lines.append("## 子目标规划")
        for sg in subgoals:
            lines.append(f"  #{sg['id']} [{sg['type']}] {sg['title']}: {sg['description']}")
        lines.append("\n## 逐步求解")
        for sg in subgoals:
            lines.append(f"\n### 子目标 #{sg['id']}「{sg['title']}」")
            lines.append(f"结果: {sg.get('result', '未求解')}")
        lines.append(f"\n## 最终答案\n{final_answer}")
        return "\n".join(lines)
