"""Prompts for generating solve plans."""

from __future__ import annotations

import json
from typing import Optional


def build_planner_prompt(
    problem: str,
    profile: dict,
    metadata: Optional[dict] = None,
) -> str:
    """Build prompt asking the model to produce a solve plan (no answer)."""
    metadata = metadata or {}
    profile_str = json.dumps(profile, ensure_ascii=False)
    metadata_str = json.dumps(metadata, ensure_ascii=False)

    return f"""请为以下数学题制定解题计划。

题目：
{problem}

题目信息：
{metadata_str}

题目分类：
{profile_str}

请只输出纯文本解题计划，格式如下：
步骤1：...
步骤2：...
步骤3：...

要求：
1. 计划简洁、可执行，3-5 步为宜；
2. 只写解题思路与检查要点；
3. 不要输出最终答案；
4. 不要直接解题或给出计算结果。
"""
