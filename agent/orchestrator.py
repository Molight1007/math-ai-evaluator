from __future__ import annotations
"""
编排器（Orchestrator）—— 简化版 v2.2
====================================

借鉴 ss-main 的简洁流水线，不做复杂回环，每道题 LLM 调用控制在 7 次以内：

    Classifier → Solver → Verifier → Formatter
    (0~1次LLM) (3次并行)  (3次投票)  (无LLM)

弱化改动：
- 不设蓝图分解（use_blueprint=False，对 Intern-S 思维流友好）
- 不设自纠错回环（直接用聚类选最优候选）
- 不设完整性审核链（省去 3+ 次 LLM 确认与续写）
- SymPy 快车道仍在（可确定性求解时短路）
"""

import logging
import time
import re as _re

from .base import BaseAgent, TaskContext, Budget, detect_truncated
from .classifier import ClassifierAgent, _KNOWN_DOMAINS
from .solver import SolverAgent
from .verifier import VerifierAgent, AnswerCluster
from .formatter import FormatterAgent
from utils.extract import (
    safe_json_serialize,
    is_acceptable_final_answer,
    smart_fallback_answer,
    extract_final_answer,
)

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
                return self._finalize(ctx)

            # 3) 求解（3 候选并行）
            self.solver.run(ctx)
            if not ctx.candidates:
                self.record(ctx, "control", "Solver 未产出候选，触发兜底直接求解")
                return self._fallback_direct(ctx)

            # 4) 验证（每候选 1 票 + 聚类选最优）
            is_proof = getattr(ctx, 'domain', '') in ('证明', '证明题')
            ver_result = self.verifier.run(
                ctx, problem=ctx.problem, candidates=ctx.candidates,
                use_clustering=True,
                use_scoring=self.config.use_scoring,
                is_proof=is_proof,
            )
            ctx.verdicts = self._verdicts_from_ver_result(ver_result)
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
                    return self._finalize(ctx)
                best = self._pick_best_from_candidates(ctx)
                if best:
                    ctx.final_response = best
                    return self._finalize(ctx)

            # 6) 格式化输出
            self.formatter.run(ctx)

            return self._finalize(ctx)
        except Exception as e:  # noqa: BLE001
            logger.error("Orchestrator run failed: %s", e)
            return self._fallback(ctx, problem, e)

    # ----------------------------------------------------------
    # 最终出口闸门：保证 final_response 非空、非拒绝、非截断、可解析
    # ----------------------------------------------------------
    _ANSWER_ONLY_SYSTEM = (
        "你是数学解题智能体。只输出最终答案本身，不要推理过程、不要解释、"
        "不要任何多余文字。选择题只输出选项字母（如 A）；"
        "填空/计算题输出数值或数学表达式（可用 LaTeX）。"
    )
    _MAX_FINAL_ANSWER_CHARS = 1500

    def _finalize(self, ctx: TaskContext) -> dict:
        """统一出口：对 final_response 做最终质量闸门后封装返回。"""
        answer = (ctx.final_response or "").strip()
        if not self._is_acceptable_final(answer):
            repaired = self._repair_final_answer(ctx, answer)
            if repaired is not None:
                answer = repaired
                self.record(ctx, "finalize",
                            f"最终答案经闸门修复: {answer[:200]}")
            else:
                self.record(ctx, "finalize",
                            f"闸门未能修复，保留原答案: {answer[:100] or '(空)'}")
        ctx.final_response = answer

        candidates_out = [
            {"id": c.id, "answer": c.answer,
             "reasoning": c.reasoning, "revised": c.revised}
            for c in (ctx.candidates or [])
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
            "final_response": ctx.final_response,
            "trace": ctx.trace,
            "candidates": candidates_out,
            "verdicts": verdicts_out,
            "cluster": cluster_out,
        })

    def _is_acceptable_final(self, answer: str) -> bool:
        """终检：非空、长度合理、非拒绝语、非截断。"""
        if not answer or not answer.strip():
            return False
        if len(answer) > self._MAX_FINAL_ANSWER_CHARS:
            return False
        if detect_truncated(answer):
            return False
        return is_acceptable_final_answer(answer)

    def _repair_final_answer(self, ctx: TaskContext, current: str):
        """
        逐级修复最终答案：
        1. 从候选答案/推理中提取（smart_fallback）
        2. 对截断的当前答案做轻量补全
        3. 仅答案直答（最后一次低温度 LLM 调用）
        4. 绝对兜底：最详细候选的答案/推理尾部
        """
        # 1) 候选提取
        for c in sorted(ctx.candidates or [],
                        key=lambda c: len(c.reasoning or ""), reverse=True):
            for raw in (c.answer, c.reasoning):
                if not raw:
                    continue
                cand = smart_fallback_answer(raw)
                if (cand and cand != current
                        and self._is_acceptable_final(cand)):
                    return cand
            cand2 = extract_final_answer(c.reasoning or c.answer or "")
            if (cand2 and cand2 != current
                    and self._is_acceptable_final(cand2)):
                return cand2

        # 2) 截断补全
        fixed = self._fix_truncated_tail(current)
        if fixed and self._is_acceptable_final(fixed):
            return fixed

        # 3) 仅答案直答（普通 → 严格，最多 2 次）
        last_direct = ""
        for strict in (False, True):
            direct = self._answer_only_call(ctx.problem or "", strict=strict)
            last_direct = direct or last_direct
            if direct and self._is_acceptable_final(direct):
                return direct

        # 4) 绝对兜底
        if ctx.candidates:
            best = max(ctx.candidates,
                       key=lambda c: len(c.reasoning or ""))
            tail = smart_fallback_answer(best.reasoning or best.answer or "")
            if tail:
                return tail[:self._MAX_FINAL_ANSWER_CHARS]
            if best.answer:
                return best.answer[:self._MAX_FINAL_ANSWER_CHARS]

        # 5) 最终保证：final_response 绝不返回空串
        if current:
            return current
        if last_direct:
            return last_direct
        return None

    @staticmethod
    def _fix_truncated_tail(answer: str) -> str:
        """轻量补全截断的答案尾部（\boxed、$、\begin、答案前缀）。"""
        if not answer:
            return answer
        fixed = answer.rstrip()
        if fixed.count("\\boxed{") > fixed.count("}"):
            fixed += "}"
        if fixed.count("$") % 2 == 1:
            fixed = fixed.rstrip("$")
        fixed = _re.sub(r"\\begin\{[^}]*\}\s*$", "", fixed).strip()
        fixed = _re.sub(
            r"(?:答案|最终答案|结果为?|解得?|等于|选)[:：=]?\s*$",
            "", fixed,
        ).strip()
        return fixed or answer

    def _answer_only_call(self, problem: str, strict: bool = False) -> str:
        """最后一道保险：让模型只输出答案本身（温度 0，限制 token）。"""
        try:
            system = self._ANSWER_ONLY_SYSTEM
            if strict:
                system += (
                    " 必须直接输出最终答案（数值/选项字母/表达式），"
                    "禁止任何解释、分析、拒绝或道歉。"
                )
            resp = self.client.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": problem},
                ],
                temperature=0.0,
                max_tokens=512,
            )
            return (resp or "").strip()
        except Exception:
            return ""

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

    def _verdicts_from_ver_result(self, ver_result: dict) -> list:
        all_verdicts = ver_result.get("verdicts", [])
        result = []
        for idx, vds in enumerate(all_verdicts):
            correct_votes = sum(1 for v in vds if v.correct)
            total_votes = len(vds)
            result.append(type('_VSummary', (), {
                "id": idx,
                "answer": "",
                "correct_votes": correct_votes,
                "total_votes": total_votes,
                "confidence": correct_votes / total_votes if total_votes else 0.0,
                "feedback": "",
            }))
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
        """Solver 无候选 → 直接 LLM 求解（仍走最终闸门）"""
        try:
            resp = self.client.chat(
                messages=[
                    {"role": "system", "content": "你是数学解题专家，请仔细分析并给出最终答案。确保输出完整。"},
                    {"role": "user", "content": ctx.problem},
                ],
                temperature=0.3,
                max_tokens=self.config.policy_max_tokens,
            )
            ctx.final_response = (resp or "").strip()
        except Exception:
            ctx.final_response = ""
        return self._finalize(ctx)

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
            ctx.final_response = answer
            ctx.trace = trace
            return self._finalize(ctx)
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
            ctx.final_response = (resp or "").strip()
        except Exception:
            ctx.final_response = ""
        ctx.trace = trace
        return self._finalize(ctx)
