"""Prompts for finalizing concise final answers."""

from __future__ import annotations

import json
from typing import Optional

from prompts.base_prompts import FINAL_ANSWER_INSTRUCTION


def build_finalize_prompt(
    problem: str,
    solution_text: str,
    metadata: Optional[dict] = None,
    problem_type: Optional[str] = None,
) -> str:
    """Build prompt to compress a long solution into final_response."""
    metadata = metadata or {}
    metadata_str = json.dumps(metadata, ensure_ascii=False)
    type_hint = problem_type or "unknown"

    type_rules = {
        "calculation": "只输出结果。",
        "fill_blank": "只输出结果。",
        "choice": "只输出选项。",
        "proof": "保留必要证明。",
        "explanation": "保留简洁明确的解释和结论。",
    }
    rule = type_rules.get(problem_type or "", "输出清晰、可判分的最终答案。")

    return f"""请从以下解题过程中提取或整理出适合作为最终判分答案的内容。

题目：
{problem}

题目信息：
{metadata_str}

题型：{type_hint}

完整解题过程：
{solution_text}

要求：
1. {rule}
2. 禁止出现：我认为、可能、大概、不确定。
3. 不要输出冗余分析或重复推理。
4. 最终输出必须明确、非空。
{FINAL_ANSWER_INSTRUCTION}

最后：
最终答案：
"""
