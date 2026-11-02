# -*- coding: utf-8 -*-
"""断言判定的零判定 —— 复现并锁住「算式断言一律被判不成立」的真实缺陷。

背景（2026-11-02，服务器 109 题次实测）
----------------------------------------
把下游注入改成「只允许已闭合结论进入」时，93% 的阻断来自「上游被判错」。
逐条复核那 26 条判词，发现判词**自己写着「左式实际值应为 1810」，却判 fail**：

    「18*100 + 10 = 1810」客观判定不成立（左式实际值应为 1810）
    「946 - 100 = 846」  客观判定不成立（左式实际值应为 846）
    「2^2 - 2^1 = 2」    客观判定不成立（左式实际值应为 2）

根因不是数学，是判据实现：解析层用 `sympify(..., evaluate=False)`，数字和保留成
**未求值的 Add**，而判定用 `d == 0` 做**结构比较**：

    expand(10 + 18*100 - 1810)  ->  -1800 + 1800
    (-1800 + 1800) == 0          ->  False     # 结构不等
    (-1800 + 1800).is_zero       ->  True      # 正确问法

于是「左式写成乘积/幂」的断言**全被误判**，且判词与判决自相矛盾。
"""
import pytest

import agent.sub_goal_solver__lean as M
from agent.sub_goal_solver__contract import _pow_to_python


class _Shim(object):
    """只装配 `_sympy_judge` 需要的方法，避免拉起整个求解器。"""

    def __init__(self):
        self._pow_to_python = _pow_to_python

    _sympy_judge = M._sympy_judge


def _judge(L, R):
    return M._sympy_judge(_Shim(), L, R)


# ---------------------------------------------------------------- Z1 零判定
@pytest.mark.parametrize("expr,expect", [
    (0, True),
    (-1800 + 1800, True),          # ★ 未求值 Add：结构不等但数学为零
    (5 * 2 + 5 * 3 - 25, True),
    (1, False),
    (-100 + 100 - 1, False),
])
def test_zero_state(expr, expect):
    assert M._zero_state(expr) is expect


# --------------------------------------------------- Z2 真实误判案例必须判通过
@pytest.mark.parametrize("L,R", [
    ("18*100 + 10", "1810"),
    ("2^2 - 2^1", "2"),
    ("946 - 100", "846"),
    ("5*2+5*3", "25"),
    ("1*5 + 1*2 + 2*1 + 5*1", "14"),
    ("8*2 + 2*3", "22"),
    ("51 * 35 + 40", "1825"),
    ("180 + 9 - 1", "188"),
    ("1*1^3 + 1*1^3 + 1*1^3", "3"),
])
def test_arithmetic_assert_no_longer_rejected(L, R):
    v, _ = _judge(L, R)
    assert v == "pass", "算对的算式断言不该被判不成立：%s = %s -> %s" % (L, R, v)


# ------------------------------------------------------- Z3 真错必须仍判 fail
@pytest.mark.parametrize("L,R", [
    ("18*100 + 10", "1811"),
    ("946 - 100", "845"),
    ("2^2 - 2^1", "3"),
])
def test_wrong_arithmetic_still_fails(L, R):
    v, info = _judge(L, R)
    assert v == "fail"
    assert "实际值" in info


# --------------------------------------------- Z4 符号断言：恒等通过/不恒等失败
@pytest.mark.parametrize("L,R", [
    ("(n-1)+n", "2*n-1"),
    ("x + x", "2*x"),
])
def test_symbolic_identity_passes(L, R):
    assert _judge(L, R)[0] == "pass"


def test_symbolic_non_identity_is_not_fatal():
    """★ 2026-11-02 口径修正：差含符号时判不出，**不得判死**。

    推导里写的是「该配置下的等式」，不是恒等断言。判据没有符号表，
    无法区分「自由变量」与「前面已定义的常量」（实测典型：`T_max = 76`、
    `-4*a + Δ - 5`、`x²+y²+z² = 3` 是题设条件），硬判必大面积误杀。
    """
    for L, R in [("a * a", "1"), ("x_k^2", "y_k"), ("T_max", "76"),
                 ("-4*a + Delta", "5")]:
        assert _judge(L, R)[0] in ("unknown", "pass"), "%s = %s" % (L, R)


def test_pure_numeric_mismatch_still_fatal():
    """两侧都是封闭数值时，差是非零常数 —— 这是唯一有资格判 fail 的情形。"""
    assert _judge("3 + 4", "8")[0] == "fail"


# --------------------------------------------------- Z6 单个符号识别（含下标/希腊）
@pytest.mark.parametrize("s,expect", [
    ("x", True),
    ("T_max", True),
    ("x_k", True),
    ("Δ", True),
    ("a * a", False),
    ("x^2", False),
    ("sin(x)", False),
    ("", False),
    ("2", False),
])
def test_is_single_symbol(s, expect):
    assert M._is_single_symbol(s) is expect


# ------------------------------------------------- Z5 赋值式仍放行（原有红线）
def test_assignment_still_unknown():
    """x = 5 是求解结果，不是恒等断言 —— 不得判 fail。"""
    assert _judge("x", "5")[0] == "unknown"
