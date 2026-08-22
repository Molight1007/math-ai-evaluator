from __future__ import annotations
"""难题三Agent协作求解器（CollaborativeSolver，v2.6）。

针对 deep 档难题，三个角色分工协作（协作链路为串行依赖；平台并发度=3 由
Orchestrator/main 的信号量约束，本模块单题内不额外开线程）：

  1. 解题 Agent  —— 完整求解，给出初步解答；
  2. 审查 Agent  —— 审查解答，定位并指出错误；
  3. 整合 Agent  —— 综合解题输出与审查意见，给出最终答案；
  4. 验证 Agent  —— 对整合结果做正确性判定（VERDICT: A/B）。

反复验证循环：只要时间未到、预算未耗尽、且验证仍未通过，
就回到「审查 → 整合 → 验证」，用上一轮的审查/验证反馈驱动修正，
直到验证通过或资源耗尽，保证难题高正确率。

超时约束：每道题最长处理时间 20 分钟由 Orchestrator 的 ``ctx.deadline``
（config.max_time_per_question=1200s）硬限；所有 LLM 调用都经
``BaseAgent.llm`` 的时间预算感知（剩余<60s 跳过），保证超时题目有兜底产出。
"""

import logging

from .base import BaseAgent, TaskContext, Candidate
from utils.extract import (
    extract_final_answer,
    rescue_final_answer,
    smart_fallback_answer,
)
from utils.prefill import prefill_messages, stitch

logger = logging.getLogger("MathPilot.Collaborative")


# ---------------------------------------------------------------------------
# 三角色提示词
# ---------------------------------------------------------------------------
_SOLVER_SYS = (
    "你是数学解题专家（协作链路中的【解题Agent】）。"
    "请对下面这道难题给出完整、严谨的求解过程，逐步推理并给出最终答案。"
    "不要省略关键步骤，最终以【最终答案】给出明确结论。"
)

_REVIEWER_SYS = (
    "你是数学证明审查专家（协作链路中的【审查Agent】）。"
    "请严格审查下面的解题过程，找出其中的错误、漏洞或跳步："
    "逐条列出「步骤定位 → 问题描述 → 修改建议」。"
    "若解答正确，也请明确说明其推理无误。不要重新解题，只做审查。"
)

_INTEGRATOR_SYS = (
    "你是数学解题总负责人（协作链路中的【整合Agent】）。"
    "请综合【解题Agent】的输出与【审查Agent】的意见，"
    "修正错误、补全漏洞，给出最终的正确解答，并以【最终答案】给出明确结论。"
)

_VERIFIER_SYS = (
    "你是严谨的数学解答评审专家。请独立验证下面的解答是否正确："
    "独立重算、对比答案、审查推理后，只输出一行 VERDICT: A（正确）或 VERDICT: B（错误）。"
)


def _parse_verdict(text: str) -> bool:
    """解析验证结果：VERDICT: A → True（通过），B → False（未通过）。"""
    if not text:
        return False
    upper = text.upper()
    if "INCORRECT" in upper or "WRONG" in upper or "FALSE" in upper:
        return False
    if "VERDICT" in upper and "B" in upper.split("VERDICT")[-1][:4]:
        return False
    if "CORRECT" in upper or "VERDICT" in upper and "A" in upper:
        return True
    return False


class CollaborativeSolver(BaseAgent):
    """难题三Agent协作：解题 → 审查 → 整合 → 验证（反复循环）。"""

    name = "CollaborativeSolver"

    def run(self, ctx: TaskContext) -> TaskContext:
        if ctx.is_time_critical() or ctx.is_timed_out():
            self.record(ctx, "collab", "时间紧张/超时，跳过三Agent协作")
            return ctx
        if ctx.budget is not None and not ctx.budget.can_spend(3):
            self.record(ctx, "collab", "预算不足，跳过三Agent协作")
            return ctx

        # 1) 解题 Agent（一次性）
        solution = self._role_solve(ctx)
        if not solution:
            self.record(ctx, "collab", "解题Agent未产出有效结果，协作终止")
            return ctx

        review = ""
        final = solution
        max_rounds = getattr(self.config, 'collab_max_rounds', 4)

        for rnd in range(1, max_rounds + 1):
            # 时间/预算耗尽 → 用当前 best 兜底返回
            if ctx.is_time_critical() or ctx.is_timed_out():
                self.record(ctx, "collab", f"第{rnd}轮前时间紧张，停止协作循环")
                break
            if ctx.budget is not None and not ctx.budget.can_spend(2):
                self.record(ctx, "collab", f"第{rnd}轮前预算不足，停止协作循环")
                break

            # 2) 审查 Agent：首轮审 solution，后续审上一轮 final
            if rnd == 1:
                review = self._role_review(ctx, solution)
            else:
                review = self._role_review(ctx, final)

            # 3) 整合 Agent：综合解题输出 + 审查意见 +（后续轮）上一轮结果
            if rnd == 1:
                final = self._role_integrate(ctx, solution, review)
            else:
                final = self._role_integrate_round(ctx, solution, review, final)

            if not final:
                self.record(ctx, "collab", f"第{rnd}轮整合Agent未产出有效结果")
                break

            # 4) 验证 Agent：判定是否正确
            ok = self._role_verify(ctx, final)
            if ok:
                self.record(ctx, "collab", f"第{rnd}轮验证通过，协作成功")
                break
            self.record(ctx, "collab", f"第{rnd}轮验证未通过，继续审查修正")

        answer = extract_final_answer(final)
        if not answer or len(answer) > 300:
            answer = rescue_final_answer(final)[0] or smart_fallback_answer(final)
        candidate = Candidate(
            id=len(ctx.candidates),
            answer=answer or "",
            reasoning=final,
            revised=False,
        )
        ctx.candidates.append(candidate)
        self.record(
            ctx, "collab",
            f"三Agent协作结束，生成候选 #{candidate.id}",
            answer=(answer or "")[:100],
        )
        return ctx

    # ------------------------------------------------------------------
    # 角色调用（均走 prefill 抑制 CoT + 预算/时间感知）
    # ------------------------------------------------------------------
    def _role_solve(self, ctx: TaskContext) -> str:
        resp = self.llm(
            ctx,
            prefill_messages(
                [
                    {"role": "system", "content": _SOLVER_SYS},
                    {"role": "user", "content": ctx.problem},
                ],
                "## 解题过程\n",
            ),
            0.3,
            self.config.policy_max_tokens,
        )
        return stitch("## 解题过程\n", resp) if resp else ""

    def _role_review(self, ctx: TaskContext, target: str) -> str:
        user = f"题目：\n{ctx.problem}\n\n待审查的解答：\n{target[-4000:]}"
        resp = self.llm(
            ctx,
            prefill_messages(
                [
                    {"role": "system", "content": _REVIEWER_SYS},
                    {"role": "user", "content": user},
                ],
                "## 审查意见\n",
            ),
            0.1,
            4096,
        )
        return stitch("## 审查意见\n", resp) if resp else ""

    def _role_integrate(self, ctx: TaskContext, solution: str, review: str) -> str:
        user = (
            f"题目：\n{ctx.problem}\n\n"
            f"【解题Agent】输出：\n{solution[-4000:]}\n\n"
            f"【审查Agent】意见：\n{review[-2000:]}"
        )
        resp = self.llm(
            ctx,
            prefill_messages(
                [
                    {"role": "system", "content": _INTEGRATOR_SYS},
                    {"role": "user", "content": user},
                ],
                "## 最终解答\n",
            ),
            0.1,
            self.config.policy_max_tokens,
        )
        return stitch("## 最终解答\n", resp) if resp else ""

    def _role_integrate_round(self, ctx: TaskContext, solution: str,
                              review: str, prev: str) -> str:
        """后续轮整合：综合原始解题 + 最新审查意见 + 上一轮结果。"""
        user = (
            f"题目：\n{ctx.problem}\n\n"
            f"【解题Agent】输出：\n{solution[-3000:]}\n\n"
            f"【上一轮解答】：\n{prev[-2000:]}\n\n"
            f"【本轮审查Agent】意见：\n{review[-2000:]}"
        )
        resp = self.llm(
            ctx,
            prefill_messages(
                [
                    {"role": "system", "content": _INTEGRATOR_SYS},
                    {"role": "user", "content": user},
                ],
                "## 最终解答\n",
            ),
            0.1,
            self.config.policy_max_tokens,
        )
        return stitch("## 最终解答\n", resp) if resp else ""

    def _role_verify(self, ctx: TaskContext, final: str) -> bool:
        answer = extract_final_answer(final)
        user = f"题目：\n{ctx.problem}\n\n待验证解答：\n{final[-3000:]}"
        if answer:
            user += f"\n\n候选最终答案：{answer}"
        resp = self.llm(
            ctx,
            prefill_messages(
                [
                    {"role": "system", "content": _VERIFIER_SYS},
                    {"role": "user", "content": user},
                ],
                "VERDICT: ",
            ),
            0.0,
            512,
        )
        text = stitch("VERDICT: ", resp) if resp else ""
        return _parse_verdict(text)
