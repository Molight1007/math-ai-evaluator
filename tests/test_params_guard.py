# -*- coding: utf-8 -*-
"""L4 critic（候选三条硬规则）守卫测试（2026-10-27）。

为什么单独测
============
critic 是**评测前唯一的一道自动闸**：它漏一个坏候选 ⇒ 白烧 3 小时评测；
它误杀好候选 ⇒ 提案器永远提不出东西。两个方向都要钉住：

  1. 该拒的必须拒（发明参数 / 类型不符 / 越界 / 泄漏题号答案）；
  2. 不该拒的不能拒（正常中文描述里出现"答案"两字是允许的；
     float 参数给整数、布尔开关改值都是合法编辑）。
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from contracts.params_guard import (  # noqa: E402
    diff_edits, domain_of, review_candidate, review_edits, scan_leak,
)
from contracts.params_io import load as load_params  # noqa: E402

PARAMS = os.path.join(REPO, "params.json")


@pytest.fixture(scope="module")
def doc():
    return load_params(PARAMS)


def _keys(vs):
    return {v["rule"] for v in vs}


# ---------------------------------------------------------------- 该放行的
def test_01_normal_edit_passes(doc):
    v = review_edits([{"key": "policy_sample_times", "to": 3}], doc)
    assert v["passed"], v["violations"]
    assert v["n_edits"] == 1


def test_02_float_accepts_int(doc):
    cur = doc["a"]["verifier_disagreement_temperature"]["value"]
    v = review_edits([{"key": "verifier_disagreement_temperature", "to": 1}], doc)
    assert v["passed"], v["violations"]
    assert isinstance(cur, float)


def test_03_chinese_prose_mentioning_answer_is_ok(doc):
    """自由文本里出现「答案」不算泄漏 —— 误杀会让提案器的假设写不出来。"""
    v = review_edits([{"key": "policy_sample_times", "to": 3}], doc,
                     scan_text="假设：多采样一个候选，让答案更稳，减少池空情形。")
    assert v["passed"], v["violations"]


# ---------------------------------------------------------------- 该拒的
def test_10_invented_key_rejected(doc):
    v = review_edits([{"key": "make_up_new_param", "to": 1}], doc)
    assert not v["passed"] and "key_whitelist" in _keys(v["violations"])


def test_11_bool_int_confusion_rejected(doc):
    """True → 1 必须拒：Python 里 bool 是 int 子类，不显式区分就会放过。"""
    v = review_edits([{"key": "five_gate_falsify", "to": 1}], doc)
    assert not v["passed"] and "value_domain" in _keys(v["violations"])


def test_12_temperature_upper_bound(doc):
    v = review_edits([{"key": "policy_temperature", "to": 5.0}], doc)
    assert not v["passed"] and "value_domain" in _keys(v["violations"])


def test_13_ratio_out_of_unit_interval(doc):
    v = review_edits([{"key": "accept_confidence", "to": 1.5}], doc)
    assert not v["passed"] and "value_domain" in _keys(v["violations"])


def test_14_negative_rounds_rejected(doc):
    v = review_edits([{"key": "blueprint_multi_gen_rounds", "to": -1}], doc)
    assert not v["passed"] and "value_domain" in _keys(v["violations"])


def test_15_leak_task_id_rejected(doc):
    for txt in ("official112 的第 3 题", "qid: 42", "题 107", "标准答案 603729"):
        v = review_edits([{"key": "policy_sample_times", "to": 3}], doc, scan_text=txt)
        assert not v["passed"], "未拦住泄漏文本：%r" % txt
        assert "no_task_leak" in _keys(v["violations"])


def test_16_leak_in_string_value_rejected(doc):
    """字符串型参数里塞题库名 —— 值本身也要筛。"""
    target = next((k for k, e in doc["a"].items() if isinstance(e["value"], str)
                   and e["value"]), None)
    if not target:
        pytest.skip("A 段没有非空字符串参数")
    v = review_edits([{"key": target, "to": "official112"}], doc)
    assert not v["passed"] and "no_task_leak" in _keys(v["violations"])


# ---------------------------------------------------------------- 文件级入口
def test_20_candidate_doc_roundtrip(doc):
    cand = {"a": {k: dict(v) for k, v in doc["a"].items()}}
    cand["a"]["policy_sample_times"]["value"] = 3
    edits = diff_edits(doc, cand)
    assert [e["key"] for e in edits] == ["policy_sample_times"]
    assert review_candidate(doc, cand)["passed"]


def test_21_deleting_a_key_rejected(doc):
    cand = {"a": {k: dict(v) for k, v in doc["a"].items()}}
    cand["a"].pop("policy_sample_times")
    v = review_candidate(doc, cand)
    assert not v["passed"] and "key_whitelist" in _keys(v["violations"])


def test_22_no_change_is_noop(doc):
    cand = {"a": {k: dict(v) for k, v in doc["a"].items()}}
    v = review_candidate(doc, cand)
    assert v["passed"] and v["n_edits"] == 0


# ---------------------------------------------------------------- 域描述
def test_30_domain_shapes(doc):
    assert domain_of("five_gate_falsify", True)["kind"] == "bool"
    assert domain_of("policy_temperature", 0.3)["max"] == 2.0
    assert domain_of("accept_confidence", 0.6)["max"] == 1.0
    d = domain_of("blueprint_multi_gen_rounds", 3)
    assert d["min"] == 0 and d["kind"] == "number"
    assert domain_of("leansearch_top_k", 25)["min"] == 0


def test_31_scan_leak_is_precise():
    assert scan_leak("把 official112 的 gold 写进去")
    assert not scan_leak("子目标里不要锁死具体数值")
    assert not scan_leak("提高候选数，减少池空")


# ---------------------------------------------------------------- 两个边界易漏项
def test_40_limit_style_names_have_bounds(doc):
    """`candidate_pool_limit` 这类不含 max_/rounds 的名字也要有下界（语义：计数 ≥0）。"""
    v = review_edits([{"key": "candidate_pool_limit", "to": -1.0}], doc)
    assert not v["passed"] and "value_domain" in _keys(v["violations"])


def test_41_json_encoded_string_validated(doc):
    """声明成 str、实际存 JSON 的参数（theorem_hint_top_k_by_stage）要卡形状。"""
    key = "theorem_hint_top_k_by_stage"
    if key not in doc["a"]:
        pytest.skip("该键不在 A 段")
    bad = review_edits([{"key": key, "to": "{not json"}], doc)
    assert not bad["passed"] and "value_domain" in _keys(bad["violations"])
    ok = review_edits([{"key": key, "to": '{"subgoal": 30}'}], doc)
    assert ok["passed"], ok["violations"]

