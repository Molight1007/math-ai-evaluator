from __future__ import annotations

# 2026-10-01 开关注册制（审查 A 级第 2 条）：开关统一走 switch_registry，
# 不再裸读 os.environ —— 既保持 env 优先级（行为不变），又能被 diag/报告还原。
try:
    from agent.switch_registry import (
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)
except ImportError:
    from switch_registry import (
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)

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
_EMERGENCY_DIRECT_MAX_TOKENS = int(os.getenv("EMERGENCY_DIRECT_MAX_TOKENS", "8192"))

from .base import BaseAgent, TaskContext, Budget, Verdict, _normalize_chat_response
from .classifier import ClassifierAgent, _KNOWN_DOMAINS
from .solver import SolverAgent
from .sub_goal_solver import SubGoalSolverAgent
from .verifier import VerifierAgent
from .formatter import FormatterAgent
from .collaborative_solver import CollaborativeSolver
from .adversarial_verifier import AdversarialVerifier
from .audit_gate import AuditGate
from utils.extract import safe_json_serialize, is_truncated_answer as _is_truncated_answer
from .param_usage import collect_param_usage

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


# ---------------------------------------------------------------------------
# 结构化错误类型聚合（2026-09-15）
# ---------------------------------------------------------------------------
# 背景：用户要求「之后测试记录大模型的具体答题情况，把错误暴露得更加具体」。
# 验证器（VerifierAgent）判 B 时会从 VERIFIER_SYSTEM 约定的**封闭标签集**
# 里回带错误类型（见 `agent/verifier.py: ERROR_TYPE_TAGS`），并以
# `error_types={标签: 票数}` 的形式写进 trace。此处把它们从 trace 收拢成
# 一个整题口径的字典，供 diag / 归因脚本直接消费。
# ⚠ 纯埋点：不参与任何判定，缺 trace 时安静返回 {}。
# ---------------------------------------------------------------------------
def _merge_error_types(ctx) -> dict:
    """从 trace 收拢本题的结构化错误类型分布（整题口径优先）。"""
    trace = getattr(ctx, "trace", None) or []
    merged: dict = {}
    fallback: dict = {}
    for t in trace:
        if not isinstance(t, dict):
            continue
        step = t.get("step")
        dist = t.get("error_types")
        if not isinstance(dist, dict):
            continue
        if step == "verify_error_types":
            merged = dist          # 整题终态，直接采用
        elif step == "vote_error_types" and not merged:
            for k, v in dist.items():   # 单次投票口径，仅作回退累加
                fallback[k] = fallback.get(k, 0) + v
    return merged or fallback


def _sum_reject_votes(ctx) -> int:
    """本题被验证器判 B 的票数（整题口径，无记录则 0）。"""
    trace = getattr(ctx, "trace", None) or []
    for t in reversed(trace):
        if (isinstance(t, dict) and t.get("step") == "verify_error_types"
                and isinstance(t.get("n_reject"), int)):
            return t["n_reject"]
    return 0


# ---------------------------------------------------------------------------
# LeanSearch 检索埋点汇总（2026-09-15，老师 #44）
# ---------------------------------------------------------------------------
# 老师 #44 要求埋点必须能回答四个维度：调用次数 / 命中数 / 去重后条数 / 被采用条数。
# 数据源 = trace 里 step=="leansearch" 的条目（**每个 TaskContext 一题**，
# 所以天然是按题隔离的，不会把全局累计值错当成本题数据）。
# ⚠ 「被采用条数」由 LeanGate 在 Lean 编译通过时回记（`note_adopted`），
#   属**跨题累计**语义，因此这里只报本题的 calls/hits/unique/elapsed，
#   不把累计值混进来（否则同一份 diag 里两个口径打架）。
# ⚠ 纯埋点：无记录时安静返回零值字典。
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
def _compute_subgoal_gaps(ctx) -> dict:
    """子目标逻辑缺口分析（2026-09-29，截图 #6）—— 纯埋点，不改任何分支。

    用户原话：
    > 子目标的设立有没有帮助大模型简化题目……可不可以用 lean 来检测有没有
    > sorry 的地方，**像这种缺少的逻辑点是不是就是大模型需要推理出来的点**？

    本函数把「子目标求解结果」翻译成**可归因的缺口清单**，回答三件事：
      ① 有多少子目标没解出来；
      ② 这些缺口**是什么性质**（纯逻辑跳跃 / 缺引理 / 形式化 / 计算 / 未归类）；
      ③ 其中**哪些才是"必须由大模型推理出来"的点**
         （只有「纯逻辑跳跃」算；形式化与检索问题不算 —— 那两类是工具链的事）。

    ★ 为什么必须做这个区分：若把全部失败笼统算作"模型推理不行"，
      优化方向会被引到调推理提示词；而实际上可能大半是译题错误 —— 那该修的是
      `lean_translator`。没有这个区分，后续所有优化决策都建立在错误归因上。

    ★ 数据源：只读 `ctx.subgoal_trace`（sub_goal_solver 已写入），
      **零新增开销、零 Lean 依赖、零 LLM 调用**。
      缺陷数据（`ctx.refine_result`，LEAP Stage3）当前链路未接入，故不参与；
      一旦接入，`gap_analyzer.merge_gap_sources()` 可直接做双源交集。
    """
    try:
        from .gap_analyzer import extract_subgoal_gaps
    except Exception as e:  # noqa: BLE001
        logger.debug("[gap_analyzer] 导入失败，跳过缺口分析: %s", e)
        return {"ok": False, "error": "模块导入失败"}
    try:
        r = extract_subgoal_gaps(getattr(ctx, "subgoal_trace", None) or [])
        # 明细只留前若干条，避免 diag 膨胀（完整清单离线分析时另取）
        if r.get("gaps"):
            r["gaps"] = r["gaps"][:20]
        return r
    except Exception as e:  # noqa: BLE001  埋点失败绝不阻断求解
        logger.debug("[gap_analyzer] 缺口分析异常: %s", e)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ---------------------------------------------------------------------------
def _compute_lean_gaps(ctx) -> dict:
    """Lean 侧逻辑缺口（2026-09-30，截图 #6 下半问）—— 纯埋点，不改分支。

    用户原话：
    > **可不可以用 lean 来检测有没有 sorry 的地方，像这种缺少的逻辑点
    > 是不是就是大模型需要推理出来的点呢？**

    数据源：`ctx.lean_dag_fails` / `ctx.lean_dag_checked`
      （由 `SubGoalSolver._lean_dag_logic_check()` 写入 —— 它把每个候选子目标
      变成 `example : (expr) := by sorry` 交给 Lean 编译；`by sorry` 挖空了
      "证明"，故**编译失败只可能来自命题本身**）。

    ★ 关键判读（必须与自然语言侧分开看）：
      编译失败 ⇒ 该子目标**连要证什么都没说清** ⇒ 属 `formalization`
      （形式化/表述缺陷），**不是模型推理不出来的点**。
      把它误读成推理瓶颈，优化方向就会错到去调解题提示词。

    与 `_compute_subgoal_gaps` 是**两个独立视角**，故 diag 中并列输出；
    需要交集时由 `gap_analyzer.merge_gap_sources()` 在离线汇总里做。
    """
    try:
        from .gap_analyzer import extract_lean_dag_gaps
    except Exception as e:  # noqa: BLE001
        logger.debug("[gap_analyzer] 导入失败，跳过 Lean 缺口分析: %s", e)
        return {"ok": False, "error": "模块导入失败"}
    try:
        r = extract_lean_dag_gaps(
            getattr(ctx, "lean_dag_fails", None) or {},
            getattr(ctx, "lean_dag_checked", None) or [],
            getattr(ctx, "blueprint", None) or {},
        )
        if r.get("gaps"):
            r["gaps"] = r["gaps"][:20]
        return r
    except Exception as e:  # noqa: BLE001
        logger.debug("[gap_analyzer] Lean 缺口分析异常: %s", e)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ---------------------------------------------------------------------------
def _switch_snapshot() -> dict:
    """开关注册表生效值快照（2026-10-01 注册制）。

    永不抛异常：注册表不可用时返回空 dict，不影响 diag 生成。
    """
    try:
        from agent.switch_registry import snapshot as _snap
        return _snap()
    except Exception:  # noqa: BLE001
        return {}


def _tool_gateway_summary(ctx) -> dict:
    """统一工具调用遥测（2026-09-30，截图 #10）—— 纯埋点，不改分支。

    数据源 = `agent/tool_gateway.ToolGateway.summarize(ctx)`，即本 ctx 上
    那一个门面实例的调用统计。

    ★ 为什么必须落盘：
      用户诉求是「调用工具的方法有没有写成规范性的类函数，需要 Lean 检测时
      直接调用，适配各阶段」。改造后"工具到底被调了几次、为什么没成功"
      必须有**单一数据源** —— 否则又要回到"遍历 trace 猜"的老路（本项目
      已因此把"没跑"误读成"没问题"多次）。

    ⚠ 口径红线：本字段为全零**只说明"没有代码走门面"**，
      绝不能读成"本轮没调用工具" —— 既有调用点（orchestrator 自建 LeanGate、
      answer_falsifier 自建 LeanBridge 等）**尚未迁移到门面**，
      它们的调用量仍在各自的既有埋点里（`leansearch` / `toolcall_exec` 等）。
    """
    try:
        from .tool_gateway import ToolGateway
        s = ToolGateway.summarize(ctx)
        # 附一句口径说明，避免诊断报告读者误读（见上方红线）
        s["_note"] = ("本表只统计走 ToolGateway 的调用；既有调用点尚未全部迁移，"
                      "全零 ≠ 本轮没调用工具")
        return s
    except Exception as e:  # noqa: BLE001
        logger.debug("[tool_gateway] 遥测汇总异常: %s", e)
        return {"total": 0, "by_tool": {}, "by_reason": {},
                "elapsed_total": 0.0, "error": f"{type(e).__name__}: {str(e)[:120]}"}


# ---------------------------------------------------------------------------
def _parse_exhaust_result(subgoal_trace) -> dict:
    """解析「解族穷尽性检查」子目标的输出，判断它**是否真的做了检查**。

    ★ 2026-09-17 新增（针对"不可检测"问题）：
    此前该子目标的 `result` 是**自由文本** ⇒ 无法区分"列了所有解族后确认只有一解"
    与"压根没列、直接把前序结论抄了一遍"。
    实测 003 的 result 就是一句 `a_n = n \\text{ for all } n \\ge 0` —— 无从判断。

    现按 `sub_goal_solver` 中强制的固定格式解析四段：
      `解族清单:` / `逐族判定:` / `前序结论复核:` / `结论: EXHAUSTIVE: yes|no`
    并给出 `complete`（四段是否齐全）与 `n_families`。
    **`complete=False` 即视为"未完成检查"** —— 这是可机检的硬信号。
    """
    out = {"found": False, "complete": False, "n_families": 0,
           "verdict": "", "missed": "", "reason": "无该子目标"}
    try:
        for sg in (subgoal_trace or []):
            if str(sg.get("title", "")).strip() != "解族穷尽性检查":
                continue
            out["found"] = True
            txt = str(sg.get("result", "") or "")
            if not txt.strip():
                out["reason"] = "result 为空"
                return out
            has_list = "解族清单" in txt
            has_judge = "逐族判定" in txt
            has_review = "前序结论复核" in txt
            # ⚠ 本模块用 `import re as _re`（非 `re`）—— 首版写 `re.search` 直接
            #   NameError 被兜底吞成"解析异常"，测试才发现。别再用裸 `re`。
            m_verdict = _re.search(r"EXHAUSTIVE\s*[:：]\s*(yes|no)", txt, _re.I)
            out["complete"] = bool(has_list and has_judge and has_review
                                   and m_verdict)
            out["verdict"] = (m_verdict.group(1).lower() if m_verdict else "")
            # 解族数量：取「解族清单」段里出现的分隔符数量 + 1（保守估计）
            if has_list:
                seg = txt.split("解族清单", 1)[-1]
                seg = _re.split(r"逐族判定", seg, maxsplit=1)[0]
                n = len(_re.findall(r"[/、,，;；]|\n\s*[-*\d]", seg))
                out["n_families"] = min(max(n, 0), 40)
            if "遗漏解族" in txt:
                out["missed"] = txt.split("遗漏解族", 1)[-1].strip()[:300]
            out["reason"] = ("格式完整" if out["complete"]
                             else "缺段：%s" % ",".join(
                                 [n for n, ok in (("解族清单", has_list),
                                                  ("逐族判定", has_judge),
                                                  ("前序结论复核", has_review),
                                                  ("EXHAUSTIVE", bool(m_verdict)))
                                  if not ok]))
            return out
    except Exception as exc:  # noqa: BLE001
        out["reason"] = "解析异常: %s" % type(exc).__name__
    return out


# ★ 2026-09-17（P1-F）：受监控的诊断键（trace step 名）。
_DIAG_MONITORED_KEYS = (
    "value_attack", "formal_spec", "formal_gaps", "pick_diag", "lemma_repo",
    "preverify_trace", "symbolic_solve_events", "objective_check_events",
    "numericize_events", "expression_eval_events",
    # 2026-09-18：文本通道工具调用（模型想调用但被协议挡住，此前不可见）
    "toolcall_text_detected",
)


# 属性型埋点键 → ctx 属性名（不经 `self.record` 写入，须单独查）
_DIAG_ATTR_KEYS = {
    "pick_diag": "_pick_diag",
    "formal_spec": "formal_spec",
    "formal_gaps": "formal_gaps",
    "lemma_repo": "lemma_repo",
    "preverify_trace": "preverify_trace",
}


def _diag_completeness(ctx) -> dict:
    """2026-09-17（P1-F）：**区分「未执行」与「执行但无产出」**。

    背景：实测 13/14 个诊断键在多数题为「键存在但值为空」，读 `diag` 时**无法判断**
    是"该环节根本没跑"还是"跑了但没产出" ⇒ 归因只能靠猜（此前已多次因此误判）。

    三态：
      · `not_ran`        —— trace 里没有该 step 的任何记录（环节未执行）
      · `ran_no_output`  —— 有记录，但内容与附加字段均为空（执行过、无产出）
      · `ran_with_data`  —— 有记录且有内容/附加字段（正常）
    """
    out = {}
    try:
        _tr = [t for t in (getattr(ctx, "trace", None) or [])
               if isinstance(t, dict)]
    except Exception:  # noqa: BLE001
        _tr = []
    for _k in _DIAG_MONITORED_KEYS:
        _hits = [t for t in _tr if str(t.get("step", "")) == _k]
        # ★ 2026-09-18 修（审计发现）：受监控键里有**属性型**的（不经 trace 写入），
        #   如 `pick_diag` 实为 `ctx._pick_diag`。原实现只查 trace step ⇒ 对它们
        #   **恒报 `not_ran`**，与事实矛盾（实测 10/10 题 `pick_diag` 非空却报 not_ran）。
        #   属性存在且非空 ⇒ 视为有产出。
        if not _hits:
            _attr = _DIAG_ATTR_KEYS.get(_k)
            if _attr:
                try:
                    if getattr(ctx, _attr, None):
                        out[_k] = "ran_with_data"
                        continue
                except Exception:  # noqa: BLE001
                    pass
            out[_k] = "not_ran"
            continue
        _has = False
        for _t in _hits:
            if str(_t.get("content", "") or "").strip():
                _has = True
                break
            if any(_kk not in ("step", "content") for _kk in _t.keys()):
                _has = True
                break
        out[_k] = "ran_with_data" if _has else "ran_no_output"
    return out


def _summarize_deep_review(ctx) -> dict:
    """按题汇总「带推理的最终复核」的判定（2026-09-15）。

    ★ 为什么必须单独导出：复核的否决是通过**压低簇置信度**表达的（复用既有
      revise 通道），**不产生新的 Verdict** ⇒ `n_reject_votes` / `error_types`
      只看投票列表，**看不到复核说了什么**。第一轮实测就吃了这个亏：
      086 的 `4_verify` 从十几秒涨到 249 秒（说明复核跑了），但导出里
      `n_reject_votes=0`、`error_types={}`，**无法判断它是判了 A 还是判了 B**。
      故此处把复核的判定作为**独立信号**导出（不伪造投票票数）。
    """
    entries = [t for t in (getattr(ctx, "trace", None) or [])
               if isinstance(t, dict) and t.get("step") == "deep_review"]
    if not entries:
        return {"ran": False, "verdict": "", "error_type": "", "skipped": ""}
    last = entries[-1]
    verdict = str(last.get("verdict") or "")
    ran = verdict in ("A", "B")
    return {
        "ran": ran,
        "verdict": verdict,
        "error_type": str(last.get("error_type") or ""),
        "chars": int(last.get("chars") or 0),
        # 未运行时的原因（时间不足 / 已达上限 / 未启用）
        "skipped": "" if ran else str(last.get("content") or "")[:120],
    }


def _summarize_leansearch(ctx, cfg=None) -> dict:
    """按题汇总 LeanSearch 检索埋点。

    ★ 2026-09-21 扩写（用户要求「记录 leansearch 到底要找多少 Mathlib
      定理」）：此前只有**产出侧**口径（calls / hits / unique / elapsed_ms /
      root），缺**需求侧与触顶侧**口径 ⇒ 事后无法回答"到底是检索次数不够、
      还是命中条数被 `leansearch_top_k` 截了、还是压根没时间检索"。
    新增字段：
      · n_queries        —— 真正发起检索的次数（= 有 n_hits 的条目数）
      · per_query        —— 每次检索的命中条数序列（看分布，不只看总和）
      · top_k / top_k_capped          —— 单次命中是否顶到 leansearch_top_k
      · max_calls_per_q / calls_capped —— 单题调用次数是否顶到上限
      · skipped_time_critical / skipped_call_cap —— 两类跳过各几次
    """
    entries = [t for t in (getattr(ctx, "trace", None) or [])
               if isinstance(t, dict) and t.get("step") == "leansearch"]
    hits_seq = [int(e.get("n_hits", 0) or 0) for e in entries
                if "n_hits" in e]
    calls = len(hits_seq)
    hits = sum(hits_seq)
    ms = sum(float(e.get("elapsed_ms", 0.0) or 0.0) for e in entries)
    uniq = set()
    for e in entries:
        for n in (e.get("names") or []):
            if n:
                uniq.add(n)
    roots = [str(e.get("root", "")) for e in entries if e.get("root")]
    # 两类跳过的 record 文案（verifier._prepare_theorem_context 里各一处）
    skipped_time = sum(1 for e in entries
                       if "时间紧张" in str(e.get("content", "")))
    skipped_cap = sum(1 for e in entries
                      if "上限" in str(e.get("content", "")))
    cap_calls = top_k = None
    try:
        if cfg is not None:
            cap_calls = int(getattr(cfg, "leansearch_max_calls_per_q", 0) or 0)
            top_k = int(getattr(cfg, "leansearch_top_k", 0) or 0)
    except Exception:  # noqa: BLE001
        cap_calls = top_k = None
    return {
        "calls": calls,                 # 兼容旧字段名（= n_queries）
        "n_queries": calls,
        "hits": hits,
        "unique": len(uniq),
        "per_query": hits_seq,          # 每次检索命中条数（分布口径）
        "top_k": top_k or None,
        "top_k_capped": bool(top_k and hits_seq and max(hits_seq) >= top_k),
        "max_calls_per_q": cap_calls or None,
        "calls_capped": bool(cap_calls and calls >= cap_calls),
        "skipped_time_critical": skipped_time,
        "skipped_call_cap": skipped_cap,
        "elapsed_ms": round(ms, 1),
        "root": roots[-1][:120] if roots else "",
    }

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
        if _sw_bool("numericize_final"):
            try:
                ans = self._maybe_numericize(ctx, ans)
            except Exception as _e:  # noqa: BLE001
                logger.debug("[P2] 数值化异常跳过: %s", _e)
        if _sw_bool("objective_selfcheck"):
            try:
                ans = self._objective_selfcheck(ctx, ans)
            except Exception as _e:  # noqa: BLE001
                logger.debug("[P5] 客观题自检异常跳过: %s", _e)
        # B0（2026-09-13）：答案形态闸门——条件式→具体值 / 求所有→枚举
        if _sw_bool("answer_form_gate"):
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
        为什么不用 `utils.math_eval.to_exact_number`：实测它对本链路的典型失分格式
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
            if not _sw_bool("answer_form_gate"):
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
                # 2026-10-02 DeepSeek 适配：原 512 ⇒ 8192。原值基于「答案规范化只需
                # 一行 + 提示词抑制输出」的 Intern-S 时代假设，对 reasoning 模型必然
                # 截断（reasoning 先吃满预算、正文为空）。
                temperature=0.0, max_tokens=8192,
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
        if not _sw_bool("lean_xcheck_numeric"):
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
                self.record(ctx, "value_attack",
                            "跳过：时间紧张（is_time_critical）")   # Z2 2026-09-17
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
                self.record(ctx, "value_attack",
                            "跳过：无蓝图 merge 文本")            # Z2 2026-09-17
                return
            # 只对"极值声称"题下手（其余题型放行，零误伤）
            import re as _re2
            if not (_re2.search(r"max|min|最大|最小", merge_text, _re2.I)):
                logger.debug("[C-lite] 跳过数值攻击：merge 文本无极值关键词")
                self.record(ctx, "value_attack",
                            "跳过：merge 文本无极值关键词")        # Z2 2026-09-17
                return
            from .value_attack import attack_value_claim
            from utils.prefill import prefill_messages, stitch
            # 1) LLM 从题目 + 声称提取: 方向/声称值/目标函数 Python 源码
            # ★★★ 2026-09-16 修复（实测驱动）：本攻击是**连续优化**专用框架
            #   （要求 LLM 给出 `f(x)` 与 `sample_point()`），但触发条件
            #   **只查 merge 文本是否含 max/min/最大/最小** ⇒ **组合题**只要提到
            #   "最小"就会被拉进来。
            #   实测 official112-013（组合极值：求最小 d 使任意整数序列存在子集和
            #   落在 1810±d）：LLM 只能为**连续**框架瞎编一个 `f`，采样得
            #   `best=0.000000`，而 `claimed=54.0` ⇒ 判"证伪"并写入
            #   `audit_reject_feedback` ⇒ **用一个无意义的采样值驱动了修订**
            #   （该题 revise_round=4）。**在极值声称正确时同样会误杀**。
            #   修法：让提取器**同时判定题目是否属连续优化**，非连续则跳过。
            sys_p = (
                "你是数值提取器。判断题目**是否为连续优化/极值问题**"
                "（即目标可写成关于实数变量 x[0],x[1],… 的连续函数，且约束为"
                "连续可判定）。\n"
                "**组合/数论/离散/图论极值问题一律判 false**"
                "（例如『求最小 d 使任意整数序列存在子集和满足…』是组合极值，不是连续优化）。\n"
                "输出 JSON：\n"
                "{\"is_continuous_opt\": true|false, "
                "\"direction\": \"max\"|\"min\", \"claimed\": <声称的极值数值近似>, "
                "\"code\": \"def f(x): ... 用 x[0],x[1]... 计算目标函数返回 float; "
                "def sample_point(): 返回一个满足约束的可行点 list\"}\n"
                "注意：claimed 是把题目声称的极值（含根式分数）算出的十进制近似；"
                "code 必须自含约束检查（不可行点返回 None）；禁止 import 外部库之外的；"
                "只输出 JSON。"
            )
            user_p = f"题目：\n{ctx.problem[:1500]}\n\n声称的答案/蓝图结论：\n{merge_text[:800]}"
            # ★ 2026-09-17（Z1）：**前置**跳过离散/组合类题。
            # 原实现把 `is_continuous_opt` 判定放在下面那次 LLM 调用**之后**
            # （`max_tokens=32768`，最坏 2×300s 超时重试）⇒ 组合/数论/离散题
            # 也**先付一次超长调用**才被跳过（实测 002/003/013/025 四题最终都判为
            # 非连续优化，即那次调用纯浪费）。
            # 判据**只用 `ctx.domain`**（高精度、零误伤）：仅在明确属离散领域时前置
            # 跳过；其余仍由 LLM 的 `is_continuous_opt` 判定（下方原逻辑完全不动）。
            _dom_now = str(getattr(ctx, "domain", "") or "")
            if any(_k in _dom_now for _k in
                   ("组合", "数论", "离散", "图论", "数理逻辑")):
                self.record(ctx, "value_attack",
                            "跳过数值攻击：领域=%s 属离散/组合类，连续采样框架不适用"
                            " —— **前置跳过，未付出 LLM 调用**（Z1 2026-09-17）"
                            % _dom_now[:20])
                return
            raw = self.llm(ctx, prefill_messages(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": user_p}], '{"direction":'), 0.0, 32768)
            if not raw:
                logger.debug("[C-lite] 跳过数值攻击：LLM 提取返回空")
                self.record(ctx, "value_attack",
                            "跳过：LLM 提取返回空（**本次已付出一次超长调用**）")
                return
            raw = stitch('{"direction":', raw)
            m = _re2.search(r"\{[\s\S]*\}", raw)
            if not m:
                logger.debug("[C-lite] 跳过数值攻击：LLM 输出无 JSON 块")
                self.record(ctx, "value_attack",
                            "跳过：LLM 输出无 JSON 块（**已付出调用**）")
                return
            import json as _json
            try:
                parsed = _json.loads(m.group())
            except (_json.JSONDecodeError, ValueError) as exc:
                logger.debug("[C-lite] 跳过数值攻击：JSON 解析失败 %s", exc)
                self.record(ctx, "value_attack",
                            "跳过：JSON 解析失败（**已付出调用**）：%s" % str(exc)[:80])
                return
            direction = str(parsed.get("direction") or "")
            claimed = parsed.get("claimed")
            code = str(parsed.get("code") or "")
            # ★ 2026-09-16：非连续优化题**直接跳过**（见上方 sys_p 的注释）。
            #   缺省视为 True 以保持旧行为（只在新字段缺失时如此，避免误跳过）。
            if parsed.get("is_continuous_opt") is False:
                self.record(ctx, "value_attack",
                            "跳过数值攻击：提取器判定本题**不是**连续优化/极值问题"
                            "（组合/数论/离散类），连续采样框架不适用")
                return
            if direction not in ("max", "min") or claimed is None:
                logger.debug("[C-lite] 跳过数值攻击：direction=%r claimed=%r 不合法",
                             direction, claimed)
                self.record(ctx, "value_attack",
                            "跳过：direction/claimed 不合法"
                            "（**已付出调用**）direction=%r claimed=%r"
                            % (direction, claimed))               # Z2 2026-09-17
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
            #      `tools/theorem_probe.py` 对预标注表做（非运行时）；
            #      **效用**由 有/无定理 的 A/B（开关 enable_theorem_hint）回答。
            #      ★ 全程 try 包裹且超时可跳过 —— 检索失败绝不阻断主流程。
            self._stage_start(ctx, "1.2_theorem_hint")
            if (getattr(self.config, "enable_theorem_hint", True)
                    and not ctx.state.emergency):
                self._retrieve_theorem_hints(ctx)

            # 2) 2026-09-29：**快车道旁路已删除**（用户决策）。
            # 原 `_fast_path()` 用正则匹配题型（如 `\d+\s*[\+\-\*/×÷]\s*\d+`）后
            # 直接 SymPy 直解并 `return`，命中即**跳过全部 19 阶段**（含 Lean 验证、
            # 候选池、投票、审核闸门）——与"研究阶段跑全部方法"直接冲突，且正则过宽、
            # 无法关闭（审计报告 DEF-A3；云端实测 12/112 题命中）。
            # 现统一走下面的完整链路，不再有任何旁路。

            # 2.5) 2026-09-29：**难度路由已删除，统一为单一档位**（用户决策）。
            # 原 DifficultyRouter 静态预判 + LLM 自评 → fast/standard/deep 三档，
            # 档位再决定候选数/投票数/子目标数/预算等"方法集"——违背"用全部方法
            # 测试大模型能力"的初衷。现 `ctx.tier` 恒为 "deep"（= 原最强档配置），
            # 不再有任何按难度分流的分支。
            # ⚠ 同时删除的还有：应急降档（emergency → standard）、deep 全卷配额闸
            #   （allow_deep()，`deep_quota_ratio=0.25` × 112 = 28 恰等于实测 deep 题数，
            #   即"研究档下仍按配额裁剪方法"的头号来源）。
            ctx.tier = "deep"
            tier = "deep"
            # 2026-10-01 按用户决策：研究期不限时 —— **删除"单题按剩余时间收紧 deadline"
            # 的降级路径**（原 `min(硬顶, 档位软预算)` 会把单题拦腰截断）。
            # 现单题只受 `max_time_per_question`（86400，仅防挂死）约束，不再按预算降级。
            # soft_budget 仅保留为诊断字段（值=档位预算，已=86400）。
            ctx.soft_budget = float(
                (getattr(self.config, 'tier_budget', None) or {}).get("deep", 86400.0))
            # 尾部阈值：统一取 deep 档值 60s（把时间用得更尽）。
            # 2026-09-29：原 `if tier == 'deep'` 分支已因统一档位删除。
            ctx.critical_tail_seconds = float(
                getattr(self.config, 'deep_critical_tail_seconds', 60.0))
            # 2026-10-01 按用户决策：研究期不限时 —— **删除"生成侧软截止 (verify_reserve)"
            # 降级路径**。原逻辑预留 540s 给验证侧、逼生成在同一截止点前停手；
            # 研究期不省资源，生成/验证不再互相掐预算。
            # `_gen_deadline` 保持未设（0.0）⇒ `gen_time_up()` 回退 `is_time_critical()`，
            # 而单题 deadline 已达 86400 ⇒ 实际不再触发任何"按剩余时间降级"。
            ctx._gen_deadline = 0.0
            # 按档位调整 LLM 调用预算（deep 档需要更多调用次数）
            max_calls = self.config.tier_max_calls.get(
                tier, self.config.max_total_calls)
            if ctx.budget is not None:
                ctx.budget.set_max_calls(max_calls)
            # ⚠ `paper_pacer` 是遗留 event 标签（PaperPacer 已于 2026-09-29 删除），
            #   内容（档位/调用预算）仍有效，2026-10-02 起仅作标签保留，勿据此判断全卷配速存在。
            self.record(ctx, "paper_pacer",
                        f"档位 {tier} 软预算帽 {ctx.soft_budget:.0f}s "
                        f"(调用预算 {max_calls})",
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

            # ★ 2026-10-02 hook 01：题意理解确认后落盘（2.6_pre_audit → 01_understanding）。
            _artifact_put(ctx, "01_understanding", {
                "question_type": getattr(ctx, "question_type", ""),
                "domain": getattr(ctx, "domain", ""),
                "lean_applicable": (ctx.metadata or {}).get("lean_applicable"),
                "lean_skip_reason": (ctx.metadata or {}).get("lean_skip_reason"),
                "trace": [t for t in (getattr(ctx, "trace", None) or [])
                          if isinstance(t, dict)
                          and t.get("step") in ("classify_type",
                                                "confirm_understanding",
                                                "lean_preverify")][-20:],
            })

            # 2026-09-29：**2.65_calc_prewarm 阶段已删除**（用户决策：
            # 「预计算没必要，且不合逻辑，删了。之后对于计算部分我们会再想办法」）。
            # 原设计在首个生成阶段前先让 LLM 预列算式并用 SymPy 算好、塞进 prompt，
            # 但用户判定其"不合逻辑"（把计算从推理链里剥离，掩盖了模型真实的
            # 计算能力）。计算部分待后续重新设计。
            # 阶段名 "2.65_calc_prewarm" 已从收尾 stage 列表中同步移除。

            self._stage_start(ctx, "2.7_subgoal_main")
            # 2.7) 子目标细化主路径（v2.9）：统一档位下先跑一次子目标分解逐步求解
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

            # ★ 2026-10-02 hook 02/03：蓝图(DAG) / 子目标落盘（只加不改）。
            #   位置刻意放在 **2.7 主路径 + deep 档 P&E 之后**：两条路径谁产出了蓝图
            #   都能覆盖；二者互斥（P&E 有 `not _subgoal_main_done` 守卫）故只写一次。
            #   02_blueprint = AND-OR DAG；03_subgoals = DAG 转出的子目标规划 + 逐步结果。
            _bp02 = getattr(ctx, "blueprint", None) or {}
            _pl03 = getattr(ctx, "blueprint_plan", None) or {}
            _st03 = getattr(ctx, "subgoal_trace", None) or []
            if _bp02:
                _artifact_put(ctx, "02_blueprint", _bp02)
            if _pl03 or _st03:
                _artifact_put(ctx, "03_subgoals", {"plan": _pl03, "trace": _st03})

            # Solver 多路采样（候选数/温度分层按档位，solver 内部读取 ctx.tier）
            # 2026-10-01 按用户决策：研究期不限时 —— **删除"L1 验证优先"触发路径**
            # （原：剩余 < verify_only_seconds 时停止生成新候选）。`ctx.state.verify_only`
            # 不再被置位（恒 False）⇒ 下游 `not ctx.state.verify_only` 门禁恒放行，
            # 不再有任何"为省时间而跳过生成/审核"的降级。
            if not ctx.state.verify_only:
                # 2026-09-06 超时修复：生成侧软截止已到且已有候选 → 不再追加
                # 生成（solver.run 单次可能 200-300s），直接带现有候选进验证。
                # 无候选时仍必须跑（兜底产出第一候选）。
                if ctx.gen_time_up() and ctx.candidates:
                    # ⚠ `paper_pacer` 是遗留 event 标签（PaperPacer 已于 2026-09-29 删除），
                    #   2026-10-02 起仅作标签保留，勿据此判断全卷配速存在。
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

            # ★ 2026-10-02 hook 05：3_solve 生成后落盘候选池（05_candidates）。
            _artifact_put(ctx, "05_candidates", [
                {"id": c.id, "answer": getattr(c, "answer", ""),
                 "reasoning": getattr(c, "reasoning", ""),
                 "revised": getattr(c, "revised", False)}
                for c in (getattr(ctx, "candidates", None) or [])
            ])

            if not self._has_usable_candidate(ctx):
                # 2026-09-13 晚：判据从 `not ctx.candidates` 放宽为"无**可用**候选"。
                # 旧判据只看池子空不空，而 solver 原先会塞占位候选 ⇒ 池子非空但
                # 全是占位符，这条兜底（以及 `_emergency_direct_solve`）永远不触发。
                self.record(ctx, "control",
                            "Solver 未产出可用候选（空/占位符），触发兜底直接求解")
                return self._fallback_direct(ctx)

            self._stage_start(ctx, "3.2_complete")
            # 3.2) 截断候选续写：统一档位 max_completions 个，应急模式跳过
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

            # 2026-09-29：**3.5_subgoal_sup 阶段已删除**（用户决策）。
            # 原逻辑「仅非 deep 档 + 候选不足时补跑子目标分解」在统一档位后
            # 条件恒假（`tier != 'deep'` 永假），且其语义与 2.7 子目标主路径
            # 完全重叠（2.7 已对所有题先跑一遍并把 `_subgoal_main_done` 置位）。
            # 该阶段已于 2026-09-29 删除；阶段名保留于审计清单（stage_audit）作历史记录。

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
            # ⚠ 2026-09-17（Audit-4）核实：`orchestrator.run()` 仅在
            #   `user_agent.solve()` 里被调用**一次**（无重试/升级循环）⇒ 本守卫的
            #   读(:此) 与写(下方) 同处一趟直线代码内，**当前恒为真分支（守卫无效）**。
            #   保留而不删除，是为将来 run() 被重入时仍能防重复触发；但**不得**把它
            #   当作"已生效的幂等保护"来依赖（原测试仅断言源码字符串含该名，锁不住行为）。
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
                    _p1_before = str(getattr(ctx, "final_response", "") or "")
                    self._deep_revise_loop(ctx, {}, tier_votes, force=True)
                    # G1（2026-09-11）：记录重解成效——此前只能看到"触发了"，
                    # 看不到"改没改、改成什么样"，导致"触发但无效"无法量化。
                    _p1_after = str(getattr(ctx, "final_response", "") or "")
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

            # 2026-10-01：比赛期「候选池统一封顶 6」已按研究期标尺删除
            # （审计 A 级第 6 条）。原注释自述 `cap 8→6（deep 候选 4→3 配套，
            # 验证成本 -25%）` —— 属以成本为由裁剪候选粒度。研究期求正确率上限，
            # 不再截断候选；此处仅保留计数记录，便于观察候选规模与耗时关系。
            _pre_verify_n = len(ctx.candidates or [])
            if _pre_verify_n > 6:
                self.record(ctx, "control",
                            f"候选池 {_pre_verify_n} 个（已取消封顶，不再截断为 6）")
            # 2026-09-13：过滤「非答案形态」候选。
            # 096 实测：候选 answer 字段里混入 Markdown 标题 `### 选项A分析`，
            # 因其 len>3 且不含拒绝词，被计入选择题投票 ⇒ **污染投票分布**。
            # 只过滤**明确的行首结构标记**（标题/列表/引用/表格），
            # 不碰正文类长答案（统计学的论述题 gold 本就是长文本）。
            # ★★ 2026-09-18（审核发现）：原判据**只认 Markdown 行首标记**
            #   （`#`/`-`/`*`/`数字.`/`>`/`|`），而实测大量脏候选是「过程叙述」
            #   （`步骤11：搜索已知结论`、`继续找规律，目前 type B：2, 8, 10。`），
            #   于是 032 记录"过滤 5 → 4"只滤掉 `- ` 开头那一条，其余全部留存
            #   并进入投票 ⇒ **污染票型、进而被选为最终答案**。
            #   现改为**复用 formatter 的 `_looks_like_non_answer`**（单一判据来源，
            #   避免两处口径分叉），Markdown 标记作为兜底保留。
            try:
                try:
                    from .formatter import _looks_like_non_answer as _nma36
                except Exception:  # noqa: BLE001
                    _nma36 = None

                def _keep_cand(_c):
                    _a = getattr(_c, "answer", "") or ""
                    if _re.match(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>\s|\|\s)", _a):
                        return False
                    if _nma36 is not None and _nma36(_a):
                        return False
                    return True

                _before36 = list(ctx.candidates or [])
                _clean = [_c for _c in _before36 if _keep_cand(_c)]
                if _clean and len(_clean) < len(_before36):
                    self.record(ctx, "control",
                                "过滤非答案形态候选 {} → {}（复用 _looks_like_non_answer，"
                                "2026-09-18）".format(len(_before36), len(_clean)))
                    ctx.candidates = _clean
                elif not _clean and _before36:
                    # 全被滤掉时不清空池（保持与 M2 同一原则），只记录
                    self.record(ctx, "control",
                                "候选池 %d 个全部呈非答案形态（未清空，保持 M2 原则，"
                                "2026-09-18）" % len(_before36))
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

            # ★ 2026-10-02 hook 06：4_verify 后落盘 verdict（06_verdicts）。
            _bc6 = getattr(ctx, "_best_cluster", None)
            _artifact_put(ctx, "06_verdicts", {
                "verdicts": [
                    {"id": v.id, "answer": getattr(v, "answer", ""),
                     "confidence": getattr(v, "confidence", None),
                     "correct_votes": getattr(v, "correct_votes", None),
                     "total_votes": getattr(v, "total_votes", None),
                     "feedback": getattr(v, "feedback", "")}
                    for v in (getattr(ctx, "verdicts", None) or [])
                ],
                "cluster": (None if _bc6 is None else {
                    "answer_norm": getattr(_bc6, "answer_norm", ""),
                    "size": getattr(_bc6, "size", None),
                    "confidence": getattr(_bc6, "confidence", None),
                    "candidate_ids": getattr(_bc6, "candidate_ids", None),
                }),
            })

            self._stage_start(ctx, "4.5_oracle")
            # 4.5) deep 档：AnswerOracle 客观复核 best_cluster（区别于投票同源自评）
            # 2026-09-06 超时修复（验证暴露残留洞）：oracle 复核单次可达 300s+，
            # 原只在内部查 is_time_critical（deadline-60s）→ algebra-003 修复后
            # verify 提前完成反而给 oracle 打开 365s 烧穿窗口（elapsed 1402s）。
            # oracle 是"4_verify 之后的复核增强"，到生成侧软截止即弃——
            # verify 已投过票，放弃复核不损失主验证，只少一层 deep 深查。
            # ★ 2026-09-17（Audit-3）：口径统一为 `is_time_critical()`（真实剩余时间）。
            # `gen_time_up()` 是**生成**侧软截止（deadline − verify_reserve）；4.5 Oracle
            # 属"4_verify 之后的复核"，用生成时钟闸它是口径错配，与已修好的 5.5 不一致。
            # 真正的耗时护栏是本行的 `_enhance_window_ok`（要求剩余 ≥ 360+tail+30），
            # 故换时钟不会重新打开烧穿窗口。
            if (tier == 'deep'
                    and getattr(ctx, '_best_cluster', None) is not None
                    and not ctx.is_time_critical()
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
                # ★ 2026-09-17（Audit-3）：同上，改用 `is_time_critical()`。
                # 全 0 票后的强制重解属**验证之后的修正**，不是生成；原用生成侧
                # 软截止闸它，与同文件 5.5（已改 `is_time_critical`）形成新的不一致。
                if (tier == 'deep' and not ctx.state.emergency
                        and not ctx.is_time_critical()):
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
                    # ★ 2026-09-23 改造：改为「**证伪优先**」。
                    #   本路径原文是"候选全 0 票 ⇒ 池不可信 ⇒ 弃池、改取 direct_solve
                    #   的另一条产线答案"。但 0923 环节效能审计推翻了该前提：
                    #   · 两个主力闸门（4_verify 全 0 票 / lean_gate proof_invalid）
                    #     在**正确题**上的误报率都是 **56%** ⇒ "全 0 票"不等于池不可信；
                    #   · 弃池的代价实测为：18 题终答出池、16 题判错（= 全部错题 43.2%）。
                    #   用户判据："**错误答案一定是能证明错误的**" ⇒ 择优的正确姿势是
                    #   **先淘汰能被客观证伪的候选**，再在幸存者中择优；只有幸存者为 0
                    #   （或证伪器不可用）时，才回退到原来的 direct_solve 兜底。
                    #   红线：证伪器只做证伪、不做证实；不确定一律放行（宁漏不误杀）。
                    _avail, _n_surv = self._falsify_candidates(ctx)
                    direct_answer = ""
                    if _avail and _n_surv > 0:
                        # 池中仍有未被证伪的候选 ⇒ **不采纳池外直答**，交 Formatter 从池中择优
                        self.record(ctx, "control",
                                    "零票兜底：证伪淘汰后仍剩 %d 个未被证伪候选 → "
                                    "改由候选池择优（不采纳 direct_solve 的池外答案）"
                                    % _n_surv)
                        ctx._zero_vote_fallback = False
                    else:
                        direct_answer = self.solver.direct_solve(ctx)
                        if (str(direct_answer or "").strip()
                                and self._falsify_rejects(ctx, direct_answer)):
                            self.record(ctx, "control",
                                        "零票兜底直答被客观证伪（数值回带 + SymPy 精确判定）"
                                        "→ 拒绝采纳，退回候选池择优")
                            direct_answer = ""
                        # 2026-09-18：过 `_set_final_response`（非答案闸门）
                        if not self._set_final_response(ctx, direct_answer,
                                                        "zero_vote_direct"):
                            if str(direct_answer or "").strip():
                                self.record(ctx, "control",
                                            "零票兜底直答被判为非答案（过程叙述/脏文本）"
                                            "→ 退回候选池择优")
                            self._set_final_response(
                                ctx, self._pick_best_from_candidates(ctx) or "",
                                "zero_vote_pick_best")
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
            # ★★ 2026-09-16 修复关键断点：此处**绝对不能用 `gen_time_up()`**。
            # 实测（0916 轮 111 题，standard 档）：
            #   · paper_pacer 把单题预算收紧到 540s；
            #   · verify_reserve=480s ⇒ `_gen_deadline` 只剩 **60s**；
            #   · `2.5_difficulty`(23.6s) + `2.7_subgoal_main`(47s) 就已耗尽 60s
            #     ⇒ 验证阶段开始时 `gen_time_up()` **早已恒为 True**。
            # 后果：**5.5 低置信度强制复核被永久禁用**——验证器把唯一候选投成
            #   0/2 票（+带推理复核判 B），却无人消费，错答直接提交。
            #   trace 实证：「全部 0 正确票，触发兜底直接求解」之后
            #   `5.5_low_conf` 阶段耗时 **9.5e-06 秒**（＝根本没执行），
            #   `revise_round=0`。
            # ⇒ 口径错配：`gen_time_up()` 是「**生成**侧软截止」，用于闸**生成**；
            #   而 5.5 是**验证之后的修正**，正是那 480s `verify_reserve` 要保护的时段。
            #   用生成时钟闸修正环节，等于把预留的验证时间作废。
            # 改判 `is_time_critical()`（真实剩余时间），与 4.5/4.6 之外的验证侧一致。
            if (_bc is not None
                    and getattr(_bc, 'confidence', 1.0) < 0.5
                    and not ctx.state.emergency
                    and not ctx.is_time_critical()):
                self.record(
                    ctx, "control",
                    f"deep 档低置信度({_bc.confidence:.2f})，强制 revise 复核提升共识",
                )
                self._deep_revise_loop(ctx, ver_result, tier_votes)

            self._stage_start(ctx, "6_format")
            # 6) 格式化输出
            self.formatter.run(ctx)

            self._stage_start(ctx, "6.5_audit_gate")
            # 2026-10-01：原 6.5 处「`calc_inconsistent`（计算冲突）优先于 Lean
            #   answer_valid」的裁决已随 `<calc>` 计算工具板块整体删除 —— 其唯一
            #   来源（`_maybe_answer_selfcheck` 里"有工具值却与答案不符"的判据）
            #   已移除 ⇒ 该分支随之消失（原 L4「判据在当前配置下不可达」已成历史）。
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
                    # 2026-10-01：比赛期上限（默认 3）已按研究期标尺放开 ⇒ 默认 -1 = 无上限
                    # （审计 A 级第 3 条）。原注释自述动机是「6.5 成为新的时间黑洞」
                    # 的省时考虑；研究期求正确率上限，不再以时间为由限制终审重做。
                    # `DEEP_MAX_REWORK=N`（N>=0）仍可显式设上限，便于 A/B。
                    try:
                        _deep_cap = int(os.environ.get("DEEP_MAX_REWORK", "-1"))
                    except (TypeError, ValueError):
                        _deep_cap = -1
                    # 2026-09-14：fast 档已删除 ⇒ 原 `tier in ("fast","standard")`
                    # 简化为 `tier == "standard"`。
                    _max_rework = (2 if tier == "standard"
                                   else (None if _deep_cap < 0 else _deep_cap))
                    best_reasoning = ""
                    for _c in (ctx.candidates or []):
                        if getattr(_c, "answer", "") == ctx.final_response:
                            best_reasoning = getattr(_c, "reasoning", "") or ""
                            break
                    g_ok = _gate.gate_final_answer(
                        ctx, tier, ctx.final_response, best_reasoning)
                    _tried = 0
                    _last_feedback = ""
                    # ★ 2026-09-21：记下"进入重做循环前"的答案，供未过审核时回滚。
                    #   候选按 confidence **降序**试探（下方 sorted(...reverse=True)），
                    #   循环因次数/时间耗尽而退出时 ctx.final_response 停在**最后换上**
                    #   的候选 = 置信度最低者；而"闸门没能确认更强" ≠ "确认更弱"。
                    _pre_rework_final = ctx.final_response
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
                                    # ★ 2026-09-17（M2）：`_gate_tried` 为空时**禁止清空**候选池。
                                    # 此时 `_pass_cands` 必为空，原代码把原有全部候选（含较优/
                                    # 正确者）删光，随后 revise 生成的 3 个成为唯一候选，且
                                    # **没有任何新旧对比**。`_gate_tried` 为空意味着"一个候选都还
                                    # 没试过"，清空属误删；保留原池，由 `_generate_revise` 自行腾位。
                                    if _pass_cands:
                                        ctx.candidates = _pass_cands[:3]  # 腾位
                                    else:
                                        self.record(ctx, "control",
                                                    "审核未试过任何候选 → 保留原候选池"
                                                    "（不清空，M2 2026-09-17）")
                                    ctx.revise_round = getattr(ctx, "revise_round", 0) + 1
                                    _before = len(ctx.candidates or [])
                                    self.solver.run(ctx)
                                    if len(ctx.candidates or []) > _before:
                                        _tried += 1
                                        _fresh = ctx.candidates[-1]
                                        # 2026-09-18：过闸门；脏答案不采纳、回 while 继续
                                        if not self._set_final_response(
                                                ctx, _fresh.answer, "gate_rework"):
                                            self.record(ctx, _gk,
                                                        f"重生成候选 #{_fresh.id} 的答案被判为"
                                                        "非答案（过程叙述/脏文本）→ 不采纳")
                                            continue
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
                        # 2026-09-18：过闸门；脏答案不采纳、继续换下一个候选
                        if not self._set_final_response(ctx, _next.answer, "gate_next"):
                            self.record(ctx, _gk,
                                        f"换候选 #{_next.id} 的答案被判为非答案"
                                        "（过程叙述/脏文本）→ 不采纳，继续换")
                            continue
                        g_ok = _gate.gate_final_answer(
                            ctx, tier, _next.answer,
                            getattr(_next, "reasoning", "") or "")
                        if g_ok:
                            self.record(ctx, _gk,
                                        f"换候选 #{_next.id} 过审核闸门，采用其答案")
                    if not g_ok:
                        ctx.gate_rejected = True
                        # ★ 2026-09-21 回滚：本重做循环把 ctx.final_response 一路往前
                        #   覆盖（gate_next / gate_rework），而候选按置信度降序试探
                        #   ⇒ 循环退出时终值 = 最后换上 = **置信度最低**者。
                        #   实测 0921 arm2c2t：000 `\boxed{1}`(conf 0.667) → `20`
                        #   (conf 0.000)；003 `\boxed{2026}` → `因此a_{2025} = 2026。`；
                        #   004 `\boxed{1012}` → 187 字过程叙述。Lean 全降级时闸门
                        #   对所有解答题恒拒 ⇒ 必然退到最弱候选。
                        #   未过审核 = 无可信证据支持替换 ⇒ 回到重做前的答案。
                        if (_pre_rework_final
                                and ctx.final_response != _pre_rework_final
                                and self._set_final_response(
                                    ctx, _pre_rework_final, "gate_rollback")):
                            try:
                                ctx._gate_rollback = True
                            except Exception:  # noqa: BLE001
                                pass
                            self.record(ctx, _gk,
                                        "候选尽数未过客观审核 → 回滚到重做前的答案"
                                        f"（{str(_pre_rework_final)[:60]}），"
                                        "不以置信度最低的候选收尾（2026-09-21）")
                        self.record(ctx, _gk,
                                    f"{tier} 档审核重做达上限仍拒（{_tried} 次换候选/重生成），"
                                    "当前答案标 rejected 放行")
                except Exception as _e:  # noqa: BLE001  闸门异常绝不阻断
                    self.record(ctx, _gk,
                                f"审核闸门异常，降级放行: {str(_e)[:120]}")

            # ★ 2026-10-02 hook 07：6.5 审核闸门后落盘（07_lean）—— Lean 门禁 / DAG 校验痕迹。
            _artifact_put(ctx, "07_lean", {
                "final_gate": getattr(ctx, "final_gate", None),
                "gate_rejected": getattr(ctx, "gate_rejected", None),
                "lean_dag_checked": getattr(ctx, "lean_dag_checked", None),
                "lean_dag_fails": getattr(ctx, "lean_dag_fails", None),
                "lean_reject_feedback": getattr(ctx, "lean_reject_feedback", None),
                "final_response_after_gate": getattr(ctx, "final_response", ""),
            })

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
            ctx.final_response = self._final_answer_postprocess(ctx)

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
        except Exception as e:  # noqa: BLE001
            logger.error("Orchestrator run failed: %s", e)
            return self._fallback(ctx, problem, e)

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
            # ★ 2026-09-17（泛化句）：返回**空串** = "复核未发现实质缺陷"。
            # 原返回一句泛化建议「解答已较完整，请重新审题核对计算细节后给出最终答案。」，
            # 它被当作 revise 反馈 ⇒ **信息量为零的盲目重解**（实测 099 的
            # `diag.revise_feedback[0]` 正是这句），白烧一轮"生成 + 验证"。
            # 改由调用方据此**结束 revise**，而不是拿它去空转。
            self.record(ctx, "review",
                        "复核判定无实质缺陷 → 不做盲目重解（2026-09-17）")
            return ""
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
        # ★ 2026-09-17（Audit-1）：全局轮数上限改由 `max_revise_rounds` 提供
        #（原先硬编码 5，而同名 config 字段全仓零读取点 ⇒ `--revise_rounds` 静默失效）。
        # 默认 5 与旧行为一致；`<=0` 表示不设全局上限（研究阶段可选）。
        _max_total = int(getattr(self.config, 'max_revise_rounds', 5) or 5)
        if _max_total > 0 and getattr(ctx, 'revise_round', 0) >= _max_total:
            self.record(ctx, "revise",
                        f"revise 已达全局上限 {_max_total} 轮（max_revise_rounds），不再继续")
            return False
        # ★ 2026-09-17（Z6）：**同一次「轮次 + 答案」不重复 revise**。
        # 实测 5) 段（全 0 票强制重解）与 5.5（低置信强制复核）会在**同一趟流程**里
        # 先后调用本函数；全 0 票时两处触发条件同时成立 ⇒ 同一批候选、同一答案被
        # revise 两遍，第二轮必然拿到同样的反馈、做同样的事。
        # 量级：`5_revise_or_fallback 1705s + 5.5_low_conf 1942s` 合计占全量 21.6%。
        # 去重键 = (revise_round, final_response)：相同即本趟已跑过，直接返回。
        # `force=True`（P1 应急重解）是调用方**显式要求**的，不参与去重。
        if not force:
            # ★ 2026-09-21 修复去重键：**去掉 revise_round** —— 它由本函数自身在
            #   下方 `ctx.revise_round += 1` 递增，拿它入键等于**自毁去重**：
            #   5) 段跑完 revise_round 变 1，5.5 段带着 1 再进来键就不同 ⇒ 必然
            #   重复整轮回环。实测 0921 arm2c2t 001：`5_revise_or_fallback` 668s
            #   + `5.5_low_conf` 655s = 1323s，占该题 41%（两段各跑一次完整回环）。
            #   去重语义本就是"本趟对**同一答案**不重复 revise"，答案相同即命中；
            #   轮次仅用于日志展示（下方 record 仍打印当前 round）。
            _pass_key = str(getattr(ctx, "final_response", "") or "")
            _seen = getattr(ctx, "_revise_pass_keys", None)
            if not isinstance(_seen, set):
                _seen = set()
                try:
                    ctx._revise_pass_keys = _seen
                except Exception:  # noqa: BLE001
                    _seen = None
            if _seen is not None:
                if _pass_key in _seen:
                    self.record(ctx, "revise",
                                "同一答案（round=%d）本趟已 revise 过 → 跳过重复回环"
                                "（Z6 去重键修复 2026-09-21）"
                                % int(getattr(ctx, "revise_round", 0) or 0))
                    return False
                _seen.add(_pass_key)
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
        _reviewed_empty = False
        if (not ctx.is_time_critical()
                and len(feedback) > 10):
            _rv = self._review_bug_feedback(ctx, feedback)
            if _rv:
                feedback = _rv
            else:
                _reviewed_empty = True
        # 注入各客观审核环节（3.6 AuditGate / 4.6 对抗 / 4.5 Oracle）淘汰反馈，
        # 驱动定向修正（audit_reject_feedback 为通用 revise 反馈通道）
        audit_fb = getattr(ctx, "audit_reject_feedback", None)
        if audit_fb:
            feedback = feedback + "\n" + "\n".join(audit_fb)
        # ★ 2026-09-17：复核判定"无实质缺陷"且无审核反馈 ⇒ **没有可修正的目标**，
        # 继续只会盲目重解（信息量为零，却要付一轮"生成 + 验证"）。直接结束回环。
        if _reviewed_empty and not audit_fb:
            self.record(ctx, "revise",
                        "复核无实质缺陷且无审核反馈 → 结束 revise"
                        "（避免零信息空转，2026-09-17）")
            return False
        for r in range(max_rounds):
            # 2026-09-06：升级 gen_time_up——revise 回环 = solver.run 生成 +
            # verifier 验证，单轮可烧 200-400s，须按生成侧软截止更早收手。
            # 2026-09-11：force=True 跳过该软截止 —— P1 硬信号"应急重解"专用。
            #   根因（10 题实测 002）：P1 外部条件（剩余 >150s）通过并调用了本函数，
            #   但此处 `gen_time_up()` 依据生成侧软截止（deadline − verify_reserve = 720s）
            #   在累计 814s 时必为 True → **第一轮就 break**，重解从未真正发生。
            #   应急重解只受硬墙约束，由调用方（P1）保证剩余时间充足。
            # ⚠ 2026-09-16 修复（与 5.5 闸门同一病灶）：`gen_time_up()` 是
            #   「**生成**侧软截止」（deadline − verify_reserve），而 revise 回环是
            #   **验证之后的修正**，正是 verify_reserve 要保护的时段 ⇒ 口径错配。
            #   预算偏紧时（如 standard 档 540s、verify_reserve 480s ⇒ _gen_deadline 仅 60s）
            #   它**恒为 True** ⇒ 回环**第一轮就 break**。
            #   ⚠ 实测澄清：在**当前无预算上限**配置下（max_time_per_question=86400）
            #   它不会触发（实测 revise_round 达 2 / 6），所以并非"永久禁用"；
            #   但一旦收紧预算就会复现 —— 故仍改为与 5.5 一致的 `is_time_critical()`。
            if ctx.is_time_critical() and not force:
                self.record(ctx, "revise", "revise 回环预算不足，提前终止")
                break
            # ★★ 2026-09-16 修复（把只写不读的字段接上）：调用方 P1 在
            #   "重解后答案未变化"时置位 `ctx._revise_no_progress_answer`
            #   （见 :1566，注释承诺"后续同源的 revise（4.6 对抗 / 5 全0票 /
            #   5.5 低置信）不再对**同一个答案**重复重解"），
            #   但**全仓没有任何读取点** ⇒ 该保护从未生效。
            #   实测代价（official112-003）：`deep 档 revise 自纠错 第1~6轮`
            #   连跑 6 轮、中间三次 `revise 回环 2 轮仍未获得正确票`，
            #   而 `P1 重解成效：答案未变化（0→0 字符）` ⇒
            #   **6 轮全部无效**，约占该题 4148s 墙钟的 22%。
            #   语义：仅对非 force 调用生效（force 是调用方明确要求的应急重解）；
            #   答案一旦变化，`_npa == _cur` 自然不成立 ⇒ 标记自动失效。
            if not force:
                _npa = getattr(ctx, "_revise_no_progress_answer", None)
                _cur_ans = str(getattr(ctx, "final_response", "") or "")
                if _npa is not None and _cur_ans and _npa == _cur_ans:
                    self.record(ctx, "revise",
                                "该答案此前重解后**未发生变化** → 跳过重复 revise"
                                "（无进展保护，:1566 置位）")
                    break
            ctx.revise_round += 1
            _ans_before = str(getattr(ctx, "final_response", "") or "")
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
            _ans_after = str(getattr(ctx, "final_response", "") or "")
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

    def _mathlib_adoption(self, ctx: TaskContext) -> dict:
        """统计「检索到的定理」里有多少**真的进了 Lean 代码**（引用即采用）。

        ★ 2026-09-23 新增，回答用户"mathlib 的定理是不是都和本题有关、哪些帮上了忙"：
          实测 `used_theorems` 的条数恒等于 `search_hits` 恒等于 `top_k`
          ⇒ **该字段实为"检索结果"，不是"实际使用"**（字段名误导）。
          本轮实测 460 条里只有 4 条（1%）出现在 Lean 代码中。

        ⚠ 因此"提高定理选择数（top_k）"是**错的解**：`top_k_capped` 已 100% 饱和，
          调大只会拿回更多同样不被使用的条目。缺的是"**检索 → 采用 → 编译验证**"闭环。

        本方法把"采用率"变成可度量字段，使该闭环的成效可被逐轮跟踪。
        """
        try:
            names = [str(x) for x in (getattr(ctx, "used_theorems", None) or [])]
            if not names:
                return {"retrieved": 0, "adopted": 0, "adoption_rate": 0.0}
            code = []
            for t in (getattr(ctx, "trace", None) or []):
                if not isinstance(t, dict):
                    continue
                if t.get("step") == "lean_gate" or t.get("step") == "subgoal_step":
                    code.append(str(t.get("content") or ""))
            blob = "\n".join(code)
            adopted = sum(1 for n in names if n.split(".")[-1] and n.split(".")[-1] in blob)
            return {"retrieved": len(names), "adopted": adopted,
                    "adoption_rate": round(100.0 * adopted / max(len(names), 1), 1)}
        except Exception:  # noqa: BLE001
            return {"retrieved": 0, "adopted": 0, "adoption_rate": 0.0}

    def _falsify_candidates(self, ctx: TaskContext) -> tuple:
        """对候选池逐个跑证伪器，把**已被证伪**的候选答案记进 `ctx._falsified_answers`。

        返回 (available, n_survivors)：
        - `available=False` ⇒ 证伪器未启用/不可用/时间不足 ⇒ 调用方**必须保持原行为**；
        - `available=True` ⇒ `n_survivors` 是未被证伪的候选数（可能为 0 = 全被证伪）。

        ★ 2026-09-23 新增，回答用户"为什么把正确的排除、投票是不是有问题"：
          实测两个主力闸门（`4_verify` 全 0 票 / `lean_gate` proof_invalid）在**正确题**上
          的误报率都是 56% ⇒ "排除正确的"是结构性噪声。用户判据是
          "**错误答案一定是能证明错误的**" ⇒ 与其让闸门投票淘汰（同源自评、无判别力），
          不如用**可机检的证伪**来淘汰：只有拿到 SymPy 确认的反例才剔除。
        """
        try:
            if not getattr(self.config, "enable_answer_falsifier", True):
                return False, 0
            cands = list(getattr(ctx, "candidates", None) or [])
            if not cands:
                return False, 0
            if ctx.is_time_critical():
                return False, 0
            from .answer_falsifier import AnswerFalsifier
            f = AnswerFalsifier(self.client, self.config)
            prob = getattr(ctx, "problem", "") or ""
            falsified = []
            for c in cands:
                if ctx.is_time_critical():
                    break
                res = f.falsify(ctx, c, problem=prob)
                if res.is_incorrect:
                    falsified.append({
                        "answer": str(getattr(c, "answer", ""))[:160],
                        "witness": (res.witness or "")[:200],
                        "oracle_type": res.oracle_type,
                    })
            if falsified:
                try:
                    ctx._falsified_answers = [x["answer"] for x in falsified]
                    meta = ctx.metadata if isinstance(ctx.metadata, dict) else {}
                    meta["falsified_answers"] = falsified
                    ctx.metadata = meta
                except Exception:  # noqa: BLE001
                    pass
                self.record(ctx, "falsify",
                            "候选证伪：%d/%d 个候选被客观证伪（SymPy 精确判定%s）"
                            % (len(falsified), len(cands),
                               "+Lean 背书" if any(x["oracle_type"] == "sympy+lean"
                                                  for x in falsified) else ""))
            return True, max(0, len(cands) - len(falsified))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[orchestrator] 候选证伪异常（忽略）: %s", str(exc)[:120])
            return False, 0

    def _falsify_rejects(self, ctx: TaskContext, answer: str) -> bool:
        """尝试**客观证伪**一个答案文本。返回 True 表示"已证伪、不得采纳"。

        与 `_oracle_review_best` 的分工：
        - `AnswerOracle` 只能做「多候选自洽共识」⇒ 判不出**绝对**对错；
        - 本方法只做**证伪**：数值回带（LLM 出闭式等式）→ SymPy 精确判定
          → Lean 背书（编译通过则推翻本次证伪）。

        设计红线（与 falsifier 一致，此处再兜一层）：
        - 任何异常 / 时间不足 / 证书缺失 / 判定不确定 ⇒ **返回 False（放行）**；
        - 绝不在此处判"正确"，也绝不用它替换答案（只做否决）。
        """
        try:
            if not getattr(self.config, "enable_answer_falsifier", True):
                return False
            if not str(answer or "").strip():
                return False
            if ctx.is_time_critical():
                return False
            from .answer_falsifier import AnswerFalsifier
            f = AnswerFalsifier(self.client, self.config)
            cand = type("_C", (), {"answer": str(answer), "reasoning": ""})()
            res = f.falsify(ctx, cand, problem=getattr(ctx, "problem", "") or "")
            if not res.is_incorrect:
                return False
            # 留痕：把证伪结论记进 diag / trace，供事后审计
            self.record(ctx, "falsify",
                        "证伪命中：%s | 反例：%s" % (
                            res.reason, (res.witness or "")[:160]))
            try:
                ctx.metadata.setdefault("falsify_hits", []).append(
                    {"answer": str(answer)[:120], "reason": res.reason,
                     "witness": (res.witness or "")[:200],
                     "checks": res.checks, "oracle_type": res.oracle_type})
            except Exception:  # noqa: BLE001
                pass
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[orchestrator] 证伪器异常（放行）: %s", str(exc)[:120])
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
        # ★ 2026-09-23 叠加「证伪」——补 oracle 的能力缺口。
        #   oracle 只有"多候选自洽共识"，没有 reference ⇒ **判不出绝对对错**
        #   （0923 效能审计：本环节召回仅 **3%**）。而证伪器能给出**可机检的反例**
        #   （数值回带 → SymPy 精确判定 → Lean 背书），正好补上"证明某个候选是错的"。
        #   被证伪 ⇒ 与 incorrect 同路：注入 revise 通道并触发一次定向修正。
        _bad_fb = result.feedback if (result.is_incorrect and result.feedback) else ""
        try:
            from .answer_falsifier import AnswerFalsifier
            _fr = AnswerFalsifier(self.client, self.config, ctx.budget).falsify(
                ctx, rep, problem=getattr(ctx, "problem", "") or "")
            if _fr.is_incorrect:
                self.record(ctx, "oracle_review",
                            "证伪器命中（%s）：%s" % (_fr.oracle_type, _fr.reason))
                _ffb = _fr.to_feedback()
                if _ffb:
                    _bad_fb = (_ffb + ("\n" + _bad_fb if _bad_fb else "")).strip()
        except Exception as _e:  # noqa: BLE001
            logger.warning("[orchestrator] 证伪器叠加异常（忽略）: %s", str(_e)[:120])
        if _bad_fb and not ctx.state.emergency:
            # 客观反馈注入 revise 通道（audit_reject_feedback 通用反馈通道）
            if not getattr(ctx, 'audit_reject_feedback', None):
                ctx.audit_reject_feedback = []
            ctx.audit_reject_feedback.append(_bad_fb)
            self.record(ctx, "oracle_review",
                        f"客观复核/证伪判错，触发定向修正: {_bad_fb[:120]}")
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
                # ★ 2026-09-16 修复（误导性诊断字段）：`correct` 此前**从不赋值**，
                #   恒为 dataclass 默认 False ⇒ 导出的 `diag.verdicts[i].correct`
                #   永远是 False，即使 `correct_votes=2, total_votes=3`（多数票判对）。
                #   实测 003 因此显示 `{'correct_votes':2,'total_votes':3,
                #   'correct':False,'confidence':0.667}` —— 与置信度自相矛盾，
                #   读诊断的人会误判"验证器把候选全判错了"。
                #   注意：字段注释标明 `correct` 是**单票**语义（verifier 内部用），
                #   聚合对象此前没有定义其含义 ⇒ 这里补上"多数票是否判对"，与
                #   `confidence` 保持一致口径。**已核验无任何代码读聚合的 `correct`**
                #   （读取点都在单票上），故属纯诊断修复、不改行为。
                correct=bool(total_votes and correct_votes * 2 > total_votes),
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

    def _maybe_final_select(self, ctx: TaskContext) -> "str | None":
        """★ 2026-10-02 阶段二-2：终答五层选择（返回答案串；未接管返回 None）。

        与 `formatter._maybe_final_select` **共用** `final_selector.run_cached`
        ⇒ 两条路径同一决策、同一缓存、同一份 LLM 成本。
        开关 OFF / 无候选 / 异常 ⇒ 返回 None ⇒ 调用方**回退既有择优**。
        """
        try:
            try:
                from .final_selector import run_cached
            except ImportError:
                from final_selector import run_cached
            res = run_cached(ctx, self.llm, self.record)
            try:
                ctx._final_select_diag = dict(res.get("diag") or {})
                ctx._final_select_diag["branch"] = res.get("branch")
            except Exception:  # noqa: BLE001
                pass
            ans = str(res.get("answer") or "").strip()
            if not ans or res.get("skipped"):
                return None
            return ans
        except Exception as exc:  # noqa: BLE001  五层失败一律回退既有逻辑
            logger.debug("[orchestrator] 终答五层选择异常（回退）: %s: %s",
                         type(exc).__name__, exc)
            return None

    def _pick_best_from_candidates(self, ctx: TaskContext) -> str:
        import re as _re
        # ★ 2026-10-02 阶段二-2：终答五层选择优先（开关 ON 时此处即返回，
        #   ⇒ 下方的 verdict 置信度 / `objective_majority_vote` 分支不执行）。
        _fs_ans = self._maybe_final_select(ctx)
        if _fs_ans is not None:
            return _fs_ans
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
            # ★ 2026-09-17（M5）：**票数优先于置信度**。`confidence = 正确票/总票`，
            # 单候选全对时 confidence=1.0 却只有 3 票；应先看"是否真的拿到正确票"。
            sorted_v = sorted(
                ctx.verdicts,
                key=lambda v: (int(getattr(v, "correct_votes", 0) or 0),
                               float(getattr(v, "confidence", 0.0) or 0.0)),
                reverse=True)
            for v in sorted_v:
                ans = getattr(v, "answer", "") or ""
                # ★ 2026-09-16 审计修复：去掉 `len(ans) > 3` 门槛（同 formatter.py:95-98
                #   的论证：单字符是合法完整答案；选择题多是 `A`/`AB`/`BCD`）。
                if ans.strip() and not _re.search(r"无法求解|无法解决|不能解决", ans):
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
        if (_sw_bool("objective_majority_vote")
                and getattr(ctx, "question_type", "") == "选择题"):
            _mv_count: dict = {}
            for _c in getattr(ctx, "candidates", None) or []:
                _a = (getattr(_c, "answer", "") or "").strip()
                # ★ 2026-09-16 审计修复：去掉 `len(_a) > 3`（否则 A/AB/BCD 类
                #   选择题答案进不了多数投票 ⇒ 该机制对目标题型失效）。
                if _a and not _re.search(
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
                if c.answer and c.answer.strip() and not _re.search(r"无法求解|无法解决|不能解决", c.answer):
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

    @staticmethod
    def _set_final_response(ctx: TaskContext, ans: str, reason: str = "") -> bool:
        """统一写入 `ctx.final_response`，**先过非答案闸门**（2026-09-18 补）。

        背景：`ctx.final_response` 原有 **6 个赋值点**，其中三个**完全没有校验**：
          · `direct_answer`（零票兜底直答）
          · `_fresh.answer`（6.5 重做循环读审核反馈重生成的候选）
          · `_next.answer`（6.5 换下一个候选）
        ⇒ 6.5 重做循环在 **formatter 之后**运行，可以把一个"过程叙述"覆盖成最终答案。
        实测 official112-020/032/025 的最终答案正是这样变成
        `搜索已知结论：…` / `继续找规律，目前 type B：2, 8, 10。` / `步骤11：搜索已知结论`
        （而 `pick_diag.picked` 记录的是另一个值 ⇒ 说明确实被后写覆盖）。

        这与 09-17 已修的"三条切片路径绕过剥壳"是**同一族问题**：
        同一语义有多个写入点，只修了一部分。⇒ 收敛为**单一入口**。

        返回 True = 已写入；False = 被闸门拦下（调用方应换候选或继续重做）。
        """
        a = str(ans or "").strip()
        if not a:
            return False          # 空答案一律拒绝（不覆盖已有值）
        try:
            from .formatter import _looks_like_non_answer as _na
            if _na(a):
                return False
        except Exception:  # noqa: BLE001  判据不可用则放行（不阻断主流程）
            pass
        # ★ 2026-10-02 阶段二-2（team-lead Q4）：终答**唯一出口** —— 池外直答
        #   （零票兜底 / 6.5 重做循环）也过五层：输入仅一个答案 ⇒ 五层**直接采用、
        #   不调 LLM**（保护项：兜底路径不变慢/不变不稳）。开关 OFF ⇒ `skipped`
        #   ⇒ 原样写入（完全回退）。保持 `@staticmethod`（测试按静态签名调用）。
        try:
            try:
                from .final_selector import adopt_single
            except ImportError:
                from final_selector import adopt_single
            _r = adopt_single(ctx, a, reason=str(reason or ""))
            if not _r.get("skipped"):
                _a2 = str(_r.get("answer") or "").strip()
                if _a2:
                    a = _a2
        except Exception:  # noqa: BLE001  五层任何异常都不得阻断写答案
            pass
        ctx.final_response = a
        return True

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
            # ★ 2026-09-23 新增：候选证伪器的命中记录（answer_falsifier）。
            #   必须导出 —— 否则"证伪器没生效"与"埋点缺失"无法区分
            #   （教训见 skill mathpilot-deepseek-error-audit §10.1）。
            "falsify_events": [str(t.get("content", ""))[:220]
                               for t in (getattr(ctx, "trace", None) or [])
                               if isinstance(t, dict)
                               and t.get("step") == "falsify"],
            # 被客观证伪的候选答案原文（供审计"证伪器到底剔除了什么"）
            "falsified_answers": [
                str(x.get("answer"))[:160] for x in
                ((ctx.metadata or {}).get("falsified_answers") or [])
            ] if isinstance(getattr(ctx, "metadata", None), dict) else [],
            # ★ 2026-09-23 新增：子目标「做成了没」的度量（用户判据：
            #   目标不是"跑通/有数据"，而是"有没有起到作用"）。
            #   0923 实测：279 个子目标里 88% 的 result < 120 字符（中位仅 30）、
            #   96% 没有 expected_output ⇒ 名义上"拆了"，实质上"没算"。
            #   该字段把"空壳率"逐题导出，使"阻断重做"有判据可依。
            "subgoal_delivery": {
                "n": len(getattr(ctx, "subgoal_trace", None) or []),
                "n_underdeliver_120": sum(
                    1 for s in (getattr(ctx, "subgoal_trace", None) or [])
                    if isinstance(s, dict) and len(str(s.get("result") or "")) < 120),
                "n_missing_expected_output": sum(
                    1 for s in (getattr(ctx, "subgoal_trace", None) or [])
                    if isinstance(s, dict)
                    and not str(s.get("expected_output") or "").strip()),
            },
            # ★ 2026-10-02（阶段二-1：「淘汰」→「保留」）：**每个子目标保留了几条候选、
            #   代表解是第几条**（-1 = 无有效候选）。数据源 = `subgoal_trace[i]["candidates"]`
            #   （阶段二-1 新增；下游消费方式零改动）。用途：验证"候选真的被保留下"，
            #   并支撑后续「最终答案层一次性对比判断」的归因。
            "subgoal_candidates": [
                {"id": s.get("id"),
                 "n_kept": len(s.get("candidates") or []),
                 "n_answers": len(s.get("candidate_answers") or []),
                 "picked_index": s.get("candidates_picked_index", -1),
                 # ★ 2026-10-02（阶段二-2）：子目标层**客观验证**选中的候选下标
                 #   （-1 = 客观验证判不出，沿用原代表解）。
                 "verified_index": s.get("candidates_verified_index", -1)}
                for s in (getattr(ctx, "subgoal_trace", None) or [])
                if isinstance(s, dict)
            ],
            # ★ 2026-10-02（阶段二-2）：终答五层选择观测（②多答案/③客观验证/
            #   ④模型对比/⑤投票 各自是否触发、命中分支、执行到的层顺序）。
            #   `exit` = 最终落地的写出口（single_adopt = 池外直答单答案快速采纳，
            #   Q4 纳入后"终答唯一出口"可归因）。
            "final_selection": {
                **dict(getattr(ctx, "_final_select_diag", {}) or {}),
                "exit": getattr(ctx, "_final_select_exit", "") or "",
            },
            # ★ 2026-10-02（阶段二-2）：**子目标层客观验证**汇总（team-lead Q1 要求）——
            #   阶段三 A/B 用它归因「客观验证到底有没有挑出对的那个」。
            "subgoal_verify_summary": {
                "n_with_multi_candidates": sum(
                    1 for s in (getattr(ctx, "subgoal_trace", None) or [])
                    if isinstance(s, dict) and len(s.get("candidates") or []) >= 2),
                "n_judged": sum(
                    1 for s in (getattr(ctx, "subgoal_trace", None) or [])
                    if isinstance(s, dict)
                    and s.get("candidates_verified_index", -1) >= 0),
                "n_undecided": sum(
                    1 for s in (getattr(ctx, "subgoal_trace", None) or [])
                    if isinstance(s, dict)
                    and len(s.get("candidates") or []) >= 2
                    and s.get("candidates_verified_index", -1) < 0),
            },
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
                          # ★ 2026-09-21（可观测性）：又是同一个坑 ——
                          #   `oracle_review`（4.5_oracle 的 AnswerOracle 复核结果，
                          #   orchestrator L2763-2774 共 3 处 record）与
                          #   `adversarial`（4.6_adv 的触发/跳过原因，L2694-2728 共 5 处）
                          #   都只写进 trace，而**不在本白名单** ⇒ jsonl/diag 里
                          #   一条都看不到。后果：无法从结果文件判定"4.5_oracle 跑了
                          #   几次、判了什么；4.6_adv 是跑了还是被窗口检查跳过"，
                          #   只能靠读日志猜（而日志里这两处恰好 0 条）。
                          #   ⇒ 补入白名单，导出 `oracle_review_events` /
                          #   `adversarial_events`。
                          "oracle_review", "adversarial",
                          # ★ 2026-09-30（截图 #8）：子目标多 agent 采样埋点。
                          #   不加这条 ⇒ 无法从结果文件区分「多 agent 没开启」
                          #   与「开启了但每次都无多数一致」—— A/B 归因失效。
                          "subgoal_multi_agent")},
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
            # ⚠ 2026-09-17：此处原先还有一条 `"audit_gate": [...][:6]`，与本文件
            #   下方（`_collect_diag` 的 ⑤ 段）**同名重复**。字典字面量里后键覆盖
            #   前键 ⇒ 那条"只留 dict、限 6 条"的实现**被静默丢弃**，一直是死代码。
            #   已删除，避免误读与 pyflakes `dictionary key repeated` 告警。
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
            # ★ 2026-09-18（可观测性）：**文本通道工具调用** —— 模型在正文/推理里
            #   手写 tool_call / function= / parameter= 这类**文本标记**，而平台未填
            #   原生 `tool_calls` ⇒ 调用**不执行、不回填**，答案退化为散文
            #   （实测 official112-025 的 5/5、032 的 4/4 候选）。
            #   该现象此前在 diag 中**完全不可见**（本键为新增）。
            "toolcall_text_detected": [
                str(t.get("content", ""))[:160]
                for t in (getattr(ctx, "trace", None) or [])
                if isinstance(t, dict)
                and t.get("step") == "toolcall_text_detected"][:20],
            # ⑦''' 工具循环审计（2026-10-01：原 calc 埋点随 `<calc>` 板块删除，
            # 改记 web_search 工具循环的模式与执行次数）
            "toolcall_mode": [str(t.get("content", ""))[:120]
                              for t in (getattr(ctx, "trace", None) or [])
                              if isinstance(t, dict)
                              and t.get("step") == "toolcall_mode"][:20],
            "toolcall_exec": [str(t.get("content", ""))[:120]
                              for t in (getattr(ctx, "trace", None) or [])
                              if isinstance(t, dict)
                              and t.get("step") == "toolcall_exec"][:20],
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
            # ★ 2026-09-21（可观测性）：6.5 审核闸门的**整题终态**标量。
            #   此前只有 `lean_gate` / `audit_gate` 里的逐条 `final_gate` 事件，
            #   没有"本题最终是否被拒 / 换过哪些候选 / 是否回滚"的汇总字段 ⇒
            #   事后要重建结论必须逐事件扫（0921 巡检即因此多绕了几步）。
            #   `gate_rollback` 与 0921 的回滚修复配对，用于 A/B 计数。
            "gate_rejected": bool(getattr(ctx, "gate_rejected", False)),
            "gate_tried": list(getattr(ctx, "_gate_tried", None) or []),
            "gate_rollback": bool(getattr(ctx, "_gate_rollback", False)),
            # 2026-09-13 P0：答案选取埋点（候选分布 + verdict 明细 + 命中分支）
            "pick_diag": getattr(ctx, "_pick_diag", None) or {},
            # B0：答案形态闸门事件（从 trace 中挑出，条数少，便于事后判定触发情况）
            "answer_form_events": [
                str(t.get("content")) for t in (getattr(ctx, "trace", None) or [])
                if isinstance(t, dict) and t.get("step") == "answer_form"
            ][:10],
            # ★ 2026-09-15（用户要求"把错误暴露得更具体"）：验证器判 B 时的
            # **结构化错误类型分布** {标签: 票数}，标签集 = verifier.ERROR_TYPE_TAGS
            # （符号错/计算错/边界遗漏/定义域错/跳步/循环论证/方法不适用/
            #  前提不成立/方向反了/漏分支/其它），回应李平老师"是否硬套定理"。
            # 口径优先取 `verify_error_types`（整题终态），无则回退
            # `vote_error_types`（单次投票）。两者都是纯埋点，不影响判定。
            "error_types": _merge_error_types(ctx),
            "n_reject_votes": _sum_reject_votes(ctx),
            # ★ 2026-09-15：LeanSearch 检索埋点（老师 #44）——本题的
            # 调用次数 / 命中数 / 去重后条数 / 耗时 / 后端 root。
            # `used_theorems`（run_eval 已导出）是命中定理名清单，两者互为交叉验证。
            "leansearch": _summarize_leansearch(ctx, self.config),
            # ★ 2026-09-29（截图 #3+#4）：领域→定理检索埋点。
            #   与上面的 `leansearch` 分开：后者是**验证期**的引理检索，
            #   本项是**理解期**的定理预取，两者用途不同、不该混算。
            #   含 query / 命中全名 / 耗时 / 后端 / （若注入标注）命中率。
            "theorem_hint": dict(getattr(ctx, "theorem_hint_trace", None) or {}),
            # ★ 2026-10-02（阶段一：子目标结论 → 主求解 信息流）：主求解是否
            #   真的用上了子目标结论 —— 注入的**条数 / 字符数**。
            #   口径：{count = 有非空 result 的子目标条数；chars = 注入块长度}。
            #   缺键 / count=0 ⇒ 未注入（无子目标结论 / 开关关闭）；便于 A/B 归因，
            #   使"主求解建立在子目标之上"这件事可被结果文件核验（而非靠日志猜）。
            "subgoal_findings_injected": dict(
                _md.get("subgoal_findings_injected", {}) or {}),
            # ★ 2026-09-29（截图 #6）：**逻辑缺口分析** —— 回答用户
            #   「缺的逻辑点是不是大模型需要推理出来的点」。
            #
            # 口径说明（重要，勿混算）：
            #   · `subgoal_gaps` 消费 `ctx.subgoal_trace`（自然语言求解视角）——
            #     每步子目标有没有产出有效结论，失败时按报错性质分五类；
            #   · 其中 `reasoning_gaps` 才是**真·推理瓶颈**（前提齐全却推不出）；
            #     `non_reasoning_gaps` 是形式化/检索/计算问题，**不该计入推理能力评估**。
            #   这个区分是本埋点的全部价值：不区分的话「大量子目标失败」会被
            #   笼统读成"推理能力差"，而实际可能大半是译题错误 —— 那会把优化
            #   方向引到完全错误的地方。
            "subgoal_gaps": _compute_subgoal_gaps(ctx),
            # ★ 2026-09-30（截图 #6 下半问）：**Lean 侧逻辑缺口** —— 回答
            #   「可不可以用 lean 来检测有没有 sorry 的地方」。
            #   与 `subgoal_gaps` 并列但**口径不同**，勿混算：
            #     · `subgoal_gaps`  ：自然语言求解有没有得出结论（软信号）；
            #     · `lean_gaps`     ：`by sorry` 声明能否编译（**硬信号**，
            #                        失败即"连要证什么都没说清"）。
            #   判读要点：`lean_gaps` 抓到的缺口绝大多数属 `formalization`
            #   （命题写得不成立），**不是模型该推出来的点**。若把它读成推理
            #   瓶颈，优化就会错到去调解题提示词。
            "lean_gaps": _compute_lean_gaps(ctx),
            # ★ 2026-09-30（截图 #10）：**统一工具调用遥测**。
            #   用户诉求「调用工具的方法有没有写成规范性的类函数，需要 Lean 检测时
            #   直接调用，适配各阶段」—— `agent/tool_gateway.py` 是那个统一入口，
            #   这里把它的调用统计落盘，使诊断报告的「工具使用」维度
            #   有**单一数据源**（此前只能靠遍历 trace 猜）。
            #   口径说明：
            #     · `total`      = 本门面被调用次数（**不等于**流水线全部工具调用，
            #                      因为只有走门面的调用才计数）；
            #     · `by_reason`  = **闭合原因码**分布，可直接聚合归因；
            #     · 关键区分：`unavailable`（环境没装）≠ `reject`（跑了判否）
            #                      ≠ `error`（调用炸了）—— 三者修法完全不同。
            #   ⚠ 若本字段为全零，**只说明"没有代码走门面"**，
            #     绝不可读成"本轮没调用工具"（既有调用点尚未迁移）。
            "tool_gateway": (_tool_gateway_summary(ctx)),
            # 2026-10-01 开关注册制：26 个开关的生效值快照（含来源 env/config/default）
            # ⇒「生效查不到」问题根治：任何一轮评测都能从 diag 还原开关状态。
            "switch_snapshot": _switch_snapshot(),
            # ★ 2026-09-21（可调参数实测记录）：把「配置上限 / 实际用了多少 / 有没有撞顶」放进同一张表，随 diag 落盘。
            #   用户诉求：「cleansearch 到底要找多少定理、检测打回要搞多少次、无条件重做多少次、子目标要设多少……我们要测出最合理的数据」（不止这几个）。
            #   明细与拓展方法见 agent/param_usage.py 的模块文档。
            "param_usage": collect_param_usage(ctx, self.config),
            # ★ 2026-09-15：带推理复核的判定（独立信号，不并入投票统计）。
            # 第一轮实测因缺此字段，无法判断复核"跑了没、判了什么"。
            "deep_review": _summarize_deep_review(ctx),
            # 穷尽性搜索机制：是否追加了「解族穷尽性检查」子目标
            "exhaust_diag": getattr(ctx, "_exhaust_diag", None) or {},
            # ★ 2026-09-17 新增：解析该子目标的输出，判断它**是否真的做了检查**。
            #   此前 result 是自由文本 ⇒ 无法区分"确认只有一解"与"没做检查"。
            #   `complete=False` 即可机检的"未完成检查"信号。
            "exhaust_result": _parse_exhaust_result(
                getattr(ctx, "subgoal_trace", None) or []),
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
            # ★ 2026-09-17（P1-F）：埋点三态自查 —— 未执行 / 执行无产出 / 有产出。
            # 解决「键存在但值为空 ⇒ 无法判断该环节跑没跑」的归因盲区。
            "diag_completeness": _diag_completeness(ctx),
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
