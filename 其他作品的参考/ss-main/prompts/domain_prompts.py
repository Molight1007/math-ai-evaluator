"""Domain-specific solver prompts for different math subjects/types."""

from __future__ import annotations

import json
from typing import Any, Optional

from prompts.base_prompts import FINAL_ANSWER_INSTRUCTION, SYSTEM_MATH_AGENT_PROMPT


def _format_common_sections(
    problem: str,
    profile: Optional[dict],
    plan: Optional[str],
    tool_hints: Any,
    candidate_id: str,
) -> dict:
    profile = profile or {}
    plan_text = plan or "理解题意，选择方法，完成推导并验证。"
    profile_str = json.dumps(profile, ensure_ascii=False)

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

    return {
        "system": SYSTEM_MATH_AGENT_PROMPT,
        "candidate_id": candidate_id,
        "problem": problem,
        "profile_str": profile_str,
        "plan_text": plan_text,
        "tool_section": tool_section,
        "final": FINAL_ANSWER_INSTRUCTION,
    }


def build_algebra_solver_prompt(
    problem: str,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints=None,
    candidate_id: str = "candidate_1",
    metadata: Optional[dict] = None,
) -> str:
    """Prompt for abstract algebra / linear algebra / finite fields."""
    c = _format_common_sections(problem, profile, plan, tool_hints, candidate_id)
    return f"""{c['system']}

你是第 {c['candidate_id']} 个独立数学求解器，专注抽象代数 / 有限域 / 线性代数。

题目：
{c['problem']}

题目分类：
{c['profile_str']}

解题计划：
{c['plan_text']}
{c['tool_section']}
专项要求：
1. 明确代数对象（群、环、域、向量空间、矩阵等）；
2. 检查阶、维数、子结构（子群、子环、子域、子空间）；
3. 对有限域题注意子域、扩张次数、生成元、最小多项式；
4. 对群论题注意子群、正规性、同态、同构、群作用、Sylow；
5. 对线性代数题注意秩、维数、特征值、特征向量、可逆性；
6. 不要只凭直觉计数，给出清晰结构依据。

最后输出：
最终答案：xxx
{c['final']}
"""


def build_analysis_solver_prompt(
    problem: str,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints=None,
    candidate_id: str = "candidate_1",
    metadata: Optional[dict] = None,
) -> str:
    """Prompt for analysis / calculus / ODE / complex analysis."""
    c = _format_common_sections(problem, profile, plan, tool_hints, candidate_id)
    return f"""{c['system']}

你是第 {c['candidate_id']} 个独立数学求解器，专注分析 / 微积分 / 微分方程。

题目：
{c['problem']}

题目分类：
{c['profile_str']}

解题计划：
{c['plan_text']}
{c['tool_section']}
专项要求：
1. 检查定义域与函数适用条件；
2. 检查收敛条件（极限、级数、积分）；
3. 注意边界条件、初值条件；
4. 对积分题检查路径、区间、奇点；
5. 对复分析题注意解析性、奇点、留数、路径方向；
6. 对级数题注意绝对收敛 / 条件收敛；
7. 对微分方程识别类型并检查解的合理性。

最后输出：
最终答案：xxx
{c['final']}
"""


def build_probability_solver_prompt(
    problem: str,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints=None,
    candidate_id: str = "candidate_1",
    metadata: Optional[dict] = None,
) -> str:
    """Prompt for probability and statistics."""
    c = _format_common_sections(problem, profile, plan, tool_hints, candidate_id)
    return f"""{c['system']}

你是第 {c['candidate_id']} 个独立数学求解器，专注概率统计。

题目：
{c['problem']}

题目分类：
{c['profile_str']}

解题计划：
{c['plan_text']}
{c['tool_section']}
专项要求：
1. 明确样本空间与事件定义；
2. 检查独立性是否已给定，不可擅自假设；
3. 写清随机变量定义与取值；
4. 区分条件概率与联合概率；
5. 期望 / 方差要检查线性性与独立性条件；
6. 注意分布类型与参数范围。

最后输出：
最终答案：xxx
{c['final']}
"""


def build_combinatorics_solver_prompt(
    problem: str,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints=None,
    candidate_id: str = "candidate_1",
    metadata: Optional[dict] = None,
) -> str:
    """Prompt for combinatorics and graph theory."""
    c = _format_common_sections(problem, profile, plan, tool_hints, candidate_id)
    return f"""{c['system']}

你是第 {c['candidate_id']} 个独立数学求解器，专注组合计数 / 图论。

题目：
{c['problem']}

题目分类：
{c['profile_str']}

解题计划：
{c['plan_text']}
{c['tool_section']}
专项要求：
1. 明确计数对象；
2. 检查是否重复计数；
3. 检查是否漏计；
4. 必要时使用容斥、递推、构造、分类讨论；
5. 图论题注意点、边、路径、连通性、匹配、染色等定义；
6. 注意对称性是否需要除以等价类。

最后输出：
最终答案：xxx
{c['final']}
"""


def build_optimization_solver_prompt(
    problem: str,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints=None,
    candidate_id: str = "candidate_1",
    metadata: Optional[dict] = None,
) -> str:
    """Prompt for optimization / operations research."""
    c = _format_common_sections(problem, profile, plan, tool_hints, candidate_id)
    return f"""{c['system']}

你是第 {c['candidate_id']} 个独立数学求解器，专注优化 / 运筹学。

题目：
{c['problem']}

题目分类：
{c['profile_str']}

解题计划：
{c['plan_text']}
{c['tool_section']}
专项要求：
1. 明确目标函数；
2. 明确约束条件；
3. 检查边界与可行域；
4. 判断问题是否凸；
5. 对线性规划检查顶点最优；
6. 对不等式优化检查等号条件 / KKT 直觉。

最后输出：
最终答案：xxx
{c['final']}
"""


def build_proof_solver_prompt_specialized(
    problem: str,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints=None,
    candidate_id: str = "candidate_1",
    metadata: Optional[dict] = None,
) -> str:
    """Prompt specialized for proof problems."""
    c = _format_common_sections(problem, profile, plan, tool_hints, candidate_id)
    return f"""{c['system']}

你是第 {c['candidate_id']} 个独立数学证明求解器。

题目：
{c['problem']}

题目分类：
{c['profile_str']}

解题计划：
{c['plan_text']}
{c['tool_section']}
专项要求：
1. 明确要证明的命题；
2. 列出已知条件；
3. 选择证明方法（直接、反证、归纳、构造等）；
4. 不跳过关键逻辑；
5. 不把结论当条件，不编造题外假设；
6. 证明过程要闭环。

最后输出：
最终答案：命题成立，证明如下：...
{c['final']}
"""


def build_choice_solver_prompt_specialized(
    problem: str,
    profile: Optional[dict] = None,
    plan: Optional[str] = None,
    tool_hints=None,
    candidate_id: str = "candidate_1",
    metadata: Optional[dict] = None,
) -> str:
    """Prompt specialized for multiple-choice problems."""
    c = _format_common_sections(problem, profile, plan, tool_hints, candidate_id)
    return f"""{c['system']}

你是第 {c['candidate_id']} 个独立数学选择题求解器。

题目：
{c['problem']}

题目分类：
{c['profile_str']}

解题计划：
{c['plan_text']}
{c['tool_section']}
专项要求：
1. 分析各选项或排除错误选项；
2. 检查是否为单选题；
3. 最终答案只输出明确选项；
4. 若多个选项看似正确，重新检查题干条件。

最后输出：
最终答案：A/B/C/D
{c['final']}
"""
