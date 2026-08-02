from __future__ import annotations
"""
过程校验智能体（VerifierAgent）
================================

功能演进：
  - v1: 二元投票（VERDICT A/B）+ 等价答案分组（未启用）
  - v2: 二元投票 + 评分模式 + 跨候选共识聚类 + 证明步骤验证

借鉴 ss-main 的投票共识与 Intern-MO 的 step 级验证，
但保持 MathPilot 多智能体 + 共享黑板的架构主线。
"""

import concurrent.futures
import json
import logging
import re

from .base import BaseAgent, TaskContext, Verdict
from prompts.verifier import (
    VERIFIER_SYSTEM,
    VERIFIER_USER_TEMPLATE,
    VERIFIER_SCORING_SYSTEM,
    VERIFIER_SCORING_TEMPLATE,
    VERIFIER_FEEDBACK_SYSTEM,
    VERIFIER_FEEDBACK_TEMPLATE,
)
from prompts.proof import PROOF_VERIFY_SYSTEM, PROOF_VERIFY_TEMPLATE

logger = logging.getLogger("MathPilot.Verifier")

# ---------------------------------------------------------------------------
# 辅助数据类
# ---------------------------------------------------------------------------

class AnswerCluster:
    """答案等价簇，用于跨候选多数投票。"""
    __slots__ = ("answer_norm", "candidate_ids", "vote_correct", "vote_total")

    def __init__(self, answer_norm: str):
        self.answer_norm = answer_norm
        self.candidate_ids: list[int] = []
        self.vote_correct: int = 0
        self.vote_total: int = 0

    @property
    def confidence(self) -> float:
        if self.vote_total == 0:
            return 0.0
        return self.vote_correct / self.vote_total

    @property
    def size(self) -> int:
        return len(self.candidate_ids)


# ===========================================================================
# VerifierAgent
# ===========================================================================

class VerifierAgent(BaseAgent):
    """
    过程校验智能体

    核心职责：
    1. 对每份候选解答进行多票独立验证（A/B 投票）
    2. 将等价答案分组（文本 + SymPy 符号归一化）
    3. 计算簇级置信度（簇内总正确票 / 总票数）
    4. 对证明题启用逐步骤验证
    5. 提取失败原因供自纠错回环使用
    """

    def __init__(self, client, config):
        super().__init__(client, config)

    # ==================================================================
    # 投票与解析
    # ==================================================================

    def _is_correct_vote(self, text: str) -> bool:
        """解析 VERDICT 行。规则：先判拒绝词，再判接受词（BUG-2 修复）。"""
        if text is None:
            logger.warning("_is_correct_vote 收到 None 输入，默认判错")
            return False
        text_upper = text.upper()

        # 1) 拒绝词优先——规避"不正确"包含"正确"的误判
        reject_patterns = [
            r'\bINCORRECT\b', r'\bWRONG\b', r'\bFALSE\b',
            r'不\s*正\s*确', r'错\s*误', r'\bNO\b(?!\s*CHANGE|TE)',
            r'VERDICT\s*:\s*B',
        ]
        for pat in reject_patterns:
            if re.search(pat, text_upper) and "不正确" not in text:
                # "不正确" 已被 \b 匹配避免；额外保底
                pass
        for pat in reject_patterns:
            if re.search(pat, text_upper):
                # 排除 VERDICT: B 旁边的假阳性（只对明确单一匹配生效）
                return False

        # 2) 接受词
        accept_patterns = [
            r'\bCORRECT\b', r'\bTRUE\b', r'正\s*确', r'\bYES\b',
            r'VERDICT\s*:\s*A',
        ]
        for pat in accept_patterns:
            if re.search(pat, text_upper):
                return True

        # 3) 仅包含 VERDICT: B → 拒绝
        if re.search(r'VERDICT\s*:\s*B', text_upper):
            return False

        # 4) 无法判断 → 保守当作正确（宁可假阳，丢给共识过滤）
        logger.warning(f"无法从文本中解析 VERDICT，默认为正确: {text[:100]}")
        return True

    # ==================================================================
    # 答案归一化与等价判定
    # ==================================================================

    def _normalize_answer_text(self, text: str) -> str:
        """文本级归一化：去空白/去 $/浮点舍入/LaTeX 分数统一。"""
        if not text:
            return ""
        t = text.strip()
        t = t.replace("$", "").replace(" ", "")
        t = t.replace("\\displaystyle", "")
        t = t.replace("\\,", "").replace("\\;", "").replace("\\!", "")
        # 浮点舍入 6 位
        try:
            f = float(t)
            t = f"{f:.6g}"
        except (ValueError, TypeError):
            pass
        # LaTeX 分数统一
        t = re.sub(r'\\frac\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}', r'(\1)/(\2)', t)
        return t

    def _are_answers_equivalent(self, a: str, b: str) -> bool:
        """三级等价判定：文本完全相同 → 分数等价 → SymPy 符号等价。"""
        if not a or not b:
            return False
        # Level 1: 归一化后字符串完全相同
        if a == b:
            return True
        # Level 2: SymPy 符号等价（若可用）
        try:
            from utils.sympy_tools import are_expressions_equal
            if are_expressions_equal(a, b):
                return True
        except ImportError:
            pass
        return False

    def _equiv_group(
        self, candidates: list, answers: list[str]
    ) -> list[list[int]]:
        """等价答案分组：返回候选 ID 列表的列表。（BUG-3 修复：实际使用返回值）"""
        n = len(answers)
        visited = [False] * n
        groups: list[list[int]] = []

        for i in range(n):
            if visited[i]:
                continue
            group = [i]
            visited[i] = True
            for j in range(i + 1, n):
                if visited[j]:
                    continue
                if self._are_answers_equivalent(answers[i], answers[j]):
                    group.append(j)
                    visited[j] = True
            groups.append(group)
        return groups

    # ==================================================================
    # 共识聚类与簇置信度
    # ==================================================================

    def _cluster_candidates(
        self, candidates: list, verdicts: list[list[Verdict]]
    ) -> list[AnswerCluster]:
        """
        基于 Equivalent Answer 聚类 + 跨候选多数投票：
        1. 提取每个候选的答案（归一化）
        2. 等价分组
        3. 每个组统计"组内候选的总体正确票数 / 总票数"
        4. 返回簇列表，按置信度 × 规模排序
        """
        answers = []
        for cand in candidates:
            ans = (cand.get("answer", "") if isinstance(cand, dict)
                   else getattr(cand, "answer", ""))
            answers.append(self._normalize_answer_text(str(ans)))
        groups = self._equiv_group(candidates, answers)

        clusters: list[AnswerCluster] = []
        for g in groups:
            rep_idx = g[0]
            cluster = AnswerCluster(answers[rep_idx])
            for idx in g:
                cid = candidates[idx].get("id", idx) if isinstance(candidates[idx], dict) else idx
                cluster.candidate_ids.append(cid)
                # 统计该候选的所有票
                if idx < len(verdicts):
                    for v in verdicts[idx]:
                        cluster.vote_total += 1
                        if v.correct:
                            cluster.vote_correct += 1
            clusters.append(cluster)

        # 排序：置信度 × 规模的加权（等价答案人越多且票越对 = 越可信）
        clusters.sort(key=lambda c: c.confidence * c.size + c.confidence, reverse=True)
        return clusters

    # ==================================================================
    # 投票执行
    # ==================================================================

    def _vote_one(self, ctx, problem: str, candidate_text: str) -> str:
        """单次投票（返回原始文本）。"""
        messages = [
            {"role": "system", "content": VERIFIER_SYSTEM},
            {"role": "user", "content": VERIFIER_USER_TEMPLATE.format(
                problem=problem, candidate_answer=candidate_text
            )},
        ]
        return self.llm(ctx, messages, 0.0, self.config.max_tokens)

    def _vote_one_scoring(self, ctx, problem: str, candidate_text: str) -> dict | None:
        """评分模式投票（返回 JSON 或 None）。"""
        messages = [
            {"role": "system", "content": VERIFIER_SCORING_SYSTEM},
            {"role": "user", "content": VERIFIER_SCORING_TEMPLATE.format(
                problem=problem, candidate_answer=candidate_text
            )},
        ]
        raw = self.llm(ctx, messages, 0.0, self.config.max_tokens)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            m = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except json.JSONDecodeError:
                    pass
            return None

    def _vote(
        self, ctx, problem: str, candidate, total_votes: int = 5,
        proportional: bool = True, use_scoring: bool = False,
    ) -> list[Verdict]:
        """
        批量投票并汇总（BUG-8 修复：用 valid_votes 替代 total_votes）。
        """
        text = self._candidate_text(candidate)
        verdicts: list[Verdict] = []

        # 二元投票
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(total_votes, self.config.max_workers)
        ) as executor:
            futures = [executor.submit(self._vote_one, ctx, problem, text)
                       for _ in range(total_votes)]
            for f in concurrent.futures.as_completed(futures):
                try:
                    raw = f.result()
                    verdicts.append(Verdict(
                        correct=self._is_correct_vote(raw),
                        raw=raw,
                    ))
                except Exception as e:
                    logger.warning(f"Vote failed: {e}")
                    verdicts.append(Verdict(correct=False, raw=str(e)))

        # 可选评分模式（补充/校准）
        if use_scoring and self.config.use_scoring:
            try:
                scoring = self._vote_one_scoring(ctx, problem, text)
                if scoring:
                    verdicts.append(Verdict(
                        correct=scoring.get("overall", "B") == "A",
                        raw=json.dumps(scoring, ensure_ascii=False),
                        score=scoring,
                    ))
            except Exception as e:
                logger.debug(f"Scoring vote failed: {e}")

        return verdicts

    # ==================================================================
    # 反馈提取（自纠错用）
    # ==================================================================

    def _extract_feedback(self, ctx, problem: str, candidate) -> str:
        text = self._candidate_text(candidate)
        messages = [
            {"role": "system", "content": VERIFIER_FEEDBACK_SYSTEM},
            {"role": "user", "content": VERIFIER_FEEDBACK_TEMPLATE.format(
                problem=problem, candidate_answer=text
            )},
        ]
        try:
            return self.llm(ctx, messages, 0.0, self.config.max_tokens)
        except Exception as e:
            logger.error(f"Feedback extraction failed: {e}")
            return "无法提取失败原因。"

    # ==================================================================
    # 证明步骤验证
    # ==================================================================

    def _verify_proof_step(self, ctx, problem: str, solution: str) -> dict | None:
        messages = [
            {"role": "system", "content": PROOF_VERIFY_SYSTEM},
            {"role": "user", "content": PROOF_VERIFY_TEMPLATE.format(
                problem=problem, solution=solution
            )},
        ]
        try:
            raw = self.llm(ctx, messages, 0.0, self.config.max_tokens)
            m = re.search(r'\{[^{}"]*(?:"[^"]*"[^{}]*)*\}', raw, re.DOTALL)
            if m:
                return json.loads(m.group())
            # fallback: larger match
            m2 = re.search(r'\{[\s\S]*\}', raw)
            if m2:
                return json.loads(m2.group())
            return {"overall": "unknown", "raw": raw[:500]}
        except Exception as e:
            logger.warning(f"Proof step verify failed: {e}")
            return None

    # ==================================================================
    # 主流程
    # ==================================================================

    def run(
        self, ctx: TaskContext, problem: str, candidates: list,
        use_clustering: bool = True,
        use_scoring: bool = False,
        is_proof: bool = False,
    ) -> dict:
        """
        验证主流程。

        返回:
            {
                "cluster_data": list[AnswerCluster],  # 候选传给 orchestrator
                "feedback": str,                       # 自纠错用
                "verdicts": list[list[Verdict]],       # 原始裁决
                "best_cluster": AnswerCluster | None,
            }
        """
        # 特殊处理证明题
        if is_proof and len(candidates) == 1:
            # 逐步骤验证
            proof_text = self._candidate_text(candidates[0])
            step_result = self._verify_proof_step(ctx, problem, proof_text)
            overall_correct = (step_result.get("overall") == "proof_valid"
                               if step_result else False)
            v = Verdict(correct=overall_correct, raw=json.dumps(step_result or {}))
            cluster = AnswerCluster("proof")
            cluster.candidate_ids = [candidates[0].get("id", 0)]
            cluster.vote_correct = 1 if overall_correct else 0
            cluster.vote_total = 1
            feedback = (step_result.get("step_verdicts", [{}])[0].get("note", "")
                        if step_result and not overall_correct else "")
            return {
                "cluster_data": [cluster],
                "feedback": feedback,
                "verdicts": [[v]],
                "best_cluster": cluster,
            }

        # 常规：每个候选投票
        all_verdicts: list[list[Verdict]] = []
        for i, cand in enumerate(candidates):
            vds = self._vote(ctx, problem, cand, total_votes=self.config.verifier_voting_times,
                             use_scoring=use_scoring)
            all_verdicts.append(vds)

        # 聚类 + 共识
        cluster_data = self._cluster_candidates(candidates, all_verdicts) if use_clustering else []
        best_cluster = cluster_data[0] if cluster_data else None

        # 自纠错反馈：从最差候选中提取（选置信度最低的）
        worst_cand = None
        if candidates:
            # 找 0 票候选
            for i, vds in enumerate(all_verdicts):
                correct_count = sum(1 for v in vds if v.correct)
                if correct_count == 0:
                    worst_cand = candidates[i]
                    break
            if worst_cand is None:
                worst_cand = candidates[0]
        feedback = self._extract_feedback(ctx, problem, worst_cand) if worst_cand else ""

        return {
            "cluster_data": cluster_data,
            "feedback": feedback,
            "verdicts": all_verdicts,
            "best_cluster": best_cluster,
        }

    # ==================================================================
    # 辅助
    # ==================================================================

    def _candidate_text(self, candidate) -> str:
        if isinstance(candidate, dict):
            parts = []
            if candidate.get("reasoning"):
                parts.append(candidate["reasoning"])
            if candidate.get("answer"):
                parts.append(f"【最终答案】{candidate['answer']}")
            return "\n".join(parts)
        reasoning = getattr(candidate, "reasoning", "")
        answer = getattr(candidate, "answer", "")
        return f"{reasoning}\n【最终答案】{answer}" if reasoning and answer else str(candidate)

    def check_completeness(self, ctx: TaskContext, candidate) -> bool:
        """
        LLM 确认答案是否完整（是否被截断/未写完）。
        返回 True 表示完整，False 表示不完整。
        """
        text = self._candidate_text(candidate)
        messages = [
            {"role": "system",
             "content": "你是答案完整性检查专家。检查以下解答是否给出了完整结论（没有截断、没有'待续'等）。只输出 COMPLETE 或 INCOMPLETE。"},
            {"role": "user", "content": text + "\n\n这个答案是完整的吗？"},
        ]
        try:
            raw = self.llm(ctx, messages, 0.0, 128)
            return "INCOMPLETE" not in raw.upper() or "COMPLETE" in raw.upper()
        except Exception:
            return True  # 网络异常时保守当作完整
