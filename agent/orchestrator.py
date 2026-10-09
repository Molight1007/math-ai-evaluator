from __future__ import annotations

# 2026-10-01 开关注册制（审查 A 级第 2 条）：开关统一走 switch_registry，
# 不再裸读 os.environ —— 既保持 env 优先级（行为不变），又能被 diag/报告还原。
try:
    from agent.switch_registry import (
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)
except ImportError:
    from switch_registry import (
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)


def _sw_bool_or(field: str, default: bool) -> bool:
    """开关读取的**容错**版：注册表缺该字段时回退 `default`（不抛）。

    为什么需要（2026-10-07 fix-gate-timing-diag）：新开关的登记落在
    `switch_registry.py` / `user_agent.py` / `param_usage.py` 三个**共享文件**，
    可能与本施工员的 `orchestrator.py` 改动**分批落盘**。若裸调 `_sw_bool(field)`
    而此时注册未落，`SWITCHES[field]` 会 KeyError → 被调用点 except 吞掉 →
    功能**静默失效**（且日志无迹）。本函数保证"注册未落也用修好后的默认值"，
    注册落盘后自动获得 env/config 覆盖能力。
    """
    try:
        return bool(_sw_bool(field))
    except Exception:  # noqa: BLE001
        return bool(default)


def _sw_num_or(field: str, default: float) -> float:
    """`get_num` 的容错版（口径同上）。"""
    try:
        return float(_sw_num(field))
    except Exception:  # noqa: BLE001
        return float(default)

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
# 2026-10-02 DeepSeek 适配：env 默认 1024 ⇒ 8192。原值基于「直答只需一行 + prefill
# 抑制思维块」的 Intern-S 时代假设，对 reasoning 模型必然截断（reasoning 先吃满
# 预算、正文为空）。仍可用 EMERGENCY_DIRECT_MAX_TOKENS 覆盖。
#
# ★ 2026-10-07 修（问题总账 §2.6 / §2.3「B 类裸 env 未登记 + import 期求值」）：
#   原为模块级常量 `_EMERGENCY_DIRECT_MAX_TOKENS = int(os.getenv(...))` ——
#   ① import 期求值 ⇒ 若"先 import 后改 env"（仓库里 `cli/run_phase0_eval.py`
#      等正是这种写法）会**静默失效**；② 常量不入注册表 ⇒ diag 的 switch_snapshot
#      看不到、报告还原不出来。
#   现改为**调用时**经注册表读取（`emergency_direct_max_tokens`，字段已于
#   2026-10-07 由 fix-switch-debt 登记进 switch_registry，默认 8192；读取优先级
#   env > config > 默认）。注册未落时回退到"调用时读 env"（与旧常量行为一致，
#   仅修掉 import 期冻结）。
def _emergency_direct_max_tokens() -> int:
    """紧急直答分支的 `max_tokens` 上限（调用时实时读取，见上方说明）。"""
    try:
        _env_default = int(os.getenv("EMERGENCY_DIRECT_MAX_TOKENS", "8192"))
    except (TypeError, ValueError):
        _env_default = 8192
    try:
        return int(_sw_num_or("emergency_direct_max_tokens", float(_env_default)))
    except Exception:  # noqa: BLE001
        return _env_default

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


def _answer_fingerprint(ctx) -> str:
    """当前「答案形态」的指纹 —— 用于跨 revise 轮判断**有没有真进展**。

    ★★ 2026-10-05 修（**两道"无进展保护"是死代码** —— 三步论第 3 步"修正要有效"）：
    两处保护原本都拿 `ctx.final_response` 比较，但它**直到
    `orchestrator.py:2191`（6_format 之后）才第一次被赋值**，而
    `_deep_revise_loop` 的**全部 5 个调用点（P1 / 4.5 oracle / 4.6 对抗 /
    5 全 0 票 / 5.5 低置信）都在 `:2191` 之前** ⇒ 比较对象**恒为 `""`**
    ⇒ `if _npa is not None and _cur_ans and ...` 与
    `if _ans_before and _ans_after and ...` **恒短路边** ⇒ 保护从未生效。
    日志实证：`P1 重解成效：答案未变化（0→0 字符）`。

    改用**候选答案集合**（排序去重后以 `|` 连接）作指纹 ——
    它在 revise 阶段一直有值，且只有"答案集合真的变了"才算有进展。
    """
    try:
        ans = sorted({str(getattr(c, "answer", "") or "").strip()
                      for c in (getattr(ctx, "candidates", None) or [])
                      if str(getattr(c, "answer", "") or "").strip()})
        return "|".join(ans)
    except Exception:  # noqa: BLE001
        return ""


def _merge_review_into_feedback(original: str, review: str,
                                append: bool) -> str:
    """把 Step 4 复核产物并入 revise 反馈 —— **附加**而非覆盖（默认）。

    ★★ 2026-10-06 修（**两处修复互相抵消**）：
      上游 `verifier.py:1819-1821` 已把「深复核推理」（尾段 6000 字符 + 判定段，
      标题 `【复核依据（判错报告原文摘录）】`，整体上限 8000）保留进 feedback；
      但 `_deep_revise_loop` 随后把复核产物**整段覆盖**回 `feedback`
      ⇒ 实测 q1–q6 最终 `diag.revise_feedback` 最长仅 2.4–3.0k、且**不含该段**
      ⇒ 那 2.5–6 万字符的推理仍没到模型手上。

      语义：复核只做「某条缺陷是否属实」的判定与标注，其产物以
      `【复核意见（逐条是否属实，误报已驳回）】` 段**附加**在原文之后；
      `append=False` 回退旧的「整段覆盖」行为（A/B 抓手）。
    """
    if not review:
        return original
    if not append:
        return review
    return (original
            + "\n\n【复核意见（逐条是否属实，误报已驳回）】\n"
            + review)


def _collect_tool_findings(ctx) -> str:
    """收集**纯工具**产出的判定（Lean 编译 / 系统命题验算 / SymPy），供结构化检错器做定位。

    ★★ 2026-10-06 新增（补上「**工具判定 → 答案级定位**」这一环）：
    工具的 finding 里 `location` 装的是**检查项名**（`answer_verify` / `lean_verify`），
    而 `agent/base.py:365` 对 `location` 的定义是「出错位置（步骤编号/行号/引用）」
    ⇒ **契约被违背**：模型收到 `location="answer_verify"` 等于没收到位置。
    工具看的是**形式化代码**、天然说不出"答案第 3 步错了"，但它
    「**这个等式/命题不成立**」的判定是**客观、可复现**的 ⇒ 是定位的最佳锚点。

    本函数把这些锚点抽出来，交给 `verifier.structured_report_for(tool_findings=...)`，
    让它**只负责在答案里逐字引用写下该等式的原文** ⇒
    产出「工具级的可靠性 + 答案级的定位」。

    去重（工具对多个候选常给出同一判定）+ 最多 3 条，避免污染提示词。
    """
    out = []
    try:
        for _k in ("lean_gate", "audit_gate"):
            for e in (getattr(ctx, _k, None) or []):
                if not isinstance(e, dict):
                    continue
                v = str(e.get("verdict") or "")
                if v in ("proof_invalid", "unknown", "reject"):
                    fb = str(e.get("feedback") or e.get("reason") or "").strip()
                    if fb:
                        out.append("[%s|%s] %s" % (_k, v, fb[:400]))
    except Exception:  # noqa: BLE001  收集失败不影响主流程
        pass
    seen, uniq = set(), []
    import re as _re_tf
    for x in reversed(out):
        k = " ".join(x.split())
        k = _re_tf.sub(r"\d+", "#", k)[:120]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
        if len(uniq) >= 3:
            break
    return "\n".join(reversed(uniq))


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
        _env_off = "0" if not _sw_bool("lean_verify") else "1"
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
    # 领域 → 定理检索（2026-09-29 新增，截图 #3+#4）
    # ------------------------------------------------------------------
    def _retrieve_theorem_hints(self, ctx) -> None:
        """1.6) 用 leansearch 到 Mathlib 检索本题该用的定理，写入 ctx。

        写出的字段（供下游各阶段按需取用，**不改变任何既有分支**）：
          · ``ctx.theorem_hints``      : list[str] 命中的 Mathlib 全名
          · ``ctx.theorem_hint_block`` : str 注入提示词用的文本块（可为空）
          · ``ctx.theorem_hint_trace`` : dict 完整埋点（query/命中/耗时/后端）

        ★ 用户要求「调用工具的方法要写成规范性的类函数，需要使用 Lean 检测时
          直接调用那个函数，适配每一阶段」⇒ 检索逻辑**全部收敛在**
          ``agent.theorem_hint.retrieve_theorems_for_question()`` 一个入口，
          本方法只做「调用 + 落盘 + 埋点」，不含任何检索细节。
          换后端/换 query 策略只改 theorem_hint.py，本处不动。

        ★ 失败与超时一律降级（不阻断主流程）：检索只是**增益**，不是门禁。
        """
        try:
            from .theorem_hint import (retrieve_theorems_for_question,
                                       match_against_ground_truth)
        except Exception as e:  # noqa: BLE001
            logger.warning("[1.6_theorem_hint] 模块导入失败，跳过: %s", e)
            return

        try:
            res = retrieve_theorems_for_question(
                ctx.problem or "",
                domain=getattr(ctx, "domain", "") or "",
                question_type=getattr(ctx, "question_type", "") or "",
                config=self.config,
                max_queries=int(getattr(
                    self.config, "theorem_hint_max_queries", 2) or 2),
                top_k=int(getattr(self.config, "leansearch_top_k", 5) or 5),
            )
        except Exception as e:  # noqa: BLE001  # 兜底：接口内已 try，此处再保险
            self.record(ctx, "theorem_hint",
                        f"定理检索异常（跳过，不阻断）: {type(e).__name__}: {e}")
            return

        ctx.theorem_hints = list(res.names)
        md = res.to_dict()
        # 与题库预标注比对（若 metadata 里带了该题标注；云端/离线注入时才有）
        gt = None
        try:
            _md = getattr(ctx, "metadata", None)
            if isinstance(_md, dict):
                gt = _md.get("theorem_gt")
        except Exception:  # noqa: BLE001
            gt = None
        if gt:
            try:
                md["gt_match"] = match_against_ground_truth(res, gt)
            except Exception as e:  # noqa: BLE001
                md["gt_match"] = {"error": f"{type(e).__name__}: {e}"}
        ctx.theorem_hint_trace = md

        # 注入块：★ 2026-09-29 改为调用 `TheoremRetrieval.render_hint_block()`。
        # 原先在此处**内联拼装**「短名 + 全名」两列，实测 5 条命中即 798 字符，
        # 其中 Mathlib 命名空间前缀占 60%+，对中文推理的大模型是纯 token 噪音。
        # 现收敛为「短名列表」——拼装口径统一由 theorem_hint 模块负责（符合用户
        # 「调工具的方法要写成规范性的类函数」），本处不再持有任何渲染细节。
        # 全名仍完整保留在 `ctx.theorem_hint_trace` 里（见下），供 Lean 侧/A-B 归因。
        try:
            ctx.theorem_hint_block = res.render_hint_block(
                max_items=int(getattr(self.config, "leansearch_top_k", 5) or 5))
        except Exception as e:  # noqa: BLE001  渲染失败不阻断
            logger.warning("[1.6_theorem_hint] 渲染注入块失败，跳过注入: %s", e)
            ctx.theorem_hint_block = ""

        self.record(
            ctx, "theorem_hint",
            f"定理检索 {'命中 ' + str(len(res.hits)) + ' 条' if res.ok else '未跑通'}"
            f"（{res.elapsed:.1f}s，后端 {res.backend or '-'}）"
            + (f"；{res.reason}" if res.reason else ""),
            n_hits=len(res.hits), elapsed=round(res.elapsed, 2),
            backend=res.backend)

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
        """3.3 自改进的**题型门控**（2026-09-11）。

        客观题（选择题 / 判断题 / 中文短语）**不做自改进**：
        它们没有"可改进的数学推导过程"，自改进只会白花一次 LLM 调用，
        且实测有害 —— smoke6_v3 实证：098 原答 B（正确），跑完 365s 自改进后
        变成 D（错误），而该题实为概念选择题（问"矩阵条件数定义"）。
        判据复用 Lean 适用性（客观题本就 lean_applicable=False）。
        开关：SELF_IMPROVE_OBJECTIVE_SKIP（默认 1，设 0 恢复旧行为）。
        """
        if not _sw_bool("self_improve_objective_skip"):
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

        ── ★★ 2026-09-15（用户指示「预算都删了，没意义，还卡正确率」）──
        新增总开关 `phase_budget_enabled`（**默认 False = 不限**）。关闭时本函数
        直接返回「无穷大」⇒ `_phase_deadline_guard` 里 `min(ctx.deadline, now+cap)`
        退化为原 deadline ⇒ **阶段帽不再生效**。
        关闭依据：2.7 的帽是 600s，而实测 mean 513 / p50 537 / **max 1168s**
        ⇒ 一半以上的题被砍断子目标链（链没跑完 = 缺项 = 错，不只是慢）。
        ⚠ 本开关**只管"分配型"阶段帽**；LLM 超时重试 / lean_timeout /
          符号求解线程超时 / 各类死循环硬上限**全部保留**（那是"别挂住"，不是配额）。

        ── ★ 2026-10-07 实测结论（问题总账 §2.6「phase_budget_enabled 疑为结构性死开关」）──
        · **非结构性死开关**：本函数是**活路径**——`config.phase_budget_enabled=True`
          时 `_phase_budget(stage="2.7_subgoal_main")` 返回 600.0、阶段帽真实收紧
          （离线实测：False→inf/收紧 0s；True→600.0/收紧 85800s）。`_CAPS` 表在
          False 时确实整表 no-op（这正是"默认关=不限"的**设计意图**，非缺陷）。
        · **但当前评测入口无法打开它**：① 默认 False；② `run_eval.py` **无对应
          CLI flag**（旧判断"不在 CLI 覆盖白名单"已过期 —— 该键现已在
          `user_agent.py` 白名单，可经 kwargs/`agent_overrides` 设置）；
          ③ 读取走 `getattr(config, ...)`，而 env `PHASE_BUDGET_ENABLED` **不经
          config**（实测 env=1 时 `AgentConfig().phase_budget_enabled` 仍为 False）
          ⇒ 单靠 env 无效。
        ⇒ 结论：**代码层活、评测入口层死**；若要真正可调，需在 `run_eval.py` 加
          CLI flag 或把读取改走注册表（后者属行为改动，本次按"唯一行为改动仅 C/E"
          的约束**未改**，仅留此标注）。
        """
        if not getattr(self.config, "phase_budget_enabled", False):
            return float("inf")
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
                # 2026-09-29 新增（截图 #3+#4）：领域→定理检索。
                # 实测（official112 前 12 题）单题 8~11s（源码扫描后端、2 query）。
                # 给 60s 上限：正常 10s 内完成，异常/后端退化时最多烧 60s 即放手。
                "1.2_theorem_hint": 60.0,
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
            _tightened = False
            if ctx.deadline and ctx.deadline > 10**8:
                ctx.deadline = min(ctx.deadline, _end)
                _tightened = True
            if getattr(ctx, "_gen_deadline", 0.0) and ctx._gen_deadline > 10**8:
                ctx._gen_deadline = min(ctx._gen_deadline, _end)
                _tightened = True
            # ★ 2026-10-07 分支静默跳过埋点（问题总账 §2.6「隐形门控」）：原两个 `if`
            #   在 deadline 未设（或为 0/非远期哨兵）时**静默不收紧**，事后只见
            #   "阶段帽没生效"却查不出原因（本项目反复吃的"未触发 vs 被吞"）。补一条。
            if not _tightened:
                self.record(ctx, "phase_budget",
                            f"阶段预算未收紧（cap={cap:.0f}s 跳过）：deadline 与 "
                            f"_gen_deadline 均未设或非远期哨兵")
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

        self._stage_start(ctx, "3.6_audit_filter")
        audit_filter_candidates(self, ctx, tier)

        self._stage_start(ctx, "4_verify")
        ver_result, tier_votes = verify_stage(self, ctx, tier)

        self._stage_start(ctx, "4.5_oracle")
        oracle_review_stage(self, ctx, tier, ver_result, tier_votes)

        self._stage_start(ctx, "4.6_adv")
        adversarial_stage(self, ctx, tier, ver_result, tier_votes)

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
                max_tokens=_emergency_direct_max_tokens(),
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
                    temperature=0.0, max_tokens=_emergency_direct_max_tokens(),
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
        # ★ 2026-10-02 hook 08（Solver 无候选 → 直答兜底）：终答落盘（只加不改）。
        _artifact_put(ctx, "08_final", {"final_response": answer,
                                        "fallback_direct": True})
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
            # ★ 2026-10-02 hook 08（异常兜底分支）：终答落盘（只加不改）。
            _artifact_put(ctx, "08_final", {"final_response": answer,
                                            "fallback": True})
            return {"final_response": answer, "trace": trace,
                    "diag": self._collect_diag(ctx)}
        # 紧急直答
        answer = self._emergency_direct_solve(problem)
        if not answer:
            answer = "未给出有效解答。"
            trace.append({"agent": self.name, "step": "fallback",
                          "content": "紧急直答失败，返回占位答案"})
        # ★ 2026-10-02 hook 08（异常兜底分支，无候选）：终答落盘（只加不改）。
        _artifact_put(ctx, "08_final", {"final_response": answer,
                                        "fallback": True})
        return {"final_response": answer, "trace": trace,
                "diag": self._collect_diag(ctx)}
