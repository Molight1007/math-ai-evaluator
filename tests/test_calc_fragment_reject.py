# -*- coding: utf-8 -*-
"""4.4 提取层「段残片拒收」+ `%` 提取（2026-10-29）。

样本全部取自真实产物原文（服务器 `results/20261028-215738/qfaed7d35/05_candidates.json`
的 `reasoning`，`omni-3556`），不是构造出来的 toy case —— 因为这类 bug
只有真实数学排版（Lean 代码块、`\\operatorname{ord}`、二进制表示、链式记号）
才能触发。

背景：`n_bad > 0` 即淘汰**整个候选**，所以一条提取残片就足以误杀正确解。
`omni-3556` 两个候选的答案都是 gold 946，却被 4.4 清池（`08_final.json`
`n_candidates=0`）。逐条复核那批 bad，**没有一条是候选真算错**。
"""
from __future__ import annotations

import pytest

from agent.math_check_gate import (
    _extract_inequalities,
    _extract_numeric_equations,
    _is_fragment,
)


# --------------------------------------------------------------- F1 括号不平衡
@pytest.mark.parametrize("lhs,rhs", [
    ("- 1)", "1"),        # official112-002 原文残片
    ("9)", "1"),          # omni-3556 `\pmod 9` 被切开
    ("(2", "6"),
])
def test_f1_unbalanced_parens_rejected(lhs, rhs):
    assert _is_fragment(lhs, rhs, "eq") is True


# --------------------------------------------------- F2 双原子而字面不同
@pytest.mark.parametrize("lhs,rhs", [
    ("2", "10"),          # 二进制写法 `2₁₀ = 10₂`（official112-032）
    ("8", "1000"),
    ("4", "1200"),        # official112-042
    ("2", "0"),           # official112-007/010，出现 6 次
    ("(2)", "6"),         # `\operatorname{ord}_9(2)=6` 被切开
    ("1", "0"),
])
def test_f2_two_atoms_different_rejected(lhs, rhs):
    assert _is_fragment(lhs, rhs, "eq") is True


@pytest.mark.parametrize("lhs,rhs", [
    ("-5", "-5"),         # 同义反复：保留（tests/test_math_check_gate.py 已守）
    ("2", "2"),
    ("(2)", "2"),
    ("05", "5"),
])
def test_f2_same_atom_kept(lhs, rhs):
    assert _is_fragment(lhs, rhs, "eq") is False


# ------------------------------------------------------------ F3 悬空符号
def test_f3_dangling_minus_rejected():
    """`official112-032` 的 4 条 `-  2^k = 2^k`：原文是 `A - 2^k`，左操作数被切。"""
    for lhs, rhs in (("-  2^1", "2"), ("-  2^3", "8"),
                     ("-  2^5", "32"), ("-  2^7", "128")):
        assert _is_fragment(lhs, rhs, "eq") is True


def test_f3_real_negative_kept():
    """真一元负号无空格 ⇒ 不判碎片。"""
    assert _is_fragment("-2^3", "-8", "eq") is False


# --------------------------------------------------- 反例保护：非双原子保留
@pytest.mark.parametrize("lhs,rhs", [
    ("2^2", "4"),
    ("6*111", "666"),
    ("262144+2", "262146"),
    ("473", "11*43"),
    ("2^(666) % 9", "1"),
])
def test_non_atom_pairs_kept(lhs, rhs):
    assert _is_fragment(lhs, rhs, "eq") is False


# ------------------------------------------------------------ `%` 提取
def test_modulo_is_one_operand_not_two():
    """`4 % 3 = 1` 旧版切成 `('3','1')` ⇒ 判「3 算错」⇒ 淘汰整候选。"""
    assert _extract_numeric_equations("4 % 3 = 1") == [("4 % 3", "1")]
    assert ("2^(666) % 9", "1") in _extract_numeric_equations("$2^{666} % 9 = 1$")


def test_modulo_leads_to_real_verification():
    """修好后能真正验证取模（而不是判算错）。"""
    from tools.agent_toolkit.calc_verify import calc_verify
    rv = calc_verify([{"expr": e, "claimed": c} for e, c in
                      [("4 % 3", "1"), ("2^666 % 9", "1"), ("(2^1+2)%1", "0")]])
    assert rv["n_bad"] == 0
    assert rv["n_ok"] == 3


# ------------------------------------------------- 端到端：真实原文不再判死
_LEAN_SEG = """```lean
example (n : ℕ) (h : (2^n + 2) % n = 0) : Even n := by
  contrapose! h
  -- n 为奇数且 n > 1（若 n = 1 则显然偶数不成立，但 n = 1 时 (2^1+2)%1=0，
  -- 而 Even 1 为假；此处我们证明：若 n 为奇数且 n ∣ 2^n+2 则 n = 1，
  -- 从而在 n ≥ 2 的范围内得到矛盾。实际上我们直接证明奇数 n > 1 不可能。
  have hn1 : n ≠ 1 := by
    intro hn1
    rw [hn1] at h
```"""

_ORD_SEG = (r"需要避免 $9\mid n$ 或确保 $2^{n-1}\equiv -1\pmod 9$。但 "
            r"$2^{n-1}\equiv -1\pmod 9$ 要求 $2^{2(n-1)}\equiv 1\pmod 9$，而 "
            r"$\operatorname{ord}_9(2)=6$，所以 $6\mid 2(n-1)$ 但 $6\nmid n-1$")


def test_real_lean_block_yields_no_false_bad():
    """Lean 代码块里的 `n ≠ 1` / `h2` 曾被提成 `1 = 0`、`2 = 1` ⇒ 整候选淘汰。"""
    from tools.agent_toolkit.calc_verify import calc_verify
    eqs = _extract_numeric_equations(_LEAN_SEG)
    items = [{"expr": a, "claimed": b} for a, b in eqs]
    if items:
        assert calc_verify(items)["n_bad"] == 0


def test_real_ord_segment_rejected():
    """`\\operatorname{ord}_9(2)=6` 曾提成 `('(2)','6')`。"""
    frags = []
    _extract_numeric_equations(_ORD_SEG, stats=frags)
    assert all(f["why"] == "fragment" for f in frags)


def test_stats_records_every_rejection():
    """拒收必须留痕（不能静默：下次才分得清「提取 15 条」与「算了 15 条」）。"""
    frags = []
    eqs = _extract_numeric_equations("$2 = 10$ 与 $2^2 = 4$", stats=frags)
    assert ("2^2", "4") in eqs
    assert len(frags) == 1
    assert frags[0]["expr"] == "2" and frags[0]["claimed"] == "10"


def test_inequalities_also_filtered():
    """不等式一侧同受碎片判据保护（括号不平衡）。

    注意 `$9) >= 1$` 到不了碎片判据：`_extract_inequalities` 要求任一侧含
    强运算符（`^ * /`），`9)` 与 `1` 都没有 ⇒ 更早就被拒。这里用含 `^`
    的残片，才能验证碎片判据本身生效。
    """
    frags = []
    got = _extract_inequalities("$2^3) >= 8$", stats=frags)
    assert got == []
    assert frags and frags[0]["why"] == "fragment"


def test_stats_default_none_keeps_backward_compat():
    """不传 stats 时行为与旧签名一致（原地调用点无需改）。"""
    assert _extract_numeric_equations("$2^2 = 4$") == [("2^2", "4")]
    assert _extract_inequalities("$x^2 - 1 >= 0$")
