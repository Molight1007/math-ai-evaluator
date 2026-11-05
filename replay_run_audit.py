# -*- coding: utf-8 -*-
"""统一运行审计口径（只读；零配额；可复核）。

为什么入仓
----------
E31–E34 的审计脚本散落在服务器 `/tmp` 与本地临时目录，彼此口径有细微
差别（闸门字段判定、闭合层级判定、qdir 选取），结论只有当时那一台机器
能复现。本文件把四个观测点收敛成**唯一一份**口径，入仓后可随版本复跑。

观测点（A/B/C/D）
-----------------
  A 闭环信号：日志中「带编译反馈重证」记录数、工具核验未过留痕数、
     Lean 真实编译调用数、配额/致命异常。日志只是旁证，0 不等于没发生。
  B 工具指派：03 的逐题工具分布，并与 `--compare-dirs` 指定的历史轮次
     逐 qid 对照（跨轮漂移只报事实，不归因、不当效果量）。
  C 工具痕迹与闸门：04 的 tool_ran / tool_verdict / sig_gate_allowed /
     stage；**闭合判定只认 04**（回放三硬约定），用 `closure_of` 唯一权威。
  D 闭合与 F-SOFT：逐条闭合层级、HARD 计数（工具级闭合，不是「判对」）、
     「判定为对 + 有推导 + 闸门否决」抽验清单。清单只列事实，不替用户拍板。

口径声明
--------
  单轮运行只能观测「是否发生」，不能证明「温度令生成确定」或任何效果量；
  HARD_CLOSED 是工具级闭合，不是题级诚实闭合；不宣称等价 / 有效 / 通过。

用法
----
  服务器只读：python replay_run_audit.py --from-server \
      --run-dir <results/2026.../> --log <run.log> \
      --compare-dirs <历史轮1> <历史轮2> --out /tmp/report.json
  本地：--data-root <数据根> 其余同上。
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from contracts.closure import (  # noqa: E402
    FAIL_WORDS, CLOSURE_HARD, closure_of,
)

RECLOSE_MARK = "带编译反馈重证"
VERIFY_MARK = "工具核验未过"
LEAN_MARK = "run_code"


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


def tool_plan_of(qdir):
    p = os.path.join(qdir, "03_subgoals.json")
    if not os.path.isfile(p):
        return {}
    try:
        obj = json.load(open(p, encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    subs = (obj.get("plan") or {}).get("subgoals") or []
    return dict(collections.Counter(str(s.get("tool") or "EMPTY")
                                    for s in subs))


def signatures_of(qdir):
    p = os.path.join(qdir, "03_subgoals.json")
    if not os.path.isfile(p):
        return 0
    try:
        obj = json.load(open(p, encoding="utf-8"))
    except (ValueError, OSError):
        return 0
    subs = (obj.get("plan") or {}).get("subgoals") or []
    return sum(1 for s in subs if str(s.get("formal_sig") or "").strip())


def audit_qdir(qdir):
    st = {"qid": os.path.basename(qdir), "qdir": qdir,
          "files": sorted(os.path.basename(x)
                          for x in glob.glob(os.path.join(qdir, "*"))),
          "n03": 0, "n03_sig": signatures_of(qdir),
          "tool_plan": tool_plan_of(qdir),
          "n04": 0, "tool_ran_true": 0, "gate_present": 0,
          "allowed_true": 0, "allowed_false": 0,
          "verdict_fail": 0, "verdict_pass": 0,
          "stages": collections.Counter(), "closure": collections.Counter(),
          "hard_closed": 0, "f_soft": [], "rows": []}
    for r in load_jsonl(os.path.join(qdir, "04_subgoal_results.jsonl")):
        st["n04"] += 1
        tv = str(r.get("tool_verdict") or "")
        if r.get("tool_ran") is True:
            st["tool_ran_true"] += 1
        # 复用契约层唯一权威词表；不得用 startswith("fail") 自写一份口径
        if any(w in tv.lower() for w in FAIL_WORDS):
            st["verdict_fail"] += 1
        if tv == "pass":
            st["verdict_pass"] += 1
        if "sig_gate_allowed" in r:
            st["gate_present"] += 1
            if r["sig_gate_allowed"] is True:
                st["allowed_true"] += 1
            else:
                st["allowed_false"] += 1
            st["stages"][str(r.get("sig_gate_stage") or "NONE")] += 1
        level, _why = closure_of(r)
        st["closure"][level] += 1
        if level == CLOSURE_HARD:
            st["hard_closed"] += 1
        if (r.get("objective_verdict") == "correct"
                and r.get("has_derivation") is True
                and r.get("sig_gate_allowed") is False):
            st["f_soft"].append({"id": r.get("id"),
                                 "stage": r.get("sig_gate_stage"),
                                 "verdict": tv[:120]})
        st["rows"].append({
            "id": r.get("id"), "tool": r.get("tool"),
            "ran": r.get("tool_ran"),
            "gate": r.get("sig_gate_allowed", "ABSENT"),
            "stage": r.get("sig_gate_stage", "-"),
            "closure": level, "verdict": tv[:110]})
    for k in ("stages", "closure"):
        st[k] = dict(st[k])
    return st


def log_signals(logpath):
    out = {"present": os.path.isfile(logpath), "log": logpath,
           "reclose_records": [], "verify_fail_records": 0,
           "lean_compile_calls": 0, "quota_or_fatal": []}
    if not out["present"]:
        return out
    for ln in open(logpath, encoding="utf-8", errors="replace"):
        if RECLOSE_MARK in ln:
            out["reclose_records"].append(ln.strip()[-200:])
        if VERIFY_MARK in ln:
            out["verify_fail_records"] += 1
        if "LeanBridge" in ln and LEAN_MARK in ln:
            out["lean_compile_calls"] += 1
        if re.search(r"20080|429|FATAL|Traceback", ln, re.I):
            out["quota_or_fatal"].append(ln.strip()[-160:])
    return out


def prior_plans(compare_dirs):
    out = {}
    for rd in compare_dirs:
        for qd in sorted(glob.glob(os.path.join(rd, "q*"))):
            if os.path.isdir(qd):
                out.setdefault(os.path.basename(qd), {})[
                    os.path.basename(rd.rstrip(os.sep))] = tool_plan_of(qd)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-server", action="store_true")
    ap.add_argument("--data-root", default="")
    ap.add_argument("--run-dir", default="")
    ap.add_argument("--log", default="")
    ap.add_argument("--compare-dirs", nargs="*", default=[])
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

    sig = log_signals(a.log) if a.log else {"present": False,
                                            "reclose_records": [],
                                            "verify_fail_records": 0,
                                            "lean_compile_calls": 0,
                                            "quota_or_fatal": []}
    prior = prior_plans(a.compare_dirs)
    questions = [audit_qdir(qd) for qd in
                 sorted(glob.glob(os.path.join(run_dir, "q*")))
                 if os.path.isdir(qd)]
    report = {
        "run_dir": run_dir, "data_root": data_root,
        "compare_dirs": a.compare_dirs,
        "log_signals": sig, "prior_tool_plan": prior,
        "questions": questions,
        "disclaimer": [
            "单轮只能观测「是否发生」，不能证明温度令生成确定",
            "HARD_CLOSED 是工具级闭合，不是题级诚实闭合",
            "日志留痕是旁证，0 不等于没发生；闭合判定只认 04",
            "不宣称等价 / 有效 / 效果量 / 评测通过",
        ],
    }
    if a.out:
        json.dump(report, open(a.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

    print("=" * 78)
    print("统一运行审计  RUN_DIR=%s" % run_dir)
    print("=" * 78)
    print("== A 闭环与工具信号 ==")
    print("  重证记录=%d  核验未过留痕=%d  Lean 编译调用=%d  日志可用=%s" %
          (len(sig["reclose_records"]), sig["verify_fail_records"],
           sig["lean_compile_calls"], sig.get("present", False)))
    for x in sig["reclose_records"][:10]:
        print("   RECLOSE", x)
    if sig["quota_or_fatal"]:
        print("   告警/异常（末 5 条）：", sig["quota_or_fatal"][-5:])
    for s in questions:
        print("-" * 78)
        print("QID %s files=%s" % (s["qid"], ",".join(s["files"])))
        print("  B 工具指派  本轮=%s | 历史=%s" %
              (s["tool_plan"], prior.get(s["qid"], {})))
        print("  03 签名=%d" % s["n03_sig"])
        print("  C 04 rows=%d tool_ran=%d gate=%d(放行%d/否决%d) "
              "verdict fail=%d pass=%d stages=%s" %
              (s["n04"], s["tool_ran_true"], s["gate_present"],
               s["allowed_true"], s["allowed_false"],
               s["verdict_fail"], s["verdict_pass"], s["stages"]))
        print("  D closure=%s HARD=%d F-SOFT 抽验清单=%d" %
              (s["closure"], s["hard_closed"], len(s["f_soft"])))
        for r in s["rows"]:
            print("    #%-3s tool=%-8s ran=%-5s gate=%-6s stage=%-13s "
                  "closure=%-12s verdict=%s" %
                  (r["id"], r["tool"], r["ran"], r["gate"], r["stage"],
                   r["closure"], r["verdict"]))
        for f in s["f_soft"]:
            print("    F-SOFT  %s" % f)
    print("=" * 78)
    for d in report["disclaimer"]:
        print("NOTE", d)
    if a.out:
        print("REPORT", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
