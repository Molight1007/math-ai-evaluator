# -*- coding: utf-8 -*-
"""闸门预演的判定逻辑（2026-11-02，零 LLM）。

预演要回答的是一句很具体的话：「只让已达标的结论进下游，有多少题走不完」。
本测试守的是**模拟语义**，不是数学：

  · 上游未达标 ⇒ 本条卡住，且**传递**给下游
  · 三档阈值的分界（工具级 / 软闭合 / 放宽）
  · 同一子目标多行时取最优（乐观口径）
  · depends_on 为空 ⇒ 不受上游影响
"""
from __future__ import annotations

import pytest

from replay_gate_sim import (
    BLOCKED,
    best_closure,
    group_by_id,
    simulate,
)
from contracts.closure import (
    CLOSURE_HARD,
    CLOSURE_OPEN,
    CLOSURE_SOFT,
    CLOSURE_UNMAPPED,
)


def hard(i, deps=()):
    return {"id": i, "depends_on": list(deps), "tool_ran": True,
            "tool_verdict": "ok"}


def soft(i, deps=()):
    return {"id": i, "depends_on": list(deps), "tool_ran": False,
            "objective_verdict": "correct", "has_derivation": True}


def opened(i, deps=(), ov="undecided", drv=True):
    return {"id": i, "depends_on": list(deps), "tool_ran": False,
            "objective_verdict": ov, "has_derivation": drv}


# --------------------------------------------------------- G1 无上游依赖
def test_chain_without_deps_never_blocks():
    """没有任何依赖边 ⇒ 不受闸门影响（上游为空，all() 恒真）。"""
    rows = [opened(1), opened(2), opened(3)]
    for lv in ("L0", "L1", "L2"):
        r = simulate(rows, lv)
        assert r["reached_tail"] is True
        assert r["n_blocked"] == 0


# --------------------------------------------------------- G2 三档分界
def test_soft_upstream_blocks_L0_but_passes_L1():
    rows = [soft(1), hard(2, deps=[1])]
    assert simulate(rows, "L0")["status"][2] == BLOCKED
    assert simulate(rows, "L1")["status"][2] == CLOSURE_HARD
    assert simulate(rows, "L2")["status"][2] == CLOSURE_HARD


def test_hard_upstream_passes_all_levels():
    rows = [hard(1), opened(2, deps=[1])]
    for lv in ("L0", "L1", "L2"):
        assert simulate(rows, lv)["status"][2] != BLOCKED


def test_open_with_derivation_passes_only_L2():
    rows = [opened(1), hard(2, deps=[1])]
    assert simulate(rows, "L1")["status"][2] == BLOCKED
    assert simulate(rows, "L2")["status"][2] == CLOSURE_HARD


def test_open_incorrect_never_passes_even_L2():
    """明确判错的结论，最宽松档也不放行。"""
    rows = [opened(1, ov="incorrect"), hard(2, deps=[1])]
    assert simulate(rows, "L2")["status"][2] == BLOCKED


def test_open_without_derivation_never_passes_L2():
    rows = [opened(1, drv=False), hard(2, deps=[1])]
    assert simulate(rows, "L2")["status"][2] == BLOCKED


# --------------------------------------------------------------- G3 传递性
def test_block_propagates_downstream():
    rows = [opened(1), soft(2, deps=[1]), hard(3, deps=[2])]
    r = simulate(rows, "L0")
    assert r["status"][1] == CLOSURE_OPEN       # 自己执行了（无依赖）
    assert r["status"][2] == BLOCKED            # 上游 1 未达标
    assert r["status"][3] == BLOCKED            # 传递
    assert r["n_blocked"] == 2
    assert r["first_block"] == 2
    assert r["reached_tail"] is False


def test_tail_reached_when_chain_intact():
    rows = [hard(1), soft(2, deps=[1])]
    assert simulate(rows, "L1")["reached_tail"] is True
    # L0：收尾仍能执行（上游是硬闭合），但它自己只到软闭合 ⇒ 不达标
    r0 = simulate(rows, "L0")
    assert r0["reached_tail"] is True
    assert r0["tail_closure"] == CLOSURE_SOFT
    assert r0["tail_passes"] is False
    assert simulate(rows, "L1")["tail_passes"] is True


def test_reached_tail_is_not_passing():
    """★「走完」≠「达标」：跑完了但没证出来，不能算成功。

    L2 是刻意放宽的档（未判错 + 有推导即接受），所以只在 L0/L1 上断言。
    """
    rows = [opened(1), opened(2)]
    for lv in ("L0", "L1"):
        r = simulate(rows, lv)
        assert r["reached_tail"] is True
        assert r["tail_passes"] is False
    assert simulate(rows, "L2")["tail_passes"] is True


def test_partial_deps_block():
    """多个上游只要有一个未达标就卡（AND 语义）。"""
    rows = [hard(1), opened(2), hard(3, deps=[1, 2])]
    assert simulate(rows, "L0")["status"][3] == BLOCKED
    assert simulate(rows, "L1")["status"][3] == BLOCKED
    assert simulate(rows, "L2")["status"][3] == CLOSURE_HARD


# ------------------------------------------------------- G4 多行取最优
def test_best_closure_prefers_hard():
    rows = [{"id": 1, "objective_verdict": "undecided"},
            {"id": 1, "tool_ran": True, "tool_verdict": "ok"},
            {"id": 1, "objective_verdict": "correct", "has_derivation": True}]
    c, _ = best_closure(rows)
    assert c == CLOSURE_HARD


def test_best_closure_empty():
    assert best_closure([])[0] == CLOSURE_UNMAPPED


def test_multi_round_takes_best():
    """同一子目标跑过多轮：某一轮证成 ⇒ 应当算证成。"""
    rows = [
        {"id": 1, "depends_on": [], "objective_verdict": "incorrect"},
        {"id": 1, "depends_on": [], "tool_ran": True, "tool_verdict": "ok"},
        hard(2, deps=[1]),
    ]
    assert simulate(rows, "L0")["status"][2] == CLOSURE_HARD


# ------------------------------------------------------------- G5 边界
def test_empty_rows():
    r = simulate([], "L0")
    assert r["n_total"] == 0
    assert r["reached_tail"] is False


def test_self_dependency_ignored():
    rows = [hard(1, deps=[1])]
    assert simulate(rows, "L0")["status"][1] == CLOSURE_HARD


def test_bad_id_skipped():
    rows = [{"id": None}, {"id": "x"}, hard(1)]
    assert simulate(rows, "L0")["n_total"] == 1


def test_group_by_id():
    rows = [{"id": 1}, {"id": 1}, {"id": 2}]
    g = group_by_id(rows)
    assert sorted(g) == [1, 2]
    assert len(g[1]) == 2


def test_deps_as_strings():
    """历史产物里 depends_on 可能是字符串编号，必须能归一。"""
    rows = [hard(1), hard(2, deps=["1"])]
    assert simulate(rows, "L0")["status"][2] == CLOSURE_HARD
