# -*- coding: utf-8 -*-
"""闭环集成测试：参数层 → 提案 → critic → 四道门 → 账本 → 回灌。

这条链是本轮的重点：**每一段单独对，不代表接起来对**（项目踩过"四件套齐但链没通"）。
所以这里不加任何桩替身，直接调真实模块，只用临时目录隔离账本与标定。

两个场景各自钉一个不变式
========================
1. **未标定**：候选过不了第一道门 ⇒ 记 UNMEASURED ⇒ 回灌后该单元是 `untested`
   （**不是 `effective`，也不能悄悄变回 `untried`**）；
2. **已标定**：候选过门 ⇒ 记 ACCEPTED ⇒ 回灌后才是 `effective`。
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tools.backfill as bf  # noqa: E402
import tools.edit_ledger as led  # noqa: E402
import tools.propose as prop  # noqa: E402
from contracts.params_io import load as load_params  # noqa: E402
from contracts.selection import decide  # noqa: E402

PARAMS = os.path.join(REPO, "params.json")

UNCAL = {"schema": "gates/1", "s_star": None, "delta_pp": None,
         "beta0_pct": 10.0, "beta1_pct_per_pp": 44.5,
         "w_s": 0.0, "w_c": 1.0, "w_n": 0.0, "source": "unmeasured"}
CAL = {"schema": "gates/1", "s_star": 34.0, "delta_pp": 2.5,
       "beta0_pct": 10.0, "beta1_pct_per_pp": 44.5,
       "w_s": 0.0, "w_c": 1.0, "w_n": 0.0, "source": "measured"}


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setattr(led, "_DIR", str(d))
    monkeypatch.setattr(led, "PATH", str(d / "ledger.jsonl"))
    return d


def _effect(doc):
    return bf.build(list(doc["a"]))["units"]


def _row(key, **kw):
    base = {"stage": "2.7_subgoal_main", "dim": "flow", "eu_id": "flow.%s" % key,
            "hypothesis": "集成测试", "diff": "x -> y", "accepted": False,
            "reject_reason": "", "delta_metric": None, "delta_cost": None,
            "bundle": 1}
    base.update(kw)
    return led.normalize(base)


# ---------------------------------------------------------------- 场景 1
def test_10_uncalibrated_chain_never_becomes_effective(ledger):
    doc = load_params(PARAMS)
    eff0 = _effect(doc)
    assert all(u["status"] == "untried" for u in eff0.values()), "空账本 ⇒ 全 untried"

    # ① L3 提案（确定性桩，不调 LLM）
    res = prop.propose(doc, eff0, llm=None)
    assert res["ok"], res["rounds"]
    edits = res["candidate"]["edits"]
    assert edits and all(e["key"] in doc["a"] for e in edits), "提案只能碰 A 段"

    # ② L4 四道门：δ 未标定 ⇒ 拒
    cand = {"id": "cand-1", "delta_s_pp": 5.0, "delta_c_pct": -10.0}
    verdict = decide([cand], UNCAL)
    assert verdict["selected"] is None and verdict["usable"] is False

    # ③ L5 记账：没测过就记 UNMEASURED，且不许标 accepted
    key = edits[0]["key"]
    errs, _ = led.validate(_row(key, accepted=True))
    assert any("accepted" in e for e in errs), "未测量却标 accepted 必须被拒"
    led.append(_row(key))

    # ④ L5 回灌：状态是 untested（不是 effective，也不是 untried）
    eff1 = bf.build(list(doc["a"]))["units"]
    assert eff1[key]["status"] == "untested"
    assert eff1[key]["n_unmeasured"] == 1 and eff1[key]["n_measured"] == 0


# ---------------------------------------------------------------- 场景 2
def test_20_calibrated_chain_reaches_effective(ledger):
    doc = load_params(PARAMS)
    key = "accept_confidence"
    cand = {"id": "cand-1", "delta_s_pp": 5.0, "delta_c_pct": -10.0}

    verdict = decide([cand], CAL)
    assert verdict["selected"] == "cand-1", verdict["rows"]
    gates = [(r["gate"], r["passed"]) for r in verdict["rows"] if r["id"] == "cand-1"]
    assert gates == [("floor", True), ("cost", True), ("guard", True), ("argmax", True)]

    led.append(_row(key, delta_metric=5.0, delta_cost=-0.1, accepted=True))
    eff = bf.build(list(doc["a"]))["units"]
    assert eff[key]["status"] == "effective"
    assert eff[key]["max_delta"] == 5.0


def test_30_measured_but_rejected_is_ineffective(ledger):
    doc = load_params(PARAMS)
    led.append(_row("accept_confidence", delta_metric=-1.5, reject_reason="低于噪声带"))
    eff = bf.build(list(doc["a"]))["units"]
    assert eff["accept_confidence"]["status"] == "ineffective"


def test_40_backfill_does_not_touch_params_json(ledger):
    """回灌只读 params.json —— 它是生成物，只能有一个写者。"""
    before = open(PARAMS, "rb").read()
    doc = load_params(PARAMS)
    led.append(_row("accept_confidence", delta_metric=5.0, accepted=True))
    bf.build(list(doc["a"]))
    assert open(PARAMS, "rb").read() == before
