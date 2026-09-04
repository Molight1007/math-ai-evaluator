# -*- coding: utf-8 -*-
"""证明结构指纹（Proof Fingerprint）。

**这是本实验的方法论核心。**

老师的问题"模型能否观察到更本质的数学结构 / 能否联想"，过去的做法只能靠
人工读答案打分（主观、不可规模化的）。这里换成一个可计算的代理量：

    一个证明用了哪些 tactic / 引理  ==  它走的是哪条"结构路径"

例如同样证明不等式：
  - `nlinarith [sq_nonneg (a-b)]`  → 走的是"配方法 / 平方和非负"
  - `nlinarith` 裸用               → 走的是"暴力代数消元"
  - `induction`                    → 走的是"归纳结构"

于是"方法迁移"就能被量化成两个指纹集合的重合度，而不再依赖主观判断。
"""
from __future__ import annotations

import re

# tactic 词汇表（用 \b 词边界匹配，避免 ring 误命中 ring_nf）
TACTIC_VOCAB: list[str] = [
    "norm_num", "ring", "ring_nf", "nlinarith", "linarith", "omega",
    "positivity", "field_simp", "gcongr", "simp", "simpa", "aesop",
    "induction", "cases", "rcases", "constructor", "use", "push_neg",
    "by_contra", "by_cases", "calc", "decide", "native_decide",
    "linarith?", "contradiction", "exact", "apply", "rw",
]

# 引理 / 定理词汇表（体现"用了什么数学事实"）
LEMMA_VOCAB: list[str] = [
    "sq_nonneg", "sq_pos_of_pos", "mul_nonneg", "div_nonneg",
    "le_of_lt", "ne_of_gt", "abs_nonneg", "abs_add_le", "Nat.Prime",
    "Nat.prime_def_lt", "Nat.dvd_prime", "Int.dvd_of_emod_eq_zero",
    "Finset.sum_range_succ", "mul_nonneg_iff_of_pos_left", "sub_nonneg",
    "ge_iff_le",
]

VOCAB: list[str] = TACTIC_VOCAB + list(dict.fromkeys(LEMMA_VOCAB))


def fingerprint(code: str) -> set[str]:
    """抽取一段 Lean 代码的结构指纹（出现的 tactic / 引理集合）。"""
    if not code:
        return set()
    found: set[str] = set()
    for w in VOCAB:
        pat = r"\b" + re.escape(w).replace(r"\?", r"\??") + r"\b"
        if re.search(pat, code):
            found.add(w)
    return found


def coverage(fp: set[str], core: list[str] | set[str]) -> float:
    """目标指纹覆盖"共享结构核心"的比例 —— 核心结构迁移率。"""
    core_set = set(core)
    if not core_set:
        return 0.0
    return len(fp & core_set) / len(core_set)


def jaccard(a: set[str], b: set[str]) -> float:
    """两指纹集合的 Jaccard 相似度 —— 方法一致度。"""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def inherit(tgt: set[str], src: set[str]) -> float:
    """目标对源方法的继承率：源里用到的方法，目标沿用了多少。"""
    if not src:
        return 0.0
    return len(tgt & src) / len(src)


def transfer_scores(
    src_fp: set[str],
    tgt_fp: set[str],
    core_family: list[str],
) -> dict[str, float]:
    """一次迁移实验的全部指纹指标。"""
    return {
        "core_coverage": round(coverage(tgt_fp, core_family), 3),
        "src_tgt_jaccard": round(jaccard(src_fp, tgt_fp), 3),
        "src_tgt_inherit": round(inherit(tgt_fp, src_fp), 3),
    }
