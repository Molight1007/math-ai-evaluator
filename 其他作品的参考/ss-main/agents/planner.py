"""Solve plan generation — rule-based with optional LLM enhancement."""

from __future__ import annotations

from typing import Any, Optional

from config import DEFAULT_MAX_TOKENS, FAST_TEMPERATURE
from prompts.planner_prompts import build_planner_prompt

SUBJECT_PLANS = {
    "algebra": (
        "1. 分析代数结构；"
        "2. 检查定义、阶、子群、子域与同态关系；"
        "3. 选择合适方法推导；"
        "4. 验证结果。"
    ),
    "analysis": (
        "1. 明确定义域与边界条件；"
        "2. 检查极限/连续条件与所需微积分公式；"
        "3. 完成计算或推导；"
        "4. 验证结果合理性。"
    ),
    "probability": (
        "1. 明确样本空间；"
        "2. 检查独立性与分布假设；"
        "3. 计算期望、方差或概率；"
        "4. 验证结果。"
    ),
    "combinatorics": (
        "1. 识别计数对象与约束；"
        "2. 选择排列、组合或递推方法；"
        "3. 完成计数推导；"
        "4. 验证结果。"
    ),
    "graph_theory": (
        "1. 建立图模型；"
        "2. 识别路径、匹配或最短路问题；"
        "3. 选择算法求解；"
        "4. 验证结果。"
    ),
    "optimization": (
        "1. 建立目标函数与约束；"
        "2. 判断线性/凸优化方法；"
        "3. 求解并检查边界；"
        "4. 验证最优性。"
    ),
}

DEFAULT_PLAN = (
    "1. 理解题意，提取已知条件；"
    "2. 选择合适数学方法；"
    "3. 完成计算或推导；"
    "4. 验证答案。"
)

PROOF_SUFFIX = (
    "明确证明目标，选择合适证明方法，逐步验证结论。"
)

MAX_PLAN_CHARS = 600
PLAN_STEP_MARKERS = ("步骤1", "步骤 1", "1.", "1、", "1:", "Step 1", "step 1")


def _is_valid_plan(text: str) -> bool:
    """Reject meta-reasoning or answer-leaking planner output."""
    if not text or not text.strip():
        return False
    text = text.strip()
    if len(text) > MAX_PLAN_CHARS:
        return False
    if "最终答案" in text:
        return False
    if text.startswith("用户要求") or text.startswith("Thinking"):
        return False
    return any(marker in text for marker in PLAN_STEP_MARKERS)


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


def rule_create_plan(problem: str, profile: dict) -> str:
    """Generate a solve plan using profile-based rules."""
    profile = profile or {}
    subject = profile.get("subject", "other")
    problem_type = profile.get("problem_type", "calculation")

    plan = SUBJECT_PLANS.get(subject, DEFAULT_PLAN)

    if problem_type == "proof":
        plan = f"{plan} {PROOF_SUFFIX}"

    if problem_type == "choice":
        plan = (
            "1. 理解题意并分析各选项；"
            "2. 推导或排除错误选项；"
            "3. 确认唯一正确选项；"
            "4. 验证选择。"
        )

    return plan.strip()


class Planner:
    """Generate concise solve plans from problem and router profile."""

    def __init__(self, client: Any = None) -> None:
        self.client = client

    def _llm_create_plan(
        self,
        problem: str,
        metadata: dict,
        profile: dict,
    ) -> Optional[str]:
        if self.client is None:
            return None
        prompt = build_planner_prompt(
            problem=problem,
            profile=profile,
            metadata=metadata,
        )
        try:
            response = self.client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=FAST_TEMPERATURE,
                max_tokens=min(512, DEFAULT_MAX_TOKENS),
            )
            text = _response_to_text(response).strip()
            if text:
                return text
        except Exception:
            return None
        return None

    def create_plan(
        self,
        problem: str,
        metadata: dict | None,
        profile: dict,
    ) -> str:
        """Return a solve plan string."""
        metadata = metadata or {}
        profile = profile or {}
        rule_plan = rule_create_plan(problem, profile)

        if self.client is None:
            return rule_plan

        llm_plan = self._llm_create_plan(problem, metadata, profile)
        if llm_plan and _is_valid_plan(llm_plan):
            return llm_plan.strip()
        return rule_plan
