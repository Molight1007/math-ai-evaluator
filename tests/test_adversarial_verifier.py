# -*- coding: utf-8 -*-
"""对抗式验证器（AdversarialVerifier）单元测试。

背景（基线 45 题）：
- 两层复核一致性仅 51%，单层过双层不过 22 题（其中 7 题其实对，误杀 31.8%）
- **反向案例 0 条** → 第二层不是独立复核，只是单纯加严
- 正向验证存在漏检

本模块用「证伪」补上漏检那一侧：正向问"这对吗"，对抗式问"假设它错了，错在哪"。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.adversarial_verifier import (
    AdversarialResult,
    AdversarialVerifier,
    ERROR_CHECKLIST,
    _ERROR_TYPES,
)


def _cfg(**kw):
    class C:
        enable_adversarial_verify = True
        adversarial_tiers = ("deep", "standard")
        adversarial_min_confidence = 0.5
        adversarial_max_tokens = 640
        adversarial_max_reasoning = 2400

    c = C()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


class _Cand:
    def __init__(self, reasoning="推理过程", answer="42"):
        self.reasoning = reasoning
        self.answer = answer


class _Ctx:
    def __init__(self, problem="求 x"):
        self.problem = problem
        self.trace = []
        self.budget = None


class TestErrorChecklist(unittest.TestCase):
    """6 类错误 checklist 本身（每条都对应真实错题样本）。"""

    def test_six_categories(self):
        self.assertEqual(len(ERROR_CHECKLIST), 6)
        self.assertEqual(len(_ERROR_TYPES), 6)

    def test_categories_have_real_samples(self):
        """每类都必须能对应到基线里的真实错题，否则是拍脑袋编的。"""
        expected = {
            "sign_error": "algebra-064",
            "skipped_step": "geometry-068",
            "boundary_missed": "number_theory-022",
            "special_case_missed": "algebra-003",
            "calculation_error": "geometry-051",
            "misread_requirement": "combinatorics-040",
        }
        for key in _ERROR_TYPES:
            self.assertIn(key, expected)


class TestParse(unittest.TestCase):
    """JSON 解析与归一化：模型输出不可控，解析必须健壮。"""

    def test_found_true(self):
        r = AdversarialVerifier._parse(
            '{"found": true, "error_type": "calculation_error", '
            '"error_step": "121/125 + 25 = 24", "counterexample": "应为 3246/125", '
            '"confidence": 0.9, "reasoning": "算术错误"}')
        self.assertTrue(r.found)
        self.assertEqual(r.error_type, "calculation_error")
        self.assertEqual(r.error_step, "121/125 + 25 = 24")
        self.assertEqual(r.counterexample, "应为 3246/125")
        self.assertAlmostEqual(r.confidence, 0.9)
        self.assertTrue(r.parsed)

    def test_found_false(self):
        r = AdversarialVerifier._parse(
            '{"found": false, "error_type": "", "error_step": "", '
            '"counterexample": "", "confidence": 0.8, "reasoning": "未找到"}')
        self.assertFalse(r.found)
        self.assertTrue(r.parsed)

    def test_chinese_error_type_normalized(self):
        """模型常回中文类型，必须归一化到 6 类之一，否则污染统计。"""
        cases = {
            "计算错误": "calculation_error",
            "符号错误": "sign_error",
            "跳步": "skipped_step",
            "边界遗漏": "boundary_missed",
            "特殊情形未排除": "special_case_missed",
            "未理解题目要求": "misread_requirement",
            "答非所问": "misread_requirement",
        }
        for raw, want in cases.items():
            got = AdversarialVerifier._parse(
                '{"found": true, "error_type": "%s", "error_step": "x", '
                '"confidence": 0.9}' % raw).error_type
            self.assertEqual(got, want, f"{raw} → {got}，期望 {want}")

    def test_unknown_error_type_dropped(self):
        """识别不了的类型宁可置空，也不能让脏值进统计。"""
        r = AdversarialVerifier._parse(
            '{"found": true, "error_type": "完全无关的词", "confidence": 0.9}')
        self.assertEqual(r.error_type, "")

    def test_truncated_json_salvaged(self):
        """输出被截断时逐步回退 salvage，而不是整个丢弃。"""
        r = AdversarialVerifier._parse(
            '{"found": true, "error_type": "sign_error", "error_step')
        self.assertTrue(r.parsed)
        self.assertTrue(r.found)
        self.assertEqual(r.error_type, "sign_error")

    def test_garbage_returns_not_found(self):
        """解析不了就当没抓到——不可信的结果不能触发 revise。"""
        r = AdversarialVerifier._parse("完全不是 JSON")
        self.assertFalse(r.parsed)
        self.assertFalse(r.found)
        self.assertEqual(r.skipped, "parse_failed")

    def test_confidence_clamped(self):
        r = AdversarialVerifier._parse('{"found": true, "confidence": 9.9}')
        self.assertAlmostEqual(r.confidence, 1.0)


class TestResultSemantics(unittest.TestCase):
    """结果语义：什么才算"足以触发 revise"。"""

    def test_found_without_location_not_actionable(self):
        """只说找到错但给不出位置 → 不可信，不触发 revise（防误伤）。"""
        self.assertFalse(AdversarialResult(found=True).is_actionable)

    def test_found_with_step_is_actionable(self):
        self.assertTrue(AdversarialResult(
            found=True, error_step="第 3 步").is_actionable)

    def test_found_with_counterexample_is_actionable(self):
        self.assertTrue(AdversarialResult(
            found=True, counterexample="n=2 时不成立").is_actionable)

    def test_not_found_not_actionable(self):
        self.assertFalse(AdversarialResult(found=False, error_step="x").is_actionable)

    def test_to_feedback_contains_checklist_label(self):
        r = AdversarialResult(found=True, error_type="skipped_step",
                              error_step="Solving yields s=187/228",
                              counterexample="需完整推导", confidence=0.9)
        fb = r.to_feedback()
        self.assertIn("对抗式审查", fb)
        self.assertIn("跳步", fb)
        self.assertIn("Solving yields", fb)
        self.assertIn("需完整推导", fb)

    def test_to_feedback_empty_when_not_actionable(self):
        self.assertEqual(AdversarialResult(found=True).to_feedback(), "")


class TestProbeGuards(unittest.TestCase):
    """探测的护栏：该跑的跑，不该跑的别浪费调用。"""

    def test_disabled_skips(self):
        v = AdversarialVerifier(None, _cfg(enable_adversarial_verify=False))
        r = v.probe(_Ctx(), _Cand(), tier="deep")
        self.assertEqual(r.skipped, "disabled")
        self.assertFalse(r.found)

    def test_tier_not_covered_skips(self):
        """fast 档是快速通道，不该为它加一次 LLM 调用。"""
        v = AdversarialVerifier(None, _cfg())
        r = v.probe(_Ctx(), _Cand(), tier="fast")
        self.assertIn("tier_not_covered", r.skipped)

    def test_empty_reasoning_skips(self):
        v = AdversarialVerifier(None, _cfg())
        r = v.probe(_Ctx(), _Cand(reasoning="  "), tier="deep")
        self.assertEqual(r.skipped, "empty_reasoning")

    def test_low_confidence_not_trusted(self):
        """置信度低于阈值 → 不采信。宁可漏掉，不可误伤。"""
        v = AdversarialVerifier(None, _cfg(adversarial_min_confidence=0.6))
        with patch.object(AdversarialVerifier, "_call_probe",
                          return_value='{"found": true, "error_type": "sign_error", '
                                       '"error_step": "第2步符号反了", "confidence": 0.3}'):
            r = v.probe(_Ctx(), _Cand(), tier="deep")
        self.assertFalse(r.found, "低置信检出不应被采信")

    def test_high_confidence_accepted(self):
        v = AdversarialVerifier(None, _cfg(adversarial_min_confidence=0.5))
        with patch.object(AdversarialVerifier, "_call_probe",
                          return_value='{"found": true, "error_type": "sign_error", '
                                       '"error_step": "第2步符号反了", "confidence": 0.9}'):
            r = v.probe(_Ctx(), _Cand(), tier="deep")
        self.assertTrue(r.found)
        self.assertEqual(r.error_type, "sign_error")

    def test_call_failure_degrades_to_not_found(self):
        """调用异常绝不向上抛——验证器的问题不能阻断主流程。"""
        v = AdversarialVerifier(None, _cfg())
        with patch.object(AdversarialVerifier, "_call_probe",
                          side_effect=RuntimeError("API down")):
            r = v.probe(_Ctx(), _Cand(), tier="deep")
        self.assertFalse(r.found)
        self.assertIn("call_failed", r.skipped)

    def test_probe_never_raises_on_bad_candidate(self):
        v = AdversarialVerifier(None, _cfg())
        r = v.probe(_Ctx(), object(), tier="deep")   # 无 reasoning 属性
        self.assertFalse(r.found)


class ReasoningProjectionTest(unittest.TestCase):
    """4.2 的 reasoning 投影口径（2026-10-27）。

    原来 `reasoning[-_max_reasoning:]` 是**从尾部**硬切：reasoning 结构是
    「题目目标 → 子目标规划 → 逐步求解 → 最终答案」，从尾切只剩最后几步，
    前面的子目标对审查者完全不可见。而单步正文变长后（3 的出口修复）
    可见步数还会继续下降 —— 实测平均可见步 75.5% → 55.3%。

    现统一走 `subgoal_result.clip_reasoning`：骨架限额 + 各步均分，
    保证每一步都能露头，预算数值不变。
    """

    @staticmethod
    def _reasoning(n_steps=8, step_len=400):
        parts = ["# 子目标分解求解过程", "## 题目目标", "要做什么: " + "z" * 200,
                 "## 子目标规划"]
        for i in range(1, n_steps + 1):
            parts.append(f"  #{i} [proof] 步骤{i}: 说明")
        parts.append("## 逐步求解")
        for i in range(1, n_steps + 1):
            parts.append(f"### 子目标 #{i}「步骤{i}」")
            parts.append("结果: 结论" + str(i) + "。" + "推导文字" * (step_len // 4))
        parts.append("## 最终答案")
        parts.append("42")
        return "\n".join(parts)

    def _capture_prompt(self, reasoning, budget=2400):
        """跑一次 _call_probe，截下真正送进模型的 messages。

        打桩打在 `llm` 上而不是 `client` 上：`_call_probe` 用的是
        `BaseAgent.llm`（要读 ctx.deadline 等），直接把 llm 换掉就不必造完整 ctx。
        """
        seen = {}

        def _fake_llm(_self, ctx, msgs, **kw):
            seen["msgs"] = msgs
            return '{"found": false}'

        v = AdversarialVerifier(None, _cfg(adversarial_max_reasoning=budget))
        with patch.object(AdversarialVerifier, "llm", _fake_llm):
            v._call_probe(_Ctx(), reasoning, "42")
        return "\n".join(m["content"] for m in seen["msgs"])

    def test_every_step_is_visible_to_verifier(self):
        """8 步 × 400 字，预算 2400 —— 尾截只会剩最后 6 步左右。"""
        prompt = self._capture_prompt(self._reasoning())
        missing = [i for i in range(1, 9) if f"### 子目标 #{i}「" not in prompt]
        self.assertEqual(missing, [], f"这些步骤对 4.2 不可见：{missing}")

    def test_first_step_conclusion_reaches_verifier(self):
        """第一步的结论必须能进 prompt（尾截会把它切掉）。"""
        prompt = self._capture_prompt(self._reasoning())
        self.assertIn("结论1", prompt)

    def test_budget_is_respected(self):
        """预算数值本身不动，投影后不得显著超出。"""
        budget = 2400
        prompt = self._capture_prompt(self._reasoning(20, 800), budget)
        # prompt 里除了 reasoning 还有题目/清单等固定内容，给固定余量
        self.assertLess(len(prompt), budget + 4000,
                        f"投影后总长 {len(prompt)} 明显超预算 {budget}")

    def test_short_reasoning_passes_through_unchanged(self):
        """短 reasoning 不该被裁剪改动。"""
        short = "### 子目标 #1「唯一一步」\n结果: 答案 42"
        prompt = self._capture_prompt(short)
        self.assertIn("答案 42", prompt)


if __name__ == "__main__":
    unittest.main()
