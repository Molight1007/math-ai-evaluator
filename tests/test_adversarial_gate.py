# -*- coding: utf-8 -*-
"""4.2 AI 对抗证伪（五道审核链第 2 道）单测 —— 2026-10-14。

覆盖：机检/LLM 两层淘汰、故障保留纪律、开关关闭、池空留痕、接线锚点。
证伪器与对抗器均以注入桩替代（`adv_gate_falsifier` / `adv_verifier`），不触发真实 LLM。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate  # noqa: E402
from agent.adversarial_gate import adversarial_gate_stage  # noqa: E402


# ----------------------------------------------------- 桩
class _Res:
    def __init__(self, incorrect=False, reason="", witness="", oracle_type=""):
        self.is_incorrect = incorrect
        self.reason = reason
        self.witness = witness
        self.oracle_type = oracle_type


class _PRes:
    def __init__(self, actionable=False, skipped="", error_type="",
                 confidence=0.6, feedback=""):
        self.is_actionable = actionable
        self.skipped = skipped
        self.error_type = error_type
        self.confidence = confidence
        self._fb = feedback

    def to_feedback(self):
        return self._fb


class _Falsifier:
    def __init__(self, seq=None):
        self.seq = list(seq or [])
        self.calls = []

    def falsify(self, ctx, c, problem=""):
        self.calls.append(getattr(c, "id", None))
        r = self.seq.pop(0) if self.seq else _Res()
        if isinstance(r, Exception):
            raise r
        return r


class _Prober:
    def __init__(self, seq=None):
        self.seq = list(seq or [])
        self.calls = []

    def probe(self, ctx, c, tier="deep"):
        self.calls.append(getattr(c, "id", None))
        r = self.seq.pop(0) if self.seq else _PRes()
        if isinstance(r, Exception):
            raise r
        return r


class _Stub:
    def __init__(self, falsifier=None, prober=None):
        self.events = []
        self.client = None

        class _C:  # config 桩
            pass
        self.config = _C()
        self.adv_gate_falsifier = falsifier or _Falsifier()
        self.adv_verifier = prober or _Prober()

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))


class _Ctx:
    def __init__(self, cands):
        self.problem = "测试题"
        self.candidates = cands
        self.metadata = {}


def _c(i, ans="48"):
    return Candidate(id=i, answer=ans, reasoning="推理")


# ----------------------------------------------------- 1) 机检证伪
def test_machine_falsified_rejected_and_probe_skipped():
    f = _Falsifier([_Res(incorrect=True, reason="回带不成立", witness="f(2)=5≠7",
                         oracle_type="sympy")])
    p = _Prober()
    stub = _Stub(f, p)
    ctx = _Ctx([_c(1), _c(2)])
    adversarial_gate_stage(stub, ctx, "deep")
    assert [c.id for c in ctx.candidates] == [2]         # 1 被判错淘汰
    assert p.calls == [2]                                # 机检已判错的候选不再 LLM 探测
    assert ctx.adversarial_gate["n_machine"] == 1
    assert ctx.adversarial_gate_rejected[0]["witness"] == "f(2)=5≠7"
    assert any("对抗证伪·机检" in fb for fb in ctx.audit_reject_feedback)
    # 既有契约：机检被证伪答案进 _falsified_answers
    assert ctx._falsified_answers == ["48"]
    assert ctx.metadata["falsified_answers"] == ["48"]


# ----------------------------------------------------- 2) LLM 对抗
def test_llm_probe_falsified_rejected():
    f = _Falsifier([_Res(), _Res()])
    p = _Prober([
        _PRes(actionable=True, error_type="前提不成立", confidence=0.8,
              feedback="[对抗式审查] 检出「前提不成立」"),
        _PRes(),
    ])
    stub = _Stub(f, p)
    ctx = _Ctx([_c(1), _c(2)])
    adversarial_gate_stage(stub, ctx, "deep")
    assert [c.id for c in ctx.candidates] == [2]
    assert ctx.adversarial_gate["n_llm"] == 1
    assert any("对抗证伪·LLM" in fb for fb in ctx.audit_reject_feedback)
    # LLM 对抗不作机检证伪 ⇒ 不进 _falsified_answers
    assert not getattr(ctx, "_falsified_answers", None)


# ----------------------------------------------------- 3) 故障与跳过纪律
def test_faults_keep_candidates():
    f = _Falsifier([RuntimeError("boom"), _Res()])
    p = _Prober([_PRes(skipped="empty_reasoning"), _PRes()])
    stub = _Stub(f, p)
    ctx = _Ctx([_c(1), _c(2)])
    adversarial_gate_stage(stub, ctx, "deep")
    # 候选 1：机检异常 + 探测跳过 ⇒ 保留；候选 2：全通过 ⇒ 保留
    assert [c.id for c in ctx.candidates] == [1, 2]
    assert ctx.adversarial_gate["n_rejected"] == 0
    assert ctx.adversarial_gate["n_failed"] == 1
    assert ctx.adversarial_gate["n_skipped"] == 1


# ----------------------------------------------------- 4) 开关与空池
def test_switch_off(monkeypatch):
    monkeypatch.setenv("FIVE_GATE_FALSIFY", "0")
    stub = _Stub()
    ctx = _Ctx([_c(1)])
    adversarial_gate_stage(stub, ctx, "deep")
    assert stub.adv_gate_falsifier.calls == []
    assert any("开关关闭" in m for _, m in stub.events)


def test_empty_pool_skips():
    stub = _Stub()
    ctx = _Ctx([])
    adversarial_gate_stage(stub, ctx, "deep")
    assert any("候选池为空" in m for _, m in stub.events)


def test_all_rejected_pool_empty_recorded():
    f = _Falsifier([_Res(incorrect=True, reason="r", witness="w")])
    stub = _Stub(f, _Prober())
    ctx = _Ctx([_c(1)])
    adversarial_gate_stage(stub, ctx, "deep")
    assert ctx.candidates == []
    assert any(k == "pool_empty" for k, _ in stub.events)


def test_exception_does_not_raise():
    class _Boom:
        @property
        def candidates(self):
            raise RuntimeError("boom")

        problem = ""

    stub = _Stub()
    adversarial_gate_stage(stub, _Boom(), "deep")  # 不得抛异常
    assert any("异常" in m for _, m in stub.events)


# ----------------------------------------------------- 5) 接线锚点（读源守卫）
def test_stage_wired_in_orchestrator():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "orchestrator.py"), encoding="utf-8").read()
    i_au = src.index('self._stage_start(ctx, "4.1_self_audit")')
    i_fa = src.index('self._stage_start(ctx, "4.2_falsify")')
    i_36 = src.index('self._stage_start(ctx, "3.6_audit_filter")')
    assert i_au < i_fa < i_36
    assert '"4.2_falsify",' in src
