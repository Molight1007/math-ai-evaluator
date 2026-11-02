# -*- coding: utf-8 -*-
"""节点语义槽位拆分：目标 / 未闭合前提 单列（2026-11-02）。

背景：节点原有 `statement` 一个槽，同时承载
    ① 计划期的「要证什么」（目标，允许错）
    ② 求解期的「我猜结果是这个」（猜想）
    ③ 入库期的「这已是事实」（结论，必须已验证）
三者共槽 ⇒ 下游无法区分权威性 ⇒「先证明、再声明」结构上无法执行。

本测试守的是**拆分本身**，不是数学正确性：
  · 模型显式声明的目标要被读到；
  · 没声明时**不得**回落 statement 再假装拆分完成（兜底≠修复）；
  · 来源标记必须一路传到下游（否则下游又把 derived 当 declared 用）；
  · 序列化往返不许丢（这个项目在丢字段上踩过多次）。
"""
from __future__ import annotations

import pytest

from agent.blueprint_planner import parse_blueprint
from agent.blueprint_planner__dag import BlueprintDAG, BlueprintNode


def _raw(nodes, root="n1"):
    return {"root_id": root, "merge_strategy": "合并各分支结论", "nodes": nodes}


# ------------------------------------------------------- S1 显式声明被读到
def test_goal_declared_is_parsed():
    dag = parse_blueprint(_raw([
        {"id": "n1", "type": "and", "statement": "求 a_n 的通项",
         "goal": "证明对所有正整数 n 有 a_n = n + 1",
         "children": ["n2"]},
        {"id": "n2", "type": "and", "statement": "计算前几项",
         "goal": "确定 a_1, a_2, a_3", "children": []},
    ]))
    assert dag is not None
    assert dag.nodes["n1"].goal == "证明对所有正整数 n 有 a_n = n + 1"
    assert dag.nodes["n2"].goal == "确定 a_1, a_2, a_3"


def test_open_goals_is_parsed():
    dag = parse_blueprint(_raw([
        {"id": "n1", "type": "and", "statement": "合并结论",
         "goal": "得出通项",
         "open_goals": ["前 n 项和有闭式", "差分可求和"],
         "children": []},
    ]))
    assert dag.nodes["n1"].open_goals == ["前 n 项和有闭式", "差分可求和"]


# --------------------------------------------------- S2 未声明时不得回落
def test_missing_goal_is_empty_not_statement():
    """★ 未声明目标时 `goal` 必须为空 —— 回落会抹掉「没声明」这个事实。"""
    dag = parse_blueprint(_raw([
        {"id": "n1", "type": "and", "statement": "a_n = n+1", "children": []},
    ]))
    assert dag.nodes["n1"].goal == ""
    assert dag.nodes["n1"].statement == "a_n = n+1"


def test_goal_of_reports_source():
    declared = BlueprintNode(id="x", node_type="and",
                             statement="求通项", goal="证明 a_n = n+1")
    assert declared.goal_of() == ("证明 a_n = n+1", "declared")

    derived = BlueprintNode(id="x", node_type="and", statement="求通项")
    text, src = derived.goal_of()
    assert text == "求通项"
    assert src == "derived"      # 调用方必须看见这个标记


# ------------------------------------------------------- S3 序列化往返不丢
def test_roundtrip_preserves_goal_and_open_goals():
    dag = parse_blueprint(_raw([
        {"id": "n1", "type": "and", "statement": "合并",
         "goal": "证明 P", "open_goals": ["Q 成立", "R 成立"],
         "children": []},
    ]))
    back = BlueprintDAG.from_dict(dag.to_dict())
    assert back.nodes["n1"].goal == "证明 P"
    assert back.nodes["n1"].open_goals == ["Q 成立", "R 成立"]


def test_from_dict_old_payload_has_empty_goal():
    """旧序列化没有这两个键 ⇒ 空值，不抛错、不回落。"""
    dag = BlueprintDAG.from_dict({
        "root_id": "n1",
        "nodes": [{"id": "n1", "type": "and", "statement": "求值", "children": []}],
    })
    assert dag.nodes["n1"].goal == ""
    assert dag.nodes["n1"].open_goals == []


# ------------------------------------------------- S4 下传带来源标记
def test_subgoal_plan_carries_goal_and_source():
    dag = parse_blueprint(_raw([
        {"id": "n1", "type": "and", "statement": "合并各分支",
         "goal": "得出最终通项", "open_goals": ["分支一成立"],
         "children": []},
    ]))
    plan = dag.to_subgoal_plan()
    sg = plan["subgoals"][0]
    assert sg["goal"] == "得出最终通项"
    assert sg["goal_source"] == "declared"
    assert sg["open_goals"] == ["分支一成立"]


def test_subgoal_plan_marks_derived():
    dag = parse_blueprint(_raw([
        {"id": "n1", "type": "and", "statement": "求 a_n 的通项", "children": []},
    ]))
    sg = dag.to_subgoal_plan()["subgoals"][0]
    assert sg["goal"] == "求 a_n 的通项"
    assert sg["goal_source"] == "derived"


# --------------------------------------------- S5 归一化容错（模型输出不规范）
@pytest.mark.parametrize("raw_goal,want", [
    (" 证明 P ", "证明 P"),
    ({"statement": "证明 P"}, "证明 P"),
    ({"claim": "证明 Q"}, "证明 Q"),
    ("none", ""),
    (None, ""),
])
def test_goal_normalization(raw_goal, want):
    dag = parse_blueprint(_raw([
        {"id": "n1", "type": "and", "statement": "s", "goal": raw_goal,
         "children": []},
    ]))
    assert dag.nodes["n1"].goal == want


def test_open_goals_keeps_sentences_with_commas():
    """一条前提就是一个句子，内部逗号不能被切碎（否则无法整体闭合）。"""
    dag = parse_blueprint(_raw([
        {"id": "n1", "type": "and", "statement": "s", "goal": "g",
         "open_goals": ["设 n 为奇数，且 n > 3，则 a_n 为整数"],
         "children": []},
    ]))
    assert dag.nodes["n1"].open_goals == ["设 n 为奇数，且 n > 3，则 a_n 为整数"]


def test_open_goals_dedup_and_drop_empty():
    dag = parse_blueprint(_raw([
        {"id": "n1", "type": "and", "statement": "s", "goal": "g",
         "open_goals": ["P", "P", "  ", None, "Q"],
         "children": []},
    ]))
    assert dag.nodes["n1"].open_goals == ["P", "Q"]
