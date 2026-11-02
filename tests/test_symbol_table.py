# -*- coding: utf-8 -*-
"""符号表 —— 把「差含符号就判不出」换成「能代入就代入后判」。

★ 与 `tests/test_zero_judge.py` 的区别（后者被自我否决过）：那份用例是
  从被修的那批判词原文抄的，测试集=训练集，绿了也证明不了什么。这里刻意用
  **与被修数据无关的通用表达式**，并且**同时锁住两个方向**：
  代入后该通过的要通过、该判错的要判错。只锁一个方向的就是在给自己放水。
"""
import pytest

import agent.sub_goal_solver__lean as M
from agent.sub_goal_solver__contract import _pow_to_python
from utils import symbol_table as ST


class _Shim(object):
    def __init__(self):
        self._pow_to_python = _pow_to_python

    _sympy_judge = M._sympy_judge


def _judge(L, R, tab=None):
    return M._sympy_judge(_Shim(), L, R, symtab=tab)


# ---------------------------------------------------------------- S1 抽取定义
@pytest.mark.parametrize("text,expect", [
    ("等式 = T_max = 76", {"T_max": "76"}),
    ("由 Δ = -4*a + 5 得", {"Δ": "-4*a + 5"}),
    ("设 v = 3 且 t = 4", {"v": "3", "t": "4"}),
])
def test_collect_bindings_hits(text, expect):
    got = ST.collect_bindings(text)
    for k, v in expect.items():
        assert got.get(k) == v, "应抽出 %s=%s，实际 %r" % (k, v, got)


@pytest.mark.parametrize("text", [
    "本步结论: 判定 = 真",          # 散文判定，不是数值定义
    "f(x) = x^2 + 1",               # 函数定义，无法安全代入
    "当且仅当 a = b 时成立",         # 右值不是数学式
    "答案是 42",
])
def test_collect_bindings_does_not_overcollect(text):
    assert ST.collect_bindings(text) == {}, "不该误收：%r" % text


def test_merge_bindings_keeps_first_definition():
    tab = {"a": "1"}
    ST.merge_bindings(tab, {"a": "2", "b": "3"})
    assert tab == {"a": "1", "b": "3"}, "先出现的定义优先，不能被覆盖"


# ---------------------------------------------------------------- S2 代入
def test_substitute_chained():
    import sympy as sp
    x = sp.Symbol("x")
    got, unres, used = ST.substitute(x + 1, {"x": "y + 1", "y": "2"})
    assert got == 4 and not unres, (got, unres, used)


def test_substitute_cycle_terminates():
    import sympy as sp
    x = sp.Symbol("x")
    got, unres, _ = ST.substitute(x, {"x": "x + 1"})
    assert "x" in unres, "自指定义必须留作未解析，不能无限展开"


def test_substitute_unknown_left_over():
    import sympy as sp
    x, y = sp.Symbol("x"), sp.Symbol("y")
    got, unres, _ = ST.substitute(x + y, {"x": "2"})
    assert unres == {"y"}, unres


# ------------------------------------------------- S3 带符号表的判定（双向）
@pytest.mark.parametrize("L,R,tab", [
    ("T_max * 2", "152", {"T_max": "76"}),      # 代入后成立
    ("(T_max - 76) * 0 + 5", "5", {"T_max": "76"}),
    ("2 * (a + 1)", "2*a + 2", {"a": "3"}),      # 代入后仍带符号但恒等
])
def test_judge_passes_with_symbol_table(L, R, tab):
    v, _ = _judge(L, R, tab)
    assert v == "pass", "代入已定义符号后成立，不该判不出：%s = %s -> %s" % (L, R, v)


@pytest.mark.parametrize("L,R,tab", [
    ("T_max * 2", "153", {"T_max": "76"}),       # 代入后是真错
    ("T_max - 76", "1", {"T_max": "76"}),
    ("v * t", "13", {"v": "3", "t": "4"}),
])
def test_judge_fails_wrong_after_substitution(L, R, tab):
    v, info = _judge(L, R, tab)
    assert v == "fail", "代入后能确定算错，必须判 fail（不能因有符号就放行）：%s = %s -> %s" % (
        L, R, v)
    assert "实际值" in info or "相差" in info


@pytest.mark.parametrize("L,R,tab", [
    ("x * y", "6", {"x": "2"}),                  # y 未定义
    ("T_max * 2", "152", None),                  # 根本没给表
    ("T_max * 2", "152", {}),                    # 空表
])
def test_judge_unknown_when_undefined(L, R, tab):
    v, info = _judge(L, R, tab)
    assert v == "unknown", "缺定义必须判 unknown（显式失败），不能猜：%s -> %s" % (L, v)
    if tab:
        assert "未定义" in info or "无定义" in info, "原因要写明缺哪个符号：%r" % info
