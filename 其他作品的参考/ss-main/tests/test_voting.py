"""Tests for voting and candidate scoring."""

from __future__ import annotations

from tools.voting import (
    are_answers_equivalent,
    majority_vote,
    normalize_for_vote,
    score_candidate,
    select_best_candidate,
)


def test_normalize_for_vote_boxed():
    assert normalize_for_vote("最终答案：\\boxed{72}") == "72"
    assert normalize_for_vote("$72$") == "72"
    assert normalize_for_vote("答案是 B。") == "b"


def test_are_answers_equivalent_sympy():
    assert are_answers_equivalent("x+x", "2*x") is True
    assert are_answers_equivalent("\\frac{1}{2}", "1/2") is True
    assert are_answers_equivalent("72", "81") is False


def test_majority_vote_prefers_common_answer():
    candidates = [
        {"id": "candidate_1", "answer": "72", "solution": "a", "confidence": 0.5},
        {"id": "candidate_2", "answer": "\\boxed{72}", "solution": "b", "confidence": 0.5},
        {"id": "candidate_3", "answer": "81", "solution": "c", "confidence": 0.5},
    ]
    group = majority_vote(candidates)
    assert group is not None
    assert group["count"] == 2
    assert normalize_for_vote(group["normalized_answer"]) == "72"


def test_select_best_candidate_uses_majority():
    candidates = [
        {"id": "candidate_1", "answer": "72", "solution": "推导A", "confidence": 0.5},
        {"id": "candidate_2", "answer": "\\boxed{72}", "solution": "推导B", "confidence": 0.5},
        {"id": "candidate_3", "answer": "81", "solution": "推导C", "confidence": 0.5},
    ]
    best = select_best_candidate(candidates)
    assert normalize_for_vote(best["answer"]) == "72"
    assert best["vote_count"] == 2
    assert best["score"] >= 0.6


def test_select_best_candidate_empty_fallback():
    best = select_best_candidate([])
    assert best["id"] == "fallback"
    assert best["need_refine"] is True
    assert best["answer"] == "无法确定"


def test_empty_answer_downweighted():
    empty = {"id": "c1", "answer": "", "solution": "text", "confidence": 0.5}
    filled = {"id": "c2", "answer": "2", "solution": "text", "confidence": 0.5}
    assert score_candidate(empty) < score_candidate(filled)


def test_uncertain_answer_downweighted():
    bad = {
        "id": "c1",
        "answer": "无法回答",
        "solution": "无法回答",
        "confidence": 0.5,
    }
    good = {
        "id": "c2",
        "answer": "42",
        "solution": "计算得到 42",
        "confidence": 0.5,
    }
    assert score_candidate(bad) < score_candidate(good)
