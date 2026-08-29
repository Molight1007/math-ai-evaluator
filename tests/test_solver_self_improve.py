# -*- coding: utf-8 -*-
"""SolverAgent 的 Step 2 无条件自改进（IMO2025 论文）单元测试。

覆盖:
- ``improve_candidates``: 改进成功更新 reasoning/answer
- 拒绝/空响应不覆盖原候选
- 明显更差的改进（过短）被丢弃
- 预算不足时跳过
"""
import unittest
import time
from types import SimpleNamespace

from agent.base import TaskContext, Budget, Candidate
from agent.solver import SolverAgent

IMPROVED = (
    "## 问题分析\n重新审视题目。\n"
    "## 详细解题步骤\n步骤1：正确计算。\n"
    "## 最终答案\n42\n"
    "## 关键验证点\n代入检验通过。"
)
REFUSAL = "抱歉，我无法解答这个问题。"
SHORT = "## 最终答案\n42"


def make_solver(response: str) -> SolverAgent:
    class C:
        def chat(self, messages=None, temperature=0.0, max_tokens=0, **kw):
            return response
    return SolverAgent(client=C(), config=SimpleNamespace(
        use_blueprint=False,
        self_improve_max=3,
        policy_temperature=0.3,
        policy_max_tokens=8192,
    ))


def make_ctx(max_calls: int = 10) -> TaskContext:
    return TaskContext(
        problem="求 x^2 = 4 的解",
        metadata={},
        start_time=time.time(),
        deadline=time.time() + 600,
        budget=Budget(max_calls=max_calls),
    )


class ImproveCandidatesTest(unittest.TestCase):
    def test_improves_candidate(self) -> None:
        s = make_solver(IMPROVED)
        ctx = make_ctx()
        ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答内容"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 1)
        self.assertIn("步骤1", ctx.candidates[0].reasoning)  # 已更新
        self.assertEqual(ctx.candidates[0].answer, "42")

    def test_refusal_keeps_original(self) -> None:
        s = make_solver(REFUSAL)
        ctx = make_ctx()
        ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答内容"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 0)
        self.assertEqual(ctx.candidates[0].reasoning, "原解答内容")  # 未被覆盖

    def test_too_short_discarded(self) -> None:
        s = make_solver(SHORT)  # 短于原版的 1/3 → 丢弃
        ctx = make_ctx()
        ctx.candidates.append(
            Candidate(id=0, answer="4", reasoning="很长的原解答" * 30))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 0)
        self.assertEqual(ctx.candidates[0].reasoning, "很长的原解答" * 30)

    def test_budget_short_skips(self) -> None:
        s = make_solver(IMPROVED)
        ctx = make_ctx(max_calls=0)  # 预算耗尽
        ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 0)
        self.assertEqual(ctx.candidates[0].reasoning, "原解答")

    def test_placeholder_reasoning_skipped(self) -> None:
        s = make_solver(IMPROVED)
        ctx = make_ctx()
        ctx.candidates.append(
            Candidate(id=0, answer="", reasoning="[子目标求解失败]"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
