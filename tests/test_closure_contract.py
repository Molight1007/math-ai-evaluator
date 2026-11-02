# -*- coding: utf-8 -*-
"""闭合判定与「已闭合集合」投影（2026-11-02，契约层）。

这套判定原来是回放床脚本里的私有实现，现在下沉为契约 —— 因为它同时被
「离线回放」和「主流程下游注入」使用。两处各写一份，口径必然漂移，
而口径一漂，所有历史对比作废。

测试重点不在数学，而在**口径不被悄悄改动**：
  · 四级闭合的分界（尤其 UNMAPPED 不等于 OPEN）
  · 只有 HARD_CLOSED 能进投影
  · 失败词表沿用历史口径（不得单方面收紧）
"""
from __future__ import annotations

import pytest

from contracts.closure import (
    CLOSURE_HARD,
    CLOSURE_OPEN,
    CLOSURE_SOFT,
    CLOSURE_UNMAPPED,
    closure_of,
    is_hard_closed,
    project_closed,
)


# ----------------------------------------------------------- C1 四级闭合分界
def test_hard_closed_requires_tool_ran():
    level, why = closure_of({"tool_ran": True, "tool_verdict": "ok"})
    assert level == CLOSURE_HARD
    assert "tool_ran" in why


@pytest.mark.parametrize("verdict", [
    "fail", "FAILED", "error", "timeout", "unknown", "unsolved", "失败", "算错",
])
def test_hard_closed_rejects_failed_verdict(verdict):
    """工具跑过但判失败 ⇒ 不是硬闭合（否则「跑过」就等于「通过」）。"""
    level, _ = closure_of({"tool_ran": True, "tool_verdict": verdict})
    assert level != CLOSURE_HARD


def test_tool_ran_false_is_not_hard():
    level, _ = closure_of({"tool_ran": False, "objective_verdict": "correct",
                           "has_derivation": True})
    assert level == CLOSURE_SOFT


def test_soft_closed_needs_correct_and_derivation():
    assert closure_of({"objective_verdict": "correct",
                       "has_derivation": True})[0] == CLOSURE_SOFT
    # 判 correct 但没有推导正文 ⇒ 不算闭合（模型可能只是"说对了"）
    assert closure_of({"objective_verdict": "correct",
                       "has_derivation": False})[0] == CLOSURE_OPEN


@pytest.mark.parametrize("item", [
    {"objective_verdict": "incorrect"},
    {"objective_verdict": None},
    {"tool_ran": False},
])
def test_open(item):
    assert closure_of(item)[0] == CLOSURE_OPEN


@pytest.mark.parametrize("item", [None, {}])
def test_unmapped_is_distinct_from_open(item):
    """★ 没产物 ≠ 未闭合。混在一起会把闭合率算错（历史踩过：0% 与 90% 平均成 34%）。"""
    level, why = closure_of(item)
    assert level == CLOSURE_UNMAPPED
    assert level != CLOSURE_OPEN
    assert why == "no_subgoal"


def test_sorry_proof_is_not_hard_closed():
    """★ 带 sorry 的证明**编译能通过**，但它不是证明。

    若不识别，一个根本没证的骨架会被当成「已闭合」流进下游 ——
    这正是「先证明、再声明」要防的那件事。
    """
    for verdict in ("ok (with sorry)", "declaration uses 'sorry'",
                    "unsolved goals ⊢ False", "admit"):
        level, _ = closure_of({"tool_ran": True, "tool_verdict": verdict})
        assert level != CLOSURE_HARD, verdict


# ------------------------------------------------------------- C2 硬闭合判据
def test_is_hard_closed():
    assert is_hard_closed({"tool_ran": True, "tool_verdict": "passed"})
    assert not is_hard_closed({"tool_ran": True, "tool_verdict": "fail"})
    assert not is_hard_closed({"objective_verdict": "correct"})


# --------------------------------------------------------------- C3 投影语义
def test_project_closed_keeps_only_hard():
    items = [
        {"id": 1, "tool_ran": True, "tool_verdict": "ok"},
        {"id": 2, "tool_ran": False, "objective_verdict": "correct",
         "has_derivation": True},          # 软闭合，不得进
        {"id": 3, "objective_verdict": "incorrect"},
        {"id": 4, "tool_ran": True, "tool_verdict": "error"},
    ]
    kept = project_closed(items)
    assert [x["id"] for x in kept] == [1]


def test_project_closed_returns_new_list_and_preserves_order():
    items = [
        {"id": 1, "tool_ran": True, "tool_verdict": "ok"},
        {"id": 2, "tool_ran": True, "tool_verdict": "ok"},
    ]
    kept = project_closed(items)
    assert kept is not items
    assert [x["id"] for x in kept] == [1, 2]


def test_project_closed_with_key():
    """包装结构：判定用的是内层，保留的是外层。"""
    items = [
        {"node": "n1", "sg": {"tool_ran": True, "tool_verdict": "ok"}},
        {"node": "n2", "sg": {"objective_verdict": "incorrect"}},
    ]
    kept = project_closed(items, key="sg")
    assert [x["node"] for x in kept] == ["n1"]


def test_project_closed_empty_and_none():
    assert project_closed([]) == []
    assert project_closed(None) == []
