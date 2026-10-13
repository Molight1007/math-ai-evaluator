# -*- coding: utf-8 -*-
"""4.5 投票（五道审核链第 5 道）单测 —— 2026-10-14。

覆盖：多答案判断（规则短路 / LLM 判定 / 失败回 None）、投票调用契约
（票数锁定 tier_votes、只喂存活候选）、汇总留痕、开关关闭、异常不阻断、接线锚点。
verifier 与 LLM 均以桩替代，不触发真实调用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate  # noqa: E402
from agent.vote_gate import vote_stage  # noqa: E402


class _Cfg:
    tier_voting_times = {"deep": 3}
    verifier_voting_times = 0
    use_scoring = True
    deep_use_playoff = True
    enable_deterministic = True
    use_rubric = False
    use_challenge = False


class _BestCluster:
    answer_norm = "48"
    size = 2
    vote_correct = 3
    vote_total = 3


class _Verifier:
    def __init__(self, result=None):
        self.result = result if result is not None else {
            "best_cluster": _BestCluster(), "cluster_data": []}
        self.calls = []

    def run(self, ctx, **kw):
        self.calls.append(kw)
        return self.result


class _State:
    playoff_enabled = False


class _Stub:
    def __init__(self, multi_reply='{"multiple": false, "reason": "单值"}',
                 ver_result=None):
        self.events = []
        self.config = _Cfg()
        self.verifier = _Verifier(ver_result)
        self.replies = [multi_reply]

    def llm(self, ctx, messages, temp, max_tokens):
        if self.replies:
            r = self.replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return '{"multiple": false}'

    def _verdicts_from_ver_result(self, vr, cands):
        return []

    def record(self, ctx, kind, msg, **kw):
        self.events.append((kind, msg))


class _Ctx:
    def __init__(self, cands, problem="求 x 的值"):
        self.problem = problem
        self.candidates = cands
        self.state = _State()
        self.question_type = ""
        self.domain = ""


def _c(i, ans="48"):
    return Candidate(id=i, answer=ans, reasoning="推理")


def test_vote_runs_with_tier_votes():
    stub = _Stub()
    ctx = _Ctx([_c(1), _c(2)])
    vote_stage(stub, ctx, "deep")
    kw = stub.verifier.calls[0]
    assert kw["voting_times"] == 3                    # ★ 绝不降为 1（008 教训）
    assert kw["candidates"] is ctx.candidates
    assert kw["use_clustering"] is True
    assert ctx.vote_gate["n"] == 2
    assert ctx.vote_gate["multi_answer"] is False
    assert ctx.vote_gate["best_cluster"]["answer_norm"] == "48"
    assert ctx.vote_multi_answer is False


def test_rule_multi_answer_short_circuits():
    stub = _Stub()
    ctx = _Ctx([_c(1)], problem="求所有可能的取值")
    vote_stage(stub, ctx, "deep")
    assert ctx.vote_multi_answer is True
    assert stub.replies == ['{"multiple": false, "reason": "单值"}']  # LLM 未被消费


def test_llm_multi_answer_true():
    stub = _Stub(multi_reply='{"multiple": true, "reason": "多解"}')
    ctx = _Ctx([_c(1)])
    vote_stage(stub, ctx, "deep")
    assert ctx.vote_multi_answer is True


def test_llm_failure_gives_none():
    stub = _Stub(multi_reply=RuntimeError("boom"))
    ctx = _Ctx([_c(1)])
    vote_stage(stub, ctx, "deep")
    assert ctx.vote_multi_answer is None
    assert stub.verifier.calls                       # 投票仍然执行


def test_empty_pool_skips():
    stub = _Stub()
    ctx = _Ctx([])
    vote_stage(stub, ctx, "deep")
    assert stub.verifier.calls == []
    assert any("候选池为空" in m for _, m in stub.events)


def test_switch_off(monkeypatch):
    monkeypatch.setenv("FIVE_GATE_VOTE", "0")
    stub = _Stub()
    ctx = _Ctx([_c(1)])
    vote_stage(stub, ctx, "deep")
    assert stub.verifier.calls == []
    assert any("开关关闭" in m for _, m in stub.events)


def test_verifier_exception_does_not_raise():
    class _BoomVerifier:
        def run(self, ctx, **kw):
            raise RuntimeError("verifier boom")

    stub = _Stub()
    stub.verifier = _BoomVerifier()
    ctx = _Ctx([_c(1)])
    vote_stage(stub, ctx, "deep")  # 不得抛异常
    assert any("异常" in m for _, m in stub.events)


def test_stage_wired_in_orchestrator():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "agent", "orchestrator.py"), encoding="utf-8").read()
    i_mc = src.index('self._stage_start(ctx, "4.4_math_check")')
    i_vo = src.index('self._stage_start(ctx, "4.5_vote")')
    i_fmt = src.index('self._stage_start(ctx, "6_format")')
    assert i_mc < i_vo < i_fmt
    assert '"4.5_vote",' in src
