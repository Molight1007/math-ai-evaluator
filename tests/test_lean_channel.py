# -*- coding: utf-8 -*-
"""Lean 双通道单测（2026-09-06 晚恢复）。

覆盖：
1) _lean_active 三态：LEAN_VERIFY=0 关 / enable_lean_verify=False 关 /
   lean 环境可用（打桩）→ 开；
2) LeanGate.gate_final_answer 的 entry 带 step="final_gate"
   （orchestrator 6.5 回环反馈读取兼容 lean/audit 两后端）；
3) LEAN_VERIFY 逃生门不影响 AuditGate 路径（回落语义 = 现有全量测试回归）。

lean 真实验证链路（编译/LLM 翻译）属集成行为，见本地冒烟，不在单测范围。
"""
import os

import pytest

from agent.base import TaskContext
from user_agent import AgentConfig


def _make_agent_config(**kw):
    kw.setdefault("enable_audit_gate", True)
    return AgentConfig(**kw)


class _DummyClient:
    """零能力 client：lean 链路里 LLM 翻译返回空（翻译失败 → unknown 放行）。"""

    def chat(self, messages=None, temperature=0.0, max_tokens=1, **kw):
        return None


# ----------------------------------------------------------------------
# 1) orchestrator._lean_active 三态
# ----------------------------------------------------------------------
def _orchestrator(monkeypatch, cfg=None, lean_module=True):
    monkeypatch.setattr("agent.orchestrator._LEAN_MODULES_OK", lean_module)
    from agent.orchestrator import Orchestrator
    orch = Orchestrator(_DummyClient(), cfg or _make_agent_config())
    orch._lean_probe = None
    return orch


def test_lean_active_env_off(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "0")
    orch = _orchestrator(monkeypatch)
    assert orch._lean_active() is False


def test_lean_active_config_off(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "1")
    cfg = _make_agent_config(enable_lean_verify=False)
    orch = _orchestrator(monkeypatch, cfg)
    assert orch._lean_active() is False


def test_lean_active_modules_missing(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "1")
    orch = _orchestrator(monkeypatch, _make_agent_config(),
                         lean_module=False)
    assert orch.lean_gate is None
    assert orch._lean_active() is False


def test_lean_active_env_on_and_probe_ok(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "1")
    orch = _orchestrator(monkeypatch, _make_agent_config())
    # 打桩 bridge：lean_available=True → lean 通道激活
    class _FakeBridge:
        lean_available = True
    orch.lean_gate._bridge = _FakeBridge()
    assert orch._lean_active() is True
    # 结果缓存：第二次不再重探
    assert orch._lean_probe is True


# ----------------------------------------------------------------------
# 2) LeanGate.gate_final_answer entry 兼容（step=final_gate）
# ----------------------------------------------------------------------
def test_lean_gate_final_entry_step(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "1")
    from tools.lean_local.lean_gate import LeanGate
    gate = LeanGate(_DummyClient(), _make_agent_config())
    ctx = TaskContext(problem="计算 1+1", metadata={})
    ctx.domain = ""
    ctx.question_type = "解答题"
    # 空答案 → 放行，且 entry 写 ctx.lean_gate 且带 step=final_gate
    assert gate.gate_final_answer(ctx, "standard", "  ") is True
    entries = list(getattr(ctx, "lean_gate", []) or [])
    assert entries, "空答案也应留记录"
    assert entries[-1].get("step") == "final_gate"


def test_lean_gate_final_reject_entry(monkeypatch):
    """proof_invalid → False，entry verdict 供 6.5 回环读取（verdict∈拒绝集）。"""
    monkeypatch.setenv("LEAN_VERIFY", "1")
    from tools.lean_local.lean_gate import LeanGate
    gate = LeanGate(_DummyClient(), _make_agent_config())
    ctx = TaskContext(problem="求 f(2)，题目数字 42", metadata={})
    ctx.domain = ""
    ctx.question_type = "解答题"

    class _FakeBridge:
        lean_available = True

        def verify_answer(self, **kw):
            class _R:
                verdict = "proof_invalid"
                findings = []
                suggestion = "逻辑错误：42 代入后不等"
                lean_code = ""
            return _R()

    gate._bridge = _FakeBridge()
    assert gate.gate_final_answer(ctx, "deep", "0", "步骤……") is False
    entries = list(getattr(ctx, "lean_gate", []) or [])
    rej = [e for e in entries
           if e.get("step") == "final_gate"
           and e.get("verdict") in ("reject", "proof_invalid", "unknown")]
    assert rej, "拒绝路径 entry 应可被 6.5 回环识别"
    assert "42" in (rej[-1].get("feedback") or "") or rej[-1].get("feedback")


# ----------------------------------------------------------------------
# 3) LEAN_VERIFY 逃生门：关 lean 后 gate 仍为 audit（回落）
# ----------------------------------------------------------------------
def test_env_off_keeps_audit_gate(monkeypatch):
    monkeypatch.setenv("LEAN_VERIFY", "0")
    from agent.orchestrator import Orchestrator
    cfg = _make_agent_config()
    orch = Orchestrator(_DummyClient(), cfg)
    assert orch._lean_active() is False
    assert orch.audit_gate is not None


# ----------------------------------------------------------------------
# 4) LeanGate.apply 连续 unknown 止损（B，2026-09-07）
#    PB-002 实证：6 候选整题 verify 563s 全 unknown 白烧 → 连续 2 个
#    unknown 后剩余候选 verify_stop，不再逐个整题 verify。
# ----------------------------------------------------------------------
from types import SimpleNamespace


def _mk_cands(n):
    return [SimpleNamespace(id=i, answer=f"ans{i}", reasoning=f"推理{i}",
                            confidence=0.5) for i in range(n)]


def _gate_with_verify(monkeypatch, verdict="unknown", stop=2, strict=False):
    monkeypatch.setenv("LEAN_VERIFY", "1")
    from tools.lean_local.lean_gate import LeanGate
    gate = LeanGate(_DummyClient(), _make_agent_config(
        lean_gate_unknown_stop=stop, lean_gate_strict=strict))

    calls = {"n": 0}

    class _FakeBridge:
        lean_available = True

        def verify(self, **kw):
            calls["n"] += 1
            r = SimpleNamespace(verdict=verdict, findings=[], suggestion="",
                                lean_code="")
            return r

    gate._bridge = _FakeBridge()
    return gate, calls


def test_apply_stops_after_2_unknown(monkeypatch):
    gate, calls = _gate_with_verify(monkeypatch, verdict="unknown", stop=2)
    ctx = TaskContext(problem="证明题题干", metadata={})
    ctx.domain = "证明题"
    ctx.question_type = ""
    kept, fb = gate.apply(ctx, "standard", _mk_cands(6))
    assert calls["n"] == 2, "连续 2 unknown 后应止损，不再逐个 verify"
    assert len(kept) == 6, "lenient_pass + verify_stop 都应保留候选"
    stops = [e for e in ctx.lean_gate if e.get("degraded") == "verify_stop"]
    assert len(stops) == 4, "剩余 4 候选应标记 verify_stop"
    assert not fb


def test_apply_stop_disabled_verifies_all(monkeypatch):
    gate, calls = _gate_with_verify(monkeypatch, verdict="unknown", stop=0)
    ctx = TaskContext(problem="证明题题干", metadata={})
    ctx.domain = "证明题"
    kept, _ = gate.apply(ctx, "standard", _mk_cands(6))
    assert calls["n"] == 6, "stop=0 关闭止损，应逐候选全验"
    assert len(kept) == 6


def test_apply_valid_resets_streak(monkeypatch):
    """候选 2 出绿点（valid）→ 计数清零 → 候选 3/4 unknown 只累计 2 不到
    阈值？候选 4 仍验（streak 从 0 数，第 3、4 个 unknown 后候选 5、6 止损）。"""
    calls = {"n": 0, "seq": []}
    monkeypatch.setenv("LEAN_VERIFY", "1")
    from tools.lean_local.lean_gate import LeanGate
    gate = LeanGate(_DummyClient(), _make_agent_config(
        lean_gate_unknown_stop=2))

    class _FakeBridge:
        lean_available = True

        def verify(self, **kw):
            calls["n"] += 1
            calls["seq"].append(calls["n"])
            # 候选 2（第 2 次调用）返回 valid → 计数清零
            if calls["n"] == 2:
                return SimpleNamespace(verdict="proof_valid", findings=[],
                                       suggestion="", lean_code="import Mathlib.Tactic\nexample : True := by trivial\n")
            return SimpleNamespace(verdict="unknown", findings=[],
                                   suggestion="", lean_code="")

    gate._bridge = _FakeBridge()
    ctx = TaskContext(problem="证明题题干", metadata={})
    ctx.domain = "证明题"
    kept, _ = gate.apply(ctx, "standard", _mk_cands(6))
    # 1 unknown(1) → 2 valid(清零) → 3 unknown(1) → 4 unknown(2,达阈值)
    # → 5、6 verify_stop。verify 调用 = 候选 1-4 = 4 次
    assert calls["n"] == 4, f"valid 清零后应从候选 3 重新计数，实际 {calls['n']}"
    assert len(kept) == 6


def test_apply_stop_strict_rejects_rest(monkeypatch):
    gate, calls = _gate_with_verify(monkeypatch, verdict="unknown", stop=2,
                                    strict=True)
    ctx = TaskContext(problem="证明题题干", metadata={})
    ctx.domain = "证明题"
    kept, fb = gate.apply(ctx, "standard", _mk_cands(6))
    assert calls["n"] == 2
    assert len(kept) == 0, "strict：验证过与 verify_stop 的 unknown 全拒"
    assert len(fb) == 6, "6 候选全产生拒绝反馈（2 验证 + 4 止损）"
