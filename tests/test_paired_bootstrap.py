# -*- coding: utf-8 -*-
"""配对显著性 / 噪声带校准（tools/paired_bootstrap.py）单测 —— 2026-10-22。

覆盖：逐题配对计数、净胜题数、任务级 bootstrap 的区间方向、McNemar 边界、
δ 校准的「翻转率」口径（不用分位数，避免稀疏分布得出 δ=0）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.paired_bootstrap import (  # noqa: E402
    calibrate_delta, compare, load_verdicts, mcnemar_exact, paired_bootstrap)


def _mk(n, correct_ids):
    return {"t%02d" % i: (i in correct_ids) for i in range(n)}


# ------------------------------------------------------------ 配对比较
def test_compare_counts_and_net():
    a = _mk(10, {0, 1, 2, 3})           # 4 对
    b = _mk(10, {0, 1, 4, 5})           # 4 对，但换了 2 题
    r = compare(a, b)
    assert r["n_tasks"] == 10
    assert r["correct_a"] == r["correct_b"] == 4
    assert r["a_only"] == ["t02", "t03"]
    assert r["b_only"] == ["t04", "t05"]
    assert r["net"] == 0               # 净胜 0，尽管有 4 题变了
    assert r["delta_pp"] == 0.0


def test_compare_counts_both_and_neither():
    a = _mk(5, {0})
    b = _mk(5, {0})
    r = compare(a, b)
    assert r["n_both"] == 1 and r["n_neither"] == 4


def test_compare_ignores_unmatched_tasks():
    a = _mk(5, {0})
    b = {"t00": True, "zzz": True}
    r = compare(a, b)
    assert r["n_tasks"] == 1


# ------------------------------------------------------------ bootstrap
def test_bootstrap_zero_when_identical():
    a = _mk(20, {1, 2, 3})
    res = paired_bootstrap(a, dict(a), n_boot=200, seed=1)
    assert res["ci_low"] == res["ci_high"] == 0.0
    assert res["significant"] is False


def test_bootstrap_positive_when_b_strictly_better():
    a = _mk(10, set())
    b = _mk(10, set(range(10)))
    res = paired_bootstrap(a, b, n_boot=500, seed=0)
    assert res["mean"] == 100.0
    assert res["ci_low"] > 0 and res["significant"] is True


def test_bootstrap_empty_overlap():
    res = paired_bootstrap({"x": True}, {"y": True}, n_boot=10)
    assert res["n_tasks"] == 0


# ------------------------------------------------------------ McNemar
def test_mcnemar_no_discordant_pairs():
    assert mcnemar_exact([], []) == 1.0


def test_mcnemar_extreme_split_is_significant():
    # 10:0 的不一致 ⇒ 双侧 p = 2 * (1/2)^10 ≈ 0.00195
    p = mcnemar_exact(["a"] * 10, [])
    assert p < 0.01


def test_mcnemar_balanced_is_one():
    assert mcnemar_exact(["a"], ["b"]) == 1.0


# ------------------------------------------------------------ δ 校准
def test_delta_uses_flip_rate_not_percentile():
    """★ 关键口径：逐题差异非 0 即 100pp，分位数会落在 0 上；
    δ 必须用翻转率（flips/n），否则稀疏分布会得出 δ=0。"""
    x = _mk(100, set())
    y = dict(x)
    y["t00"] = True
    y["t01"] = True
    res = calibrate_delta(x, y)
    assert res["n_flipped_tasks"] == 2
    assert res["flip_pp"] == 2.0
    assert res["delta_pp"] == 2.0


def test_delta_never_below_resolution():
    x = _mk(10, set())
    res = calibrate_delta(x, dict(x))
    assert res["resolution_pp"] == 10.0
    assert res["delta_pp"] == 10.0     # 10 题集的最小分辨率就是 10pp


def test_delta_empty_overlap_warns():
    res = calibrate_delta({"a": True}, {"b": True})
    assert res["n_tasks"] == 0 and "warning" in res


# ------------------------------------------------------------ 读取
def test_load_verdicts_skips_rows_without_correct(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text(
        '{"id":"a","correct":true}\n'
        '{"id":"b"}\n'                  # 没有 correct ⇒ 未跑，不算答错
        '{"id":"c","correct":false}\n'
        'not json\n',
        encoding="utf-8")
    d = load_verdicts(str(p))
    assert d == {"a": True, "c": False}
