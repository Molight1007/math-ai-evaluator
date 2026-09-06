# -*- coding: utf-8 -*-
"""易错点记忆库（prompts/error_lessons.py）测试（2026-09-06 A 档）。

行为契约（防误伤，宁缺毋滥）：
1. 命中关键词/题型才注入，无命中返回空串 = 零噪音（绝不能每题都带清单）；
2. E-check（数值代回）只进解答题/计算题，不进纯证明题；
3. E-form（解族完整性）只命中"求函数/通解/Find all"类题干；
4. E-extreme（极值数值验证）只在题干含极值词时触发；
5. solver.error_lessons_block 在应急模式（emergency）下返回空。
"""

from __future__ import annotations

from agent.base import RunState, TaskContext
from agent.solver import error_lesson_ids, error_lessons_block
from prompts.error_lessons import lesson_ids, match_lessons


def _ctx(problem="x", domain="Algebra", qtype="解答题", emergency=False):
    ctx = TaskContext(problem=problem, metadata={}, domain=domain)
    ctx.question_type = qtype
    ctx.state = RunState()
    ctx.state.emergency = emergency
    return ctx


def test_function_family_hits_form():
    """求函数/Find all functions → E-form 命中（漏常数项教训）。"""
    block = match_lessons(domain="Algebra", question_type="解答题",
                          problem="Find all functions g:R->R which is not linear")
    assert "E-form" in lesson_ids(domain="Algebra", question_type="解答题",
                                  problem="Find all functions g:R->R")
    assert "漏" in block and "常数" in block


def test_answer_check_hits_for_computational():
    """解答题（组合计数）→ E-check 数值代回自检命中。"""
    ids = lesson_ids(domain="Combinatorics", question_type="解答题",
                     problem="A classroom contains 68 pairs...")
    assert "E-check" in ids


def test_proof_not_hit_by_answer_check():
    """纯证明题不触发 E-check（数值代回检查清单对证明题是噪音）。"""
    ids = lesson_ids(domain="Geometry", question_type="证明题",
                     problem="Prove that the angle bisector...")
    assert "E-check" not in ids


def test_extreme_hits_only_with_keyword():
    """极值清单只在题干含 max/min/最大 时触发。"""
    assert "E-extreme" in lesson_ids(
        domain="Algebra", question_type="解答题",
        problem="Find the maximum value of x^2+2x")
    assert "E-extreme" not in lesson_ids(
        domain="Algebra", question_type="解答题",
        problem="Solve the equation x^2+2x=3")


def test_no_hit_returns_empty():
    """完全不匹配 → 空串（零注入零噪音）。"""
    assert match_lessons(domain="History", question_type="填空",
                         problem="Which year?") == ""


def test_geometry_proof_only_no_hits():
    """几何纯证明且无关键词 → 至少不给数值类清单。"""
    ids = lesson_ids(domain="Geometry", question_type="证明题",
                     problem="Prove AB=CD using congruent triangles")
    assert "E-check" not in ids


def test_block_skipped_in_emergency():
    """应急模式 → solver.error_lessons_block 返回空。"""
    ctx = _ctx(emergency=True)
    assert error_lessons_block(ctx) == ""


def test_block_normal_injects():
    """正常模式 + 命中题 → block 非空且含清单标题。"""
    ctx = _ctx(problem="Find all functions g:R->R not linear", qtype="解答题")
    assert "历史易错自查清单" in error_lessons_block(ctx)
    assert error_lesson_ids(ctx)  # 非空
