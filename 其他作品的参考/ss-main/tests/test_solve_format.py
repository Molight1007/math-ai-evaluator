"""Tests for solve return format."""

import json

from user_agent import ReasoningAgent


class FakeClient:
    def chat(self, messages, temperature=0.2, max_tokens=4096):
        return "推理过程略。\n最终答案：42"


class ErrorClient:
    def chat(self, messages, temperature=0.2, max_tokens=4096):
        raise RuntimeError("API error")


def test_solve_returns_dict():
    agent = ReasoningAgent(client=FakeClient())
    result = agent.solve("计算 40+2。", {"idx": 0})
    assert isinstance(result, dict)


def test_solve_has_final_response():
    agent = ReasoningAgent(client=FakeClient())
    result = agent.solve("1+1=?", {})
    assert "final_response" in result
    assert isinstance(result["final_response"], str)
    assert result["final_response"].strip()


def test_solve_json_serializable():
    agent = ReasoningAgent(client=FakeClient())
    result = agent.solve("1+1=?", {})
    serialized = json.dumps(result, ensure_ascii=False)
    assert serialized


def test_solve_empty_problem():
    agent = ReasoningAgent(client=FakeClient())
    result = agent.solve("", {})
    assert result["final_response"] == "无法确定"


def test_solve_client_error():
    agent = ReasoningAgent(client=ErrorClient())
    result = agent.solve("1+1=?", {})
    assert isinstance(result, dict)
    assert result["final_response"].strip()


def test_solve_extracts_answer():
    agent = ReasoningAgent(client=FakeClient())
    result = agent.solve("计算 40+2。", {"idx": 0})
    assert result["final_response"] == "42"
