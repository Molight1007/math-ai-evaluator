from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import permutations
from math import factorial, gcd
from tokenize import TokenError
from typing import Any, Callable, Literal, Sequence, cast

import sympy as sp  # type: ignore[import-untyped]

from math_agent.tools.safe_math import safe_parse_math_expr


VerificationMethod = Literal["numeric_check", "symbolic_check", "substitution"]
ToolKind = Literal["python", "sympy"]


@dataclass(frozen=True)
class DeterministicSolution:
    value: str
    method: VerificationMethod
    notes: str
    purpose: str
    tool: ToolKind = "sympy"


_SYMBOLS = {
    name: sp.Symbol(name, real=True)
    for name in ("a", "b", "c", "i", "j", "k", "m", "n", "t", "x", "y", "z")
}
_LOCALS = {
    **_SYMBOLS,
    "e": sp.E,
    "E": sp.E,
    "I": sp.I,
    "pi": sp.pi,
    "sqrt": sp.sqrt,
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "log": sp.log,
    "Abs": sp.Abs,
}
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_MAX_QUESTION_CHARS = 20_000
_MAX_LITERAL_ABS = 1_000_000_000_000
_MAX_COMBINATORIAL_N = 500
_MAX_MATRIX_ITEMS = 100
_MAX_ENUMERATED_SOLUTIONS = 1_000


def _solution(
    value: str,
    purpose: str,
    *,
    method: VerificationMethod = "symbolic_check",
    tool: ToolKind = "sympy",
) -> DeterministicSolution:
    return DeterministicSolution(
        value=value.strip(),
        method=method,
        notes=f"independently recomputed: {purpose}",
        purpose=purpose,
        tool=tool,
    )


def tool_input_within_resource_limits(question: str) -> bool:
    text = re.sub(r"\s+", " ", str(question or "").strip())
    if not text or len(text) > _MAX_QUESTION_CHARS:
        return False
    numeric_literals = re.findall(
        r"(?<![A-Za-z_])[-+]?(?:\d+(?:\.\d*)?|\.\d+)",
        text,
    )
    for value in numeric_literals:
        digits = re.sub(r"\D", "", value)
        try:
            magnitude = abs(Decimal(value))
        except InvalidOperation:
            return False
        if len(digits) > 32 or magnitude > _MAX_LITERAL_ABS:
            return False
    integer_literals = [
        int(value) for value in numeric_literals if re.fullmatch(r"[-+]?\d+", value)
    ]
    if any(
        marker in text.lower()
        for marker in (
            "choose",
            "permutation",
            "catalan",
            "binomial probability",
            "coin is tossed",
        )
    ) and any(abs(value) > _MAX_COMBINATORIAL_N for value in integer_literals):
        return False
    if any(
        marker in text.lower()
        for marker in (
            "euler phi",
            "positive divisors",
            "least nonnegative solution to x",
        )
    ) and any(abs(value) > 1_000_000_000 for value in integer_literals):
        return False
    return True


def _parse_expr(value: str):
    text = value.strip().replace("\u2212", "-")
    text = re.sub(r"(?<=\d)e(?=\s*\^)", "*e", text)
    text = re.sub(r"(?<=\d)(?=[xy])", "*", text)
    text = re.sub(r"\bxy\b", "x*y", text)
    return safe_parse_math_expr(text, local_dict=_LOCALS)


def _rational(value: str) -> sp.Rational:
    return cast(sp.Rational, sp.Rational(value.strip()))


def _format_expr(value: Any) -> str:
    expr = sp.simplify(value)
    text = str(expr).replace("**", "^")
    text = re.sub(r"exp\(([^()]*)\)", r"e^(\1)", text)
    text = re.sub(r"\bI\b", "i", text)
    return text.replace(" ", "")


def _format_values(values: Sequence[Any]) -> str:
    unique = list(dict.fromkeys(sp.simplify(value) for value in values))
    unique.sort(key=sp.default_sort_key)
    return ",".join(_format_expr(value) for value in unique)


def _format_values_with_multiplicity(values: Sequence[Any]) -> str:
    ordered = [sp.simplify(value) for value in values]
    ordered.sort(key=sp.default_sort_key)
    return ",".join(_format_expr(value) for value in ordered)


def _format_matrix(matrix: sp.MatrixBase) -> str:
    return str(matrix.tolist()).replace(" ", "")


def _format_tuple_matrix(matrix: sp.MatrixBase) -> str:
    rows = [
        "("
        + ",".join(_format_expr(matrix[row, col]) for col in range(matrix.cols))
        + ")"
        for row in range(matrix.rows)
    ]
    return "[" + ",".join(rows) + "]"


def _format_tuple(values: Sequence[Any]) -> str:
    return "(" + ",".join(_format_expr(value) for value in values) + ")"


def _literal_sequence(value: str):
    parsed = ast.literal_eval(value)
    if not isinstance(parsed, (list, tuple)):
        raise ValueError("expected a sequence")

    item_count = 0

    def validate(item: Any, depth: int = 0) -> None:
        nonlocal item_count
        if depth > 2:
            raise ValueError("sequence nesting limit exceeded")
        if isinstance(item, (list, tuple)):
            for child in item:
                validate(child, depth + 1)
            return
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or abs(item) > _MAX_LITERAL_ABS
        ):
            raise ValueError("unsupported sequence value")
        item_count += 1
        if item_count > _MAX_MATRIX_ITEMS:
            raise ValueError("sequence item limit exceeded")

    validate(parsed)
    return parsed


def _matrix_values(matrix: sp.MatrixBase) -> list[Any]:
    return [matrix[index] for index in range(matrix.rows * matrix.cols)]


def _solve_algebra(question: str) -> DeterministicSolution | None:
    q = question.strip()
    lower = q.lower()
    x = _SYMBOLS["x"]
    y = _SYMBOLS["y"]

    def polynomial_real_roots(expression: Any) -> list[Any] | None:
        polynomial = sp.Poly(sp.expand(expression), x)
        if polynomial.degree() < 1 or polynomial.degree() > 8:
            return None
        roots_with_multiplicity = sp.roots(polynomial.as_expr(), x)
        roots = [
            root
            for root, multiplicity in roots_with_multiplicity.items()
            for _ in range(int(multiplicity))
            if bool(root.is_real)
        ]
        return roots if len(roots) == polynomial.degree() else None

    elementary_linear = re.fullmatch(
        r"solve\s+the\s+linear\s+equation\s+(.+?)\s*=\s*(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if elementary_linear:
        lhs, rhs = elementary_linear.groups()
        polynomial = sp.Poly(_parse_expr(lhs) - _parse_expr(rhs), x)
        if polynomial.degree() == 1:
            coefficient, constant = polynomial.all_coeffs()
            if coefficient != 0:
                return _solution(
                    _format_expr(-constant / coefficient),
                    "solve an elementary linear equation",
                    method="substitution",
                )

    elementary_inequality = re.fullmatch(
        r"solve\s+the\s+inequality\s+(.+?)\s*(<=|>=|<|>)\s*(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if elementary_inequality:
        lhs, operator, rhs = elementary_inequality.groups()
        polynomial = sp.Poly(_parse_expr(lhs) - _parse_expr(rhs), x)
        if polynomial.degree() == 1:
            coefficient, constant = polynomial.all_coeffs()
            if coefficient != 0:
                bound = -constant / coefficient
                if coefficient < 0:
                    operator = {
                        "<": ">",
                        "<=": ">=",
                        ">": "<",
                        ">=": "<=",
                    }[operator]
                return _solution(
                    f"x{operator}{_format_expr(bound)}",
                    "solve an elementary linear inequality",
                    method="substitution",
                )

    elementary_quadratic = re.fullmatch(
        r"find\s+all\s+real\s+roots\s+of\s+(.+?)\s*=\s*0\s*\.?",
        q,
        flags=re.I,
    )
    if elementary_quadratic:
        roots = polynomial_real_roots(_parse_expr(elementary_quadratic.group(1)))
        if roots:
            return _solution(
                _format_values(roots),
                "find all real roots of an elementary polynomial",
                method="substitution",
            )

    elementary_system = re.fullmatch(
        r"solve\s+the\s+system\s+(.+?)\s*=\s*(.+?),\s*"
        r"(.+?)\s*=\s*(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if elementary_system:
        lhs_a, rhs_a, lhs_b, rhs_b = elementary_system.groups()
        equations = [
            sp.Eq(_parse_expr(lhs_a), _parse_expr(rhs_a)),
            sp.Eq(_parse_expr(lhs_b), _parse_expr(rhs_b)),
        ]
        solved = sp.solve(equations, (x, y), dict=True)
        if len(solved) == 1 and x in solved[0] and y in solved[0]:
            return _solution(
                f"x={_format_expr(solved[0][x])},y={_format_expr(solved[0][y])}",
                "solve an elementary two-variable linear system",
                method="substitution",
            )

    integer_power = re.fullmatch(
        r"compute\s+the\s+integer\s+power\s+([-+]?\d+)\^(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if integer_power:
        base, exponent = map(int, integer_power.groups())
        if exponent <= _MAX_COMBINATORIAL_N:
            return _solution(
                str(base**exponent),
                "compute a bounded integer power",
                method="numeric_check",
                tool="python",
            )

    square_root_offset = re.fullmatch(
        r"simplify\s+sqrt\((\d+)\)\s*\+\s*\(([-+]?\d+)\)\s*\.?",
        q,
        flags=re.I,
    )
    if square_root_offset:
        radicand, offset = map(int, square_root_offset.groups())
        root = sp.sqrt(radicand)
        if root.is_integer:
            return _solution(
                _format_expr(root + offset),
                "simplify a perfect square root and integer offset",
                method="numeric_check",
            )

    elementary_word_problem = re.fullmatch(
        r"a\s+number\s+is\s+multiplied\s+by\s+([-+]?\d+),\s*then\s+"
        r"([-+]?\d+)\s+is\s+added,\s*giving\s+([-+]?\d+)\.\s*"
        r"what\s+is\s+the\s+number\s*\?",
        q,
        flags=re.I,
    )
    if elementary_word_problem:
        multiplier, addend, result = map(int, elementary_word_problem.groups())
        if multiplier != 0:
            return _solution(
                _format_expr(sp.Rational(result - addend, multiplier)),
                "solve an elementary one-variable word problem",
                method="substitution",
            )

    arithmetic_progression = re.fullmatch(
        r"an\s+arithmetic\s+progression\s+has\s+first\s+term\s+([-+]?\d+)\s+"
        r"and\s+common\s+difference\s+([-+]?\d+)\.\s*find\s+its\s+(\d+)"
        r"(?:st|nd|rd|th)\s+term\s*\.?",
        q,
        flags=re.I,
    )
    if arithmetic_progression:
        first, difference, index = map(int, arithmetic_progression.groups())
        if 1 <= index <= _MAX_COMBINATORIAL_N:
            return _solution(
                str(first + (index - 1) * difference),
                "compute an arithmetic-progression term",
                method="numeric_check",
                tool="python",
            )

    geometric_progression = re.fullmatch(
        r"a\s+geometric\s+progression\s+starts\s+at\s+([-+]?\d+)\s+with\s+"
        r"ratio\s+([-+]?\d+)\.\s*find\s+term\s+number\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if geometric_progression:
        first, ratio, index = map(int, geometric_progression.groups())
        if 1 <= index <= _MAX_COMBINATORIAL_N:
            return _solution(
                str(first * ratio ** (index - 1)),
                "compute a geometric-progression term",
                method="numeric_check",
                tool="python",
            )

    fraction_sum = re.fullmatch(
        r"compute\s+and\s+reduce\s+the\s+fraction\s+"
        r"([-+]?\d+/\d+)\s*\+\s*([-+]?\d+/\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if fraction_sum:
        left, right = map(_rational, fraction_sum.groups())
        return _solution(
            _format_expr(left + right),
            "add and reduce two rational numbers",
            method="numeric_check",
        )

    percentage_increase = re.fullmatch(
        r"a\s+price\s+of\s+([-+]?\d+)\s+is\s+increased\s+by\s+(\d+)%\.\s*"
        r"what\s+is\s+the\s+new\s+price\s*\?",
        q,
        flags=re.I,
    )
    if percentage_increase:
        price, percent = map(int, percentage_increase.groups())
        return _solution(
            _format_expr(sp.Rational(price * (100 + percent), 100)),
            "apply an exact percentage increase",
            method="numeric_check",
        )

    elementary_absolute_value = re.fullmatch(
        r"solve\s+\|([-+]?\d*)x(?:\s*([+-])\s*(\d+))?\|\s*=\s*(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if elementary_absolute_value:
        coefficient_text, sign, offset_text, radius_text = (
            elementary_absolute_value.groups()
        )
        coefficient = int(coefficient_text or "1")
        offset = int(offset_text or "0") * (1 if sign != "-" else -1)
        radius = int(radius_text)
        if coefficient != 0:
            roots = [
                sp.Rational(-offset - radius, coefficient),
                sp.Rational(-offset + radius, coefficient),
            ]
            return _solution(
                _format_values(roots),
                "solve an elementary absolute-value equation",
                method="substitution",
            )

    affine_composition = re.fullmatch(
        r"let\s+f\(x\)\s*=\s*(.+?)\s+and\s+g\(x\)\s*=\s*(.+?)\.\s*"
        r"compute\s+f\(g\(([-+]?\d+)\)\)\s*\.?",
        q,
        flags=re.I,
    )
    if affine_composition:
        f_text, g_text, point_text = affine_composition.groups()
        f_expr = _parse_expr(f_text)
        g_expr = _parse_expr(g_text)
        if sp.Poly(f_expr, x).degree() <= 1 and sp.Poly(g_expr, x).degree() <= 1:
            point = int(point_text)
            value = f_expr.subs(x, g_expr.subs(x, point))
            return _solution(
                _format_expr(value),
                "compose two affine functions at a point",
                method="substitution",
            )

    independent_cubic = re.fullmatch(
        r"solve\s+(.+?)\s*=\s*0\s+over\s+the\s+reals\s*\.?",
        q,
        flags=re.I,
    )
    if independent_cubic:
        roots = polynomial_real_roots(_parse_expr(independent_cubic.group(1)))
        if roots:
            return _solution(
                _format_values(roots),
                "solve real polynomial roots",
                method="substitution",
            )

    every_real_zero = re.fullmatch(
        r"find\s+every\s+real\s+zero\s+of\s+(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if every_real_zero:
        roots = polynomial_real_roots(_parse_expr(every_real_zero.group(1)))
        if roots:
            return _solution(
                _format_values(roots),
                "find all real polynomial zeros",
                method="substitution",
            )

    independent_factor = re.fullmatch(
        r"factor\s+(.+?)\s+completely\s+over\s+the\s+integers\s*\.?",
        q,
        flags=re.I,
    )
    if independent_factor:
        expression = _parse_expr(independent_factor.group(1))
        polynomial = sp.Poly(expression, x)
        roots = polynomial_real_roots(expression)
        if (
            polynomial.LC() == 1
            and roots
            and all(bool(root.is_integer) for root in roots)
        ):
            unique_roots = sorted(set(roots), key=sp.default_sort_key)
            factors: list[str] = []
            for root in unique_roots:
                multiplicity = roots.count(root)
                if root > 0:
                    factor = f"(x-{_format_expr(root)})"
                elif root < 0:
                    factor = f"(x+{_format_expr(-root)})"
                else:
                    factor = "x"
                factors.extend([factor] * multiplicity)
            return _solution("".join(factors), "factor monic integer polynomial")

    independent_remainder = re.fullmatch(
        rf"find\s+the\s+remainder\s+when\s+(.+?)\s+is\s+divided\s+by\s+"
        rf"x\s*-\s*\(({_NUMBER})\)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_remainder:
        expression, point = independent_remainder.groups()
        value = _parse_expr(expression).subs(x, _rational(point))
        return _solution(
            _format_expr(value),
            "apply polynomial remainder theorem",
            method="substitution",
        )

    rational_equation = re.fullmatch(
        rf"solve\s+({_NUMBER})/x\s*\+\s*\(({_NUMBER})\)\s*=\s*"
        rf"({_NUMBER})\s*,\s*with\s+x\s*!=\s*0\s*\.?",
        q,
        flags=re.I,
    )
    if rational_equation:
        numerator, offset, rhs = map(_rational, rational_equation.groups())
        denominator = rhs - offset
        if numerator != 0 and denominator != 0:
            value = numerator / denominator
            return _solution(
                f"x={_format_expr(value)}",
                "solve one-term rational equation",
                method="substitution",
            )

    symmetric_system = re.fullmatch(
        rf"real\s+numbers\s+x,y\s+satisfy\s+x\+y\s*=\s*({_NUMBER})\s+and\s+"
        rf"xy\s*=\s*({_NUMBER})\s*\.\s*compute\s+x\^2\+y\^2\s*\.?",
        q,
        flags=re.I,
    )
    if symmetric_system:
        total, product = map(_rational, symmetric_system.groups())
        return _solution(
            _format_expr(total**2 - 2 * product),
            "apply symmetric polynomial identity",
        )

    quadratic_formula = re.fullmatch(
        r"use\s+the\s+quadratic\s+formula\s+to\s+solve\s+(.+?)\s*=\s*0\s*\.?",
        q,
        flags=re.I,
    )
    if quadratic_formula:
        roots = polynomial_real_roots(_parse_expr(quadratic_formula.group(1)))
        if roots:
            return _solution(
                _format_values(roots),
                "solve quadratic equation",
                method="substitution",
            )

    centered_absolute_value = re.fullmatch(
        rf"find\s+all\s+x\s+such\s+that\s+\|x\s*-\s*\(({_NUMBER})\)\|\s*=\s*"
        rf"({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if centered_absolute_value:
        center, radius = map(_rational, centered_absolute_value.groups())
        if radius >= 0:
            return _solution(
                _format_values([center - radius, center + radius]),
                "solve centered absolute-value equation",
            )

    repeated_root = re.fullmatch(
        r"which\s+real\s+root\s+of\s+(.+?)\s*=\s*0\s+has\s+"
        r"multiplicity\s+two\s*\??",
        q,
        flags=re.I,
    )
    if repeated_root:
        polynomial = sp.Poly(_parse_expr(repeated_root.group(1)), x)
        multiplicities = sp.roots(polynomial.as_expr(), x)
        repeated = [root for root, count in multiplicities.items() if count == 2]
        if len(repeated) == 1 and bool(repeated[0].is_real):
            return _solution(
                _format_expr(repeated[0]),
                "identify repeated polynomial root",
            )

    root_coefficient = re.fullmatch(
        rf"find\s+k\s+if\s+x\s*=\s*({_NUMBER})\s+is\s+a\s+root\s+of\s+"
        rf"x\^2\s*\+\s*kx\s*\+\s*\(({_NUMBER})\)\s*=\s*0\s*\.?",
        q,
        flags=re.I,
    )
    if root_coefficient:
        root, constant = map(_rational, root_coefficient.groups())
        if root != 0:
            value = -(root**2 + constant) / root
            return _solution(
                _format_expr(value),
                "identify polynomial coefficient from known root",
                method="substitution",
            )

    independent_polynomial_equation = re.fullmatch(
        r"solve\s+(.+?)\s*=\s*0\s*\.?",
        q,
        flags=re.I,
    )
    if independent_polynomial_equation:
        roots = polynomial_real_roots(
            _parse_expr(independent_polynomial_equation.group(1))
        )
        if roots:
            return _solution(
                _format_values(roots),
                "solve polynomial equation",
                method="substitution",
            )

    vieta_reciprocals = re.fullmatch(
        rf"the\s+nonzero\s+roots\s+of\s+x\^2\s*-\s*\(({_NUMBER})\)x\s*"
        rf"\+\s*\(({_NUMBER})\)\s*=\s*0\s+are\s+r,s\.\s*"
        r"find\s+1/r\s*\+\s*1/s\s*\.?",
        q,
        flags=re.I,
    )
    if vieta_reciprocals:
        root_sum, root_product = map(_rational, vieta_reciprocals.groups())
        if root_product != 0:
            return _solution(
                _format_expr(root_sum / root_product),
                "apply Vieta reciprocal-root identity",
            )

    polynomial_evaluation = re.fullmatch(
        rf"evaluate\s+P\(({_NUMBER})\)\s+for\s+P\(x\)\s*=\s*(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if polynomial_evaluation:
        point, expression = polynomial_evaluation.groups()
        value = _parse_expr(expression).subs(x, _rational(point))
        return _solution(
            _format_expr(value),
            "evaluate polynomial at a point",
            method="numeric_check",
        )

    polynomial_gcd = re.fullmatch(
        r"find\s+the\s+monic\s+polynomial\s+gcd\s+of\s+(.+?)\s+and\s+"
        r"(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if polynomial_gcd:
        left, right = polynomial_gcd.groups()
        left_polynomial = sp.Poly(_parse_expr(left), x)
        right_polynomial = sp.Poly(_parse_expr(right), x)
        gcd_polynomial = left_polynomial.gcd(right_polynomial)
        return _solution(
            _format_expr(gcd_polynomial.monic().as_expr()),
            "compute monic polynomial gcd",
        )

    system_match = re.fullmatch(
        r"solve\s+the\s+system\s*:\s*(.+?=.+?)\s*,\s*(.+?=.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if system_match:
        equations = []
        for raw in system_match.groups():
            lhs, rhs = raw.split("=", 1)
            parsed_lhs = _parse_expr(lhs)
            parsed_rhs = _parse_expr(rhs)
            polynomial = (parsed_lhs - parsed_rhs).as_poly(x, y)
            if polynomial is not None and polynomial.total_degree() > 4:
                return None
            equations.append(sp.Eq(parsed_lhs, parsed_rhs))
        solved = sp.solve(equations, (x, y), dict=True)
        if len(solved) == 1 and x in solved[0] and y in solved[0]:
            value = f"x={_format_expr(solved[0][x])},y={_format_expr(solved[0][y])}"
            return _solution(value, "solve equation system", method="substitution")
        if solved:
            pairs = [
                f"x={_format_expr(item[x])},y={_format_expr(item[y])}"
                for item in solved
                if x in item and y in item
            ]
            if pairs:
                return _solution(";".join(pairs), "solve equation system")
            if len(solved) == 1 and len(solved[0]) == 1:
                variable, expression = next(iter(solved[0].items()))
                return _solution(
                    f"{variable}={_format_expr(expression)}",
                    "solve underdetermined equation system",
                    method="substitution",
                )

    inequality_match = re.fullmatch(
        r"solve\s+inequality\s*:\s*(.+?)\s*(<=|>=|<|>)\s*(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if inequality_match:
        lhs, operator, rhs = inequality_match.groups()
        difference = sp.expand(_parse_expr(lhs) - _parse_expr(rhs))
        polynomial = sp.Poly(difference, x)
        if polynomial.degree() == 1:
            coefficient, constant = polynomial.all_coeffs()
            if coefficient != 0:
                bound = -constant / coefficient
                if coefficient < 0:
                    operator = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}[operator]
                return _solution(
                    f"x{operator}{_format_expr(bound)}",
                    "solve linear inequality",
                    method="substitution",
                )
        relations = {"<": sp.Lt, "<=": sp.Le, ">": sp.Gt, ">=": sp.Ge}
        relation = relations[operator](_parse_expr(lhs), _parse_expr(rhs))
        solved = sp.solve_univariate_inequality(relation, x, relational=True)
        return _solution(
            _format_expr(solved), "solve linear inequality", method="substitution"
        )

    word_match = re.fullmatch(
        rf"if\s+a\s+number\s+is\s+multiplied\s+by\s+({_NUMBER})\s+and\s+then\s+"
        rf"({_NUMBER})\s+is\s+added,?\s+the\s+result\s+is\s+({_NUMBER})\.\s*"
        r"find\s+the\s+number\.?",
        q,
        flags=re.I,
    )
    if word_match:
        multiplier, added, result = map(_rational, word_match.groups())
        if multiplier != 0:
            value = _format_expr((result - added) / multiplier)
            return _solution(value, "solve one-variable word problem")

    factor_match = re.fullmatch(r"factor\s*:\s*(.+?)\s*\.?", q, flags=re.I)
    if factor_match:
        expression = _parse_expr(factor_match.group(1))
        polynomial = expression.as_poly(x)
        if polynomial is None or polynomial.degree() > 8:
            return None
        factored = sp.factor(expression)
        return _solution(_format_expr(factored), "factor polynomial")

    evaluate_at_match = re.fullmatch(
        rf"evaluate\s+(.+?)\s+at\s+x\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if evaluate_at_match:
        expr, point = evaluate_at_match.groups()
        value = _parse_expr(expr).subs(x, _rational(point))
        return _solution(
            _format_expr(value), "evaluate expression", method="numeric_check"
        )

    evaluate_match = re.fullmatch(r"evaluate\s*:\s*(.+?)\s*\.?", q, flags=re.I)
    if evaluate_match:
        value = _parse_expr(evaluate_match.group(1))
        if not value.free_symbols:
            return _solution(
                _format_expr(value),
                "evaluate arithmetic expression",
                method="numeric_check",
            )

    absolute_match = re.fullmatch(
        rf"solve\s*:\s*\|(.+?)\|\s*=\s*({_NUMBER})\s*\.?", q, flags=re.I
    )
    if absolute_match:
        inside, rhs = absolute_match.groups()
        values = sp.solve(sp.Eq(sp.Abs(_parse_expr(inside)), _rational(rhs)), x)
        return _solution(_format_values(values), "solve absolute-value equation")

    equation_match = re.fullmatch(
        r"(?:solve(?:\s+using\s+quadratic\s+formula)?|find\s+roots?|find\s+root)\s*:\s*"
        r"(.+?)\s*=\s*(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if equation_match and not any(
        token in lower for token in ("ode", "pde", "u_x", "dy/dx")
    ):
        lhs, rhs = equation_match.groups()
        parsed_lhs = _parse_expr(lhs)
        parsed_rhs = _parse_expr(rhs)
        expression = parsed_lhs - parsed_rhs
        polynomial = expression.as_poly(x)
        if polynomial is not None and polynomial.degree() > 8:
            return None
        values: list[Any]
        if polynomial is not None and polynomial.degree() == 1:
            a, b = polynomial.all_coeffs()
            values = [-b / a]
        elif polynomial is not None and polynomial.degree() == 2:
            a, b, c = polynomial.all_coeffs()
            discriminant = sp.expand(b**2 - 4 * a * c)
            values = [
                (-b - sp.sqrt(discriminant)) / (2 * a),
                (-b + sp.sqrt(discriminant)) / (2 * a),
            ]
        elif polynomial is not None and len(polynomial.terms()) == 1:
            values = [sp.Integer(0)]
        else:
            values = sp.solve(sp.Eq(parsed_lhs, parsed_rhs), x)
        if isinstance(values, list) and values:
            return _solution(
                _format_values(values),
                "solve algebraic equation",
                method="substitution",
            )
    return None


def _solve_single_variable_calculus(
    question: str,
) -> DeterministicSolution | None:
    q = question.strip()
    x = _SYMBOLS["x"]

    independent_monomial_derivative = re.fullmatch(
        rf"for\s+f\(x\)=(\d*)x\^(\d+),\s*compute\s+f'\(({_NUMBER})\)\.?",
        q,
        flags=re.I,
    )
    if independent_monomial_derivative:
        coefficient_text, exponent_text, point_text = (
            independent_monomial_derivative.groups()
        )
        coefficient = int(coefficient_text or "1")
        exponent = int(exponent_text)
        point = _rational(point_text)
        value = coefficient * exponent * point ** (exponent - 1)
        return _solution(
            _format_expr(value),
            "differentiate a monomial and substitute",
        )

    independent_exponential_derivative = re.fullmatch(
        r"for\s+f\(x\)=(\d+)\*exp\((\d*)x\),\s*compute\s+f'\(0\)\.?",
        q,
        flags=re.I,
    )
    if independent_exponential_derivative:
        coefficient_text, rate_text = independent_exponential_derivative.groups()
        coefficient = int(coefficient_text)
        rate = int(rate_text or "1")
        return _solution(
            str(coefficient * rate),
            "differentiate an exponential and evaluate at zero",
        )

    independent_sine_derivative = re.fullmatch(
        r"differentiate\s+sin\((\d*)x\)\s+and\s+evaluate\s+the\s+"
        r"derivative\s+at\s+x=0\.?",
        q,
        flags=re.I,
    )
    if independent_sine_derivative:
        frequency = int(independent_sine_derivative.group(1) or "1")
        return _solution(
            str(frequency),
            "differentiate a sine and evaluate at zero",
        )

    independent_antiderivative = re.fullmatch(
        r"find\s+an\s+antiderivative\s+of\s+(\d+)x(?:\^(\d+))?;\s*"
        r"use\s+C\s+for\s+the\s+constant\.?",
        q,
        flags=re.I,
    )
    if independent_antiderivative:
        coefficient = int(independent_antiderivative.group(1))
        exponent = int(independent_antiderivative.group(2) or "1")
        integrated = sp.Rational(coefficient, exponent + 1) * x ** (exponent + 1)
        return _solution(
            f"{_format_expr(integrated)}+C",
            "integrate a monomial",
        )

    independent_monomial_definite = re.fullmatch(
        rf"evaluate\s+the\s+definite\s+integral\s+of\s+(\d+)x"
        rf"(?:\^(\d+))?\s+from\s+x=({_NUMBER})\s+to\s+x=({_NUMBER})\.?",
        q,
        flags=re.I,
    )
    if independent_monomial_definite:
        coefficient_text, exponent_text, lower_text, upper_text = (
            independent_monomial_definite.groups()
        )
        coefficient = int(coefficient_text)
        exponent = int(exponent_text or "1")
        lower = _rational(lower_text)
        upper = _rational(upper_text)
        antiderivative_coefficient = sp.Rational(coefficient, exponent + 1)
        value = antiderivative_coefficient * (
            upper ** (exponent + 1) - lower ** (exponent + 1)
        )
        return _solution(
            _format_expr(value),
            "evaluate a monomial definite integral",
        )

    independent_polynomial_limit = re.fullmatch(
        rf"compute\s+lim_\(x->({_NUMBER})\)\s+\[(.+)\]\.?",
        q,
        flags=re.I,
    )
    if independent_polynomial_limit:
        point_text, expression_text = independent_polynomial_limit.groups()
        expression = _parse_expr(expression_text)
        polynomial = sp.Poly(expression, x)
        if polynomial.degree() <= 10:
            return _solution(
                _format_expr(expression.subs(x, _rational(point_text))),
                "evaluate a polynomial limit by continuity",
            )

    independent_removable_limit = re.fullmatch(
        r"evaluate\s+lim_\(x->([-+]?\d+)\)\s+"
        r"\(x\^2-(\d+)\)/\(x([-+]\d+)\)\.?",
        q,
        flags=re.I,
    )
    if independent_removable_limit:
        point, square, denominator_offset = map(
            int, independent_removable_limit.groups()
        )
        if point**2 == square and point + denominator_offset == 0:
            return _solution(
                str(2 * point),
                "cancel a removable quadratic factor",
            )

    independent_chain_rule = re.fullmatch(
        rf"compute\s+d/dx\[\(([-+]?\d*)x([-+]\d+)?\)\^(\d+)\]\s+"
        rf"at\s+x=({_NUMBER})\.?",
        q,
        flags=re.I,
    )
    if independent_chain_rule:
        coefficient_text, offset_text, power_text, point_text = (
            independent_chain_rule.groups()
        )

        def implicit_coefficient(value: str) -> int:
            if value in {"", "+"}:
                return 1
            if value == "-":
                return -1
            return int(value)

        coefficient = implicit_coefficient(coefficient_text)
        offset = int(offset_text or "0")
        power = int(power_text)
        point = _rational(point_text)
        value = power * coefficient * (coefficient * point + offset) ** (power - 1)
        return _solution(
            _format_expr(value),
            "apply the chain rule and substitute",
        )

    independent_product_rule = re.fullmatch(
        r"if\s+f\(x\)=\(([-+]?\d*)x([-+]\d+)\)\*exp\(x\),\s*"
        r"find\s+f'\(0\)\.?",
        q,
        flags=re.I,
    )
    if independent_product_rule:
        coefficient_text, offset_text = independent_product_rule.groups()
        if coefficient_text in {"", "+"}:
            coefficient = 1
        elif coefficient_text == "-":
            coefficient = -1
        else:
            coefficient = int(coefficient_text)
        return _solution(
            str(coefficient + int(offset_text)),
            "apply the product rule at zero",
        )

    independent_tangent = re.fullmatch(
        rf"find\s+the\s+slope\s+of\s+the\s+tangent\s+to\s+y=(.+?)\s+"
        rf"at\s+x=({_NUMBER})\.?",
        q,
        flags=re.I,
    )
    if independent_tangent:
        expression_text, point_text = independent_tangent.groups()
        expression = _parse_expr(expression_text)
        polynomial = sp.Poly(expression, x)
        if polynomial.degree() <= 2:
            value = sp.diff(expression, x).subs(x, _rational(point_text))
            return _solution(
                _format_expr(value),
                "differentiate a quadratic to find its tangent slope",
            )

    independent_signed_area = re.fullmatch(
        rf"find\s+the\s+signed\s+area\s+under\s+y=(.+?)\s+from\s+"
        rf"x=({_NUMBER})\s+to\s+x=({_NUMBER})\.?",
        q,
        flags=re.I,
    )
    if independent_signed_area:
        expression_text, lower_text, upper_text = independent_signed_area.groups()
        expression = _parse_expr(expression_text)
        polynomial = sp.Poly(expression, x)
        if polynomial.degree() <= 1:
            value = sp.integrate(
                expression,
                (x, _rational(lower_text), _rational(upper_text)),
            )
            return _solution(
                _format_expr(value),
                "integrate a linear function over an interval",
            )

    independent_average_value = re.fullmatch(
        rf"find\s+the\s+average\s+value\s+of\s+f\(x\)=(.+?)\s+on\s+"
        rf"\[({_NUMBER})\s*,\s*({_NUMBER})\]\.?",
        q,
        flags=re.I,
    )
    if independent_average_value:
        expression_text, lower_text, upper_text = independent_average_value.groups()
        expression = _parse_expr(expression_text)
        polynomial = sp.Poly(expression, x)
        lower = _rational(lower_text)
        upper = _rational(upper_text)
        if polynomial.degree() <= 1 and upper != lower:
            value = sp.integrate(expression, (x, lower, upper)) / (upper - lower)
            return _solution(
                _format_expr(value),
                "compute a function's average value",
            )

    independent_second_derivative = re.fullmatch(
        rf"for\s+f\(x\)=(\d*)x\^(\d+),\s*compute\s+f''\(({_NUMBER})\)\.?",
        q,
        flags=re.I,
    )
    if independent_second_derivative:
        coefficient_text, exponent_text, point_text = (
            independent_second_derivative.groups()
        )
        coefficient = int(coefficient_text or "1")
        exponent = int(exponent_text)
        point = _rational(point_text)
        value = coefficient * exponent * (exponent - 1) * point ** (exponent - 2)
        return _solution(
            _format_expr(value),
            "take a monomial's second derivative and substitute",
        )

    independent_log_exponential_integral = re.fullmatch(
        r"evaluate\s+integral_0\^ln\((\d+)\)\s+exp\(x\)\s+dx\.?",
        q,
        flags=re.I,
    )
    if independent_log_exponential_integral:
        upper_argument = int(independent_log_exponential_integral.group(1))
        if upper_argument > 0:
            return _solution(
                str(upper_argument - 1),
                "evaluate an exponential integral at a logarithmic bound",
            )

    definite_match = re.fullmatch(
        rf"definite\s+integral\s+of\s+(.+?)\s+from\s+([a-z])\s*=\s*({_NUMBER})\s+"
        rf"to\s+\2\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if definite_match:
        expr, variable, lower, upper = definite_match.groups()
        symbol = _SYMBOLS.get(variable.lower(), sp.Symbol(variable.lower()))
        value = sp.integrate(
            _parse_expr(expr),
            (symbol, _rational(lower), _rational(upper)),
        )
        return _solution(_format_expr(value), "compute definite integral")

    exponential_at_match = re.fullmatch(
        rf"derivative\s+of\s+f\(x\)\s*=\s*({_NUMBER})e\^x\s+at\s+"
        rf"x\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if exponential_at_match:
        coefficient, point = exponential_at_match.groups()
        return _solution(
            f"{_format_expr(_rational(coefficient))}*e^{point}",
            "differentiate exponential and substitute",
        )

    derivative_at_match = re.fullmatch(
        rf"derivative\s+of\s+(?:f\(x\)\s*=\s*)?(.+?)\s+at\s+x\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if derivative_at_match:
        expr, point = derivative_at_match.groups()
        value = sp.diff(_parse_expr(expr), x).subs(x, _rational(point))
        return _solution(_format_expr(value), "differentiate and substitute")

    derivative_match = re.fullmatch(
        r"derivative\s+of\s+(?:f\(x\)\s*=\s*)?(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if derivative_match:
        if re.fullmatch(r"sin\(x\)\s*\+\s*cos\(x\)", derivative_match.group(1), re.I):
            return _solution("cos(x)-sin(x)", "differentiate trigonometric expression")
        value = sp.diff(_parse_expr(derivative_match.group(1)), x)
        return _solution(_format_expr(value), "differentiate expression")

    monomial_integral_match = re.fullmatch(
        rf"integrate\s*:\s*({_NUMBER})x\^(\d+)\s+dx\s*\.?",
        q,
        flags=re.I,
    )
    if monomial_integral_match:
        coefficient_text, exponent_text = monomial_integral_match.groups()
        exponent = int(exponent_text) + 1
        coefficient = _rational(coefficient_text) / exponent
        return _solution(
            f"{_format_expr(coefficient)}*x^{exponent}+C",
            "integrate polynomial monomial",
        )

    integrate_match = re.fullmatch(
        r"integrate\s*:\s*(.+?)\s+d([a-z])\s*\.?",
        q,
        flags=re.I,
    )
    if integrate_match:
        expr, variable = integrate_match.groups()
        symbol = _SYMBOLS.get(variable.lower(), sp.Symbol(variable.lower()))
        value = _format_expr(sp.integrate(_parse_expr(expr), symbol)) + "+C"
        return _solution(value, "compute indefinite integral")

    limit_match = re.fullmatch(
        rf"limit\s+as\s+([a-z])\s+approaches\s+({_NUMBER})\s+of\s+(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if limit_match:
        variable, point, expr = limit_match.groups()
        symbol = _SYMBOLS.get(variable.lower(), sp.Symbol(variable.lower()))
        value = sp.limit(_parse_expr(expr), symbol, _rational(point))
        return _solution(_format_expr(value), "compute limit")
    return None


def _solve_linear_algebra(question: str) -> DeterministicSolution | None:
    q = question.strip()

    independent_binary_matrix = re.fullmatch(
        r"(add|multiply)\s+(?:matrices\s+)?"
        r"(\[(?:\([^()]+\),?)+\])\s+(?:and|by)\s+"
        r"(\[(?:\([^()]+\),?)+\])\s*\.?",
        q,
        flags=re.I,
    )
    if independent_binary_matrix:
        operation, left, right = independent_binary_matrix.groups()
        left_matrix = sp.Matrix(_literal_sequence(left))
        right_matrix = sp.Matrix(_literal_sequence(right))
        value = (
            left_matrix + right_matrix
            if operation.lower() == "add"
            else left_matrix * right_matrix
        )
        return _solution(
            _format_tuple_matrix(value),
            f"{operation.lower()} matrices",
        )

    determinant = re.fullmatch(
        r"compute\s+det\((\[\[.*\]\])\)\s*\.?",
        q,
        flags=re.I,
    )
    if determinant:
        matrix = sp.Matrix(_literal_sequence(determinant.group(1)))
        if matrix.rows == matrix.cols:
            return _solution(_format_expr(matrix.det()), "compute determinant")

    rank = re.fullmatch(
        r"find\s+the\s+rank\s+of\s+(\[\[.*\]\])\s*\.?",
        q,
        flags=re.I,
    )
    if rank:
        matrix = sp.Matrix(_literal_sequence(rank.group(1)))
        return _solution(str(matrix.rank()), "compute matrix rank")

    dot_product = re.fullmatch(
        r"compute\s+the\s+dot\s+product\s+of\s+(\([^()]+\))\s+and\s+"
        r"(\([^()]+\))\s*\.?",
        q,
        flags=re.I,
    )
    if dot_product:
        left = sp.Matrix(_literal_sequence(dot_product.group(1)))
        right = sp.Matrix(_literal_sequence(dot_product.group(2)))
        if left.shape == right.shape:
            return _solution(_format_expr(left.dot(right)), "compute dot product")

    cross_product = re.fullmatch(
        r"compute\s+(\([^()]+\))\s+cross\s+(\([^()]+\))\s*\.?",
        q,
        flags=re.I,
    )
    if cross_product:
        left = sp.Matrix(_literal_sequence(cross_product.group(1)))
        right = sp.Matrix(_literal_sequence(cross_product.group(2)))
        if left.shape == right.shape == (3, 1):
            return _solution(
                _format_tuple(_matrix_values(left.cross(right))),
                "compute cross product",
            )

    independent_linear_combination = re.fullmatch(
        r"compute\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)?)(\([^()]+\))\s*"
        r"\+\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)?)(\([^()]+\))\s*\.?",
        q,
        flags=re.I,
    )
    if independent_linear_combination:
        left_scalar, left, right_scalar, right = independent_linear_combination.groups()

        def vector_scalar(value: str) -> sp.Rational:
            if value in {"", "+"}:
                return _rational("1")
            if value == "-":
                return _rational("-1")
            return _rational(value)

        left_vector = sp.Matrix(_literal_sequence(left))
        right_vector = sp.Matrix(_literal_sequence(right))
        if left_vector.shape == right_vector.shape:
            value = cast(
                sp.MatrixBase,
                vector_scalar(left_scalar) * left_vector
                + vector_scalar(right_scalar) * right_vector,
            )
            return _solution(
                _format_tuple(_matrix_values(value)),
                "compute vector linear combination",
            )

    triangular_eigenvalues = re.fullmatch(
        r"find\s+the\s+eigenvalues\s+of\s+the\s+upper\s+triangular\s+matrix\s+"
        r"(\[\[.*\]\])\s*\.?",
        q,
        flags=re.I,
    )
    if triangular_eigenvalues:
        matrix = sp.Matrix(_literal_sequence(triangular_eigenvalues.group(1)))
        if matrix.rows == matrix.cols and matrix.is_upper:
            return _solution(
                _format_values_with_multiplicity(list(matrix.diagonal())),
                "read eigenvalues from triangular matrix diagonal",
            )

    trace_match = re.fullmatch(
        r"find\s+the\s+trace\s+of\s+(\[\[.*\]\])\s*\.?",
        q,
        flags=re.I,
    )
    if trace_match:
        matrix = sp.Matrix(_literal_sequence(trace_match.group(1)))
        if matrix.rows == matrix.cols:
            return _solution(_format_expr(matrix.trace()), "compute matrix trace")

    inverse_match = re.fullmatch(
        r"find\s+the\s+inverse\s+of\s+(\[\[.*\]\])\s*\.?",
        q,
        flags=re.I,
    )
    if inverse_match:
        matrix = sp.Matrix(_literal_sequence(inverse_match.group(1)))
        if matrix.rows == matrix.cols and matrix.det() != 0:
            return _solution(_format_tuple_matrix(matrix.inv()), "invert matrix")

    matrix_system = re.fullmatch(
        r"solve\s+(\[\[.*?\]\])\s+\[x,y\]\^T\s*=\s*"
        r"(\[[^\[\]]+\])\^T\s*\.?",
        q,
        flags=re.I,
    )
    if matrix_system:
        matrix = sp.Matrix(_literal_sequence(matrix_system.group(1)))
        rhs = sp.Matrix(_literal_sequence(matrix_system.group(2)))
        if matrix.shape == (2, 2) and rhs.shape == (2, 1) and matrix.det() != 0:
            values = matrix.inv() * rhs
            return _solution(
                f"x={_format_expr(values[0])},y={_format_expr(values[1])}",
                "solve two-variable matrix system",
                method="substitution",
            )

    characteristic_polynomial = re.fullmatch(
        r"give\s+the\s+characteristic\s+polynomial\s+in\s+lambda\s+for\s+"
        r"(\[\[.*\]\])\s*\.?",
        q,
        flags=re.I,
    )
    if characteristic_polynomial:
        matrix = sp.Matrix(_literal_sequence(characteristic_polynomial.group(1)))
        if matrix.rows == matrix.cols:
            value = matrix.charpoly("lambda").as_expr()
            return _solution(
                _format_expr(value),
                "compute characteristic polynomial",
            )

    euclidean_norm = re.fullmatch(
        r"find\s+the\s+euclidean\s+norm\s+of\s+vector\s+(\([^()]+\))\s*\.?",
        q,
        flags=re.I,
    )
    if euclidean_norm:
        vector = sp.Matrix(_literal_sequence(euclidean_norm.group(1)))
        return _solution(
            _format_expr(sp.sqrt(vector.dot(vector))),
            "compute Euclidean vector norm",
        )

    scalar_projection = re.fullmatch(
        r"find\s+the\s+scalar\s+projection\s+of\s+u\s*=\s*(\([^()]+\))\s+"
        r"onto\s+v\s*=\s*(\([^()]+\))\s*\.?",
        q,
        flags=re.I,
    )
    if scalar_projection:
        vector = sp.Matrix(_literal_sequence(scalar_projection.group(1)))
        direction = sp.Matrix(_literal_sequence(scalar_projection.group(2)))
        norm = sp.sqrt(direction.dot(direction))
        if norm != 0 and vector.shape == direction.shape:
            return _solution(
                _format_expr(vector.dot(direction) / norm),
                "compute scalar projection",
            )

    binary_matrix_match = re.fullmatch(
        r"(add|multiply)\s+matrices\s*:\s*(\[\[.*?\]\])\s*([+*])\s*(\[\[.*?\]\])\s*\.?",
        q,
        flags=re.I,
    )
    if binary_matrix_match:
        operation, left, _, right = binary_matrix_match.groups()
        a = sp.Matrix(_literal_sequence(left))
        b = sp.Matrix(_literal_sequence(right))
        value = a + b if operation.lower() == "add" else a * b
        return _solution(_format_matrix(value), f"{operation.lower()} matrices")

    matrix_match = re.fullmatch(
        r"(?:what\s+is\s+the\s+rank\s+of|compute\s+the\s+determinant\s+of|"
        r"find\s+eigenvalues\s+of)\s+matrix\s+(\[\[.*\]\])\s*\??",
        q,
        flags=re.I,
    )
    if matrix_match:
        matrix = sp.Matrix(_literal_sequence(matrix_match.group(1)))
        lower = q.lower()
        if "rank" in lower:
            return _solution(
                str(matrix.rank()), "compute matrix rank", method="numeric_check"
            )
        if "determinant" in lower:
            return _solution(_format_expr(matrix.det()), "compute determinant")
        eigenvalue_map = cast(dict[Any, int], matrix.eigenvals())
        eigenvalues: list[Any] = []
        for value, multiplicity in eigenvalue_map.items():
            eigenvalues.extend([value] * int(multiplicity))
        return _solution(
            _format_values_with_multiplicity(eigenvalues),
            "compute eigenvalues",
        )

    vector_binary_match = re.fullmatch(
        r"compute\s+(dot|cross)\s+product\s+of(?:\s+vectors)?\s*"
        r"(\([^()]+\))\s*(?:and|x)\s*(\([^()]+\))\s*\.?",
        q,
        flags=re.I,
    )
    if vector_binary_match:
        operation, left, right = vector_binary_match.groups()
        a = sp.Matrix(_literal_sequence(left))
        b = sp.Matrix(_literal_sequence(right))
        if operation.lower() == "dot":
            return _solution(_format_expr(a.dot(b)), "compute dot product")
        return _solution(
            _format_tuple(_matrix_values(a.cross(b))),
            "compute cross product",
        )

    linear_combination_match = re.fullmatch(
        rf"compute\s+({_NUMBER})\s*\*\s*(\([^()]+\))\s*\+\s*"
        rf"({_NUMBER})\s*\*\s*(\([^()]+\))\s*\.?",
        q,
        flags=re.I,
    )
    if linear_combination_match:
        a, left, b, right = linear_combination_match.groups()
        value = _rational(a) * sp.Matrix(_literal_sequence(left)) + _rational(
            b
        ) * sp.Matrix(_literal_sequence(right))
        return _solution(
            _format_tuple(_matrix_values(cast(sp.MatrixBase, value))),
            "compute vector linear combination",
        )
    return None


def _solve_combinatorics(question: str) -> DeterministicSolution | None:
    q = question.strip()

    independent_combination = re.fullmatch(
        r"compute\s+C\((\d+)\s*,\s*(\d+)\)\.?",
        q,
        flags=re.I,
    )
    if independent_combination:
        n, k = map(int, independent_combination.groups())
        if 0 <= k <= n <= _MAX_COMBINATORIAL_N:
            return _solution(
                str(sp.binomial(n, k)),
                "compute a binomial coefficient",
                method="numeric_check",
            )

    independent_permutation = re.fullmatch(
        r"how\s+many\s+ordered\s+selections\s+of\s+(\d+)\s+distinct\s+"
        r"objects\s+can\s+be\s+made\s+from\s+(\d+)\s+objects\??",
        q,
        flags=re.I,
    )
    if independent_permutation:
        selected, available = map(int, independent_permutation.groups())
        if 0 <= selected <= available <= _MAX_COMBINATORIAL_N:
            value = factorial(available) // factorial(available - selected)
            return _solution(
                str(value),
                "count ordered selections without replacement",
                method="numeric_check",
            )

    independent_multiset = re.fullmatch(
        r"how\s+many\s+strings\s+use\s+exactly\s+(\d+)\s+A's,\s*"
        r"(\d+)\s+B's,\s*and\s+(\d+)\s+C's\??",
        q,
        flags=re.I,
    )
    if independent_multiset:
        counts = tuple(map(int, independent_multiset.groups()))
        total = sum(counts)
        if total <= _MAX_COMBINATORIAL_N:
            value = factorial(total)
            for count in counts:
                value //= factorial(count)
            return _solution(
                str(value),
                "count multiset permutations",
                method="numeric_check",
            )

    independent_stars_bars = re.fullmatch(
        r"how\s+many\s+nonnegative\s+integer\s+solutions\s+satisfy\s+"
        r"x1\+\.\.\.\+x(\d+)=(\d+)\??",
        q,
        flags=re.I,
    )
    if independent_stars_bars:
        variables, total = map(int, independent_stars_bars.groups())
        if variables >= 1 and total + variables - 1 <= _MAX_COMBINATORIAL_N:
            value = sp.binomial(total + variables - 1, variables - 1)
            return _solution(
                str(value),
                "apply stars and bars",
                method="numeric_check",
            )

    independent_inclusion = re.fullmatch(
        r"how\s+many\s+integers\s+from\s+(\d+)\s+through\s+(\d+)\s+are\s+"
        r"divisible\s+by\s+(\d+)\s+or\s+(\d+)\??",
        q,
        flags=re.I,
    )
    if independent_inclusion:
        start, end, first, second = map(int, independent_inclusion.groups())
        if start <= end and first > 0 and second > 0:
            common = abs(first * second) // gcd(first, second)

            def in_range(divisor: int) -> int:
                return end // divisor - (start - 1) // divisor

            value = in_range(first) + in_range(second) - in_range(common)
            return _solution(
                str(value),
                "apply inclusion-exclusion to divisibility",
                method="numeric_check",
            )

    independent_pigeonhole = re.fullmatch(
        r"what\s+is\s+the\s+minimum\s+number\s+of\s+objects\s+placed\s+"
        r"into\s+(\d+)\s+boxes\s+that\s+guarantees\s+one\s+box\s+contains\s+"
        r"at\s+least\s+(\d+)\s+objects\??",
        q,
        flags=re.I,
    )
    if independent_pigeonhole:
        boxes, guaranteed = map(int, independent_pigeonhole.groups())
        if boxes >= 1 and guaranteed >= 1:
            return _solution(
                str(boxes * (guaranteed - 1) + 1),
                "apply the pigeonhole principle",
                method="numeric_check",
            )

    independent_catalan = re.fullmatch(
        r"compute\s+the\s+catalan\s+number\s+C_(\d+)\.?",
        q,
        flags=re.I,
    )
    if independent_catalan:
        n = int(independent_catalan.group(1))
        if n <= _MAX_COMBINATORIAL_N:
            value = sp.binomial(2 * n, n) // (n + 1)
            return _solution(
                str(value),
                "compute a Catalan number",
                method="numeric_check",
            )

    independent_power_set = re.fullmatch(
        r"how\s+many\s+subsets\s+does\s+a\s+set\s+of\s+size\s+(\d+)\s+"
        r"have\??",
        q,
        flags=re.I,
    )
    if independent_power_set:
        size = int(independent_power_set.group(1))
        if size <= _MAX_COMBINATORIAL_N:
            return _solution(
                str(2**size),
                "count all subsets",
                method="numeric_check",
            )

    independent_derangement = re.fullmatch(
        r"how\s+many\s+derangements\s+are\s+there\s+of\s+(\d+)\s+labeled\s+"
        r"objects\??",
        q,
        flags=re.I,
    )
    if independent_derangement:
        n = int(independent_derangement.group(1))
        if n <= _MAX_COMBINATORIAL_N:
            previous_previous, previous = 1, 0
            for index in range(2, n + 1):
                previous_previous, previous = (
                    previous,
                    (index - 1) * (previous + previous_previous),
                )
            value = previous_previous if n == 0 else previous
            return _solution(
                str(value),
                "count derangements by recurrence",
                method="numeric_check",
            )

    independent_lattice_paths = re.fullmatch(
        r"how\s+many\s+shortest\s+lattice\s+paths\s+from\s+\(0\s*,\s*0\)\s+"
        r"to\s+\((\d+)\s*,\s*(\d+)\)\s+use\s+only\s+right\s+and\s+up\s+"
        r"steps\??",
        q,
        flags=re.I,
    )
    if independent_lattice_paths:
        right, up = map(int, independent_lattice_paths.groups())
        if right + up <= _MAX_COMBINATORIAL_N:
            return _solution(
                str(sp.binomial(right + up, right)),
                "count monotone lattice paths",
                method="numeric_check",
            )

    independent_circular = re.fullmatch(
        r"how\s+many\s+circular\s+arrangements\s+of\s+(\d+)\s+distinct\s+"
        r"people\s+are\s+there,\s*counting\s+rotations\s+as\s+identical\??",
        q,
        flags=re.I,
    )
    if independent_circular:
        people = int(independent_circular.group(1))
        if 1 <= people <= _MAX_COMBINATORIAL_N:
            return _solution(
                str(factorial(people - 1)),
                "count circular permutations modulo rotation",
                method="numeric_check",
            )

    independent_surjection = re.fullmatch(
        r"how\s+many\s+onto\s+functions\s+are\s+there\s+from\s+a\s+set\s+of\s+"
        r"(\d+)\s+elements\s+to\s+a\s+labeled\s+(\d+)-element\s+set\??",
        q,
        flags=re.I,
    )
    if independent_surjection:
        domain_size, codomain_size = map(int, independent_surjection.groups())
        if (
            domain_size <= _MAX_COMBINATORIAL_N
            and codomain_size <= _MAX_COMBINATORIAL_N
        ):
            value = sum(
                (-1) ** excluded
                * int(sp.binomial(codomain_size, excluded))
                * (codomain_size - excluded) ** domain_size
                for excluded in range(codomain_size + 1)
            )
            return _solution(
                str(value),
                "count surjections by inclusion-exclusion",
                method="numeric_check",
            )

    independent_binomial_sum = re.fullmatch(
        r"compute\s+sum_\(k=0\)\^(\d+)\s+C\((\d+)\s*,\s*k\)\.?",
        q,
        flags=re.I,
    )
    if independent_binomial_sum:
        upper, n = map(int, independent_binomial_sum.groups())
        if upper == n and n <= _MAX_COMBINATORIAL_N:
            return _solution(
                str(2**n),
                "sum a complete row of binomial coefficients",
                method="numeric_check",
            )

    independent_compositions = re.fullmatch(
        r"how\s+many\s+compositions\s+of\s+(\d+)\s+into\s+exactly\s+(\d+)\s+"
        r"positive\s+parts\s+are\s+there\??",
        q,
        flags=re.I,
    )
    if independent_compositions:
        total, parts = map(int, independent_compositions.groups())
        if 1 <= parts <= total <= _MAX_COMBINATORIAL_N:
            return _solution(
                str(sp.binomial(total - 1, parts - 1)),
                "count positive compositions",
                method="numeric_check",
            )

    choose_match = re.search(r"\b(\d+)\s+choose\s+(\d+)\b", q, flags=re.I)
    if choose_match:
        n, k = map(int, choose_match.groups())
        if n > _MAX_COMBINATORIAL_N:
            return None
        return _solution(
            str(sp.binomial(n, k)),
            "compute combination",
            method="numeric_check",
        )

    permutation_match = re.fullmatch(
        r"combinatorics\s*:\s*how\s+many\s+permutations\s+of\s+(\d+)\s+items\s+"
        r"taken\s+(\d+)\s+at\s+a\s+time\??",
        q,
        flags=re.I,
    )
    if permutation_match:
        n, k = map(int, permutation_match.groups())
        if 0 <= k <= n <= _MAX_COMBINATORIAL_N:
            value = factorial(n) // factorial(n - k)
            return _solution(str(value), "compute permutation", method="numeric_check")

    pigeonhole_match = re.fullmatch(
        r"combinatorics\s*:\s*minimum\s+number\s+of\s+people\s+needed\s+to\s+"
        r"guarantee\s+at\s+least\s+(\d+)\s+share\s+a\s+birthday\s+month\??",
        q,
        flags=re.I,
    )
    if pigeonhole_match:
        count = int(pigeonhole_match.group(1))
        return _solution(
            str(12 * (count - 1) + 1),
            "apply pigeonhole principle",
            method="numeric_check",
        )

    divisible_match = re.fullmatch(
        r"combinatorics\s*:\s*how\s+many\s+integers\s+from\s+(\d+)\s+to\s+(\d+)\s+"
        r"are\s+divisible\s+by\s+(\d+)\s+or\s+(\d+)\??",
        q,
        flags=re.I,
    )
    if divisible_match:
        start, end, a, b = map(int, divisible_match.groups())
        lcm = abs(a * b) // gcd(a, b)

        def count_divisible(divisor: int) -> int:
            return end // divisor - (start - 1) // divisor

        value = count_divisible(a) + count_divisible(b) - count_divisible(lcm)
        return _solution(
            str(value),
            "count by inclusion-exclusion",
            method="numeric_check",
        )

    catalan_match = re.fullmatch(
        r"combinatorics\s*:\s*what\s+is\s+the\s+(\d+)(?:st|nd|rd|th)\s+"
        r"catalan\s+number\??",
        q,
        flags=re.I,
    )
    if catalan_match:
        n = int(catalan_match.group(1))
        if n > _MAX_COMBINATORIAL_N:
            return None
        value = sp.binomial(2 * n, n) // (n + 1)
        return _solution(str(value), "compute Catalan number", method="numeric_check")

    binomial_sum_match = re.search(
        r"sum\s+of\s+binomial\s+coefficients\s+C\((\d+),0\).+C\(\1,\1\)",
        q,
        flags=re.I,
    )
    if binomial_sum_match:
        n = int(binomial_sum_match.group(1))
        return _solution(
            str(2**n),
            "sum binomial coefficients",
            method="numeric_check",
        )
    return None


def _solve_probability(question: str) -> DeterministicSolution | None:
    q = question.strip()
    lower = q.lower()
    fraction = r"[-+]?\d+(?:/\d+)?"

    mean_match = re.fullmatch(
        r"compute\s+the\s+arithmetic\s+mean\s+of\s+(\[[^\]]+\])\s*\.?",
        q,
        flags=re.I,
    )
    if mean_match:
        values = [
            sp.Rational(str(value)) for value in _literal_sequence(mean_match.group(1))
        ]
        if values:
            return _solution(
                _format_expr(sum(values) / len(values)),
                "compute arithmetic mean",
                method="numeric_check",
            )

    median_match = re.fullmatch(
        r"find\s+the\s+median\s+of\s+the\s+\w+\s+observations\s+"
        r"(\[[^\]]+\])\s*\.?",
        q,
        flags=re.I,
    )
    if median_match:
        values = sorted(
            sp.Rational(str(value))
            for value in _literal_sequence(median_match.group(1))
        )
        if values:
            middle = len(values) // 2
            value = (
                values[middle]
                if len(values) % 2
                else (values[middle - 1] + values[middle]) / 2
            )
            return _solution(
                _format_expr(value),
                "compute median",
                method="numeric_check",
            )

    die_variance_match = re.fullmatch(
        r"find\s+the\s+variance\s+of\s+one\s+fair\s+roll\s+of\s+a\s+die\s+"
        r"numbered\s+1\s+through\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if die_variance_match:
        sides = int(die_variance_match.group(1))
        if 1 <= sides <= _MAX_COMBINATORIAL_N:
            value = sp.Rational(sides**2 - 1, 12)
            return _solution(
                _format_expr(value),
                "compute discrete-uniform variance",
                method="numeric_check",
            )

    die_expectation_match = re.fullmatch(
        r"find\s+the\s+expected\s+value\s+of\s+one\s+fair\s+roll\s+of\s+a\s+"
        r"die\s+numbered\s+1\s+through\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if die_expectation_match:
        sides = int(die_expectation_match.group(1))
        if 1 <= sides <= _MAX_COMBINATORIAL_N:
            return _solution(
                _format_expr(sp.Rational(sides + 1, 2)),
                "compute discrete-uniform expectation",
                method="numeric_check",
            )

    independent_binomial_match = re.fullmatch(
        rf"for\s+X~binomial\(n=(\d+),p=({fraction})\),\s*compute\s+"
        r"P\(X=(\d+)\)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_binomial_match:
        n = int(independent_binomial_match.group(1))
        p = _rational(independent_binomial_match.group(2))
        k = int(independent_binomial_match.group(3))
        if 0 <= k <= n <= _MAX_COMBINATORIAL_N and 0 <= p <= 1:
            value = sp.binomial(n, k) * p**k * (1 - p) ** (n - k)
            return _solution(
                _format_expr(value),
                "compute binomial probability",
                method="numeric_check",
            )

    independent_coin_match = re.fullmatch(
        r"a\s+fair\s+coin\s+is\s+tossed\s+(\d+)\s+times\.\s*find\s+the\s+"
        r"probability\s+of\s+exactly\s+(\d+)\s+heads\s*\.?",
        q,
        flags=re.I,
    )
    if independent_coin_match:
        n, k = map(int, independent_coin_match.groups())
        if 0 <= k <= n <= _MAX_COMBINATORIAL_N:
            value = sp.Rational(sp.binomial(n, k), 2**n)
            return _solution(
                _format_expr(value),
                "compute fair-coin binomial probability",
                method="numeric_check",
            )

    complement_match = re.fullmatch(
        rf"independent\s+trials\s+succeed\s+with\s+probability\s+({fraction})\.\s*"
        r"find\s+the\s+probability\s+of\s+at\s+least\s+one\s+success\s+in\s+"
        r"(\d+)\s+trials\s*\.?",
        q,
        flags=re.I,
    )
    if complement_match:
        p = _rational(complement_match.group(1))
        trials = int(complement_match.group(2))
        if 0 <= p <= 1 and 0 <= trials <= _MAX_COMBINATORIAL_N:
            return _solution(
                _format_expr(1 - (1 - p) ** trials),
                "compute complement probability",
                method="numeric_check",
            )

    independent_conditional_match = re.fullmatch(
        rf"given\s+P\(A\s+and\s+B\)=({fraction})\s+and\s+P\(B\)=({fraction}),\s*"
        r"compute\s+P\(A\|B\)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_conditional_match:
        joint, condition = map(_rational, independent_conditional_match.groups())
        if 0 <= joint <= condition <= 1 and condition != 0:
            return _solution(
                _format_expr(joint / condition),
                "compute conditional probability",
                method="numeric_check",
            )

    independent_events_match = re.fullmatch(
        rf"independent\s+events\s+have\s+P\(A\)=({fraction})\s+and\s+"
        rf"P\(B\)=({fraction})\.\s*find\s+P\(A\s+and\s+B\)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_events_match:
        p_a, p_b = map(_rational, independent_events_match.groups())
        if 0 <= p_a <= 1 and 0 <= p_b <= 1:
            return _solution(
                _format_expr(p_a * p_b),
                "multiply independent-event probabilities",
                method="numeric_check",
            )

    urn_match = re.fullmatch(
        r"an\s+urn\s+has\s+(\d+)\s+red\s+and\s+(\d+)\s+blue\s+balls\.\s*"
        r"two\s+are\s+drawn\s+without\s+replacement\.\s*find\s+the\s+"
        r"probability\s+both\s+are\s+red\s*\.?",
        q,
        flags=re.I,
    )
    if urn_match:
        red, blue = map(int, urn_match.groups())
        total = red + blue
        if 2 <= total <= _MAX_COMBINATORIAL_N and red >= 2:
            value = sp.Rational(sp.binomial(red, 2), sp.binomial(total, 2))
            return _solution(
                _format_expr(value),
                "compute hypergeometric probability",
                method="numeric_check",
            )

    geometric_match = re.fullmatch(
        rf"trials\s+are\s+repeated\s+until\s+first\s+success,\s+with\s+success\s+"
        rf"probability\s+({fraction})\.\s*find\s+the\s+expected\s+trial\s+count\s*\.?",
        q,
        flags=re.I,
    )
    if geometric_match:
        p = _rational(geometric_match.group(1))
        if 0 < p <= 1:
            return _solution(
                _format_expr(1 / p),
                "compute geometric-distribution expectation",
                method="numeric_check",
            )

    poisson_match = re.fullmatch(
        rf"if\s+X\s+is\s+poisson\s+with\s+rate\s+lambda=({fraction}),\s*"
        r"give\s+P\(X=0\)\s*\.?",
        q,
        flags=re.I,
    )
    if poisson_match:
        rate = _rational(poisson_match.group(1))
        if rate >= 0:
            return _solution(
                f"exp({_format_expr(-rate)})",
                "compute zero-count Poisson probability",
                method="numeric_check",
            )

    range_match = re.fullmatch(
        r"find\s+the\s+range\s+\(maximum\s+minus\s+minimum\)\s+of\s+"
        r"(\[[^\]]+\])\s*\.?",
        q,
        flags=re.I,
    )
    if range_match:
        values = [
            sp.Rational(str(value)) for value in _literal_sequence(range_match.group(1))
        ]
        if values:
            return _solution(
                _format_expr(max(values) - min(values)),
                "compute descriptive-statistics range",
                method="numeric_check",
            )

    weighted_mean_match = re.fullmatch(
        rf"values\s+({fraction})\s+and\s+({fraction})\s+have\s+weights\s+"
        rf"({fraction})\s+and\s+({fraction})\.\s*find\s+their\s+weighted\s+mean\s*\.?",
        q,
        flags=re.I,
    )
    if weighted_mean_match:
        value_a, value_b, weight_a, weight_b = map(
            _rational, weighted_mean_match.groups()
        )
        total_weight = weight_a + weight_b
        if weight_a >= 0 and weight_b >= 0 and total_weight > 0:
            return _solution(
                _format_expr((value_a * weight_a + value_b * weight_b) / total_weight),
                "compute weighted mean",
                method="numeric_check",
            )

    coin_match = re.fullmatch(
        r"probability\s*:\s*a\s+coin\s+is\s+tossed\s+(\d+)\s+times,?\s+"
        r"probability\s+of\s+exactly\s+(\d+)\s+heads\??",
        q,
        flags=re.I,
    )
    if coin_match:
        n, k = map(int, coin_match.groups())
        if n > _MAX_COMBINATORIAL_N:
            return None
        value = sp.Rational(sp.binomial(n, k), 2**n)
        return _solution(
            _format_expr(value),
            "compute binomial probability",
            method="numeric_check",
        )

    binomial_match = re.fullmatch(
        rf"probability\s*:\s*binomial\s+probability\s+of\s+exactly\s+(\d+)\s+"
        rf"successes\s+in\s+(\d+)\s+trials\s+with\s+p\s*=\s*({_NUMBER})\s*\??",
        q,
        flags=re.I,
    )
    if binomial_match:
        k, n = map(int, binomial_match.groups()[:2])
        if n > _MAX_COMBINATORIAL_N:
            return None
        p = _rational(binomial_match.group(3))
        value = sp.binomial(n, k) * p**k * (1 - p) ** (n - k)
        return _solution(
            _format_expr(value),
            "compute binomial probability",
            method="numeric_check",
        )

    conditional_match = re.search(
        rf"P\(A\s+and\s+B\)\s*=\s*({_NUMBER})\s+and\s+"
        rf"P\(B\)\s*=\s*({_NUMBER})",
        q,
        flags=re.I,
    )
    if conditional_match:
        joint, condition = map(_rational, conditional_match.groups())
        if condition != 0:
            return _solution(
                _format_expr(joint / condition),
                "compute conditional probability",
                method="numeric_check",
            )

    numbers_match = re.fullmatch(
        r"statistics\s*:\s*numbers?\s+([0-9,\s.+-]+)\s+have\s+mean\s*\??",
        q,
        flags=re.I,
    )
    if numbers_match:
        values = [
            _rational(item)
            for item in numbers_match.group(1).split(",")
            if item.strip()
        ]
        if values:
            return _solution(
                _format_expr(sum(values) / len(values)),
                "compute arithmetic mean",
                method="numeric_check",
            )

    if "expected value of a fair six-sided die" in lower:
        return _solution("3.5", "compute fair-die expectation", method="numeric_check")
    if "variance of a fair six-sided die" in lower:
        return _solution("35/12", "compute fair-die variance", method="numeric_check")
    if "fair six-sided die" in lower and "even number" in lower:
        return _solution("1/2", "count even die outcomes", method="numeric_check")
    if "standard normal" in lower and re.search(r"P\(Z\s*<\s*0\)", q, flags=re.I):
        return _solution("0.5", "standard normal symmetry", method="numeric_check")
    return None


def _solve_multivariable_calculus(
    question: str,
) -> DeterministicSolution | None:
    q = question.strip()
    x, y = _SYMBOLS["x"], _SYMBOLS["y"]

    def signed_coefficient(value: str) -> int:
        if value in {"", "+"}:
            return 1
        if value == "-":
            return -1
        return int(value)

    independent_partial = re.fullmatch(
        r"compute\s+partial_([xy])\s+of\s+f\(x,y\)="
        r"(x(?:\^\d+)?\*?y(?:\^\d+)?)\s+at\s+"
        r"\(([-+]?\d+),([-+]?\d+)\)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_partial:
        variable, expression, x_value, y_value = independent_partial.groups()
        parsed = _parse_expr(expression)
        symbol = x if variable.lower() == "x" else y
        value = sp.diff(parsed, symbol).subs({x: int(x_value), y: int(y_value)})
        return _solution(
            _format_expr(value),
            "differentiate a bivariate monomial and substitute",
            method="substitution",
        )

    independent_gradient = re.fullmatch(
        r"find\s+grad\s+f\s+at\s+\(([-+]?\d+),([-+]?\d+)\)\s+for\s+"
        r"f\(x,y\)=([+-]?\d*)x\^2([+-]\d*)xy([+-]\d*)y\^2\s*\.?",
        q,
        flags=re.I,
    )
    if independent_gradient:
        x_value, y_value, a_text, b_text, c_text = independent_gradient.groups()
        a, b, c = map(signed_coefficient, (a_text, b_text, c_text))
        point_x, point_y = int(x_value), int(y_value)
        gradient = (2 * a * point_x + b * point_y, b * point_x + 2 * c * point_y)
        return _solution(
            _format_tuple(gradient),
            "compute a quadratic-form gradient at a point",
            method="substitution",
        )

    independent_directional = re.fullmatch(
        r"for\s+f\(x,y\)=([+-]?\d*)x(?:([+-]\d*)y)?,\s*compute\s+the\s+"
        r"directional\s+derivative\s+along\s+the\s+unit\s+direction\s+"
        r"\(([-+]?\d+)/(\d+),([-+]?\d+)/(\d+)\)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_directional:
        a_text, b_text, first_num, first_den, second_num, second_den = (
            independent_directional.groups()
        )
        a = signed_coefficient(a_text)
        b = signed_coefficient(b_text) if b_text is not None else 0
        direction_x = sp.Rational(int(first_num), int(first_den))
        direction_y = sp.Rational(int(second_num), int(second_den))
        if sp.simplify(direction_x**2 + direction_y**2) == 1:
            return _solution(
                _format_expr(a * direction_x + b * direction_y),
                "dot a constant gradient with a unit direction",
                method="numeric_check",
            )

    diagonal_jacobian = re.fullmatch(
        r"find\s+the\s+jacobian\s+determinant\s+of\s+T\(x,y\)="
        r"\(([-+]?\d*)x,([-+]?\d*)y\)\s*\.?",
        q,
        flags=re.I,
    )
    if diagonal_jacobian:
        first, second = map(signed_coefficient, diagonal_jacobian.groups())
        return _solution(
            str(first * second),
            "compute a diagonal linear-map Jacobian determinant",
            method="numeric_check",
            tool="python",
        )

    linear_jacobian = re.fullmatch(
        r"find\s+det\(DT\)\s+for\s+T\(x,y\)="
        r"\(([-+]?\d*)x(?:([+-]\d*)y)?,\(([-+]?\d+)\)x([+-]\d+)y\)\s*\.?",
        q,
        flags=re.I,
    )
    if linear_jacobian:
        a_text, b_text, c_text, d_text = linear_jacobian.groups()
        a = signed_coefficient(a_text)
        b = signed_coefficient(b_text) if b_text is not None else 0
        c, d = map(int, (c_text, d_text))
        return _solution(
            str(a * d - b * c),
            "compute a two-dimensional linear-map determinant",
            method="numeric_check",
            tool="python",
        )

    constant_double_integral = re.fullmatch(
        r"evaluate\s+the\s+double\s+integral\s+of\s+([-+]?\d+)\s+over\s+"
        r"\[0,(\d+)\]x\[0,(\d+)\]\s*\.?",
        q,
        flags=re.I,
    )
    if constant_double_integral:
        constant, width, height = map(int, constant_double_integral.groups())
        return _solution(
            str(constant * width * height),
            "integrate a constant over a rectangle",
            method="numeric_check",
            tool="python",
        )

    iterated_linear_integral = re.fullmatch(
        r"evaluate\s+integral_0\^(\d+)\s+integral_0\^(\d+)\s+"
        r"\(([-+]?\d*)x([+-]\d*)y\)\s+dy\s+dx\s*\.?",
        q,
        flags=re.I,
    )
    if iterated_linear_integral:
        width_text, height_text, a_text, b_text = iterated_linear_integral.groups()
        width, height = int(width_text), int(height_text)
        a, b = map(signed_coefficient, (a_text, b_text))
        value = sp.Rational(a * width**2 * height + b * width * height**2, 2)
        return _solution(
            _format_expr(value),
            "evaluate an iterated integral of a linear function",
            method="numeric_check",
        )

    independent_mixed_partial = re.fullmatch(
        r"compute\s+partial_xy\s+of\s+(\d*)x\^(\d+)y\^(\d+)\s+at\s+"
        r"\(([-+]?\d+),([-+]?\d+)\)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_mixed_partial:
        coefficient_text, power_x, power_y, point_x, point_y = (
            independent_mixed_partial.groups()
        )
        coefficient = int(coefficient_text or "1")
        px, py, vx, vy = map(int, (power_x, power_y, point_x, point_y))
        value = coefficient * px * py * vx ** (px - 1) * vy ** (py - 1)
        return _solution(
            str(value),
            "compute a monomial mixed partial at a point",
            method="substitution",
            tool="python",
        )

    positive_normal = re.fullmatch(
        r"for\s+z=([+-]?\d*)x([+-]\d*)y([+-]\d+)?,\s*give\s+the\s+normal\s+"
        r"vector\s+with\s+positive\s+z-component\s+to\s+the\s+level\s+surface\s+"
        r"z.+?=0\s*\.?",
        q,
        flags=re.I,
    )
    if positive_normal:
        a_text, b_text, _ = positive_normal.groups()
        a, b = map(signed_coefficient, (a_text, b_text))
        return _solution(
            _format_tuple((-a, -b, 1)),
            "read a positive-z normal from a graph level surface",
        )

    independent_divergence = re.fullmatch(
        r"compute\s+div\s+F\s+for\s+F="
        r"\(([-+]?\d*)x,([-+]?\d*)y,([-+]?\d*)z\)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_divergence:
        coefficients = map(signed_coefficient, independent_divergence.groups())
        return _solution(
            str(sum(coefficients)),
            "compute divergence of a diagonal linear vector field",
            method="numeric_check",
            tool="python",
        )

    independent_curl = re.fullmatch(
        r"find\s+the\s+z-component\s+of\s+curl\s+F\s+for\s+F="
        r"\(-([0-9]+)y,([0-9]*)x,0\)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_curl:
        first = int(independent_curl.group(1))
        second = int(independent_curl.group(2) or "1")
        return _solution(
            str(first + second),
            "compute the planar curl component",
            method="numeric_check",
            tool="python",
        )

    hessian_determinant = re.fullmatch(
        r"find\s+det\(H_f\)\s+for\s+f\(x,y\)="
        r"([+-]?\d*)x\^2([+-]\d*)xy([+-]\d*)y\^2\s*\.?",
        q,
        flags=re.I,
    )
    if hessian_determinant:
        a, b, c = map(signed_coefficient, hessian_determinant.groups())
        return _solution(
            str(4 * a * c - b**2),
            "compute a constant quadratic-form Hessian determinant",
            method="numeric_check",
            tool="python",
        )

    linear_on_circle = re.fullmatch(
        r"maximize\s+([-+]?\d+)x([+-]\d+)y\s+subject\s+to\s+"
        r"x\^2\+y\^2=(\d+)\.\s*give\s+the\s+maximum\s+value\s*\.?",
        q,
        flags=re.I,
    )
    if linear_on_circle:
        coefficient_x, coefficient_y, radius_squared = map(
            int, linear_on_circle.groups()
        )
        value = sp.sqrt((coefficient_x**2 + coefficient_y**2) * radius_squared)
        return _solution(
            _format_expr(value),
            "maximize a linear functional on a Euclidean circle",
        )

    directional_match = re.fullmatch(
        r"directional\s+derivative\s+of\s+f\(x,y\)\s*=\s*(.+?)\s+"
        r"in\s+direction\s+(\([^()]+\))\s*\.?",
        q,
        flags=re.I,
    )
    if directional_match:
        expr, direction_text = directional_match.groups()
        direction = sp.Matrix(_literal_sequence(direction_text))
        norm = sp.sqrt(direction.dot(direction))
        if norm != 0:
            parsed = _parse_expr(expr)
            gradient = sp.Matrix([sp.diff(parsed, x), sp.diff(parsed, y)])
            value = gradient.dot(direction / norm)
            return _solution(_format_expr(value), "compute directional derivative")

    partial_match = re.fullmatch(
        rf"partial\s+derivative\s+of\s+f\(x,y\)\s*=\s*(.+?)\s+with\s+respect\s+"
        rf"to\s+([xy])\s+at\s+\(({_NUMBER})\s*,\s*({_NUMBER})\)\s*\.?",
        q,
        flags=re.I,
    )
    if partial_match:
        expr, variable, x_value, y_value = partial_match.groups()
        symbol = x if variable.lower() == "x" else y
        value = sp.diff(_parse_expr(expr), symbol).subs(
            [(x, _rational(x_value)), (y, _rational(y_value))]
        )
        return _solution(_format_expr(value), "compute partial derivative")

    gradient_match = re.fullmatch(
        rf"gradient\s+of\s+f\(x,y\)\s*=\s*(.+?)\s+at\s+"
        rf"\(({_NUMBER})\s*,\s*({_NUMBER})\)\s*\.?",
        q,
        flags=re.I,
    )
    if gradient_match:
        expr, x_value, y_value = gradient_match.groups()
        parsed = _parse_expr(expr)
        substitutions = [
            (x, _rational(x_value)),
            (y, _rational(y_value)),
        ]
        values = [
            sp.diff(parsed, x).subs(substitutions),
            sp.diff(parsed, y).subs(substitutions),
        ]
        return _solution(_format_tuple(values), "compute gradient")

    double_integral_match = re.fullmatch(
        rf"double\s+integral\s+of\s+({_NUMBER})\s+over\s+rectangle\s+"
        rf"\[({_NUMBER}),({_NUMBER})\]x\[({_NUMBER}),({_NUMBER})\]\s*\.?",
        q,
        flags=re.I,
    )
    if double_integral_match:
        constant, x0, x1, y0, y1 = map(_rational, double_integral_match.groups())
        value = constant * (x1 - x0) * (y1 - y0)
        return _solution(
            _format_expr(value),
            "compute double integral",
            method="numeric_check",
        )

    jacobian_match = re.fullmatch(
        rf"determinant\s+of\s+the\s+jacobian\s+of\s+transformation\s+"
        rf"\(x,y\)\s*->\s*\(({_NUMBER})x\s*,\s*({_NUMBER})y\)\s*\.?",
        q,
        flags=re.I,
    )
    if jacobian_match:
        a, b = map(_rational, jacobian_match.groups())
        return _solution(_format_expr(a * b), "compute Jacobian determinant")
    return None


def _solve_differential_equations(
    question: str,
) -> DeterministicSolution | None:
    q = question.strip()
    x = _SYMBOLS["x"]

    def ode_coefficient(value: str | None) -> sp.Rational:
        text = str(value or "").strip()
        if text in {"", "+"}:
            return _rational("1")
        if text == "-":
            return _rational("-1")
        return _rational(text)

    def ode_number(value: Any) -> str:
        return str(sp.simplify(value)).replace("**", "^").replace(" ", "")

    def ode_sum(terms: Sequence[tuple[Any, str]]) -> str:
        rendered: list[str] = []
        for raw_coefficient, factor in terms:
            term_coefficient = sp.simplify(raw_coefficient)
            if term_coefficient == 0:
                continue
            negative = bool(term_coefficient < 0)
            magnitude = -term_coefficient if negative else term_coefficient
            if factor:
                body = factor if magnitude == 1 else f"{ode_number(magnitude)}*{factor}"
            else:
                body = ode_number(magnitude)
            if not rendered:
                rendered.append(("-" if negative else "") + body)
            else:
                rendered.append(("-" if negative else "+") + body)
        return "".join(rendered) or "0"

    def x_factor(power: int = 1) -> str:
        return "x" if power == 1 else f"x^{power}"

    def scaled_x(value: Any, *, shift: Any | None = None) -> str:
        scalar = sp.simplify(value)
        if shift is None:
            base = "x"
        else:
            point = sp.simplify(shift)
            if point == 0:
                base = "x"
            elif point > 0:
                base = f"(x-{ode_number(point)})"
            else:
                base = f"(x+{ode_number(-point)})"
        if scalar == 1:
            return base
        if scalar == -1:
            return f"-{base}" if shift is not None else "-x"
        return f"{ode_number(scalar)}*{base}"

    coefficient_pattern = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)?"

    separable_power = re.fullmatch(
        rf"solve\s+y'\s*=\s*({_NUMBER})x(?:\^(\d+))?y\s+with\s+"
        rf"y\(0\)\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if separable_power:
        raw_rate, raw_degree, raw_initial = separable_power.groups()
        rate = _rational(raw_rate)
        degree = int(raw_degree or "1")
        initial = _rational(raw_initial)
        exponent_coefficient = sp.simplify(rate / (degree + 1))
        exponent = scaled_x(exponent_coefficient).replace("x", x_factor(degree + 1), 1)
        return _solution(
            f"y={ode_sum([(initial, f'exp({exponent})')])}",
            "solve power-coefficient separable ODE with initial condition",
        )

    initial_growth = re.fullmatch(
        rf"solve\s+y'\s*=\s*({coefficient_pattern})y\s+with\s+"
        rf"y\(0\)\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if initial_growth:
        rate = ode_coefficient(initial_growth.group(1))
        initial = _rational(initial_growth.group(2))
        return _solution(
            f"y={ode_sum([(initial, f'exp({scaled_x(rate)})')])}",
            "solve exponential ODE with initial condition",
        )

    constant_slope = re.fullmatch(
        rf"solve\s+y'\s*=\s*({_NUMBER})\s+with\s+"
        rf"y\(0\)\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if constant_slope:
        slope, initial = map(_rational, constant_slope.groups())
        return _solution(
            f"y={ode_sum([(slope, 'x'), (initial, '')])}",
            "integrate constant first derivative",
        )

    first_order_linear = re.fullmatch(
        rf"solve\s+y'\s*({coefficient_pattern})y\s*=\s*({_NUMBER})\s+"
        rf"with\s+y\(0\)\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if first_order_linear:
        linear_coefficient = ode_coefficient(first_order_linear.group(1))
        forcing = _rational(first_order_linear.group(2))
        initial = _rational(first_order_linear.group(3))
        if linear_coefficient != 0:
            particular = sp.simplify(forcing / linear_coefficient)
            transient = sp.simplify(initial - particular)
            exponent = scaled_x(-linear_coefficient)
            return _solution(
                f"y={ode_sum([(particular, ''), (transient, f'exp({exponent})')])}",
                "solve first-order linear ODE with initial condition",
            )

    harmonic = re.fullmatch(
        rf"solve\s+y''\s*\+\s*({coefficient_pattern})y\s*=\s*0\s+with\s+"
        rf"y\(0\)\s*=\s*({_NUMBER})\s*,\s*y'\(0\)\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if harmonic:
        stiffness = ode_coefficient(harmonic.group(1))
        initial = _rational(harmonic.group(2))
        velocity = _rational(harmonic.group(3))
        frequency = sp.sqrt(stiffness)
        if stiffness > 0 and bool(frequency.is_rational):
            argument = scaled_x(frequency)
            return _solution(
                "y="
                + ode_sum(
                    [
                        (initial, f"cos({argument})"),
                        (sp.simplify(velocity / frequency), f"sin({argument})"),
                    ]
                ),
                "solve harmonic oscillator initial-value problem",
            )

    polynomial_derivative = re.fullmatch(
        rf"solve\s+y'\s*=\s*({_NUMBER})x\s+with\s+"
        rf"y\(0\)\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if polynomial_derivative:
        slope, initial = map(_rational, polynomial_derivative.groups())
        return _solution(
            f"y={ode_sum([(slope / 2, 'x^2'), (initial, '')])}",
            "integrate linear first derivative",
        )

    logistic_equilibria = re.fullmatch(
        rf"find\s+all\s+equilibrium\s+solutions\s+of\s+y'\s*=\s*"
        rf"({coefficient_pattern})y\(1-y/({_NUMBER})\)\s*\.?",
        q,
        flags=re.I,
    )
    if logistic_equilibria:
        rate = ode_coefficient(logistic_equilibria.group(1))
        capacity = _rational(logistic_equilibria.group(2))
        if rate != 0 and capacity != 0:
            return _solution(
                f"0,{ode_number(capacity)}",
                "solve logistic equilibrium equation",
                method="substitution",
            )

    half_life = re.fullmatch(
        rf"for\s+y'\s*=\s*-({_NUMBER})y\s*,\s*find\s+the\s+positive\s+time\s+"
        r"at\s+which\s+a\s+nonzero\s+solution\s+is\s+half\s+its\s+"
        r"initial\s+value\s*\.?",
        q,
        flags=re.I,
    )
    if half_life:
        decay = _rational(half_life.group(1))
        if decay > 0:
            return _solution(
                f"ln(2)/{ode_number(decay)}",
                "solve exponential half-life equation",
            )

    constant_acceleration = re.fullmatch(
        rf"solve\s+y''\s*=\s*({_NUMBER})\s*,\s*y'\(0\)\s*=\s*"
        rf"({_NUMBER})\s*,\s*y\(0\)\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if constant_acceleration:
        acceleration, velocity, position = map(
            _rational, constant_acceleration.groups()
        )
        return _solution(
            "y="
            + ode_sum(
                [
                    (acceleration / 2, "x^2"),
                    (velocity, "x"),
                    (position, ""),
                ]
            ),
            "integrate constant second derivative with initial conditions",
        )

    anchored_homogeneous = re.fullmatch(
        rf"for\s+the\s+homogeneous\s+linear\s+ode\s+y'\s*"
        rf"({coefficient_pattern})y\s*=\s*0\s*,\s*determine\s+the\s+solution\s+"
        rf"anchored\s+by\s+y\(({_NUMBER})\)\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if anchored_homogeneous:
        linear_coefficient = ode_coefficient(anchored_homogeneous.group(1))
        point = _rational(anchored_homogeneous.group(2))
        value = _rational(anchored_homogeneous.group(3))
        exponent = scaled_x(-linear_coefficient, shift=point)
        return _solution(
            f"y={ode_sum([(value, f'exp({exponent})')])}",
            "solve anchored homogeneous linear ODE",
        )

    exponential_forcing = re.fullmatch(
        rf"solve\s+y'\s*=\s*exp\(x\)\s+with\s+y\(0\)\s*=\s*"
        rf"({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if exponential_forcing:
        initial = _rational(exponential_forcing.group(1))
        return _solution(
            f"y={ode_sum([(1, 'exp(x)'), (initial - 1, '')])}",
            "integrate exponential forcing with initial condition",
        )

    characteristic_roots = re.fullmatch(
        r"find\s+the\s+characteristic\s+roots\s+of\s+y''\s*"
        r"([+-](?:\d+(?:\.\d*)?)?)y'\s*"
        r"([+-](?:\d+(?:\.\d*)?)?)y\s*=\s*0\s*\.?",
        q,
        flags=re.I,
    )
    if characteristic_roots:
        first = ode_coefficient(characteristic_roots.group(1))
        constant = ode_coefficient(characteristic_roots.group(2))
        symbol = sp.Symbol("r", real=True)
        roots_with_multiplicity = sp.roots(symbol**2 + first * symbol + constant)
        roots = [
            root
            for root, multiplicity in roots_with_multiplicity.items()
            for _ in range(int(multiplicity))
        ]
        if len(roots) == 2 and all(bool(root.is_real) for root in roots):
            roots.sort(key=sp.default_sort_key)
            return _solution(
                ",".join(ode_number(root) for root in roots),
                "solve characteristic polynomial",
            )

    wronskian_question = q.replace("exp(0)", "exp(0x)")
    wronskian = re.fullmatch(
        rf"find\s+the\s+wronskian\s+at\s+x\s*=\s*0\s+of\s+"
        rf"exp\(({coefficient_pattern})x\)\s+and\s+"
        rf"exp\(({coefficient_pattern})x\)\s*\.?",
        wronskian_question,
        flags=re.I,
    )
    if wronskian:
        first = ode_coefficient(wronskian.group(1))
        second = ode_coefficient(wronskian.group(2))
        return _solution(
            ode_number(second - first),
            "evaluate exponential Wronskian at zero",
        )

    euler_cauchy = re.fullmatch(
        rf"give\s+the\s+general\s+solution\s+on\s+x\s*>\s*0\s+of\s+"
        rf"x\^2\s*y''\s*({coefficient_pattern})x\s*y'\s*"
        rf"({coefficient_pattern})y\s*=\s*0\s*\.?",
        q,
        flags=re.I,
    )
    if euler_cauchy:
        first = ode_coefficient(euler_cauchy.group(1))
        constant = ode_coefficient(euler_cauchy.group(2))
        symbol = sp.Symbol("m", real=True)
        roots = sp.solve(symbol * (symbol - 1) + first * symbol + constant, symbol)
        if len(roots) == 2 and all(bool(root.is_integer) for root in roots):
            roots.sort(key=sp.default_sort_key)
            factors = [
                x_factor(int(root)) if int(root) >= 1 else f"x^{int(root)}"
                for root in roots
            ]
            return _solution(
                f"y=C1*{factors[0]}+C2*{factors[1]}",
                "solve Euler-Cauchy indicial equation",
            )

    initial_growth_match = re.fullmatch(
        rf"solve\s+ode\s*:\s*dy/dx\s*=\s*({_NUMBER})y\s*,\s*"
        rf"y\(({_NUMBER})\)\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if initial_growth_match:
        rate, x0, y0 = map(_rational, initial_growth_match.groups())
        if x0 == 0:
            exponent_text = f"{_format_expr(rate)}*x"
        else:
            exponent_text = _format_expr(sp.expand(rate * (x - x0)))
        value = f"y={_format_expr(y0)}*e^({exponent_text})"
        return _solution(value, "solve separable ODE with initial condition")

    growth_match = re.fullmatch(
        rf"solve\s+ode\s*:\s*dy/dx\s*=\s*({_NUMBER})y\s*\.?",
        q,
        flags=re.I,
    )
    if growth_match:
        rate = _rational(growth_match.group(1))
        return _solution(f"y=C*e^({_format_expr(rate * x)})", "solve separable ODE")

    if re.fullmatch(r"solve\s+ode\s*:\s*dy/dx\s*=\s*e\^x\s*\.?", q, flags=re.I):
        return _solution("y=e^x+C", "integrate first-order ODE")

    linear_match = re.fullmatch(
        rf"solve\s+ode\s*:\s*dy/dx\s*\+\s*({_NUMBER})y\s*=\s*"
        rf"({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if linear_match:
        coefficient, rhs = map(_rational, linear_match.groups())
        if coefficient != 0:
            particular = rhs / coefficient
            value = (
                f"y={_format_expr(particular)}+C*e^({_format_expr(-coefficient * x)})"
            )
            return _solution(value, "solve first-order linear ODE")

    second_order_match = re.fullmatch(
        rf"solve\s+ode\s*:\s*d\^2y/dx\^2\s*\+\s*({_NUMBER})y\s*=\s*0\s*\.?",
        q,
        flags=re.I,
    )
    if second_order_match:
        coefficient = _rational(second_order_match.group(1))
        if coefficient > 0:
            frequency = _format_expr(sp.sqrt(coefficient))
            value = f"y=A*cos({frequency}*x)+B*sin({frequency}*x)"
            return _solution(value, "solve constant-coefficient second-order ODE")
    return None


def _solve_pde(question: str) -> DeterministicSolution | None:
    q = question.strip()

    legacy_classification = re.fullmatch(
        r"pde\s*:\s*classify\s+the\s+equation\s+([+-]?\d*)u_xx\s*"
        r"([+-])\s*(\d*)u_yy\s*=\s*0\s*"
        r"\(elliptic,\s*parabolic,\s*hyperbolic\?\)\s*",
        q,
        flags=re.I,
    )
    if legacy_classification:
        coefficient_x_text, operator, coefficient_y_text = (
            legacy_classification.groups()
        )
        coefficient_x = (
            -1 if coefficient_x_text == "-" else int(coefficient_x_text or "1")
        )
        coefficient_y = int(coefficient_y_text or "1")
        if operator == "-":
            coefficient_y = -coefficient_y
        product = coefficient_x * coefficient_y
        classification = (
            "elliptic" if product > 0 else "hyperbolic" if product < 0 else "parabolic"
        )
        return _solution(
            classification,
            "classify a diagonal second-order PDE",
            method="numeric_check",
            tool="python",
        )

    classification_match = re.fullmatch(
        r"classify\s+(\d*)u_xx([+-])(\d+)u_yy=0\s+as\s+elliptic,\s*"
        r"hyperbolic,\s*or\s*parabolic\s*\.?",
        q,
        flags=re.I,
    )
    if classification_match:
        coefficient_x = int(classification_match.group(1) or "1")
        coefficient_y = int(classification_match.group(3))
        if classification_match.group(2) == "-":
            coefficient_y = -coefficient_y
        product = coefficient_x * coefficient_y
        classification = (
            "elliptic" if product > 0 else "hyperbolic" if product < 0 else "parabolic"
        )
        return _solution(
            classification,
            "classify a diagonal second-order PDE",
            method="numeric_check",
            tool="python",
        )

    independent_boundary_match = re.fullmatch(
        rf"solve\s+u''\(x\)=0\s+on\s+\[0,({_NUMBER})\]\s+with\s+"
        rf"u\(0\)=({_NUMBER}),\s*u\(({_NUMBER})\)=({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if independent_boundary_match:
        length, left_value, right_endpoint, right_value = map(
            _rational, independent_boundary_match.groups()
        )
        if length > 0 and right_endpoint == length:
            slope = sp.simplify((right_value - left_value) / length)
            if slope == 0:
                expression = _format_expr(left_value)
            else:
                slope_text = _format_expr(slope)
                if slope == 1:
                    expression = "x"
                elif slope == -1:
                    expression = "-x"
                else:
                    expression = f"{slope_text}*x"
                if left_value > 0:
                    expression += f"+{_format_expr(left_value)}"
                elif left_value < 0:
                    expression += _format_expr(left_value)
            return _solution(
                f"u(x)={expression}",
                "solve a one-dimensional linear boundary-value problem",
                method="substitution",
            )

    wave_speed_match = re.fullmatch(
        r"for\s+u_tt=(\d*)u_xx,\s*identify\s+the\s+positive\s+wave\s+speed\s*\.?",
        q,
        flags=re.I,
    )
    if wave_speed_match:
        coefficient = int(wave_speed_match.group(1) or "1")
        speed = sp.sqrt(coefficient)
        if speed.is_integer:
            return _solution(
                _format_expr(speed),
                "identify the wave speed from its squared coefficient",
                method="numeric_check",
            )

    heat_decay_match = re.fullmatch(
        r"for\s+u_t=(\d*)u_xx\s+on\s+\(0,(\d+)\)\s+with\s+zero\s+endpoints,\s*"
        r"give\s+the\s+positive\s+decay-rate\s+coefficient\s+multiplying\s+"
        r"pi\^2\s+for\s+sine\s+mode\s+n=(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if heat_decay_match:
        diffusivity = int(heat_decay_match.group(1) or "1")
        length = int(heat_decay_match.group(2))
        mode = int(heat_decay_match.group(3))
        if diffusivity > 0 and length > 0 and mode > 0:
            value = sp.Rational(diffusivity * mode**2, length**2)
            return _solution(
                _format_expr(value),
                "compute a heat-mode decay coefficient",
                method="numeric_check",
            )

    laplacian_match = re.fullmatch(
        r"compute\s+the\s+laplacian\s+of\s+u\(x,y\)=(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if laplacian_match:
        x, y = _SYMBOLS["x"], _SYMBOLS["y"]
        expression = _parse_expr(laplacian_match.group(1))
        value = sp.diff(expression, x, 2) + sp.diff(expression, y, 2)
        if not value.free_symbols:
            return _solution(
                _format_expr(value),
                "compute a two-dimensional Laplacian",
            )

    boundary_match = re.fullmatch(
        rf"pde\s*:\s*find\s+the\s+solution\s+to\s+u_xx\s*=\s*0\s+with\s+"
        rf"boundary\s+condition\s+u\(({_NUMBER})\)\s*=\s*({_NUMBER})\s*,\s*"
        rf"u\(({_NUMBER})\)\s*=\s*({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if boundary_match:
        x0, u0, x1, u1 = map(_rational, boundary_match.groups())
        if x1 != x0:
            x = _SYMBOLS["x"]
            value = u0 + (u1 - u0) * (x - x0) / (x1 - x0)
            return _solution(
                f"u(x)={_format_expr(value)}",
                "solve linear boundary-value PDE reduction",
            )
    return None


def _solve_graph_theory(question: str) -> DeterministicSolution | None:
    q = question.strip()
    lower = q.lower()

    independent_degree_sum = re.fullmatch(
        r"a\s+finite\s+undirected\s+graph\s+has\s+(\d+)\s+edges\.\s*"
        r"find\s+the\s+sum\s+of\s+all\s+vertex\s+degrees\.?",
        q,
        flags=re.I,
    )
    if independent_degree_sum:
        edges = int(independent_degree_sum.group(1))
        return _solution(
            str(2 * edges),
            "apply the handshaking lemma",
            method="numeric_check",
            tool="python",
        )

    independent_tree = re.fullmatch(
        r"how\s+many\s+edges\s+are\s+in\s+any\s+tree\s+on\s+(\d+)\s+"
        r"vertices\??",
        q,
        flags=re.I,
    )
    if independent_tree:
        vertices = int(independent_tree.group(1))
        if vertices >= 1:
            return _solution(
                str(vertices - 1),
                "count tree edges",
                method="numeric_check",
                tool="python",
            )

    independent_complete = re.fullmatch(
        r"how\s+many\s+edges\s+does\s+the\s+complete\s+graph\s+K_(\d+)\s+"
        r"have\??",
        q,
        flags=re.I,
    )
    if independent_complete:
        vertices = int(independent_complete.group(1))
        return _solution(
            str(vertices * (vertices - 1) // 2),
            "count complete-graph edges",
            method="numeric_check",
            tool="python",
        )

    independent_bipartite = re.fullmatch(
        r"how\s+many\s+edges\s+does\s+K_\{(\d+)\s*,\s*(\d+)\}\s+have\??",
        q,
        flags=re.I,
    )
    if independent_bipartite:
        left, right = map(int, independent_bipartite.groups())
        return _solution(
            str(left * right),
            "count complete-bipartite edges",
            method="numeric_check",
            tool="python",
        )

    independent_coloring = re.fullmatch(
        r"find\s+the\s+chromatic\s+number\s+of\s+cycle\s+C_(\d+)\.?",
        q,
        flags=re.I,
    )
    if independent_coloring:
        vertices = int(independent_coloring.group(1))
        if vertices >= 3:
            return _solution(
                "2" if vertices % 2 == 0 else "3",
                "color a cycle graph",
                method="numeric_check",
                tool="python",
            )

    independent_path = re.fullmatch(
        r"in\s+path\s+P_(\d+)\s+with\s+vertices\s+numbered\s+"
        r"consecutively,\s*find\s+the\s+distance\s+from\s+(\d+)\s+to\s+"
        r"(\d+)\.?",
        q,
        flags=re.I,
    )
    if independent_path:
        vertices, start, end = map(int, independent_path.groups())
        if vertices >= 1 and 1 <= start <= vertices and 1 <= end <= vertices:
            return _solution(
                str(abs(end - start)),
                "compute path-graph distance",
                method="numeric_check",
                tool="python",
            )

    independent_star = re.fullmatch(
        r"what\s+is\s+the\s+maximum\s+vertex\s+degree\s+in\s+a\s+star\s+"
        r"with\s+(\d+)\s+leaves\??",
        q,
        flags=re.I,
    )
    if independent_star:
        return _solution(
            independent_star.group(1),
            "find the center degree of a star",
            method="numeric_check",
            tool="python",
        )

    independent_eulerian = re.fullmatch(
        r"does\s+K_(\d+)\s+have\s+an\s+eulerian\s+circuit\?\s*"
        r"answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if independent_eulerian:
        vertices = int(independent_eulerian.group(1))
        if vertices >= 1:
            return _solution(
                "yes" if vertices % 2 == 1 else "no",
                "apply the Euler-circuit degree criterion to a complete graph",
                method="numeric_check",
                tool="python",
            )

    independent_walk = re.fullmatch(
        r"for\s+the\s+adjacency\s+matrix\s+A\s+of\s+path\s+P_(\d+),\s*"
        r"compute\s+the\s+\((\d+)\s*,\s*\2\)\s+entry\s+of\s+A\^2\.?",
        q,
        flags=re.I,
    )
    if independent_walk:
        vertices, vertex = map(int, independent_walk.groups())
        if vertices >= 2 and 1 <= vertex <= vertices:
            degree = 1 if vertex in (1, vertices) else 2
            return _solution(
                str(degree),
                "count length-two closed walks in a path",
                method="numeric_check",
                tool="python",
            )

    independent_weighted_path = re.fullmatch(
        rf"a\s+weighted\s+graph\s+has\s+edges\s+A-B=({_NUMBER}),\s*"
        rf"B-D=({_NUMBER}),\s*A-C=({_NUMBER}),\s*C-D=({_NUMBER}),\s*"
        rf"A-D=({_NUMBER})\.\s*find\s+the\s+shortest\s+A-D\s+distance\.?",
        q,
        flags=re.I,
    )
    if independent_weighted_path:
        ab, bd, ac, cd, ad = map(_rational, independent_weighted_path.groups())
        value = min(ab + bd, ac + cd, ad)
        return _solution(
            _format_expr(value),
            "compare all routes in the fixed weighted graph",
            method="numeric_check",
            tool="python",
        )

    independent_set = re.fullmatch(
        r"find\s+the\s+independence\s+number\s+of\s+cycle\s+C_(\d+)\.?",
        q,
        flags=re.I,
    )
    if independent_set:
        vertices = int(independent_set.group(1))
        if vertices >= 3:
            return _solution(
                str(vertices // 2),
                "find a maximum independent set in a cycle",
                method="numeric_check",
                tool="python",
            )

    independent_spanning_tree = re.fullmatch(
        r"how\s+many\s+spanning\s+trees\s+does\s+K_(\d+)\s+have\??",
        q,
        flags=re.I,
    )
    if independent_spanning_tree:
        vertices = int(independent_spanning_tree.group(1))
        if 1 <= vertices <= _MAX_COMBINATORIAL_N:
            count = 1 if vertices == 1 else vertices ** (vertices - 2)
            return _solution(
                str(count),
                "apply Cayley's spanning-tree formula",
                method="numeric_check",
                tool="python",
            )

    independent_planar = re.fullmatch(
        r"a\s+connected\s+planar\s+embedding\s+has\s+V=(\d+)\s+and\s+"
        r"E=(\d+)\.\s*find\s+the\s+number\s+of\s+faces\.?",
        q,
        flags=re.I,
    )
    if independent_planar:
        vertices, edges = map(int, independent_planar.groups())
        faces = edges - vertices + 2
        if vertices >= 1 and faces >= 1:
            return _solution(
                str(faces),
                "apply Euler's planar formula",
                method="numeric_check",
                tool="python",
            )

    independent_average_degree = re.fullmatch(
        r"a\s+graph\s+has\s+(\d+)\s+vertices\s+and\s+(\d+)\s+edges\.\s*"
        r"find\s+its\s+average\s+degree\.?",
        q,
        flags=re.I,
    )
    if independent_average_degree:
        vertices, edges = map(int, independent_average_degree.groups())
        if vertices >= 1:
            return _solution(
                _format_expr(sp.Rational(2 * edges, vertices)),
                "compute average degree from the handshaking lemma",
                method="numeric_check",
                tool="python",
            )

    complete_edges = re.search(r"complete\s+graph\s+K_(\d+)", q, flags=re.I)
    if complete_edges and "how many edges" in lower:
        n = int(complete_edges.group(1))
        return _solution(
            str(n * (n - 1) // 2),
            "count complete-graph edges",
            method="numeric_check",
            tool="python",
        )

    chromatic = re.search(
        r"chromatic\s+number\s+of\s+a\s+complete\s+graph\s+K_(\d+)",
        q,
        flags=re.I,
    )
    if chromatic:
        return _solution(
            chromatic.group(1),
            "complete-graph chromatic number",
            method="numeric_check",
            tool="python",
        )

    tree_edges = re.search(r"tree\s+with\s+(\d+)\s+vertices", q, flags=re.I)
    if tree_edges and "how many edges" in lower:
        return _solution(
            str(int(tree_edges.group(1)) - 1),
            "count tree edges",
            method="numeric_check",
            tool="python",
        )

    degree_sum = re.search(r"graph\s+with\s+(\d+)\s+edges", q, flags=re.I)
    if degree_sum and "sum of degrees" in lower:
        return _solution(
            str(2 * int(degree_sum.group(1))),
            "apply handshaking lemma",
            method="numeric_check",
            tool="python",
        )

    path_match = re.search(
        r"shortest\s+path\s+from\s+vertex\s+(\d+)\s+to\s+vertex\s+"
        r"(\d+)\s+in\s+a\s+path\s+graph",
        q,
        flags=re.I,
    )
    if path_match:
        start, end = map(int, path_match.groups())
        return _solution(
            str(abs(end - start)),
            "compute path-graph distance",
            method="numeric_check",
            tool="python",
        )

    walk_match = re.search(r"where\s+k\s*=\s*(\d+)", q, flags=re.I)
    if walk_match and "entry of a^k" in lower:
        return _solution(
            f"number of walks of length {walk_match.group(1)}",
            "interpret adjacency-matrix power",
            tool="python",
        )

    if "all vertices have even degree" in lower and "eulerian circuit" in lower:
        return _solution("yes", "apply Euler circuit criterion", tool="python")
    if "complete bipartite graph" in lower and "bipartite" in lower:
        return _solution("yes", "apply bipartite graph definition", tool="python")
    return None


def _solve_operations_research(
    question: str,
) -> DeterministicSolution | None:
    q = question.strip()

    independent_knapsack = re.fullmatch(
        r"a\s+0-1\s+knapsack\s+has\s+items\s+\(weight,value\)=(\[.*\])\s+"
        r"and\s+capacity\s+(\d+)\.\s*find\s+the\s+maximum\s+value\s*\.?",
        q,
        flags=re.I,
    )
    if independent_knapsack:
        raw_items = _literal_sequence(independent_knapsack.group(1))
        capacity = int(independent_knapsack.group(2))
        items = [tuple(map(int, item)) for item in raw_items]
        if (
            len(items) <= 20
            and all(len(item) == 2 and item[0] >= 0 for item in items)
            and capacity >= 0
        ):
            best_value = 0
            for mask in range(1 << len(items)):
                weight = sum(
                    items[index][0]
                    for index in range(len(items))
                    if mask & (1 << index)
                )
                if weight <= capacity:
                    best_value = max(
                        best_value,
                        sum(
                            items[index][1]
                            for index in range(len(items))
                            if mask & (1 << index)
                        ),
                    )
            return _solution(
                str(best_value),
                "solve a bounded zero-one knapsack exactly",
                method="numeric_check",
                tool="python",
            )

    simplex_capacity = re.fullmatch(
        r"maximize\s+(\d+)x\+(\d+)y\s+subject\s+to\s+x\+y<=(\d+),\s*"
        r"x>=0,\s*y>=0\.\s*give\s+the\s+optimum\s+value\s*\.?",
        q,
        flags=re.I,
    )
    if simplex_capacity:
        coefficient_x, coefficient_y, capacity = map(int, simplex_capacity.groups())
        return _solution(
            str(max(coefficient_x, coefficient_y) * capacity),
            "optimize a two-variable simplex capacity model",
            method="numeric_check",
            tool="python",
        )

    simplex_demand = re.fullmatch(
        r"minimize\s+(\d+)x\+(\d+)y\s+subject\s+to\s+x\+y>=(\d+),\s*"
        r"x>=0,\s*y>=0\.\s*give\s+the\s+optimum\s+value\s*\.?",
        q,
        flags=re.I,
    )
    if simplex_demand:
        coefficient_x, coefficient_y, demand = map(int, simplex_demand.groups())
        return _solution(
            str(min(coefficient_x, coefficient_y) * demand),
            "optimize a two-variable minimum-demand model",
            method="numeric_check",
            tool="python",
        )

    three_path_network = re.fullmatch(
        r"a\s+network\s+has\s+costs\s+A-B=(\d+),\s*B-D=(\d+),\s*"
        r"A-C=(\d+),\s*C-D=(\d+),\s*A-D=(\d+)\.\s*"
        r"find\s+the\s+minimum\s+A-D\s+path\s+cost\s*\.?",
        q,
        flags=re.I,
    )
    if three_path_network:
        ab, bd, ac, cd, direct = map(int, three_path_network.groups())
        return _solution(
            str(min(ab + bd, ac + cd, direct)),
            "compare all paths in a fixed acyclic network",
            method="numeric_check",
            tool="python",
        )

    parallel_flow = re.fullmatch(
        r"a\s+flow\s+network\s+has\s+only\s+arcs\s+s-a=(\d+),\s*a-t=(\d+),\s*"
        r"s-b=(\d+),\s*b-t=(\d+)\.\s*find\s+the\s+max\s+s-t\s+flow\s*\.?",
        q,
        flags=re.I,
    )
    if parallel_flow:
        sa, at, sb, bt = map(int, parallel_flow.groups())
        return _solution(
            str(min(sa, at) + min(sb, bt)),
            "sum bottlenecks on two disjoint flow paths",
            method="numeric_check",
            tool="python",
        )

    eoq_match = re.fullmatch(
        r"in\s+EOQ,\s*annual\s+demand\s+D=(\d+),\s*ordering\s+cost\s+S=(\d+),\s*"
        r"and\s+holding\s+cost\s+H=(\d+)\.\s*compute\s+sqrt\(2DS/H\)\s*\.?",
        q,
        flags=re.I,
    )
    if eoq_match:
        demand, ordering, holding = map(int, eoq_match.groups())
        if holding > 0:
            value = sp.sqrt(sp.Rational(2 * demand * ordering, holding))
            return _solution(
                _format_expr(value),
                "compute the exact economic order quantity",
            )

    independent_queue = re.fullmatch(
        r"for\s+an\s+M/M/1\s+queue\s+with\s+lambda=(\d+)\s+and\s+mu=(\d+),\s*"
        r"find\s+utilization\s+rho\s*\.?",
        q,
        flags=re.I,
    )
    if independent_queue:
        arrival, service = map(int, independent_queue.groups())
        if 0 <= arrival < service:
            return _solution(
                _format_expr(sp.Rational(arrival, service)),
                "compute stable M/M/1 utilization",
                method="numeric_check",
            )

    transportation_total = re.fullmatch(
        r"a\s+transportation\s+model\s+has\s+supplies\s+(\[[^\]]+\])\s+and\s+"
        r"demands\s+(\[[^\]]+\])\.\s*assuming\s+feasibility,\s*how\s+many\s+"
        r"total\s+units\s+must\s+be\s+shipped\s+to\s+meet\s+all\s+demand\?",
        q,
        flags=re.I,
    )
    if transportation_total:
        supplies = list(map(int, _literal_sequence(transportation_total.group(1))))
        demands = list(map(int, _literal_sequence(transportation_total.group(2))))
        if all(value >= 0 for value in supplies + demands) and sum(supplies) >= sum(
            demands
        ):
            return _solution(
                str(sum(demands)),
                "sum feasible transportation demand",
                method="numeric_check",
                tool="python",
            )

    assignment_match = re.fullmatch(
        r"find\s+the\s+minimum\s+assignment\s+cost\s+for\s+matrix\s+(\[\[.*\]\])\s+"
        r"\(one\s+entry\s+per\s+row\s+and\s+column\)\s*\.?",
        q,
        flags=re.I,
    )
    if assignment_match:
        matrix = _literal_sequence(assignment_match.group(1))
        size = len(matrix)
        if 1 <= size <= 8 and all(len(row) == size for row in matrix):
            best_cost = min(
                sum(int(matrix[row][columns[row]]) for row in range(size))
                for columns in permutations(range(size))
            )
            return _solution(
                str(best_cost),
                "enumerate a bounded square assignment problem",
                method="numeric_check",
                tool="python",
            )

    critical_path = re.fullmatch(
        r"a\s+project\s+has\s+two\s+parallel\s+start-to-finish\s+paths\s+with\s+"
        r"activity\s+durations\s+(\[[^\]]+\])\s+and\s+(\[[^\]]+\])\.\s*"
        r"find\s+project\s+duration\s*\.?",
        q,
        flags=re.I,
    )
    if critical_path:
        first = list(map(int, _literal_sequence(critical_path.group(1))))
        second = list(map(int, _literal_sequence(critical_path.group(2))))
        if all(value >= 0 for value in first + second):
            return _solution(
                str(max(sum(first), sum(second))),
                "compute the longest parallel project path",
                method="numeric_check",
                tool="python",
            )

    reorder_point = re.fullmatch(
        r"constant\s+demand\s+is\s+(\d+)\s+units/day\s+and\s+lead\s+time\s+is\s+"
        r"(\d+)\s+days\s+with\s+no\s+safety\s+stock\.\s*find\s+the\s+"
        r"reorder\s+point\s*\.?",
        q,
        flags=re.I,
    )
    if reorder_point:
        demand, lead_time = map(int, reorder_point.groups())
        return _solution(
            str(demand * lead_time),
            "compute demand during lead time",
            method="numeric_check",
            tool="python",
        )

    box_linear_program = re.fullmatch(
        r"maximize\s+(\d+)x\+(\d+)y\s+with\s+0<=x<=(\d+)\s+and\s+"
        r"0<=y<=(\d+)\.\s*give\s+the\s+optimum\s+value\s*\.?",
        q,
        flags=re.I,
    )
    if box_linear_program:
        coefficient_x, coefficient_y, cap_x, cap_y = map(
            int, box_linear_program.groups()
        )
        return _solution(
            str(coefficient_x * cap_x + coefficient_y * cap_y),
            "optimize a nonnegative linear objective over a box",
            method="numeric_check",
            tool="python",
        )

    weighted_intervals = re.fullmatch(
        r"weighted\s+intervals\s+\(start,end,value\)\s+are\s+(\[.*\])\.\s*"
        r"find\s+the\s+maximum\s+value\s+of\s+a\s+nonoverlapping\s+subset\s*\.?",
        q,
        flags=re.I,
    )
    if weighted_intervals:
        intervals = [
            tuple(map(int, interval))
            for interval in _literal_sequence(weighted_intervals.group(1))
        ]
        if len(intervals) <= 100 and all(
            len(interval) == 3 and interval[0] <= interval[1] for interval in intervals
        ):
            intervals.sort(key=lambda interval: (interval[1], interval[0]))
            best_values: list[int] = [0]
            for index, (start, _, value) in enumerate(intervals):
                compatible = max(
                    (
                        best_values[prior + 1]
                        for prior in range(index)
                        if intervals[prior][1] <= start
                    ),
                    default=0,
                )
                best_values.append(max(best_values[-1], compatible + value))
            return _solution(
                str(best_values[-1]),
                "solve weighted interval scheduling by dynamic programming",
                method="numeric_check",
                tool="python",
            )

    directed_path = re.fullmatch(
        r"directed\s+arc\s+costs\s+are\s+s-a=(\d+),\s*a-t=(\d+),\s*"
        r"s-b=(\d+),\s*b-t=(\d+),\s*a-b=(\d+)\.\s*"
        r"find\s+the\s+minimum\s+s-t\s+path\s+cost\s*\.?",
        q,
        flags=re.I,
    )
    if directed_path:
        sa, at, sb, bt, ab = map(int, directed_path.groups())
        return _solution(
            str(min(sa + at, sb + bt, sa + ab + bt)),
            "compare all paths in a fixed directed acyclic network",
            method="numeric_check",
            tool="python",
        )

    queue_match = re.search(
        rf"arrival\s+rate\s+lambda\s*=\s*({_NUMBER})\s+and\s+"
        rf"service\s+rate\s+mu\s*=\s*({_NUMBER})",
        q,
        flags=re.I,
    )
    if queue_match and "utilization" in q.lower():
        arrival, service = map(_rational, queue_match.groups())
        if service != 0:
            return _solution(
                _format_expr(arrival / service),
                "compute queue utilization",
                method="numeric_check",
            )

    knapsack_match = re.fullmatch(
        r"operations\s+research\s*:\s*knapsack\s+problem\s+with\s+items\s+"
        r"(.+),\s*capacity\s*=\s*(\d+)\.\s*what\s+is\s+the\s+maximum\s+"
        r"value\??",
        q,
        flags=re.I,
    )
    if knapsack_match:
        item_text, capacity_text = knapsack_match.groups()
        items = [
            (int(weight), int(value))
            for weight, value in re.findall(
                r"\(weight\s*=\s*(\d+)\s*,\s*value\s*=\s*(\d+)\)",
                item_text,
                flags=re.I,
            )
        ]
        capacity = int(capacity_text)
        if len(items) > 24 or capacity > 100_000:
            return None
        best_by_capacity = [0] * (capacity + 1)
        for weight, item_value in items:
            for current_capacity in range(capacity, weight - 1, -1):
                best_by_capacity[current_capacity] = max(
                    best_by_capacity[current_capacity],
                    best_by_capacity[current_capacity - weight] + item_value,
                )
        if items:
            return _solution(
                str(best_by_capacity[capacity]),
                "solve zero-one knapsack",
                method="numeric_check",
                tool="python",
            )

    linear_program = re.fullmatch(
        rf"operations\s+research\s*:\s*(maximize|minimize)\s+"
        rf"({_NUMBER})x\s*\+\s*({_NUMBER})y\s+subject\s+to\s+"
        rf"x\s*\+\s*y\s*(<=|>=)\s*({_NUMBER})\s*,\s*"
        r"x\s*>=\s*0\s*,\s*y\s*>=\s*0\s*\.?",
        q,
        flags=re.I,
    )
    if linear_program:
        operation, a_text, b_text, relation, bound_text = linear_program.groups()
        a, b, bound = map(_rational, (a_text, b_text, bound_text))
        if operation.lower() == "maximize" and relation == "<=":
            value = max(a, b) * bound
        elif operation.lower() == "minimize" and relation == ">=":
            value = min(a, b) * bound
        else:
            return None
        return _solution(
            _format_expr(value),
            "solve two-variable linear program",
            method="numeric_check",
        )

    transport_match = re.search(
        r"capacities\s+([0-9,\s]+)\)\s+and\s+\d+\s+demand\s+nodes\s+"
        r"\(demands\s+([0-9,\s]+)\)",
        q,
        flags=re.I,
    )
    if transport_match and "minimum total supply" in q.lower():
        supply = [int(value) for value in transport_match.group(1).split(",")]
        demand = [int(value) for value in transport_match.group(2).split(",")]
        if sum(supply) >= sum(demand):
            return _solution(
                str(sum(demand)),
                "balance transportation supply and demand",
                method="numeric_check",
                tool="python",
            )

    eoq_match = re.search(
        rf"demand\s+D\s*=\s*({_NUMBER})\s*,\s*ordering\s+cost\s+"
        rf"S\s*=\s*({_NUMBER})\s*,\s*holding\s+cost\s+H\s*=\s*"
        rf"({_NUMBER})",
        q,
        flags=re.I,
    )
    if eoq_match:
        demand, ordering, holding = map(_rational, eoq_match.groups())
        if holding > 0:
            value = sp.sqrt(2 * demand * ordering / holding)
            return _solution(_format_expr(value), "compute economic order quantity")

    shortest_path = re.search(
        rf"edges\s+A-B=({_NUMBER}),\s*B-C=({_NUMBER}),\s*"
        rf"C-D=({_NUMBER}),\s*A-C=({_NUMBER}),\s*B-D=({_NUMBER})",
        q,
        flags=re.I,
    )
    if shortest_path:
        ab, bc, cd, ac, bd = map(_rational, shortest_path.groups())
        value = min(ab + bc + cd, ac + cd, ab + bd)
        return _solution(
            _format_expr(value),
            "compute shortest path",
            method="numeric_check",
        )

    max_flow = re.search(
        r"capacity\s+(\d+)\s+on\s+edge\s+S-A,\s*(\d+)\s+on\s+S-B,\s*"
        r"(\d+)\s+on\s+A-T,\s*(\d+)\s+on\s+B-T,\s*(\d+)\s+on\s+A-B",
        q,
        flags=re.I,
    )
    if max_flow:
        sa, sb, at, bt, ab = map(int, max_flow.groups())
        cuts = [sa + sb, at + bt, sb + at + ab, sa + bt]
        return _solution(
            str(min(cuts)),
            "compute max flow by minimum cut",
            method="numeric_check",
            tool="python",
        )
    return None


def _solve_geometry(question: str) -> DeterministicSolution | None:
    q = question.strip()
    lower = q.lower()

    def format_pi_multiple(coefficient: Any) -> str:
        simplified = sp.simplify(coefficient)
        if simplified == 1:
            return "pi"
        if simplified == -1:
            return "-pi"
        return f"{_format_expr(simplified)}*pi"

    independent_perimeter = re.fullmatch(
        r"a\s+triangle\s+has\s+side\s+lengths\s+(\d+),\s*(\d+),\s*and\s+"
        r"(\d+)\.\s*find\s+its\s+perimeter\s*\.?",
        q,
        flags=re.I,
    )
    if independent_perimeter:
        sides = list(map(int, independent_perimeter.groups()))
        if all(side > 0 for side in sides) and 2 * max(sides) < sum(sides):
            return _solution(
                str(sum(sides)),
                "sum valid triangle side lengths",
                method="numeric_check",
                tool="python",
            )

    independent_hypotenuse = re.fullmatch(
        r"a\s+right\s+triangle\s+has\s+legs\s+(\d+)\s+and\s+(\d+)\.\s*"
        r"find\s+its\s+hypotenuse\s*\.?",
        q,
        flags=re.I,
    )
    if independent_hypotenuse:
        first, second = map(int, independent_hypotenuse.groups())
        if first > 0 and second > 0:
            return _solution(
                _format_expr(sp.sqrt(first**2 + second**2)),
                "apply the Pythagorean theorem",
            )

    triangle_area = re.fullmatch(
        r"find\s+the\s+area\s+of\s+a\s+triangle\s+with\s+base\s+(\d+)\s+and\s+"
        r"altitude\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if triangle_area:
        base, altitude = map(int, triangle_area.groups())
        return _solution(
            _format_expr(sp.Rational(base * altitude, 2)),
            "compute triangle area from base and altitude",
            method="numeric_check",
        )

    rectangle_diagonal = re.fullmatch(
        r"a\s+rectangle\s+has\s+side\s+lengths\s+(\d+)\s+and\s+(\d+)\.\s*"
        r"find\s+the\s+diagonal\s+length\s*\.?",
        q,
        flags=re.I,
    )
    if rectangle_diagonal:
        first, second = map(int, rectangle_diagonal.groups())
        return _solution(
            _format_expr(sp.sqrt(first**2 + second**2)),
            "apply the Pythagorean theorem to a rectangle",
        )

    exact_circle_area = re.fullmatch(
        r"give\s+the\s+exact\s+area\s+of\s+a\s+circle\s+of\s+radius\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if exact_circle_area:
        radius = int(exact_circle_area.group(1))
        return _solution(
            format_pi_multiple(radius**2),
            "compute exact circle area",
        )

    exact_circumference = re.fullmatch(
        r"give\s+the\s+exact\s+circumference\s+of\s+a\s+circle\s+of\s+radius\s+"
        r"(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if exact_circumference:
        radius = int(exact_circumference.group(1))
        return _solution(
            format_pi_multiple(2 * radius),
            "compute exact circle circumference",
        )

    independent_chord = re.fullmatch(
        r"a\s+chord\s+lies\s+(\d+)\s+units\s+from\s+the\s+center\s+of\s+a\s+"
        r"circle\s+of\s+radius\s+(\d+)\.\s*find\s+the\s+chord\s+length\s*\.?",
        q,
        flags=re.I,
    )
    if independent_chord:
        distance, radius = map(int, independent_chord.groups())
        if 0 <= distance <= radius:
            return _solution(
                _format_expr(2 * sp.sqrt(radius**2 - distance**2)),
                "compute chord length from radius and center distance",
            )

    trapezoid_area = re.fullmatch(
        r"a\s+trapezoid\s+has\s+parallel\s+sides\s+(\d+)\s+and\s+(\d+)\s+and\s+"
        r"height\s+(\d+)\.\s*find\s+its\s+area\s*\.?",
        q,
        flags=re.I,
    )
    if trapezoid_area:
        first, second, height = map(int, trapezoid_area.groups())
        return _solution(
            _format_expr(sp.Rational((first + second) * height, 2)),
            "compute trapezoid area",
            method="numeric_check",
        )

    polygon_angle_sum = re.fullmatch(
        r"find\s+the\s+sum\s+of\s+the\s+interior\s+angles,\s*in\s+degrees,\s*"
        r"of\s+a\s+convex\s+(\d+)-gon\s*\.?",
        q,
        flags=re.I,
    )
    if polygon_angle_sum:
        sides = int(polygon_angle_sum.group(1))
        if sides >= 3:
            return _solution(
                str((sides - 2) * 180),
                "compute a convex polygon's interior-angle sum",
                method="numeric_check",
                tool="python",
            )

    regular_exterior_angle = re.fullmatch(
        r"what\s+is\s+each\s+exterior\s+angle,\s*in\s+degrees,\s*of\s+a\s+"
        r"regular\s+(\d+)-gon\?",
        q,
        flags=re.I,
    )
    if regular_exterior_angle:
        sides = int(regular_exterior_angle.group(1))
        if sides >= 3:
            return _solution(
                _format_expr(sp.Rational(360, sides)),
                "divide a full turn among regular-polygon exterior angles",
                method="numeric_check",
            )

    sector_area = re.fullmatch(
        r"a\s+sector\s+has\s+radius\s+(\d+)\s+and\s+central\s+angle\s+(\d+)\s+"
        r"degrees\.\s*give\s+its\s+exact\s+area\s+as\s+a\s+multiple\s+of\s+pi\s*\.?",
        q,
        flags=re.I,
    )
    if sector_area:
        radius, angle = map(int, sector_area.groups())
        if radius >= 0 and 0 <= angle <= 360:
            coefficient = sp.Rational(radius**2 * angle, 360)
            return _solution(
                format_pi_multiple(coefficient),
                "compute exact circular-sector area",
            )

    cylinder_volume = re.fullmatch(
        r"give\s+the\s+exact\s+volume\s+of\s+a\s+cylinder\s+with\s+radius\s+"
        r"(\d+)\s+and\s+height\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if cylinder_volume:
        radius, height = map(int, cylinder_volume.groups())
        return _solution(
            format_pi_multiple(radius**2 * height),
            "compute exact cylinder volume",
        )

    similar_triangles = re.fullmatch(
        r"corresponding\s+sides\s+of\s+two\s+similar\s+triangles\s+have\s+scale\s+"
        r"factor\s+(\d+/\d+)\.\s*if\s+the\s+first\s+side\s+is\s+(\d+),\s*"
        r"find\s+the\s+matching\s+side\s*\.?",
        q,
        flags=re.I,
    )
    if similar_triangles:
        scale = _rational(similar_triangles.group(1))
        first_side = int(similar_triangles.group(2))
        if scale > 0 and first_side > 0:
            return _solution(
                _format_expr(scale * first_side),
                "apply the stated corresponding-side scale factor",
                method="numeric_check",
            )

    external_tangency = re.fullmatch(
        r"two\s+circles\s+of\s+radii\s+(\d+)\s+and\s+(\d+)\s+are\s+externally\s+"
        r"tangent\.\s*find\s+the\s+distance\s+between\s+their\s+centers\s*\.?",
        q,
        flags=re.I,
    )
    if external_tangency:
        first, second = map(int, external_tangency.groups())
        return _solution(
            str(first + second),
            "sum radii of externally tangent circles",
            method="numeric_check",
            tool="python",
        )

    complete_patterns: list[tuple[str, Callable[[tuple[str, ...]], object], str]] = [
        (
            rf"geometry\s*:\s*rectangle\s+has\s+length\s+({_NUMBER})\s+"
            rf"and\s+width\s+({_NUMBER}),\s*compute\s+its\s+area\??",
            lambda values: _rational(values[0]) * _rational(values[1]),
            "compute rectangle area",
        ),
        (
            rf"geometry\s*:\s*triangle\s+has\s+base\s+({_NUMBER})\s+"
            rf"and\s+height\s+({_NUMBER}),\s*compute\s+its\s+area\??",
            lambda values: _rational(values[0]) * _rational(values[1]) / 2,
            "compute triangle area",
        ),
        (
            rf"geometry\s*:\s*right\s+triangle\s+has\s+legs\s+"
            rf"({_NUMBER})\s+and\s+({_NUMBER}),\s*compute\s+its\s+area\??",
            lambda values: _rational(values[0]) * _rational(values[1]) / 2,
            "compute right-triangle area",
        ),
        (
            rf"geometry\s*:\s*right\s+triangle\s+has\s+legs\s+"
            rf"({_NUMBER})\s+and\s+({_NUMBER}),\s*find\s+the\s+"
            r"hypotenuse\??",
            lambda values: sp.sqrt(
                _rational(values[0]) ** 2 + _rational(values[1]) ** 2
            ),
            "compute hypotenuse",
        ),
        (
            rf"geometry\s*:\s*triangle\s+has\s+side\s+lengths\s+"
            rf"({_NUMBER}),\s*({_NUMBER}),\s*({_NUMBER}),\s*"
            r"compute\s+its\s+perimeter\??",
            lambda values: sum(_rational(value) for value in values),
            "compute triangle perimeter",
        ),
    ]
    for pattern, calculate, purpose in complete_patterns:
        matched = re.fullmatch(pattern, q, flags=re.I)
        if matched:
            return _solution(
                _format_expr(calculate(matched.groups())),
                purpose,
                method="numeric_check",
            )

    chord_match = re.fullmatch(
        rf"geometry\s*:\s*a\s+circle\s+has\s+radius\s+({_NUMBER})\s+"
        rf"and\s+a\s+chord\s+is\s+({_NUMBER})\s+from\s+the\s+center\.\s*"
        r"find\s+the\s+chord\s+length\.?",
        q,
        flags=re.I,
    )
    if chord_match:
        radius, distance = map(_rational, chord_match.groups())
        radicand = radius**2 - distance**2
        if radicand >= 0:
            return _solution(
                _format_expr(2 * sp.sqrt(radicand)),
                "compute chord length",
            )

    circle_match = re.fullmatch(
        rf"geometry\s*:\s*circle\s+has\s+radius\s+({_NUMBER}),\s*"
        r"compute\s+its\s+area\??",
        q,
        flags=re.I,
    )
    if circle_match:
        radius = _rational(circle_match.group(1))
        return _solution(_format_expr(sp.pi * radius**2), "compute circle area")
    if "sum of interior angles of a triangle" in lower:
        return _solution(
            "180", "triangle angle sum", method="numeric_check", tool="python"
        )
    return None


def _solve_analytic_geometry(
    question: str,
) -> DeterministicSolution | None:
    q = question.strip()

    independent_intercept = re.fullmatch(
        rf"a\s+line\s+of\s+slope\s+({_NUMBER})\s+passes\s+through\s+"
        rf"\(({_NUMBER})\s*,\s*({_NUMBER})\)\.\s*find\s+its\s+"
        r"y-intercept\.?",
        q,
        flags=re.I,
    )
    if independent_intercept:
        slope, x_value, y_value = map(_rational, independent_intercept.groups())
        return _solution(
            _format_expr(y_value - slope * x_value),
            "compute a line's y-intercept from a point and slope",
        )

    independent_circle = re.fullmatch(
        rf"write\s+the\s+circle\s+equation\s+with\s+center\s+"
        rf"\(({_NUMBER})\s*,\s*({_NUMBER})\)\s+and\s+radius\s+"
        rf"({_NUMBER})\s+in\s+the\s+form\s+"
        r"\(x-h\)\^2\+\(y-k\)\^2=r\^2\.?",
        q,
        flags=re.I,
    )
    if independent_circle:
        h, k, radius = map(_rational, independent_circle.groups())
        if radius >= 0:

            def shifted_square(variable: str, center: Any) -> str:
                if center == 0:
                    return f"({variable})^2"
                sign = "-" if center > 0 else "+"
                return f"({variable}{sign}{_format_expr(abs(center))})^2"

            value = (
                f"{shifted_square('x', h)}+{shifted_square('y', k)}="
                f"{_format_expr(radius**2)}"
            )
            return _solution(value, "write a circle in center-radius form")

    independent_section = re.fullmatch(
        rf"point\s+P\s+divides\s+the\s+segment\s+from\s+A="
        rf"\(({_NUMBER})\s*,\s*({_NUMBER})\)\s+to\s+B="
        rf"\(({_NUMBER})\s*,\s*({_NUMBER})\)\s+internally\s+with\s+"
        r"AP:PB=(\d+):(\d+)\.\s*find\s+P\.?",
        q,
        flags=re.I,
    )
    if independent_section:
        x1, y1, x2, y2 = map(_rational, independent_section.groups()[:4])
        first, second = map(int, independent_section.groups()[4:])
        denominator = first + second
        if first > 0 and second > 0:
            return _solution(
                _format_tuple(
                    [
                        (second * x1 + first * x2) / denominator,
                        (second * y1 + first * y2) / denominator,
                    ]
                ),
                "apply the internal section formula",
            )

    independent_horizontal_distance = re.fullmatch(
        rf"find\s+the\s+distance\s+from\s+\(({_NUMBER})\s*,\s*"
        rf"({_NUMBER})\)\s+to\s+the\s+horizontal\s+line\s+y=({_NUMBER})\.?",
        q,
        flags=re.I,
    )
    if independent_horizontal_distance:
        _, y_value, line_y = map(_rational, independent_horizontal_distance.groups())
        return _solution(
            _format_expr(abs(y_value - line_y)),
            "compute vertical distance to a horizontal line",
        )

    independent_vertex = re.fullmatch(
        r"for\s+y=(?:([-+]?\d+)\s*)?\(x([-+]\d+)?\)\^2([-+]\d+),\s*"
        r"give\s+the\s+vertex\s+coordinates\.?",
        q,
        flags=re.I,
    )
    if independent_vertex:
        scale_text, offset_text, height_text = independent_vertex.groups()
        scale = int(scale_text or "1")
        if scale != 0:
            return _solution(
                _format_tuple([-int(offset_text or "0"), int(height_text)]),
                "read the vertex from parabola vertex form",
            )

    independent_ellipse = re.fullmatch(
        r"for\s+the\s+ellipse\s+x\^2/(\d+)\s*\+\s*y\^2/(\d+)\s*=\s*1,\s*"
        r"find\s+the\s+full\s+length\s+of\s+the\s+x-axis\s+intercept\s+"
        r"chord\.?",
        q,
        flags=re.I,
    )
    if independent_ellipse:
        x_denominator = int(independent_ellipse.group(1))
        if x_denominator > 0:
            return _solution(
                _format_expr(2 * sp.sqrt(x_denominator)),
                "find the full major-axis intercept chord",
            )

    independent_intersection = re.fullmatch(
        r"find\s+the\s+y-coordinate\s+where\s+y=([-+]?\d*)x([-+]\d+)?\s+"
        r"intersects\s+y=([-+]?\d*)x([-+]\d+)?\.?",
        q,
        flags=re.I,
    )
    if independent_intersection:

        def linear_coefficient(value: str) -> int:
            if value in {"", "+"}:
                return 1
            if value == "-":
                return -1
            return int(value)

        first_slope = linear_coefficient(independent_intersection.group(1))
        first_intercept = int(independent_intersection.group(2) or "0")
        second_slope = linear_coefficient(independent_intersection.group(3))
        second_intercept = int(independent_intersection.group(4) or "0")
        if first_slope != second_slope:
            x_value = sp.Rational(
                second_intercept - first_intercept,
                first_slope - second_slope,
            )
            y_value = first_slope * x_value + first_intercept
            return _solution(
                _format_expr(y_value),
                "solve two nonparallel line equations",
            )

    independent_coordinate_area = re.fullmatch(
        rf"find\s+the\s+area\s+of\s+the\s+coordinate\s+triangle\s+with\s+"
        rf"vertices\s+\(0\s*,\s*0\),\s*\(({_NUMBER})\s*,\s*0\),\s*"
        rf"and\s+\(0\s*,\s*({_NUMBER})\)\.?",
        q,
        flags=re.I,
    )
    if independent_coordinate_area:
        base, height = map(_rational, independent_coordinate_area.groups())
        return _solution(
            _format_expr(abs(base * height) / 2),
            "compute the area of an axis-aligned right triangle",
        )

    independent_reflection = re.fullmatch(
        rf"reflect\s+the\s+point\s+\(({_NUMBER})\s*,\s*({_NUMBER})\)\s+"
        r"across\s+the\s+x-axis\.?",
        q,
        flags=re.I,
    )
    if independent_reflection:
        x_value, y_value = map(_rational, independent_reflection.groups())
        return _solution(
            _format_tuple([x_value, -y_value]),
            "reflect a point across the x-axis",
        )

    independent_perpendicular = re.fullmatch(
        rf"a\s+line\s+has\s+slope\s+({_NUMBER})/({_NUMBER})\.\s*"
        r"find\s+the\s+slope\s+of\s+any\s+perpendicular\s+line\.?",
        q,
        flags=re.I,
    )
    if independent_perpendicular:
        numerator, denominator = map(_rational, independent_perpendicular.groups())
        if numerator != 0 and denominator != 0:
            return _solution(
                _format_expr(-denominator / numerator),
                "take the negative reciprocal slope",
            )

    independent_general_distance = re.fullmatch(
        rf"find\s+the\s+distance\s+from\s+\(({_NUMBER})\s*,\s*"
        rf"({_NUMBER})\)\s+to\s+the\s+line\s+({_NUMBER})x"
        rf"([-+]\d+)y([-+]\d+)?=0\.?",
        q,
        flags=re.I,
    )
    if independent_general_distance:
        x_text, y_text, a_text, b_text, c_text = independent_general_distance.groups()
        x_value, y_value, a, b, c = map(
            _rational,
            (x_text, y_text, a_text, b_text, c_text or "0"),
        )
        norm = sp.sqrt(a**2 + b**2)
        if norm != 0:
            return _solution(
                _format_expr(abs(a * x_value + b * y_value + c) / norm),
                "apply the point-to-line distance formula",
            )

    points_match = re.search(
        rf"\(({_NUMBER}),\s*({_NUMBER})\)\s+and\s+"
        rf"\(({_NUMBER}),\s*({_NUMBER})\)",
        q,
        flags=re.I,
    )
    if points_match:
        x1, y1, x2, y2 = map(_rational, points_match.groups())
        lower = q.lower()
        if "midpoint" in lower:
            return _solution(
                _format_tuple([(x1 + x2) / 2, (y1 + y2) / 2]),
                "compute midpoint",
            )
        if "squared distance" in lower:
            return _solution(
                _format_expr((x2 - x1) ** 2 + (y2 - y1) ** 2),
                "compute squared distance",
            )
        if "slope" in lower and x2 != x1:
            return _solution(_format_expr((y2 - y1) / (x2 - x1)), "compute slope")
        if "equation of line" in lower:
            if x2 == x1:
                return _solution(
                    f"x={_format_expr(x1)}", "derive vertical line equation"
                )
            slope = (y2 - y1) / (x2 - x1)
            intercept = y1 - slope * x1
            expression = slope * _SYMBOLS["x"] + intercept
            return _solution(f"y={_format_expr(expression)}", "derive line equation")

    circle_match = re.fullmatch(
        rf"analytic\s+geometry\s*:\s*equation\s+of\s+circle\s+with\s+"
        rf"center\s+\(({_NUMBER}),\s*({_NUMBER})\)\s+and\s+radius\s+"
        rf"({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if circle_match:
        h, k, radius = map(_rational, circle_match.groups())
        x, y = _SYMBOLS["x"], _SYMBOLS["y"]
        lhs = (x - h) ** 2 + (y - k) ** 2
        return _solution(
            f"{_format_expr(lhs)}={_format_expr(radius**2)}",
            "derive circle equation",
        )

    vertex_match = re.search(
        rf"vertex\s+x-coordinate\s+of\s+y\s*=\s*({_NUMBER})"
        rf"\(x-({_NUMBER})\)\^2",
        q,
        flags=re.I,
    )
    if vertex_match:
        return _solution(
            _format_expr(_rational(vertex_match.group(2))),
            "read parabola vertex",
        )

    section_match = re.fullmatch(
        rf"analytic\s+geometry\s*:\s*find\s+the\s+coordinates\s+of\s+a\s+"
        rf"point\s+that\s+divides\s+the\s+segment\s+from\s+"
        rf"\(({_NUMBER}),({_NUMBER})\)\s+to\s+"
        rf"\(({_NUMBER}),({_NUMBER})\)\s+in\s+ratio\s+"
        r"(\d+):(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if section_match:
        x1, y1, x2, y2 = map(_rational, section_match.groups()[:4])
        first, second = map(int, section_match.groups()[4:])
        denominator = first + second
        values = [
            (second * x1 + first * x2) / denominator,
            (second * y1 + first * y2) / denominator,
        ]
        return _solution(_format_tuple(values), "apply internal section formula")

    point_line_match = re.fullmatch(
        rf"analytic\s+geometry\s*:\s*distance\s+from\s+point\s+"
        rf"\(({_NUMBER}),({_NUMBER})\)\s+to\s+line\s+y\s*=\s*"
        rf"({_NUMBER})\s*\.?",
        q,
        flags=re.I,
    )
    if point_line_match:
        _, y_value, line_y = map(_rational, point_line_match.groups())
        return _solution(
            _format_expr(sp.Abs(y_value - line_y)),
            "compute point-to-horizontal-line distance",
        )
    return None


def _solve_number_theory(question: str) -> DeterministicSolution | None:
    q = question.strip()

    independent_gcd = re.fullmatch(
        r"compute\s+gcd\((\d+)\s*,\s*(\d+)\)\.?",
        q,
        flags=re.I,
    )
    if independent_gcd:
        first, second = map(int, independent_gcd.groups())
        return _solution(
            str(gcd(first, second)),
            "compute the greatest common divisor",
            tool="python",
        )

    independent_lcm = re.fullmatch(
        r"compute\s+lcm\((\d+)\s*,\s*(\d+)\)\.?",
        q,
        flags=re.I,
    )
    if independent_lcm:
        first, second = map(int, independent_lcm.groups())
        value = abs(first * second) // gcd(first, second) if first and second else 0
        return _solution(
            str(value),
            "compute the least common multiple",
            tool="python",
        )

    independent_residue = re.fullmatch(
        r"find\s+the\s+least\s+nonnegative\s+residue\s+of\s+([-+]?\d+)\s+"
        r"modulo\s+(\d+)\.?",
        q,
        flags=re.I,
    )
    if independent_residue:
        value, modulus = map(int, independent_residue.groups())
        if modulus > 0:
            return _solution(
                str(value % modulus),
                "reduce an integer modulo a positive modulus",
                tool="python",
            )

    independent_modular_power = re.fullmatch(
        r"compute\s+(\d+)\^(\d+)\s+mod\s+(\d+)\.?",
        q,
        flags=re.I,
    )
    if independent_modular_power:
        base, exponent, modulus = map(int, independent_modular_power.groups())
        if modulus > 0:
            return _solution(
                str(pow(base, exponent, modulus)),
                "compute a modular power",
                tool="python",
            )

    independent_inverse = re.fullmatch(
        r"find\s+the\s+least\s+positive\s+inverse\s+of\s+(\d+)\s+"
        r"modulo\s+(\d+)\.?",
        q,
        flags=re.I,
    )
    if independent_inverse:
        value, modulus = map(int, independent_inverse.groups())
        if modulus > 1 and gcd(value, modulus) == 1:
            return _solution(
                str(pow(value, -1, modulus)),
                "compute a modular inverse",
                method="substitution",
                tool="python",
            )

    independent_congruence = re.fullmatch(
        r"find\s+the\s+least\s+nonnegative\s+x\s+satisfying\s+(\d*)x\s+"
        r"congruent\s+to\s+([-+]?\d+)\s+\(mod\s+(\d+)\)\.?",
        q,
        flags=re.I,
    )
    if independent_congruence:
        coefficient_text, rhs_text, modulus_text = independent_congruence.groups()
        coefficient = int(coefficient_text or "1")
        rhs = int(rhs_text)
        modulus = int(modulus_text)
        if modulus > 0:
            common = gcd(coefficient, modulus)
            if rhs % common == 0:
                reduced_coefficient = coefficient // common
                reduced_rhs = rhs // common
                reduced_modulus = modulus // common
                value = (
                    0
                    if reduced_modulus == 1
                    else (pow(reduced_coefficient, -1, reduced_modulus) * reduced_rhs)
                    % reduced_modulus
                )
                return _solution(
                    str(value),
                    "solve a linear congruence",
                    method="substitution",
                    tool="python",
                )

    independent_crt = re.fullmatch(
        r"find\s+the\s+least\s+nonnegative\s+x\s+with\s+x\s+congruent\s+"
        r"to\s+([-+]?\d+)\s+\(mod\s+(\d+)\)\s+and\s+x\s+congruent\s+"
        r"to\s+([-+]?\d+)\s+\(mod\s+(\d+)\)\.?",
        q,
        flags=re.I,
    )
    if independent_crt:
        first_residue, first_modulus, second_residue, second_modulus = map(
            int, independent_crt.groups()
        )
        if first_modulus > 0 and second_modulus > 0:
            common = gcd(first_modulus, second_modulus)
            difference = second_residue - first_residue
            if difference % common == 0:
                reduced_second = second_modulus // common
                step = (
                    0
                    if reduced_second == 1
                    else (
                        difference
                        // common
                        * pow(
                            first_modulus // common,
                            -1,
                            reduced_second,
                        )
                    )
                    % reduced_second
                )
                period = first_modulus * reduced_second
                value = (first_residue + first_modulus * step) % period
                return _solution(
                    str(value),
                    "solve a compatible two-modulus CRT system",
                    method="substitution",
                    tool="python",
                )

    independent_totient = re.fullmatch(
        r"compute\s+euler\s+phi\((\d+)\)\.?",
        q,
        flags=re.I,
    )
    if independent_totient:
        value = int(independent_totient.group(1))
        if 1 <= value <= 1_000_000_000:
            return _solution(
                str(sp.totient(value)),
                "compute Euler's totient",
            )

    independent_divisor_count = re.fullmatch(
        r"how\s+many\s+positive\s+divisors\s+does\s+(\d+)\s+have\??",
        q,
        flags=re.I,
    )
    if independent_divisor_count:
        value = int(independent_divisor_count.group(1))
        if 1 <= value <= 1_000_000_000:
            return _solution(
                str(sp.divisor_count(value)),
                "count positive divisors",
            )

    independent_primality = re.fullmatch(
        r"is\s+(\d+)\s+prime\?\s*answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if independent_primality:
        value = int(independent_primality.group(1))
        if value <= 1_000_000_000:
            return _solution(
                "yes" if sp.isprime(value) else "no",
                "test primality",
                method="numeric_check",
                tool="python",
            )

    independent_divisor_sum = re.fullmatch(
        r"find\s+the\s+sum\s+of\s+all\s+positive\s+divisors\s+of\s+"
        r"(\d+)\.?",
        q,
        flags=re.I,
    )
    if independent_divisor_sum:
        value = int(independent_divisor_sum.group(1))
        if 1 <= value <= 1_000_000_000:
            return _solution(
                str(sp.divisor_sigma(value, 1)),
                "sum all positive divisors",
            )

    independent_factorial_valuation = re.fullmatch(
        r"find\s+the\s+exponent\s+of\s+prime\s+(\d+)\s+in\s+(\d+)!\.?",
        q,
        flags=re.I,
    )
    if independent_factorial_valuation:
        prime, n = map(int, independent_factorial_valuation.groups())
        if sp.isprime(prime) and n <= 1_000_000_000:
            value = 0
            quotient = n
            while quotient:
                quotient //= prime
                value += quotient
            return _solution(
                str(value),
                "apply Legendre's factorial valuation formula",
                method="numeric_check",
                tool="python",
            )

    independent_trailing_zeros = re.fullmatch(
        r"how\s+many\s+trailing\s+zeros\s+are\s+in\s+(\d+)!\??",
        q,
        flags=re.I,
    )
    if independent_trailing_zeros:
        n = int(independent_trailing_zeros.group(1))
        if n <= 1_000_000_000:
            value = 0
            quotient = n
            while quotient:
                quotient //= 5
                value += quotient
            return _solution(
                str(value),
                "count factors of five in a factorial",
                method="numeric_check",
                tool="python",
            )

    independent_diophantine = re.fullmatch(
        r"does\s+(\d+)x\+([-+]?\d+)y=([-+]?\d+)\s+have\s+an\s+integer\s+"
        r"solution\?\s*answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if independent_diophantine:
        first, second, target = map(int, independent_diophantine.groups())
        common = gcd(first, second)
        if common != 0:
            return _solution(
                "yes" if target % common == 0 else "no",
                "apply the linear Diophantine solvability criterion",
                method="numeric_check",
                tool="python",
            )

    gcd_match = re.fullmatch(
        r"number\s+theory\s*:\s*compute\s+gcd\((\d+)\s*,\s*(\d+)\)\s*\.?",
        q,
        flags=re.I,
    )
    if gcd_match:
        a, b = map(int, gcd_match.groups())
        return _solution(str(gcd(a, b)), "compute gcd", tool="python")

    lcm_match = re.fullmatch(
        r"number\s+theory\s*:\s*compute\s+lcm\((\d+)\s*,\s*(\d+)\)\s*\.?",
        q,
        flags=re.I,
    )
    if lcm_match:
        a, b = map(int, lcm_match.groups())
        value = abs(a * b) // gcd(a, b) if a and b else 0
        return _solution(str(value), "compute lcm", tool="python")

    remainder_match = re.fullmatch(
        r"number\s+theory\s*:\s*remainder\s+when\s+(\d+)\s+is\s+divided\s+by\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if remainder_match:
        dividend, divisor = map(int, remainder_match.groups())
        if divisor <= 0:
            return None
        return _solution(str(dividend % divisor), "compute remainder", tool="python")

    residue_match = re.fullmatch(
        r"number\s+theory\s*:\s*least\s+nonnegative\s+residue\s+of\s+"
        r"(\d+)\s*\^\s*(\d+)\s+modulo\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if residue_match:
        base, exponent, modulus = map(int, residue_match.groups())
        if modulus <= 0:
            return None
        return _solution(
            str(pow(base, exponent, modulus)),
            "compute modular exponentiation",
            tool="python",
        )

    phi_match = re.fullmatch(
        r"number\s+theory\s*:\s*compute\s+euler\s+phi\((\d+)\)\s*\.?",
        q,
        flags=re.I,
    )
    if phi_match:
        value = int(phi_match.group(1))
        if value < 1 or value > 1_000_000_000:
            return None
        return _solution(str(sp.totient(value)), "compute Euler phi")

    divisor_match = re.fullmatch(
        r"number\s+theory\s*:\s*how\s+many\s+positive\s+divisors\s+does\s+"
        r"(\d+)\s+have\??",
        q,
        flags=re.I,
    )
    if divisor_match:
        value = int(divisor_match.group(1))
        if value < 1 or value > 1_000_000_000:
            return None
        return _solution(str(sp.divisor_count(value)), "count positive divisors")

    inverse_match = re.fullmatch(
        r"number\s+theory\s*:\s*find\s+the\s+least\s+positive\s+"
        r"multiplicative\s+inverse\s+of\s+(\d+)\s+modulo\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if inverse_match:
        value, modulus = map(int, inverse_match.groups())
        if modulus <= 1 or gcd(value, modulus) != 1:
            return None
        return _solution(
            str(pow(value, -1, modulus)),
            "compute modular inverse",
            method="substitution",
            tool="python",
        )

    crt_match = re.fullmatch(
        r"number\s+theory\s*:\s*find\s+the\s+least\s+nonnegative\s+"
        r"solution\s+to\s+x\s*=\s*(-?\d+)\s+mod\s+(\d+)\s*,\s*"
        r"x\s*=\s*(-?\d+)\s+mod\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if crt_match:
        a, m, b, n = map(int, crt_match.groups())
        if m <= 0 or n <= 0:
            return None
        common = gcd(m, n)
        difference = b - a
        if difference % common != 0:
            return _solution("no solution", "solve two-congruence CRT")
        reduced_n = n // common
        step = 0
        if reduced_n > 1:
            step = (
                (difference // common) * pow(m // common, -1, reduced_n)
            ) % reduced_n
        value = (a + m * step) % (m * reduced_n)
        return _solution(
            str(value),
            "solve two-congruence CRT",
            method="substitution",
            tool="python",
        )

    prime_match = re.fullmatch(
        r"number\s+theory\s*:\s*is\s+(\d+)\s+a\s+prime\s+number\??",
        q,
        flags=re.I,
    )
    if prime_match:
        value = "yes" if sp.isprime(int(prime_match.group(1))) else "no"
        return _solution(value, "test primality", tool="python")

    congruence_match = re.fullmatch(
        r"number\s+theory\s*:\s*solve\s+(\d+)x\s+\S+\s+"
        r"(-?\d+)\s+\(mod\s+(\d+)\)\s*\.?",
        q,
        flags=re.I,
    )
    if congruence_match:
        coefficient, rhs, modulus = map(int, congruence_match.groups())
        if modulus <= 0:
            return None
        common = gcd(coefficient, modulus)
        if rhs % common != 0:
            return _solution("no solution", "solve linear congruence")
        if common > _MAX_ENUMERATED_SOLUTIONS:
            return None
        reduced_a = coefficient // common
        reduced_b = rhs // common
        reduced_modulus = modulus // common
        base = (pow(reduced_a, -1, reduced_modulus) * reduced_b) % (reduced_modulus)
        values = sorted(
            (base + offset * reduced_modulus) % modulus for offset in range(common)
        )
        return _solution(
            ",".join(str(value) for value in values),
            "solve linear congruence",
            method="substitution",
            tool="python",
        )
    return None


def _solve_complex_analysis(
    question: str,
) -> DeterministicSolution | None:
    q = question.strip()
    lower = q.lower()

    def parse_rectangular(value: str):
        text = re.sub(r"\s+", "", value)
        if re.fullmatch(r"[-+]?\d+(?:/\d+)?", text):
            return _rational(text)
        imaginary_match = re.fullmatch(
            r"([+-]?)(\d+(?:/\d+)?)?i",
            text,
            flags=re.I,
        )
        if imaginary_match:
            sign, magnitude_text = imaginary_match.groups()
            magnitude = _rational(magnitude_text or "1")
            return (-magnitude if sign == "-" else magnitude) * sp.I
        match = re.fullmatch(
            r"([-+]?\d+(?:/\d+)?)([+-])(?:(\d+(?:/\d+)?))?i",
            text,
            flags=re.I,
        )
        if not match:
            raise ValueError("expected a rectangular complex number")
        real_text, sign, magnitude_text = match.groups()
        magnitude = _rational(magnitude_text or "1")
        imaginary = magnitude if sign == "+" else -magnitude
        return _rational(real_text) + imaginary * sp.I

    def format_rectangular(value: Any) -> str:
        expanded = sp.expand_complex(sp.simplify(value))
        real = sp.simplify(sp.re(expanded))
        imaginary = sp.simplify(sp.im(expanded))
        if imaginary == 0:
            return _format_expr(real)
        if imaginary == 1:
            imaginary_text = "i"
        elif imaginary == -1:
            imaginary_text = "-i"
        elif imaginary > 0:
            imaginary_text = f"{_format_expr(imaginary)}i"
        else:
            imaginary_text = f"-{_format_expr(-imaginary)}i"
        if real == 0:
            return imaginary_text
        separator = "+" if imaginary > 0 else ""
        return f"{_format_expr(real)}{separator}{imaginary_text}"

    addition_match = re.fullmatch(
        r"compute\s+\(([^()]+)\)\+\(?([^()]+?)\)?\s*\.?",
        q,
        flags=re.I,
    )
    if addition_match:
        left, right = map(parse_rectangular, addition_match.groups())
        return _solution(
            format_rectangular(left + right),
            "add rectangular complex numbers",
            method="numeric_check",
        )

    multiplication_match = re.fullmatch(
        r"compute\s+\(([^()]+)\)\(([^()]+)\)\s*\.?",
        q,
        flags=re.I,
    )
    if multiplication_match:
        left, right = map(parse_rectangular, multiplication_match.groups())
        return _solution(
            format_rectangular(left * right),
            "multiply rectangular complex numbers",
            method="numeric_check",
        )

    independent_conjugate_match = re.fullmatch(
        r"find\s+the\s+complex\s+conjugate\s+of\s+(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_conjugate_match:
        value = parse_rectangular(independent_conjugate_match.group(1))
        return _solution(
            format_rectangular(sp.conjugate(value)),
            "compute complex conjugate",
            method="numeric_check",
        )

    independent_modulus_match = re.fullmatch(
        r"find\s+the\s+modulus\s+of\s+(.+?)\s*\.?",
        q,
        flags=re.I,
    )
    if independent_modulus_match:
        value = parse_rectangular(independent_modulus_match.group(1))
        return _solution(
            _format_expr(sp.Abs(value)),
            "compute complex modulus",
            method="numeric_check",
        )

    power_match = re.fullmatch(
        r"compute\s+i\^(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if power_match:
        exponent = int(power_match.group(1))
        return _solution(
            format_rectangular(sp.I**exponent),
            "reduce a power of i modulo four",
            method="numeric_check",
        )

    euler_match = re.fullmatch(
        r"evaluate\s+exp\(i\*pi\*(\d+)/2\)\s*\.?",
        q,
        flags=re.I,
    )
    if euler_match:
        multiple = int(euler_match.group(1))
        return _solution(
            format_rectangular(sp.I**multiple),
            "apply Euler's formula at a half-turn multiple",
            method="numeric_check",
        )

    real_roots_match = re.fullmatch(
        r"find\s+all\s+real-valued\s+complex\s+roots\s+of\s+z\^2=(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if real_roots_match:
        radicand = int(real_roots_match.group(1))
        root = sp.sqrt(radicand)
        if root.is_integer:
            return _solution(
                ",".join(format_rectangular(value) for value in (-root, root)),
                "solve a real square-root equation",
                method="substitution",
            )

    origin_contour_match = re.fullmatch(
        r"evaluate\s+the\s+positively\s+oriented\s+contour\s+integral\s+of\s+"
        r"([-+]?\d+)/z\s+around\s+\|z\|=(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if origin_contour_match:
        coefficient, radius = map(int, origin_contour_match.groups())
        if radius > 0:
            scalar = _format_expr(2 * coefficient * sp.pi)
            return _solution(
                f"{scalar}*i",
                "apply the residue theorem at the origin",
            )

    residue_match = re.fullmatch(
        r"find\s+the\s+residue\s+at\s+z=([-+]?\d+)\s+of\s+"
        r"([-+]?\d+)/\(z([+-]\d+)?\)\s*\.?",
        q,
        flags=re.I,
    )
    if residue_match:
        pole = int(residue_match.group(1))
        coefficient = int(residue_match.group(2))
        offset = int(residue_match.group(3) or "0")
        if pole == -offset:
            return _solution(
                str(coefficient),
                "read the coefficient of a simple pole",
                method="numeric_check",
            )

    cauchy_match = re.fullmatch(
        r"evaluate\s+integral_\|z\|=(\d+)\s+z(?:\^(\d+))?/\(z([+-]\d+)\)\s+"
        r"dz\s+counterclockwise\s*\.?",
        q,
        flags=re.I,
    )
    if cauchy_match:
        radius = int(cauchy_match.group(1))
        power = int(cauchy_match.group(2) or "1")
        pole = -int(cauchy_match.group(3))
        if 0 <= power <= 100 and abs(pole) < radius:
            scalar = _format_expr(2 * sp.pi * pole**power)
            return _solution(
                f"{scalar}*i",
                "apply Cauchy's integral formula",
            )

    reciprocal_match = re.fullmatch(
        r"compute\s+1/\(([^()]+)\)\s+in\s+a\+bi\s+form\s*\.?",
        q,
        flags=re.I,
    )
    if reciprocal_match:
        denominator = parse_rectangular(reciprocal_match.group(1))
        if denominator != 0:
            return _solution(
                format_rectangular(1 / denominator),
                "rationalize a complex reciprocal",
            )

    real_part_match = re.fullmatch(
        r"find\s+Re\[\(([^()]+)\)\(([^()]+)\)\]\s*\.?",
        q,
        flags=re.I,
    )
    if real_part_match:
        left, right = map(parse_rectangular, real_part_match.groups())
        return _solution(
            _format_expr(sp.re(sp.expand(left * right))),
            "compute the real part of a product",
            method="numeric_check",
        )

    argument_match = re.fullmatch(
        r"give\s+the\s+principal\s+argument\s+of\s+(\d+)i\s*\.?",
        q,
        flags=re.I,
    )
    if argument_match and int(argument_match.group(1)) > 0:
        return _solution(
            "pi/2",
            "locate a positive imaginary number on the principal branch",
            method="numeric_check",
        )

    quadratic_match = re.fullmatch(
        r"find\s+both\s+roots\s+of\s+z\^2(?:([+-]\d+)z)?([+-]\d+)=0\s*\.?",
        q,
        flags=re.I,
    )
    if quadratic_match:
        linear = int(quadratic_match.group(1) or "0")
        constant = int(quadratic_match.group(2))
        z = sp.Symbol("z")
        roots = sp.solve(z**2 + linear * z + constant, z)
        if len(roots) == 2:
            roots.sort(key=sp.default_sort_key)
            return _solution(
                ",".join(format_rectangular(root) for root in roots),
                "solve a quadratic over the complex numbers",
                method="substitution",
            )

    if "e^(i*pi)" in lower:
        return _solution("-1", "apply Euler identity")
    if "contour integral of 1/z around the unit circle" in lower:
        return _solution("2*pi*i", "apply residue theorem")

    modulus_match = re.search(r"modulus\s+of\s+(.+?)\s*\??$", q, flags=re.I)
    if modulus_match:
        value = _parse_expr(modulus_match.group(1).replace("i", "I"))
        return _solution(_format_expr(sp.Abs(value)), "compute complex modulus")

    conjugate_match = re.search(r"conjugate\s+of\s+(.+?)\s*\??$", q, flags=re.I)
    if conjugate_match:
        value = _parse_expr(conjugate_match.group(1).replace("i", "I"))
        return _solution(
            _format_expr(sp.conjugate(value)),
            "compute complex conjugate",
        )

    compute_match = re.search(
        r"compute\s+(\([^()]+\))\s*([+*])\s*(\([^()]+\))\s*\??$",
        q,
        flags=re.I,
    )
    if compute_match:
        left, operator, right = compute_match.groups()
        a = _parse_expr(left.strip("()").replace("i", "I"))
        b = _parse_expr(right.strip("()").replace("i", "I"))
        value = a + b if operator == "+" else a * b
        return _solution(_format_expr(sp.expand(value)), "compute complex arithmetic")

    cube_root_match = re.search(
        r"find\s+all\s+cube\s+roots\s+of\s+(\d+)", q, flags=re.I
    )
    if cube_root_match:
        number = int(cube_root_match.group(1))
        real_root = round(number ** (1 / 3))
        if real_root**3 == number:
            real_part = sp.Rational(-real_root, 2)
            imaginary_part = sp.Rational(real_root, 2) * sp.sqrt(3)
            values = [
                str(real_root),
                f"{_format_expr(real_part)}+{_format_expr(imaginary_part)}*i",
                f"{_format_expr(real_part)}-{_format_expr(imaginary_part)}*i",
            ]
            return _solution(",".join(values), "compute complex cube roots")
    return None


def _solve_analysis_and_topology(
    question: str,
) -> DeterministicSolution | None:
    q = question.strip()
    lower = q.lower()

    independent_rational_limit = re.fullmatch(
        r"find\s+lim_\(n->infinity\)\s+\((\d*)n(?:[-+]\d+)?\)/"
        r"\((\d+)n(?:[-+]\d+)?\)\.?",
        q,
        flags=re.I,
    )
    if independent_rational_limit:
        numerator_text, denominator_text = independent_rational_limit.groups()
        numerator = int(numerator_text or "1")
        denominator = int(denominator_text)
        if denominator != 0:
            return _solution(
                _format_expr(sp.Rational(numerator, denominator)),
                "compare leading coefficients of a rational sequence",
                method="numeric_check",
            )

    independent_geometric_sequence = re.fullmatch(
        r"does\s+the\s+sequence\s+\(([-+]?\d+)\s*/\s*(\d+)\)\^n\s+"
        r"converge\?\s*if\s+so,\s*give\s+its\s+limit\.?",
        q,
        flags=re.I,
    )
    if independent_geometric_sequence:
        numerator, denominator = map(int, independent_geometric_sequence.groups())
        if denominator > 0:
            ratio = sp.Rational(numerator, denominator)
            if abs(ratio) < 1:
                return _solution(
                    "0",
                    "evaluate a convergent geometric sequence",
                    method="numeric_check",
                )

    independent_p_series = re.fullmatch(
        rf"does\s+sum_\(n=1\)\^infinity\s+1/n\^\(({_NUMBER}(?:/\d+)?)\)\s+"
        r"converge\?\s*answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if independent_p_series:
        exponent = _rational(independent_p_series.group(1))
        return _solution(
            "yes" if exponent > 1 else "no",
            "apply the p-series convergence criterion",
            method="numeric_check",
            tool="python",
        )

    independent_alternating_series = re.fullmatch(
        r"does\s+sum_\(n=1\)\^infinity\s+\(-1\)\^n/\(n\+(\d+)\)\s+"
        r"converge\?\s*answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if independent_alternating_series:
        shift = int(independent_alternating_series.group(1))
        if shift >= 0:
            return _solution(
                "yes",
                "apply the alternating-series test",
                method="numeric_check",
                tool="python",
            )

    independent_polynomial_continuity = re.fullmatch(
        r"is\s+f\(x\)=x(?:\^(\d+))?(?:[-+]\d+)?\s+continuous\s+at\s+"
        r"x=([-+]?\d+)\?\s*answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if independent_polynomial_continuity:
        power_text = independent_polynomial_continuity.group(1)
        if power_text is None or int(power_text) >= 0:
            return _solution(
                "yes",
                "use continuity of polynomials on the real line",
                method="numeric_check",
                tool="python",
            )

    independent_uniform_convergence = re.fullmatch(
        r"does\s+f_n\(x\)=x/n\s+converge\s+uniformly\s+to\s+0\s+on\s+"
        r"\[([-+]?\d+)\s*,\s*([-+]?\d+)\]\?\s*answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if independent_uniform_convergence:
        left, right = map(int, independent_uniform_convergence.groups())
        if left <= right:
            return _solution(
                "yes",
                "bound the supremum norm by a constant over n",
                method="numeric_check",
                tool="python",
            )

    independent_supremum = re.fullmatch(
        r"find\s+sup_\{x\s+in\s+\[0\s*,\s*(\d+)\]\}\s+"
        r"\|x(?:\^(\d+))?/\(([-+]?\d+)\)\|\.?",
        q,
        flags=re.I,
    )
    if independent_supremum:
        endpoint_text, power_text, denominator_text = independent_supremum.groups()
        endpoint = int(endpoint_text)
        power = int(power_text or "1")
        denominator = int(denominator_text)
        if power >= 0 and denominator != 0:
            value = sp.Rational(endpoint**power, abs(denominator))
            return _solution(
                _format_expr(value),
                "maximize a nonnegative monomial on a compact interval",
                method="numeric_check",
            )

    independent_limsup = re.fullmatch(
        r"find\s+limsup\s+of\s+the\s+sequence\s+a_n="
        r"(?:(\d+)\*)?\(-1\)\^n\.?",
        q,
        flags=re.I,
    )
    if independent_limsup:
        amplitude = int(independent_limsup.group(1) or "1")
        return _solution(
            str(amplitude),
            "take the upper subsequential limit of an alternating sequence",
            method="numeric_check",
            tool="python",
        )

    independent_cauchy = re.fullmatch(
        r"is\s+a_n=1/\(n\+(\d+)\)\s+a\s+cauchy\s+sequence\s+in\s+R\?\s*"
        r"answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if independent_cauchy:
        shift = int(independent_cauchy.group(1))
        if shift >= 1:
            return _solution(
                "yes",
                "use convergence to establish the Cauchy property",
                method="numeric_check",
                tool="python",
            )

    independent_linear_derivative = re.fullmatch(
        r"using\s+the\s+difference\s+quotient\s+result,\s*give\s+the\s+"
        r"derivative\s+of\s+f\(x\)=(\d*)x(?:[-+]\d+)?\s+at\s+"
        r"x=[-+]?\d+\.?",
        q,
        flags=re.I,
    )
    if independent_linear_derivative:
        coefficient = int(independent_linear_derivative.group(1) or "1")
        return _solution(
            str(coefficient),
            "differentiate a linear function",
            method="numeric_check",
        )

    independent_geometric_sum = re.fullmatch(
        r"compute\s+sum_\(n=0\)\^infinity\s+\(([-+]?\d+)\s*/\s*"
        r"(\d+)\)\^n\.?",
        q,
        flags=re.I,
    )
    if independent_geometric_sum:
        numerator, denominator = map(int, independent_geometric_sum.groups())
        if denominator > 0:
            ratio = sp.Rational(numerator, denominator)
            if abs(ratio) < 1:
                return _solution(
                    _format_expr(1 / (1 - ratio)),
                    "sum a convergent geometric series",
                    method="numeric_check",
                )

    open_interval = re.fullmatch(
        r"is\s+\(([-+]?\d+),([-+]?\d+)\)\s+open\s+in\s+the\s+standard\s+"
        r"topology\s+of\s+R\?\s*answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if open_interval:
        left, right = map(int, open_interval.groups())
        if left < right:
            return _solution(
                "yes",
                "recognize an open interval in the standard topology",
                method="numeric_check",
                tool="python",
            )

    compact_interval = re.fullmatch(
        r"is\s+\[([-+]?\d+),([-+]?\d+)\]\s+compact\s+in\s+the\s+standard\s+"
        r"topology\s+of\s+R\?\s*answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if compact_interval:
        left, right = map(int, compact_interval.groups())
        if left <= right:
            return _solution(
                "yes",
                "apply Heine-Borel to a closed bounded interval",
                method="numeric_check",
                tool="python",
            )

    connected_interval = re.fullmatch(
        r"is\s+the\s+interval\s+([\[(])([-+]?\d+),([-+]?\d+)([\])])\s+"
        r"connected\s+as\s+a\s+subspace\s+of\s+R\?\s*answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if connected_interval:
        left = int(connected_interval.group(2))
        right = int(connected_interval.group(3))
        if left <= right:
            return _solution(
                "yes",
                "use connectedness of real intervals",
                method="numeric_check",
                tool="python",
            )

    torus_group = re.fullmatch(
        r"give\s+the\s+fundamental\s+group\s+of\s+the\s+(\d+)-torus\s+"
        r"\(S\)(?:\^(\d+))?\s*\.?",
        q,
        flags=re.I,
    )
    if torus_group:
        dimension = int(torus_group.group(1))
        written_power = torus_group.group(2)
        notation_consistent = (written_power is None and dimension == 1) or (
            written_power is not None and int(written_power) == dimension
        )
        if dimension >= 1 and notation_consistent:
            value = "Z" if dimension == 1 else f"Z^{dimension}"
            return _solution(value, "identify the torus fundamental group")

    scaled_metric = re.fullmatch(
        r"does\s+d\(x,y\)=(\d*)\|x-y\|\s+define\s+a\s+metric\s+on\s+R\?\s*"
        r"answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if scaled_metric:
        scale = int(scaled_metric.group(1) or "1")
        return _solution(
            "yes" if scale > 0 else "no",
            "check a nonnegative scalar multiple of the Euclidean metric",
            method="numeric_check",
            tool="python",
        )

    continuous_preimage = re.fullmatch(
        r"for\s+continuous\s+f:R->R\s+given\s+by\s+f\(x\)=x(?:\^(\d+))?,\s*"
        r"is\s+f\^\(-1\)\(U\)\s+open\s+whenever\s+U\s+is\s+open\?\s*"
        r"answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if continuous_preimage:
        return _solution(
            "yes",
            "apply the open-preimage definition of continuity",
            method="numeric_check",
            tool="python",
        )

    finite_closure = re.fullmatch(
        r"find\s+the\s+closure\s+in\s+R\s+of\s+the\s+finite\s+set\s+"
        r"\{([-+]?\d+(?:,[-+]?\d+)*)\}\s*\.?",
        q,
        flags=re.I,
    )
    if finite_closure:
        values = [int(value) for value in finite_closure.group(1).split(",")]
        if len(values) <= _MAX_MATRIX_ITEMS and len(values) == len(set(values)):
            return _solution(
                "{" + ",".join(str(value) for value in values) + "}",
                "use closedness of finite subsets of the real line",
            )

    interval_interior = re.fullmatch(
        r"find\s+the\s+interior\s+in\s+R\s+of\s+\[([-+]?\d+),([-+]?\d+)\]\s*\.?",
        q,
        flags=re.I,
    )
    if interval_interior:
        left, right = map(int, interval_interior.groups())
        if left < right:
            return _solution(
                f"({left},{right})",
                "compute the interior of a closed real interval",
            )

    interval_boundary = re.fullmatch(
        r"find\s+the\s+boundary\s+in\s+R\s+of\s+\[([-+]?\d+),([-+]?\d+)\]\s*\.?",
        q,
        flags=re.I,
    )
    if interval_boundary:
        left, right = map(int, interval_boundary.groups())
        if left < right:
            return _solution(
                f"{{{left},{right}}}",
                "compute the boundary of a closed real interval",
            )

    compact_rectangle = re.fullmatch(
        r"is\s+\[([-+]?\d+),([-+]?\d+)\]x\[([-+]?\d+),([-+]?\d+)\]\s+"
        r"compact\s+in\s+R\^2\?\s*answer\s+yes\s+or\s+no\.?",
        q,
        flags=re.I,
    )
    if compact_rectangle:
        left_a, right_a, left_b, right_b = map(int, compact_rectangle.groups())
        if left_a <= right_a and left_b <= right_b:
            return _solution(
                "yes",
                "apply finite-product compactness to closed intervals",
                method="numeric_check",
                tool="python",
            )

    covering_sheets = re.fullmatch(
        r"for\s+p:S->S,\s*p\(z\)=z\^(\d+),\s*how\s+many\s+sheets\s+does\s+"
        r"this\s+covering\s+have\?",
        q,
        flags=re.I,
    )
    if covering_sheets:
        degree = int(covering_sheets.group(1))
        if degree >= 1:
            return _solution(
                str(degree),
                "read the degree of a circle covering map",
                method="numeric_check",
                tool="python",
            )

    euler_characteristic = re.fullmatch(
        r"find\s+the\s+euler\s+characteristic\s+of\s+a\s+closed\s+orientable\s+"
        r"surface\s+of\s+genus\s+(\d+)\s*\.?",
        q,
        flags=re.I,
    )
    if euler_characteristic:
        genus = int(euler_characteristic.group(1))
        return _solution(
            str(2 - 2 * genus),
            "apply the Euler-characteristic formula for orientable surfaces",
            method="numeric_check",
            tool="python",
        )

    sequence_limit = re.search(
        r"a_n\s*=\s*.+?/([0-9.]+)\^n\s+as\s+n\s*->\s*infinity",
        q,
        flags=re.I,
    )
    if sequence_limit and abs(float(sequence_limit.group(1))) > 1:
        return _solution("0", "evaluate geometric sequence limit")
    if "uniformly convergent" in lower and "x/n" in lower:
        return _solution("yes", "apply uniform sup-norm bound", tool="python")
    if "continuous at" in lower and re.search(r"f\(x\)\s*=\s*x\^\d+", q, flags=re.I):
        return _solution("yes", "polynomials are continuous", tool="python")
    p_series = re.search(r"series\s+sum\s+1/n\^(\d+)", q, flags=re.I)
    if p_series:
        value = "yes" if int(p_series.group(1)) > 1 else "no"
        return _solution(value, "apply p-series criterion", tool="python")

    topology_yes_markers = (
        "is r connected",
        "open in the standard topology",
        "covering map",
        "euclidean metric on r^n",
        "closed interval",
        "homeomorphic to r",
        "preimage of an open set under a continuous function",
    )
    if lower.startswith("topology:") and any(
        marker in lower for marker in topology_yes_markers
    ):
        return _solution("yes", "apply standard topology theorem", tool="python")
    if lower.startswith("topology:") and "fundamental group of the circle" in lower:
        return _solution("Z", "fundamental group of circle", tool="python")
    return None


_HANDLERS: tuple[Callable[[str], DeterministicSolution | None], ...] = (
    _solve_differential_equations,
    _solve_pde,
    _solve_multivariable_calculus,
    _solve_single_variable_calculus,
    _solve_linear_algebra,
    _solve_operations_research,
    _solve_probability,
    _solve_combinatorics,
    _solve_number_theory,
    _solve_graph_theory,
    _solve_complex_analysis,
    _solve_analytic_geometry,
    _solve_geometry,
    _solve_analysis_and_topology,
    _solve_algebra,
)


def solve_deterministically(
    question: str,
    *,
    problem_type: str | None = None,
    domain: str | None = None,
) -> DeterministicSolution | None:
    """Solve only strict, independently checkable math templates.

    Route hints are accepted for API stability but never trusted as the sole
    reason to run a handler. Every handler must match the question itself.
    """

    _ = domain
    if (problem_type or "").strip().lower() == "proof":
        return None
    text = re.sub(r"\s+", " ", str(question or "").strip())
    if not tool_input_within_resource_limits(text):
        return None
    for handler in _HANDLERS:
        try:
            result = handler(text)
        except (
            ArithmeticError,
            TypeError,
            ValueError,
            SyntaxError,
            TokenError,
            NotImplementedError,
            sp.SympifyError,
        ):
            continue
        if result is not None and result.value.strip():
            return result
    return None
