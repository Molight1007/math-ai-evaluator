# -*- coding: utf-8 -*-
"""4.3 Lean 逻辑判断·答案代回题目（五道审核链第 3 道）单测 —— 2026-10-14。

覆盖：部分淘汰/全拒标记/严格清池/不适用豁免/未激活/开关关闭/异常保留/接线锚点。
LeanGate 以注入桩替代（`self.lean_gate`），不触发真实 Lean 编译。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate  # noqa: E402
from agent.lean_backcheck import lean_backcheck_stage  # noqa: E402


class _Gate:
    def __init__(self, kept=None, fbs=None):
        self._kept = kept
        self._fbs = fbs or []
        self.calls = 0

    def apply(self, ctx, tier, cands):
        self.calls += 1
        kept = self._kept if self._kept is not None else list(cands)
        return list(kept), list(self._fbs)


class _Cfg:
    strict_all_rejected = False


class _Stub:
    def __init__(self, gate=None, active=True, applicable=True):
        self.events = []
        self.client = None
        self.config = _Cfg()
        self.lean_gate = gate or _Gate()
        self._active_flag = active
        self._applicable_flag = applicable

    def _lean_active(self):
        return self._active_flag

    def _lean_applicable(self, ctx):
        return self._applicable_flag

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))


class _Ctx:
    def __init__(self, cands):
        self.problem = "证明题"
        self.candidates = cands


def _c(i):
    return Candidate(id=i, answer="答案%d" % i, reasoning="推理")


def test_partial_rejection_filters_pool():
    gate = _Gate(kept=[_c(2)], fbs=["[Lean] cid=1 proof_invalid"])
    stub = _Stub(gate)
    ctx = _Ctx([_c(1), _c(2)])
    lean_backcheck_stage(stub, ctx, "deep")
    assert [c.id for c in ctx.candidates] == [2]
    assert ctx.lean_backcheck["n_rejected"] == 1
    assert ctx.lean_backcheck["all_rejected"] is False
    assert any("[Lean]" in fb for fb in ctx.audit_reject_feedback)
    assert any("[Lean]" in fb for fb in ctx.lean_reject_feedback)


def test_all_rejected_marked_not_cleared():
    gate = _Gate(kept=[], fbs=["[Lean] 全拒反馈"])
    stub = _Stub(gate)
    ctx = _Ctx([_c(1)])
    lean_backcheck_stage(stub, ctx, "deep")
    assert [c.id for c in ctx.candidates] == [1]      # 不静默清池
    assert ctx._gate_all_rejected is True
    assert ctx.lean_backcheck["all_rejected"] is True
    assert any("全部未通过" in m for _, m in stub.events)


def test_all_rejected_refuted_clears_pool():
    """★ 2026-10-22：全部被 Lean 明确证伪（failure_kind=refuted）⇒ 答案确实错，
    清池交 4.6 重写（这是正常判定，不是降级）。"""
    gate = _Gate(kept=[], fbs=["[Lean] 全拒反馈"])
    stub = _Stub(gate)
    ctx = _Ctx([_c(1), _c(2)])
    ctx.lean_gate = [{"id": 1, "failure_kind": "refuted"},
                     {"id": 2, "failure_kind": "refuted"}]
    lean_backcheck_stage(stub, ctx, "deep")
    assert ctx.candidates == []
    assert ctx.lean_backcheck["reject_kinds"] == {"refuted": 2}
    assert any("全部被证伪" in m for _, m in stub.events)


def test_all_rejected_unproved_keeps_pool():
    """★ 2026-10-22：全拒原因是 unproved（没证出来）⇒ 与答案对错无关，保留候选，
    并把原因分布写进 diag（不再静默标记）。"""
    gate = _Gate(kept=[], fbs=[])
    stub = _Stub(gate)
    ctx = _Ctx([_c(1)])
    ctx.lean_gate = [{"id": 1, "failure_kind": "unproved"}]
    lean_backcheck_stage(stub, ctx, "deep")
    assert [c.id for c in ctx.candidates] == [1]
    assert ctx.lean_backcheck["reject_kinds"] == {"unproved": 1}
    assert any("不是证伪" in m for _, m in stub.events)


def test_all_rejected_mixed_kinds_keeps_pool():
    """一个 refuted + 一个 env ⇒ 不能判整池都错，保留。"""
    gate = _Gate(kept=[], fbs=[])
    stub = _Stub(gate)
    ctx = _Ctx([_c(1), _c(2)])
    ctx.lean_gate = [{"id": 1, "failure_kind": "refuted"},
                     {"id": 2, "failure_kind": "env"}]
    lean_backcheck_stage(stub, ctx, "deep")
    assert len(ctx.candidates) == 2
    assert ctx.lean_backcheck["reject_kinds"] == {"refuted": 1, "env": 1}


def test_all_rejected_strict_clears_pool():
    gate = _Gate(kept=[], fbs=["[Lean] 全拒反馈"])
    stub = _Stub(gate)
    stub.config.strict_all_rejected = True
    ctx = _Ctx([_c(1)])
    lean_backcheck_stage(stub, ctx, "deep")
    assert ctx.candidates == []
    assert any(k == "pool_empty" for k, _ in stub.events)


def test_not_applicable_exempt():
    gate = _Gate()
    stub = _Stub(gate, applicable=False)
    ctx = _Ctx([_c(1)])
    lean_backcheck_stage(stub, ctx, "deep")
    assert gate.calls == 0
    assert ctx.lean_backcheck["skipped"] == "not_applicable"


def test_lean_inactive_degrades():
    stub = _Stub(active=False)
    ctx = _Ctx([_c(1)])
    lean_backcheck_stage(stub, ctx, "deep")
    assert stub.lean_gate.calls == 0
    assert any("未激活" in m for _, m in stub.events)


def test_switch_off(monkeypatch):
    monkeypatch.setenv("FIVE_GATE_LEAN_CHECK", "0")
    stub = _Stub()
    ctx = _Ctx([_c(1)])
    lean_backcheck_stage(stub, ctx, "deep")
    assert stub.lean_gate.calls == 0
    assert any("开关关闭" in m for _, m in stub.events)


def test_empty_pool_skips():
    stub = _Stub()
    ctx = _Ctx([])
    lean_backcheck_stage(stub, ctx, "deep")
    assert stub.lean_gate.calls == 0


def test_gate_exception_does_not_raise():
    class _BoomGate:
        def apply(self, ctx, tier, cands):
            raise RuntimeError("lean boom")

    stub = _Stub(_BoomGate())
    ctx = _Ctx([_c(1)])
    lean_backcheck_stage(stub, ctx, "deep")  # 不得抛异常
    assert [c.id for c in ctx.candidates] == [1]
    assert any("异常" in m for _, m in stub.events)


def test_stage_wired_in_orchestrator():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "orchestrator.py"), encoding="utf-8").read()
    i_fa = src.index('self._stage_start(ctx, "4.2_falsify")')
    i_lc = src.index('self._stage_start(ctx, "4.3_lean_check")')
    i_fmt = src.index('self._stage_start(ctx, "6_format")')
    assert i_fa < i_lc < i_fmt
    assert '"4.3_lean_check",' in src
