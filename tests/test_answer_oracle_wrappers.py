# -*- coding: utf-8 -*-
"""AnswerOracle 的 `\\boxed{}` 外表壳处理回归测试（2026-09-16）。

背景（0916 轮 003/013 两题同时命中，属最高价值 bug 之一）
------------------------------------------------------
题目明确要求「Remember to put your final answer within `\\boxed{}`」——
**模型照做了**，但 oracle 因此把答案判为"无法解析"：

    is_parseable('\\boxed{2025}')             -> False   （而 '2025' -> True）
    answers_equivalent('\\boxed{2025}','2025')-> False

底层原因：`utils/sympy_tools._try_parse` 的前处理把 `\\boxed{2025}` 归一成
`\\boxed2025`（删了花括号、留下 `\\boxed`）⇒ SymPy `could not parse`。

**一个解析 bug 同时废掉两个机制**：
  ① 可解析性闸门 → 假判 `incorrect` → trace 记「客观复核判错，触发定向修正」
     ⇒ 触发长达 10 分钟的徒劳修正（003 实耗 **775.9s**、013 **591.4s**，
     而这两题总耗时 1620s / 1467s ⇒ 约一半墙钟）；
  ② `answers_equivalent` 归组失效 ⇒ 自洽共识 `group_size` 恒为 1 ⇒ 信号作废。

修复：oracle 内部先 `strip_wrappers` 再解析/比较（不动 `sympy_tools` 全局行为，
避免影响 `run_eval.answers_match` 等其它调用方）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.answer_oracle import AnswerOracle as A  # noqa: E402


class StripWrappersTest(unittest.TestCase):

    def test_boxed(self):
        self.assertEqual(A.strip_wrappers(r"\boxed{2025}"), "2025")
        self.assertEqual(A.strip_wrappers(r"\boxed{\frac{1}{2}}"), r"\frac{1}{2}")

    def test_math_delimiters(self):
        self.assertEqual(A.strip_wrappers(r"\( \boxed{50} \)"), "50")
        self.assertEqual(A.strip_wrappers(r"\[ 48 \]"), "48")
        self.assertEqual(A.strip_wrappers("$48$"), "48")

    def test_text_wrapper(self):
        self.assertEqual(A.strip_wrappers(r"\text{2026}"), "2026")

    def test_nested(self):
        self.assertEqual(A.strip_wrappers(r"\boxed{\text{是}}"), "是")

    def test_plain_unchanged(self):
        self.assertEqual(A.strip_wrappers("2025"), "2025")
        self.assertEqual(A.strip_wrappers("2026, 2030"), "2026, 2030")

    def test_empty_and_unbalanced_no_crash(self):
        """未闭合 / 空串不得抛异常，也不得吞掉内容。"""
        self.assertEqual(A.strip_wrappers(""), "")
        self.assertEqual(A.strip_wrappers(r"\boxed{"), r"\boxed{")
        self.assertEqual(A.strip_wrappers(r"\boxed{2025"), r"\boxed{2025")


class IsParseableTest(unittest.TestCase):

    def test_boxed_now_parseable(self):
        """★ 核心回归：题面要求的书写格式必须被判为可解析。"""
        for s in (r"\boxed{2025}", r"\boxed{50}", r"\boxed{48}",
                  r"\boxed{\frac{1}{2}}", r"\( \boxed{48} \)"):
            with self.subTest(s=s):
                self.assertTrue(A.is_parseable(s))

    def test_plain_still_parseable(self):
        for s in ("2025", "50", "2026, 2030", "48"):
            with self.subTest(s=s):
                self.assertTrue(A.is_parseable(s))

    def test_empty_false(self):
        self.assertFalse(A.is_parseable(""))

    def test_no_regression_on_unparseable(self):
        self.assertFalse(A.is_parseable(r"\boxed{"))


class AnswersEquivalentTest(unittest.TestCase):

    def test_boxed_vs_plain(self):
        """★ 核心回归：自洽共识依赖它归组，必须跨外壳等价。"""
        self.assertTrue(A.answers_equivalent(r"\boxed{2025}", "2025"))
        self.assertTrue(A.answers_equivalent("2026", r"\boxed{2026}"))
        self.assertTrue(A.answers_equivalent(r"\boxed{2/4}", r"\boxed{1/2}"))

    def test_same_boxed(self):
        self.assertTrue(A.answers_equivalent(r"\boxed{2026}", r"\boxed{2026}"))

    def test_different_values_still_false(self):
        """⚠ 反向保护：等价判定不能被改宽到把不同数值判等。"""
        self.assertFalse(A.answers_equivalent(r"\boxed{10}", "50"))
        self.assertFalse(A.answers_equivalent(r"\boxed{10}", r"\boxed{11}"))
        self.assertFalse(A.answers_equivalent("", "50"))
        self.assertFalse(A.answers_equivalent("10", ""))

    def test_consensus_groups_across_wrapper(self):
        """一致性端到端：混合外壳的候选应被归入同一组。"""
        class C:
            def __init__(self, a):
                self.answer = a

        target = C(r"\boxed{2026}")
        cands = [C("2026"), C(r"\boxed{2026}"), C(r"\boxed{2025}")]
        group, total, usable = A._consensus(target, cands)
        self.assertTrue(usable)
        self.assertEqual(total, 3)
        self.assertEqual(group, 2, "`2026` 与 `\\boxed{2026}` 必须同组")


if __name__ == "__main__":
    unittest.main()
