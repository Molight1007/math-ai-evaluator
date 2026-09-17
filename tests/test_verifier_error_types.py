# -*- coding: utf-8 -*-
"""验证器「结构化错误类型」埋点单元测试（2026-09-15）。

背景
----
用户要求「之后测试记录大模型的具体答题情况，把错误暴露得更加具体」。

改动前：trace 里每张投票只留 ``correct`` / ``abstain`` / ``raw``，错因**全埋在
自然语言里** ⇒ 无法统计，归因只能靠人工读日志（"推理错 62 题"就是这么数出来的）。
改动后：``VERIFIER_SYSTEM`` 判 B 时必须从**封闭标签集**回带错误类型
（``agent/verifier.py: ERROR_TYPE_TAGS``），verifier 抽取 → 聚合 → 落 trace →
orchestrator ``_collect_diag()`` 汇总成 ``diag["error_types"]``。

同时回应李平老师「推理中会不会硬套某个定理」的疑问：新增的 ``方法不适用`` /
``前提不成立`` / ``方向反了`` 三个标签正是"硬套"的可观测判据。

覆盖:
- ``_extract_error_type``: 封闭标签集、多标签、去重保序、非标签文本过滤
- ``VerifierAgent._error_type_dist``: 计数口径（弃权票不计）
- ``VerifierAgent._record_error_types``: trace 落盘与空值安静返回
- ``Verdict.error_type``: 默认空串向后兼容
- ``orchestrator._merge_error_types`` / ``_sum_reject_votes``: diag 收拢口径
"""
import unittest
from types import SimpleNamespace

from agent.base import Verdict
from agent.verifier import (
    ERROR_TYPE_TAGS,
    VerifierAgent,
    _extract_error_type,
)
from agent.orchestrator import _merge_error_types, _sum_reject_votes


def make_verifier() -> VerifierAgent:
    return VerifierAgent(client=object(), config=SimpleNamespace())


def make_ctx(trace=None):
    return SimpleNamespace(trace=list(trace or []))


class ExtractErrorTypeTest(unittest.TestCase):
    """``_extract_error_type``：只认封闭标签集，返回逗号分隔串。"""

    def test_single_tag_full_width_paren(self):
        self.assertEqual(
            _extract_error_type("VERDICT: B（方法不适用）"), "方法不适用")

    def test_single_tag_half_width_paren(self):
        self.assertEqual(_extract_error_type("VERDICT: B(计算错)"), "计算错")

    def test_multiple_tags_preserve_order_and_dedup(self):
        got = _extract_error_type("裁定：B（跳步、符号错、跳步）")
        self.assertEqual(got, "跳步,符号错")

    def test_two_tags_on_one_line(self):
        self.assertEqual(
            _extract_error_type("VERDICT: B（方法不适用, 前提不成立）"),
            "方法不适用,前提不成立")

    def test_verdict_a_has_no_error_type(self):
        self.assertEqual(_extract_error_type("VERDICT: A"), "")

    def test_empty_text(self):
        self.assertEqual(_extract_error_type(""), "")

    def test_none_text(self):
        self.assertEqual(_extract_error_type(None), "")

    def test_fabricated_tag_is_filtered(self):
        """模型自造标签不得进入统计 —— 否则归因被新词污染。"""
        self.assertEqual(_extract_error_type("VERDICT: B（我自造的新词）"), "")

    def test_other_tag_is_kept(self):
        self.assertEqual(_extract_error_type("VERDICT: B（其它）"), "其它")

    def test_closed_tag_set_contains_hard_wrap_markers(self):
        """回应李平老师「硬套定理」：三个"硬套"判据必须在封闭集内。"""
        for tag in ("方法不适用", "前提不成立", "方向反了"):
            self.assertIn(tag, ERROR_TYPE_TAGS)


class ErrorTypeDistTest(unittest.TestCase):
    """``_error_type_dist``：只统计判 B 且带回标签的票。"""

    def test_counts_by_tag(self):
        vs = [
            Verdict(correct=False, error_type="计算错,跳步"),
            Verdict(correct=False, error_type="计算错"),
            Verdict(correct=True, error_type=""),          # A 票无标签
            Verdict(correct=False, abstain=True, error_type=""),  # 弃权票
            Verdict(correct=False, error_type="其它"),
        ]
        self.assertEqual(
            VerifierAgent._error_type_dist(vs),
            {"计算错": 2, "跳步": 1, "其它": 1})

    def test_empty_list(self):
        self.assertEqual(VerifierAgent._error_type_dist([]), {})

    def test_none_list(self):
        self.assertEqual(VerifierAgent._error_type_dist(None), {})

    def test_whitespace_tags_are_stripped(self):
        vs = [Verdict(correct=False, error_type="计算错, 跳步")]
        self.assertEqual(
            VerifierAgent._error_type_dist(vs), {"计算错": 1, "跳步": 1})


class RecordErrorTypesTest(unittest.TestCase):
    """``_record_error_types``：落 trace，无 B 票时保持安静。"""

    def setUp(self):
        self.v = make_verifier()

    def test_writes_trace_entry_with_dist_and_count(self):
        ctx = make_ctx()
        vs = [
            Verdict(correct=False, error_type="计算错"),
            Verdict(correct=False, error_type="计算错,方法不适用"),
            Verdict(correct=True, error_type=""),
        ]
        dist = self.v._record_error_types(ctx, vs)
        self.assertEqual(dist, {"计算错": 2, "方法不适用": 1})
        self.assertEqual(len(ctx.trace), 1)
        entry = ctx.trace[0]
        self.assertEqual(entry["step"], "vote_error_types")
        self.assertEqual(entry["error_types"], dist)
        # 判 B 票数 = 2（A 票不计）
        self.assertEqual(entry["n_reject"], 2)
        # 人类可读摘要按票数降序
        self.assertIn("计算错×2", entry["content"])

    def test_custom_step_name(self):
        ctx = make_ctx()
        self.v._record_error_types(
            ctx, [Verdict(correct=False, error_type="跳步")],
            step="verify_error_types")
        self.assertEqual(ctx.trace[0]["step"], "verify_error_types")

    def test_no_reject_votes_writes_nothing(self):
        ctx = make_ctx()
        self.v._record_error_types(
            ctx, [Verdict(correct=True, error_type="")])
        self.assertEqual(ctx.trace, [])

    def test_reject_without_tag_is_counted_but_dist_empty(self):
        """模型没按格式回带标签时仍要记数（否则误读成"没有错误"）。"""
        ctx = make_ctx()
        dist = self.v._record_error_types(
            ctx, [Verdict(correct=False, error_type="")])
        self.assertEqual(dist, {})
        self.assertEqual(ctx.trace[0]["n_reject"], 1)
        self.assertIn("模型未回带标签", ctx.trace[0]["content"])

    def test_returns_dict_even_when_empty(self):
        ctx = make_ctx()
        self.assertEqual(
            self.v._record_error_types(ctx, []), {})


class VerdictDefaultTest(unittest.TestCase):
    """``Verdict.error_type`` 默认空串 —— 老代码不传该参数也能工作。"""

    def test_default_empty(self):
        self.assertEqual(Verdict(correct=True).error_type, "")

    def test_explicit_value(self):
        self.assertEqual(
            Verdict(correct=False, error_type="符号错").error_type, "符号错")


class OrchestratorMergeTest(unittest.TestCase):
    """diag 收拢：整题口径优先，单次投票口径回退。"""

    def test_prefers_verify_scope(self):
        ctx = make_ctx([
            {"step": "vote_error_types",
             "error_types": {"计算错": 3}, "n_reject": 3},
            {"step": "verify_error_types",
             "error_types": {"方法不适用": 2, "计算错": 5}, "n_reject": 7},
        ])
        self.assertEqual(
            _merge_error_types(ctx), {"方法不适用": 2, "计算错": 5})
        self.assertEqual(_sum_reject_votes(ctx), 7)

    def test_falls_back_to_vote_scope(self):
        ctx = make_ctx([
            {"step": "vote_error_types",
             "error_types": {"跳步": 2}, "n_reject": 2}])
        self.assertEqual(_merge_error_types(ctx), {"跳步": 2})
        # 无整题口径记录 → 0
        self.assertEqual(_sum_reject_votes(ctx), 0)

    def test_vote_scope_accumulates(self):
        ctx = make_ctx([
            {"step": "vote_error_types",
             "error_types": {"跳步": 1}, "n_reject": 1},
            {"step": "vote_error_types",
             "error_types": {"跳步": 2, "计算错": 1}, "n_reject": 3},
        ])
        self.assertEqual(_merge_error_types(ctx), {"跳步": 3, "计算错": 1})

    def test_empty_trace(self):
        self.assertEqual(_merge_error_types(make_ctx()), {})
        self.assertEqual(_sum_reject_votes(make_ctx()), 0)

    def test_ignores_malformed_entries(self):
        ctx = make_ctx([
            "not-a-dict",
            {"step": "other", "error_types": {"计算错": 9}},
            {"step": "verify_error_types", "error_types": "not-a-dict"},
        ])
        self.assertEqual(_merge_error_types(ctx), {})
        self.assertEqual(_sum_reject_votes(ctx), 0)

    def test_ctx_without_trace_attribute(self):
        self.assertEqual(_merge_error_types(SimpleNamespace()), {})
        self.assertEqual(_sum_reject_votes(SimpleNamespace()), 0)


if __name__ == "__main__":
    unittest.main()
