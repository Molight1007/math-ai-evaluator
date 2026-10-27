# -*- coding: utf-8 -*-
"""L2 归因核对 —— 提案时说的"会影响这几道题"，事后到底对不对。

图上那个板块叫「看它猜得准不准」，判据只有两个数：
    ① **命中率** = 预测对了且**真的变了**的题 / 预测集合
    ② **未预料的退步** = 变错了、但事先没预测到的题（这一项比命中率更重要）

为什么必须先有这个再谈"提得准"
==============================
如果提案器预测的题一道没动，说明它并不理解这个参数在干什么 ——
这时候的"涨分"要么是噪声，要么是别的机制在起作用，记到账上就是脏证据。

输入只要三样（都是纯 JSON，不依赖 LLM）
=====================================
    --pred    预测：{"predicted_affected": ["q1","q2"]}
              或候选文件：{"candidate": {..., "predicted_affected": ["q1", ...]}}
    --before  改动前的评测结果 jsonl（每题一行，含 id 与 correct）
    --after   改动后的评测结果 jsonl

题号只在本文件里出现（属于评测产物，不进仓库）；输出只落 `results/`。

用法
====
    python tools/attribution.py --pred cand.json --before a.jsonl --after b.jsonl
    python tools/attribution.py ... --write     # 追加到 results/_edit_ledger/attribution.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

SCHEMA = "attribution/1"
OUT = os.path.join(_ROOT, "results", "_edit_ledger", "attribution.jsonl")


def load_scores(path: str) -> dict:
    """评测结果 jsonl → {题号: 是否答对}。`correct` 缺失的题跳过（判不了分不算）。"""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            qid = row.get("id")
            if qid is None or "correct" not in row:
                continue
            out[str(qid)] = bool(row["correct"])
    return out


def load_predicted(path: str) -> dict:
    """读预测。支持两种形状：裸 `predicted_affected`，或提案器产出的候选文件。"""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if isinstance(doc, dict) and "candidate" in doc:
        doc = doc["candidate"]
    if not isinstance(doc, dict):
        raise ValueError("预测文件不是对象")
    pred = doc.get("predicted_affected")
    if isinstance(pred, str):
        # 提案器写的是**自然语言描述**（不该出现题号）；这种情况无法机核，如实报
        return {"items": [], "raw": pred, "structured": False}
    if not isinstance(pred, list):
        raise ValueError("predicted_affected 既不是列表也不是字符串")
    return {"items": [str(x) for x in pred], "raw": "", "structured": True}


def compare(before: dict, after: dict, predicted) -> dict:
    """算出命中率与未预料退步。题集不一致时只比共同题，并报出来。"""
    common = sorted(set(before) & set(after))
    only_b, only_a = sorted(set(before) - set(after)), sorted(set(after) - set(before))
    became_wrong = [q for q in common if before[q] and not after[q]]
    became_right = [q for q in common if not before[q] and after[q]]
    changed = set(became_wrong) | set(became_right)
    pred = set(predicted.get("items") or [])
    hit = sorted(pred & changed)
    missed = sorted(pred - changed)                 # 预测会变、实际没变
    unexpected = sorted(set(became_wrong) - pred)   # ⚠ 没预料到的退步
    n_pred = len(pred)
    return {"schema": SCHEMA, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "structured_prediction": bool(predicted.get("structured")),
            "predicted": sorted(pred), "n_predicted": n_pred,
            "n_common": len(common),
            "became_right": became_right, "became_wrong": became_wrong,
            "hit": hit, "missed": missed, "unexpected_regressions": unexpected,
            "hit_rate": (len(hit) / n_pred) if n_pred else None,
            "only_before": only_b, "only_after": only_a}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="L2 归因核对：预测 vs 实际变化")
    ap.add_argument("--pred", required=True)
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--show-ids", type=int, default=10)
    args = ap.parse_args(argv)

    try:
        pred = load_predicted(args.pred)
        before = load_scores(args.before)
        after = load_scores(args.after)
    except (OSError, ValueError) as e:
        print("❌ %s" % e)
        return 2

    r = compare(before, after, pred)
    print("# 归因核对（共同题 %d 道）\n" % r["n_common"])
    if not r["structured_prediction"]:
        print("⚠ 预测是**自然语言**（%r），无法机核命中率。\n"
              "  提案器的 predicted_affected 应写成题号列表才能核；"
              "按 R6，题号只允许出现在 results/ 产物里，不许进参数层。\n"
              % (pred.get("raw") or "")[:80])
    print("| 指标 | 值 |")
    print("|---|---:|")
    print("| 预测数 | %d |" % r["n_predicted"])
    print("| 命中（预测且真变） | %d |" % len(r["hit"]))
    print("| 命中率 | %s |" % ("-" if r["hit_rate"] is None else "%.1f%%" % (r["hit_rate"] * 100)))
    print("| 预测了但没变 | %d |" % len(r["missed"]))
    print("| **未预料的退步** | **%d** |" % len(r["unexpected_regressions"]))
    print("| 变对 | %d ｜ 变错 | %d |" % (len(r["became_right"]), len(r["became_wrong"])))
    if r["only_before"] or r["only_after"]:
        print("| 题集差异 | 仅前 %d ｜ 仅后 %d |"
              % (len(r["only_before"]), len(r["only_after"])))
    print()
    for k, label in (("unexpected_regressions", "未预料的退步（最该查）"),
                     ("missed", "预测了但没变（说明它不懂这个参数）"),
                     ("hit", "命中")):
        if r[k]:
            print("%s：%s" % (label, ", ".join(r[k][:args.show_ids])))
    if args.write:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("\n已追加 %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
