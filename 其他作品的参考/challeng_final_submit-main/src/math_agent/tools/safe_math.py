from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import sympy as sp  # type: ignore[import-untyped]
from sympy.parsing.sympy_parser import (  # type: ignore[import-untyped]
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)


MAX_EXPRESSION_CHARS = 512
MAX_INTEGER_DIGITS = 32
MAX_ABSOLUTE_INTEGER = 1_000_000_000_000
MAX_NUMERIC_EXPONENT = 128
MAX_PARENTHESES_DEPTH = 32
MAX_OPERATORS = 128
MAX_FUNCTION_NESTING = 8

_TRANSFORMS = standard_transformations + (
    convert_xor,
    implicit_multiplication_application,
)
_SYMBOL_NAMES = {
    *"abcdefghijklmnopqrstuvwxyz",
    *"ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "alpha",
    "beta",
    "gamma",
    "theta",
}
_FUNCTIONS: dict[str, Any] = {
    "Abs": sp.Abs,
    "abs": sp.Abs,
    "acos": sp.acos,
    "asin": sp.asin,
    "atan": sp.atan,
    "cos": sp.cos,
    "cosh": sp.cosh,
    "exp": sp.exp,
    "factorial": sp.factorial,
    "ln": sp.log,
    "log": sp.log,
    "sin": sp.sin,
    "sinh": sp.sinh,
    "sqrt": sp.sqrt,
    "tan": sp.tan,
    "tanh": sp.tanh,
}
_CONSTANTS: dict[str, Any] = {
    "E": sp.E,
    "I": sp.I,
    "e": sp.E,
    "oo": sp.oo,
    "pi": sp.pi,
}
_SAFE_GLOBALS: dict[str, Any] = {
    "__builtins__": {},
    "Add": sp.Add,
    "Float": sp.Float,
    "Integer": sp.Integer,
    "Mul": sp.Mul,
    "Pow": sp.Pow,
    "Rational": sp.Rational,
    "Symbol": sp.Symbol,
}


def _check_parentheses(text: str) -> None:
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
            if depth > MAX_PARENTHESES_DEPTH:
                raise ValueError("math expression nesting limit exceeded")
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced math expression parentheses")
    if depth:
        raise ValueError("unbalanced math expression parentheses")


def validate_math_expression(
    expression: str,
    *,
    extra_identifiers: set[str] | None = None,
) -> str:
    text = str(expression or "").strip()
    if not text:
        raise ValueError("empty math expression")
    if len(text) > MAX_EXPRESSION_CHARS:
        raise ValueError("math expression length limit exceeded")
    if "__" in text:
        raise ValueError("dunder access is not allowed in math expressions")
    if not re.fullmatch(r"[0-9A-Za-z_+\-*/^().,\s]+", text):
        raise ValueError("math expression contains unsupported characters")
    if re.search(r"(?<!\d)\.(?!\d)", text):
        raise ValueError("attribute access is not allowed in math expressions")
    if len(re.findall(r"[+\-*/^]", text)) > MAX_OPERATORS:
        raise ValueError("math expression operation limit exceeded")
    for number in re.findall(
        r"(?<![A-Za-z_])[-+]?(?:\d+(?:\.\d*)?|\.\d+)",
        text,
    ):
        digits = re.sub(r"\D", "", number)
        try:
            magnitude = abs(Decimal(number))
        except InvalidOperation as exc:
            raise ValueError("invalid numeric literal") from exc
        if len(digits) > MAX_INTEGER_DIGITS or magnitude > MAX_ABSOLUTE_INTEGER:
            raise ValueError("math expression integer-size limit exceeded")
    factorial_calls = list(
        re.finditer(r"\bfactorial\s*\(\s*(\d+)\s*\)", text)
    )
    if len(re.findall(r"\bfactorial\b", text)) != len(factorial_calls):
        raise ValueError("factorial requires a direct nonnegative integer argument")
    if factorial_calls and re.search(r"\^|\*\*", text):
        raise ValueError("factorial combined with exponentiation is not allowed")
    for match in factorial_calls:
        if int(match.group(1)) > 14:
            raise ValueError("factorial argument limit exceeded")

    _check_parentheses(text)

    allowed_identifiers = (
        _SYMBOL_NAMES
        | set(_FUNCTIONS)
        | set(_CONSTANTS)
        | (extra_identifiers or set())
    )
    identifiers = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
    unsupported = sorted(identifiers - allowed_identifiers)
    if unsupported:
        raise ValueError(
            "unsupported math identifier(s): " + ", ".join(unsupported)
        )

    for match in re.finditer(
        r"(?:\^|\*\*)\s*\(?\s*([-+]?\d+)", text
    ):
        if abs(int(match.group(1))) > MAX_NUMERIC_EXPONENT:
            raise ValueError("math expression exponent limit exceeded")
    return text


def safe_parse_math_expr(
    expression: str,
    *,
    local_dict: Mapping[str, Any] | None = None,
):
    local_values: dict[str, Any] = {
        **{name: sp.Symbol(name, real=True) for name in _SYMBOL_NAMES},
        **_FUNCTIONS,
        **_CONSTANTS,
    }
    if local_dict:
        local_values.update(dict(local_dict))
    text = validate_math_expression(
        expression,
        extra_identifiers=set(local_values),
    )
    try:
        parsed = parse_expr(
            text,
            transformations=_TRANSFORMS,
            local_dict=local_values,
            global_dict=_SAFE_GLOBALS,
            evaluate=False,
        )
    except Exception as exc:
        raise ValueError("invalid math expression") from exc
    if sp.count_ops(parsed, visual=False) > MAX_OPERATORS:
        raise ValueError("parsed math expression operation limit exceeded")
    def function_depth(node: Any) -> int:
        child_depth = max(
            (function_depth(child) for child in node.args),
            default=0,
        )
        return child_depth + (1 if bool(getattr(node, "is_Function", False)) else 0)

    if function_depth(parsed) > MAX_FUNCTION_NESTING:
        raise ValueError("math function nesting limit exceeded")

    for node in sp.preorder_traversal(parsed):
        if isinstance(node, sp.Integer) and abs(int(node)) > MAX_ABSOLUTE_INTEGER:
            raise ValueError("parsed integer-size limit exceeded")
        if isinstance(node, sp.Pow):
            exponent = node.exp
            if node.base.is_number and exponent.has(sp.Pow):
                raise ValueError("numeric power towers are not allowed")
            if exponent.is_number and exponent.is_real:
                if not isinstance(exponent, (sp.Integer, sp.Rational, sp.Float)):
                    raise ValueError("compound numeric exponents are not allowed")
                try:
                    exponent_value = float(exponent)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("invalid numeric exponent") from exc
                if abs(exponent_value) > MAX_NUMERIC_EXPONENT:
                    raise ValueError("parsed exponent limit exceeded")
    return parsed
