from __future__ import annotations

import math
import re
from fractions import Fraction

import sympy as sp  # type: ignore[import-untyped]

from math_agent.tools.answer_normalizer import normalize_answer
from math_agent.tools.safe_math import safe_parse_math_expr


_MAX_SEMANTIC_ANSWER_CHARS = 512
_UNORDERED_SEQUENCE_TYPES = {
    "absolute_value",
    "characteristic_equation",
    "complex_root",
    "eigenvalue",
    "logistic_ode",
    "polynomial",
    "quadratic_equation",
    "root_multiplicity",
}
_ORDERED_SEQUENCE_TYPES = {
    "cross_product",
    "gradient",
    "line_intersection",
    "linear_combination",
    "parabola_vertex",
    "projection",
    "section_formula",
    "tangent_plane",
    "transformation",
}
_ASSIGNMENT_SEQUENCE_TYPES = {
    "linear_system",
    "nonlinear_system",
}
_MATRIX_TYPES = {
    "matrix_addition",
    "matrix_inverse",
    "matrix_multiplication",
}
_RELATION_TYPES = {
    "circle_equation",
    "conic_section",
    "line_equation",
    "tangent_plane",
}
_ODE_TYPES = {
    "characteristic_equation",
    "euler_cauchy_ode",
    "exponential_decay",
    "linear_ode",
    "logistic_ode",
    "ode",
    "second_order_ode",
    "separable_ode",
    "wronskian",
}


def exact_match(pred: str, gold: str) -> bool:
    return (pred or "") == (gold or "")


def normalized_match(pred: str, gold: str) -> bool:
    return (
        normalize_answer(pred or "").casefold()
        == normalize_answer(gold or "").casefold()
    )


def numeric_match(pred: str, gold: str, tol: float = 1e-9) -> bool:
    p = normalize_answer(pred or "")
    g = normalize_answer(gold or "")
    if len(p) > 512 or len(g) > 512:
        return False

    def _to_float(value: str) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            try:
                return float(Fraction(value))
            except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                return None

    pf = _to_float(p)
    gf = _to_float(g)
    if pf is None or gf is None:
        return False
    return math.isclose(pf, gf, rel_tol=tol, abs_tol=tol)


def symbolic_match(pred: str, gold: str) -> bool:
    p = normalize_answer(pred or "")
    g = normalize_answer(gold or "")
    try:
        pexpr = safe_parse_math_expr(p, local_dict={"e": sp.E, "E": sp.E})
        gexpr = safe_parse_math_expr(g, local_dict={"e": sp.E, "E": sp.E})
    except Exception:
        return False
    try:
        return bool(sp.simplify(pexpr - gexpr) == 0)
    except Exception:
        return False


def _semantic_math_text(
    value: str,
    *,
    ode_variables: bool = False,
    complex_numbers: bool = False,
    strip_assignment: bool = True,
) -> str:
    text = normalize_answer(value or "")
    text = re.sub(r"\bmathbb\{([CNRQZ])\}", r"\1", text)
    text = re.sub(
        r"\b(\d{1,2})!(?=$|[^A-Za-z0-9_])",
        r"factorial(\1)",
        text,
    )
    text = re.sub(r"\bpii\b", "pi*i", text)
    text = re.sub(r"\be\*\*\{([^{}]+)\}", r"exp(\1)", text)
    text = re.sub(r"\be\*\*\(([^()]*)\)", r"exp(\1)", text)
    text = re.sub(r"\*\*\{([-+]?\d+)\}", r"**\1", text)
    text = re.sub(r"\bln\s*(\d+(?:\.\d+)?)\b", r"ln(\1)", text)
    text = text.replace("^", "**")
    if strip_assignment and "=" in text:
        lhs, rhs = text.split("=", 1)
        if re.fullmatch(r"[A-Za-z](?:\([A-Za-z]\))?", lhs):
            text = rhs
    if ode_variables:
        text = re.sub(r"\b(sin|cos|tan)([tx])\b", r"\1(\2)", text)
        text = re.sub(r"\bt\b", "x", text)
    if complex_numbers:
        text = re.sub(r"\bi\b", "I", text)
    return text


def _scalar_semantic_match(
    pred: str,
    gold: str,
    *,
    complex_numbers: bool = False,
) -> bool:
    if normalized_match(pred, gold) or numeric_match(pred, gold):
        return True
    p = _semantic_math_text(pred, complex_numbers=complex_numbers)
    g = _semantic_math_text(gold, complex_numbers=complex_numbers)
    try:
        pexpr = safe_parse_math_expr(p, local_dict={"e": sp.E, "E": sp.E})
        gexpr = safe_parse_math_expr(g, local_dict={"e": sp.E, "E": sp.E})
        difference = pexpr - gexpr
        if difference == 0:
            return True
        if not difference.free_symbols:
            numeric_difference = complex(sp.N(difference, 30))
            return math.isclose(
                numeric_difference.real,
                0.0,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ) and math.isclose(
                numeric_difference.imag,
                0.0,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        if sp.count_ops(difference) > 64:
            return False
        return bool(sp.expand(difference) == 0)
    except Exception:
        return False


def _flat_sequence(value: str) -> list[str]:
    text = normalize_answer(value or "").strip()
    if len(text) >= 2 and text[0] in "[({" and text[-1] in "])}":
        text = text[1:-1].strip()
    if not text or any(token in text for token in ("[[", "]]", ";")):
        return []
    parts = [part.strip() for part in text.split(",")]
    if len(parts) < 2 or not all(parts):
        return []
    return parts


def _sequence_match(
    pred: str,
    gold: str,
    *,
    ordered: bool,
    complex_numbers: bool = False,
) -> bool:
    pred_items = _flat_sequence(pred)
    gold_items = _flat_sequence(gold)
    if not pred_items or len(pred_items) != len(gold_items):
        return False

    if ordered:
        return all(
            _scalar_semantic_match(
                pred_item,
                gold_item,
                complex_numbers=complex_numbers,
            )
            for pred_item, gold_item in zip(pred_items, gold_items)
        )

    unmatched = list(gold_items)
    for pred_item in pred_items:
        for index, gold_item in enumerate(unmatched):
            if _scalar_semantic_match(
                pred_item,
                gold_item,
                complex_numbers=complex_numbers,
            ):
                unmatched.pop(index)
                break
        else:
            return False
    return not unmatched


def _assignment_sequence(value: str) -> dict[str, str] | None:
    items = _flat_sequence(value)
    if not items:
        return None
    assignments: dict[str, str] = {}
    for item in items:
        if item.count("=") != 1:
            return None
        name, scalar = item.split("=", 1)
        name = name.strip().casefold()
        if not re.fullmatch(r"[a-z]", name) or name in assignments:
            return None
        assignments[name] = scalar.strip()
    return assignments


def _assignment_sequence_match(pred: str, gold: str) -> bool:
    pred_assignments = _assignment_sequence(pred)
    gold_assignments = _assignment_sequence(gold)
    if (
        pred_assignments is None
        or gold_assignments is None
        or pred_assignments.keys() != gold_assignments.keys()
    ):
        return False
    return all(
        _scalar_semantic_match(pred_assignments[name], gold_assignments[name])
        for name in pred_assignments
    )


def _nested_sequence(value: str) -> list[list[str]] | None:
    text = normalize_answer(value or "").strip()
    row_pattern = re.compile(r"[\[(]([^\[\]()]+)[\])]")
    matches = list(row_pattern.finditer(text))
    if not matches:
        return None
    remainder = row_pattern.sub("", text)
    if remainder.strip("[],()"):
        return None
    rows = [[item.strip() for item in match.group(1).split(",")] for match in matches]
    if not rows or any(not row or not all(row) for row in rows):
        return None
    width = len(rows[0])
    return rows if width and all(len(row) == width for row in rows) else None


def _matrix_match(pred: str, gold: str) -> bool:
    pred_rows = _nested_sequence(pred)
    gold_rows = _nested_sequence(gold)
    if pred_rows is None or gold_rows is None:
        return False
    if len(pred_rows) != len(gold_rows):
        return False
    return all(
        len(pred_row) == len(gold_row)
        and all(
            _scalar_semantic_match(pred_item, gold_item)
            for pred_item, gold_item in zip(pred_row, gold_row)
        )
        for pred_row, gold_row in zip(pred_rows, gold_rows)
    )


def _relation_residual(value: str, *, complex_numbers: bool = False):
    text = _semantic_math_text(
        value,
        complex_numbers=complex_numbers,
        strip_assignment=False,
    )
    if text.count("=") != 1:
        return None
    lhs, rhs = text.split("=", 1)
    try:
        return sp.expand(safe_parse_math_expr(lhs) - safe_parse_math_expr(rhs))
    except Exception:
        return None


def _relation_match(pred: str, gold: str, *, complex_numbers: bool = False) -> bool:
    pred_residual = _relation_residual(pred, complex_numbers=complex_numbers)
    gold_residual = _relation_residual(gold, complex_numbers=complex_numbers)
    if pred_residual is None or gold_residual is None:
        return False
    try:
        if sp.count_ops(pred_residual) + sp.count_ops(gold_residual) > 64:
            return False
        return bool(
            sp.expand(pred_residual - gold_residual) == 0
            or sp.expand(pred_residual + gold_residual) == 0
        )
    except Exception:
        return False


def _euler_cauchy_basis(value: str) -> tuple[int, ...] | None:
    text = _semantic_math_text(value, ode_variables=True).replace("_", "")
    term_pattern = re.compile(r"[+-]?[A-C](?:\d+)?\*x(?:\*\*(\d+))?")
    matches = list(term_pattern.finditer(text))
    if len(matches) != 2:
        return None
    remainder = term_pattern.sub("", text).replace("+", "").replace("-", "")
    if remainder:
        return None
    return tuple(sorted(int(match.group(1) or "1") for match in matches))


def _ode_semantic_match(pred: str, gold: str, problem_type: str) -> bool:
    if problem_type in _UNORDERED_SEQUENCE_TYPES and _sequence_match(
        pred, gold, ordered=False
    ):
        return True
    if problem_type == "euler_cauchy_ode":
        pred_basis = _euler_cauchy_basis(pred)
        gold_basis = _euler_cauchy_basis(gold)
        return pred_basis is not None and pred_basis == gold_basis

    p = _semantic_math_text(pred, ode_variables=True)
    g = _semantic_math_text(gold, ode_variables=True)
    try:
        pexpr = safe_parse_math_expr(p, local_dict={"x": sp.Symbol("x", real=True)})
        gexpr = safe_parse_math_expr(g, local_dict={"x": sp.Symbol("x", real=True)})
        return bool(sp.simplify(pexpr - gexpr) == 0)
    except Exception:
        return False


def short_answer_match(
    pred: str,
    gold: str,
    *,
    problem_type: str = "",
    domain: str = "",
) -> bool:
    """Conservatively accept exact, numeric, or proven symbolic equivalence."""

    prediction = str(pred or "")
    expected = str(gold or "")
    if (
        len(prediction) > _MAX_SEMANTIC_ANSWER_CHARS
        or len(expected) > _MAX_SEMANTIC_ANSWER_CHARS
    ):
        return False
    if normalized_match(prediction, expected):
        return True
    ptype = str(problem_type or "").strip().lower()
    normalized_domain = str(domain or "").strip().lower()
    complex_numbers = normalized_domain == "complexanalysis"
    simple_prediction = prediction.strip().rstrip(".").casefold()
    simple_expected = expected.strip().rstrip(".").casefold()
    if simple_prediction in {"yes", "no"} or simple_expected in {"yes", "no"}:
        return simple_prediction == simple_expected
    if ptype in _ASSIGNMENT_SEQUENCE_TYPES and _assignment_sequence_match(
        prediction, expected
    ):
        return True
    if ptype in _UNORDERED_SEQUENCE_TYPES and _sequence_match(
        prediction,
        expected,
        ordered=False,
        complex_numbers=complex_numbers,
    ):
        return True
    if ptype in _ORDERED_SEQUENCE_TYPES and _sequence_match(
        prediction,
        expected,
        ordered=True,
        complex_numbers=complex_numbers,
    ):
        return True
    if ptype in _MATRIX_TYPES and _matrix_match(prediction, expected):
        return True
    if normalized_domain == "ode" or ptype in _ODE_TYPES:
        return _ode_semantic_match(prediction, expected, ptype)
    if ptype in _RELATION_TYPES and _relation_match(
        prediction,
        expected,
        complex_numbers=complex_numbers,
    ):
        return True
    return _scalar_semantic_match(
        prediction,
        expected,
        complex_numbers=complex_numbers,
    )
