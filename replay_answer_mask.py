#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""2.6 题意理解「结果值」掩码的离线评估床（δ=0，纯函数回放，零 LLM 成本）。

用法（服务器上跑，那里才有真实产物）：
    .venv/bin/python replay_answer_mask.py \
        --bank 题库/official112_full.jsonl 题库/omni8_20261027.jsonl \
        --data-dir results --since 20261015

做什么：
    遍历 `<data-dir>/<run>/<qid>/01_understanding.json`，取出
    `problem_goal.terminal_state` / `answer_slot`，用**原题题面**（按
    `qid = "q"+md5(problem)[:8]` 从题库反查）作白名单，喂给
    `agent.value_mask.mask_result_values`，输出掩码前后对照 + 统计。

    纯函数 ⇒ 本床 δ=0，不是近似。改判据前后在同一批输入上跑，差异只来自判据。

本脚本**只观测**：不改任何文件、不调用 LLM、不产生淘汰。

判读要点：
    · `拦截` —— 终态里出现具体值且被掩（好）
    · `误伤` —— 掩掉了题面已给的量 / 结构描述（坏，需人工看）
    误伤目前靠「题面数字白名单」机械排除一轮，剩余仍要人眼过 `--show-all`。
"""
import argparse
import glob
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.value_mask import mask_result_values   # noqa: E402


def qid_of(problem: str) -> str:
    return "q" + hashlib.md5(str(problem or "").encode("utf-8")).hexdigest()[:8]


def load_bank(paths):
    """题库 → {qid: (id, problem)}。"""
    idx = {}
    for p in paths:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            q = r.get("question") or r.get("problem") or ""
            if q:
                idx[qid_of(q)] = (r.get("id"), q)
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", nargs="+", required=True)
    ap.add_argument("--data-dir", default="results")
    ap.add_argument("--since", default="", help="只统计 run 目录名前缀 >= 此值的（如 20261015）")
    ap.add_argument("--show-all", action="store_true", help="逐条打印（默认只打印有变化的）")
    args = ap.parse_args()

    bank = load_bank(args.bank)
    print("题库映射条目: %d" % len(bank))

    files = sorted(glob.glob(os.path.join(args.data_dir, "*", "q*", "01_understanding.json")))
    if args.since:
        files = [f for f in files
                 if os.path.basename(os.path.dirname(os.path.dirname(f))) >= args.since]
    print("样本: %d 份 01_understanding.json" % len(files))

    stat = {"total": 0, "no_bank": 0, "empty": 0, "masked": 0, "spans": 0}
    masked_rows, unmasked_rows = [], []

    for f in files:
        run = os.path.basename(os.path.dirname(os.path.dirname(f)))
        qid = os.path.basename(os.path.dirname(f))
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        pg = d.get("problem_goal") or {}
        ts = str(pg.get("terminal_state") or "")
        slot = str(pg.get("answer_slot") or "")
        if not ts and not slot:
            stat["empty"] += 1
            continue
        hit = bank.get(qid)
        if not hit:
            stat["no_bank"] += 1
            continue
        _tid, problem = hit
        stat["total"] += 1

        out_ts, n1 = mask_result_values(ts, problem)
        out_sl, n2 = mask_result_values(slot, problem)
        k = n1 + n2
        if k:
            stat["masked"] += 1
            stat["spans"] += k
            masked_rows.append((run, qid, _tid, n1, n2, ts, out_ts, slot, out_sl))
        else:
            unmasked_rows.append((run, qid, _tid, ts, slot))

    print()
    print("有题面可比对: %d" % stat["total"])
    print("  终态/答案槽为空 : %d" % stat["empty"])
    print("  题库里查不到题面: %d（qid 对不上，可能是题库版本不同）" % stat["no_bank"])
    print("  **被掩**         : %d 题（%d 处）"
          % (stat["masked"], stat["spans"]))
    if stat["total"]:
        print("  掩码覆盖率       : %.1f%%" % (100.0 * stat["masked"] / stat["total"]))

    print()
    print("=== 被掩明细（逐条人工判：是真泄漏还是误伤）===")
    for run, qid, tid, n1, n2, ts, out_ts, slot, out_sl in masked_rows:
        print("-" * 78)
        print("%s %s %s  终态掩%d / 槽掩%d" % (run, qid, tid, n1, n2))
        if n1:
            print("  前: " + ts[:200].replace("\n", " "))
            print("  后: " + out_ts[:200].replace("\n", " "))
        if n2:
            print("  槽前: " + slot[:120].replace("\n", " "))
            print("  槽后: " + out_sl[:120].replace("\n", " "))

    if args.show_all:
        print()
        print("=== 未触发掩码（抽检误伤漏网 / 无值终态）===")
        for run, qid, tid, ts, slot in unmasked_rows:
            print("-" * 78)
            print("%s %s %s" % (run, qid, tid))
            print("  终: " + ts[:200].replace("\n", " "))
            print("  槽: " + slot[:120].replace("\n", " "))


if __name__ == "__main__":
    main()
