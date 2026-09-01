# -*- coding: utf-8 -*-
"""LeanGate 硬验证门禁单元测试。

覆盖：档位/领域/开关过滤、proof_valid 接受、proof_invalid 淘汰+反馈、
unknown 的 lenient/strict 两种降级、环境缺失与异常的整体降级。
"""
import unittest

from agent.base import BugReport, Finding, TaskContext, Candidate
from agent.lean_gate import LeanGate
from user_agent import AgentConfig


class MockClient:
    def chat(self, messages=None, temperature=0.0, max_tokens=1024, **kw):
        return ""


class FakeBridge:
    """伪造 LeanBridge：按 reasoning 关键字返回不同 verdict。"""
    lean_available = True

    def __init__(self, *a, **k):
        pass

    def verify(self, problem, reasoning, domain="", timeout=60.0):
        if "PROOF_VALID" in reasoning:
            return BugReport(verdict="proof_valid", findings=[])
        if "PROOF_INVALID" in reasoning:
            return BugReport(
                verdict="proof_invalid",
                findings=[Finding(location="step1", kind="Critical",
                                  severity=5, desc="gap")],
                suggestion="请补全步骤")
        return BugReport(verdict="unknown", findings=[])

    def verify_answer(self, problem, reasoning, answer, domain="", timeout=60.0):
        # 轻量答案验证：按同一关键字返回 answer_valid / proof_invalid / unknown
        if "PROOF_VALID" in reasoning:
            return BugReport(verdict="answer_valid", findings=[])
        if "PROOF_INVALID" in reasoning:
            return BugReport(
                verdict="proof_invalid",
                findings=[Finding(location="step1", kind="Critical",
                                  severity=5, desc="gap")],
                suggestion="请补全步骤")
        return BugReport(verdict="unknown", findings=[])


class BoomBridge:
    lean_available = True

    def verify(self, *a, **k):
        raise RuntimeError("boom")

    def verify_answer(self, *a, **k):
        raise RuntimeError("boom")


def make_cfg(**kw):
    c = AgentConfig()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def mk_ctx(domain="证明", candidates=None):
    ctx = TaskContext(problem="Prove P", metadata={}, domain=domain)
    ctx.candidates = candidates or []
    return ctx


def mk_cands():
    return [Candidate(id=i, answer=str(i), reasoning=r, revised=False)
            for i, r in [(0, "PROOF_VALID steps"),
                         (1, "PROOF_INVALID steps"),
                         (2, "middle")]]


class LeanGateFilterTest(unittest.TestCase):

    def test_disabled_keeps_all(self):
        g = LeanGate(MockClient(), make_cfg(enable_lean_verify=False))
        g._bridge = FakeBridge()
        ctx = mk_ctx(candidates=mk_cands())
        kept, fb = g.apply(ctx, "deep", ctx.candidates)
        self.assertEqual(len(kept), 3)
        self.assertEqual(fb, [])

    def test_standard_tier_gated(self):
        # v2.8：门禁扩展到全部证明题档位（含 standard），非 deep 档同样门禁
        g = LeanGate(MockClient(), make_cfg())
        g._bridge = FakeBridge()
        ctx = mk_ctx(candidates=mk_cands())
        kept, fb = g.apply(ctx, "standard", ctx.candidates)
        self.assertEqual([c.id for c in kept], [0, 2])  # proof_valid + unknown(lenient)
        self.assertEqual(len(fb), 1)
        self.assertIn("Lean 硬验证", fb[0])

    def test_standard_tier_noop_when_all_proofs_false(self):
        # 旧行为（仅 deep 档门禁）由 lean_gate_all_proofs=False 保留
        g = LeanGate(MockClient(), make_cfg(lean_gate_all_proofs=False))
        g._bridge = FakeBridge()
        ctx = mk_ctx(candidates=mk_cands())
        kept, fb = g.apply(ctx, "standard", ctx.candidates)
        self.assertEqual(len(kept), 3)
        self.assertEqual(fb, [])

    def test_non_proof_domain_deep_gated(self):
        """#45（2026-08-30）行为变更：非证明题不再被整体排除在 Lean 之外。

        原逻辑 ``_enabled`` 里有 ``domain not in ("证明","证明题") → False``，
        把计算题挡在门外。老师指出计算题同样含证明成分、主要依赖依赖链，
        不该被排除。现改为：非证明题在 **deep 档** 照常门禁
        （限制在 deep 是因为 deep 有 25% 配额闸封顶，避免 21s/次 的编译
        拖垮全卷 —— 见 #43 时间分配归因）。
        """
        g = LeanGate(MockClient(), make_cfg())
        g._bridge = FakeBridge()
        ctx = mk_ctx(domain="代数", candidates=mk_cands())
        kept, fb = g.apply(ctx, "deep", ctx.candidates)
        self.assertEqual([c.id for c in kept], [0, 2])  # valid + unknown(lenient)
        self.assertEqual(len(fb), 1)
        self.assertIn("Lean 硬验证", fb[0])

    def test_non_proof_domain_standard_gated(self):
        """2026-09-01 行为变更：用户要求「所有题目都要用到 Lean」，
        非证明题默认全档启用（含 standard），走轻量 verify_answer。
        旧行为（非证明题仅 deep 档）由 lean_gate_nonproof_deep_only=True 保留。"""
        g = LeanGate(MockClient(), make_cfg())
        g._bridge = FakeBridge()
        ctx = mk_ctx(domain="代数", candidates=mk_cands())
        kept, fb = g.apply(ctx, "standard", ctx.candidates)
        self.assertEqual([c.id for c in kept], [0, 2])  # answer_valid + unknown(lenient)
        self.assertEqual(len(fb), 1)
        self.assertIn("Lean 硬验证", fb[0])

    def test_non_proof_domain_standard_noop_when_deep_only(self):
        """回退开关 lean_gate_nonproof_deep_only=True：非证明题恢复仅 deep 档。"""
        g = LeanGate(MockClient(), make_cfg(lean_gate_nonproof_deep_only=True))
        g._bridge = FakeBridge()
        ctx = mk_ctx(domain="代数", candidates=mk_cands())
        kept, fb = g.apply(ctx, "standard", ctx.candidates)
        self.assertEqual(len(kept), 3)
        self.assertEqual(fb, [])

    def test_non_proof_gate_can_be_disabled(self):
        """回退开关：lean_gate_nonproof=False 时恢复"仅证明题"旧行为。"""
        g = LeanGate(MockClient(), make_cfg(lean_gate_nonproof=False))
        g._bridge = FakeBridge()
        ctx = mk_ctx(domain="代数", candidates=mk_cands())
        kept, fb = g.apply(ctx, "deep", ctx.candidates)
        self.assertEqual(len(kept), 3)
        self.assertEqual(fb, [])

    def test_hard_gate_rejects_invalid_lenient_unknown(self):
        g = LeanGate(MockClient(), make_cfg())
        g._bridge = FakeBridge()
        ctx = mk_ctx(candidates=mk_cands())
        kept, fb = g.apply(ctx, "deep", ctx.candidates)
        ids = [c.id for c in kept]
        self.assertEqual(ids, [0, 2])  # proof_valid + unknown(lenient)
        self.assertEqual(len(fb), 1)
        self.assertIn("Lean 硬验证", fb[0])

    def test_strict_rejects_unknown(self):
        g = LeanGate(MockClient(), make_cfg(lean_gate_strict=True))
        g._bridge = FakeBridge()
        ctx = mk_ctx(candidates=mk_cands())
        kept, fb = g.apply(ctx, "deep", ctx.candidates)
        ids = [c.id for c in kept]
        self.assertEqual(ids, [0])  # 仅 proof_valid
        self.assertEqual(len(fb), 2)

    def test_env_missing_degrades(self):
        g = LeanGate(MockClient(), make_cfg())
        g._bridge = None
        ctx = mk_ctx(candidates=mk_cands())
        kept, fb = g.apply(ctx, "deep", ctx.candidates)
        self.assertEqual(len(kept), 3)
        self.assertEqual(fb, [])
        self.assertTrue(ctx.lean_gate)

    def test_exception_degrades_candidate(self):
        g = LeanGate(MockClient(), make_cfg())
        g._bridge = BoomBridge()
        ctx = mk_ctx(candidates=mk_cands())
        kept, fb = g.apply(ctx, "deep", ctx.candidates)
        self.assertEqual(len(kept), 3)  # 全部降级放行
        self.assertEqual(fb, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
