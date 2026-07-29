"""Prompts for independent solver candidates."""

from __future__ import annotations

import json
from typing import Callable, Optional

from prompts.base_prompts import FINAL_ANSWER_INSTRUCTION, SYSTEM_MATH_AGENT_PROMPT
from prompts.domain_prompts import (
    build_algebra_solver_prompt,
    build_analysis_solver_prompt,
    build_choice_solver_prompt_specialized,
    build_combinatorics_solver_prompt,
    build_optimization_solver_prompt,
    build_probability_solver_prompt,
    build_proof_solver_prompt_specialized,
)


def build_solver_prompt(
    problem: str,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    candidate_id: str = "candidate_1",
    metadata: Optional[dict] = None,
    tool_hints=None,
) -> str:
    """Build default prompt for one independent solver candidate."""
    profile = profile or {}
    metadata = metadata or {}
    profile_str = json.dumps(profile, ensure_ascii=False)
    metadata_str = json.dumps(metadata, ensure_ascii=False)
    plan_text = plan or "理解题意，选择方法，完成推导并验证。"

    tool_section = ""
    if tool_hints:
        try:
            if isinstance(tool_hints, dict):
                hints_text = json.dumps(tool_hints, ensure_ascii=False)
            else:
                hints_text = str(tool_hints)
        except Exception:
            hints_text = str(tool_hints)
        tool_section = f"""
可用工具提示：
{hints_text}

注意：工具提示只能作为辅助，不能替代严谨推理。
"""

    return f"""{SYSTEM_MATH_AGENT_PROMPT}

你是第 {candidate_id} 个独立数学求解器。

请重新独立完成推导。
不要参考其他求解器的结果。
不要猜测答案。

题目：
{problem}

题目信息：
{metadata_str}

题目分类：
{profile_str}

解题计划：
{plan_text}
{tool_section}
要求：
1. 独立完成求解；
2. 分析条件，选择方法，完成推导；
3. 检查计算与逻辑；
4. 不要输出与其他候选相关的内容。

最后输出：
最终答案：xxx
{FINAL_ANSWER_INSTRUCTION}
"""


def get_solver_prompt_route(profile: Optional[dict] = None) -> str:
    """Return route name for the selected specialized/default prompt."""
    profile = profile or {}
    problem_type = str(profile.get("problem_type", "")).lower().strip()
    subject = str(profile.get("subject", "")).lower().strip()

    if problem_type == "proof":
        return "proof"
    if problem_type == "choice":
        return "choice"
    if subject in ("algebra", "abstract_algebra", "linear_algebra"):
        return "algebra"
    if subject in ("analysis", "calculus"):
        return "analysis"
    if subject in ("probability", "statistics"):
        return "probability"
    if subject in ("combinatorics", "graph_theory", "graph"):
        return "combinatorics"
    if subject in ("optimization", "operations_research"):
        return "optimization"
    return "default"


def select_solver_prompt_builder(profile: Optional[dict] = None) -> Callable:
    """Select a specialized prompt builder from profile."""
    route = get_solver_prompt_route(profile)
    mapping = {
        "proof": build_proof_solver_prompt_specialized,
        "choice": build_choice_solver_prompt_specialized,
        "algebra": build_algebra_solver_prompt,
        "analysis": build_analysis_solver_prompt,
        "probability": build_probability_solver_prompt,
        "combinatorics": build_combinatorics_solver_prompt,
        "optimization": build_optimization_solver_prompt,
        "default": build_solver_prompt,
    }
    return mapping.get(route, build_solver_prompt)


def build_routed_solver_prompt(
    problem: str,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    candidate_id: str = "candidate_1",
    tool_hints=None,
    metadata: Optional[dict] = None,
) -> str:
    """Build a domain-routed solver prompt with safe fallback."""
    try:
        builder = select_solver_prompt_builder(profile)
        return builder(
            problem=problem,
            profile=profile,
            plan=plan,
            tool_hints=tool_hints,
            candidate_id=candidate_id,
            metadata=metadata,
        )
    except Exception:
        return build_solver_prompt(
            problem=problem,
            profile=profile,
            plan=plan,
            candidate_id=candidate_id,
            metadata=metadata,
            tool_hints=tool_hints,
        )
