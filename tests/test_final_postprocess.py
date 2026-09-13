"""P2（强制数值化）与 P5（客观题自检）单元测试 —— 2026-09-11。

覆盖：LaTeX 常数求值器（幂/阶乘/分式/根式/自由变量拒绝）、最终答案后处理
（数值化替换、纯数字与符号式保留）、客观题写法归一、以及总开关。
不依赖 LLM：orchestrator 以 __new__ 构造并打桩 record。
"""
import os
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _orch():
    from agent.orchestrator import Orchestrator
    o = Orchestrator.__new__(Orchestrator)
    o.record = lambda *a, **k: None      # 打桩：不写 ctx（本测试只验逻辑）
    return o


class _Ctx:
    def __init__(self, problem="", answer=""):
        self.problem = problem
        self.final_response = answer


# ---------------- P2: LaTeX 常数求值 ----------------
def test_latex_const_power():
    assert _orch()._latex_const_value("2023^2") == Fraction(4092529, 1)


def test_latex_const_factorial():
    assert _orch()._latex_const_value("3!") == Fraction(6, 1)


def test_latex_const_cdot_factorial():
    assert _orch()._latex_const_value("2^{10} \\cdot 3!") == Fraction(1024 * 6, 1)


def test_latex_const_frac():
    assert _orch()._latex_const_value("\\frac{6}{4}") == Fraction(3, 2)


def test_latex_const_sqrt():
    assert _orch()._latex_const_value("\\sqrt{16}") == Fraction(4, 1)


def test_latex_const_rejects_free_variable():
    """含自由变量必须拒绝（否则会把符号式当常数算）。"""
    assert _orch()._latex_const_value("x^2") is None


def test_latex_const_rejects_plain_number():
    """纯数字不属于"未求值表达式"，不处理。"""
    assert _orch()._latex_const_value("123") is None


# ---------------- P2: 数值化替换 ----------------
def test_numericize_replaces_unevaluated():
    out = _orch()._maybe_numericize(_Ctx(), "\\boxed{2023^2}")
    assert out == "\\boxed{4092529}"


def test_numericize_keeps_plain_number():
    assert _orch()._maybe_numericize(_Ctx(), "\\boxed{123}") == "\\boxed{123}"


def test_numericize_keeps_symbolic():
    assert _orch()._maybe_numericize(_Ctx(), "\\boxed{x^2}") == "\\boxed{x^2}"


# ---------------- P5: 客观题自检 ----------------
def test_objective_normalizes_judgement_symbols():
    o = _orch()
    assert o._objective_selfcheck(_Ctx(problem="判断：以下说法…"), "\\boxed{√}") == "\\boxed{正确}"
    assert o._objective_selfcheck(_Ctx(problem="判断：以下说法…"), "\\boxed{×}") == "\\boxed{错误}"


def test_objective_keeps_letter_answer():
    o = _orch()
    assert o._objective_selfcheck(_Ctx(problem="A. 甲 B. 乙"), "\\boxed{B}") == "\\boxed{B}"


# ---------------- 总开关 ----------------
def test_postprocess_switch_off(monkeypatch):
    o = _orch()
    monkeypatch.setenv("NUMERICIZE_FINAL", "0")
    monkeypatch.setenv("OBJECTIVE_SELFCHECK", "0")
    ctx = _Ctx(answer="\\boxed{2023^2}")
    assert o._final_answer_postprocess(ctx) == "\\boxed{2023^2}"


def test_postprocess_applies_both(monkeypatch):
    o = _orch()
    monkeypatch.setenv("NUMERICIZE_FINAL", "1")
    monkeypatch.setenv("OBJECTIVE_SELFCHECK", "1")
    ctx = _Ctx(problem="判断：…", answer="\\boxed{√}")
    assert o._final_answer_postprocess(ctx) == "\\boxed{正确}"
