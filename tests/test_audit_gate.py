# -*- coding: utf-8 -*-
"""AuditGate（答案审核闸门，2026-09-06 取代 Lean 系审核）单元测试。

覆盖:
- ``confirm_understanding``: 默认跳过 / 时间紧张跳过 / LLM 复述解析
- ``audit_candidates``: 无候选 / deterministic fail 淘汰 / 全否回退保留
- ``gate_final_answer``: 空答案放行 / deterministic fail 打回 /
  challenge hard_fail 打回 / rubric 高置信 B 打回 / 正常放行
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from agent.audit_gate import AuditGate


def make_gate(config=None):
    class C:
        def chat(self, messages=None, temperature=0.0, max_tokens=0, **kw):
            return '{"understood":true,"restatement":"ok","gaps":[]}'
    cfg = config or SimpleNamespace(
        audit_confirm_understanding=False,
        use_rubric=False,
        use_challenge=False,
        audit_rubric_reject_conf=0.85,
        max_workers=2,
        verifier_voting_times=1,
        use_scoring=False,
        use_bug_report_feedback=False,
    )
    return AuditGate(client=C(), config=cfg)


def make_ctx(problem="求 x^2=4 的正根", deadline=0.0):
    from agent.base import TaskContext, Budget
    return TaskContext(problem=problem, metadata={},
                       budget=Budget(max_calls=100), deadline=deadline)


def cand(answer="2", reasoning="因为 x^2=4", cid=0):
    from types import SimpleNamespace as NS
    return NS(id=cid, answer=answer, reasoning=reasoning)


class ConfirmUnderstandingTest(unittest.TestCase):
    def test_disabled_skips(self) -> None:
        g = make_gate()
        ctx = make_ctx()
        res = g.confirm_understanding(ctx)
        self.assertTrue(res.get("skipped"))
        self.assertEqual(len(ctx.revise_feedback), 0)

    def test_enabled_parses_understood(self) -> None:
        g = make_gate(SimpleNamespace(
            audit_confirm_understanding=True, use_rubric=False,
            use_challenge=False, audit_rubric_reject_conf=0.85,
            max_workers=2, verifier_voting_times=1, use_scoring=False,
            use_bug_report_feedback=False))
        ctx = make_ctx()
        res = g.confirm_understanding(ctx)
        self.assertTrue(res.get("understood"))

    def test_exception_degrades_open(self) -> None:
        """复核异常不阻断主流程（宁放行不崩溃）。"""
        class Boom:
            def chat(self, messages=None, temperature=0.0,
                     max_tokens=0, **kw):
                raise RuntimeError("llm 崩")
        cfg = SimpleNamespace(audit_confirm_understanding=True)
        g = AuditGate(client=Boom(), config=cfg)
        ctx = make_ctx()
        res = g.confirm_understanding(ctx)
        self.assertTrue(res.get("understood"))


class AuditCandidatesTest(unittest.TestCase):
    def test_empty_candidates(self) -> None:
        g = make_gate()
        ctx = make_ctx()
        kept, fb = g.audit_candidates(ctx, "deep", [])
        self.assertEqual(kept, [])
        self.assertEqual(fb, [])

    def test_all_keep_when_no_fail(self) -> None:
        g = make_gate()
        ctx = make_ctx()
        c1, c2 = cand("2", cid=1), cand("2", cid=2)
        kept, fb = g.audit_candidates(ctx, "deep", [c1, c2])
        # 答案 "2" 对 x^2=4 是正根，确定性应为 pass/unknown，不全否决
        self.assertEqual(len(kept), 2)
        self.assertEqual(fb, [])

    def test_fail_rejected_but_not_all(self) -> None:
        """一个被程序否决，另一个保留（不全否 → 淘汰坏的）。"""
        g = make_gate()
        ctx = make_ctx()
        good = cand("2", cid=1)
        bad = cand("99999", cid=2)
        real = {}

        class FakeDet:
            def check_answer(self, ctx, problem, answer, domain=None):
                if answer == "99999":
                    return {"verdict": "fail", "evidence": "代入不成立"}
                return {"verdict": "unknown", "evidence": "x"}

        with mock.patch("agent.audit_gate.DeterministicChecker",
                        return_value=FakeDet()):
            kept, fb = g.audit_candidates(ctx, "deep", [good, bad])
        ids = [k.id for k in kept]
        self.assertIn(1, ids)
        self.assertNotIn(2, ids)
        self.assertTrue(any("否决" in f or "AuditGate" in f for f in fb))

    def test_all_fail_rolls_back(self) -> None:
        """全部候选被程序否决 → 回退保留原候选（宁 unknown 不误杀）。"""
        g = make_gate()
        ctx = make_ctx()

        class AllFail:
            def check_answer(self, ctx, problem, answer, domain=None):
                return {"verdict": "fail", "evidence": "全部错"}

        with mock.patch("agent.audit_gate.DeterministicChecker",
                        return_value=AllFail()):
            c1, c2 = cand("a", cid=1), cand("b", cid=2)
            kept, fb = g.audit_candidates(ctx, "deep", [c1, c2])
        # 全部被否 → 保留原候选且无淘汰反馈
        self.assertEqual(sorted(k.id for k in kept), [1, 2])
        self.assertEqual(fb, [])


class GateFinalAnswerTest(unittest.TestCase):
    def test_empty_answer_passes(self) -> None:
        g = make_gate()
        ctx = make_ctx()
        self.assertTrue(g.gate_final_answer(ctx, "standard", ""))

    def test_deterministic_fail_rejects(self) -> None:
        """程序硬核验 fail → 打回（客观，不依赖 LLM）。"""
        g = make_gate()
        ctx = make_ctx()
        with mock.patch("agent.audit_gate.DeterministicChecker") as D:
            inst = mock.Mock()
            inst.check_answer.return_value = {
                "verdict": "fail", "evidence": "x=99999 代入不成立",
                "method": "sympy"}
            D.return_value = inst
            self.assertFalse(g.gate_final_answer(ctx, "deep", "99999"))

    def test_challenge_hard_fail_rejects(self) -> None:
        """反例挑战命中（程序数值验证证伪）→ 打回。"""
        g = make_gate(SimpleNamespace(
            audit_confirm_understanding=False, use_rubric=False,
            use_challenge=True, audit_rubric_reject_conf=0.85,
            max_workers=2, verifier_voting_times=1, use_scoring=False,
            use_bug_report_feedback=False))
        ctx = make_ctx()
        with mock.patch.object(g._verifier_inst,
                               "_challenge_counterexample",
                               return_value={"hard_fail": True,
                                             "evidence": "n=0 处反例"}):
            self.assertFalse(
                g.gate_final_answer(ctx, "deep", "x^2>=x", "推理"))

    def test_rubric_high_conf_b_rejects(self) -> None:
        """rubric 高置信 B → 打回（带错因供 rework/revise）。"""
        g = make_gate(SimpleNamespace(
            audit_confirm_understanding=False, use_rubric=True,
            use_challenge=False, audit_rubric_reject_conf=0.85,
            max_workers=2, verifier_voting_times=1, use_scoring=False,
            use_bug_report_feedback=False))
        ctx = make_ctx()
        # deterministic 放行（mock 掉避免真实 sympy），rubric 判 B 高置信
        with mock.patch("agent.audit_gate.DeterministicChecker") as D, \
                mock.patch.object(g._verifier_inst, "_vote_one_rubric",
                                  return_value={"verdict": "B",
                                                "confidence": 0.95,
                                                "error_type": "计算错误",
                                                "step_index": 2,
                                                "reason": "展开错了"}):
            inst = mock.Mock()
            inst.check_answer.return_value = {
                "verdict": "unknown", "evidence": "表达式无法判定"}
            D.return_value = inst
            self.assertFalse(g.gate_final_answer(ctx, "deep", "x^2>=x", "推理"))

    def test_rubric_low_conf_b_passes(self) -> None:
        """rubric B 但置信度低 → 放行（宁 unknown 不误杀）。"""
        g = make_gate(SimpleNamespace(
            audit_confirm_understanding=False, use_rubric=True,
            use_challenge=False, audit_rubric_reject_conf=0.85,
            max_workers=2, verifier_voting_times=1, use_scoring=False,
            use_bug_report_feedback=False))
        ctx = make_ctx()
        with mock.patch("agent.audit_gate.DeterministicChecker") as D, \
                mock.patch.object(g._verifier_inst, "_vote_one_rubric",
                                  return_value={"verdict": "B",
                                                "confidence": 0.5,
                                                "reason": "不确定"}):
            inst = mock.Mock()
            inst.check_answer.return_value = {
                "verdict": "unknown", "evidence": "x"}
            D.return_value = inst
            self.assertTrue(g.gate_final_answer(ctx, "deep", "x^2>=x", "推理"))

    def test_all_pass(self) -> None:
        g = make_gate()
        ctx = make_ctx()
        with mock.patch("agent.audit_gate.DeterministicChecker") as D:
            inst = mock.Mock()
            inst.check_answer.return_value = {
                "verdict": "unknown", "evidence": "x"}
            D.return_value = inst
            self.assertTrue(g.gate_final_answer(ctx, "standard", "2", "推理"))


def _solution_cfg(**kw):
    """解答题判别重写相关的配置（含 2026-10-07 新增的两个开关）。"""
    base = dict(
        audit_confirm_understanding=False, use_rubric=False, use_challenge=False,
        audit_rubric_reject_conf=0.85, max_workers=2, verifier_voting_times=1,
        use_scoring=False, use_bug_report_feedback=False,
        audit_gate_skip_non_proof=True,        # 旧"解答题早退"开关仍开
        deterministic_solution_check=True,      # 但判别重写已开 ⇒ 不应再早退
        audit_gate_rubric_nonproof=False)
    base.update(kw)
    return SimpleNamespace(**base)


class SolutionProblemGateTest(unittest.TestCase):
    """2026-10-07：解答题不再"结构性无输出"（闸门真跑判据、能拦错误答案）。"""

    def test_nonproof_not_early_exit_when_solution_check_on(self) -> None:
        g = make_gate(_solution_cfg())
        ctx = make_ctx(problem="求解方程 x^2-5x+6=0")
        ctx.question_type = "解答题"
        ctx.final_response = r"\boxed{5}"          # 错误答案 → 应被客观否决
        res = g.run(ctx, stage="final")
        self.assertFalse(res.get("ok"))
        self.assertFalse(any(e.get("skipped") == "non_proof_early_exit"
                             for e in ctx.audit_gate))
        finals = [e for e in ctx.audit_gate if e.get("step") == "final_gate"]
        self.assertTrue(finals)
        self.assertEqual(finals[-1].get("deterministic_method"), "substitution")

    def test_nonproof_early_exit_when_solution_check_off(self) -> None:
        """solution_check 关 → 恢复旧的"解答题早退"（回退路径）。"""
        g = make_gate(_solution_cfg(deterministic_solution_check=False))
        ctx = make_ctx(problem="求解方程 x^2-5x+6=0")
        ctx.question_type = "解答题"
        ctx.final_response = r"\boxed{5}"
        res = g.run(ctx, stage="final")
        self.assertEqual(res.get("skipped"), "non_proof")
        self.assertTrue(any(e.get("skipped") == "non_proof_early_exit"
                            for e in ctx.audit_gate))

    def test_rubric_nonproof_gated_in_audit_candidates(self) -> None:
        """`audit_gate_rubric_nonproof` 只作用于 `audit_candidates`（候选级）。

        "rubric 仅对证明题运行"的限制只在该方法；默认关（=旧行为）；开启后
        解答题候选也走 Level2 rubric。`gate_final_answer` 的 rubric 本就无题型门，
        故本开关不影响它（保持不回退）。
        """
        # 关（默认）：解答题候选 → 不调用 rubric
        g = make_gate(_solution_cfg(use_rubric=True,
                                    audit_gate_rubric_nonproof=False))
        ctx = make_ctx(problem="求解方程 x^2-5x+6=0")
        ctx.question_type = "解答题"
        with mock.patch.object(g._verifier_inst, "_vote_one_rubric") as rb, \
                mock.patch("agent.audit_gate.DeterministicChecker") as D:
            D.return_value.check_answer.return_value = {
                "verdict": "unknown", "evidence": "x", "method": "parse_only"}
            g.audit_candidates(ctx, "deep", [cand("1", cid=1)])
            rb.assert_not_called()
        # 开：解答题候选 → 调用 rubric
        g2 = make_gate(_solution_cfg(use_rubric=True,
                                     audit_gate_rubric_nonproof=True))
        ctx2 = make_ctx(problem="求解方程 x^2-5x+6=0")
        ctx2.question_type = "解答题"
        with mock.patch.object(
                g2._verifier_inst, "_vote_one_rubric",
                return_value={"verdict": "A", "confidence": 0.9}) as rb2, \
                mock.patch("agent.audit_gate.DeterministicChecker") as D2:
            D2.return_value.check_answer.return_value = {
                "verdict": "unknown", "evidence": "x", "method": "parse_only"}
            g2.audit_candidates(ctx2, "deep", [cand("1", cid=1)])
            rb2.assert_called_once()


if __name__ == "__main__":
    unittest.main()
