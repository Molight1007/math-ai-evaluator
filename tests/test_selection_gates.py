# -*- coding: utf-8 -*-
"""L4 四道门（floor → cost → guard → argmax）守卫测试（2026-10-27）。

要钉住的四条
============
1. **δ 未标定 ⇒ 拒绝一切候选**。这是本轮最重要的一条：没有噪声带时，
   「涨 3 分」分不清是改进还是抖动（温度 0.3，单题 ~1087s），放行就是给后续轮次喂噪声。
2. **门是短路执行的**：第一道不过就不该再看后面三道（否则会在明显更烂的候选上讨论成本）。
3. **成本规则的两种情形算对**：ΔS>δ 用 β0+β1·ΔS 上限；ΔS≤δ 用 w_s·ΔS−w_c·ΔC+w_n·ν。
   `w_s=0` 的语义是"带内的分数一文不值"，所以带内涨分但涨成本 = 拒。
4. **argmax 是字典序不是加权和**：分数先说话，成本只做同分时的次序。
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from contracts.selection import (  # noqa: E402
    SelectionError, calibration_usable, decide, load_calibration,
    missing_fields, validate_calibration,
)

MEASURED = {"schema": "gates/1", "s_star": 34.0, "delta_pp": 3.0,
            "beta0_pct": 10.0, "beta1_pct_per_pp": 44.5,
            "w_s": 0.0, "w_c": 1.0, "w_n": 0.0, "source": "measured"}
BORROWED = dict(MEASURED, source="rrsi-borrowed")


def _gates(out, cid):
    return [(r["gate"], r["passed"]) for r in out["rows"] if r["id"] == cid]


# ---------------------------------------------------------------- 1. 未标定 ⇒ 全拒
def test_01_missing_fields_reject_everything():
    cal = {"schema": "gates/1", "s_star": None, "delta_pp": None,
           "beta0_pct": 10.0, "beta1_pct_per_pp": 44.5,
           "w_s": 0.0, "w_c": 1.0, "w_n": 0.0, "source": "unmeasured"}
    assert missing_fields(cal) == ["s_star", "delta_pp"]
    out = decide([{"id": "c1", "delta_s_pp": 9.0, "delta_c_pct": -50.0}], cal)
    assert out["usable"] is False
    assert out["selected"] is None
    assert "未标定" in out["reason"]
    # 每个候选只留一条「拒绝」记录，不假装还能过后面几道
    assert out["rows"] == [{"id": "c1", "gate": "floor", "passed": False,
                            "reason": "拒绝：" + out["reason"]}]


def test_02_borrowed_is_not_measured():
    ok, why = calibration_usable(BORROWED, require_measured=True)
    assert not ok and "未实测" in why
    out = decide([{"id": "c1", "delta_s_pp": 9.0, "delta_c_pct": -50.0}], BORROWED)
    assert out["selected"] is None


def test_03_borrowed_allowed_explicitly():
    out = decide([{"id": "c1", "delta_s_pp": 9.0, "delta_c_pct": -50.0}], BORROWED,
                 require_measured=False)
    assert out["usable"] is True
    assert out["selected"] == "c1", out["rows"]


def test_04_bad_calibration_rejected_loudly():
    with pytest.raises(SelectionError):
        validate_calibration({"schema": "gates/0"})
    with pytest.raises(SelectionError):
        validate_calibration(dict(MEASURED, delta_pp=0))
    with pytest.raises(SelectionError):
        validate_calibration(dict(MEASURED, delta_pp="3"))


# ---------------------------------------------------------------- 2/3. 两道门
def test_10_floor_rejects_drop_beyond_noise():
    out = decide([{"id": "c1", "delta_s_pp": -5.0, "delta_c_pct": -30.0}], MEASURED)
    assert out["selected"] is None
    assert _gates(out, "c1") == [("floor", False)]


def test_11_floor_passes_then_cost_runs():
    out = decide([{"id": "c1", "delta_s_pp": 5.0, "delta_c_pct": 300.0}], MEASURED)
    assert _gates(out, "c1") == [("floor", True), ("cost", False)]
    assert out["selected"] is None


def test_12_cost_cap_uses_beta0_beta1():
    """ΔS=5pp > δ=3 ⇒ 上限 = 10 + 44.5×5 = 232.5%。"""
    ok = decide([{"id": "c1", "delta_s_pp": 5.0, "delta_c_pct": 232.0}], MEASURED)
    assert ok["selected"] == "c1"
    bad = decide([{"id": "c1", "delta_s_pp": 5.0, "delta_c_pct": 233.0}], MEASURED)
    assert bad["selected"] is None


def test_13_in_band_gain_with_cost_increase_rejected():
    """带内（ΔS=1pp ≤ δ）涨分但涨 20% 成本 ⇒ w_s=0 ⇒ 净收益 −20 ⇒ 拒。"""
    out = decide([{"id": "c1", "delta_s_pp": 1.0, "delta_c_pct": 20.0}], MEASURED)
    assert out["selected"] is None
    assert _gates(out, "c1")[-1] == ("cost", False)


def test_14_in_band_cost_saving_passes():
    """带内没真涨分，但省了 5% 成本 ⇒ 净收益 +5 ⇒ 过（RRSI：带内的分数一文不值）。"""
    out = decide([{"id": "c1", "delta_s_pp": 0.5, "delta_c_pct": -5.0}], MEASURED)
    assert out["selected"] == "c1", out["rows"]


def test_15_s_hat_only_candidate_works():
    """只给绝对分数的候选也要能用（s_hat 与 S* 比）。"""
    out = decide([{"id": "c1", "s_hat": 33.0, "delta_c_pct": -1.0}], MEASURED)
    assert out["selected"] == "c1", out["rows"]


# ---------------------------------------------------------------- 4. 守卫与排序
def test_20_guard_callback_can_reject():
    out = decide([{"id": "c1", "delta_s_pp": 9.0, "delta_c_pct": -50.0}], MEASURED,
                 guard=lambda c: (False, "单领域提升，跨域无变化"))
    assert out["selected"] is None
    assert _gates(out, "c1")[-1] == ("guard", False)


def test_21_guard_exception_is_not_pass():
    """守卫自己炸了不能当成"通过"（历史上"失败被包装成成功"最危险）。"""
    def boom(_c):
        raise RuntimeError("x")
    out = decide([{"id": "c1", "delta_s_pp": 9.0, "delta_c_pct": -50.0}], MEASURED, guard=boom)
    assert out["selected"] is None


def test_22_argmax_is_lexicographic_not_weighted():
    cands = [{"id": "cheap", "delta_s_pp": 4.0, "delta_c_pct": -80.0},
             {"id": "better", "delta_s_pp": 6.0, "delta_c_pct": 50.0}]
    out = decide(cands, MEASURED)
    assert out["selected"] == "better", "加权和会让成本优势盖掉真实提升"
    assert out["ranking"][0] == "better"


def test_23_tie_broken_by_cost_then_novelty():
    cands = [{"id": "a", "delta_s_pp": 5.0, "delta_c_pct": 20.0},
             {"id": "b", "delta_s_pp": 5.0, "delta_c_pct": 10.0},
             {"id": "c", "delta_s_pp": 5.0, "delta_c_pct": 10.0, "novelty": 1.0}]
    out = decide(cands, MEASURED)
    assert out["ranking"][:2] == ["c", "b"]


def test_24_empty_and_all_failed():
    assert decide([], MEASURED)["selected"] is None
    out = decide([{"id": "x", "delta_s_pp": -99.0}], MEASURED)
    assert out["selected"] is None and out["notes"]


# ---------------------------------------------------------------- 文件
def test_30_load_from_file(tmp_path):
    p = tmp_path / "gates.json"
    import json
    p.write_text(json.dumps(MEASURED), encoding="utf-8")
    cal = load_calibration(str(p))
    assert calibration_usable(cal)[0] is True
