"""
答案规范化智能体（FormatterAgent）
==================================

把原 ``ReasoningAgent`` 末尾的答案抽取 / 兜底逻辑迁移为独立 Agent：
- 从 ``ctx.verdicts``（按置信度最高）或 ``ctx.candidates`` 选择最优答案；
- 通过 ``format_response`` 确保 ``final_response`` 非空且可序列化；
- 结果写入 ``ctx.final_response``，Orchestrator 负责封装返回字典。
"""

import logging
import re

from .base import BaseAgent, TaskContext
try:
    from utils.extract import format_response
except ImportError:  # 作为 submit 子包导入时
    from submit.utils.extract import format_response

logger = logging.getLogger("MathPilot")

# 拒绝回答/不完整答案的模式
_REFUSAL_RE = re.compile(r"无法求解|无法解决|不能解决|无法解答|我无法|暂无|无解", re.IGNORECASE)

# 明显截断/不完整的 LaTeX 环境或元语句
_INCOMPLETE_RE = re.compile(
    r"\\begin\{[^}]*\}\s*$|\\begin\{[^}]*\}\s*\\end\{[^}]*\}\s*$|"
    r"通解为\s*：\s*$|最终答案\s*：\s*$|答案为\s*$|选\s*$|"
    r"不过.{0,30}$|然而.{0,30}$|但是.{0,30}$|这可能不是",
    re.IGNORECASE,
)


class FormatterAgent(BaseAgent):
    name = "Formatter"

    def run(self, ctx: TaskContext) -> TaskContext:
        best = self._pick_best(ctx)
        if best is None:
            answer = "无法求解"
            confidence = 0.0
        else:
            answer = getattr(best, "answer", "") or "无法求解"
            confidence = getattr(best, "confidence", 0.0)

        # 如果最佳答案是拒绝类 / 明显不完整，尝试从其他候选找更好答案
        if not answer or _REFUSAL_RE.search(answer) or _INCOMPLETE_RE.search(answer):
            fallback = self._pick_fallback(ctx, exclude_answer=answer)
            if fallback:
                answer = fallback
                self.record(ctx, "finalize",
                           f"最佳候选答案为拒绝/不完整，改用候选兜底答案")
                confidence = 0.0

        # 答案质量终检 + 自动修复
        answer = self._diagnose_and_repair(answer, ctx)

        ctx.final_response = format_response(answer)
        self.record(
            ctx, "finalize",
            f"最终答案: {ctx.final_response[:200]} (置信度: {confidence:.2f})",
            confidence=round(confidence, 4),
        )
        return ctx

    def _pick_best(self, ctx: TaskContext):
        """选择最优答案来源：优先有效投票的 verdict，其次首个非空候选"""
        if ctx.verdicts:
            # 优先使用有有效投票的 verdict；全为 0 票时才用 0 票兜底
            valid = [v for v in ctx.verdicts if v.total_votes > 0]
            if valid:
                return max(valid, key=lambda v: v.confidence)
            return max(ctx.verdicts, key=lambda v: v.confidence)
        if ctx.candidates:
            for c in ctx.candidates:
                if c.answer:
                    return c
            return ctx.candidates[0]
        return None

    def _pick_fallback(self, ctx: TaskContext, exclude_answer: str = "") -> str:
        """当最佳答案是拒绝/不完整回答时，从候选中找到更可靠的答案"""
        exclude = exclude_answer or ""
        # 优先从有效 verdicts 中找非拒绝/非不完整答案（按置信度降序）
        valid_verdicts = [v for v in ctx.verdicts if v.total_votes > 0]
        if valid_verdicts:
            for v in sorted(valid_verdicts, key=lambda x: x.confidence, reverse=True):
                ans = getattr(v, "answer", "") or ""
                if (ans and len(ans) > 3
                        and ans != exclude
                        and not _REFUSAL_RE.search(ans)
                        and not _INCOMPLETE_RE.search(ans)):
                    return ans
        # 从 candidates 中找非拒绝/非不完整答案
        if ctx.candidates:
            for c in sorted(ctx.candidates, key=lambda x: len(x.reasoning or ""), reverse=True):
                ans = c.answer or ""
                if (ans and len(ans) > 3
                        and ans != exclude
                        and not _REFUSAL_RE.search(ans)
                        and not _INCOMPLETE_RE.search(ans)):
                    return ans
                # 候选答案也是拒绝类，但推理足够长 → 提取尾部
                if c.reasoning and len(c.reasoning) > 200:
                    from submit.utils.extract import extract_final_answer
                    fallback = extract_final_answer(c.reasoning)
                    if (fallback and len(fallback) > 2
                            and fallback != exclude
                            and not _REFUSAL_RE.search(fallback)
                            and not _INCOMPLETE_RE.search(fallback)):
                        return fallback
        return ""

    @staticmethod
    def _diagnose_and_repair(answer: str, ctx: TaskContext) -> str:
        """
        答案质量终检 + 自动修复。

        检测项:
        - 42 幻觉兜底（孤立的 42）
        - 截断 LaTeX（未闭合的 $ / { / \\begin）
        - markdown 污染（**...** 残留）
        - 多余包装文字

        返回修复后的答案（或原答案）。
        """
        if not answer or answer == "无法求解":
            return answer

        fixed = answer

        # 1. markdown 污染检测与修复
        if "**" in fixed or "__" in fixed:
            fixed = fixed.replace("**", "").replace("__", "")
            logger.info("Formatter 终检: 移除 markdown 标记")

        # 2. 42 幻觉检测（孤立的 42 / 42.0）
        stripped = fixed.strip()
        if re.fullmatch(r"42(?:\.0+)?", stripped):
            logger.warning("Formatter 终检: 检测到 42 兜底幻觉 → 尝试回溯")
            # 从其他候选中找到非 42 的答案
            for v in (ctx.verdicts or []):
                ans = (getattr(v, "answer", "") or "").strip()
                if ans and not re.fullmatch(r"42(?:\.0+)?", ans) and len(ans) > 1:
                    return ans
            for c in (ctx.candidates or []):
                ans = (c.answer or "").strip()
                if ans and not re.fullmatch(r"42(?:\.0+)?", ans) and len(ans) > 1:
                    return ans

        # 3. 截断 LaTeX 检测
        if re.search(r"\\begin\{[^}]*\}\s*$", fixed):
            logger.warning("Formatter 终检: 答案以 \\begin 结尾（截断）→ 尝试补全")
            # 从 reasoning 找对应的完整表达式
            for c in (ctx.candidates or []):
                if not c.reasoning:
                    continue
                env_match = re.search(
                    r"\\begin\{([^}]+)\}.*?\\end\{\1\}",
                    c.reasoning, re.DOTALL,
                )
                if env_match:
                    return env_match.group().strip()
        # 未闭合的 $ 或 {
        if fixed.count("$") % 2 == 1:
            fixed = fixed.rstrip("$")  # 移除不配对的 $
        open_braces = fixed.count("{") - fixed.count("}")
        if open_braces > 0:
            fixed = fixed + "}" * open_braces  # 补全大括号

        # 4. 多余包装文字剥离（如「因此答案是 x」→「x」）
        wrapped = re.match(
            r"^(?:因此|所以|故|综上[所]?述|答案为?|最终答案[为是]?)[,，:：]?\s*(.+?)\s*(?:。|$)",
            fixed, re.DOTALL | re.IGNORECASE,
        )
        if wrapped and len(wrapped.group(1)) > 1:
            inner = wrapped.group(1).strip()
            if inner != fixed.strip():
                logger.info("Formatter 终检: 剥离包装文字")
                return inner

        return fixed
