# -*- coding: utf-8 -*-
"""固定蓝图单变量回放台（只读；零配额；不干扰任何正在运行的评测）。

为什么需要它
------------
E34 同一轮改了三件事（蓝图温度、编译反馈闭环、编译额度），违反了 E14 的
「同输入 + 单变量」铁律：E33 轮与 E34 轮一旦有差异，无法归因；没有差异，
也无法定位是哪一处没生效。本台用**固定蓝图 + 固定求解输出**（逐字取自
真实归档）把「是否走编译反馈闭环」单独翻一个变量，让结论可复核。

三档必须分开报（沿用 E25 / E27 / P0 的口径）
--------------------------------------------
  A. **历史可观测**：03 固定蓝图的工具/签名分布、04 归档的 tool_ran /
     闸门字段、生产权威 `closure_of` 逐条复现的闭合层级、日志里真实的
     「工具核验未过」留痕次数。确定性、零配额、逐条可核，结论可写进报告。
  B. **单变量反事实**：在 A 档同一批固定输入上只翻「闭环路径」一个变量，
     报触发行数与逐条记录；「改证后二次核验通过」是**反事实假设**（回放床
     替身写入），只给上界，不得写成观测效果或效果量。
  C. **不可验**：温度 0.0 是否让蓝图确定化（需同配置两轮真实运行）、
     重解后的证明体是否真能编译通过（需真实 LLM + Lean）、E34 相对 E33
     的效果量（需 E14 事前算 n 并跑满）。本档明确留白，不做推断。

★ 观测性缺口必须显性化（不许偷偷补默认值）
  真实 04 归档里**没有** `fb`（工具核验反馈原文），也**没有**
  `tool_not_run_reason`。因此 A 档不能声称复现了真实反馈；B 档的 fb 是
  显式构造前提，并用 `--assume-not-run` 量化「缺失字段」对结论的敏感性。

防过拟合口径
------------
  留出集：按 qid 目录 mtime 排序，前 70% 开发集 / 后 30% 留出集**分别报**，
  不合并成一个百分比。分层：逐 qid 列，禁止把不同题平均。人工抽验：输出
  逐条记录。零无解释差异：**非 lean 行两臂必须逐字一致**，否则退出码 1。

  只写「在 N 条固定输入上未发现无解释差异」，不写「等价 / 有效 / 提升」。

用法
----
  本地：python replay_fixed_blueprint.py --data-root <仓库或数据根> \
            --run-dir <results/2026.../> --log <run.log> --out report.json
  服务器只读：把本文件放到服务器 /tmp，--from-server 指向 ~/mathpilot，
            报告写 /tmp；不写仓库、不碰运行代码。
"""
from __future__ import annotations

import argparse
import collections
import copy
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from contracts.closure import (  # noqa: E402
    FAIL_WORDS, closure_of,
)
from agent import subgoal_collab as COLLAB  # noqa: E402

# 显式标注为构造前提：绝不冒充真实编译器反馈。
SYNTHETIC_FB = "SYNTHETIC_COMPILE_FAILURE: 回放床构造前提，非真实反馈"
# 替身重解文本必须 >40 字（生产函数以此判有效）；同样显式标注为替身产物。
SYNTHETIC_REWRITE = ("SYNTHETIC_REWRITE: 回放床替身输出，非模型产物；"
                     "本字段只用于驱动控制流，不代表任何证明内容。")
VERIFY_MARK = "工具核验未过"


class RecordingSolver:
    """回放床替身：只记录控制流，不调 LLM、不编译、不联网。

    保留生产函数 `verify_and_mark` / `_maybe_lean_reclose` 的**真实控制流**，
    替换的只有外部依赖（模型与编译器）。第二次核验写 `pass` 是 B 档的
    反事实假设，不是观测结果。
    """

    def __init__(self, first_fb=SYNTHETIC_FB, second_pass=True):
        self.first_fb = first_fb
        self.second_pass = second_pass
        self.n_verify = 0
        self.solve_hints = []
        self.records = []

    def record(self, ctx, tag, msg):
        self.records.append(str(msg))

    def _tool_declared_verify(self, ctx, sg, text):
        self.n_verify += 1
        if self.n_verify == 1:
            return self.first_fb
        if self.second_pass:
            sg["tool_ran"] = True
            sg["tool_verdict"] = "pass"
        return ""

    def _solve_subgoal(self, ctx, sg, next_plan, done_digest, hint):
        self.solve_hints.append(str(hint))
        return SYNTHETIC_REWRITE


def load_jsonl(path):
    if not os.path.isfile(path):
        return []
    out = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


def plan_rows(qdir):
    """固定蓝图：只用 03_subgoals（回放三硬约定之一）。"""
    p = os.path.join(qdir, "03_subgoals.json")
    if not os.path.isfile(p):
        return []
    try:
        obj = json.load(open(p, encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return (obj.get("plan") or {}).get("subgoals") or []


def result_rows(qdir):
    """闭合判定只用 04_subgoal_results（只有它带 tool_ran）。"""
    return load_jsonl(os.path.join(qdir, "04_subgoal_results.jsonl"))


def log_verify_marks(logpath):
    """日志只是旁证：record() 不写运行日志，故 0 **不等于**没有失败。"""
    if not os.path.isfile(logpath):
        return {"present": False, "n": 0, "samples": [],
                "note": "未提供日志；失败判据以 04 归档 tool_verdict 为准"}
    n, samples = 0, []
    for ln in open(logpath, encoding="utf-8", errors="replace"):
        if VERIFY_MARK in ln:
            n += 1
            if len(samples) < 8:
                samples.append(ln.strip()[-160:])
    note = ("record() 不写运行日志：计数 0 不等于没有失败；"
            "以 04 归档 tool_verdict 为准" if n == 0 else "日志留痕可用（旁证）")
    return {"present": True, "n": n, "samples": samples, "note": note}


def is_fail_verdict(v):
    """复用契约层唯一权威词表，禁止回放床自写一份（口径漂移教训）。"""
    s = str(v or "").strip().lower()
    return bool(s) and any(w in s for w in FAIL_WORDS)


def run_pair(row, fb, assume_not_run):
    """两臂唯一差别：是否调用生产闭环函数。返回逐条对照记录。"""
    rec = {
        "id": row.get("id"), "tool": row.get("tool"),
        "verdict": str(row.get("tool_verdict") or "")[:110],
        "tool_ran_observed": row.get("tool_ran"),
        "gate_observed": row.get("sig_gate_allowed", "ABSENT"),
        "has_not_run_field": "tool_not_run_reason" in row,
        "closure_observed": closure_of(row)[0],
    }
    base = copy.deepcopy(row)
    reclose = copy.deepcopy(row)
    if assume_not_run and "tool_not_run_reason" not in row:
        # 假设必须**同时施加到两臂**：只加在闭环臂会凭空造出伪差异
        # （2026-11-05 敏感性对照实测 16 条 UNEXPLAINED，即此缺陷）。
        # 显式假设参数只在回放床生效；不写回档、不进生产代码。
        base["tool_not_run_reason"] = "ASSUMED_MISSING_FIELD"
        reclose["tool_not_run_reason"] = "ASSUMED_MISSING_FIELD"

    s1 = RecordingSolver(first_fb=fb)
    COLLAB.verify_and_mark(s1, None, base, str(base.get("result") or ""))
    rec["baseline"] = {
        "n_verify": s1.n_verify, "n_resolve": len(s1.solve_hints),
        "closure": closure_of(base)[0],
        "sg": _slim(base),
    }

    s2 = RecordingSolver(first_fb=fb)
    got_fb = COLLAB.verify_and_mark(
        s2, None, reclose, str(reclose.get("result") or ""))
    out2 = COLLAB._maybe_lean_reclose(
        s2, None, reclose, got_fb, "", "", str(reclose.get("title") or ""))
    rec["reclose"] = {
        "n_verify": s2.n_verify, "n_resolve": len(s2.solve_hints),
        "triggered": bool(out2),
        "closure": closure_of(reclose)[0],
        "sg": _slim(reclose),
    }
    rec["closure_changed"] = (rec["baseline"]["closure"]
                              != rec["reclose"]["closure"])
    rec["unexplained"] = (str(row.get("tool") or "").strip().lower() != "lean"
                          and rec["baseline"]["sg"] != rec["reclose"]["sg"])
    return rec


def _slim(sg):
    """两臂可比的最小字段集（决定性不变量用）。"""
    keys = ("tool", "tool_ran", "tool_verdict", "sig_gate_allowed",
            "sig_gate_stage", "tool_not_run_reason", "objective_verdict",
            "has_derivation")
    return {k: sg.get(k, "ABSENT") for k in keys}


def split_holdout(qdirs):
    """按目录内最晚文件 mtime 排序；前 70% 开发集 / 后 30% 留出集。"""
    def mtime_of(d):
        fs = glob.glob(os.path.join(d, "*"))
        return max((os.path.getmtime(f) for f in fs), default=os.path.getmtime(d))
    ordered = sorted(qdirs, key=mtime_of)
    cut = int(len(ordered) * 0.7)
    return ordered[:cut], ordered[cut:]


def audit_part(qdirs, fb, assume_not_run):
    out = {"n_qid": len(qdirs), "questions": [], "n_rows": 0,
           "n_lean_rows": 0, "n_candidate_rows": 0, "n_triggered": 0,
           "n_closure_changed": 0, "unexplained": [],
           "closure_observed": collections.Counter(),
           "tool_plan": collections.Counter(), "spot_check": []}
    for qd in qdirs:
        q = {"qid": os.path.basename(qd), "n03": 0, "n03_sig": 0,
             "tool_plan": {}, "rows": [], "n_triggered": 0}
        subs = plan_rows(qd)
        q["n03"] = len(subs)
        q["n03_sig"] = sum(1 for s in subs
                           if str(s.get("formal_sig") or "").strip())
        q["tool_plan"] = dict(collections.Counter(
            str(s.get("tool") or "EMPTY") for s in subs))
        out["tool_plan"].update(q["tool_plan"])
        for row in result_rows(qd):
            r = run_pair(row, fb, assume_not_run)
            q["rows"].append(r)
            out["n_rows"] += 1
            out["closure_observed"][r["closure_observed"]] += 1
            is_lean = str(row.get("tool") or "").strip().lower() == "lean"
            if is_lean:
                out["n_lean_rows"] += 1
            # 归档可观测的「闭环候选」：真跑过 + 编译判失败 + lean
            if is_lean and row.get("tool_ran") is True \
                    and is_fail_verdict(row.get("tool_verdict")):
                out["n_candidate_rows"] += 1
            if r["reclose"]["triggered"]:
                out["n_triggered"] += 1
                q["n_triggered"] += 1
                out["spot_check"].append({
                    "qid": q["qid"], "id": r["id"], "tool": r["tool"],
                    "verdict": r["verdict"], "gate": r["gate_observed"],
                    "has_not_run_field": r["has_not_run_field"],
                    "closure_before": r["closure_observed"],
                    "closure_after": r["reclose"]["closure"]})
            if r["closure_changed"]:
                out["n_closure_changed"] += 1
            if r["unexplained"]:
                out["unexplained"].append(
                    {"qid": q["qid"], "id": r["id"], "tool": r["tool"]})
        out["questions"].append(q)
    out["closure_observed"] = dict(out["closure_observed"])
    out["tool_plan"] = dict(out["tool_plan"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-server", action="store_true",
                    help="数据根取 /home/ubuntu/mathpilot（只读）")
    ap.add_argument("--data-root", default="")
    ap.add_argument("--run-dir", default="")
    ap.add_argument("--log", default="")
    ap.add_argument("--fb", default=SYNTHETIC_FB,
                    help="B 档构造前提；默认显式标注为合成值")
    ap.add_argument("--assume-not-run", action="store_true",
                    help="对归档缺失 tool_not_run_reason 的行显式假设「未真跑」")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    data_root = ("/home/ubuntu/mathpilot" if a.from_server
                 else (a.data_root or ROOT))
    run_dir = a.run_dir
    if not run_dir:
        cands = sorted(glob.glob(os.path.join(data_root, "results", "20*")),
                       key=os.path.getmtime)
        run_dir = cands[-1] if cands else ""
    if not run_dir or not os.path.isdir(run_dir):
        print("ERROR 找不到运行目录：%s" % run_dir)
        return 2

    qdirs = sorted(d for d in glob.glob(os.path.join(run_dir, "q*"))
                   if os.path.isdir(d))
    dev, hold = split_holdout(qdirs)
    a_dev = audit_part(dev, a.fb, a.assume_not_run)
    a_hold = audit_part(hold, a.fb, a.assume_not_run)
    loginfo = log_verify_marks(a.log) if a.log else {"present": False}

    report = {
        "run_dir": run_dir, "data_root": data_root,
        "assume_not_run": a.assume_not_run,
        "fb_is_synthetic": a.fb == SYNTHETIC_FB,
        "archive_gap": {
            "fb_field_present": False,
            "tool_not_run_reason_field_present": any(
                r["has_not_run_field"]
                for p in (a_dev, a_hold) for q in p["questions"]
                for r in q["rows"]),
            "note": "04 归档无反馈原文与未真跑标记；A 档不声称复现真实反馈",
        },
        "A_observable": {
            "n_qid": len(qdirs), "log_verify_marks": loginfo,
            "dev": a_dev, "holdout": a_hold,
        },
        "B_counterfactual": {
            "note": "只翻闭环路径一个变量；二次核验 pass 为反事实假设（上界）",
            "dev": {k: a_dev[k] for k in
                    ("n_rows", "n_lean_rows", "n_candidate_rows",
                     "n_triggered", "n_closure_changed", "unexplained",
                     "spot_check")},
            "holdout": {k: a_hold[k] for k in
                        ("n_rows", "n_lean_rows", "n_candidate_rows",
                         "n_triggered", "n_closure_changed", "unexplained",
                         "spot_check")},
        },
        "C_unverifiable": [
            "蓝图温度 0.0 是否令生成确定化（需同配置两轮真实运行）",
            "重解后的证明体是否真能编译通过（需真实 LLM + Lean）",
            "E34 相对 E33 的效果量 δ（需 E14 事前算 n 且跑满）",
            "F-SOFT 语义（需「判对+有推导+闸门否决」真实触发样例）",
        ],
    }
    if a.out:
        json.dump(report, open(a.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

    print("=" * 78)
    print("固定蓝图单变量回放台  RUN_DIR=%s" % run_dir)
    print("★ 归档缺口：fb 原文缺失=%s | 未真跑标记缺失=%s | 合成 fb=%s" %
          (not report["archive_gap"]["fb_field_present"],
           not report["archive_gap"]["tool_not_run_reason_field_present"],
           report["fb_is_synthetic"]))
    print("=" * 78)
    print("== A 档：历史可观测（确定性，可写进报告）==")
    print("  qid 数=%d（开发集 %d / 留出集 %d）  日志核验未过留痕=%s" %
          (len(qdirs), len(dev), len(hold),
           loginfo.get("n", "未提供日志")))
    print("  日志口径说明：%s" % loginfo.get("note", ""))
    for label, part in (("开发集", a_dev), ("留出集", a_hold)):
        print("  [%s] 04 行=%d  closure=%s  03 工具分布=%s" %
              (label, part["n_rows"], part["closure_observed"],
               part["tool_plan"]))
        for q in part["questions"]:
            print("     %s  03 子目标=%d 签名=%d  工具=%s" %
                  (q["qid"], q["n03"], q["n03_sig"], q["tool_plan"]))
    print()
    print("== B 档：单变量反事实（不是观测效果，不得当效果量）==")
    for label, part in (("开发集", a_dev), ("留出集", a_hold)):
        print("  [%s] 总行=%d lean=%d 归档可观测候选=%d 闭环触发=%d "
              "闭合层级变化=%d 无解释差异=%d" %
              (label, part["n_rows"], part["n_lean_rows"],
               part["n_candidate_rows"], part["n_triggered"],
               part["n_closure_changed"], len(part["unexplained"])))
    for x in (a_dev["spot_check"] + a_hold["spot_check"])[:20]:
        print("     抽验 %s #%s tool=%s gate=%s has_not_run=%s  %s→%s | %s" %
              (x["qid"], x["id"], x["tool"], x["gate"],
               x["has_not_run_field"], x["closure_before"],
               x["closure_after"], x["verdict"][:60]))
    print()
    print("== C 档：不可验（明确留白）==")
    for x in report["C_unverifiable"]:
        print("   -", x)
    print("=" * 78)
    print("声明：只写「未发现无解释差异」；不写等价 / 有效 / 提升 / 已证明。")
    if a.out:
        print("REPORT", a.out)

    bad = a_dev["unexplained"] + a_hold["unexplained"]
    if bad:
        print("UNEXPLAINED_DIFF %d 条（非 lean 行两臂不一致）" % len(bad))
        return 1
    print("NO_UNEXPLAINED_DIFF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
