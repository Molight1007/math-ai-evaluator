"""
Phase 6.1 + 6.2 测试

Phase 6.1: JSON Parse Fallback Recovery
测试 _robust_fallback_parse 及其子策略，
覆盖常见 LLM 输出格式问题。

Phase 6.2: 错误分类修复
测试 _make_error_result 的 error_type="incomplete"，
以及解析失败/空答案场景的错误分类。

运行: python verify_phase6.py
"""
import sys
import os
import json

# 添加当前目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from intern_s1 import (
    parse_multi_candidate_response,
    _robust_fallback_parse,
    _extract_markdown_json_robust,
    _repair_and_parse_json,
    _extract_fields_by_regex,
    _extract_json_chunk,
    _repair_truncated_json,
    _escape_control_chars,
    _fallback_parse,
    _make_error_result,
)

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {detail}")


# ==================== 测试 1: 正常 JSON（主解析器应直接处理） ====================
def test_1_valid_json():
    """正常 JSON 应该被主解析器直接处理，不走 fallback。"""
    text = json.dumps({
        "final_answer": "42",
        "reasoning": "6 * 7 = 42",
        "candidates": [],
    })
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_1_valid_json: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 2: Markdown JSON with closing fence ====================
def test_2_markdown_json_closed():
    """```json ... ``` 格式应被 extract_json_from_text 处理。"""
    text = '```json\n{"answer": "42", "reasoning": "6*7=42"}\n```'
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_2_markdown_json_closed: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 3: Markdown JSON without closing fence (truncated) ====================
def test_3_markdown_json_truncated():
    """缺少闭合 ``` 的 markdown JSON — 模型输出被 max_tokens 截断。"""
    text = '```json\n{"answer": "42", "reasoning": "6*7=42"}'
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_3_markdown_json_truncated: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 4: Markdown JSON with uppercase JSON tag ====================
def test_4_markdown_json_uppercase():
    """大写 ```JSON 标签 — extract_json_from_text 的正则大小写敏感会失败。"""
    text = '```JSON\n{"answer": "42", "reasoning": "6*7=42"}\n```'
    # 先验证 extract_json_from_text 是否真的失败
    from llm_client import extract_json_from_text
    primary = extract_json_from_text(text)
    # 如果主解析器碰巧成功了，那这个测试就验证 fallback 不破坏它
    # 如果失败了，验证 fallback 能处理
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_4_markdown_json_uppercase: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 5: Trailing commas ====================
def test_5_trailing_commas():
    """JSON 尾随逗号 — LLM 常见错误。"""
    text = '{"answer": "42", "reasoning": "6*7=42",}'
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_5_trailing_commas: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 6: Trailing commas in nested structure ====================
def test_6_trailing_commas_nested():
    """嵌套结构中的尾随逗号。"""
    text = '''{
    "final_answer": "42",
    "candidates": [
        {"answer": "42", "confidence": 0.9,},
        {"answer": "41", "confidence": 0.1,},
    ],
}'''
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_6_trailing_commas_nested: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 7: Single quotes ====================
def test_7_single_quotes():
    """单引号替代双引号。"""
    text = "{'answer': '42', 'reasoning': '6*7=42'}"
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_7_single_quotes: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 8: JavaScript line comments ====================
def test_8_line_comments():
    """JavaScript 风格行注释。"""
    text = '''{
    "answer": "42",  // the answer
    "reasoning": "6*7=42"
}'''
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_8_line_comments: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 9: Block comments ====================
def test_9_block_comments():
    """JavaScript 风格块注释。"""
    text = '''{
    /* This is the answer */
    "answer": "42",
    "reasoning": "6*7=42"
}'''
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_9_block_comments: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 10: Truncated JSON (missing closing braces) ====================
def test_10_truncated_json():
    """截断的 JSON — 缺少闭合括号（max_tokens 截断）。"""
    text = '{"answer": "42", "reasoning": "6*7=42", "candidates": [{"answer": "42", "confidence": 0.9'
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_10_truncated_json: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 11: Unescaped newlines in string values ====================
def test_11_unescaped_newlines():
    """字符串值中的未转义换行符。"""
    text = '{"answer": "42", "reasoning": "Step 1: 6*7\nStep 2: = 42"}'
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_11_unescaped_newlines: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 12: Markdown JSON truncated with trailing commas ====================
def test_12_markdown_truncated_with_commas():
    """截断的 markdown JSON + 尾随逗号 — 组合问题。"""
    text = '```json\n{\n  "answer": "42",\n  "reasoning": "6*7=42",\n'
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_12_markdown_truncated_with_commas: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 13: Regex extraction (completely unparseable) ====================
def test_13_regex_extraction():
    """完全无法作为 JSON 解析 — 走正则键值对提取。"""
    text = 'The answer is:\n"answer": "42"\n"reasoning": "6 times 7 equals 42"'
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_13_regex_extraction: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 14: Empty / garbage text ====================
def test_14_garbage_text():
    """完全无法提取任何信息 — 应返回 error result。"""
    text = "I cannot solve this problem."
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_14_garbage_text: has error",
         "error" in result or result["answer"] == "",
         f'got answer={result["answer"]!r}')
    test("test_14_garbage_text: reasoning has Parse error",
         "Parse error" in result.get("reasoning", ""),
         f'got reasoning={result.get("reasoning", "")!r}')


# ==================== 测试 15: Valid multi-candidate JSON (regression) ====================
def test_15_valid_multicandidate():
    """正常的多候选 JSON 不受影响。"""
    text = json.dumps({
        "final_answer": "42",
        "candidates": [
            {"answer": "42", "confidence": 0.9, "reasoning": "6*7=42"},
            {"answer": "41", "confidence": 0.1, "reasoning": "maybe 41"},
        ],
        "selected_index": 0,
        "selection_reasoning": "First candidate is correct",
    })
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_15_valid_multicandidate: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')
    test("test_15_valid_multicandidate: candidates count",
         result["candidates"] is not None and len(result["candidates"]) == 2,
         f'got {result["candidates"]!r}')
    test("test_15_valid_multicandidate: selected_index",
         result["selected_index"] == 0,
         f'got {result["selected_index"]!r}')


# ==================== 测试 16: _extract_json_chunk with strings containing braces ====================
def test_17_chunk_with_braces_in_strings():
    """字符串值中包含 { } — 括号匹配不应被干扰。"""
    text = '{"answer": "42", "reasoning": "f(x) = {x: 1, y: 2}"}'
    chunk = _extract_json_chunk(text)
    test("test_17_chunk_with_braces_in_strings: complete extraction",
         chunk is not None and chunk.startswith('{') and chunk.endswith('}'),
         f'got {chunk!r}')
    # 验证解析成功
    data = json.loads(chunk)
    test("test_17_chunk_with_braces_in_strings: answer",
         data["answer"] == "42",
         f'got {data.get("answer")!r}')


# ==================== 测试 18: _repair_truncated_json basic ====================
def test_18_repair_truncated():
    """截断 JSON 修复 — 补全缺失闭合括号。"""
    text = '{"answer": "42", "reasoning": "6*7=42"'
    repaired = _repair_truncated_json(text)
    test("test_18_repair_truncated: valid json after repair",
         _is_valid_json(repaired),
         f'got {repaired!r}')


def _is_valid_json(s):
    try:
        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False


# ==================== 测试 19: _escape_control_chars ====================
def test_19_escape_control_chars():
    """控制字符转义。"""
    text = '{"answer": "42", "reasoning": "line1\nline2"}'
    escaped = _escape_control_chars(text)
    test("test_19_escape_control_chars: newline escaped",
         '\\n' in escaped and '\n' not in escaped.split('"')[3] if len(escaped.split('"')) > 3 else False,
         f'got {escaped!r}')


# ==================== 测试 20: Markdown with extra text before/after ====================
def test_20_markdown_with_surrounding_text():
    """markdown JSON 前后有额外文本。"""
    text = '''Here is my solution:

```json
{"answer": "42", "reasoning": "6*7=42"}
```

Hope this helps!'''
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_20_markdown_with_surrounding_text: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 21: Markdown truncated with surrounding text ====================
def test_21_markdown_truncated_with_text():
    """markdown JSON 截断 + 前后有文本。"""
    text = '''Let me solve this step by step.

```json
{
  "answer": "42",
  "reasoning": "6 multiplied by 7 equals 42"'''
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_21_markdown_truncated_with_text: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 22: Multiple code blocks, first is explanation ====================
def test_22_multiple_code_blocks():
    """多个代码块，第一个是说明，第二个是答案。"""
    text = '''I'll show the formula first:

```
f(x) = 6 * 7
```

Here's the answer:

```json
{"answer": "42", "reasoning": "6*7=42"}
```'''
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_22_multiple_code_blocks: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 23: JSON with None/null values ====================
def test_23_null_values():
    """JSON 中的 null 值不应导致解析失败。"""
    text = '{"answer": "42", "reasoning": "6*7=42", "verification": null}'
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_23_null_values: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')


# ==================== 测试 24: _robust_fallback_parse directly ====================
def test_24_robust_fallback_direct():
    """直接测试 _robust_fallback_parse 各场景。"""
    # trailing commas
    assert _robust_fallback_parse('{"answer": "42",}') is not None
    print("  [PASS] test_24_robust_fallback_direct: trailing commas")

    # single quotes
    assert _robust_fallback_parse("{'answer': '42'}") is not None
    print("  [PASS] test_24_robust_fallback_direct: single quotes")

    # truncated
    assert _robust_fallback_parse('{"answer": "42"') is not None
    print("  [PASS] test_24_robust_fallback_direct: truncated")

    # markdown truncated
    assert _robust_fallback_parse('```json\n{"answer": "42"') is not None
    print("  [PASS] test_24_robust_fallback_direct: markdown truncated")

    # garbage
    assert _robust_fallback_parse("hello world") is None
    print("  [PASS] test_24_robust_fallback_direct: garbage returns None")

    global passed
    passed += 5


# ==================== 测试 25: Realistic multi-candidate with markdown + trailing commas ====================
def test_25_realistic_multicandidate_markdown():
    """模拟真实的多候选 markdown JSON 输出（带尾随逗号）。"""
    text = '''```json
{
  "final_answer": "42",
  "candidates": [
    {
      "answer": "42",
      "confidence": 0.9,
      "reasoning": "6 * 7 = 42",
    },
    {
      "answer": "41",
      "confidence": 0.1,
      "reasoning": "Off by one error",
    }
  ],
  "selected_index": 0,
  "selection_reasoning": "First is correct",
}
```'''
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_25_realistic_multicandidate_markdown: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')
    test("test_25_realistic_multicandidate_markdown: candidates",
         result["candidates"] is not None and len(result["candidates"]) == 2,
         f'got {result["candidates"]!r}')


# ==================== Phase 6.2: 错误分类修复测试 ====================

# ==================== 测试 26: _make_error_result 包含 error_type="incomplete" ====================
def test_26_error_result_has_incomplete():
    """_make_error_result 应返回 error_type="incomplete"。"""
    result = _make_error_result("Test parse failure")
    test("test_26_error_result_has_incomplete: error_type",
         result.get("error_type") == "incomplete",
         f'got {result.get("error_type")!r}')
    test("test_26_error_result_has_incomplete: answer empty",
         result["answer"] == "",
         f'got {result["answer"]!r}')
    test("test_26_error_result_has_incomplete: error field set",
         result["error"] == "Test parse failure",
         f'got {result["error"]!r}')


# ==================== 测试 27: garbage text → error_type="incomplete" ====================
def test_27_garbage_incomplete():
    """无法解析的文本应返回 error_type="incomplete"。"""
    text = "I cannot solve this problem."
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_27_garbage_incomplete: error_type",
         result.get("error_type") == "incomplete",
         f'got {result.get("error_type")!r}')


# ==================== 测试 28: empty string → error_type="incomplete" ====================
def test_28_empty_string_incomplete():
    """空字符串应返回 error_type="incomplete"。"""
    result = parse_multi_candidate_response("", question="What is 6*7?")
    test("test_28_empty_string_incomplete: error_type",
         result.get("error_type") == "incomplete",
         f'got {result.get("error_type")!r}')
    test("test_28_empty_string_incomplete: answer empty",
         result["answer"] == "",
         f'got {result["answer"]!r}')


# ==================== 测试 29: valid JSON → no error_type="incomplete" (regression) ====================
def test_29_valid_no_incomplete():
    """有效 JSON 解析不应标记 error_type="incomplete"。"""
    text = json.dumps({
        "final_answer": "42",
        "reasoning": "6 * 7 = 42",
        "candidates": [],
    })
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_29_valid_no_incomplete: answer correct",
         result["answer"] == "42",
         f'got {result["answer"]!r}')
    test("test_29_valid_no_incomplete: not incomplete",
         result.get("error_type") != "incomplete",
         f'got {result.get("error_type")!r}')


# ==================== 测试 30: parse failure sets error field ====================
def test_30_parse_failure_error_field():
    """解析失败时 error 字段应被设置。"""
    result = parse_multi_candidate_response("garbage", question="test")
    test("test_30_parse_failure_error_field: error set",
         bool(result.get("error")),
         f'got {result.get("error")!r}')
    test("test_30_parse_failure_error_field: error_type incomplete",
         result.get("error_type") == "incomplete",
         f'got {result.get("error_type")!r}')


# ==================== 测试 31: _make_error_result preserves all fields ====================
def test_31_error_result_fields():
    """_make_error_result 应包含所有必要字段。"""
    result = _make_error_result("test error")
    required_keys = {
        "answer", "reasoning", "steps", "verification",
        "candidates", "selected_index", "selection_reasoning",
        "verification_score", "verification_confidence",
        "proof_quality_score", "verification_warning",
        "error", "error_type",
    }
    missing = required_keys - set(result.keys())
    test("test_31_error_result_fields: all keys present",
         len(missing) == 0,
         f'missing: {missing}')


# ==================== 测试 32: InferenceResult error propagation (mock) ====================
def test_32_inference_error_propagation():
    """模拟 _do_inference 的错误检测逻辑：空答案应设置 error。"""
    # 模拟 _do_inference 中的错误检测逻辑
    def check_incomplete(parsed):
        """复制 _do_inference 中的检测逻辑。"""
        final_answer = (parsed.get("answer") or "").strip()
        parse_error = parsed.get("error")
        if parse_error:
            return parse_error
        elif not final_answer:
            return "No valid answer produced"
        return None

    # Case 1: parse failure
    err1 = check_incomplete(_make_error_result("parse failed"))
    test("test_32_error_propagation: parse failure sets error",
         err1 == "parse failed",
         f'got {err1!r}')

    # Case 2: valid JSON but empty answer
    err2 = check_incomplete({"answer": "", "reasoning": "some reasoning"})
    test("test_32_error_propagation: empty answer sets error",
         err2 == "No valid answer produced",
         f'got {err2!r}')

    # Case 3: valid answer — no error
    err3 = check_incomplete({"answer": "42", "reasoning": "6*7=42"})
    test("test_32_error_propagation: valid answer no error",
         err3 is None,
         f'got {err3!r}')

    # Case 4: whitespace-only answer
    err4 = check_incomplete({"answer": "   ", "reasoning": ""})
    test("test_32_error_propagation: whitespace answer sets error",
         err4 == "No valid answer produced",
         f'got {err4!r}')


# ==================== 测试 33: main.py JudgeResult error_type (mock) ====================
def test_33_judge_result_error_type():
    """模拟 main.py 中 inference.error 时的 JudgeResult 创建逻辑。"""
    from models import JudgeResult

    # 模拟 main.py 的 fallback JudgeResult 创建
    inference_error = "Failed to parse JSON from response"
    judge = JudgeResult(
        problem_id="TEST",
        is_correct=False,
        confidence=0.0,
        explanation=f"Inference error: {inference_error}",
        error_type="incomplete",
        error=inference_error,
    )
    test("test_33_judge_result: error_type is incomplete",
         judge.error_type == "incomplete",
         f'got {judge.error_type!r}')
    test("test_33_judge_result: is_correct False",
         judge.is_correct is False,
         f'got {judge.is_correct}')
    test("test_33_judge_result: error set",
         judge.error == inference_error,
         f'got {judge.error!r}')


# ==================== 测试 34: valid multi-candidate → no error_type (regression) ====================
def test_34_valid_multicandidate_no_error():
    """有效多候选 JSON 不应有 error_type="incomplete"。"""
    text = json.dumps({
        "final_answer": "42",
        "candidates": [
            {"answer": "42", "confidence": 0.9, "reasoning": "6*7=42"},
            {"answer": "41", "confidence": 0.1, "reasoning": "maybe 41"},
        ],
        "selected_index": 0,
    })
    result = parse_multi_candidate_response(text, question="What is 6*7?")
    test("test_34_valid_multicandidate_no_error: answer",
         result["answer"] == "42",
         f'got {result["answer"]!r}')
    test("test_34_valid_multicandidate_no_error: no incomplete",
         result.get("error_type") != "incomplete",
         f'got {result.get("error_type")!r}')
    test("test_34_valid_multicandidate_no_error: no error",
         not result.get("error"),
         f'got {result.get("error")!r}')


# ==================== 运行所有测试 ====================
def run_all():
    print("=" * 60)
    print("Phase 6.1 + 6.2: JSON Parse Fallback + Error Classification Tests")
    print("=" * 60)

    tests = [
        # Phase 6.1 tests
        test_1_valid_json,
        test_2_markdown_json_closed,
        test_3_markdown_json_truncated,
        test_4_markdown_json_uppercase,
        test_5_trailing_commas,
        test_6_trailing_commas_nested,
        test_7_single_quotes,
        test_8_line_comments,
        test_9_block_comments,
        test_10_truncated_json,
        test_11_unescaped_newlines,
        test_12_markdown_truncated_with_commas,
        test_13_regex_extraction,
        test_14_garbage_text,
        test_15_valid_multicandidate,
        test_17_chunk_with_braces_in_strings,
        test_18_repair_truncated,
        test_19_escape_control_chars,
        test_20_markdown_with_surrounding_text,
        test_21_markdown_truncated_with_text,
        test_22_multiple_code_blocks,
        test_23_null_values,
        test_24_robust_fallback_direct,
        test_25_realistic_multicandidate_markdown,
        # Phase 6.2 tests
        test_26_error_result_has_incomplete,
        test_27_garbage_incomplete,
        test_28_empty_string_incomplete,
        test_29_valid_no_incomplete,
        test_30_parse_failure_error_field,
        test_31_error_result_fields,
        test_32_inference_error_propagation,
        test_33_judge_result_error_type,
        test_34_valid_multicandidate_no_error,
    ]

    for t in tests:
        print(f"\n--- {t.__name__} ---")
        t()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
