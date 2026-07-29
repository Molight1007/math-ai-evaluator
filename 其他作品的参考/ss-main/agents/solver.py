"""Multi-candidate math solver."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import (
    CREATIVE_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    ENABLE_MULTI_CANDIDATE,
)
from prompts.solver_prompts import build_routed_solver_prompt, get_solver_prompt_route
from tools.answer_extractor import extract_final_answer

CANDIDATE_TEMPERATURES = (0.1, 0.3, 0.5)
DEFAULT_CONFIDENCE = 0.5

DIFFICULTY_COUNTS = {
    "easy": 1,
    "medium": 2,
    "hard": 3,
}


def _response_to_text(response: Any) -> str:
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


def candidate_count_for_profile(profile: Optional[dict]) -> int:
    """Decide how many candidates to generate from difficulty."""
    if not ENABLE_MULTI_CANDIDATE:
        return 1
    profile = profile or {}
    difficulty = str(profile.get("difficulty", "medium")).lower()
    return DIFFICULTY_COUNTS.get(difficulty, 2)


class Solver:
    """Generate multiple independent solution candidates."""

    def __init__(self, client: Any = None) -> None:
        self.client = client

    def _call_once(self, prompt: str, temperature: float) -> str:
        if self.client is None:
            return ""
        try:
            response = self.client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=DEFAULT_MAX_TOKENS,
            )
            return _response_to_text(response)
        except Exception:
            return ""

    def generate_candidates(
        self,
        problem: str,
        metadata: Optional[dict],
        profile: Optional[dict],
        plan: Optional[str],
        tool_hints=None,
    ) -> List[Dict[str, Any]]:
        """Generate independent solution candidates."""
        metadata = metadata or {}
        profile = profile or {}
        plan = plan or ""

        count = candidate_count_for_profile(profile)
        problem_type = profile.get("problem_type")
        answer_form = profile.get("answer_form")

        candidates: List[Dict[str, Any]] = []
        prompt_route = get_solver_prompt_route(profile)
        for i in range(count):
            candidate_id = f"candidate_{i + 1}"
            temperature = (
                CANDIDATE_TEMPERATURES[i]
                if i < len(CANDIDATE_TEMPERATURES)
                else CREATIVE_TEMPERATURE
            )
            prompt = build_routed_solver_prompt(
                problem=problem,
                profile=profile,
                plan=plan,
                candidate_id=candidate_id,
                tool_hints=tool_hints,
                metadata=metadata,
            )
            raw = self._call_once(prompt, temperature=temperature)
            answer = extract_final_answer(
                raw,
                problem_type=problem_type,
                answer_form=answer_form,
            )
            if not answer and raw:
                answer = raw.strip()

            candidates.append(
                {
                    "id": candidate_id,
                    "solution": raw,
                    "answer": answer,
                    "confidence": DEFAULT_CONFIDENCE,
                    "prompt_route": prompt_route,
                }
            )

        if not candidates:
            candidates.append(
                {
                    "id": "candidate_1",
                    "solution": "",
                    "answer": "",
                    "confidence": 0.0,
                    "prompt_route": prompt_route,
                }
            )

        return candidates
