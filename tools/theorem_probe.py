# -*- coding: utf-8 -*-
"""定理检索命中率评测（2026-09-29，截图 #3+#4）。

回答用户的三个问题
------------------
> ① 判断大模型或 leansearch 最后有没有找到正确的定理
> ② 定理对大模型的推理效果如何

本脚本负责 **①**（检索侧的客观测量）：
   拿题库预标注表（`tools/build_theorem_gt.py` 产出，人工可校正）作基准，
   对每题跑 `agent.theorem_hint.retrieve_theorems_for_question()`，
   比对命中情况，产出**逐题 + 汇总**指标。

② 由流水线侧负责（`ctx.theorem_hint_trace` 埋点 + 有/无定理的 A/B 对照），
   见 `agent/orchestrator.py` 的 `1.2_theorem_hint` 阶段。

核心指标
--------
· hit_rate        必中定理的召回率（required_hit / required_n）
· all_hit         是否**全部**必中定理都找到（严格口径，最能说明"找对了"）
· best_rank       首个必中定理的位次（1 = 排在第一位；越靠前越有用）
· topk_capped     命中条数是否顶到 top_k（说明条数是被截出来的，不是"恰好只有这些"）
· miss           漏掉的必中定理名（直接告诉你"哪条没找到"）
· elapsed_s      单题检索耗时（判断能否塞进流水线预算）

用法
----
    python tools/theorem_probe.py --limit 20            # 先跑 20 题看效果
    python tools/theorem_probe.py                       # 全量
    python tools/theorem_probe.py --top-k 10 --max-queries 3
    python tools/theorem_probe.py --report out.md       # 另出 markdown 小结
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

DEFAULT_BANK = os.path.join(
    _REPO_ROOT, "题库", "official112_本地测试题库", "official112_full.jsonl")
DEFAULT_GT = os.path.join(
    _REPO_ROOT, "data", "theorem_ground_truth", "official112_theorems.jsonl")
DEFAULT_OUT = os.path.join(
    _REPO_ROOT, "data", "theorem_ground_truth", "probe_official112.json")


def _load_jsonl_theorem_probe(path: str) -> list:
    if not os.path.isfile(path):
        return []
    out: list = []
    for l in io.open(path, encoding="utf-8", errors="replace"):
        if not l.strip():
            continue
        try:
            out.append(json.loads(l))
        except Exception:  # noqa: BLE001
            continue
    return out


def _summarize(per_q: list, args) -> dict:
    """汇总指标（纯函数，便于续跑时中途落盘复用）。"""
    scored = [x for x in per_q if x["scored"]] if not args.include_empty_gt \
        else [x for x in per_q if x["ok"]]
    ok_runs = [x for x in per_q if x["ok"]]

    rates = [x["hit_rate"] for x in scored if x["hit_rate"] is not None]
    ranks = [x["best_rank"] for x in scored if x["best_rank"]]
    elapsed = [x["elapsed_s"] for x in per_q]

    return {
        "n_total": len(per_q),
        "n_retrieval_ok": len(ok_runs),
        "n_scored": len(scored),
        "n_all_hit": sum(1 for x in scored if x["all_hit"]),
        "all_hit_rate": (sum(1 for x in scored if x["all_hit"]) / len(scored)
                         if scored else None),
        "mean_hit_rate": (statistics.fmean(rates) if rates else None),
        "median_best_rank": (statistics.median(ranks) if ranks else None),
        "topk_capped_ratio": (sum(1 for x in per_q if x["topk_capped"])
                              / len(per_q) if per_q else None),
        "elapsed_mean_s": (statistics.fmean(elapsed) if elapsed else None),
        "elapsed_total_s": 0.0,
        "top_k": args.top_k, "max_queries": args.max_queries,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="定理检索命中率评测")
    ap.add_argument("--bank", default=DEFAULT_BANK, help="题库 jsonl")
    ap.add_argument("--gt", default=DEFAULT_GT, help="预标注表 jsonl")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出 JSON 路径")
    ap.add_argument("--report", default="", help="额外输出 markdown 小结路径")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（0=全量）")
    ap.add_argument("--top-k", type=int, default=5, help="每次检索取回条数")
    ap.add_argument("--max-queries", type=int, default=2, help="每题最多发几次检索")
    ap.add_argument("--include-empty-gt", action="store_true",
                    help="把预标注为空（模型没给出定理）的题也计入统计")
    ap.add_argument("--resume", action="store_true",
                    help="从 --out 已有结果续跑（跳过已完成的题）；"
                         "用于被外部信号打断后接着跑，避免重跑白烧十几分钟")
    ap.add_argument("--checkpoint-every", type=int, default=10,
                    help="每完成 N 题落一次盘（配合 --resume）")
    args = ap.parse_args()

    bank = _load_jsonl_theorem_probe(args.bank)
    gt_rows = _load_jsonl_theorem_probe(args.gt)
    if not bank:
        print(f"题库为空或不存在: {args.bank}")
        return 1
    if not gt_rows:
        print(f"预标注表为空或不存在: {args.gt}")
        print("请先运行: python tools/build_theorem_gt.py")
        return 1

    gt_map = {str(r.get("id")): r for r in gt_rows}
    if args.limit:
        bank = bank[:args.limit]

    from agent.theorem_hint import (retrieve_theorems_for_question,
                                    match_against_ground_truth)

    # ---- 断点续跑：读回已有结果，跳过已完成的题 ----
    # 背景：本脚本全量约 12 分钟（112 题 × ~6.5s），而宿主对单次命令有硬时限，
    # 跑到一半会被 SIGTERM。没有续跑就只能从头再烧一遍，白等十几分钟。
    done_map: dict = {}
    if args.resume and os.path.isfile(args.out):
        try:
            with io.open(args.out, encoding="utf-8") as f:
                prev = json.load(f)
            for rec in (prev.get("per_question") or []):
                if rec.get("id"):
                    done_map[str(rec["id"])] = rec
            print(f"[resume] 已载入 {len(done_map)} 题既有结果，将跳过")
        except Exception as exc:  # noqa: BLE001
            print(f"[resume] 读取 {args.out} 失败，按全新跑：{exc}")
            done_map = {}

    def _flush() -> None:
        """落盘（中途也调用，保证被杀后能续）。"""
        _sum = _summarize(per_q, args)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with io.open(args.out, "w", encoding="utf-8") as f:
            json.dump({"summary": _sum, "per_question": per_q},
                      f, ensure_ascii=False, indent=2)

    per_q: list = []
    print(f"题库 {len(bank)} 题 | top_k={args.top_k} "
          f"max_queries={args.max_queries}")
    t_all = time.time()
    n_skipped = 0
    for i, row in enumerate(bank, 1):
        rid = str(row.get("id") or f"idx{i-1}")
        problem = str(row.get("question") or row.get("problem") or "")
        domain = str(row.get("domain") or "")
        gt = gt_map.get(rid) or {}
        req = gt.get("required") or []

        if rid in done_map:
            rec = done_map[rid]
            # 标注表可能被去污脚本改过 ⇒ required 以**当前**标注表为准重算，
            # 否则续跑会把旧标注的命中结果带进来，口径打架。
            if rec.get("required") != req:
                from agent.theorem_hint import TheoremRetrieval, TheoremHit
                _names = rec.get("hits") or []
                _r = TheoremRetrieval(
                    ok=bool(rec.get("ok")),
                    domain=rec.get("domain") or "",
                    reason=rec.get("reason") or "",
                    backend=rec.get("backend") or "",
                    queries=rec.get("queries") or [],
                    hits=[TheoremHit(name=str(n), short=str(n).split(".")[-1])
                          for n in _names],
                    elapsed=float(rec.get("elapsed_s") or 0.0))
                m = match_against_ground_truth(_r, gt)
                rec.update({
                    "required": req,
                    "required_hit": m["required_hit"],
                    "required_n": m["required_n"],
                    "miss": m["required_miss"],
                    "hit_rate": m["hit_rate"],
                    "all_hit": m["all_required_hit"],
                    "best_rank": m["best_rank"],
                    "scored": bool(req),
                })
            per_q.append(rec)
            n_skipped += 1
            continue

        r = retrieve_theorems_for_question(
            problem, domain=domain, question_type="",
            max_queries=args.max_queries, top_k=args.top_k)
        m = match_against_ground_truth(r, gt)

        capped = len(r.hits) >= args.top_k
        rec = {
            "id": rid, "domain": domain,
            "ok": r.ok, "reason": r.reason, "backend": r.backend,
            "elapsed_s": round(r.elapsed, 2),
            "queries": r.queries,
            "n_hits": len(r.hits), "topk_capped": capped,
            "hits": r.names,
            "required": req,
            "required_hit": m["required_hit"],
            "required_n": m["required_n"],
            "miss": m["required_miss"],
            "hit_rate": m["hit_rate"],
            "all_hit": m["all_required_hit"],
            "best_rank": m["best_rank"],
            "scored": bool(req),
        }
        per_q.append(rec)

        if req:
            mark = "ALL" if m["all_required_hit"] else (
                "PART" if m["required_hit"] else "MISS")
        else:
            mark = "—"
        print(f"[{i}/{len(bank)}] {mark:4s} {rid} "
              f"hit={m['required_hit']}/{m['required_n']} "
              f"rank={m['best_rank']} {len(r.hits)}条 {r.elapsed:.1f}s"
              + (f" miss={m['required_miss']}" if m["required_miss"] else ""),
              flush=True)

        if args.checkpoint_every and len(per_q) % args.checkpoint_every == 0:
            _flush()

    if n_skipped:
        print(f"[resume] 本次跳过 {n_skipped} 题（沿用既有结果）")

    # ---- 汇总（默认只统计有 required 的题 —— 空标注不可评） ----
    summary = _summarize(per_q, args)
    summary["elapsed_total_s"] = round(time.time() - t_all, 1)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "per_question": per_q},
                  f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 66)
    print("汇总")
    print("=" * 66)
    print(f"  可评题数        {summary['n_scored']} / {summary['n_total']}")
    print(f"  检索跑通        {summary['n_retrieval_ok']}")
    if summary["mean_hit_rate"] is not None:
        print(f"  平均命中率      {summary['mean_hit_rate']:.1%}")
    if summary["all_hit_rate"] is not None:
        print(f"  全中率(严格)    {summary['all_hit_rate']:.1%}"
              f"  ({summary['n_all_hit']}/{summary['n_scored']})")
    if summary["median_best_rank"] is not None:
        print(f"  首个命中位次中位 {summary['median_best_rank']:.0f}")
    if summary["topk_capped_ratio"] is not None:
        print(f"  顶到 top_k 比例 {summary['topk_capped_ratio']:.1%}"
              f"  (高=条数被截出来，非真实相关数)")
    if summary["elapsed_mean_s"] is not None:
        print(f"  单题检索耗时    {summary['elapsed_mean_s']:.1f}s "
              f"(总 {summary['elapsed_total_s']}s)")
    print(f"\n已写出: {args.out}")

    if args.report:
        _write_report(args.report, summary, per_q)
        print(f"已写出: {args.report}")
    return 0


def _write_report(path: str, summary: dict, per_q: list) -> None:
    L: list = []
    L.append("# 定理检索命中率评测报告\n")
    L.append(f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    # ★ 方法学警示：这张表**不能**当"检索能力强"的证据读。
    #   原因：标注表 source 字段全为 auto:leansearch —— 基准答案本身就是
    #   检索结果，等于用检索去考检索自己，命中率天然趋近 100%。
    #   必须人工校正标注表后，这个指标才有解释力。
    L.append("## ⚠ 读表前必看（同源性警示）\n")
    L.append("本报告的基准（required）由 `tools/build_theorem_gt.py` 生成，")
    L.append("其 `source` 字段为 **auto:leansearch** —— 即**基准答案本身取自 leansearch 检索结果**。")
    L.append("因此「命中率」在此衡量的是**检索的自洽性**，不是「检索能否找对定理」的能力。\n")
    L.append("· 已被修正的污染：早期版本把检索**前 N 条直接当 required**，")
    L.append("  导致 7 条泛化定理横跨 >5 题（`card_perms_of_finset` 横跨 **49/112** 题），")
    L.append("  占 448 个槽位的 **32.1%**。已由 `tools/theorem_gt_dedup.py` 降级到 optional。")
    L.append("· 去污前 86.6% → 去污后 **98.5%**。**上升**恰恰说明：原来的低分主要来自")
    L.append("  「被当作必中、实为检索噪声」的泛化定理，而不是题目特异定理找不着。")
    L.append("· **仍未解决的问题**：基准与评测同源。要得到可信的检索能力数字，")
    L.append("  必须**人工校正 `official112_theorems.jsonl`**（当前 112 题 `note` 全空、零人工介入），")
    L.append("  或用独立来源（教材/gold 解答）建立基准。\n")

    L.append("## 汇总\n")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append(f"| 可评题数 | {summary['n_scored']} / {summary['n_total']} |")
    L.append(f"| 检索跑通 | {summary['n_retrieval_ok']} |")
    mr = summary.get("mean_hit_rate")
    L.append(f"| 平均命中率 | {mr:.1%} |" if mr is not None else "| 平均命中率 | — |")
    ah = summary.get("all_hit_rate")
    L.append(f"| 全中率（严格） | {ah:.1%} |" if ah is not None else "| 全中率 | — |")
    br = summary.get("median_best_rank")
    L.append(f"| 首个命中位次中位 | {br:.0f} |" if br else "| 首个命中位次中位 | — |")
    tc = summary.get("topk_capped_ratio")
    L.append(f"| 顶到 top_k 比例 | {tc:.1%} |" if tc is not None else "| — | — |")
    em = summary.get("elapsed_mean_s")
    L.append(f"| 单题检索耗时 | {em:.1f}s |" if em else "| 单题检索耗时 | — |")
    L.append(f"| top_k / max_queries | {summary['top_k']} / {summary['max_queries']} |")
    L.append("\n## 逐题明细\n")
    L.append("| # | 题号 | 领域 | 必中 | 命中 | 全中 | 位次 | 条数 | 耗时 | 漏掉 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for i, x in enumerate(per_q, 1):
        miss = ", ".join(x["miss"]) if x["miss"] else "—"
        L.append(f"| {i} | {x['id']} | {x['domain']} | {x['required_n']} | "
                 f"{x['required_hit']} | {'✓' if x['all_hit'] else '✗'} | "
                 f"{x['best_rank'] or '—'} | {x['n_hits']} | "
                 f"{x['elapsed_s']:.1f}s | {miss} |")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
