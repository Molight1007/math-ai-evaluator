"""Candidate answer voting and scoring helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from tools.sympy_tools import compare_expr, safe_sympify

UNCERTAIN_TOKENS = (
    "不知道",
    "无法回答",
    "不会",
    "无法确定",
    "cannot solve",
    "uncertain",
    "maybe",
)

BOXED_PATTERN = re.compile(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}")
FRAC_PATTERN = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
MARKDOWN_FENCE_PATTERN = re.compile(
    r"```(?:json|python|text|latex|math)?\s*([\s\S]*?)```",
    re.IGNORECASE,
)
PREFIX_PATTERN = re.compile(
    r"^(?:最终答案|答案是|答案|Answer)[：:\s]*",
    re.IGNORECASE,
)


def _clamp(score: float) -> float:
    return max(0.0, min(1.0, float(score)))


def normalize_for_vote(answer: str) -> str:
    """Normalize an answer string for voting comparisons."""
    try:
        if answer is None:
            return ""
        text = str(answer).strip()
        if not text:
            return ""

        fence = MARKDOWN_FENCE_PATTERN.search(text)
        if fence:
            text = fence.group(1).strip()
        text = re.sub(r"^```(?:\w+)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        boxed = BOXED_PATTERN.search(text)
        if boxed:
            text = boxed.group(1)

        text = text.replace("$", "")
        text = PREFIX_PATTERN.sub("", text.strip())
        text = re.sub(r"\s+", " ", text).strip()
        text = text.lower()
        text = text.rstrip("。.!！?？;；,，")
        return text.strip()
    except Exception:
        return ""


def _latex_frac_to_slash(text: str) -> str:
    try:
        prev = None
        while prev != text:
            prev = text
            text = FRAC_PATTERN.sub(r"(\1)/(\2)", text)
        return text
    except Exception:
        return text


def are_answers_equivalent(a: str, b: str) -> bool:
    """Return True if two answers are equivalent for voting."""
    try:
        na = normalize_for_vote(a)
        nb = normalize_for_vote(b)
        if not na and not nb:
            return True
        if not na or not nb:
            return False
        if na == nb:
            return True

        a_sym = _latex_frac_to_slash(na)
        b_sym = _latex_frac_to_slash(nb)
        if a_sym == b_sym:
            return True

        if safe_sympify(a_sym) is not None and safe_sympify(b_sym) is not None:
            eq = compare_expr(a_sym, b_sym)
            if eq is True:
                return True

        return False
    except Exception:
        return False


def group_equivalent_answers(candidates: List[dict]) -> List[dict]:
    """Group candidates by equivalent answers."""
    groups: List[dict] = []
    try:
        for candidate in candidates or []:
            answer = normalize_for_vote(candidate.get("answer", ""))
            placed = False
            for group in groups:
                rep = group.get("normalized_answer", "")
                # Empty answers only group with other empties via exact match.
                if (not answer and not rep) or (
                    answer
                    and rep
                    and are_answers_equivalent(answer, rep)
                ):
                    group["members"].append(candidate)
                    group["count"] = len(group["members"])
                    placed = True
                    break
            if not placed:
                groups.append(
                    {
                        "normalized_answer": answer,
                        "members": [candidate],
                        "count": 1,
                    }
                )
    except Exception:
        return []
    return groups


def majority_vote(candidates: List[dict]) -> Optional[dict]:
    """Return the largest equivalent-answer group."""
    try:
        if not candidates:
            return None
        groups = group_equivalent_answers(candidates)
        if not groups:
            return None
        # Prefer non-empty answers when counts tie.
        groups_sorted = sorted(
            groups,
            key=lambda g: (
                g.get("count", 0),
                1 if g.get("normalized_answer") else 0,
            ),
            reverse=True,
        )
        return groups_sorted[0]
    except Exception:
        return None


def score_candidate(
    candidate: dict,
    vote_group: Optional[dict] = None,
) -> float:
    """Score one candidate with voting-aware bonuses/penalties."""
    try:
        answer = str(candidate.get("answer") or "").strip()
        solution = str(candidate.get("solution") or "").strip()
        norm = normalize_for_vote(answer)
        text_blob = f"{solution}\n{answer}".lower()
        score = 0.0

        if answer:
            score += 0.25
        else:
            score -= 0.5

        if solution:
            score += 0.15
        else:
            score -= 0.2

        if vote_group and candidate in vote_group.get("members", []):
            score += 0.25
            if int(vote_group.get("count", 1) or 1) >= 2:
                score += 0.05
        elif vote_group:
            # Also match by id when object identity differs.
            member_ids = {
                str(m.get("id")) for m in vote_group.get("members", []) if isinstance(m, dict)
            }
            if str(candidate.get("id", "")) in member_ids and candidate.get("id"):
                score += 0.25
                if int(vote_group.get("count", 1) or 1) >= 2:
                    score += 0.05

        uncertain = any(tok.lower() in text_blob for tok in UNCERTAIN_TOKENS)
        if not uncertain:
            score += 0.15
        else:
            score -= 0.3

        if "confidence" in candidate and candidate.get("confidence") is not None:
            try:
                conf = float(candidate.get("confidence"))
                score += min(max(conf, 0.0), 1.0) * 0.1
            except (TypeError, ValueError):
                pass

        # Tiny tie-breaker favoring shorter explicit answers.
        if norm and len(norm) <= 20:
            score += 0.02

        return _clamp(score)
    except Exception:
        return 0.0


def _candidate_issues(candidate: dict, score: float) -> List[str]:
    issues: List[str] = []
    answer = str(candidate.get("answer") or "").strip()
    solution = str(candidate.get("solution") or "").strip()
    if not answer:
        issues.append("empty_answer")
    if not solution:
        issues.append("empty_solution")
    blob = f"{solution}\n{answer}".lower()
    if any(tok.lower() in blob for tok in UNCERTAIN_TOKENS):
        issues.append("uncertain_language")
    if score < 0.6:
        issues.append("low_score")
    return issues


def select_best_candidate(candidates: List[dict]) -> dict:
    """Select the best candidate using voting + scoring."""
    fallback = {
        "id": "fallback",
        "answer": "无法确定",
        "solution": "",
        "score": 0.0,
        "vote_count": 0,
        "normalized_answer": "",
        "issues": ["no candidates"],
        "need_refine": True,
        "confidence": 0.0,
    }

    try:
        if not candidates:
            return fallback

        majority = majority_vote(candidates)
        groups = group_equivalent_answers(candidates)
        vote_count_map: Dict[str, int] = {}
        norm_map: Dict[str, str] = {}
        for group in groups:
            for member in group.get("members", []):
                cid = str(member.get("id", ""))
                vote_count_map[cid] = int(group.get("count", 1))
                norm_map[cid] = str(group.get("normalized_answer", ""))

        scored_rows: List[dict] = []
        for candidate in candidates:
            cid = str(candidate.get("id", ""))
            score = score_candidate(candidate, majority)
            vote_count = vote_count_map.get(cid, 1)
            normalized = norm_map.get(cid, normalize_for_vote(candidate.get("answer", "")))
            issues = _candidate_issues(candidate, score)
            need_refine = (
                score < 0.6
                or not str(candidate.get("answer") or "").strip()
                or "uncertain_language" in issues
            )
            row = dict(candidate)
            row.update(
                {
                    "score": score,
                    "vote_count": vote_count,
                    "normalized_answer": normalized,
                    "issues": issues,
                    "need_refine": need_refine,
                }
            )
            scored_rows.append(row)

        def sort_key(row: dict):
            answer = str(row.get("answer") or "")
            return (
                float(row.get("score", 0.0)),
                int(row.get("vote_count", 0)),
                -len(answer.strip()),
            )

        scored_rows.sort(key=sort_key, reverse=True)
        best = scored_rows[0]

        # If all candidates are poor, force refine.
        if all(float(r.get("score", 0.0)) < 0.6 for r in scored_rows):
            best["need_refine"] = True
            if "low_score" not in best["issues"]:
                best["issues"] = list(best.get("issues") or []) + ["low_score"]

        return best
    except Exception:
        return fallback
