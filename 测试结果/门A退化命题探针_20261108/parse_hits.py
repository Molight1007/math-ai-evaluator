# -*- coding: utf-8 -*-
"""解析 out/*.log → 每条例 (idx) 是否闭合；输出 hits.json（键 = idx）"""
import json
import os
import re
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
man = json.load(open(os.path.join(HERE, "manifest.json"), encoding="utf-8"))
ERRLINE = re.compile(r"^lean/[^:]+:(\d+):(\d+): error")

closed = collections.defaultdict(list)   # idx -> ["P:simp", ...]
orphan = collections.Counter()

for f in man["files"]:
    name = f["file"]
    path = os.path.join(HERE, "out", name.replace(".lean", ".log"))
    by_line = {e["line"]: e for e in f["entries"]}
    bad = set()
    for raw in open(path, encoding="utf-8", errors="replace"):
        m = ERRLINE.match(raw)
        if not m:
            continue
        ln = int(m.group(1))
        if ln in by_line:
            bad.add(ln)
        else:
            orphan[(name, ln)] += 1
    for e in f["entries"]:
        if e["line"] not in bad:
            closed[e["idx"]].append("%s:%s" % (e["side"], e["tactic"]))
    print("%-14s examples=%2d failed=%2d closed=%2d" %
          (name, len(f["entries"]), len(bad), len(f["entries"]) - len(bad)))

print("\norphan error lines:", len(orphan), list(orphan.items())[:5])

items = man["items"]
print("\n=== 有命中 ===")
for idx, hits in sorted(closed.items(), key=lambda kv: -len(kv[1])):
    it = items[idx]
    print("[%2d] %s/%s #%s  %-28s %s" % (idx, it["run"], it["qid"], it["sg_id"],
                                         "|".join(hits), it["prop"][:70]))

# 分组结论
p_hits = {i: h for i, h in closed.items() if any(x.startswith("P:") for x in h)}
n_only = {i: h for i, h in closed.items() if not any(x.startswith("P:") for x in h)}
lit_false = [it["idx"] for it in items if it["prop"].strip() == "False"]
print("\nP侧命中(可疑平凡真/循环命题): %d 条 %s" % (len(p_hits), sorted(p_hits)))
print("N侧命中(¬P可证): %d 条 %s" % (len(n_only), sorted(n_only)))
print("其中目标本身写成 False 的: %d 条 %s" % (len(lit_false), lit_false))
print("N侧命中且非False目标:", sorted(set(n_only) - set(lit_false)))

json.dump({"closed": {str(k): v for k, v in closed.items()},
           "items": items, "literal_false": lit_false},
          open(os.path.join(HERE, "hits.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\nwrote hits.json")
