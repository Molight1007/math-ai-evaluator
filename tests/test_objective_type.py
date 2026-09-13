# -*- coding: utf-8 -*-
"""客观题（选择 / 判断 / 填空）题型识别与特化解法单元测试（2026-09-12）。

覆盖 official112 实测暴露的 5 类漏检与 1 类误判守护：

  漏检回归（修复前均被判"解答题"，特化策略与选项清单因此完全没生效）：
    · 087 —— LaTeX 列表选项 `\\item[A.] …`；
    · 098 —— 选项后紧跟 `\\(\\kappa(A)=…\\)`；
    · 102/103/106/107 —— 中文连排选项 `A.长期趋势B.季节变动…`；
    · 093/096/103 —— 五选项（旧提取只认 A–D，**E 项丢失**，与模型"漏选 E"直接相关）；
    · 086 —— `(\\quad)` 三空型（gold 形态 `域, 次数, 是`）。

  误判守护（历史教训：PB 证明题 39/60 被误判选择题）：
    · 数学正文里的小写 `(a)`/`(b)`、`\\kappa(A)` 调用不得判为选择题。
"""
import os
import unittest

from agent.question_type import (
    QT_CHOICE,
    QT_FILL,
    QT_JUDGE,
    _option_sequence_length,
    classify_question_type,
    extract_options,
    get_question_type_hint,
    lean_applicable,
)

# --------------------------------------------------------------------------
# 真实题面片段（取自 official112，仅保留判定所需部分）
# --------------------------------------------------------------------------
Q_087 = r"""设$D_8$是正方形上的二面体群，下列正确的是：
\begin{itemize}
    \item[A.] $D_8$中存在$8$阶元.
    \item[B.] $D_8$的四阶子群一定是Abel群.
    \item[C.] $C(D_8)=\{1\}$.
    \item[D.] $[D_8,D_8]$是$2$阶群.
\end{itemize}"""

Q_098 = r"""7. 矩阵A 的条件数定义是:

A. \(\kappa(A)=\sqrt{|A|_{1}|A^{-1}|_{1}}\) B. \(\kappa(A)=|A|_{1}|A^{-1}|_{1}\) C. \(\kappa(A)=\sqrt{|A|_{2}|A^{-1}|_{2}}\) D. \(\kappa(A)=|A|_{2}|A^{-1}|_{2}\)"""

Q_103 = "6. 时间序列的构成要素有（）。\n\nA.长期趋势B.季节变动C.循环变动D.不规则变动E.随机变动"

Q_106 = "8、对于一个大型数据集，为了快速了解数据的基本特征，以下哪种统计图形最为合适？（）\n\nA. 直方图B. 散点图C. 箱线图D. 折线图"

Q_102 = "6．正态分布的两个参数分别是（）\n\nA.均值和方差B.均值和标准差C.中位数和方差D.中位数和标准差"

Q_093 = ("下列关于实数集上紧集的描述，正确的是：A. 实数集 $\\mathbb{R}$ 的子集是紧集当且仅当它是闭集。\n"
         "B. 实数集 $\\mathbb{R}$ 的子集是紧集当且仅当它是开集。\n"
         "C. 实数集 $\\mathbb{R}$ 的子集是紧集当且仅当它是闭集且有界。\n"
         "D. 实数集 $\\mathbb{R}$ 的子集是紧集当且仅当它是开集且有界。\n"
         "E. 实数集 $\\mathbb{R}$ 的子集是紧集当且仅当它的每个开覆盖都有有限子覆盖。")

Q_101 = "判断：5. 两个总量指标时间数列相比照得到的时间数列一定是相对数时间数列。（"
Q_111 = "判断：4.异方差性会导致普通最小二乘估计量的方差增大。（"

Q_086 = (r"$x^4+5\in\mathbb{Q}[x]$在$\mathbb{Q}$上的分裂域(记为$E$)是$(\quad)$."
         r"$[E:\mathbb{Q}]=(\quad)$."
         r"$E/\mathbb{Q}$ $(\quad)$(填“是”或“否”.)为Galois扩张.")

# 误判守护样本（数学正文，非选项）
MATH_009 = r"设 $g$ 连续，$\frac{g(a)-g(b)}{a-b}$ 有意义，求 $\lim_{x\to 0} f(x)$。"
MATH_045 = r"分两步：(a) Bob 先取第一张卡片；(b) Ali 后取第二张卡片。求概率。"


class ObjectiveDetectionTest(unittest.TestCase):
    """题型识别：5 类漏检必须全部修回。"""

    def test_latex_item_options_is_choice(self) -> None:
        self.assertEqual(classify_question_type(Q_087), QT_CHOICE)

    def test_options_followed_by_math_is_choice(self) -> None:
        self.assertEqual(classify_question_type(Q_098), QT_CHOICE)

    def test_chinese_inline_options_is_choice(self) -> None:
        for q in (Q_103, Q_106, Q_102):
            self.assertEqual(classify_question_type(q), QT_CHOICE, q[:30])

    def test_five_option_question_is_choice(self) -> None:
        self.assertEqual(classify_question_type(Q_093), QT_CHOICE)

    def test_quad_blank_is_fill(self) -> None:
        self.assertEqual(classify_question_type(Q_086), QT_FILL)

    def test_judge_question(self) -> None:
        for q in (Q_101, Q_111):
            self.assertEqual(classify_question_type(q), QT_JUDGE, q[:20])


class OptionExtractionTest(unittest.TestCase):
    """选项提取：E 项不得丢失，碎片不得混入。"""

    def test_latex_item_options(self) -> None:
        opts = extract_options(Q_087)
        self.assertEqual([lab for lab, _ in opts], ["A", "B", "C", "D"])
        self.assertIn("D_8", opts[0][1])

    def test_math_inside_options_not_fragmented(self) -> None:
        opts = extract_options(Q_098)
        self.assertEqual([lab for lab, _ in opts], ["A", "B", "C", "D"])
        self.assertIn(r"\kappa", opts[0][1])

    def test_five_options_keep_e(self) -> None:
        for q in (Q_103, Q_093):
            opts = extract_options(q)
            self.assertEqual([lab for lab, _ in opts], ["A", "B", "C", "D", "E"], q[:20])

    def test_inline_option_content(self) -> None:
        opts = extract_options(Q_103)
        self.assertEqual(opts[0][1], "长期趋势")
        self.assertEqual(opts[4][1], "随机变动")

    def test_no_options_returns_empty(self) -> None:
        self.assertEqual(extract_options(Q_086), [])
        self.assertEqual(extract_options(MATH_009), [])


class NoFalsePositiveTest(unittest.TestCase):
    """误判守护：数学正文不得判成选择题。"""

    def test_math_body_not_choice(self) -> None:
        for q in (MATH_009, MATH_045):
            self.assertNotEqual(classify_question_type(q), QT_CHOICE, q[:30])

    def test_lowercase_marks_not_counted(self) -> None:
        # 小写 (a)/(b) 是数学调用或分点枚举，不成序列
        self.assertEqual(_option_sequence_length(MATH_009)[0], 0)
        self.assertEqual(_option_sequence_length(MATH_045)[0], 0)

    def test_paren_call_not_counted(self) -> None:
        # `\kappa(A)` 这类右括号形态不认（否则 098 会被切出 8 个碎片）
        self.assertEqual(_option_sequence_length(r"\kappa(A)=\sqrt{|A|_{1}}")[0], 0)


class LeanApplicabilityTest(unittest.TestCase):
    """客观题 Lean 豁免（答案不是数学对象，编译只能得 unknown）。"""

    def test_objective_types_skipped(self) -> None:
        for q in (Q_087, Q_098, Q_103, Q_093, Q_101, Q_111):
            ok, why = lean_applicable(q, classify_question_type(q))
            self.assertFalse(ok, q[:20])
            self.assertIn(why, ("objective_type", "objective_options"))

    def test_math_question_still_applicable(self) -> None:
        ok, _ = lean_applicable("求 $x^2+1=0$ 在复数域上的解。", "")
        self.assertTrue(ok)


class TacticHintTest(unittest.TestCase):
    """特化解法提示词存在且要点齐全。"""

    def test_choice_hint_points(self) -> None:
        hint = get_question_type_hint(QT_CHOICE)
        for kw in ("清点选项", "逐项独立判真", "反例", "连写", "复核"):
            self.assertIn(kw, hint)

    def test_judge_hint_points(self) -> None:
        hint = get_question_type_hint(QT_JUDGE)
        for kw in ("核心断言", "反例", "定义", "正确", "错误"):
            self.assertIn(kw, hint)

    def test_fill_hint_points(self) -> None:
        hint = get_question_type_hint(QT_FILL)
        for kw in ("先后顺序", "逗号", "同一行"):
            self.assertIn(kw, hint)

    def test_proof_hint_untouched(self) -> None:
        # 证明题策略不受本次客观题特化影响（尊重 8/30「证明题不分流」结论）
        hint = get_question_type_hint("证明题")
        self.assertNotIn("客观题特化解法", hint)


class Official112RegressionTest(unittest.TestCase):
    """全量回归：official112 的客观题分布（题库缺失时跳过）。"""

    BANK = os.path.join("题库", "official112_本地测试题库", "official112_full.jsonl")

    def setUp(self) -> None:
        if not os.path.exists(self.BANK):
            self.skipTest("official112 题库不在工作区")

    def _rows(self):
        import json
        with open(self.BANK, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_objective_distribution(self) -> None:
        rows = self._rows()
        self.assertEqual(len(rows), 112)
        kinds = [classify_question_type(r["question"]) for r in rows]
        self.assertEqual(kinds.count(QT_CHOICE), 12, "选择题应恰好 12 道")
        self.assertEqual(kinds.count(QT_JUDGE), 2, "判断题应恰好 2 道")
        self.assertEqual(kinds.count(QT_FILL), 1, "填空题应恰好 1 道（086 三空型）")
        # 12 道选择题 + 2 判断题 + 1 填空题 = 15 道客观题，其余 97 道为解答/证明
        self.assertEqual(kinds.count("解答题"), 97)

    def test_all_choice_options_extractable(self) -> None:
        rows = self._rows()
        for r in rows:
            if classify_question_type(r["question"]) != QT_CHOICE:
                continue
            opts = extract_options(r["question"])
            self.assertGreaterEqual(len(opts), 4, r["id"])


class ObjectiveInjectionTest(unittest.TestCase):
    """注入文本（三条生成路径的共用实现）：客观题拿到选项清单 + 特化纪律。"""

    def test_choice_injection_has_options_and_tactic(self) -> None:
        from agent.question_type import objective_injection
        txt = objective_injection(Q_103, QT_CHOICE, True)
        self.assertIn("[已知选项]", txt)
        self.assertIn("E. 随机变动", txt)
        self.assertIn("逐项独立判真", txt)

    def test_tactic_off_keeps_options(self) -> None:
        # 选项清单属"输入信息补全"始终注入；特化纪律才受开关控制
        from agent.question_type import objective_injection
        txt = objective_injection(Q_103, QT_CHOICE, False)
        self.assertIn("[已知选项]", txt)
        self.assertNotIn("逐项独立判真", txt)

    def test_judge_and_fill_injection(self) -> None:
        from agent.question_type import objective_injection
        self.assertIn("反例", objective_injection(Q_101, QT_JUDGE, True))
        self.assertIn("逗号", objective_injection(Q_086, QT_FILL, True))

    def test_non_objective_empty(self) -> None:
        from agent.question_type import objective_injection
        for qt in ("解答题", "证明题", ""):
            self.assertEqual(objective_injection("求 $x$ 的值", qt, True), "")

    def test_all_choice_samples_get_options(self) -> None:
        from agent.question_type import objective_injection
        for q in (Q_087, Q_098, Q_102, Q_103, Q_106, Q_093):
            self.assertIn("[已知选项]", objective_injection(q, QT_CHOICE, True), q[:20])


if __name__ == "__main__":
    unittest.main()
