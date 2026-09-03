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
    VERIFIER_BUGREPORT_SYSTEM,
    VERIFIER_BUGREPORT_TEMPLATE,
)
from prompts.proof import PROOF_VERIFY_SYSTEM, PROOF_VERIFY_TEMPLATE
from utils.extract import smart_fallback_answer
from utils.prefill import prefill_messages, stitch

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

        # 4) 无法判断 → 保守当作错误（宁可假阴，交给共识/revise 兜底）
        #    v2.6 修复"虚高置信度"：此前默认判对会导致未解析的票计入正确票，
        #    使错误答案也拿到高置信度。改为判错后，低共识会触发 revise/协作复核。
        logger.warning(f"无法从文本中解析 VERDICT，默认为错误: {text[:100]}")
        return False

    # ==================================================================
    # 答案归一化与等价判定
    # ==================================================================

    def _normalize_answer_text(self, text: str) -> str:
        """文本级归一化：去空白/去 $/浮点舍入/文本分数→数值/LaTeX 分数统一。"""
        if not text:
            return ""
        t = text.strip()
        t = t.replace("$", "").replace(" ", "")
        t = t.replace("\\displaystyle", "")
        t = t.replace("\\,", "").replace("\\;", "").replace("\\!", "")
        # LaTeX 分数统一（与本地 _normalize_answer 一致，无括号便于数值解析）
        t = re.sub(r'\\frac\s*\{\s*([^}]*)\s*\}\s*\{\s*([^}]*)\s*\}', r'\1/\2', t)
        # 浮点舍入 6 位
        try:
            f = float(t)
            t = f"{f:.6g}"
        except (ValueError, TypeError):
            # 文本分数（如 1/2、(1)/(2)）→ 数值，统一 1/2 与 0.5、3 与 3.0
            stripped = re.sub(r'^\((-?\d+)\)/\((-?\d+)\)$', r'\1/\2', t)
            if re.fullmatch(r'-?\d+/\d+', stripped):
                try:
                    num, den = stripped.split("/")
                    f = int(num) / int(den)
                    t = f"{f:.6g}"
                except (ValueError, ZeroDivisionError):
                    pass
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
        """单次投票（返回原始文本）。

        v2.4.1：prefill「VERDICT: 」抑制 CoT——投票输出只需 A/B，
        实测 prefill 仲裁 0.8s vs 普通 70.2s（140×），杜绝 Intern-S2 推理流占满预算。
        """
        messages = [
            {"role": "system", "content": VERIFIER_SYSTEM},
            {"role": "user", "content": VERIFIER_USER_TEMPLATE.format(
                problem=problem, candidate_answer=candidate_text
            )},
        ]
        raw = self.llm(ctx, prefill_messages(messages, "VERDICT: "), 0.0, 32768)
        return stitch("VERDICT: ", raw) if raw else raw

    def _vote_one_scoring(self, ctx, problem: str, candidate_text: str) -> dict | None:
        """评分模式投票（返回 JSON 或 None）。

        v2.4.1：prefill「{"」引导直接输出 JSON，抑制 CoT 前置长推理。
        """
        messages = [
            {"role": "system", "content": VERIFIER_SCORING_SYSTEM},
            {"role": "user", "content": VERIFIER_SCORING_TEMPLATE.format(
                problem=problem, candidate_answer=candidate_text
            )},
        ]
        raw = self.llm(ctx, prefill_messages(messages, '{"'), 0.0, 32768)
        if raw:
            raw = stitch('{"', raw)
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
        2026-09-02 修复：deadline 已过仍启动投票 → 每票 LLM 全被跳过返回 None，
        _is_correct_vote(None) 全判错 + 疯狂刷日志空转（027 实测超 deadline 137s）。
        """
        # 超时保护：deadline 已过 → 不投票（空 verdicts 由上层走兜底）
        if ctx.is_timed_out():
            logger.warning("Verifier: 单题 deadline 已过，跳过投票（%d 票）",
                           total_votes)
            return []
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
            # v2.4.1：prefill「错因：」抑制 CoT，直接输出错因定位
            raw = self.llm(ctx, prefill_messages(messages, "错因："), 0.0, 32768)
            return stitch("错因：", raw) if raw else "无法提取失败原因。"
        except Exception as e:
            logger.error(f"Feedback extraction failed: {e}")
            return "无法提取失败原因。"

    # ------------------------------------------------------------------
    # 结构化 Bug Report（依据 IMO 2025 验证-精炼流水线论文）
    # ------------------------------------------------------------------
    def _extract_bug_report(self, ctx, problem: str, candidate) -> dict:
        """让验证器产出结构化 bug report（分类 + 精确定位），而非一句话错因。

        论文依据：Huang & Yang (2025) 用「验证 + 精炼」流水线把 IMO 2025
        从 best-of-32 的 21.4%~38.1% 提到 85.7%。关键不在于多采样，而在于
        验证器给出**可执行的错因**（哪一步、什么类型、为什么），
        修正步骤才能有的放矢。

        返回 dict：{verdict, findings:[{location, type, explanation}]}
        解析失败时返回 {"verdict": "unknown", "findings": []}。
        """
        text = self._candidate_text(candidate)
        messages = [
            {"role": "system", "content": VERIFIER_BUGREPORT_SYSTEM},
            {"role": "user", "content": VERIFIER_BUGREPORT_TEMPLATE.format(
                problem=problem, candidate_answer=text
            )},
        ]
        empty = {"verdict": "unknown", "findings": []}
        try:
            # prefill 锚定到 JSON 开头：Intern 无短种子会先吐思维块吃满预算
            raw = self.llm(ctx, prefill_messages(messages, "{"), 0.0, 32768)
            if not raw:
                return empty
            raw = stitch("{", raw)
        except Exception as e:  # noqa: BLE001
            logger.error(f"BugReport extraction failed: {e}")
            return empty

        data = self._parse_json_loose(raw)
        if not isinstance(data, dict):
            return empty
        findings = []
        for f in (data.get("findings") or []):
            if not isinstance(f, dict):
                continue
            loc = str(f.get("location") or "").strip()
            expl = str(f.get("explanation") or "").strip()
            ftype = str(f.get("type") or "").strip().lower()
            if ftype not in ("critical_error", "justification_gap"):
                ftype = "justification_gap"
            if not (loc or expl):
                continue
            findings.append({"location": loc, "type": ftype,
                             "explanation": expl})
        verdict = str(data.get("verdict") or "").strip().lower()
        if verdict not in ("correct", "critical_error", "justification_gap"):
            # 以 findings 反推，比信任模型的自陈更可靠
            verdict = ("critical_error"
                       if any(f["type"] == "critical_error" for f in findings)
                       else "justification_gap" if findings else "unknown")
        return {"verdict": verdict, "findings": findings}

    @staticmethod
    def _parse_json_loose(raw: str):
        """从 LLM 输出里尽力抠出 JSON 对象（去围栏、平衡括号）。"""
        if not raw:
            return None
        import json as _json
        text = raw.strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            text = m.group(1).strip()
        try:
            return _json.loads(text)
        except (_json.JSONDecodeError, ValueError):
            pass
        # 平衡括号：取第一个能完整解析的对象
        depth = 0
        start = -1
        in_str = esc = False
        for i, ch in enumerate(text):
            if esc:
                esc = False
            elif in_str and ch == "\\":
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == "{":
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start >= 0:
                        try:
                            return _json.loads(text[start:i + 1])
                        except (_json.JSONDecodeError, ValueError):
                            start = -1
        return None

    @staticmethod
    def _format_bug_report(report: dict) -> str:
        """把结构化 bug report 渲染成注入 solver 的反馈文本。

        按「关键错误优先」排序：修正步骤应当先修断链的错误，
        论证漏洞其次（否则会先去补一处无关紧要的严谨性，浪费修正预算）。
        """
        findings = report.get("findings") or []
        if not findings:
            return ""
        crit = [f for f in findings if f["type"] == "critical_error"]
        gaps = [f for f in findings if f["type"] == "justification_gap"]
        lines = []
        if crit:
            lines.append("【关键错误（必须修正，否则整条推理链作废）】")
            for i, f in enumerate(crit, 1):
                lines.append(f"{i}. 位置：“{f['location']}”")
                lines.append(f"   问题：{f['explanation']}")
        if gaps:
            lines.append("【论证漏洞（需补充论证，结论可能仍成立）】")
            for i, f in enumerate(gaps, 1):
                lines.append(f"{i}. 位置：“{f['location']}”")
                lines.append(f"   问题：{f['explanation']}")
        return "\n".join(lines)

    def _extract_revise_feedback(self, ctx, problem: str,
                                 candidates: list, best_cluster) -> str:
        """恢复 Reflexion 反馈：仅在需要 revise 时提取错因（受预算约束）。

        触发条件：best_cluster 存在且置信度 < 0.5（正确票未过半，验证器自身
        都不确定）。此时提取 LLM 错因定位，并叠加 AnswerOracle 的客观
        sanity check（纯本地、不消耗预算）。

        返回空串表示无需 revise 或预算不足。
        """
        if best_cluster is None:
            return ""
        if getattr(best_cluster, "confidence", 0.0) >= 0.5:
            return ""
        if ctx.is_time_critical():
            return ""

        # 取 best_cluster 的代表候选（共识簇内第一个候选）
        rep_candidate = None
        cids = getattr(best_cluster, "candidate_ids", []) or []
        if cids and candidates:
            idx = cids[0] if cids[0] < len(candidates) else 0
            rep_candidate = candidates[idx]
        if rep_candidate is None and candidates:
            rep_candidate = candidates[0]
        if rep_candidate is None:
            return ""

        parts = []
        # 1) LLM 错因提取（消耗 1 次预算）
        #    优先用结构化 bug report（分类 + 原文定位，修正时有的放矢）；
        #    解析不出 findings 时回退到原来的一句话错因。二者都只花 1 次调用，
        #    所以这是替换不是叠加。
        llm_feedback = ""
        if getattr(self.config, "use_bug_report_feedback", True):
            report = self._extract_bug_report(ctx, problem, rep_candidate)
            llm_feedback = self._format_bug_report(report)
        if not llm_feedback:
            llm_feedback = self._extract_feedback(ctx, problem, rep_candidate)
            if llm_feedback == "无法提取失败原因。":
                llm_feedback = ""
        if llm_feedback:
            parts.append(llm_feedback)
        # 2) AnswerOracle 客观 sanity check（纯本地，不消耗预算）
        oracle_fb = self._oracle_sanity_feedback(rep_candidate)
        if oracle_fb:
            parts.append(oracle_fb)

        if parts:
            return "\n".join(parts)
        return "所有候选均未获验证通过，请重新审题并纠正推理错误。"

    @staticmethod
    def _oracle_sanity_feedback(candidate) -> str:
        """用 AnswerOracle 做客观 sanity check（纯本地），返回客观反馈。"""
        answer = getattr(candidate, "answer", "") or ""
        if not answer:
            return "候选答案为空，需重新求解。"
        try:
            from .answer_oracle import AnswerOracle
            if not AnswerOracle.is_parseable(answer):
                return "候选答案无法解析为有效数学表达式，可能为幻觉或格式错误。"
        except Exception:  # noqa: BLE001
            pass
        return ""

    # ==================================================================
    # P1-1: Python/SymPy 独立验证通道 + 确定性复算（playoff）
    # ==================================================================

    _PLAYOFF_SYS = (
        "你是数学解题专家。重新独立地解答下面这道题，"
        "只输出最终答案（数值、表达式或选项字母），不要任何推理过程。"
    )

    def _sympy_spot_check(self, answer: str) -> dict:
        """对候选答案做 SymPy 独立 sanity check（不消耗 LLM 预算）。

        返回 {"parseable": bool, "value": str|None, "note": str}。
        仅用于给投票做旁证：可解析的数值/表达式答案可信度更高。
        """
        if not answer:
            return {"parseable": False, "value": None, "note": "empty"}
        try:
            from utils.sympy_tools import _try_parse, eval_expression
            parsed, err = _try_parse(answer)
            if parsed is None:
                return {"parseable": False, "value": None, "note": err}
            val = eval_expression(answer)
            return {"parseable": True, "value": val, "note": "ok"}
        except Exception as e:
            return {"parseable": False, "value": None, "note": str(e)[:80]}

    def _deterministic_check(self, ctx, problem: str, candidate) -> dict:
        """对候选答案做确定性旁证/否决（0 LLM 预算）。

        返回 DeterministicChecker.check_answer 的结果 dict：
        {"verdict": "pass"|"fail"|"unknown", "confidence": float,
         "evidence": str, "method": str}。
        任何异常一律降级 unknown（宁可 unknown 绝不误杀）。
        """
        answer = (candidate.get("answer", "") if isinstance(candidate, dict)
                  else getattr(candidate, "answer", ""))
        if not answer:
            return {"verdict": "unknown", "confidence": 0.0,
                    "evidence": "答案为空", "method": "none"}
        try:
            from .deterministic import DeterministicChecker
            checker = DeterministicChecker()
            return checker.check_answer(ctx, problem, answer,
                                        getattr(ctx, "domain", "") or "")
        except Exception as e:  # noqa: BLE001
            logger.warning("Deterministic check failed: %s", e)
            return {"verdict": "unknown", "confidence": 0.0,
                    "evidence": f"异常: {str(e)[:80]}", "method": "exception"}

    def _playoff_recheck(self, ctx, problem: str, top_answer: str) -> bool:
        """确定性复算（playoff）：用 temperature=0 重新解一遍，比对答案。

        解决"验证器与解题器同源一起错"的问题：低温重解是独立采样，
        若两次独立求解答案一致，则置信度大幅提升。
        """
        try:
            # v2.4.1：playoff 也走 prefill——「答案：」让答案前置，抑制 CoT 推理流
            resp = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": self._PLAYOFF_SYS},
                        {"role": "user", "content": problem},
                    ],
                    "答案：",
                ),
                0.0, 32768,
            )
            if resp:
                resp = stitch("答案：", resp)
            if not resp or not resp.strip():
                return False
            recheck_ans = smart_fallback_answer(resp)
            if not recheck_ans:
                return False
            return self._are_answers_equivalent(
                self._normalize_answer_text(top_answer),
                self._normalize_answer_text(recheck_ans),
            )
        except Exception as e:
            logger.warning("playoff recheck failed: %s", e)
            return False

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
            # v2.4.1：prefill「{"」引导 JSON 输出，抑制 CoT 前置长推理
            raw = self.llm(ctx, prefill_messages(messages, '{"'), 0.0, 32768)
            if raw:
                raw = stitch('{"', raw)
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
        use_playoff: bool = False,
        voting_times: int = None,
        use_deterministic: bool = False,
    ) -> dict:
        """
        验证主流程。

        参数:
            voting_times: 每候选投票数；None 时回退 config.verifier_voting_times。
                          （难题深度通道：deep 档传 3，fast/standard 传 1）

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

        # 常规：每个候选投票（voting_times 参数化：难题深度通道 deep 档 3 票）
        # v2.8：ctx.state.voting_times 优先（RunState 运行时覆盖），config 兜底
        if voting_times is None:
            voting_times = (getattr(ctx.state, 'voting_times', None)
                            or getattr(self.config, 'verifier_voting_times', 1))
        all_verdicts: list[list[Verdict]] = []
        for i, cand in enumerate(candidates):
            vds = self._vote(ctx, problem, cand, total_votes=voting_times,
                             use_scoring=use_scoring)
            all_verdicts.append(vds)

        # v2.8 确定性硬否决：SymPy 代入回验/反例对候选做客观旁证，
        # fail → 该候选全部票判错（淘汰）；unknown/pass → 仅挂证据不改判决。
        # 全部 fail 时回退保留（宁可 unknown 绝不误杀，镜像 LeanGate 降级逻辑）。
        if use_deterministic and candidates:
            det_results = [self._deterministic_check(ctx, problem, c) for c in candidates]
            n_fail = sum(1 for r in det_results if r.get("verdict") == "fail")
            if 0 < n_fail < len(candidates):
                for i, r in enumerate(det_results):
                    if r.get("verdict") == "fail":
                        for v in all_verdicts[i]:
                            v.correct = False
                            v.deterministic = r
                        all_verdicts[i].append(Verdict(
                            correct=False, raw="deterministic_fail", deterministic=r))
                        self.record(ctx, "deterministic",
                                    f"确定性硬否决候选 #{i}: {r.get('evidence', '')[:120]}")
                    else:
                        for v in all_verdicts[i]:
                            if v.deterministic is None:
                                v.deterministic = r
            else:
                for i, r in enumerate(det_results):
                    for v in all_verdicts[i]:
                        if v.deterministic is None:
                            v.deterministic = r
                if n_fail == len(candidates) and n_fail > 0:
                    self.record(ctx, "deterministic",
                                "全部候选确定性否决，回退保留（宁 unknown 不误杀）")

        # 聚类 + 共识
        cluster_data = self._cluster_candidates(candidates, all_verdicts) if use_clustering else []
        best_cluster = cluster_data[0] if cluster_data else None

        # P1-1 确定性复算（playoff）：共识不强或验证全错时，低温独立重解
        # P0-4 修复：默认关闭（use_playoff=False），仅在时间宽裕时由 orchestrator 开启，
        # 避免叠加调用链耗尽单题预算 → 45 error
        if use_playoff and best_cluster is not None and ctx.budget is not None:
            confidence = (best_cluster.vote_correct / best_cluster.vote_total
                          if best_cluster.vote_total else 0.0)
            # 触发条件：置信度低（验证结果不可靠）或投票全否
            if confidence < 0.5 and True:
                top_ans = best_cluster.answer_norm or ""
                if self._playoff_recheck(ctx, problem, top_ans):
                    best_cluster.vote_correct += 1
                    best_cluster.vote_total += 1
                    self.record(ctx, "playoff", "确定性复算通过，答案可信")
                else:
                    # 复算不一致 → 置信度下调，标记供 orchestrator 走 revise
                    best_cluster.vote_correct = 0
                    best_cluster.vote_total = max(1, best_cluster.vote_total)
                    self.record(ctx, "playoff", "确定性复算不一致，转自纠错")

        # Reflexion 修复：恢复失败反馈提取。仅在 best_cluster 低置信度/全错时
        # 提取（受预算约束），让 revise 回环拿到真实错误定位，而非空串导致的
        # "请重新审题"泛泛提示。
        feedback = self._extract_revise_feedback(ctx, problem, candidates, best_cluster)

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
            # v2.4.1：prefill「COMPLETE 」抑制 CoT，秒级返回判定
            raw = self.llm(ctx, prefill_messages(messages, "COMPLETE "), 0.0, 64)
            return "INCOMPLETE" not in raw.upper() or "COMPLETE" in raw.upper()
        except Exception:
            return True  # 网络异常时保守当作完整
