"""Core math reasoning orchestrator (MVP)."""

from __future__ import annotations

from typing import Any, Dict, List

from agents.planner import Planner
from agents.refiner import Refiner, should_refine
from agents.router import ProblemRouter
from agents.solver import Solver
from agents.verifier import Verifier
from config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
)
from schemas.result_schema import make_success_result, make_trace_step, safe_to_string
from tools.answer_extractor import extract_final_answer
from tools.answer_normalizer import normalize_final_response
from tools.math_utils import build_tool_hints, tool_hints_to_text


def response_to_text(response: Any) -> str:
    """Convert various client response formats to plain text."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        if "content" in response:
            return str(response["content"])
        if "text" in response:
            return str(response["text"])
        if "choices" in response:
            try:
                return str(response["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError):
                return str(response)
    return str(response)


def call_llm(
    client: Any,
    messages: List[Dict[str, str]],
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Safely call client.chat and return text."""
    try:
        response = client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response_to_text(response)
    except Exception:
        return ""


def _summarize_candidates(candidates: List[dict]) -> str:
    """Short candidate summary for traces (no full solutions)."""
    parts = []
    route = ""
    for c in candidates or []:
        cid = c.get("id", "?")
        answer = safe_to_string(c.get("answer", ""), max_chars=80)
        parts.append(f"{cid}:{answer or '(empty)'}")
        if not route and c.get("prompt_route"):
            route = str(c.get("prompt_route"))
    route_part = f"prompt_route={route}; " if route else ""
    return (
        f"{route_part}generated {len(candidates or [])} candidates; "
        + "; ".join(parts)
    )


def _summarize_solution(text: str, selected_id: str, max_chars: int = 400) -> str:
    """Keep solve-step content short — never dump full LLM output."""
    raw = safe_to_string(text or "", max_chars=max_chars)
    if not raw.strip():
        return f"(empty response from {selected_id})"
    return f"from {selected_id}: {raw}"


class MathReasoningAgentCore:
    """Minimal single-round math reasoning agent."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.router = ProblemRouter(client=client)
        self.planner = Planner(client=client)
        self.solver = Solver(client=client)
        self.verifier = Verifier(client=client)
        self.refiner = Refiner(client=client)

    def solve(self, problem: str, metadata: dict) -> dict:
        trace: List[Dict[str, str]] = []

        if not isinstance(problem, str) or not problem.strip():
            return make_success_result(
                "无法确定",
                trace=[make_trace_step("input_check", "problem 为空")],
            )

        if metadata is None or not isinstance(metadata, dict):
            metadata = {}

        trace.append(make_trace_step("input", f"problem_len={len(problem)}"))

        profile = self.router.classify(problem=problem, metadata=metadata)
        trace.append(
            make_trace_step(
                "classify",
                {
                    "subject": profile.get("subject"),
                    "problem_type": profile.get("problem_type"),
                    "difficulty": profile.get("difficulty"),
                },
            )
        )

        plan = self.planner.create_plan(
            problem=problem,
            metadata=metadata,
            profile=profile,
        )
        trace.append(make_trace_step("plan", plan))

        tool_hints = build_tool_hints(problem=problem, profile=profile)
        trace.append(
            make_trace_step(
                "tool_hints",
                tool_hints_to_text(tool_hints) or tool_hints or {},
            )
        )

        candidates = self.solver.generate_candidates(
            problem=problem,
            metadata=metadata,
            profile=profile,
            plan=plan,
            tool_hints=tool_hints,
        )
        trace.append(make_trace_step("candidates", _summarize_candidates(candidates)))

        best = self.verifier.verify_candidates(
            problem=problem,
            candidates=candidates,
            profile=profile,
            metadata=metadata,
        )
        best_id = best.get("id", "candidate_1") or "candidate_1"
        best_score = float(best.get("score", 0.0) or 0.0)
        vote_count = int(best.get("vote_count", 1) or 1)
        trace.append(
            make_trace_step(
                "verify",
                f"selected {best_id} score={best_score:.2f} vote_count={vote_count}",
            )
        )

        selected = best
        if should_refine(best):
            reason = (
                "need_refine=True"
                if best.get("need_refine")
                else f"score < threshold ({best_score:.2f})"
            )
            selected = self.refiner.refine(
                problem=problem,
                candidate=best,
                issues=best.get("issues") or [],
                profile=profile,
                plan=plan,
                metadata=metadata,
            )
            trace.append(
                make_trace_step("refine", f"candidate refined because {reason}")
            )

        raw_response = selected.get("solution", "") or ""
        extracted = selected.get("answer", "") or ""
        selected_id = selected.get("id", best_id) or best_id

        if not extracted and raw_response:
            extracted = extract_final_answer(raw_response) or raw_response.strip()

        trace.append(
            make_trace_step(
                "solve",
                _summarize_solution(raw_response, selected_id=selected_id),
            )
        )

        final_response = normalize_final_response(extracted)
        trace.append(make_trace_step("finalize", final_response))

        return make_success_result(final_response, trace=trace)
