# -*- coding: utf-8 -*-
"""符号化方程求解通道单测（2026-09-12）。

四段链路全覆盖：
  ① 数值剥离（strip_given_numbers）  ② 协议解析（parse_symbolic_solve）
  ③ 三层硬校验（validate_payload）   ④ 工具求解（solve_with_tool）
外加：端到端（剥离 → 建模 → 校验 → 求解 → 已知答案）与开关 noop。
"""
import pytest

from agent.symbolic_solve import (
    strip_given_numbers, parse_symbolic_solve, validate_payload,
    solve_with_tool,
)


# ==========================================================================
# ① 数值剥离器
# ==========================================================================
def test_strip_assign_form():
    r = strip_given_numbers("设 n = 100，求 n^2 + 2n 的值")
    assert r is not None
    assert r.params == {"P1": "100"}
    assert "P1" in r.problem and "100" not in r.problem
    assert "^2" in r.problem            # 结构性常数（指数）必须保留


def test_strip_quantity_form():
    r = strip_given_numbers("某商品单价 60 元，买了 3 个，求总价")
    assert r is not None
    assert sorted(r.params.values()) == ["3", "60"]


def test_strip_copula_form():
    r = strip_given_numbers("等差数列首项为 3，公差是 4，求第 10 项")
    assert r is not None
    assert sorted(r.params.values()) == ["3", "4"]
    assert "10" in r.problem             # 序数「第 10 项」不属于给定数据


def test_strip_keeps_structural_constants():
    # 底数是数据 → 剥离；指数是结构 → 保留
    r = strip_given_numbers("求 2023^2 的值")
    assert r is not None
    assert r.params == {"P1": "2023"}
    assert "^2" in r.problem and "2023" not in r.problem
    # 纯结构常数（分数）→ 无可剥离数据
    assert strip_given_numbers("求 1/2 + 1/3 的值") is None


def test_strip_bare_assign_and_big_number():
    r = strip_given_numbers("设 n=2024，求 n 的各位数字之和")
    assert r is not None
    assert "2024" not in r.problem and "P1" in r.problem


def test_strip_too_many_params():
    text = "有 " + "，".join(f"{i} 个" for i in range(1, 15))
    assert strip_given_numbers(text) is None


def test_strip_empty_and_none():
    assert strip_given_numbers("") is None
    assert strip_given_numbers(None) is None
    assert strip_given_numbers("   ") is None


# ==========================================================================
# ② 协议解析
# ==========================================================================
def test_parse_compact_block():
    text = "EQUATIONS:\n2*P1+3*P2=P3\nP1-P2=P4\n\nTARGET: P1+P2"
    p = parse_symbolic_solve(text)
    assert len(p["equations"]) == 2
    assert p["target"] == "P1+P2"
    assert p["unsupported"] is False


def test_parse_json_form():
    p = parse_symbolic_solve('{"equations": ["2*x=10"], "target": "x"}')
    assert p["equations"] == ["2*x=10"]
    assert p["target"] == "x"


def test_parse_semicolon_separated():
    p = parse_symbolic_solve("EQUATIONS: a+b=P1; a-b=P2\nTARGET: a")
    assert len(p["equations"]) == 2
    assert p["target"] == "a"


def test_parse_unsupported():
    p = parse_symbolic_solve("UNSUPPORTED")
    assert p["unsupported"] is True
    ok, why = validate_payload(p, {})
    assert not ok and "UNSUPPORTED" in why


def test_parse_markdown_fence():
    p = parse_symbolic_solve("```\nEQUATIONS:\n2*x=10\nTARGET: x\n```")
    assert p["target"] == "x"


def test_parse_empty_returns_none():
    assert parse_symbolic_solve("") is None
    assert parse_symbolic_solve(None) is None
    assert parse_symbolic_solve("我无法建模") is None


# ==========================================================================
# ③ 三层硬校验
# ==========================================================================
def test_validate_ok():
    p = {"equations": ["2*P1+3*P2=P3", "P1-P2=P4"], "target": "P1+P2"}
    ok, why = validate_payload(
        p, {"P1": "23", "P2": "18", "P3": "100", "P4": "5"})
    assert ok, why


def test_validate_rejects_two_equals():
    ok, why = validate_payload({"equations": ["x=1=2"], "target": "x"}, {})
    assert not ok and "等号" in why


def test_validate_rejects_bare_number_target():
    ok, why = validate_payload(
        {"equations": ["x=P1"], "target": "42"}, {"P1": "1"})
    assert not ok and "裸数值" in why


def test_validate_rejects_ungiven_literal():
    ok, why = validate_payload(
        {"equations": ["x=P1+100"], "target": "x"}, {"P1": "5"})
    assert not ok and "100" in why


def test_validate_allows_given_literal():
    ok, why = validate_payload(
        {"equations": ["x=P1"], "target": "x"}, {"P1": "100"})
    assert ok, why


def test_validate_rejects_non_math_chars():
    ok, why = validate_payload({"equations": ["x=P1{"], "target": "x"}, {})
    assert not ok


def test_validate_rejects_both_constants():
    ok, why = validate_payload({"equations": ["3=4"], "target": "x"}, {})
    assert not ok


def test_validate_rejects_empty_payload():
    ok, why = validate_payload(None, {})
    assert not ok
    ok, why = validate_payload({"equations": [], "target": ""}, {})
    assert not ok


# ==========================================================================
# ④ 工具求解（SymPy）
# ==========================================================================
def test_solve_single_equation():
    v, d = solve_with_tool({"equations": ["2*x=10"], "target": "x"}, {})
    assert v == "5"


def test_solve_fraction_result():
    v, d = solve_with_tool({"equations": ["3*x=1"], "target": "x"}, {})
    assert v == "1/3"


def test_solve_system_with_params():
    p = {"equations": ["a+b=P1", "a-b=P2"], "target": "a"}
    v, d = solve_with_tool(p, {"P1": "100", "P2": "4"})
    assert v == "52"


def test_solve_multi_solution_unique_target():
    v, d = solve_with_tool({"equations": ["x**2=16"], "target": "x**2"}, {})
    assert v == "16"


def test_solve_multi_solution_rejected():
    v, d = solve_with_tool({"equations": ["x**2=16"], "target": "x"}, {})
    assert v is None and "多解" in d


def test_solve_no_solution():
    v, d = solve_with_tool({"equations": ["x=1", "x=2"], "target": "x"}, {})
    assert v is None


def test_solve_free_symbol_rejected():
    v, d = solve_with_tool({"equations": ["x=y+1"], "target": "x"}, {})
    assert v is None


def test_solve_timeout_guard_does_not_hang():
    # 病态输入不应卡死（daemon 线程 + 5s 超时护栏）
    v, d = solve_with_tool({"equations": ["x**2**3**2=1"], "target": "x"}, {})
    assert v is None or isinstance(v, str)


# ==========================================================================
# 端到端：剥离 → 建模 → 校验 → 求解（全部已知答案）
# ==========================================================================
@pytest.mark.parametrize("problem,equations,target,expect", [
    ("设 n = 100，求 n^2 + 2n 的值",
     ["result=n**2+2*n", "n=P1"], "result", "10200"),
    ("某商品单价 60 元，买了 3 个，求总价",
     ["t=P1*P2"], "t", "180"),
    ("等差数列首项为 3，公差是 4，求第 10 项",
     ["a=P1+(10-1)*P2"], "a", "39"),
    ("长方形长为 8 米、宽为 5 米，求面积",
     ["s=P1*P2"], "s", "40"),
    ("甲乙两数之和为 100，之差为 4，求甲数",
     ["a+b=P1", "a-b=P2"], "a", "52"),
])
def test_end_to_end_known_answers(problem, equations, target, expect):
    strip = strip_given_numbers(problem)
    assert strip is not None, f"剥离失败：{problem}"
    payload = {"equations": equations, "target": target}
    ok, why = validate_payload(payload, strip.params)
    assert ok, f"校验未通过：{why}"
    value, detail = solve_with_tool(payload, strip.params)
    assert value == expect, f"{problem} → {value}（应为 {expect}）；{detail}"


# ==========================================================================
# 开关 noop（默认关必须零影响）
# ==========================================================================
class _Cfg:
    symbolic_solve_enabled = False


class _Ctx:
    problem = "设 n = 100，求 n^2+2n 的值"

    def gen_time_up(self):
        return False


class _Stub:
    config = _Cfg()

    def record(self, *args, **kwargs):
        pass


def test_switch_off_is_noop():
    from agent.solver import SolverAgent
    out = SolverAgent._maybe_symbolic_solve(_Stub(), _Ctx(), "原解答", "10200")
    assert out == ("原解答", "10200")
