"""Rule-based math problem classification."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

PROFILE_KEYS = (
    "subject",
    "problem_type",
    "answer_form",
    "needs_proof",
    "needs_tool",
    "difficulty",
    "confidence",
)

SUBJECT_KEYWORDS: Dict[str, List[str]] = {
    "algebra": ["群", "环", "域", "有限域", "同态", "子群", "生成元"],
    "analysis": ["极限", "连续", "导数", "积分", "级数", "留数"],
    "probability": ["概率", "随机变量", "期望", "方差", "分布"],
    "combinatorics": ["排列", "组合", "计数", "递推"],
    "graph_theory": ["图", "路径", "最短路", "匹配"],
    "optimization": ["最大", "最小", "线性规划", "凸优化"],
}

PROOF_KEYWORDS = ["prove", "proof", "证明", "show that"]
CHOICE_KEYWORDS = ["选择", "选项"]
CHOICE_PATTERNS = [
    re.compile(r"\b[A-D]\.", re.IGNORECASE),
    re.compile(r"[（(][A-D][)）]"),
]
CALCULATION_KEYWORDS = ["求", "计算", "evaluate", "find", "calculate"]
FILL_BLANK_KEYWORDS = ["填空", "blank"]
EXPRESSION_KEYWORDS = ["表达式", "expression", "化简", "因式分解"]
TOOL_KEYWORDS = ["积分", "微分", "方程", "矩阵", "行列式", "符号"]

DEFAULT_PROFILE: Dict[str, Any] = {
    "subject": "other",
    "problem_type": "calculation",
    "answer_form": "integer_or_number",
    "needs_proof": False,
    "needs_tool": False,
    "difficulty": "medium",
    "confidence": 0.5,
}


def _contains_any(text: str, keywords: List[str]) -> bool:
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


def _match_choice(text: str) -> bool:
    if _contains_any(text, CHOICE_KEYWORDS):
        return True
    return any(p.search(text) for p in CHOICE_PATTERNS)


def _detect_problem_type(text: str) -> Tuple[str, bool, float]:
    """Return (problem_type, needs_proof, confidence_boost)."""
    if _contains_any(text, PROOF_KEYWORDS):
        return "proof", True, 0.35
    if _match_choice(text):
        return "choice", False, 0.3
    if _contains_any(text, FILL_BLANK_KEYWORDS):
        return "fill_blank", False, 0.25
    if _contains_any(text, CALCULATION_KEYWORDS):
        return "calculation", False, 0.2
    return "calculation", False, 0.0


def _detect_subject(text: str) -> Tuple[str, float]:
    """Return (subject, confidence_boost)."""
    matches: List[Tuple[str, int]] = []
    lower = text.lower()
    for subject, keywords in SUBJECT_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in lower)
        if count:
            matches.append((subject, count))
    if not matches:
        return "other", 0.0
    matches.sort(key=lambda x: x[1], reverse=True)
    best_subject, best_count = matches[0]
    boost = min(0.15 + 0.1 * (best_count - 1), 0.35)
    return best_subject, boost


def _detect_answer_form(problem_type: str, text: str) -> str:
    if problem_type == "proof":
        return "proof"
    if problem_type == "choice":
        return "choice"
    if _contains_any(text, EXPRESSION_KEYWORDS):
        return "expression"
    if problem_type == "fill_blank":
        return "expression"
    return "integer_or_number"


def _estimate_difficulty(text: str, subject: str) -> str:
    hard_signals = ["证明", "prove", "抽象", "同态", "留数", "凸优化", "递推"]
    easy_signals = ["计算", "求", "1+1", "evaluate", "calculate"]
    if _contains_any(text, hard_signals):
        return "hard"
    if _contains_any(text, easy_signals) and subject != "other":
        return "easy"
    return "medium"


def normalize_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure profile has all required keys with valid types."""
    profile = dict(DEFAULT_PROFILE)
    if not isinstance(raw, dict):
        return profile

    if raw.get("subject"):
        profile["subject"] = str(raw["subject"])
    if raw.get("problem_type"):
        profile["problem_type"] = str(raw["problem_type"])
    if raw.get("answer_form"):
        profile["answer_form"] = str(raw["answer_form"])
    if "needs_proof" in raw:
        profile["needs_proof"] = bool(raw["needs_proof"])
    if "needs_tool" in raw:
        profile["needs_tool"] = bool(raw["needs_tool"])
    if raw.get("difficulty"):
        profile["difficulty"] = str(raw["difficulty"])

    try:
        confidence = float(raw.get("confidence", profile["confidence"]))
    except (TypeError, ValueError):
        confidence = profile["confidence"]
    profile["confidence"] = max(0.0, min(1.0, confidence))

    if profile["problem_type"] == "proof":
        profile["needs_proof"] = True
    if profile["problem_type"] == "choice" and profile["answer_form"] == "integer_or_number":
        profile["answer_form"] = "choice"

    return profile


def rule_classify(problem: str, metadata: Optional[dict] = None) -> dict:
    """Classify a math problem using lightweight keyword rules."""
    metadata = metadata or {}
    text = problem.strip() if isinstance(problem, str) else ""

    problem_type, needs_proof, type_boost = _detect_problem_type(text)
    subject, subject_boost = _detect_subject(text)
    answer_form = _detect_answer_form(problem_type, text)
    needs_tool = _contains_any(text, TOOL_KEYWORDS)
    difficulty = _estimate_difficulty(text, subject)

    confidence = 0.45 + type_boost + subject_boost
    if metadata.get("subject") and subject == "other":
        meta_subject = str(metadata["subject"]).lower()
        subject_map = {
            "抽象代数": "algebra",
            "代数": "algebra",
            "分析": "analysis",
            "概率": "probability",
            "组合": "combinatorics",
            "图论": "graph_theory",
            "优化": "optimization",
        }
        for key, mapped in subject_map.items():
            if key in meta_subject or mapped in meta_subject:
                subject = mapped
                confidence += 0.15
                break

    confidence = min(confidence, 0.92)

    return normalize_profile(
        {
            "subject": subject,
            "problem_type": problem_type,
            "answer_form": answer_form,
            "needs_proof": needs_proof,
            "needs_tool": needs_tool,
            "difficulty": difficulty,
            "confidence": confidence,
        }
    )
