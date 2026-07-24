"""
过程校验智能体（VerifierAgent）
==============================

把原 ``ReasoningAgent._verify_candidates`` / ``_vote_on_candidate`` 迁移为
独立 Agent，并新增 **失败原因提取** 能力（供 Orchestrator 触发自纠错回环）：

- 仅对尚未验证的候选投票（支持 revise / 追加候选后的增量验证）；
- 投票结果写入 ``ctx.verdicts``，按置信度降序；
- ``feedback`` 方法在被判定为错误的候选上，额外调用一次验证器提取错因。

性能优化：
- 多候选验证并行执行；
- 单个候选的多轮投票并行执行。
"""

import concurrent.futures
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
        to_verify = [c for c in ctx.candidates if c.id not in ctx.verified_ids()]
        if not to_verify:
            ctx.verdicts.sort(key=lambda v: v.confidence, reverse=True)
            self.record(ctx, "verify", "无需验证候选")
            return ctx

        # 并行验证所有未验证候选
        new_verdicts = []
        workers = max(1, min(8, len(to_verify)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._vote, ctx, c) for c in to_verify]
            for fut in concurrent.futures.as_completed(futures):
                new_verdicts.append(fut.result())

        ctx.verdicts.extend(new_verdicts)
        ctx.verdicts.sort(key=lambda v: v.confidence, reverse=True)
        self.record(
            ctx, "verify", "验证候选解答",
            verification=[{"id": v.id, "confidence": v.confidence}
                          for v in ctx.verdicts],
        )
        return ctx

    def _vote(self, ctx: TaskContext, c: Candidate) -> Verdict:
        """对单个候选多轮投票，返回带置信度的验证结果（投票并行）"""
        if not c.answer:
            return Verdict(c.id, c.answer, c.reasoning, 0.0, 0, 0)

        total_votes = self.config.verifier_voting_times

        def _do_one_vote(_: int):
            user_msg = VERIFIER_USER_TEMPLATE.format(
                problem=ctx.problem,
                candidate_answer=c.reasoning[:3000],
            )
            return self.llm(
                ctx,
                [
                    {"role": "system", "content": VERIFIER_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                self.config.verifier_temperature,
                256,
            )

        valid_responses = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=total_votes) as pool:
            futures = [pool.submit(_do_one_vote, i) for i in range(total_votes)]
            for fut in concurrent.futures.as_completed(futures):
                resp = fut.result()
                if resp is not None:
                    valid_responses.append(resp)

        correct_votes = sum(1 for resp in valid_responses if self._is_correct_vote(resp))
        total = max(len(valid_responses), 1)
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
