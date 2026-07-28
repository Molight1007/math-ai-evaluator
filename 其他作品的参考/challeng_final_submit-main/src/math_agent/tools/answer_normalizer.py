from __future__ import annotations

import re
from fractions import Fraction

_MAX_NORMALIZE_CHARS = 10_000

_ANSWER_PATTERNS = [
    r"final\s*answer\s*[:：]\s*(.+)$",
    r"answer\s*[:：]\s*(.+)$",
    r"result\s*[:：]\s*(.+)$",
    r"最终答案\s*[：:]\s*(.+)$",
    r"最终结论\s*[：:]\s*(.+)$",
    r"答案\s*[：:]\s*(.+)$",
    r"\*\*答案\*\*\s*[：:]\s*(.+)$",
    r"answer\s*[:：]\s*(.+)$",
    r"final_answer\.value\s*[=:：]\s*(.+)$",
    r"解为\s*(.+)$",
    r"解得\s*(.+)$",
    r"所以\s*(.+)$",
]


def _extract_braced_content(text: str, open_idx: int) -> tuple[str, int] | None:
    if open_idx < 0 or open_idx >= len(text) or text[open_idx] != "{":
        return None
    depth = 0
    chars: list[str] = []
    for idx in range(open_idx, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
            if depth > 1:
                chars.append(ch)
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(chars), idx
            if depth < 0:
                return None
            chars.append(ch)
            continue
        if depth >= 1:
            chars.append(ch)
    return None


def extract_boxed_answers(text: str) -> list[str]:
    if not text:
        return []
    needle = r"\boxed"
    start = 0
    matches: list[str] = []
    while True:
        pos = text.find(needle, start)
        if pos < 0:
            break
        brace_pos = pos + len(needle)
        while brace_pos < len(text) and text[brace_pos].isspace():
            brace_pos += 1
        if brace_pos < len(text) and text[brace_pos] == "{":
            parsed = _extract_braced_content(text, brace_pos)
            if parsed is not None:
                content, end_pos = parsed
                cleaned = content.strip().replace("\\\\", "\\")
                if cleaned:
                    matches.append(cleaned)
                start = end_pos + 1
                continue
        start = pos + len(needle)
    return matches


def extract_boxed_answer(text: str) -> str | None:
    matches = extract_boxed_answers(text)
    if matches:
        return matches[-1]
    return None


def extract_answer_by_patterns(text: str) -> str | None:
    if not text:
        return None
    cleaned_text = text.replace("**", "")
    for pattern in _ANSWER_PATTERNS:
        matched = re.search(pattern, cleaned_text, flags=re.I | re.M)
        if matched:
            candidate = _clean_extracted_answer(matched.group(1))
            if candidate:
                return candidate
    return None


def _clean_extracted_answer(raw: str) -> str:
    candidate = (raw or "").strip()
    candidate = candidate.replace("**", "").strip()
    if "。" in candidate:
        candidate = candidate.split("。", 1)[0].strip()
    candidate = re.sub(r"^\$+\s*(.*?)\s*\$+$", r"\1", candidate)
    candidate = candidate.strip("` ").strip()
    candidate = re.sub(r"\s+", " ", candidate)
    if len(candidate) > 160 or "```" in candidate or "###" in candidate:
        return ""
    return candidate


def _replace_latex_fractions(value: str) -> str:
    text = value
    for command in ("dfrac", "frac"):
        pattern = re.compile(rf"\\{command}\s*\{{([^{{}}]+)\}}\s*\{{([^{{}}]+)\}}")
        while True:
            updated = pattern.sub(
                lambda m: f"{m.group(1).strip()}/{m.group(2).strip()}",
                text,
            )
            if updated == text:
                break
            text = updated
    return text


def _compact_math_spacing(value: str) -> str:
    text = re.sub(r"\s*([=+\-*/,\[\]\(\)])\s*", r"\1", value.strip())
    text = re.sub(r"\s+", " ", text)
    has_multiword_prose = bool(
        re.search(r"[A-Za-z]{2,}\s+[A-Za-z]{2,}", text)
    )
    if re.search(r"[=+\-*/\[\]\(\)\d]", text) and not has_multiword_prose:
        text = text.replace(" ", "")
    return text


def _insert_implicit_multiplication(value: str) -> str:
    text = value
    text = re.sub(r"(?<=\d)(?=pi\b)", "*", text, flags=re.I)
    text = re.sub(r"(?<=\d)(?=[a-zA-Z])", "*", text)
    text = re.sub(
        r"(?<=[A-Z])(?=(?:e|sin|cos|tan|log|sqrt)\b)",
        "*",
        text,
    )
    text = re.sub(r"\)(?=\d|[a-zA-Z])", ")*", text)
    text = re.sub(r"(?<=\d)\(", "*(", text)
    text = re.sub(r"\)\(", ")*(", text)
    text = text.replace("**", "__POW__")
    text = re.sub(r"\*+", "*", text)
    return text.replace("__POW__", "**")


def strip_units(text: str) -> str:
    value = text.strip()
    return re.sub(
        r"(?<=\d)\s*(cm|mm|m|km|kg|g|mg|s|sec|celsius|dollars|usd|%)$",
        "",
        value,
        flags=re.I,
    ).strip()


def normalize_latex(text: str) -> str:
    value = text.strip()
    value = value.strip("$")
    value = value.replace("\\left", "").replace("\\right", "")
    value = re.sub(r"\\(?:text|mathrm)\s*\{([^{}]+)\}", r"\1", value)
    value = _replace_latex_fractions(value)
    value = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", value)
    value = re.sub(r"sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", value)
    value = value.replace("\\cdot", "*").replace("\\times", "*")
    value = value.replace("\\pi", "pi").replace("π", "pi")
    value = value.replace("^", "**")
    value = value.replace("\\", "")
    return value.strip()


def normalize_number(text: str) -> str:
    value = text.strip()
    if re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", value):
        value = value.replace(",", "")
    value = re.sub(
        r"(?<![\d.])([-+]?\d+)\.0+(?=($|[+\-*/\)]))",
        lambda m: m.group(1),
        value,
    )
    value = re.sub(r"(?<!\d)1\*pi\b", "pi", value)
    if re.fullmatch(r"[-+]?\d+\.0+", value):
        return str(int(float(value)))
    if re.fullmatch(r"[-+]?\d*\.\d+", value):
        normalized = str(float(value)).rstrip("0").rstrip(".")
        return normalized if normalized else "0"
    return value


def normalize_answer(text: str) -> str:
    if len(str(text or "")) > _MAX_NORMALIZE_CHARS:
        return ""
    boxed = extract_boxed_answer(text)
    if boxed is not None:
        candidate = boxed
    else:
        candidate = text
        extracted = extract_answer_by_patterns(text)
        if extracted is not None:
            candidate = extracted

    candidate = strip_units(candidate)
    candidate = normalize_latex(candidate)
    candidate = _compact_math_spacing(candidate)
    candidate = _insert_implicit_multiplication(candidate)
    candidate = normalize_number(candidate)
    return candidate.strip()


_ROOT_LIST_TYPES = {
    "absolute_value",
    "polynomial",
    "quadratic",
    "quadratic_equation",
}
_SYSTEM_TYPES = {"linear_system", "nonlinear_system", "system"}


def _sortable_scalar(value: str) -> tuple[int, object, str]:
    text = value.strip()
    try:
        return (0, Fraction(text), text)
    except (ValueError, ZeroDivisionError):
        return (1, text.casefold(), text)


def _split_flat_sequence(value: str) -> list[str]:
    text = value.strip()
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        text = text[1:-1].strip()
    if not text or any(token in text for token in ("[[", "]]", ";")):
        return []
    parts = [part.strip() for part in text.split(",")]
    return parts if len(parts) >= 2 and all(parts) else []


def canonicalize_final_answer(
    text: str,
    *,
    problem_type: str = "",
    question: str = "",
) -> str:
    """Return a compact, stable answer representation for protocol output.

    This is deliberately conservative: brackets are removed only for equation
    roots and systems, where the benchmark expects a comma-separated answer.
    Matrix, interval, vector, and set notation remain intact.
    """

    value = normalize_answer(str(text or ""))
    if not value:
        return ""

    value = re.sub(r"\s*(<=|>=|=|<|>)\s*", r"\1", value)
    ptype = (problem_type or "").strip().lower()
    qlower = (question or "").lower()
    parts = _split_flat_sequence(value)

    is_root_list = ptype in _ROOT_LIST_TYPES or (
        parts
        and any(token in qlower for token in ("find roots", "find root", "solve:"))
        and not any("=" in part and not part.lower().startswith("x=") for part in parts)
    )
    if parts and is_root_list:
        roots = [
            re.sub(r"^x\s*=\s*", "", part, flags=re.I).strip()
            for part in parts
        ]
        roots.sort(key=_sortable_scalar)
        value = ",".join(roots)
    elif parts and ptype in _SYSTEM_TYPES:
        assignments = [part.strip() for part in parts]
        assignments.sort(key=lambda part: part.split("=", 1)[0].casefold())
        value = ",".join(assignments)

    if value.casefold() in {"yes", "no"}:
        return value.casefold()
    return value.replace("**", "^").strip()
