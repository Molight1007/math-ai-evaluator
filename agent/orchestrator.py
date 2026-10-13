from __future__ import annotations


# 2026-10-02 中间结果存储层（李平老师架构建议 #5，老师点名的「耦合过紧」根因）：
# 把题意理解 / 蓝图 / 子目标 / 候选 / verdict / Lean / 终答**多存一份**到
# results/<run_id>/<qid>/。只加不改：不删分支、不改判定、不动返回值；
# 每一处调用都**永不抛异常**（失败只落一条 trace，绝不阻断主链）。
try:
    from agent.artifact_store import (
        put_ctx as _artifact_put, append_ctx as _artifact_append,
        attach as _artifact_attach)
except ImportError:
    from artifact_store import (
        put_ctx as _artifact_put, append_ctx as _artifact_append,
        attach as _artifact_attach)
"""
编排器（Orchestrator）—— 简化版
================================

借鉴 ss-main 的简洁流水线，不做复杂回环，每道题 LLM 调用控制在 7 次以内：

    Classifier → Solver → Verifier → Formatter
    (1次LLM)   (3次并行)  (3次投票)  (无LLM)

弱化改动：
- 蓝图分解默认开启（`use_blueprint=True`；2026-10-01 研究期按用户决策默认开）
- 不设自纠错回环（直接用聚类选最优候选）
- 不设完整性审核链（省去 3+ 次 LLM 确认与续写）
- Symbol 快车道仍在（可确定性求解时短路）
"""

import logging
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


from .base import BaseAgent, TaskContext, Budget, Verdict, _normalize_chat_response
from .classifier import ClassifierAgent, _KNOWN_DOMAINS
from .solver import SolverAgent
from .sub_goal_solver import SubGoalSolverAgent
# ★ 2026-10-06：`_clip_review_prose` **直接 import 复用**（不复制正则）——
#   复核清单与 verifier 深复核原文需同一道清洗口径，两处各写一份必然分叉
#   （仓库既有教训）。verifier 不 import orchestrator ⇒ 无循环导入。
from .verifier import VerifierAgent, _clip_review_prose
# ★ 2026-10-07（问题总账 §2.6「择优逻辑口径分叉」）：终答兜底择优**复用** formatter
#   的统一排序键 `_rank_key`（票数→独立复现数→置信度→答案形态→答案更短），
#   以及配套的 `_attach_support`（把"独立复现数"挂到候选上）。**只读引用，不改
#   formatter.py**。formatter 不 import orchestrator ⇒ 无循环导入。
from .formatter import (
    FormatterAgent,
    _rank_key as _formatter_rank_key,
    _attach_support as _formatter_attach_support)
from .collaborative_solver import CollaborativeSolver
from .adversarial_verifier import AdversarialVerifier
from .audit_gate import AuditGate
from utils.extract import safe_json_serialize
# 2026-10-07 阶段C1：`collect_param_usage` 已随 _collect_diag 移到
# agent/diag_export.py；此处**原位 re-export** 以保契约（
# tests/test_param_usage_0921.py 断言 orchestrator 可导入该符号）。
from .param_usage import collect_param_usage  # noqa: F401
# 2026-10-07 阶段C1：diag 专用汇总函数抽到 agent/diag_metrics.py；此处 re-export，
# 既有 `from agent.orchestrator import _merge_error_types` 等调用点/测试零改动。
from .diag_metrics import (  # noqa: F401
    _merge_error_types, _sum_reject_votes, _compute_subgoal_gaps,
    _compute_lean_gaps, _switch_snapshot, _tool_gateway_summary,
    _parse_exhaust_result, _diag_completeness, _summarize_deep_review,
    _summarize_leansearch)
from .diag_export import collect_diag  # noqa: F401  （供 _collect_diag 委托）
# 2026-10-07 阶段C2：6.5_audit_gate 段已抽到 agent/orchestrator__final_gate.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__final_gate import final_answer_gate, format_stage  # noqa: F401
# 2026-10-07 阶段C3a：3.6_audit_filter 段已抽到 agent/orchestrator__audit_filter.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__audit_filter import audit_filter_candidates  # noqa: F401
from .answer_normalizer import normalize_stage  # noqa: F401
# 2026-10-07 阶段C3b：5.5_low_conf 段已抽到 agent/orchestrator__low_conf.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__low_conf import low_confidence_recheck  # noqa: F401
# 2026-10-07 阶段C3c：3.4_collab 段已抽到 agent/orchestrator__collab.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__collab import collaborative_deep_improve  # noqa: F401
# 2026-10-07 阶段C4a：2.7_subgoal_main 段已抽到 agent/orchestrator__solve.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__solve import subgoal_main_path  # noqa: F401
# 2026-10-07 阶段C4b：3.2_complete 段已抽到 agent/orchestrator__solve.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__solve import complete_truncated  # noqa: F401
# 2026-10-07 阶段C4c：3.3_improve 段已抽到 agent/orchestrator__solve.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__solve import self_improve_step  # noqa: F401
# 2026-10-08 阶段C4e：3_solve 段已抽到 agent/orchestrator__solve.py，
# 由 run 以「哨兵 + 解包」方式委托（阶段打点原位保留，契约不变）。
# ⚠ 非纯逐字搬：段体末尾新增哨兵 return，调用点由裸段改为解包透传。
from .orchestrator__solve import solve_stage, _SOLVE_CONTINUE  # noqa: F401
# 2026-10-07 阶段C4d：4.5_oracle 段已抽到 agent/orchestrator__verify.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__verify import oracle_review_stage  # noqa: F401
# 2026-10-07 阶段C5：4_verify 段已抽到 agent/orchestrator__verify.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__verify import verify_stage  # noqa: F401
# 2026-10-07 阶段C6：1.2_theorem_hint 段已抽到 agent/orchestrator__prep.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__prep import prep_tier_budget  # noqa: F401
from .orchestrator__prep import theorem_hint_stage  # noqa: F401
from .orchestrator__prep import type_understanding_stage  # noqa: F401
# 2026-10-07 阶段C6：2.6_pre_audit 段已抽到 agent/orchestrator__prep.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__prep import pre_audit_stage  # noqa: F401
# 2026-10-07 阶段C6：4.6_adv 段已抽到 agent/orchestrator__verify.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__verify import adversarial_stage  # noqa: F401
from . import orchestrator__oracle as _orch_oracle
from . import orchestrator__numeric as _orch_numeric
from . import orchestrator__select as _orch_select
from . import orchestrator__revise as _orch_revise
from . import orchestrator__fallback as _orch_fallback
from . import orchestrator__budget as _orch_budget
from . import orchestrator__lean as _orch_lean
# 2026-10-09 批16：orchestrator 的 7 个模块级工具函数已搬到
# agent/orchestrator__helpers.py（_sw_bool_or / _sw_num_or /
# _emergency_direct_max_tokens / _load_lean_modules / _answer_fingerprint /
# _merge_review_into_feedback / _collect_tool_findings）。此处**原位 re-export**，
# 既有 `from agent.orchestrator import <名>` 调用点（tests/test_feedback_review.py、
# orchestrator__revise/verify/final_gate/fallback 的惰性 import）零改动。
from .orchestrator__helpers import (  # noqa: F401
    _sw_bool_or, _sw_num_or, _emergency_direct_max_tokens,
    _load_lean_modules, _answer_fingerprint, _merge_review_into_feedback,
    _collect_tool_findings)
# 2026-10-07 阶段C6：5_revise_or_fallback 段已抽到 agent/orchestrator__low_conf.py，
# 由 run 一行委托调用（阶段打点原位保留，契约不变）。
from .orchestrator__low_conf import revise_or_fallback_stage  # noqa: F401

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
        # 2026-09-29：DifficultyRouter（难度路由）与 PaperPacer（全卷时间池）
        # 已按用户决策删除 —— 统一单一档位，不再有按难度/配额裁剪方法的机制。
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
        return _orch_lean._ensure_lean_modules(self)

    def _lean_active(self) -> bool:
        return _orch_lean._lean_active(self)

    def _lean_applicable(self, ctx) -> bool:
        return _orch_lean._lean_applicable(self, ctx)

    # ------------------------------------------------------------------
    # 领域 → 定理检索（2026-09-29 新增，截图 #3+#4）
    # ------------------------------------------------------------------
    def _retrieve_theorem_hints(self, ctx) -> None:
        return _orch_lean._retrieve_theorem_hints(self, ctx)

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

    @staticmethod
    def _reassign_stage_time(ctx, name: str, seconds: float) -> None:
        """把 `seconds` 从**当前正在计时**的阶段窗口里**搬**到阶段 `name`。

        ★ 2026-10-07（fix-gate-timing-diag 问题 2.8）：`_deep_revise_loop` 是**共享
        子过程**，被 4 个阶段调用（P1@4_verify :2051 / 4.6 对抗 :2210 / 5 :2225 /
        5.5 :2339）。`_stage_start` 只在阶段入口打点 ⇒ 谁调用它，耗时就算进谁：
        实测题 001 `4_verify=5546s` 而 `5_revise_or_fallback=7.4e-06s`
        （revise_round=4，即 4 轮 revise 全被记进 4_verify）；题 000 恰好从 5 段
        调用 ⇒ `5_revise_or_fallback=3683s`。同一机制两种归属 ⇒ 耗时表不可比、
        「verify 占 51.26%」被高估。

        做法：正的 `seconds` 加到 `_stage_durs[name]`，**同时把当前开放阶段的起点
        后移** `seconds`（`dur = now - start` ⇒ 起点后移即等量扣减）。若开放的正是
        `name` 自己（从 5 段内调用），加/扣相抵 ⇒ 幂等，不会重复计数。
        `<=0` 直接返回；无开放阶段时只累加。
        """
        try:
            s = float(seconds or 0.0)
            if s <= 0:
                return
            ctx._stage_durs = getattr(ctx, "_stage_durs", {}) or {}
            ctx._stage_durs[name] = ctx._stage_durs.get(name, 0.0) + s
            starts = getattr(ctx, "_stage_starts", {}) or {}
            for _open in list(starts.keys()):
                try:
                    starts[_open] = starts[_open] + s
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001  纯埋点，绝不阻断主流程
            return

    # ------------------------------------------------------------------
    # C-lite：数值攻击蓝图极值声称（2026-09-03 老师拍板）
    # ------------------------------------------------------------------
    def _final_answer_postprocess(self, ctx, ans: str = "") -> str:
        return _orch_numeric._final_answer_postprocess(self, ctx, ans)

    @staticmethod
    def _latex_const_value(core: str):
        return _orch_numeric._latex_const_value(core)

    def _maybe_numericize(self, ctx, ans: str) -> str:
        return _orch_numeric._maybe_numericize(self, ctx, ans)

    def _objective_selfcheck(self, ctx, ans: str) -> str:
        return _orch_numeric._objective_selfcheck(self, ctx, ans)

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
        return _orch_numeric._answer_form_gate(self, ctx, ans)

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
        return _orch_numeric._looks_like_answer(txt)

    def _ask_for_form(self, ctx, cur: str, asks_all: bool) -> str:
        return _orch_numeric._ask_for_form(self, ctx, cur, asks_all)

    def _lean_crosscheck_number(self, ctx, latex_expr: str, value: str) -> bool:
        return _orch_numeric._lean_crosscheck_number(self, ctx, latex_expr, value)

    def _self_improve_applicable(self, ctx) -> bool:
        return _orch_budget._self_improve_applicable(self, ctx)

    def _phase_budget(self, ctx, ratio: float = 0.0, floor: float = 180.0,
                      reserve: float = 0.0, stage: str = "") -> float:
        return _orch_budget._phase_budget(self, ctx, ratio, floor, reserve, stage)

    def _phase_deadline_guard(self, ctx, cap: float):
        return _orch_budget._phase_deadline_guard(self, ctx, cap)

    @staticmethod
    def _phase_deadline_restore(ctx, saved) -> None:
        return _orch_budget._phase_deadline_restore(ctx, saved)

    def _value_attack_blueprint(self, ctx, tier: str) -> None:
        return _orch_numeric._value_attack_blueprint(self, ctx, tier)

    # ----------------------------------------------------------
    # 主入口（简化版流水线）
    # ----------------------------------------------------------
    def run(self, problem: str, metadata: dict) -> dict:
        now = time.time()
        # ---- 全卷时钟锚点（2026-09-13 修复「全卷时钟是死的」）------------------
        # 原实现把 total_start_time / total_deadline 都基于 `now`，而平台是**逐题**
        # 调用 solve()→run() 的 ⇒ total_deadline 每题都被重置成"此刻 + 6.25h"
        # ⇒ elapsed_total 恒 ≈ 0、ratio 恒 0。
        # ★ 2026-10-01：原先依赖 ratio 的「应急模式 / 时间收紧」两个全卷保护分支
        #   已按研究期标尺**整体删除**（该阶段已于 2026-10-02 删除，见 CHANGES）。
        #   保留锚点仅用于**诊断字段**（`ctx.total_deadline` 等），不再驱动任何
        #   降级逻辑；全卷不做时间总量控制。
        # 锚点只在**首题**锁定一次、跨题保留（并发下"先到先写"，幂等）。
        if getattr(self, "_paper_anchor", None) is None:
            self._paper_anchor = now
        _anchor = float(self._paper_anchor)
        ctx = TaskContext(
            problem=problem,
            metadata=metadata or {},
            budget=Budget(max_calls=self.config.max_total_calls),
            start_time=now,
            deadline=now + getattr(self.config, 'max_time_per_question', 300),
            total_start_time=_anchor,
            total_deadline=_anchor + getattr(self.config, 'max_total_time_seconds', 21000),
            # 2026-10-02：题型惰性求值开关（`1_classify` 阶段删除后由属性消费）。
            _enable_question_type=getattr(self.config, "enable_question_type", True),
        )
        # ★ 2026-10-02 hook 0：中间结果存储层挂载（关闭/失败 → 静默 no-op，主链无感）。
        #   run_id 取进程级稳定值（一轮评测一个目录）；qid 由题面哈希生成（文件名不含中文）。
        try:
            _artifact_attach(ctx, config=self.config, problem=problem)
        except Exception:  # noqa: BLE001  存储层任何问题都不得阻断求解
            pass
        try:
            # ★ 2026-10-02：`0_paper_pacer` 阶段已删除（用户 2026-10-02 点名「全卷配速删了」）。
            #   该阶段原仅记录单题剩余时间的诊断字段、无任何实际逻辑（PaperPacer 已于
            #   2026-09-29 删除），其诊断字段随本阶段一并移除。历史报告仍含该阶段名
            #   （阶段名是稳定契约，此处仅留痕）。
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
                # ★ 2026-10-02 hook 08（超时早返回分支）：终答同样落盘（只加不改）。
                _artifact_put(ctx, "08_final", {
                    "final_response": answer, "timeout": True})
                return safe_json_serialize({
                    "final_response": answer, "trace": ctx.trace,
                    "diag": self._collect_diag(ctx),
                })
            # 2026-10-01：比赛期「全卷时间池按比例降级」已按研究期标尺删除
            # （审计 A 级第 1 条）。原 ratio>0.95 / >0.8 三档会静默置
            # `ctx.state.emergency`，级联关闭 P1 强制重解、2.6 前置验证、
            # 2.7 子目标主路径、3.2 续写、3.3 自改进等能力；且与上方
            # 「PaperPacer 已彻底删除、全卷不做时间总量控制」的注释直接矛盾。
            # ★ 注意：RunState.playoff_enabled 默认为 False，必须在正常态**显式打开**，
            #   否则会静默关掉 playoff（反而多裁一项能力）。
            # 单题唯一约束仍是 `max_time_per_question` 硬墙（见上方 is_timed_out）。
            ctx.state.emergency = False
            ctx.state.playoff_enabled = True

            # ★ 2026-10-02：`1_classify` 阶段已删除（老师建议「聚焦推导」）。
            #   题型不再预分类、不缓存进 ctx；`ctx.question_type` 改为**惰性属性**
            #   （首次读取时按需调 `classify_question_type`，见 agent/base.py）。
            #   下游 130+ 处 `getattr(ctx,"question_type","")` 读取点**零改动**。
            #   历史报告仍含 `1_classify` 阶段名（阶段名是稳定契约，此处仅留痕）。
            #   `enable_question_type=False` 时惰性属性直接返回 ""（消融路径不变）。

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

            # 1.6) 领域 → 定理检索（2026-09-29 新增，截图 #3+#4 老师重点关注）
            #      用户诉求：「我们要判断它是哪个领域的题目，会用到什么定理
            #      （这里就要使用 leansearch 去 mathlib 搜索对应的定理）……
            #      判断大模型或 leansearch 最后有没有找到正确的定理，以及
            #      定理对大模型的推理效果如何？」
            #      本阶段负责**找**（检索命中定理并写入 ctx，供 2.6 前置理解 /
            #      3_solve 提示词使用）；**判定命中率**由离线脚本
            #      `cli/theorem_probe.py` 对预标注表做（非运行时）；
            #      **效用**由 有/无定理 的 A/B（开关 enable_theorem_hint）回答。
            #      ★ 全程 try 包裹且超时可跳过 —— 检索失败绝不阻断主流程。
            _r = self._run_main_stages(ctx)
            if _r is not _SOLVE_CONTINUE:
                return _r

            # ★ 2026-10-02 hook 07：6.5 审核闸门后落盘（07_lean）—— Lean 门禁 / DAG 校验痕迹。
            _artifact_put(ctx, "07_lean", {
                "final_gate": getattr(ctx, "final_gate", None),
                "gate_rejected": getattr(ctx, "gate_rejected", None),
                "lean_dag_checked": getattr(ctx, "lean_dag_checked", None),
                "lean_dag_fails": getattr(ctx, "lean_dag_fails", None),
                "lean_reject_feedback": getattr(ctx, "lean_reject_feedback", None),
                "final_response_after_gate": getattr(ctx, "final_response", ""),
            })

            return self._run_finalize(ctx)
        except Exception as e:  # noqa: BLE001
            logger.error("Orchestrator run failed: %s", e)
            return self._fallback(ctx, problem, e)

    def _run_main_stages(self, ctx: TaskContext) -> dict:
        """主阶段序列 1.2_theorem_hint → 6.5_audit_gate（含 3_solve 哨兵早退）。

        纯搬迁自 ``run``（2026-10-08 批8 原地拆分），**阶段名顺序与 record 步序逐字不变**。
        返回 ``_SOLVE_CONTINUE`` 表示「继续往下走」；其余值（含 3_solve 的早退产物）由调用方透传。
        """
        # ★ 2026-10-13（§3 方案 A）：**1.1_type_understanding** 置于检索之前 ——
        #   先判题型（LLM + 规则交叉校验），产出 `ctx.type_path` 指导后续路径。
        self._stage_start(ctx, "1.1_type_understanding")
        try:
            type_understanding_stage(self, ctx)
        except Exception as _e_tu:  # noqa: BLE001  判题失败不得阻断主链
            self.record(ctx, "type_understanding",
                        f"题型判题阶段异常（跳过，沿用规则判定）: "
                        f"{type(_e_tu).__name__}: {str(_e_tu)[:120]}")

        self._stage_start(ctx, "1.2_theorem_hint")
        theorem_hint_stage(self, ctx)

        # 2) 2026-09-29：**快车道旁路已删除**（用户决策）。
        # 原 `_fast_path()` 用正则匹配题型（如 `\d+\s*[\+\-\*/×÷]\s*\d+`）后
        # 直接 SymPy 直解并 `return`，命中即**跳过全部 19 阶段**（含 Lean 验证、
        # 候选池、投票、审核闸门）——与"研究阶段跑全部方法"直接冲突，且正则过宽、
        # 无法关闭（审计报告 DEF-A3；云端实测 12/112 题命中）。
        # 现统一走下面的完整链路，不再有任何旁路。

        tier = prep_tier_budget(self, ctx)

        self._stage_start(ctx, "2.6_pre_audit")
        pre_audit_stage(self, ctx, tier)

        # 2026-09-29：**2.65_calc_prewarm 阶段已删除**（用户决策：
        # 「预计算没必要，且不合逻辑，删了。之后对于计算部分我们会再想办法」）。
        # 原设计在首个生成阶段前先让 LLM 预列算式并用 SymPy 算好、塞进 prompt，
        # 但用户判定其"不合逻辑"（把计算从推理链里剥离，掩盖了模型真实的
        # 计算能力）。计算部分待后续重新设计。
        # 阶段名 "2.65_calc_prewarm" 已从收尾 stage 列表中同步移除。

        self._stage_start(ctx, "2.7_subgoal_main")
        subgoal_main_path(self, ctx, tier)

        self._stage_start(ctx, "3_solve")
        # 3_solve 求解段已抽到 agent/orchestrator__solve.py::solve_stage，
        # 以「哨兵 + 解包」委托：段内唯一 run 级 return（_fallback_direct）
        # 经哨兵透传，其余路径返回 _SOLVE_CONTINUE。
        _r = solve_stage(self, ctx, tier)
        if _r is not _SOLVE_CONTINUE:
            return _r

        self._stage_start(ctx, "3.2_complete")
        complete_truncated(self, ctx, tier)

        self._stage_start(ctx, "3.3_improve")
        self_improve_step(self, ctx)

        self._stage_start(ctx, "3.4_collab")
        collaborative_deep_improve(self, ctx, tier)

        # 2026-09-29：**3.5_subgoal_sup 阶段已删除**（用户决策）。
        # 原逻辑「仅非 deep 档 + 候选不足时补跑子目标分解」在统一档位后
        # 条件恒假（`tier != 'deep'` 永假），且其语义与 2.7 子目标主路径
        # 完全重叠（2.7 已对所有题先跑一遍并把 `_subgoal_main_done` 置位）。
        # 该阶段已于 2026-09-29 删除；阶段名保留于审计清单（stage_audit）作历史记录。

        # ★ 2026-10-14（五道审核链第 0 道）：**4.0_normalize —— 答案规范化前置**。
        #   用户口径（原话）：「既然会用到 lean 和计算工具，就要提前把答案规范化」。
        #   纯增量：只挂 answer_norm / answer_kind（形态分流：numeric/symbolic/
        #   multi/proof/text/unparseable），**不改 c.answer** ⇒ 旧链行为零变化。
        #   五道全貌：4.0 规范化 → ①自审 → ②证伪 → ③Lean 代回 → ④计算 → ⑤投票。
        self._stage_start(ctx, "4.0_normalize")
        normalize_stage(self, ctx)

        self._stage_start(ctx, "3.6_audit_filter")
        audit_filter_candidates(self, ctx, tier)

        self._stage_start(ctx, "4_verify")
        ver_result, tier_votes = verify_stage(self, ctx, tier)

        self._stage_start(ctx, "4.5_oracle")
        oracle_review_stage(self, ctx, tier, ver_result, tier_votes)

        self._stage_start(ctx, "4.6_adv")
        adversarial_stage(self, ctx, tier, ver_result, tier_votes)

        # ★ 2026-10-13（方案 v3.9 / 用户 Q30）：**4.7_lean —— Lean 检测前移到投票之前**。
        #   起因（审核实测）：答案级 Lean（`6.5_audit_gate` 的 final_gate）在**投票之后**才做
        #   ⇒ 等 Lean 判完，答案早已被选出 ⇒ "淘汰"失去意义（§3.9 E-2）。
        #   本阶段把**候选级 Lean 硬验证**显式前移到投票之前：不通过的候选在投票前即被淘汰。
        #   ⚠ 默认 **False**：这是**主链改动**，按纪律先 A/B、专项回归后再考虑翻默认。
        #   ⚠ 与 3.6 / 4_verify 既有的 Lean 通道可能重叠 ⇒ 只在开关开时启用，并留痕淘汰数。
        if getattr(self.config, "enable_lean_before_vote", False):
            self._stage_start(ctx, "4.7_lean")
            try:
                from tools.lean_local.lean_gate import LeanGate as _LG47
                _gate47 = getattr(self, "lean_gate", None) or _LG47(
                    self.client, self.config)
                _n_in47 = len(ctx.candidates or [])
                _kept47, _fbs47 = _gate47.apply(ctx, tier, list(ctx.candidates or []))
                if _kept47:
                    ctx.candidates = _kept47
                if _fbs47:
                    ctx.audit_reject_feedback = list(
                        getattr(ctx, "audit_reject_feedback", None) or []) + list(_fbs47)
                self.record(ctx, "4.7_lean",
                            "投票前 Lean 淘汰 %d/%d 个候选（保留 %d）"
                            % (_n_in47 - len(_kept47), _n_in47, len(_kept47)))
                ctx._lean_prechecked = True
                from .orchestrator__verify import _pool_empty_fallback as _pef47
                _pef47(self, ctx, "4.7_lean")
            except Exception as _e_47:  # noqa: BLE001  增益环节，绝不阻断主链
                self.record(ctx, "4.7_lean",
                            f"投票前 Lean 检查异常（跳过，不阻断）: "
                            f"{type(_e_47).__name__}: {str(_e_47)[:120]}")

        self._stage_start(ctx, "5_revise_or_fallback")
        revise_or_fallback_stage(self, ctx, tier, ver_result, tier_votes)

        self._stage_start(ctx, "5.5_low_conf")
        low_confidence_recheck(self, ctx, ver_result, tier_votes)

        self._stage_start(ctx, "6_format")
        format_stage(self, ctx)
        self._stage_start(ctx, "6.5_audit_gate")
        final_answer_gate(self, ctx, tier)
        return _SOLVE_CONTINUE

    def _run_finalize(self, ctx: TaskContext) -> dict:
        """收尾：统一 stage_stop + 输出装配（候选/裁决/簇）+ hook08 + 终返回字典。

        纯搬迁自 ``run`` 尾部（2026-10-08 批8 原地拆分），语句逐字不变。
        """
        # 阶段耗时收尾（2026-09-03）：统一 stop 全部阶段（start 在阶段开始）
        # ★ 2026-10-02 移除 `1_classify` / `2.5_difficulty` / `0_paper_pacer`（阶段均已删）；
        #   此前报告仍含这些阶段名（留痕，阶段名是契约）。
        for _stg in ("1.2_theorem_hint",
                     "2.6_pre_audit",
                     "2.7_subgoal_main","3_solve","3.2_complete","3.3_improve",
                     "3.4_collab",
                     "4.0_normalize",
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
        # ★ 2026-10-04（D25）：**已上移到 6.5 闸门之前**（见 `6_format` 之后那段），
        #   此处刻意**不再调用** —— 否则会二次执行，并重新落回
        #   "闸门验 A、实际提交 B"。早退路径（超时兜底 / `_fallback_direct`）
        #   仍在各自出口自行调用，不受影响。

        # ★ 2026-10-02 hook 08：run() 正常返回前落盘终答（08_final）。
        _artifact_put(ctx, "08_final", {
            "final_response": ctx.final_response or "",
            "n_candidates": len(getattr(ctx, "candidates", None) or []),
            "n_verdicts": len(getattr(ctx, "verdicts", None) or []),
        })

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
                # ★ 2026-09-23：「引用即采用」采用率（回答"定理有没有真用上"）
                "adoption": self._mathlib_adoption(ctx),
            },
            # ---- 逐步归因诊断（2026-09-02 用户要求：错题要能定位到环节）----
            # 统一由 _collect_diag 构建（全 getattr 兜底：提前 return / 异常路径也覆盖）
            "diag": self._collect_diag(ctx),
        })

    # ----------------------------------------------------------
    # 2026-09-29：快车道（_fast_path / _try_sympy_solve）已按用户要求**整体删除**。
    #
    # 原设计：正则匹配题型（如 `\d+\s*[\+\-\*/×÷]\s*\d+`）后直接 SymPy 直解并
    # `return`，命中即跳过全部后续阶段（Lean 验证 / 候选池 / 投票 / 审核闸门）。
    # 删除理由：
    #   ① 与"研究阶段用全部方法测试大模型"直接冲突 —— 它省掉的恰是待研究的环节；
    #   ② 首条正则过宽（任何含两个数字与运算符的题干都命中），且无开关可关
    #      （审计报告 DEF-A3）；云端实测 12/112 题命中；
    #   ③ 用户决策"统一一个档位、统一答题格式"，不允许任何旁路。
    # 保留说明：`utils.sympy_tools` 的 import 仍保留（其它模块可能引用），
    # 不再有未定义名风险。
    # ----------------------------------------------------------

    def _review_bug_feedback(self, ctx: TaskContext, feedback: str) -> str:
        return _orch_revise._review_bug_feedback(self, ctx, feedback)

    def _deep_revise_loop(self, ctx: TaskContext, ver_result: dict,
                          tier_votes: int, force: bool = False) -> bool:
        return _orch_revise._deep_revise_loop(self, ctx, ver_result, tier_votes, force)

    def _deep_revise_loop_inner(self, ctx: TaskContext, ver_result: dict,
                                tier_votes: int, force: bool = False) -> bool:
        return _orch_revise._deep_revise_loop_inner(self, ctx, ver_result, tier_votes, force)

    def _build_revise_feedback(self, ctx: TaskContext, ver_result: dict,
                               force: bool) -> str:
        return _orch_revise._build_revise_feedback(self, ctx, ver_result, force)

    def _revise_rounds(self, ctx: TaskContext, max_rounds: int,
                       feedback: str, force: bool, tier_votes: int) -> bool:
        return _orch_revise._revise_rounds(self, ctx, max_rounds, feedback, force, tier_votes)

    def _update_accept_gate(self, ctx: TaskContext, is_proof: bool = False) -> str:
        return _orch_revise._update_accept_gate(self, ctx, is_proof)

    def _enhance_window_ok(self, ctx: TaskContext, tag: str) -> bool:
        return _orch_oracle._enhance_window_ok(self, ctx, tag)

    def _adversarial_probe(self, ctx: TaskContext, tier: str) -> bool:
        return _orch_oracle._adversarial_probe(self, ctx, tier)

    def _mathlib_adoption(self, ctx: TaskContext) -> dict:
        return _orch_select._mathlib_adoption(self, ctx)

    def _falsify_candidates(self, ctx: TaskContext) -> tuple:
        return _orch_oracle._falsify_candidates(self, ctx)

    def _falsify_rejects(self, ctx: TaskContext, answer: str) -> bool:
        return _orch_oracle._falsify_rejects(self, ctx, answer)

    def _oracle_review_best(self, ctx: TaskContext, ver_result: dict,
                            tier_votes: int) -> None:
        return _orch_oracle._oracle_review_best(self, ctx, ver_result, tier_votes)

    def _verdicts_from_ver_result(self, ver_result: dict, candidates: list = None) -> list:
        return _orch_select._verdicts_from_ver_result(self, ver_result, candidates)

    def _has_usable_candidate(self, ctx: TaskContext) -> bool:
        return _orch_select._has_usable_candidate(self, ctx)

    def _maybe_final_select(self, ctx: TaskContext) -> "str | None":
        return _orch_select._maybe_final_select(self, ctx)

    def _pick_best_from_candidates(self, ctx: TaskContext) -> str:
        return _orch_select._pick_best_from_candidates(self, ctx)

    _DIRECT_SYS = (
        "你是数学解题专家。请解答下面这道题。"
        "最后一行必须以【最终答案】: <答案> 的格式给出最终答案，"
        "答案只写数值、表达式或选项字母，不要写任何解释或推理。"
    )

    @staticmethod
    def _set_final_response(ctx: TaskContext, ans: str, reason: str = "") -> bool:
        return _orch_select._set_final_response(ctx, ans, reason)

    def _collect_diag(self, ctx: TaskContext) -> dict:
        return _orch_select._collect_diag(self, ctx)

    def _emergency_direct_solve(self, problem: str) -> str:
        return _orch_fallback._emergency_direct_solve(self, problem)

    def _fallback_direct(self, ctx: TaskContext) -> dict:
        return _orch_fallback._fallback_direct(self, ctx)

    def _fallback(self, ctx: TaskContext, problem: str, exc: Exception) -> dict:
        return _orch_fallback._fallback(self, ctx, problem, exc)
