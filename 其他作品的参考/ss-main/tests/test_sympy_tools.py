"""Tests for SymPy tool helpers."""

from __future__ import annotations

from tools.math_utils import build_tool_hints
from tools.sympy_tools import (
    compare_expr,
    expand_expr,
    factor_expr,
    safe_sympify,
    simplify_expr,
    solve_equation,
)
from user_agent import ReasoningAgent


def test_simplify_expr_x_plus_x():
    result = simplify_expr("x + x")
    assert result is not None
    assert "2" in result and "x" in result.replace(" ", "")


def test_expand_expr():
    result = expand_expr("(x+1)**2")
    assert result is not None
    assert "x" in result


def test_factor_expr():
    result = factor_expr("x**2 - 1")
    assert result is not None
    assert "x" in result


def test_compare_expr_equivalent():
    assert compare_expr("x+x", "2*x") is True


def test_solve_equation_quadratic():
    solutions = solve_equation("x**2 - 1 = 0")
    assert solutions is not None
    normalized = {s.replace(" ", "") for s in solutions}
    assert "-1" in normalized or "(-1)" in normalized
    assert "1" in normalized


def test_illegal_expression_returns_none():
    assert safe_sympify("@@@not_an_expr@@@") is None
    assert simplify_expr("@@@not_an_expr@@@") is None
    assert expand_expr("@@@not_an_expr@@@") is None
    assert factor_expr("@@@not_an_expr@@@") is None
    assert compare_expr("@@@", "x") is None
    assert solve_equation("@@@ = 0") is None


def test_main_flow_with_tool_hints_does_not_crash():
    class FakeClient:
        def chat(self, messages, temperature=0.2, max_tokens=4096):
            content = messages[0]["content"] if messages else ""
            if "分类" in content or "JSON" in content:
                return (
                    '{"subject":"analysis","problem_type":"calculation",'
                    '"answer_form":"expression","needs_proof":false,'
                    '"needs_tool":true,"difficulty":"easy","confidence":0.9}'
                )
            if "计划" in content or "解题计划" in content:
                return "1. 理解题意\n2. 计算\n3. 验证"
            if "正确性" in content or "验证" in content:
                return "正确性：正确\n问题：无\n修正答案：2\n置信度：0.9"
            return "分析略。\n最终答案：2"

    agent = ReasoningAgent(client=FakeClient())
    result = agent.solve("计算 1+1。", {"idx": 0})
    assert isinstance(result, dict)
    assert result["final_response"].strip()
    steps = [t["step"] for t in result.get("trace", [])]
    assert "tool_hints" in steps


def test_build_tool_hints_safe():
    hints = build_tool_hints(
        "求导数：对 x**2 求导",
        {"subject": "analysis", "problem_type": "calculation"},
    )
    assert isinstance(hints, dict)
    assert "hint" in hints
