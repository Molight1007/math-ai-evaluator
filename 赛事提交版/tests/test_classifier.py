# -*- coding: utf-8 -*-
"""分类器关键词匹配单元测试。

覆盖 ``_keyword_classify``：关键词加权分类，高权重关键词 ×3。
"""
import unittest

from agent.classifier import _keyword_classify


class KeywordClassifyTest(unittest.TestCase):
    def test_empty_input(self) -> None:
        domain, score = _keyword_classify("")
        self.assertEqual(domain, "")
        self.assertEqual(score, 0)

    def test_analysis_domain(self) -> None:
        domain, score = _keyword_classify("求极限 lim_{x→0} (sin x)/x")
        self.assertEqual(domain, "数学分析")
        self.assertGreaterEqual(score, 2)

    def test_linear_algebra_domain(self) -> None:
        domain, score = _keyword_classify("计算矩阵 A 的特征值和特征向量")
        self.assertEqual(domain, "线性代数")
        self.assertGreaterEqual(score, 3)

    def test_pde_high_weight(self) -> None:
        # "PDE" 为高权重关键词，得分 ×3
        domain, score = _keyword_classify("求解 PDE 波动方程")
        self.assertEqual(domain, "偏微分方程")
        self.assertGreaterEqual(score, 3)

    def test_indefinite_integral_domain(self) -> None:
        domain, score = _keyword_classify("计算不定积分")
        # 已知局限：并列得分取先序域（"数学分析"含"积分"），
        # 单关键词命中得分仅 1，运行时该结果会被 LLM 分类覆盖（score>=2 才采用）
        self.assertEqual(domain, "数学分析")
        self.assertEqual(score, 1)

    def test_no_keyword_hit(self) -> None:
        domain, score = _keyword_classify("今天天气不错")
        self.assertEqual(domain, "")
        self.assertEqual(score, 0)


if __name__ == "__main__":
    unittest.main()
