"""Problem type router — rule-based with optional LLM fallback."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from config import DEFAULT_MAX_TOKENS, FAST_TEMPERATURE
from prompts.classify_prompts import build_classify_prompt
from tools.problem_classifier import normalize_profile, rule_classify

# Rule confidence below this threshold triggers LLM classification.
LLM_CONFIDENCE_THRESHOLD = 0.65


def _extract_json_object(text: str) -> Optional[dict]:
    """Extract and parse the first JSON object from model output."""
    if not text:
        return None
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return None
    return None


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


class ProblemRouter:
    """Route math problems to structured profiles via rules and optional LLM."""

    def __init__(self, client: Any = None) -> None:
        self.client = client

    def _llm_classify(self, problem: str, metadata: dict) -> Optional[dict]:
        if self.client is None:
            return None
        prompt = build_classify_prompt(problem=problem, metadata=metadata)
        try:
            response = self.client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=FAST_TEMPERATURE,
                max_tokens=min(512, DEFAULT_MAX_TOKENS),
            )
            raw = _response_to_text(response)
            parsed = _extract_json_object(raw)
            if parsed:
                return normalize_profile(parsed)
        except Exception:
            return None
        return None

    def classify(self, problem: str, metadata: dict | None = None) -> dict:
        """Classify problem into a structured profile."""
        metadata = metadata or {}
        rule_result = rule_classify(problem, metadata)

        if self.client is None:
            return rule_result

        if rule_result.get("confidence", 0.0) >= LLM_CONFIDENCE_THRESHOLD:
            return rule_result

        llm_result = self._llm_classify(problem, metadata)
        if llm_result:
            merged = dict(rule_result)
            for key, value in llm_result.items():
                if value not in ("", None, False, 0.0):
                    merged[key] = value
            if llm_result.get("confidence", 0) > rule_result.get("confidence", 0):
                merged["confidence"] = llm_result["confidence"]
            return normalize_profile(merged)

        return rule_result
