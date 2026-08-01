from __future__ import annotations
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
import time
import re as _re

from .base import BaseAgent, TaskContext, Budget
from .classifier import ClassifierAgent, _KNOWN_DOMAINS
from .solver import SolverAgent
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
        self.verifier = VerifierAgent(client, config)
        self.formatter = FormatterAgent(client, config)

    # ----------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------
    def run(self, problem: str, metadata: dict) -> dict:
        now = time.time()
        ctx = TaskContext(
            problem=problem,
            metadata=metadata or {},
            budget=Budget(max_calls=self.config.max_total_calls),
            start_time=now,
            deadline=now + getattr(self.config, 'max_time_per_question', 1100),
            total_start_time=now,
            total_deadline=now + getattr(self.config, 'max_total_time_seconds', 21000),
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

            # 验证器返回聚类数据（含簇级置信度）
            ver_result = self.verifier.run(
                ctx, problem=ctx.problem, candidates=ctx.candidates,
                use_clustering=True,
                use_scoring=self.config.use_scoring,
                is_proof=(getattr(ctx, 'domain', '') in ('证明', '证明题')),
            )
            ctx.verdicts = self._verdicts_from_ver_result(ver_result)
            ctx._cluster_data = ver_result.get("cluster_data", [])
            ctx._best_cluster = ver_result.get("best_cluster")

            self._regulate(ctx)            # 自主调控（回环 / 增强 / 提前退出）

            # 答案完整性审核：检查最佳答案是否截断，不完整则续写
            self._ensure_completeness(ctx)

            # 兜底：所有候选验证均 0 正确票（模型全拒绝 / 空响应）
            # → 跳过复杂流水线，直接用最简提示词让模型单次求解
            if (ctx.verdicts and all(v.total_votes > 0 for v in ctx.verdicts)
                    and all(v.correct_votes == 0 for v in ctx.verdicts)):
                self.record(ctx, "control", "所有候选验证 0 正确票，触发兜底直接求解")
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
            # 候选与验证结果
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
            # 附带聚类信息
            cluster_out = None
            if getattr(ctx, '_best_cluster', None):
                bc = ctx._best_cluster
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
        快车道：对可确定性求解的题目直接用 SymPy 计算（若可用）。
        成功返回答案字符串，失败返回 None 回退正常工作流。
        （原为仅检测不求解的死代码，现已激活）
        """
        problem = ctx.problem or ""
        # 先用快速提示词提取核心表达式
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

            self.record(ctx, "fast_path", f"快车道题型 {tag}: SymPy 求解失败，回退正常流程")

        return None

    def _try_sympy_solve(self, problem: str, tag: str) -> str | None:
        """使用 LLM 提取核心表达式后调用 SymPy 求解。"""
        extract_prompt = (
            "请从以下题目中提取**核心数学表达式**（只输出表达式，不要额外文字）。"
            "对于方程，输出到等号左边（剩余项移到左边=0的意思，输出f(x)即可）；"
            "对于求导，输出被求导的函数；对于积分，输出被积函数。"
            f"\n\n题目类型: {tag}\n题目: {problem}\n\n表达式:"
        )
        try:
            raw_expr = self.client.chat(
                messages=[
                    {"role": "system", "content": "你只输出数学表达式，不要任何解释。"},
                    {"role": "user", "content": extract_prompt},
                ],
                temperature=0.0,
                max_tokens=self.config.policy_max_tokens,
            )
            raw_expr = (raw_expr or "").strip()
            self.record(None, "fast_path", f"提取的表达式: {raw_expr}")
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

    # ----------------------------------------------------------
    # 自主调控核心
    # ----------------------------------------------------------
    def _regulate(self, ctx: TaskContext) -> None:
        """自主调控：基于簇级置信度（跨候选多数投票）做三档决策。
        
        新增时间驱动退出（适配竞赛新规则：单题≤20分钟）：
        - 时间紧迫（<2分钟）时跳过所有可选步骤，直接选最优候选
        - 时间不足做完整revise时降级为追加候选
        """
        max_iter = self.config.max_revise_rounds + 2
        min_votes_for_high_conf = 2

        for _ in range(max_iter):
            # ── 时间检查：紧迫时直接退出 ──
            if ctx.is_time_critical():
                self.record(ctx, "control",
                            f"时间紧迫（剩余 {ctx.time_remaining():.0f}s < 120s），跳过调控直接出结果")
                break
            if ctx.is_timed_out():
                self.record(ctx, "control", "已超时，强制退出调控")
                break

            best_cluster = getattr(ctx, '_best_cluster', None)
            cluster_data = getattr(ctx, '_cluster_data', [])

            # 聚合簇置信度
            if best_cluster:
                cluster_conf = best_cluster.confidence
                cluster_votes = best_cluster.vote_total
            else:
                # 降级：传统单候选置信度
                valid_verdicts = [v for v in (ctx.verdicts or []) if v.total_votes > 0]
                if not valid_verdicts:
                    self.record(ctx, "control", "所有候选验证均失败，停止调控")
                    break
                best = max(valid_verdicts, key=lambda v: v.confidence)
                cluster_conf = best.confidence
                cluster_votes = best.total_votes

            # 1) 高置信度 + 足够规模 → 提前退出
            if (cluster_conf >= self.config.conf_high
                    and cluster_votes >= min_votes_for_high_conf):
                best = getattr(best_cluster, 'answer_norm', '') if best_cluster else ''
                self.record(ctx, "control",
                            f"高置信度 {cluster_conf:.2f} ≥ {self.config.conf_high} "
                            f"(簇规模={getattr(best_cluster, 'size', 0) if best_cluster else 0}, "
                            f"{getattr(best_cluster, 'vote_correct', 0)}/{cluster_votes} 票, "
                            f"答案≈{best[:20]})，提前退出")
                break

            # 2) 预算不足 → 直接出结果
            if not ctx.budget.can_spend(2):
                self.record(ctx, "control", "预算不足，停止增强并出结果")
                break

            # 3) 低置信度 → 自纠错回环（检查时间是否够用再做）
            if (cluster_conf < self.config.conf_low
                    and ctx.revise_round < self.config.max_revise_rounds):
                # 时间检查：做revise需要~30s额外时间，不足则跳过
                if ctx.time_remaining() < 30.0:
                    self.record(ctx, "control",
                                f"时间不足做revise（剩余 {ctx.time_remaining():.0f}s），跳过自纠错")
                    break
                ver_result = getattr(ctx, '_last_ver_result', None)
                feedback = ver_result.get("feedback", "") if ver_result else ""
                if not feedback:
                    # 降级：从最差候选提取
                    valid_vs = [v for v in (ctx.verdicts or []) if v.total_votes > 0]
                    if valid_vs:
                        best_v = max(valid_vs, key=lambda v: v.confidence)
                        feedback = self._collect_feedback(ctx, best_v)
                if feedback and len(feedback) > 5:
                    ctx.revise_feedback.append(feedback)
                    ctx.revise_round += 1
                    self.record(ctx, "control",
                                f"低置信度 {cluster_conf:.2f} < {self.config.conf_low}，"
                                f"触发自纠错回环 R{ctx.revise_round}: {feedback[:120]}")
                    self.solver.run(ctx)
                    # 时间再检查
                    if ctx.is_time_critical():
                        self.record(ctx, "control", "revise后时间不足，跳过重验证直接出结果")
                        break
                    ver_result = self.verifier.run(
                        ctx, problem=ctx.problem, candidates=ctx.candidates,
                        use_clustering=True,
                        use_scoring=self.config.use_scoring,
                    )
                    ctx.verdicts = self._verdicts_from_ver_result(ver_result)
                    ctx._cluster_data = ver_result.get("cluster_data", [])
                    ctx._best_cluster = ver_result.get("best_cluster")
                    continue

            # 4) 中置信度 → 追加候选并重验（一次性，检查时间）
            if ctx.time_remaining() < 60.0:
                self.record(ctx, "control",
                            f"时间不足以追加候选（剩余 {ctx.time_remaining():.0f}s），跳过增强")
                break
            if ctx.budget.can_spend(self.config.policy_sample_times + 1):
                self.record(ctx, "control",
                            f"中置信度 {cluster_conf:.2f}，追加候选并重验")
                self.solver.add_candidates(ctx, count=2)
                ver_result = self.verifier.run(
                    ctx, problem=ctx.problem, candidates=ctx.candidates,
                    use_clustering=True,
                    use_scoring=self.config.use_scoring,
                )
                ctx.verdicts = self._verdicts_from_ver_result(ver_result)
                ctx._cluster_data = ver_result.get("cluster_data", [])
                ctx._best_cluster = ver_result.get("best_cluster")
            break

    def _verdicts_from_ver_result(self, ver_result: dict) -> list:
        """从 verifier 返回的 dict 提取传统的 verdicts 列表（向后兼容）。"""
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

    def _collect_feedback(self, ctx: TaskContext, verdict) -> str:
        """针对当前最差候选，让验证器提取失败原因"""
        # 遍历候选找匹配的（BUG-14 修复：不再依赖 ctx.candidates[cid] 索引）
        cand = None
        for c in ctx.candidates:
            if c.id == getattr(verdict, 'id', None):
                cand = c
                break
        if cand is None or not cand.reasoning:
            return ""
        return self.verifier._extract_feedback(ctx.problem, cand)

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
        - 时间紧迫时跳过（适配竞赛 20 分钟限制）
        """
        if not ctx.candidates:
            return

        # 时间紧迫：跳过完整性检查，节省 LLM 调用
        if ctx.is_time_critical():
            self.record(ctx, "complete", "时间紧迫，跳过完整性检查")
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

        # 双重检查完整性
        heuristic_ok = self.solver.is_answer_complete(best_cand.reasoning, best_cand.answer)
        if heuristic_ok:
            self.record(ctx, "complete", "答案完整性检查通过（启发式）")
            return

        # 时间再检查：LLM 完整性确认也耗时间
        if ctx.is_time_critical():
            self.record(ctx, "complete", "时间紧迫，跳过 LLM 完整性确认")
            return

        # 启发式判断不完整 → 用 LLM 二次确认
        llm_ok = self.verifier.check_completeness(ctx, best_cand)
        if llm_ok:
            self.record(ctx, "complete", "答案完整性检查通过（LLM确认完整）")
            return

        # LLM 也认为不完整 → 续写（检查时间是否够）
        if ctx.is_time_critical():
            self.record(ctx, "complete", "时间不足，跳过续写")
            return

        self.record(ctx, "complete",
                   f"答案不完整，触发续写 (候选 #{best_cand.id})")
        completed = self.solver.complete_answer(ctx, best_cand)

        if completed and completed.answer != best_cand.answer:
            for i, cand in enumerate(ctx.candidates):
                if cand.id == best_cand.id:
                    ctx.candidates[i] = completed
                    break
            # BUG-5 修复：续写后清除旧 verdict
            ctx.verdicts = [v for v in (ctx.verdicts or []) if v.id != best_cand.id]
            self.record(ctx, "complete", f"续写完成，已清除候选 #{best_cand.id} 旧验证")
            # 时间检查：续写后重验证需要额外时间
            if ctx.is_time_critical():
                self.record(ctx, "complete", "续写后时间不足，跳过重验证")
                return
            # 重新验证
            ver_result = self.verifier.run(
                ctx, problem=ctx.problem, candidates=ctx.candidates,
                use_clustering=True,
                use_scoring=self.config.use_scoring,
            )
            ctx.verdicts = self._verdicts_from_ver_result(ver_result)
            ctx._cluster_data = ver_result.get("cluster_data", [])
            ctx._best_cluster = ver_result.get("best_cluster")
            self.record(ctx, "complete", "续写后重新验证完成")

    # ----------------------------------------------------------
    # 兜底：单次直接求解，保证 final_response 非空
    # ----------------------------------------------------------
    def _fallback(self, ctx: TaskContext, problem: str, exc: Exception) -> dict:
        """兜底求解：绝不返回拒绝语。优先使用已有候选/推理，再尝试单次 LLM，最后输出尽力答案。"""
        trace = list(ctx.trace) if ctx.trace else []
        trace.append({
            "agent": self.name,
            "step": "error",
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
                    {"role": "system",
                     "content": "你是数学解题专家，请仔细分析并给出最终答案。确保输出完整。"},
                    {"role": "user", "content": problem},
                ],
                temperature=0.3,
                max_tokens=self.config.policy_max_tokens,
            )
            answer = (resp or "").strip()
            from .base import detect_hallucination, detect_truncated
            if detect_truncated(answer):
                trace.append({"agent": self.name, "step": "fallback",
                              "content": "WARNING: 兜底答案可能被截断"})
            hallu = detect_hallucination(answer)
            if hallu:
                trace.append({"agent": self.name, "step": "fallback",
                              "content": f"WARNING: 兜底答案包含幻觉模式 {hallu}"})
                answer = answer[:200] if len(answer) > 200 else answer
        except Exception:
            answer = ""
        # 最终防线：退到原始问题文本
        if not answer or len(answer) < 5:
            answer = problem[:500] if problem else "请重新提问"
            trace.append({"agent": self.name, "step": "fallback",
                          "content": "所有求解尝试均失败，返回原始问题文本"})
        return {"final_response": answer, "trace": trace}
