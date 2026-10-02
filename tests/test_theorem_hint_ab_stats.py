# -*- coding: utf-8 -*-
"""A/B 配对统计的正确性测试（2026-09-29）。

动机：`tools/theorem_hint_ab.py` 的 `analyze()` 是**结论产出器** ——
它说"有效"用户就会据此保留机制，它说"无差异"用户就会去做别的改动。
一个算错的统计脚本比没有脚本更危险，因为它会给出**看起来可信的错误结论**。

因此这里用**合成数据做三重对照**（阳性 / 阴性 / 负向），断言它：
  · 在真有效时判"有效"（不能漏报）；
  · 在无差异时判"无显著差异"（不能虚报 —— 这是最容易发生的错误）；
  · 在有害时判"负向"（不能把伤害读成无害）；
  · 无共同题号时**直接拒绝**（不能拿空交集算出"Δ=0 无差异"）。

★ 这些断言不依赖本机环境（无网络、无 LLM、无文件系统外部状态）。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.theorem_hint_ab import analyze  # noqa: E402


def _write(path: str, mapping: dict) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for k, v in mapping.items():
            f.write(json.dumps({"id": k, "correct": v},
                               ensure_ascii=False) + "\n")
    return path


@pytest.fixture()
def tmp_jsonl(tmp_path):
    def _mk(name, mapping):
        return _write(str(tmp_path / name), mapping)
    return _mk


# ----------------------------------------------------------------------
# 阳性对照：注入真的带来提升 ⇒ 必须判「有效」
# ----------------------------------------------------------------------
def test_positive_control_reports_effective(tmp_jsonl):
    off = {f"q{i:02d}": False for i in range(40)}
    off["q30"] = off["q31"] = True          # 2 题对照本来就对

    on = dict(off)
    for i in range(10):
        on[f"q{i:02d}"] = True              # 10 题 off错 → on对
    on["q30"] = on["q31"] = False           # 2 题反向（off对 → on错）

    r = analyze(tmp_jsonl("off.jsonl", off), tmp_jsonl("on.jsonl", on))

    assert r["flip_off2on"]["n"] == 10
    assert r["flip_on2off"]["n"] == 2
    assert r["net"] == 8
    assert r["delta_pp"] == pytest.approx(20.0, abs=0.01)
    assert r["mcnemar_p"] < 0.05
    assert "有效" in r["verdict"]


# ----------------------------------------------------------------------
# 阴性对照：两组完全一致 ⇒ 必须判「无显著差异」，**绝不能虚报有效**
# ----------------------------------------------------------------------
def test_negative_control_reports_no_difference(tmp_jsonl):
    off = {f"q{i:02d}": (i % 3 == 0) for i in range(40)}
    r = analyze(tmp_jsonl("off.jsonl", off), tmp_jsonl("same.jsonl", dict(off)))

    assert r["net"] == 0
    assert r["flip_off2on"]["n"] == 0
    assert r["flip_on2off"]["n"] == 0
    assert r["delta_pp"] == pytest.approx(0.0, abs=1e-9)
    assert r["mcnemar_p"] == 1.0
    assert "无显著差异" in r["verdict"]


def test_negative_control_with_noise_still_no_difference(tmp_jsonl):
    """抖动但**对称**（对错互换各 5 题）⇒ net=0，仍不得判「有效」。

    这是最危险的假阳性形态：正确率看起来没变但翻转很大，
    若判据只看 |Δ| 就会误判；必须看 net 与配对显著性。
    """
    off = {f"q{i:02d}": True for i in range(20)}
    on = dict(off)
    for i in range(5):
        on[f"q{i:02d}"] = False             # 5 题掉
    for i in range(5, 10):
        on[f"q{i:02d}"] = True              # （这 5 题本就 True，无变化）

    off2 = dict(off)
    for i in range(5, 10):
        off2[f"q{i:02d}"] = False           # 让这 5 题成为 off错→on对
    r = analyze(tmp_jsonl("a.jsonl", off2), tmp_jsonl("b.jsonl", on))

    assert r["flip_off2on"]["n"] == 5
    assert r["flip_on2off"]["n"] == 5
    assert r["net"] == 0
    assert r["delta_pp"] == pytest.approx(0.0, abs=1e-9)
    assert "无显著差异" in r["verdict"]


# ----------------------------------------------------------------------
# 负向对照：注入有害 ⇒ 必须判「负向」，不能读成无害
# ----------------------------------------------------------------------
def test_harmful_injection_reports_negative(tmp_jsonl):
    off = {f"k{i:02d}": True for i in range(40)}
    on = dict(off)
    for i in range(10):
        on[f"k{i:02d}"] = False             # 10 题 off对 → on错，无反向

    r = analyze(tmp_jsonl("off.jsonl", off), tmp_jsonl("on.jsonl", on))

    assert r["net"] == -10
    assert r["delta_pp"] == pytest.approx(-25.0, abs=0.01)
    assert "负向" in r["verdict"]


# ----------------------------------------------------------------------
# 退化输入：必须拒绝，不能静默产出结论
# ----------------------------------------------------------------------
def test_no_common_ids_is_rejected(tmp_jsonl):
    off = {f"x{i}": True for i in range(10)}
    on = {f"y{i}": True for i in range(10)}
    with pytest.raises(SystemExit):
        analyze(tmp_jsonl("off.jsonl", off), tmp_jsonl("on.jsonl", on))


def test_unpaired_ids_are_reported_not_silently_dropped(tmp_jsonl):
    """只在一组出现的题必须被**点名** —— 否则「样本变少」会被误读成「题目变少」。"""
    off = {f"q{i}": True for i in range(10)}
    on = {f"q{i}": True for i in range(3)}
    r = analyze(tmp_jsonl("off.jsonl", off), tmp_jsonl("on.jsonl", on))
    assert r["n_paired"] == 3
    assert len(r["unpaired"]["off_only_ids"]) == 7


# ----------------------------------------------------------------------
# 结果文件读取的宽容性（字段名在项目里有多套写法）
# ----------------------------------------------------------------------
@pytest.mark.parametrize("field", ["correct", "is_correct", "matched",
                                   "reference_matched"])
def test_verdict_field_aliases(tmp_jsonl, field):
    path = str(tmp_jsonl("alias.jsonl", {}))
    with open(path, "w", encoding="utf-8") as f:
        for i in range(5):
            f.write(json.dumps({"id": f"q{i}", field: i % 2 == 0}) + "\n")
    r = analyze(path, path)
    assert r["n_paired"] == 5
    assert r["net"] == 0


def test_score_field_is_thresholded(tmp_jsonl):
    path = str(tmp_jsonl("score.jsonl", {}))
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "q0", "score": 1.0}) + "\n")
        f.write(json.dumps({"id": "q1", "score": 0.5}) + "\n")
    r = analyze(path, path)
    assert r["n_paired"] == 2
