"""Lightweight math helpers and tool hint builders."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from config import ENABLE_SYMPY
from tools.sympy_tools import (
    compute_limit,
    differentiate_expr,
    integrate_expr,
    simplify_expr,
    try_extract_simple_expr,
)


def build_tool_hints(problem: str, profile: Optional[dict] = None) -> Dict[str, Any]:
    """Build lightweight SymPy-related hints for the solver.

    Keep this conservative: never crash, never force-parse complex NL formulas.
    """
    try:
        if not ENABLE_SYMPY:
            return {"hint": "SymPy disabled."}

        if not isinstance(problem, str) or not problem.strip():
            return {}

        profile = profile or {}
        subject = str(profile.get("subject", "")).lower()
        problem_type = str(profile.get("problem_type", "")).lower()

        hints: Dict[str, Any] = {}
        simple_expr = try_extract_simple_expr(problem)

        is_analysis = subject in ("analysis", "calculus") or any(
            k in problem for k in ("极限", "积分", "导数", "微分", "limit", "integral")
        )

        if is_analysis or subject == "analysis":
            if any(k in problem for k in ("导数", "求导", "differentiate", "derivative", "d/dx")):
                hints["task"] = "differentiate"
                if simple_expr:
                    result = differentiate_expr(simple_expr)
                    if result is not None:
                        hints["expr"] = simple_expr
                        hints["sympy_result"] = result
                        hints["hint"] = f"对 {simple_expr} 求导，SymPy 参考结果：{result}"
                    else:
                        hints["hint"] = "可使用 SymPy 辅助求导验证。"
                else:
                    hints["hint"] = "可使用 SymPy 辅助求导验证。"

            elif any(k in problem for k in ("积分", "integrate", "integral", "∫")):
                hints["task"] = "integrate"
                if simple_expr:
                    result = integrate_expr(simple_expr)
                    if result is not None:
                        hints["expr"] = simple_expr
                        hints["sympy_result"] = result
                        hints["hint"] = f"对 {simple_expr} 积分，SymPy 参考结果：{result}"
                    else:
                        hints["hint"] = "可使用 SymPy 辅助积分验证。"
                else:
                    hints["hint"] = "可使用 SymPy 辅助积分验证。"

            elif any(k in problem for k in ("极限", "limit", "lim")):
                hints["task"] = "limit"
                if simple_expr:
                    result = compute_limit(simple_expr)
                    if result is not None:
                        hints["expr"] = simple_expr
                        hints["sympy_result"] = result
                        hints["hint"] = f"对 {simple_expr} 求极限，SymPy 参考结果：{result}"
                    else:
                        hints["hint"] = "可使用 SymPy 辅助求极限验证。"
                else:
                    hints["hint"] = "可使用 SymPy 辅助求极限验证。"

        if problem_type == "calculation" and "hint" not in hints:
            if simple_expr:
                simplified = simplify_expr(simple_expr)
                if simplified is not None:
                    hints["expr"] = simple_expr
                    hints["simplified"] = simplified
                    hints["hint"] = (
                        f"可使用 SymPy 辅助化简或验证表达式。"
                        f"参考化简：{simple_expr} -> {simplified}"
                    )
                else:
                    hints["hint"] = "可使用 SymPy 辅助化简或验证表达式。"
            else:
                hints["hint"] = "可使用 SymPy 辅助化简或验证表达式。"

        if not hints:
            return {"hint": "No reliable symbolic hint generated."}

        # Ensure JSON-serializable content for traces.
        json.dumps(hints, ensure_ascii=False)
        return hints
    except Exception:
        return {"hint": "No reliable symbolic hint generated."}


def tool_hints_to_text(tool_hints: Optional[dict]) -> str:
    """Render tool hints as short text for prompts/traces."""
    if not tool_hints:
        return ""
    try:
        if isinstance(tool_hints, dict) and "hint" in tool_hints and len(tool_hints) == 1:
            return str(tool_hints["hint"])
        return json.dumps(tool_hints, ensure_ascii=False)
    except Exception:
        return str(tool_hints)
