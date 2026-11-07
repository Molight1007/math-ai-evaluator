#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「first | 结构」×「策略集合」2x2 对照床（零配额、只读、评估床 delta=0）

起因：E37 声称做过「严格单变量对照」——G = E28 旧策略串、Z = 新构造性
模板。但 Z 顺手把每个 `first` 分支包了 `; done`（修假阴性），G 没有。
于是两臂**同时变了两个变量**：分支结构 + 策略集合。

实测反例 q5a7e5ee2/20261027#1（结论与前提 h 逐字相同，assumption 即可证）：
    G  旧串无 done  -> FAIL (unsolved goals)
    G+ 旧策略 +done -> PASS
    Z  新策略 +done -> PASS
即 E37 报的「新增 2 条」里至少有 1 条与构造性模板无关，纯粹来自结构修复。

本床补 G+ 臂，形成 2x2：
                 旧策略集合(G_T)      新策略集合(Z_T)
    无 done      G  (E28 原串)       —（不做，无意义）
    有 done      G+ (本床新增)       Z  (E37 已跑)
    * G  vs G+ : 唯一变量 = 分支结构（; done）
    * G+ vs Z  : 唯一变量 = 策略集合
    这样才配称单变量对照。

设计：
  · 样本逐条复用 /tmp/fidelity_probe_compare.json 的 90 行（E37 同一抽样，
    STATABLE 且签名原文完全一致），不重新抽样，避免配对漂移。
  · PRELUDE 逐字复用 E37；唯一差别是策略串。
  · 逐条落盘 /tmp/fidelity_cmp_gp.jsonl，可断点续跑。
  · 每个分支仍包 (t; done)：这是结构修复本身，不是新变量。

边界：
  · 只报各档条数与逐条清单；不报比例、不作统计推断、不宣称效果量/等价。
  · PASS 只说明「存在编译级零数学证明」，不穷尽；FAIL 不作判定。
  · 不改任何生产代码、不写回任何历史结果文件、不新增 POLICY 项/开关。

用法：
  cd ~/mathpilot && source deploy/lean-env.sh
  .venv/bin/python 平凡性探针_2x2对照.py gp       # 跑 G+ 臂
  .venv/bin/python 平凡性探针_2x2对照.py report   # 合并 G/G+/Z -> /tmp/fidelity_2x2.json
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.getcwd())
from contracts.formal_sig_gate import SORRY_RE

PRELUDE = "import Mathlib.Tactic\n\nset_option maxHeartbeats 400000\n\n"
G_TACTICS = ["decide", "norm_num", "omega", "simp", "linarith", "ring_nf",
             "positivity", "nlinarith", "gcongr", "assumption", "rfl"]
# 与 G 的策略集合逐字相同，只把每个分支包 (t; done)
GPLUS = "first\n" + "\n".join("  | (" + t + "; done)" for t in G_TACTICS)

SRC = "/tmp/fidelity_probe_compare.json"
GP_JSONL = "/tmp/fidelity_cmp_gp.jsonl"
OUT = "/tmp/fidelity_2x2.json"


def compile_one(sig, path, timeout=45):
    code = SORRY_RE.sub(GPLUS, sig)
    with open(path, "w", encoding="utf-8") as f:
        f.write(PRELUDE + code.strip() + "\n")
    try:
        r = subprocess.run(["lean", path], capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "timeout"
    if r.returncode == 0:
        return "PASS", ""
    e = (r.stderr or r.stdout or "").strip()
    first = next((l.strip() for l in e.splitlines() if "error" in l), "")
    return "FAIL", (first or (e.splitlines()[0] if e else ""))[:160]


def load_rows():
    return json.load(open(SRC, encoding="utf-8"))["rows"]


def arm_gp():
    rows = load_rows()
    done = {}
    if os.path.exists(GP_JSONL):
        for line in open(GP_JSONL, encoding="utf-8"):
            try:
                d = json.loads(line)
                done[d["idx"]] = d
            except Exception:
                pass
    tmp = tempfile.mkdtemp(prefix="f2x2_")
    with open(GP_JSONL, "a", encoding="utf-8") as out:
        for r in rows:
            if r["idx"] in done:
                continue
            st, err = compile_one(r["sig"], os.path.join(tmp, "p.lean"))
            out.write(json.dumps({"idx": r["idx"], "qid": r["qid"],
                                  "run": r["run"], "sg_id": r["sg_id"],
                                  "old_cat": r["old_cat"],
                                  "gp": st, "err": err},
                                 ensure_ascii=False) + "\n")
            out.flush()
    print("G+ arm done:", sum(1 for _ in open(GP_JSONL, encoding="utf-8")),
          "/", len(rows))


def report():
    rows = load_rows()
    gp = {}
    for line in open(GP_JSONL, encoding="utf-8"):
        d = json.loads(line)
        gp[d["idx"]] = d["gp"]
    merged = []
    for r in rows:
        merged.append({"idx": r["idx"], "qid": r["qid"], "run": r["run"],
                       "sg_id": r["sg_id"], "old_cat": r["old_cat"],
                       "g": r["g"], "gp": gp.get(r["idx"], "MISSING"),
                       "z": r["z"]})
    cnt = {k: sum(1 for r in merged if r[k] == "PASS")
           for k in ("g", "gp", "z")}
    struct = [r for r in merged if r["g"] != "PASS" and r["gp"] == "PASS"]
    strategy = [r for r in merged if r["gp"] != "PASS" and r["z"] == "PASS"]
    both = [r for r in merged if r["g"] != "PASS" and r["gp"] == "PASS"
            and r["z"] == "PASS"]
    obj = {"n": len(merged), "counts": cnt,
           "struct_only_pass": [r["qid"] + "/" + r["run"] + "#" + str(r["sg_id"])
                                for r in struct],
           "strategy_only_pass": [r["qid"] + "/" + r["run"] + "#" + str(r["sg_id"])
                                  for r in strategy],
           "both_arms_pass": [r["qid"] + "/" + r["run"] + "#" + str(r["sg_id"])
                              for r in both],
           "gplus_tactic": GPLUS, "prelude": PRELUDE, "rows": merged}
    json.dump(obj, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("n", len(merged), "counts", cnt)
    print("G->G+ (structure only):", len(struct), obj["struct_only_pass"])
    print("G+->Z (strategy only):", len(strategy), obj["strategy_only_pass"])
    print("both:", len(both), obj["both_arms_pass"])
    print("wrote", OUT)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "gp":
        arm_gp()
    elif cmd == "report":
        report()
    else:
        raise SystemExit("usage: 平凡性探针_2x2对照.py {gp|report}")
