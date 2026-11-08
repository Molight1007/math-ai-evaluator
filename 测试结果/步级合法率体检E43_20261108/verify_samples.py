# -*- coding: utf-8 -*-
"""E43 人工抽验 + 独立单文件复现。

E42 曾因「只认 `error: `、漏掉 `error(lean.xxx): `」造出假闭合，所以本轮
不信任批量解析本身：按首条硬错误类型**分层抽 8 条翻案样本** + 4 条对照，
各生成一个独立 .lean 单文件重新编译，核对 rc 与首条错误是否一致。

抽验清单同时打印出来供人工阅读（不只是机器判定）。
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compile_check_strict import DIAG_RE, UNSOLVED_RE  # noqa: E402
from gen_steps import build_body, HB  # noqa: E402

m = json.load(open(os.path.join(HERE, "manifest.json"), encoding="utf-8"))
r = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
steps = m["steps"]
cls_full = {int(k): v for k, v in r["classify"]["full"].items()}
cls_pref = {int(k): v for k, v in r["classify"]["prefix"].items()}

# 批量日志里按行号区间取出某条目的全部诊断行
entries = m["files"]["S_full.lean"]["entries"]
by_idx = {e["idx"]: e for e in entries}
log = open(os.path.join(HERE, "out", "S_full.log"),
           encoding="utf-8", errors="replace").read().splitlines()
diags = collections.defaultdict(list)
for line in log:
    dm = DIAG_RE.match(line)
    if not dm:
        continue
    ln = int(dm.group(1))
    hit = [e for e in entries if e["start"] - 1 <= ln <= e["mark_line"]]
    if hit:
        diags[hit[0]["idx"]].append((dm.group(2), dm.group(3)))

# ---- 分层抽样：按首条硬错误类型分桶，每桶取 1 条 ----
fake = [s for s in steps if s["compiled"] and s["probe_verify"] == "UNSOLVED"
        and cls_full[s["idx"]] == "HARD_ERROR"]
buckets = collections.defaultdict(list)
for s in fake:
    hard = [msg for sev, msg in diags[s["idx"]]
            if sev == "error" and not UNSOLVED_RE.search(msg)]
    key = re.sub(r"`[^`]*`", "`X`", hard[0])[:50] if hard else "(无)"
    buckets[key].append(s)
picked = []
for key in sorted(buckets, key=lambda k: -len(buckets[k])):
    if len(picked) >= 8:
        break
    picked.append(buckets[key][0])
# 4 条对照：严格判 OPEN（真合法未闭合）
opened = [s for s in steps if s["compiled"]
          and cls_full[s["idx"]] == "OPEN" and cls_pref[s["idx"]] == "OPEN"]
controls = opened[::max(1, len(opened) // 4)][:4]
sample = picked + controls

print("翻案样本 %d 条（覆盖 %d 种首错类型，总桶数 %d）；对照 %d 条\n" %
      (len(picked), len(set(
          re.sub(r"`[^`]*`", "`X`",
                 [msg for sev, msg in diags[s["idx"]]
                  if sev == "error" and not UNSOLVED_RE.search(msg)][0])[:50]
          for s in picked)), len(buckets), len(controls)))

os.makedirs(os.path.join(HERE, "verify"), exist_ok=True)
rows = []
for s in sample:
    i = s["idx"]
    body = build_body(s["sig"], s["prefix"] + [s["tactic"]]).rstrip("\n")
    text = ("import Mathlib.Tactic\n\nset_option maxHeartbeats %d in\n%s\n"
            '#eval "MARK_%d"\n' % (HB, body, i))
    open(os.path.join(HERE, "verify", "V_%d.lean" % i), "w",
         encoding="utf-8", newline="\n").write(text)
    ds = diags[i]
    hard = [msg for sev, msg in ds
            if sev == "error" and not UNSOLVED_RE.search(msg)]
    uns = [msg for sev, msg in ds if sev == "error" and UNSOLVED_RE.search(msg)]
    rows.append({"idx": i, "arm": s["arm"], "tag": s["tag"],
                 "step": s["step"], "probe_verify": s["probe_verify"],
                 "strict": cls_full[i], "prefix_strict": cls_pref[i],
                 "tactic": s["tactic"], "prefix_len": s["prefix_len"],
                 "hard": hard[:3], "unsolved": uns[:2],
                 "expected_rc": 0 if cls_full[i] in ("OPEN", "CLOSED") else 1})
    print("--- idx %-3d %-4s %-4s step%-2s probe=%-8s strict=%-10s prefix=%-10s" %
          (i, s["arm"], s["tag"], s["step"], s["probe_verify"],
           cls_full[i], cls_pref[i]))
    print("    tactic : %r" % s["tactic"][:110])
    print("    诊断   : hard=%d unsolved=%d" % (len(hard), len(uns)))
    for x in hard[:2]:
        print("      HARD %s" % x[:130])
    for x in uns[:1]:
        print("      UNS  %s" % x[:80])

json.dump(rows, open(os.path.join(HERE, "verify_map.json"), "w",
                     encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n已写 %d 个独立 .lean + verify_map.json" % len(sample))
