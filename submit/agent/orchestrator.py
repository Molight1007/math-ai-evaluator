"""
编排器（Orchestrator）
====================

多智能体协作的调度核心，把 4 个 Agent 串成流水线，并实现 **推理自主调控**：

    Classifier -> Solver -> Verifier --(调控决策)--> [Formatter]

自主调控三档分支（每次决策均写入 trace，全程可追溯）：
- 高置信度（>= conf_high）：提前退出，节省增强调用；
- 中置信度（conf_low ~ conf_high）：追加候选并重验（一次性，防死循环）；
- 低置信度（< conf_low 且预算充足）：**自纠错回环**——把验证器的失败原因
  回传给 Solver 定向重解（最多 max_revise_rounds 轮）。

预算（Budget）硬上限保证在竞赛平台调用限额 / 超时约束内绝不越界。
任一环节异常自动降级为单次直接求解，保证 final_response 非空。
"""

import logging

from .base import BaseAgent, TaskContext, Budget
from .classifier import ClassifierAgent
from .solver import SolverAgent
from .verifier import VerifierAgent
from .formatter import FormatterAgent
try:
    from utils.extract import safe_json_serialize
except ImportError:  # 作为 submit 子包导入时
    from submit.utils.extract import safe_json_serialize

logger = logging.getLogger("MathPilot")


class Orchestrator(BaseAgent):
    name = "Orchestrator"

    def __init__(self, client, config):
        super().__init__(client, config)
        self.classifier = ClassifierAgent(client, config)
        self.solver = SolverAgent(client, config)
        self.verifier = VerifierAgent(client, config)
        self.formatter = FormatterAgent(client, config)

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------
    def run(self, problem: str, metadata: dict) -> dict:
        ctx = TaskContext(
            problem=problem,
            metadata=metadata or {},
            budget=Budget(max_calls=self.config.max_total_calls),
        )
        try:
            self.classifier.run(ctx)       # 题型识别
            self.solver.run(ctx)           # 初始候选
            self.verifier.run(ctx)         # 验证
            self._regulate(ctx)            # 自主调控（回环 / 增强 / 提前退出）
            self.formatter.run(ctx)        # 规范化输出
            # 候选与验证结果（纯 dict，便于评测器报告与调试；不破坏平台契约）
            candidates_out = [
                {"id": c.id, "answer": c.answer,
                 "reasoning": c.reasoning, "revised": c.revised}
                for c in ctx.candidates
            ]
            verdicts_out = [
                {"id": v.id, "answer": v.answer,
                 "confidence": v.confidence,
                 "correct_votes": v.correct_votes,
                 "total_votes": v.total_votes,
                 "feedback": v.feedback}
                for v in ctx.verdicts
            ]
            return safe_json_serialize({
                "final_response": ctx.final_response,
                "trace": ctx.trace,
                "candidates": candidates_out,
                "verdicts": verdicts_out,
            })
        except Exception as e:  # noqa: BLE001
            logger.error("Orchestrator run failed: %s", e)
            return self._fallback(ctx, problem, e)

    # ----------------------------------------------------------
    # 自主调控核心
    # ----------------------------------------------------------
    def _regulate(self, ctx: TaskContext) -> None:
        max_iter = self.config.max_revise_rounds + 2  # 防死循环硬上限
        for _ in range(max_iter):
            if not ctx.verdicts:
                break

            best = max(ctx.verdicts, key=lambda v: v.confidence)

            # 1) 高置信度 -> 提前退出（节省增强调用）
            if best.confidence >= self.config.conf_high:
                self.record(
                    ctx, "control",
                    f"高置信度 {best.confidence:.2f} ≥ {self.config.conf_high}，"
                    f"提前退出（节省增强调用）")
                break

            # 2) 预算不足 -> 直接出结果
            if not ctx.budget.can_spend(2):
                self.record(ctx, "control", "预算不足，停止增强并出结果")
                break

            # 3) 低置信度 -> 自纠错回环
            if (best.confidence < self.config.conf_low
                    and ctx.revise_round < self.config.max_revise_rounds):
                feedback = self._collect_feedback(ctx, best)
                if feedback:
                    ctx.revise_feedback.append(feedback)
                    ctx.revise_round += 1
                    self.record(
                        ctx, "control",
                        f"低置信度 {best.confidence:.2f} < {self.config.conf_low}，"
                        f"触发自纠错回环 R{ctx.revise_round}：{feedback[:120]}")
                    self.solver.run(ctx)    # 定向重解（追加修正候选）
                    self.verifier.run(ctx)  # 重新验证（含旧候选，最差退化为多一个候选）
                    continue

            # 4) 中置信度 -> 追加候选并重验（一次性）
            if ctx.budget.can_spend(self.config.policy_sample_times + 1):
                self.record(
                    ctx, "control",
                    f"中置信度 {best.confidence:.2f}，追加候选并重验")
                self.solver.add_candidates(ctx, count=2)
                self.verifier.run(ctx)
            break

    def _collect_feedback(self, ctx: TaskContext, verdict) -> str:
        """针对当前最差候选，让验证器提取失败原因"""
        cand = next((c for c in ctx.candidates if c.id == verdict.id), None)
        if cand is None or not cand.reasoning:
            return ""
        return self.verifier.feedback(ctx, cand)

    # ----------------------------------------------------------
    # 兜底：单次直接求解，保证 final_response 非空
    # ----------------------------------------------------------
    def _fallback(self, ctx: TaskContext, problem: str, exc: Exception) -> dict:
        trace = list(ctx.trace) if ctx.trace else []
        trace.append({
            "agent": self.name,
            "step": "error",
            "content": f"求解异常: {type(exc).__name__}: {exc}",
        })
        try:
            resp = self.client.chat(
                [
                    {"role": "system",
                     "content": "你是数学解题专家，请仔细分析并给出最终答案。"},
                    {"role": "user", "content": problem},
                ],
                0.3, self.config.policy_max_tokens,
            )
            answer = (resp or "").strip() or "无法求解"
        except Exception:  # noqa: BLE001
            answer = "无法求解"
        return {
            "final_response": answer,
            "trace": trace,
        }
