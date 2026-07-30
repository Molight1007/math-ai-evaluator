"""
过程校验智能体（VerifierAgent）
==============================

把原 ``ReasoningAgent._verify_candidates`` / ``_vote_on_candidate`` 迁移为
独立 Agent，并新增 **失败原因提取** 能力（供 Orchestrator 触发自纠错回环）：

- 仅对尚未验证的候选投票（支持 revise / 追加候选后的增量验证）；
- 投票结果写入 ``ctx.verdicts``，按置信度降序；
- ``feedback`` 方法在被判定为错误的候选上，额外调用一次验证器提取错因。

执行策略：
- 候选之间、同一候选的各轮投票均串行执行，避免并发 API 调用触发速率限制；
- 置信度分母固定为配置的投票次数，确保少量有效投票时不会虚高到 1.0。
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import BaseAgent, TaskContext, Candidate, Verdict
from prompts.verifier import (
    VERIFIER_SYSTEM,
    VERIFIER_USER_TEMPLATE,
    VERIFIER_FEEDBACK_SYSTEM,
    VERIFIER_FEEDBACK_TEMPLATE,
    VERIFIER_SCORING_SYSTEM,
    VERIFIER_SCORING_TEMPLATE,
)
from utils.extract import smart_fallback_answer

logger = logging.getLogger("MathPilot")


class VerifierAgent(BaseAgent):
    name = "Verifier"

    def run(self, ctx: TaskContext) -> TaskContext:
        to_verify = [c for c in ctx.candidates if c.id not in ctx.verified_ids()]
        if not to_verify:
            ctx.verdicts.sort(key=lambda v: v.confidence, reverse=True)
            self.record(ctx, "verify", "无需验证候选")
            return ctx

        # 1) 规则预筛：快速拒绝明显格式错误的答案（零 LLM 成本）
        pre_rejected = self._rule_prescreen(ctx, to_verify)
        active = [c for c in to_verify if c.id not in pre_rejected]
        for cid in pre_rejected:
            c = ctx.candidates[cid]
            ctx.verdicts.append(Verdict(
                id=cid, answer=c.answer or "", reasoning=c.reasoning,
                confidence=0.0, correct_votes=0, total_votes=1,
                feedback="规则预筛: 答案格式无效",
            ))

        if not active:
            ctx.verdicts.sort(key=lambda v: v.confidence, reverse=True)
            self.record(ctx, "verify", "全部候选被规则预筛拒绝")
            return ctx

        # 2) 等价分组（同一组内答案数学等价）
        self._equiv_group(ctx, active)

        # 3) 并行验证所有未验证候选
        new_verdicts = []
        max_workers = min(len(active), 6)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._vote, ctx, c): c for c in active}
            for future in as_completed(futures):
                new_verdicts.append(future.result())

        ctx.verdicts.extend(new_verdicts)
        ctx.verdicts.sort(key=lambda v: v.confidence, reverse=True)
        self.record(
            ctx, "verify", "验证候选解答",
            verification=[{"id": v.id, "confidence": v.confidence,
                           "correct_votes": v.correct_votes, "total_votes": v.total_votes}
                          for v in ctx.verdicts],
        )
        return ctx

    def _vote(self, ctx: TaskContext, c: Candidate) -> Verdict:
        """对单个候选多轮投票，返回带置信度的验证结果（投票串行+重试）"""
        if not c.answer:
            # 兜底：answer 为空时尝试从 reasoning 尾部提取（最多 500 字符）
            reasoning_text = c.reasoning.strip() if c.reasoning else ""
            if not reasoning_text or reasoning_text.startswith("[生成失败]") or reasoning_text.startswith("[重解失败]"):
                return Verdict(c.id, c.answer, c.reasoning, 0.0, 0, 0)
            from utils.extract import extract_final_answer
            fallback_answer = extract_final_answer(reasoning_text)
            if not fallback_answer:
                fallback_answer = smart_fallback_answer(reasoning_text)
            c.answer = fallback_answer

        total_votes = self.config.verifier_voting_times

        def _do_one_vote():
            # 把完整答案 + 尽量完整的推理传给验证器，避免截断导致误判
            max_reasoning_len = 12000
            if len(c.reasoning) > max_reasoning_len:
                reasoning_text = (
                    c.reasoning[:max_reasoning_len // 2]
                    + "\n...[中间推理已省略]\n"
                    + c.reasoning[-max_reasoning_len // 2:]
                )
            else:
                reasoning_text = c.reasoning
            combined = f"完整推理过程：\n{reasoning_text}\n\n请基于以上推理过程，判断以下答案是否正确：{c.answer}"
            user_msg = VERIFIER_USER_TEMPLATE.format(
                problem=ctx.problem,
                candidate_answer=combined,
            )
            return self.llm(
                ctx,
                [
                    {"role": "system", "content": VERIFIER_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                self.config.verifier_temperature,
                256,
            )

        # 并行投票 + 失败重试
        def _vote_with_retry(vote_idx: int) -> str | None:
            for retry in range(2):
                resp = _do_one_vote()
                if resp is not None:
                    return resp
                if retry == 0:
                    logger.warning("Verifier vote %d for candidate %d empty, retry", vote_idx, c.id)
                    time.sleep(1.0)
            return None

        valid_responses = []
        with ThreadPoolExecutor(max_workers=min(total_votes, 2)) as pool:
            futures = [pool.submit(_vote_with_retry, i) for i in range(total_votes)]
            for f in futures:
                resp = f.result()
                if resp is not None:
                    valid_responses.append(resp)

        correct_votes = sum(1 for resp in valid_responses if self._is_correct_vote(resp))

        # 没有任何有效投票 → 返回 total_votes=0，让 orchestrator 感知验证失败
        if not valid_responses:
            return Verdict(c.id, c.answer, c.reasoning, 0.0, 0, 0)

        # 使用配置的 total_votes 作为分母，避免 1/1 变成 1.0
        confidence = round(correct_votes / total_votes, 4)
        return Verdict(
            c.id, c.answer, c.reasoning,
            confidence, correct_votes, total_votes,
        )

    def feedback(self, ctx: TaskContext, candidate: Candidate) -> str:
        """提取候选解答的错误原因（自纠错回环用）"""
        # 提取尽量完整的推理用于错因分析（优先保留尾部结论）
        feedback_reasoning = candidate.reasoning
        if len(feedback_reasoning) > 12000:
            feedback_reasoning = (
                feedback_reasoning[:6000]
                + "\n...[中间推理已省略]\n"
                + feedback_reasoning[-6000:]
            )
        user_msg = VERIFIER_FEEDBACK_TEMPLATE.format(
            problem=ctx.problem,
            candidate_answer=feedback_reasoning,
        )
        resp = self.llm(
            ctx,
            [
                {"role": "system", "content": VERIFIER_FEEDBACK_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            0.0, 512,
        )
        return (resp or "未提供错误分析").strip()

    def check_completeness(self, ctx: TaskContext, candidate: Candidate) -> bool:
        """
        用 LLM 检查答案是否完整（未被截断、有明确结论）。
        返回 True 表示完整，False 表示不完整。
        """
        # 取 reasoning 尾部，通常包含结论和“答案”；保留更多上下文防止误判
        tail_len = 2500
        if candidate.reasoning and len(candidate.reasoning) > tail_len:
            tail = "...[中间推理已省略]\n" + candidate.reasoning[-tail_len:]
        else:
            tail = candidate.reasoning or "(空)"
        check_prompt = (
            "请判断以下数学推理是否完整（未被截断，有明确的最终答案）。\n"
            "只回复 YES 或 NO，不要任何解释。\n\n"
            f"提取的答案：{candidate.answer or '(空)'}\n"
            f"推理尾部（最后 {tail_len} 字符）：\n{tail}"
        )
        try:
            resp = self.llm(
                ctx,
                [{"role": "system", "content": "只回复 YES 或 NO。"},
                 {"role": "user", "content": check_prompt}],
                0.0, 16,
            )
        except Exception:
            return True  # 网络错误时保守认为完整
        if resp is None:
            return True
        resp_upper = resp.strip().upper()
        if "YES" in resp_upper and "NO" not in resp_upper:
            return True
        if "NO" in resp_upper:
            return False
        return True  # 默认认为完整

    @staticmethod
    def _is_correct_vote(response: str) -> bool:
        """
        解析验证器的投票结果（与原实现保持一致）：
        - VERDICT: A / VERDICT: B
        - 纯输出 A / B
        - CORRECT / INCORRECT
        - 正确 / 错误
        """
        text = response.strip().upper()
        if "VERDICT: A" in text or "VERDICT:A" in text:
            return True
        if "VERDICT: B" in text or "VERDICT:B" in text:
            return False
        if "CORRECT" in text or "正确" in text:
            return True
        if "INCORRECT" in text or "错误" in text or "WRONG" in text:
            return False
        lines = response.strip().split("\n")
        last = lines[-1].strip().upper() if lines else ""
        # 容忍尾部杂音：A. / (A) / "A" 等变形
        last_clean = re.sub(r'[^\w]', '', last)
        if last_clean and last_clean[-1:] in ("A", "B"):
            return last_clean[-1:] == "A"
        # 精确匹配单字符
        if last in ("A", "B"):
            return last == "A"
        return False

    # ── 规则预筛 & 等价分组 ──────────────────────────────

    # 明显无意义的答案模式
    _EMPTY_ANSWER_PATTERNS = [
        re.compile(r"^\s*$"),                          # 纯空白
        re.compile(r"^(N/?A|null|none|undefined)\s*$", re.IGNORECASE),
        re.compile(r"^[，,。.;；:：!！?？…\-—\s]+$"),   # 纯标点
        re.compile(r"^(答案|结果)(：|:)?\s*$"),          # 有标签无内容
    ]

    @classmethod
    def _rule_prescreen(cls, ctx, candidates: list) -> set:
        """快速排除明显无效的答案（answer 和 reasoning 同时为空时才拒绝）。"""
        rejected = set()
        for c in candidates:
            ans = (c.answer or "").strip()
            # 如果 answer 为空，用 reasoning 作为判断依据
            if not ans:
                ans = (c.reasoning or "").strip()
            if not ans or any(p.search(ans) for p in cls._EMPTY_ANSWER_PATTERNS):
                logger.info("Verifier 规则预筛: candidate %d 答案为空/无意义 → 拒绝", c.id)
                rejected.add(c.id)
        return rejected

    @staticmethod
    def _equiv_group(ctx, candidates: list) -> list[list[int]]:
        """
        将候选按答案数学等价性分组（纯文本策略）。

        分组规则：
        1) 归一化后完全相同的答案 → 同一组
        2) 归一化后差异仅在精度上的数值 → 同一组

        返回: [[cid1, cid2, ...], [cid3, ...], ...]
        """
        if not candidates:
            return []

        def _norm(s: str) -> str:
            """轻量归一化：去空白、去 LaTeX 外壳、数值归精度"""
            s = s.strip()
            if s.startswith("$$") and s.endswith("$$"):
                s = s[2:-2].strip()
            if s.startswith("$") and s.endswith("$"):
                s = s[1:-1].strip()
            s = re.sub(r"\s+", "", s)
            def _round_num(m):
                try:
                    return f"{float(m.group()):.6g}"
                except ValueError:
                    return m.group()
            s = re.sub(r"\d+\.\d+", _round_num, s)
            return s

        groups: list[set[int]] = []
        for c in candidates:
            ans = _norm(c.answer or "")
            if not ans:
                continue
            found = False
            for g in groups:
                ref_cid = next(iter(g))
                ref_ans = _norm((ctx.candidates[ref_cid].answer or ""))
                if ans == ref_ans:
                    g.add(c.id)
                    found = True
                    break
            if not found:
                groups.append({c.id})

        result = [sorted(g) for g in groups]
        if len(result) < len(candidates):
            logger.info("Verifier 等价分组: %d 候选 → %d 组", len(candidates), len(result))
        return result
