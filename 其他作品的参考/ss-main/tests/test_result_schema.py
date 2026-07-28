"""Tests for result schema / trace safety helpers."""

from __future__ import annotations

import json

from schemas.result_schema import (
    ensure_json_serializable,
    make_error_result,
    make_success_result,
    make_trace_step,
    redact_sensitive,
    trim_trace,
)
from user_agent import ReasoningAgent


def test_make_trace_step_handles_dict():
    step = make_trace_step("classify", {"a": 1})
    assert step["step"] == "classify"
    assert isinstance(step["content"], str)
    assert "a" in step["content"]


def test_make_trace_step_handles_exception():
    step = make_trace_step("error", ValueError("boom"))
    assert isinstance(step["content"], str)
    assert "ValueError" in step["content"]
    assert "boom" in step["content"]


def test_redact_sensitive_sk_token():
    text = redact_sensitive("key=sk-abcdefghijklmnop")
    assert "sk-abcdef" not in text
    assert "[REDACTED_KEY]" in text


def test_trim_trace_limits_steps():
    long_trace = [{"step": f"s{i}", "content": f"c{i}"} for i in range(50)]
    trimmed = trim_trace(long_trace, max_steps=10)
    assert len(trimmed) <= 10
    assert all(isinstance(t["content"], str) for t in trimmed)


def test_make_success_result_non_empty():
    result = make_success_result("", trace=[])
    assert result["final_response"] == "无法确定"
    result2 = make_success_result("72", trace=[{"step": "x", "content": "y"}])
    assert result2["final_response"] == "72"


def test_make_error_result_json_dumps():
    result = make_error_result(RuntimeError("fail"), trace=[{"step": "a", "content": "b"}])
    serialized = json.dumps(result, ensure_ascii=False)
    assert serialized
    assert result["final_response"] == "无法确定"


def test_ensure_json_serializable_custom_object():
    class Obj:
        def __str__(self):
            return "obj"

    data = ensure_json_serializable({"x": Obj(), "y": [1, Obj()]})
    json.dumps(data)
    assert data["x"] == "obj"


def test_reasoning_agent_result_json_dumps():
    class FakeClient:
        def chat(self, messages, temperature=0.2, max_tokens=4096):
            return "最终答案：42"

    agent = ReasoningAgent(client=FakeClient())
    result = agent.solve("1+1", {})
    json.dumps(result, ensure_ascii=False)
    assert result["final_response"].strip()
    assert isinstance(result["trace"], list)


def test_trace_redacts_intern_api_key():
    step = make_trace_step(
        "debug",
        "INTERN_API_KEY=supersecrettokenvalue123 && Bearer abcdefghijklmnop",
    )
    assert "supersecrettokenvalue123" not in step["content"]
    assert "abcdefghijklmnop" not in step["content"] or "[REDACTED]" in step["content"]
    assert "INTERN_API_KEY=[REDACTED_KEY]" in step["content"] or "[REDACTED" in step["content"]
