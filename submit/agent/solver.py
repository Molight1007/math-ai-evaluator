"""
通用求解智能体（SolverAgent）
============================

把原 ``ReasoningAgent._generate_candidates`` 迁移为独立 Agent，并新增
**自纠错重解（revise）模式**：

- 初始求解：蓝图分解（LEAP 启发）+ 领域提示注入（复用 prompts/policy）；
- 重解模式：当 ``ctx.revise_feedback`` 非空且处于 revise 轮次时，改用
  ``prompts/revise`` 的纠错提示词，针对验证器指出的错误定向修正；
- 追加候选：中置信度分支调用 ``add_candidates`` 补充采样。
- 直接求解：当所有候选都失败时（last-resort），使用简化提示词直接求解。

性能优化：
- 候选生成和纠错重解改为串行请求（每次间隔 0.3s），避免 API 请求风暴。
"""


import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import (
    BaseAgent, TaskContext, Candidate,
    detect_hallucination, detect_truncated,
)
try:
    from prompts.policy import (
        POLICY_SYSTEM,
        get_policy_system,
        get_domain_hint,
        build_blueprint_user_message,
    )
    from prompts.revise import REVISE_SYSTEM, REVISE_USER_TEMPLATE
    from utils.extract import extract_final_answer, smart_fallback_answer
except ImportError:  # 作为 submit 子包导入时（如评测器以项目根为 sys.path）
    from submit.prompts.policy import (
        POLICY_SYSTEM,
        get_policy_system,
        get_domain_hint,
        build_blueprint_user_message,
    )
    from submit.prompts.revise import REVISE_SYSTEM, REVISE_USER_TEMPLATE
    from submit.utils.extract import extract_final_answer, smart_fallback_answer

logger = logging.getLogger("MathPilot")

# ------------------------------------------------------------------
# 拒绝回答的检测模式
# ------------------------------------------------------------------
_REFUSAL_PATTERNS = [
    r"无法求解",
    r"无法解决",
    r"不能解决",
    r"无法解答",
    r"我无法",
    r"我没办法",
    r"很抱歉.{0,10}(?:无法|不能)",
    r"抱歉.{0,10}(?:无法|不能)",
    r"超出.{0,5}能力",
    r"暂时无法",
    r"(?:不|没有)足够.{0,5}(?:信息|条件|数据)",
    r"题目.{0,5}(?:有误|不完整|不清晰)",
    r"(?:I\s)?can'?t\s+solve",
    r"no\s+solution",
    r"unable\s+to\s+solve",
]

_REINFORCED_SYSTEM = (
    "你是一名顶尖的数学竞赛选手，必须对每道题给出明确的解答。"
    "即使题目看起来困难或信息不全，也要尽力推理并给出你最好的答案。"
    "绝对不能回答'无法求解'或'不能解决'。请务必在【最终答案】中给出一个确定的答案。"
)


def _is_refusal(text: str) -> bool:
    """检测模型输出是否为拒绝回答"""
    if not text or not text.strip():
        return True
    # 去掉推理过程，只看结尾 500 字符和开头 200 字符
    start = text.strip()[:200]
    end = text.strip()[-500:]
    for pat in _REFUSAL_PATTERNS:
        if re.search(pat, end) or re.search(pat, start):
            return True
    # 纯拒绝（全文很短且无数学内容）
    if len(text.strip()) < 200:
        has_math = bool(re.search(r"[$\\=+\-*/^()]|\d{2,}", text))
        if not has_math:
            return True
    return False


class SolverAgent(BaseAgent):
    name = "Solver"

    def run(self, ctx: TaskContext) -> TaskContext:
        """根据当前上下文状态决定初始求解还是纠错重解"""
        if ctx.revise_round > 0 and ctx.revise_feedback:
            self._generate_revise(ctx)
        else:
            self._generate_initial(ctx)
        return ctx

    def add_candidates(self, ctx: TaskContext, count: int = None) -> TaskContext:
        """中置信度分支：补充生成普通候选（默认与初始采样数一致）"""
        self._generate_initial(ctx, count or self.config.policy_sample_times)
        return ctx

    @staticmethod
    def _adaptive_count(ctx: TaskContext, default_count: int) -> int:
        """根据题目领域自适应调整候选数量"""
        domain = (ctx.domain or "").lower()
        problem_len = len(ctx.problem)
        # 证明题（proof/inequality/geometry theorem）→ 1 个候选即可
        proof_keywords = ["proof", "prove", "证明", "证明题", "不等式证明", "几何证明"]
        if any(k in domain for k in proof_keywords):
            return 1
        # 高难度计算题 → 增加候选
        hard_signals = [
            problem_len > 500,  # 长题目
            any(k in domain for k in ("differential_equation", "微分方程")),
            any(k in domain for k in ("series", "级数")),
            any(k in domain for k in ("integral", "不定积分", "indefinite_integral",
                                        "重积分", "曲线积分", "曲面积分")),
        ]
        if sum(hard_signals) >= 2:
            return max(default_count, 3)
        # 单选题/填空题 → 3 个候选互相验证
        if any(k in domain for k in ("choice", "fill", "选择", "填空")):
            return max(default_count, 3)
        return default_count

    # ----------------------------------------------------------
    # 初始求解（蓝图分解 + 领域提示）
    # ----------------------------------------------------------
    def _generate_initial(self, ctx: TaskContext, count: int = None) -> None:
        count = count or self.config.policy_sample_times
        # 领域自适应候选数：证明题少生成，计算题多生成
        count = self._adaptive_count(ctx, count)

        if self.config.use_blueprint:
            system_prompt = get_policy_system(use_blueprint=True)
            domain_hint = get_domain_hint(ctx.domain) if ctx.domain else ""
            user_content = build_blueprint_user_message(ctx.problem, domain_hint)
        else:
            system_prompt = get_policy_system(use_blueprint=False)
            user_content = ctx.problem
            if ctx.domain:
                user_content = get_domain_hint(ctx.domain) + "\n" + ctx.problem

        base_cid = len(ctx.candidates)
        # 温度分层：不同候选使用不同温度以增加多样性
        _STRATIFIED_TEMPS = [0.1, 0.3, 0.5]

        def _make_one(i: int):
            cid = base_cid + i
            # 温度分层：按索引轮转取值（count>=3 时生效）
            base_temp = _STRATIFIED_TEMPS[i % len(_STRATIFIED_TEMPS)] if count >= 3 else self.config.policy_temperature
            # 候选 2+ 追加微扰动提示，引导不同解题思路
            _perturb_hints = [
                "",  # 候选 0: 无扰动
                "\n请特别注意计算过程中的每一步细节，确保数值精确。",  # 候选 1
                "\n如果可以，尝试用另一种方法重新审视这个问题。",  # 候选 2
            ]

            # 最多重试 3 次（原始请求 + 2 次重试），避免空响应/拒绝回答
            for retry in range(3):
                current_temp = base_temp
                current_system = system_prompt
                # 如果是拒绝回答后的重试，用强化提示词和更高温度
                if retry > 0:
                    current_system = _REINFORCED_SYSTEM
                    current_temp = max(self.config.policy_temperature, 0.7) + 0.1 * retry

                resp = self.llm(
                    ctx,
                    [
                        {"role": "system", "content": current_system},
                        {"role": "user",
                         "content": user_content + (_perturb_hints[i % len(_perturb_hints)] if retry == 0 else "")},
                    ],
                    current_temp,
                    self.config.policy_max_tokens,
                )
                # 空响应 -> 重试
                if resp is None or not resp.strip():
                    if retry < 2:
                        logger.warning("Candidate %d empty response (retry %d/2)", cid, retry + 1)
                        time.sleep(1)
                    continue
                # 幻觉检测
                hallu = detect_hallucination(resp)
                if hallu:
                    logger.warning("Candidate %d hallucination detected: %s", cid,
                                   ", ".join(f"{h[0]}({h[1]:.0%})" for h in hallu))
                    # 42 兜底 → 尝试重试
                    if any("42" in h[0] for h in hallu) and retry < 2:
                        logger.warning("Candidate %d 42-dodge, retry", cid)
                        time.sleep(1)
                        continue
                # 截断检测 → 记录但不拒绝（后续由 orchestrator 续写）
                if detect_truncated(resp):
                    logger.info("Candidate %d truncated; will attempt completion", cid)
                # 拒绝回答 -> 重试
                if _is_refusal(resp):
                    if retry < 2:
                        logger.warning("Candidate %d refused to answer (retry %d/2)", cid, retry + 1)
                        time.sleep(1)
                    continue
                # 有效回答
                return cid, resp, False
            # 全部重试失败，返回最后一次响应
            return cid, resp, True

        # 并行生成候选（用线程池提高吞吐，限制最大并发防止 API 过载）
        results = []
        max_workers = min(count, 6)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_make_one, i): i for i in range(count)}
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda x: x[0])

        for cid, resp, is_fallback in results:
            if resp is None or (is_fallback and _is_refusal(resp)):
                # 预算不足 / 调用失败 / 始终拒绝：占位候选
                ctx.candidates.append(Candidate(
                    id=cid, answer="", reasoning="[生成失败] 调用受限或模型拒绝回答"))
                logger.warning("Candidate %d generation failed/skipped", cid)
                continue
            answer = extract_final_answer(resp)
            # 如果提取不到答案但推理内容存在，取尾部作为答案
            if not answer and resp.strip():
                answer = smart_fallback_answer(resp)
            ctx.candidates.append(Candidate(
                id=cid,
                answer=answer,
                reasoning=resp,
                revised=False,
            ))
            logger.debug("Candidate %d generated (len=%d)", cid, len(resp))

        self.record(
            ctx, "solve",
            f"生成 {len(ctx.candidates)} 个候选解答 "
            f"(蓝图={self.config.use_blueprint}, 领域={ctx.domain})",
            count=len(ctx.candidates),
        )

    # ----------------------------------------------------------
    # 纠错重解（revise 模式）
    # ----------------------------------------------------------
    def _generate_revise(self, ctx: TaskContext) -> None:
        feedback_text = "\n".join(f"- {fb}" for fb in ctx.revise_feedback)
        count = self.config.revise_sample_times

        base_cid = len(ctx.candidates)

        def _make_one(i: int):
            cid = base_cid + i
            user_content = REVISE_USER_TEMPLATE.format(
                problem=ctx.problem, feedback=feedback_text)
            for retry in range(3):
                resp = self.llm(
                    ctx,
                    [
                        {"role": "system", "content": REVISE_SYSTEM},
                        {"role": "user", "content": user_content},
                    ],
                    self.config.policy_temperature,
                    self.config.policy_max_tokens,
                )
                if resp is not None and resp.strip():
                    # 幻觉/拒绝检测（与 _generate_initial 一致）
                    hallu = detect_hallucination(resp)
                    if any("42" in h[0] for h in hallu) and retry < 2:
                        logger.warning("Revise %d 42-dodge (retry %d/2)", cid, retry + 1)
                        time.sleep(1)
                        continue
                    if _is_refusal(resp) and retry < 2:
                        logger.warning("Revise %d refused (retry %d/2)", cid, retry + 1)
                        time.sleep(1)
                        continue
                    if detect_truncated(resp):
                        logger.info("Revise %d truncated; will attempt completion", cid)
                    return cid, resp
                if retry < 2:
                    logger.warning("Revise candidate %d empty response (retry %d/2)", cid, retry + 1)
                    time.sleep(1)
            return cid, resp

        # 并行生成修正候选
        results = []
        max_workers = min(count, 6)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_make_one, i): i for i in range(count)}
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda x: x[0])

        for cid, resp in results:
            if resp is None:
                ctx.candidates.append(Candidate(
                    id=cid, answer="", reasoning="[重解失败] 调用受限"))
                logger.warning("Revise candidate %d failed/skipped", cid)
                continue
            ctx.candidates.append(Candidate(
                id=cid,
                answer=extract_final_answer(resp),
                reasoning=resp,
                revised=True,
            ))

        self.record(
            ctx, "revise",
            f"纠错重解 第{ctx.revise_round}轮：生成 {count} 个修正候选",
            round=ctx.revise_round,
        )

    # ----------------------------------------------------------
    # 兜底直接求解（所有候选都失败时的 last-resort）
    # ----------------------------------------------------------
    def direct_solve(self, ctx: TaskContext) -> str:
        """
        用最简提示词直接求解（跳过蓝图分解和领域提示），
        要求模型必须输出【最终答案】。适用于所有多智能体候选均失败时兜底。
        返回最终答案字符串。
        """
        direct_system = _REINFORCED_SYSTEM + "\n\n请直接在【最终答案】中给出答案，不要省略任何步骤。"
        user_content = f"请仔细求解以下数学问题，必须给出确定的答案。\n\n题目：\n{ctx.problem}"

        for attempt in range(3):
            try:
                resp = self.llm(
                    ctx,
                    [
                        {"role": "system", "content": direct_system},
                        {"role": "user", "content": user_content},
                    ],
                    0.1 if attempt == 0 else 0.4,   # 首次低温，重试时提高温度
                    8192,
                )
            except Exception:  # noqa: BLE001
                resp = None

            if resp and resp.strip() and not _is_refusal(resp):
                # 幻觉检测：42 兜底 → 重试
                hallu = detect_hallucination(resp)
                if any("42" in h[0] for h in hallu) and attempt < 2:
                    logger.warning("Direct solve %d 42-dodge (retry)", attempt + 1)
                    time.sleep(1)
                    continue
                # 截断检测 → 要求模型补充
                if detect_truncated(resp):
                    logger.warning("Direct solve %d truncated → retry with continuation prompt", attempt + 1)
                    if attempt < 2:
                        continuation = (
                            direct_system + "\n\n上一轮回答被截断，请继续完成推理并确保输出完整的【最终答案】。"
                        )
                        user_content = (
                            f"上一轮你的回答被截断在：{resp[-200:]}\n\n"
                            f"请从截断处续写，给出完整的最终答案。原题目：\n{ctx.problem}"
                        )
                        self.record(ctx, "direct_solve", f"截断重试 (attempt {attempt + 2})")
                        continue
                answer = extract_final_answer(resp)
                if answer:
                    self.record(ctx, "direct_solve", f"兜底直接求解成功 (attempt {attempt + 1})")
                    return answer
                # 提取失败，取全文作为答案
                self.record(ctx, "direct_solve",
                           f"兜底求解成功但提取失败，使用全文 (attempt {attempt + 1})")
                return smart_fallback_answer(resp)
            logger.warning("Direct solve attempt %d/3 returned empty or refused", attempt + 1)
            time.sleep(1)

        self.record(ctx, "direct_solve", "兜底直接求解失败")
        return ""

    # ----------------------------------------------------------
    # 答案完整性检查与续写
    # ----------------------------------------------------------
    def is_answer_complete(self, reasoning: str, answer: str) -> bool:
        """
        检查推理是否完整（未被截断、有明确结论）。
        返回 True 表示完整，False 表示可能不完整。
        """
        if not reasoning or not reasoning.strip():
            return False
        text = reasoning.strip()
        # 1) 推理过短 → 可能不完整
        if len(text) < 400:
            # 有明确答案 → 仍然算完整
            if answer and len(answer) > 3 and not _is_refusal(text):
                return True
            return False
        # 2) 末尾是否完整结束
        tail = text[-200:]
        complete_endings = re.compile(
            r"([。！？\.!\?\)）】」』\"'']\s*$|\\boxed\{.+\}\s*$|"
            r"最终答案|【最终答案】|答案为|故选|因此|综上)",
        )
        if complete_endings.search(tail):
            return True
        # 3) 末尾是否像被截断（以逗号/and/or/且/并结尾）
        truncation_hints = re.compile(
            r"([,，\s]$|and\s*$|or\s*$|且\s*$|并\s*$|然后\s*$|"
            r"还有\s*$|此外\s*$|另外\s*$|以及\s*$)",
        )
        if truncation_hints.search(text[-50:]):
            logger.debug("Answer appears truncated at end")
            return False
        # 4) 最后一行特别短且无结束标点 → 可能被截断
        last_line = text.split("\n")[-1].strip()
        if last_line and len(last_line) < 30 and not re.search(r"[。！？\.!\?\)）】」』]", last_line):
            # 但如果包含答案关键词 / LaTeX，可能正常
            if re.search(r"\$|答案|boxed|[=＝]", last_line):
                return True
            return False
        return True

    def complete_answer(self, ctx: TaskContext, candidate: Candidate) -> Candidate:
        """
        对不完整的推理进行续写。
        将截断的推理发回模型，要求其继续完成，然后合并。
        """
        if not candidate.reasoning or not candidate.reasoning.strip():
            return candidate

        reasoning = candidate.reasoning.strip()
        # 取尾部 1500 字符作为续写上下文
        context_tail = reasoning[-1500:]

        continue_prompt = (
            "你的推理在下面中断了，请直接从断点处继续完成推理，"
            "并在最后给出【最终答案】。不要重复之前的内容，直接接着写：\n\n"
            f"--- 断点 ---\n{context_tail}\n--- 请继续 ---"
        )

        for attempt in range(2):
            try:
                continuation = self.llm(
                    ctx,
                    [
                        {"role": "system",
                         "content": "你是数学解题专家，正在完成一段被中断的推理。请从断点处直接继续，"
                                    "完成剩下的推导过程，并给出【最终答案】。"},
                        {"role": "user", "content": continue_prompt},
                    ],
                    0.2,
                    4096,
                )
            except Exception:
                continuation = None

            if continuation and continuation.strip():
                # 合并推理
                full_reasoning = reasoning + "\n\n[续写]\n" + continuation.strip()
                new_answer = extract_final_answer(full_reasoning)
                if not new_answer:
                    new_answer = smart_fallback_answer(continuation)
                self.record(ctx, "complete",
                           f"答案续写成功 (attempt {attempt + 1})")
                return Candidate(
                    id=candidate.id,
                    answer=new_answer,
                    reasoning=full_reasoning,
                    revised=candidate.revised,
                )
            logger.warning("Answer completion attempt %d returned empty", attempt + 1)
            time.sleep(0.5)

        self.record(ctx, "complete", "答案续写失败，使用原始答案")
        return candidate
