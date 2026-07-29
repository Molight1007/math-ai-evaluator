"""Lightweight SymPy helpers with safe fallbacks."""

from __future__ import annotations

import re
from typing import List, Optional, Union

try:
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    _HAS_SYMPY = True
except Exception:  # pragma: no cover - import failure path
    sp = None  # type: ignore
    parse_expr = None  # type: ignore
    _HAS_SYMPY = False

_TRANSFORMATIONS = None
if _HAS_SYMPY:
    _TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)


def safe_sympify(expr: str):
    """Safely parse an expression string into a SymPy object, or None."""
    if not _HAS_SYMPY or not isinstance(expr, str):
        return None
    text = expr.strip()
    if not text:
        return None
    # Reject obviously unsafe / non-math content.
    if any(tok in text for tok in ("__", "import", "exec", "eval", "os.", "sys.")):
        return None
    try:
        return parse_expr(
            text,
            transformations=_TRANSFORMATIONS,
            evaluate=True,
        )
    except Exception:
        try:
            return sp.sympify(text)
        except Exception:
            return None


def _to_str(obj) -> Optional[str]:
    if obj is None:
        return None
    try:
        return str(obj)
    except Exception:
        return None


def simplify_expr(expr: str) -> Optional[str]:
    """Simplify an expression string. Returns None on failure."""
    try:
        parsed = safe_sympify(expr)
        if parsed is None:
            return None
        return _to_str(sp.simplify(parsed))
    except Exception:
        return None


def expand_expr(expr: str) -> Optional[str]:
    """Expand an expression string. Returns None on failure."""
    try:
        parsed = safe_sympify(expr)
        if parsed is None:
            return None
        return _to_str(sp.expand(parsed))
    except Exception:
        return None


def factor_expr(expr: str) -> Optional[str]:
    """Factor an expression string. Returns None on failure."""
    try:
        parsed = safe_sympify(expr)
        if parsed is None:
            return None
        return _to_str(sp.factor(parsed))
    except Exception:
        return None


def compare_expr(expr1: str, expr2: str) -> Optional[bool]:
    """Return True if expr1 and expr2 are symbolically equivalent."""
    try:
        a = safe_sympify(expr1)
        b = safe_sympify(expr2)
        if a is None or b is None:
            return None
        diff = sp.simplify(a - b)
        return bool(diff == 0)
    except Exception:
        return None


def _split_equation(equation: str) -> Optional[str]:
    """Convert 'lhs = rhs' into 'lhs - (rhs)', else return original."""
    if not isinstance(equation, str):
        return None
    text = equation.strip()
    if not text:
        return None
    if "=" in text:
        parts = text.split("=")
        if len(parts) != 2:
            return None
        left, right = parts[0].strip(), parts[1].strip()
        if not left:
            return None
        if not right:
            right = "0"
        return f"({left})-({right})"
    return text


def solve_equation(
    equation: str, variable: str = "x"
) -> Optional[List[str]]:
    """Solve a simple univariate equation. Returns list of solution strings."""
    try:
        expr_text = _split_equation(equation)
        if expr_text is None:
            return None
        parsed = safe_sympify(expr_text)
        if parsed is None:
            return None
        var = sp.Symbol(variable)
        solutions = sp.solve(parsed, var)
        if solutions is None:
            return None
        if not isinstance(solutions, (list, tuple)):
            solutions = [solutions]
        result = []
        for sol in solutions:
            s = _to_str(sol)
            if s is not None:
                result.append(s)
        return result
    except Exception:
        return None


def compute_limit(
    expr: str, variable: str = "x", point: Union[int, float, str] = 0
) -> Optional[str]:
    """Compute a simple limit. Returns None on failure."""
    try:
        parsed = safe_sympify(expr)
        if parsed is None:
            return None
        var = sp.Symbol(variable)
        if isinstance(point, str):
            pt = safe_sympify(point)
            if pt is None:
                return None
        else:
            pt = point
        result = sp.limit(parsed, var, pt)
        return _to_str(result)
    except Exception:
        return None


def differentiate_expr(expr: str, variable: str = "x") -> Optional[str]:
    """Differentiate an expression. Returns None on failure."""
    try:
        parsed = safe_sympify(expr)
        if parsed is None:
            return None
        var = sp.Symbol(variable)
        return _to_str(sp.diff(parsed, var))
    except Exception:
        return None


def integrate_expr(expr: str, variable: str = "x") -> Optional[str]:
    """Compute an indefinite integral. Returns None on failure."""
    try:
        parsed = safe_sympify(expr)
        if parsed is None:
            return None
        var = sp.Symbol(variable)
        return _to_str(sp.integrate(parsed, var))
    except Exception:
        return None


# Optional simple-expression sniffing helpers live in try_extract_simple_expr.


def try_extract_simple_expr(text: str) -> Optional[str]:
    """Best-effort extraction of a simple math expression from text."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        # Prefer $...$ LaTeX-ish snippets without backslash commands.
        dollar = re.findall(r"\$([^$]+)\$", text)
        for cand in dollar:
            cand = cand.strip()
            if cand and "\\" not in cand and safe_sympify(cand) is not None:
                return cand
        # Fallback: look for a short ascii expression with operators.
        for match in re.finditer(
            r"[0-9a-zA-Z_][0-9a-zA-Z_+\-*/^().\s]{0,40}[0-9a-zA-Z_)]",
            text,
        ):
            cand = match.group(0).strip()
            if any(op in cand for op in "+-*/^") and safe_sympify(cand) is not None:
                return cand
        return None
    except Exception:
        return None
