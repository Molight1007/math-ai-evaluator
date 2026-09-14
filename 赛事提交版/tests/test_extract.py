# -*- coding: utf-8 -*-
"""答案提取与规范化纯函数单元测试。

覆盖:
- ``extract_final_answer``: 显式标记 / boxed / 尾部有效行
- ``normalize_answer``: LaTeX 归一化 / 隐式乘法 / 数值统一 / 单位剥离
- ``rescue_final_answer``: boxed / 强结论模式 / 尾部兜底
"""
import unittest

from utils.extract import (
    extract_final_answer,
    normalize_answer,
    rescue_final_answer,
)


class ExtractFinalAnswerTest(unittest.TestCase):
    def test_empty_input(self) -> None:
        self.assertEqual(extract_final_answer(""), "")
        self.assertEqual(extract_final_answer(None), "")

    def test_explicit_final_answer_marker(self) -> None:
        text = (
            "推导过程：\n"
            "先求导，再化简。\n\n"
            "【最终答案】\n"
            "5"
        )
        self.assertEqual(extract_final_answer(text), "5")

    def test_final_answer_colon(self) -> None:
        text = r"经过一系列计算，最终答案：\frac{1}{2}"
        self.assertIn("\\frac", extract_final_answer(text))

    def test_boxed_answer(self) -> None:
        text = r"化简得 \boxed{7}，因此结论成立。"
        self.assertEqual(extract_final_answer(text), "7")

    def test_nested_boxed(self) -> None:
        text = r"答案 \boxed{\frac{1}{3}} 是唯一解。"
        ans = extract_final_answer(text)
        self.assertIn("1", ans)
        self.assertIn("3", ans)

    def test_tail_valid_line(self) -> None:
        text = "计算过程略。\n因此可得答案为 42。"
        ans = extract_final_answer(text)
        # 中文结论句无强模式命中时，兜底返回整行（含答案）
        self.assertIn("42", ans)

    def test_shell_output_rejected(self) -> None:
        """回归：纯定界符 / 纯标题的"空壳"输出必须返回空串。

        历史失败样本（本地评测 45 条里 4 条）：模型答案区只写出 `$$`、`\\[`
        或 `## 最终答案`，此前会被尾部兜底策略原样返回并当作答案提交，        判分器必然判错。返回空串才能让调用方换用其它候选或重试。
        """
        for shell in ("$$", r"\[", "## 最终答案", "#### Answer", "$", "## 最终答案\n"):
            self.assertEqual(extract_final_answer(shell), "",
                             f"空壳输出 {shell!r} 应被判为无答案内容")

    def test_real_answer_not_rejected(self) -> None:
        """反例：含实质内容的答案不得被空壳过滤误杀。"""
        for real in ("42", "$42$", r"\boxed{42}", "3", "x = 2", "A", "1,3,5"):
            self.assertNotEqual(extract_final_answer(real), "",
                                f"正常答案 {real!r} 不应被过滤")


class NormalizeAnswerTest(unittest.TestCase):
    def test_latex_fraction_to_decimal(self) -> None:
        self.assertEqual(normalize_answer(r"\frac{1}{2}"), "0.5")

    def test_implicit_multiplication(self) -> None:
        self.assertEqual(normalize_answer("2x"), "2*x")

    def test_trailing_zero_removed(self) -> None:
        self.assertEqual(normalize_answer("3.0"), "3")

    def test_unit_stripped(self) -> None:
        self.assertEqual(normalize_answer("5cm"), "5")
        self.assertEqual(normalize_answer("120s"), "120")

    def test_set_standardized(self) -> None:
        self.assertEqual(normalize_answer("{1,2,3}"), "[1,2,3]")

    def test_prefix_label_stripped(self) -> None:
        self.assertEqual(normalize_answer("答案：4"), "4")

    def test_empty_input(self) -> None:
        self.assertEqual(normalize_answer(""), "")
        self.assertEqual(normalize_answer(None), "")


class RescueFinalAnswerTest(unittest.TestCase):
    def test_boxed_source(self) -> None:
        text = r"推理……最终 \boxed{8}。"
        ans, source = rescue_final_answer(text)
        self.assertEqual(ans, "8")
        self.assertEqual(source, "boxed")

    def test_strong_pattern_source(self) -> None:
        text = "N = 3 is a valid candidate for the problem."
        ans, source = rescue_final_answer(text)
        self.assertEqual(ans, "3")
        self.assertEqual(source, "strong_pattern")

    def test_tail_fallback_source(self) -> None:
        text = "先列方程，再化简，最后得到\nx = 2"
        ans, source = rescue_final_answer(text)
        # "x = 2" 命中尾部弱赋值模式，属于强模式分支
        self.assertEqual(ans, "2")
        self.assertEqual(source, "strong_pattern")

    def test_tail_fallback_chinese_line(self) -> None:
        text = "推导完成\n因此答案为 2"
        ans, source = rescue_final_answer(text)
        # 中文结论行无强模式命中，走尾部兜底，返回整行
        self.assertIn("2", ans)
        self.assertEqual(source, "tail_fallback")

    def test_empty_input(self) -> None:
        self.assertEqual(rescue_final_answer(""), ("", ""))
        self.assertEqual(rescue_final_answer(None), ("", ""))


class UnbalancedMathDelimsTest(unittest.TestCase):
    """2026-09-11：截断的推理正文不得进入答案（Bug清单 §6 / #006 实况）。

    #006 提交的答案是 `假设 \\( A(0) = 0 \\)，代入 \\( p = 1 \\) 和 \\( q`
    （39 字符、句子中间硬断）：既不可判分，又被当作锚串喂给 Lean 污染判定。
    """

    def test_truncated_reasoning_rejected(self) -> None:
        from utils.extract import _clean_extracted_answer
        # 3 个 \( 配 2 个 \) → 未闭合 → 判无效
        text = "假设 \\( A(0) = 0 \\)，代入 \\( p = 1 \\) 和 \\( q"
        self.assertEqual(_clean_extracted_answer(text), "")

    def test_properly_paired_latex_kept(self) -> None:
        from utils.extract import _clean_extracted_answer
        text = "\\( A(x) = 1 - x \\)"
        self.assertEqual(_clean_extracted_answer(text), text)

    def test_odd_dollar_rejected_even_kept(self) -> None:
        from utils.extract import _clean_extracted_answer
        self.assertEqual(_clean_extracted_answer("$x^2$"), "$x^2$")
        self.assertEqual(_clean_extracted_answer("答案是 $x^2"), "")

    def test_plain_answer_unaffected(self) -> None:
        from utils.extract import _clean_extracted_answer
        # 不含任何定界符的正常答案不得被误杀
        self.assertEqual(_clean_extracted_answer("524288"), "524288")
        self.assertEqual(_clean_extracted_answer(r"\boxed{16}"), r"\boxed{16}")

    def test_rescue_skips_unbalanced_tail(self) -> None:
        from utils.extract import rescue_final_answer
        ans, src = rescue_final_answer("推理……\n假设 \\( A(0) = 0 \\)，代入 \\( p = 1 \\) 和 \\( q")
        self.assertNotIn("\\( q", ans)


class StripContinuationMarkersTest(unittest.TestCase):
    """2026-08-29 回归：Intern 会回显 `[续写]` 占位符污染最终答案。"""

    def test_marker_in_answer(self) -> None:
        from utils.extract import clean_answer
        # 真实失败样本：algebra-075 答案 `3\n\n[续写]\n--- 请继续 ---`
        self.assertEqual(clean_answer("3\n\n[续写]\n--- 请继续 ---"), "3")

    def test_marker_mid_answer(self) -> None:
        from utils.extract import clean_answer
        self.assertEqual(
            clean_answer("x = 2 [续写] --- 请继续 --- 因此 y = 3"), "x = 2 因此 y = 3")

    def test_marker_variants(self) -> None:
        from utils.extract import _strip_continuation_markers
        for bad in ("[续写]", "--- 请继续 ---", "请继续完成", "[TBC]"):
            self.assertNotIn(bad, _strip_continuation_markers(f"答案{bad}"))

    def test_normal_answer_untouched(self) -> None:
        from utils.extract import clean_answer
        self.assertEqual(clean_answer("\\boxed{3}"), "\\boxed{3}")
        self.assertEqual(clean_answer("1307674368000"), "1307674368000")


if __name__ == "__main__":
    unittest.main()


class CalcMarkerStripTest(unittest.TestCase):
    """2026-09-06 P4：模型截断在 <calc> 处 → 裸 calc 标记污染答案（comb-022
    pred='<calc>' 整题格式丢分实测）；resolve 正则需要闭合标签不处理，
    extract_final_answer 出口统一剥除后按空壳走调用方兜底。"""

    def _imports(self):
        from utils.extract import _strip_calc_markers, extract_final_answer
        return _strip_calc_markers, extract_final_answer

    def test_bare_calc_is_empty(self) -> None:
        _, extract = self._imports()
        self.assertEqual(extract("<calc>"), "")
        self.assertEqual(extract("<calc>\n"), "")
        self.assertEqual(extract("</calc>"), "")

    def test_calc_in_prose_stripped(self) -> None:
        strip, _ = self._imports()
        out = strip("先算 <calc>1/2+1/3</calc> 得 5/6")
        self.assertNotIn("calc", out)
        self.assertIn("先算", out)
        self.assertIn("5/6", out)

    def test_resolved_text_untouched(self) -> None:
        _, extract = self._imports()
        self.assertEqual(extract("【最终答案】: \\boxed{1960000}"), "\\boxed{1960000}")

    def test_normal_number_untouched(self) -> None:
        _, extract = self._imports()
        self.assertEqual(extract("25502500"), "25502500")
