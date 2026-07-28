"""Result schema helpers for safe, JSON-serializable agent outputs."""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional

from config import MAX_FINAL_RESPONSE_CHARS, MAX_TRACE_CHARS_PER_STEP

FALLBACK_ANSWER = "无法确定"
DEFAULT_TRACE_MAX_STEPS = 30
TRUNCATION_SUFFIX = "...[truncated]"

# Sensitive patterns to redact from traces / responses.
_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b"),
    re.compile(r"(?i)\bINTERN_API_KEY\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bAPI[_-]?KEY\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bAuthorization\s*[:=]\s*\S+"),
    # Long opaque tokens (hex/base64-like), keep conservative.
    re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"),
]


def safe_to_string(obj: Any, max_chars: int = 2000) -> str:
    """Convert any object to a truncated safe string."""
    try:
        if obj is None:
            text = ""
        elif isinstance(obj, str):
            text = obj
        elif isinstance(obj, BaseException):
            text = f"{type(obj).__name__}: {obj}"
        elif isinstance(obj, (dict, list, tuple)):
            try:
                text = json.dumps(obj, ensure_ascii=False, default=str)
            except Exception:
                text = str(obj)
        elif isinstance(obj, (int, float, bool)):
            text = str(obj)
        else:
            text = str(obj)
    except Exception:
        try:
            text = str(obj)
        except Exception:
            text = "<unprintable>"

    if max_chars is None or max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    keep = max(0, max_chars - len(TRUNCATION_SUFFIX))
    return text[:keep] + TRUNCATION_SUFFIX


def redact_sensitive(text: str) -> str:
    """Redact API keys / tokens from text."""
    if not isinstance(text, str) or not text:
        return "" if text is None else str(text) if not isinstance(text, str) else text
    try:
        result = text
        result = re.sub(r"(?i)\bsk-[A-Za-z0-9_\-]{8,}\b", "[REDACTED_KEY]", result)
        result = re.sub(
            r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*",
            "Bearer [REDACTED]",
            result,
        )
        result = re.sub(
            r"(?i)\bINTERN_API_KEY\s*[:=]\s*\S+",
            "INTERN_API_KEY=[REDACTED_KEY]",
            result,
        )
        result = re.sub(
            r"(?i)\bAPI[_-]?KEY\s*[:=]\s*\S+",
            "API_KEY=[REDACTED_KEY]",
            result,
        )
        result = re.sub(
            r"(?i)\bAuthorization\s*[:=]\s*\S+",
            "Authorization=[REDACTED]",
            result,
        )
        # Long opaque tokens — avoid redacting math-ish short strings.
        result = re.sub(r"\b[A-Za-z0-9_\-]{48,}\b", "[REDACTED_TOKEN]", result)
        return result
    except Exception:
        return text


def make_trace_step(
    step: str,
    content: Any,
    max_chars: int = MAX_TRACE_CHARS_PER_STEP,
) -> dict:
    """Build a normalized trace step with string content."""
    step_str = safe_to_string(step, max_chars=100) if not isinstance(step, str) else step
    if not step_str.strip():
        step_str = "unknown"
    raw = safe_to_string(content, max_chars=max_chars)
    redacted = redact_sensitive(raw)
    # Re-truncate after redaction (redaction may change length slightly).
    if len(redacted) > max_chars:
        keep = max(0, max_chars - len(TRUNCATION_SUFFIX))
        redacted = redacted[:keep] + TRUNCATION_SUFFIX
    return {"step": step_str, "content": redacted}


def trim_trace(
    trace: Any,
    max_steps: int = DEFAULT_TRACE_MAX_STEPS,
    max_chars_per_step: int = MAX_TRACE_CHARS_PER_STEP,
) -> List[dict]:
    """Normalize and bound a trace list."""
    if not isinstance(trace, list):
        return []

    normalized: List[dict] = []
    for item in trace:
        try:
            if isinstance(item, dict):
                step = item.get("step", "unknown")
                content = item.get("content", "")
                normalized.append(
                    make_trace_step(step, content, max_chars=max_chars_per_step)
                )
            else:
                normalized.append(
                    make_trace_step("unknown", item, max_chars=max_chars_per_step)
                )
        except Exception:
            normalized.append({"step": "unknown", "content": "<invalid trace item>"})

    if max_steps <= 0:
        return []
    if len(normalized) <= max_steps:
        return normalized

    # Keep head and tail when over limit.
    head = max(1, max_steps // 2)
    tail = max(1, max_steps - head - 1)
    marker = make_trace_step(
        "truncated",
        f"omitted {len(normalized) - head - tail} steps",
        max_chars=max_chars_per_step,
    )
    return normalized[:head] + [marker] + normalized[-tail:]


def ensure_json_serializable(obj: Any) -> Any:
    """Recursively convert obj into a JSON-serializable structure."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            key = k if isinstance(k, str) else str(k)
            result[key] = ensure_json_serializable(v)
        return result
    if isinstance(obj, (list, tuple)):
        return [ensure_json_serializable(v) for v in obj]
    if isinstance(obj, BaseException):
        return f"{type(obj).__name__}: {obj}"
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return safe_to_string(obj)


def make_success_result(
    final_response: Any,
    trace: Optional[list] = None,
    max_final_chars: int = MAX_FINAL_RESPONSE_CHARS,
) -> dict:
    """Build a success result dict ready for competition judging."""
    text = safe_to_string(final_response, max_chars=max_final_chars).strip()
    text = redact_sensitive(text).strip()
    if not text:
        text = FALLBACK_ANSWER
    if len(text) > max_final_chars:
        keep = max(0, max_final_chars - len(TRUNCATION_SUFFIX))
        text = text[:keep] + TRUNCATION_SUFFIX

    cleaned_trace = trim_trace(trace or [])
    result = {
        "final_response": text,
        "trace": cleaned_trace,
    }
    return ensure_json_serializable(result)


def make_error_result(error: Any, trace: Optional[list] = None) -> dict:
    """Build a safe error result without raising."""
    try:
        steps = list(trace) if isinstance(trace, list) else []
        steps.append(make_trace_step("error", error))
        return make_success_result(FALLBACK_ANSWER, trace=steps)
    except Exception as e:
        return {
            "final_response": FALLBACK_ANSWER,
            "trace": [
                {
                    "step": "error",
                    "content": redact_sensitive(
                        safe_to_string(f"{type(e).__name__}: {e}", max_chars=500)
                    ),
                }
            ],
        }
