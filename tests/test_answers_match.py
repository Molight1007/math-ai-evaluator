# -*- coding: utf-8 -*-
r"""答案判分器语义匹配回归测试（2026-09-08，45 题评测 4 个判分误杀修复）。

修复清单（均来自 ab45_full_0907 实测错题）：
  1. alg-084：pred 尾部 '(c \in \mathbb{C})' 域说明未剥 → 文本等价判 expr_wrong
  2. alg-087：pred 全中文 '被 2 或 3 整除' → 整除语义只认英文，中文漏判
  3. 一元_003：pred/gold 都是'题设矛盾/无解'措辞不同 → 无解语义未匹配
  4. 多元_005：gold 是完整解题过程文本 → 未取过程末句结论与 pred 比
"""
import unittest

from run_eval import answers_match


class TestAnswersMatchSemantic(unittest.TestCase):
    """正向：4 个实测误杀案例修复后必须判 True。"""

    def test_084_quad_with_domain_bracket(self):
        pred = r"Q(x) = c(x-1)^2(x-4)(x+2) \quad (c \in \mathbb{C})"
        gold = r"$Q(x)=c(x-1)^2(x-4)(x+2)$"
        self.assertTrue(answers_match(pred, gold))

    def test_087_cn_divisibility(self):
        pred = "所有被 2 或 3 整除的正整数"
        gold = r"$n=2k, n=3k$"
        self.assertTrue(answers_match(pred, gold))

    def test_no_solution_semantic(self):
        pred = "题目条件矛盾，不存在满足条件的函数，f'(1) 不存在"
        gold = "题目条件矛盾，无法确定"
        self.assertTrue(answers_match(pred, gold))

    def test_gold_process_tail_extraction(self):
        pred = r"\boxed{-\ln 2 \cdot x + y + z + 1 = 0}"
        gold = ("设F(x,y,z)=z-xln(1+z^2)+e^y，则F_x=-ln(1+z^2)，F_y=e^y，"
                "F_z=1-(2xz)/(1+z^2)。在点(0,0,-1)处，F_x=-ln2，F_y=1，F_z=1。"
                "故法向量为(-ln2,1,1)，切平面方程为-ln2*(x-0)+1*(y-0)+1*(z+1)=0，"
                "即-ln2*x+y+z+1=0。")
        self.assertTrue(answers_match(pred, gold))

    def test_latex_cdot_normalized(self):
        # \cdot x 空格被删后仍能归一（P1 修复）
        pred = r"\boxed{-\ln 2 \cdot x + y + z + 1 = 0}"
        gold = r"$-\ln2*x+y+z+1=0$"
        self.assertTrue(answers_match(pred, gold))

    def test_cn_divisibility_multiple(self):
        # 中文整除 + 多数字：'被 3、5 整除' ↔ n=3k,n=5k（防漏 3 个以上除数）
        pred = "所有被 3 或 5 整除的正整数"
        gold = r"$n=3k, n=5k$"
        self.assertTrue(answers_match(pred, gold))


class TestAnswersMatchNoOverreach(unittest.TestCase):
    """反向：规则不得误放真错题（防'修误杀引入误报'）。"""

    def test_cn_divisibility_wrong_numbers(self):
        # 整除数字集合对不上 → 不放行
        pred = "所有被 2 或 3 整除的正整数"
        gold = r"$n=5k$"
        self.assertFalse(answers_match(pred, gold))

    def test_no_solution_but_gold_has_value(self):
        # pred 声称无解但 gold 是具体值 3 → 不放行
        pred = "不存在满足条件的函数"
        gold = "3"
        self.assertFalse(answers_match(pred, gold))

    def test_gold_short_no_process(self):
        # gold 短（不是过程文本）→ 不触发尾句提取
        pred = r"x+y+1=0"
        gold = "2"
        self.assertFalse(answers_match(pred, gold))

    def test_domain_bracket_not_stripped_mid(self):
        # 域说明不在尾部（中间出现）→ 不被误剥（回归保护：仅剥尾部）
        pred = r"(c \in \mathbb{C}), Q(x)=c(x-1)^2(x-4)(x+2)"
        gold = r"$Q(x)=c(x-1)^2(x-4)(x+2)$"
        # pred 带前导说明，未命中尾部剥除 → 走其它层应判 False（不与 gold 等价）
        self.assertFalse(answers_match(pred, gold))

    def test_real_wrong_alg060_still_wrong(self):
        # 真错题回归：alg-060 输出 1175/1176，gold 2617/2618 → 仍判 False
        pred = r"\boxed{\dfrac{1175}{1176}}"
        gold = r"$\frac{2617}{2618}$"
        self.assertFalse(answers_match(pred, gold))

    def test_real_wrong_comb027_still_wrong(self):
        # 真错题回归：comb-027 输出 2916，gold 2048 → 仍判 False
        pred = "2916"
        gold = "2048"
        self.assertFalse(answers_match(pred, gold))


if __name__ == "__main__":
    unittest.main()
