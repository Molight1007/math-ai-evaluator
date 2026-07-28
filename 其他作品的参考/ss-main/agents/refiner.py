"""One-shot answer refinement for low-scoring candidates."""

from __future__ import annotations

from typing import Any, List, Optional

from config import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, ENABLE_REFLECTION
from prompts.refiner_prompts import build_refiner_prompt
from tools.answer_extractor import extract_final_answer

REFINE_SCORE_THRESHOLD = 0.6
DEFAULT_REFINED_CONFIDENCE = 0.55


def should_refine(candidate: Optional[dict], threshold: float = REFINE_SCORE_THRESHOLD) -> bool:
    """Return True if candidate needs one refine pass."""
    if not ENABLE_REFLECTION:
        return False
    candidate = candidate or {}
    score = float(candidate.get("score", 0.0) or 0.0)
    need_refine = bool(candidate.get("need_refine", False))
    return need_refine or score < threshold


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


def _refined_id(candidate: dict) -> str:
    base = str(candidate.get("id") or "candidate_1").strip() or "candidate_1"
    if base.endswith("_refined"):
        return base
    return f"{base}_refined"


def rule_refine(candidate: Optional[dict], issues: Optional[List[Any]] = None) -> dict:
    """Fallback refine without LLM: keep content, mark as refined."""
    candidate = candidate or {}
    answer = str(candidate.get("answer") or "").strip()
    solution = str(candidate.get("solution") or "").strip()
    confidence = float(candidate.get("confidence", DEFAULT_REFINED_CONFIDENCE) or 0.0)
    if not answer and solution:
        answer = extract_final_answer(solution) or ""
    return {
        "id": _refined_id(candidate),
        "solution": solution,
        "answer": answer,
        "confidence": max(0.0, min(1.0, confidence if confidence > 0 else DEFAULT_REFINED_CONFIDENCE)),
    }


class Refiner:
    """Refine a weak candidate at most once."""

    def __init__(self, client: Any = None) -> None:
        self.client = client

    def _llm_refine(
        self,
        problem: str,
        candidate: dict,
        issues: List[Any],
        profile: dict,
        plan: str,
        metadata: dict,
    ) -> Optional[dict]:
        if self.client is None:
            return None
        prompt = build_refiner_prompt(
            problem=problem,
            candidate=candidate,
            issues=issues,
            profile=profile,
            plan=plan,
            metadata=metadata,
        )
        try:
            response = self.client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=DEFAULT_MAX_TOKENS,
            )
            raw = _response_to_text(response).strip()
            if not raw:
                return None
            problem_type = (profile or {}).get("problem_type")
            answer_form = (profile or {}).get("answer_form")
            answer = extract_final_answer(
                raw,
                problem_type=problem_type,
                answer_form=answer_form,
            )
            if not answer:
                answer = raw.strip()
            return {
                "id": _refined_id(candidate),
                "solution": raw,
                "answer": answer,
                "confidence": DEFAULT_REFINED_CONFIDENCE,
            }
        except Exception:
            return None

    def refine(
        self,
        problem: str,
        candidate: dict,
        issues: Optional[List[Any]],
        profile: Optional[dict],
        plan: Optional[str],
        metadata: Optional[dict] = None,
    ) -> dict:
        """Return a refined candidate (at most one LLM attempt)."""
        candidate = candidate or {}
        issues = list(issues or candidate.get("issues") or [])
        profile = profile or {}
        plan = plan or ""
        metadata = metadata or {}

        llm_result = self._llm_refine(
            problem=problem,
            candidate=candidate,
            issues=issues,
            profile=profile,
            plan=plan,
            metadata=metadata,
        )
        if llm_result:
            return llm_result
        return rule_refine(candidate, issues)
