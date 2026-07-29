"""Prompts for verifying a single solution candidate."""

from __future__ import annotations

import json
from typing import Any, Optional


def build_verifier_prompt(
    problem: str,
    candidate: dict,
    metadata: Optional[dict] = None,
) -> str:
    """Build prompt asking the model to verify one candidate."""
    metadata = metadata or {}
    candidate = candidate or {}
    metadata_str = json.dumps(metadata, ensure_ascii=False)
    solution = candidate.get("solution", "") or ""
    answer = candidate.get("answer", "") or ""
    candidate_id = candidate.get("id", "")

    return f"""请严格检查以下数学题的候选解答。

题目：
{problem}

题目信息：
{metadata_str}

候选 ID：
{candidate_id}

候选解：
{solution}

候选最终答案：
{answer}

请判断：
1. 理解题意是否正确；
2. 推理过程是否正确；
3. 是否遗漏条件；
4. 最终答案是否正确。

请严格按如下格式输出：
正确性：correct / wrong / uncertain
问题：
修正答案：
置信度：
"""
