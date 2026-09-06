# -*- coding: utf-8 -*-
"""#51 答案定型：疑似推理文本的判定（_answer_looks_suspicious）单元测试。

基线 45 题实测：仅 7/45（15.6%）用了 \\boxed{}，5 题抽出的答案 >60 字符
（明显是整段计算步骤或结论句）。本地宽松 LLM 判分能看懂，平台判分看不懂。

判定的难点在**不要误伤合法答案**——`{1, 3, 5}`、`x = 2, y = 3` 这类
列表/多值答案绝不能被判成可疑，否则会触发无谓的定向重问。
"""

from __future__ import annotations

import unittest

from agent.solver import SolverAgent


class TestAnswerLooksSuspicious(unittest.TestCase):
    """判定函数本身：可疑样本必须抓到，合法答案必须放过。"""

    def _check(self, text, expected, label):
        got = SolverAgent._answer_looks_suspicious(text)
        self.assertEqual(got, expected, f"{label}: {text[:40]!r}")

    # ---------- 必须放过：合法答案 ----------
    def test_normal_answers_pass(self):
        """普通数值 / 表达式答案不应触发重问。"""
        for a in ("42", "3000", "-3", r"\frac{1}{2}", r"2\sqrt{3}",
                  r"\boxed{42}", "0", "100!"):
            self._check(a, False, f"合法答案 {a}")

    def test_list_answer_passes(self):
        """列表型答案含多个逗号，绝不能误判为推理文本。"""
        for a in ("{1, 3, 5}", "1, 3, 5", "(2, 4, 6)"):
            self._check(a, False, f"列表答案 {a}")

    def test_multi_value_equation_passes(self):
        """多值方程答案（多个等号但很短）不应误判。"""
        for a in ("x = 2, y = 3", "a = 1, b = -1"):
            self._check(a, False, f"多值答案 {a}")

    # ---------- 必须抓到：真实缺陷样本 ----------
    def test_real_defect_samples_caught(self):
        """基线 45 题里实际出现的 4 条超长答案（人工核对均为推理文本）。"""
        samples = [
            "19) = 1 + 27 = 28，$T(28) = 2 + 24 = 26$，$T(26) = 2 + 18 = 20$",
            "所有满足条件的复系数多项式为 $Q(x) = C(x + 2)(x - 1)^2(x - 4)$，"
            "其中 $C$ 为任意复常数。",
            "1。  步骤3：判断 $x = -2$ 处的敛散性 将 $x = -2$ 代入新幂级数："
            " $\\sum_{n=1}^{\\infty} n a_n (-2+2)^",
            r"\in \mathbb{Z}$ - $\sum \frac{1}{s_j} = S \in \mathbb{Z}$  由于有无穷多组不同的 $(a,b,c)$",
        ]
        for a in samples:
            self._check(a, True, "真实缺陷样本")

    # ---------- 判定规则的各个分支 ----------
    def test_empty_is_suspicious(self):
        self._check("", True, "空答案")
        self._check("   ", True, "纯空白")

    def test_over_length_is_suspicious(self):
        """超过 60 字符即判定为段落而非答案。"""
        self._check("x" * 61, True, "61 字符")
        self._check("x" * 60, False, "60 字符（边界内）")

    def test_sentence_period_is_suspicious(self):
        """答案是短语，出现句号说明抽到句子。"""
        self._check("答案是 42。", True, "含句号")

    def test_narrative_words_are_suspicious(self):
        """推理连接词：因此/所以/由于/其中/可得/步骤N 等。"""
        for a in ("因此 x = 42", "所以答案为 42", "由于 n 为偶数",
                  "综上，x = 42", "其中 k 为整数", "步骤3：代入",
                  "注意到 f 连续"):
            self._check(a, True, f"叙述性 {a}")

    def test_derivation_chain_is_suspicious(self):
        """多个等号 + 一定长度 = 推导链，不是答案。"""
        self._check("S = 1 + 2 + 3 = 6", True, "推导链")
        # 短的多值方程不该被这条规则抓到
        self._check("x = 2", False, "单一方程")

    def test_math_operators_in_answer_are_suspicious(self):
        """求和/积分/极限出现在答案里，说明抽到了表达式而非结果。"""
        for a in (r"$\sum_{i=1}^{n} i$", r"\int_0^1 x dx", r"\lim_{x \to 0} f(x)"):
            self._check(a, True, f"运算符 {a}")


if __name__ == "__main__":
    unittest.main()
