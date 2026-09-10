# -*- coding: utf-8 -*-
"""4.5/4.6 验证增强时间窗口护栏单测（2026-09-07 治 oracle/对抗烧穿 6.5）。

冒烟 v2 实证：3.3/3.6 止损省下的时间被 4.5 Oracle(365s)/4.6 对抗(372s)
单次 300s+ 不可打断的复核吸收 → 6.5 Lean 终局仍 time_critical、0 绿点。
护栏：放行前要求剩余时间 >= verify_enhance_est_seconds(360) + critical_tail + 30。
"""
import time
import unittest
from types import SimpleNamespace

from agent.base import TaskContext
from agent.orchestrator import Orchestrator


def _make_orch(est=360.0, adv_enabled=True):
    orch = Orchestrator.__new__(Orchestrator)
    orch.config = SimpleNamespace(
        verify_enhance_est_seconds=est,
        enable_adversarial_verify=adv_enabled,
    )
    orch.record = lambda *a, **k: None
    orch.adv_verifier = SimpleNamespace()
    return orch


def _make_ctx(remaining, critical_tail=120.0):
    ctx = TaskContext(problem="题", metadata={})
    ctx.deadline = time.time() + remaining  # 真实 epoch → time_remaining() 返回 remaining
    ctx.critical_tail_seconds = critical_tail
    ctx.candidates.append(
        SimpleNamespace(id=0, answer="ans", reasoning="推理", confidence=0.9))
    ctx._best_cluster = SimpleNamespace(rep_candidate=ctx.candidates[0])
    return ctx


class EnhanceWindowTest(unittest.TestCase):
    """_enhance_window_ok 门槛语义。"""

    def test_plenty_time_passes(self):
        orch = _make_orch()
        ctx = _make_ctx(remaining=700, critical_tail=60)  # need=450
        self.assertTrue(orch._enhance_window_ok(ctx, "oracle"))

    def test_insufficient_time_blocks(self):
        orch = _make_orch()
        ctx = _make_ctx(remaining=300, critical_tail=60)  # < 360+60+30
        self.assertFalse(orch._enhance_window_ok(ctx, "oracle"))

    def test_disabled_est0_passes(self):
        """verify_enhance_est_seconds=0 → 关闭护栏（旧行为）。"""
        orch = _make_orch(est=0.0)
        ctx = _make_ctx(remaining=10)
        self.assertTrue(orch._enhance_window_ok(ctx, "oracle"))

    def test_boundary_exact_need(self):
        """need = est + critical_tail + 30；达标（含 δ 裕量）放行，明显不足拦截。"""
        orch = _make_orch()
        ctx = _make_ctx(remaining=510 + 5, critical_tail=120)  # 360+120+30+5
        self.assertTrue(orch._enhance_window_ok(ctx, "adversarial"))
        ctx2 = _make_ctx(remaining=490, critical_tail=120)  # 差 20s
        self.assertFalse(orch._enhance_window_ok(ctx2, "adversarial"))

    def test_est360_deep_need450(self):
        """deep 档 critical_tail=60 → need=450（PB/alg 冒烟复盘：起始 rem~345 被拦）。"""
        orch = _make_orch()
        self.assertFalse(orch._enhance_window_ok(
            _make_ctx(remaining=345, critical_tail=60), "oracle"))
        self.assertTrue(orch._enhance_window_ok(
            _make_ctx(remaining=460, critical_tail=60), "oracle"))


class AdversarialProbeWindowTest(unittest.TestCase):
    """_adversarial_probe 在窗口不足时短路，不发起 probe。"""

    def _probe_orch(self):
        orch = _make_orch()
        calls = {"n": 0}

        def probe(ctx, rep, tier=None):
            calls["n"] += 1
            return SimpleNamespace(
                skipped=None, is_actionable=False, confidence=0.9,
                error_type=None, to_feedback=lambda: "fb")

        orch.adv_verifier.probe = probe
        return orch, calls

    def test_window_blocked_skips_probe(self):
        orch, calls = self._probe_orch()
        ctx = _make_ctx(remaining=200)  # < need(standard)=510
        self.assertFalse(orch._adversarial_probe(ctx, "standard"))
        self.assertEqual(calls["n"], 0, "窗口不足时不应发起 probe")

    def test_window_ok_runs_probe(self):
        orch, calls = self._probe_orch()
        ctx = _make_ctx(remaining=900)  # > need(standard)=510
        # mock probe 返回 not actionable → 高置信接受 → 返回 False
        self.assertFalse(orch._adversarial_probe(ctx, "standard"))
        self.assertEqual(calls["n"], 1, "窗口充足时应发起 probe")
        self.assertIsNotNone(getattr(ctx, "adversarial_result", None),
                             "probe 结果应写入 ctx.adversarial_result")

    def test_disabled_est0_keeps_old_behavior(self):
        """est=0 时 probe 照常发起（护栏关）。用 remaining=200：> critical_tail(120)
        过 gen_time_up、但 < 510 增强窗口——区分拦截来自哪个护栏。"""
        orch, calls = self._probe_orch()
        orch.config.verify_enhance_est_seconds = 0.0
        ctx = _make_ctx(remaining=200)
        orch._adversarial_probe(ctx, "standard")
        self.assertEqual(calls["n"], 1, "est=0 时不应被增强窗口拦截")


if __name__ == "__main__":
    unittest.main()
