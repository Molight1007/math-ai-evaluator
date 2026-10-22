# -*- coding: utf-8 -*-
"""泄漏筛查（RRSI 内化，2026-10-22）。

为什么需要它
============
RRSI（arXiv:2609.24972 §3.3）把「把 evolve 集的答案/题面特征编码进 harness」
称为 **leakage**，并要求在**评测之前**由 critic 读 diff 直接拒掉这类改动——
理由是一旦这类候选拿到虚高的 evolve 分，后面几轮都会被它吸引。

本项目已有一份同构的实证：K11「蓝图/子目标锁死具体值」占错题根因 41/99，
本质就是把某道题的答案写进了通用机制里。以前只能靠事后逐题归因发现，
本工具把它变成**提交前的一次静态扫描**。

判据（四类命中）
----------------
1. ``TASK_ID``  —— 出现具体题号（official112-073 / imo-bench-…-075 / q<8hex>）
2. ``GOLD``     —— 出现某题标准答案的原文（长度 ≥6，避免 "1"/"x" 这类通用值）
3. ``CONST``    —— 出现只属于极少数题目的长常量（≥4 位数字）
4. ``BRANCH``   —— 形如 ``if <题号>`` / ``== "<题号>"`` 的单题分支（惰性机械）

用法
----
    # 扫工作区相对某提交的改动（默认 HEAD，即未提交改动）
    python tools/leakage_scan.py --base HEAD

    # 扫指定文件（提交前自查）
    python tools/leakage_scan.py --files agent/math_check_gate.py

    # CI 用：命中即非零退出
    python tools/leakage_scan.py --base origin/ma --strict

只依赖标准库（tools 层不得反向依赖 agent）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = os.path.join(ROOT, "题库", "official112_本地测试题库", "official112_full.jsonl")

# 题号形态：覆盖本项目用过的全部命名
_TASK_ID_RES = (
    (re.compile(r"official112-\d{3}"), "official112 题号"),
    (re.compile(r"imo-bench-[A-Za-z_]+-\d{3}"), "imo-bench 题号"),
    (re.compile(r"number_theory-\d{3}"), "number_theory 题号"),
    (re.compile(r"\bq[0-9a-f]{8}\b"), "题号哈希"),
)

# 单题分支：if/elif 条件里直接写题号
_BRANCH_RE = re.compile(
    r"(?:if|elif)\b[^\n]{0,80}?(official112-\d{3}|q[0-9a-f]{8}|number_theory-\d{3})")

# 常量：≥4 位数字（年份类如 2026 常见，单独降级为提示）
_CONST_RE = re.compile(r"(?<![\d.])(\d{4,})(?![\d.])")
_BENIGN_CONSTS = {"2025", "2026", "2027", "1000", "1024", "2048", "4096",
                  "8192", "3600", "1200", "1800", "9999"}

MAX_HITS_PER_KIND = 20


def _load_bank(path: str = BANK):
    """读题库 → (gold 答案列表, {常量: 覆盖题数})。

    只收**足够长**的 gold（≥6 字符）：``1`` / ``x`` 这类答案在任何代码里都会
    偶然出现，拿它们做泄漏判据只会制造假阳性。
    """
    golds: list = []
    const_freq: Counter = Counter()
    if not os.path.isfile(path):
        return golds, const_freq
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            ans = str(d.get("answer") or "").strip()
            # ★ 只收「足够独特」的 gold：含 4 位以上数字，或长到 20 字符以上。
            #   否则 `$2-2m$` / `$\frac{1}{2}$` 这类通用符号式会误报（实测会命中
            #   任何含分数的代码）。
            if re.search(r"\d{4,}", ans) or len(ans) >= 20:
                golds.append((str(d.get("id") or "?"), ans))
            for c in set(_CONST_RE.findall(str(d.get("question") or ""))):
                const_freq[c] += 1
    return golds, const_freq


def _collect_diff(base: str, files: list) -> str:
    """取待检查的文本：git diff（只取新增行，删掉的代码不会造成泄漏）。"""
    if files:
        chunks = []
        for p in files:
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    chunks.append(fh.read())
            except OSError as e:
                chunks.append("# 读取失败 %s: %s" % (p, e))
        return "\n".join(chunks)
    try:
        out = subprocess.run(
            ["git", "diff", "--unified=0", base, "--", "."],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120)
    except Exception as e:  # noqa: BLE001
        return "# git diff 失败: %s" % e
    # 只保留新增行（以 + 开头且不是 +++ 头）
    added = [ln[1:] for ln in (out.stdout or "").splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    return "\n".join(added)


def scan(text: str, golds: list, const_freq: Counter) -> dict:
    """对文本做四类扫描，返回 {命中类别: [明细]}。"""
    hits: dict = {"TASK_ID": [], "GOLD": [], "CONST": [], "BRANCH": []}
    if not text.strip():
        return hits

    for rx, label in _TASK_ID_RES:
        for m in rx.finditer(text):
            hits["TASK_ID"].append({"match": m.group(0), "kind": label})

    for m in _BRANCH_RE.finditer(text):
        hits["BRANCH"].append({"match": m.group(1),
                               "context": m.group(0)[:100]})

    norm = text.replace("\r", "")
    for tid, ans in golds:
        if ans in norm:
            hits["GOLD"].append({"task": tid, "answer": ans[:60]})

    for m in _CONST_RE.finditer(text):
        c = m.group(1)
        if c in _BENIGN_CONSTS or len(c) < 5:
            continue
        # 只属于**唯一**一道题的长常量才算「单题特有」。
        # （初期用 ≤2 时误报严重：注释里的示例数字 `3000` 恰好出现在 2 道题里。）
        if const_freq.get(c, 0) == 1:
            hits["CONST"].append({"match": c, "tasks_containing": 1})

    for k in hits:
        hits[k] = hits[k][:MAX_HITS_PER_KIND]
    return hits


def verdict(hits: dict) -> tuple:
    """返回 (等级, 说明)。

    ★ 只有三类**硬泄漏**决定等级：题号 / 单题分支 / 答案原文。
      ``CONST``（单题特有常量）只作提示 —— 实测假阳性高（注释里的示例数字、
      通用配置常量都会命中），让它决定等级会逼人忽略告警。
    """
    hard = len(hits["TASK_ID"]) + len(hits["BRANCH"]) + len(hits["GOLD"])
    if hard:
        return "LEAK", "命中 %d 处硬泄漏（题号/单题分支/答案原文）" % hard
    if hits["CONST"]:
        return "CLEAN", "未发现硬泄漏（%d 处单题常量仅作提示）" % len(hits["CONST"])
    return "CLEAN", "未发现泄漏迹象"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="改动泄漏筛查（题号/答案/单题常量）")
    ap.add_argument("--base", default="HEAD", help="对比的提交（默认 HEAD）")
    ap.add_argument("--files", nargs="*", default=None, help="直接扫这些文件")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true", help="LEAK 时非零退出")
    ap.add_argument("--bank", default=BANK, help="题库 jsonl 路径")
    args = ap.parse_args(argv)

    golds, const_freq = _load_bank(args.bank)
    text = _collect_diff(args.base, args.files)
    hits = scan(text, golds, const_freq)
    level, msg = verdict(hits)

    if args.json:
        print(json.dumps({"level": level, "message": msg, "hits": hits,
                          "n_gold_loaded": len(golds)},
                         ensure_ascii=False, indent=2))
    else:
        print("泄漏筛查：%s —— %s" % (level, msg))
        for k in ("TASK_ID", "BRANCH", "GOLD", "CONST"):
            if not hits[k]:
                continue
            print("  [%s] %d 处" % (k, len(hits[k])))
            for h in hits[k][:6]:
                print("    - %s" % json.dumps(h, ensure_ascii=False)[:120])
    if args.strict and level == "LEAK":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
