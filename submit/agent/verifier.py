"""
过程校验智能体（VerifierAgent）
==============================

把原 ``ReasoningAgent._verify_candidates`` / ``_vote_on_candidate`` 迁移为
独立 Agent，并新增 **失败原因提取** 能力（供 Orchestrator 触发自纠错回环）：

- 仅对尚未验证的候选投票（支持 revise / 追加候选后的增量验证）；
- 投票结果写入 ``ctx.verdicts``，按置信度降序；
- ``feedback`` 方法在被判定为错误的候选上，额外调用一次验证器提取错因。
"""

import logging

from .base import BaseAgent, TaskContext, Candidate, Verdict
try:
    from prompts.verifier import (
        VERIFIER_SYSTEM,
        VERIFIER_USER_TEMPLATE,
        VERIFIER_FEEDBACK_SYSTEM,
        VERIFIER_FEEDBACK_TEMPLATE,
    )
except ImportError:  # 作为 submit 子包导入时
    from submit.prompts.verifier import (
        VERIFIER_SYSTEM,
        VERIFIER_USER_TEMPLATE,
        VERIFIER_FEEDBACK_SYSTEM,
        VERIFIER_FEEDBACK_TEMPLATE,
    )

logger = logging.getLogger("MathPilot")


class VerifierAgent(BaseAgent):
    name = "Verifier"

    def run(self, ctx: TaskContext) -> TaskContext:
        for c in ctx.candidates:
            if c.id in ctx.verified_ids():
                continue
            ctx.verdicts.append(self._vote(ctx, c))
        ctx.verdicts.sort(key=lambda v: v.confidence, reverse=True)
        self.record(
            ctx, "verify", "验证候选解答",
            verification=[{"id": v.id, "confidence": v.confidence}
                          for v in ctx.verdicts],
        )
        return ctx

    def _vote(self, ctx: TaskContext, c: Candidate) -> Verdict:
        """对单个候选多轮投票，返回带置信度的验证结果"""
        if not c.answer:
            return Verdict(c.id, c.answer, c.reasoning, 0.0, 0, 0)

        correct_votes = 0
        total_votes = self.config.verifier_voting_times

        for _ in range(total_votes):
            user_msg = VERIFIER_USER_TEMPLATE.format(
                problem=ctx.problem,
                candidate_answer=c.reasoning[:3000],
            )
            resp = self.llm(
                ctx,
                [
                    {"role": "system", "content": VERIFIER_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                self.config.verifier_temperature,
                256,
            )
            if resp is None:
                total_votes -= 1
                continue
            if self._is_correct_vote(resp):
                correct_votes += 1

        total = max(total_votes, 1)
        return Verdict(
            c.id, c.answer, c.reasoning,
            round(correct_votes / total, 4), correct_votes, total,
        )

    def feedback(self, ctx: TaskContext, candidate: Candidate) -> str:
        """提取候选解答的错误原因（自纠错回环用）"""
        user_msg = VERIFIER_FEEDBACK_TEMPLATE.format(
            problem=ctx.problem,
            candidate_answer=candidate.reasoning[:3000],
        )
        resp = self.llm(
            ctx,
            [
                {"role": "system", "content": VERIFIER_FEEDBACK_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            0.0, 512,
        )
        return (resp or "未提供错误分析").strip()

    @staticmethod
    def _is_correct_vote(response: str) -> bool:
        """
        解析验证器的投票结果（与原实现保持一致）：
        - VERDICT: A / VERDICT: B
        - 纯输出 A / B
        - CORRECT / INCORRECT
        - 正确 / 错误
        """
        text = response.strip().upper()
        if "VERDICT: A" in text or "VERDICT:A" in text:
            return True
        if "VERDICT: B" in text or "VERDICT:B" in text:
            return False
        if "CORRECT" in text or "正确" in text:
            return True
        if "INCORRECT" in text or "错误" in text or "WRONG" in text:
            return False
        lines = response.strip().split("\n")
        last = lines[-1].strip().upper() if lines else ""
        if last in ("A", "B"):
            return last == "A"
        return True
