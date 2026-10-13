# -*- coding: utf-8 -*-
"""4.6 重写通道（五道审核链配套）单测 —— 2026-10-14 用户定案。

覆盖：池空触发 / 诊断解析 / 重建+重写循环 / 新候选重过五道链（桩）/
轮数上限 / 池非空不动 / 开关关闭 / 异常不阻断 / 接线锚点。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate  # noqa: E402
from agent.rewrite_gate import (  # noqa: E402
    _parse_diag_json, rewrite_stage,
)


# ----------------------------------------------------- 解析
def test_parse_diag_json():
    d = _parse_diag_json('{"root_cause": "蓝图锁死了错误值", "fix": "先收集条件"}')
    assert d["root_cause"] == "蓝图锁死了错误值"
    assert _parse_diag_json("不是 JSON") == {}
    assert _parse_diag_json('{"foo": 1}') == {}       # 缺字段
    fenced = '```json\n{"root_cause": "r", "fix": "f"}\n```'
    assert _parse_diag_json(fenced)["fix"] == "f"


# ----------------------------------------------------- 桩
class _Subgoal:
    def __init__(self, produce_rounds=1):
        self.produce_rounds = produce_rounds
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        ctx.rewrite_last_call = self.calls
        if self.calls <= self.produce_rounds:
            ctx.candidates = [Candidate(id=900 + self.calls, answer="48",
                                        reasoning="重写推理")]


class _Cfg:
    rewrite_max_rounds = 2


class _Stub:
    def __init__(self, produce_rounds=1):
        self.events = []
        self.config = _Cfg()
        self.sub_goal_solver = _Subgoal(produce_rounds)
        self.replies = ['{"root_cause": "蓝图锁死", "fix": "重分解"}'] * 5

    def llm(self, ctx, messages, temp, max_tokens):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))


class _Ctx:
    def __init__(self, cands):
        self.problem = "测试题"
        self.candidates = cands
        self.pool_empty_errors = [{"stage": "4.2_falsify", "error": "回带不成立"}]
        self.self_audit_rejected = [{"id": 1, "answer": "47",
                                     "error_desc": "结论与推理不符"}]
        self.adversarial_gate_rejected = []
        self.math_check_rejected = []
        self.trace = []


def _patch_gates(monkeypatch, clear_on_rounds=()):
    """把六道复核函数替换为桩（记录调用）。

    `clear_on_rounds=(1,)` ⇒ 在第 1 轮重写后由投票桩清空候选
    （模拟"重写候选再次被全灭"）⇒ 驱动多轮。
    """
    calls = []

    def _mk(name):
        def _f(self, ctx, *a, **k):
            calls.append((name, getattr(ctx, "rewrite_last_call", 0)))
            if name == "vote" and getattr(ctx, "rewrite_last_call", 0) in \
                    clear_on_rounds:
                ctx.candidates = []
        return _f

    import agent.answer_normalizer as _an
    import agent.self_auditor as _sa
    import agent.adversarial_gate as _ag
    import agent.lean_backcheck as _lb
    import agent.math_check_gate as _mc
    import agent.vote_gate as _vg
    monkeypatch.setattr(_an, "normalize_stage", _mk("normalize"))
    monkeypatch.setattr(_sa, "self_audit_stage", _mk("self_audit"))
    monkeypatch.setattr(_ag, "adversarial_gate_stage", _mk("falsify"))
    monkeypatch.setattr(_lb, "lean_backcheck_stage", _mk("lean"))
    monkeypatch.setattr(_mc, "math_check_stage", _mk("math"))
    monkeypatch.setattr(_vg, "vote_stage", _mk("vote"))
    return calls


# ----------------------------------------------------- 主流程
def test_rewrite_success_first_round(monkeypatch):
    calls = _patch_gates(monkeypatch)
    stub = _Stub(produce_rounds=1)
    ctx = _Ctx([])
    rewrite_stage(stub, ctx, "deep")
    assert stub.sub_goal_solver.calls == 1
    assert [c.id for c in ctx.candidates] == [901]
    assert [n for n, _ in calls] == ["normalize", "self_audit", "falsify",
                                     "lean", "math", "vote"]
    assert ctx.rewrite_gate["survived"] is True
    assert ctx.rewrite_gate["n_diag_ok"] == 1
    assert "蓝图锁死" in ctx.rewrite_context
    assert "错误情况" in ctx.rewrite_context
    assert any(k == "rewrite" for k, _ in stub.events)


def test_rewrite_retries_until_success(monkeypatch):
    _patch_gates(monkeypatch, clear_on_rounds=(1,))   # 第 1 轮候选被全灭
    stub = _Stub(produce_rounds=2)
    ctx = _Ctx([])
    rewrite_stage(stub, ctx, "deep")
    assert stub.sub_goal_solver.calls == 2            # 第 2 轮重写
    assert ctx.rewrite_gate["survived"] is True
    assert ctx.rewrite_gate["n_produced"] == 2
    assert any("再次被审核全灭" in m for _, m in stub.events)


def test_rewrite_all_rounds_fail(monkeypatch):
    _patch_gates(monkeypatch)
    stub = _Stub(produce_rounds=0)      # 每轮都产不出候选
    ctx = _Ctx([])
    rewrite_stage(stub, ctx, "deep")
    assert stub.sub_goal_solver.calls == 2           # 上限 2 轮
    assert ctx.candidates == []
    assert ctx.rewrite_gate["survived"] is False
    assert ctx.rewrite_gate["rounds"] == 2


def test_noop_when_pool_nonempty(monkeypatch):
    _patch_gates(monkeypatch)
    stub = _Stub()
    ctx = _Ctx([Candidate(id=1, answer="1", reasoning="r")])
    rewrite_stage(stub, ctx, "deep")
    assert stub.sub_goal_solver.calls == 0
    assert any("无需重写" in m for _, m in stub.events)


def test_switch_off(monkeypatch):
    monkeypatch.setenv("FIVE_GATE_REWRITE", "0")
    stub = _Stub()
    ctx = _Ctx([])
    rewrite_stage(stub, ctx, "deep")
    assert stub.sub_goal_solver.calls == 0
    assert any("开关关闭" in m for _, m in stub.events)


def test_diag_llm_failure_still_rewrites(monkeypatch):
    _patch_gates(monkeypatch)
    stub = _Stub(produce_rounds=1)
    stub.replies = [RuntimeError("llm boom")]
    ctx = _Ctx([])
    rewrite_stage(stub, ctx, "deep")
    assert stub.sub_goal_solver.calls == 1           # 裸错误摘要继续重写
    assert ctx.rewrite_gate["n_diag_ok"] == 0
    assert "错误情况" in ctx.rewrite_context


def test_exception_does_not_raise():
    class _Boom:
        @property
        def candidates(self):
            raise RuntimeError("boom")

        problem = ""

    stub = _Stub()
    rewrite_stage(stub, _Boom(), "deep")
    assert any("异常" in m for _, m in stub.events)


def test_stage_wired_in_orchestrator():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "orchestrator.py"), encoding="utf-8").read()
    i_vo = src.index('self._stage_start(ctx, "4.5_vote")')
    i_rw = src.index('self._stage_start(ctx, "4.6_rewrite")')
    i_fmt = src.index('self._stage_start(ctx, "6_format")')
    assert i_vo < i_rw < i_fmt
    assert '"4.6_rewrite",' in src


def test_blueprint_injection_guard():
    """注入助手必须默认零变化（无 rewrite_context ⇒ 逐字返回 problem）。"""
    from agent.blueprint_planner import _effective_problem

    class _C:
        problem = "P"

    assert _effective_problem(_C()) == "P"
    _C.rewrite_context = "RW"
    assert _effective_problem(_C()).startswith("P") and "RW" in _effective_problem(_C())
