#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「探针强度」单变量对照床（零配额、只读、评估床 δ=0）

问题：E28 报「TRIVIAL 只有 6 条」，用的是一组通用自动策略 G。
      26 条抽样里 G 命中 1 条、补了构造性步骤的 Z 命中 2 条 ⇒
      「空洞少」可能只是探针太弱。本床在历史 151 条上把这件事量化。

设计（严格单变量）：
  · 数据：/tmp/lean_close_res.json（E28 151 条，含 sig 原文与历史 cat）
          /tmp/sig_gate_res.json（门A 影子，含 stated）
  · 样本：只取 stated == STATABLE 的 90 条。ILLEGAL 54 条换任何证明策略
          都必然编译失败（命题本身不能陈述），SKIPPED 7 条门A 未判，
          纳入只会稀释，故不跑。
  · 两臂共用**完全相同**的 PRELUDE（E28 原式）、相同的签名、相同的编译
    顺序；唯一变量是替换 sorry 的策略串 G / Z。
  · G = replay_lean_close.TACTIC（逐字复刻，历史口径）
  · Z = 11 个「零数学」构造性模板合并的 first 探针
    ★ 与 26 条探针的 12 模板版差异：去掉 `aesop`。理由：26 条上 aesop
      从未成为任一 PASS 条目的唯一命中策略（#21 另有 simp/norm_num/rfl，
      #24 另有三个空集策略），而它是难命题上跑满 heartbeats 的主要耗时源。
      去掉它会让 Z 更保守（PASS 只会更少），不制造假阳性。

★ 边界
  · 只报各档条数与逐条清单；不报比例结论、不作统计推断、不宣称效果量 /
    等价 / 评测通过。
  · Z=PASS 只说明「存在编译级零数学证明」，不穷尽；Z=FAIL 不作判定。
  · 不改任何生产代码、不写回任何历史结果文件。

用法（两臂分开跑，避免单次长连接超时；逐条落盘可断点续跑）：
  cd ~/mathpilot && source deploy/lean-env.sh
  .venv/bin/python 平凡性探针_151条对照.py g       # /tmp/fidelity_cmp_g.jsonl
  .venv/bin/python 平凡性探针_151条对照.py z       # /tmp/fidelity_cmp_z.jsonl
  .venv/bin/python 平凡性探针_151条对照.py report  # /tmp/fidelity_probe_compare.json
"""
import collections
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.getcwd())
from contracts.formal_sig_gate import SORRY_RE

PRELUDE = "import Mathlib.Tactic\n\nset_option maxHeartbeats 400000\n\n"
G = ("first | decide | norm_num | omega | simp | linarith | ring_nf | positivity "
     "| nlinarith | gcongr | assumption | rfl")
ZERO_STRATEGIES = [
    ("化简 simp", "simp"),
    ("线性算术 omega", "omega"),
    ("可判定 decide", "decide"),
    ("数值 norm_num", "norm_num"),
    ("取 0 作存在见证", "use 0 <;> simp"),
    ("取空集作存在见证", "use ∅ <;> simp"),
    ("空集 + 化简", "refine ⟨∅, ?_⟩ <;> simp"),
    ("空集 + 右分支", "refine ⟨∅, Or.inr ?_⟩ <;> simp"),
    ("走右分支", "right <;> simp"),
    ("走左分支", "left <;> simp"),
    ("存在性 rfl", "exact ⟨_, rfl⟩"),
]
Z = "first\n" + "\n".join("  | (" + t + "; done)" for _, t in ZERO_STRATEGIES)
OUT = {"g": "/tmp/fidelity_cmp_g.jsonl", "z": "/tmp/fidelity_cmp_z.jsonl"}

# ★ 2026-11-07 实测修正：合并 `first |` 的每个分支必须包 `; done`。
#   否则 `refine ⟨∅, ?_⟩ <;> simp` 这类分支会留下未解目标却不算 tactic 失败，
#   `first` 就此停止、后续分支不再尝试，最终报 unsolved goals ⇒ **假阴性**。
#   实测 qdecd0474/20261019#2（即抽验 #24）：逐策略 3 个 PASS，
#   未加 done 的合并版 FAIL，加 done 后 PASS；正常命题 q10a65b3d#6 两版均 FAIL
#   （对照有效）。`done` 在有未解 goals 时失败，才会让 first 继续试下一分支。


def compile_one(code, path, timeout=45):
    with open(path, "w", encoding="utf-8") as f:
        f.write(PRELUDE + code.strip() + "\n")
    try:
        r = subprocess.run(["lean", path], capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "timeout"
    err = (r.stderr or r.stdout or "").strip()
    first = next((ln.strip() for ln in err.splitlines() if "error" in ln), "")
    return ("PASS" if r.returncode == 0 else "FAIL"), first[:200]


def load_rows():
    old = {tuple(str(x[k]) for k in ("qid", "run", "sg_id")): x
           for x in json.load(open("/tmp/lean_close_res.json", encoding="utf-8"))}
    gate = json.load(open("/tmp/sig_gate_res.json", encoding="utf-8"))
    rows = []
    for x in gate:
        if x["stated"] != "STATABLE":
            continue
        key = tuple(str(x[k]) for k in ("qid", "run", "sg_id"))
        o = old.get(key, {})
        rows.append({"idx": len(rows), "qid": x["qid"], "run": x["run"],
                     "sg_id": x["sg_id"],
                     "old_cat": x.get("old_cat") or o.get("cat"),
                     "sig": o.get("sig") or ""})
    return rows


def run_arm(arm):
    rows = load_rows()
    tactic = G if arm == "g" else Z
    path = OUT[arm]
    done = set()
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            try:
                done.add(json.loads(ln)["idx"])
            except Exception:
                pass
    tmp = tempfile.mkdtemp(prefix="fidelity_cmp_")
    with open(path, "a", encoding="utf-8") as sink:
        for r in rows:
            if r["idx"] in done:
                continue
            if not r["sig"] or not SORRY_RE.search(r["sig"]):
                st, err = "SKIP", ""
            else:
                st, err = compile_one(SORRY_RE.sub(tactic, r["sig"]),
                                      os.path.join(tmp, "%s%05d.lean" % (arm, r["idx"])))
            sink.write(json.dumps({"idx": r["idx"], "qid": r["qid"],
                                   "run": r["run"], "sg_id": r["sg_id"],
                                   "old_cat": r["old_cat"], "st": st,
                                   "err": err}, ensure_ascii=False) + "\n")
            sink.flush()
            if (r["idx"] + 1) % 15 == 0:
                print("  %s ...%d/%d" % (arm, r["idx"] + 1, len(rows)), flush=True)
    print("%s 完成：%d 条写入 %s" % (arm, len(rows), path), flush=True)


def report():
    rows = load_rows()
    arms = {}
    for arm in ("g", "z"):
        arms[arm] = {d["idx"]: d for d in
                     (json.loads(ln) for ln in open(OUT[arm], encoding="utf-8"))}
    merged = []
    for r in rows:
        merged.append(dict(r, g=arms["g"].get(r["idx"], {}).get("st", "MISSING"),
                           z=arms["z"].get(r["idx"], {}).get("st", "MISSING")))
    gp = [r for r in merged if r["g"] == "PASS"]
    zp = [r for r in merged if r["z"] == "PASS"]
    new = [r for r in merged if r["z"] == "PASS" and r["g"] != "PASS"]
    print("\n== 单变量对照结果（n=%d）==" % len(merged))
    print("  G(E28 原策略)   PASS = %d 条" % len(gp))
    print("  Z(补构造性步骤) PASS = %d 条" % len(zp))
    print("  Z 相对 G 新增命中 = %d 条" % len(new))
    print("  各档状态:", dict(collections.Counter((r["g"], r["z"]) for r in merged)))
    print("  历史 cat × Z:", dict(collections.Counter(
        (r["old_cat"], r["z"]) for r in merged)))
    print("\n== 新增命中逐条 ==")
    for r in new:
        print("  %s/%s#%s  历史=%s" % (r["qid"], r["run"], r["sg_id"], r["old_cat"]))
    json.dump({"rows": merged, "n": len(merged),
               "g_pass": len(gp), "z_pass": len(zp), "new_hit": len(new),
               "g_tactic": G, "z_tactic": Z, "prelude": PRELUDE},
              open("/tmp/fidelity_probe_compare.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n写入 /tmp/fidelity_probe_compare.json")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "report"
    if a in ("g", "z"):
        run_arm(a)
    else:
        report()
