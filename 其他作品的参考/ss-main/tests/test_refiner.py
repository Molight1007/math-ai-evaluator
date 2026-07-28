"""Tests for Refiner module."""

from agents.refiner import Refiner, should_refine
from user_agent import ReasoningAgent


def test_low_score_should_refine():
    assert should_refine(
        {
            "id": "candidate_1",
            "answer": "",
            "solution": "",
            "score": 0.2,
            "need_refine": True,
            "issues": ["empty_answer"],
        }
    )


def test_high_score_should_not_refine():
    assert not should_refine(
        {
            "id": "candidate_1",
            "answer": "42",
            "solution": "最终答案：42",
            "score": 0.9,
            "need_refine": False,
            "issues": [],
        }
    )


def test_refine_with_fake_client():
    class FakeClient:
        def chat(self, messages, temperature=0.2, max_tokens=4096):
            return "重新推导\n最终答案：42"

    refiner = Refiner(client=FakeClient())
    result = refiner.refine(
        problem="计算40+2",
        candidate={
            "id": "candidate_1",
            "answer": "41",
            "solution": "错误推理",
            "score": 0.3,
            "issues": ["可能计算错误"],
        },
        issues=["可能计算错误"],
        profile={"difficulty": "easy", "problem_type": "calculation"},
        plan="重新计算",
    )
    assert result["id"] == "candidate_1_refined"
    assert result["answer"] == "42"
    assert "solution" in result


def test_refine_client_none_fallback():
    refiner = Refiner(client=None)
    result = refiner.refine(
        problem="计算1+1",
        candidate={
            "id": "candidate_2",
            "answer": "2",
            "solution": "1+1=2",
            "score": 0.4,
            "issues": ["low_score"],
        },
        issues=["low_score"],
        profile={},
        plan="检查计算",
    )
    assert result["id"] == "candidate_2_refined"
    assert result["answer"] == "2"
    assert isinstance(result["confidence"], float)


def test_agent_skips_refine_for_high_quality():
    class FakeClient:
        def chat(self, messages, temperature=0.2, max_tokens=4096):
            content = messages[0]["content"] if messages else ""
            if "请严格检查以下数学题的候选解答" in content:
                return "正确性：correct\n问题：无\n修正答案：\n置信度：0.9"
            if "请修正以下数学题的候选解答" in content:
                raise AssertionError("refine should not be called")
            return "推理过程\n最终答案：42"

    agent = ReasoningAgent(client=FakeClient())
    result = agent.solve("计算40+2", {})
    assert result["final_response"] == "42"
    steps = [t["step"] for t in result["trace"]]
    assert "refine" not in steps
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


def test_agent_triggers_refine_for_low_quality():
    class FakeClient:
        def __init__(self):
            self.solver_calls = 0

        def chat(self, messages, temperature=0.2, max_tokens=4096):
            content = messages[0]["content"] if messages else ""
            if "请严格检查以下数学题的候选解答" in content:
                return "正确性：uncertain\n问题：答案可疑\n修正答案：\n置信度：0.2"
            if "请修正以下数学题的候选解答" in content:
                return "重新检查后得到答案\n最终答案：42"
            # First solver responses are weak/empty-ish to force low score path
            self.solver_calls += 1
            if self.solver_calls == 1:
                return "无法回答"
            return "最终答案：42"

    agent = ReasoningAgent(client=FakeClient())
    result = agent.solve("计算40+2", {})
    steps = [t["step"] for t in result["trace"]]
    assert "refine" in steps
    assert result["final_response"] == "42"
