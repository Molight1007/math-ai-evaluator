from __future__ import annotations
"""
编排器（Orchestrator）—— 简化版
================================

借鉴 ss-main 的简洁流水线，不做复杂回环，每道题 LLM 调用控制在 7 次以内：

    Classifier → Solver → Verifier → Formatter
    (1次LLM)   (3次并行)  (3次投票)  (无LLM)

弱化改动：
- 不设蓝图分解（use_blueprint=False，对 Intern-S 思维流友好）
- 不设自纠错回环（直接用聚类选最优候选）
- 不设完整性审核链（省去 3+ 次 LLM 确认与续写）
- Symbol 快车道仍在（可确定性求解时短路）
"""

import logging
import time
import re as _re

from .base import BaseAgent, TaskContext, Budget, Verdict
from .classifier import ClassifierAgent, _KNOWN_DOMAINS
from .solver import SolverAgent
from .sub_goal_solver import SubGoalSolverAgent
from .verifier import VerifierAgent, AnswerCluster
from .formatter import FormatterAgent
from utils.extract import safe_json_serialize

try:
    from utils.sympy_tools import (
        _HAS_SYMPY, eval_expression, compute_derivative,
        compute_integral, compute_determinant, solve_equation,
        compute_limit,
    )
except ImportError:
    _HAS_SYMPY = False

logger = logging.getLogger("MathPilot")


class Orchestrator(BaseAgent):
    name = "Orchestrator"

    def __init__(self, client, config):
        super().__init__(client, config)
        self.classifier = ClassifierAgent(client, config)
        self.solver = SolverAgent(client, config)
        self.sub_goal_solver = SubGoalSolverAgent(client, config)
        self.verifier = VerifierAgent(client, config)
        self.formatter = FormatterAgent(client, config)

    # ----------------------------------------------------------
    # 主入口（简化版流水线）
    # ----------------------------------------------------------
    def run(self, problem: str, metadata: dict) -> dict:
        now = time.time()
        ctx = TaskContext(
            problem=problem,
            metadata=metadata or {},
            budget=Budget(max_calls=self.config.max_total_calls),
            start_time=now,
            deadline=now + getattr(self.config, 'max_time_per_question', 300),
            total_start_time=now,
            total_deadline=now + getattr(self.config, 'max_total_time_seconds', 21000),
        )
        try:
            # 1) 题型识别（元数据已知时跳过 LLM）
            pre_known_domain = (metadata or {}).get("domain", "")
            if pre_known_domain and pre_known_domain in _KNOWN_DOMAINS:
                ctx.domain = pre_known_domain
                self.record(ctx, "classify",
                    f"题型分类（元数据已知）: {pre_known_domain}", domain=pre_known_domain)
            elif self.config.enable_domain_hint:
                self.classifier.run(ctx)

            # 2) 快车道（可确定性求解 → 直接出结果）
            fast_result = self._fast_path(ctx)
            if fast_result is not None:
                ctx.final_response = fast_result
                self.record(ctx, "fast_path", f"快车道直接求解: {fast_result[:200]}")
                return safe_json_serialize({
                    "final_response": fast_result, "trace": ctx.trace,
                    "candidates": [], "verdicts": [],
                })

            # 3) 求解（3 候选并行）
            self.solver.run(ctx)
            if not ctx.candidates:
                self.record(ctx, "control", "Solver 未产出候选，触发兜底直接求解")
                return self._fallback_direct(ctx)

            # 3.5) 子目标分解补充候选（可选）：候选不足或证明/难题时触发
            is_proof = getattr(ctx, 'domain', '') in ('证明', '证明题')
            if (getattr(self.config, 'use_sub_goal', False)
                    and ctx.budget.can_spend(3)
                    and (len(ctx.candidates) < 2 or is_proof)):
                self.record(ctx, "control",
                            "候选不足或证明题，触发子目标分解补充候选",
                            sub_goal_trigger=f"candidates={len(ctx.candidates)}, is_proof={is_proof}")
                self.sub_goal_solver.run(ctx)

            # 4) 验证（每候选 1 票 + 聚类选最优）
            ver_result = self.verifier.run(
                ctx, problem=ctx.problem, candidates=ctx.candidates,
                use_clustering=True,
                use_scoring=self.config.use_scoring,
                is_proof=is_proof,
            )
            ctx.verdicts = self._verdicts_from_ver_result(ver_result, ctx.candidates)
            ctx._best_cluster = ver_result.get("best_cluster")
            ctx._cluster_data = ver_result.get("cluster_data", [])

            # 5) 全部 0 正确票 → 兜底直接求解（不做回环）
            if (ctx.verdicts
                    and all(v.total_votes > 0 for v in ctx.verdicts)
                    and all(v.correct_votes == 0 for v in ctx.verdicts)):
                self.record(ctx, "control", "全部 0 正确票，触发兜底直接求解")
                direct_answer = self.solver.direct_solve(ctx)
                if direct_answer:
                    ctx.final_response = direct_answer
                    return safe_json_serialize({
                        "final_response": direct_answer, "trace": ctx.trace,
                    })
                best = self._pick_best_from_candidates(ctx)
                if best:
                    ctx.final_response = best
                    return safe_json_serialize({
                        "final_response": best, "trace": ctx.trace,
                    })

            # 6) 格式化输出
            self.formatter.run(ctx)

            # 构建返回
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
                for v in (ctx.verdicts or [])
            ]
            cluster_out = None
            bc = getattr(ctx, '_best_cluster', None)
            if bc:
                cluster_out = {
                    "answer_norm": bc.answer_norm,
                    "size": bc.size,
                    "confidence": bc.confidence,
                    "candidate_ids": bc.candidate_ids,
                }
            return safe_json_serialize({
                "final_response": ctx.final_response or "",
                "trace": ctx.trace,
                "candidates": candidates_out,
                "verdicts": verdicts_out,
                "cluster": cluster_out,
            })
        except Exception as e:  # noqa: BLE001
            logger.error("Orchestrator run failed: %s", e)
            return self._fallback(ctx, problem, e)

    # ----------------------------------------------------------
    # 快车道：可确定性求解的题目直接用 SymPy 短路
    # ----------------------------------------------------------
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
        problem = ctx.problem or ""
        for pattern, tag in self._FAST_PATH_PATTERNS:
            if not _re.search(pattern, problem, _re.IGNORECASE):
                continue
            self.record(ctx, "fast_path", f"检测到可快车道求解题型: {tag}")
            if not _HAS_SYMPY:
                self.record(ctx, "fast_path", "SymPy 未安装，跳过快车道")
                continue
            result = self._try_sympy_solve(problem, tag)
            if result:
                self.record(ctx, "fast_path", f"快车道 SymPy 求解成功: {result}")
                return result
            self.record(ctx, "fast_path", f"快车道 {tag}: SymPy 求解失败，回退")
        return None

    def _try_sympy_solve(self, problem: str, tag: str) -> str | None:
        extract_prompt = (
            "请从以下题目中提取**核心数学表达式**（只输出表达式，不要额外文字）。"
            f"\n\n题目类型: {tag}\n题目: {problem}\n\n表达式:"
        )
        try:
            raw_expr = self.client.chat(
                messages=[
                    {"role": "system", "content": "你只输出数学表达式，不要任何解释。"},
                    {"role": "user", "content": extract_prompt},
                ],
                temperature=0.0,
                max_tokens=256,
            )
            raw_expr = (raw_expr or "").strip()
        except Exception:
            return None
        if not raw_expr or len(raw_expr) > 500:
            return None
        try:
            if tag in ("arithmetic", "quadratic"):
                return eval_expression(raw_expr)
            elif tag == "derivative":
                return compute_derivative(raw_expr)
            elif tag == "integral":
                return compute_integral(raw_expr)
            elif tag == "determinant":
                return compute_determinant(raw_expr)
            elif tag in ("equation",):
                return solve_equation(raw_expr)
            elif tag == "limit":
                return compute_limit(raw_expr)
        except Exception:
            pass
        return None

    def _verdicts_from_ver_result(self, ver_result: dict, candidates: list = None) -> list:
        """将验证器产出的多票结果汇总为 Verdict 数据类列表。

        每个候选可能有多张票（Verdict），此处聚合成一个汇总 Verdict：
        - confidence = 正确票 / 总票数
        - answer 取自候选（便于 Formatter 兜底直接使用）
        - feedback 取第一张有效票的反馈，score 取第一张非空票的评分
        """
        all_verdicts = ver_result.get("verdicts", [])
        result = []
        for idx, vds in enumerate(all_verdicts):
            correct_votes = sum(1 for v in vds if v.correct)
            total_votes = len(vds)
            candidate = candidates[idx] if candidates and idx < len(candidates) else None
            answer = candidate.answer if candidate else ""
            feedback = next((v.feedback for v in vds if v.feedback), "")
            score = next((v.score for v in vds if v.score is not None), None)
            result.append(Verdict(
                id=idx,
                answer=answer,
                confidence=correct_votes / total_votes if total_votes else 0.0,
                correct_votes=correct_votes,
                total_votes=total_votes,
                feedback=feedback,
                score=score,
            ))
        return result

    def _pick_best_from_candidates(self, ctx: TaskContext) -> str:
        import re as _re
        # 1) 从 verdicts 找有非拒绝答案的
        if ctx.verdicts:
            sorted_v = sorted(ctx.verdicts, key=lambda v: v.confidence, reverse=True)
            for v in sorted_v:
                ans = getattr(v, "answer", "") or ""
                if ans and len(ans) > 3 and not _re.search(r"无法求解|无法解决|不能解决", ans):
                    return ans
        # 2) 从 candidates 找有非拒绝答案的
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

    def _fallback_direct(self, ctx: TaskContext) -> dict:
        """Solver 无候选 → 直接 LLM 求解"""
        try:
            resp = self.client.chat(
                messages=[
                    {"role": "system", "content": "你是数学解题专家，请仔细分析并给出最终答案。确保输出完整。"},
                    {"role": "user", "content": ctx.problem},
                ],
                temperature=0.3,
                max_tokens=self.config.policy_max_tokens,
            )
            answer = (resp or "").strip()
            if not answer or len(answer) < 5:
                answer = ctx.problem[:500]
            return safe_json_serialize({
                "final_response": answer, "trace": ctx.trace,
            })
        except Exception:
            return safe_json_serialize({
                "final_response": ctx.problem[:500], "trace": ctx.trace,
            })

    def _fallback(self, ctx: TaskContext, problem: str, exc: Exception) -> dict:
        trace = list(ctx.trace) if ctx.trace else []
        trace.append({
            "agent": self.name, "step": "error",
            "content": f"求解异常: {type(exc).__name__}: {exc}",
        })
        answer = self._pick_best_from_candidates(ctx)
        if answer:
            trace.append({"agent": self.name, "step": "fallback",
                          "content": "使用已有候选最佳答案作为兜底"})
            return {"final_response": answer, "trace": trace}
        # 尝试单次 LLM
        try:
            resp = self.client.chat(
                messages=[
                    {"role": "system", "content": "你是数学解题专家，请仔细分析并给出最终答案。确保输出完整。"},
                    {"role": "user", "content": problem},
                ],
                temperature=0.3,
                max_tokens=self.config.policy_max_tokens,
            )
            answer = (resp or "").strip()
        except Exception:
            answer = ""
        if not answer or len(answer) < 5:
            answer = problem[:500] if problem else "请重新提问"
            trace.append({"agent": self.name, "step": "fallback",
                          "content": "所有求解尝试均失败，返回原始问题文本"})
        return {"final_response": answer, "trace": trace}
