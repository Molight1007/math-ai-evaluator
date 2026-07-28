"""Tests for answer extraction."""

from tools.answer_extractor import (
    extract_after_markers,
    extract_boxed,
    extract_choice_answer,
    extract_final_answer,
    fallback_extract,
)


def test_extract_final_answer_marker():
    assert extract_final_answer("最终答案：72") == "72"


def test_extract_boxed():
    assert extract_boxed("\\boxed{72}") == "72"
    assert extract_final_answer("因此 \\boxed{72}") == "72"


def test_extract_choice():
    assert extract_choice_answer("所以答案是 B") == "B"
    assert extract_final_answer("分析各选项...\n最终答案：B") == "B"


def test_extract_long_text():
    text = "第一步：分析\n第二步：计算\n最终答案：100"
    assert extract_final_answer(text) == "100"


def test_fallback_extract():
    text = "这是一段很长的推理过程，没有明确标记。\n\n最后得到 55。"
    result = fallback_extract(text)
    assert result


def test_empty_text():
    assert extract_final_answer("") == ""
    assert extract_after_markers("") == ""


def test_extract_answer_english():
    assert extract_final_answer("Answer: 3.14") == "3.14"
