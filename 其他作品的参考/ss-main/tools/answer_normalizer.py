"""Normalize final_response for scoring."""

from __future__ import annotations

import re

from config import MAX_FINAL_RESPONSE_CHARS

FALLBACK_ANSWER = "无法确定"

MARKDOWN_FENCE_PATTERN = re.compile(
    r"```(?:json|python|text|latex|math)?\s*([\s\S]*?)```",
    re.IGNORECASE,
)
REDUNDANT_PREFIX_PATTERN = re.compile(
    r"^(?:final_response\s*=|答案\s*=|answer\s*=)\s*",
    re.IGNORECASE,
)


def normalize_whitespace(text: str) -> str:
    """Collapse excessive whitespace while preserving single newlines."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def strip_markdown_fence(text: str) -> str:
    """Remove markdown code fences."""
    if not text:
        return ""
    match = MARKDOWN_FENCE_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    text = re.sub(r"^```(?:json|python|text|latex|math)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def remove_redundant_prefix(text: str) -> str:
    """Remove redundant answer prefixes."""
    if not text:
        return ""
    text = REDUNDANT_PREFIX_PATTERN.sub("", text.strip())
    text = re.sub(r"^(?:最终答案|答案|Answer)[：:]\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def truncate_text(text: str, max_chars: int = MAX_FINAL_RESPONSE_CHARS) -> str:
    """Safely truncate long text."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def ensure_non_empty(text: str, fallback: str = FALLBACK_ANSWER) -> str:
    """Ensure text is a non-empty string."""
    if text is None:
        return fallback
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()
    if not text:
        return fallback
    return text


def normalize_final_response(text: str) -> str:
    """Full normalization pipeline for final_response."""
    text = ensure_non_empty(text, fallback="")
    if not text:
        return FALLBACK_ANSWER

    text = strip_markdown_fence(text)
    text = remove_redundant_prefix(text)
    text = normalize_whitespace(text)
    text = text.strip("\"'""''")
    text = truncate_text(text)
    return ensure_non_empty(text, fallback=FALLBACK_ANSWER)
