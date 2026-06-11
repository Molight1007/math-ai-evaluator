"""
Data models for the Math Agent Evaluator.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Problem:
    id: str
    question: str
    domain: Optional[str] = None
    reference_answer: Optional[str] = None


@dataclass
class InferenceResult:
    problem_id: str
    question: str
    answer: str = ""
    reasoning: str = ""
    steps: list[str] = field(default_factory=list)
    verification: str = ""
    raw_response: str = ""
    tokens_used: int = 0
    latency_seconds: float = 0.0
    error: Optional[str] = None


@dataclass
class JudgeResult:
    problem_id: str
    is_correct: bool = False
    confidence: float = 0.0
    explanation: str = ""
    error_type: Optional[str] = None
    correct_answer: Optional[str] = None
    raw_response: str = ""
    tokens_used: int = 0
    latency_seconds: float = 0.0
    error: Optional[str] = None


@dataclass
class EvaluationResult:
    problem_id: str
    question: str
    domain: Optional[str] = None
    reference_answer: Optional[str] = None
    intern_answer: str = ""
    intern_reasoning: str = ""
    intern_steps: list[str] = field(default_factory=list)
    intern_verification: str = ""
    is_correct: bool = False
    confidence: float = 0.0
    judge_explanation: str = ""
    error_type: Optional[str] = None
    correct_answer_judge: Optional[str] = None
    inference_tokens: int = 0
    judge_tokens: int = 0
    inference_latency: float = 0.0
    judge_latency: float = 0.0
    inference_error: Optional[str] = None
    judge_error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
