# -*- coding: utf-8 -*-
"""全工具云端使用情况审计：把每题 diag 里所有"工具"相关字段摊开。

用法: .venv/bin/python deploy/_audit_tools.py [结果.jsonl]
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def newest(pat):
    fs = [f for f in glob.glob(pat) if os.path.isfile(f)]
    return max(fs, key=os.path.getmtime) if fs else ""


f = sys.argv[1] if len(sys.argv) > 1 else newest("results/cloud*.jsonl")
rows = []
if f and os.path.isfile(f):
    for ln in open(f, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if ln:
            try:
                rows.append(json.loads(ln))
            except Exception:  # noqa: BLE001
                pass
print(f"结果文件 {f}   已完成 {len(rows)} 题")
if not rows:
    raise SystemExit(0)

print("=" * 78)
print("一、tool_calls —— 代理层的工具调用台账")
print("=" * 78)
keys = set()
for r in rows:
    tc = r.get("tool_calls") or {}
    keys |= set(tc.keys())
for k in sorted(keys):
    agg = {}
    for r in rows:
        d = (r.get("tool_calls") or {}).get(k) or {}
        for kk, vv in d.items():
            if isinstance(vv, (int, float)):
                agg[kk] = agg.get(kk, 0) + vv
            else:
                agg[kk] = vv
    calls = agg.get("calls", 0)
    mark = "✅" if calls else "❌"
    print(f"  {mark} {k:<16} calls={agg.get('calls')}  ok={agg.get('ok')}  "
          f"fail={agg.get('fail')}  verdict={agg.get('verdict')}")
    if agg.get("seconds"):
        print(f"       seconds={agg.get('seconds'):.1f}s")

print()
print("=" * 78)
print("二、Lean 相关 —— 主链路是否真的启用")
print("=" * 78)
for k in ("lean_active", "lean_applicable", "lean_executable", "lean_skip_reason",
          "degraded_flags"):
    vals = {str(r.get("diag", {}).get(k)) for r in rows}
    print(f"  {k:<20} {vals}")
lg_n = sum(len(r.get("diag", {}).get("lean_gate") or []) for r in rows)
mus = {}
for r in rows:
    for kk, vv in (r.get("mathlib_usage_stats") or {}).items():
        if isinstance(vv, (int, float)):
            mus[kk] = mus.get(kk, 0) + vv
print(f"  lean_gate 条目数合计   {lg_n}")
print(f"  mathlib_usage_stats    {mus}")
lc = [x for r in rows for x in (r.get("diag", {}).get("lean_gate") or [])]
if lc:
    print(f"  lean_gate 首条         {json.dumps(lc[0], ensure_ascii=False)[:220]}")

print()
print("=" * 78)
print("三、检索类工具")
print("=" * 78)
for k in ("leansearch", "lemma_repo"):
    seen = {}
    for r in rows:
        v = r.get("diag", {}).get(k)
        if isinstance(v, dict):
            for kk, vv in v.items():
                seen[kk] = vv if not isinstance(vv, (int, float)) else \
                    (seen.get(kk, 0) + vv if isinstance(seen.get(kk), (int, float)) or kk not in seen else vv)
        elif v is not None:
            seen["(值)"] = str(v)[:60]
    print(f"  {k:<12} {json.dumps(seen, ensure_ascii=False)[:260]}")

print()
print("=" * 78)
print("四、计算/符号类工具")
print("=" * 78)
for k in ("calc_tool_mode", "calc_tool_calls", "calc_easy_pass_events",
          "calc_fallback", "calc_rewrite", "calc_prewarm_events",
          "symbolic_solve_events", "symbolic_crosscheck_events",
          "expression_eval_events", "numericize_events", "p1_check_events",
          "answer_selfcheck_events", "value_attack", "exhaust_diag",
          "exhaust_result", "formal_spec", "formal_gaps"):
    tot = 0
    sample = ""
    for r in rows:
        v = r.get("diag", {}).get(k)
        if isinstance(v, list):
            tot += len(v)
            if v and not sample:
                sample = str(v[0])[:110]
        elif isinstance(v, dict):
            tot += len(v)
            if v and not sample:
                sample = json.dumps(v, ensure_ascii=False)[:110]
        elif isinstance(v, str) and v:
            if not sample:
                sample = v[:110]
    mark = "✅" if tot else "❌"
    extra = f"  样例: {sample}" if sample else ""
    print(f"  {mark} {k:<28} 条目={tot}{extra}")

print()
print("=" * 78)
print("五、蓝图 / 子目标 / DAG")
print("=" * 78)
for k in ("blueprint_nodes", "blueprint_merge", "blueprint_value_false",
          "subgoal_stats", "subgoal_trace", "subgoal_merge_plan",
          "dag_review", "dag_replan_events", "sketch_audit", "skeleton_review"):
    vals = []
    for r in rows:
        v = r.get("diag", {}).get(k)
        if isinstance(v, (list, dict)):
            vals.append(len(v))
        elif v is not None:
            vals.append(str(v)[:40])
    mark = "✅" if any(x not in (0, "0", "", "None") for x in vals) else "❌"
    print(f"  {mark} {k:<26} {vals}")

print()
print("=" * 78)
print("六、逐题闸门与候选")
print("=" * 78)
print(f"  {'题号':<20}{'tier':<9}{'候选':>4}{'票':>4}{'修订':>5}{'漏跳':>5}{'降级':>5}  错误分类")
for r in rows:
    d = r.get("diag", {})
    print(f"  {str(r.get('id'))[:19]:<20}{str(d.get('tier')):<9}"
          f"{d.get('n_candidates') or 0:>4}{d.get('n_verdicts') or 0:>4}"
          f"{d.get('revise_round') or 0:>5}{d.get('budget_skips') or 0:>5}"
          f"{d.get('degraded_flags') or 0:>5}  {r.get('error_class') or ''}")
