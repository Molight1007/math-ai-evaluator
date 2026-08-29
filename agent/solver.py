from __future__ import annotations
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
    detect_template_leak,
    LemmaRepo,
)
from prompts.policy import (
    POLICY_SYSTEM,
    get_policy_system,
    get_domain_hint,
    build_blueprint_user_message,
)
from prompts.revise import REVISE_SYSTEM, REVISE_USER_TEMPLATE
from prompts.proof import PROOF_SYSTEM, PROOF_TEMPLATE
from utils.extract import (
    extract_final_answer,
    smart_fallback_answer,
    rescue_final_answer,
    is_valid_final_answer,
)
from utils.prefill import prefill_messages, stitch

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

# v3 P3：视角采样提示库（替代纯温度分层）。
# 同模型、同题、不同解题路径 → 错误模式去相关（弱独立采样）。
_VIEW_HINTS: list[tuple[str, str]] = [
    ("direct",      ""),                                          # 视角0：直接求解
    ("substitute",  "\n提示：考虑换元/设未知数/参数化，先化简再求解。"),  # 视角1：换元
    ("geometric",   "\n提示：尝试从几何/图形/构造的角度重新理解问题。"),  # 视角2：几何
    ("algebraic",   "\n提示：尝试代数变形/因式分解/对称性简化。"),        # 视角3：代数
    ("backward",    "\n提示：尝试从目标倒推，先确定结论形式再找路径。"),  # 视角4：倒推
]


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


def _needs_followup(content: str) -> bool:
    """检测是否需要追问中文答案。
    注意：Intern-S 模型天然倾向英文输出，但数学答案（数字/表达式）无所谓语言。
    目前暂时禁用追问机制，避免无限循环。英文答案同样可以通过正则提取。"""
    return False  # 禁用：Intern-S 英文输出不影响答案提取


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
        # 证明题 → 减少候选（精确推演比广度采样更重要）
        proof_keywords = ["proof", "prove", "证明", "证明题", "不等式证明", "几何证明"]
        if any(k in domain for k in proof_keywords):
            return max(1, default_count // 3)
        # P0-4 修复：不再为高难度题提高候选数——3 候选 × 3 重试曾耗尽单题
        # 300s 预算导致 45 error。保持 default_count（配置=2），省预算保产出。
        hard_signals = [
            problem_len > 500,
            any(k in domain for k in ("differential_equation", "微分方程")),
            any(k in domain for k in ("series", "级数")),
            any(k in domain for k in ("integral", "不定积分", "indefinite_integral",
                                        "重积分", "曲线积分", "曲面积分")),
        ]
        if sum(hard_signals) >= 2:
            return default_count
        if any(k in domain for k in ("choice", "fill", "选择", "填空")):
            return default_count
        return default_count

    @staticmethod
    def _adaptive_max_tokens(ctx: TaskContext, base_tokens: int) -> int:
        """P0-4/5 修复：按题目领域/长度分级 max_tokens，杜绝截断丢答案。

        与 ICMA 高分样例对齐：简单题 8192 / 中等 base / 难题 24576。
        base_tokens（policy_max_tokens）默认 24576，难题上探 24576，
        cap 同步上调（user_agent max_tokens_cap=24576），不再被二次裁剪。
        """
        domain = (ctx.domain or "").lower()
        problem_len = len(ctx.problem or "")
        # 简单题（选择/填空/算术）→ 中小预算，快速出答案
        simple_signals = any(k in domain for k in ("choice", "fill", "选择", "填空", "arithmetic", "算术"))
        if simple_signals:
            return min(base_tokens, 8192)
        # 难题（证明/级数/积分/方程/长题）→ 大预算 24576（ICMA 对齐：上限而非实际用量，
        # 实测模型仅用 3-7K token，24576 保住贴上限的奥赛题；超时由压缩 prefill 兜底）
        hard_signals = any(k in domain for k in (
            "proof", "prove", "证明", "series", "级数",
            "integral", "积分", "equation", "方程", "derivative", "微分",
        )) or problem_len > 500
        if hard_signals:
            return max(base_tokens, 24576)
        return base_tokens

    def _collect_lemma_context(self, ctx: TaskContext) -> str:
        """收集已验证的子结论（引理库），作为解题上下文注入。"""
        if not getattr(self.config, 'use_lemma_accumulation', False):
            return ""
        repo = getattr(ctx, 'lemma_repo', None)
        if repo is None:
            return ""
        # P2：兼容 LemmaRepo（结构化）与旧式 list[str]
        if isinstance(repo, LemmaRepo):
            if len(repo) == 0:
                return ""
            recent = repo.query(ctx.problem, limit=5)
        else:
            lemmas = list(repo)
            if not lemmas:
                return ""
            recent = lemmas[-5:]  # 最多注入 5 条
        return "【已验证的中间结论】\n" + "\n".join(f"- {l}" for l in recent) + "\n\n"

    # ----------------------------------------------------------
    # 证明题专用通道
    # ----------------------------------------------------------
    def _generate_proof(self, ctx: TaskContext) -> Candidate | None:
        """使用证明题专用提示词生成分步编号的完整证明。"""
        from .base import Candidate
        conditions = "见题目"
        strategy_hint = "选择最合适的证明方法（直接证明/反证法/归纳法/构造法）"
        user = PROOF_TEMPLATE.format(
            problem=ctx.problem, conditions=conditions, strategy_hint=strategy_hint
        )
        # v2.4.1：证明通道同样走 prefill（完整 CoT 在本环境必然超时）
        raw = self._compressed_solve(
            ctx, PROOF_SYSTEM, user,
            temperature=0.3, max_tokens=self.config.max_answer_tokens,
        )
        if not raw or len(raw) < 30:
            return None
        answer = extract_final_answer(raw)
        if not answer or len(answer) > 300:
            answer = rescue_final_answer(raw)[0]
        if not answer:
            answer = smart_fallback_answer(raw)
        if not is_valid_final_answer(answer) and len(raw) > 0:
            answer = raw[-500:]
        cid = len(ctx.candidates)
        cand = Candidate(id=cid, reasoning=raw, answer=answer)

        # 队友 Lean 改造3（合并自 origin/main）：证明题通道接入 Lean 形式化验证
        # （默认关闭 enable_lean_verify，保守兼容）。开启时用 LeanBridge 验证推理，
        # 与 LLM 逐步骤验证结果融合写入 ctx.revise_feedback，驱动既有 _generate_revise 闭环。
        if getattr(self.config, 'enable_lean_verify', False):
            self._lean_verify_and_feedback(ctx, cand)
        return cand

    def _lean_verify_and_feedback(self, ctx: TaskContext, cand: Candidate) -> None:
        """调用 LeanBridge 验证推理，把 Lean 结果融合进 ctx.revise_feedback。

        - Lean 判定 proof_invalid 且含修正建议 → 直接作为 revise 反馈，驱动闭环；
        - Lean 环境缺失 / 超时 / 纯翻译错误（unknown）→ 不污染 revise 反馈，
          交由既有 LLM 逐步骤验证兜底。
        """
        try:
            from .lean_bridge import LeanBridge
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Solver] LeanBridge 导入失败，跳过 Lean 验证: %s", exc)
            return
        try:
            bridge = LeanBridge(
                self.client, config=self.config,
                budget=getattr(ctx, 'budget', None))
            timeout = float(getattr(self.config, 'lean_timeout', 60.0) or 60.0)
            report = bridge.verify(ctx.problem, cand.reasoning,
                                   domain=ctx.domain or "", timeout=timeout)
            if report is None:
                return
            if not report.is_valid() and report.suggestion:
                ctx.revise_feedback.append(report.suggestion)
                self.record(ctx, "lean_verify",
                            f"Lean 验证反馈: {report.suggestion[:80]}")
        except Exception as e:  # noqa: BLE001
            logger.warning("[Solver] Lean 验证异常，跳过（由 LLM 兜底）: %s", e)

    def _compressed_solve(self, ctx: TaskContext, system: str, user: str,
                          temperature: float = 0.1,
                          max_tokens: int = 8192) -> str | None:
        """ICMA 同款压缩求解：prefill 种子「## 问题分析」抑制 CoT，快速产出答案。

        v2.4.1 起为本环境**主求解路径**：诊断实测完整 CoT 单次调用 >200s 不返回
        （780s 仍读超时），而 prefill 压缩求解 36.7s 即返回 ~2000 tokens 结构化解答。
        prefill 答案前置：即使输出被截断，也只损失思考、不损失答案。
        """
        try:
            msgs = prefill_messages(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "## 问题分析\n",
            )
            resp = self.llm(ctx, msgs, temperature, max_tokens)
            if resp:
                return stitch("## 问题分析\n", resp)
            # 空响应 → 简化直答重试（2026-08-30，对弱模型鲁棒）：
            # 复杂四章节 prompt 在弱模型/部分后端下偶发空响应（=必 0 分），
            # 换成"直接求解输出答案"的极简提示重试一次，能救回大量空分题。
            logger.warning("[Solver] 压缩求解空响应，简化直答重试")
            try:
                simple_msgs = [
                    {"role": "system",
                     "content": "你是一个数学解题助手。请求解题目并直接输出最终答案（可含简要步骤）。"},
                    {"role": "user", "content": user},
                ]
                resp2 = self.llm(ctx, simple_msgs, max(temperature, 0.2), max_tokens)
                if resp2 and resp2.strip():
                    return resp2.strip()
            except Exception as e2:  # noqa: BLE001
                logger.warning("[Solver] 简化直答重试失败: %s", str(e2)[:120])
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("Compressed solve failed: %s", e)
            return None

    # ----------------------------------------------------------
    # 初始求解（蓝图分解 + 领域提示）
    # ----------------------------------------------------------
    def _generate_initial(self, ctx: TaskContext, count: int = None) -> None:
        # B6：PaperPacer 运行时收紧候选数（如应急模式）写入 ctx.state，此处读取生效值
        if count is None:
            count = (ctx.state.sample_times
                     if ctx.state and ctx.state.sample_times
                     else self.config.policy_sample_times)
        # 领域自适应候选数
        count = self._adaptive_count(ctx, count)

        # 证明题专用通道（若启用）
        is_proof = False
        proof_keywords = ["proof", "prove", "证明", "证明题", "不等式证明", "几何证明"]
        if any(k in (ctx.domain or "").lower() for k in proof_keywords):
            is_proof = True
        if is_proof and getattr(self.config, 'use_proof_channel', False):
            proof_cand = self._generate_proof(ctx)
            if proof_cand:
                ctx.candidates.append(proof_cand)
                self.record(ctx, "generate", f"证明题专用通道生成候选 #{proof_cand.id}")
                return
            self.record(ctx, "generate", "证明题专用通道未产出有效候选，回退通用求解")

        # lemma 上下文注入
        lemma_ctx = self._collect_lemma_context(ctx)

        if getattr(self.config, 'use_sketch', False):
            # #26：先出轻量解题大纲（sketch）再求解——引导组织思路但不占思维流
            system_prompt = get_policy_system(use_sketch=True)
            user_content = ctx.problem
            if ctx.domain:
                user_content = get_domain_hint(ctx.domain) + "\n" + ctx.problem
        elif self.config.use_blueprint:
            system_prompt = get_policy_system(use_blueprint=True)
            domain_hint = get_domain_hint(ctx.domain) if ctx.domain else ""
            user_content = build_blueprint_user_message(ctx.problem, domain_hint)
        else:
            system_prompt = get_policy_system(use_blueprint=False)
            user_content = ctx.problem
            if ctx.domain:
                user_content = get_domain_hint(ctx.domain) + "\n" + ctx.problem

        # 注入 lemma 上下文
        if lemma_ctx:
            system_prompt = lemma_ctx + system_prompt

        # ICMA 对齐（v2.4.0）：末尾追加章节输出引导。系统 prompt 已要求四章节
        # 结构化输出并禁止思考过程，这里仅强调【最终答案】章节必须明确，不引导自由 CoT。
        _ANSWER_GUIDE = (
            "\n\n请严格按系统提示的四章节格式输出完整解答，"
            "确保【最终答案】章节给出明确、简洁的最终结论。"
        )
        user_content = user_content + _ANSWER_GUIDE

        base_cid = len(ctx.candidates)
        _STRATIFIED_TEMPS = [0.1, 0.3, 0.5]
        # v3 P3：视角采样开关（默认关，A/B 验证后开）
        use_views = bool(getattr(self.config, 'use_view_sampling', False))

        def _make_one(i: int):
            cid = base_cid + i
            if use_views:
                # 视角采样：视角轮转 + 小温度变化（错误模式去相关）
                view_name, view_hint = _VIEW_HINTS[i % len(_VIEW_HINTS)]
                base_temp = 0.1 + 0.1 * (i % 3)
            else:
                view_name, view_hint = "", ""
                # 温度分层：按索引轮转取值（count>=3 时生效）
                base_temp = _STRATIFIED_TEMPS[i % len(_STRATIFIED_TEMPS)] if count >= 3 else self.config.policy_temperature
            # 候选 2+ 追加微扰动提示，引导不同解题思路
            _perturb_hints = [
                "",  # 候选 0: 无扰动
                "\n请特别注意计算过程中的每一步细节，确保数值精确。",  # 候选 1
                "\n如果可以，尝试用另一种方法重新审视这个问题。",  # 候选 2
            ]

            # v2.4.1 主路径：prefill 压缩求解（诊断实测 37s 返回，答案前置不受截断影响）。
            # 本环境完整 CoT >200s 不返回（780s 仍读超时），prefill 是唯一保证
            # 300s 单题预算内出答案的路径。最多重试 2 次（原始 + 1 次重试）。
            resp = None
            template_leak_retry = False  # 标记是否为模板泄露后的重试
            for retry in range(2):
                current_temp = base_temp
                current_system = system_prompt
                # 模板泄露重试时使用简化prompt（不覆盖）
                if template_leak_retry:
                    current_user = f"请直接解答以下数学问题，只输出解答过程和最终答案：\n\n{ctx.problem}"
                    current_system = _REINFORCED_SYSTEM
                    current_temp = max(self.config.policy_temperature, 0.7) + 0.1 * retry
                    template_leak_retry = False
                else:
                    if use_views:
                        hint = view_hint if retry == 0 else ""
                    else:
                        hint = _perturb_hints[i % len(_perturb_hints)] if retry == 0 else ""
                    current_user = user_content + hint
                    if retry > 0:
                        current_system = _REINFORCED_SYSTEM
                        current_temp = max(self.config.policy_temperature, 0.7) + 0.1 * retry

                # 主求解 = prefill（无完整 CoT 尝试；prefill 模式下模型输出克制，
                # max_tokens 上限 16384 已远超实测用量 ~2K token）
                resp = self._compressed_solve(
                    ctx, current_system, current_user,
                    temperature=current_temp,
                    max_tokens=min(
                        self._adaptive_max_tokens(ctx, self.config.policy_max_tokens),
                        16384,
                    ),
                )
                # 空响应 -> 重试
                if resp is None or not resp.strip():
                    if retry < 1:
                        logger.warning("Candidate %d empty response (retry %d/1)", cid, retry + 1)
                        time.sleep(1)
                    continue
                # 模板泄露检测 → 重试
                if detect_template_leak(resp):
                    if retry < 1:
                        logger.warning("Candidate %d template leak (retry %d/1)", cid, retry + 1)
                        template_leak_retry = True
                        time.sleep(0.5)
                        continue
                # 英文think泄露 → 追问中文答案
                if _needs_followup(resp) and retry < 1:
                    logger.warning("Candidate %d English think leak → followup", cid)
                    # v2.4.1：followup 也走 prefill，防止完整 CoT 超时
                    followup_resp = self._compressed_solve(
                        ctx,
                        _REINFORCED_SYSTEM,
                        f"请用中文重新表达你的解答过程，并给出【最终答案】。\n\n上轮回答：\n{resp[-1500:]}\n\n请用中文写出完整解答和最终答案：",
                        temperature=0.3,
                        max_tokens=min(
                            self._adaptive_max_tokens(ctx, self.config.policy_max_tokens),
                            16384,
                        ),
                    )
                    if followup_resp and followup_resp.strip():
                        if not detect_template_leak(followup_resp) and not _needs_followup(followup_resp):
                            resp = followup_resp
                            break  # 追问成功，跳出重试循环
                    time.sleep(0.5)
                    continue
                # 幻觉检测
                hallu = detect_hallucination(resp)
                if hallu:
                    logger.warning("Candidate %d hallucination detected: %s", cid,
                                   ", ".join(f"{h[0]}({h[1]:.0%})" for h in hallu))
                    # 42 兜底 → 尝试重试
                    if any("42" in h[0] for h in hallu) and retry < 1:
                        logger.warning("Candidate %d 42-dodge, retry", cid)
                        time.sleep(1)
                        continue
                # 截断检测 → 记录但不拒绝（后续由 orchestrator 续写）
                if detect_truncated(resp):
                    logger.info("Candidate %d truncated; will attempt completion", cid)
                # 拒绝回答 -> 重试
                if _is_refusal(resp):
                    if retry < 1:
                        logger.warning("Candidate %d refused to answer (retry %d/1)", cid, retry + 1)
                        time.sleep(1)
                    continue
                # 有效回答
                return cid, resp, False
            # 全部重试失败，返回最后一次响应
            return cid, resp, True

        # 并行生成候选（用线程池提高吞吐，限制最大并发防止 API 过载）
        # P0-4 修复：并行度 6→2，降低并发 API 超时/限流风险
        if use_views:
            view_names = [v[0] for v in _VIEW_HINTS[:count]]
            self.record(ctx, "solve", f"视角采样开启: {view_names}")
        results = []
        max_workers = min(count, 2)
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
            # 如果提取不到答案 / 答案过长（>300字符大概率是推理文本），
            # 先试 rescue 兜底（嵌套 boxed / 中段强模式结论），再取尾部
            if not answer or len(answer) > 300 and resp.strip():
                rescued = rescue_final_answer(resp)[0]
                if rescued:
                    answer = rescued
                else:
                    fallback = smart_fallback_answer(resp)
                    if fallback and (not answer or len(fallback) < len(answer)):
                        answer = fallback
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
                # v2.4.1：revise 也走 prefill（完整 CoT 在本环境必然超时）
                resp = self._compressed_solve(
                    ctx, REVISE_SYSTEM, user_content,
                    temperature=self.config.policy_temperature,
                    max_tokens=min(
                        self._adaptive_max_tokens(ctx, self.config.policy_max_tokens),
                        16384,
                    ),
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
            answer = extract_final_answer(resp)
            if not answer or len(answer) > 300:
                answer = rescue_final_answer(resp)[0]
            if not answer:
                answer = smart_fallback_answer(resp)
            ctx.candidates.append(Candidate(
                id=cid,
                answer=answer,
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
        # P0-4 修复：兜底场景用 prefill 让答案前置——时间紧时优先保答案而非推理
        base_msgs = [
            {"role": "system", "content": direct_system},
            {"role": "user", "content": user_content},
        ]

        for attempt in range(3):
            try:
                resp = self.llm(
                    ctx,
                    prefill_messages(base_msgs, "最终答案："),
                    0.1 if attempt == 0 else 0.4,   # 首次低温，重试时提高温度
                    8192,
                )
                if resp:
                    resp = stitch("最终答案：", resp)
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
                # 常规提取失败 → rescue 兜底（嵌套 boxed / 中段强模式）
                rescued = rescue_final_answer(resp)[0]
                if rescued:
                    self.record(ctx, "direct_solve",
                               f"兜底求解成功但常规提取失败，rescue 截取 (attempt {attempt + 1})")
                    return rescued
                # 仍失败，取全文作为答案
                self.record(ctx, "direct_solve",
                           f"兜底求解成功但提取失败，使用全文 (attempt {attempt + 1})")
                return smart_fallback_answer(resp)
            logger.warning("Direct solve attempt %d/3 returned empty or refused", attempt + 1)
            time.sleep(1)

        self.record(ctx, "direct_solve", "兜底直接求解失败")
        return ""

    # ----------------------------------------------------------
    # 截断候选批量续写（P0-3）
    # ----------------------------------------------------------
    def complete_truncated_candidates(self, ctx: TaskContext, max_count: int = 1) -> int:
        """对截断的候选发起续写，把完成的候选放回列表。返回续写成功数量。

        P0-4 修复：默认只续写"最有希望恢复"的 1 个截断候选（reasoning 最长的
        即信息最全、最接近完成的），避免 3 候选 × 多轮续写耗尽单题预算 → 45 error。
        修复：此前 orchestrator 只在日志里记录 truncated，从不真正续写，
        导致 65% 被截断的候选答案丢失 → invalid。
        """
        truncated = [c for c in ctx.candidates
                     if c.reasoning and c.reasoning.strip() and detect_truncated(c.reasoning)]
        if not truncated:
            return 0
        # 选信息最全的截断候选优先续写
        truncated.sort(key=lambda c: len(c.reasoning), reverse=True)
        chosen = truncated[:max_count]

        completed = 0
        new_list = []
        for c in ctx.candidates:
            if c not in chosen:
                new_list.append(c)
                continue
            # 预算允许才续写
            if ctx.budget is None or ctx.budget.can_spend(1):
                new_c = self.complete_answer(ctx, c)
                if new_c is not c and new_c.answer and len(new_c.answer) > 1:
                    new_list.append(new_c)
                    completed += 1
                    self.record(ctx, "complete", f"候选 #{c.id} 截断续写成功")
                    continue
            new_list.append(c)
        ctx.candidates = new_list
        return completed

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

    _COMPLETE_SYS = (
        "你是数学解题专家，正在完成一段被中断的推理。"
        "请直接续写剩下的推导并给出最终答案。"
    )
    _ANSWER_PREFIX_SYS = (
        "你是数学解题专家。根据下面被截断的推理，直接给出最终答案。"
        "只输出答案本身（数值、表达式或选项字母），不要解释、不要推理过程。"
    )

    def complete_answer(self, ctx: TaskContext, candidate: Candidate) -> Candidate:
        """
        对不完整的推理进行续写。

        P0-2/P0-3 强化：先尝试续写推理；若仍提取不到答案，
        再用【答案前置】紧急重问（prefill 精神：答案在前，截断不丢）。
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

        # P0-4 修复：续写仅 1 次（2+1→1+1），压缩调用链防超时
        for attempt in range(1):
            try:
                # v2.4.1：续写也走 prefill（断点种子抑制 CoT，防 4096 token 超时）
                continuation = self.llm(
                    ctx,
                    prefill_messages(
                        [
                            {"role": "system", "content": self._COMPLETE_SYS},
                            {"role": "user", "content": continue_prompt},
                        ],
                        "--- 请继续 ---\n",
                    ),
                    0.2,
                    4096,
                )
                if continuation:
                    continuation = stitch("--- 请继续 ---\n", continuation)
            except Exception:
                continuation = None

            if continuation and continuation.strip():
                # 合并推理
                full_reasoning = reasoning + "\n\n[续写]\n" + continuation.strip()
                new_answer = extract_final_answer(full_reasoning)
                if not new_answer:
                    new_answer = rescue_final_answer(full_reasoning)[0]
                if not new_answer:
                    new_answer = smart_fallback_answer(continuation)
                if new_answer:
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

        # 答案前置紧急重问（P0-4：正式 prefill）：即使推理不全，也要把答案抢救出来。
        # 用 assistant 前缀"最终答案："抑制 CoT 开启，答案从开头生成——截断不丢答案。
        try:
            _prefill_msgs = prefill_messages(
                [
                    {"role": "system", "content": self._ANSWER_PREFIX_SYS},
                    {"role": "user",
                     "content": f"被截断的推理片段：\n{context_tail}"},
                ],
                "最终答案：",
            )
            direct = self.llm(ctx, _prefill_msgs, 0.0, 1024)
            if direct:
                direct = stitch("最终答案：", direct)
            if direct and direct.strip():
                direct_ans = smart_fallback_answer(direct)
                if direct_ans:
                    self.record(ctx, "complete", "答案前置重问成功")
                    return Candidate(
                        id=candidate.id,
                        answer=direct_ans,
                        reasoning=reasoning + "\n\n[答案重问]\n" + direct.strip(),
                        revised=candidate.revised,
                    )
        except Exception as e:
            logger.warning("Answer prefill retry failed: %s", e)

        self.record(ctx, "complete", "答案续写失败，使用原始答案")
        return candidate
