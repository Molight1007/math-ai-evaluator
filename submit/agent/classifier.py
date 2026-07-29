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

可选领域：
函数极限与连续、导数与微分、微分中值定理、不定积分、定积分、定积分的应用、
多元函数微分学、多元函数积分学、曲线与曲面积分、常微分方程、无穷级数、
向量代数与空间解析几何、线性代数、概率论与数理统计

请只输出领域名称，不要输出任何其他内容。"""

# 已知有效领域（与 prompts/policy.py 中 DOMAIN_HINTS 键保持一致）
_KNOWN_DOMAINS: frozenset = frozenset({
    "函数极限与连续", "导数与微分", "微分中值定理",
    "不定积分", "定积分", "定积分的应用",
    "多元函数微分学", "多元函数积分学", "曲线与曲面积分",
    "常微分方程", "无穷级数", "向量代数与空间解析几何",
    "偏微分方程", "复分析", "拓扑学", "运筹学", "代数", "数论",
    "几何", "概率论", "统计学", "泛函分析", "组合数学",
    "图论", "数值分析", "实分析", "离散数学", "数学物理", "抽象代数",
    "线性代数", "概率论与数理统计",
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
            domain = resp.strip().rstrip("。.，,、")
            # 精确匹配
            if domain in _KNOWN_DOMAINS:
                ctx.domain = domain
                self.record(ctx, "classify", f"题型分类结果: {domain}", domain=domain)
                logger.info("Domain classified: %s", domain)
                return ctx
            # 模糊匹配：尝试在已知领域中找包含关系
            for known in _KNOWN_DOMAINS:
                if known in domain or domain in known:
                    ctx.domain = known
                    self.record(ctx, "classify", f"题型分类结果(模糊): {domain} → {known}", domain=known)
                    logger.info("Domain classified (fuzzy): %s -> %s", domain, known)
                    return ctx
            # 看起来像有效的中文领域名 → 仍然采用（但不保证有 DOMAIN_HINTS）
            if len(domain) >= 3 and any('\u4e00' <= ch <= '\u9fff' for ch in domain):
                ctx.domain = domain
                self.record(ctx, "classify", f"题型分类结果(新领域): {domain}", domain=domain)
                logger.info("Domain classified (novel): %s", domain)
                return ctx
            logger.debug("Unknown domain classification: %s", domain)

        ctx.domain = None
        self.record(ctx, "classify", "分类失败，使用通用策略")
        return ctx
