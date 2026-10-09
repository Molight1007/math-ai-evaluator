# -*- coding: utf-8 -*-
"""`cli/deepseek_error_analyst.py` 的**证据包构建与收缩层**（2026-10-09 拆分 批6-2）。

逐字搬出：
  · 有效性三态判据 —— `classify_validity` / `detect_invalid` / `PLACEHOLDERS`；
  · 证据包组装 —— `build_evidence` 及其截断/计数小工具（`_cut` / `_count` /
    `_capped` / `_as_list` / `_as_dict`）；
  · 分析师模式推理摘录 —— `_reasoning_excerpt` / `_subgoal_excerpt`；
  · 证据包按预算分级收缩 —— `render_evidence` / `_EV_KEEP` / `_ev_size` /
    `_trim_to_budget` / `_ev_levels` / `fit_evidence`。

依赖方向：本模块**不反向导入** `cli.deepseek_error_analyst` ⇒ 无包级环。
其中 `PLACEHOLDERS` / `_as_dict` / `_as_list` / `classify_validity` 由
`cli.deepseek_error_analyst` 原样 re-export（被 `cli/test_report*.py` 依赖）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


PLACEHOLDERS = (
    "未给出有效解答。",
    "未给出有效解答",
    "empty response",
    "",
    "None",
)


def _cut(s: Any, n: int) -> str:
    t = "" if s is None else str(s)
    t = t.replace("\n", " ⏎ ")
    return t if len(t) <= n else t[:n] + " …[截断]"


# ================================================================
# 有效性闸门
# ================================================================
def classify_validity(rec: Dict[str, Any]) -> tuple:
    """三态判定数据质量：(level, reason)。

    level ∈ {"clean", "degraded", "invalid", "unknown"}。
    判据取自 2026-09-22 配额耗尽事件的实测分布：LLM 失败步数 / trace 总步数。
    实测：000 = 0/176、001 = 0/118、002 = 7/168（4.2%）、003 = 52/176（29.5%）。
    —— 只看日志首现时刻会把 002/003 误判为「健康」，故必须逐题按比例判。

    阈值（2026-09-22 晚修订）：
      · 噪声线 2%：偶发单步失败（如 1/108 ≈ 0.9%）属瞬时限流，重试即成，不算退化。
        实测 cloud112_0920d 的 32 道错题：21 道 0%，11 道 0–1.1%，无一超过 2%
        ⇒ 不设噪声线会让「退化」标记几乎恒亮，失去信息量。
      · 无效线 50%。
      · 无 trace ⇒ "unknown"：**不可判为 clean**。0910/0908 等老记录整轮无 trace，
        若按 0 步失败记为 clean 就是假阴性（无法证明健康 ≠ 健康）。
    """
    pred = str(rec.get("predicted") or "").strip()
    trace = _as_list(rec.get("trace"))
    n_step = len(trace)
    n_err = sum(1 for t in trace if isinstance(t, dict) and t.get("step") == "llm_error")
    ratio = (n_err / n_step) if n_step else 0.0
    if pred in PLACEHOLDERS:
        return "invalid", "占位符答案（未产出真实解答）"
    if n_step == 0:
        return "unknown", "无 trace，无法判定 LLM 健康度（不得据此视为干净）"
    if ratio >= 0.5:
        return "invalid", ("LLM 调用失败步占 %.0f%%（%d/%d），数据被配额/限流主导"
                           % (100 * ratio, n_err, n_step))
    if ratio >= 0.02:
        return "degraded", ("存在 %d 步 LLM 调用失败（占 %.0f%%），结论需打折看待"
                            % (n_err, 100 * ratio))
    return "clean", None


def detect_invalid(rec: Dict[str, Any]) -> Optional[str]:
    """兼容旧调用点：仅当 level == invalid 时返回原因，否则 None。"""
    level, reason = classify_validity(rec)
    return reason if level == "invalid" else None


# ================================================================
# 证据包
# ================================================================
def build_evidence(rec: Dict[str, Any], core: Optional[Dict[str, Any]],
                   source: str, mode: str = "checker") -> Dict[str, Any]:
    d = rec.get("diag") or {}
    st = d.get("stage_timers"); st = st if isinstance(st, dict) else {}
    tot = sum(v for v in st.values() if isinstance(v, (int, float))) or 1.0

    # 阶段耗时（top 8）
    stages = [
        {"stage": k, "sec": round(v, 1), "pct": round(100.0 * v / tot, 1)}
        for k, v in sorted(st.items(), key=lambda x: -(x[1] or 0))
        if isinstance(v, (int, float)) and v > 0.5
    ][:8]

    # lean_gate 摘要
    lg = _as_list(d.get("lean_gate"))
    lg_counts: Dict[str, int] = {}
    for e in lg:
        if isinstance(e, dict):
            lg_counts[str(e.get("verdict"))] = lg_counts.get(str(e.get("verdict")), 0) + 1
    lg_head = [
        {
            "verdict": e.get("verdict"),
            "reason": e.get("verdict_reason"),
            "compiled": e.get("compiled"),
            "cross_check": e.get("cross_check"),
            "code": _cut(e.get("lean_code"), 180),
        }
        for e in lg[:6] if isinstance(e, dict)
    ]

    # audit_gate 摘要
    ag = _as_list(d.get("audit_gate"))
    ag_counts: Dict[str, int] = {}
    for e in ag:
        if isinstance(e, dict):
            ag_counts[str(e.get("verdict"))] = ag_counts.get(str(e.get("verdict")), 0) + 1

    # 候选池
    cands = []
    for c in _as_list(rec.get("candidates"))[:8]:
        if isinstance(c, dict):
            cands.append({"id": c.get("id"), "answer": _cut(c.get("answer"), 220),
                          "reasoning_len": len(str(c.get("reasoning") or ""))})
        else:
            cands.append({"raw": _cut(c, 220)})

    # pick_diag
    pd = d.get("pick_diag"); pd = pd if isinstance(pd, dict) else {}
    clusters = [
        {"answer": _cut(c.get("answer"), 120), "size": c.get("size"),
         "confidence": c.get("confidence"),
         "votes": "%s/%s" % (c.get("correct_votes"), c.get("total_votes"))}
        for c in _as_list(pd.get("divergent_clusters"))[:5] if isinstance(c, dict)
    ]

    tc = rec.get("tool_calls"); tc = tc if isinstance(tc, dict) else {}
    llm = rec.get("llm_calls"); llm = llm if isinstance(llm, dict) else {}

    ev = {
        "source": source,
        "id": rec.get("id"),
        "domain": d.get("domain") or rec.get("domain"),
        "question_type": d.get("question_type"),
        "tier": d.get("tier"),
        "correct": rec.get("correct"),
        "error_class": rec.get("error_class"),
        "elapsed_sec": round(rec.get("elapsed_sec") or 0, 1),
        "placeholder": d.get("placeholder"),
        "invalid_reason": detect_invalid(rec),
        "data_quality": classify_validity(rec)[0],
        "data_quality_reason": classify_validity(rec)[1],
        "question": _cut(rec.get("question"), 1000),
        "gold": _cut(rec.get("gold"), 200),
        "predicted": _cut(rec.get("predicted"), 300),
        "candidates": cands,
        "pick_diag": {"branch": pd.get("branch"), "picked": _cut(pd.get("picked"), 160),
                      "clusters": clusters},
        "lean_gate": {"n": len(lg), "verdict_counts": lg_counts, "head": lg_head,
                      "applicable": d.get("lean_applicable"),
                      "skip_reason": d.get("lean_skip_reason")},
        "audit_gate": {"n": len(ag), "verdict_counts": ag_counts,
                       "note": _cut((ag[0] or {}).get("note") if ag else None, 200)},
        "stages": stages,
        "mechanics": {
            "subgoal_stats": d.get("subgoal_stats"),
            "exhaust_result": d.get("exhaust_result"),
            "blueprint_nodes": _count(d.get("blueprint_nodes")),
            "blueprint_merge": _cut(d.get("blueprint_merge"), 200),
            "toolcall_text_detected": _count(d.get("toolcall_text_detected")),
            "leansearch": d.get("leansearch"),
            "toolcall_exec": _count(d.get("toolcall_exec")),
            "preverify_trace": (
                {"verdict": (d.get("preverify_trace") or {}).get("verdict"),
                 "rounds": (d.get("preverify_trace") or {}).get("rounds")}
                if isinstance(d.get("preverify_trace"), dict) else None),
            "revise_round": d.get("revise_round"),
            "degraded_flags": d.get("degraded_flags"),
            "capped_params": _capped(d.get("param_usage")),
        },
        "tool_calls": {
            "lean_mcp": (tc.get("lean_mcp") or {}).get("calls"),
            "lean_mcp_fail": (tc.get("lean_mcp") or {}).get("fail"),
            "web_search": (tc.get("web_search") or {}).get("calls"),
        },
        "llm_calls": {"calls": llm.get("calls"), "truncated": llm.get("truncated")},
        "trace_tail": [
            {"step": t.get("step"), "content": _cut(t.get("content"), 170)}
            for t in _as_list(rec.get("trace"))[-8:] if isinstance(t, dict)
        ],
        "local_history": (
            {"correct_before": core.get("correct"), "tier_before": core.get("tier"),
             "elapsed_before": core.get("elapsed_sec")} if core else None),
    }
    # ★ 2026-09-23 分析师模式专用：**推理全文**。
    #   checker 模式只给 reasoning_len（等于没给推理）⇒ 模型只能做"池里有没有
    #   gold"的对照题。分析师模式必须把推理原文喂进去，否则"分析推理漏洞"
    #   无从谈起（用户 2026-09-23 口径）。
    #   ⚠ **只在 analyst 模式注入**：checker 模式保持字段集不变，
    #   否则 `evidence_sha` 全变 ⇒ 既有轮次的幂等去重全部失效、37 题会被重跑。
    if mode == "analyst":
        ev["candidate_reasoning"] = _reasoning_excerpt(rec)
        ev["subgoal_results"] = _subgoal_excerpt(rec)
    return ev


# ★ 分析师模式的推理预算：推理原文总字符上限（超出则按候选均分截断）
REASONING_BUDGET = 24000
SUBGOAL_BUDGET = 8000


def _reasoning_excerpt(rec: Dict[str, Any], budget: int = REASONING_BUDGET) -> List[Dict[str, Any]]:
    """抽取候选推理**原文**（分析师模式的核心输入）。

    按候选均分字符预算；单条至少给 1200 字符、最多 12000 字符。
    截断处显式标注 `[后文截断]`，让模型知道它没看到全文（防"此处无异常"的误判）。
    """
    cands = [c for c in _as_list(rec.get("candidates")) if isinstance(c, dict)]
    if not cands:
        return []
    per = max(1200, min(12000, budget // max(1, len(cands))))
    out = []
    for c in cands:
        r = str(c.get("reasoning") or "")
        if not r:
            continue
        item = {
            "id": c.get("id"),
            "answer": _cut(c.get("answer"), 160),
            "reasoning": _cut(r, per),
            "reasoning_len": len(r),
        }
        if len(r) > per:
            item["reasoning"] = item["reasoning"] + "……[后文截断，原文共 %d 字符]" % len(r)
        out.append(item)
    return out


def _subgoal_excerpt(rec: Dict[str, Any], budget: int = SUBGOAL_BUDGET) -> List[Dict[str, Any]]:
    """抽取子目标的**产出原文**（子目标推理）。"""
    d = rec.get("diag") or {}
    sgs = [s for s in _as_list(d.get("subgoal_trace")) if isinstance(s, dict)]
    if not sgs:
        return []
    per = max(200, min(3000, budget // max(1, len(sgs))))
    out = []
    for s in sgs:
        out.append({
            "id": s.get("id"),
            "title": _cut(s.get("title"), 80),
            "type": s.get("type"),
            "expected_output": _cut(s.get("expected_output"), 120),
            "result": _cut(s.get("result"), per),
        })
    return out


def _as_list(v: Any) -> List[Any]:
    """埋点类型在轮次间漂移（list / dict / int / None）⇒ 一律安全降级为 list。"""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return []


def _as_dict(v: Any) -> Dict[str, Any]:
    """同上：把非 dict 的埋点安全降级成空 dict，避免 .get 崩。"""
    return v if isinstance(v, dict) else {}


def _count(v: Any) -> Any:
    """埋点可能是 list / dict / int ⇒ 统一成「条目数」或原值。"""
    if v is None:
        return None
    if isinstance(v, (list, dict, str)):
        return len(v)
    return v


def _capped(param_usage: Any) -> List[str]:
    """挑出真正撞顶的上限（capped=true 且 exact=true）。"""
    if not isinstance(param_usage, dict):
        return []
    out = []
    for k, v in (param_usage.get("items") or {}).items():
        if isinstance(v, dict) and v.get("capped") and v.get("exact"):
            out.append("%s(%s/%s)" % (k, v.get("used"), v.get("cap")))
    return out


def render_evidence(ev: Dict[str, Any]) -> str:
    # 去掉逐题不变的信源字段再渲染，让哈希只反映本题内容
    body = {k: v for k, v in ev.items() if k != "source"}
    return json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True)


# ----------------------------------------------------------------
# 证据包收缩（防止长上下文 / 长推理导致调用中断）
# ----------------------------------------------------------------
_EV_KEEP = ("id", "question_type", "tier", "correct", "error_class", "elapsed_sec",
            "question", "gold", "predicted", "candidates", "pick_diag",
            "lean_gate", "audit_gate", "stages", "mechanics", "tool_calls",
            "llm_calls", "data_quality",
            # ★ 分析师模式必须保留的字段：丢了就等于丢了分析对象
            "candidate_reasoning", "subgoal_results")


def _ev_size(o: Dict[str, Any]) -> int:
    """与真正发送的文本同口径计长（render_evidence 的缩进/排序一致）。"""
    return len(render_evidence(o))


def _trim_to_budget(e: Dict[str, Any], budget: int) -> Dict[str, Any]:
    """兜底强制裁剪：按「信息密度从低到高」依次削，直到进入预算。"""
    import copy
    o = copy.deepcopy(e)
    steps = (
        lambda x: x.pop("trace_tail", None),
        lambda x: x.pop("stages", None),
        lambda x: x.pop("llm_calls", None),
        lambda x: x.pop("tool_calls", None),
        lambda x: x.pop("audit_gate", None),
        lambda x: x.get("mechanics") and x["mechanics"].pop("blueprint_merge", None),
        lambda x: x.__setitem__("question", _cut(x.get("question"), 120)),
        lambda x: x.__setitem__("gold", _cut(x.get("gold"), 60)),
        lambda x: x.pop("mechanics", None),
        lambda x: x.pop("pick_diag", None),
        lambda x: x.pop("lean_gate", None),
        lambda x: x.__setitem__(
            "candidates",
            [{"id": c.get("id"), "answer": _cut(c.get("answer"), 60)}
             for c in (x.get("candidates") or [])]),
        lambda x: x.__setitem__("candidates", (x.get("candidates") or [])[:3]),
    )
    for fn in steps:
        if _ev_size(o) <= budget:
            return o
        try:
            fn(o)
        except Exception:  # noqa: BLE001
            pass
    return o


def _ev_levels(ev: Dict[str, Any]) -> List[Dict[str, Any]]:
    """由大到小的证据包收缩阶梯，每级都自洽、都保留判错所需的核心字段。

    L0 原样 → L1 去 trace_tail → L2 再砍 Lean 代码/候选答案/题面 → L3 只留核心键。
    用途有二：① 按预算裁剪；② 失败重试时逐级换更小的输入。
    """
    import copy
    lv: List[Dict[str, Any]] = [copy.deepcopy(ev)]

    a = copy.deepcopy(ev)
    a.pop("trace_tail", None)
    lv.append(a)

    b = copy.deepcopy(a)
    lg = b.get("lean_gate")
    if isinstance(lg, dict):
        for h in (lg.get("head") or []):
            if isinstance(h, dict):
                h.pop("code", None)
        lg["head"] = (lg.get("head") or [])[:2]
    for c in (b.get("candidates") or []):
        if isinstance(c, dict) and "answer" in c:
            c["answer"] = _cut(c.get("answer"), 120)
    b["question"] = _cut(b.get("question"), 300)
    # ★ 分析师模式：L2 只压缩推理到一半，**不删** —— 推理是分析对象，不是装饰
    for c in (b.get("candidate_reasoning") or []):
        if isinstance(c, dict) and c.get("reasoning"):
            c["reasoning"] = _cut(c.get("reasoning"), 4000)
    for s in (b.get("subgoal_results") or []):
        if isinstance(s, dict) and s.get("result"):
            s["result"] = _cut(s.get("result"), 800)
    lv.append(b)

    c = {k: b[k] for k in _EV_KEEP if k in b}
    if isinstance(c.get("lean_gate"), dict):
        c["lean_gate"] = {k: v for k, v in c["lean_gate"].items()
                          if k in ("n", "verdict_counts", "applicable")}
    lv.append(c)
    return lv


def fit_evidence(ev: Dict[str, Any], budget: int) -> Dict[str, Any]:
    """返回「不超过 budget 字符」的最大可用证据包；都不超则原样返回。"""
    lv = _ev_levels(ev)
    for e in lv:
        if _ev_size(e) <= budget:
            return e
    return _trim_to_budget(lv[-1], budget)
