# -*- coding: utf-8 -*-
"""评估床：形式签名的**真实**可闭合率（零 LLM，需 Lean 工具链）。

## 为什么需要这个床

历史观测 `HARD_CLOSED = 0/448`、`tool_ran=True` 在 1087 条子目标里 0 条。
2026-11-04 查清：不是没有可闭合的对象，是**工具一次都没跑过**
（744 行 `04_subgoal_results` 的 `tool_verdict` 全空、`tool_ran` 全 False）。

## 本床的两次自我修正（务必先读）

### 第一版：把 sorry 换成自动策略，报四分类 PASS/LEGAL/REFUTED/ILLEGAL

`REFUTED`（"正向失败、反命题可证 ⇒ 命题是假的"）报了 8 条，
**抽验 8 条全是 `example ... : False`** —— 这是反证法的标准形式
（假设条件不相容，导出矛盾），不是「规划层造了假结论」。
`¬ False` 恒真，反命题必然可证 ⇒ **该判据零信息量，8/8 误报**。
⇒ 已删除自动 REFUTED 判定。`prop == False` 单列 `CONTRADICTION`
（反证式，需要真证明，不计入假命题）。

`PASS` 报了 6 条，**抽验 6 条全是退化命题**：

    example ... : True
    example ... : (180 / Nat.gcd α 180) = (180 / Nat.gcd α 180)     # A = A
    example ... : (2^k - 2^l : ℤ) ∈ (Set.univ : Set ℤ)               # 恒真
    example ... : ∃ k : ℕ, k = 360 / Nat.gcd 360 (2 * θ)              # 取 k 为该式即可

⇒ 编译通过 ≠ 证明有内容。**闸门若被当成绩效指标，最省力的刷法就是产出退化命题。**
⇒ `is_trivial_prop()` 单列 `TRIVIAL`。它是**保守下界**（只认最明确的几种形态），
   不是完备判据；PASS 的命题全文强制写进明细 json 供人工抽验。

### 口径纪律（E27 教训）
「只翻一个变量」挡不住抽验。**任何判据类改动，效果量必须配人工抽验。**
本床的分类结果不得在未抽验的情况下当结论报出去。

## 分类

| 类 | 含义 |
|---|---|
| `PASS` | 自动策略证出，且命题非平凡 = **真硬闭合** |
| `TRIVIAL` | 编译通过但命题是退化/重言式（**不计入有效闭合**） |
| `CONTRADICTION` | `prop` 是 `False`，反证式证明步骤，需真证明 |
| `LEGAL` | 命题合法但自动策略证不出 |
| `ILLEGAL` | 命题本身写不出来（语法/未定义符号/类型错），再细分原因 |

★ 五类必须分开报。`TRIVIAL` 绝不能并入 `PASS`，`CONTRADICTION` 绝不能说成「假命题」。

## 用法

    cd ~/mathpilot && source deploy/lean-env.sh
    .venv/bin/python replay_lean_close.py /tmp/e21_license.json 20261015

依赖：`lean` 在 PATH 上、`LEAN_PATH` 指向 mathlib 闭包。
★ 单文件 `import Mathlib.Tactic` 约 2.4s / 峰值 RSS 3.4GB ⇒ **必须串行**，
  7.5G 内存下并发会 OOM。
"""
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
import time

# ★ 2026-11-04：切分 / 退化 / 非法原因的**唯一权威源**下沉到契约层，
#   主流程与回放床共用一份，避免两份正则漂移（项目已因口径漂移吃过亏：
#   值断言率 4.5% vs 32.4%、闭合率 0% 与 90% 被平均成 34%）。
from contracts.formal_sig_gate import (  # noqa: E402
    SORRY_RE, TAIL_RE, TRIVIAL_RULES,
    is_trivial_prop, split_sig, illegal_kind, classify_stated,
)

TACTIC = ("first | decide | norm_num | omega | simp | linarith | ring_nf | positivity "
          "| nlinarith | gcongr | assumption | rfl")
PRELUDE = "import Mathlib.Tactic\n\nset_option maxHeartbeats 400000\n\n"


def classify(first_err, full_err, returncode):
    """一次编译结果的初分类。纯函数，可单测。

    ★ 本函数判的是「自动策略**能否证出**」，不是「命题**能否陈述**」。
      后者用 `contracts.formal_sig_gate.classify_stated()`（保留 by sorry 编译）。
      两者失败原因不同：这里把「策略不够」与「命题非法」混在一起，E29 的
      37% 非法率是从中拆出来的估计 ⇒ 必须用门 A 的干净口径重量，
      见 `replay_sig_gate.py`。

    ★★ 判据不是「有没有 unsolved goals」，而是「有没有**别的** error 行」。
       Lean 在致命错误（unknown constant / Application type mismatch / Invalid field）
       之后做错误恢复，仍会留下 unsolved goals。2026-11-04 用「有 unsolved goals
       就判 LEGAL」误放了 12 条非法命题，抽验 12/12 全部仍应 ILLEGAL。
       ⇒ 只要存在任何非 unsolved-goals 的 error 行，一律 ILLEGAL。
    """
    if returncode == 0:
        return "PASS", ""
    if "TIMEOUT" in (first_err or ""):
        return "TIMEOUT", ""
    full = full_err or ""
    fatal = [ln for ln in full.splitlines()
             if "error" in ln and "unsolved goals" not in ln]
    if fatal:
        return "ILLEGAL", illegal_kind("\n".join(fatal))
    if "unsolved goals" in full:
        return "LEGAL", ""
    return "ILLEGAL", illegal_kind(full)


def _run(code, path, timeout=90):
    with open(path, "w", encoding="utf-8") as f:
        f.write(PRELUDE + code + "\n")
    try:
        p = subprocess.run(["lean", path], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", "TIMEOUT"
    err = (p.stderr or p.stdout or "").strip()
    first = next((ln.strip() for ln in err.splitlines() if "error" in ln), "")
    return p.returncode == 0, first, err


def judge_one(item, tmp, idx):
    """单条分类。★ 不再做反命题编译 —— 见 docstring 第一版自我修正。"""
    got = split_sig(item["sig"])
    if not got:
        return dict(item, cat="UNPARSED", kind="", err=item["sig"][:120], prop="")
    head, prop = got
    base = dict(item, prop=prop)
    # 正向用**原形**（只替换 sorry，不额外加括号）—— 加括号会引入伪语法错误
    body = SORRY_RE.sub(TACTIC, item["sig"].strip())
    ok, first, full = _run(body, os.path.join(tmp, "f%05d.lean" % idx))
    if ok:
        trivial = is_trivial_prop(prop)
        if trivial:
            return dict(base, cat="TRIVIAL", kind=trivial, err="")
        return dict(base, cat="PASS", kind="", err="")
    if prop.strip() == "False":
        # 反证法的标准形态：假设不相容、导出矛盾。不是「命题是假的」。
        return dict(base, cat="CONTRADICTION", kind="反证式", err=first)
    cat, kind = classify(first, full, 1)
    return dict(base, cat=cat, kind=kind, err=first)


def collect_sigs(index_path, since="20261015"):
    """从题次索引抽所有带 sorry 的 formal_sig。"""
    d = json.load(open(index_path, encoding="utf-8"))
    qs = d if isinstance(d, list) else (d.get("questions") or d.get("items") or [])
    qs = [q for q in qs if str(q.get("run_id") or "")[:8] >= since]
    out = []
    for q in qs:
        p = os.path.join(q["qdir"], "03_subgoals.json")
        if not os.path.exists(p):
            continue
        try:
            dd = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for sg in ((dd.get("plan") or {}).get("subgoals") or []):
            sig = str(sg.get("formal_sig") or "").strip()
            if sig and SORRY_RE.search(sig):
                out.append({"qid": q.get("qid"), "run": str(q.get("run_id"))[:8],
                            "sg_id": sg.get("id"), "type": sg.get("type"), "sig": sig})
    return out, len(qs)


def report(res, n_q):
    c = collections.Counter(r["cat"] for r in res)
    n = len(res) or 1
    print("\n== 五分类（n=%d 条形式签名 / 全部题次 %d）==" % (len(res), n_q))
    for k in ("PASS", "TRIVIAL", "CONTRADICTION", "LEGAL", "ILLEGAL", "TIMEOUT", "UNPARSED"):
        if c.get(k):
            print("  %-14s %4d  %5.1f%%" % (k, c[k], 100.0 * c[k] / n))
    kinds = collections.Counter(r["kind"] for r in res if r["cat"] == "ILLEGAL")
    if kinds:
        print("  -- ILLEGAL 细分 --")
        for k, v in kinds.most_common():
            print("     %-14s %4d" % (k, v))
    triv = collections.Counter(r["kind"] for r in res if r["cat"] == "TRIVIAL")
    if triv:
        print("  -- TRIVIAL 细分 --")
        for k, v in triv.most_common():
            print("     %-14s %4d" % (k, v))
    passes = [r for r in res if r["cat"] == "PASS"]
    if passes:
        print("\n  -- PASS 命题全文（强制人工抽验，未抽验不得当结论） --")
        for r in passes:
            print("     [%s] %s" % (r["qid"], str(r.get("prop") or "")[:220]))
    byq = collections.defaultdict(set)
    for r in res:
        byq[r["qid"]].add(r["cat"])
    npass = sum(1 for s in byq.values() if "PASS" in s)
    print("\n== 题级：至少一条**有效**硬闭合 ==")
    print("  %d / %d 全部题次；%d / %d 含形式签名的题次" %
          (npass, n_q, npass, len(byq)))
    print("\n★ TRIVIAL 不计入有效闭合；CONTRADICTION 是反证式，不是假命题。"
          "\n★ PASS 必须人工抽验后才能当结论报。明细里保留每条命题全文。")


def main():
    index = sys.argv[1] if len(sys.argv) > 1 else "/tmp/e21_license.json"
    since = sys.argv[2] if len(sys.argv) > 2 else "20261015"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    sigs, n_q = collect_sigs(index, since)
    if limit:
        sigs = sigs[:limit]
    print("题次 %d，带 sorry 的形式签名 %d 条" % (n_q, len(sigs)))
    tmp = tempfile.mkdtemp(prefix="leanclose_")
    t0 = time.time()
    res = []
    for i, item in enumerate(sigs):
        r = judge_one(item, tmp, i)
        res.append(r)
        print("[%3d/%d] %-14s %-12s %s" %
              (i + 1, len(sigs), r["cat"], r["kind"], item["qid"]), flush=True)
        if (i + 1) % 25 == 0:
            print("   ... %.0fs" % (time.time() - t0), flush=True)
    out = "/tmp/lean_close_res.json"
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    report(res, n_q)
    print("明细 %s ，用时 %.0fs" % (out, time.time() - t0))


if __name__ == "__main__":
    main()
