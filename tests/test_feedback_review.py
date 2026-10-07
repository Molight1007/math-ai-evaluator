# -*- coding: utf-8 -*-
"""Step 4 bug report 复核（论文流水线）单元测试。

覆盖:
- 反馈属实 → 保留（复核后反馈含原缺陷）
- 反馈误报 → 驳回（返回**空串**；由调用方据此结束 revise，见下方用例说明）
- 复核配置关闭 → 原样返回
- 空/短反馈 → 不触发复核
"""
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, ".")


def _make_ctx_and_orch(mock_responses: list):
    import time
    from agent.base import TaskContext, Budget, Candidate
    from agent.orchestrator import Orchestrator

    class C:
        def __init__(self, responses):
            self._r = list(responses)

        def chat(self, messages=None, temperature=0.0, max_tokens=0, **kw):
            return self._r.pop(0) if self._r else ""

    cfg = SimpleNamespace(enable_feedback_review=True)
    orch = Orchestrator.__new__(Orchestrator)
    orch.config = cfg
    orch.client = C(mock_responses)
    ctx = TaskContext(problem="求 x^2 = 4 的解", metadata={},
                      start_time=time.time(), deadline=time.time() + 600,
                      budget=Budget(max_calls=10))
    ctx.candidates = [Candidate(id=0, answer="2", reasoning="x = ±2，正解 2")]
    return orch, ctx


class ReviewFeedbackTest(unittest.TestCase):
    def test_feedback_kept_when_valid(self) -> None:
        orch, ctx = _make_ctx_and_orch(
            ["缺陷1：漏掉了 x = -2 的解，属实。"])
        out = orch._review_bug_feedback(ctx, "缺陷1：漏掉了 x = -2 的解")
        self.assertIn("漏掉", out)

    def test_feedback_rejected_when_false(self) -> None:
        """判定为误报时返回**空串**（2026-09-17 有意的行为变更）。

        原行为：返回通用提示「解答已较完整，请重新审题核对计算细节后给出最终答案。」
        问题：该句**信息量为零**，却被当作 revise 反馈驱动一整轮"生成 + 验证"
        （实测 official112-099 的 `diag.revise_feedback[0]` 正是这句，属纯浪费）。
        现行为：返回空串 = "复核未发现实质缺陷"，由调用方
        `Orchestrator._deep_revise_loop` 据此**结束回环**而非盲目重解。

        本用例同时保留并锁死原始意图：**被驳回的误报内容不得透传给模型**。
        """
        orch, ctx = _make_ctx_and_orch(["无实质缺陷"])
        out = orch._review_bug_feedback(ctx, "缺陷：x = 2 是错误答案（实际正确）")
        self.assertNotIn("x = 2 是错误答案", out)
        self.assertEqual(out, "")

    def test_disabled_config_passthrough(self) -> None:
        orch, ctx = _make_ctx_and_orch([])
        orch.config = SimpleNamespace(enable_feedback_review=False)
        fb = "缺陷：某个中间步骤符号错误"
        self.assertEqual(orch._review_bug_feedback(ctx, fb), fb)

    def test_short_feedback_skipped(self) -> None:
        orch, ctx = _make_ctx_and_orch([])
        self.assertEqual(orch._review_bug_feedback(ctx, "短"), "短")
        self.assertEqual(orch._review_bug_feedback(ctx, ""), "")

    def test_no_llm_budget_returns_original(self) -> None:
        import time
        from agent.base import TaskContext, Budget
        from agent.orchestrator import Orchestrator
        from types import SimpleNamespace as NS
        orch = Orchestrator.__new__(Orchestrator)
        orch.config = NS(enable_feedback_review=True)
        orch.client = None
        ctx = TaskContext(problem="p", metadata={},
                          start_time=time.time(), deadline=time.time() + 600,
                          budget=Budget(max_calls=0))  # 预算耗尽
        fb = "缺陷：某处符号错误（影响结果）"
        self.assertEqual(orch._review_bug_feedback(ctx, fb), fb)


class ReviewFeedbackLengthCapTest(unittest.TestCase):
    """★ 2026-10-06：复核产物**长度上限**（治实测 157,550 字符裸输出）。

    依据（审计已确认）：official112-007 单题 `_review_bug_feedback` 返回
    157,550 字符（英文独白 + 同一条 Lean 消息重复几十遍），经 `ctx.revise_feedback`
    被 `solver._generate_revise` 原样拼进提示词 ⇒ 提示词被灌爆。
    上限与 verifier 复核反馈同口径（`verifier.py:1821` 结构化分支 `[:8000]`），
    **保头**截断（复核结论在开头），末尾加「…（已截断）」。
    """

    def test_long_output_body_is_capped_head_preserved(self) -> None:
        body = "保留的缺陷清单：\n" + ("英文独白 repeated Lean message. " * 6000)
        orch, ctx = _make_ctx_and_orch([body])
        out = orch._review_bug_feedback(ctx, "缺陷：某处符号错误（影响结果）")
        self.assertLess(len(out), 8100, "超长复核产物必须被截断")
        self.assertTrue(out.startswith("保留的缺陷清单"), "截断必须保头（结论在开头）")
        self.assertTrue(out.endswith("…（已截断）"), "末尾须有截断标记")

    def test_cap_zero_disables_truncation(self) -> None:
        from types import SimpleNamespace as NS
        body = "保留的缺陷清单：\n" + ("x" * 20000)
        orch, ctx = _make_ctx_and_orch([body])
        orch.config = NS(enable_feedback_review=True, feedback_review_max_chars=0)
        out = orch._review_bug_feedback(ctx, "缺陷：某处符号错误（影响结果）")
        self.assertGreater(len(out), 19000, "max_chars=0 ⇒ 不截断（回退旧行为）")


class MergeReviewIntoFeedbackTest(unittest.TestCase):
    """★ 2026-10-06：复核产物**附加**而非覆盖 —— 保住 verifier 的深复核推理段。

    依据（审计已确认）：`verifier.py:1819-1821` 已把深复核推理（
    `【复核依据（判错报告原文摘录）】`，上限 8000）保留进 feedback，但旧的
    `feedback = _rv` 覆盖式写法把它整段摘要掉 ⇒ 实测 q1–q6 最终
    `diag.revise_feedback` 最长仅 2.4–3.0k 且不含该段。
    """

    def test_append_keeps_original_reasoning(self) -> None:
        from agent.orchestrator import _merge_review_into_feedback
        original = ("【带推理复核判错｜错误类型：漏项】…\n\n"
                    "【复核依据（判错报告原文摘录）】\n真实推理段（应到达模型）")
        review = "保留的缺陷：① 漏了 x=-2 的解"
        out = _merge_review_into_feedback(original, review, append=True)
        self.assertIn("真实推理段（应到达模型）", out, "深复核推理段不得被抹掉")
        self.assertIn(review, out)
        self.assertIn("【复核意见", out)

    def test_replace_fallback_for_ab(self) -> None:
        from agent.orchestrator import _merge_review_into_feedback
        out = _merge_review_into_feedback("原文推理", "复核清单", append=False)
        self.assertEqual(out, "复核清单", "append=False ⇒ 回退旧的整段覆盖")

    def test_empty_review_keeps_original(self) -> None:
        from agent.orchestrator import _merge_review_into_feedback
        self.assertEqual(_merge_review_into_feedback("原文", "", append=True), "原文")


if __name__ == "__main__":
    unittest.main()
