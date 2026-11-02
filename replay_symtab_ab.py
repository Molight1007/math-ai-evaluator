# -*- coding: utf-8 -*-
"""符号表 A/B 对照 —— 同一份数据、同一份代码，**只翻 symtab 一个变量**。

为什么必须这样测
----------------
之前的「111/112 翻案、闸门 95.2%」是拿**当前全部代码**去重判**多个历史版本**
写下的判词，中间还夹着别的改动 —— 那不是效果量，是版本总差。这里把变量收紧：
两臂共用同一次解析、同一个判定函数，唯一差别是 `_sympy_judge` 有没有拿到
本题已定义符号表。

两臂的符号表**从历史原始数据独立构建**（历史 verdict==correct 的行），
与重判结果无关 —— 否则 B 臂的输入会被自己的判定改变，就不是单变量了。

零 LLM、零配额。
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.getcwd())

import replay_gate_sim as G          # noqa: E402
import replay_zero_fix_impact as Z   # noqa: E402
from utils import symbol_table as ST  # noqa: E402


def build_symtab(rows):
    """从历史数据里独立构建符号表：只收历史判定为 correct 的步骤定义。"""
    tab = {}
    trail = []
    for r in rows:
        if str(r.get("objective_verdict") or "") != "correct":
            continue
        b = ST.collect_bindings(
            str(r.get("conclusion") or ""),
            str(r.get("conclusion_support") or ""),
            str(r.get("result") or "")[:2000])
        if ST.merge_bindings(tab, b):
            trail.append((str(r.get("id") or "?"), sorted(b)))
    return tab, trail


def run_arm(qs, use_symtab):
    """返回 {(qdir,qid,rowidx): (verdict, reason)} 与统计。"""
    shim = Z._Shim()
    out = {}
    stat = collections.Counter()
    for q in qs:
        rows = Z.load_rows(q["qdir"])
        tab, _trail = build_symtab(rows)
        for i, r in enumerate(rows):
            if not Z._TARGET_REASON.match(str(r.get("objective_reason") or "")):
                continue
            res = str(r.get("result") or "")
            answers = [str(x) for x in (r.get("candidate_answers") or [])]
            try:
                contract = shim._parse_step_contract(res)
                _, v, reason = shim._judge_subgoal_objective(
                    {}, contract, res, answers, existing_idx=-1,
                    symtab=(tab if use_symtab else None))
            except Exception as e:  # noqa: BLE001
                v, reason = "parse_err", str(e)[:60]
            out[(q["qdir"], q.get("qid"), i)] = (v, reason, tab if use_symtab else None)
            stat[v] += 1
    return out, stat


def main():
    idx = sys.argv[1] if len(sys.argv) > 1 else "/tmp/e21_license.json"
    lo = sys.argv[2] if len(sys.argv) > 2 else "20261015"
    qs = [q for q in G.load_qdirs(idx) if str(q.get("run_id") or "")[:8] >= lo]
    a, sa = run_arm(qs, False)
    b, sb = run_arm(qs, True)

    print("== 范围 ==")
    print("  题次 %d，纳入行 %d（只含算术判据可达的行）" % (len(qs), len(a)))
    print("\n== 两臂判词分布（同一批行）==")
    keys = sorted(set(sa) | set(sb))
    for k in keys:
        print("  %-10s A(无符号表) %3d   B(有符号表) %3d" % (k, sa.get(k, 0), sb.get(k, 0)))

    print("\n== 迁移矩阵 A -> B ==")
    mig = collections.Counter()
    for key in a:
        mig[(a[key][0], b[key][0])] += 1
    for (x, y), c in sorted(mig.items(), key=lambda t: -t[1]):
        mark = "" if x == y else "   <- 变了"
        print("  %-10s -> %-10s %3d%s" % (x, y, c, mark))

    print("\n== 被救回（A=undecided → B=pass/fail）样例 ==")
    n_show = 0
    for key in a:
        va, vb = a[key][0], b[key][0]
        if va in ("undecided", "unknown") and vb in ("correct", "incorrect"):
            qid = key[1]
            print("  [%s] %s -> %s | %s" % (qid, va, vb, b[key][1][:100]))
            n_show += 1
            if n_show >= 12:
                break
    if not n_show:
        print("  （无）")

    print("\n== 反向：B 比 A 更糟的情况（应恒为 0）==")
    bad = [(k, a[k][0], b[k][0]) for k in a
           if a[k][0] in ("correct", "incorrect") and b[k][0] not in ("correct", "incorrect")]
    print("  条数:", len(bad))
    for k, va, vb in bad[:5]:
        print("   ", k[1], va, "->", vb)


if __name__ == "__main__":
    main()
