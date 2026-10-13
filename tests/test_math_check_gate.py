# -*- coding: utf-8 -*-
"""4.4 数学工具计算检测（五道审核链第 4 道）单测 —— 2026-10-14。

覆盖：fail 淘汰 / unknown 放行 / 全拒回退保留 / 异常放行 / answer_norm 优先 /
开关关闭 / 接线锚点。DeterministicChecker 以注入桩替代（`self.math_check_det`）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate  # noqa: E402
from agent.math_check_gate import math_check_stage  # noqa: E402


class _Det:
    def __init__(self, seq=None):
        self.seq = list(seq or [])
        self.calls = []

    def check_answer(self, ctx, problem, answer, domain=None):
        self.calls.append(answer)
        r = self.seq.pop(0) if self.seq else {"verdict": "unknown"}
        if isinstance(r, Exception):
            raise r
        return r


class _Stub:
    def __init__(self, det=None):
        self.events = []
        self.config = type("_C", (), {})()
        self.math_check_det = det or _Det()

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))


class _Ctx:
    def __init__(self, cands):
        self.problem = "求 x"
        self.domain = ""
        self.candidates = cands


def _c(i, ans="48"):
    return Candidate(id=i, answer=ans, reasoning="推理")


def test_fail_rejected_unknown_kept():
    det = _Det([
        {"verdict": "fail", "method": "substitution", "evidence": "回带不成立"},
        {"verdict": "unknown", "method": "parse", "evidence": "无法解析"},
        {"verdict": "pass", "method": "substitution", "evidence": "回带成立"},
    ])
    stub = _Stub(det)
    ctx = _Ctx([_c(1), _c(2), _c(3)])
    math_check_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [2, 3]
    assert ctx.math_check["n_rejected"] == 1
    assert ctx.math_check["n_unknown"] == 1
    assert ctx.math_check_rejected[0]["method"] == "substitution"
    assert any("计算检测" in fb for fb in ctx.audit_reject_feedback)


def test_all_fail_falls_back_keep_all():
    det = _Det([
        {"verdict": "fail", "method": "substitution", "evidence": "e1"},
        {"verdict": "fail", "method": "parse", "evidence": "e2"},
    ])
    stub = _Stub(det)
    ctx = _Ctx([_c(1), _c(2)])
    math_check_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1, 2]      # 回退保留
    assert ctx.math_check["all_rejected_fallback"] is True
    assert ctx.math_check["would_reject_ids"] == [1, 2]
    assert any("全部未通过" in m for _, m in stub.events)


def test_exception_treated_unknown():
    det = _Det([RuntimeError("boom")])
    stub = _Stub(det)
    ctx = _Ctx([_c(1)])
    math_check_stage(stub, ctx)
    assert [c.id for c in ctx.candidates] == [1]
    assert ctx.math_check["n_rejected"] == 0


def test_answer_norm_preferred():
    det = _Det([{"verdict": "pass", "method": "substitution", "evidence": "ok"}])
    stub = _Stub(det)
    c = _c(1, ans="所以最小 d 是 48。")
    c.answer_norm = "48"
    ctx = _Ctx([c])
    math_check_stage(stub, ctx)
    assert det.calls == ["48"]


def test_switch_off(monkeypatch):
    monkeypatch.setenv("FIVE_GATE_MATH_CHECK", "0")
    stub = _Stub()
    ctx = _Ctx([_c(1)])
    math_check_stage(stub, ctx)
    assert stub.math_check_det.calls == []
    assert any("开关关闭" in m for _, m in stub.events)


def test_empty_pool_skips():
    stub = _Stub()
    ctx = _Ctx([])
    math_check_stage(stub, ctx)
    assert stub.math_check_det.calls == []


def test_exception_does_not_raise():
    class _Boom:
        @property
        def candidates(self):
            raise RuntimeError("boom")

        problem = ""

    stub = _Stub()
    math_check_stage(stub, _Boom())
    assert any("异常" in m for _, m in stub.events)


def test_stage_wired_in_orchestrator():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "orchestrator.py"), encoding="utf-8").read()
    i_lc = src.index('self._stage_start(ctx, "4.3_lean_check")')
    i_mc = src.index('self._stage_start(ctx, "4.4_math_check")')
    i_36 = src.index('self._stage_start(ctx, "3.6_audit_filter")')
    assert i_lc < i_mc < i_36
    assert '"4.4_math_check",' in src
