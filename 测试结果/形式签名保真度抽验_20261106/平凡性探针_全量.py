#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""形式签名「编译级平凡性探针」全量版（零配额、只读、评估床，δ=0）

运行环境：服务器 ~/mathpilot
  source deploy/lean-env.sh && .venv/bin/python 平凡性探针_全量.py
依赖：/tmp/fidelity_picks.json（26 条盲审抽样的 formalsig）
输出：/tmp/fidelity_probe_full.json

三档编译，必须分开报：
  S 可陈述  ：原样 `:= by sorry` 编译（只出 sorry warning 即算 STATABLE）
  G 通用策略：项目现成 TACTIC（E28 用的那组）替换 sorry
  Z 零数学  ：一组确定性「不需要数学内容」的 tactic 合并探针替换 sorry
              PASS ⇒ 存在编译级平凡证明（硬证据）
              FAIL ⇒ 不作任何结论（探针不完备）

★ 关键纪律
  · 探针只给存在性证据，不保证「没证出的就不平凡」。
  · 见证策略是通用模板，不是按条目手挑 ⇒ 不做主观挑样。
  · 合并 `first |` 的某个分支可能留下未解目标导致提前终止 ⇒ 这是保守
    偏差：PASS 一定是硬证据，FAIL 一律记作「无结论」。
  · 「不可陈述」只说明该签名在此 Mathlib 闭包编译不了（可能是环境记法
    缺失，如 ∑ i in s,），不等于命题空洞，也不等于命题写歪。
  · 不作效果量、不报比例推断、不宣称等价 / 真判有效 / 评测通过。

★ 已知坑：contracts.formal_sig_gate.SORRY_RE 只匹配 `sorry` 单词，
  替换串绝不能再带 `by`，否则变成 `by by` 全 FAIL（原型踩过一次）。
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.getcwd())       # 从 ~/mathpilot 执行 /tmp 下的脚本时仍可 import contracts
from contracts.formal_sig_gate import SORRY_RE

PRELUDE = ("import Mathlib.Tactic\n\nopen scoped BigOperators\n\n"
           "set_option maxHeartbeats 400000\n\n")
GENERAL = ("first | decide | norm_num | omega | simp | linarith | ring_nf "
           "| positivity | nlinarith | gcongr | assumption | rfl")

ZERO_STRATEGIES = [
    ("自动构造 aesop", "aesop"),
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
ZERO = "first\n" + "\n".join("  | (" + t + "; done)" for _, t in ZERO_STRATEGIES)
# ★ 每个分支必须包 `; done`：否则 refine ⟨∅, ?_⟩ 之类留下未解目标却不算
#   tactic 失败，first 提前终止 ⇒ 假阴性。逐策略定位另跑，不受影响。

WITNESS = {                       # 已实锤的定向见证，单独复核一次
    21: "exact ⟨360 / Nat.gcd 360 (2 * θ), rfl⟩",
    24: "refine ⟨∅, Or.inr ?_⟩; simp",
}


def compile_one(code, path, timeout=90):
    with open(path, "w", encoding="utf-8") as f:
        f.write(PRELUDE + code.strip() + "\n")
    try:
        r = subprocess.run(["lean", path], capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "timeout"
    err = (r.stderr or r.stdout or "").strip()
    first = next((ln.strip() for ln in err.splitlines() if "error" in ln), "")
    return ("PASS" if r.returncode == 0 else "FAIL"), first[:220]


def main():
    d = json.load(open("/tmp/fidelity_picks.json", encoding="utf-8"))
    blind = {b["no"]: b for b in d["blind"]}
    tmp = tempfile.mkdtemp(prefix="fidelity_full_")
    out = []
    for no in sorted(blind):
        sig = blind[no]["formal_sig"]
        row = {"no": no, "qid": blind[no]["qid"],
               "subgoal_id": blind[no]["subgoal_id"],
               "sig_len": len(sig), "has_sorry": bool(SORRY_RE.search(sig))}
        row["stated"], row["stated_err"] = compile_one(
            sig, os.path.join(tmp, "s%02d.lean" % no))
        if not row["has_sorry"]:
            row.update(general="SKIP", zero="SKIP", general_err="",
                       zero_err="", hit=[], witness="SKIP")
        else:
            row["general"], row["general_err"] = compile_one(
                SORRY_RE.sub(GENERAL, sig), os.path.join(tmp, "g%02d.lean" % no))
            row["zero"], row["zero_err"] = compile_one(
                SORRY_RE.sub(ZERO, sig), os.path.join(tmp, "z%02d.lean" % no))
            row["hit"] = []
            if row["zero"] == "PASS":
                for label, tactic in ZERO_STRATEGIES:
                    st, _ = compile_one(
                        SORRY_RE.sub(tactic, sig),
                        os.path.join(tmp, "h%02d_%d.lean" % (no, len(row["hit"]))))
                    if st == "PASS":
                        row["hit"].append({"label": label, "tactic": tactic})
            w = WITNESS.get(no)
            row["witness"] = ("SKIP" if not w else
                              compile_one(SORRY_RE.sub(w, sig),
                                          os.path.join(tmp, "w%02d.lean" % no))[0])
        out.append(row)
        print("%02d S=%-5s G=%-5s Z=%-5s W=%-5s hit=%s  %s"
              % (no, row["stated"], row["general"], row["zero"],
                 row["witness"], ",".join(h["label"] for h in row["hit"]),
                 row["stated_err"][:58]), flush=True)
    json.dump({"rows": out, "zero_strategies": ZERO_STRATEGIES},
              open("/tmp/fidelity_probe_full.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n写入 /tmp/fidelity_probe_full.json，共", len(out), "条")


if __name__ == "__main__":
    main()
