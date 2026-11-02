# -*- coding: utf-8 -*-
"""闸门预演：只让已达标的结论进下游，会让多少题断掉（E23，零 LLM / 零配额）。

要回答的问题
------------
把下游注入从「节点全文拼接」改成「只从已闭合集合取」之后，
**有多少题会走不到最后一步**。这个数决定改造代价可不可接受。

为什么必须分档
--------------
严格档（只认工具级闭合）在历史上必然**全断**：归档回放里
`tool_ran=True` 一条都没有。得出「100% 断掉」没有信息量 ——
它只说明过去一次都没真验过，不说明改造代价。

所以分三档，看代价随严格程度怎么变：
    L0  工具级（HARD）                       —— 不可贿赂，但历史为空
    L1  工具级 + 模型判对且有推导（SOFT）      —— 现实可用档
    L2  L1 + 未判错且确有推导（放宽 OPEN）     —— 最宽松的现实档

模拟规则
--------
按子目标顺序（id 升序）逐条判：
  · 若某条目**全部上游**在档内达标 ⇒ 它可执行，状态取其实际闭合层级；
  · 否则 ⇒ 卡住（BLOCKED），它的下游也一律卡住（传递性）。
题级判据：**最后一条**（收尾）是否被执行到。

★ 口径两条，必须随数一起引用
  1. **乐观口径**：同一子目标有多行时取**最优**（某一轮证成过就算证成）。
     理由：多轮重解的存在意义就是"某轮成功即成立"。取最后一行会把
     早期成功抹掉，不符合语义。
  2. **只统计可判定题次**：没有 `04_subgoal_results` 的题次不参与
     （早期批次根本没有子目标产物），否则「没数据」会被算成「断掉」，
     把 0% 与 90% 平均成一个假数（E21 已踩过）。
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contracts.closure import (  # noqa: E402
    CLOSURE_HARD,
    CLOSURE_OPEN,
    CLOSURE_SOFT,
    CLOSURE_UNMAPPED,
    closure_of,
)

BLOCKED = "BLOCKED"

LEVELS = ("L0", "L1", "L2")

LEVEL_DESC = {
    "L0": "只认工具级闭合",
    "L1": "工具级 + 模型判对且有推导",
    "L2": "L1 + 未判错且确有推导",
}


def _passes(level, closure, row):
    """某条目在某档下是否「达标」（可作为下游前提）。"""
    if closure == CLOSURE_HARD:
        return True
    if closure == CLOSURE_SOFT:
        return level in ("L1", "L2")
    if closure == CLOSURE_OPEN:
        if level != "L2":
            return False
        # L2：未判错 + 确有推导正文，才给一次机会
        ov = (row.get("objective_verdict") or "").lower()
        return row.get("has_derivation") is True and ov != "incorrect"
    return False


def best_closure(rows):
    """同一子目标的多行取**最优**闭合（乐观口径，见模块头）。"""
    order = {CLOSURE_HARD: 3, CLOSURE_SOFT: 2, CLOSURE_OPEN: 1, CLOSURE_UNMAPPED: 0}
    best = None
    for r in rows:
        c = closure_of(r)[0]
        if best is None or order[c] > order[best[0]]:
            best = (c, r)
    return best or (CLOSURE_UNMAPPED, {})


def group_by_id(rows):
    """按子目标 id 归并（一个 id 可能多行：多轮重解）。"""
    out = {}
    for r in rows:
        try:
            k = int(r.get("id"))
        except (TypeError, ValueError):
            continue
        out.setdefault(k, []).append(r)
    return out


def simulate(rows, level):
    """对一道题的子目标做闸门模拟。

    返回 dict：
        reached_tail  收尾子目标是否被执行到
        n_total       子目标数
        n_blocked     卡住数
        first_block   第一个卡住的子目标 id（无则 None）
        status        {id: 闭合层级 或 BLOCKED}
    """
    grouped = group_by_id(rows)
    if not grouped:
        return {"reached_tail": False, "n_total": 0, "n_blocked": 0,
                "first_block": None, "status": {}}

    status = {}
    first_block = None
    for sg_id in sorted(grouped):
        entries = grouped[sg_id]
        closure, row = best_closure(entries)
        # 上游：任一上游未达标 ⇒ 本条卡住（AND 语义）
        deps = []
        for r in entries:
            for d in (r.get("depends_on") or []):
                try:
                    deps.append(int(d))
                except (TypeError, ValueError):
                    continue
        deps = sorted(set(d for d in deps if d != sg_id))
        upstream_ok = all(
            d in status and status[d] != BLOCKED
            # 用该上游的**最优**那条来判是否达标（与它自己的状态同一口径）
            and _passes(level, status[d], best_closure(grouped.get(d, []))[1])
            for d in deps)
        if not upstream_ok:
            status[sg_id] = BLOCKED
            if first_block is None:
                first_block = sg_id
            continue
        status[sg_id] = closure

    tail = max(grouped)
    tail_status = status.get(tail)
    return {
        "reached_tail": tail_status != BLOCKED,
        # ★「走到收尾」不等于「收尾达标」：它能执行（前提齐全）但自己可能
        #   仍未闭合。两个指标必须分开报，否则会把「跑完了但没证出来」
        #   算成成功 —— 而那正是当前系统的病。
        "tail_closure": tail_status,
        "tail_passes": (tail_status is not None and tail_status != BLOCKED
                        and _passes(level, tail_status,
                                    best_closure(grouped.get(tail, []))[1])),
        "n_total": len(grouped),
        "n_blocked": sum(1 for v in status.values() if v == BLOCKED),
        "first_block": first_block,
        "status": status,
    }


def load_qdirs(index_path):
    """从回放索引里取 (qdir, label, run_id, qid)，只要可判定的题次。"""
    with open(index_path, encoding="utf-8") as f:
        idx = json.load(f)
    out = []
    for q in idx.get("questions") or []:
        qdir = q.get("qdir") or ""
        if not qdir or not os.path.isdir(qdir):
            continue
        p4 = os.path.join(qdir, "04_subgoal_results.jsonl")
        if not os.path.isfile(p4):
            continue
        out.append({
            "qdir": qdir,
            "qid": q.get("qid"),
            "run_id": q.get("run_id"),
            "label": q.get("label"),
            "n_nodes": q.get("n_nodes"),
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, help="回放 --json 输出（取题次与判对标签）")
    ap.add_argument("--json", dest="out", default="", help="明细落盘")
    args = ap.parse_args(argv)

    qs = load_qdirs(args.index)
    print("可判定题次（有 04 产物）：%d" % len(qs))
    if not qs:
        return 1

    detail = []
    agg = {lv: {"n": 0, "tail_ok": 0, "tail_pass": 0, "blocked": 0,
                "sg_total": 0, "by_label": {}} for lv in LEVELS}

    for q in qs:
        p4 = os.path.join(q["qdir"], "04_subgoal_results.jsonl")
        rows = []
        with open(p4, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
        if not rows:
            continue
        rec = {"qdir": q["qdir"], "qid": q["qid"], "run_id": q["run_id"],
               "label": q["label"]}
        for lv in LEVELS:
            r = simulate(rows, lv)
            rec[lv] = {k: r[k] for k in ("reached_tail", "tail_closure",
                                         "tail_passes", "n_total",
                                         "n_blocked", "first_block")}
            a = agg[lv]
            a["n"] += 1
            a["tail_ok"] += 1 if r["reached_tail"] else 0
            a["tail_pass"] += 1 if r["tail_passes"] else 0
            a["blocked"] += r["n_blocked"]
            a["sg_total"] += r["n_total"]
            lb = str(q["label"])
            b = a["by_label"].setdefault(lb, {"n": 0, "tail_ok": 0, "tail_pass": 0})
            b["n"] += 1
            b["tail_ok"] += 1 if r["reached_tail"] else 0
            b["tail_pass"] += 1 if r["tail_passes"] else 0
        detail.append(rec)

    print("\n== 各档下的题级结果 ==")
    print("   （走完 = 前提齐全能执行到收尾；达标 = 收尾自身也够本档标准）")
    for lv in LEVELS:
        a = agg[lv]
        n = a["n"] or 1
        print("  %s（%s）" % (lv, LEVEL_DESC[lv]))
        print("     走完 %3d / %3d = %5.1f%%   达标 %3d = %5.1f%%"
              % (a["tail_ok"], a["n"], 100.0 * a["tail_ok"] / n,
                 a["tail_pass"], 100.0 * a["tail_pass"] / n))
        print("     卡住子目标 %4d / %4d = %5.1f%%"
              % (a["blocked"], a["sg_total"],
                 100.0 * a["blocked"] / (a["sg_total"] or 1)))
        for lb in sorted(a["by_label"]):
            b = a["by_label"][lb]
            print("       label=%-6s 走完 %3d/%-3d=%5.1f%%   达标 %3d/%-3d=%5.1f%%"
                  % (lb, b["tail_ok"], b["n"],
                     100.0 * b["tail_ok"] / (b["n"] or 1),
                     b["tail_pass"], b["n"],
                     100.0 * b["tail_pass"] / (b["n"] or 1)))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"summary": agg, "questions": detail}, f,
                      ensure_ascii=False, indent=1)
        print("\n明细已写: %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
