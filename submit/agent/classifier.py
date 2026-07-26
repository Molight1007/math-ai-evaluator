"""
题型识别智能体（ClassifierAgent）
===============================

把原 ``ReasoningAgent._classify_domain`` 迁移为独立 Agent：
- temperature=0 稳定分类，18 个数学领域选 1；
- 解析失败 / 禁用时返回 None，后续走通用策略；
- 全程通过 ``ctx.domain`` 与 trace 对外暴露。
"""

import logging
from typing import Optional

from .base import BaseAgent, TaskContext

logger = logging.getLogger("MathPilot")

CLASSIFY_PROMPT = """你是一位数学题目分类专家。请判断以下题目属于哪个数学领域。

可选领域：偏微分方程、复分析、拓扑学、运筹学、代数、数论、几何、概率论、统计学、泛函分析、常微分方程、组合数学、图论、数值分析、实分析、离散数学、数学物理、抽象代数

请只输出领域名称，不要输出任何其他内容。"""

# 已知有效领域（与 prompts/policy.py 中 DOMAIN_HINTS 键保持一致）
_KNOWN_DOMAINS: frozenset = frozenset({
    "偏微分方程", "复分析", "拓扑学", "运筹学", "代数", "数论",
    "几何", "概率论", "统计学", "泛函分析", "常微分方程", "组合数学",
    "图论", "数值分析", "实分析", "离散数学", "数学物理", "抽象代数",
})


class ClassifierAgent(BaseAgent):
    name = "Classifier"

    def run(self, ctx: TaskContext) -> TaskContext:
        if not self.config.enable_domain_hint:
            ctx.domain = None
            self.record(ctx, "classify", "领域提示已禁用，使用通用策略")
            return ctx

        resp = self.llm(ctx, [
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": ctx.problem},
        ], 0.0, 64)

        if resp:
            domain = resp.strip()
            if domain in _KNOWN_DOMAINS:
                ctx.domain = domain
                self.record(ctx, "classify", f"题型分类结果: {domain}", domain=domain)
                logger.info("Domain classified: %s", domain)
                return ctx
            logger.debug("Unknown domain classification: %s", domain)

        ctx.domain = None
        self.record(ctx, "classify", "分类失败，使用通用策略")
        return ctx
