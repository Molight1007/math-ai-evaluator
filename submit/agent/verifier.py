"""
过程校验智能体（VerifierAgent）
==============================

把原 ``ReasoningAgent._verify_candidates`` / ``_vote_on_candidate`` 迁移为
独立 Agent，并新增 **失败原因提取** 能力（供 Orchestrator 触发自纠错回环）：

- 仅对尚未验证的候选投票（支持 revise / 追加候选后的增量验证）；
- 投票结果写入 ``ctx.verdicts``，按置信度降序；
- ``feedback`` 方法在被判定为错误的候选上，额外调用一次验证器提取错因。

执行策略：
- 候选之间、同一候选的各轮投票均串行执行，避免并发 API 调用触发速率限制；
- 置信度分母固定为配置的投票次数，确保少量有效投票时不会虚高到 1.0。
"""

import logging
import time

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

        # 串行验证所有未验证候选，避免 API 请求风暴
        new_verdicts = []
        for c in to_verify:
            verdict = self._vote(ctx, c)
            new_verdicts.append(verdict)
            # 候选之间短暂间隔，进一步降低并发压力
            time.sleep(0.5)

        ctx.verdicts.extend(new_verdicts)
        ctx.verdicts.sort(key=lambda v: v.confidence, reverse=True)
        self.record(
            ctx, "verify", "验证候选解答",
            verification=[{"id": v.id, "confidence": v.confidence,
                           "correct_votes": v.correct_votes, "total_votes": v.total_votes}
                          for v in ctx.verdicts],
        )
        return ctx

    def _vote(self, ctx: TaskContext, c: Candidate) -> Verdict:
        """对单个候选多轮投票，返回带置信度的验证结果（投票串行+重试）"""
        if not c.answer:
            # 兜底：answer 为空时尝试从 reasoning 尾部提取（最多 500 字符）
            reasoning_text = c.reasoning.strip() if c.reasoning else ""
            if not reasoning_text or reasoning_text.startswith("[生成失败]") or reasoning_text.startswith("[重解失败]"):
                return Verdict(c.id, c.answer, c.reasoning, 0.0, 0, 0)
            try:
                from utils.extract import extract_final_answer
            except ImportError:
                from submit.utils.extract import extract_final_answer
            fallback_answer = extract_final_answer(reasoning_text)
            if not fallback_answer:
                fallback_answer = reasoning_text[-500:]
            c.answer = fallback_answer

        total_votes = self.config.verifier_voting_times

        def _do_one_vote():
            # 把答案 + 尾部推理（而非头部）传给验证器，确保答案被看到
            reasoning_tail = c.reasoning[-2500:] if len(c.reasoning) > 2500 else c.reasoning
            combined = f"最终答案：{c.answer}\n\n推理尾部：\n{reasoning_tail}"
            user_msg = VERIFIER_USER_TEMPLATE.format(
                problem=ctx.problem,
                candidate_answer=combined,
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
        # 串行投票 + 失败重试（避免并发 API 调用触发速率限制）
        for i in range(total_votes):
            resp = None
            for retry in range(2):
                resp = _do_one_vote()
                if resp is not None:
                    break
                if retry == 0:
                    logger.warning("Verifier vote %d for candidate %d empty, retry", i, c.id)
                    time.sleep(1.0)
            if resp is not None:
                valid_responses.append(resp)
            if i < total_votes - 1:
                time.sleep(0.5)

        correct_votes = sum(1 for resp in valid_responses if self._is_correct_vote(resp))

        # 没有任何有效投票 → 返回 total_votes=0，让 orchestrator 感知验证失败
        if not valid_responses:
            return Verdict(c.id, c.answer, c.reasoning, 0.0, 0, 0)

        # 使用配置的 total_votes 作为分母，避免 1/1 变成 1.0
        confidence = round(correct_votes / total_votes, 4)
        return Verdict(
            c.id, c.answer, c.reasoning,
            confidence, correct_votes, total_votes,
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

    def check_completeness(self, ctx: TaskContext, candidate: Candidate) -> bool:
        """
        用 LLM 检查答案是否完整（未被截断、有明确结论）。
        返回 True 表示完整，False 表示不完整。
        """
        check_prompt = (
            "请判断以下数学推理是否完整（未被截断，有明确的最终答案）。\n"
            "只回复 YES 或 NO，不要任何解释。\n\n"
            f"提取的答案：{candidate.answer or '(空)'}\n"
            f"推理尾部（最后 600 字符）：\n{candidate.reasoning[-600:] if candidate.reasoning else '(空)'}"
        )
        try:
            resp = self.llm(
                ctx,
                [{"role": "system", "content": "只回复 YES 或 NO。"},
                 {"role": "user", "content": check_prompt}],
                0.0, 16,
            )
        except Exception:
            return True  # 网络错误时保守认为完整
        if resp is None:
            return True
        resp_upper = resp.strip().upper()
        if "YES" in resp_upper and "NO" not in resp_upper:
            return True
        if "NO" in resp_upper:
            return False
        return True  # 默认认为完整

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
        return False
