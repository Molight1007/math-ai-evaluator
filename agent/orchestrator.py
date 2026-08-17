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

from .base import BaseAgent, TaskContext, Budget, Verdict, _normalize_chat_response
from .classifier import ClassifierAgent, _KNOWN_DOMAINS
from .solver import SolverAgent
from .sub_goal_solver import SubGoalSolverAgent
from .verifier import VerifierAgent, AnswerCluster
from .formatter import FormatterAgent
from .difficulty_router import DifficultyRouter
from .paper_pacer import PaperPacer
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
        # 难题深度求解通道（v2.5）
        self.difficulty_router = DifficultyRouter(client, config)
        self.pacer = PaperPacer(config)

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
            # 0) PaperPacer 全卷时间池：5h 目标动态预算帽 + MIN_SOFT 保底
            self.pacer.begin()
            ctx.pacer_remaining = self.pacer.hard_remaining()
            elapsed_total = time.time() - ctx.total_start_time
            total_budget = ctx.total_deadline - ctx.total_start_time
            ratio = elapsed_total / total_budget if total_budget > 0 else 0.0
            self.config._time_ratio = ratio
            if ratio > 0.75:
                # 应急模式：候选→1、投票→1，跳过续写/复算（45 error 主因根治）
                self.config.policy_sample_times = max(1, self.config.policy_sample_times - 1)
                self.config.verifier_voting_times = 1
                self.config._emergency = True
                self.config._playoff_enabled = False
                self.record(ctx, "paper_pacer", f"应急模式：已用 {ratio:.0%} 总预算")
            elif ratio > 0.5:
                self.config.verifier_voting_times = 1
                self.config._emergency = False
                self.config._playoff_enabled = False
                self.record(ctx, "paper_pacer", f"时间收紧：已用 {ratio:.0%} 总预算")
            else:
                self.config._emergency = False
                self.config._playoff_enabled = True

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
                self.pacer.end()
                return safe_json_serialize({
                    "final_response": fast_result, "trace": ctx.trace,
                    "candidates": [], "verdicts": [],
                })

            # 2.5) 难度路由：静态预判 + LLM 自评 → 三级档位（难题深度通道）
            self.difficulty_router.run(ctx)
            tier = getattr(ctx, 'tier', 'standard')
            # 应急模式：所有档位强制降级到 fast（预算收紧，保产出）
            if getattr(self.config, '_emergency', False) and tier != 'fast':
                ctx.tier = 'fast'
                tier = 'fast'
                self.record(ctx, "paper_pacer", "应急模式：强制降档到 fast")
            # 全卷时间池动态预算帽（写入 ctx 供 trace/诊断）
            ctx.soft_budget = self.pacer.budget_for(tier)
            # 按档位调整 LLM 调用预算（deep 档需要更多调用次数）
            max_calls = self.config.tier_max_calls.get(
                tier, self.config.max_total_calls)
            if ctx.budget is not None:
                ctx.budget.set_max_calls(max_calls)
            self.record(ctx, "paper_pacer",
                        f"档位 {tier} 软预算帽 {ctx.soft_budget:.0f}s "
                        f"(剩余目标 {ctx.pacer_remaining:.0f}s, 调用预算 {max_calls})",
                        tier=tier, soft_budget=round(ctx.soft_budget))

            # 3) 求解（候选数/温度分层按档位，solver 内部读取 ctx.tier）
            self.solver.run(ctx)
            if not ctx.candidates:
                self.record(ctx, "control", "Solver 未产出候选，触发兜底直接求解")
                self.pacer.end(tier=tier)
                return self._fallback_direct(ctx)

            # 3.2) 截断候选续写：每档 max_completions 个（fast=0 跳过），应急模式跳过
            if (getattr(ctx, 'candidates', None)
                    and not getattr(self.config, '_emergency', False)):
                max_comp = self.config.tier_max_completions.get(tier, 1)
                if max_comp > 0:
                    n_completed = self.solver.complete_truncated_candidates(
                        ctx, max_count=max_comp)
                    if n_completed > 0:
                        self.record(ctx, "control",
                                    f"截断续写完成 {n_completed} 个候选")

            # 3.5) 子目标分解补充候选：deep 档强制；其他档候选不足或证明题时触发
            is_proof = getattr(ctx, 'domain', '') in ('证明', '证明题')
            use_sub = (getattr(self.config, 'deep_use_sub_goal', True)
                       if tier == 'deep' else getattr(self.config, 'use_sub_goal', False))
            if (use_sub
                    and ctx.budget.can_spend(3)
                    and (len(ctx.candidates) < 2 or is_proof or tier == 'deep')):
                self.record(ctx, "control",
                            "触发子目标分解补充候选",
                            sub_goal_trigger=f"tier={tier}, candidates={len(ctx.candidates)}, is_proof={is_proof}")
                self.sub_goal_solver.run(ctx)

            # 4) 验证（投票数按档位：fast=1/standard=1/deep=3）
            # P0-4 修复：playoff 复算按时间宽裕度开关，deep 档且时间宽裕时启用
            tier_votes = self.config.tier_voting_times.get(tier, 1)
            ver_result = self.verifier.run(
                ctx, problem=ctx.problem, candidates=ctx.candidates,
                use_clustering=True,
                use_scoring=self.config.use_scoring,
                is_proof=is_proof,
                use_playoff=(getattr(self.config, '_playoff_enabled', False)
                             and (tier != 'deep' or self.config.deep_use_playoff)),
                voting_times=tier_votes,
            )
            ctx.verdicts = self._verdicts_from_ver_result(ver_result, ctx.candidates)
            ctx._best_cluster = ver_result.get("best_cluster")
            ctx._cluster_data = ver_result.get("cluster_data", [])

            # 5) 全部 0 正确票：
            #    - deep 档：先 revise 自纠错回环（最多 deep_revise_rounds 轮）
            #    - 其他档：直接兜底直接求解
            if (ctx.verdicts
                    and all(v.total_votes > 0 for v in ctx.verdicts)
                    and all(v.correct_votes == 0 for v in ctx.verdicts)):
                revised_ok = False
                if tier == 'deep' and not getattr(self.config, '_emergency', False):
                    revised_ok = self._deep_revise_loop(ctx, ver_result, tier_votes)
                if not revised_ok:
                    self.record(ctx, "control", "全部 0 正确票，触发兜底直接求解")
                    direct_answer = self.solver.direct_solve(ctx)
                    if direct_answer:
                        ctx.final_response = direct_answer
                        self.pacer.end(tier=tier)
                        return safe_json_serialize({
                            "final_response": direct_answer, "trace": ctx.trace,
                        })
                    best = self._pick_best_from_candidates(ctx)
                    if best:
                        ctx.final_response = best
                        self.pacer.end(tier=tier)
                        return safe_json_serialize({
                            "final_response": best, "trace": ctx.trace,
                        })

            # 6) 格式化输出
            self.formatter.run(ctx)
            self.pacer.end(tier=tier)

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
            try:
                self.pacer.end()
            except Exception:
                pass
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
            # v2.4.1：prefill「表达式：」抑制 CoT——快车道只需表达式，秒级返回
            from utils.prefill import prefill_messages, stitch
            raw_expr = _normalize_chat_response(self.client.chat(
                messages=prefill_messages(
                    [
                        {"role": "system", "content": "你只输出数学表达式，不要任何解释。"},
                        {"role": "user", "content": extract_prompt},
                    ],
                    "表达式：",
                ),
                temperature=0.0,
                max_tokens=256,
            ))
            if raw_expr:
                raw_expr = stitch("表达式：", raw_expr)
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

    def _deep_revise_loop(self, ctx: TaskContext, ver_result: dict,
                          tier_votes: int) -> bool:
        """deep 档 0 正确票时的 revise 自纠错回环。

        用验证器反馈驱动定向修正：最多 deep_revise_rounds 轮，
        每轮 solver 走 _generate_revise 重解 + verifier 重新验证。
        返回是否在回环中获得至少 1 个候选获得正确票。
        """
        max_rounds = getattr(self.config, 'deep_revise_rounds', 1)
        if max_rounds <= 0 or getattr(self.config, '_emergency', False):
            return False
        feedback = ver_result.get("feedback", "")
        if not feedback:
            feedback = "所有候选均未获验证通过，请重新审题并纠正推理错误。"
        for r in range(max_rounds):
            if not ctx.budget.can_spend(3):
                self.record(ctx, "revise", "revise 回环预算不足，提前终止")
                break
            ctx.revise_round += 1
            ctx.revise_feedback = [feedback]
            self.record(ctx, "revise",
                        f"deep 档 revise 自纠错 第{ctx.revise_round}轮",
                        round=ctx.revise_round)
            self.solver.run(ctx)  # 走 _generate_revise 路径
            ver2 = self.verifier.run(
                ctx, problem=ctx.problem, candidates=ctx.candidates,
                use_clustering=True,
                use_scoring=self.config.use_scoring,
                is_proof=getattr(ctx, 'domain', '') in ('证明', '证明题'),
                use_playoff=getattr(self.config, '_playoff_enabled', False),
                voting_times=tier_votes,
            )
            ctx.verdicts = self._verdicts_from_ver_result(ver2, ctx.candidates)
            ctx._best_cluster = ver2.get("best_cluster")
            ctx._cluster_data = ver2.get("cluster_data", [])
            if any(v.correct_votes > 0 for v in ctx.verdicts):
                self.record(ctx, "revise", f"revise 第{ctx.revise_round}轮获得正确票")
                return True
            feedback = ver2.get("feedback") or feedback
        self.record(ctx, "revise", f"revise 回环 {max_rounds} 轮仍未获得正确票")
        return False

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

    _DIRECT_SYS = (
        "你是数学解题专家。请解答下面这道题。"
        "最后一行必须以【最终答案】: <答案> 的格式给出最终答案，"
        "答案只写数值、表达式或选项字母，不要写任何解释或推理。"
    )

    def _emergency_direct_solve(self, problem: str) -> str:
        """紧急直答：用最精简 prompt 逼模型输出答案，绝不返回原题。

        P0-4 修复：集成 prefill 答案前置——时间最紧时优先保答案，
        抑制 CoT 开启，即使截断也只损失思考、不损失答案（ICMA 验证 58-140× 加速）。
        """
        try:
            from utils.prefill import prefill_messages, stitch
            resp = self.client.chat(
                messages=prefill_messages(
                    [
                        {"role": "system", "content": self._DIRECT_SYS},
                        {"role": "user", "content": problem},
                    ],
                    "【最终答案】: ",
                ),
                temperature=0.0,
                max_tokens=self.config.max_answer_tokens,
            )
            text = _normalize_chat_response(resp)
            if text:
                text = stitch("【最终答案】: ", text)
            if not text or not text.strip():
                return ""
            # 优先提取【最终答案】行
            m = _re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
            if m:
                ans = m.group(1).strip().split("\n")[0].strip()
                if ans:
                    return ans
            # 兜底：最后一个非空行
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if lines:
                return lines[-1][:500]
            return text.strip()[:500]
        except Exception:
            return ""

    def _fallback_direct(self, ctx: TaskContext) -> dict:
        """Solver 无候选 → 直接 LLM 求解（紧急直答，绝不返回原题）"""
        answer = self._emergency_direct_solve(ctx.problem)
        if not answer:
            answer = "未给出有效解答。"
            ctx.trace.append({"agent": self.name, "step": "fallback",
                              "content": "紧急直答失败，返回占位答案"})
        return safe_json_serialize({
            "final_response": answer, "trace": ctx.trace,
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
        # 紧急直答
        answer = self._emergency_direct_solve(problem)
        if not answer:
            answer = "未给出有效解答。"
            trace.append({"agent": self.name, "step": "fallback",
                          "content": "紧急直答失败，返回占位答案"})
        return {"final_response": answer, "trace": trace}
