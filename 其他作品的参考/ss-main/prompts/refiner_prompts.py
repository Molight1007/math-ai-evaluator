"""Prompts for refining low-quality candidate answers."""

from __future__ import annotations

import json
from typing import Any, List, Optional


def build_refiner_prompt(
    problem: str,
    candidate: dict,
    issues: Optional[List[Any]] = None,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    """Build prompt asking the model to correct a flawed candidate."""
    candidate = candidate or {}
    profile = profile or {}
    metadata = metadata or {}
    issues = issues or []

    issues_text = "；".join(str(i) for i in issues if i) if issues else "答案质量不足，需要复查"
    profile_str = json.dumps(profile, ensure_ascii=False)
    metadata_str = json.dumps(metadata, ensure_ascii=False)
    plan_text = plan or "理解题意，检查条件，重新推导并验证。"
    solution = candidate.get("solution", "") or ""
    answer = candidate.get("answer", "") or ""

    return f"""请修正以下数学题的候选解答。

题目：
{problem}

题目信息：
{metadata_str}

题目分类：
{profile_str}

解题计划：
{plan_text}

你之前的答案存在以下问题：
{issues_text}

原候选解答：
{solution}

原最终答案：
{answer}

请重新检查：
1. 题目条件；
2. 数学推导；
3. 计算过程；
4. 最终答案。

要求：
1. 不要解释修改过程；
2. 重新输出完整解答；
3. 最后一行必须输出：最终答案：xxx
"""
