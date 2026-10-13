# -*- coding: utf-8 -*-
"""蓝图多次生成（迭代式）+ 自审 回归测试（2026-10-12 批次 2）。

用户决策（Q11–Q15）：**迭代式**（1 次初始 + N-1 次在上一轮基础上无条件自改进）、
采用**最后一轮**、差异**只记录不裁决**。本测试不依赖真实 LLM（全桩）。
"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent.blueprint_planner import (  # noqa: E402
    BlueprintPlannerAgent, _dag_diff)


def _mk_dag(statements):
    nodes = {"n%d" % i: SimpleNamespace(
        node_type="and", children=[], statement=s)
        for i, s in enumerate(statements)}
    return SimpleNamespace(nodes=nodes,
                           to_dict=lambda: {"nodes": sorted(nodes)})


def _mk_planner(cfg, dags):
    p = BlueprintPlannerAgent.__new__(BlueprintPlannerAgent)
    p.config = cfg
    p.record = lambda *a, **k: None
    p.generate_blueprint = (
        lambda ctx, max_attempts=3, prior_dag_json="": dags.pop(0) if dags else None)
    return p


def _mk_ctx(**kw):
    d = dict(problem="p", blueprint=None, blueprint_diffs=[],
             blueprint_gen_rounds=0, is_time_critical=lambda: False)
    d.update(kw)
    return SimpleNamespace(**d)


def test_dag_diff_reports_struct_and_semantic():
    d1 = _mk_dag(["证 A", "证 B"])
    d2 = _mk_dag(["证 A", "证 C", "证 D"])
    diff = _dag_diff(d1, d2)
    assert diff["struct_prev"]["nodes"] == 2
    assert diff["struct_new"]["nodes"] == 3
    assert diff["stmt_added"] == ["证 C", "证 D"]
    assert diff["stmt_removed"] == ["证 B"]
    assert diff["stmt_changed"] == 1        # n1: 证 B -> 证 C


def test_iterative_runs_three_rounds_and_adopts_last():
    cfg = SimpleNamespace(blueprint_multi_gen_rounds=3)
    d1 = _mk_dag(["第一版"])
    d2 = _mk_dag(["第二版"])
    d3 = _mk_dag(["第三版"])
    p = _mk_planner(cfg, [d1, d2, d3])
    ctx = _mk_ctx()
    dag = p.generate_blueprint_iterative(ctx)
    assert dag is d3, "应采用最后一轮（Q13）"
    assert ctx.blueprint_gen_rounds == 3
    assert len(ctx.blueprint_diffs) == 2, "3 轮应有 2 次差异记录"
    assert ctx.blueprint == d3.to_dict()


def test_iterative_keeps_prior_when_improve_round_fails():
    cfg = SimpleNamespace(blueprint_multi_gen_rounds=3)
    d1 = _mk_dag(["第一版"])
    p = _mk_planner(cfg, [d1, None])       # 第 2 轮无产出
    ctx = _mk_ctx()
    dag = p.generate_blueprint_iterative(ctx)
    assert dag is d1, "改进轮未产出时必须保留上一轮，不得丢蓝图"
    assert ctx.blueprint_gen_rounds == 1
    assert ctx.blueprint_diffs == []


def test_rounds_one_is_single_generation():
    cfg = SimpleNamespace(blueprint_multi_gen_rounds=1)
    d1 = _mk_dag(["唯一一版"])
    p = _mk_planner(cfg, [d1])
    ctx = _mk_ctx()
    dag = p.generate_blueprint_iterative(ctx)
    assert dag is d1
    assert ctx.blueprint_gen_rounds == 1
    assert ctx.blueprint_diffs == []


def test_first_round_failure_returns_none():
    cfg = SimpleNamespace(blueprint_multi_gen_rounds=3)
    p = _mk_planner(cfg, [None])
    ctx = _mk_ctx()
    assert p.generate_blueprint_iterative(ctx) is None
