from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field


class MathQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)
    question_id: str = Field(default="unknown", min_length=1, max_length=256)


class ProblemParse(BaseModel):
    goal: str
    givens: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)


class ToolTrace(BaseModel):
    tool: Literal["python", "sympy", "none"]
    purpose: str
    status: Literal["success", "fail", "skipped"]
    summary: str


class FinalAnswer(BaseModel):
    type: Literal["number", "expression", "set", "proof", "algorithm", "text"]
    value: str
    boxed: str


class Verification(BaseModel):
    method: Literal[
        "symbolic_check",
        "numeric_check",
        "substitution",
        "logic_review",
        "self_review",
        "none",
    ]
    passed: bool
    notes: str


class SolveResult(BaseModel):
    question_id: str
    domain: str
    problem_type: str
    problem_parse: ProblemParse
    solution_plan: list[str] = Field(default_factory=list)
    visible_solution_steps: list[str] = Field(default_factory=list)
    tool_trace: list[ToolTrace] = Field(default_factory=list)
    final_answer: FinalAnswer
    verification: Verification
    didactic_hint: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["success", "partial", "fail"]
    error: str | None = None


# compatibility alias for older imports
MathResult = SolveResult


_SENSITIVE_KEYWORDS = (
    "api_key",
    "authorization",
    "bearer",
    "token",
    "secret",
    "password",
    ".env",
)
_RAW_SECRET_PATTERN = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{16,}\b")
_MAX_PROTOCOL_DEPTH = 20
_MAX_PROTOCOL_ITEMS = 1_000


def _sanitize_protocol_string(value: str) -> str:
    text = _RAW_SECRET_PATTERN.sub("[REDACTED]", value)
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*)([^\s,;]+)",
        r"\1[REDACTED]",
        text,
    )
    return re.sub(
        r"(?i)(bearer\s+)([^\s,;]+)",
        r"\1[REDACTED]",
        text,
    )


def _sanitize_protocol_value(
    value: Any,
    *,
    seen: set[int],
    depth: int,
) -> Any:
    if depth > _MAX_PROTOCOL_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return _sanitize_protocol_string(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        return "[BINARY REDACTED]"
    if isinstance(value, dict):
        object_id = id(value)
        if object_id in seen:
            return "[CIRCULAR]"
        seen.add(object_id)
        try:
            sanitized: dict[str, Any] = {}
            for index, (key, child) in enumerate(value.items()):
                if index >= _MAX_PROTOCOL_ITEMS:
                    sanitized["__truncated__"] = True
                    break
                try:
                    key_text = str(key)
                except Exception:
                    key_text = "[UNPRINTABLE KEY]"
                if any(k in key_text.lower() for k in _SENSITIVE_KEYWORDS):
                    sanitized[key_text] = "[REDACTED]"
                else:
                    sanitized[key_text] = _sanitize_protocol_value(
                        child,
                        seen=seen,
                        depth=depth + 1,
                    )
            return sanitized
        finally:
            seen.remove(object_id)
    if isinstance(value, (list, tuple, set, frozenset)):
        object_id = id(value)
        if object_id in seen:
            return "[CIRCULAR]"
        seen.add(object_id)
        try:
            items = []
            for index, child in enumerate(value):
                if index >= _MAX_PROTOCOL_ITEMS:
                    items.append("[TRUNCATED]")
                    break
                items.append(
                    _sanitize_protocol_value(
                        child,
                        seen=seen,
                        depth=depth + 1,
                    )
                )
            return items
        finally:
            seen.remove(object_id)
    try:
        return _sanitize_protocol_string(str(value))
    except Exception:
        return f"[UNSERIALIZABLE {type(value).__name__}]"


def sanitize_protocol_metadata(data: dict[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize_protocol_value(data, seen=set(), depth=0)
    return sanitized if isinstance(sanitized, dict) else {}


def to_jsonable(model: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        return model.model_dump()
    return sanitize_protocol_metadata(model)


class AgentStep(BaseModel):
    step_id: str
    agent_name: str
    role: str
    input_summary: str = ""
    output_summary: str = ""
    status: Literal["success", "partial", "fail", "skipped"]
    risk_flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.metadata = sanitize_protocol_metadata(self.metadata)


class ToolCallRecord(BaseModel):
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""
    status: Literal["success", "fail", "skipped"]
    latency_seconds: float | None = None
    error: str | None = None

    def model_post_init(self, __context: Any) -> None:
        self.parameters = sanitize_protocol_metadata(self.parameters)


class ProtocolVerifierResult(BaseModel):
    passed: bool
    method: Literal[
        "symbolic",
        "numeric",
        "substitution",
        "logic_review",
        "format_check",
        "weighted_vote",
        "self_review",
        "none",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
    suggested_action: Literal["stop", "refine", "fallback", "fail"]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.metadata = sanitize_protocol_metadata(self.metadata)


class CandidateAnswer(BaseModel):
    candidate_id: str
    source: str
    answer_type: str = "text"
    final_answer_value: str = ""
    final_answer_boxed: str = ""
    final_answer_type: str = "text"
    normalized_answer: str = ""
    verifier_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)
    verification_method: str = "none"
    verification_passed: bool = False
    selected: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.metadata = sanitize_protocol_metadata(self.metadata)


class WeightedVoteResult(BaseModel):
    selected_candidate_id: str | None = None
    selected_answer: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    cluster_summary: list[dict[str, Any]] = Field(default_factory=list)
    need_more_verification: bool = False
    issues: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        self.metadata = sanitize_protocol_metadata(self.metadata)


def make_agent_step(**kwargs: Any) -> AgentStep:
    return AgentStep(**kwargs)


def make_tool_call_record(**kwargs: Any) -> ToolCallRecord:
    return ToolCallRecord(**kwargs)


def make_failure_result(
    question_id: str, question: str, error_message: str
) -> SolveResult:
    return SolveResult(
        question_id=question_id,
        domain="unknown",
        problem_type="unknown",
        problem_parse=ProblemParse(goal=question, givens=[], symbols=[]),
        solution_plan=[],
        visible_solution_steps=[],
        tool_trace=[
            ToolTrace(
                tool="none",
                purpose="skip_due_to_error",
                status="fail",
                summary=error_message,
            )
        ],
        final_answer=FinalAnswer(type="text", value="", boxed=""),
        verification=Verification(
            method="none", passed=False, notes="No verification due to failure."
        ),
        didactic_hint="请先检查题目输入格式或稍后重试。",
        confidence=0.0,
        status="fail",
        error=error_message,
    )


def validate_result_dict(data: dict) -> SolveResult:
    return SolveResult.model_validate(data)
