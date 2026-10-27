# -*- coding: utf-8 -*-
"""编辑账本 v2（bundle / outcome / 未测量区分）守卫测试（2026-10-27）。

要钉住的两件事
==============
1. **未测量不是数据**：gate 失败的候选（critic 拒 / smoke 失败 / 评测无效）
   必须记 `delta_metric=None` ⇒ `outcome=UNMEASURED`、`measured=False`，
   且**不进接受率分母、不进"已试组件"**。否则一墙的 abort 会被读成"试过没用"，
   从而把还有救的组件错误剪掉。
2. **老账本仍可读**：v1 记录没有 `bundle` / `outcome`，读出来要自动补齐，
   不允许因为"新 schema"就让历史数据无法统计。
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tools.edit_ledger as led  # noqa: E402


@pytest.fixture()
def tmp_ledger(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setattr(led, "_DIR", str(d))
    monkeypatch.setattr(led, "PATH", str(d / "ledger.jsonl"))
    return d


def _rec(**kw):
    base = {"stage": "2.7_subgoal_main", "dim": "flow", "eu_id": "flow.max_subgoals",
            "hypothesis": "改上限", "diff": "6 → 8", "accepted": False,
            "reject_reason": "", "delta_metric": None, "delta_cost": None}
    base.update(kw)
    return base


# ---------------------------------------------------------------- 归一
def test_01_v1_record_normalized():
    r = led.normalize(_rec())
    assert r["measured"] is False
    assert r["outcome"] == "UNMEASURED"
    assert r["bundle"] == 1


def test_02_measured_outcomes_inferred():
    assert led.normalize(_rec(delta_metric=3.0, accepted=True))["outcome"] == "ACCEPTED"
    assert led.normalize(_rec(delta_metric=-2.0))["outcome"] == "REJECTED"


def test_03_explicit_outcome_kept():
    r = led.normalize(_rec(delta_metric=1.0, outcome="lost"))
    assert r["outcome"] == "lost", "normalize 只能补空，不能覆盖显式值"


# ---------------------------------------------------------------- 校验
def test_10_unmeasured_cannot_be_accepted():
    errs, _ = led.validate(_rec(accepted=True, delta_metric=None))
    assert any("accepted" in e for e in errs)


def test_11_measured_cannot_be_unmeasured():
    errs, _ = led.validate(_rec(delta_metric=2.0, outcome="UNMEASURED"))
    assert any("UNMEASURED" in e for e in errs), errs


def test_12_unknown_outcome_rejected():
    errs, _ = led.validate(_rec(delta_metric=2.0, outcome="MAYBE"))
    assert any("outcome" in e for e in errs)


def test_13_measured_reject_needs_reason():
    errs, _ = led.validate(_rec(delta_metric=-1.0))
    assert any("reject_reason" in e for e in errs)


def test_14_unmeasured_needs_no_reason():
    """gate 失败的条目本身就有 gate_failure 原因，不强制写 reject_reason。"""
    errs, _ = led.validate(_rec())
    assert not errs, errs


# ---------------------------------------------------------------- 统计口径
def test_20_stats_excludes_unmeasured_from_denominator(tmp_ledger, capsys):
    led.append(led.normalize(_rec(delta_metric=5.0, accepted=True)))
    led.append(led.normalize(_rec(eu_id="flow.other", delta_metric=-1.0,
                                  reject_reason="低于噪声带")))
    led.append(led.normalize(_rec(eu_id="flow.gate_failed")))   # 未测量

    led.main(["stats"])
    out = capsys.readouterr().out
    assert "1/2 = 50.0%" in out, out          # 分母只算已测的 2 条
    assert "未测量（不进统计、不进已试集） | 1" in out
    assert "| UNMEASURED | 1 |" in out


def test_21_unmeasured_not_counted_as_tried(tmp_ledger, capsys):
    """未测量条目的 EU 不能算「已试过」—— 否则探索配额会漏掉它。"""
    led.append(led.normalize(_rec(eu_id="flow.gate_failed")))
    seen = {r["eu_id"] for r in led.records() if r["measured"]}
    assert "flow.gate_failed" not in seen


def test_30_append_and_reload_roundtrip(tmp_ledger):
    led.append(led.normalize(_rec(delta_metric=2.0, accepted=True, bundle=3,
                                  outcome="ACCEPTED")))
    rows = led.records()
    assert len(rows) == 1 and rows[0]["bundle"] == 3 and rows[0]["measured"] is True


def test_31_list_shows_outcome(tmp_ledger, capsys):
    led.append(led.normalize(_rec()))
    led.main(["list", "--unmeasured-only"])
    out = capsys.readouterr().out
    assert "UNMEASURED" in out, out
