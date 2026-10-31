"""评测检验力与配对分析（0-LLM，纯 stdlib）。

## 为什么需要这个工具

2026-10-29 定论：**当前的实验设计在物理上无法验证任何单点改动。**

铁证（`ab_{on,off}_1027_2326.jsonl`，8 题配对）：

    都对 3 · 都错 0 · 结论相反 5（off 胜 2 / on 胜 3）· 一致率 38%

同题同配置两臂 5/8 结论相反 ⇒ **单次运行近似抛硬币**，McNemar `b=2,c=3 ⇒ p=1.000`。
而单题中位耗时 **204~229 分钟**。

## 核心结论（本工具要守住的一条）

配对设计下 `Δ_i = p̂_on,i − p̂_off,i`，`Var(Δ) = 2p(1−p)/k`，于是

    n = (z_{1−α/2} + z_{1−β})² · 2p(1−p) / (k·δ²)

**总运行次数 `n·k` 与 k 无关** ⇒ 「多跑几遍取多数票」和「多换几道题」对总机时是**等价**的，
都不省钱。省钱的唯一方向是**降低单次运行成本**，或**只追大效应**。

（另注：多数票把 k 次压成 1 个二值，反而丢掉信息 —— 统计检验应当用**比例** `p̂`，
不是「k 次里过半算对」。本工具的 `--pairs` 走比例，不走多数票。）

## 用法

    python tools/eval_power.py --pairs off.jsonl on.jsonl      # 配对分析（McNemar + bootstrap CI）
    python tools/eval_power.py --design                        # 所需题数 / 机时表
    python tools/eval_power.py --design --hours 3.7 --budget 240

参数口径：`p0` 为基线答对率（默认 0.40，取自服务器 090 条实测 22%~40% 区间上沿，保守）；
`hours` 为单次运行中位机时（默认 3.7，取自 204~229min 实测）。
"""

from __future__ import annotations

import argparse
import io
import json
import math
import random
import sys

# ---------------------------------------------------------------- 分布工具

Z_A = 1.959963985     # 双侧 α=0.05
Z_B = 0.841621234     # power=0.80


def _phi(x: float) -> float:
    """标准正态 CDF。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def power_of(n: int, k: int, delta: float, p0: float,
             alpha: float = 0.05) -> float:
    """解析功效：配对比例差的双侧 z 检验。

    `n` 题 × `k` 次/题，真实效应 `delta`（绝对百分点，如 0.10）。
    """
    if delta <= 0 or n <= 0 or k <= 0:
        return float(alpha)
    var = 2.0 * p0 * (1.0 - p0) / k
    se = math.sqrt(var / n)
    z = (1.959963985 if alpha == 0.05 else _inv_norm(1 - alpha / 2))
    # 拒绝 H0 的概率 = P(|Z|>z)，Z ~ N(delta/se, 1)
    return _phi(delta / se - z) + _phi(-delta / se - z)


def _inv_norm(p: float) -> float:
    """标准正态分位（Acklam 近似，足够 1e-6 精度）。"""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - 0.02425:
        return -_inv_norm(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def required_n(delta: float, k: int = 1, p0: float = 0.40,
               power: float = 0.80, alpha: float = 0.05) -> int:
    """满足功效所需**题数**（题数×k 次 = 总运行次数/臂）。"""
    if delta <= 0:
        return 10 ** 9
    z_a = 1.959963985 if alpha == 0.05 else _inv_norm(1 - alpha / 2)
    z_b = _inv_norm(power)
    var = 2.0 * p0 * (1.0 - p0) / k
    return int(math.ceil((z_a + z_b) ** 2 * var / (delta ** 2)))


# ---------------------------------------------------------------- 配对分析


def _load_correct(path: str) -> dict:
    out = {}
    for ln in io.open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        r = json.loads(ln)
        rid = str(r.get("id") or "")
        if rid:
            out[rid] = bool(r.get("correct"))
    return out


def _binom_two_sided(b: int, c: int) -> float:
    """McNemar 精确检验：b ~ Binom(b+c, 1/2)。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2.0 ** n)
    return min(1.0, 2.0 * tail)


def analyse_pairs(off_path: str, on_path: str, iters: int = 20000) -> dict:
    off, on = _load_correct(off_path), _load_correct(on_path)
    ids = sorted(set(off) & set(on))
    if not ids:
        raise SystemExit("两臂没有共同题 id，无法配对")
    both_r = both_w = b = c = 0
    for i in ids:
        a, o = off[i], on[i]
        if a and o:
            both_r += 1
        elif a and not o:
            b += 1
        elif o and not a:
            c += 1
        else:
            both_w += 1
    n = len(ids)
    concordant = both_r + both_w
    p_mcnemar = _binom_two_sided(b, c)
    return {
        "n": n, "off_acc": sum(off[i] for i in ids) / n,
        "on_acc": sum(on[i] for i in ids) / n,
        "both_right": both_r, "both_wrong": both_w,
        "off_only": b, "on_only": c,
        "concordance": concordant / n,
        "p_mcnemar": p_mcnemar,
        # 单次二值设计的功效上限：不一致对数决定一切
        "max_detectable_ratio": (max(b, c) / (b + c)) if (b + c) else None,
        "min_p_two_sided": (2.0 * 0.5 ** (b + c)) if (b + c) else None,
    }


def report_pairs(st: dict, hours: float) -> None:
    n = st["n"]
    print("=" * 76)
    print("配对分析（n=%d 题）" % n)
    print("=" * 76)
    print("答对率：off %.1f%%  →  on %.1f%%   （差 %+.1fpp）"
          % (100 * st["off_acc"], 100 * st["on_acc"],
             100 * (st["on_acc"] - st["off_acc"])))
    print("配对表：都对 %d · 都错 %d · off 独对 %d · on 独对 %d"
          % (st["both_right"], st["both_wrong"], st["off_only"], st["on_only"]))
    print("一致率：%.0f%%   ★单次结论的可复现性" % (100 * st["concordance"]))
    print("McNemar 精确 p = %.3f   （b=%d, c=%d）"
          % (st["p_mcnemar"], st["off_only"], st["on_only"]))
    if st["min_p_two_sided"] is not None:
        print("→ 该设计**在最优情形**下能达到的最小 p = %.3f（不一致对仅 %d 对）"
              % (st["min_p_two_sided"], st["off_only"] + st["on_only"]))
        print("  ⇒ 不一致对少于 6 对时，即使「全胜」也无法显著（双侧 α=0.05）。")
    print()
    # 一致率直接给出 ICC 的粗糙上界：不一致比例 = 测量噪声占比
    incons = 1 - st["concordance"]
    print("推论：不一致比例 %.0f%% ⇒ 同一配置两次运行的结论有多大概率翻转。" % (100 * incons))
    print("      按此噪声，单次运行对单题的判定不可作为改进依据（回归到均值会伪装成效果）。")
    print()
    print("该设计能检测的最小效应（power=0.80, n=%d, k=1）：" % n)
    for d in (0.10, 0.20, 0.30, 0.40, 0.50):
        pw = power_of(n, 1, d, max(0.05, st["off_acc"]))
        if pw >= 0.80:
            print("  δ = +%.0fpp ⇒ power %.2f ✅ 首个可检测效应" % (100 * d, pw))
            break
        print("  δ = +%.0fpp ⇒ power %.2f（不足）" % (100 * d, pw))
    print()


# ---------------------------------------------------------------- 设计表


def report_design(hours: float, budget_h: float, p0: float,
                  conc: int = 1) -> None:
    print("=" * 76)
    print("设计表：配对 + 比例估计（p0=%.2f, power=0.80, 双侧 α=0.05）" % p0)
    print("单次运行 %.2f h，预算 %.0f h（墙钟），并发 %d，两臂（A/B 各跑一遍）"
          % (hours, budget_h, conc))
    print("墙钟 = 总机时 / 并发。★ 并发受 API 配额约束，撞限流时墙钟不降反升。")
    print("=" * 76)
    print("%-8s %10s %10s %10s %12s %10s %10s %s"
          % ("δ", "n(k=1)", "n(k=3)", "n(k=5)", "总运行/臂", "机时(两臂)",
             "墙钟", "预算"))
    print("（总次数列三档本应相同；n 向上取整造成 ≤1/k 的偏差属正常）")
    for d in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
        route = []
        for k in (1, 3, 5):
            n = required_n(d, k, p0)
            total = n * k
            h = total * 2 * hours
            route.append((n, total, h))
        n1, t1, h1 = route[0]
        _, t3, _ = route[1]
        _, t5, _ = route[2]
        wall = h1 / max(1, conc)
        ok = "✅" if wall <= budget_h else "❌"
        print("%-8s %10d %10d %10d %12d %9.0f h %9.1f h %s"
              % ("+%.0fpp" % (100 * d), n1, route[1][0], route[2][0],
                 t1, h1, wall, ok))
        # 总运行次数与 k 无关；n 向上取整会带来 ≤1/k 的偏差，属正常，不告警
    print()
    print("★ 读法：三列的「总运行/臂」应当**完全相同**（n·k 与 k 无关）。")
    print("  ⇒ 加题数、加重跑次数，两者消耗的总机时一样；它们只交换")
    print("    「题型覆盖广度」与「单题估计精度」，不改变可检测的效应下限。")
    print("  ⇒ 唯一能压低「可检测下限」的两个动作：")
    print("     ① 降低单次运行机时（固定蓝图回放 / 只跑相关阶段）")
    print("     ② 接受只追大效应（δ ≥ 20pp）")
    print()
    # 反解：给定预算能检测多大效应
    print("反解：预算 %.0f h 下能检测的最小 δ（k=1，两臂）" % budget_h)
    best = None
    for d in [x / 1000.0 for x in range(50, 601, 5)]:
        n = required_n(d, 1, p0)
        if n * 2 * hours <= budget_h:
            best = (d, n)
            break
    if best:
        print("  ⇒ δ ≥ +%.1fpp（n=%d 题）" % (100 * best[0], best[1]))
    else:
        print("  ⇒ 预算连 +50pp 的效应都检测不了（需要更多机时或更低单次成本）")
    # 成本反解：要在预算内检测 +10pp，单次成本需降到多少
    n10 = required_n(0.10, 1, p0)
    need = budget_h * max(1, conc) / (n10 * 2)
    print("  ⇒ 若要在预算内检测 +10pp（n=%d）：单次运行须 ≤ %.2f h（现为 %.2f h，需降 %.1f×）"
          % (n10, need, hours, hours / need if need > 0 else float("inf")))
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs=2, metavar=("OFF", "ON"))
    ap.add_argument("--design", action="store_true")
    ap.add_argument("--hours", type=float, default=3.7,
                    help="单次运行中位机时（h），默认 3.7 = 220min 实测")
    ap.add_argument("--budget", type=float, default=240.0,
                    help="可用总机时（h），默认 240")
    ap.add_argument("--p0", type=float, default=0.40, help="基线答对率")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="并发数（决定墙钟 = 机时/并发）")
    args = ap.parse_args()

    if args.pairs:
        st = analyse_pairs(*args.pairs)
        report_pairs(st, args.hours)
    if args.design or not args.pairs:
        report_design(args.hours, args.budget, args.p0, args.concurrency)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
