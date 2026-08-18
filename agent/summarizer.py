from __future__ import annotations
"""
摘要智能体（SummarizerAgent）—— P5
====================================

职责：把长推理压缩成**可检索的中间结论**，写入 LemmaRepo（引理库），
供 Solver / 后续轮次跨题复用，减少重复推理。

与 SolverAgent / VerifierAgent 解耦：
  - 输入：某候选（dict / Candidate）或纯文本的推理内容；
  - 输出：把结构化中间结论写入 ``ctx.lemma_repo``（LemmaRepo）；
  - 不修改 ctx.candidates / verdicts，只做"压榨与沉淀"。

契约（QA test_summarizer.py 对齐）：
  - ``run(ctx)``：压缩最优候选 → 写库（去重）；
  - ``summarize(ctx, text) -> list[str]``：返回提取出的中间结论；
  - ``persist(ctx, conclusions)``：去重写入 ctx.lemma_repo；
  - 无 LLM 可用时安全降级（不抛异常）。
"""

import logging
import re

from .base import BaseAgent, TaskContext, LemmaRepo
from prompts.summarizer import (
    SUMMARIZER_SYSTEM,
    SUMMARIZER_USER_TEMPLATE,
)
from utils.prefill import prefill_messages, stitch

logger = logging.getLogger("MathPilot.Summarizer")


class SummarizerAgent(BaseAgent):
    name = "Summarizer"

    def run(self, ctx: TaskContext) -> TaskContext:
        """压缩最优/最新候选的推理，沉淀中间结论到 LemmaRepo。"""
        if ctx.state.emergency:
            # 应急模式：跳过压缩，省预算保产出
            return ctx
        candidate = self._pick_candidate(ctx)
        if candidate is None:
            return ctx
        text = self._candidate_text(candidate)
        conclusions = self.summarize(ctx, text)
        self.persist(ctx, conclusions)
        self.record(ctx, "summarize",
                    f"沉淀 {len(conclusions)} 条中间结论到引理库"
                    f"（库内共 {len(ctx.lemma_repo)} 条）")
        return ctx

    # ----------------------------------------------------------
    # 摘要核心
    # ----------------------------------------------------------
    def summarize(self, ctx: TaskContext, text: str) -> list[str]:
        """把推理压缩成中间结论列表。LLM 失败时返回空列表。"""
        if not text or not text.strip():
            return []
        user_content = SUMMARIZER_USER_TEMPLATE.format(reasoning=text)
        try:
            raw = self.llm(
                ctx,
                prefill_messages(
                    [
                        {"role": "system", "content": SUMMARIZER_SYSTEM},
                        {"role": "user", "content": user_content},
                    ],
                    "- ",
                ),
                0.0,
                2048,
            )
            if raw:
                raw = stitch("- ", raw)
            return self._parse_conclusions(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("Summarizer failed: %s", e)
            return []

    def persist(self, ctx: TaskContext, conclusions: list[str]) -> int:
        """去重写入 ctx.lemma_repo，返回新增条数。"""
        repo = getattr(ctx, 'lemma_repo', None)
        if not isinstance(repo, LemmaRepo):
            # 兼容旧式 list[str]
            if isinstance(repo, list):
                added = 0
                for c in conclusions:
                    if c not in repo:
                        repo.append(c)
                        added += 1
                return added
            return 0
        added = 0
        for c in conclusions:
            if repo.add(c, verified=True):
                added += 1
        return added

    # ----------------------------------------------------------
    # 辅助
    # ----------------------------------------------------------
    def _pick_candidate(self, ctx: TaskContext):
        """挑选最优候选（best_cluster 对应 / 置信度最高 / 最详细）。

        健壮性：candidates 可能是 ``Candidate`` 对象（主流程）或 ``dict``，
        统一用 getattr / isinstance 取值，避免属性访问抛异常（B7 结构化改造后
        的兼容层，兼容 dict 与对象两种形态）。
        """
        def _get(c, attr, default=None):
            if isinstance(c, dict):
                return c.get(attr, default)
            return getattr(c, attr, default)

        best_cluster = getattr(ctx, '_best_cluster', None)
        if best_cluster is not None and best_cluster.candidate_ids:
            for c in ctx.candidates:
                if _get(c, "id") in best_cluster.candidate_ids:
                    return c
        if ctx.candidates:
            return max(
                ctx.candidates,
                key=lambda c: len(_get(c, "reasoning") or ""),
            )
        return None

    @staticmethod
    def _candidate_text(candidate) -> str:
        if isinstance(candidate, dict):
            parts = []
            if candidate.get("reasoning"):
                parts.append(candidate["reasoning"])
            if candidate.get("answer"):
                parts.append(f"【最终答案】{candidate['answer']}")
            return "\n".join(parts)
        reasoning = getattr(candidate, "reasoning", "")
        answer = getattr(candidate, "answer", "")
        return f"{reasoning}\n【最终答案】{answer}" if reasoning or answer else str(candidate)

    @staticmethod
    def _parse_conclusions(raw: str) -> list[str]:
        """从 LLM 输出解析 "- " 开头的中间结论行。"""
        if not raw:
            return []
        out = []
        for line in raw.split("\n"):
            line = line.strip()
            # 去掉列表前缀
            line = re.sub(r"^[-*•\d\.\)、]+\s*", "", line)
            if not line or len(line) < 2:
                continue
            # 去掉包裹的引号
            line = line.strip("`\"'“”‘’")
            if line not in out:
                out.append(line)
        return out
