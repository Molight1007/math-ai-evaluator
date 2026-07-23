"""
答案规范化智能体（FormatterAgent）
==================================

把原 ``ReasoningAgent`` 末尾的答案抽取 / 兜底逻辑迁移为独立 Agent：
- 从 ``ctx.verdicts``（按置信度最高）或 ``ctx.candidates`` 选择最优答案；
- 通过 ``format_response`` 确保 ``final_response`` 非空且可序列化；
- 结果写入 ``ctx.final_response``，Orchestrator 负责封装返回字典。
"""

import logging

from .base import BaseAgent, TaskContext
try:
    from utils.extract import format_response
except ImportError:  # 作为 submit 子包导入时
    from submit.utils.extract import format_response

logger = logging.getLogger("MathPilot")


class FormatterAgent(BaseAgent):
    name = "Formatter"

    def run(self, ctx: TaskContext) -> TaskContext:
        best = self._pick_best(ctx)
        if best is None:
            answer = "无法求解"
            confidence = 0.0
        else:
            answer = getattr(best, "answer", "") or "无法求解"
            confidence = getattr(best, "confidence", 0.0)

        ctx.final_response = format_response(answer)
        self.record(
            ctx, "finalize",
            f"最终答案: {ctx.final_response[:200]} (置信度: {confidence:.2f})",
            confidence=round(confidence, 4),
        )
        return ctx

    def _pick_best(self, ctx: TaskContext):
        """选择最优答案来源：优先最高置信度 verdict，其次首个非空候选"""
        if ctx.verdicts:
            return max(ctx.verdicts, key=lambda v: v.confidence)
        if ctx.candidates:
            for c in ctx.candidates:
                if c.answer:
                    return c
            return ctx.candidates[0]
        return None
