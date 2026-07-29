from __future__ import annotations

import json
import math
import os
import re
import secrets
import time
from typing import Any, cast
from urllib.parse import urlsplit

import requests


def _positive_int(
    value: str | None,
    default: int,
    *,
    maximum: int,
) -> int:
    bounded_default = max(1, min(int(default), maximum))
    if value is None or value.strip() == "":
        return bounded_default
    try:
        parsed = int(value)
    except ValueError:
        return bounded_default
    return min(parsed, maximum) if parsed > 0 else bounded_default


class InternS1Client:
    DEFAULT_MODEL = "intern-s1"
    MOCK_RESPONSE = "[MOCK] Intern-S1 stable response"
    MAX_MESSAGE_CHARS = 100_000
    MAX_RESPONSE_CHARS = 200_000
    MAX_HTTP_RESPONSE_BYTES = 2_000_000
    MAX_ERROR_RESPONSE_BYTES = 16_384

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        mock: bool = False,
    ) -> None:
        self.api_key = api_key or os.getenv("INTERNS1_API_KEY")
        self.base_url = base_url or os.getenv("INTERNS1_BASE_URL")
        self.model = model or os.getenv("INTERNS1_MODEL") or self.DEFAULT_MODEL
        self.timeout = _positive_int(
            os.getenv("INTERNS1_TIMEOUT"),
            timeout if timeout is not None else 60,
            maximum=300,
        )
        self.max_retries = _positive_int(
            os.getenv("INTERNS1_MAX_RETRIES"),
            max_retries if max_retries is not None else 4,
            maximum=8,
        )
        self.mock = mock

    @classmethod
    def _bounded_response_json(
        cls,
        response: requests.Response,
        *,
        max_bytes: int | None = None,
    ) -> Any:
        limit = max_bytes or cls.MAX_HTTP_RESPONSE_BYTES
        if not isinstance(response, requests.Response):
            return response.json()
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > limit:
                    raise ValueError("invalid_response: response body size limit exceeded")
            except ValueError as exc:
                if "size limit" in str(exc):
                    raise
        payload = bytearray()
        for chunk in response.iter_content(chunk_size=65_536):
            if not chunk:
                continue
            payload.extend(chunk)
            if len(payload) > limit:
                raise ValueError("invalid_response: response body size limit exceeded")
        try:
            return json.loads(bytes(payload).decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid_response: response body is not valid JSON") from exc

    @classmethod
    def _response_detail(cls, response: requests.Response) -> str:
        try:
            data = cls._bounded_response_json(
                response, max_bytes=cls.MAX_ERROR_RESPONSE_BYTES
            )
            if isinstance(data, dict):
                raw = (
                    data.get("error")
                    or data.get("message")
                    or data.get("detail")
                    or ""
                )
                if isinstance(raw, dict):
                    raw = raw.get("message") or raw.get("detail") or str(raw)
                detail = str(raw)
            else:
                detail = str(data)
        except (TypeError, ValueError):
            detail = ""
        detail = re.sub(r"\s+", " ", detail).strip()
        return detail[:300]

    @staticmethod
    def _retry_delay(response: requests.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(30.0, max(0.0, float(retry_after)))
                except ValueError:
                    pass
        exponential = min(8.0, float(2 ** max(0, attempt - 1)))
        return exponential + secrets.randbelow(251) / 1000.0

    def _sleep_before_retry(
        self, response: requests.Response | None, attempt: int
    ) -> None:
        time.sleep(self._retry_delay(response, attempt))

    def _build_chat_completions_url(self) -> str:
        if not self.base_url:
            raise ValueError(
                "missing_base_url: INTERNS1_BASE_URL is required in --real mode"
            )
        normalized = self.base_url.rstrip("/")
        return (
            normalized
            if normalized.endswith("/chat/completions")
            else f"{normalized}/chat/completions"
        )

    def _validate_real_mode_config(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ValueError(
                "missing_api_key: INTERNS1_API_KEY is required in --real mode"
            )
        if len(self.api_key) > 4096:
            raise ValueError("invalid_api_key: API key length limit exceeded")
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise ValueError(
                "missing_base_url: INTERNS1_BASE_URL is required in --real mode"
            )
        if len(self.base_url) > 2048 or any(
            ord(char) < 32 for char in self.base_url
        ):
            raise ValueError("invalid_base_url: URL length or character limit exceeded")
        parsed = urlsplit(self.base_url)
        if parsed.scheme.casefold() != "https" or not parsed.hostname:
            raise ValueError("invalid_base_url: an absolute HTTPS URL is required")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "invalid_base_url: credentials, query strings, and fragments are not allowed"
            )
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 256:
            raise ValueError("invalid_model: model name must contain 1 to 256 characters")

    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        top_p: float = 0.9,
        max_tokens: int = 4096,
    ) -> str:
        if not isinstance(messages, list) or not messages or len(messages) > 64:
            raise ValueError("invalid_messages: expected 1 to 64 messages")
        total_message_chars = 0
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError("invalid_messages: each message must be a mapping")
            role = str(message.get("role", ""))
            if role not in {"system", "user", "assistant", "tool"}:
                raise ValueError(f"invalid_messages: unsupported role '{role}'")
            total_message_chars += len(str(message.get("content", "")))
        if total_message_chars > self.MAX_MESSAGE_CHARS:
            raise ValueError("invalid_messages: content length limit exceeded")
        if self.mock:
            return self.MOCK_RESPONSE
        self._validate_real_mode_config()
        url = self._build_chat_completions_url()
        try:
            parsed_temperature = float(temperature)
            parsed_top_p = float(top_p)
            parsed_max_tokens = int(max_tokens)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("invalid_generation_parameters") from exc
        if not math.isfinite(parsed_temperature) or not math.isfinite(parsed_top_p):
            raise ValueError("invalid_generation_parameters: values must be finite")
        bounded_temperature = max(0.0, min(2.0, parsed_temperature))
        bounded_top_p = max(0.0, min(1.0, parsed_top_p))
        bounded_max_tokens = max(1, min(16_384, parsed_max_tokens))
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": bounded_temperature,
            "top_p": bounded_top_p,
            "max_tokens": bounded_max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        attempts = max(1, self.max_retries)
        for attempt in range(1, attempts + 1):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=cast(Any, payload),
                    timeout=self.timeout,
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    if 300 <= resp.status_code < 400:
                        raise ValueError(
                            f"redirect_error: HTTP {resp.status_code} redirects are disabled"
                        )
                    if resp.status_code in {401, 403}:
                        raise ValueError("auth_error: unauthorized (401/403)")
                    if resp.status_code == 429:
                        if attempt < attempts:
                            self._sleep_before_retry(resp, attempt)
                            continue
                        raise ValueError("rate_limit: HTTP 429")
                    if 500 <= resp.status_code < 600:
                        if attempt < attempts:
                            self._sleep_before_retry(resp, attempt)
                            continue
                        raise ValueError(f"server_error: HTTP {resp.status_code}")
                    if 400 <= resp.status_code < 500:
                        detail = self._response_detail(resp)
                        suffix = f": {detail}" if detail else ""
                        raise ValueError(
                            f"client_error: HTTP {resp.status_code}{suffix}"
                        )
                    resp.raise_for_status()
                    data = self._bounded_response_json(resp)
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    if isinstance(exc, ValueError) and str(exc).startswith(
                        (
                            "auth_error:",
                            "client_error:",
                            "invalid_response:",
                            "rate_limit:",
                            "redirect_error:",
                            "server_error:",
                        )
                    ):
                        raise
                    raise ValueError(
                        "invalid_response: response JSON is not chat-completions compatible"
                    ) from exc
                finally:
                    resp.close()
                content_text = str(content)
                if len(content_text) > self.MAX_RESPONSE_CHARS:
                    raise ValueError("invalid_response: content length limit exceeded")
                return content_text
            except requests.Timeout:
                if attempt >= attempts:
                    raise ValueError("timeout: request timed out") from None
                self._sleep_before_retry(None, attempt)
            except requests.RequestException:
                if attempt >= attempts:
                    raise ValueError("unknown_error: network request failed") from None
                self._sleep_before_retry(None, attempt)
            except ValueError:
                raise
        raise ValueError("unknown_error: request failed after retries")
