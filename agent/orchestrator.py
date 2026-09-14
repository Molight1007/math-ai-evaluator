from __future__ import annotations
"""
编排器（Orchestrator）—— 简化版
================================

借鉴 ss-main 的简洁流水线，不做复杂回环，每道题 LLM 调用控制在 7 次以内：

    Classifier → Solver → Verifier → Formatter
    (1次LLM)   (3次并行)  (3次投票)  (无LLM)

弱化改动：
- 不设蓝图分解（use_blueprint=False，对 Intern-S 思维流友好）
- 不设自纠错回环（直接用聚类选最优候选）
- 不设完整性审核链（省去 3+ 次 LLM 确认与续写）
- Symbol 快车道仍在（可确定性求解时短路）
"""

import logging
import os
import time
import re as _re

# 2026-09-13 晚：拒绝/占位符答案的正则。与 `agent/formatter.py` 与
# `user_agent.ReasoningAgent._DEGRADED_ANSWER_RE` 同源，此处独立一份是为了避免
# orchestrator↔formatter 的导入顺序纠缠（formatter 已被本文件 import，反向引用成环）。
# 三处**必须同步修改**。
# ⚠ 口径刻意收窄：**不含** `无解` / `暂无` —— 它们是**合法答案**（「该方程无解」就是
#   正确答案）。`formatter._REFUSAL_RE` 里保留这两个词是 HEAD 既有语义（用于"换个
#   候选试试"），但这里决定的是"有没有可用候选"，误判会让 `_fallback_direct`
#   用直答**覆盖正确解**（独立验证者实测：唯一候选 answer='无解' → 被覆盖成 '7'）。
_DEGRADED_ANSWER_RE = _re.compile(
    r"生成失败|调用受限|拒绝回答|未给出有效解答|无法作答|子目标求解失败|"
    r"我无法|无法求解|无法解决|不能解决|无法解答",
    _re.IGNORECASE,
)

# 2026-09-13 晚：紧急直答的输出上限（token）。旧值直接用 `max_answer_tokens`
# （65536）= 允许"只输出一行答案"的调用写一整篇论文，与 prefill 语义矛盾，
# 且在读超时下更容易被截断/挂住。紧急直答只需要一行 ⇒ 1024 足够且更快更稳。
_EMERGENCY_DIRECT_MAX_TOKENS = int(os.getenv("EMERGENCY_DIRECT_MAX_TOKENS", "1024"))

from .base import BaseAgent, TaskContext, Budget, Verdict, _normalize_chat_response
from .classifier import ClassifierAgent, _KNOWN_DOMAINS
from .solver import SolverAgent
from .sub_goal_solver import SubGoalSolverAgent
from .verifier import VerifierAgent
from .formatter import FormatterAgent
from .difficulty_router import DifficultyRouter
from .paper_pacer import PaperPacer
from .collaborative_solver import CollaborativeSolver
from .adversarial_verifier import AdversarialVerifier
from .audit_gate import AuditGate
from utils.extract import safe_json_serialize, is_truncated_answer as _is_truncated_answer

# ---- Lean 双通道（2026-09-06 晚恢复）----
# lean 系工具随 P2 去 Lean 化迁到 tools/lean_local/（归档），lean-toolchain
# 工具仓离线落地后重新接入检测链：Lean 环境可用 → 硬验证，不可用 → AuditGate 兜底。
# 惰性 import：模块缺失/import 异常一律视 lean 不可用，绝不拖垮主链路。
try:
    from tools.lean_local.lean_gate import LeanGate
    from tools.lean_local.lean_pre_verifier import LeanPreVerifier
    _LEAN_MODULES_OK = True
except Exception:  # noqa: BLE001
    LeanGate = None
    LeanPreVerifier = None
    _LEAN_MODULES_OK = False
    logger = logging.getLogger("MathPilot")
    logger.warning("tools.lean_local 不可用，Lean 双通道禁用（回落 AuditGate）")


def _load_lean_modules() -> bool:
    """（重）加载 Lean 双通道模块 —— 治「循环导入导致的静默永久禁用」。

    2026-09-10 定位到的真实环：``tools/lean_local/lean_gate.py`` 模块级
    ``from agent.base import ...`` → 触发 ``agent/__init__.py`` → 它 eager
    导入 ``.orchestrator`` → 本文件顶部的 ``from tools.lean_local.lean_gate
    import LeanGate`` 此时命中**部分初始化模块**（lean_gate 还没执行到类定义）
    → ImportError 被上面的裸 ``except`` 吞掉 → ``_LEAN_MODULES_OK=False``、
    ``LeanGate=None``，**整个 Lean 通道永久静默关闭**（不报错、不打日志、
    输出完全正常，只是 Lean 一次没跑）。

    该错序与入口的 import 顺序绑定：谁先 import ``tools.lean_local.*``（如
    独立核验脚本、平台 main、部分单测），谁就会中招；先 import
    ``agent.orchestrator`` 则正常。**顺序依赖 = 不可靠**。

    修法：保留顶部快速路径，另设本函数在**首次真正需要 Lean 时**重试导入
    （那时环已解开，必然成功），成功即回填全局并重建实例。一次性开关变成
    可自愈的懒加载，任何入口顺序都不再能永久禁用 Lean。
    """
    global LeanGate, LeanPreVerifier, _LEAN_MODULES_OK
    if _LEAN_MODULES_OK and LeanGate is not None:
        return True
    try:
        from tools.lean_local.lean_gate import LeanGate as _LG
        from tools.lean_local.lean_pre_verifier import LeanPreVerifier as _LPV
        LeanGate, LeanPreVerifier = _LG, _LPV
        _LEAN_MODULES_OK = True
        logger.info("Lean 双通道模块延迟加载成功（顶部导入曾被循环导入阻断，已自愈）")
        return True
    except Exception as _e:  # noqa: BLE001
        logger.warning("Lean 双通道模块重新加载仍失败，Lean 保持禁用: %s", _e)
        return False

try:
    from utils.sympy_tools import (
        _HAS_SYMPY, eval_expression, compute_derivative,
        compute_integral, compute_determinant, solve_equation,
        compute_limit,
    )
except ImportError:
    _HAS_SYMPY = False

logger = logging.getLogger("MathPilot")


class Orchestrator(BaseAgent):
    name = "Orchestrator"

    def __init__(self, client, config):
        super().__init__(client, config)
        self.classifier = ClassifierAgent(client, config)
        self.solver = SolverAgent(client, config)
        self.sub_goal_solver = SubGoalSolverAgent(client, config)
        self.verifier = VerifierAgent(client, config)
        self.formatter = FormatterAgent(client, config)
        # 难题深度求解通道（v2.5）
        self.difficulty_router = DifficultyRouter(client, config)
        self.pacer = PaperPacer(config)
        # deep 档难题三Agent协作求解器（v2.6：解题→审查→整合→反复验证）
        self.collab = CollaborativeSolver(client, config)
        # AuditGate 答案审核闸门（2026-09-06 去 Lean 化：取代 lean_gate /
        # lean_pre_verifier 在检测链中的全部作用——平台无 Lean，硬核验/反例/
        # rubric 程序与 LLM 混合瀑布，只审不答）
        self.audit_gate = AuditGate(client, config)
        # Lean 双通道（2026-09-06 晚恢复）：lean 可用即 LeanGate 硬验证 /
        # LeanPreVerifier 前置形式化；不可用由 _lean_active() 回落 AuditGate。
        self.lean_gate = (LeanGate(client, config)
                          if _LEAN_MODULES_OK and LeanGate is not None else None)
        self.lean_pre_verifier = (
            LeanPreVerifier(client, config)
            if _LEAN_MODULES_OK and LeanPreVerifier is not None else None)
        self._lean_probe: bool | None = None   # lean 环境探测结果（进程内缓存）
        # 对抗式验证器（#16，2026-08-30）：正向验证**通过后**主动证伪，治漏检。
        # 与 Step 4（_review_bug_feedback，治误杀）互补：
        #   正向不过 → Step 4 复核是否误报
        #   正向通过 → 本模块去找漏掉的错误
        self.adv_verifier = AdversarialVerifier(client, config)

    # ------------------------------------------------------------------
    # Lean 双通道探测（2026-09-06 晚）
    # ------------------------------------------------------------------
    def _ensure_lean_modules(self) -> None:
        """首用时自愈 Lean 模块（见 :func:`_load_lean_modules`）。

        顶部 import 若被循环导入阻断（``_LEAN_MODULES_OK=False``），此处重试
        导入并补建 ``lean_gate`` / ``lean_pre_verifier`` 实例——把「静默永久
        禁用」变成「首用自愈」。已就绪时零成本直接返回。
        """
        if _LEAN_MODULES_OK and LeanGate is not None:
            if self.lean_gate is None:
                try:
                    self.lean_gate = LeanGate(self.client, self.config)
                except Exception as _e:  # noqa: BLE001
                    logger.warning("LeanGate 重建失败: %s", _e)
            if self.lean_pre_verifier is None and LeanPreVerifier is not None:
                try:
                    self.lean_pre_verifier = LeanPreVerifier(self.client, self.config)
                except Exception as _e:  # noqa: BLE001
                    logger.warning("LeanPreVerifier 重建失败: %s", _e)
            return
        if not _load_lean_modules():
            return
        try:
            if self.lean_gate is None and LeanGate is not None:
                self.lean_gate = LeanGate(self.client, self.config)
            if self.lean_pre_verifier is None and LeanPreVerifier is not None:
                self.lean_pre_verifier = LeanPreVerifier(self.client, self.config)
            logger.info("Lean 双通道已自愈启用（此前被循环导入静默禁用）")
        except Exception as _e:  # noqa: BLE001
            logger.warning("Lean 双通道自愈后实例化失败，保持禁用: %s", _e)

    def _lean_active(self) -> bool:
        """Lean 通道是否启用：总开关开 + lean 模块在 + Lean 环境可用（结果缓存）。

        探测 = LeanGate 懒加载的 LeanBridge.lean_available（跑一次
        `lean --version`，进程内只探一次）。任何异常都视为不可用 → 回落
        AuditGate，绝不让 lean 探测本身拖垮/阻断评测。
        环境变量 LEAN_VERIFY=0（或 false/no/off）可一键关闭 lean 通道
        （单测经 tests/conftest.py 统一置 0；评测 A/B 对照也可用它）。
        """
        self._ensure_lean_modules()          # 2026-09-10：治循环导入静默禁用
        _env_off = (os.environ.get("LEAN_VERIFY", "1") or "1").strip().lower()
        if _env_off in ("0", "false", "no", "off"):
            return False
        if not getattr(self.config, "enable_lean_verify", True):
            return False
        if self.lean_gate is None:
            return False
        if self._lean_probe is None:
            try:
                _b = self.lean_gate._bridge_inst
                self._lean_probe = bool(_b is not None and _b.lean_available)
            except Exception:  # noqa: BLE001
                self._lean_probe = False
            if not self._lean_probe:
                logger.warning("Lean 环境不可用，检测链回落 AuditGate（AI 判分）")
        return bool(self._lean_probe)

    def _lean_applicable(self, ctx) -> bool:
        """按题 Lean 适用性（2026-09-10 用户要求「所有题都要用 Lean，除非非常
        简单的题」）。

        判定值由 1.1) 步骤落盘到 ``ctx.metadata["lean_applicable"]``（见
        :func:`agent.question_type.lean_applicable`）。此处只读，用于把
        **整题豁免**的题（答案不是数学对象：选项字母 / 判断值 / 概念文字）
        从 Lean 通道改路由到 AuditGate —— 即「豁免 Lean，但不豁免检测」，
        而不是让它们裸奔输出。

        缺省语义：metadata 无该键（旧结果、手搓 ctx、单测 fixture）→ 视为
        适用，保持既有行为完全不变。
        """
        md = getattr(ctx, "metadata", None)
        if isinstance(md, dict) and md.get("lean_applicable") is False:
            return False
        return True

    # ------------------------------------------------------------------
    # 阶段耗时埋点（2026-09-03 老师：deep 档需要每个环节具体耗时做决定）
    # ------------------------------------------------------------------
    @staticmethod
    def _stage_start(ctx, name: str) -> None:
        # 2026-09-03 修正：进入新阶段前先结束所有未 stop 的旧阶段。
        # 否则 stop 只在流程末尾统一调用 → 每阶段耗时 = "从该阶段开始到
        # 流程结束"的剩余时间（实测 0_paper_pacer=1310s 全等于总时长，数据无效）。
        for _old in list((getattr(ctx, "_stage_starts", {}) or {}).keys()):
            if _old != name:
                Orchestrator._stage_stop(ctx, _old)
        ctx._stage_starts = getattr(ctx, "_stage_starts", {}) or {}
        ctx._stage_starts[name] = time.time()

    @staticmethod
    def _stage_stop(ctx, name: str) -> None:
        starts = getattr(ctx, "_stage_starts", {}) or {}
        s = starts.pop(name, None)
        if s is None:
            return
        ctx._stage_durs = getattr(ctx, "_stage_durs", {}) or {}
        ctx._stage_durs[name] = ctx._stage_durs.get(name, 0.0) + (time.time() - s)

    def _collect_stage_durs(self, ctx) -> dict:
        return dict(getattr(ctx, "_stage_durs", {}) or {})

    # ------------------------------------------------------------------
    # C-lite：数值攻击蓝图极值声称（2026-09-03 老师拍板）
    # ------------------------------------------------------------------
    def _final_answer_postprocess(self, ctx, ans: str = "") -> str:
        """最终答案后处理总入口（2026-09-11）：P2 强制数值化 + P5 客观题自检。

        设计原则（用户 9/11 指示：一次性实施全部优化 + 逐项埋点，避免"改一点测一点"）：
          - 每项优化独立开关（环境变量，便于 A/B 与逐项审查）
          - 每项优化独立埋点（record → diag，单次评测即可看出各项是否触发、影响哪些题）
          - 全部保守：任何异常或不确定情形一律原样返回，绝不降低既有正确率
        参数 ans 为空时回退读 ctx.final_response（供提前返回路径复用）。
        """
        ans = ans or ctx.final_response or ""
        if not ans.strip():
            return ans
        # 2026-09-12 审核补可观测（**不改行为**）：主出口调用点位于 **6.5 最终答案
        # 闸门之后**，而下面的 P2 数值化会**改写答案内容** ⇒ 闸门校验的字符串
        # 可能并非最终提交的字符串（"闸门验 A、实际提交 B"）。此处记录改动事实，
        # 便于用评测数据判断是否需要把后处理**前移到闸门之前**（那属主链顺序
        # 调整，定型前不动）。
        _before_pp = ans
        if os.environ.get("NUMERICIZE_FINAL", "1") != "0":
            try:
                ans = self._maybe_numericize(ctx, ans)
            except Exception as _e:  # noqa: BLE001
                logger.debug("[P2] 数值化异常跳过: %s", _e)
        if os.environ.get("OBJECTIVE_SELFCHECK", "1") != "0":
            try:
                ans = self._objective_selfcheck(ctx, ans)
            except Exception as _e:  # noqa: BLE001
                logger.debug("[P5] 客观题自检异常跳过: %s", _e)
        # B0（2026-09-13）：答案形态闸门——条件式→具体值 / 求所有→枚举
        if os.environ.get("ANSWER_FORM_GATE", "1") != "0":
            try:
                ans = self._answer_form_gate(ctx, ans)
            except Exception as _e:  # noqa: BLE001
                logger.debug("[B0] 形态闸门异常跳过: %s", _e)
        if ans != _before_pp:
            try:
                self.record(ctx, "final_postprocess_change",
                            "后处理改写了最终答案（闸门校验串≠提交串）："
                            f"{str(_before_pp)[:60]} → {str(ans)[:60]}")
            except Exception:  # noqa: BLE001
                pass
        return ans

    @staticmethod
    def _latex_const_value(core: str):
        """LaTeX 常数表达式 → Fraction（精确值）；不确定则 None。

        支持：数字、+ - * / **、括号、`\\frac{}{}`、`\\cdot`、`\\times`、
              `!`（阶乘，作用于整数）、`\\sqrt{}`。
        为什么不用 `calc_tool.to_exact_number`：实测它对本链路的典型失分格式
        （`2023^2`、`2^{19}\\cdot 19!`、`3!`）一律返回 None，等于 P2 无效。
        安全：仅接受白名单字符（数字/运算符/括号/空格/F），异常一律 None。
        """
        import re as _re
        from fractions import Fraction
        s = (core or "").strip()
        if not s or len(s) > 160:
            return None
        s = s.replace("\\left", "").replace("\\right", "")
        s = s.replace("\\cdot", "*").replace("\\times", "*")
        s = _re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"((\1)/(\2))", s)
        s = _re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"((\1)**(1/2))", s)
        s = s.replace("{", "(").replace("}", ")")
        s = _re.sub(r"(\d+)\s*!", r"F(\1)", s)      # 阶乘：3! → F(3)
        s = s.replace("^", "**")
        s = s.replace("$", "").strip()
        if not _re.fullmatch(r"[0-9+\-*/().\sF]+", s) or "F" not in s and "*" not in s and "/" not in s and "(" not in s:
            # 纯数字/算式仍需含运算特征，否则交给原逻辑
            if not _re.search(r"[*/(^]|\*\*", s):
                return None
        try:
            from sympy import sympify, factorial as _fact, Rational
            v = sympify(s, locals={"F": _fact})
            if v is None or not getattr(v, "is_rational", False):
                return None
            r = Rational(v)
            return Fraction(int(r.p), int(r.q))
        except Exception:
            return None

    def _maybe_numericize(self, ctx, ans: str) -> str:
        """P2：把"未求值的常数表达式"数值化（official112 有 4+ 道此类失分）。

        例：`2^{19}\\cdot 19!`、`2023^2`、`2 \\times 777^2`。
        严格保守：仅当 ① 答案含幂/阶乘/分式等表达式特征；② 可被
        `_latex_const_value` 精确求值；③ 结果与原写法不同 —— 才替换。
        """
        import re as _re
        m = _re.search(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", ans)
        core = (m.group(1) if m else ans).strip()
        if not core or len(core) > 160:
            return ans
        # 仅处理"表达式型"答案（纯数字/纯文字不动）
        if not _re.search(r"[\^!]|\\cdot|\\times|\\frac|\\sqrt", core):
            return ans
        val = self._latex_const_value(core)
        if val is None:
            return ans
        try:
            new = (str(val.numerator) if val.denominator == 1
                   else f"\\frac{{{val.numerator}}}{{{val.denominator}}}")
        except Exception:
            return ans
        if not new or new == core:
            return ans
        self.record(ctx, "numericize",
                    f"P2 未求值表达式已数值化：{core[:60]} → {new[:40]}")
        # B1（2026-09-11）：Lean 侧独立交叉校验（与 SymPy 互为第二意见）
        self._lean_crosscheck_number(ctx, core, new)
        return ans.replace(core, new) if core in ans else f"\\boxed{{{new}}}"

    def _objective_selfcheck(self, ctx, ans: str) -> str:
        """P5：客观题专项自检（official112 客观题段 2/11 且零验证兜底）。

        低风险动作：① 判断题写法归一（√/×/对/错 → 正确/错误）；
        ② 选项合法性**仅记录不改动**（题面未列出的选项字母 → 记录告警，避免误改）。
        """
        import re as _re
        q = ctx.problem or ""
        m = _re.search(r"\\boxed\{([^{}]*)\}", ans)
        core = (m.group(1) if m else ans).strip()
        # ① 判断题归一
        _jmap = {"√": "正确", "×": "错误", "对": "正确", "错": "错误",
                 "T": "正确", "F": "错误", "true": "正确", "false": "错误"}
        _norm = _jmap.get(core)
        if _norm and _norm != core and (
                ("判断" in q) or _re.search(r"^\s*(正确|错误)\s*$", core)
                or core in ("√", "×", "T", "F", "true", "false")):
            self.record(ctx, "objective_check", f"P5 判断题归一：{core} → {_norm}")
            return f"\\boxed{{{_norm}}}"
        # ② 选项合法性（只诊断）
        # 2026-09-13 修复（实测 103 暴露）：原正则要求选项字母**前为空白/行首/
        # 括号**，而连排选项（`长期趋势B.季节变动C.循环变动`）中字母前是汉字
        # ⇒ 实际只匹配到 A，报出假告警「答案 ABCD 含题面未列选项 BCD（题面选项 A）」。
        # 改为复用 `extract_options`（与题型判定同源的「有序字母序列」定位），
        # 避免两套选项解析器长期漂移——本项目"同源注入"教训的又一次重现。
        # 当前该检测**只诊断不改动**，故此前无实际危害；但不修则 P5 统计失真，
        # 且一旦升级为实际校验会误改答案。
        _opts: set = set()
        try:
            from .question_type import extract_options as _extract_opts
            _opts = {lab for lab, _ in _extract_opts(q)}
        except Exception:  # noqa: BLE001
            _opts = set()
        if _opts and _re.fullmatch(r"[A-E]+", core or ""):
            _bad = [c for c in core if c not in _opts]
            if _bad:
                self.record(ctx, "objective_check",
                            f"P5 选项越界告警：答案 {core} 含题面未列选项 {''.join(_bad)}"
                            f"（题面选项 {''.join(sorted(_opts))}）")
        return ans

    # ---- B0 答案形态闸门（2026-09-13）----
    # 台账 B0 两个可救模式：
    #   ① 条件式代替具体值（015 答 `n ≥ 2` / 正解 `2`；064 答 `m is even` / 正解 `4`）
    #   ② 求所有却只给一支（003 漏 2030；074 漏取整解族）
    _ASKS_ALL_RE = _re.compile(
        r"find\s+all|determine\s+all|all\s+possible|"
        r"求.{0,12}所有|求.{0,12}全部|所有\s*可能|全部\s*可能",
        _re.IGNORECASE)
    _ASKS_RANGE_RE = _re.compile(
        r"范围|区间|取值范围|充要条件|必要条件|充分条件", _re.IGNORECASE)
    # 条件式答案：同时覆盖 **Unicode 符号**（≥≤）与 **LaTeX 命令**（\geq \le …）
    # —— 实测 015 的答案是 `n \geq 2`（LaTeX），只认 ≥ 会漏判。
    _COND_ANS_RE = _re.compile(
        r"(^|[\s（(])([a-zA-Z]\s*)?(≥|≤|>=|<=|>|<)"
        r"|\\geq|\\leq|\\ge\b|\\le\b|\\gt|\\lt"
        r"|is\s+(even|odd)|for\s+all|对任意|任意\s*[a-zA-Z]", _re.IGNORECASE)

    def _answer_form_gate(self, ctx, ans: str) -> str:
        """B0：答案形态闸门（条件式 → 具体值；求所有 → 枚举）。

        台账 B0 明确两个可救模式（本题库实测）：
          ① **条件式代替具体值**：015 `n ≥ 2`→`2`；064 `m is even`→`4`
          ② **求所有却只给一支**：003 只给 `2026`、漏 `2030`
        检测到形态不符 → **定向重问一次**（明确要求枚举/具体值）；
        时间不足或重问失败则原样返回（绝不降低既有答案质量）。

        设计要点：**只看硬限**（`is_timed_out` / 剩余 < 120s），
        不使用 `gen_time_up()` —— formatter 处于流程末段，该判据恒为 True
        （差分检测曾因此永久失效，见 formatter._objective_diff_probe 的教训）。
        """
        try:
            if os.environ.get("ANSWER_FORM_GATE", "1") == "0":
                return ans
            _q = ctx.problem or ""
            _m = _re.search(r"\\boxed\{([^{}]*)\}", ans or "")
            _core = ((_m.group(1) if _m else ans) or "").strip()
            if not _core or len(_core) > 200:
                return ans
            _asks_all = bool(self._ASKS_ALL_RE.search(_q))
            _asks_range = bool(self._ASKS_RANGE_RE.search(_q))
            _cond = bool(self._COND_ANS_RE.search(_core))
            _is_enum = bool(_re.search(r"[,\uFF0C;；、]\s*\S", _core)) or \
                bool(_re.match(r"^\s*[\{\[]", _core))
            _trigger, _why = False, ""
            if _asks_all and not _is_enum:
                _trigger, _why = True, "题面要求『所有』但答案非枚举列表"
            elif _cond and not _asks_range:
                _trigger, _why = True, "答案为条件式，但题面未要求范围/条件"
            if not _trigger:
                return ans
            if ctx.is_timed_out() or ctx.time_remaining() < 120:
                self.record(ctx, "answer_form",
                            "B0 形态闸门：{}（时间不足一次重问，跳过）".format(_why))
                return ans
            self.record(ctx, "answer_form",
                        "B0 形态闸门触发：{} → 定向重问".format(_why))
            _fixed = self._ask_for_form(ctx, _core, _asks_all)
            if _fixed and _fixed != _core:
                # ⚠ 采纳前必须校验 —— 003 实测重问返回了**指令复述**
                # （`The user wants me to act as a math answer formatting tool.`），
                # 无校验直接采纳会把好答案改坏。不像答案 → 保留原答案。
                if not self._looks_like_answer(_fixed):
                    self.record(ctx, "answer_form",
                                "B0 重问结果不像答案，弃用并保留原答案：{}"
                                .format(_fixed[:60]))
                    return ans
                self.record(ctx, "answer_form",
                            "B0 重问修正：{} → {}".format(_core[:50], _fixed[:50]))
                return _fixed if _m is None else "\\boxed{{{}}}".format(_fixed)
            self.record(ctx, "answer_form", "B0 重问未获更优答案，原样返回")
            return ans
        except Exception as _e:  # noqa: BLE001
            logger.debug("[B0] 形态闸门异常跳过: %s", _e)
            return ans

    # 元话语特征 —— 重问可能返回"角色说明/指令复述"而非答案。
    # 003 实测：模型返回 `The user wants me to act as a math answer formatting tool.`
    _META_ANS_RE = _re.compile(
        r"the user|user wants|i (will|should|am)\b|让我|需要我|要求我|"
        r"作为.{0,8}(工具|助手|规范|器)|assistant|instruction|prompt",
        _re.IGNORECASE)

    # 题面复述 / 疑问式措辞 —— 2026-09-14 加严（#005 实测）。
    # 实况：重问把 `\boxed{1234}` 改写成
    #   `The problem asks for all possible values of $C(1234)$ …`
    # 旧判据 `re.search(r"\d", txt)` 因为它含 `1234` 而**放行**，
    # 结果答案从"可判的数值"退化成"不可判的散文"（error_class=format_unresolved）。
    # ⚠ 刻意只收**题面/疑问式**措辞，不收一般英文散文 —— 因为本题库存在
    #   **合法英文答案**（如 011 的 gold `$f(x,y)= g(x+y, xy(x-y)^{2})$ for some
    #   polynomial $g$`），过宽会误杀正确解。
    _RESTATE_ANS_RE = _re.compile(
        r"the\s+(problem|question|task|answer\s+is\s+asked)\b|"
        r"\basks?\s+(for|us\s+to)\b|\bwe\s+(need|want|must|are\s+asked)\b|"
        r"\blet\s+us\b|\bfind\s+all\b|\ball\s+possible\s+values?\b|"
        r"\bwhat\s+is\b|\bwhich\s+of\s+the\s+following\b|\bnote\s+that\b|"
        r"\bthe\s+user\b",
        _re.IGNORECASE)

    @staticmethod
    def _looks_like_answer(txt: str) -> bool:
        """重问结果是否"像答案"——防元话语 / 题面复述污染（003、005 实测教训）。

        判据：① 非空且不过长 ② 不含元话语 ③ **不含题面复述/疑问式措辞**
              ④ 含"答案核"（数字 / 数学宏 / 结构化集合）
        不满足则调用方**保留原答案**（绝不因重问而变差）。
        """
        if not txt or len(txt) > 120:
            return False
        if Orchestrator._META_ANS_RE.search(txt):
            return False
        # 2026-09-14（#005）：题面复述一律不是答案 —— 即便它里面含数字。
        if Orchestrator._RESTATE_ANS_RE.search(txt):
            return False
        if _re.search(r"\d", txt):
            return True
        return bool(_re.search(r"\\[a-zA-Z]+|π|√|∞|⌈|⌉|⌊|⌋|≤|≥", txt))

    def _ask_for_form(self, ctx, cur: str, asks_all: bool) -> str:
        """B0 定向重问：按题目要求给出枚举列表 / 具体值（一次短调用）。"""
        try:
            from .base import _normalize_chat_response
            _rule = (
                "本题要求『求所有』——必须列出**全部**取值，用逗号分隔"
                "（如 `2026, 2030`），并确认已穷尽所有可能分支。"
                if asks_all else
                "本题要求**具体数值**——不要输出 `≥/≤/>/< / 任意 / for all / "
                "is even` 这类条件式或性质描述；若答案确为集合，请写成具体元素列表。"
            )
            _sys = ("你是数学答题规范器。根据题目要求给出最终答案，"
                    "只输出答案本身（一行），不要任何解释或推导。")
            _user = "题目：\n{}\n\n当前答案：{}\n\n要求：{}".format(
                ctx.problem, cur, _rule)
            _resp = self.client.chat(
                messages=[{"role": "system", "content": _sys},
                          {"role": "user", "content": _user}],
                temperature=0.0, max_tokens=512,
            )
            _text = (_normalize_chat_response(_resp) or "").strip()
            if not _text:
                return ""
            return _text.split("\n")[0].strip()[:200]
        except Exception:  # noqa: BLE001
            return ""

    def _lean_crosscheck_number(self, ctx, latex_expr: str, value: str) -> bool:
        """B1（2026-09-11）：用 lean-lsp-mcp 独立复算，与 SymPy 结果交叉验证。

        仅验证"数值等式"：``example : ((<expr>) : ℚ) = <value> := by norm_num``。
        - 全本地、不联网；环境缺失/异常一律返回 True（**静默降级，不阻断主链路**）。
        - 返回 False 表示"Lean 认为该等式不成立" → 由调用方记录（可作硬信号）。
        价值：Lean 的 ℕ/ℤ/ℚ 语义精确，可捕捉 SymPy 在语义/精度上的偏差。
        """
        if os.environ.get("LEAN_XCHECK_NUMERIC", "1") == "0":
            return True
        try:
            from tools.lean_local.lean_bridge import mcp_run_code
        except Exception:  # noqa: BLE001
            return True
        _cfg = getattr(self, "config", None)   # 测试以 __new__ 构造时无 config
        _wd = str(getattr(_cfg, "lean_project_dir", "") or "")
        if not _wd or not os.path.isdir(_wd):
            return True
        le = (latex_expr or "").replace("\\cdot", "*").replace("\\times", "*")
        le = _re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"((\1)/(\2))", le)
        le = le.replace("{", "(").replace("}", ")").strip()
        if not le or len(le) > 120:
            return True
        code = (f"import Mathlib.Tactic\n"
                f"example : (({le}) : ℚ) = ({value}) := by norm_num\n")
        try:
            res = mcp_run_code(code, _wd, timeout=90.0)
        except Exception:  # noqa: BLE001
            return True
        if res.get("ok"):
            self.record(ctx, "numericize",
                        f"P2 Lean 交叉校验通过：{le} = {value}")
            return True
        self.record(ctx, "numericize",
                    f"P2 Lean 交叉校验不一致：{le} ≠ {value}"
                    f"（{str(res.get('items'))[:140]}）")
        return False

    def _self_improve_applicable(self, ctx) -> bool:
        """3.3 自改进的**题型门控**（2026-09-11）。

        客观题（选择题 / 判断题 / 中文短语）**不做自改进**：
        它们没有"可改进的数学推导过程"，自改进只会白花一次 LLM 调用，
        且实测有害 —— smoke6_v3 实证：098 原答 B（正确），跑完 365s 自改进后
        变成 D（错误），而该题实为概念选择题（问"矩阵条件数定义"）。
        判据复用 Lean 适用性（客观题本就 lean_applicable=False）。
        开关：SELF_IMPROVE_OBJECTIVE_SKIP（默认 1，设 0 恢复旧行为）。
        """
        if os.environ.get("SELF_IMPROVE_OBJECTIVE_SKIP", "1") == "0":
            return True
        try:
            m = ctx.metadata if isinstance(ctx.metadata, dict) else {}
            if m.get("lean_applicable") is False:
                self.record(ctx, "control",
                            "Step2 自改进跳过：题型为客观题（无可改进的推导过程）")
                return False
        except Exception:  # noqa: BLE001
            pass
        return True

    def _phase_budget(self, ctx, ratio: float = 0.0, floor: float = 180.0,
                      reserve: float = 0.0, stage: str = "") -> float:
        """阶段时间上限（秒）—— 2026-09-13 改为「实测口径」。

        ── 为什么废弃旧口径 ─────────────────────────────────────────────
        旧实现：`(soft_budget − reserve) × ratio`，ratio 取 0.30 / 0.35。
        三个致命问题（本次审计 + 195 题实测发现）：
          ① ratio 本身**没有任何实测依据**，是拍脑袋的固定切分；
          ② 它把"单题预算"当蛋糕切，而单题预算当时被 1200s 常量钉死
             ⇒ 切出 234s 这种碎块，把有用工作直接砍掉（与用户要求
             "确保时间开销有用、不做无用功"直接冲突）；
          ③ 各阶段 ratio 之和（0.30+0.30+0.35）已达 0.95 ⇒ 新增阶段无预算可分，
             所以 3.2 / 3.5 / 3.6 / 4_verify / 4.6 才会长期"无预算裸跑"。

        ── 新口径 ──────────────────────────────────────────────────────
        直接给该阶段**实测所需**（195 题 `stage_timers` 的 max × 约 1.2 余量），
        仅作"防单阶段无限膨胀"的上限；跨阶段的保护由 `_gen_deadline`
        （生成侧）与 `verify_reserve`（验证侧）统一负责，不再靠比例切分。

        传 `stage` 时走新口径；不传则回退旧公式（保证既有测试与外部调用零变化）。
        """
        if stage:
            # 依据：`results/*.jsonl` 的 `stage_timers`，最近三代代码 195 题实测 max。
            _CAPS = {
                "2.6_pre_audit": 650.0,       # 实测 max 560
                # 2026-09-13 收紧：原 1200 取自"实测 max"，但它 **≥ 单题全部预算
                # （1150）** ⇒ `min(deadline, now+1200)` 恒等于 deadline，**等于没有
                # 上限**。而实测 2.7 占单题 45%（112 题 mean 513s / p50 537s），是
                # 单题最大开销。按"不超过单题预算一半"压到 600s，把余量让给
                # 3_solve / 3.6 / 4_verify。
                # ⚠ 注意 `base.py:619` 单次 `client.chat` **不可中断**、预算闸只在
                # 调用之间生效 ⇒ 本上限是"调用之间"的闸，不能硬切正在进行的一次调用。
                "2.7_subgoal_main": 600.0,    # 实测 mean 513 / p50 537 / max 1168
                # 2026-09-13 二轮收紧：**1200 → 600**。
                # 根因（同题 A/B 实测 + 代码判定）：`_phase_deadline_guard` 做的是
                # `min(ctx.deadline, now + cap)`，而 3_solve 开始时 `now + 1200` **恒大于**
                # 单题 deadline（1000s）⇒ min 恒等于原 deadline ⇒ 本上限**完全失效（no-op）**，
                # 于是 2.7 让出的时间被 3_solve 全部吸收。
                # 铁证（同一题，v7 旧 cap 234/180 → 新 cap 1200）：
                #   000: 2.7 425→337 而 3_solve 294→**429**；004: 258→135 而 365→**542**；
                #   010: 262→245 而 490→**585**；budget_skips 由 7/10/8/6 → 1/1/2/8。
                # 同一病理 2.7 已在上面修过（1200→600），**3_solve 当时被漏掉**。
                # 600 = 单题预算（1000）的六成，与 2.7 对称，保证后段 3.6/4_verify/6.5 不被饿死。
                # ⚠ 单次 LLM 200-300s 不可中断（`base.py:619`）⇒ 仍可能被跨过一次。
                "3_solve": 600.0,             # 实测 max 1148；**上限必须 < 单题预算才有效**
                "3.2_complete": 220.0,        # 实测 max 175
                "3.3_improve": 500.0,         # 实测 max 453（与 3.4 共享改进额度）
                "3.4_collab": 800.0,          # 实测 max 691
                "3.5_subgoal_sup": 300.0,     # 实测 max 0（默认关闭）
                "3.6_audit_filter": 750.0,    # 实测 max 632
                "4_verify": 900.0,            # 实测 max 783
                "4.5_oracle": 150.0,          # 实测 max 116
                "4.6_adv": 900.0,             # 实测 max 856
                "6.5_audit_gate": 550.0,      # 实测 max 460
            }
            return max(floor, float(_CAPS.get(stage, 600.0)))
        _soft = float(getattr(ctx, "soft_budget", 0) or 0)
        _avail = max(0.0, _soft - max(0.0, reserve))
        return max(floor, _avail * ratio)

    def _phase_deadline_guard(self, ctx, cap: float):
        """阶段预算包裹（同时收紧 `deadline` 与 `_gen_deadline`）。

        ⚠ 2026-09-13 关键修复（实测定位）：`BaseAgent.gen_time_up()` 用的是
        **`_gen_deadline`**（单题开始时按 `deadline − verify_reserve` 设一次），
        与 `ctx.deadline` 是**两个独立字段**。此前各阶段的预算包裹**只设
        `ctx.deadline`**，而循环体查的是 `gen_time_up()` ⇒ **阶段预算对循环完全
        无效**（形同虚设）。实测铁证：
          · `2.7_subgoal_main` 预算 660s → 实跑 **816s**
          · `3_solve` 预算 273s → 实跑 **617s**
          · `3.4_collab` 无包裹 → 实跑 **691s**
        三者叠加把 1200s 预算吃光 ⇒ 3.3/4_verify/4.6/6.5 全被饿死（0s）。

        本方法同时收紧两个字段，使 `gen_time_up()` 与 `is_time_critical()`
        **都**在阶段预算到点时返回 True ⇒ 循环真正停手。
        返回 (t0, saved) 供 `_phase_deadline_restore` 还原。
        """
        import time as _t
        _t0 = _t.time()
        _saved = (ctx.deadline, getattr(ctx, "_gen_deadline", 0.0))
        _end = _t0 + max(1.0, float(cap))
        try:
            if ctx.deadline and ctx.deadline > 10**8:
                ctx.deadline = min(ctx.deadline, _end)
            if getattr(ctx, "_gen_deadline", 0.0) and ctx._gen_deadline > 10**8:
                ctx._gen_deadline = min(ctx._gen_deadline, _end)
        except Exception:  # noqa: BLE001
            pass
        return _t0, _saved

    @staticmethod
    def _phase_deadline_restore(ctx, saved) -> None:
        """还原阶段预算包裹前的两个时间字段。"""
        try:
            ctx.deadline, ctx._gen_deadline = saved[0], saved[1]
        except Exception:  # noqa: BLE001
            pass

    def _value_attack_blueprint(self, ctx, tier: str) -> None:
        """蓝图 merge 声称"极值=数值"时，数值采样攻击验证。

        009 实况：蓝图声称最大 4∛(85/98)≈3.815，真值 2∛(196/13)≈4.94——
        LLM 心算错值后全链路自洽执行，Lean unknown 拦不住。这里用
        **确定性 Python 采样**（20k 点）找突破声称值的可行点 → 证伪。
        """
        # 审核补充（2026-09-03）：原实现所有早退分支都是裸 return，
        # v17 全程 0 条 value_attack 痕迹时无法判断"未触发"还是"异常被吞"。
        # 每个早退点都留 debug 日志，便于下一轮定位。
        try:
            if ctx.is_time_critical():
                logger.debug("[C-lite] 跳过数值攻击：时间紧张")
                return
            # 审核修正（2026-09-03）：原读 `ctx.blueprint_merge`——该属性**不存在**
            # （TaskContext 无此字段，diag 用的是 ctx.blueprint["merge_strategy"]），
            # 等于蓝图那一路 merge 文本永远拿不到，只剩子目标整合方案兜底。
            _bp = getattr(ctx, "blueprint", None) or {}
            _bp_merge = _bp.get("merge_strategy", "") if isinstance(_bp, dict) \
                else str(getattr(_bp, "merge_strategy", "") or "")
            merge_text = _bp_merge or getattr(ctx, "subgoal_merge_plan", "") or ""
            if not merge_text:
                logger.debug("[C-lite] 跳过数值攻击：无蓝图 merge 文本"
                             "（blueprint.merge_strategy / subgoal_merge_plan 均空）")
                return
            # 只对"极值声称"题下手（其余题型放行，零误伤）
            import re as _re2
            if not (_re2.search(r"max|min|最大|最小", merge_text, _re2.I)):
                logger.debug("[C-lite] 跳过数值攻击：merge 文本无极值关键词")
                return
            from .value_attack import attack_value_claim
            from utils.prefill import prefill_messages, stitch
            # 1) LLM 从题目 + 声称提取: 方向/声称值/目标函数 Python 源码
            sys_p = (
                "你是数值提取器。根据题目（一个连续优化/极值问题）生成可执行 Python。\n"
                "输出 JSON：\n"
                "{\"direction\": \"max\"|\"min\", \"claimed\": <声称的极值数值近似>, "
                "\"code\": \"def f(x): ... 用 x[0],x[1]... 计算目标函数返回 float; "
                "def sample_point(): 返回一个满足约束的可行点 list\"}\n"
                "注意：claimed 是把题目声称的极值（含根式分数）算出的十进制近似；"
                "code 必须自含约束检查（不可行点返回 None）；禁止 import 外部库之外的；"
                "只输出 JSON。"
            )
            user_p = f"题目：\n{ctx.problem[:1500]}\n\n声称的答案/蓝图结论：\n{merge_text[:800]}"
            raw = self.llm(ctx, prefill_messages(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": user_p}], '{"direction":'), 0.0, 32768)
            if not raw:
                logger.debug("[C-lite] 跳过数值攻击：LLM 提取返回空")
                return
            raw = stitch('{"direction":', raw)
            m = _re2.search(r"\{[\s\S]*\}", raw)
            if not m:
                logger.debug("[C-lite] 跳过数值攻击：LLM 输出无 JSON 块")
                return
            import json as _json
            try:
                parsed = _json.loads(m.group())
            except (_json.JSONDecodeError, ValueError) as exc:
                logger.debug("[C-lite] 跳过数值攻击：JSON 解析失败 %s", exc)
                return
            direction = str(parsed.get("direction") or "")
            claimed = parsed.get("claimed")
            code = str(parsed.get("code") or "")
            if direction not in ("max", "min") or claimed is None:
                logger.debug("[C-lite] 跳过数值攻击：direction=%r claimed=%r 不合法",
                             direction, claimed)
                return
            # 2) 数值攻击
            result = attack_value_claim(
                ctx.problem or "", float(claimed), direction, code)
            if not result.get("ok"):
                reason = result.get("reason", "数值攻击证伪")
                ctx.blueprint_value_false = reason
                self.record(ctx, "value_attack",
                            f"蓝图极值证伪（{direction}={claimed}）：{reason[:160]}")
                # 传给下游：候选生成/求解时提示蓝图方向不可信
                ctx.revise_feedback = list(getattr(ctx, "revise_feedback", []) or []) + [
                    f"[数值攻击] 蓝图声称极值 {claimed} 已被数值采样证伪"
                    f"（发现 {result.get('found', '?')}）。请重新推导极值，"
                    f"不要沿用蓝图的候选值。{reason[:200]}"]
                # P1（2026-09-10）：同步写入**修订驱动通道**。
                # 背景：official112 全量实测——数值攻击已发现反例 47 题（其中错题 36 题），
                # 但仅 6 题触发修订；根因是本函数此前只写 revise_feedback（提示通道），
                # 而 _deep_revise_loop 只消费 audit_reject_feedback（修订驱动通道）。
                ctx.audit_reject_feedback = list(
                    getattr(ctx, "audit_reject_feedback", []) or []) + [
                    f"[数值攻击证伪] 蓝图声称极值 {claimed} 已被采样证伪"
                    f"（发现 {result.get('found', '?')}）：{reason[:200]}"]
            else:
                self.record(ctx, "value_attack",
                            f"蓝图极值未被证伪（采样上界 "
                            f"{result.get('found', '?')}，声称 {claimed}）")
        except Exception as _e:  # noqa: BLE001  攻击失败不影响主流程
            self.record(ctx, "value_attack",
                        f"数值攻击异常跳过: {str(_e)[:120]}")

    # ----------------------------------------------------------
    # 主入口（简化版流水线）
    # ----------------------------------------------------------
    def run(self, problem: str, metadata: dict) -> dict:
        now = time.time()
        # ---- 全卷时钟锚点（2026-09-13 修复「全卷时钟是死的」）------------------
        # 原实现把 total_start_time / total_deadline 都基于 `now`，而平台是**逐题**
        # 调用 solve()→run() 的 ⇒ total_deadline 每题都被重置成"此刻 + 6.25h"
        # ⇒ elapsed_total 恒 ≈ 0、ratio 恒 0 ⇒ 下面 `ratio > 0.95`（应急模式）与
        # `ratio > 0.8`（时间收紧）两个全卷保护分支**永不触发** —— 全卷时间管理
        # 实际是死的，每题只顾自己跑到单题硬顶（这正是"某题吃光预算"的温床）。
        # 修复：锚点只在**首题**锁定一次、跨题保留（并发下"先到先写"，幂等）；
        # 并把 PaperPacer 的 start_time 对齐同一锚点，使
        # `total_time_remaining()`（TaskContext）与 `hard_remaining()` /
        # `budget_for()`（PaperPacer）三个口径完全一致，不会各算一套时间。
        if getattr(self, "_paper_anchor", None) is None:
            self._paper_anchor = now
            try:
                self.pacer.start_time = now
            except Exception:  # noqa: BLE001
                pass
        _anchor = float(self._paper_anchor)
        ctx = TaskContext(
            problem=problem,
            metadata=metadata or {},
            budget=Budget(max_calls=self.config.max_total_calls),
            start_time=now,
            deadline=now + getattr(self.config, 'max_time_per_question', 300),
            total_start_time=_anchor,
            total_deadline=_anchor + getattr(self.config, 'max_total_time_seconds', 21000),
        )
        try:
            self._stage_start(ctx, "0_paper_pacer")
            # 0) PaperPacer 全卷时间池：5h 目标动态预算帽 + MIN_SOFT 保底
            self.pacer.begin()
            ctx.pacer_remaining = self.pacer.hard_remaining()
            # 单题 20 分钟硬限：超时直接跳过（保留已有候选/兜底产出）
            if ctx.is_timed_out():
                self.record(ctx, "timeout", "单题超过 20 分钟，跳过处理")
                # 2026-09-02 bug 修复：超时分支先看已有候选（比瞎直答可靠），
                # 003 1206s 超时直接 emergency_direct_solve → "No such function"
                # 裸奔（无推理、无 Lean 把关）的根因。
                answer = self._pick_best_from_candidates(ctx)
                if not answer:
                    answer = self._emergency_direct_solve(ctx.problem)
                if not answer:
                    answer = "未给出有效解答。"
                self.pacer.end(soft=getattr(ctx, "soft_budget", None))
                return safe_json_serialize({
                    "final_response": answer, "trace": ctx.trace,
                    "diag": self._collect_diag(ctx),
                })
            elapsed_total = time.time() - ctx.total_start_time
            total_budget = ctx.total_deadline - ctx.total_start_time
            ratio = elapsed_total / total_budget if total_budget > 0 else 0.0
            # v2.8：运行时覆盖统一写入 ctx.state（RunState），不再改写共享 config，
            # 消除并发=3 时跨题污染（时间预算自律核心）。
            if ratio > 0.95:
                # P1 修复：阈值 0.75→0.95。本地测试更晚进入应急模式，把准确率放在时间前面。
                # 应急模式：候选→1、投票→1，跳过续写/复算（45 error 主因根治）
                ctx.state.sample_times = max(1, self.config.policy_sample_times - 1)
                ctx.state.voting_times = 1
                ctx.state.emergency = True
                ctx.state.playoff_enabled = False
                self.record(ctx, "paper_pacer", f"应急模式：已用 {ratio:.0%} 总预算")
            elif ratio > 0.8:
                ctx.state.voting_times = 1
                ctx.state.emergency = False
                ctx.state.playoff_enabled = False
                self.record(ctx, "paper_pacer", f"时间收紧：已用 {ratio:.0%} 总预算")
            else:
                ctx.state.emergency = False
                ctx.state.playoff_enabled = True

            self._stage_start(ctx, "1_classify")
            # 1) 题型识别（零 LLM 关键词分类，供 Lean 门禁区分证明题/解答题、
            #    及题型差异化策略使用）。
            # 2026-09-01 补漏：原逻辑仅在「元数据 domain 未知」时才跑 classifier.run，
            # 若 metadata.domain ∈ _KNOWN_DOMAINS（如 "代数"）则跳过 → ctx.question_type
            # 永不赋值 → lean_gate 拿不到 question_type，该 domain 下的证明题会被误判
            # 为非证明题走轻量答案验证而非整题 verify。这里无条件先做题型识别。
            if self.config.enable_question_type:
                from .question_type import classify_question_type
                ctx.question_type = classify_question_type(ctx.problem)
                self.record(ctx, "classify_type",
                            f"题型识别结果: {ctx.question_type}",
                            question_type=ctx.question_type)

            # 1.1) Lean 适用性判定（2026-09-10 用户要求「所有题都要用 Lean，
            #      除非非常简单的题」）：答案不是数学对象的题（选项字母 /
            #      判断值 / 概念文字）Lean 结构上无从形式化核验，按题豁免，
            #      而不是用全局开关一刀切。official112 标定：豁免 18/112，
            #      误伤 0 道。结果写入 ctx.metadata 供 LeanGate 读取（tools/
            #      不反向依赖 agent/ 包），并把原因落进 diag 供事后追溯。
            try:
                from .question_type import lean_applicable
                _la_ok, _la_why = lean_applicable(
                    ctx.problem or "", getattr(ctx, "question_type", "") or "")
                if isinstance(getattr(ctx, "metadata", None), dict):
                    ctx.metadata["lean_applicable"] = bool(_la_ok)
                    if not _la_ok:
                        ctx.metadata["lean_skip_reason"] = _la_why
                    self.record(ctx, "lean_applicable",
                                f"Lean 适用性: {'适用' if _la_ok else '豁免(' + _la_why + ')'}",
                                lean_applicable=bool(_la_ok))
            except Exception as _e:  # noqa: BLE001
                # 判定失败 → 不豁免（保持 Lean 全跑，宁可多跑不漏跑）
                logger.warning("Lean 适用性判定失败，按适用处理: %s", _e)

            # 1.5) 领域（元数据已知时跳过 LLM）
            pre_known_domain = (metadata or {}).get("domain", "")
            if pre_known_domain and pre_known_domain in _KNOWN_DOMAINS:
                ctx.domain = pre_known_domain
                self.record(ctx, "classify",
                    f"题型分类（元数据已知）: {pre_known_domain}", domain=pre_known_domain)
            elif self.config.enable_domain_hint:
                self.classifier.run(ctx)

            # 2) 快车道（可确定性求解 → 直接出结果）
            fast_result = self._fast_path(ctx)
            if fast_result is not None:
                ctx.final_response = fast_result
                self.record(ctx, "fast_path", f"快车道直接求解: {fast_result[:200]}")
                self.pacer.end(soft=getattr(ctx, "soft_budget", None))
                return safe_json_serialize({
                    "final_response": fast_result, "trace": ctx.trace,
                    "candidates": [], "verdicts": [],
                    "diag": self._collect_diag(ctx),
                })

            self._stage_start(ctx, "2.5_difficulty")
            # 2.5) 难度路由：静态预判 + LLM 自评 → 三级档位（难题深度通道）
            self.difficulty_router.run(ctx)
            tier = getattr(ctx, 'tier', 'standard')
            # 应急模式：所有档位强制降档到 **standard**（预算收紧，保产出）。
            # 2026-09-14：**fast 档已删除**（用户要求，只留 standard/deep）
            # ⇒ 应急降档目标改为 standard —— 它仍保有完整的子目标分解与
            # 逐项判定链路，只压缩预算；不像已删除的 fast 那样连候选池与
            # 子目标分解都一并省掉（实测那正是 102/103/106 出问题的原因）。
            if ctx.state.emergency and tier != 'standard':
                ctx.tier = 'standard'
                tier = 'standard'
                self.record(ctx, "paper_pacer", "应急模式：强制降档到 standard")
            # deep 档配额闸（2026-08-28 新增）：deep 占比封顶 25%。
            # 时间账：并发 3 × 6h = 64800 题·秒；deep 占 30% 需 70080，超 5280
            # → 全卷必爆。超配额时降级到 standard，保证全卷能做完。
            if tier == 'deep' and not self.pacer.allow_deep():
                ctx.tier = 'standard'
                tier = 'standard'
                self.record(ctx, "paper_pacer",
                            f"deep 配额用尽（{self.pacer.deep_used}/"
                            f"{self.pacer.total_questions}×"
                            f"{self.pacer.deep_quota_ratio:.0%}），降级到 standard")
            elif tier == 'deep':
                self.pacer.note_deep()
            # 全卷时间池动态预算帽
            ctx.soft_budget = self.pacer.budget_for(tier)
            # ---- 让动态预算真正生效（2026-09-13 恢复并改造）--------------------
            # 历史：2026-09-03 老师要求"每题上限 1200s，不到 1200 不要截断；
            # 强制结束 = 错误"，故**取消**了此处的 deadline 收紧，deadline 恒等于
            # 1200s 硬顶 —— 后果是 PaperPacer 算出的 soft_budget **只被记录、完全
            # 不生效**，单题预算退化成常量，全卷调度形同虚设（112 题 × 1200s ÷
            # 并发 3 = 12.4h，与"6.5h 内跑完"在数学上直接冲突）。
            #
            # 现改为**有上限的放开**：
            #     单题硬墙 = min(放开后的硬顶 max_time_per_question,
            #                    PaperPacer 动态预算 soft_budget)
            # · 时间宽裕（本地少量题 / 卷面前段）→ soft_budget 大 → 拿满硬顶，
            #   等价于"放开时间、不截断"，老师原本的意图仍然满足；
            # · 卷面吃紧 → soft_budget 自动回落 → 提前收手，保证后面的题还有预算
            #   （这就是"不卡在某一题上导致写不完"的执行点）。
            # 下方 `_vres` / `_gen_deadline` 基于收紧后的 deadline 计算，故必须
            # 在本行之后进行（顺序不能调换）。
            _hard_cap = float(getattr(self.config, 'max_time_per_question', 1200) or 1200)
            _one_q = max(60.0, min(_hard_cap, float(ctx.soft_budget or 0) or _hard_cap))
            if ctx.deadline and ctx.deadline >= 10**8:
                _new_dl = ctx.start_time + _one_q
                if _new_dl < ctx.deadline:
                    self.record(ctx, "paper_pacer",
                                f"单题预算收紧 {ctx.deadline - ctx.start_time:.0f}s → "
                                f"{_one_q:.0f}s（档位 {tier}，全卷剩余 "
                                f"{self.pacer.hard_remaining():.0f}s）")
                    ctx.deadline = _new_dl
            # 尾部阈值：默认 120s；deep 档再收紧到 60s，把时间用得更尽
            ctx.critical_tail_seconds = float(
                getattr(self.config, 'critical_tail_seconds', 120.0))
            if tier == 'deep':
                ctx.critical_tail_seconds = float(
                    getattr(self.config, 'deep_critical_tail_seconds', 60.0))
            # 生成侧软截止（2026-09-06 超时修复，冒烟 4/5 题烧穿 1200s 实证）：
            # 生成类单次 LLM 调用可达 200-300s，各模块循环只在候选/子目标边界查
            # is_time_critical（= deadline-120/60s）→ 最后一段生成必然跨过临界点
            # 把剩余预算烧穿 → 4_verify 投票全跳（"deadline 已过跳过投票"×6）、
            # 6.5 闸门空转（stage_timers 实证 0.0003s）、答案零验证裸提交。
            # 这里按档位预留 verify_reserve 秒强制留给 4_verify 投票 + 6.5 审核：
            #   deep=240s（投票 3 票/候选 + 打回重做窗口）/ 其余=180s。
            # config.verify_reserve_seconds 可覆盖；设 0 关闭（= 旧行为）。
            # 2026-09-11 v6：再上调预留（deep 360→540 / standard 300→480）。v5 实证：
            # 010 剩余已升至 387s（预留机制确认生效），但 002 的 3_solve 扩张到 579s
            # → 至 3.6 累计 1080s、剩余仅 120s（< 150 门槛）。根因是"生成侧各阶段共享
            # 同一截止点，单个阶段（3_solve）即可吃掉大部分余量"。故进一步前移生成截止，
            # 把更多预算明确让给验证与硬信号重解（P1）。
            # 2026-09-13 更正：先前的 800 基于错误前提（"单题可放到 3600s"），已回滚。
            # 现实约束：单题平台硬限 **1200s**（超时整个进程组被杀、不执行 finally、
            # 该题计 C），故单题预算 1150s 就是全部可用时间。验证侧各阶段
            # （3.6 + 4_verify + 4.5 + 4.6 + 5 + 5.5 + 6 + 6.5）p90 合计 ≈ 756s，
            # 占 1150s 的 66% —— 全给验证侧会把生成侧饿死。
            # 按"生成 ≈55% / 验证 ≈45%"分配 ⇒ deep 540s、其余 480s（沿用原值，
            # 它本就是 1200s 约束下的合理切分）。本预留必须保住"最后能格式化出答案"。
            _vres = float(getattr(
                self.config, 'verify_reserve_seconds',
                540.0 if tier == 'deep' else 480.0))
            ctx._gen_deadline = (
                ctx.deadline - _vres
                if ctx.deadline and ctx.deadline >= 10**8 else 0.0)
            self.record(ctx, "paper_pacer",
                        f"生成侧软截止 {ctx.deadline - ctx._gen_deadline:.0f}s"
                        f" 前停手（verify_reserve={_vres:.0f}s，留给验证/审核）"
                        if ctx._gen_deadline else
                        "生成侧软截止未启用（无 deadline）")
            # 按档位调整 LLM 调用预算（deep 档需要更多调用次数）
            max_calls = self.config.tier_max_calls.get(
                tier, self.config.max_total_calls)
            if ctx.budget is not None:
                ctx.budget.set_max_calls(max_calls)
            self.record(ctx, "paper_pacer",
                        f"档位 {tier} 软预算帽 {ctx.soft_budget:.0f}s "
                        f"(剩余目标 {ctx.pacer_remaining:.0f}s, 调用预算 {max_calls})",
                        tier=tier, soft_budget=round(ctx.soft_budget))

            self._stage_start(ctx, "2.6_pre_audit")
            # 2.6) 题意理解确认（2026-09-06 晚恢复 Lean 前置形式化：lean 可用且
            # 命中档位 → 题目转 Lean 声明编译校验理解，失败带错误强制重新审题；
            # lean 不可用/档位不命中 → AuditGate 可选 LLM 题意复核，默认关闭，
            # 失败不阻断主流程，由下游 revise/重理解兜底）。
            if not ctx.state.emergency:
                if (self._lean_active()
                        and self._lean_applicable(ctx)
                        and getattr(self.config, "enable_lean_preverify", True)
                        and tier in tuple(getattr(
                            self.config, "lean_preverify_tiers", ("deep",)))):
                    try:
                        self.lean_pre_verifier.run(ctx)
                    except Exception as _e2:  # noqa: BLE001
                        self.record(ctx, "lean_preverify",
                                    f"前置形式化异常（跳过，不阻断）: "
                                    f"{type(_e2).__name__}: {str(_e2)[:120]}")
                else:
                    self.audit_gate.confirm_understanding(ctx)

            self._stage_start(ctx, "2.65_calc_prewarm")
            # 2.65) 方案 B（2026-09-13 用户选定）：**生成前算式预计算**——主动把
            # "该用工具算的算式"先算好、摆到模型面前。动机：016 实测
            # `calc_tool_calls=[]` 且 `calc_fallback=0` ⇒ 模型压根不写 <calc>，
            # 所有"写在前面才生效"的防线（降级解析/分档/值汇总）全部空转。
            # 必须放在**首个生成阶段（2.7 子目标主路径）之前**：子目标链是最早产出
            # 内容的路径，预计算值在这里第一次能被看见（随后 revise/improve/merge
            # 也自动带上，见 `solver._calc_trace_block` / `sub_goal_solver._calc_results_block`）。
            # graceful：内部自带触发判据 + 时间护栏，失败/超时/NONE/纯四则一律
            # 不写 block、不阻断，仅留 `calc_prewarm` 埋点。
            try:
                self.solver.prewarm_calcs(ctx, tier=tier)
            except Exception as _e_cp:  # noqa: BLE001  预计算失败不阻断主流程
                self.record(ctx, "calc_prewarm",
                            f"预计算调用异常（已跳过，不阻断）: "
                            f"{type(_e_cp).__name__}: {str(_e_cp)[:120]}")

            self._stage_start(ctx, "2.7_subgoal_main")
            # 2.7) 子目标细化主路径（v2.9）：全部档位统一先跑一次子目标分解逐步求解
            # 2026-09-06：时间判断升级 gen_time_up（生成侧软截止，给验证留预算）
            if (getattr(self.config, 'enable_subgoal_main_path', True)
                    and not ctx.state.emergency
                    and not ctx.gen_time_up()):
                self.record(ctx, "control",
                            "子目标细化主路径先行（前置形式化已校准题意）")
                # P4（2026-09-11）：2.7 阶段预算上限——把超额时间让给验证与重解。
                # 数据依据（official112 冒烟实测）：2.7 单阶段耗 753–1078s（占 1200s 硬顶的
                #   63–90%），波动可达 base 均值(513s)的 2 倍；致 3.x / 4 验证 / 4.6 对抗 /
                #   P1 重解全部无预算（P1 三次前移均因时间耗尽而未触发）。
                # 口径：档位软预算 × ratio（默认 0.55 → standard≈297s / deep≈660s），
                #   且不低于 240s（保证子目标链有基本时间）；ratio 可经 config 覆盖
                #   （subgoal_phase_budget_ratio，设 1.0 等价于关闭本限制，便于 A/B 对照）。
                # 实现：临时收紧 ctx.deadline（子目标链内部的时间判断随之生效），
                #   finally 恢复原 deadline，不影响后续阶段。
                # 2026-09-13 预算修复（两处问题）：
                # ① 原用 `soft_budget × ratio`，**未扣除 reserve** ⇒ deep 档 660s
                #    直接吃掉本该留给后段（4_verify/4.6/6.5）的配额；
                # ② 默认 0.55 过大（实测 2.7 常跑到 816s，预算形同虚设）。
                # 现统一走 `_phase_budget`（(soft − reserve) × ratio）并下调到 0.30
                # ⇒ deep：(1200−420)×0.30 = **234s**，为 3_solve / 3.3 / 后段留空间。
                # 2026-09-13：改走**实测上限**口径（旧的比例切分 ratio 无实测依据，
                # 且把单题预算切成 234s 碎块、砍掉有用工作 —— 详见 `_phase_budget`
                # docstring）。本阶段上限 = 实测 max 1168s × 余量。
                _p4_cap = self._phase_budget(ctx, stage="2.7_subgoal_main")
                _p4_t0, _p4_saved_dl = self._phase_deadline_guard(ctx, _p4_cap)
                try:
                    self.sub_goal_solver.run(ctx)
                finally:
                    self._phase_deadline_restore(ctx, _p4_saved_dl)
                ctx._subgoal_main_done = True
                self.record(ctx, "control",
                            f"2.7 阶段预算 {_p4_cap:.0f}s"
                            f"（实耗 {time.time() - _p4_t0:.0f}s）")

            # C-lite（2026-09-03）：子目标蓝图 merge 产出后、候选生成前，
            # 数值攻击蓝图极值声称——009 型"蓝图心算错值"在求解前就证伪。
            # 审核修正（2026-09-03）：原读 `_blueprint_value_false`（带下划线），
            # 写入处是 `blueprint_value_false`（无下划线）→ 幂等守卫从未生效。
            if not getattr(ctx, "blueprint_value_false", None):
                try:
                    self._value_attack_blueprint(ctx, tier)
                except Exception as exc:  # noqa: BLE001  数值攻击失败不阻断主链路
                    # 2026-09-03 审核：原为 `pass` 无日志 → v17 全程 0 痕迹时
                    # 无法区分"未触发"与"异常被吞"（与 lean_gate 吞 AttributeError
                    # 同型）。改为 warning + 埋点，任何失败都留证据。
                    logger.warning("[C-lite] 数值攻击异常（已跳过）: %s: %s",
                                   type(exc).__name__, exc)
                    self.record(ctx, "value_attack",
                                f"数值攻击异常跳过: {type(exc).__name__}: {exc}")

            self._stage_start(ctx, "3_solve")
            # 3) 求解
            # deep 档：Plan-and-Execute 主路径先行（子目标分解逐步求解 + 每步 oracle 校验），
            # 让结构化计划-执行候选先进入后续客观审核与投票。
            if (tier == 'deep'
                    and getattr(self.config, 'deep_use_sub_goal', True)
                    and not getattr(ctx, '_subgoal_main_done', False)
                    and not ctx.state.emergency
                    and not ctx.gen_time_up()):
                self.record(ctx, "control", "deep 档 Plan-and-Execute 主路径先行（子目标分解）")
                # P4-2（2026-09-11）：deep 档 P&E 同样纳入阶段预算（否则它可独占 3_solve）
                # 2026-09-13：改走实测上限口径（实测 max 1148s × 余量）。
                _dsp_cap = self._phase_budget(ctx, stage="3_solve")
                _dsp_t0, _dsp_saved = self._phase_deadline_guard(ctx, _dsp_cap)
                try:
                    self.sub_goal_solver.run(ctx)
                finally:
                    self._phase_deadline_restore(ctx, _dsp_saved)
                self.record(ctx, "control",
                            f"3_solve(deep P&E) 阶段预算 {_dsp_cap:.0f}s"
                            f"（实耗 {time.time() - _dsp_t0:.0f}s）")

            # Solver 多路采样（候选数/温度分层按档位，solver 内部读取 ctx.tier）
            # L1 验证优先（2026-08-31）：剩余时间不足 verify_only_seconds 时
            # 停止生成新候选，把最后的时间留给验证投票。
            # 依据：A_base 30 题日志 170 次"剩余时间不足"跳过调用、
            # 117 次"验证拿到 None 默认判错" —— 生成阶段把时间烧光，
            # 验证投票被饿死（误杀正确候选）。verify_only 治的就是这个。
            # ⚠ D 组对照实测净 −1、p=1.0 → 默认关闭（verify_only_seconds=0），
            # 触发条件必须显式 > 0，避免 deadline 已过（remaining<0）时误触发。
            _remaining_before_solve = (
                ctx.deadline - time.time() if ctx.deadline else float("inf"))
            _verify_only_seconds = getattr(self.config, 'verify_only_seconds', 0)
            if _verify_only_seconds > 0 and _remaining_before_solve < _verify_only_seconds:
                ctx.state.verify_only = True
                self.record(ctx, "paper_pacer",
                            f"L1 验证优先：剩余 {_remaining_before_solve:.0f}s"
                            f" < {_verify_only_seconds}s，"
                            f"停止生成新候选，只保留验证",
                            verify_only=True)
            if not ctx.state.verify_only:
                # 2026-09-06 超时修复：生成侧软截止已到且已有候选 → 不再追加
                # 生成（solver.run 单次可能 200-300s），直接带现有候选进验证。
                # 无候选时仍必须跑（兜底产出第一候选）。
                if ctx.gen_time_up() and ctx.candidates:
                    self.record(ctx, "paper_pacer",
                                "生成侧软截止已到且已有候选，跳过追加生成"
                                "直接进入验证/审核")
                else:
                    # P4-2（2026-09-11）：3_solve 阶段预算上限。
                    # v5 冒烟实证：`3_solve` 是本链路的**预算黑洞**（单阶段耗 303–1094s；
                    # 014 至 3.6 累计 1348s，远超当时的生成截止 900s 达 448s）——原因是
                    # `solver.run` 内部虽查 `gen_time_up()`，但**单次 LLM 调用可达 200-300s**，
                    # 多次调用叠加即可穿越截止点。故对本次调用临时收紧 deadline，
                    # 使循环边界的检查真正生效。
                    # 2026-09-13：改走**实测上限**口径（实测 max 1148s × 余量）。
                    # 旧比例切分（0.30 × (soft−420)）无实测依据，且把预算切成
                    # 234s 碎块。跨阶段保护改由 `_gen_deadline` + `verify_reserve`
                    # 统一负责，不再在此扣 reserve。
                    _sp_cap = self._phase_budget(ctx, stage="3_solve")
                    # 2026-09-13 修复（Explore 审计发现）：此处原为**手写**收紧，
                    # 只改 `ctx.deadline`、**未改 `_gen_deadline`** ⇒ solver 内部
                    # 循环查的 `gen_time_up()`（看 _gen_deadline）完全不受本阶段
                    # 预算约束，单次 LLM 调用 200-300s 可反复叠加穿越预算
                    # （实测 3_solve 超预算 1.7×）。统一改用 _phase_deadline_guard
                    # （两个字段一起收紧），与 2.7 / 3.4 / 6.5 口径一致。
                    _sp_t0, _sp_saved = self._phase_deadline_guard(ctx, _sp_cap)
                    try:
                        self.solver.run(ctx)
                    finally:
                        self._phase_deadline_restore(ctx, _sp_saved)
                    self.record(ctx, "control",
                                f"3_solve 阶段预算 {_sp_cap:.0f}s"
                                f"（实耗 {time.time() - _sp_t0:.0f}s）")
            if not self._has_usable_candidate(ctx):
                # 2026-09-13 晚：判据从 `not ctx.candidates` 放宽为"无**可用**候选"。
                # 旧判据只看池子空不空，而 solver 原先会塞占位候选 ⇒ 池子非空但
                # 全是占位符，这条兜底（以及 `_emergency_direct_solve`）永远不触发。
                self.record(ctx, "control",
                            "Solver 未产出可用候选（空/占位符），触发兜底直接求解")
                self.pacer.end(tier=tier, soft=getattr(ctx, "soft_budget", None))
                return self._fallback_direct(ctx)

            self._stage_start(ctx, "3.2_complete")
            # 3.2) 截断候选续写：每档 max_completions 个（fast=0 跳过），应急模式跳过
            if (getattr(ctx, 'candidates', None)
                    and not ctx.state.emergency
                    and not ctx.state.verify_only):
                max_comp = self.config.tier_max_completions.get(tier, 1)
                if max_comp > 0:
                    n_completed = self.solver.complete_truncated_candidates(
                        ctx, max_count=max_comp)
                    if n_completed > 0:
                        self.record(ctx, "control",
                                    f"截断续写完成 {n_completed} 个候选")

            self._stage_start(ctx, "3.3_improve")
            # 3.3) Step 2 无条件自改进（IMO2025 论文流水线）：
            #      生成后、验证前，对候选先 review+improve 一遍（注入第二段推理
            #      预算）。论文实测初始解质量低、此步显著改进。
            #      仅非应急模式执行（2026-09-14：fast 档已删除，原
            #      `tier != 'fast'` 条件恒真 ⇒ 移除，见 difficulty_router）。
            if (getattr(self.config, 'enable_self_improve', True)
                    and not ctx.state.emergency
                    and not ctx.state.verify_only
                    and ctx.candidates
                    and self._self_improve_applicable(ctx)):
                # N1''（2026-09-11 修正）：3.3 是「验证前的最后改进机会」，也是论文
                # 验证的最大杠杆（22.2%→31.1%），**不能用生成侧软截止拦它**。
                # 原因：3.3 排在 2.7/3_solve 之后，而 gen_time_up() 用的是
                # _gen_deadline = deadline − verify_reserve(480s) = 720s ——
                # 走到这里时必然已越过 720s → 恒被跳过（smoke6_v2 六题 3.3 全为 0s）。
                # 改用**硬墙口径**：只要距 1200s 墙还够一次改进调用，就执行。
                _imp_left = float(ctx.time_remaining())
                if _imp_left > float(getattr(
                        self.config, "self_improve_min_left_sec", 150.0)):
                    # 注意：本调用已由上方条件块门控
                    # （`not ctx.state.verify_only` / `not ctx.state.emergency`）。
                    _imp_t0 = time.time()
                    n_imp = self.solver.improve_candidates(ctx)
                    # 2026-09-13：记录本阶段实耗，供 3.4 计算"改进类共享预算"的余额
                    # （两者语义重叠：3.3 是单 Agent 自审自改，3.4 是三 Agent 协作改进）。
                    try:
                        ctx._improve_phase_used = (float(
                            getattr(ctx, "_improve_phase_used", 0.0) or 0.0)
                            + (time.time() - _imp_t0))
                    except Exception:  # noqa: BLE001
                        pass
                    if n_imp > 0:
                        self.record(ctx, "control",
                                    f"Step2 自改进完成 {n_imp} 个候选"
                                    f"（剩余 {_imp_left:.0f}s）")
                else:
                    self.record(ctx, "control",
                                f"Step2 自改进跳过（剩余 {_imp_left:.0f}s "
                                f"< 门槛 {getattr(self.config, 'self_improve_min_left_sec', 150.0):.0f}s）")

            self._stage_start(ctx, "3.4_collab")
            # 3.4) deep 档难题：三Agent协作（解题→审查→整合→反复验证）
            #      只要时间未到且未验证通过，CollaborativeSolver 内部反复循环，
            #      保证难题高正确率。
            if (tier == 'deep'
                    and getattr(self.config, 'enable_collaborative_deep', True)
                    and not ctx.state.emergency
                    and not ctx.state.verify_only
                    and not ctx.gen_time_up()):
                # 2026-09-13 **加阶段预算**（照搬 2.7 / 3_solve 的 P4 做法）。
                # 实测（004 复现）：本阶段**此前无任何上限**，单题烧掉 **691s**，
                # 把 `3.3`(自改进) / `4_verify`(投票) / `6.5`(闸门) 全部挤成 0s
                # ⇒ 错误答案未经任何后续防线直接提交（1012 ≠ 2024）。
                # 另：`3.3` 与 `3.4` 语义重叠（都是"生成后改进候选"），故二者
                # **共享"改进阶段总预算"**：`3.3` 先用、`3.4` 只用余额 ⇒
                # 既保住 3.3（论文实测 22.2%→31.1% 的强杠杆），又不让 3.4 重复吃时间。
                # 2026-09-13：改走**实测上限**口径（3.4 实测 max 691s × 余量）。
                # 3.3 与 3.4 语义重叠（都是"生成后改进候选"），继续共享同一额度：
                # 3.3 先用，3.4 只用余额。
                _improve_total = self._phase_budget(ctx, stage="3.4_collab")
                _imp_used = float(getattr(ctx, "_improve_phase_used", 0.0) or 0.0)
                _collab_cap = max(60.0, _improve_total - _imp_used)
                _collab_t0, _collab_saved = self._phase_deadline_guard(ctx, _collab_cap)
                try:
                    self.record(ctx, "control", "deep 档启用三Agent协作验证机制")
                    self.collab.run(ctx)
                finally:
                    self._phase_deadline_restore(ctx, _collab_saved)
                self.record(ctx, "control",
                            f"3.4 阶段预算 {_collab_cap:.0f}s"
                            f"（改进共享预算 {_improve_total:.0f}s − 3.3 已用 "
                            f"{_imp_used:.0f}s；实耗 {time.time() - _collab_t0:.0f}s）")

            self._stage_start(ctx, "3.5_subgoal_sup")
            # 3.5) 子目标分解补充候选：仅非 deep 档（deep 档已作为主路径提前执行）
            # 2026-08-30（#45 移除题型分流）：原逻辑带 `or is_proof`，即证明题
            # **无条件**触发子目标分解。但 IMO 基本全是证明题，该分支等于让
            # 全部题目都多跑一轮子目标规划 —— 而 #43 归因已证明：错题主因是
            # 时间分配错误（规划抢走了真正写题的预算）。故去掉题型条件，
            # 只保留与题型无关的统一触发条件：候选不足时才补。
            use_sub = getattr(self.config, 'use_sub_goal', False)
            if (tier != 'deep'
                    and use_sub
                    and not getattr(ctx, '_subgoal_main_done', False)
                    and not ctx.state.verify_only
                    and not ctx.gen_time_up()
                    and len(ctx.candidates) < 2):
                self.record(ctx, "control",
                            "触发子目标分解补充候选",
                            sub_goal_trigger=f"tier={tier}, "
                                             f"candidates={len(ctx.candidates)}")
                self.sub_goal_solver.run(ctx)

            self._stage_start(ctx, "3.6_audit_filter")
            # 3.6) 候选客观审核（2026-09-06 晚：Lean 双通道 + AuditGate 串行）。
            # lean 可用 → 先 LeanGate.apply（内部按题型/档位自判：证明题全档整题
            # verify 淘汰 proof_invalid 并收 revise 反馈；非证明题 lean_gate_nonproof
            # 默认关 → 秒级记录跳过，零成本）；随后 AuditGate.audit_candidates 照跑
            # （证明题 rubric 默认关 → 空转零成本；非证明题 Level0 数值代回核验照旧，
            # 与去 Lean 期完全一致）。lean 不可用 → 纯 AuditGate（现状 AI 判分链）。
            # L1：verify_only 时跳过（把剩余时间留给验证投票）。
            if ctx.state.verify_only:
                self.record(ctx, "audit_gate",
                            "L1 验证优先：跳过 AuditGate 候选审核（时间不足）")
            else:
                _audit_total = len(ctx.candidates)
                # 2026-09-10：适用性豁免题（选项字母/判断值/概念文字答案）不进
                # LeanGate（结构上无从形式化）；下方 AuditGate.audit_candidates
                # 仍照跑（Level0 数值代回等），即「豁免 Lean，不豁免检测」。
                if self._lean_active() and self._lean_applicable(ctx):
                    _lt = len(ctx.candidates)
                    lean_kept, lean_fb = self.lean_gate.apply(
                        ctx, tier, ctx.candidates)
                    if lean_kept:
                        ctx.candidates = lean_kept
                        self.record(ctx, "lean_gate",
                                    f"Lean 硬验证通过 {len(lean_kept)}/{_lt} 候选")
                    if lean_fb:
                        ctx.audit_reject_feedback = list(
                            getattr(ctx, "audit_reject_feedback", []) or []
                        ) + lean_fb
                        # 2026-09-12 新增（用户要求「把 Lean 发现的错误总结并反馈
                        # 大模型、筛掉明显逻辑错误的候选」）：**单独留一份** Lean
                        # 反馈，供 revise prompt 区分「Lean 编译器发现的形式化/逻辑
                        # 缺陷」与「AuditGate 的数值/格式缺陷」——原先两者混在
                        # 同一条 ③ 里，模型无从判断哪条才是"逻辑错了"。
                        try:
                            ctx.lean_reject_feedback = list(lean_fb)
                        except Exception:  # noqa: BLE001
                            pass
                        self.record(ctx, "lean_gate",
                                    f"Lean 硬验证淘汰 {len(lean_fb)} 候选，"
                                    f"revise 将注入 Lean 反馈")
                audit_kept, audit_feedbacks = self.audit_gate.audit_candidates(
                    ctx, tier, ctx.candidates)
                if audit_kept:
                    ctx.candidates = audit_kept
                    self.record(ctx, "audit_gate",
                                f"客观审核通过 {len(audit_kept)}/{_audit_total} 候选")
                if audit_feedbacks:
                    ctx.audit_reject_feedback = list(
                        getattr(ctx, "audit_reject_feedback", []) or []
                    ) + audit_feedbacks
                    self.record(ctx, "audit_gate",
                                f"客观审核淘汰 {len(audit_feedbacks)} 候选，"
                                f"revise 将注入审核反馈")

            self._stage_start(ctx, "4_verify")
            # 4) 验证（投票数按档位：fast=1/standard=1/deep=3）
            # P0-4 修复：playoff 复算按时间宽裕度开关，deep 档且时间宽裕时启用
            #
            # 2026-08-31 修复 NameError：#45 移除题型分流时把 3.5 步的
            # `is_proof = ...` 赋值一起删了，但这里的 verifier.run 仍在用它 →
            # 每题抛 `name 'is_proof' is not defined`，整条流水线走异常兜底。
            # 说明：#45 要移除的是「**子目标触发** / **Lean 门禁**看题型」，
            # 验证器的 is_proof 是另一回事（verifier.py 用它决定单候选时的
            # 严格度），属于正当用途，必须保留。
            is_proof = (getattr(ctx, 'question_type', '') == '证明题'
                        or getattr(ctx, 'domain', '') in ('证明', '证明题'))
            tier_votes = self.config.tier_voting_times.get(tier, 1)

            # P1 v3（2026-09-11）：验证硬信号 → 强制重解（official112 头号靶点）。
            # 演进记录（三次实测定位）：
            #   v1：位于 4.6 对抗验证（363s）之后 + `gen_time_up()` 护栏 → 冒烟 4/4 未触发；
            #   v2：前移到 4_verify 之后 + 硬墙剩余护栏 → 复测仍未触发：002 到 4_verify
            #       结束已用 1201s、010 用 1110s（剩余 90s < 240s 门槛）。
            #   → 结论：**4_verify 结束时时间已耗尽**，护栏怎么调都晚。
            # v3 定位：3.6 候选筛选之后 / 4_verify 之前（tier_votes 已就绪）。典型时点
            #   约 600-700s，剩余 500s+，足够一轮重解（约 100-200s）。
            #   ver_result 此时尚未生成 → 传 {}；_deep_revise_loop 会走默认 feedback 并把
            #   audit_reject_feedback 中的硬信号拼入，正是所需的定向修正输入。
            # 信号源（均为该点之前已产生）：数值攻击证伪（蓝图阶段，写 blueprint_value_false）、
            #   AuditGate reject（3.6 阶段）。final_gate 在 6.5 才产生，晚于此处，不纳入。
            if not getattr(ctx, "_p1_triggered", False):
                _p1_msgs = []
                if getattr(ctx, "blueprint_value_false", None):
                    _p1_msgs.append(
                        f"[数值攻击证伪] {str(ctx.blueprint_value_false)[:200]}")
                _p1_ag = [g for g in (getattr(ctx, "audit_gate", None) or [])
                          if isinstance(g, dict)
                          and (g.get("verdict") or "") == "reject"]
                if _p1_ag:
                    _p1_msgs.append("[客观审核拒绝] " + str(
                        _p1_ag[-1].get("reason") or "")[:200])
                # ★ 2026-09-11 修复：补上「3.6 阶段 Lean 候选级淘汰」信号。
                # 原因（v7 实测 014）：`final_gate` 的 proof_invalid 在 **6.5** 才产生，
                # 晚于本检查点（4_verify 之前）→ 结构上不可见，导致"有时间、有信号却
                # 不触发"。3.6 的候选级 LeanGate.apply 会写"淘汰 N 候选"记录，位于本点之前。
                # 2026-09-12 修复（消除脆耦合）：改用**结构化字段**取该信号。
                # 原实现是"在 trace 里匹配 content 是否含中文子串『淘汰』"—— 一旦
                # 有人改写那句日志文案（如"淘汰"→"筛除"），P1 会**静默地不再触发**
                # 且无任何报错（典型"改文案即功能失效"，且不可观测）。
                # 注意本块上面两个信号源（blueprint_value_false、audit_gate[].verdict）
                # 本来就是结构化字段，此处统一口径。
                # `ctx.lean_reject_feedback` 由 3.6 的 Lean 淘汰分支写入（同一时点之前）。
                _p1_lg = list(getattr(ctx, "lean_reject_feedback", None) or [])
                if _p1_lg:
                    _p1_msgs.append(
                        "[Lean 候选级验证淘汰] " + str(_p1_lg[-1])[:200])
                if (_p1_msgs and tier in ("deep", "standard")
                        and not ctx.state.emergency
                        and ctx.time_remaining() > 150):
                    ctx._p1_triggered = True
                    ctx.audit_reject_feedback = list(
                        getattr(ctx, "audit_reject_feedback", []) or []) + _p1_msgs
                    self.record(ctx, "revise",
                                "P1 硬信号触发强制重解"
                                f"（{len(_p1_msgs)} 条，tier={tier}，"
                                f"剩余 {ctx.time_remaining():.0f}s）")
                    _p1_before = str(getattr(ctx, "final_answer", "") or "")
                    self._deep_revise_loop(ctx, {}, tier_votes, force=True)
                    # G1（2026-09-11）：记录重解成效——此前只能看到"触发了"，
                    # 看不到"改没改、改成什么样"，导致"触发但无效"无法量化。
                    _p1_after = str(getattr(ctx, "final_answer", "") or "")
                    self.record(
                        ctx, "revise",
                        f"P1 重解成效：{'答案已变化' if _p1_after != _p1_before else '答案未变化'}"
                        f"（{len(_p1_before)}→{len(_p1_after)} 字符）")
                    # 2026-09-13（用户原则："无用功要保证检测并截断，但不得影响原有
                    # 功能"）：把已记录的成效**变成决策依据** —— 重解后答案未变化时
                    # 打标记，后续同源的 revise（4.6 对抗 / 5 全0票 / 5.5 低置信）
                    # 不再对**同一个答案**重复重解。
                    # 保守性：仅在"答案完全未变"时置位；一旦答案变化即视为有进展，
                    # 标记在下一轮由 final_answer 变化自动失效（见下游判断）。
                    if _p1_after == _p1_before:
                        try:
                            ctx._revise_no_progress_answer = _p1_after
                        except Exception:  # noqa: BLE001
                            pass
                else:
                    # 2026-09-12 可观测性补强（Bug 4 跟进）：P1"0 触发"必须能区分
                    # 是「**没有硬信号**」还是「**有时间但因档位/emergency/门槛被拦**」。
                    # 此前两者在日志里都表现为"什么都没记"，导致无法定位。
                    # 事件名用 `p1_check`（不写 `revise`）以免污染 revise 统计口径。
                    _p1_why = []
                    if not _p1_msgs:
                        _p1_why.append(
                            "无硬信号（数值攻击证伪 / AuditGate reject / "
                            "3.6 Lean 候选级淘汰 三者皆空）")
                    if tier not in ("deep", "standard"):
                        _p1_why.append(f"档位 {tier} 不在 deep/standard")
                    if ctx.state.emergency:
                        _p1_why.append("处于 emergency 状态")
                    if ctx.time_remaining() <= 150:
                        _p1_why.append(
                            f"剩余 {ctx.time_remaining():.0f}s ≤ 150s 门槛")
                    if _p1_why:
                        self.record(ctx, "p1_check",
                                    "P1 未触发：" + "；".join(_p1_why))

            # 2026-09-02 老师需求：候选池统一封顶（兜底所有生成路径：
            # 初始/改进/续写/协作/子目标/revise 追加总量都可能超）
            # 2026-09-04：cap 8→6（deep 候选 4→3 配套，验证成本 -25%；
            # 平台实测候选边际收益低，杠杆在验证器错因质量，不在堆候选）
            _pre_verify_n = len(ctx.candidates or [])
            if _pre_verify_n > 6:
                ctx.candidates = (ctx.candidates or [])[:6]
                self.record(ctx, "control",
                            f"候选池 {_pre_verify_n} → 6（统一封顶）")
            # 2026-09-13：过滤「非答案形态」候选。
            # 096 实测：候选 answer 字段里混入 Markdown 标题 `### 选项A分析`，
            # 因其 len>3 且不含拒绝词，被计入选择题投票 ⇒ **污染投票分布**。
            # 只过滤**明确的行首结构标记**（标题/列表/引用/表格），
            # 不碰正文类长答案（统计学的论述题 gold 本就是长文本）。
            try:
                _clean = [
                    _c for _c in (ctx.candidates or [])
                    if not _re.match(
                        r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s|\|\s)",
                        (getattr(_c, "answer", "") or ""))]
                if _clean and len(_clean) < len(ctx.candidates or []):
                    self.record(ctx, "control",
                                "过滤非答案形态候选 {} → {}".format(
                                    len(ctx.candidates), len(_clean)))
                    ctx.candidates = _clean
            except Exception:  # noqa: BLE001
                pass
            ver_result = self.verifier.run(
                ctx, problem=ctx.problem, candidates=ctx.candidates,
                use_clustering=True,
                use_scoring=self.config.use_scoring,
                is_proof=is_proof,
                use_playoff=(
                    (tier == 'deep' and getattr(self.config, 'deep_use_playoff', True))
                    or (tier != 'deep' and ctx.state.playoff_enabled)
                ),
                use_deterministic=getattr(self.config, 'enable_deterministic', True),
                use_rubric=getattr(self.config, 'use_rubric', False),
                use_challenge=getattr(self.config, 'use_challenge', False),
                voting_times=tier_votes,
            )
            ctx.verdicts = self._verdicts_from_ver_result(ver_result, ctx.candidates)
            ctx._best_cluster = ver_result.get("best_cluster")
            ctx._cluster_data = ver_result.get("cluster_data", [])

            self._stage_start(ctx, "4.5_oracle")
            # 4.5) deep 档：AnswerOracle 客观复核 best_cluster（区别于投票同源自评）
            # 2026-09-06 超时修复（验证暴露残留洞）：oracle 复核单次可达 300s+，
            # 原只在内部查 is_time_critical（deadline-60s）→ algebra-003 修复后
            # verify 提前完成反而给 oracle 打开 365s 烧穿窗口（elapsed 1402s）。
            # oracle 是"4_verify 之后的复核增强"，到生成侧软截止即弃——
            # verify 已投过票，放弃复核不损失主验证，只少一层 deep 深查。
            if (tier == 'deep'
                    and getattr(ctx, '_best_cluster', None) is not None
                    and not ctx.gen_time_up()
                    and self._enhance_window_ok(ctx, "oracle")):
                self._oracle_review_best(ctx, ver_result, tier_votes)

            self._stage_start(ctx, "4.6_adv")
            # 4.6) 对抗式验证（#16）：正向通过后主动证伪，抓漏检。
            #      仅当"确有候选被正向判对"时才跑——正向全错的会走 revise，
            #      再证伪一次是纯浪费（每轮调用都吃预算，见 #43 归因）。
            _any_correct = any(
                getattr(v, 'correct_votes', 0) > 0 for v in (ctx.verdicts or []))
            if _any_correct:
                # 2026-09-04 修复：对抗检出错误 → 立即触发定向修正（原反馈滞留 bug）。
                # 原实现仅把反馈塞进 audit_reject_feedback（曾名 lean_reject_feedback），
                # 而 5（全 0 票）/5.5（置信<0.5）触发条件都看投票共识 → 验证器自信
                # 通过时对抗检出的错误无人消费、答案带错提交（与 4.5 Oracle 判错即
                # revise 不对称）。误报风险由 Step4 _review_bug_feedback 复核兜底，
                # 死循环由 revise_round 全局上限 5 + 时间检查防护。
                if self._adversarial_probe(ctx, tier):
                    self._deep_revise_loop(ctx, ver_result, tier_votes)

            self._stage_start(ctx, "5_revise_or_fallback")
            # 5) 全部 0 正确票：
            #    - deep 档：先 revise 自纠错回环（最多 deep_revise_rounds 轮）
            #    - 其他档：直接兜底直接求解
            if (ctx.verdicts
                    and all(v.total_votes > 0 for v in ctx.verdicts)
                    and all(v.correct_votes == 0 for v in ctx.verdicts)):
                revised_ok = False
                if (tier == 'deep' and not ctx.state.emergency
                        and not ctx.gen_time_up()):
                    revised_ok = self._deep_revise_loop(ctx, ver_result, tier_votes)
                if not revised_ok:
                    self.record(ctx, "control", "全部 0 正确票，触发兜底直接求解")
                    # 2026-09-02 bug 修复：不再提前 return！
                    # 旧代码 direct_solve/_pick_best 后直接 return，跳过了
                    # formatter(6步：占位符拦截/截断续写/拒绝兜底) 和
                    # 6.5 AuditGate 最终闸门 → 闸门 10/10 题 0 执行、
                    # 003 直答 "No such function" 裸奔的根因。
                    # 现改为：兜底答案先存入 ctx.final_response，落回统一出口，
                    # 由 formatter 校验/修复（候选都差时保留预设答案），
                    # 再进 6.5 AuditGate 闸门把关，最后统一 return。
                    direct_answer = self.solver.direct_solve(ctx)
                    if direct_answer:
                        ctx.final_response = direct_answer
                    else:
                        ctx.final_response = self._pick_best_from_candidates(ctx) or ""
                    # 标记 0 票兜底路径：formatter 需要它来判断是否保留预设答案
                    ctx._zero_vote_fallback = True

            self._stage_start(ctx, "5.5_low_conf")
            # 5.5) 低置信度强制复核（v2.6 杀掉虚高置信度）：
            #   deep 档 best_cluster 置信度 < 0.5（正确票未过半，验证器自身都不确定）
            #   且时间/预算宽裕时，不自信接受低共识答案，而是触发 revise 提升共识。
            # 所有档位（不只 deep）启用低置信度强制复核：
            # 只要投票共识 < 0.5（验证器自身都不确定），就不再"自信接受"错答案，
            # 而是触发 revise 反复验证，直到获得正确票或超时/预算耗尽。
            _bc = getattr(ctx, '_best_cluster', None)
            if (_bc is not None
                    and getattr(_bc, 'confidence', 1.0) < 0.5
                    and not ctx.state.emergency
                    and not ctx.gen_time_up()):
                self.record(
                    ctx, "control",
                    f"deep 档低置信度({_bc.confidence:.2f})，强制 revise 复核提升共识",
                )
                self._deep_revise_loop(ctx, ver_result, tier_votes)

            self._stage_start(ctx, "6_format")
            # 6) 格式化输出
            self.formatter.run(ctx)

            self._stage_start(ctx, "6.5_audit_gate")
            # 6.5) 最终答案闸门（2026-09-06 晚：Lean/AuditGate 双后端路由）。
            #      Lean 环境可用 → LeanGate.gate_final_answer：证明题整题 verify、
            #      非证明题 verify_answer（norm_num/ring 答案锚定核验，5-21s），
            #      proof_invalid/unknown → 拒绝换候选（老师 9/2：Lean 一定不能跳过；
            #      9/3：无法验证/未知必须默认拒绝，不许裸奔）；
            #      Lean 不可用 → AuditGate.gate_final_answer（Level0 程序硬核验等，
            #      平台 AI 判分兜底，与去 Lean 期完全一致）。
            #      验不过 → 换候选（按答案与 final 不同的顺序试 ≤2 个）。
            # gate_final_answer 内部已自护：空答案放行、time_remaining<15s
            # 或 budget.skip 才跳过；rubric 高置信 B 才打回（宁 unknown 不误杀）。
            #  2026-09-10：再叠加「按题适用性」——豁免题（答案非数学对象）
            #      不改路由到 Lean，改用 AuditGate 做最终闸门，绝不裸奔。
            _gate_lean = self._lean_active() and self._lean_applicable(ctx)
            if ((_gate_lean or getattr(self.config, 'enable_audit_gate', True))
                    and ctx.final_response):
                _gk = "lean_gate" if _gate_lean else "audit_gate"
                _gate = self.lean_gate if _gate_lean else self.audit_gate
                try:
                    # 2026-09-03 老师：不到 1200s 且审核判错就**不放过**，
                    # 一直换候选重做、时间到 1200s 才放行 —— 该"不放过"规则自
                    # 2026-09-04 起**仅保留给 deep 档**（见下方 2026-09-04 档位封顶说明）。
                    # 同时把上一轮审核反馈注入到 revise_feedback（让 LLM 重生成时能看到具体错）。
                    import time as _t3
                    _hard_end = ctx.start_time + float(
                        getattr(self.config, "max_time_per_question", 1200))
                    # 2026-09-04 按档位封顶（治本：2534334 平台 64 invalid = 时间墙归因）。
                    # 此前 6.5 对**所有档**都用 1200s 硬限 → fast/standard 题也被拖到
                    # 墙边，重做耗尽的题整题超时无最终答案。现改为：
                    #   fast/standard：最多 2 次打回，且整题时间超 tier_budget 即放行；
                    #   deep：保留"做到 1200s"，但每次打回前保证剩余时间够完成。
                    _tbl_budget = getattr(self.config, 'tier_budget', None) or {}
                    _tier_budget = float(_tbl_budget.get(tier, 1200.0))
                    # ⚠ 2026-09-13 修复（审查发现；这是会导致**计 C（0 分）**的严重问题）：
                    # 原式 `min(_hard_end, start + _tier_budget)`，而 deep 档
                    # tier_budget=1150 恰等于 max_time_per_question ⇒ **与硬墙完全相等、
                    # 零余量**。但 while 循环体内会调 `solver.run`（**单次 200-300s、
                    # 不可中断**），而护栏只在"发起时刻"判断（`<_rework_deadline - 5`）、
                    # **不约束调用时长** ⇒ 只要在剩余 200-300s 时发起一次重做，就会
                    # 跨过 1150/1200 硬墙：平台**终止整个进程组、不执行 finally**，
                    # 该题**计 C 且分母不变**。
                    # 修复：为"一次重做 + 闸门复验"预留 `_rework_reserve`（默认 300s），
                    # 让循环体内的 solver.run 必定能在硬墙前跑完。
                    try:
                        _rework_reserve = float(
                            os.environ.get("REWORK_RESERVE_SEC", "300"))
                    except (TypeError, ValueError):
                        _rework_reserve = 300.0
                    _rework_deadline = min(
                        _hard_end,
                        ctx.start_time + _tier_budget) - max(0.0, _rework_reserve)
                    # 2026-09-12 A4 修复（Bug 2：6.5 成为新的时间黑洞）：
                    # 此前 deep 档 `_max_rework=None`（**无上限**）→ 实测 #000 单题
                    # 6.5 占 531s（44%）、#006 占 31%，"砍掉 4.6 省下的时间被 6.5
                    # 吃回去"。且 unknown→strict_reject 的题**重做后输出不变**
                    # （17 次 strict_reject 白烧 1520s，只烧时间不改输出）。
                    # 现给 deep 档设上限（默认 3 次，与 standard 的 2 次对称）；
                    # `DEEP_MAX_REWORK=-1` 恢复旧行为（无上限），便于 A/B 与回退。
                    try:
                        _deep_cap = int(os.environ.get("DEEP_MAX_REWORK", "3"))
                    except (TypeError, ValueError):
                        _deep_cap = 3
                    # 2026-09-14：fast 档已删除 ⇒ 原 `tier in ("fast","standard")`
                    # 简化为 `tier == "standard"`。
                    _max_rework = (2 if tier == "standard"
                                   else (None if _deep_cap < 0 else _deep_cap))
                    best_reasoning = ""
                    for _c in (ctx.candidates or []):
                        if getattr(_c, "answer", "") == ctx.final_response:
                            best_reasoning = getattr(_c, "reasoning", "") or ""
                            break
                    # 2026-09-13 联动修复（实测驱动）：若该答案在 answer_selfcheck
                    # 里被判"涉高危运算却无 <calc> 工具来源"且因剩余不足未重问，
                    # 则**不接受** Lean 的 answer_valid —— 它只证明"LLM 写的那个
                    # 命题可被证明"，在题面无 ≥3 位数字时会退化为"自证放行"
                    # （实测 010：错误答案 0 被判 answer_valid，见
                    #   lean_bridge._cross_check_problem_symbols 注释）。
                    # 此处改判为需重做，进入下方 while 重生成循环。
                    _su = str(getattr(ctx, "selfcheck_unverified_answer", "")
                              or "").strip()
                    # 2026-09-13 方案 C-B：**计算冲突**优先级更高 —— 答案与本地
                    # 精确计算器（calc_tool/SymPy）的结果直接矛盾时，无论 Lean 判
                    # 什么（answer_valid 只证明"LLM 写的命题可证"），一律不放行。
                    # 这把"数值答案正确性"的裁决权从 Lean 收回给计算器。
                    _ci = bool(getattr(ctx, "calc_inconsistent", False))
                    if _ci:
                        self.record(
                            ctx, "final_gate",
                            "答案与本地精确计算器结果冲突（calc_inconsistent）"
                            "→ 拒绝放行，按需重做")
                        g_ok = False
                    elif _su and _su in str(ctx.final_response or ""):
                        self.record(
                            ctx, "final_gate",
                            f"答案 {_su[:40]} 涉高危运算却无 <calc> 工具来源"
                            "（selfcheck 未核验）→ 不接受 Lean answer_valid，按需重做")
                        g_ok = False
                    else:
                        g_ok = _gate.gate_final_answer(
                            ctx, tier, ctx.final_response, best_reasoning)
                    _tried = 0
                    _last_feedback = ""
                    while (not g_ok
                           and _t3.time() < _rework_deadline - 5
                           and (_max_rework is None or _tried < _max_rework)):
                        # 取最近一条闸门拒绝反馈（写 ctx.lean_gate / ctx.audit_gate；
                        # lean 的拒绝 verdict=proof_invalid/unknown，audit 的=reject）
                        for _entry in reversed(getattr(ctx, _gk, []) or []):
                            if (_entry.get("step") == "final_gate"
                                    and _entry.get("verdict")
                                    in ("reject", "proof_invalid", "unknown")):
                                _last_feedback = (_entry.get("feedback")
                                                  or _entry.get("reason") or "")[:400]
                                break
                        # 注入到 revise_feedback 供 LLM 重生成时参考
                        if _last_feedback:
                            ctx.revise_feedback = list(ctx.revise_feedback) + [
                                f"[审核闸门反馈] 上一候选 (#{_tried+1}) "
                                f"未通过客观审核：{_last_feedback}"
                            ]
                        self.record(ctx, _gk,
                                    f"审核拒候选 #{_tried+1}（本档位重做剩余 "
                                    f"{int(_rework_deadline - _t3.time())}s）继续换/重做")
                        # 换下一候选（按置信度）试；候选换尽后 → 让 Solver 读
                        # 审核反馈**重新生成**新候选（真正的"告诉 AI 错哪了"闭环）
                        _next = None
                        for _c in sorted(
                                ctx.candidates or [],
                                key=lambda c: getattr(c, "confidence", 0.0),
                                reverse=True):
                            if _c.answer == ctx.final_response:
                                continue
                            if not getattr(_c, "answer", ""):
                                continue
                            if _c.id in (getattr(ctx, "_gate_tried", []) or []):
                                continue
                            _next = _c
                            break
                        if _next is None:
                            # 候选已全部试过 → 触发 Solver 读反馈重新生成（重做到对）
                            # 2026-09-04：重生成 ≈ 生成(~60-120s) + 闸门验证(秒级)，
                            # 剩余 <180s 时无法保证完成 → 不再打回，提交当前答案碰运气。
                            if _t3.time() < _rework_deadline - 180:
                                self.record(
                                    ctx, _gk,
                                    "所有候选未过客观审核，触发 Solver 读反馈重新生成"
                                    f"（revise_feedback 已含 {_tried+1} 条审核定位）")
                                try:
                                    # solver.run 内部：ctx.revise_round>0 且
                                    # ctx.revise_feedback 非空 → 走 _generate_revise
                                    # （读反馈定向修正，见 solver.py:122）。
                                    # **先腾位**：候选池已满 6（cap）时 solver.run
                                    # remaining=0 直接 return 不生成 → 保留已过
                                    # 审核的最优候选，其余清空给新候选腾位。
                                    _pass_cands = []
                                    for _cc in (ctx.candidates or []):
                                        if _cc.id in (getattr(ctx, "_gate_tried", []) or []):
                                            _pass_cands.append(_cc)  # 未过审核的作参考保留
                                    ctx.candidates = _pass_cands[:3]  # 腾位
                                    ctx.revise_round = getattr(ctx, "revise_round", 0) + 1
                                    _before = len(ctx.candidates or [])
                                    self.solver.run(ctx)
                                    if len(ctx.candidates or []) > _before:
                                        _tried += 1
                                        _fresh = ctx.candidates[-1]
                                        ctx.final_response = _fresh.answer
                                        g_ok = _gate.gate_final_answer(
                                            ctx, tier, _fresh.answer,
                                            getattr(_fresh, "reasoning", "") or "")
                                        if g_ok:
                                            self.record(
                                                ctx, _gk,
                                                f"Solver 读审核反馈重生成的候选 "
                                                f"#{_fresh.id} 过闸门，采用")
                                        continue  # 未过则回到 while 顶部继续
                                except Exception as _e2:  # noqa: BLE001
                                    self.record(ctx, _gk,
                                                f"审核反馈重生成异常: {str(_e2)[:120]}")
                            self.record(ctx, _gk,
                                        "重生成后仍无候选过审核或时间不足，停")
                            break
                        # 2026-09-04：换候选=再验 1 次，剩余 <35s 时打完
                        # 就到墙边，不再打回，直接提交当前答案（避免撞 1200s 无答案）。
                        if _rework_deadline - _t3.time() < 35:
                            self.record(ctx, _gk,
                                        f"剩余 {int(_rework_deadline - _t3.time())}s "
                                        "不足完成换候选验证，停")
                            break
                        _tried += 1
                        ctx._gate_tried = list(getattr(ctx, "_gate_tried", []) or []) + [_next.id]
                        ctx.final_response = _next.answer
                        g_ok = _gate.gate_final_answer(
                            ctx, tier, _next.answer,
                            getattr(_next, "reasoning", "") or "")
                        if g_ok:
                            self.record(ctx, _gk,
                                        f"换候选 #{_next.id} 过审核闸门，采用其答案")
                    if not g_ok:
                        ctx.gate_rejected = True
                        self.record(ctx, _gk,
                                    f"{tier} 档审核重做达上限仍拒（{_tried} 次换候选/重生成），"
                                    "当前答案标 rejected 放行")
                except Exception as _e:  # noqa: BLE001  闸门异常绝不阻断
                    self.record(ctx, _gk,
                                f"审核闸门异常，降级放行: {str(_e)[:120]}")

            self.pacer.end(tier=tier, soft=getattr(ctx, "soft_budget", None))

            # 阶段耗时收尾（2026-09-03）：统一 stop 全部 19 阶段（之前 start 在阶段开始）
            for _stg in ("0_paper_pacer","1_classify","2.5_difficulty","2.6_pre_audit",
                         "2.65_calc_prewarm",
                         "2.7_subgoal_main","3_solve","3.2_complete","3.3_improve",
                         "3.4_collab","3.5_subgoal_sup",
                         "3.6_audit_filter","4_verify","4.5_oracle","4.6_adv",
                         "5_revise_or_fallback","5.5_low_conf","6_format","6.5_audit_gate"):
                self._stage_stop(ctx, _stg)

            # 构建返回
            candidates_out = [
                {"id": c.id, "answer": c.answer,
                 "reasoning": c.reasoning, "revised": c.revised}
                for c in ctx.candidates
            ]
            verdicts_out = [
                {"id": v.id, "answer": v.answer,
                 "confidence": v.confidence,
                 "correct_votes": v.correct_votes,
                 "total_votes": v.total_votes,
                 "feedback": v.feedback}
                for v in (ctx.verdicts or [])
            ]
            cluster_out = None
            bc = getattr(ctx, '_best_cluster', None)
            if bc:
                cluster_out = {
                    "answer_norm": bc.answer_norm,
                    "size": bc.size,
                    "confidence": bc.confidence,
                    "candidate_ids": bc.candidate_ids,
                }
            # 最终答案后处理（P2 强制数值化 + P5 客观题自检）——统一出口挂载，
            # 每项带独立开关与埋点，便于单次评测逐项审查（2026-09-11 用户指示）
            ctx.final_response = self._final_answer_postprocess(ctx)

            return safe_json_serialize({
                "final_response": ctx.final_response or "",
                "trace": ctx.trace,
                "candidates": candidates_out,
                "verdicts": verdicts_out,
                "cluster": cluster_out,
                # AI 实际检索/引用过的 Mathlib 定理（#1/#2 证据链）
                "used_theorems": list(ctx.used_theorems or []),
                # 检索/命中/编译通过统计（回应"调用频繁但定理不多"）
                "mathlib_usage_stats": {
                    **(ctx.mathlib_usage_stats or {}),
                    "distinct_theorems": len(ctx.used_theorems or []),
                },
                # ---- 逐步归因诊断（2026-09-02 用户要求：错题要能定位到环节）----
                # 统一由 _collect_diag 构建（全 getattr 兜底：提前 return / 异常路径也覆盖）
                "diag": self._collect_diag(ctx),
            })
        except Exception as e:  # noqa: BLE001
            logger.error("Orchestrator run failed: %s", e)
            try:
                self.pacer.end(soft=getattr(ctx, "soft_budget", None))
            except Exception:
                pass
            return self._fallback(ctx, problem, e)

    # ----------------------------------------------------------
    # 快车道：可确定性求解的题目直接用 SymPy 短路
    # ----------------------------------------------------------
    _FAST_PATH_PATTERNS = [
        (r"\d+\s*[\+\-\*/×÷]\s*\d+", "arithmetic"),
        (r"(?:calculate|compute|evaluate)\b", "arithmetic"),
        (r"(?:求导|导数|微分|derivative?|differentiate|f'|f''|d/dx)", "derivative"),
        (r"(?:积分|∫|integral|integrate)", "integral"),
        (r"(?:行列式|determinant|det\s*\(|矩阵的?行列式)", "determinant"),
        (r"(?:解(?:方程|方程组)|solve.{0,6}equation)", "equation"),
        (r"(?:一元二次|二次方程|quadratic)", "quadratic"),
        (r"(?:极限|limit)", "limit"),
    ]

    _FAST_PATH_TIME_LIMIT = 20.0  # 快车道总耗时上限（秒），超限即放弃、回退主流程

    def _fast_path(self, ctx: TaskContext) -> str | None:
        problem = ctx.problem or ""
        start = time.time()
        for pattern, tag in self._FAST_PATH_PATTERNS:
            if not _re.search(pattern, problem, _re.IGNORECASE):
                continue
            self.record(ctx, "fast_path", f"检测到可快车道求解题型: {tag}")
            if not _HAS_SYMPY:
                self.record(ctx, "fast_path", "SymPy 未安装，跳过快车道")
                continue
            # 耗时控制：超过预算立即放弃快车道，避免过度消耗时间
            if time.time() - start > self._FAST_PATH_TIME_LIMIT:
                self.record(ctx, "fast_path", "快车道耗时超限，放弃，回退主流程")
                return None
            result = self._try_sympy_solve(problem, tag)
            if result:
                self.record(ctx, "fast_path", f"快车道 SymPy 求解成功: {result}")
                return result
            self.record(ctx, "fast_path", f"快车道 {tag}: SymPy 求解失败，回退")
        return None

    def _try_sympy_solve(self, problem: str, tag: str) -> str | None:
        extract_prompt = (
            "请从以下题目中提取**核心数学表达式**（只输出表达式，不要额外文字）。"
            f"\n\n题目类型: {tag}\n题目: {problem}\n\n表达式:"
        )
        try:
            # v2.4.1：prefill「表达式：」抑制 CoT——快车道只需表达式，秒级返回
            from utils.prefill import prefill_messages, stitch
            raw_expr = _normalize_chat_response(self.client.chat(
                messages=prefill_messages(
                    [
                        {"role": "system", "content": "你只输出数学表达式，不要任何解释。"},
                        {"role": "user", "content": extract_prompt},
                    ],
                    "表达式：",
                ),
                temperature=0.0,
                max_tokens=32768,
            ))
            if raw_expr:
                raw_expr = stitch("表达式：", raw_expr)
            raw_expr = (raw_expr or "").strip()
        except Exception:
            return None
        if not raw_expr or len(raw_expr) > 500:
            return None
        try:
            if tag in ("arithmetic", "quadratic"):
                return eval_expression(raw_expr)
            elif tag == "derivative":
                return compute_derivative(raw_expr)
            elif tag == "integral":
                return compute_integral(raw_expr)
            elif tag == "determinant":
                return compute_determinant(raw_expr)
            elif tag in ("equation",):
                return solve_equation(raw_expr)
            elif tag == "limit":
                return compute_limit(raw_expr)
        except Exception:
            pass
        return None

    def _review_bug_feedback(self, ctx: TaskContext, feedback: str) -> str:
        """Step 4：让模型复核验证器的缺陷反馈，可驳回误报（论文流水线）。

        论文（Huang & Yang 2025）：验证器产出的 bug report 不一定全对，
        模型复核后可驳回误报——避免好答案被错误反馈引导改坏。
        返回复核后的 feedback；复核失败/无实质缺陷时返回精简反馈。
        """
        if not feedback or len(feedback) < 10:
            return feedback
        if not getattr(self.config, 'enable_feedback_review', True):
            return feedback
        # 候选：用最佳候选的 reasoning 作复核依据
        cand_text = ""
        bc = getattr(ctx, '_best_cluster', None)
        if bc is not None and getattr(bc, 'rep_candidate', None) is not None:
            cand_text = str(getattr(bc.rep_candidate, 'reasoning', ''))[:900]
        if not cand_text and ctx.candidates:
            cand_text = str(getattr(ctx.candidates[0], 'reasoning', ''))[:900]
        user_msg = (
            f"【题目】\n{ctx.problem}\n\n"
            f"【当前解答（节选）】\n{cand_text}\n\n"
            f"【验证器给出的缺陷反馈】\n{feedback}\n\n"
            "请逐条复核上述缺陷反馈是否属实：\n"
            "- 属实（真实存在且影响正确性）→ 保留该条\n"
            "- 误报（与解答不符或判断错误）→ 驳回该条\n"
            "只输出复核后保留的缺陷清单，若全部误报则输出：无实质缺陷")
        raw = self.llm(ctx, [
            {"role": "system",
             "content": "你是严谨的数学复核员，只客观判断缺陷反馈是否属实。"},
            {"role": "user", "content": user_msg},
        ], temperature=0.0, max_tokens=32768)
        if not raw or not raw.strip():
            return feedback
        reviewed = raw.strip()
        self.record(ctx, "review",
                    f"反馈复核完成: {reviewed[:60]}")
        if "无实质缺陷" in reviewed:
            return "解答已较完整，请重新审题核对计算细节后给出最终答案。"
        return reviewed

    def _deep_revise_loop(self, ctx: TaskContext, ver_result: dict,
                          tier_votes: int, force: bool = False) -> bool:
        """deep 档 0 正确票时的 revise 自纠错回环。

        用验证器反馈驱动定向修正：最多 deep_revise_rounds 轮，
        每轮 solver 走 _generate_revise 重解 + verifier 重新验证。
        返回是否在回环中获得至少 1 个候选获得正确票。
        """
        max_rounds = getattr(self.config, 'deep_revise_rounds', 1)
        if max_rounds <= 0 or ctx.state.emergency:
            return False
        # 2026-09-02 老师需求：revise 全局轮数上限 5（revise_round 跨主路径累计）
        if getattr(ctx, 'revise_round', 0) >= 5:
            self.record(ctx, "revise", "revise 已达全局上限 5 轮，不再继续")
            return False
        if force:
            # P1 应急重解：构造**结构化错误诊断报告**（2026-09-11 用户指正：
            # "不能光检测错误，要把错误情况总结后返回给大模型，否则等于没检查"）。
            # 实测依据（v10 的 002/004/022）：原反馈是「所有候选均未获验证通过，请重新
            # 审题…」这类无信息量默认句 + 验证代码细节 → 重解等于重来一遍，正确率无变化。
            # 这里改为逐条定性 + 可操作指引：① 当前答案是什么（要推翻什么）
            # ② 数值攻击的「声称值 vs 采样反例」矛盾 ③ Lean/AuditGate 的具体缺陷。
            _parts = ["【本次重解必须修正以下已检测到的具体问题（逐条回应，勿泛泛重来）】"]
            try:
                _cands0 = list(ctx.candidates or [])
                _cur_ans = str(getattr(_cands0[0], "answer", "") or "")[:300] if _cands0 else ""
            except Exception:  # noqa: BLE001
                _cur_ans = ""
            if _cur_ans:
                _parts.append(f"① 当前答案（已验证不通过，需重新推导）：{_cur_ans}")
            _bvf = str(getattr(ctx, "blueprint_value_false", "") or "")
            if _bvf:
                _parts.append(
                    f"② 数值攻击证伪：{_bvf[:280]}\n"
                    "    → 含义：原推导中该**极值/边界结论与数值采样矛盾**。"
                    "请重新独立推导该量的真实取值，不要沿用原结论；"
                    "若判定为浮点噪声（差异 < 1e-6），须说明理由方可保留。")
            _audit_fb = list(getattr(ctx, "audit_reject_feedback", None) or [])
            if _audit_fb:
                # 2026-09-12：单项截断 280 → 500。理由同 lean_gate：desc 末尾现在
                # 带「修法提示」，280 会把可操作部分切掉。条数仍限 3，避免 prompt 膨胀。
                _parts.append("③ 验证/审核环节给出的具体缺陷：\n"
                              + "\n".join(f"    - {str(x)[:500]}" for x in _audit_fb[:3]))
            # B2（2026-09-11）：从既有 Lean 反馈里提取【当前待证目标】(⊢ ...) 注入。
            # 依据：P1 虽已能触发重解，但反馈里缺"还差什么" → 模型只能盲目重算。
            # 目标状态是 Lean 独有信息（bridge/mcp 输出中的 `⊢` 行），定向价值最高。
            _goals: list = []
            for _x in _audit_fb:
                for _ln in str(_x).splitlines():
                    _s = _ln.strip()
                    if "⊢" in _s and _s not in _goals:
                        _goals.append(_s[:200])
            if _goals:
                _parts.append(
                    "④ Lean 给出的**当前待证目标**（据此定向修正，勿另起炉灶）：\n"
                    + "\n".join(f"    {g}" for g in _goals[:3]))
            # 2026-09-12 新增（用户要求）：把 **Lean 编译器发现的逻辑缺陷**单独成条，
            # 与 ③ 的混合反馈区分开 —— 让模型明确知道"哪些是明显逻辑错误"，
            # 从而优先、定向地修正该处，而不是笼统重算一遍。
            _lean_fb_sep = list(getattr(ctx, "lean_reject_feedback", None) or [])
            if _lean_fb_sep:
                _parts.append(
                    "⑤ **Lean 编译器发现的逻辑缺陷**（属明显错误，必须优先修正；"
                    "来自形式化验证，非数值误差）：\n"
                    + "\n".join(f"    - {str(x)[:500]}" for x in _lean_fb_sep[:3]))
            _parts.append(
                "【要求】逐条回应 ②③⑤：指出原推理中出错的具体步骤、重新推导，"
                "并给出与新证据一致的最终答案（置于 \\boxed{} 内）；"
                "若某条证据判定为误报，必须明确说明理由。")
            feedback = "\n".join(_parts)
        else:
            feedback = ver_result.get("feedback", "")
            if not feedback:
                feedback = "所有候选均未获验证通过，请重新审题并纠正推理错误。"
        # Step 4：复核验证器反馈（可驳回误报），避免被错误反馈误导修正。
        # 仅当反馈非空且预算允许时做（deep 档 +1 次调用，回环前只做一次）。
        if (not ctx.is_time_critical()
                and len(feedback) > 10):
            feedback = self._review_bug_feedback(ctx, feedback)
        # 注入各客观审核环节（3.6 AuditGate / 4.6 对抗 / 4.5 Oracle）淘汰反馈，
        # 驱动定向修正（audit_reject_feedback 为通用 revise 反馈通道）
        audit_fb = getattr(ctx, "audit_reject_feedback", None)
        if audit_fb:
            feedback = feedback + "\n" + "\n".join(audit_fb)
        for r in range(max_rounds):
            # 2026-09-06：升级 gen_time_up——revise 回环 = solver.run 生成 +
            # verifier 验证，单轮可烧 200-400s，须按生成侧软截止更早收手。
            # 2026-09-11：force=True 跳过该软截止 —— P1 硬信号"应急重解"专用。
            #   根因（10 题实测 002）：P1 外部条件（剩余 >150s）通过并调用了本函数，
            #   但此处 `gen_time_up()` 依据生成侧软截止（deadline − verify_reserve = 720s）
            #   在累计 814s 时必为 True → **第一轮就 break**，重解从未真正发生。
            #   应急重解只受硬墙约束，由调用方（P1）保证剩余时间充足。
            if ctx.gen_time_up() and not force:
                self.record(ctx, "revise", "revise 回环预算不足，提前终止")
                break
            ctx.revise_round += 1
            _ans_before = str(getattr(ctx, "final_answer", "") or "")
            ctx.revise_feedback = [feedback]
            self.record(ctx, "revise",
                        f"deep 档 revise 自纠错 第{ctx.revise_round}轮",
                        round=ctx.revise_round)
            self.solver.run(ctx)  # 走 _generate_revise 路径
            # 2026-09-13（用户原则："无用功要保证检测并截断，但要保证原有环节功能
            # 不受影响"）：**轮间无进展即停**。
            # 依据：本轮"生成 + 验证"实测量级 200-400s；若生成后答案与上轮**完全
            # 相同**，说明这一轮没有产出任何新东西，继续下一轮只是重复同一次空转
            # （实测 010：P1 强制重解跑满 2 轮，答案始终 `\boxed{0}`，白花 366s，
            #   最终成效埋点仍记"答案未变化"）。
            # 保守性：**只在答案完全未变时停**，且**第 1 轮永远保留**（有可能一次
            # 改对）；答案一旦变化即视为有进展，继续跑满剩余轮数 —— 原有功能不变。
            _ans_after = str(getattr(ctx, "final_answer", "") or "")
            if (_ans_before and _ans_after and _ans_before == _ans_after
                    and ctx.revise_round >= 1):
                self.record(
                    ctx, "revise",
                    f"revise 第{ctx.revise_round}轮无进展（答案未变 "
                    f"{_ans_before[:20]}）→ 提前终止，不再空转")
                break
            ver2 = self.verifier.run(
                ctx, problem=ctx.problem, candidates=ctx.candidates,
                use_clustering=True,
                use_scoring=self.config.use_scoring,
                is_proof=(getattr(ctx, 'question_type', '') == '证明题' or getattr(ctx, 'domain', '') in ('证明', '证明题')),
                use_playoff=ctx.state.playoff_enabled,
                use_deterministic=getattr(self.config, 'enable_deterministic', True),
                use_rubric=getattr(self.config, 'use_rubric', False),
                use_challenge=getattr(self.config, 'use_challenge', False),
                voting_times=tier_votes,
            )
            ctx.verdicts = self._verdicts_from_ver_result(ver2, ctx.candidates)
            ctx._best_cluster = ver2.get("best_cluster")
            ctx._cluster_data = ver2.get("cluster_data", [])
            # v2.8 AcceptGate：按本轮结果更新门控，连续重大缺陷达阈值 → 提前放弃
            decision = self._update_accept_gate(
                ctx, is_proof=(getattr(ctx, 'question_type', '') == '证明题' or getattr(ctx, 'domain', '') in ('证明', '证明题')))
            # 2026-09-02 老师需求：≥4 个候选获得正确票才算通过（防 1 票假阳性误收）
            n_pass = sum(1 for v in ctx.verdicts
                         if getattr(v, 'correct_votes', 0) > 0)
            if n_pass >= 4:
                self.record(ctx, "revise",
                            f"revise 第{ctx.revise_round}轮 {n_pass} 个候选通过（≥4）")
                return True
            if decision == "REJECT":
                self.record(ctx, "revise", "AcceptGate 连续重大缺陷达阈值，放弃 revise")
                return False
            feedback = ver2.get("feedback") or feedback
        self.record(ctx, "revise", f"revise 回环 {max_rounds} 轮仍未获得正确票")
        return False

    def _update_accept_gate(self, ctx: TaskContext, is_proof: bool = False) -> str:
        """按本轮验证结果更新 AcceptGate（RoundState），返回最新 decision。

        - is_pass：best_cluster 置信度 >= accept_confidence；
        - has_major_defect：证明题全部 0 正确票，或常规题置信度 < 0.3。
        """
        accept_conf = getattr(self.config, 'accept_confidence', 0.6)
        bc = getattr(ctx, '_best_cluster', None)
        conf = bc.confidence if bc is not None else 0.0
        is_pass = conf >= accept_conf
        has_major = False
        if is_proof:
            has_major = bool(ctx.verdicts) and all(v.correct_votes == 0 for v in ctx.verdicts)
        elif conf < 0.3:
            has_major = True
        decision = ctx.round_state.update(is_pass=is_pass, has_major_defect=has_major)
        self.record(
            ctx, "accept_gate",
            f"AcceptGate={decision} (pass={ctx.round_state.consecutive_pass}, "
            f"defect={ctx.round_state.consecutive_major_defect})",
            confidence=round(conf, 3),
        )
        return decision

    def _enhance_window_ok(self, ctx: TaskContext, tag: str) -> bool:
        """4.5 Oracle / 4.6 对抗：可弃验证增强的剩余时间窗口检查。

        单次复核 LLM 调用最坏 ~360s（LLMClient 180s 超时 ×2 次重试）且
        不可打断——放行会把 6.5 final_gate 的 verify_reserve 烧穿（冒烟 v2
        实证：oracle 365s / 对抗 372s → 6.5 仍 time_critical、compile_valid 0）。
        增强属可弃：要求剩余时间 ≥ est(默认360) + critical_tail + 30s 缓冲，
        否则跳过直进 6.5（宁少一层深查，不饿死最终闸门）。
        verify_enhance_est_seconds=0 关闭护栏（= 旧行为）。
        """
        est = float(getattr(self.config, "verify_enhance_est_seconds", 360.0))
        if est <= 0:
            return True
        rem = ctx.time_remaining()
        need = est + float(ctx.critical_tail_seconds) + 30.0
        ok = rem >= need
        if not ok:
            self.record(ctx, "control",
                        f"验证增强 {tag} 跳过：剩余 {rem:.0f}s < 需 {need:.0f}s"
                        f"（est {est:.0f} + critical {ctx.critical_tail_seconds:.0f}"
                        f" + 30），保 6.5 终局")
        return ok

    def _adversarial_probe(self, ctx: TaskContext, tier: str) -> bool:
        """对抗式验证（#16）：正向通过后主动证伪，抓正向漏检的错误。

        为什么只在"正向通过"后跑
        --------------------------
        - 正向**不过**的候选会直接进 revise / Step 4 复核是否误报，
          再证伪一次纯属浪费调用。
        - 正向**通过**的候选才是漏检风险区：验证器顺着作者思路走
          （确认偏误），错误没被审出来，这类答案会直接提交。

        返回 True 表示检出错误并已注入 revise 通道。
        任何异常都被吞掉返回 False——验证器的问题绝不能阻断主流程。
        """
        try:
            if not getattr(self.config, 'enable_adversarial_verify', True):
                return False
            bc = getattr(ctx, '_best_cluster', None)
            rep = getattr(bc, 'rep_candidate', None) if bc is not None else None
            if rep is None:
                rep = ctx.candidates[0] if ctx.candidates else None
            if rep is None:
                return False
            # 预算护栏：时间紧张时不跑，避免抢走写题时间（#43 归因）。
            # 2026-09-06：升级 gen_time_up——对抗审查是可弃增强，到生成侧
            # 软截止即弃，把 reserve 时间留给 4_verify 主投票与 6.5 最终闸门。
            if ctx.gen_time_up():
                self.record(ctx, "adversarial", "预算不足，跳过对抗式审查")
                return False
            if getattr(ctx.state, 'emergency', False) or ctx.gen_time_up():
                self.record(ctx, "adversarial", "时间紧张，跳过对抗式审查")
                return False
            # 2026-09-07 增强窗口护栏：剩余时间不足（est + critical_tail + 30）
            # 时跳过——对抗审查单次 LLM 最坏 ~360s 不可打断，放行会把 6.5
            # final_gate 的 verify_reserve 烧穿（冒烟 v2：4.6_adv=372s → 6.5
            # time_critical、compile_valid 0）。可弃增强，宁跳过保 6.5 终局。
            if not self._enhance_window_ok(ctx, "adversarial"):
                return False

            result = self.adv_verifier.probe(ctx, rep, tier=tier)
            if result.skipped:
                self.record(ctx, "adversarial", f"跳过：{result.skipped}")
                return False

            if not result.is_actionable:
                # 正向通过 + 尽力证伪仍无反例 → 高置信接受。
                # 这比"第二层再判一遍"更可信，也正是治误杀的关键：
                # 不再被一个单纯更严的第二层无脑否掉。
                self.record(ctx, "adversarial",
                            f"对抗式审查未找到错误（置信 {result.confidence:.2f}），"
                            f"高置信接受",
                            adv_found=False,
                            adv_confidence=result.confidence)
                ctx.adversarial_result = result
                return False

            # 检出错误 → 注入 revise 通道（audit_reject_feedback 通用反馈通道）
            if not getattr(ctx, 'audit_reject_feedback', None):
                ctx.audit_reject_feedback = []
            ctx.audit_reject_feedback.append(result.to_feedback())
            ctx.adversarial_result = result
            self.record(ctx, "adversarial",
                        f"对抗式审查检出「{result.error_type or '未知类型'}」，"
                        f"注入 revise（置信 {result.confidence:.2f}）",
                        adv_found=True,
                        adv_error_type=result.error_type,
                        adv_confidence=result.confidence)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[orchestrator] 对抗式审查异常（已忽略）: %s", str(exc)[:120])
            return False

    def _oracle_review_best(self, ctx: TaskContext, ver_result: dict,
                            tier_votes: int) -> None:
        """deep 档：对 best_cluster 代表候选做 AnswerOracle 客观复核。

        投票是"验证器与解题器同源"的自评，会一起错；这里用 AnswerOracle
        （SymPy 符号等价/可解析性）做独立客观验证。2026-09-06 去 Lean 化：
        证明题不再做 Lean 编译（平台无 Lean），verify() 对证明题直接返回
        unknown，客观把关由 AuditGate（6.5 rubric）与对抗式验证（4.6）承担。
        incorrect 时把客观反馈注入 revise 通道并触发一次定向修正。
        """
        try:
            from .answer_oracle import AnswerOracle
        except Exception:  # noqa: BLE001
            return
        bc = getattr(ctx, '_best_cluster', None)
        if bc is None or not ctx.candidates:
            return
        cids = getattr(bc, 'candidate_ids', []) or []
        idx = cids[0] if cids and cids[0] < len(ctx.candidates) else 0
        rep = ctx.candidates[idx]
        oracle = AnswerOracle(self.client, self.config, ctx.budget)
        try:
            result = oracle.verify(ctx, rep, candidates=ctx.candidates)
        except Exception as e:  # noqa: BLE001
            self.record(ctx, "oracle_review", f"AnswerOracle 复核异常: {e}")
            return
        self.record(ctx, "oracle_review",
                    f"AnswerOracle 客观复核: {result.verdict} ({result.oracle_type})",
                    verdict=result.verdict, oracle_type=result.oracle_type)
        if (result.is_incorrect and result.feedback
                and not ctx.state.emergency):
            # 客观反馈注入 revise 通道（audit_reject_feedback 通用反馈通道）
            if not getattr(ctx, 'audit_reject_feedback', None):
                ctx.audit_reject_feedback = []
            ctx.audit_reject_feedback.append(result.feedback)
            self.record(ctx, "oracle_review",
                        f"客观复核判错，触发定向修正: {result.feedback[:120]}")
            self._deep_revise_loop(ctx, ver_result, tier_votes)

    def _verdicts_from_ver_result(self, ver_result: dict, candidates: list = None) -> list:
        """将验证器产出的多票结果汇总为 Verdict 数据类列表。

        每个候选可能有多张票（Verdict），此处聚合成一个汇总 Verdict：
        - confidence = 正确票 / 总票数
        - answer 取自候选（便于 Formatter 兜底直接使用）
        - feedback 取第一张有效票的反馈，score 取第一张非空票的评分
        """
        all_verdicts = ver_result.get("verdicts", [])
        result = []
        for idx, vds in enumerate(all_verdicts):
            # 2026-09-11 三态化：弃权票（LLM 调用失败 / 输出无法解析，属基础设施
            # 或格式故障）剔出分母——故障不是反证。此前 `len(vds)` 把 36 张故障票
            # 当"错票"计入（票池 ~120 → ~30% 错票）→ 置信度虚低 → 无谓 revise。
            effective = [v for v in vds if not getattr(v, "abstain", False)]
            correct_votes = sum(1 for v in effective if v.correct)
            total_votes = len(effective)
            candidate = candidates[idx] if candidates and idx < len(candidates) else None
            answer = candidate.answer if candidate else ""
            feedback = next((v.feedback for v in vds if v.feedback), "")
            score = next((v.score for v in vds if v.score is not None), None)
            result.append(Verdict(
                id=idx,
                answer=answer,
                confidence=correct_votes / total_votes if total_votes else 0.0,
                correct_votes=correct_votes,
                total_votes=total_votes,
                feedback=feedback,
                score=score,
            ))
        return result

    def _has_usable_candidate(self, ctx: TaskContext) -> bool:
        """候选池里是否存在**可用**答案（2026-09-13 晚新增）。

        为什么不能只用 `if not ctx.candidates`：solver 原先在候选生成失败时会
        append 一个 reasoning=`[生成失败] 调用受限或模型拒绝回答` 的占位候选，
        于是池子"非空但不可用"，orchestrator 的兜底直接求解被永久绕开
        （4 题实测 010/016 的 `predicted` 就是这个占位符）。

        判据：候选必须有非空 answer 且不是拒绝/占位符；answer 为空时按 formatter
        的语义接受"reasoning 可作答案"的候选（formatter 会取 reasoning 尾部），
        避免把本可挽救的候选判死。
        """
        for c in (getattr(ctx, "candidates", None) or []):
            ans = (getattr(c, "answer", "") or "").strip()
            rea = (getattr(c, "reasoning", "") or "").strip()
            # ⚠ 用模块级常量：写成 `self._DEGRADED_ANSWER_RE` 不会回退到模块全局
            # （Python 的 self 查找只到实例/类/基类，不回落到模块命名空间）。
            if ans and not _DEGRADED_ANSWER_RE.search(ans):
                return True
            if (not ans) and rea and not _DEGRADED_ANSWER_RE.search(rea):
                return True
        return False

    def _pick_best_from_candidates(self, ctx: TaskContext) -> str:
        import re as _re
        # 2026-09-13 P0 诊断埋点：记录"候选答案分布 + verdict 明细 + 命中分支"，
        # 用于确证 102 题（候选 4/6 正确却输出错答案）的根因。
        # 纯记录、不改选取行为；写入 ctx._pick_diag 供 _collect_diag 落盘。
        try:
            _pd: dict = {"cand_answers": [], "verdicts": [], "branch": ""}
            for _c in getattr(ctx, "candidates", None) or []:
                _a = getattr(_c, "answer", "") or ""
                _pd["cand_answers"].append(_a[:40])
            for _v in getattr(ctx, "verdicts", None) or []:
                _pd["verdicts"].append({
                    "answer": (getattr(_v, "answer", "") or "")[:40],
                    "conf": round(float(getattr(_v, "confidence", 0.0) or 0.0), 3),
                    "cvotes": getattr(_v, "correct_votes", 0),
                    "tvotes": getattr(_v, "total_votes", 0),
                    "abstain": bool(getattr(_v, "abstain", False)),
                })
            ctx._pick_diag = _pd
        except Exception:  # noqa: BLE001
            ctx._pick_diag = {"error": "pick_diag_failed"}
        # 1) 从 verdicts 找有非拒绝答案的
        if ctx.verdicts:
            sorted_v = sorted(ctx.verdicts, key=lambda v: v.confidence, reverse=True)
            for v in sorted_v:
                ans = getattr(v, "answer", "") or ""
                if ans and len(ans) > 3 and not _re.search(r"无法求解|无法解决|不能解决", ans):
                    if isinstance(getattr(ctx, "_pick_diag", None), dict):
                        ctx._pick_diag["branch"] = "verdict_confidence"
                        ctx._pick_diag["picked"] = ans[:40]
                    return ans
        # 2026-09-13 P1：选择题答案多数投票（用户确认"针对选择题尝试"）
        # 触发条件：① 环境变量 OBJECTIVE_MAJORITY_VOTE=1 ② 题面=选择题
        # ③ verdicts 路径未命中（即没人能给出高 confidence 的裁决）
        # 行为：对归一化后的候选答案做频次统计，取最高频。
        # 设计依据：self-consistency（Wang 2022），对"答案形态稳定"
        # （A–E 字母组合）的客观题有理论支撑。
        if (os.environ.get("OBJECTIVE_MAJORITY_VOTE", "0") == "1"
                and getattr(ctx, "question_type", "") == "选择题"):
            _mv_count: dict = {}
            for _c in getattr(ctx, "candidates", None) or []:
                _a = (getattr(_c, "answer", "") or "").strip()
                if _a and len(_a) > 3 and not _re.search(
                        r"无法求解|无法解决|不能解决", _a):
                    _mv_count[_a] = _mv_count.get(_a, 0) + 1
            if _mv_count:
                _top_ans, _top_n = max(
                    _mv_count.items(), key=lambda kv: kv[1])
                if isinstance(getattr(ctx, "_pick_diag", None), dict):
                    ctx._pick_diag["branch"] = "majority_vote_objective"
                    ctx._pick_diag["picked"] = _top_ans[:40]
                    ctx._pick_diag["majority_dist"] = {
                        k[:40]: v for k, v in _mv_count.items()}
                    ctx._pick_diag["majority_top_n"] = _top_n
                return _top_ans
        # 2) 从 candidates 找有非拒绝答案的
        if ctx.candidates:
            sorted_c = sorted(ctx.candidates, key=lambda c: len(c.reasoning or ""), reverse=True)
            for c in sorted_c:
                if c.answer and len(c.answer) > 3 and not _re.search(r"无法求解|无法解决|不能解决", c.answer):
                    if isinstance(getattr(ctx, "_pick_diag", None), dict):
                        ctx._pick_diag["branch"] = "candidate_longest_reasoning"
                        ctx._pick_diag["picked"] = c.answer[:40]
                    return c.answer
        # 3) 最后防线：取最详细推理的尾部
        if ctx.candidates:
            best = max(ctx.candidates, key=lambda c: len(c.reasoning or ""))
            if best.reasoning and len(best.reasoning) > 50:
                if isinstance(getattr(ctx, "_pick_diag", None), dict):
                    ctx._pick_diag["branch"] = "reasoning_tail"
                return best.reasoning.strip()[-500:]
        if isinstance(getattr(ctx, "_pick_diag", None), dict):
            ctx._pick_diag["branch"] = "empty"
        return ""

    _DIRECT_SYS = (
        "你是数学解题专家。请解答下面这道题。"
        "最后一行必须以【最终答案】: <答案> 的格式给出最终答案，"
        "答案只写数值、表达式或选项字母，不要写任何解释或推理。"
    )

    def _collect_diag(self, ctx: TaskContext) -> dict:
        """逐步归因诊断（2026-09-02 用户要求：错题要能定位到环节）。

        打包各阶段中间状态：理解→蓝图→骨架评审→子目标→Lean→验证→预算。
        全部 getattr + 默认值兜底：任意提前 return / 异常路径下调用都安全
        （TaskContext 各字段均有默认值，直接访问也不会崩）。
        由 run_eval.solve_one 落盘为结果行 diag 字段；tools/analyze_errors.py 消费。
        """
        _md = getattr(ctx, "metadata", None)
        _md = _md if isinstance(_md, dict) else {}
        # ⑤''' Lean 链路自证（2026-09-10 审核教训：结果文件没有 lean_active /
        #     lean_executable 就绝不能声称 Lean 跑过 —— 闸门身份会被静默降级
        #     顶换成 audit_gate 而输出看起来完全正常）。只读已算好的 _lean_probe，
        #     不在此触发新的环境探测。
        _lean_on, _lean_exe = False, ""
        try:
            _lean_on = bool(getattr(self, "_lean_probe", None))
            if self.lean_gate is not None:
                _b = self.lean_gate._bridge_inst
                if _b is not None:
                    _lean_exe = str(_b._lean_executable or "")
        except Exception:  # noqa: BLE001
            pass
        return {
            # ① 题型与档位
            "question_type": getattr(ctx, "question_type", "") or "",
            "domain": getattr(ctx, "domain", "") or "",
            "tier": getattr(ctx, "tier", "") or "",
            "tier_evidence": getattr(ctx, "tier_evidence", None) or {},
            "soft_budget": round(float(getattr(ctx, "soft_budget", 0) or 0), 1),
            # ② 题目理解（原 Lean 前置 preverify 已去 Lean 化移除；以下为遗留字段恒空，
            #    保留供旧日志/工具兼容）
            "formal_spec": (getattr(ctx, "formal_spec", "") or "")[:600],
            "formal_gaps": list(getattr(ctx, "formal_gaps", None) or [])[:10],
            "preverify_trace": getattr(ctx, "preverify_trace", None) or {},
            # ③ 蓝图 DAG + 骨架评审 + DAG 评审
            "blueprint_nodes": len((getattr(ctx, "blueprint", None) or {}).get("nodes", []) or []),
            "blueprint_merge": (getattr(ctx, "blueprint", None) or {}).get("merge_strategy", ""),
            "skeleton_review": getattr(ctx, "skeleton_review_report", None) or None,
            "dag_review": getattr(ctx, "dag_review_report", None) or {},
            "sketch_audit": getattr(ctx, "sketch_audit", None) or {},
            # ③' 骨架评审事件流 + 求解前 DAG 强制门事件流（2026-09-08 补：
            #    两机制 record 只进 ctx.trace 且 trace 不落盘 → 冒烟 10 题事后
            #    查不到门是否触发/重规划几轮。现从 trace 提取进 diag，同
            #    value_attack 模式。skeleton_review/dag_review 是最终态报告，
            #    这里是逐轮事件（通过/重规划/放行/预算耗尽），互为补充。）
            "skeleton_review_events": [str(t.get("content", ""))[:200]
                                       for t in (getattr(ctx, "trace", None) or [])
                                       if isinstance(t, dict)
                                       and t.get("step") == "skeleton_review"],
            "dag_replan_events": [str(t.get("content", ""))[:200]
                                  for t in (getattr(ctx, "trace", None) or [])
                                  if isinstance(t, dict)
                                  and t.get("step") == "dag_replan"],
            # ★ 本轮优化埋点（2026-09-11，用户要求"一次评测即可逐项审查"）
            #   P2 数值化 / P5 客观题自检 / P4 阶段预算（control 中的预算记录）
            "numericize_events": [str(t.get("content", ""))[:200]
                                  for t in (getattr(ctx, "trace", None) or [])
                                  if isinstance(t, dict)
                                  and t.get("step") == "numericize"],
            "objective_check_events": [str(t.get("content", ""))[:200]
                                       for t in (getattr(ctx, "trace", None) or [])
                                       if isinstance(t, dict)
                                       and t.get("step") == "objective_check"],
            "phase_budget_events": [str(t.get("content", ""))[:200]
                                    for t in (getattr(ctx, "trace", None) or [])
                                    if isinstance(t, dict)
                                    and t.get("step") == "control"
                                    and "阶段预算" in str(t.get("content", ""))],
            # 数值攻击证伪信号（此前未导出，导致 v1–v3 诊断时误判"无信号"）
            "blueprint_value_false": (str(getattr(ctx, "blueprint_value_false", "") or "")[:200]),
            # P1 未触发原因（2026-09-12 补：只导出 revise 事件时，"0 触发"在日志里
            # 表现为"什么都没记"，无法区分「没信号」与「有时间但被档位/emergency
            # /门槛拦」。此处单独导出，与 revise_events 并列、互不污染口径。
            "p1_check_events": [str(t.get("content", ""))[:220]
                                for t in (getattr(ctx, "trace", None) or [])
                                if isinstance(t, dict)
                                and t.get("step") == "p1_check"],
            # ★ 2026-09-12 补导出：符号化求解 / 独立符号复核 / 答案工具自检 的埋点。
            # 此前这些只写进 ctx.trace，而 diag 导出按固定字段挑 → jsonl 里看不到，
            # 导致"机制到底跑没跑"无法从结果文件判定（只能靠日志旁证）。
            "symbolic_solve_events": [str(t.get("content", ""))[:220]
                                      for t in (getattr(ctx, "trace", None) or [])
                                      if isinstance(t, dict)
                                      and str(t.get("step", "")).startswith(
                                          "symbolic_solve")],
            "symbolic_crosscheck_events": [str(t.get("content", ""))[:220]
                                           for t in (getattr(ctx, "trace", None) or [])
                                           if isinstance(t, dict)
                                           and str(t.get("step", "")).startswith(
                                               "symbolic_crosscheck")],
            "answer_selfcheck_events": [str(t.get("content", ""))[:220]
                                        for t in (getattr(ctx, "trace", None) or [])
                                        if isinstance(t, dict)
                                        and str(t.get("step", "")).startswith(
                                            "answer_selfcheck")],
            # ★ 表达式范式（9/12）：模型只建模、本地代入求值 → 答案取工具值。
            # 不加这行则 jsonl 里看不到"默认生成方程"是否真的被触发。
            "expression_eval_events": [str(t.get("content", ""))[:220]
                                       for t in (getattr(ctx, "trace", None) or [])
                                       if isinstance(t, dict)
                                       and str(t.get("step", "")).startswith(
                                           "expression_eval")],
            # 2026-09-12 补导出：一批「record 了但 diag 看不到」的事件统一补齐。
            # 本项目多次出现"埋点写了、jsonl 里找不到" ⇒ A/B 归因失效；本次新加的
            # 几处又踩了同一个坑（run_eval 只落盘 diag，trace 被丢弃），故一次补齐。
            **{f"{_k}_events": [str(t.get("content", ""))[:220]
                                for t in (getattr(ctx, "trace", None) or [])
                                if isinstance(t, dict) and t.get("step") == _k]
               for _k in ("final_postprocess_change", "subgoal_recover",
                          "subgoal_replan_needed", "lean_feedback_revise",
                          "calc_easy_pass",
                          # 2026-09-13 晚补：方案 B（生成前预计算 `2.65_calc_prewarm`）
                          # 在 `solver.prewarm_calcs()` 里写了 7 处 record，但**不在本
                          # 白名单** ⇒ 埋点全被丢弃（trace 不落盘、run_eval 只存 diag），
                          # 4 题实测跑完连"预计算产出几条算式"都查不到 —— 正是本注释
                          # 上一段吐槽过的同一个坑。补上即可见。
                          "calc_prewarm")},
            # revise 事件（含"P1 硬信号触发强制重解"/自纠错轮次/预算不足终止）
            # ——2026-09-11 补：此前仅 revise_round 可观测，看不到触发原因
            "revise_events": [str(t.get("content", ""))[:200]
                              for t in (getattr(ctx, "trace", None) or [])
                              if isinstance(t, dict) and t.get("step") == "revise"],
            # 2026-09-13 补导出（**今天多次被"看不到"卡住后的根治**）：
            # `control` 事件是"阶段为何跳过/触发"的唯一记录（如 3.3 自改进的
            # "跳过（剩余 X < 门槛）"），`verdicts` 是 4_verify 投票明细、
            # `audit_gate` 是客观审核明细 —— 三者此前都不在导出白名单里，
            # 导致归因时只能靠猜（本轮即因 `control_events` 缺失，无法判定
            # 004 的 3.3 为何从 363s 变成 0s）。
            "control_events": [str(t.get("content", ""))[:200]
                               for t in (getattr(ctx, "trace", None) or [])
                               if isinstance(t, dict) and t.get("step") == "control"],
            "verdicts": [
                {"correct_votes": getattr(v, "correct_votes", None),
                 "total_votes": getattr(v, "total_votes", None),
                 "correct": getattr(v, "correct", None),
                 "confidence": getattr(v, "confidence", None)}
                for v in (getattr(ctx, "verdicts", None) or [])],
            "audit_gate": [g for g in (getattr(ctx, "audit_gate", None) or [])
                           if isinstance(g, dict)][:6],
            # ④ 子目标求解（结构化轨迹）
            "subgoal_trace": getattr(ctx, "subgoal_trace", None) or [],
            "subgoal_merge_plan": (getattr(ctx, "subgoal_merge_plan", "") or "")[:300],
            # ④'' S4-lite 独立性指标（老师 9/6：子目标数/依赖边/平均入度/上下文注入量）
            "subgoal_stats": getattr(ctx, "subgoal_stats", None) or {},
            "subgoal_ctx_inject_chars": int(
                getattr(ctx, "subgoal_ctx_inject_chars", 0) or 0),
            "lemma_repo": list(getattr(ctx, "lemma_repo", None) or [])[:20],
            # ④' C-lite 数值攻击（2026-09-03 审核补：原本只 record 进 trace，
            # 而 trace 不落盘 → v17 事后完全查不到是否执行。现在进 diag。）
            "value_attack": [str(t.get("content", ""))[:200]
                             for t in (getattr(ctx, "trace", None) or [])
                             if isinstance(t, dict)
                             and t.get("step") == "value_attack"],
            # ⑦'' calc 工具审计（2026-09-09 P1-2：<calc> 求值 WARN/ERROR = 工具
            # 失败/模型自算降级点，自算率 = 该事件数 / 计算点数，A/B 核心指标）
            "calc_fallback": [{"expr": str(t.get("expr", ""))[:100],
                               "reason": str(t.get("reason", ""))[:100]}
                              for t in (getattr(ctx, "trace", None) or [])
                              if isinstance(t, dict)
                              and t.get("step") == "calc_fallback"][:20],
            # ⑦''' calc 强制打回审计（2026-09-09 P1-1：心算打回是否真触发——
            # solver 主链定向重问 / 子目标 L0C 重解 / 二次裸算标注，全部可观测）
            "calc_rewrite": [str(t.get("content", ""))[:120]
                             for t in (getattr(ctx, "trace", None) or [])
                             if isinstance(t, dict)
                             and t.get("step") == "solver_calc_rewrite"][:20],
            "calc_tool_mode": [str(t.get("content", ""))[:120]
                            for t in (getattr(ctx, "trace", None) or [])
                            if isinstance(t, dict)
                            and t.get("step") == "calc_tool_mode"][:20],
            "calc_tool_calls": [str(t.get("content", ""))[:120]
                              for t in (getattr(ctx, "trace", None) or [])
                              if isinstance(t, dict)
                              and t.get("step") == "calc_tool_call"][:20],
            "subgoal_l0c": [str(t.get("content", ""))[:120]
                            for t in (getattr(ctx, "trace", None) or [])
                            if isinstance(t, dict)
                            and t.get("step") == "subgoal_l0c"][:20],
            "subgoal_naked_twice": sum(
                1 for t in (getattr(ctx, "trace", None) or [])
                if isinstance(t, dict) and t.get("step") == "subgoal_step"
                and "二次裸算" in str(t.get("content", ""))),
            # ⑤ 检测链 AuditGate（2026-09-06 去 Lean 化顶替 lean_gate；
            #    Level0-3 多级瀑布记录：候选过滤 / 最终答案门禁 / 理解确认；
            #    2026-09-06 晚 Lean 双通道恢复后，lean 不可用时的兜底记录）
            "audit_gate": [e for e in (getattr(ctx, "audit_gate", None) or [])][:60],
            # ⑤' Lean 双通道记录（2026-09-06 晚恢复：lean 环境可用时
            #     LeanGate/LeanPreVerifier 的候选过滤与最终闸门写这里，材料证据链）
            "lean_gate": [e for e in (getattr(ctx, "lean_gate", None) or [])][:60],
            # ⑤'' Lean 按题适用性（2026-09-10）：False = 本题答案非数学对象
            #     （选项字母/判断值/概念文字）→ 整题豁免 Lean、改路由 AuditGate。
            #     字段缺失（旧结果）视为 True，与 _lean_applicable 缺省口径一致。
            "lean_applicable": bool(_md.get("lean_applicable", True)),
            "lean_skip_reason": str(_md.get("lean_skip_reason", "") or ""),
            # ⑤''' Lean 链路自证：lean_active=True 且 lean_executable 非空，
            #      才可声称本题走过 Lean 通道（闸门身份 = diag.lean_gate 非空）。
            "lean_active": _lean_on,
            "lean_executable": _lean_exe,
            # ⑥ 候选/验证/自纠错
            "n_candidates": len(getattr(ctx, "candidates", None) or []),
            "n_verdicts": len(getattr(ctx, "verdicts", None) or []),
            "revise_round": getattr(ctx, "revise_round", 0),
            "revise_feedback": list(getattr(ctx, "revise_feedback", None) or [])[:20],
            # 2026-09-13 P0：答案选取埋点（候选分布 + verdict 明细 + 命中分支）
            "pick_diag": getattr(ctx, "_pick_diag", None) or {},
            # B0：答案形态闸门事件（从 trace 中挑出，条数少，便于事后判定触发情况）
            "answer_form_events": [
                str(t.get("content")) for t in (getattr(ctx, "trace", None) or [])
                if isinstance(t, dict) and t.get("step") == "answer_form"
            ][:10],
            # 穷尽性搜索机制：是否追加了「解族穷尽性检查」子目标
            "exhaust_diag": getattr(ctx, "_exhaust_diag", None) or {},
            # ⑦ 预算健康（trace 中 budget_skip / degraded / 占位符计数）
            "budget_skips": sum(1 for t in (getattr(ctx, "trace", None) or [])
                                if isinstance(t, dict) and t.get("step") == "budget_skip"),
            "degraded_flags": sum(1 for t in (getattr(ctx, "trace", None) or [])
                                  if isinstance(t, dict)
                                  and ("degrad" in str(t.get("step", "")).lower()
                                       or "degrad" in str(t.get("content", "")).lower())),
            "placeholder": "[子目标求解失败]" in (getattr(ctx, "final_response", "") or ""),
            # 2026-09-02 老师需求：答案截断可观测（003 题 g(x)=-2x^{ 截断被识别）
            "answer_complete": not _is_truncated_answer(
                getattr(ctx, "final_response", "") or ""),
            # 阶段耗时（2026-09-03 老师要看 deep 档每环节具体耗时）
            "stage_timers": self._collect_stage_durs(ctx),
        }

    def _emergency_direct_solve(self, problem: str) -> str:
        """紧急直答：用最精简 prompt 逼模型输出答案，绝不返回原题。

        P0-4 修复：集成 prefill 答案前置——时间最紧时优先保答案，
        抑制 CoT 开启，即使截断也只损失思考、不损失答案（ICMA 验证 58-140× 加速）。
        """
        try:
            from utils.prefill import prefill_messages, stitch
            resp = self.client.chat(
                messages=prefill_messages(
                    [
                        {"role": "system", "content": self._DIRECT_SYS},
                        {"role": "user", "content": problem},
                    ],
                    "【最终答案】: ",
                ),
                temperature=0.0,
                max_tokens=_EMERGENCY_DIRECT_MAX_TOKENS,
            )
            text = _normalize_chat_response(resp)
            if text:
                text = stitch("【最终答案】: ", text)
            if not text or not text.strip():
                return ""
            # 优先提取【最终答案】行
            m = _re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
            if m:
                ans = m.group(1).strip().split("\n")[0].strip()
                if ans:
                    return ans
            # 兜底：最后一个非空行
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if lines:
                return lines[-1][:500]
            return text.strip()[:500]
        except Exception:
            return ""

    def _fallback_direct(self, ctx: TaskContext) -> dict:
        """Solver 无候选 → 直接 LLM 求解（紧急直答，绝不返回原题）"""
        answer = self._emergency_direct_solve(ctx.problem)
        if not answer:
            # 2026-09-02 二次尝试：换更强调语气重答（094 实测一次直答失败
            # 即返回"未给出有效解答"——多一次机会，成本仅 1 次调用）
            try:
                from utils.prefill import prefill_messages, stitch
                resp2 = self.client.chat(
                    messages=prefill_messages(
                        [
                            {"role": "system", "content": (
                                "直接输出本题最终答案。禁止拒绝、禁止解释。"
                                "若答案是数值给出数值，若需集合/表达式按标准数学格式。")},
                            {"role": "user", "content": ctx.problem},
                        ],
                        "【最终答案】: ",
                    ),
                    temperature=0.0, max_tokens=_EMERGENCY_DIRECT_MAX_TOKENS,
                )
                text = _normalize_chat_response(resp2)
                if text:
                    text = stitch("【最终答案】: ", text)
                    m = _re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
                    if m:
                        ans2 = m.group(1).strip().split("\n")[0].strip()
                        if ans2 and len(ans2) > 1:
                            answer = ans2
            except Exception:  # noqa: BLE001
                pass
        if not answer:
            answer = "未给出有效解答。"
            ctx.trace.append({"agent": self.name, "step": "fallback",
                              "content": "紧急直答失败，返回占位答案"})
        # P2/P5 后处理同样适用于兜底路径（提前返回，绕过统一出口）
        answer = self._final_answer_postprocess(ctx, answer)
        return safe_json_serialize({
            "final_response": answer, "trace": ctx.trace,
            "diag": self._collect_diag(ctx),
        })

    def _fallback(self, ctx: TaskContext, problem: str, exc: Exception) -> dict:
        trace = list(ctx.trace) if ctx.trace else []
        trace.append({
            "agent": self.name, "step": "error",
            "content": f"求解异常: {type(exc).__name__}: {exc}",
        })
        answer = self._pick_best_from_candidates(ctx)
        if answer:
            trace.append({"agent": self.name, "step": "fallback",
                          "content": "使用已有候选最佳答案作为兜底"})
            return {"final_response": answer, "trace": trace,
                    "diag": self._collect_diag(ctx)}
        # 紧急直答
        answer = self._emergency_direct_solve(problem)
        if not answer:
            answer = "未给出有效解答。"
            trace.append({"agent": self.name, "step": "fallback",
                          "content": "紧急直答失败，返回占位答案"})
        return {"final_response": answer, "trace": trace,
                "diag": self._collect_diag(ctx)}
