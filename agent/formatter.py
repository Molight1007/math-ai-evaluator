from __future__ import annotations
"""
答案规范化智能体（FormatterAgent）
==================================

把原 ``ReasoningAgent`` 末尾的答案抽取 / 兜底逻辑迁移为独立 Agent：
- 从 ``ctx.verdicts``（按置信度最高）或 ``ctx.candidates`` 选择最优答案；
- 通过 ``format_response`` 确保 ``final_response`` 非空且可序列化；
- 结果写入 ``ctx.final_response``，Orchestrator 负责封装返回字典。

BUG 修复：
  - 绝不输出"无法求解"等拒绝语（评测判 0）
  - _pick_best 启用共识加权（等价答案簇 → 更大簇更可信）
  - 增加 _is_valid_final_answer 终检
"""

import logging
import re

from .base import BaseAgent, TaskContext
from utils.extract import format_response, is_truncated_answer

logger = logging.getLogger("MathPilot")

# 拒绝回答/不完整答案的模式（2026-09-02 加"子目标求解失败"占位符：
# 占位符直接当最终答案 = 50% 错题（009/053/004/022 等），必须触发换候选兜底）
_REFUSAL_RE = re.compile(r"无法求解|无法解决|不能解决|无法解答|我无法|暂无|无解|子目标求解失败", re.IGNORECASE)

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
        # 2026-09-02 bug 修复：0 票兜底路径（orchestrator 5) 段）预设的答案
        # （direct_solve 直答结果）优先——该路径候选全 0 票不可信，重选候选
        # 反而会把直答的好答案换掉。预设答案仍需过拒绝/占位/截断检查。
        preset = (getattr(ctx, 'final_response', '') or '')
        if (getattr(ctx, '_zero_vote_fallback', False) and preset.strip()):
            answer = preset
            confidence = 0.0
            best = None
        else:
            best = self._pick_best(ctx)
            if best is None:
                # BUG-1 修复：绝不输出"无法求解"，也绝不把原题当答案。
                if ctx.candidates:
                    best = max(ctx.candidates, key=lambda c: len(c.reasoning or ""))
                    answer = best.answer if best.answer and len(best.answer) > 2 else (
                        (best.reasoning or "")[-500:])
                else:
                    answer = ""
                confidence = 0.0
            else:
                answer = getattr(best, "answer", "") or ""
                if not answer or len(answer) < 2:
                    answer = (getattr(best, "reasoning", "") or "")[-500:]
                confidence = getattr(best, "confidence", 0.0)
                # 如果来自聚类路径，优先使用簇的置信度（更可靠：基于多票共识）
                best_cluster = getattr(ctx, '_best_cluster', None)
                if best_cluster and getattr(best_cluster, 'confidence', 0.0) > 0:
                    confidence = best_cluster.confidence

        # 答案过长检测：如果答案超过300字符，尝试从推理尾部重新提取
        if answer and len(answer) > 300:
            for c in (ctx.candidates or []):
                if c.reasoning and getattr(c, 'answer', '') == answer:
                    from utils.extract import extract_final_answer
                    retry = extract_final_answer(c.reasoning)
                    if retry and len(retry) < len(answer) and len(retry) > 1:
                        self.record(ctx, "finalize",
                                   f"长答案重提取: {len(answer)}→{len(retry)} 字符")
                        answer = retry
                        confidence = max(confidence, 0.5)  # 重提取成功，给默认置信度
                        break

        # 如果最佳答案是拒绝类 / 明显不完整，尝试从其他候选找更好答案
        if not answer or _REFUSAL_RE.search(answer) or _INCOMPLETE_RE.search(answer):
            fallback = self._pick_fallback(ctx, exclude_answer=answer)
            if fallback:
                answer = fallback
                self.record(ctx, "finalize",
                           "最佳候选答案为拒绝/不完整，改用候选兜底答案")
                confidence = 0.0

        # 答案质量终检 + 自动修复
        answer = self._diagnose_and_repair(answer, ctx)

        # 2026-09-02 老师需求：最终答案截断必解决。
        # 003 题答案 g(x)=-2x^{ 就是生成截断直接提交 → expr_wrong。
        # 修复：检出截断 → 用 LLM 续写补全（最多 2 次），仍失败才原样返回。
        answer = self._repair_truncated(ctx, answer)

        # 2026-09-02 占位符兜底：子目标求解失败的占位符（50% 错题根源）
        # 续写无意义 → 走紧急直答重新求一次最终答案
        if "[子目标求解失败]" in (answer or ""):
            direct = self._emergency_answer(ctx)
            if direct:
                self.record(ctx, "finalize", f"占位符答案 → 紧急直答: {direct[:120]}")
                answer = direct
            else:
                self.record(ctx, "finalize", "占位符答案且紧急直答失败，原样输出")

        ctx.final_response = format_response(answer)
        self.record(
            ctx, "finalize",
            f"最终答案: {ctx.final_response[:200]} (置信度: {confidence:.2f})",
            confidence=round(confidence, 4),
        )
        return ctx

    def _pick_best(self, ctx: TaskContext):
        """
        选择最优答案（BUG-13 修复：共识加权）。
        优先使用聚类结果中置信度最高且规模最大的簇；其次使用传统 verdict 置信度。
        """
        # 0) 聚类数据（来自 verifier）→ 找最佳簇中第一个候选
        best_cluster = getattr(ctx, '_best_cluster', None)
        if best_cluster:
            cid_set = set(getattr(best_cluster, 'candidate_ids', []))
            matching = [c for c in (ctx.candidates or []) if c.id in cid_set]
            if matching:
                # 簇内选推理最详细的
                matching.sort(key=lambda c: len(c.reasoning or ""), reverse=True)
                return matching[0]

        # 1) 传统 verdict 置信度
        if ctx.verdicts:
            valid = [v for v in ctx.verdicts if v.total_votes > 0]
            if valid:
                return max(valid, key=lambda v: v.confidence)
            return max(ctx.verdicts, key=lambda v: v.confidence)

        # 2) 候选兜底
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
                    from utils.extract import extract_final_answer
                    fallback = extract_final_answer(c.reasoning)
                    if (fallback and len(fallback) > 2
                            and fallback != exclude
                            and not _REFUSAL_RE.search(fallback)
                            and not _INCOMPLETE_RE.search(fallback)):
                        return fallback
        return ""

    def _repair_truncated(self, ctx: TaskContext, answer: str) -> str:
        """2026-09-02 老师需求：截断答案续写补全（根治 -2x^{ 型截断）。

        截断信号：is_truncated_answer(answer) 为 True（LaTeX 半截/花括号不配对等）。
        用 LLM 从断点续写补全，最多 2 次；补全后仍截断则原样返回。
        """
        if not answer or not is_truncated_answer(answer):
            return answer
        try:
            from .base import _normalize_chat_response
            from utils.prefill import prefill_messages, stitch
            for attempt in range(2):
                if not is_truncated_answer(answer):
                    break
                tail = answer[-200:]  # 断点前片段作锚
                msgs = [
                    {"role": "system", "content":
                        "你是数学解答补全器。下面是一段被截断的解答结尾，"
                        "请从断点处继续，把最终答案补全为完整、规范的数学答案。"
                        "只输出续写内容（从断点开始），不要重复已给出的片段。"},
                    {"role": "user", "content": tail},
                ]
                resp = self.client.chat(
                    messages=prefill_messages(msgs, "【续写】: "),
                    temperature=0.0, max_tokens=65536,
                )
                text = _normalize_chat_response(resp)
                if not text:
                    break
                text = stitch("【续写】: ", text)
                m = re.search(r"【续写】[:：]?\s*([\s\S]+)", text)
                piece = m.group(1).strip() if m else text.strip()
                if not piece:
                    break
                # 防重复拼接：piece 若以 answer 尾部开头则剪掉重复段
                for cut in (80, 50, 30):
                    dup = answer[-cut:]
                    if dup and piece.startswith(dup):
                        piece = piece[cut:]
                        break
                answer = (answer + piece).strip()
                self.record(ctx, "finalize",
                            f"截断答案续写补全（第{attempt + 1}次）→ {answer[:120]}")
        except Exception:  # noqa: BLE001  补全失败不阻断，原样返回
            pass
        return answer

    def _emergency_answer(self, ctx: TaskContext) -> str:
        """2026-09-02 占位符兜底：最精简直答（prefill 答案前置，防截断）。

        主流程子目标全失败时 final 可能是占位符，续写救不回；
        直接让模型只输出【最终答案】，一次调用拿可用答案。
        """
        try:
            from .base import _normalize_chat_response
            from utils.prefill import prefill_messages, stitch
            sys_p = ("你是数学解题器。请直接给出题目的最终答案"
                     "（数值/表达式/集合），不要任何解释或推导过程。"
                     "格式：【最终答案】: <答案>")
            resp = self.client.chat(
                messages=prefill_messages(
                    [{"role": "system", "content": sys_p},
                     {"role": "user", "content": ctx.problem}],
                    "【最终答案】: ",
                ),
                temperature=0.0, max_tokens=65536,
            )
            text = _normalize_chat_response(resp)
            if not text:
                return ""
            text = stitch("【最终答案】: ", text)
            m = re.search(r"【最终答案】[:：]?\s*([\s\S]+)", text)
            ans = m.group(1).strip() if m else text.strip()
            # 去掉多余换行/包装，取首个完整行
            ans = ans.split("\n")[0].strip()
            if ans and not is_truncated_answer(ans):
                return ans
            return ""
        except Exception:  # noqa: BLE001
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
