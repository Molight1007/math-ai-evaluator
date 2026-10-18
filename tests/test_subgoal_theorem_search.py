# -*- coding: utf-8 -*-
"""per-subgoal 定理检索回归（2026-10-18）。"""
import os, sys
from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.theorem_hint import search_for_subgoal  # noqa: E402


def test_search_and_cache(monkeypatch):
    calls = {"n": 0}

    def fake(q, top_k):
        calls["n"] += 1
        return {"theorems": [{"name": "Mathlib.Algebra.Test.lemma1", "statement": "S"}]}

    monkeypatch.setattr("tools.agent_toolkit.leansearch", fake)
    ctx = SimpleNamespace(_subgoal_hints={})
    sg = {"id": "sg1", "title": "证明 x", "description": "y"}
    b1 = search_for_subgoal(ctx, sg)
    assert "lemma1" in b1
    b2 = search_for_subgoal(ctx, sg)   # 缓存命中，不再检索
    assert b1 == b2 and calls["n"] == 1


def test_failure_returns_empty(monkeypatch):
    def fake(q, top_k):
        raise RuntimeError("boom")
    monkeypatch.setattr("tools.agent_toolkit.leansearch", fake)
    ctx = SimpleNamespace(_subgoal_hints={})
    assert search_for_subgoal(ctx, {"id": "x", "title": "t"}) == ""
