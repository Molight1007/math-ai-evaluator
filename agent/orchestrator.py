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
import re as _re

from .base import BaseAgent, TaskContext, Budget
from .classifier import ClassifierAgent, _KNOWN_DOMAINS
from .solver import SolverAgent
from .verifier import VerifierAgent
from .formatter import FormatterAgent
from utils.extract import safe_json_serialize

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
            # 元数据中已知领域 -> 跳过分类器 LLM 调用，直接复用
            pre_known_domain = (metadata or {}).get("domain", "")
            if pre_known_domain and pre_known_domain in _KNOWN_DOMAINS:
                ctx.domain = pre_known_domain
                self.record(
                    ctx, "classify",
                    f"题型分类结果（元数据已知）: {pre_known_domain}",
                    domain=pre_known_domain)
            else:
                self.classifier.run(ctx)       # 题型识别

            # ── 快车道：可确定性求解的题目跳过完整流水线 ──
            fast_result = self._fast_path(ctx)
            if fast_result is not None:
                ctx.final_response = fast_result
                self.record(ctx, "fast_path", f"快车道直接求解: {fast_result[:200]}")
                return safe_json_serialize({
                    "final_response": fast_result,
                    "trace": ctx.trace,
                    "candidates": [],
                    "verdicts": [],
                })

            self.solver.run(ctx)           # 初始候选
            self.verifier.run(ctx)         # 验证
            self._regulate(ctx)            # 自主调控（回环 / 增强 / 提前退出）

            # 答案完整性审核：检查最佳答案是否截断，不完整则续写
            self._ensure_completeness(ctx)

            # 兜底：所有验证结果均为 0/0 票（模型空响应 + 回环也失败）
            # → 跳过复杂流水线，直接用最简提示词让模型单次求解
            if ctx.verdicts and all(v.total_votes == 0 for v in ctx.verdicts):
                self.record(ctx, "control", "所有候选验证投票均为 0，触发兜底直接求解")
                direct_answer = self.solver.direct_solve(ctx)
                if direct_answer:
                    ctx.final_response = direct_answer
                    self.record(ctx, "finalize",
                               f"兜底直接求解结果: {direct_answer[:200]}")
                    return safe_json_serialize({
                        "final_response": direct_answer,
                        "trace": ctx.trace,
                    })
                # 直接求解也失败 → 从所有候选中选最有内容的答案
                best_candidate = self._pick_best_from_candidates(ctx)
                if best_candidate:
                    ctx.final_response = best_candidate
                    self.record(ctx, "finalize",
                               f"兜底也失败，使用最佳候选答案: {best_candidate[:200]}")
                    return safe_json_serialize({
                        "final_response": best_candidate,
                        "trace": ctx.trace,
                    })

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
    # 快车道：可确定性求解的题目
    # ----------------------------------------------------------
    # 预检模式 → 题库分类关键词映射
    _FAST_PATH_PATTERNS = [
        (r"\d+\s*[\+\-\*/×÷]\s*\d+", "arithmetic"),
        (r"(?:calculate|compute|evaluate)\b", "arithmetic"),
        (r"(?:求导|导数|微分|derivative?|differentiate|f'|f''|d/dx)", "derivative"),
        (r"(?:积分|∫|integral|integrate)", "integral"),
        (r"(?:行列式|determinant|det\s*\(|矩阵的?行列式)", "determinant"),
        (r"(?:解(?:方程|方程组)|solve.{0,6}equation)", "equation"),
        (r"(?:一元二次|二次方程|quadratic)", "quadratic"),
        (r"(?:极限|limit)", "limit"),
    ]

    def _fast_path(self, ctx: TaskContext) -> str | None:
        """
        尝试用确定性方法快速求解。成功返回答案，失败返回 None（回退正常工作流）。

        当前策略：仅做预检记录，不拦截流水线。
        未来将集成 SymPy 进行自动求解。
        """
        problem = ctx.problem or ""
        for pattern, tag in self._FAST_PATH_PATTERNS:
            if _re.search(pattern, problem, _re.IGNORECASE):
                self.record(ctx, "fast_path", f"检测到可快车道求解题型: {tag}")
        return None

    # ----------------------------------------------------------
    # 自主调控核心
    # ----------------------------------------------------------
    def _regulate(self, ctx: TaskContext) -> None:
        max_iter = self.config.max_revise_rounds + 2  # 防死循环硬上限
        min_votes_for_high_conf = 2  # 至少 2 票才允许高置信度提前退出
        for _ in range(max_iter):
            if not ctx.verdicts:
                break

            # 过滤掉验证失败的候选（total_votes=0）后再做决策
            valid_verdicts = [v for v in ctx.verdicts if v.total_votes > 0]
            if not valid_verdicts:
                self.record(ctx, "control", "所有候选验证均失败，停止调控")
                break

            best = max(valid_verdicts, key=lambda v: v.confidence)

            # 1) 高置信度 -> 提前退出（节省增强调用）
            # 必须同时满足：置信度够高，且有效票数不少于阈值
            if (best.confidence >= self.config.conf_high
                    and best.total_votes >= min_votes_for_high_conf):
                self.record(
                    ctx, "control",
                    f"高置信度 {best.confidence:.2f} ≥ {self.config.conf_high} "
                    f"({best.correct_votes}/{best.total_votes} 票)，"
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
                        f"低置信度 {best.confidence:.2f} < {self.config.conf_low} "
                        f"({best.correct_votes}/{best.total_votes} 票)，"
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

    def _pick_best_from_candidates(self, ctx: TaskContext) -> str:
        """
        从所有候选中选择最有价值的答案（无正确答案时的兜底选择）。
        优先级：有答案内容的 verdict > 有答案内容的 candidate > 有推理内容的 candidate
        """
        import re as _re
        # 1) 从 verdicts 找有非拒绝答案的
        if ctx.verdicts:
            sorted_v = sorted(ctx.verdicts, key=lambda v: v.confidence, reverse=True)
            for v in sorted_v:
                ans = getattr(v, "answer", "") or ""
                if ans and len(ans) > 3 and not _re.search(r"无法求解|无法解决|不能解决", ans):
                    return ans
        # 2) 从 candidates 找有非拒绝答案的（按推理长度排序 → 越详细越可信）
        if ctx.candidates:
            sorted_c = sorted(ctx.candidates, key=lambda c: len(c.reasoning or ""), reverse=True)
            for c in sorted_c:
                if c.answer and len(c.answer) > 3 and not _re.search(r"无法求解|无法解决|不能解决", c.answer):
                    return c.answer
        # 3) 最后防线：取最详细推理的尾部
        if ctx.candidates:
            best = max(ctx.candidates, key=lambda c: len(c.reasoning or ""))
            if best.reasoning and len(best.reasoning) > 50:
                return best.reasoning.strip()[-500:]
        return ""

    def _ensure_completeness(self, ctx: TaskContext) -> None:
        """
        自我审核：检查最佳候选答案是否完整。
        - 先用 solver 启发式检查，再用 verifier LLM 检查
        - 完整：直接通过
        - 不完整：调用 solver 续写，然后重新验证
        """
        if not ctx.candidates:
            return

        # 找到当前最佳候选（对应最高置信度且验证有效的 verdict 的候选）
        best_cand = None
        valid_verdicts = [v for v in ctx.verdicts if v.total_votes > 0]
        if valid_verdicts:
            best_verdict = max(valid_verdicts, key=lambda v: v.confidence)
            best_cand = next(
                (c for c in ctx.candidates if c.id == best_verdict.id), None)

        if best_cand is None:
            # 没有 verdict，取最详细推理的候选
            if ctx.candidates:
                best_cand = max(ctx.candidates, key=lambda c: len(c.reasoning or ""))

        if best_cand is None:
            return

        # 双重检查完整性：启发式 + LLM 确认
        heuristic_ok = self.solver.is_answer_complete(best_cand.reasoning, best_cand.answer)
        if heuristic_ok:
            self.record(ctx, "complete", "答案完整性检查通过（启发式）")
            return

        # 启发式判断不完整 → 用 LLM 二次确认
        llm_ok = self.verifier.check_completeness(ctx, best_cand)
        if llm_ok:
            self.record(ctx, "complete", "答案完整性检查通过（LLM确认完整）")
            return

        # LLM 也认为不完整 → 续写
        self.record(ctx, "complete",
                   f"答案不完整，触发续写 (候选 #{best_cand.id})")
        completed = self.solver.complete_answer(ctx, best_cand)

        if completed and completed.answer != best_cand.answer:
            # 替换原候选
            for i, cand in enumerate(ctx.candidates):
                if cand.id == best_cand.id:
                    ctx.candidates[i] = completed
                    break
            # 重新验证续写后的候选
            self.verifier.run(ctx)
            self.record(ctx, "complete", "续写后重新验证完成")

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
                messages=[
                    {"role": "system",
                     "content": "你是数学解题专家，请仔细分析并给出最终答案。确保输出完整，不要截断。"},
                    {"role": "user", "content": problem},
                ],
                temperature=0.3,
                max_tokens=self.config.policy_max_tokens,
            )
            answer = (resp or "").strip() or "无法求解"
            # 截断/幻觉检测
            from .base import detect_hallucination, detect_truncated
            if detect_truncated(answer):
                trace.append({
                    "agent": self.name,
                    "step": "fallback",
                    "content": "WARNING: 兜底答案可能被截断",
                })
            hallu = detect_hallucination(answer)
            if hallu:
                trace.append({
                    "agent": self.name,
                    "step": "fallback",
                    "content": f"WARNING: 兜底答案包含幻觉模式 {hallu}",
                })
        except Exception:  # noqa: BLE001
            answer = "无法求解"
        return {
            "final_response": answer,
            "trace": trace,
        }
