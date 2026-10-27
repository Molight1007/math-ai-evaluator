# -*- coding: utf-8 -*-
"""L2 归因核对测试（预测 vs 实际变化）。

判据的优先级：**未预料的退步**比命中率重要 ——
命中率高只说明"它蒙对了几道该动的"，漏掉的退步才是把分数吃掉的凶手。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tools.attribution as att  # noqa: E402


def _write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(p)


def test_01_hit_and_miss():
    before = {"q1": True, "q2": False, "q3": True}
    after = {"q1": False, "q2": True, "q3": True}
    r = att.compare(before, after, {"items": ["q1", "q2", "q9"], "structured": True})
    assert r["became_wrong"] == ["q1"] and r["became_right"] == ["q2"]
    assert r["hit"] == ["q1", "q2"]
    assert r["missed"] == ["q9"]                  # 预测会变，实际没这道题
    assert r["hit_rate"] == pytest.approx(2 / 3)


def test_02_unexpected_regression_is_flagged():
    before = {"q1": True, "q2": True}
    after = {"q1": False, "q2": True}
    r = att.compare(before, after, {"items": [], "structured": True})
    assert r["unexpected_regressions"] == ["q1"], "没预测到却变错，必须单列"
    assert r["hit_rate"] is None, "零预测时命中率应为 None，不能是 0（0 会被读成全错）"


def test_03_natural_language_prediction_cannot_be_checked():
    r = att.compare({"q1": True}, {"q1": False},
                    {"items": [], "raw": "所有组合题", "structured": False})
    assert r["structured_prediction"] is False and r["hit_rate"] is None


def test_04_load_scores_skips_unscored_rows(tmp_path):
    p = _write(tmp_path, "b.jsonl", [
        {"id": "q1", "correct": True},
        {"id": "q2"},                       # 没有 correct ⇒ 判不了分，跳过
        {"id": "q3", "correct": False},
        "not-a-dict",
    ])
    assert att.load_scores(p) == {"q1": True, "q3": False}


def test_05_dataset_mismatch_reported(tmp_path):
    before = {"q1": True}
    after = {"q1": True, "q2": True}
    r = att.compare(before, after, {"items": [], "structured": True})
    assert r["only_after"] == ["q2"] and r["n_common"] == 1


def test_06_load_predicted_accepts_candidate_file(tmp_path):
    p = tmp_path / "cand.json"
    p.write_text(json.dumps({"candidate": {"predicted_affected": ["q1", "q2"]}}),
                 encoding="utf-8")
    got = att.load_predicted(str(p))
    assert got["structured"] is True and got["items"] == ["q1", "q2"]


def test_07_cli_writes_jsonl(tmp_path):
    pred = tmp_path / "p.json"
    pred.write_text(json.dumps({"predicted_affected": ["q1"]}), encoding="utf-8")
    b = _write(tmp_path, "b.jsonl", [{"id": "q1", "correct": True}])
    a = _write(tmp_path, "a.jsonl", [{"id": "q1", "correct": False}])
    out = tmp_path / "attr.jsonl"
    rc = att.main(["--pred", str(pred), "--before", b, "--after", a,
                   "--out", str(out), "--write"])
    assert rc == 0
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["hit"] == ["q1"] and row["hit_rate"] == 1.0
