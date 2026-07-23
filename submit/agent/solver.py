"""
通用求解智能体（SolverAgent）
============================

把原 ``ReasoningAgent._generate_candidates`` 迁移为独立 Agent，并新增
**自纠错重解（revise）模式**：

- 初始求解：蓝图分解（LEAP 启发）+ 领域提示注入（复用 prompts/policy）；
- 重解模式：当 ``ctx.revise_feedback`` 非空且处于 revise 轮次时，改用
  ``prompts/revise`` 的纠错提示词，针对验证器指出的错误定向修正；
- 追加候选：中置信度分支调用 ``add_candidates`` 补充采样。
"""

import logging

from .base import BaseAgent, TaskContext, Candidate
try:
    from prompts.policy import (
        get_policy_system,
        get_domain_hint,
        build_blueprint_user_message,
    )
    from prompts.revise import REVISE_SYSTEM, REVISE_USER_TEMPLATE
    from utils.extract import extract_final_answer
except ImportError:  # 作为 submit 子包导入时（如评测器以项目根为 sys.path）
    from submit.prompts.policy import (
        get_policy_system,
        get_domain_hint,
        build_blueprint_user_message,
    )
    from submit.prompts.revise import REVISE_SYSTEM, REVISE_USER_TEMPLATE
    from submit.utils.extract import extract_final_answer

logger = logging.getLogger("MathPilot")


class SolverAgent(BaseAgent):
    name = "Solver"

    def run(self, ctx: TaskContext) -> TaskContext:
        """根据当前上下文状态决定初始求解还是纠错重解"""
        if ctx.revise_round > 0 and ctx.revise_feedback:
            self._generate_revise(ctx)
        else:
            self._generate_initial(ctx)
        return ctx

    def add_candidates(self, ctx: TaskContext, count: int = None) -> TaskContext:
        """中置信度分支：补充生成普通候选（默认与初始采样数一致）"""
        self._generate_initial(ctx, count or self.config.policy_sample_times)
        return ctx

    # ----------------------------------------------------------
    # 初始求解（蓝图分解 + 领域提示）
    # ----------------------------------------------------------
    def _generate_initial(self, ctx: TaskContext, count: int = None) -> None:
        count = count or self.config.policy_sample_times

        if self.config.use_blueprint:
            system_prompt = get_policy_system(use_blueprint=True)
            domain_hint = get_domain_hint(ctx.domain) if ctx.domain else ""
            user_content = build_blueprint_user_message(ctx.problem, domain_hint)
        else:
            system_prompt = get_policy_system(use_blueprint=False)
            user_content = ctx.problem
            if ctx.domain:
                user_content = get_domain_hint(ctx.domain) + "\n" + ctx.problem

        for _ in range(count):
            cid = len(ctx.candidates)
            resp = self.llm(
                ctx,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                self.config.policy_temperature,
                self.config.policy_max_tokens,
            )
            if resp is None:
                # 预算不足 / 调用失败：占位候选，验证器会给 0 置信度
                ctx.candidates.append(Candidate(
                    id=cid, answer="", reasoning="[生成失败] 调用受限"))
                logger.warning("Candidate %d generation failed/skipped", cid)
                continue
            ctx.candidates.append(Candidate(
                id=cid,
                answer=extract_final_answer(resp),
                reasoning=resp,
                revised=False,
            ))
            logger.debug("Candidate %d generated (len=%d)", cid, len(resp))

        self.record(
            ctx, "solve",
            f"生成 {len(ctx.candidates)} 个候选解答 "
            f"(蓝图={self.config.use_blueprint}, 领域={ctx.domain})",
            count=len(ctx.candidates),
        )

    # ----------------------------------------------------------
    # 纠错重解（revise 模式）
    # ----------------------------------------------------------
    def _generate_revise(self, ctx: TaskContext) -> None:
        feedback_text = "\n".join(f"- {fb}" for fb in ctx.revise_feedback)
        count = self.config.revise_sample_times

        for _ in range(count):
            cid = len(ctx.candidates)
            user_content = REVISE_USER_TEMPLATE.format(
                problem=ctx.problem, feedback=feedback_text)
            resp = self.llm(
                ctx,
                [
                    {"role": "system", "content": REVISE_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
                self.config.policy_temperature,
                self.config.policy_max_tokens,
            )
            if resp is None:
                ctx.candidates.append(Candidate(
                    id=cid, answer="", reasoning="[重解失败] 调用受限"))
                logger.warning("Revise candidate %d failed/skipped", cid)
                continue
            ctx.candidates.append(Candidate(
                id=cid,
                answer=extract_final_answer(resp),
                reasoning=resp,
                revised=True,
            ))

        self.record(
            ctx, "revise",
            f"纠错重解 第{ctx.revise_round}轮：生成 {count} 个修正候选",
            round=ctx.revise_round,
        )
