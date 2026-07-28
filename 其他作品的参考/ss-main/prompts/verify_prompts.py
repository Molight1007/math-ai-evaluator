"""Prompts for verifying candidate answers."""

from __future__ import annotations

import json
from typing import Optional


def build_verify_prompt(
    problem: str,
    candidate_solution: str,
    candidate_answer: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    """Build prompt for verifying a candidate solution (for future verifier)."""
    metadata = metadata or {}
    metadata_str = json.dumps(metadata, ensure_ascii=False)
    answer_section = candidate_answer or "（未单独提供，请从候选解答中提取）"

    return f"""请严格检查以下数学题的候选解答是否正确。

题目：
{problem}

题目信息：
{metadata_str}

候选解答：
{candidate_solution}

候选最终答案：
{answer_section}

请重点检查：
1. 是否理解题意；
2. 是否遗漏条件；
3. 计算是否正确；
4. 逻辑是否完整；
5. 答案是否符合题目要求。

如果答案不正确，请给出修正答案。

请按如下格式输出：
正确性：正确/错误/不确定
问题：
修正答案：
置信度：
"""
