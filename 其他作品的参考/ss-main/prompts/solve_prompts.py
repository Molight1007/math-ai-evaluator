"""Prompts for solving math problems."""

from __future__ import annotations

import json
from typing import Any, Optional

from prompts.base_prompts import FINAL_ANSWER_INSTRUCTION, SYSTEM_MATH_AGENT_PROMPT


def _format_metadata(metadata: Optional[dict]) -> str:
    if not metadata:
        return "{}"
    return json.dumps(metadata, ensure_ascii=False)


def _format_optional_section(label: str, value: Optional[Any]) -> str:
    if value is None or value == "" or value == {} or value == []:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    return f"\n{label}：\n{text}\n"


def build_general_solve_prompt(
    problem: str,
    metadata: Optional[dict] = None,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints: Optional[Any] = None,
) -> str:
    """Build a general-purpose solve prompt."""
    metadata_str = _format_metadata(metadata)
    extra = (
        _format_optional_section("题目分类", profile)
        + _format_optional_section("解题计划", plan)
        + _format_optional_section("工具提示", tool_hints)
    )

    return f"""{SYSTEM_MATH_AGENT_PROMPT}

请完成数学问题：

{problem}

题目信息：
{metadata_str}
{extra}
要求：
1. 分析条件；
2. 选择方法；
3. 完成推导；
4. 检查结果。

最后输出：
最终答案：xxx
{FINAL_ANSWER_INSTRUCTION}"""


def build_calculation_solve_prompt(
    problem: str,
    metadata: Optional[dict] = None,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints: Optional[Any] = None,
) -> str:
    """Build a prompt tailored for calculation problems."""
    metadata_str = _format_metadata(metadata)
    extra = (
        _format_optional_section("题目分类", profile)
        + _format_optional_section("解题计划", plan)
        + _format_optional_section("工具提示", tool_hints)
    )

    return f"""{SYSTEM_MATH_AGENT_PROMPT}

你是严谨的数学计算解题智能体。

请完成数学问题：

{problem}

题目信息：
{metadata_str}
{extra}
要求：
1. 分析条件；
2. 选择方法进行计算；
3. 完成推导；
4. 检查漏解、定义域与化简；
5. 答案尽量化简；整数或分数不要用小数近似，除非题目要求。

最后输出：
最终答案：xxx
{FINAL_ANSWER_INSTRUCTION}"""


def build_proof_solve_prompt(
    problem: str,
    metadata: Optional[dict] = None,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints: Optional[Any] = None,
) -> str:
    """Build a prompt tailored for proof problems."""
    metadata_str = _format_metadata(metadata)
    extra = (
        _format_optional_section("题目分类", profile)
        + _format_optional_section("解题计划", plan)
        + _format_optional_section("工具提示", tool_hints)
    )

    return f"""{SYSTEM_MATH_AGENT_PROMPT}

你是严谨的数学证明智能体。

请完成数学问题：

{problem}

题目信息：
{metadata_str}
{extra}
要求：
1. 分析条件；
2. 明确要证明的命题；
3. 选择证明方法并完成推导；
4. 检查结果，不要跳过关键步骤，不要编造题目外条件。

最后输出：
最终答案：xxx
{FINAL_ANSWER_INSTRUCTION}
最终答案格式示例：最终答案：命题成立，证明如下：..."""


def build_choice_solve_prompt(
    problem: str,
    metadata: Optional[dict] = None,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints: Optional[Any] = None,
) -> str:
    """Build a prompt tailored for multiple-choice problems."""
    metadata_str = _format_metadata(metadata)
    extra = (
        _format_optional_section("题目分类", profile)
        + _format_optional_section("解题计划", plan)
        + _format_optional_section("工具提示", tool_hints)
    )

    return f"""{SYSTEM_MATH_AGENT_PROMPT}

请完成数学问题：

{problem}

题目信息：
{metadata_str}
{extra}
要求：
1. 分析条件；
2. 分析或排除选项；
3. 完成推导；
4. 检查结果，确保选项唯一明确。

最后输出：
最终答案：xxx
{FINAL_ANSWER_INSTRUCTION}
最终答案格式示例：最终答案：B"""
