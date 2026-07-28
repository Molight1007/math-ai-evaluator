"""Competition entry point — ReasoningAgent."""

from __future__ import annotations

from agents.reasoning_agent_core import MathReasoningAgentCore
from schemas.result_schema import make_error_result, make_success_result
from tools.answer_normalizer import normalize_final_response


class ReasoningAgent:
    """Math reasoning agent for competition platform."""

    def __init__(self, client, *args, **kwargs):
        self.client = client
        self.core = MathReasoningAgentCore(client=client)

    def solve(self, problem: str, metadata: dict) -> dict:
        try:
            if not isinstance(problem, str) or not problem.strip():
                return make_success_result(
                    "无法确定",
                    trace=[{"step": "input_check", "content": "problem 为空或格式错误"}],
                )

            if metadata is None or not isinstance(metadata, dict):
                metadata = {}

            result = self.core.solve(problem=problem, metadata=metadata)

            final_response = normalize_final_response(result.get("final_response", ""))
            if not final_response:
                final_response = "无法确定"

            return make_success_result(
                final_response,
                trace=result.get("trace", []),
            )

        except Exception as e:
            return make_error_result(e)
