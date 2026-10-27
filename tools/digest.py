# -*- coding: utf-8 -*-
"""L2 机械摘要（digest）—— 一条轨迹 → 一段结构化摘要（**不调 LLM**）。

图上那个节点叫「读一条轨迹摘要点」。RRSI 的做法是派一个只读小助手（LLM）看轨迹、
交回 ≤6000 字摘要。我们没有真实轨迹预算时，先把**能确定的部分**机械化：
diag 里已经记了 70 多个键（候选池、五道链判定、Lean 门、票型、阶段耗时、降级标志），
这些不需要大模型也能读出来。

诚实的边界
==========
· 本工具产出的是**机械摘要**：只陈述"记录里有什么"，不做因果判断。
· `suspect_stage` 是按规则猜的**疑点**，不是根因；根因要靠人看摘要在候选单元里挑
  （候选单元用 `tools/localize.py --stage <环节>` 列）。
· LLM 版摘要（把 5 万字轨迹压成 6000 字）仍未做，等有真实轨迹预算再上。

为什么必须 ≤6000 字符
====================
摘要一旦和原文一样长，分析者就会退化成"读原文然后说套话"（RRSI 的硬上限就是这么来的）。
超长时**宁可截断并标注**，也不提交一份假装完整的摘要。

用法
====
    python tools/digest.py --result results/xxx.jsonl                 # 全部题，逐条摘要
    python tools/digest.py --result results/xxx.jsonl --qid official112-003
    python tools/digest.py --result results/xxx.jsonl --out results/_digest/x.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

SCHEMA = "digest/1"
MAX_CHARS = 6000


def _num(x) -> str:
    try:
        return "%.0f" % float(x)
    except (TypeError, ValueError):
        return "?"


def _norm_answer(a) -> str:
    s = str(a or "")
    s = s.replace("\\boxed{", "").replace("\\boxed", "")
    s = s.replace("$", "").strip("{} ").strip()
    return re.sub(r"\s+", " ", s)


def _stage_timers(d: dict, top: int = 5) -> list:
    st = d.get("stage_timers") or {}
    if not isinstance(st, dict):
        return []
    rows = [(k, float(v)) for k, v in st.items() if isinstance(v, (int, float))]
    rows.sort(key=lambda x: -x[1])
    return [(k, v) for k, v in rows[:top] if v >= 1.0]


def _pool(r: dict, d: dict) -> dict:
    cands = r.get("candidates") or []
    answers = {}
    for c in cands:
        a = _norm_answer((c or {}).get("answer"))
        if a:
            answers[a] = answers.get(a, 0) + 1
    top = sorted(answers.items(), key=lambda kv: -kv[1])[:3]
    gold = _norm_answer(r.get("gold"))
    gold_parts = {_norm_answer(p) for p in re.split(r"[;；,，]|\bor\b", str(r.get("gold") or "")) if p.strip()}
    in_pool = bool(gold_parts) and any(g in answers for g in gold_parts)
    return {"n_candidates": int(d.get("n_candidates") or len(cands)),
            "distinct_answers": len(answers),
            "top_answers": top, "gold_in_pool": in_pool if gold_parts else None,
            "gold": gold[:60]}


def _gates(d: dict) -> dict:
    lg = d.get("lean_gate")
    lean = {"n": 0, "valid": 0, "invalid": 0, "unknown": 0}
    if isinstance(lg, list):
        for row in lg:
            lean["n"] += 1
            v = str((row or {}).get("verdict") or "").lower()
            # ⚠ 必须**先判 invalid**：'answer_invalid'.endswith('valid') 也是 True，
            #   按后缀先判 valid 会把「判错」数成「判对」（第一版就栽在这里）。
            if "invalid" in v:
                lean["invalid"] += 1
            elif v.endswith("valid"):
                lean["valid"] += 1
            elif v:
                lean["unknown"] += 1
    et = d.get("error_types") or {}
    top_et = sorted(((k, v) for k, v in et.items() if isinstance(v, (int, float))),
                    key=lambda kv: -kv[1])[:3] if isinstance(et, dict) else []
    pick = d.get("pick_diag") or {}
    return {"lean": lean, "error_types_top": top_et,
            "pick_branch": (pick or {}).get("branch", ""),
            "n_reject_votes": d.get("n_reject_votes"),
            "degraded_flags": d.get("degraded_flags"),
            "budget_skips": d.get("budget_skips"),
            "lean_skip_reason": d.get("lean_skip_reason")}


def _suspect(d: dict, r: dict, pool: dict, gates: dict) -> tuple:
    """按规则猜疑点（**不是根因**）。返回 (stage, 依据)。"""
    if pool["n_candidates"] == 0:
        return "3_solve", "候选池为空 ⇒ 生成环节没产出"
    if pool["gold_in_pool"] is False:
        return "3_solve", "gold 不在候选池 ⇒ 生成/入池阶段丢失正解"
    lean = gates["lean"]
    if lean["invalid"] > 0:
        return "4.3_lean_check", "%d 个候选被 Lean 判 invalid" % lean["invalid"]
    if "zero_vote" in str(gates["pick_branch"]):
        return "4.5_vote", "选答走了 %s（票型无共识）" % gates["pick_branch"]
    if pool["distinct_answers"] == 1 and not r.get("correct"):
        return "3_solve", "全池同一答案但仍判错 ⇒ 生成方向一致地错"
    if gates["degraded_flags"]:
        return "runtime", "%d 次降级标志被置" % int(gates["degraded_flags"] or 0)
    return "", ""


def digest_one(r: dict, max_chars: int = MAX_CHARS) -> dict:
    d = r.get("diag") or {}
    pool = _pool(r, d) if isinstance(d, dict) else _pool(r, {})
    gates = _gates(d) if isinstance(d, dict) else _gates({})
    stage, why = _suspect(d, r, pool, gates)
    timers = _stage_timers(d) if isinstance(d, dict) else []
    sub = (d or {}).get("subgoal_stats") or {}

    lines = []
    lines.append("题 %s ｜ %s ｜ %s ｜ tier=%s ｜ %s ｜ 耗时 %ss"
                 % (r.get("id"), r.get("domain") or (d or {}).get("domain") or "-",
                    (d or {}).get("question_type") or "-", (d or {}).get("tier") or "-",
                    "✅ 答对" if r.get("correct") else "❌ 答错（%s）" % (r.get("error_class") or "-"),
                    _num(r.get("elapsed_sec"))))
    lines.append("候选池：%d 个候选、%d 个不同答案；gold 在池内=%s"
                 % (pool["n_candidates"], pool["distinct_answers"],
                    {True: "是", False: "否", None: "未知"}[pool["gold_in_pool"]]))
    if pool["top_answers"]:
        def _short(a: str) -> str:
            return a if len(a) <= 40 else a[:40] + "…"
        lines.append("票型：%s" % "；".join("%s ×%d" % (_short(a) or "(空)", n)
                                          for a, n in pool["top_answers"]))
    if sub:
        lines.append("子目标：%s 个、依赖边 %s、无依赖 %s"
                     % (sub.get("n_subgoals"), sub.get("dep_edges"), sub.get("dep_free")))
    lean = gates["lean"]
    if lean["n"]:
        lines.append("Lean 门：%d 条判定（valid %d / invalid %d / 其它 %d）%s"
                     % (lean["n"], lean["valid"], lean["invalid"], lean["unknown"],
                        "；跳过原因=%s" % gates["lean_skip_reason"] if gates["lean_skip_reason"] else ""))
    elif gates["lean_skip_reason"]:
        lines.append("Lean 门：未跑（%s）" % gates["lean_skip_reason"])
    if gates["error_types_top"]:
        lines.append("审核标出的错误类型：%s"
                     % "；".join("%s ×%s" % (k, v) for k, v in gates["error_types_top"]))
    if gates["n_reject_votes"]:
        lines.append("反对票：%s" % gates["n_reject_votes"])
    if gates["pick_branch"]:
        lines.append("选答分支：%s" % gates["pick_branch"])
    if timers:
        lines.append("耗时 Top：%s" % "；".join("%s %.0fs" % (k, v) for k, v in timers))
    if gates["degraded_flags"] or gates["budget_skips"]:
        lines.append("降级/预算跳过：%s / %s" % (gates["degraded_flags"], gates["budget_skips"]))
    lines.append("疑点（机械猜测，非根因）：%s%s" % (stage or "无法判定",
                                                "（%s）" % why if why else ""))

    text = "\n".join(lines)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n…（摘要超长已截断：原文 %d 字符）" % len(text)
    return {"schema": SCHEMA, "qid": str(r.get("id")), "correct": bool(r.get("correct")),
            "error_class": r.get("error_class") or "",
            "suspect_stage": stage, "suspect_reason": why,
            "chars": len(text), "truncated": truncated,
            "pool": pool, "gates": gates, "timers": timers, "text": text}


def iter_rows(path: str):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("id"):
                yield row


def analyze(digests: list) -> dict:
    """多份机械摘要 → 一张问题清单（**不调 LLM**）。

    只做"计数型"汇总：哪些环节最常成为疑点、gold 有多少根本没进池、错误类型分布。
    这不是 RRSI 的 analyst（三视角 + 能力缺口 + 成功习惯）—— 那些要读语义，
    诚实标注：`method="mechanical"`。
    """
    n = len(digests)
    if not n:
        return {"schema": "analysis/1", "method": "mechanical", "n": 0}
    wrong = [d for d in digests if not d.get("correct")]
    stages, errs, pool_miss = {}, {}, 0
    lean_invalid = 0
    for d in digests:
        s = d.get("suspect_stage") or "(无法判定)"
        stages[s] = stages.get(s, 0) + 1
        for k, v in ((d.get("gates") or {}).get("error_types_top") or []):
            errs[k] = errs.get(k, 0) + int(v or 0)
        if (d.get("pool") or {}).get("gold_in_pool") is False:
            pool_miss += 1
        lean_invalid += int(((d.get("gates") or {}).get("lean") or {}).get("invalid") or 0)
    top = sorted(stages.items(), key=lambda kv: -kv[1])
    return {"schema": "analysis/1", "method": "mechanical", "n": n,
            "n_wrong": len(wrong),
            "suspect_stage_dist": top,
            "gold_missing_from_pool": pool_miss,
            "gold_missing_ratio": round(pool_miss / n, 4),
            "error_types": sorted(errs.items(), key=lambda kv: -kv[1])[:8],
            "lean_invalid_total": lean_invalid,
            "note": "计数型汇总（无 LLM）：只陈述疑点分布，不判根因、不写改动建议"}


def render_analysis(a: dict) -> str:
    if not a.get("n"):
        return "（没有摘要可汇总）"
    lines = ["# 机械汇总（%d 题，其中错 %d）" % (a["n"], a["n_wrong"]), "",
             "> %s" % a["note"], "",
             "| 疑点环节 | 题数 |", "|---|---:|"]
    for k, v in a["suspect_stage_dist"]:
        lines.append("| %s | %d |" % (k, v))
    lines += ["", "gold 不在候选池：**%d / %d（%.1f%%）**"
              % (a["gold_missing_from_pool"], a["n"], a["gold_missing_ratio"] * 100),
              "Lean 判 invalid 合计：%d" % a["lean_invalid_total"]]
    if a["error_types"]:
        lines += ["", "审核标出的错误类型 Top："]
        lines += ["- %s ×%d" % (k, v) for k, v in a["error_types"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="L2 机械摘要（不调 LLM）")
    ap.add_argument("--result", default="", help="评测结果 jsonl（一行一题）")
    ap.add_argument("--analyze", default="", help="对已生成的 digest jsonl 做机械汇总")
    ap.add_argument("--qid", default="", help="只看某题")
    ap.add_argument("--limit", type=int, default=0, help="只看前 N 题（0=全部）")
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    ap.add_argument("--out", default="", help="写 jsonl（不写只打印）")
    ap.add_argument("--text", action="store_true", help="打印可读摘要而不是 JSON")
    args = ap.parse_args(argv)

    if args.analyze:
        rows = []
        with open(args.analyze, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        a = analyze(rows)
        print(render_analysis(a))
        return 0

    if not args.result:
        print("❌ 需要 --result（生成摘要）或 --analyze（汇总已有摘要）")
        return 2
    if not os.path.isfile(args.result):
        print("❌ 找不到 %s" % args.result)
        return 2

    rows, out = [], []
    for r in iter_rows(args.result):
        if args.qid and str(r.get("id")) != args.qid:
            continue
        dg = digest_one(r, args.max_chars)
        out.append(dg)
        if args.limit and len(out) >= args.limit:
            break

    if not out:
        print("没有匹配的题")
        return 1

    if args.text:
        for i, dg in enumerate(out):
            if i:
                print("\n" + "-" * 60)
            print(dg["text"])
    else:
        print(json.dumps(out if len(out) > 1 else out[0], ensure_ascii=False, indent=1))

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            for dg in out:
                fh.write(json.dumps(dg, ensure_ascii=False) + "\n")
        print("\n已写 %s（%d 条）" % (args.out, len(out)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
