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

    def test_time_critical_skips(self) -> None:
        """2026-09-03 预算解除：时间紧迫才跳过自改进。

        原 test_budget_short_skips 用 Budget(max_calls=0) 模拟预算耗尽
        → 跳过改进——预算闸门已删，预算=0 也会照常改进。
        """
        import time as _t
        s = make_solver(IMPROVED)
        ctx = make_ctx(max_calls=0)  # 预算=0（不再阻断）
        ctx.deadline = _t.time() - 1  # 真实时间戳已过期 → 时间紧迫
        ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 0)
        self.assertEqual(ctx.candidates[0].reasoning, "原解答")

    def test_budget_zero_still_improves(self) -> None:
        """预算=0 不再阻断：自改进照常执行（新语义）。"""
        s = make_solver(IMPROVED)
        ctx = make_ctx(max_calls=0)
        ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 1)
        self.assertIn("步骤1", ctx.candidates[0].reasoning)

    def test_placeholder_reasoning_skipped(self) -> None:
        s = make_solver(IMPROVED)
        ctx = make_ctx()
        ctx.candidates.append(
            Candidate(id=0, answer="", reasoning="[子目标求解失败]"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 0)

    # ---- A（2026-09-07）：improve_min_remaining 单候选预留停手 ----
    def test_min_remaining_stops_before_call(self) -> None:
        """距生成软截止 < improve_min_remaining（300）→ 不再开新候选改进。"""
        import time as _t
        s = make_solver(IMPROVED)
        s.config = SimpleNamespace(  # 覆盖为带 improve_min_remaining 的配置
            use_blueprint=False, self_improve_max=3,
            policy_temperature=0.3, policy_max_tokens=8192,
            improve_min_remaining=300.0)
        ctx = make_ctx()
        # N1''（2026-09-11）：基准由 _gen_deadline 改为**硬墙 deadline**——
        # 因为 3.3_improve 排在 2.7/3_solve 之后，用 _gen_deadline(=deadline−480)
        # 做差必为负 → 恒停手（smoke6_v2 六题 3.3 恒为 0s 的第三层原因）。
        # 语义仍为"给单候选最坏成本(200-300s)留够余量"。
        ctx.deadline = _t.time() + 60        # 距硬墙仅 60s < 300s
        ctx._gen_deadline = _t.time() + 60
        ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答内容"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 0, "预留不足应停手，不再发起 200-300s 的改进调用")
        self.assertEqual(ctx.candidates[0].reasoning, "原解答内容")

    def test_min_remaining_ample_still_improves(self) -> None:
        """距软截止充足（> 300）→ 照常改进（护栏不误伤正常路径）。"""
        import time as _t
        s = make_solver(IMPROVED)
        s.config = SimpleNamespace(
            use_blueprint=False, self_improve_max=3,
            policy_temperature=0.3, policy_max_tokens=8192,
            improve_min_remaining=300.0)
        ctx = make_ctx()
        ctx.deadline = _t.time() + 900       # 距硬墙充足（N1''：基准改 deadline）
        ctx._gen_deadline = _t.time() + 900
        ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答内容"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 1, "硬墙余量充足时应正常改进")

    def test_min_remaining_zero_keeps_old_behavior(self) -> None:
        """improve_min_remaining=0（默认未配置）→ 仅走 gen_time_up 旧逻辑。"""
        import time as _t
        s = make_solver(IMPROVED)  # config 无 improve_min_remaining 字段 → getattr 0
        ctx = make_ctx()
        ctx._gen_deadline = _t.time() + 60   # 距截止很近但不 time_critical
        ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答内容"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 1, "0=关闭预留护栏，回到旧行为")


if __name__ == "__main__":
    unittest.main()
