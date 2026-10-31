# -*- coding: utf-8 -*-
"""E21 蓝图许可证回放的口径守卫。

为什么要有这些测试
----------------
这个回放的全部结论都依赖几个**文本口径**（什么算「直接断言值」、
什么算「闭合」）。口径一旦在下一次修改里悄悄漂移，结论就会跟着变，
而漂移不会报错 —— 只会给出一个看着合理的新数字。

实测教训：R4 的宽/严两个口径差 **10 倍**（26.1% vs 2.6%），
所以口径必须被钉住，且两个口径都要能独立算出。
"""

from __future__ import print_function

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import replay_blueprint_license as R  # noqa: E402


# ------------------------------------------------------------------ qid

def test_qid_deterministic_and_matches_production_rule():
    """qid 必须与 agent/artifact_store.py::_qid_from_problem 同规则（md5 前 8）。"""
    import hashlib
    q = "Find all positive integers n such that 2^n + 1 is prime."
    want = "q" + hashlib.md5(q.encode("utf-8")).hexdigest()[:8]
    assert R._qid_from_question(q) == want
    assert R._qid_from_question(q) == R._qid_from_question(q)
    assert R._qid_from_question(q).startswith("q")
    assert len(R._qid_from_question(q)) == 9


# ------------------------------------------------------------------ 闭合层级

def test_closure_hard_requires_tool_actually_ran():
    """HARD 只认 tool_ran=True —— 这是唯一不可贿赂的闭合。"""
    sg = {"tool_ran": True, "tool_verdict": "ok", "objective_verdict": "correct"}
    assert R.closure_of(sg)[0] == "HARD_CLOSED"


def test_closure_hard_rejects_failed_tool_verdict():
    sg = {"tool_ran": True, "tool_verdict": "error: unknown module", "objective_verdict": "correct"}
    assert R.closure_of(sg)[0] == "SOFT_CLOSED"


def test_closure_soft_is_llm_self_report_only():
    """LLM 自评 correct 只能是 SOFT —— 同源失效，不能当硬证据。"""
    sg = {"tool_ran": False, "objective_verdict": "correct", "has_derivation": True}
    assert R.closure_of(sg)[0] == "SOFT_CLOSED"


@pytest.mark.parametrize("ov", ["incorrect", "undecided", None, ""])
def test_closure_open(ov):
    sg = {"tool_ran": False, "objective_verdict": ov, "has_derivation": True}
    assert R.closure_of(sg)[0] == "OPEN"


def test_closure_unmapped_when_no_subgoal():
    """无子目标必须单列 UNMAPPED，不能被算成 OPEN（否则闭合率虚高）。"""
    assert R.closure_of(None)[0] == "UNMAPPED"
    assert R.closure_of({})[0] == "UNMAPPED"


# ------------------------------------------------------------------ 断言口径

def _assert_like(statement):
    """复刻 analyze_question 里的 R4 双口径判定（严, 宽）。"""
    va = va_loose = False
    if statement:
        low = statement.lower()
        if any(w.lower() in low for w in R._ASSERT_MARKERS):
            return True, True
        if R._VALUE_EQ_RE.search(statement):
            has_derive = any(w.lower() in low for w in R._DERIVE_WORDS)
            if not has_derive:
                va = True
            body = statement
            for w in R._DERIVE_WORDS:
                body = body.replace(w, u" ")
            if R._VALUE_EQ_RE.search(body):
                va_loose = True
    return va, va_loose


@pytest.mark.parametrize("st", [
    u"a_n = n+1",
    u"C(1) = 1",
    u"T = \\frac{\\sqrt{5}-1}{2}",
    u"x = 2026",
])
def test_value_assert_strict_catches_bare_equality(st):
    va, va_loose = _assert_like(st)
    assert va is True and va_loose is True


@pytest.mark.parametrize("st", [
    u"由 n1 的单射性与原方程确定 f(1) = 1",
    u"Compute C(1234) for each classified nice function",
    "Prove by induction that C(n) >= n for all n, using C(1)=1",
    u"由 x^2+y^2+z^2=3 建立 |x|,|y|,|z| <= sqrt(3) 的范围约束",
])
def test_value_assert_strict_excludes_derivation_sentences(st):
    """带推导词的句子不算「直接断言」——这是修掉的大假阳性来源。"""
    va, _ = _assert_like(st)
    assert va is False


def test_value_assert_loose_is_superset_of_strict():
    """宽口径 ⊇ 严口径（任何严口径命中都必须宽口径也命中）。"""
    for st in (u"a_n = n+1", u"由 n1 确定 f(1) = 1", u"证明 f 是单射函数"):
        va, loose = _assert_like(st)
        assert (not va) or loose


def test_loose_catches_derivation_sentence_with_written_value():
    """「由…确定 f(1) = 1」：形式在推、结论写死 ⇒ 只有宽口径抓到。
    这正是宽/严两个口径必须并列报出的原因。"""
    va, loose = _assert_like(u"由 n1 的单射性与原方程确定 f(1) = 1")
    assert va is False
    assert loose is True


def test_equation_of_a_compound_expression_is_not_a_value_assert():
    """题设方程 `x^2+y^2+z^2=3` 左式是算式不是单一符号 ⇒ 两个口径都不算断言。
    （这是修掉的第二个假阳性：旧口径把它当成「断言值」）"""
    for st in (u"由 x^2+y^2+z^2=3 建立范围约束", u"验证 2+2=4", u"由 x^2 + y^2 = 3 得"):
        va, loose = _assert_like(st)
        assert va is False and loose is False, st


def test_assert_marker_catches_must_equal_without_equals_sign():
    """「必须等于 2026」/「must equal 2026」不含 `=`，仍须判为断言。"""
    for st in (u"a_n 必须等于 2026", "the total must equal 2026"):
        va, loose = _assert_like(st)
        assert va is True and loose is True


# ------------------------------------------------------------------ 节点↔子目标映射

def test_map_prefers_text_over_position():
    nodes = [
        {"id": "g", "statement": u"求总和"},
        {"id": "n1", "statement": u"证明 f 是单射"},
        {"id": "n2", "statement": u"确定 f(1)"},
    ]
    subgoals = [
        {"id": 1, "description": u"确定 f(1)", "title": u"子目标1: 确定 f(1)"},
        {"id": 2, "description": u"证明 f 是单射", "title": u"子目标2: 证明 f 是单射"},
    ]
    m, method = R.map_nodes_to_subgoals(nodes, subgoals, "g")
    assert m["n1"]["id"] == 2
    assert m["n2"]["id"] == 1
    assert method["text"] == 2


def test_map_falls_back_to_position_and_reports_it():
    """文本对不上时按落位配对，但必须在 match_method 里留痕（不能静默）。"""
    nodes = [
        {"id": "g", "statement": u"root"},
        {"id": "n1", "statement": u"完全不同的措辞"},
    ]
    subgoals = [{"id": 1, "description": u"另一句话", "title": u"子目标1: 另一句话"}]
    m, method = R.map_nodes_to_subgoals(nodes, subgoals, "g")
    assert m["n1"]["id"] == 1
    assert method["position"] == 1


def test_map_marks_unmatched_when_more_nodes_than_subgoals():
    nodes = [{"id": "g", "statement": "r"}, {"id": "n1", "statement": "a"},
             {"id": "n2", "statement": "b"}]
    subgoals = [{"id": 1, "description": "a", "title": "子目标1: a"}]
    m, method = R.map_nodes_to_subgoals(nodes, subgoals, "g")
    assert m["n1"]["id"] == 1
    assert m["n2"] is None
    assert method["unmatched"] == 1


# ------------------------------------------------------------------ 统计检验

def test_fisher_known_values():
    # 完全无关联
    assert R.fisher_two_sided(10, 10, 10, 10) == pytest.approx(1.0, abs=1e-9)
    # 完全分离：3/3 vs 0/3 ⇒ 双侧 p = 0.1
    assert R.fisher_two_sided(3, 0, 0, 3) == pytest.approx(0.1, abs=1e-9)
    # 单格为 0 但边缘不为 0
    assert 0.0 < R.fisher_two_sided(0, 5, 5, 5) < 1.0


def test_mann_whitney_detects_clear_shift():
    # 返回的是单侧 p：P(第一样本 > 第二样本)。第一样本明显更小 ⇒ p 接近 1。
    _, p = R.mann_whitney([1, 2, 3], [10, 11, 12])
    assert p is not None and p > 0.90
    # 反过来就该很小（显著）
    _, p_rev = R.mann_whitney([10, 11, 12], [1, 2, 3])
    assert p_rev is not None and p_rev < 0.10
    _, p_same = R.mann_whitney([1, 2, 3], [1, 2, 3])
    assert p_same is not None and 0.10 <= p_same <= 1.0


# ------------------------------------------------------------------ 端到端

def _mk(tmpdir, qid, nodes, subgoals, results):
    d = os.path.join(str(tmpdir), "20261030-120000", qid)
    os.makedirs(d)
    with open(os.path.join(d, "02_blueprint.json"), "w", encoding="utf-8") as f:
        json.dump({"root_id": "g", "nodes": nodes}, f, ensure_ascii=False)
    with open(os.path.join(d, "03_subgoals.json"), "w", encoding="utf-8") as f:
        json.dump({"plan": {"subgoals": subgoals}}, f, ensure_ascii=False)
    with open(os.path.join(d, "04_subgoal_results.jsonl"), "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return d


def test_analyze_question_flags_reference_to_open_node(tmpdir):
    """核心语义：引用了未闭合节点 ⇒ R2；引用一个「直接断言值」的节点 ⇒ R6。"""
    nodes = [
        {"id": "g", "statement": u"求答案", "inputs": []},
        {"id": "n1", "statement": u"a_n = n+1", "inputs": []},
        {"id": "n2", "statement": u"由 n1 代入求和", "inputs": ["n1"]},
    ]
    subgoals = [
        {"id": 1, "description": u"a_n = n+1", "title": u"子目标1: a_n = n+1"},
        {"id": 2, "description": u"由 n1 代入求和", "title": u"子目标2: 由 n1 代入求和"},
    ]
    results = [
        {"id": 1, "tool_ran": False, "objective_verdict": "undecided", "has_derivation": True},
        {"id": 2, "tool_ran": False, "objective_verdict": "correct", "has_derivation": True},
    ]
    d = _mk(tmpdir, "qdeadbeef", nodes, subgoals, results)
    r = R.analyze_question(d)
    by = {n["node"]: n for n in r["nodes"]}
    assert "R2_DOWNSTREAM_UNCLOSED" in by["n2"]["violations"]
    assert by["n2"]["open_refs"] == ["n1"]
    assert "R6_FALSE_PREMISE" in by["n2"]["violations"]
    assert "R4_VALUE_ASSERT" in by["n1"]["violations"]
    assert by["n2"]["closure"] == "SOFT_CLOSED"
    assert by["n1"]["closure"] == "OPEN"


def test_analyze_question_no_hard_close_is_universal(tmpdir):
    """整题没有 tool_ran=True ⇒ R5 必报。这是 P0 的实体，不能漏。"""
    nodes = [{"id": "g", "statement": "r", "inputs": []},
             {"id": "n1", "statement": u"证明 P", "inputs": []}]
    subgoals = [{"id": 1, "description": u"证明 P", "title": u"子目标1: 证明 P"}]
    results = [{"id": 1, "tool_ran": False, "objective_verdict": "correct",
                "has_derivation": True}]
    d = _mk(tmpdir, "qcafebabe", nodes, subgoals, results)
    r = R.analyze_question(d)
    assert r["viol"].get("R5_NO_HARD_CLOSE") == 1
    assert r["closure"]["HARD"] == 0


def test_analyze_question_excludes_root_node(tmpdir):
    nodes = [{"id": "g", "statement": u"根", "inputs": []},
             {"id": "n1", "statement": u"证明 P", "inputs": []}]
    d = _mk(tmpdir, "q0badf00d", nodes, [{"id": 1, "description": u"证明 P"}],
            [{"id": 1, "tool_ran": True, "tool_verdict": "ok"}])
    r = R.analyze_question(d)
    assert r["n_nodes"] == 1
    assert all(n["node"] != "g" for n in r["nodes"])
    assert r["closure"]["HARD"] == 1


def test_analyze_question_returns_none_without_blueprint(tmpdir):
    d = os.path.join(str(tmpdir), "run", "qempty")
    os.makedirs(d)
    assert R.analyze_question(d) is None


# ------------------------------------------------------------------ 标签口径

def test_label_prefers_paired_jsonl_over_global_qid():
    """同一题在多臂出现且一对错时，必须用**本 run 配对到的 jsonl**，
    不能因为「全局混合」把整题丢弃（实测这条让可用标签 45→97）。"""
    by_qid = {"qabc": [
        {"jsonl": "ab_on", "qid": "qabc", "correct": True},
        {"jsonl": "ab_off", "qid": "qabc", "correct": False},
    ]}
    by_jsonl_qid = {
        "ab_on": {"qabc": {"correct": True}},
        "ab_off": {"qabc": {"correct": False}},
    }
    assert R.label_for(by_qid, by_jsonl_qid, "r", "qabc", "ab_off")[0] is False
    assert R.label_for(by_qid, by_jsonl_qid, "r", "qabc", "ab_on")[0] is True


def test_label_discards_mixed_but_keeps_unanimous():
    by_qid = {"q1": [{"jsonl": "a", "qid": "q1", "correct": True},
                     {"jsonl": "b", "qid": "q1", "correct": False}]}
    assert R.label_for(by_qid, {}, "r", "q1", None)[0] is None
    by_qid2 = {"q2": [{"jsonl": "a", "qid": "q2", "correct": False},
                      {"jsonl": "b", "qid": "q2", "correct": False}]}
    assert R.label_for(by_qid2, {}, "r", "q2", None)[0] is False
