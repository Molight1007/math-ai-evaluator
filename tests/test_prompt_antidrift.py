# -*- coding: utf-8 -*-
"""提示词「防跑偏」改动的单元测试（2026-09-15）。

背景（10 题评测实测错因）
------------------------
6 道错题里 **5 道是「漏项 / 多选 / 方向反」这类完备性与形态错误**，
只有 086 是概念混淆，**「计算错」为 0**：

| 题 | 表现 | 归属 |
|---|---|---|
| 099 | 题面「…方法**有哪些**」，只答 1 个方法（正解为多个） | 完备性 |
| 103 | 答 `ABCD`，正解 `ABCDE` —— **漏选 E** | 完备性 |
| 096 | 答 `AD`，正解 `D` —— **多选 A** | 完备性 |
| 101 | 答「错误」，正解「正确」—— **方向反** | 方向性 |
| 091 | 表达式多一项 | 完备性 |
| 086 | 三空，第 2 空算错（8 vs 16） | 知识性 |

诊断结论：**规则本来就在提示词里**（清点选项、逐项判真、方向性陷阱、逐空求解），
模型仍然不遵守 ⇒ 缺的不是"告知"，而是**定稿前的机械核对**。
另查出**一处真实注入缺口**：099 用「哪些」提问，而旧 `_ASKS_ALL_RE` 只认「所有/全部」
⇒ 完备性要求根本没注入。

覆盖:
- `_ASKS_ALL_RE` 扩展：哪些/哪几种/有哪些/列举 必须触发
- 选择题：定稿前机械核对（三问 + 集合校验等式）在场，且校验等式表述明确
- 判断题：方向性核对在场
- 填空题：先数空 + 按段数核对在场
- 回归保护：选择题/证明题**不得**被注入"必须给具体数值"
"""
import re
import unittest

from agent.question_type import (
    QT_CHOICE, QT_FILL, QT_JUDGE, QT_PROOF,
    _ASKS_ALL_RE, answer_form_requirement, get_question_type_hint,
)


class AsksAllTriggerTest(unittest.TestCase):
    """穷尽性问法必须触发完备性要求（099 的直接根因）。"""

    def test_099_style_which_ones_triggers(self):
        p = "求解偏微分方程时常用的离散化方法有哪些？请简要说明各方法的适用场景。"
        self.assertTrue(_ASKS_ALL_RE.search(p), "「有哪些」必须触发完备性要求")
        self.assertTrue(answer_form_requirement(p, "解答题"),
                        "099 类题面必须注入完备性要求")

    def test_various_exhaustive_phrasings(self):
        for p in ("下列哪些是正确的",
                  "满足条件的整数是哪几个",
                  "请列举所有可能情形",
                  "请罗列该方程的解",
                  "求所有可能的取值",
                  "determine all solutions",
                  "find all integers n"):
            self.assertTrue(_ASKS_ALL_RE.search(p), "应触发: %s" % p)

    def test_non_exhaustive_not_triggered(self):
        for p in ("求该定积分的值", "计算行列式", "证明该函数连续"):
            self.assertFalse(_ASKS_ALL_RE.search(p), "不应触发: %s" % p)


class ChoiceHintTest(unittest.TestCase):

    def test_mechanical_checklist_present(self):
        h = get_question_type_hint(QT_CHOICE)
        self.assertIn("定稿前机械核对", h)
        self.assertIn("没判过的必须补判", h)

    def test_set_equality_rule_present(self):
        h = get_question_type_hint(QT_CHOICE)
        self.assertIn("答案字母集合", h)
        self.assertIn("既不多也不少", h)

    def test_steps_are_dense_and_ordered(self):
        h = get_question_type_hint(QT_CHOICE)
        nums = [int(n) for n in re.findall(r"(?m)^(\d)\.", h)]
        self.assertEqual(nums, list(range(1, len(nums) + 1)),
                         "步骤编号必须从 1 连续且唯一（重复编号会误导模型）")


class JudgeHintTest(unittest.TestCase):

    def test_direction_check_present(self):
        h = get_question_type_hint(QT_JUDGE)
        self.assertIn("定稿前机械核对", h)
        self.assertIn("方向", h)

    def test_steps_dense(self):
        h = get_question_type_hint(QT_JUDGE)
        nums = [int(n) for n in re.findall(r"(?m)^(\d)\.", h)]
        self.assertEqual(nums, list(range(1, len(nums) + 1)))


class FillHintTest(unittest.TestCase):

    def test_count_blanks_then_verify(self):
        h = get_question_type_hint(QT_FILL)
        self.assertIn("先数空", h)
        self.assertIn("定稿前机械核对", h)
        self.assertIn("恰好 N 段", h)

    def test_steps_dense(self):
        h = get_question_type_hint(QT_FILL)
        nums = [int(n) for n in re.findall(r"(?m)^(\d)\.", h)]
        self.assertEqual(nums, list(range(1, len(nums) + 1)))


class NoInterferenceTest(unittest.TestCase):
    """⚠ 回归保护：选择题/证明题**不得**被注入「必须给具体数值」这类要求。

    历史教训：两套要求同时注入会把 093 的答案 `CE` 要求成"具体数值"。
    """

    def test_choice_gets_no_answer_form_requirement(self):
        p = "关于勒贝格可积性，下列哪些陈述是正确的？"
        self.assertTrue(_ASKS_ALL_RE.search(p))          # 现在会触发
        self.assertEqual(answer_form_requirement(p, QT_CHOICE), "",
                         "选择题必须返回空（形态由 objective_injection 负责）")

    def test_proof_gets_no_answer_form_requirement(self):
        p = "求证：所有正整数 n 都满足该不等式。"
        self.assertEqual(answer_form_requirement(p, QT_PROOF), "")

    def test_solution_still_gets_requirement(self):
        p = "常用的离散化方法有哪些？"
        out = answer_form_requirement(p, "解答题")
        self.assertIn("必须", out)
        self.assertIn("枚举", out)


if __name__ == "__main__":
    unittest.main()
