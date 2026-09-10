"""
测试：求解前门 Lean 逻辑层检测（dag_replan 门升级，2026-09-08）
===============================================================
覆盖三个纯函数（_parse_lean_expr_map / _map_lean_errors /
_merge_lean_rejects）与配置关闭时的零成本守卫。
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.sub_goal_solver import SubGoalSolverAgent

from agent.dag_reviewer import DagReviewReport, DagReviewResult


class _Ctx:
    def __init__(self):
        self.trace = []

    def is_time_critical(self):
        return False

    def gen_time_up(self):
        return False


class _Cfg(SimpleNamespace):
    pass


def _agent(cfg=None):
    client = MagicMock()
    return SubGoalSolverAgent(client, cfg if cfg is not None else _Cfg())


# ---------------------------------------------------------------- parse map

def test_parse_lean_expr_map_normal():
    resp = '{"n1": "∀ x : ℝ, f x = x^2", "n2": "x ≤ y"}'
    out = SubGoalSolverAgent._parse_lean_expr_map(
        resp, ["n1", "n2", "n3"])
    assert out["n1"].startswith("∀ x : ℝ")
    assert "n3" not in out


def test_parse_lean_expr_map_fence_and_noise():
    resp = '```json\n{"n1": "Odd n", "n2": ""}\n``` 说明文字'
    out = SubGoalSolverAgent._parse_lean_expr_map(resp, ["n1", "n2"])
    assert out == {"n1": "Odd n"}          # 空串被丢弃


def test_parse_lean_expr_map_fail_returns_empty():
    assert SubGoalSolverAgent._parse_lean_expr_map(None, ["n1"]) == {}
    assert SubGoalSolverAgent._parse_lean_expr_map("无 JSON", ["n1"]) == {}


# ---------------------------------------------------------------- map errors

def test_map_lean_errors_per_node():
    err = ("daglogic_1_2.lean:3:0: error: unknown identifier 'f'\n"
           "daglogic_1_2.lean:5:1: error: type mismatch\n"
           "daglogic_1_2.lean:9:0: error: unexpected token\n")
    line_of = {"n1": 3, "n2": 5, "n3": 9}
    out = SubGoalSolverAgent._map_lean_errors(err, line_of)
    assert set(out) == {"n1", "n2", "n3"}
    assert "unknown identifier" in out["n1"]


def test_map_lean_errors_file_level_returns_empty():
    # import/文件级错误（行号 < 首个 example）→ 环境问题，不误判节点
    err = "daglogic_1_2.lean:1:0: error: file 'Mathlib' not found\n"
    line_of = {"n1": 3, "n2": 5}
    assert SubGoalSolverAgent._map_lean_errors(err, line_of) == {}


def test_map_lean_errors_ok_when_no_match():
    assert SubGoalSolverAgent._map_lean_errors("", {"n1": 3}) == {}
    assert SubGoalSolverAgent._map_lean_errors(
        "daglogic_1_2.lean:4:0: error: some other error\n",
        {"n1": 3}) == {}                    # 错误行不属于任何节点 → 放行


# ---------------------------------------------------------------- merge

def _report(results=None):
    return DagReviewReport(results=results or {})


def test_merge_lean_rejects_upgrades_and_adds():
    report = _report({
        "n1": DagReviewResult(node_id="n1", verdict="accept",
                              quality_score=0.9),
        "n2": DagReviewResult(node_id="n2", verdict="reject",
                              quality_score=0.1,
                              issues=["under_specified:..."]),
    })
    ups = SubGoalSolverAgent._merge_lean_rejects(
        report, {"n1": "type mismatch", "n3": "unknown identifier"})
    assert set(ups) == {"n1", "n3"}
    # n1：accept → reject，带 lean 诊断
    assert report.results["n1"].is_reject
    assert any(str(i).startswith("lean_logic_error:")
               for i in report.results["n1"].issues)
    # n2：已 reject，保持原 issues 不被篡改
    assert report.results["n2"].is_reject
    assert not any(str(i).startswith("lean_logic_error:")
                   for i in report.results["n2"].issues)
    # n3：新加入 reject
    assert report.results["n3"].is_reject
    assert report.reject_count == 3


# ---------------------------------------------------------------- guard

def test_lean_check_zero_cost_when_config_off():
    """配置关闭时：不触碰 Lean 桥、不调 LLM，直接返回 {}。"""
    cfg = _Cfg(dag_replan_lean_check=False)
    agent = _agent(cfg)
    assert agent._lean_dag_logic_check(_Ctx(), None, ["n1"]) == {}


def test_lean_check_zero_cost_when_empty_nodes():
    agent = _agent(_Cfg(dag_replan_lean_check=True))
    assert agent._lean_dag_logic_check(_Ctx(), None, []) == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
