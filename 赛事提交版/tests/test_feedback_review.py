# -*- coding: utf-8 -*-
"""Step 4 bug report 复核（论文流水线）单元测试。

覆盖:
- 反馈属实 → 保留（复核后反馈含原缺陷）
- 反馈误报 → 驳回（返回"无实质缺陷"降级提示）
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
        orch, ctx = _make_ctx_and_orch(["无实质缺陷"])
        out = orch._review_bug_feedback(ctx, "缺陷：x = 2 是错误答案（实际正确）")
        self.assertNotIn("x = 2 是错误答案", out)
        self.assertIn("重新审题", out)  # 降级为通用提示

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


if __name__ == "__main__":
    unittest.main()
