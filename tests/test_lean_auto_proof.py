# -*- coding: utf-8 -*-
"""P4 自动证明链：多策略 Lean 声明构建器单测（2026-09-09）。

_build_auto_proof 是纯生成器（不触发编译）；真实"任一策略闭合/全失败"语义
由 10 题评测实证（依赖 lean 环境），不进单测。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.sub_goal_solver import SubGoalSolverAgent  # noqa: E402


def _solver():
    return SubGoalSolverAgent.__new__(SubGoalSolverAgent)


def _build(fails):
    out = _solver()._build_auto_proof(fails)
    return out


def test_numeric_group_three_strats():
    code, groups = _build([("37*43 + 2024", "2025")])
    assert code and groups
    assert len(groups) == 1 and len(groups[0]) == 3   # norm_num/norm_num1/ring
    for ln in groups[0]:
        assert "example : (37*43 + 2024 : ℚ) = (2025 : ℚ) :=" in code[ln - 1]
        assert code[ln - 1].rstrip().endswith(
            ("by norm_num", "by norm_num1", "by ring"))


def test_poly_group_six_strats():
    code, groups = _build([("x^2 - 1", "(x - 1)*(x + 1)")])
    assert len(groups) == 1 and len(groups[0]) == 6   # ring 策略族
    strat_tail = ("by ring", "by ring_nf", "by nlinarith",
                  "by omega", "by grind", "by aesop")
    for ln in groups[0]:
        assert code[ln - 1].rstrip().endswith(strat_tail), code[ln - 1]
    # ℤ 绑定变量出现
    assert "example (x : ℤ) :" in code[groups[0][0] - 1]


def test_multiple_asserts_groups_monotonic():
    code, groups = _build([("1/2+1/3", "5/6"), ("a*b + b*a", "2*a*b")])
    assert len(groups) == 2
    assert max(groups[0]) < min(groups[1])
    # 行号唯一
    all_lines = [ln for v in groups.values() for ln in v]
    assert len(all_lines) == len(set(all_lines))


def test_skip_division_or_many_vars():
    # 含除号的变量式 / 超 3 变量 → Lean 无法背书，宁放行
    assert _build([("x / y", "z")]) is None
    assert _build([("a + b + c + d", "0")]) is None
    assert _build([("x / 2", "1/2")]) is None      # 变量分母含除号 → 跳过
