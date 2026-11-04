# -*- coding: utf-8 -*-
"""评估床：出口闸门**真判生效**会在服务器真实数据上砍掉什么（零配额）。

## 为什么要单独再写一张床

`replay_sig_gate.py` 是 E30 的**影子**床：只统计「若生效会砍谁」，verdict
不进闭合准入。E31（`d8fff9d`）把三道门真接到了 `tool_verdict` 与
`closure_of`，但至今只有回归与离线回放证据，**没有一轮真实运行**。
本床把真判的合成链在历史产物上重放一遍，专门找「不该否决却被否决」。

## ★★★ 三档必须分开报（E25 / E27 教训）

  A. **历史可观测**：门 A（保留 `:= by sorry` 的真实 Lean 编译）+ 门 B
     （零成本文本判据）。这一档的结论可以写进报告。
  B. **反事实**：假设 E31 的合成链真被调用，把 `gate_fields()` 注入历史
     子目标，看 `tool_verdict` / `closure_of` 会变成什么。
     ★ 历史产物**本来没有** `sig_gate_allowed` 字段 ⇒ 实际 `closure_of`
       逐字不变。这一档是「若生效会怎样」，**不是观测到的效果**，
       不得写成效果量，也不得与 A 档混成一个百分比。
  C. **不可验**：门 C 需要求解侧补完的证明体，历史盘上没有（90 条
     NO_PROOF）。只标 `NOT_VERIFIABLE`，不给历史数字；合成逻辑由
     `tests/test_gate_enforce_paths.py` 用构造用例验。

## 判定口径

  · 门 A 必须与 11-04 影子缓存 `/tmp/sig_gate_res.json` 的编译结论逐条复现，
    不一致要能解释（超时 / 环境），否则判 UNEXPLAINED。
  · 影子 stage vs 真判 stage 的差异必须逐条给 disposition；任何差异没有
    E31 语义解释 ⇒ exit 1。
  · **强制输出分层人工抽验清单**。E27：干净 A/B 数字漂亮但抽验 8 条 7 错；
    E29：连「编译通过」都挡不住语义空洞。未抽验不得当结论。

## 用法（服务器，需 source deploy/lean-env.sh）

    cd ~/mathpilot && source deploy/lean-env.sh
    .venv/bin/python replay_gate_enforce.py \
        --index /tmp/e21_license.json --since 20261015 \
        --shadow /tmp/sig_gate_res.json \
        --out /tmp/gate_enforce_res.json \
        --report /tmp/gate_enforce_report.json

★ 单文件 import Mathlib.Tactic ≈2.4s / 峰值 3.4GB ⇒ 必须串行。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys
import tempfile
import time

from contracts.closure import closure_of
from contracts.formal_sig_gate import (
    evaluate, classify_stated, gate_fields, verdict_text, illegal_kind,
)
from replay_lean_close import PRELUDE, _run


def compile_stated(sig, tmp, idx):
    """门 A：保留 `by sorry` 原样编译，返回 (returncode, full_err)。"""
    ok, _first, full = _run(sig.strip(), os.path.join(tmp, "e%05d.lean" % idx))
    return (0 if ok else 1), full


def first_error(full_err):
    for ln in (full_err or "").splitlines():
        if "error" in ln and "warning" not in ln.lower():
            return ln.strip()[:240]
    return ""


def load_index(index_path, since):
    """题次 → (qdir, qid, 03 子目标, 04 结果条目)。按 id 对齐，不猜顺序。"""
    d = json.load(open(index_path, encoding="utf-8"))
    qs = d if isinstance(d, list) else (d.get("questions") or d.get("items") or [])
    qs = [q for q in qs if str(q.get("run_id") or "")[:8] >= since]
    out, n_q = [], len(qs)
    for q in qs:
        qdir = q["qdir"]
        p3 = os.path.join(qdir, "03_subgoals.json")
        p4 = os.path.join(qdir, "04_subgoal_results.jsonl")
        if not os.path.exists(p3):
            continue
        try:
            plan = json.load(open(p3, encoding="utf-8"))
        except Exception:
            continue
        hist = {}
        if os.path.exists(p4):
            for ln in open(p4, encoding="utf-8", errors="ignore"):
                if not ln.strip():
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                if r.get("id") is not None:
                    hist[str(r["id"])] = r
        for sg in ((plan.get("plan") or {}).get("subgoals") or []):
            sig = str(sg.get("formal_sig") or "").strip()
            if not sig:
                continue
            out.append({
                "qid": q.get("qid"),
                "run": str(q.get("run_id"))[:8],
                "sg_id": sg.get("id"),
                "type": sg.get("type"),
                "tool": sg.get("tool"),
                "sig": sig,
                "hist": hist.get(str(sg.get("id"))) or {},
                "qdir": qdir,
            })
    return out, n_q


def load_shadow(path):
    """11-04 影子床的编译结论，按 (qid, sig) 对齐。只作历史参照，不当真判结果。"""
    if not path or not os.path.exists(path):
        return {}
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}
    return {(r.get("qid"), r.get("sig")): r for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="/tmp/e21_license.json")
    ap.add_argument("--since", default="20261015")
    ap.add_argument("--shadow", default="/tmp/sig_gate_res.json")
    ap.add_argument("--out", default="/tmp/gate_enforce_res.json")
    ap.add_argument("--report", default="/tmp/gate_enforce_report.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-compile", action="store_true",
                    help="复用影子缓存的编译结论，不重跑 Lean（仅用于快速复核）")
    args = ap.parse_args()

    items, n_q = load_index(args.index, args.since)
    shadow = load_shadow(args.shadow)
    if args.limit:
        items = items[:args.limit]
    print("题次 %d，形式签名 %d 条；影子缓存可用 %d 条" %
          (n_q, len(items), len(shadow)), flush=True)

    tmp = tempfile.mkdtemp(prefix="gateenf_")
    t0 = time.time()
    res = []
    for i, it in enumerate(items):
        sig = it["sig"]
        hist = it["hist"]
        # ---- E31 生产链：_init_sig_gate 总是先跑 ----
        v_init = evaluate(sig)
        skip = v_init["stage"] in ("ABSENT", "SHAPE", "NONTRIVIAL")
        if skip:
            rc, full, stated, why = None, "", "SKIPPED", ""
            # 生产里若没有 lean 代码块，_commit_sig_gate 不会被调用，
            # 字段保持 _init 的结果（UNVERIFIED / SHAPE / NONTRIVIAL）。
            v_commit = v_init
            compile_mode = "zero_cost_only"
        elif args.no_compile:
            s = shadow.get((it["qid"], sig)) or {}
            stated = s.get("stated") or "MISSING"
            why = s.get("stated_why") or ""
            full = s.get("first_err") or ""
            rc = 0 if stated == "STATABLE" else 1
            v_commit = evaluate(sig, compile_result=(rc, full), proof_code=None)
            compile_mode = "reused_shadow"
        else:
            rc, full = compile_stated(sig, tmp, i)
            stated, why = classify_stated(rc, full)
            # 历史盘上没有求解侧证明体 ⇒ proof_code=None ⇒ NO_PROOF/PROOF
            v_commit = evaluate(sig, compile_result=(rc, full), proof_code=None)
            compile_mode = "fresh_lean"

        gf = gate_fields(v_commit)
        vt = verdict_text(v_commit)
        # ---- 反事实：把闸门字段注入历史条目，看闭合准入会怎样 ----
        old_cl, old_why = closure_of(hist)
        new_item = dict(hist)
        new_item.update(gf)
        new_cl, new_why = closure_of(new_item)
        # 模拟 _mark：闸门否决优先于「工具说通过」
        ran = hist.get("tool_ran") is True
        failed = "fail" in str(hist.get("tool_verdict") or "").lower()
        old_tv = str(hist.get("tool_verdict") or "")
        new_tv = vt if gf["sig_gate_allowed"] is False else (
            "fail" if failed else ("pass" if ran else ""))

        srow = shadow.get((it["qid"], sig)) or {}
        row = {
            "qid": it["qid"], "run": it["run"], "sg_id": it["sg_id"],
            "type": it["type"], "tool": it["tool"], "sig": sig,
            "prop": v_commit["prop"],
            "compile_mode": compile_mode,
            "stated": stated, "stated_why": why,
            "first_err": first_error(full),
            "init_stage": v_init["stage"],
            "stage": v_commit["stage"],
            "allowed": v_commit["allowed"],
            "reasons": v_commit["reasons"],
            "verdict_text": vt,
            "sig_gate_allowed": gf["sig_gate_allowed"],
            "hist_tool_ran": hist.get("tool_ran"),
            "hist_tool_verdict": old_tv,
            "old_tv": old_tv, "new_tv": new_tv,
            "old_closure": old_cl, "old_closure_why": old_why,
            "new_closure": new_cl, "new_closure_why": new_why,
            "shadow_stage": srow.get("stage", "(缺)"),
            "shadow_stated": srow.get("stated", "(缺)"),
            "shadow_cat": srow.get("old_cat", "(缺)"),
            "qdir": it["qdir"],
        }
        res.append(row)
        if (i + 1) % 25 == 0:
            print("   ... %d/%d  %.0fs" % (i + 1, len(items), time.time() - t0),
                  flush=True)

    report = build_report(res, n_q, args)
    json.dump(res, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(report, open(args.report, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n明细 %s\n报告 %s\n用时 %.0fs" %
          (args.out, args.report, time.time() - t0), flush=True)
    print("判定 %s；无解释差异 %d" %
          (report["verdict"], len(report["unexplained"])), flush=True)
    if report["unexplained"]:
        for x in report["unexplained"][:20]:
            print("  UNEXPLAINED: %s" % x, flush=True)
        return 1
    return 0


def build_report(res, n_q, args):
    """三档分开报；差异逐条 disposition；抽验清单确定性分层。"""
    n = len(res) or 1
    stages = collections.Counter(r["stage"] for r in res)
    stated_c = collections.Counter(r["stated"] for r in res)
    # ---- A 档：门 A 与影子缓存逐条复现 ----
    compile_rows = [r for r in res if r["compile_mode"] == "fresh_lean"]
    repro = collections.Counter(
        ("复现" if r["stated"] == r["shadow_stated"] else "不一致")
        for r in compile_rows)
    # ---- 影子 → 真判 stage 差异，逐条解释 ----
    diff = collections.Counter()
    unexplained = []
    for r in res:
        a, b = r["shadow_stage"], r["stage"]
        key = "%s→%s" % (a, b)
        diff[key] += 1
        if a == b or a == "(缺)":
            continue
        # E31 把 proof_code 默认值从 "" 改为 None：旧版会判 PROOF(EMPTY)，
        # 新版判 NO_PROOF(尚未交付证明体)。这是唯一允许的语义解释。
        if {a, b} <= {"PROOF", "NO_PROOF"}:
            continue
        unexplained.append("%s sg%s 影子 %s → 真判 %s（无 E31 语义解释）" %
                           (r["qid"], r["sg_id"], a, b))
    for r in compile_rows:
        if r["stated"] != r["shadow_stated"]:
            # 超时/环境是可解释的编译波动，其余一律无解释
            if "TIMEOUT" in r["stated"] or "TIMEOUT" in r["shadow_stated"]:
                continue
            unexplained.append(
                "%s sg%s 门A编译 本次 %s vs 影子 %s：%s" %
                (r["qid"], r["sg_id"], r["stated"], r["shadow_stated"],
                 r["first_err"][:90]))
    # ---- B 档：反事实影响 ----
    tv_changed = [r for r in res if r["old_tv"] != r["new_tv"]]
    cl_changed = [r for r in res if r["old_closure"] != r["new_closure"]]
    cl_reason_changed = [r for r in res if r["old_closure_why"] != r["new_closure_why"]]
    by_q = collections.defaultdict(list)
    for r in res:
        by_q[r["qid"]].append(r)
    ready_q = [q for q, rows in by_q.items()
               if any(x["allowed"] for x in rows)]
    # ---- 抽验清单：确定性分层，不做随机「漂亮抽样」 ----
    rng = random.Random(20261105)
    picks = []

    def add(r, layer):
        picks.append({
            "layer": layer, "qid": r["qid"], "sg_id": r["sg_id"],
            "tool": r["tool"], "sig": r["sig"][:500], "prop": r["prop"][:300],
            "stated": r["stated"], "stated_why": r["stated_why"],
            "first_err": r["first_err"][:240],
            "init_stage": r["init_stage"], "stage": r["stage"],
            "reasons": r["reasons"], "verdict_text": r["verdict_text"],
            "old_tv": r["old_tv"], "new_tv": r["new_tv"],
            "old_closure": r["old_closure"], "new_closure": r["new_closure"],
            "shadow_stage": r["shadow_stage"], "shadow_stated": r["shadow_stated"],
        })

    # (1) 所有影子→真判不一致条目，全量抽
    for r in res:
        if r["shadow_stage"] != r["stage"] and r["shadow_stage"] != "(缺)":
            add(r, "DIFF_FULL")
    # (2) 门 A 编译复现不一致，全量抽
    for r in compile_rows:
        if r["stated"] != r["shadow_stated"]:
            add(r, "REPRO_MISMATCH")
    # (3) ILLEGAL 按原因分层，每类 3 条
    by_kind = collections.defaultdict(list)
    for r in res:
        if r["stated"] == "ILLEGAL":
            by_kind[r["stated_why"]].append(r)
    for kind, rows in sorted(by_kind.items()):
        for r in rng.sample(rows, min(3, len(rows))):
            add(r, "ILLEGAL/" + kind)
    # (4) STATABLE 按时间前/后各 5 条（不按结论挑，防过拟合）
    stab = [r for r in res if r["stated"] == "STATABLE"]
    stab.sort(key=lambda r: (r["run"], str(r["qid"]), str(r["sg_id"])))
    half = len(stab) // 2
    for r in rng.sample(stab[:half], min(5, len(stab[:half]))):
        add(r, "STATABLE/EARLY")
    for r in rng.sample(stab[half:], min(5, len(stab[half:]))):
        add(r, "STATABLE/LATE")
    # (5) 退化命题与形态异常，全量抽
    for r in res:
        if r["stage"] in ("NONTRIVIAL", "SHAPE"):
            add(r, r["stage"])

    report = {
        "claim": ("在 %d 条形式签名 / %d 题次上，未发现无解释差异；"
                  "不宣称等价、不宣称真判有效、不宣称效果量。" % (len(res), n_q)),
        "scope": {
            "A_historical_observable": "门A 真实 Lean 编译 + 门B 零成本判据",
            "B_counterfactual": ("注入 gate_fields 后的 tool_verdict / closure_of；"
                                 "历史产物本无该字段，实际逐字不变 ⇒ 不是观测效果"),
            "C_not_verifiable": ("门C 需求解侧证明体，历史盘上没有；"
                                 "合成逻辑另由 tests/test_gate_enforce_paths.py 验"),
        },
        "rows": len(res), "questions": n_q,
        "compile_mode": collections.Counter(r["compile_mode"] for r in res),
        "A_stages": dict(stages),
        "A_stated": dict(stated_c),
        "A_illegal_kinds": dict(collections.Counter(
            r["stated_why"] for r in res if r["stated"] == "ILLEGAL")),
        "A_reproduce_vs_shadow": dict(repro),
        "compile_evidence": ("fresh_lean: %d 条真实 Lean 编译，逐条对齐影子缓存"
                             % len(compile_rows)) if compile_rows else
                            ("NOT_COMPILED: 本轮 --no-compile 复用影子缓存，"
                             "不得作为门A 复现证据"),
        "shadow_to_enforce_stage": dict(diff),
        "B_tool_verdict_changed": len(tv_changed),
        "B_closure_level_changed": len(cl_changed),
        "B_closure_reason_changed": len(cl_reason_changed),
        # ★ 60 条降级必须拆开报：STATED/NONTRIVIAL 有实质依据（命题写不出 /
        #   命题是空的）；NO_PROOF 只是「历史盘上没有求解侧证明体」，
        #   是数据缺口不是判据结论，不得外推成真实运行时的误杀。
        "B_closure_transitions": dict(collections.Counter(
            "%s→%s/%s" % (r["old_closure"], r["new_closure"], r["stage"])
            for r in res if r["old_closure"] != r["new_closure"])),
        "B_downgrade_with_substantive_basis": sum(
            1 for r in res if r["old_closure"] != r["new_closure"]
            and r["stage"] in ("STATED", "NONTRIVIAL")),
        "B_downgrade_due_to_history_gap": sum(
            1 for r in res if r["old_closure"] != r["new_closure"]
            and r["stage"] == "NO_PROOF"),
        "B_questions_with_ready": len(ready_q),
        "B_hist_tool_ran_true": sum(1 for r in res if r["hist_tool_ran"] is True),
        "B_note": ("历史 tool_ran 全 False ⇒ 真判路径从未被触发；"
                   "本档是反事实上界，不得引用为预期"),
        "manual_spot_check": picks,
        "unexplained": unexplained,
        "verdict": "NO_UNEXPLAINED_DIFF" if not unexplained else "UNEXPLAINED_DIFF",
    }
    print("\n== A 档：真判 stage（n=%d）==" % len(res), flush=True)
    for k in ("ABSENT", "SHAPE", "NONTRIVIAL", "UNVERIFIED", "STATED",
              "NO_PROOF", "PROOF", "READY"):
        if stages.get(k):
            print("  %-12s %4d  %5.1f%%" % (k, stages[k], 100.0 * stages[k] / n),
                  flush=True)
    print("\n== A 档：门 A 编译（n=%d）==" % len(compile_rows), flush=True)
    for k, v in stated_c.most_common():
        print("  %-12s %4d" % (k, v), flush=True)
    print("  与影子缓存逐条复现：%s" % dict(repro), flush=True)
    print("\n== 影子 → 真判 stage 差异 ==", flush=True)
    for k, v in diff.most_common():
        print("  %-28s %4d" % (k, v), flush=True)
    print("\n== B 档：反事实影响（不是观测效果）==", flush=True)
    print("  tool_verdict 变化 %d 条；闭合层级变化 %d 条；闭合理由变化 %d 条" %
          (len(tv_changed), len(cl_changed), len(cl_reason_changed)), flush=True)
    print("  历史 tool_ran=True %d 条；若生效至少一条 READY 的题次 %d" %
          (report["B_hist_tool_ran_true"], len(ready_q)), flush=True)
    print("\n== 人工抽验 %d 条（分层，写在报告里，未抽验不得当结论）==" %
          len(picks), flush=True)
    return report


if __name__ == "__main__":
    sys.exit(main())
