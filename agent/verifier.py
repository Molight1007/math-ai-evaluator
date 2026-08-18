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

from .base import BaseAgent, TaskContext, Verdict, BugReport, Finding, Artifact, LemmaRepo
from prompts.verifier import (
    VERIFIER_SYSTEM,
    VERIFIER_USER_TEMPLATE,
    VERIFIER_SCORING_SYSTEM,
    VERIFIER_SCORING_TEMPLATE,
    VERIFIER_FEEDBACK_SYSTEM,
    VERIFIER_FEEDBACK_TEMPLATE,
    VERIFIER_RUBRIC_SYSTEM,
    VERIFIER_RUBRIC_TEMPLATE,
    VERIFIER_CHALLENGE_SYSTEM,
    VERIFIER_CHALLENGE_TEMPLATE,
)
from prompts.proof import PROOF_VERIFY_SYSTEM, PROOF_VERIFY_TEMPLATE
from utils.extract import smart_fallback_answer
from utils.prefill import prefill_messages, stitch

try:
    from .deterministic import DeterministicChecker
except ImportError:  # pragma: no cover - 极端导入失败降级
    DeterministicChecker = None

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
        self._checker = None  # DeterministicChecker 懒初始化

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

    def _vote_one(self, ctx, problem: str, artifact) -> str:
        """单次投票（返回原始文本）。

        v2.4.1：prefill「VERDICT: 」抑制 CoT——投票输出只需 A/B，
        实测 prefill 仲裁 0.8s vs 普通 70.2s（140×），杜绝 Intern-S2 推理流占满预算。
        P6：入参为结构化 Artifact，经 render 渲染模板。
        """
        messages = [
            {"role": "system", "content": VERIFIER_SYSTEM},
            {"role": "user", "content": artifact.render(VERIFIER_USER_TEMPLATE, problem=problem)},
        ]
        raw = self.llm(ctx, prefill_messages(messages, "VERDICT: "), 0.0, 512)
        return stitch("VERDICT: ", raw) if raw else raw

    def _vote_one_scoring(self, ctx, problem: str, artifact) -> dict | None:
        """评分模式投票（返回 JSON 或 None）。

        v2.4.1：prefill「{"」引导直接输出 JSON，抑制 CoT 前置长推理。
        P6：入参为结构化 Artifact，经 render 渲染模板。
        """
        messages = [
            {"role": "system", "content": VERIFIER_SCORING_SYSTEM},
            {"role": "user", "content": artifact.render(VERIFIER_SCORING_TEMPLATE, problem=problem)},
        ]
        raw = self.llm(ctx, prefill_messages(messages, '{"'), 0.0, 1024)
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

    # ==================================================================
    # v3 P1/P2：确定性旁证 + rubric 结构化判分（0 LLM 预算 / prefill 秒回）
    # ==================================================================

    def _get_checker(self) -> "DeterministicChecker | None":
        """懒初始化确定性验证器（无 SymPy 或导入失败时返回 None）。"""
        if DeterministicChecker is None:
            return None
        if self._checker is None:
            try:
                self._checker = DeterministicChecker()
            except Exception as e:  # pragma: no cover - 防御性兜底
                logger.warning("DeterministicChecker 初始化失败: %s", e)
                self._checker = None
        return self._checker

    def _deterministic_check(self, ctx, problem: str, candidate, cid: int) -> dict:
        """对候选答案做确定性旁证（SymPy 代入/解析），只记录证据、不参与判分。"""
        checker = self._get_checker()
        if checker is None:
            return {"verdict": "unknown", "confidence": 0.0,
                    "evidence": "确定性通道不可用", "method": "none"}
        try:
            ans = (candidate.get("answer", "") if isinstance(candidate, dict)
                   else getattr(candidate, "answer", ""))
            det = checker.check_answer(ctx, problem, str(ans),
                                       domain=getattr(ctx, "domain", None))
            self.record(ctx, "deterministic",
                        f"候选#{cid} 确定性旁证: {det['verdict']} - {det['evidence'][:100]}")
            return det
        except Exception as e:  # pragma: no cover - 防御性兜底
            return {"verdict": "unknown", "confidence": 0.0,
                    "evidence": f"异常: {str(e)[:80]}", "method": "error"}

    @staticmethod
    def _parse_rubric_json(raw: str) -> dict | None:
        """解析 rubric 判分 JSON（容忍包裹文本/截断）。"""
        if not raw:
            return None
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        m = re.search(r'\{[\s\S]*\}', raw)
        if m:
            try:
                obj = json.loads(m.group())
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        return None

    def _vote_one_rubric(self, ctx, problem: str, candidate_text: str) -> dict | None:
        """一次 rubric 结构化判分（JSON prefill，秒级返回，P2）。

        借鉴 Intern-MO judge：独立重算 → 对比 → 定位错因 → 输出
        {"verdict","confidence","error_type","step_index","reason"}。
        """
        messages = [
            {"role": "system", "content": VERIFIER_RUBRIC_SYSTEM},
            {"role": "user", "content": VERIFIER_RUBRIC_TEMPLATE.format(
                problem=problem, candidate_answer=candidate_text
            )},
        ]
        raw = self.llm(ctx, prefill_messages(messages, '{"'), 0.0, 1024)
        if raw:
            raw = stitch('{"', raw)
        rub = self._parse_rubric_json(raw)
        if rub is None:
            logger.warning("Rubric 判分 JSON 解析失败: %s", (raw or "")[:120])
        return rub

    def _challenge_counterexample(self, ctx, problem: str,
                                  candidate_text: str, answer: str) -> dict:
        """反例挑战（P2）：LLM 生成候选命题 → 程序数值验证才生效。

        只对非纯数值答案触发（数值答案直接走代入验证）。
        返回 {"hard_fail": bool, "evidence": str}。
        """
        checker = self._get_checker()
        if checker is None:
            return {"hard_fail": False, "evidence": "确定性通道不可用"}
        if not answer or not str(answer).strip():
            return {"hard_fail": False, "evidence": "无答案可挑战"}
        if re.fullmatch(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(answer).strip()):
            return {"hard_fail": False, "evidence": "数值答案，跳过命题反例搜索"}
        messages = [
            {"role": "system", "content": VERIFIER_CHALLENGE_SYSTEM},
            {"role": "user", "content": VERIFIER_CHALLENGE_TEMPLATE.format(
                problem=problem, candidate_answer=candidate_text
            )},
        ]
        raw = self.llm(ctx, prefill_messages(messages, '{"'), 0.0, 512)
        if raw:
            raw = stitch('{"', raw)
        parsed = self._parse_rubric_json(raw)
        if not parsed or not parsed.get("found"):
            return {"hard_fail": False, "evidence": "模型未提出反例命题"}
        statement = str(parsed.get("statement", "")).strip()
        if not statement:
            return {"hard_fail": False, "evidence": "反例命题为空"}
        res = checker.search_counterexample(statement, attempts=300)
        if res.get("found"):
            return {"hard_fail": True,
                    "evidence": f"反例验证成功: {statement} 在 {res.get('counterexample')} 处不成立"}
        return {"hard_fail": False, "evidence": f"反例搜索未找到 ({statement[:80]})"}

    def _vote_rubric(self, ctx, problem: str, candidate,
                     use_deterministic: bool = False) -> list[Verdict]:
        """P2 主判分路径：rubric 结构化判分 + 确定性旁证。

        - rubric: verdict A/B + confidence + 错因定位（错误类型/步骤/修正方向）
        - 确定性 fail → 硬否决（候选直接判错，绕过 LLM 判分，0 预算、100% 可复现）
        - 确定性 pass → 追加一张独立正确票（多证据汇审）
        - 确定性 unknown → 只挂证据，不追加票
        """
        text = self._candidate_text(candidate)
        cid = (candidate.get("id", 0) if isinstance(candidate, dict)
               else getattr(candidate, "id", 0))
        votes: list[Verdict] = []

        # 1) rubric 判分（1 次 JSON prefill）
        rub = self._vote_one_rubric(ctx, problem, text)
        if rub is None:
            votes.append(Verdict(correct=True, raw="rubric_parse_failed",
                                 feedback="rubric 判分解析失败，保守放行"))
        else:
            correct = str(rub.get("verdict", "B")).upper() == "A"
            feedback = ""
            if not correct:
                parts = []
                step = rub.get("step_index")
                if step is not None:
                    parts.append(f"步骤{step}")
                err = rub.get("error_type", "")
                if err and err != "无":
                    parts.append(err)
                reason = rub.get("reason", "")
                if reason:
                    parts.append(reason)
                feedback = "；".join(parts)
            votes.append(Verdict(
                correct=correct,
                raw=json.dumps(rub, ensure_ascii=False),
                feedback=feedback,
                score=rub,
                confidence=(float(rub.get("confidence", 0.0) or 0.0)
                            if correct else 0.0),
            ))

        # 2) 确定性旁证（0 LLM 预算）
        if use_deterministic:
            det = self._deterministic_check(ctx, problem, candidate, cid)
            if det.get("verdict") == "fail":
                logger.warning("确定性验证失败 → 硬否决候选#%d: %s", cid,
                               det.get("evidence", "")[:80])
                for v in votes:
                    v.correct = False
                    v.confidence = 0.0
                votes.append(Verdict(correct=False, raw="deterministic_fail",
                                     feedback=f"确定性验证否决: {det.get('evidence','')[:120]}",
                                     deterministic=det))
            elif det.get("verdict") == "pass":
                votes.append(Verdict(correct=True, raw="deterministic_pass",
                                     deterministic=det))
            else:
                # unknown：只挂证据，不追加票
                for v in votes:
                    v.deterministic = det

        return votes

    def _vote(
        self, ctx, problem: str, candidate, total_votes: int = 5,
        proportional: bool = True, use_scoring: bool = False,
    ) -> list[Verdict]:
        """
        批量投票并汇总（BUG-8 修复：用 valid_votes 替代 total_votes）。
        """
        # P6：用结构化 Artifact 渲染，替代手拼大字符串
        artifact = self._candidate_artifact(ctx, candidate)
        verdicts: list[Verdict] = []

        # 二元投票
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(total_votes, self.config.max_workers)
        ) as executor:
            futures = [executor.submit(self._vote_one, ctx, problem, artifact)
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
                scoring = self._vote_one_scoring(ctx, problem, artifact)
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
        artifact = self._candidate_artifact(ctx, candidate)
        messages = [
            {"role": "system", "content": VERIFIER_FEEDBACK_SYSTEM},
            {"role": "user", "content": artifact.render(
                VERIFIER_FEEDBACK_TEMPLATE, problem=problem)},
        ]
        try:
            # v2.4.1：prefill「错因：」抑制 CoT，直接输出错因定位
            raw = self.llm(ctx, prefill_messages(messages, "错因："), 0.0, 1024)
            return stitch("错因：", raw) if raw else "无法提取失败原因。"
        except Exception as e:
            logger.error(f"Feedback extraction failed: {e}")
            return "无法提取失败原因。"

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
                0.0,
                2048,
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
    # 证明步骤验证（P3：产出 step 级 BugReport，而非只返回 proof_valid/unknown）
    # ==================================================================

    def _parse_proof_json(self, raw: str) -> dict | None:
        """从 LLM 返回的 JSON 文本解析证明评审结构，失败返回 None。

        优先取最外层 JSON 对象（避免正则贪到内层子对象）。
        """
        if not raw:
            return None
        # 1) 直接整体解析（常见形态：裸 JSON）
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
        # 2) 取最外层大括号之间的内容（从首个 { 到最末 }，去除非 JSON 前后缀）
        m2 = re.search(r'\{[\s\S]*\}', raw)
        if m2:
            try:
                obj = json.loads(m2.group())
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError):
                pass
        # 3) 逐层尝试：取最后一对平衡括号（最内层到外层）
        depth = 0
        start = -1
        candidates = []
        for i, ch in enumerate(raw):
            if ch == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    candidates.append(raw[start:i + 1])
                    start = -1
        # 外层优先：从最长到最短尝试
        candidates.sort(key=len, reverse=True)
        for cand in candidates:
            try:
                obj = json.loads(cand)
                if isinstance(obj, dict) and 'overall' in obj:
                    return obj
            except (json.JSONDecodeError, ValueError):
                continue
        return None

    def _verify_proof_step(self, ctx, problem: str, solution: str) -> BugReport | None:
        """逐步骤验证证明，产出结构化 BugReport（P3）。

        BugReport.findings 中每条 Finding 映射一个出错步骤：
          - location = 步骤编号；
          - kind = Critical（fatal_error）| Gap（minor_issue）；
          - severity = 5（Critical）/ 1（Gap）；
          - desc = 评审注记。
        verdict = 'proof_valid' | 'proof_invalid' | 'unknown'。
        """
        messages = [
            {"role": "system", "content": PROOF_VERIFY_SYSTEM},
            {"role": "user", "content": PROOF_VERIFY_TEMPLATE.format(
                problem=problem, solution=solution
            )},
        ]
        try:
            # v2.4.1：prefill「{"」引导 JSON 输出，抑制 CoT 前置长推理
            raw = self.llm(ctx, prefill_messages(messages, '{"'), 0.0, 2048)
            if raw:
                raw = stitch('{"', raw)
            parsed = self._parse_proof_json(raw)
            if not parsed:
                return BugReport(verdict="unknown", findings=[])

            verdict = parsed.get("overall", "unknown")
            findings: list[Finding] = []
            for sv in parsed.get("step_verdicts", []) or []:
                v = sv.get("verdict", "")
                note = sv.get("note", "") or ""
                if v == "fatal_error":
                    findings.append(Finding(
                        location=str(sv.get("step", "")),
                        kind="Critical", severity=5, desc=note))
                elif v == "minor_issue":
                    findings.append(Finding(
                        location=str(sv.get("step", "")),
                        kind="Gap", severity=1, desc=note))
            if parsed.get("first_error_step"):
                findings.insert(0, Finding(
                    location=f"first_error_step={parsed['first_error_step']}",
                    kind="Critical" if verdict == "proof_invalid" else "Gap",
                    severity=5 if verdict == "proof_invalid" else 1,
                    desc=parsed.get("raw", "")[:200]))
            return BugReport(findings=findings, verdict=verdict)
        except Exception as e:
            logger.warning(f"Proof step verify failed: {e}")
            return BugReport(verdict="unknown", findings=[])

    # ==================================================================
    # 主流程
    # ==================================================================

    def run(
        self, ctx: TaskContext, problem: str, candidates: list,
        use_clustering: bool = True,
        use_scoring: bool = False,
        is_proof: bool = False,
        use_playoff: bool = False,
        use_deterministic: bool | None = None,
        use_rubric: bool | None = None,
        use_challenge: bool | None = None,
    ) -> dict:
        """
        验证主流程。

        参数:
            use_deterministic: v3 P1 确定性旁证；None 取 config.use_deterministic。
                P1 模式：只挂证据（Verdict.deterministic）不改决策；
                P2（use_rubric）模式：fail 硬否决、pass 追加独立正确票。
            use_rubric: v3 P2 结构化 rubric 判分（JSON：verdict/置信度/错因定位）；
                None 取 config.use_rubric。开启后替代二元投票路径。
            use_challenge: v3 P2 反例挑战（LLM 生成命题 + 程序验证）。

        返回:
            {
                "cluster_data": list[AnswerCluster],  # 候选传给 orchestrator
                "feedback": str,                       # 自纠错用
                "verdicts": list[list[Verdict]],       # 原始裁决
                "best_cluster": AnswerCluster | None,
            }
        """
        if use_deterministic is None:
            use_deterministic = bool(getattr(self.config, "use_deterministic", False))
        if use_rubric is None:
            use_rubric = bool(getattr(self.config, "use_rubric", False))
        if use_challenge is None:
            use_challenge = bool(getattr(self.config, "use_challenge", False))
        # 特殊处理证明题
        if is_proof and len(candidates) == 1:
            # 逐步骤验证（P3：产出 BugReport，包含 step 级 findings）
            proof_text = self._candidate_text(candidates[0])
            report = self._verify_proof_step(ctx, problem, proof_text)
            overall_correct = report.is_valid() if report else False
            v = Verdict(correct=overall_correct,
                        raw=report.to_json() if report else "{}")
            cluster = AnswerCluster("proof")
            cluster.candidate_ids = [candidates[0].get("id", 0)]
            cluster.vote_correct = 1 if overall_correct else 0
            cluster.vote_total = 1
            # P1：失败时把首个致命缺陷/缺口作为自纠错反馈回传
            feedback = ""
            if report and not overall_correct:
                first = next((f for f in report.findings if f.kind == "Critical"),
                             report.findings[0] if report.findings else None)
                feedback = first.desc if first else report.verdict
            return {
                "cluster_data": [cluster],
                "feedback": feedback,
                "verdicts": [[v]],
                "best_cluster": cluster,
            }

        # 常规：每个候选投票
        all_verdicts: list[list[Verdict]] = []
        # B6：PaperPacer 运行时收紧投票数（如应急模式）写入 ctx.state，此处读取生效值
        effective_votes = (ctx.state.voting_times
                          if ctx.state and ctx.state.voting_times
                          else self.config.verifier_voting_times)
        for i, cand in enumerate(candidates):
            if use_rubric:
                # v3 P2：rubric 结构化判分 + 确定性旁证（fail 硬否决 / pass 独立票）
                vds = self._vote_rubric(ctx, problem, cand,
                                        use_deterministic=use_deterministic)
            else:
                vds = self._vote(ctx, problem, cand, total_votes=effective_votes,
                                 use_scoring=use_scoring)
                # v3 P1：确定性旁证（0 LLM 预算，只出证据不改决策）
                if use_deterministic:
                    det = self._deterministic_check(ctx, problem, cand, i)
                    for v in vds:
                        v.deterministic = det
            # v3 P2：反例挑战（仅全错候选触发，LLM 命题 + 程序验证）
            if use_challenge and vds and not any(v.correct for v in vds):
                ans = (cand.get("answer", "") if isinstance(cand, dict)
                       else getattr(cand, "answer", ""))
                chal = self._challenge_counterexample(
                    ctx, problem, self._candidate_text(cand), str(ans))
                if chal.get("hard_fail"):
                    for v in vds:
                        v.correct = False
                        v.confidence = 0.0
                    vds.append(Verdict(correct=False, raw="counterexample_fail",
                                       feedback=f"反例挑战否决: {chal.get('evidence','')[:120]}"))
                self.record(ctx, "challenge",
                            f"候选#{i} 反例挑战: {chal['evidence'][:100]}")
            all_verdicts.append(vds)

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
            if confidence < 0.5 and ctx.budget.can_spend(1):
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

        # P1：恢复自纠错回环所需的结构化反馈提取（此前 L501 硬编码为 ""）
        # 只有最佳簇未全票通过时才提取，避免无谓的反馈 LLM 调用
        feedback = ""
        if best_cluster is not None and best_cluster.vote_total > 0 \
                and best_cluster.vote_correct < best_cluster.vote_total:
            # 选中错票最多的候选作为反馈目标（最不可信 → 最需要定向修正）
            worst_cand = self._worst_candidate(candidates, all_verdicts)
            if worst_cand is not None and ctx.budget is not None \
                    and ctx.budget.can_spend(1):
                feedback = self._extract_feedback(ctx, problem, worst_cand)
                self.record(ctx, "feedback", "已提取自纠错反馈")

        return {
            "cluster_data": cluster_data,
            "feedback": feedback,
            "verdicts": all_verdicts,
            "best_cluster": best_cluster,
        }

    def _worst_candidate(self, candidates: list, all_verdicts: list) -> object | None:
        """选出错票最多（最不可信）的候选，作为自纠错反馈的目标。

        P1：反馈应针对"验证最失败"的候选，而不是随机或首个候选，
        从而让 Solver 的定向修正更精准。
        """
        if not candidates:
            return None
        worst_idx, worst_neg = 0, -1
        for i, cand in enumerate(candidates):
            vds = all_verdicts[i] if i < len(all_verdicts) else []
            neg = sum(1 for v in vds if not v.correct)
            if neg > worst_neg:
                worst_neg = neg
                worst_idx = i
        if worst_neg <= 0:
            return None  # 没有错误票，无需反馈
        return candidates[worst_idx]

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

    def _candidate_artifact(self, ctx: TaskContext, candidate) -> Artifact:
        """P6：把候选构建为结构化 Artifact（含 reasoning/answer/lemmas/citations）。

        从 ctx.lemma_repo 抽取可复用引理填充 lemmas，替代手拼大字符串。
        """
        artifact = Artifact.from_candidate(candidate)
        repo = getattr(ctx, "lemma_repo", None)
        if repo is not None:
            try:
                if isinstance(repo, LemmaRepo):
                    artifact.lemmas = repo.query(ctx.problem, limit=5)
                else:
                    artifact.lemmas = list(repo)[-5:]
            except Exception:
                artifact.lemmas = []
        # citations 预留：可挂接来源/参考文献（当前为空列表）
        artifact.citations = []
        return artifact

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
