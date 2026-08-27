# -*- coding: utf-8 -*-
"""
判分逻辑修复的单元测试。

覆盖：
1. _answers_equivalent / _normalize_answer / _try_parse_number（答案等价判定）
2. parse_judge_batch_response / _extract_partial_json_objects（批量判题解析）
3. apply_reference_leniency（参考答案等价强制判对）

运行方式：
    cd d:\\挑战杯 && python -m pytest 测试工具/test_deepseek_fixes.py -v
"""
import os
import sys
import unittest

# 将项目根目录与测试工具目录加入 sys.path，确保 deepseek/config/models 等模块可导入
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOL_DIR = os.path.join(_PROJECT_ROOT, "测试工具")
for _p in (_PROJECT_ROOT, _TOOL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from deepseek import (  # noqa: E402
    _answers_equivalent,
    _build_dynamic_batches,
    _estimate_tokens,
    _extract_partial_json_objects,
    _normalize_answer,
    _truncate_by_tokens,
    _try_parse_number,
    apply_reference_leniency,
    parse_judge_batch_response,
)
from models import InferenceResult  # noqa: E402


def _make_inference(problem_id="test-1", answer="2048", reasoning="推理过程",
                    raw_response="raw") -> InferenceResult:
    return InferenceResult(
        question="测试题目内容",
        problem_id=problem_id,
        answer=answer,
        reasoning=reasoning,
        raw_response=raw_response,
    )


class TestAnswersEquivalent(unittest.TestCase):
    """_answers_equivalent：模型答案与参考答案的等价判定。"""

    def test_identical_integer(self):
        self.assertTrue(_answers_equivalent("2048", "2048"))

    def test_integer_vs_float(self):
        self.assertTrue(_answers_equivalent("2048", "2048.0"))
        self.assertTrue(_answers_equivalent("2048.0", "2048"))

    def test_fraction_vs_decimal(self):
        self.assertTrue(_answers_equivalent("1/2", "0.5"))
        self.assertTrue(_answers_equivalent("\\frac{1}{2}", "0.5"))
        self.assertTrue(_answers_equivalent("\\tfrac{1}{2}", "0.5"))

    def test_boxed_wrapper(self):
        self.assertTrue(_answers_equivalent("\\boxed{2048}", "2048"))
        self.assertTrue(_answers_equivalent("\\boxed{\\frac{1}{2}}", "0.5"))
        self.assertTrue(_answers_equivalent("\\boxed{2048}", "\\boxed{2048}"))

    def test_natural_language_prefix(self):
        self.assertTrue(_answers_equivalent("答案为 2048", "2048"))
        self.assertTrue(_answers_equivalent("答案是 2048", "2048"))
        self.assertTrue(_answers_equivalent("Answer: 2048", "2048"))

    def test_thousands_separator(self):
        self.assertTrue(_answers_equivalent("2,048", "2048"))

    def test_empty_or_none(self):
        self.assertFalse(_answers_equivalent("", "2048"))
        self.assertFalse(_answers_equivalent("2048", ""))
        self.assertFalse(_answers_equivalent("", ""))

    def test_different_values(self):
        self.assertFalse(_answers_equivalent("2049", "2048"))
        self.assertFalse(_answers_equivalent("2048", "1024"))


class TestNormalizeAnswer(unittest.TestCase):
    """_normalize_answer：答案文本规范化。"""

    def test_nested_frac(self):
        self.assertEqual(_normalize_answer("\\boxed{\\frac{1}{2}}"), "1/2")

    def test_nested_boxed(self):
        self.assertEqual(_normalize_answer("\\boxed{\\boxed{2048}}"), "2048")

    def test_text_prefix_removed(self):
        self.assertEqual(_normalize_answer("答案为 2048"), "2048")
        self.assertEqual(_normalize_answer("Answer: 2048"), "2048")

    def test_empty(self):
        self.assertEqual(_normalize_answer(""), "")
        self.assertEqual(_normalize_answer(None), "")


class TestTryParseNumber(unittest.TestCase):
    """_try_parse_number：数字解析。"""

    def test_plain_number(self):
        self.assertEqual(_try_parse_number("2048"), 2048.0)

    def test_fraction(self):
        self.assertEqual(_try_parse_number("1/2"), 0.5)

    def test_scientific(self):
        self.assertEqual(_try_parse_number("2.048e3"), 2048.0)

    def test_thousands(self):
        self.assertEqual(_try_parse_number("1,000"), 1000.0)

    def test_percent(self):
        self.assertAlmostEqual(_try_parse_number("50%"), 0.5)

    def test_invalid(self):
        self.assertIsNone(_try_parse_number("abc"))
        self.assertIsNone(_try_parse_number(""))


class TestParseJudgeBatchResponse(unittest.TestCase):
    """parse_judge_batch_response：批量判题结果解析。"""

    def test_full_array(self):
        content = (
            '[{"problem_index": 1, "is_correct": true, "confidence": 0.9, '
            '"explanation": "ok"}, '
            '{"problem_index": 2, "is_correct": false, "confidence": 0.3, '
            '"explanation": "bad"}]'
        )
        parsed_list, missing = parse_judge_batch_response(content, ["P1", "P2"])
        self.assertEqual(len(parsed_list), 2)
        self.assertEqual(missing, [])
        self.assertTrue(parsed_list[0]["is_correct"])
        self.assertFalse(parsed_list[1]["is_correct"])

    def test_dict_wrapper(self):
        content = (
            '{"results": [{"problem_index": 1, "is_correct": true, '
            '"confidence": 0.8, "explanation": "ok"}]}'
        )
        parsed_list, missing = parse_judge_batch_response(content, ["P1", "P2"])
        self.assertEqual(len(parsed_list), 2)
        # 只有 P1 有结果，P2 缺失
        self.assertEqual(missing, [1])
        self.assertTrue(parsed_list[0]["is_correct"])

    def test_truncated_partial_recovery(self):
        # 截断内容：第二个对象不完整，应尽力恢复第一个对象
        content = (
            '[\n{"problem_index": 1, "is_correct": true, "confidence": 0.9, '
            '"explanation": "ok"},\n{"problem_index": 2, "is_c'
        )
        parsed_list, missing = parse_judge_batch_response(content, ["P1", "P2"])
        # 恢复出一个对象
        found = [p for p in parsed_list if p is not None]
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["is_correct"])

    def test_garbage_content(self):
        content = "no json here at all"
        parsed_list, missing = parse_judge_batch_response(content, ["P1", "P2"])
        self.assertEqual(missing, [0, 1])
        self.assertTrue(all(p is None for p in parsed_list))


class TestExtractPartialJsonObjects(unittest.TestCase):
    """_extract_partial_json_objects：截断内容的部分 JSON 恢复。"""

    def test_recovers_first_object(self):
        content = (
            '{"problem_index": 1, "is_correct": true}, '
            '{"problem_index": 2, "is_c'
        )
        objs = _extract_partial_json_objects(content)
        self.assertGreaterEqual(len(objs), 1)
        self.assertEqual(objs[0]["problem_index"], 1)

    def test_empty(self):
        self.assertEqual(_extract_partial_json_objects(""), [])
        self.assertEqual(_extract_partial_json_objects(None), [])


class TestApplyReferenceLeniency(unittest.TestCase):
    """apply_reference_leniency：参考答案等价强制判对。"""

    def _parsed(self, is_correct=False, confidence=0.3, explanation="模型误判"):
        return {
            "is_correct": is_correct,
            "conclusion_correct": is_correct,
            "confidence": confidence,
            "explanation": explanation,
            "error_type": "mathematical_error",
        }

    def test_equivalent_answer_forces_correct(self):
        inf = _make_inference(answer="2048")
        parsed = self._parsed(is_correct=False, confidence=0.99)
        result = apply_reference_leniency(inf, parsed, "2048")
        self.assertTrue(result["is_correct"])
        self.assertTrue(result["conclusion_correct"])
        # 不再静默覆盖：error_type 保持原始，confidence 不被拉高
        self.assertEqual(result["error_type"], "mathematical_error")
        self.assertEqual(result["confidence"], 0.99)
        # 新增兜底标记与原始判分字段
        self.assertTrue(result["reference_matched"])
        self.assertFalse(result["judge_raw"]["is_correct"])
        self.assertEqual(result["judge_raw"]["confidence"], 0.99)
        self.assertEqual(result["judge_raw"]["error_type"], "mathematical_error")

    def test_nonequivalent_answer_unchanged(self):
        inf = _make_inference(answer="2049")
        parsed = self._parsed(is_correct=False, confidence=0.99)
        result = apply_reference_leniency(inf, parsed, "2048")
        self.assertFalse(result["is_correct"])
        self.assertFalse(result["reference_matched"])

    def test_no_reference_answer_unchanged(self):
        inf = _make_inference(answer="2048")
        parsed = self._parsed(is_correct=False)
        result = apply_reference_leniency(inf, parsed, None)
        self.assertFalse(result["is_correct"])
        self.assertFalse(result["reference_matched"])

    def test_empty_model_answer_unchanged(self):
        inf = _make_inference(answer="")
        parsed = self._parsed(is_correct=False)
        result = apply_reference_leniency(inf, parsed, "2048")
        self.assertFalse(result["is_correct"])
        self.assertFalse(result["reference_matched"])

    def test_already_correct_unchanged(self):
        inf = _make_inference(answer="2048")
        parsed = self._parsed(is_correct=True, confidence=0.99)
        result = apply_reference_leniency(inf, parsed, "2048")
        self.assertTrue(result["is_correct"])
        self.assertFalse(result["reference_matched"])

    def test_fraction_equivalent_forces_correct(self):
        inf = _make_inference(answer="\\frac{1}{2}")
        parsed = self._parsed(is_correct=False)
        result = apply_reference_leniency(inf, parsed, "0.5")
        self.assertTrue(result["is_correct"])
        self.assertTrue(result["reference_matched"])


class TestTokenEstimation(unittest.TestCase):
    """_estimate_tokens：用字符数保守估算 token 数。"""

    def test_empty(self):
        self.assertEqual(_estimate_tokens(""), 0)
        self.assertEqual(_estimate_tokens(None), 0)

    def test_short_text_min_one(self):
        self.assertEqual(_estimate_tokens("abc"), 1)

    def test_divisor(self):
        self.assertEqual(_estimate_tokens("a" * 300), 100)


class TestTruncateByTokens(unittest.TestCase):
    """_truncate_by_tokens：按 token 估算截断文本，保留首尾。"""

    def test_under_limit_unchanged(self):
        text = "short text"
        self.assertEqual(_truncate_by_tokens(text, 100), text)

    def test_over_limit_truncated(self):
        text = "A" * 3000  # 约 1000 token
        result = _truncate_by_tokens(text, 100, head_ratio=0.6)
        self.assertLess(len(result), len(text))
        self.assertIn("省略", result)

    def test_empty(self):
        self.assertEqual(_truncate_by_tokens("", 100), "")
        self.assertIsNone(_truncate_by_tokens(None, 100))


class TestBuildDynamicBatches(unittest.TestCase):
    """_build_dynamic_batches：按推理长度动态分批。"""

    def _inf(self, problem_id, answer="2048", reasoning="short", question="Q"):
        return InferenceResult(
            question=question,
            problem_id=problem_id,
            answer=answer,
            reasoning=reasoning,
            raw_response="raw",
        )

    def test_short_questions_merged(self):
        infs = [self._inf(f"p{i}") for i in range(5)]
        batches = _build_dynamic_batches(infs)
        # 短题应合并为少量批次
        self.assertLess(len(batches), len(infs))

    def test_long_reasoning_alone(self):
        # 证明题的超长推理精简后仍超单批上限，应单独成批
        infs = [
            self._inf("short1", reasoning="s"),
            self._inf(
                "long1",
                question="Prove that P holds for all n",
                reasoning="R" * 60000,  # 精简后约 6000 token，仍超单批上限
            ),
            self._inf("short2", reasoning="s"),
        ]
        batches = _build_dynamic_batches(infs)
        long_batches = [
            b for b in batches if any(inf.problem_id == "long1" for inf in b)
        ]
        self.assertEqual(len(long_batches), 1)
        self.assertEqual(len(long_batches[0]), 1)

    def test_empty(self):
        self.assertEqual(_build_dynamic_batches([]), [])


if __name__ == "__main__":
    unittest.main()
