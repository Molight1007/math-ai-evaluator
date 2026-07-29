"""Tests for multi-candidate Solver."""

from agents.solver import Solver, candidate_count_for_profile
from user_agent import ReasoningAgent


class FakeClient:
    def chat(self, messages, temperature=0.2, max_tokens=4096):
        return "推理过程\n最终答案：42"


def test_generate_candidates_returns_list():
    solver = Solver(client=FakeClient())
    candidates = solver.generate_candidates(
        problem="计算40+2",
        metadata={},
        profile={"difficulty": "medium", "problem_type": "calculation"},
        plan="计算并验证",
    )
    assert isinstance(candidates, list)
    assert len(candidates) >= 1


def test_candidate_has_required_fields():
    solver = Solver(client=FakeClient())
    candidates = solver.generate_candidates(
        problem="计算40+2",
        metadata={},
        profile={"difficulty": "easy"},
        plan="计算",
    )
    c = candidates[0]
    assert "id" in c
    assert "solution" in c
    assert "answer" in c
    assert c["answer"] == "42"


def test_difficulty_candidate_counts():
    assert candidate_count_for_profile({"difficulty": "easy"}) == 1
    assert candidate_count_for_profile({"difficulty": "medium"}) == 2
    assert candidate_count_for_profile({"difficulty": "hard"}) == 3
    assert candidate_count_for_profile({}) == 2


def test_hard_generates_three_candidates():
    solver = Solver(client=FakeClient())
    candidates = solver.generate_candidates(
        problem="证明题",
        metadata={},
        profile={"difficulty": "hard"},
        plan="证明",
    )
    assert len(candidates) == 3
    assert candidates[0]["id"] == "candidate_1"
    assert candidates[2]["id"] == "candidate_3"


def test_client_none_does_not_crash():
    solver = Solver(client=None)
    candidates = solver.generate_candidates(
        problem="计算1+1",
        metadata={},
        profile={"difficulty": "medium"},
        plan="计算",
    )
    assert isinstance(candidates, list)
    assert len(candidates) == 2
    assert candidates[0]["id"] == "candidate_1"


def test_solver_integrated_in_agent():
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
