# -*- coding: utf-8 -*-
"""A/B 对比工具（D6 三把钥匙用）：比较两份评测结果，给出逐题变化。

用法：
    python tools/compare_ab.py results/ab_baseline.jsonl results/ab_lemma.jsonl
    python tools/compare_ab.py results/ab_baseline.jsonl results/ab_lemma.jsonl --detail
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from run_eval import answers_match  # noqa: E402


def load(path: str) -> dict[str, dict]:
    rows = {}
    if not os.path.exists(path):
        print(f"[error] 文件不存在: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            rows[str(r.get("id", ""))] = r
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B 评测对比")
    ap.add_argument("baseline")
    ap.add_argument("variant")
    ap.add_argument("--detail", action="store_true", help="逐题列出变化")
    args = ap.parse_args()

    base = load(args.baseline)
    var = load(args.variant)
    common = sorted(set(base) & set(var))
    print(f"基线 {len(base)} 题 vs 变体 {len(var)} 题；共同 {len(common)} 题")

    def acc(rows: dict) -> tuple[int, int]:
        scored = [r for r in rows.values() if r.get("correct") is not None]
        return sum(1 for r in scored if r["correct"]), len(scored)

    b_c, b_t = acc(base)
    v_c, v_t = acc(var)
    print(f"\n正确率  基线 {b_c}/{b_t} = {b_c / b_t:.1%}" if b_t else "基线无得分题")
    print(f"        变体 {v_c}/{v_t} = {v_c / v_t:.1%}" if v_t else "变体无得分题")
    delta = (v_c / v_t - b_c / b_t) if (b_t and v_t) else 0
    print(f"        差值 {delta:+.1%}")

    improved = [i for i in common if not base[i].get("correct") and var[i].get("correct")]
    regressed = [i for i in common if base[i].get("correct") and not var[i].get("correct")]
    print(f"\n变体挽回 {len(improved)} 题，新引入错误 {len(regressed)} 题")

    if args.detail and (improved or regressed):
        for i in improved:
            print(f"\n  ↑ 挽回 {i}")
            print(f"    gold: {str(base[i].get('gold'))[:60]}")
            print(f"    变体: {str(var[i].get('predicted'))[:60]}")
        for i in regressed:
            print(f"\n  ↓ 回退 {i}")
            print(f"    gold: {str(base[i].get('gold'))[:60]}")
            print(f"    基线: {str(base[i].get('predicted'))[:60]}")
            print(f"    变体: {str(var[i].get('predicted'))[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
