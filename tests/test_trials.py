# -*- coding: utf-8 -*-
"""评测聚合口径测试（k 次 / 缺失记 0 / 基础设施失败单列）。

为什么值得单独测
================
这三个口径直接决定"涨了多少分"这个数。任何一个写错，账本里记的 Δ 全是错的
——而账本是自动化闭环的燃料（错燃料比没燃料更糟）。
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from contracts.trials import aggregate, delta_pp  # noqa: E402


def test_01_missing_trial_counts_as_zero_without_shrinking_denominator():
    """q2 只跑了 1 次且对：按 k=2 算 0.5，不是"只算跑过的那次"=1.0。"""
    out = aggregate({"q1": [1, 0], "q2": [1]}, k=2)
    assert out["n_missing"] == 1
    assert out["score"] == pytest.approx((0.5 + 0.5) / 2)
    assert out["tasks"]["q2"]["present"] == 1


def test_02_infra_failure_excluded_from_denominator():
    out = aggregate({"q1": [1, 1], "q2": [{"r": 0, "infra": True}, 0]}, k=2)
    assert out["n_infra"] == 1 and out["n_scored"] == 1
    assert out["score"] == pytest.approx(1.0), "基础设施失败不该把分拉低"
    assert out["infra_tasks"] == ["q2"]


def test_03_pass_at_k_vs_pass_hat_k():
    out = aggregate({"q1": [1, 0], "q2": [1, 1], "q3": [0, 0]}, k=2)
    assert out["pass_at_k"] == pytest.approx(2 / 3)
    assert out["pass_hat_k"] == pytest.approx(1 / 3)
    assert out["pass_at_k"] > out["pass_hat_k"]


def test_04_k_is_denominator_not_max():
    """k=3 但只跑了 2 次全对 ⇒ 2/3，而不是 2/2。"""
    out = aggregate({"q1": [1, 1]}, k=3)
    assert out["score"] == pytest.approx(2 / 3)


def test_05_delta_pp_guards_incomparables():
    a = aggregate({"q1": [1, 0]}, k=2)
    b = aggregate({"q1": [1, 1]}, k=2)
    assert delta_pp(a, b) == pytest.approx(50.0)
    with pytest.raises(ValueError):
        delta_pp(a, aggregate({"q1": [1]}, k=1))
    with pytest.raises(ValueError):
        delta_pp(a, aggregate({"q1": [1, 1], "q2": [1, 1]}, k=2))


def test_06_empty_is_zero_not_crash():
    out = aggregate({}, k=2)
    assert out["score"] == 0.0 and out["n_scored"] == 0
    with pytest.raises(ValueError):
        aggregate({"q1": [1]}, k=0)
