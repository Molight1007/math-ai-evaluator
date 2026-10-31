"""池空挽救上限评估床（δ=0，纯离线回放）。

问题：池空时（`predicted = "未给出有效解答。"`）现在直接判 0，并走 4.6 重写。
但被 4.1/4.2/4.4 判死的候选里，**答案本身可能是对的** —— 判死理由是"证明有洞"，
不是"答案错"。本脚本量的是：如果池空时回退到"被判死候选的多数票答案"，
能救回多少题、会不会引入新的错答。

判分口径一律用 `run_eval__scoring.answers_match`（与评测同源），不另写比较逻辑。

用法：
    python replay_pool_salvage.py --srv D:/mp_tmp/srv_oct --ab D:/mp_tmp/ab_dump2.json

★ 放在仓库根目录：`tools/` 不许 import `run_eval__scoring`（分层门禁），
  且这是"评估床"性质，与 `replay_calc_gate.py` / `replay_reasoning_projection.py` 同级。
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys

from run_eval__scoring import answers_match

# ★ 两套比较口径必须分开（否则 δ=0 不成立）：
#   · 聚类 = **系统内部**怎么判两个候选答案相同 → `_are_answers_equivalent`
#     （agent 层既有实现，含 `\boxed{}` 剥壳 + SymPy 兜底）；
#   · 判分 = **评测**怎么判预测是否等于 gold → `answers_match`（判分器权威）。
#   实现时系统只能用前者；后者只在本脚本里当标尺用。
from agent.verifier__cluster import _are_answers_equivalent


# ---------------------------------------------------------------- 数据读取

_EMPTY_PRED = ("未给出有效解答", "")


def _load_srv(pattern: str) -> list:
    """服务器历史 jsonl（10 月 81 条那批，字段名与新版略有差异）。"""
    out = []
    for f in sorted(glob.glob(pattern)):
        for line in open(f, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            d = r.get("diag") or r.get("diagnostics") or {}
            errs = d.get("pool_empty_errors") or []
            if not errs:
                continue
            out.append({
                "src": os.path.basename(f),
                "id": r.get("id") or r.get("question_id"),
                "gold": str(r.get("gold") or ""),
                "pred": str(r.get("predicted") or ""),
                "errs": errs,
            })
    return out


def _load_ab(path: str) -> list:
    """本轮 A/B 的导出结构（两条臂各一份，含候选 id）。"""
    out = []
    if not path or not os.path.isfile(path):
        return out
    d = json.load(open(path, encoding="utf-8"))
    for arm, rows in d.items():
        for r in rows:
            errs = r.get("errs") or r.get("pool_empty") or []
            if not errs:
                continue
            out.append({
                "src": f"ab/{arm}",
                "id": r["id"],
                "gold": str(r.get("gold") or ""),
                "pred": str(r.get("pred") or ""),
                "errs": errs,
            })
    return out


# ---------------------------------------------------------------- 投票

def _dedup(errs: list) -> list:
    """同一候选被 4.1 与 4.4 双杀时会出现两条 —— 按候选 id 去重。

    ★ 必须去重：否则"被多个阶段判死"的候选会被算成多票，系统性抬高票数。
    """
    seen, out = set(), []
    for e in errs:
        key = str(e.get("id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _answers(errs: list) -> list:
    """取被判死候选的答案原文（保序）。空答案/占位符不计票。"""
    vals = []
    for e in _dedup(errs):
        a = str(e.get("answer") or "").strip()
        if not a or a in _EMPTY_PRED or a.startswith("未给出"):
            continue
        vals.append(a)
    return vals


def _vote(answers: list, min_share: float) -> tuple:
    """按 `answers_match` 聚成等价类后投票，返回 (得票答案, 票数, 总票数)。

    ★ 用 `_are_answers_equivalent` 而不是字符串相等：`x - 4` 与 `\\boxed{x - 4}`
      在系统口径下是同一个答案，按字面分会把票拆散。
    """
    if not answers:
        return None, 0, 0
    clusters = []                       # [(代表答案, 票数)]
    for a in answers:
        for i, (rep, n) in enumerate(clusters):
            if _are_answers_equivalent(None, a, rep) or _are_answers_equivalent(None, rep, a):
                clusters[i] = (rep, n + 1)
                break
        else:
            clusters.append((a, 1))
    clusters.sort(key=lambda x: -x[1])
    rep, n = clusters[0]
    if n / len(answers) < min_share:    # 没有足够共识 ⇒ 不挽救
        return None, n, len(answers)
    return rep, n, len(answers)


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--srv", default="D:/mp_tmp/srv_oct/*.jsonl")
    ap.add_argument("--ab", default="D:/mp_tmp/ab_dump2.json")
    ap.add_argument("--show", type=int, default=25)
    args = ap.parse_args()

    rows = _load_srv(args.srv) + _load_ab(args.ab)
    print(f"池空记录：{len(rows)} 条（历史 {len(rows) - len(_load_ab(args.ab))} + 本轮 {len(_load_ab(args.ab))}）\n")

    # 现状核对：池空记录的 predicted 必须真的是空
    bad = [r for r in rows if not str(r["pred"]).startswith("未给出")]
    if bad:
        print(f"⚠ {len(bad)} 条记录的 predicted 不是空串，可能不是真池空：")
        for r in bad[:5]:
            print(f"    {r['src']} {r['id']} pred={r['pred'][:40]!r}")

    print(f"{'来源':<26}{'题号':<28}{'票':>7}{'共识':>7}  {'挽救':<6}{'gold':<22}得票答案")
    print("-" * 128)

    stat = collections.Counter()
    for share in (0.5, 0.6, 2 / 3):
        stat[f"rescue_ok_{share}"] = 0
        stat[f"rescue_bad_{share}"] = 0
        stat[f"nocon_{share}"] = 0

    for r in rows:
        ans = _answers(r["errs"])
        rep, n, tot = _vote(ans, 0.5)
        ok = rep is not None and answers_match(rep, r["gold"])
        stat["total"] += 1
        stat["has_ans"] += 1 if ans else 0
        for share in (0.5, 0.6, 2 / 3):
            rr, nn, tt = _vote(ans, share)
            if rr is None:
                stat[f"nocon_{share}"] += 1
            elif answers_match(rr, r["gold"]):
                stat[f"rescue_ok_{share}"] += 1
            else:
                stat[f"rescue_bad_{share}"] += 1
        if len(ans) == 0:
            continue
        mark = "✓救对" if ok else ("✗救错" if rep else "共识不足")
        print(f"{r['src'][:25]:<26}{str(r['id'])[:27]:<28}{n:>3}/{tot:<3}{n/max(tot,1):>6.0%}  "
              f"{mark:<6}{r['gold'][:20]:<22}{str(rep)[:36] if rep else '—'}")

    print()
    print("=" * 70)
    print(f"总池空题 {stat['total']} 条，其中被判死候选里**有可用答案**的 {stat['has_ans']} 条")
    for share in (0.5, 0.6, 2 / 3):
        ok, bd, nc = (stat[f"rescue_ok_{share}"], stat[f"rescue_bad_{share}"],
                      stat[f"nocon_{share}"])
        print(f"  共识阈值 ≥{share:.0%}：救对 {ok} · 救错 {bd}（维持 0，无损失）"
              f" · 共识不足 {nc}  ⇒ 净增 {ok:+d} 题（基线 0）")
    print()
    print("★ 池空题当前得分恒为 0，输出任何答案都不会让分数更低 ⇒ 救对是纯收益，")
    print("  「救错」只是维持 0。真正的约束不是准确率，而是**别丢掉 4.6 的重写机会**。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
