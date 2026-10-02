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
# ⚠ 2026-09-30：多轮/无条件用例需用**长响应**——上游有「改进输出过短」门槛
#   （实测 202 字符），短响应会在改进成功判定前被丢弃（返回 0），
#   导致"A 跑了但没产出"与"A 根本没跑"混淆。此处显式跨过该门槛。
IMPROVED_LONG = (
    "## 问题分析\n重新审视题目，确认已知条件与求解目标。\n"
    "## 详细解题步骤\n"
    + "步骤1：整理并化简式子，逐步推导出关键关系。\n" * 8
    + "## 最终答案\n42\n"
    "## 关键验证点\n将答案代回原式逐项检验，两侧相等，结论成立。"
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


# ======================================================================
# 遍数 1/2 可配 + 真无条件（2026-09-30，截图 #7）
# ----------------------------------------------------------------------
# 用户原话：
# > 无条件自改进是一遍还是两遍？哪种效果最好，需要尝试。
#
# 因此这里锁的不是"哪个遍数更好"（那要跑 A/B 才有答案），而是
# **两件事必须都真的可切换**，否则 A/B 无从下手：
#   ① `self_improve_rounds` 真的驱动循环次数（不是写了不生效）；
#   ② 第 2 轮**真的对同一批候选再改进一次**（不是被 `self_improved`
#      标记全部过滤掉而空转 —— 这是最隐蔽的失效模式）。
# 外加 ③「真无条件」= `self_improve_conditional=False` 时不过滤缺陷。
# ======================================================================
class ImproveRoundsTest(unittest.TestCase):

    def test_default_rounds_is_one(self) -> None:
        """默认不配 ⇒ 只跑 1 轮（不改变既有行为，A/B 的 baseline）。"""
        s = make_solver(IMPROVED)
        ctx = make_ctx()
        ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答内容"))
        n = s.improve_candidates(ctx)
        self.assertEqual(n, 1)
        self.assertFalse(hasattr(s.config, "self_improve_rounds"))

    def test_two_rounds_actually_run_twice(self) -> None:
        """★ 核心回归：rounds=2 时 LLM 必须被调 **2 次**。

        若第 2 轮的 `self_improved` 标记没被重置，`_needs_improve` 会把
        候选全过滤掉 ⇒ 第 2 轮 0 次调用却"看起来跑了"（静默空转）。
        本用例用调用计数直接锁死这一点。
        """
        calls = []

        class C:
            def chat(self, messages=None, temperature=0.0, max_tokens=0, **kw):
                calls.append(1)
                return IMPROVED_LONG

        cfg = SimpleNamespace(use_blueprint=False, self_improve_max=3,
                              policy_temperature=0.3, policy_max_tokens=8192,
                              self_improve_rounds=2)
        s = SolverAgent(client=C(), config=cfg)
        ctx = make_ctx(max_calls=20)
        ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答内容"))
        n = s.improve_candidates(ctx)
        # ★ 调用次数 = 3（不是 2），原因是**候选池会增长**：
        #   第 1 轮：1 个原候选 → 改进成功时"保留原版 + 写入改进版"
        #           ⇒ 池子变 2 个（实测 trace：保留原版候选#1，改进版写入#0）；
        #   第 2 轮：对这 2 个各调一次（上限 self_improve_max=3 未撞）
        #           ⇒ 1 + 2 = 3 次。
        #   本用例锁的是**第 2 轮真的跑了**（不是被 self_improved 标记全过滤
        #   而空转）—— 若没重置标记，第 2 轮会是 0 次，总数只会是 1。
        self.assertEqual(len(calls), 3, "第 2 轮必须真的对候选再改进（池已增长为 2）")
        self.assertEqual(n, 3, "累计改进次数应跨轮累加")
        # 判据核心：第 2 轮确实产生了调用（> 第 1 轮的 1 次）
        self.assertGreater(len(calls), 1, "第 2 轮若空转则此处为 1")

    def test_two_rounds_respects_self_improve_max_per_round(self) -> None:
        """每轮仍受 self_improve_max 约束（不能因多轮而放大单轮成本）。"""
        calls = []

        class C:
            def chat(self, messages=None, temperature=0.0, max_tokens=0, **kw):
                calls.append(1)
                return IMPROVED_LONG

        cfg = SimpleNamespace(use_blueprint=False, self_improve_max=2,
                              policy_temperature=0.3, policy_max_tokens=8192,
                              self_improve_rounds=2)
        s = SolverAgent(client=C(), config=cfg)
        ctx = make_ctx(max_calls=50)
        for i in range(5):
            ctx.candidates.append(Candidate(id=i, answer="4", reasoning=f"原解{i}"))
        s.improve_candidates(ctx)
        self.assertEqual(len(calls), 4, "2 轮 × 每轮 2 个候选 = 4 次")

    def test_rounds_never_goes_below_one(self) -> None:
        """配 0 / 负数也要至少跑一轮 —— 否则"自改进"被静默关闭。"""
        for bogus in (0, -3):
            s = make_solver(IMPROVED)
            s.config.self_improve_rounds = bogus
            ctx = make_ctx()
            ctx.candidates.append(Candidate(id=0, answer="4", reasoning="原解答内容"))
            self.assertEqual(s.improve_candidates(ctx), 1,
                             f"rounds={bogus} 不应导致 0 轮")

    def test_conditional_true_filters_defective_candidate(self) -> None:
        """★ 反向对照：`self_improve_conditional=True` 时，完好的候选**不该**被改进。"""
        s = make_solver(IMPROVED)
        s.config.self_improve_conditional = True
        ctx = make_ctx()
        # 推理充分、答案完整 ⇒ 条件模式下应被过滤
        ctx.candidates.append(Candidate(
            id=0, answer="42",
            reasoning="## 问题分析\n" + "充分展开的推理内容。" * 60))
        self.assertEqual(s.improve_candidates(ctx), 0,
                         "条件模式应过滤完好候选")

    def test_unconditional_is_default_and_improves_even_good_candidate(self) -> None:
        """★ 核心：默认（真无条件）时，**即便候选看起来完好也要改进一遍**。"""
        s = make_solver(IMPROVED_LONG)
        # config 无 self_improve_conditional ⇒ getattr 默认 False = 真无条件
        self.assertFalse(getattr(s.config, "self_improve_conditional", False))
        ctx = make_ctx()
        ctx.candidates.append(Candidate(
            id=0, answer="42",
            reasoning="## 问题分析\n" + "充分展开的推理内容。" * 60))
        self.assertEqual(s.improve_candidates(ctx), 1,
                         "真无条件：完好候选也要过一次自改进")


if __name__ == "__main__":
    unittest.main()
