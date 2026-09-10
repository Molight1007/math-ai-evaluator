# -*- coding: utf-8 -*-
"""_collect_diag 事件流提取守卫测试（2026-09-08）。

背景：骨架评审 / 求解前 DAG 强制门（_dag_replan_gate）的 record 只写
ctx.trace，而 trace 不落盘、_collect_diag 也未提取 → 冒烟 10 题事后
完全查不到「优化是否触发、重规划几轮」。本测试守卫新字段
skeleton_review_events / dag_replan_events 必须从 trace 正确提取，
防止后续重构把提取逻辑删掉（value_attack 同款先例：2026-09-03 曾
因 trace 不落盘导致事后无法核查）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.base import TaskContext
from agent.orchestrator import Orchestrator


def _make_orch():
    """构造 Orchestrator（mock client+config，避免真实 LLM/Lean 依赖）。"""
    return Orchestrator(MagicMock(), MagicMock())


def _mk_ctx(trace_steps):
    """构造带指定 step 序列的 TaskContext。"""
    ctx = TaskContext(problem="test", metadata={})
    for step, content in trace_steps:
        ctx.trace.append({"agent": "t", "step": step, "content": content})
    return ctx


def test_dag_replan_events_extracted_from_trace():
    """求解前 DAG 门 record 必须出现在 diag.dag_replan_events。"""
    orch = _make_orch()
    ctx = _mk_ctx([
        ("dag_replan", "求解前 DAG 评审通过（round=1），进入子目标求解"),
        ("dag_replan", "求解前 DAG 第 1/2 轮重规划: 9 节点, root=a"),
        ("dag_review", "DAG 评审: total=8 reject=3 (37%), should_replan=True"),
        ("skeleton_review", "骨架评审通过"),
    ])
    diag = orch._collect_diag(ctx)
    events = diag["dag_replan_events"]
    assert len(events) == 2, f"应提取 2 条 dag_replan 事件，实际 {len(events)}"
    assert "评审通过" in events[0]
    assert "重规划" in events[1]
    # dag_review 事件不应混入 dag_replan_events（step 精确匹配）
    assert all("DAG 评审:" not in e for e in events)


def test_skeleton_review_events_extracted_from_trace():
    """骨架评审 record 必须出现在 diag.skeleton_review_events。"""
    orch = _make_orch()
    ctx = _mk_ctx([
        ("skeleton_review", "骨架评审通过（round=1）"),
        ("skeleton_review", "骨架第 2 轮重生成"),
        ("dag_replan", "求解前 DAG 评审通过（round=1）"),
    ])
    diag = orch._collect_diag(ctx)
    events = diag["skeleton_review_events"]
    assert len(events) == 2, f"应提取 2 条骨架评审事件，实际 {len(events)}"
    assert "骨架评审通过" in events[0]


def test_no_events_when_trace_empty():
    """无 trace 时两个事件流字段为空列表（不崩、默认值兜底）。"""
    orch = _make_orch()
    ctx = _mk_ctx([])
    diag = orch._collect_diag(ctx)
    assert diag["dag_replan_events"] == []
    assert diag["skeleton_review_events"] == []
    # 其余既有字段照常存在
    assert "dag_review" in diag
    assert "skeleton_review" in diag


def test_events_truncated_to_200_chars():
    """事件内容按 200 字符截断（与 value_attack 同款防 diag 膨胀）。"""
    orch = _make_orch()
    long_content = "x" * 500
    ctx = _mk_ctx([("dag_replan", long_content)])
    diag = orch._collect_diag(ctx)
    assert len(diag["dag_replan_events"][0]) == 200
