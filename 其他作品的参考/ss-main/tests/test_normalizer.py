"""Tests for answer normalizer."""

from config import MAX_FINAL_RESPONSE_CHARS
from tools.answer_normalizer import (
    ensure_non_empty,
    normalize_final_response,
    normalize_whitespace,
    strip_markdown_fence,
    truncate_text,
)


def test_none_to_fallback():
    assert normalize_final_response(None) == "无法确定"


def test_empty_to_fallback():
    assert normalize_final_response("") == "无法确定"
    assert normalize_final_response("   ") == "无法确定"


def test_strip_markdown_fence():
    text = "```json\n72\n```"
    assert strip_markdown_fence(text) == "72"
    assert normalize_final_response(text) == "72"


def test_normalize_whitespace():
    assert normalize_whitespace("  hello   world  ") == "hello world"
    assert normalize_whitespace("a\n\n\nb") == "a\nb"


def test_truncate_long_text():
    long_text = "x" * (MAX_FINAL_RESPONSE_CHARS + 100)
    result = truncate_text(long_text)
    assert len(result) <= MAX_FINAL_RESPONSE_CHARS
    assert result.endswith("...")


def test_ensure_non_empty():
    assert ensure_non_empty(None) == "无法确定"
    assert ensure_non_empty("hello") == "hello"


def test_remove_prefix():
    assert normalize_final_response("最终答案：72") == "72"
