# -*- coding: utf-8 -*-
"""题意理解歧义下传回归（2026-10-17，p0b5_r3-089 误读根因）。

原判定只看「有没有终态」、忽略 gaps_a ⇒ 发现题面歧义仍判 ok，模型默默做了
错误假设（"某市民没座"读成单剧院超员）。现：gaps_a → ctx.problem_ambiguities
+ verdict=assumption_required。
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import TaskContext  # noqa: E402
from tools.lean_local.lean_pre_verifier import LeanPreVerifier  # noqa: E402


class _Fake(LeanPreVerifier):
    def __init__(self, gaps):
        self.config = SimpleNamespace(enable_understanding_chain=True)
        self._gaps = gaps

    def _understanding_round(self, ctx, force_json: bool = False):
        return {"terminal_state": "求最小座位数 x", "answer_slot": "x",
                "gaps": self._gaps}

    def record(self, ctx, stage, msg):
        pass


def test_ambiguity_passed_down_and_verdict_marked():
    gaps = [{"kind": "A", "detail": "题面未定义「某市民没座」对应的概率事件"}]
    ctx = TaskContext(problem="某剧院容量问题", metadata={})
    _Fake(gaps).run_understanding_chain(ctx)
    assert ctx.problem_ambiguities == ["题面未定义「某市民没座」对应的概率事件"]
    assert ctx.understanding_chain["verdict"] == "assumption_required"


def test_no_ambiguity_keeps_ok():
    ctx = TaskContext(problem="普通题", metadata={})
    _Fake([]).run_understanding_chain(ctx)
    assert ctx.problem_ambiguities == []
    assert ctx.understanding_chain["verdict"] == "ok"
