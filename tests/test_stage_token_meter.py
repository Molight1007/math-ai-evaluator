# -*- coding: utf-8 -*-
"""阶段级 token 计量（2026-10-30）。

背景：配额 90M input/月，单题实测 3.7M~6.4M ⇒ 月产能 12~24 题。要降成本必须
先知道 token 花在哪个阶段，而 `diag.stage_timers` 只有秒数、`results/*.log`
没有 usage 行。本文件锁住四个性质：

1. **不可用即静默**：llm_client 没有 token 累积器（本地旧版）⇒ 不写
   `_stage_tokens`，绝不因埋点影响主流程、也绝不写成"花了 0"。
2. **差分正确**：阶段内增量 = stop 快照 − start 快照。
3. **消费式基线**：同名阶段多次 stop 累加而不重复计数。
4. **总量守恒**：各阶段之和 = 全程增量（阶段外调用除外）。

★ 第 1 条是本设计的关键：它让同一份代码在「有累积器的服务器」和「没有累
积器的本地」都能跑，且本地行为与改动前完全一致。
"""

import pytest

import agent.orchestrator as orch
from agent.orchestrator import Orchestrator


class _Ctx:
    """最小 ctx 替身：只要求属性可写（不依赖 TaskContext 的其余字段）。"""


def _snap(p, c, n):
    return {"prompt_tokens": p, "completion_tokens": c, "calls": n}


def test_snapshot_unavailable_is_silent(monkeypatch):
    """快照不可用 ⇒ 不产生 _stage_tokens（不是写 0），且不抛异常。"""
    monkeypatch.setattr(orch, "_tok_snapshot", lambda: None)
    ctx = _Ctx()
    Orchestrator._stage_start(ctx, "2.7_subgoal_main")
    Orchestrator._stage_stop(ctx, "2.7_subgoal_main")
    assert getattr(ctx, "_stage_tokens", None) in (None, {})
    # 耗时埋点不受影响
    assert "2.7_subgoal_main" in (ctx._stage_durs or {})


def test_single_stage_delta(monkeypatch):
    seq = [_snap(100, 10, 1)]
    monkeypatch.setattr(orch, "_tok_snapshot", lambda: dict(seq[-1]))
    ctx = _Ctx()
    Orchestrator._stage_start(ctx, "a")
    seq.append(_snap(300, 40, 5))
    Orchestrator._stage_stop(ctx, "a")
    assert ctx._stage_tokens["a"] == {
        "prompt_tokens": 200, "completion_tokens": 30, "calls": 4}


def test_same_stage_twice_accumulates_without_double_counting(monkeypatch):
    """消费式基线：第二次 stop 只记第二次的增量。"""
    seq = [_snap(100, 0, 0)]
    monkeypatch.setattr(orch, "_tok_snapshot", lambda: dict(seq[-1]))
    ctx = _Ctx()
    Orchestrator._stage_start(ctx, "a")
    seq.append(_snap(300, 0, 0))
    Orchestrator._stage_stop(ctx, "a")          # 记 200
    Orchestrator._stage_start(ctx, "a")         # base = 300
    seq.append(_snap(350, 0, 0))
    Orchestrator._stage_stop(ctx, "a")          # 再记 50
    assert ctx._stage_tokens["a"]["prompt_tokens"] == 250


def test_stage_switch_splits_at_boundary(monkeypatch):
    """切阶段时旧阶段先收口，增量各自归属；总和守恒。"""
    seq = [_snap(100, 10, 1)]
    monkeypatch.setattr(orch, "_tok_snapshot", lambda: dict(seq[-1]))
    ctx = _Ctx()
    Orchestrator._stage_start(ctx, "a")
    seq.append(_snap(300, 40, 5))
    Orchestrator._stage_start(ctx, "b")         # 触发 a 收口
    assert ctx._stage_tokens["a"]["prompt_tokens"] == 200
    seq.append(_snap(380, 60, 9))
    Orchestrator._stage_stop(ctx, "b")
    assert ctx._stage_tokens["b"]["prompt_tokens"] == 80
    total = sum(v["prompt_tokens"] for v in ctx._stage_tokens.values())
    assert total == 280                         # = 380 - 100


def test_no_stage_started_means_no_record(monkeypatch):
    """未 start 直接 stop ⇒ 提前 return，不产生任何键。"""
    monkeypatch.setattr(orch, "_tok_snapshot", lambda: _snap(9, 9, 9))
    ctx = _Ctx()
    Orchestrator._stage_stop(ctx, "ghost")
    assert getattr(ctx, "_stage_tokens", None) is None


def test_real_llm_client_without_token_meter_returns_none():
    """本地 utils.llm_client 若无 token 累积器，_tok_snapshot 必须返回 None。

    这条是「本地零影响」的守门测试：一旦本地也加了累积器，它会失败并提醒把
    本测试改成断言 dict（那时阶段 token 在本地也可观测）。
    """
    from utils import llm_client as lc
    has_meter = hasattr(lc, "get_usage_stats") or (
        "prompt_tokens" in (lc.get_truncation_stats() or {}))
    snap = orch._tok_snapshot()
    if has_meter:
        assert isinstance(snap, dict)
        assert set(snap) == {"prompt_tokens", "completion_tokens", "calls"}
    else:
        assert snap is None


def test_diag_exports_stage_tokens():
    """diag 必须带出 stage_tokens 键（空字典也算有键，避免「没跑」与「跑了 0」混淆）。"""
    import inspect
    from agent import diag_export
    src = inspect.getsource(diag_export)
    assert '"stage_tokens"' in src
