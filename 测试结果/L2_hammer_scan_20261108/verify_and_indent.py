# -*- coding: utf-8 -*-
"""E42 两个校验：(A) 闭合点独立复现；(B) 多行 tactic 缩进修复对照。

A：hits.json 里所有 CLOSED 的 (tactic, idx)，每条单独一个 .lean，
   单文件 rc / error / sorry 一锤定音，排除大文件行号归属造成的假阳性。
B：V_base 判为 BROKEN 的点，把 prefix 里**每一行**统一 +2 空格
   （探针 build_code 只给第一行加缩进，多行 tactic 会散架），
   重编译看硬错误是否消失 ⇒ 量化「多少坏前缀是我们没接住」。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gen_hammer import HB  # noqa: E402

m = json.load(open(os.path.join(HERE, "manifest.json"), encoding="utf-8"))
h = json.load(open(os.path.join(HERE, "hits.json"), encoding="utf-8"))
items = m["items"]
OUT = os.path.join(HERE, "verify")
os.makedirs(OUT, exist_ok=True)


def render_lines(sig, tactics, idx, fix_indent=False):
    body = re.sub(r":=\s*by\s+sorry\b", ":= by", sig.strip())
    for t in tactics:
        if fix_indent:
            body += "\n" + "\n".join("  " + ln for ln in t.split("\n"))
        else:
            body += "\n" + ("  " + t.lstrip()
                            if not t.startswith("  ") else t)
    return ["import Mathlib.Tactic", "",
            "set_option maxHeartbeats %d in" % HB,
            *body.split("\n"), '#eval "MARK_%d"' % idx, ""]


def write(name, lines):
    open(os.path.join(OUT, name), "w", encoding="utf-8",
         newline="\n").write("\n".join(lines) + "\n")


# ---------------- A ----------------
closed = []
for stem, per in h["classify"].items():
    if not stem.startswith("H_"):
        continue
    for k, s in per.items():
        if s == "CLOSED":
            closed.append((stem, int(k)))
# 反查 tactic
tac_by_stem = {os.path.splitext(f)[0]: v["tactic"]
               for f, v in m["files"].items() if v["kind"] == "hammer"}
amap = {}
for stem, idx in closed:
    it = items[idx]
    tac = tac_by_stem[stem]
    name = "A_%s_%03d.lean" % (stem[2:], idx)
    write(name, render_lines(it["sig"], it["prefix"] + [tac], idx))
    amap[name] = {"tactic": tac, "idx": idx, "prefix_len": it["prefix_len"],
                  "tags": sorted(set(it["tags"]))}
print("A: 独立复现文件", len(amap))

# ---------------- B ----------------
broken = [i for i in range(len(items))
          if h["classify"]["V_base"][str(i)] == "BROKEN"]
lines = ["import Mathlib.Tactic", ""]
bmap = []
for i in broken:
    it = items[i]
    tacs = list(it["prefix"]) + ([it["model_tac"]] if it["model_tac"] else [])
    body = re.sub(r":=\s*by\s+sorry\b", ":= by", it["sig"].strip())
    for t in tacs:
        body += "\n" + "\n".join("  " + ln for ln in t.split("\n"))
    lines.append("set_option maxHeartbeats %d in" % HB)
    start = len(lines) + 1
    lines.extend(body.split("\n"))
    end = len(lines)
    lines.append('#eval "MARK_%d"' % i)
    lines.append("")
    bmap.append({"idx": i, "start": start, "end": end, "mark_line": end + 1})
write("B_indent_fix.lean", lines)
json.dump({"A": amap, "B": bmap},
          open(os.path.join(HERE, "verify_map.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("B: 缩进修复点", len(bmap))
