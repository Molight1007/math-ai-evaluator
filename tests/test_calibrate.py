# -*- coding: utf-8 -*-
"""δ 标定工具测试（公式 / 拒绝 / 来源标记）。

关键点：δ 一旦被写成"看起来像实测"的样子，四道门就会开始放行候选 ——
所以这里除了算对，还要钉住**两条拒绝**：重复次数不足、来源不是 measured。
"""
from __future__ import annotations

import json
import os
import statistics
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tools.calibrate as cal_mod  # noqa: E402
from contracts.selection import calibration_usable, validate_calibration  # noqa: E402


def test_01_repeats_formula():
    scores = [34.0, 33.5, 35.2]
    out = cal_mod.calibrate_repeats(scores, z=2.0)
    sd = statistics.stdev(scores)
    assert out["sd_single"] == pytest.approx(sd, abs=1e-4)
    assert out["delta_pp"] == pytest.approx(2.0 * sd * (2 ** 0.5), abs=1e-3)
    assert out["s_star"] == pytest.approx(statistics.fmean(scores), abs=1e-4)


def test_02_needs_two_repeats():
    with pytest.raises(ValueError):
        cal_mod.calibrate_repeats([34.0])


def test_03_bootstrap_needs_two_scored_tasks():
    with pytest.raises(ValueError):
        cal_mod.calibrate_bootstrap({"q1": [1, 1]}, k=2)


def test_04_bootstrap_is_deterministic_with_seed():
    rewards = {("q%d" % i): [1, 0] if i % 2 else [1, 1] for i in range(10)}
    a = cal_mod.calibrate_bootstrap(rewards, k=2, seed=7, n_boot=200)
    b = cal_mod.calibrate_bootstrap(rewards, k=2, seed=7, n_boot=200)
    assert a["delta_pp"] == b["delta_pp"] and a["method"] == "bootstrap"


def test_05_doc_marks_beta_as_borrowed():
    doc = cal_mod.build_doc(cal_mod.calibrate_repeats([34.0, 34.6]))
    assert doc["source"] == "measured"
    assert doc["beta_source"] == "rrsi-borrowed", "δ 是实测的，β 还是借的，必须分开标"
    assert doc["schema"] == "gates/1"
    validate_calibration(doc)
    assert calibration_usable(doc, require_measured=True)[0] is True


def test_06_write_refuses_to_overwrite(tmp_path, capsys):
    out = tmp_path / "gates.json"
    out.write_text(json.dumps({"schema": "gates/1"}), encoding="utf-8")
    rc = cal_mod.main(["--scores", "34", "34.5", "--out", str(out), "--write"])
    assert rc == 1
    assert "不覆盖" in capsys.readouterr().out


def test_07_write_creates_usable_file(tmp_path):
    out = tmp_path / "gates.json"
    rc = cal_mod.main(["--scores", "34", "34.5", "--out", str(out), "--write"])
    assert rc == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert calibration_usable(doc)[0] is True
    assert doc["delta_pp"] > 0
