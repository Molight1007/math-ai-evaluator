from __future__ import annotations

import inspect
from typing import Any

from math_agent.clients.interns1_client import InternS1Client
from math_agent.pipeline import MathAgentPipeline
from math_agent.prompting import default_prompt_config_path
from math_agent.schemas import SolveResult, sanitize_protocol_metadata

_MAX_MODEL_RESPONSE_CHARS = 200_000


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_float(
    value: Any, default: float, minimum: float, maximum: float
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(maximum, parsed))


class _OfficialClientAdapter:
    """Normalize the official competition client to the local ChatClient shape."""

    def __init__(
        self,
        client: Any,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> None:
        self._client = client
        self.temperature = _bounded_float(temperature, 0.2, 0.0, 2.0)
        self.max_tokens = _bounded_int(max_tokens, 4096, 1, 16_384)

    @property
    def model(self) -> str:
        return str(getattr(self._client, "model", "official-client"))

    def chat(
        self,
        messages: list[dict[str, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> str:
        kwargs.setdefault("temperature", self.temperature)
        kwargs.setdefault("max_tokens", self.max_tokens)
        chat_fn = self._client.chat
        if _accepts_positional_messages(chat_fn):
            response = chat_fn(messages, *args, **kwargs)
        else:
            response = chat_fn(*args, messages=messages, **kwargs)
        return _extract_chat_content(response)


def _accepts_positional_messages(chat_fn: Any) -> bool:
    try:
        signature = inspect.signature(chat_fn)
    except (TypeError, ValueError):
        return True
    parameters = list(signature.parameters.values())
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in parameters):
        return True
    messages_param = signature.parameters.get("messages")
    if messages_param is not None:
        return messages_param.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    if not parameters:
        return False
    first = parameters[0]
    return first.kind in {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }


def _extract_chat_content(response: Any) -> str:
    if isinstance(response, str):
        return _bounded_chat_content(response)
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and "content" in message:
                    return _bounded_chat_content(message["content"])
                if "text" in first:
                    return _bounded_chat_content(first["text"])
        if "content" in response:
            return _bounded_chat_content(response["content"])
    choices = getattr(response, "choices", None)
    if choices:
        first = choices[0]
        message = getattr(first, "message", None)
        content = getattr(message, "content", None)
        if content is not None:
            return _bounded_chat_content(content)
        text = getattr(first, "text", None)
        if text is not None:
            return _bounded_chat_content(text)
    content = getattr(response, "content", None)
    if content is not None:
        return _bounded_chat_content(content)
    return _bounded_chat_content(response)


def _bounded_chat_content(value: Any) -> str:
    content = str(value)
    if len(content) > _MAX_MODEL_RESPONSE_CHARS:
        raise ValueError("invalid_response: content length limit exceeded")
    return content


def _question_id_from_metadata(metadata: dict[str, Any]) -> str:
    for key in ("idx", "question_id", "id"):
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return str(value)[:256]
    return "unknown"


def _safe_error(error_type: str, message: str) -> dict[str, str]:
    return sanitize_protocol_metadata(
        {
            "type": error_type,
            "message": message,
        }
    )


def _final_response_from_result(result: SolveResult) -> str:
    value = (result.final_answer.value or "").strip()
    if value:
        return value
    boxed = (result.final_answer.boxed or "").strip()
    if boxed:
        return boxed
    for step in reversed(result.visible_solution_steps):
        text = str(step or "").strip()
        if text:
            return text[:1000]
    return "Unable to produce a final answer."


def _trace_from_result(result: SolveResult) -> list[dict[str, str]]:
    trace: list[dict[str, str]] = [
        {
            "step": "route",
            "content": (
                f"domain={result.domain}; problem_type={result.problem_type}; "
                f"status={result.status}"
            ),
        }
    ]
    if result.visible_solution_steps:
        trace.append(
            {
                "step": "solve",
                "content": str(result.visible_solution_steps[-1])[:2000],
            }
        )
    if result.tool_trace:
        trace.append(
            {
                "step": "tools",
                "content": "; ".join(
                    f"{item.tool}:{item.status}:{item.summary}"
                    for item in result.tool_trace[:3]
                )[:2000],
            }
        )
    trace.append(
        {
            "step": "verify",
            "content": (
                f"{result.verification.method}; passed={result.verification.passed}; "
                f"{result.verification.notes}"
            )[:2000],
        }
    )
    if result.error:
        trace.append({"step": "error", "content": result.error[:1000]})
    return sanitize_protocol_metadata({"trace": trace})["trace"]


class ReasoningAgent:
    """Official preliminary-round entry point.

    The platform initializes this class with its official client:

        agent = ReasoningAgent(client=official_client)

    Then it calls:

        agent.solve(problem, metadata)
    """

    def __init__(self, client: Any | None = None, *args: Any, **kwargs: Any) -> None:
        _ = args
        self._metadata_keys_used = ("idx", "question_id", "id")
        run_mode = str(kwargs.get("run_mode", "fast"))
        if run_mode not in {"full", "fast", "tool-first"}:
            run_mode = "fast"
        enable_tools = bool(kwargs.get("enable_tools", True))
        max_refine_rounds = _bounded_int(
            kwargs.get("max_refine_rounds", 0), 0, 0, 2
        )
        prompt_config_path = kwargs.get(
            "prompt_config_path",
            default_prompt_config_path(),
        )
        temperature = _bounded_float(
            kwargs.get("temperature", 0.2), 0.2, 0.0, 2.0
        )
        max_tokens = _bounded_int(
            kwargs.get("max_tokens", 4096), 4096, 1, 16_384
        )

        if client is None:
            adapted_client: Any = InternS1Client(mock=True)
            mock = True
        else:
            adapted_client = _OfficialClientAdapter(
                client,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            mock = False

        self._pipeline = MathAgentPipeline(
            client=adapted_client,
            prompt_config_path=prompt_config_path,
            mock=mock,
            enable_tools=enable_tools,
            max_refine_rounds=max_refine_rounds,
            save_trace=False,
            run_mode=run_mode,
        )

    def solve(self, problem: str, metadata: dict[str, Any] | None = None) -> dict:
        try:
            safe_metadata = metadata if isinstance(metadata, dict) else {}
            question_id = _question_id_from_metadata(safe_metadata)
            result = self._pipeline.solve(str(problem), question_id)
            final_response = _final_response_from_result(result)
            success = result.status == "success" and bool(final_response.strip())
            payload: dict[str, Any] = {
                "success": success,
                "status": result.status,
                "final_response": final_response,
                "trace": _trace_from_result(result),
            }
            if result.error:
                payload["error"] = _safe_error("PipelineError", result.error)
            return sanitize_protocol_metadata(payload)
        except Exception as exc:
            try:
                message = str(exc)[:1000]
            except Exception:
                message = "Unable to render the upstream exception message."
            return sanitize_protocol_metadata({
                "success": False,
                "status": "error",
                "final_response": "Unable to produce a final answer.",
                "trace": [
                    {
                        "step": "error",
                        "content": f"{exc.__class__.__name__}: {message}",
                    }
                ],
                "error": _safe_error(exc.__class__.__name__, message),
            })
