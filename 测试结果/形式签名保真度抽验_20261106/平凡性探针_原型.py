#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""形式签名「平凡性探针」原型（零配额、只读、评估床，δ=0）

运行环境：服务器 ~/mathpilot，必须先 `source deploy/lean-env.sh`，
          用 `.venv/bin/python` 执行；依赖 /tmp/fidelity_picks.json。
          服务器无 pytest，本脚本不是测试。

两档探针，必须分开报（对应 E30 三道门）：
  P1 可陈述：原样 `:= by sorry` 编译（只出 sorry warning 即算 STATABLE）
  P2 平凡性：把 sorry 换成「定向平凡见证」，若编译通过 ⇒ 无需任何数学即可证出

★ 2026-11-07 原型实测结论（6 条抽样 + 4 条定向见证）：
  · 通用自动策略 TACTIC = first | decide | norm_num | omega | simp | ... 抓不到
    这批空洞：6 条里 0 条被判平凡（#11 正常 / #14 #17 #22 语法或实例失败 /
    #21 #24 unsolved goals）。原因是它不含 use / constructor / Or.inr 这类
    构造性步骤 ⇒ E28 报的 TRIVIAL 只有 6 条，可能是探针太弱而非空洞少。
  · 定向见证有效：
      #21 `exact ⟨360 / Nat.gcd 360 (2 * θ), rfl⟩`      → PASS（存在性平凡化）
      #24 `refine ⟨∅, Or.inr ?_⟩; simp`                  → PASS（括号优先级漏洞）
      #11 `aesop`（正常命题对照）                        → FAIL
  · #14 卡在 `∑ i in s,` 记法：服务器 mathlib 闭包三种 import 方案全部失败
    （A `open scoped BigOperators` FAIL / B 加 `open Finset` FAIL /
     C 显式 import BigOperators 直接 object file 缺失）⇒ 该签名在此环境
    「不可陈述」，但这属于环境记法缺失，不能直接推出「命题空洞」。

★ 边界：探针只给**存在性证据**（能证出的确实平凡），不保证没证出的就不平凡；
  见证代码由模型/人工按形态构造，编译只验证「这个见证成立」，不验证「已穷尽」。
  不作效果量、不宣称等价、不宣称评测通过。
"""
import json
import os
import subprocess
import tempfile

from contracts.formal_sig_gate import SORRY_RE

PRELUDE = ("import Mathlib.Tactic\n\nopen scoped BigOperators\n\n"
           "set_option maxHeartbeats 400000\n\n")
TACTIC = ("first | decide | norm_num | omega | simp | linarith | ring_nf "
          "| positivity | nlinarith | gcongr | assumption | rfl")

# 编号 -> 定向平凡见证（不带 `by`；SORRY_RE 只匹配 sorry 这个单词！）
WITNESS = {
    11: "aesop",                                        # 正常命题，作对照
    14: "refine ⟨∅, ?_⟩; simp",                         # 空集 + ℕ 截断减法
    21: "exact ⟨360 / Nat.gcd 360 (2 * θ), rfl⟩",      # ∃ k, k = expr 平凡化
    24: "refine ⟨∅, Or.inr ?_⟩; simp",                  # ∧/∨ 优先级漏掉 Infinite
}


def compile_one(code, path, timeout=75):
    with open(path, "w", encoding="utf-8") as f:
        f.write(PRELUDE + code.strip() + "\n")
    try:
        r = subprocess.run(["lean", path], capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ""
    err = (r.stderr or r.stdout or "").strip()
    first = next((ln.strip() for ln in err.splitlines() if "error" in ln), "")
    return ("PASS" if r.returncode == 0 else "FAIL"), first[:160]


def main():
    d = json.load(open("/tmp/fidelity_picks.json", encoding="utf-8"))
    blind = {b["no"]: b for b in d["blind"]}
    tmp = tempfile.mkdtemp(prefix="fidelity_probe_")
    print("no  stated  general  witness  first_error")
    for no in sorted(WITNESS):
        sig = blind[no]["formal_sig"]
        s, e1 = compile_one(sig, os.path.join(tmp, "s%02d.lean" % no))
        g, e2 = compile_one(SORRY_RE.sub(TACTIC, sig),
                            os.path.join(tmp, "g%02d.lean" % no))
        w, e3 = compile_one(SORRY_RE.sub(WITNESS[no], sig),
                            os.path.join(tmp, "w%02d.lean" % no))
        print("%02d  %-7s %-8s %-8s %s"
              % (no, s, g, w, (e1 or e2 or e3)[:80]))
    print("\n只报存在性：witness=PASS 的条目确有编译级平凡证明；"
          "witness=FAIL 不代表命题不平凡，也不代表探针完备。")


if __name__ == "__main__":
    main()
