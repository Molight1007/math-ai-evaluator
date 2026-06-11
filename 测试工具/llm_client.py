"""
LLM Client - OpenAI compatible async HTTP client.
Supports retry, timeout, and JSON extraction.
"""
import json
import logging
import asyncio
import re
from typing import Optional

import httpx

from config import LLMConfig

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    pass


class APITimeoutError(LLMClientError):
    pass


class APIResponseError(LLMClientError):
    pass


class LLMClient:
    """OpenAI-compatible async LLM client."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._url = f"{config.base_url.rstrip('/')}/chat/completions"

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        response_format: Optional[dict] = None,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout) as c:
                    resp = await c.post(self._url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    return {
                        "content": choice["message"]["content"],
                        "tokens_used": data.get("usage", {}).get("total_tokens", 0),
                        "finish_reason": choice.get("finish_reason", "unknown"),
                    }
            except httpx.TimeoutException as e:
                last_error = APITimeoutError(str(e))
                logger.warning(str(last_error))
            except httpx.HTTPStatusError as e:
                last_error = APIResponseError(f"HTTP {e.response.status_code}")
                logger.warning(str(last_error))
                if 400 <= e.response.status_code < 500:
                    raise last_error
            except Exception as e:
                last_error = LLMClientError(str(e))
                logger.warning(str(last_error))
            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        raise last_error or LLMClientError("unknown error")


def extract_json_from_text(text: str) -> Optional[dict]:
    """Extract JSON object from LLM response text."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    i = text.find("{")
    if i == -1:
        return None
    d = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            d += 1
        elif text[j] == "}":
            d -= 1
            if d == 0:
                try:
                    return json.loads(text[i:j + 1])
                except json.JSONDecodeError:
                    return None
    return None
