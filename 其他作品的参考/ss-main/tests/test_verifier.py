"""Tests for Verifier module."""

from agents.verifier import Verifier, rule_score_candidate
from collections import Counter
from user_agent import ReasoningAgent


def test_same_answers_get_consensus_bonus():
    verifier = Verifier(client=None)
    candidates = [
        {
            "id": "candidate_1",
            "answer": "42",
            "solution": "推理 A\n最终答案：42",
            "confidence": 0.5,
        },
        {
            "id": "candidate_2",
            "answer": "42",
            "solution": "推理 B\n最终答案：42",
            "confidence": 0.5,
        },
    ]
    best = verifier.verify_candidates(
        problem="计算40+2",
        candidates=candidates,
        profile={"difficulty": "medium"},
    )
    assert best["answer"] == "42"
    assert best["score"] >= 0.9


def test_empty_answer_lowers_score():
    counts = Counter({"": 0})
    scored = rule_score_candidate(
        {"id": "candidate_1", "answer": "", "solution": "some text"},
        counts,
    )
    assert scored["score"] < 0.5
    assert "empty_answer" in scored["issues"]


def test_client_none_rule_mode():
    verifier = Verifier(client=None)
    best = verifier.verify_candidates(
        problem="1+1",
        candidates=[
            {"id": "candidate_1", "answer": "2", "solution": "1+1=2"},
            {"id": "candidate_2", "answer": "3", "solution": "wrong"},
        ],
        profile={},
    )
    assert best["id"] in ("candidate_1", "candidate_2")
    assert "score" in best
    assert "issues" in best
    assert "need_refine" in best


def test_llm_verifier_with_fake_client():
    class FakeVerifyClient:
        def chat(self, messages, temperature=0.2, max_tokens=4096):
            return "正确性：correct\n问题：无\n修正答案：\n置信度：0.9"

    verifier = Verifier(client=FakeVerifyClient())
    best = verifier.verify_candidates(
        problem="计算40+2",
        candidates=[
            {
                "id": "candidate_1",
                "answer": "42",
                "solution": "最终答案：42",
            }
        ],
        profile={},
    )
    assert best["answer"] == "42"
    assert best["score"] > 0.5


def test_multiple_candidates_return_structure():
    verifier = Verifier(client=None)
    best = verifier.verify_candidates(
        problem="求极限",
        candidates=[
            {"id": "candidate_1", "answer": "1", "solution": "推导1"},
            {"id": "candidate_2", "answer": "0", "solution": "推导2"},
            {"id": "candidate_3", "answer": "1", "solution": "推导3"},
        ],
        profile={"difficulty": "hard"},
    )
    for key in ("id", "answer", "solution", "score", "issues", "need_refine"):
        assert key in best
    assert best["answer"] == "1"


def test_verifier_integrated_in_agent():
    class FakeClient:
        def chat(self, messages, temperature=0.2, max_tokens=4096):
            content = messages[0]["content"] if messages else ""
            if "请严格检查以下数学题的候选解答" in content:
                return "正确性：correct\n问题：无\n修正答案：\n置信度：0.8"
            return "推理过程\n最终答案：42"

    agent = ReasoningAgent(client=FakeClient())
    result = agent.solve("计算40+2", {})
    assert result["final_response"] == "42"
    steps = [t["step"] for t in result["trace"]]
    assert steps == [
        "input",
        "classify",
        "plan",
        "tool_hints",
        "candidates",
        "verify",
        "solve",
        "finalize",
    ]
