"""可表达率探针（0-LLM 评估床）：搜索/枚举路线究竟能覆盖多少题？

## 这个探针回答什么

**不是**「我的 `detect()` 正则认得出几道题」——那只会测出我自己写的正则有多长。
**是**「按答案形态与题面结构，多少题的答案**能由有限枚举产生、并由精确计算验证**」。

区分三档（措辞保守，宁可低估）：

| 档 | 含义 | 判据 |
|---|---|---|
| `E1` 机械可判定 | 存在可枚举/可递推的对象空间，谓词可精确计算 ⇒ 枚举/DP **能产生**答案 | 答案离散 + 题面有界或对象显式有限 + 无连续/几何 |
| `E2` 只能验证 | 答案不是离散对象（闭式、集合、证明），枚举**只能复核候选、不能产生候选** | 无连续/几何，但答案形态或定义域不满足 E1 |
| `E3` 不可机械化 | 涉及实数/积分/概率/几何/函数方程 ⇒ 需洞察或构造 | 题面含 `real numbers` / `\\int` / `\\triangle` / `f(x)=` 等 |

★ `E1` 只表示「机械上可做」，**不表示便宜**：Motzkin 计数要 DP、组合计数要容斥。
   把 `E1` 当成「写个 for 循环就行」是误读。

★★ **E1/E2/E3 三层未经校准，不得作为证据引用。** 人工抽查 18 例有 6 例判错，
   且错法不是随机的 —— 静态结构信号分不清「答案是个整数」与「答案能枚举出来」：
   - 假阳性：「2017 位数学家点餐，答案 127009」「30 个学生最大 k，答案 6」被 `count`
     信号判成 E1，实际需要洞察或极值证明；
   - 假阴性：「determine all positive integers n such that…」（答案 `2, 3`）是**最典型**
     的可搜索形态，因题面无显式区间被判成 E2。
   ⇒ 本探针**只应引用三项客观量**：① 答案形态分布 ② `P(答案可被整数表示)`
     ③ 「有界量词 ∧ (整除 | is an integer)」的占比。分档结论仅供定位。

## 为什么要跑全量而不是 8 题

`题库/omni8_20261027.jsonl` 的抽样规则里有一条「**答案纯整数**」。
若「答案纯整数」在总体里是少数，则 omni8 是**条件样本**，其机械路径率不能外推。
本探针第一项输出就是这条：`P(answer 是纯整数)` 在 omni8 与全量上的差。

用法::

    python probe_search_expressible.py                       # omni 全量 + omni8 + official112
    python probe_search_expressible.py --bank <path>         # 单库
    python probe_search_expressible.py --sample 12           # 每档抽 12 题原文
    python probe_search_expressible.py --json out.json       # 落盘逐题判定
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter

# ---------------------------------------------------------------- 读题

OMNI_ALL = "题库/omni_math/test.jsonl"
OMNI8 = "题库/omni8_20261027.jsonl"
OFFICIAL112 = "题库/official112_本地测试题库/official112_full.jsonl"


def load(path: str) -> list:
    rows = []
    for ln in io.open(path, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            rows.append(json.loads(ln))
    return rows


def text_of(row: dict) -> str:
    return str(row.get("problem") or row.get("question") or "")


# ---------------------------------------------------------------- 答案形态

_BOX = re.compile(r"\\boxed\s*\{([^{}]*)\}")
_INT = re.compile(r"^[-+]?\d{1,18}$")
_RAT = re.compile(r"^[-+]?\d{1,18}\s*/\s*\d{1,9}$")
_DEC = re.compile(r"^[-+]?\d+(?:\.\d+)?$")
_MULTI_INT = re.compile(r"^[-+]?\d{1,18}(?:\s*,\s*[-+]?\d{1,18})+$")


def norm_answer(a) -> str:
    """剥 `$`、`\\boxed{}`、外层花括号 —— 只做形态归一，不改数值。"""
    s = str(a if a is not None else "").strip()
    for _ in range(4):
        m = _BOX.search(s)
        if m:
            s = m.group(1).strip()
            continue
        t = s.strip().strip("$").strip()
        if t == s:
            break
        s = t
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()
    return s


def answer_kind(a: str) -> str:
    if not a:
        return "empty"
    if _INT.match(a):
        return "int"
    if _RAT.match(a) or _DEC.match(a):
        return "rat"
    if _MULTI_INT.match(a):
        return "int_list"
    low = a.lower()
    if low in ("proof", "proved", "q.e.d.", "qed") or low.startswith("proof"):
        return "proof"
    if re.search(r"[A-Za-z\\]", a):
        return "expr"
    return "other"


# ---------------------------------------------------------------- 题面结构信号
# 全部是「有没有」的布尔信号，不做解析 —— 这是刻意保守：
# 宁可把可机械化的题漏进 E2/E3（低估覆盖），也不要靠猜算子边界制造假阳性。

_SIG = {
    # 双侧有界：`0 \le x \le 19` / `100 \leq n \leq 1997`
    "bounded2": re.compile(r"\d{1,6}\s*(?:\\le|\\leq|≤|<)\s*[A-Za-z]\s*(?:\\le|\\leq|≤|<)\s*\d{1,6}"),
    # 单侧上界：`n \le 100` / `positive integers n \leq 100`
    "boundedhi": re.compile(r"[A-Za-z]\s*(?:\\le|\\leq|≤|<)\s*\d{1,6}"),
    # 计数问法
    "count": re.compile(r"number of|how many|how many ways|count the|compute the number"),
    # 显式有限组合对象
    "finite": re.compile(r"permutation|subset|partition|colou?ring|graph|tuple|arrangement|"
                         r"sequence of length|subsequence|grid"),
    # 连续量（实数、积分、概率、极限、可微）—— E3 的硬信号
    "continuous": re.compile(r"real numbers?|\\mathbb\{R\}|\\int\b|integral|probability|"
                             r"\\lim\b|continuous|differentiab|\\in\\(0,1\\)|expected value|expectation"),
    # 几何
    "geom": re.compile(r"\\triangle|\\angle|circum|tangent|\\overline|incircle|"
                       r"perpendicular|midpoint of"),
    # 函数方程 / 泛函
    "funceq": re.compile(r"functional equation|f\s*\(\s*[a-z]\s*\)\s*=|f\s*:\s*\\mathbb|"
                         r"f\s*:\\\s*(?:\\mathbb\{R\}|R)\s*(?:\\to|→)"),
    # 证明题（题面要求证明，而不是求值）
    "proof": re.compile(r"\bprove\b|\bshow that\b|证明"),
    # 整除/同余
    "divis": re.compile(r"\\mid\b|divides|divisible|整除|\\equiv|\\pmod"),
    # 「… is an integer」型谓词（含 `\frac{a}{b}` 形式）—— 3556 属于这一支，
    # 旧版只统计 divis ⇒ 把它漏掉了
    "int_cond": re.compile(r"(?:is|are)\s+(?:also\s+)?(?:an?\s+)?integers?"
                           r"|是整数|为整数"),
    # 无穷对象
    "infinite": re.compile(r"for all (?:positive )?integers|infinitely many|"
                           r"all sufficiently large|sequence \{?a_n\}?|\\sum_\{n=|series"),
}


def signals(problem: str) -> dict:
    return {k: bool(p.search(problem)) for k, p in _SIG.items()}


# ---------------------------------------------------------------- 三档判定


def verdict(kind: str, sig: dict) -> str:
    # ① 连续 / 几何 ⇒ 无论答案形态都不可机械枚举
    if sig["continuous"] or sig["geom"]:
        return "E3"
    # ② 整题是「对任意参数成立」的闭式命题（函数方程、无穷族）⇒ 枚举只能验证
    if sig["funceq"] and kind != "int":
        return "E3"
    if sig["infinite"] and kind != "int":
        return "E3"
    # ③ 证明题：枚举能找反例、不能给证明
    if sig["proof"] and kind in ("proof", "expr", "empty"):
        return "E3"
    # ④ 答案离散 ⇒ 枚举/DP 能产生答案
    if kind in ("int", "int_list"):
        if sig["bounded2"] or sig["boundedhi"] or sig["finite"] or sig["count"]:
            return "E1"
        return "E2"
    # ⑤ 答案非离散（闭式、实数、集合描述）
    if kind in ("rat",):
        return "E2" if (sig["bounded2"] or sig["boundedhi"] or sig["count"]) else "E3"
    if kind in ("expr", "other"):
        # 有界 + 非连续 ⇒ 枚举可验证候选（E2）
        return "E2" if (sig["bounded2"] or sig["boundedhi"]) else "E3"
    return "E2"


def analyse(rows: list, name: str) -> dict:
    out = []
    for r in rows:
        text = text_of(r)
        kind = answer_kind(norm_answer(r.get("answer")))
        sig = signals(text)
        out.append({
            "id": r.get("id") or r.get("source") or "",
            "domain": r.get("domain", ""),
            "difficulty": r.get("difficulty", ""),
            "answer_kind": kind,
            "verdict": verdict(kind, sig),
            "signals": [k for k, v in sig.items() if v],
            "answer": norm_answer(r.get("answer"))[:60],
            "problem": text[:200],
        })
    return {"bank": name, "n": len(rows), "rows": out}


# ---------------------------------------------------------------- 报告


def _pct(a: int, b: int) -> str:
    return "%.1f%%" % (100.0 * a / b) if b else "-"


def report(res: dict, show: int = 0) -> None:
    rows = res["rows"]
    n = res["n"]
    print("=" * 78)
    print("题库：%s   题数：%d" % (res["bank"], n))
    print("=" * 78)

    kinds = Counter(r["answer_kind"] for r in rows)
    vers = Counter(r["verdict"] for r in rows)
    print("\n[答案形态]  " + "  ".join("%s=%d(%s)" % (k, c, _pct(c, n))
                                      for k, c in kinds.most_common()))
    print("[机械可判定*] " + "  ".join("%s=%d(%s)" % (k, c, _pct(c, n))
                                      for k, c in sorted(vers.items()))
          + "   *未校准粗分，不可引用")

    # 交叉：答案形态 × 档
    print("\n[交叉表] 行=答案形态，列=档")
    hdr = "%-10s %8s %8s %8s %8s" % ("kind", "E1", "E2", "E3", "row")
    print(hdr)
    for k, c in kinds.most_common():
        e1 = sum(1 for r in rows if r["answer_kind"] == k and r["verdict"] == "E1")
        e2 = sum(1 for r in rows if r["answer_kind"] == k and r["verdict"] == "E2")
        e3 = sum(1 for r in rows if r["answer_kind"] == k and r["verdict"] == "E3")
        print("%-10s %8d %8d %8d %8d" % (k, e1, e2, e3, c))

    # 关键标量：题面里出现「有界量词 + 整除/同余」的比例（E12 检测器的语义域上界）
    both = sum(1 for r in rows
               if ("bounded2" in r["signals"] or "boundedhi" in r["signals"])
               and ("divis" in r["signals"] or "int_cond" in r["signals"]))
    print("\n[E12 语义域] 有界量词 ∧ (整除 | is an integer)：%d/%d（%s）"
          % (both, n, _pct(both, n)))

    if show:
        print("\n[抽样原文]" + "-" * 60)
        seen = Counter()
        for r in rows:
            if seen[r["verdict"]] >= show:
                continue
            seen[r["verdict"]] += 1
            print("\n<%s | %s | %s> ans=%r" % (r["verdict"], r["answer_kind"],
                                               ",".join(r["signals"]), r["answer"]))
            print("  " + r["problem"].replace("\n", " ")[:190])
    print()


def compare(omni_all: dict, omni8: dict) -> None:
    """核心输出：omni8 是不是条件样本。"""
    print("=" * 78)
    print("★ omni8 vs omni 全量：抽样偏差检验")
    print("=" * 78)
    a, b = omni_all["rows"], omni8["rows"]
    for key, label in (("answer_kind", "答案形态"), ("verdict", "机械可判定")):
        ca = Counter(r[key] for r in a)
        cb = Counter(r[key] for r in b)
        keys = sorted(set(ca) | set(cb))
        print("\n[%s]" % label)
        print("%-10s %18s %18s" % ("", "omni 全量(n=%d)" % len(a), "omni8(n=%d)" % len(b)))
        for k in keys:
            print("%-10s %18s %18s" % (
                k,
                "%d (%s)" % (ca.get(k, 0), _pct(ca.get(k, 0), len(a))),
                "%d (%s)" % (cb.get(k, 0), _pct(cb.get(k, 0), len(b))),
            ))
        # 纯整数答案 = 枚举能「产生答案」的硬上界
    pa = sum(1 for r in a if r["answer_kind"] in ("int", "int_list"))
    pb = sum(1 for r in b if r["answer_kind"] in ("int", "int_list"))
    print("\n★ P(答案可被单个整数/整数列表表示)：全量 %s  vs  omni8 %s"
          % (_pct(pa, len(a)), _pct(pb, len(b))))
    print("  ⇒ omni8 的这一维若显著高于全量，则它是在该条件下抽的样本，")
    print("    其「机械路径率」不能外推为通用能力。")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", action="append", default=None)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    banks = args.bank or [OMNI_ALL, OMNI8, OFFICIAL112]
    results = []
    for p in banks:
        try:
            rows = load(p)
        except OSError as e:
            print("跳过 %s：%s" % (p, e), file=sys.stderr)
            continue
        res = analyse(rows, p.split("/")[-1])
        results.append(res)
        report(res, show=args.sample)

    if len(results) >= 3:
        try:
            compare(results[0], results[1])
        except IndexError:
            pass

    if args.json:
        io.open(args.json, "w", encoding="utf-8").write(
            json.dumps(results, ensure_ascii=False, indent=1))
        print("逐题判定已写入 %s" % args.json)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
