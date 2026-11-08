# -*- coding: utf-8 -*-
"""E41 对照：EMPTY 驳回续写（新） vs 直接终止（旧 b_fix 基线）。

输出三块：
  1. 两臂总数：pass / stop 分布
  2. 基线 8 条 EMPTY 逐条去哪了（驳回后有没有续上、续了几步、最后什么结局）
  3. 驳回轮里模型写了什么（判断是「真能续」还是「换一句谎话」）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(os.path.dirname(HERE), "L2逐步探针_20261107",
                    "l2_step_probe_b_fix.json")


def load(path):
    return json.load(open(path, encoding="utf-8"))


def main():
    new_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        HERE, "l2_step_probe_b_rej.json")
    old = {r["tag"]: r for r in load(BASE)}
    new = load(new_path)
    newm = {r["tag"]: r for r in new}

    print("== 总数 ==")
    for name, rows in (("旧 b_fix（EMPTY 即终止）", list(old.values())),
                       ("新（EMPTY 驳回 %d 轮）" % new[0].get("rejects", 2)
                        if new and "rejects" in new[0] else "新（EMPTY 驳回）",
                        new)):
        n = len(rows)
        p = sum(1 for r in rows if r.get("pass"))
        print("  %-26s pass %d/%d" % (name, p, n))

    print("\n== stop 分布 ==")
    for name, rows in (("旧", list(old.values())), ("新", new)):
        c = {}
        for r in rows:
            c[r.get("stop")] = c.get(r.get("stop"), 0) + 1
        print("  %s: %s" % (name, dict(sorted(c.items(), key=lambda kv: -kv[1]))))

    print("\n== 基线 EMPTY 的 8 条去哪了 ==")
    print("  %-5s %-16s %-16s %-6s %s" % ("tag", "旧结局", "新结局", "步数", "驳回详情"))
    for tag, ro in old.items():
        if ro.get("stop") != "EMPTY":
            continue
        rn = newm.get(tag, {})
        rj = []
        for rec in rn.get("trace", []):
            for x in rec.get("rejects") or []:
                rj.append("r%d:claim=%s→new=%r" %
                          (x["round"], (x["claim"] or "")[:18],
                           (x["new_tactic"] or "")[:40]))
        print("  %-5s %-16s %-16s %-6s %s" %
              (tag, ro.get("stop"), rn.get("stop"), rn.get("steps"),
               " | ".join(rj)[:150] or "-"))

    print("\n== 其余条目有无意外变化（旧非 EMPTY 的 10 条）==")
    for tag, ro in old.items():
        if ro.get("stop") == "EMPTY":
            continue
        rn = newm.get(tag, {})
        if ro.get("stop") != rn.get("stop") or bool(ro.get("pass")) != bool(rn.get("pass")):
            print("  %-5s 旧 %-14s → 新 %-14s" % (tag, ro.get("stop"), rn.get("stop")))
    print("  （未列出 = 结局相同）")


if __name__ == "__main__":
    main()
