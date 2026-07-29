"""Candidate answer verification — voting score with optional LLM."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional

from config import DEFAULT_MAX_TOKENS, FAST_TEMPERATURE
from prompts.verifier_prompts import build_verifier_prompt
from tools.voting import normalize_for_vote, score_candidate, select_best_candidate

UNCERTAIN_PHRASES = ("无法回答", "不知道", "不会", "无法确定")


def _clamp(score: float) -> float:
    return max(0.0, min(1.0, score))


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


def _normalize_answer(answer: Any) -> str:
    if answer is None:
        return ""
    return str(answer).strip()


def rule_score_candidate(
    candidate: dict,
    answer_counts: Counter,
) -> Dict[str, Any]:
    """Legacy-compatible rule scorer used by older unit tests.

    Prefer select_best_candidate / score_candidate for new logic.
    """
    answer = _normalize_answer(candidate.get("answer"))
    solution = str(candidate.get("solution") or "").strip()
    issues: List[str] = []

    # Build a synthetic majority group when consensus exists.
    vote_group = None
    if answer and answer_counts.get(answer, 0) >= 2:
        vote_group = {
            "normalized_answer": normalize_for_vote(answer),
            "members": [candidate],
            "count": answer_counts.get(answer, 1),
        }

    score = score_candidate(candidate, vote_group)
    # Extra consensus bump for identical raw answers (legacy expectation).
    if answer and answer_counts.get(answer, 0) >= 2:
        score = _clamp(score + 0.05)

    if not answer:
        issues.append("empty_answer")
    if not solution:
        issues.append("empty_solution")
    text_blob = f"{solution}\n{answer}"
    if any(phrase in text_blob for phrase in UNCERTAIN_PHRASES):
        issues.append("uncertain_language")

    need_refine = score < 0.6 or bool(issues)
    return {
        "id": candidate.get("id", ""),
        "answer": answer,
        "solution": solution,
        "score": score,
        "issues": issues,
        "need_refine": need_refine,
    }


def parse_llm_verification(text: str) -> Optional[Dict[str, Any]]:
    """Parse verifier LLM output into structured fields."""
    if not text or not text.strip():
        return None

    correctness_match = re.search(
        r"正确性[：:]\s*(correct|wrong|uncertain|正确|错误|不确定)",
        text,
        re.IGNORECASE,
    )
    if not correctness_match:
        return None

    raw = correctness_match.group(1).lower()
    mapping = {
        "correct": "correct",
        "正确": "correct",
        "wrong": "wrong",
        "错误": "wrong",
        "uncertain": "uncertain",
        "不确定": "uncertain",
    }
    correctness = mapping.get(raw, "uncertain")

    issues_match = re.search(r"问题[：:]\s*(.*?)(?:\n|$)", text)
    fix_match = re.search(r"修正答案[：:]\s*(.*?)(?:\n|$)", text)
    conf_match = re.search(r"置信度[：:]\s*([0-9]*\.?[0-9]+)", text)

    issues: List[str] = []
    if issues_match:
        issue_text = issues_match.group(1).strip()
        if issue_text and issue_text not in ("无", "无。", "none", "None", "-"):
            issues.append(issue_text)

    try:
        confidence = float(conf_match.group(1)) if conf_match else 0.5
    except (TypeError, ValueError, AttributeError):
        confidence = 0.5
    confidence = _clamp(confidence)

    corrected = ""
    if fix_match:
        corrected = fix_match.group(1).strip()

    return {
        "correctness": correctness,
        "issues": issues,
        "corrected_answer": corrected,
        "confidence": confidence,
    }


class Verifier:
    """Select the best candidate via voting/scoring and optional LLM checks."""

    def __init__(self, client: Any = None) -> None:
        self.client = client

    def _llm_verify_one(self, problem: str, candidate: dict, metadata: dict) -> Optional[dict]:
        if self.client is None:
            return None
        prompt = build_verifier_prompt(
            problem=problem,
            candidate=candidate,
            metadata=metadata,
        )
        try:
            response = self.client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=FAST_TEMPERATURE,
                max_tokens=min(512, DEFAULT_MAX_TOKENS),
            )
            return parse_llm_verification(_response_to_text(response))
        except Exception:
            return None

    def _apply_llm_adjustment(
        self,
        scored: dict,
        llm_result: dict,
    ) -> dict:
        """Adjust score lightly; do not overturn voting selection identity."""
        updated = dict(scored)
        correctness = llm_result.get("correctness", "uncertain")
        confidence = float(llm_result.get("confidence", 0.5))
        issues = list(updated.get("issues") or [])
        issues.extend(llm_result.get("issues") or [])

        if correctness == "correct":
            updated["score"] = _clamp(float(updated.get("score", 0.0)) + 0.15 * confidence)
        elif correctness == "wrong":
            updated["score"] = _clamp(float(updated.get("score", 0.0)) - 0.25 * confidence)
            corrected = (llm_result.get("corrected_answer") or "").strip()
            if corrected:
                updated["answer"] = corrected
                issues.append("llm_corrected")
        else:
            updated["score"] = _clamp(float(updated.get("score", 0.0)) - 0.05)

        updated["issues"] = issues
        if not str(updated.get("answer") or "").strip():
            updated["need_refine"] = True
        else:
            # Keep LLM-reported issues able to trigger refine.
            updated["need_refine"] = (
                float(updated.get("score", 0.0)) < 0.6 or bool(issues)
            )
        return updated

    def verify_candidates(
        self,
        problem: str,
        candidates: List[dict],
        profile: Optional[dict],
        metadata: Optional[dict] = None,
    ) -> dict:
        """Score candidates with voting and return the best one."""
        metadata = metadata or {}
        profile = profile or {}
        candidates = candidates or []

        best = select_best_candidate(candidates)
        if best.get("id") == "fallback" and not candidates:
            return {
                "id": "",
                "answer": "",
                "solution": "",
                "score": 0.0,
                "vote_count": 0,
                "normalized_answer": "",
                "issues": ["no_candidates"],
                "need_refine": True,
            }

        # Optional LLM verify on the voting winner only — score nudge, keep selection.
        if self.client is not None and candidates:
            llm_result = self._llm_verify_one(problem, best, metadata)
            if llm_result:
                best = self._apply_llm_adjustment(best, llm_result)

        # Ensure required return fields.
        return {
            "id": best.get("id", ""),
            "answer": best.get("answer", ""),
            "solution": best.get("solution", ""),
            "score": float(best.get("score", 0.0) or 0.0),
            "vote_count": int(best.get("vote_count", 1) or 1),
            "normalized_answer": best.get("normalized_answer", ""),
            "issues": list(best.get("issues") or []),
            "need_refine": bool(best.get("need_refine")),
            "confidence": best.get("confidence", 0.5),
        }
