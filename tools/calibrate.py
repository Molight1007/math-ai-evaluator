# -*- coding: utf-8 -*-
"""δ 标定 —— 用**同一版本的重复评测**量出噪声带，写 `gates.json`。

为什么必须有它
==============
四道门的第一道是 `S' ≥ S* − δ`。没有 δ，这道门只能拒绝一切候选（这是刻意的，
见 `contracts/selection.py`）。而 δ 不是拍出来的：温度 0.3、单题 ~1087s，
同样代码重跑一遍分数就会动，得先量出「动多少算正常」。

公式（RRSI `calibrate.py`）
==========================
    δ = z × sd(null ΔS)

  · `null ΔS` = **同一版本**两次评测的分数差。若两次独立，`sd(ΔS) = √2 × sd(单次)`。
  · `z` 默认 2.0 ⇒ 未改动的 harness 约 97.5% 概率满足 `S ≥ S* − δ`。

两条路径：

1. **多次重复**（推荐）：给 N 份基线分数（N ≥ 2）⇒ `sd(单次) = stdev(scores)`；
2. **只有一份**：给每题的 k 次 trial ⇒ 在**题内**重采样 bootstrap 出均值的散布。
   诚实提示：这条路把「题目难度差异」当成噪声源，δ 会偏大（更保守），
   所以输出里会标 `method=bootstrap`，别和多次重复的 δ 混着比。

不会替你决定 β/γ
================
`β0 / β1 / w_s / w_c / w_n` 是**成本规则**的参数，与本模块算的 δ 无关。
默认照抄 RRSI coding 域实参，并在文件里记 `beta_source="rrsi-borrowed"`
—— 也就是说：δ 是实测的，成本权重还是借的，读报告时不能混为一谈。

用法
====
    # 五次重复基线
    python tools/calibrate.py --scores 34.0 33.5 35.2 34.8 33.9 --write

    # 只有一次跑，但每题跑了 k=2 次
    python tools/calibrate.py --trials trials.json --k 2 --write
    # trials.json: {"q1": [1, 0], "q2": [1, 1], ...}

    # 只看不写
    python tools/calibrate.py --scores 34 34.6
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from contracts.trials import aggregate  # noqa: E402

CAL_PATH = os.path.join(_ROOT, "results", "_calibration", "gates.json")
CAL_SCHEMA = "gates/1"

# 成本权重仍照抄 RRSI coding 域（文件里会标 beta_source，不许当成我们自己的标定）
BETA_DEFAULTS = {"beta0_pct": 10.0, "beta1_pct_per_pp": 44.5,
                 "w_s": 0.0, "w_c": 1.0, "w_n": 0.0}


def calibrate_repeats(scores, z: float = 2.0) -> dict:
    """多次重复基线 ⇒ δ = z × sd × √2。"""
    vals = [float(s) for s in scores]
    if len(vals) < 2:
        raise ValueError("至少要 2 次重复评测才能算 sd（只有一份时改用 --trials）")
    sd = statistics.stdev(vals)
    return {"method": "repeats", "n_repeats": len(vals),
            "s_star": round(statistics.fmean(vals), 4),
            "sd_single": round(sd, 4),
            "delta_pp": round(z * sd * (2 ** 0.5), 4),
            "z": z}


def calibrate_bootstrap(rewards: dict, k: int, z: float = 2.0,
                        n_boot: int = 1000, seed: int = 0) -> dict:
    """单次评测 + 每题 k 次 ⇒ 题内重采样 bootstrap 出均值的散布。"""
    base = aggregate(rewards, k)
    if base["n_scored"] < 2:
        raise ValueError("可计分题数 < 2，无法 bootstrap")
    tids = [t for t, r in base["tasks"].items() if not r["infra"]]
    per_task = {t: (base["tasks"][t]["reward_sum"] or 0.0) / k for t in tids}
    rng = random.Random(seed)
    means = []
    for _ in range(int(n_boot)):
        pick = [per_task[rng.choice(tids)] for _ in tids]
        means.append(sum(pick) / len(pick))
    sd = statistics.stdev(means)
    return {"method": "bootstrap", "n_repeats": 1, "n_boot": int(n_boot),
            "seed": int(seed), "s_star": round(base["score_pct"], 4),
            "sd_single": round(sd, 4),
            "delta_pp": round(z * sd * (2 ** 0.5), 4), "z": z,
            "note": "题内重采样把难度差异也算进噪声 ⇒ δ 偏保守"}


def build_doc(cal: dict, beta: dict = None) -> dict:
    b = dict(BETA_DEFAULTS, **(beta or {}))
    doc = {"schema": CAL_SCHEMA}
    doc.update(cal)
    doc.update(b)
    doc["source"] = "measured"
    doc["beta_source"] = "rrsi-borrowed"
    doc["measured_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    doc["note"] = ("δ 来自本项目基线实测（%s）；β/γ 仍照抄 RRSI coding 域，"
                   "两者不可混为一谈" % cal["method"])
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="δ 标定（写 gates.json）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--scores", nargs="+", help="N 份同版本基线分数（pp），N ≥ 2")
    g.add_argument("--trials", help="JSON：{题号: [trial...]}（单次评测、每题 k 次）")
    ap.add_argument("--k", type=int, default=2, help="每题试次（--trials 时用）")
    ap.add_argument("--z", type=float, default=2.0)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--beta0", type=float, default=None)
    ap.add_argument("--beta1", type=float, default=None)
    ap.add_argument("--out", default=CAL_PATH)
    ap.add_argument("--write", action="store_true", help="写文件（不加只打印）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的标定")
    args = ap.parse_args(argv)

    try:
        if args.scores:
            cal = calibrate_repeats(args.scores, z=args.z)
        else:
            with open(args.trials, encoding="utf-8") as fh:
                rewards = json.load(fh)
            cal = calibrate_bootstrap(rewards, args.k, z=args.z,
                                      n_boot=args.n_boot, seed=args.seed)
    except (ValueError, OSError) as e:
        print("❌ %s" % e)
        return 2

    beta = {}
    if args.beta0 is not None:
        beta["beta0_pct"] = args.beta0
    if args.beta1 is not None:
        beta["beta1_pct_per_pp"] = args.beta1
    doc = build_doc(cal, beta)

    print("方法      %s（n=%d）" % (cal["method"], cal["n_repeats"]))
    print("S*        %.4f pp" % doc["s_star"])
    print("sd(单次)  %.4f pp" % doc["sd_single"])
    print("δ = z×sd×√2 = %.2f × %.4f × 1.414 = **%.2f pp**"
          % (doc["z"], doc["sd_single"], doc["delta_pp"]))
    print("β/γ       照抄 RRSI（beta_source=%s）" % doc["beta_source"])

    if not args.write:
        print("\n（未写文件；加 --write 落盘到 %s）" % args.out)
        return 0
    if os.path.exists(args.out) and not args.force:
        print("\n已存在 %s ⇒ 不覆盖（要重写加 --force）" % args.out)
        return 1
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("\n已写 %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
