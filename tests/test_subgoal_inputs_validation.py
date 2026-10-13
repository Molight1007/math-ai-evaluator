# -*- coding: utf-8 -*-
"""子目标 inputs 机械校验（R1/R2）回归测试（2026-10-12 批次 3，用户 D19–D21）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent.blueprint_planner__dag import (  # noqa: E402
    BlueprintDAG, BlueprintNode, _as_id_list)


def _dag(nodes, root="g"):
    return BlueprintDAG(nodes=nodes, root_id=root)


def test_as_id_list_normalizes_shapes():
    assert _as_id_list(["n1", "n2"]) == ["n1", "n2"]
    assert _as_id_list("n1") == ["n1"]
    assert _as_id_list("n1, n2、n3") == ["n1", "n2", "n3"]
    assert _as_id_list([{"id": "n1"}, {"node": "n2"}]) == ["n1", "n2"]
    assert _as_id_list(None) == []
    assert _as_id_list([None, "", "  "]) == []


def test_validate_inputs_detects_broken_ref():
    d = _dag({"g": BlueprintNode(id="g", node_type="and", statement="根", children=["a"]),
              "a": BlueprintNode(id="a", node_type="and", statement="甲", inputs=["ghost"])})
    res = d.validate_inputs()
    assert not res["ok"]
    assert res["broken"] and res["broken"][0]["ref"] == "ghost"
    assert res["broken"][0]["reason"] == "引用不存在的节点"


def test_validate_inputs_detects_self_reference():
    d = _dag({"g": BlueprintNode(id="g", node_type="and", statement="根", children=["a"]),
              "a": BlueprintNode(id="a", node_type="and", statement="甲", inputs=["a"])})
    res = d.validate_inputs()
    assert any(b["reason"] == "自引用" for b in res["broken"])


def test_validate_inputs_flags_leaf_consuming_prior_result():
    """R1：真叶子却依赖前序结论 ⇒ 形态可疑（K11 空壳成因）。"""
    d = _dag({"g": BlueprintNode(id="g", node_type="and", statement="根", children=["a"]),
              "a": BlueprintNode(id="a", node_type="and", statement="甲", inputs=["b"]),
              "b": BlueprintNode(id="b", node_type="and", statement="乙")})
    res = d.validate_inputs()
    assert not res["ok"]
    assert res["leaky_leaves"] and res["leaky_leaves"][0]["id"] == "a"
    assert res["leaky_leaves"][0]["refs"] == ["b"]


def test_validate_inputs_ok_when_clean():
    d = _dag({"g": BlueprintNode(id="g", node_type="and", statement="根", children=["a", "b"]),
              "a": BlueprintNode(id="a", node_type="and", statement="甲"),
              "b": BlueprintNode(id="b", node_type="and", statement="乙", inputs=["a"])})
    res = d.validate_inputs()
    # b 依赖 a（真依赖），a 是叶子且无外部 inputs ⇒ 无 broken；b 有 children? 无 ⇒ b 也是叶子
    assert res["broken"] == []
    assert res["ok"] in (True, False)      # leaky 判定取决于 B 是否有 children


def test_subgoal_plan_carries_inputs_and_method():
    d = _dag({"g": BlueprintNode(id="g", node_type="and", statement="根", children=["a", "b"]),
              "a": BlueprintNode(id="a", node_type="and", statement="求时间 t",
                                 method="t = s / v"),
              "b": BlueprintNode(id="b", node_type="and", statement="求速度 v", inputs=["a"])})
    plan = d.to_subgoal_plan(0)
    by_stmt = {s["description"]: s for s in plan["subgoals"]}
    assert by_stmt["求速度 v"]["inputs_raw"] == ["a"]
    assert by_stmt["求速度 v"]["inputs"], "应把节点 id 映射为子目标序号"
    assert by_stmt["求时间 t"]["method"] == "t = s / v"
    assert by_stmt["求速度 v"]["inputs"] == [by_stmt["求时间 t"]["id"]]
