# -*- coding: utf-8 -*-
"""工具③不等式检测回归（2026-10-17 用户要求「计算错误靠工具检」）。

017 型错误：``a^2 + 3b^2 >= 4|a||b|^3`` 在 a=2,b=1 时 7 >= 8 为假——原工具
只验数值等式，此类不等式错误完全不在检测范围。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.math_check_gate import _extract_inequalities  # noqa: E402
from tools.agent_toolkit.calc_verify import calc_verify  # noqa: E402


def test_false_inequality_caught():
    """017 型假不等式必须被判 n_bad=1（随机代值确证反例）。"""
    r = calc_verify([{"expr": "a**2+3*b**2",
                      "claimed": "4*Abs(a)*Abs(b)**3", "op": "ge"}])
    assert r["n_bad"] == 1, r
    assert "不成立" in r["results"][0]["detail"]


def test_true_inequality_not_misjudged():
    """真不等式（AM-GM / 平方非负）绝不判成错（判不出就 n_err）。"""
    for it in ({"expr": "a**2+b**2", "claimed": "2*a*b", "op": "ge"},
               {"expr": "a**2", "claimed": "0", "op": "ge"}):
        r = calc_verify([it])
        assert r["n_bad"] == 0, (it, r)


def test_equality_still_works():
    r = calc_verify([{"expr": "2+3", "claimed": "6"}])
    assert r["n_bad"] == 1
    r2 = calc_verify([{"expr": "2+3", "claimed": "5"}])
    assert r2["n_ok"] == 1


def test_extract_strips_cn_and_abs():
    pairs = _extract_inequalities("由 a^2+3b^2 >= 4*|a|*|b|^3 可得...")
    assert pairs, "应提取到不等式"
    lhs, rhs, op = pairs[0]
    assert "a^2+3b^2" in lhs
    assert "Abs(" in rhs and "..." not in rhs
    assert op == "ge"


def test_extract_skips_plain_conditions():
    """题面条件（n >= 2 / k >= 1）不得被当作可复算不等式（防误杀）。"""
    assert _extract_inequalities("其中 n >= 2 且 k >= 1") == []
