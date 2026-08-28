# -*- coding: utf-8 -*-
"""验证器（VerifierAgent）核心逻辑单元测试。

覆盖:
- ``_is_correct_vote``: 拒绝词优先、接受词兜底
- ``_normalize_answer_text``: 文本级归一化
- ``_are_answers_equivalent``: 三级等价判定
- ``_equiv_group``: 等价答案聚类
- ``_parse_json_loose`` / ``_format_bug_report``: 结构化 bug report
  （依据 IMO 2025 验证-精炼流水线论文，用于驱动 revise 迭代修正）
- ``_extract_bug_report``: 端到端解析 + 分类回退
"""
import unittest
from types import SimpleNamespace

from agent.verifier import VerifierAgent


def make_verifier() -> VerifierAgent:
    return VerifierAgent(client=object(), config=SimpleNamespace())


class IsCorrectVoteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = make_verifier()

    def test_none_input(self) -> None:
        self.assertFalse(self.verifier._is_correct_vote(None))

    def test_verdict_a(self) -> None:
        self.assertTrue(self.verifier._is_correct_vote("VERDICT: A"))

    def test_verdict_b(self) -> None:
        self.assertFalse(self.verifier._is_correct_vote("VERDICT: B"))

    def test_explicit_correct(self) -> None:
        self.assertTrue(self.verifier._is_correct_vote("该解答完全正确"))
        self.assertTrue(self.verifier._is_correct_vote("CORRECT"))

    def test_reject_word_wins_over_correct(self) -> None:
        # "不正确" 含 "正确" 子串，拒绝词必须优先
        self.assertFalse(self.verifier._is_correct_vote("答案不正确"))
        self.assertFalse(self.verifier._is_correct_vote("The answer is INCORRECT"))

    def test_reject_words(self) -> None:
        self.assertFalse(self.verifier._is_correct_vote("错误"))
        self.assertFalse(self.verifier._is_correct_vote("WRONG"))


class NormalizeAnswerTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = make_verifier()

    def test_empty_input(self) -> None:
        self.assertEqual(self.verifier._normalize_answer_text(""), "")
        self.assertEqual(self.verifier._normalize_answer_text(None), "")

    def test_whitespace_and_dollar(self) -> None:
        self.assertEqual(self.verifier._normalize_answer_text("$ 5 $"), "5")

    def test_fraction_to_decimal(self) -> None:
        self.assertEqual(self.verifier._normalize_answer_text("1/2"), "0.5")
        self.assertEqual(self.verifier._normalize_answer_text(r"\frac{1}{2}"), "0.5")

    def test_trailing_zero_removed(self) -> None:
        self.assertEqual(self.verifier._normalize_answer_text("3.0"), "3")


class AreAnswersEquivalentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = make_verifier()

    def test_identical_strings(self) -> None:
        self.assertTrue(self.verifier._are_answers_equivalent("2", "2"))

    def test_fraction_vs_decimal(self) -> None:
        self.assertTrue(self.verifier._are_answers_equivalent("1/2", "0.5"))

    def test_different_values(self) -> None:
        self.assertFalse(self.verifier._are_answers_equivalent("1/2", "0.25"))

    def test_empty_input(self) -> None:
        self.assertFalse(self.verifier._are_answers_equivalent("", "0"))
        self.assertFalse(self.verifier._are_answers_equivalent("1", None))


class EquivGroupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = make_verifier()

    def test_groups_equivalent_answers(self) -> None:
        groups = self.verifier._equiv_group([], ["1/2", "0.5", "3"])
        self.assertEqual(len(groups), 2)
        # 第一组应包含 "1/2" 与 "0.5"
        first = sorted(groups[0])
        self.assertEqual(first, [0, 1])

    def test_single_element(self) -> None:
        groups = self.verifier._equiv_group([], ["7"])
        self.assertEqual(groups, [[0]])

    def test_no_duplicates_in_groups(self) -> None:
        groups = self.verifier._equiv_group([], ["a", "b", "a"])
        flat = sorted(i for g in groups for i in g)
        self.assertEqual(flat, [0, 1, 2])


# ============================================================
# 结构化 Bug Report（论文：IMO 2025 验证-精炼流水线）
# ============================================================

class ParseJsonLooseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.v = make_verifier()

    def test_plain_json(self) -> None:
        self.assertEqual(self.v._parse_json_loose('{"a": 1}'), {"a": 1})

    def test_markdown_fence(self) -> None:
        raw = '```json\n{"verdict": "correct", "findings": []}\n```'
        self.assertEqual(self.v._parse_json_loose(raw)["verdict"], "correct")

    def test_leading_prose(self) -> None:
        """模型先说一段话再给 JSON —— 必须仍能抠出来。"""
        raw = '我的审查结果如下：\n{"verdict": "critical_error", "findings": []}'
        self.assertEqual(self.v._parse_json_loose(raw)["verdict"], "critical_error")

    def test_nested_braces(self) -> None:
        """findings 内部有嵌套对象，括号平衡不能提前收尾。"""
        raw = ('{"verdict":"x","findings":[{"location":"a > b",'
               '"type":"critical_error","explanation":"y"}]}')
        data = self.v._parse_json_loose(raw)
        self.assertEqual(data["findings"][0]["location"], "a > b")

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(self.v._parse_json_loose("完全没有 JSON"))
        self.assertIsNone(self.v._parse_json_loose(""))


class FormatBugReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.v = make_verifier()

    def test_empty_findings(self) -> None:
        self.assertEqual(self.v._format_bug_report({"findings": []}), "")

    def test_critical_errors_first(self) -> None:
        """关键错误必须排在论证漏洞之前——修正要先修断链的那一步。"""
        report = {"verdict": "critical_error", "findings": [
            {"location": "步骤2", "type": "justification_gap",
             "explanation": "跳步"},
            {"location": "步骤1", "type": "critical_error",
             "explanation": "符号写反"},
        ]}
        out = self.v._format_bug_report(report)
        self.assertLess(out.index("符号写反"), out.index("跳步"),
                        "关键错误应排在论证漏洞之前")
        self.assertIn("关键错误", out)
        self.assertIn("论证漏洞", out)

    def test_quotes_location(self) -> None:
        """location 要带引号，便于模型定位到原文那一句。"""
        report = {"findings": [
            {"location": "由 A>B 推出 A-C>B-D", "type": "critical_error",
             "explanation": "逻辑谬误"}]}
        self.assertIn("“由 A>B 推出 A-C>B-D”", self.v._format_bug_report(report))


class ExtractBugReportTest(unittest.TestCase):
    def _make(self, response):
        from agent.base import TaskContext, Budget

        class C:
            def chat(self, messages=None, temperature=0.0, max_tokens=0, **kw):
                return response

        v = VerifierAgent(client=C(), config=SimpleNamespace())
        ctx = TaskContext(problem="证明 x^2 >= 0", metadata={},
                          budget=Budget(max_calls=10))
        return v, ctx

    def test_parses_valid_report(self) -> None:
        v, ctx = self._make(
            '{"verdict":"critical_error","findings":['
            '{"location":"2+3=6","type":"critical_error",'
            '"explanation":"计算错误"}]}')
        r = v._extract_bug_report(ctx, "题", type("C", (), {
            "reasoning": "推理", "answer": "42"})())
        self.assertEqual(r["verdict"], "critical_error")
        self.assertEqual(len(r["findings"]), 1)
        self.assertEqual(r["findings"][0]["location"], "2+3=6")

    def test_verdict_inferred_when_missing(self) -> None:
        """模型漏给 verdict 时，用 findings 反推比信任自陈更可靠。"""
        v, ctx = self._make(
            '{"findings":[{"location":"a","type":"critical_error",'
            '"explanation":"b"}]}')
        r = v._extract_bug_report(ctx, "题", type("C", (), {
            "reasoning": "r", "answer": "1"})())
        self.assertEqual(r["verdict"], "critical_error")

    def test_unknown_type_defaults_to_gap(self) -> None:
        v, ctx = self._make(
            '{"verdict":"x","findings":[{"location":"a","type":"乱写的",'
            '"explanation":"b"}]}')
        r = v._extract_bug_report(ctx, "题", type("C", (), {
            "reasoning": "r", "answer": "1"})())
        self.assertEqual(r["findings"][0]["type"], "justification_gap")

    def test_garbage_returns_unknown(self) -> None:
        v, ctx = self._make("我无法完成这项任务")
        r = v._extract_bug_report(ctx, "题", type("C", (), {
            "reasoning": "r", "answer": "1"})())
        self.assertEqual(r["verdict"], "unknown")
        self.assertEqual(r["findings"], [])


if __name__ == "__main__":
    unittest.main()
