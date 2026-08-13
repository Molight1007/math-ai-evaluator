# -*- coding: utf-8 -*-
"""验证器（VerifierAgent）核心逻辑单元测试。

覆盖:
- ``_is_correct_vote``: 拒绝词优先、接受词兜底
- ``_normalize_answer_text``: 文本级归一化
- ``_are_answers_equivalent``: 三级等价判定
- ``_equiv_group``: 等价答案聚类
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


if __name__ == "__main__":
    unittest.main()
