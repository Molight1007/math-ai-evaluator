# -*- coding: utf-8 -*-
"""可调上限「配置 vs 实测」记录（2026-09-21）。

诉求（用户原话）：
    「对于 leansearch 到底要找多少 mathlib 的定理，检测打回要搞多少次，
      无条件重做要搞多少次，子目标要设立多少，像这种数据你都要找到并记录
      （不止我说的这几个）我们要测试出最合理的数据。」

问题：这些数字此前散落在 trace 与各 `ctx` 计数器里，**没有统一口径**的
「配置上限 / 实际用了多少 / 有没有撞顶」三元组 ⇒ 调参只能凭直觉
（`max_subgoals=6` / `leansearch_top_k=5` / `lean_gate_unknown_stop=2`
这些值都是当初拍的，没有一条来自实测分布）。

本模块把「上限」与「实测」放进同一张表，随每题的 diag 一起落盘::

    diag["param_usage"] = {
        "schema": "param_usage/1",
        "tier": "deep",
        "items": {
            "leansearch_max_calls_per_q": {
                "cap": 2, "used": 2, "capped": True,
                "unit": "次", "src": "ctx._leansearch_calls",
                "note": "单题 LeanSearch 检索调用次数上限"},
            ...,
            "max_answer_tokens": {
                "cap": 65536, "used": None, "capped": None,
                "unit": "token", "src": "",
                "note": "token 口径不在 ctx 上；由 LLM 截断台账统计（见 utils.llm_client）"},
        },
        "counters": {"subgoals": 12, "leansearch_hits": 14, "distinct_theorems": 9, ...},
        "gaps": ["max_answer_tokens", ...],   # 有上限但当前无实测口径
        "approx": ["policy_sample_times", ...],  # 只有代理指标，判不了是否撞顶
    }

设计原则
    1. **只读**：不写 ctx、不改任何行为，纯派生快照。
    2. **不抛异常**：全程 try/except，任一项取不到就保留 cap、used=None。
       埋点把主流程搞挂的代价，远大于少一个数字。
    3. **`used=None` 的含义是「当前没有埋点，无法判断」，不是 0**。
       这些键会同时进 ``gaps``，即"想调它就得先补埋点"。
    4. **声明式**：新增一个可调上限 = 在 :data:`_SPEC` 里加一行。

⚠ 本模块**不 import 任何 agent 子模块**（只有 getattr 鸭子取数），
  以免引入循环导入；这也是它能被单测直接 import 的原因。
"""
from __future__ import annotations

SCHEMA = "param_usage/1"


# ======================================================================
# 取数工具
# ======================================================================
def _int(v):
    """宽松取整。取不到返回 ``None``（**不返回 0** —— 0 表示"确实用了 0 次"）。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _trace(ctx, step):
    """trace 中指定 step 的事件列表。"""
    return [t for t in (getattr(ctx, "trace", None) or [])
            if isinstance(t, dict) and t.get("step") == step]


def _gate_events(ctx):
    """合并 ``audit_gate`` / ``lean_gate`` 的闸门事件（两键通常只有一个非空）。"""
    out = []
    for key in ("audit_gate", "lean_gate"):
        for e in (getattr(ctx, key, None) or []):
            if isinstance(e, dict):
                out.append(e)
    return out


def _cfg_get(cfg, name, default=None):
    try:
        return getattr(cfg, name, default)
    except Exception:  # noqa: BLE001
        return default


def _cap(cfg, name, default=None):
    return _int(_cfg_get(cfg, name, default))


def _cap_by_tier(cfg, flat, table, tier):
    """档位字典优先 → 回退同名扁平值。

    与 ``sub_goal_solver`` 里 `_max_subgoals_for()` 的消费逻辑**刻意保持一致**
    （字典命中档位就用字典，否则用扁平值），否则埋点记的上限会与真正生效的
    上限不是同一个数，调参就白调了。
    """
    d = _cfg_get(cfg, table, None)
    if isinstance(d, dict) and tier and tier in d:
        v = _int(d.get(tier))
        if v is not None:
            return v
    return _cap(cfg, flat)


# ======================================================================
# 实测值（used）提取器 —— 每个都返回 (值, 取值来源字符串)
# ======================================================================
def _u_leansearch_calls(ctx):
    """① LeanSearch 实际调用次数（用户点名「到底要找多少定理」）。"""
    v = _int(getattr(ctx, "_leansearch_calls", None))
    if v is not None:
        return v, "ctx._leansearch_calls"
    # 回退：trace 里真正返回过 n_hits 的条目数（= 检索真的跑通的次数）
    n = sum(1 for t in _trace(ctx, "leansearch") if "n_hits" in t)
    return (n or None), "trace[step=leansearch 且含 n_hits]"


def _u_leansearch_topk(ctx):
    """② 单次检索实际拿到几条定理（对照 `leansearch_top_k`）。"""
    hits = [_int(t.get("n_hits")) for t in _trace(ctx, "leansearch")
            if "n_hits" in t]
    hits = [h for h in hits if h is not None]
    return (max(hits) if hits else None), "max(trace[step=leansearch].n_hits)"


def _u_subgoals(ctx):
    """③ 实际设立了几个子目标（对照 `max_subgoals(_by_tier)`）。"""
    st = getattr(ctx, "subgoal_stats", None)
    if isinstance(st, dict):
        v = _int(st.get("n_subgoals"))
        if v is not None:
            return v, "ctx.subgoal_stats.n_subgoals"
    tr = getattr(ctx, "subgoal_trace", None)
    if isinstance(tr, list) and tr:
        return len(tr), "len(ctx.subgoal_trace)"
    return None, ""


def _u_gate_tried(ctx):
    """④ 6.5 审核闸门实际试过几个候选（＝「检测打回」的次数口径）。

    `_gate_tried` 只记录"被换上重试过的候选 id"，**不含首个候选**，
    故它是打回次数的**下界**（首个候选被拒不计入）。这一点写进 note，
    避免报告把它当成精确值。
    """
    g = getattr(ctx, "_gate_tried", None)
    if isinstance(g, list) and g:
        return len(g), "len(ctx._gate_tried)（下界：不含首个候选）"
    n = sum(1 for e in _gate_events(ctx) if e.get("step") == "final_gate")
    return (n or None), "count(gate events step=final_gate)"


def _u_unknown_streak(ctx):
    """⑤ 闸门连续判 unknown 的最长连击（对照 `lean_gate_unknown_stop`）。

    该上限的语义是「**连续** N 个 unknown 后止损、剩余候选不再逐个整题 verify」
    ⇒ 真正的"撞顶"信号是**连续**长度，不是 unknown 总数。故这里算最长连击。
    """
    seq = []
    for e in _gate_events(ctx):
        if e.get("step") not in ("final_gate", "candidate_audit"):
            continue
        v = str(e.get("verdict", "") or "")
        if v:
            seq.append(v)
    if not seq:
        return None, ""
    best = cur = 0
    for v in seq:
        cur = cur + 1 if v == "unknown" else 0
        best = max(best, cur)
    return best, "max 连续 unknown in gate events"


def _u_revise_round(ctx):
    """⑥ 无条件重做（自纠错）实际跑了几轮（对照 `max_revise_rounds`）。

    `ctx.revise_round` 全仓只有 `orchestrator._deep_revise_loop` 一处自增
    （已 grep 确认）⇒ 它就是"深档 revise 轮次"的权威计数。
    """
    return _int(getattr(ctx, "revise_round", None)), "ctx.revise_round"


def _u_preverify_rounds(ctx):
    """⑦ 前置形式化验证实际修正了几轮（对照 `preverify_max_rounds`）。"""
    pt = getattr(ctx, "preverify_trace", None)
    if isinstance(pt, dict):
        for k in ("rounds", "n_rounds", "attempts", "revisions"):
            v = _int(pt.get(k))
            if v is not None:
                return v, "ctx.preverify_trace.%s" % k
    n = len(_trace(ctx, "preverify"))
    return (n or None), "count(trace step=preverify)"


def _u_skeleton_rounds(ctx):
    """⑧ 骨架评审实际跑了几轮（对照 `skeleton_review_max_rounds`）。"""
    sr = getattr(ctx, "skeleton_review_report", None)
    if isinstance(sr, dict):
        for k in ("rounds", "n_rounds", "replan_rounds", "attempts"):
            v = _int(sr.get(k))
            if v is not None:
                return v, "ctx.skeleton_review_report.%s" % k
    return None, ""


def _u_total_calls(ctx):
    """⑨ 本题 LLM 调用总次数（对照 `max_total_calls`；该上限**只记账不阻断**）。"""
    b = getattr(ctx, "budget", None)
    v = _int(getattr(b, "used_calls", None))
    return v, "ctx.budget.used_calls"


def _u_candidates(ctx):
    """⑩ 实际产出的候选数（对照 `policy_sample_times` / `tier_sample_times`）。"""
    cs = getattr(ctx, "candidates", None)
    if isinstance(cs, list) and cs:
        return len(cs), "len(ctx.candidates)"
    return _int(getattr(ctx, "n_candidates", None)), "ctx.n_candidates"


def _u_verdicts(ctx):
    """⑪ 实际投票次数（对照 `verifier_voting_times` / `tier_voting_times`）。"""
    vs = getattr(ctx, "verdicts", None)
    if isinstance(vs, list) and vs:
        return len(vs), "len(ctx.verdicts)"
    return None, ""


def _u_deep_review(ctx):
    """⑫ 带推理深复核实际跑了几次（对照 `verifier_deep_final` 链路）。"""
    n = len(_trace(ctx, "deep_review"))
    return (n or None), "count(trace step=deep_review)"


# ======================================================================
# 规范表：一个可调上限 = 一行
#   (键名, cap 取值器, used 取值器, 单位, 说明, exact)
#
# ★ `exact` 决定 `capped` 能不能算：
#     True  = used 与 cap **是同一个量**（如「实际检索次数」对「检索次数上限」）
#             ⇒ 可以判是否撞顶。
#     False = 只是**近似/代理**指标（如拿「实际候选数」当「采样次数上限」的代理）
#             ⇒ `capped` 恒 None，并进 `approx` 清单。宁可标"判不了"，也绝不
#               让一个单位不符的数字冒充"撞顶了"——那会把调参带到错方向。
# ======================================================================
_SPEC = (
    # ==== 2026-10-01 开关注册制（审查 A 级第 2 条）======================
    # 以下 29 项来自 `agent/switch_registry.py::SWITCHES`。
    # 它们不是「用量上限（cap）」而是**开关当前取值**，故 used/capped 记 None，
    # 目的是让「启动统计」能把这些开关的生效值记录下来（注册制第③件）。
    # `src` 用 getattr 直读 AgentConfig —— 注意 env 优先级在 registry 内部处理，
    # 本表只反映配置字段值，故 note 里标注了对应的环境变量名。
    # ================================================================
    ("artifact_store_enabled",
     lambda cfg, tier, _f="artifact_store_enabled", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "ARTIFACT_STORE_ENABLED — 中间结果落盘（results/<run_id>/<qid>/，默认开）", None),
    ("answer_form_gate",
     lambda cfg, tier, _f="answer_form_gate", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "ANSWER_FORM_GATE — 答案形态闸门（非答案形态不放行）", None),
    ("deterministic_timeout_sec",
     lambda cfg, tier, _f="deterministic_timeout_sec", _d=5.0: getattr(cfg, _f, _d),
     None, "数",
     "DETERMINISTIC_TIMEOUT_SEC — 确定性验证通道的单次超时（秒）", None),
    ("enable_subgoal_findings",
     lambda cfg, tier, _f="enable_subgoal_findings", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "ENABLE_SUBGOAL_FINDINGS — 主求解注入子目标结论（阶段一信息流，默认开）", None),
    ("enable_final_answer_selection",
     lambda cfg, tier, _f="enable_final_answer_selection", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "ENABLE_FINAL_ANSWER_SELECTION — 终答五层选择（阶段二-2，默认开；=0 回退改动前）", None),
    ("eval_alpha_equiv",
     lambda cfg, tier, _f="eval_alpha_equiv", _d=False: getattr(cfg, _f, _d),
     None, "bool",
     "EVAL_ALPHA_EQUIV — 字母等价（A/a）判定（默认关）", None),
    ("eval_split_cn",
     lambda cfg, tier, _f="eval_split_cn", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "EVAL_SPLIT_CN — 中文答案分隔符切分", None),
    ("expr_eval_grounding_guard",
     lambda cfg, tier, _f="expr_eval_grounding_guard", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "EXPR_EVAL_GROUNDING_GUARD — 表达式求值接地护栏", None),
    ("lean_gate_parallel",
     lambda cfg, tier, _f="lean_gate_parallel", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "LEAN_GATE_PARALLEL — Lean 门禁并行预取（=0 串行）", None),
    ("lean_gate_strict_unknown",
     lambda cfg, tier, _f="lean_gate_strict_unknown", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "LEAN_GATE_STRICT_UNKNOWN — Lean 门禁对 unknown 从严", None),
    ("lean_mcp_autolake",
     lambda cfg, tier, _f="lean_mcp_autolake", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "LEAN_MCP_AUTOLAKE — MCP 自动 lake 环境准备", None),
    ("lean_mcp_goal_loc",
     lambda cfg, tier, _f="lean_mcp_goal_loc", _d=False: getattr(cfg, _f, _d),
     None, "bool",
     "LEAN_MCP_GOAL_LOC — MCP 回报 goal 位置（默认关）", None),
    ("lean_mcp_hover_check",
     lambda cfg, tier, _f="lean_mcp_hover_check", _d=False: getattr(cfg, _f, _d),
     None, "bool",
     "LEAN_MCP_HOVER_CHECK — MCP hover 检查（默认关）", None),
    ("lean_mcp_multi_attempt",
     lambda cfg, tier, _f="lean_mcp_multi_attempt", _d=False: getattr(cfg, _f, _d),
     None, "bool",
     "LEAN_MCP_MULTI_ATTEMPT — MCP 多次尝试（默认关）", None),
    ("lean_mcp_timeout_floor",
     lambda cfg, tier, _f="lean_mcp_timeout_floor", _d=300.0: getattr(cfg, _f, _d),
     None, "数",
     "LEAN_MCP_TIMEOUT_FLOOR — MCP 调用超时下限（秒）", None),
    ("lean_mcp_verify_axioms",
     lambda cfg, tier, _f="lean_mcp_verify_axioms", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "LEAN_MCP_VERIFY_AXIOMS — MCP 校验公理使用", None),
    ("lean_verify",
     lambda cfg, tier, _f="lean_verify", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "LEAN_VERIFY — Lean 通道总开关（=0 一键关闭）", None),
    ("lean_xcheck_numeric",
     lambda cfg, tier, _f="lean_xcheck_numeric", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "LEAN_XCHECK_NUMERIC — 数值答案的 Lean 交叉校验", None),
    ("llm_retry_on_timeout",
     lambda cfg, tier, _f="llm_retry_on_timeout", _d=False: getattr(cfg, _f, _d),
     None, "bool",
     "LLM_RETRY_ON_TIMEOUT — LLM 超时是否重试（默认不重试）", None),
    ("minimal_mode",
     lambda cfg, tier, _f="minimal_mode", _d=False: getattr(cfg, _f, _d),
     None, "bool",
     "MINIMAL_MODE — 最小基础模式（只留主链，默认关）", None),
    ("mp_arm",
     lambda cfg, tier, _f="mp_arm", _d='baseline': getattr(cfg, _f, _d),
     None, "str",
     "MP_ARM — 实验臂名称（deploy 用）", None),
    ("numericize_final",
     lambda cfg, tier, _f="numericize_final", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "NUMERICIZE_FINAL — 终答数值化（把精确式转小数）", None),
    ("objective_itemwise_priority",
     lambda cfg, tier, _f="objective_itemwise_priority", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "OBJECTIVE_ITEMWISE_PRIORITY — 客观题逐项优先策略", None),
    ("objective_majority_vote",
     lambda cfg, tier, _f="objective_majority_vote", _d=False: getattr(cfg, _f, _d),
     None, "bool",
     "OBJECTIVE_MAJORITY_VOTE — 客观题多数投票（默认关）", None),
    ("objective_selfcheck",
     lambda cfg, tier, _f="objective_selfcheck", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "OBJECTIVE_SELFCHECK — 客观题自查", None),
    ("self_improve_keep_original",
     lambda cfg, tier, _f="self_improve_keep_original", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "SELF_IMPROVE_KEEP_ORIGINAL — 自改进保留原答案", None),
    ("self_improve_objective_skip",
     lambda cfg, tier, _f="self_improve_objective_skip", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "SELF_IMPROVE_OBJECTIVE_SKIP — 客观题跳过无条件自改进（=0 则也跑）", None),
    ("theorem_hint",
     lambda cfg, tier, _f="theorem_hint", _d=True: getattr(cfg, _f, _d),
     None, "bool",
     "THEOREM_HINT — 定理检索注入（=0 关闭）", None),
    ("toolcall_text_fallback",
     lambda cfg, tier, _f="toolcall_text_fallback", _d=False: getattr(cfg, _f, _d),
     None, "bool",
     "TOOLCALL_TEXT_FALLBACK — 文本工具调用兜底（直接改主链生成行为，默认关）", None),

    # ---- ① LeanSearch（用户点名）--------------------------------------
    ("leansearch_max_calls_per_q",
     lambda cfg, tier: _cap(cfg, "leansearch_max_calls_per_q"),
     _u_leansearch_calls, "次",
     "单题 LeanSearch 检索调用次数上限", True),
    ("leansearch_top_k",
     lambda cfg, tier: _cap(cfg, "leansearch_top_k"),
     _u_leansearch_topk, "条",
     "单次检索返回定理条数上限（对照『到底要找多少 Mathlib 定理』）", True),

    # ---- ② 检测打回（用户点名）----------------------------------------
    ("lean_gate_unknown_stop",
     lambda cfg, tier: _cap(cfg, "lean_gate_unknown_stop"),
     _u_unknown_streak, "连击",
     "闸门连续 unknown 达 N 次即止损（0=关闭）。capped=True 表示止损真触发", True),
    ("gate_max_rework",
     lambda cfg, tier: (2 if tier == "standard" else 3),
     _u_gate_tried, "次",
     "6.5 审核重做的候选数上限：standard=2 / deep=3（DEEP_MAX_REWORK 覆盖 deep）", True),

    # ---- ③ 无条件重做（用户点名）--------------------------------------
    ("max_revise_rounds",
     lambda cfg, tier: _cap(cfg, "max_revise_rounds"),
     _u_revise_round, "轮",
     "自纠错（revise）总轮数上限", True),
    ("deep_revise_rounds",
     lambda cfg, tier: _cap(cfg, "deep_revise_rounds"),
     _u_revise_round, "轮",
     "deep 档单次 0 票时的 revise 轮数上限（与上者同源计数 ctx.revise_round）", True),

    # ---- ④ 子目标（用户点名）------------------------------------------
    ("max_subgoals",
     lambda cfg, tier: _cap_by_tier(cfg, "max_subgoals",
                                   "max_subgoals_by_tier", tier),
     _u_subgoals, "个",
     "子目标个数上限（档位字典 max_subgoals_by_tier 优先，与代码消费逻辑一致）", True),

    # ---- ⑤ 其它可调上限（用户说的「不止这几个」）------------------------
    ("preverify_max_rounds",
     lambda cfg, tier: _cap(cfg, "preverify_max_rounds"),
     _u_preverify_rounds, "轮",
     "Lean 前置形式化验证的修正轮数上限", True),
    ("skeleton_review_max_rounds",
     lambda cfg, tier: _cap(cfg, "skeleton_review_max_rounds"),
     _u_skeleton_rounds, "轮",
     "骨架评审重规划轮数上限（arm2 已开 enable_skeleton_review）", True),
    ("max_total_calls",
     lambda cfg, tier: _cap(cfg, "max_total_calls"),
     _u_total_calls, "次",
     "LLM 调用记账上限（⚠ 只记账不阻断，见 agent/base.py:327）", True),

    # ---- ⑥ 只有代理指标、判不了撞顶的（标"近似"，不冒充撞顶）------------
    ("collab_max_rounds",
     lambda cfg, tier: _cap(cfg, "collab_max_rounds"),
     _u_deep_review, "轮",
     "deep 档三 Agent 协作循环上限（无专有计数，代理=deep_review 事件数）", False),
    ("self_improve_max",
     lambda cfg, tier: _cap(cfg, "self_improve_max"),
     _u_candidates, "个",
     "3.3 自改进候选数上限（代理=实际候选数，二者非同一量）", False),
    ("policy_sample_times",
     lambda cfg, tier: _cap(cfg, "policy_sample_times"),
     _u_candidates, "个",
     "策略采样候选数上限（代理=实际候选数，二者非同一量）", False),
    ("verifier_voting_times",
     lambda cfg, tier: _cap(cfg, "verifier_voting_times"),
     _u_verdicts, "次",
     "验证器投票次数上限（代理=len(ctx.verdicts)，含加赛票，非同一量）", False),
    ("verifier_disagreement_votes",
     lambda cfg, tier: _cap(cfg, "verifier_disagreement_votes"),
     _u_verdicts, "次",
     "分歧时追加投票次数（代理=len(ctx.verdicts)，非同一量）", False),

    # ---- ⑦ token 类上限（实测口径不在 ctx 上）--------------------------
    ("max_answer_tokens",
     lambda cfg, tier: _cap(cfg, "max_answer_tokens"),
     lambda ctx: (None, ""), "token",
     "答案生成上限；实测见 LLM 截断台账（utils.llm_client._TRUNCATION_STATS）", False),
    ("verifier_deep_review_max_tokens",
     lambda cfg, tier: _cap(cfg, "verifier_deep_review_max_tokens"),
     lambda ctx: (None, ""), "token",
     "深复核 token 上限；实测见 LLM 截断台账", False),
    ("adversarial_max_tokens",
     lambda cfg, tier: _cap(cfg, "adversarial_max_tokens"),
     lambda ctx: (None, ""), "token",
     "对抗验证 token 上限；实测见 LLM 截断台账", False),
    ("max_subgoals_by_tier",
     lambda cfg, tier: (None if not isinstance(
         _cfg_get(cfg, "max_subgoals_by_tier"), dict)
         else len(_cfg_get(cfg, "max_subgoals_by_tier"))),
     lambda ctx: (None, ""), "档位",
     "档位化上限表（本身不是数值上限，仅登记其存在与档位数）", False),
)


# ======================================================================
# 对外入口
# ======================================================================
def _counters(ctx) -> dict:
    """一题一次的关键计数快照（与上限无关，但报告里必须一起看）。"""
    mus = getattr(ctx, "mathlib_usage_stats", None)
    mus = mus if isinstance(mus, dict) else {}
    used_th = getattr(ctx, "used_theorems", None)
    return {
        "tier": str(getattr(ctx, "tier", "") or ""),
        "leansearch_search_calls": _int(mus.get("search_calls")),
        "leansearch_hits_raw": _int(mus.get("search_hits")),
        "distinct_theorems": (len(used_th)
                              if isinstance(used_th, list) and used_th else None),
        "lean_compile_valid": _int(mus.get("compile_valid")),
        "n_candidates": _int(getattr(ctx, "n_candidates", None)),
        "n_verdicts": _int(getattr(ctx, "n_verdicts", None)),
        "revise_round": _int(getattr(ctx, "revise_round", None)),
    }


_EMPTY = {"schema": SCHEMA, "tier": "", "items": {}, "counters": {},
          "gaps": [], "approx": []}


def collect_param_usage(ctx, cfg) -> dict:
    """采集本题「上限 vs 实测」表。**任何异常都被吞掉**，最坏返回空表。"""
    try:
        return _collect_inner(ctx, cfg)
    except Exception:  # noqa: BLE001
        return dict(_EMPTY)


def _collect_inner(ctx, cfg) -> dict:
    try:
        tier = str(getattr(ctx, "tier", "") or "")
    except Exception:  # noqa: BLE001
        # ⚠ 取不到 tier 不该放弃整张表：上限（来自 cfg）与其它实测都还在。
        #   0921 单测正是靠这条发现"提前 return 空表"会把有用信息一起丢掉。
        tier = ""
    try:
        counters = _counters(ctx)
    except Exception:  # noqa: BLE001
        counters = {}

    items: dict = {}
    gaps: list = []
    approx: list = []
    for name, cap_fn, used_fn, unit, note, exact in _SPEC:
        entry = {"cap": None, "used": None, "capped": None, "exact": bool(exact),
                 "unit": unit, "src": "", "note": note}
        try:
            cap = cap_fn(cfg, tier)
        except Exception:  # noqa: BLE001
            cap = None
        try:
            used, src = used_fn(ctx)
        except Exception:  # noqa: BLE001
            used, src = None, ""
        entry["cap"] = cap
        entry["used"] = used
        entry["src"] = src
        # capped：仅在「口径精确 + 有上限 + 有实测」时才判
        if cap is not None and used is not None and exact:
            if cap <= 0:
                # 多个上限用 0 表示"关闭该限制"（如 lean_gate_unknown_stop）
                entry["capped"] = None
                entry["note"] = note + "（cap=0 表示该限制已关闭）"
            else:
                entry["capped"] = bool(used >= cap)
        if used is None:
            gaps.append(name)
        if not exact:
            approx.append(name)
        items[name] = entry

    return {"schema": SCHEMA, "tier": tier, "items": items,
            "counters": counters,
            "gaps": sorted(gaps), "approx": sorted(approx)}


def aggregate(records) -> dict:
    """把多题的 `diag.param_usage` 汇总成「实测 vs 上限」对照。

    ``records`` = 可迭代的 ``param_usage`` 字典（各题）。
    返回::

        {"n_questions": N,
         "items": {name: {"cap": 上限众数, "cap_min", "cap_max", "n_used",
                          "used_mean", "used_max", "n_capped", "capped_rate"}},
         "counters": {key: {"mean","max","n"}}}

    只做纯算术，不做判断 —— 判断（该不该调）留给报告层，方便复算。
    """
    from collections import Counter

    rows = [r for r in (records or []) if isinstance(r, dict)]
    caps: dict = {}
    useds: dict = {}
    capped_cnt: dict = {}
    exact_seen: dict = {}
    ctr: dict = {}
    n = 0
    for r in rows:
        items = r.get("items")
        if not isinstance(items, dict):
            continue
        n += 1
        for name, e in items.items():
            if not isinstance(e, dict):
                continue
            if e.get("cap") is not None:
                caps.setdefault(name, []).append(e["cap"])
            if e.get("used") is not None:
                useds.setdefault(name, []).append(e["used"])
            if e.get("capped") is True:
                capped_cnt[name] = capped_cnt.get(name, 0) + 1
            # ★ exact 必须跟着聚合走：否则报告层会把代理口径当成可判撞顶，
            #   而 aggregate() 是报告/测试共用的入口，丢了它两处都会误判。
            if e.get("exact") is True:
                exact_seen[name] = exact_seen.get(name, 0) + 1
        c = r.get("counters")
        if isinstance(c, dict):
            for k, v in c.items():
                if isinstance(v, int):
                    ctr.setdefault(k, []).append(v)

    def _stat(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        if not vals:
            return None
        return {"n": len(vals), "mean": round(sum(vals) / len(vals), 2),
                "max": max(vals), "min": min(vals)}

    out_items = {}
    for name in sorted(set(caps) | set(useds) | set(capped_cnt) | set(exact_seen)):
        cap_vals = caps.get(name) or []
        mode = None
        if cap_vals:
            mode = Counter(cap_vals).most_common(1)[0][0]
        out_items[name] = {
            "cap": mode,
            "exact": bool(exact_seen.get(name)),
            "cap_min": min(cap_vals) if cap_vals else None,
            "cap_max": max(cap_vals) if cap_vals else None,
            "cap_values": sorted(set(cap_vals))[:6],
            "used": _stat(useds.get(name) or []),
            "n_capped": capped_cnt.get(name, 0),
            "capped_rate": (round(capped_cnt.get(name, 0) / n, 3) if n else None),
        }
    return {"n_questions": n, "items": out_items,
            "counters": {k: _stat(v) for k, v in sorted(ctr.items())}}
