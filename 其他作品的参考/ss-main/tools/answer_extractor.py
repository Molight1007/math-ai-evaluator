"""Extract final answers from model output text."""

from __future__ import annotations

import re
from typing import Optional

BOXED_PATTERN = re.compile(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}")
CHOICE_PATTERN = re.compile(
    r"(?:最终答案|答案|Answer|正确选项|选项)[：:\s]*([A-Da-d])\b",
    re.IGNORECASE,
)
STANDALONE_CHOICE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])([A-D])(?![A-Za-z0-9])"
)
NUMERIC_PATTERN = re.compile(
    r"(-?\d+(?:\.\d+)?(?:/\d+)?|-?\d+/\d+)"
)

MARKER_PATTERNS = [
    re.compile(r"最终答案[：:]\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"答案[：:]\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"Answer[：:]\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"Therefore[,，]?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"Hence[,，]?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"Thus[,，]?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"因此[,，]?\s*(.+?)(?:\n|$)", re.IGNORECASE),
    re.compile(r"所以(?:答案)?[是為为]?\s*(.+?)(?:\n|$)", re.IGNORECASE),
]


def extract_boxed(text: str) -> str:
    """Extract content from \\boxed{...}."""
    if not text:
        return ""
    match = BOXED_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return ""


def extract_after_markers(text: str) -> str:
    """Extract answer after common answer markers."""
    if not text:
        return ""
    for pattern in MARKER_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).strip()
            candidate = candidate.rstrip("。.!！?？")
            if candidate:
                return candidate
    return ""


def extract_choice_answer(text: str) -> str:
    """Extract multiple-choice option letter."""
    if not text:
        return ""
    match = CHOICE_PATTERN.search(text)
    if match:
        return match.group(1).upper()
    matches = STANDALONE_CHOICE_PATTERN.findall(text)
    if matches:
        return matches[-1].upper()
    return ""


def extract_numeric_answer(text: str) -> str:
    """Extract the last numeric-looking token from text."""
    if not text:
        return ""
    matches = NUMERIC_PATTERN.findall(text)
    if matches:
        return matches[-1]
    return ""


def fallback_extract(text: str, max_chars: int = 500) -> str:
    """Fallback: use last non-empty paragraph or truncated text."""
    if not text:
        return ""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if paragraphs:
        last = paragraphs[-1]
        if len(last) > max_chars:
            return last[:max_chars].strip()
        return last
    stripped = text.strip()
    if len(stripped) > max_chars:
        return stripped[:max_chars].strip()
    return stripped


def extract_final_answer(
    text: str,
    problem_type: Optional[str] = None,
    answer_form: Optional[str] = None,
) -> str:
    """Extract final answer using prioritized rules."""
    if not text or not isinstance(text, str):
        return ""

    text = text.strip()
    if not text:
        return ""

    boxed = extract_boxed(text)
    if boxed:
        return boxed

    marker = extract_after_markers(text)
    if marker:
        return marker

    if problem_type == "choice" or answer_form == "option":
        choice = extract_choice_answer(text)
        if choice:
            return choice

    choice = extract_choice_answer(text)
    if choice and re.search(r"[A-Da-d][\.、\)]", text):
        return choice

    if problem_type in ("calculation", "fill_blank") or answer_form in (
        "integer",
        "rational",
    ):
        numeric = extract_numeric_answer(text)
        if numeric:
            return numeric

    return fallback_extract(text)
