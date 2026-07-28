"""Utility tools for answer extraction, normalization, and math helpers."""

from tools.math_utils import build_tool_hints, tool_hints_to_text
from tools.sympy_tools import (
    compare_expr,
    compute_limit,
    differentiate_expr,
    expand_expr,
    factor_expr,
    integrate_expr,
    safe_sympify,
    simplify_expr,
    solve_equation,
)
from tools.voting import (
    are_answers_equivalent,
    group_equivalent_answers,
    majority_vote,
    normalize_for_vote,
    score_candidate,
    select_best_candidate,
)

__all__ = [
    "build_tool_hints",
    "tool_hints_to_text",
    "safe_sympify",
    "simplify_expr",
    "expand_expr",
    "factor_expr",
    "compare_expr",
    "solve_equation",
    "compute_limit",
    "differentiate_expr",
    "integrate_expr",
    "normalize_for_vote",
    "are_answers_equivalent",
    "group_equivalent_answers",
    "majority_vote",
    "score_candidate",
    "select_best_candidate",
]
