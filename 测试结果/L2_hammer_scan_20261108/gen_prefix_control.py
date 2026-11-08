# -*- coding: utf-8 -*-
"""生成 V_prefix.lean：只含扫描点的证明前缀（不含模型本步 tactic、不含 hammer）。

这才是判断「这个 goal state 是否真实存在」的正确对照：
V_base 里的硬错误可能来自模型本步 tactic，而不是前缀。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen_hammer import HB, build_body  # noqa: E402

m = json.load(open(os.path.join(HERE, "manifest.json"), encoding="utf-8"))
items = m["items"]
lines = ["import Mathlib.Tactic", ""]
entries = []
for it in items:
    body = build_body(it["sig"], it["prefix"]).rstrip("\n")
    lines.append("set_option maxHeartbeats %d in" % HB)
    start = len(lines) + 1
    lines.extend(body.split("\n"))
    end = len(lines)
    lines.append('#eval "MARK_%d"' % it["idx"])
    lines.append("")
    entries.append({"idx": it["idx"], "start": start, "end": end,
                    "mark_line": end + 1})
os.makedirs(os.path.join(HERE, "lean"), exist_ok=True)
open(os.path.join(HERE, "lean", "V_prefix.lean"), "w", encoding="utf-8",
     newline="\n").write("\n".join(lines) + "\n")
json.dump(entries, open(os.path.join(HERE, "prefix_control_map.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)
print("V_prefix.lean lines=%d entries=%d" % (len(lines), len(entries)))
