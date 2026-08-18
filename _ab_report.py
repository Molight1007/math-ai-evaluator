"""A/B 结果对比报告：比较两个 run_eval 结果 JSONL。

用法:
    python _ab_report.py --base outputs/ab_baseline.jsonl --exp outputs/ab_p1.jsonl

输出:
    - 总览：题数/判分题/正确/准确率/平均耗时（两版对比）
    - 逐题翻转：错→对（改进）/ 对→错（回退）
    - 分领域准确率对比
"""
import argparse
import json
import sys


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summary(rows):
    scored = [r for r in rows if r.get("correct") is not None]
    correct = sum(1 for r in scored if r["correct"])
    return {
        "total": len(rows),
        "scored": len(scored),
        "correct": correct,
        "accuracy": correct / len(scored) if scored else 0.0,
        "avg_elapsed": sum(r.get("elapsed_sec", 0) for r in rows) / max(len(rows), 1),
    }


def per_domain(rows):
    stat = {}
    for r in rows:
        if r.get("correct") is None:
            continue
        d = r.get("domain", "unknown")
        s = stat.setdefault(d, [0, 0])
        s[0] += 1
        s[1] += 1 if r["correct"] else 0
    return {d: (s[1] / s[0], s[0], s[1]) for d, s in stat.items()}


def main():
    ap = argparse.ArgumentParser(description="A/B 结果对比")
    ap.add_argument("--base", required=True, help="基线结果 JSONL")
    ap.add_argument("--exp", required=True, help="实验结果 JSONL")
    args = ap.parse_args()

    base, exp = load(args.base), load(args.exp)
    bs, es = summary(base), summary(exp)

    print("=" * 62)
    print("A/B 总览")
    print("=" * 62)
    print(f"{'指标':<14}{'基线':>12}{'实验':>12}{'Δ':>10}")
    print("-" * 62)
    print(f"{'题数':<14}{bs['total']:>12}{es['total']:>12}")
    print(f"{'判分题':<14}{bs['scored']:>12}{es['scored']:>12}")
    print(f"{'正确数':<14}{bs['correct']:>12}{es['correct']:>12}{es['correct']-bs['correct']:>+10}")
    print(f"{'准确率':<14}{bs['accuracy']:>12.2%}{es['accuracy']:>12.2%}{es['accuracy']-bs['accuracy']:>+10.2%}")
    print(f"{'平均耗时':<14}{bs['avg_elapsed']:>10.1f}s{es['avg_elapsed']:>10.1f}s{es['avg_elapsed']-bs['avg_elapsed']:>+8.1f}s")

    # 逐题翻转
    bmap = {r.get("id"): r for r in base}
    flips_good, flips_bad = [], []
    for r in exp:
        b = bmap.get(r.get("id"))
        if b is None:
            continue
        bc, ec = b.get("correct"), r.get("correct")
        if bc is not None and ec is not None and bc != ec:
            (flips_good if ec else flips_bad).append(
                (r.get("id"), b.get("domain"), b.get("gold"), b.get("predicted"), r.get("predicted")))

    print()
    print(f"翻转 错→对（改进）: {len(flips_good)} 题")
    for pid, dom, gold, p_base, p_exp in flips_good:
        print(f"  + {pid} [{dom}] gold={gold!r}\n      基线={p_base!r}\n      实验={p_exp!r}")
    print(f"翻转 对→错（回退）: {len(flips_bad)} 题")
    for pid, dom, gold, p_base, p_exp in flips_bad:
        print(f"  - {pid} [{dom}] gold={gold!r}\n      基线={p_base!r}\n      实验={p_exp!r}")

    # 分领域
    print()
    print("分领域准确率")
    bd, ed = per_domain(base), per_domain(exp)
    print(f"{'领域':<16}{'基线':>14}{'实验':>14}{'Δ':>10}")
    print("-" * 62)
    for d in sorted(set(bd) | set(ed)):
        b, e = bd.get(d), ed.get(d)
        bs_s = f"{b[2]}/{b[1]}={b[0]:.0%}" if b else "-"
        es_s = f"{e[2]}/{e[1]}={e[0]:.0%}" if e else "-"
        delta = (e[0] - b[0]) if b and e else 0
        print(f"{str(d)[:14]:<16}{bs_s:>14}{es_s:>14}{delta:>+10.0%}")


if __name__ == "__main__":
    main()
