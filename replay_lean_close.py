# -*- coding: utf-8 -*-
"""评估床：形式签名的**真实**可闭合率（零 LLM，需 Lean 工具链）。

## 为什么需要这个床

历史观测里 `HARD_CLOSED = 0/448`、`tool_ran=True` 在 1087 条子目标里 0 条。
长期结论是「系统里不存在可硬闭合的对象」。本床证明这个结论是**错的**：
不是没有可闭合的对象，是**工具一次都没跑过**（744 行 `04_subgoal_results`
的 `tool_verdict` 全空、`tool_ran` 全 False）。

## 做了什么

规划层产出的 `formal_sig` 一律形如

    example (x : ℝ) (h : x ^ 2 = 3) : ... := by sorry

`sorry` 同时屏蔽了两种检查：
  1. 命题是不是**合法**的 Lean 命题（未定义符号、字段名错、括号不配都会被吃掉）
  2. 命题是不是**被证明**了（sorry 让编译器无条件通过）

本床把 `sorry` 换成自动策略组合，逐条真编译，四分类：

| 分类 | 含义 |
|---|---|
| `PASS` | 自动策略证出来了 = **真硬闭合** |
| `LEGAL` | 命题合法，但自动策略证不出（需人/模型给证明） |
| `REFUTED` | 正向失败而**反命题**被自动策略证出 ⇒ 命题是假的 |
| `ILLEGAL` | 命题本身写不出来（语法/未定义符号/类型错） |

★ 单向判据的教训：只报 PASS 率会把「命题写不出来」混进「证不出来」，
   所以四类必须分开报，且 `ILLEGAL` 再细分原因。

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

TACTIC = ("first | decide | norm_num | omega | simp | linarith | ring_nf | positivity "
          "| nlinarith | gcongr | assumption | rfl")
PRELUDE = "import Mathlib.Tactic\n\nset_option maxHeartbeats 400000\n\n"
SORRY_RE = re.compile(r"\b(sorry|admit)\b")
TAIL_RE = re.compile(r":=\s*by\s*(?:sorry|admit)\s*$", re.S)

# 非法原因细分（顺序即优先级，先命中先归类）
ILLEGAL_KINDS = (
    ("未定义符号", r"unknown (identifier|constant|namespace|free variable)"),
    ("语法/括号", r"unexpected token|expected token|expected '|unexpected identifier"),
    ("类型实例缺失", r"failed to synthesize|synthInstanceFailed"),
    ("字段/应用不存在", r"Function expected|Application type mismatch|Invalid field|unknown field"),
)


def split_sig(sig):
    """拆出 (声明头, 命题)。

    先剥掉尾部的 `:= by sorry`，再找**括号深度为 0 的第一个冒号**作为分隔。

    ★ 三种错法都试过，只有这一种对：
      - 非贪婪 `^(.*?):` ⇒ `example (x : ℝ) : P` 被在类型标注处切开；
      - **从右往左找最后一个冒号** ⇒ `example : ∀ k : ℕ, P` 被在 `k : ℕ` 处切开
        （单测 `test_split_sig_nested_colon` 抓到的就是这个）；
      - 平扫第一个冒号但不看深度 ⇒ `example (x : ℝ) : P` 又被切开。
      判据必须是「深度 0」，因为绑定变量的类型标注、`∀` 的冒号都在括号内或紧随量词。
    """
    m = TAIL_RE.search(sig.strip())
    if not m:
        return None
    core = sig.strip()[:m.start()].rstrip()
    depth = 0
    for i, ch in enumerate(core):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif ch == ":" and depth == 0:
            if i == 0:
                return None
            return core[:i].rstrip(), core[i + 1:].strip()
    return None


def classify(first_err, returncode):
    """把一次编译结果归到四分类之一。纯函数，可单测。"""
    if returncode == 0:
        return "PASS", ""
    if "unsolved goals" in (first_err or ""):
        return "LEGAL", ""
    return "ILLEGAL", illegal_kind(first_err or "")


def illegal_kind(err):
    for name, pat in ILLEGAL_KINDS:
        if re.search(pat, err):
            return name
    return "其它"


def _run(code, path, timeout=90):
    with open(path, "w", encoding="utf-8") as f:
        f.write(PRELUDE + code + "\n")
    try:
        p = subprocess.run(["lean", path], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    err = (p.stderr or p.stdout or "").strip()
    first = next((ln.strip() for ln in err.splitlines() if "error" in ln), "")
    return p.returncode == 0, first


def judge_one(item, tmp, idx):
    """单条四分类。正反两次编译才有 REFUTED，所以不能只看正向。"""
    got = split_sig(item["sig"])
    if not got:
        return dict(item, cat="UNPARSED", kind="", err=item["sig"][:120])
    head, prop = got
    # ★ 正向用**原形**（只替换 sorry，不额外加括号）—— 加括号会引入伪语法错误
    body = SORRY_RE.sub(TACTIC, item["sig"].strip())
    ok, err = _run(body, os.path.join(tmp, "f%05d.lean" % idx))
    if ok:
        return dict(item, cat="PASS", kind="", err="")
    cat, kind = classify(err, 1)
    if cat == "ILLEGAL":
        return dict(item, cat=cat, kind=kind, err=err)
    ok2, _ = _run("%s : ¬ (%s) := by %s" % (head, prop, TACTIC),
                  os.path.join(tmp, "b%05d.lean" % idx))
    if ok2:
        return dict(item, cat="REFUTED", kind="命题是假的", err=err)
    return dict(item, cat="LEGAL", kind="", err=err)


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
    print("\n== 四分类（n=%d，题次 %d）==" % (len(res), n_q))
    for k in ("PASS", "LEGAL", "REFUTED", "ILLEGAL", "UNPARSED"):
        if c.get(k):
            print("  %-10s %4d  %5.1f%%" % (k, c[k], 100.0 * c[k] / n))
    kinds = collections.Counter(r["kind"] for r in res if r["cat"] == "ILLEGAL")
    if kinds:
        print("  -- ILLEGAL 细分 --")
        for k, v in kinds.most_common():
            print("     %-14s %4d" % (k, v))
    byq = collections.defaultdict(set)
    for r in res:
        byq[r["qid"]].add(r["cat"])
    npass = sum(1 for s in byq.values() if "PASS" in s)
    print("\n== 题级：至少一条真硬闭合 ==")
    print("  %d / %d 题" % (npass, len(byq)))
    print("\n★ PASS = 真硬闭合（自动策略证出）；LEGAL ≠ 真，只是没被判死；"
          "REFUTED = 命题本身是假的。三者不可合并报。")


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
        print("[%3d/%d] %-9s %-12s %s" % (i + 1, len(sigs), r["cat"], r["kind"], item["qid"]),
              flush=True)
        if (i + 1) % 25 == 0:
            print("   ... %.0fs" % (time.time() - t0), flush=True)
    out = "/tmp/lean_close_res.json"
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    report(res, n_q)
    print("明细 %s ，用时 %.0fs" % (out, time.time() - t0))


if __name__ == "__main__":
    main()
