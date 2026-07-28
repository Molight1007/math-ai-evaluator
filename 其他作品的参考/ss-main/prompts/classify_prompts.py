"""Prompts for problem classification."""

from __future__ import annotations

import json
from typing import Optional


def build_classify_prompt(problem: str, metadata: Optional[dict] = None) -> str:
    """Build prompt asking the model to classify a math problem."""
    metadata = metadata or {}
    metadata_str = json.dumps(metadata, ensure_ascii=False)

    return f"""请分析以下数学题目，并只返回 JSON 格式的分类结果。

题目：
{problem}

题目信息：
{metadata_str}

请输出如下 JSON（只输出 JSON，不要其他内容）：
{{
    "subject": "",
    "problem_type": "",
    "answer_form": "",
    "needs_proof": false,
    "needs_tool": false,
    "difficulty": "",
    "confidence": 0.0
}}

字段说明：

subject 取值之一：
- algebra
- analysis
- geometry
- probability
- optimization
- number_theory
- other

problem_type 取值之一：
- calculation
- proof
- choice
- fill_blank
- explanation

answer_form：期望答案形式（如 integer / rational / expression / set / proof / option / text）
needs_proof：是否需要完整证明
needs_tool：是否可能需要符号计算工具
difficulty：easy / medium / hard
confidence：0.0 到 1.0 之间的确信度
"""
