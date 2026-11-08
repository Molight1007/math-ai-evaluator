# -*- coding: utf-8 -*-
"""评估床：三道门的**影子**影响，以及「命题可陈述」的干净口径。

## 为什么单独再写一张床

E28/E29 用「把 sorry 换成自动策略再编译」来分类。那张床判的是
**能不能证出**，错误文本里同时混着「命题非法」与「策略不够」，
只能靠 `classify()` 去拆。拆的结果是 ILLEGAL 56/151 = 37.1%，
但那个数字**依赖拆解规则**，而拆解规则本身在 E29 里被抽验打回过一次
（「有 unsolved goals 就判合法」误放 12 条）。

本床换一个不依赖拆解的判据：**保留 `:= by sorry` 原样编译**。
Lean 仍会 elaborate 命题（未定义符号、语法错、类型错照样报错），
但证明体被 sorry 直接结束 ⇒ 不会产生 unsolved goals。
所以：

    编译过 ⇒ 命题可陈述（STATABLE）
    编译错 ⇒ 命题写不出（ILLEGAL）

这一刀把「证明能力」完全排除在外，37% 到底站不站得住，可以直接量。

## 三道门（见 contracts/formal_sig_gate.py）

    门 B  命题非平凡     零成本，纯文本
    门 A  命题可陈述     需一次 Lean 编译（保留 by sorry）
    门 C  证明凭证       历史数据里没有「求解侧补完的证明体」⇒ 本床只报
                        NO_PROOF，不假装能验

★ 全是**影子**：只统计「若生效会砍谁」，不改任何生产行为。
★ E27/E29 铁律：分类结果必须配人工抽验。本床强制打印所有被拒条目的
  签名原文与首条错误，未抽验不得当结论报出去。

## 用法

    cd ~/mathpilot && source deploy/lean-env.sh
    .venv/bin/python replay_sig_gate.py /tmp/e21_license.json 20261015

★ 单文件 import Mathlib.Tactic 约 2.4s / 峰值 3.4GB ⇒ 必须串行。
"""
import collections
import json
import os
import sys
import tempfile
import time

from contracts.formal_sig_gate import (
    evaluate, classify_stated, with_strict_implicit)
from replay_lean_close import PRELUDE, collect_sigs, _run

OLD_RES = "/tmp/lean_close_res.json"
OUT = "/tmp/sig_gate_res.json"


def compile_stated(sig, tmp, idx):
    """保留 `by sorry` 原样编译。返回 (returncode, full_err)。

    ★ 2026-11-08（E39）：与生产 `_compile_stated` 共用 `with_strict_implicit()`
    —— 必须关 `autoImplicit`，否则未声明标识符被绑成全称量化隐式变量，命题
    写不成立也 rc=0。两份口径必须同步，本项目已因漂移吃过亏。
    `_run` 会在前面再补 PRELUDE（内含 import），故该 option 落在 import 之后。
    """
    ok, _first, full = _run(with_strict_implicit(sig.strip()),
                            os.path.join(tmp, "s%05d.lean" % idx))
    return (0 if ok else 1), full


def first_error(full_err):
    for ln in (full_err or "").splitlines():
        if "error" in ln and "warning" not in ln.lower():
            return ln.strip()[:220]
    return ""


def load_old():
    """上一版五分类，按 (qid, sig) 对齐，做交叉表。"""
    if not os.path.exists(OLD_RES):
        return {}
    try:
        rows = json.load(open(OLD_RES, encoding="utf-8"))
    except Exception:
        return {}
    return {(r.get("qid"), r.get("sig")): r.get("cat") for r in rows}


def main():
    index = sys.argv[1] if len(sys.argv) > 1 else "/tmp/e21_license.json"
    since = sys.argv[2] if len(sys.argv) > 2 else "20261015"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    sigs, n_q = collect_sigs(index, since)
    if limit:
        sigs = sigs[:limit]
    old = load_old()
    print("题次 %d，带 sorry 的形式签名 %d 条；上一版分类可用 %d 条" %
          (n_q, len(sigs), len(old)), flush=True)

    tmp = tempfile.mkdtemp(prefix="siggate_")
    t0 = time.time()
    res = []
    for i, item in enumerate(sigs):
        sig = item["sig"]
        v0 = evaluate(sig)                     # 零成本门（SHAPE / NONTRIVIAL）
        if v0["stage"] in ("SHAPE", "NONTRIVIAL", "ABSENT"):
            rc, full, stated, why = None, "", "SKIPPED", ""
        else:
            rc, full = compile_stated(sig, tmp, i)
            stated, why = classify_stated(rc, full)
            v0 = evaluate(sig, compile_result=(rc, full))
        row = dict(item)
        row.update(stage=v0["stage"], allowed=v0["allowed"],
                   reasons=v0["reasons"], prop=v0["prop"],
                   goal_is_false=v0["goal_is_false"],
                   stated=stated, stated_why=why,
                   first_err=first_error(full),
                   old_cat=old.get((item.get("qid"), sig), "(缺)"))
        res.append(row)
        print("[%3d/%d] %-12s %-10s %s" %
              (i + 1, len(sigs), row["stage"], stated, item["qid"]), flush=True)
        if (i + 1) % 25 == 0:
            print("   ... %.0fs" % (time.time() - t0), flush=True)

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    report(res, n_q)
    print("明细 %s，用时 %.0fs" % (OUT, time.time() - t0))


def report(res, n_q):
    n = len(res) or 1
    stages = collections.Counter(r["stage"] for r in res)
    stated = collections.Counter(r["stated"] for r in res)

    print("\n== 影子 verdict（n=%d 条 / 全部题次 %d）==" % (len(res), n_q))
    for k in ("ABSENT", "SHAPE", "NONTRIVIAL", "UNVERIFIED", "STATED",
              "NO_PROOF", "PROOF", "READY"):
        if stages.get(k):
            print("  %-12s %4d  %5.1f%%" % (k, stages[k], 100.0 * stages[k] / n))

    compiled = [r for r in res if r["stated"] != "SKIPPED"]
    print("\n== 门 A：保留 by sorry 编译（n=%d）==" % len(compiled))
    for k, v in stated.most_common():
        if k != "SKIPPED":
            print("  %-12s %4d  %5.1f%%" % (k, v, 100.0 * v / (len(compiled) or 1)))
    kinds = collections.Counter(r["stated_why"] for r in compiled
                                if r["stated"] == "ILLEGAL")
    if kinds:
        print("  -- 不可陈述原因 --")
        for k, v in kinds.most_common():
            print("     %-18s %4d" % (k, v))

    # ★ E40：只读分桶 —— STATABLE 里有多少是「目标字面 False」的反证骨架。
    #   这一层不参与任何判定，只防止把 STATABLE 当成忠实度引用。
    ok = [r for r in compiled if r["stated"] == "STATABLE"]
    if ok:
        skel = [r for r in ok if r.get("goal_is_false")]
        print("\n== 门 A 分桶（只读，不参与判定）==")
        print("  STATABLE %4d；其中目标字面 False（反证骨架）%3d（%.1f%%）"
              "；普通命题 %4d"
              % (len(ok), len(skel), 100.0 * len(skel) / len(ok), len(ok) - len(skel)))
        print("  ★ 骨架的可证性取决于假设是否自相矛盾，门 A 判不出，"
              "不得计入「命题成立」。")

    print("\n== 交叉表：上一版分类 x 门 A（检验 37% 是否站得住）==")
    cross = collections.Counter((r["old_cat"], r["stated"]) for r in res)
    for (o, s), v in sorted(cross.items(), key=lambda x: (x[0][0], x[0][1])):
        print("  %-16s x %-10s %4d" % (o, s, v))

    print("\n== 被拒条目原文（强制人工抽验，未抽验不得当结论）==")
    for r in res:
        if r["stage"] in ("READY",):
            continue
        print("  [%s %s/%s] %s" %
              (r["qid"], r["stage"], r["stated"], r["first_err"][:110]))
        print("     SIG: %s" % r["sig"][:230].replace("\n", " "))
        print("     因: %s" % "；".join(r["reasons"])[:170])

    ready = [r for r in res if r["stage"] == "READY"]
    if ready:
        print("\n== READY 命题全文（强制人工抽验）==")
        for r in ready:
            print("  [%s] %s" % (r["qid"], r["prop"][:220]))

    print("\n★ stage=NO_PROOF 表示历史数据里没有求解侧证明体，门 C 无法在回放里验；"
          "\n  它不等于「证明通过」。★ 本床是影子模式，未改任何生产行为。")


if __name__ == "__main__":
    main()
