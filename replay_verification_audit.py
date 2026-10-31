# -*- coding: utf-8 -*-
"""推导审计的**回放床**（纯函数，不跑 LLM，δ=0）。

用法（服务器上直接跑，数据只认 `results/` 下的真实产物）：

    .venv/bin/python replay_verification_audit.py                # 全量汇总
    .venv/bin/python replay_verification_audit.py --show 20      # 逐条看前 20 条命中
    .venv/bin/python replay_verification_audit.py --run 20261027-232401
    .venv/bin/python replay_verification_audit.py --json out.json

输出三块：
  ① **算术复核命中**：断言被判假（精确整数运算）—— 这些是可硬判的，逐条可复核；
  ② **结论自相矛盾**：头部值在正文里被自己否掉；
  ③ **跨轮冲突**：一次运行内各轮末步结论不等价。

为什么要有这个床：提示词改动无法 δ=0 回放，但**审计判据**可以 ——
输入是历史产物，输出只取决于判据本身，改判据前后跑同一批数据即可比差异
（误报增加多少条，一眼可见）。这正是 RRSI 规则 E 要求的「同一假设只测一次」。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.verification_audit import audit_step, pass_conflicts  # noqa: E402


class _Ctx:
    """最小 ctx 桩：账本只依赖 setattr。"""

    pass


def _steps(path: str) -> list:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except Exception:  # noqa: BLE001
        return []
    return out


def scan(root: str, only_run: str = "") -> dict:
    from agent.verification_audit import note_step

    res = {"runs": {}, "false": [], "refuted": [], "conflicts": [], "n_steps": 0}
    for path in sorted(glob.glob(os.path.join(root, "*", "q*",
                                              "04_subgoal_results.jsonl"))):
        run = os.path.basename(os.path.dirname(os.path.dirname(path)))
        if only_run and run != only_run:
            continue
        rows = _steps(path)
        if not rows:
            continue
        ctx = _Ctx()
        n_false = n_ref = 0
        for r in rows:
            text = str(r.get("result") or "")
            note_step(ctx, {"id": r.get("id"), "title": r.get("title"),
                            "result": text})
            a = audit_step(text)
            res["n_steps"] += 1
            if a["false_claims"]:
                n_false += 1
                res["false"].append({
                    "run": run, "qid": os.path.basename(os.path.dirname(path)),
                    "title": str(r.get("title") or "")[:60],
                    "claims": a["false_claims"]})
            if a["conclusion_refuted"]:
                n_ref += 1
                res["refuted"].append({
                    "run": run, "qid": os.path.basename(os.path.dirname(path)),
                    "title": str(r.get("title") or "")[:60],
                    "value": a["conclusion"]})
        cfl = pass_conflicts(ctx)
        for c in cfl:
            res["conflicts"].append({
                "run": run, "qid": os.path.basename(os.path.dirname(path)),
                "detail": c})
        res["runs"].setdefault(run, {"q": 0, "steps": 0, "false": 0,
                                     "refuted": 0, "conflicts": 0})
        e = res["runs"][run]
        e["q"] += 1
        e["steps"] += len(rows)
        e["false"] += n_false
        e["refuted"] += n_ref
        e["conflicts"] += len(cfl)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results")
    ap.add_argument("--run", default="")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print("目录不存在：%s" % args.root)
        return 2
    res = scan(args.root, args.run)
    print("=" * 78)
    print("步骤总数 %d | 算术复核命中 %d 步 | 结论自相矛盾 %d 步 | 跨轮冲突 %d 条"
          % (res["n_steps"], len(res["false"]), len(res["refuted"]),
             len(res["conflicts"])))
    print("=" * 78)
    print("%-22s %4s %6s %6s %7s %7s" % ("run", "题", "步骤", "算术假",
                                        "自相矛盾", "跨轮冲突"))
    for run, e in sorted(res["runs"].items()):
        print("%-22s %4d %6d %6d %7d %7d"
              % (run, e["q"], e["steps"], e["false"], e["refuted"],
                 e["conflicts"]))
    if res["false"]:
        print("\n--- 算术复核命中（可逐条用精确整数运算复核） ---")
        for x in res["false"][:args.show or 5]:
            print("· %s %s | %s" % (x["run"], x["qid"], x["title"]))
            for c in x["claims"]:
                print("    - " + c)
    if res["refuted"]:
        print("\n--- 结论自相矛盾（头部值在正文被自己否掉） ---")
        for x in res["refuted"][:args.show or 5]:
            print("· %s %s | %s | 值=%s"
                  % (x["run"], x["qid"], x["title"], x["value"]))
    if res["conflicts"]:
        print("\n--- 跨轮结论冲突 ---")
        for x in res["conflicts"][:args.show or 10]:
            print("· %s %s | %s" % (x["run"], x["qid"], x["detail"]))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print("\n已写 %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
