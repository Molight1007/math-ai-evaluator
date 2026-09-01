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
)
from prompts.policy import (
    POLICY_SYSTEM,
    SELF_IMPROVE_USER,
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
        # 难题深度通道：deep 档保持多候选（4 候选，不做缩减）
        if getattr(ctx, 'tier', 'standard') == 'deep':
            return default_count
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

    def _use_lemma(self, ctx: TaskContext) -> bool:
        """判断当前题是否启用 lemma 累积（按领域路由，2026-08-29）。

        A/B 实测：lemma 全领域开 = 净 0.0pp（代数/组合被噪声拖累，数论 +23pp）。
        因此默认按领域路由：lemma_domains 命中才注入，把数论的收益变成
        确定收益，同时避免拖累其他领域。
        """
        if not getattr(self.config, 'use_lemma_accumulation', False):
            return False
        domains = list(getattr(self.config, 'lemma_domains', []) or [])
        if not domains:
            return True  # 空列表 = 全领域开启
        d = str(getattr(ctx, 'domain', '') or '')
        return any(k in d for k in domains)

    def _collect_lemma_context(self, ctx: TaskContext) -> str:
        """收集已验证的子结论（引理库），作为解题上下文注入。"""
        if not self._use_lemma(ctx):
            return ""
        lemmas = getattr(ctx, 'lemma_repo', [])
        if not lemmas:
            return ""
        recent = lemmas[-5:]  # 最多注入 5 条
        return "【已验证的中间结论】\n" + "\n".join(f"- {l}" for l in recent) + "\n\n"

    # ----------------------------------------------------------
    # 证明题专用通道
    # ----------------------------------------------------------
    # ----------------------------------------------------------
    # #51 答案定型：疑似推理文本的定向重问
    # ----------------------------------------------------------
    # 判定阈值取 60：基线 45 题中，答案长度 >60 的 5 条经人工核对均为
    # "整段计算步骤"或"结论句"，而非答案本身。
    _SUSPICIOUS_ANSWER_LEN = 60

    # 叙述性措辞：出现在答案里说明抽到的是句子而非结论。
    # 刻意不含"是/为"等通用系动词，避免误伤 "x = 2" 这类合法答案。
    _NARRATIVE_PAT = (
        r"因此|所以|由于|于是|综上|可得|由此|进而|注意到|显然",
        r"步骤\s*\d", r"^第\s*[一二三四五六七八九十\d]+\s*[步点、]",
        r"其中|其[中次]|这里|我们|可以[看得]出|答案[是为]|故[，,]",
        r"\\sum|\\int|\\lim|\\prod|\\oint",
    )

    def _reask_final_answer(self, ctx: TaskContext, reasoning: str,
                            answer: str) -> str:
        """答案疑似推理文本时，向模型定向重问一次"仅输出最终答案"。

        只在**抽取结果不可信**时触发（空 / 超长 / 含多步推导痕迹），
        正常答案直接原样返回，不增加任何开销。

        失败一律返回原答案——兜底动作不能让情况变得更糟。
        """
        if not self._answer_looks_suspicious(answer):
            return answer
        try:
            # 只喂推理尾部，避免长上下文拖慢这次短调用
            tail = reasoning[-1200:] if len(reasoning) > 1200 else reasoning
            system = (
                "你是数学答案格式化助手。只输出最终答案，不要解释、不要推导、"
                "不要任何多余文字。"
            )
            user = (
                "下面是某题的解答过程（可能不完整）。\n\n"
                f"{tail}\n\n"
                "请只输出这道题的最终答案，满足：\n"
                "1) 用 \\boxed{...} 包裹，例如 \\boxed{42}\n"
                "2) 下一行给出不含公式标记的最简形式，例如：最简形式：42\n"
                "3) 不要输出推导过程、单位说明或任何解释性文字\n"
                "4) 若答案是多个值，用逗号分隔放在同一个 \\boxed{} 内"
            )
            raw = self._compressed_solve(
                ctx, system, user,
                temperature=0.0,
                max_tokens=int(getattr(self.config, 'answer_reask_max_tokens', 256)),
            )
            if not raw:
                return answer
            new_ans = extract_final_answer(raw)
            if not new_ans:
                return answer
            # 重问结果必须"比原来更像答案"才采纳
            if self._answer_looks_suspicious(new_ans):
                return answer
            self.record(ctx, "answer_reask",
                        f"答案疑似推理文本（{len(answer)} 字符），定向重问后收敛为 "
                        f"{len(new_ans)} 字符")
            return new_ans
        except Exception as exc:  # noqa: BLE001
            logger.debug("[solver] 答案定向重问失败，保留原答案: %s", str(exc)[:120])
            return answer

    @classmethod
    def _answer_looks_suspicious(cls, answer: str) -> bool:
        """判断抽取出的答案是否"疑似推理文本"而非答案本身。

        判定按「长度 → 句式 → 结构」三级，且刻意保守：
        **误判的代价是一次短调用**，但把合法答案判成可疑会导致重问，
        所以 `{1, 3, 5}`、`x = 2, y = 3` 这类列表/多值答案必须放过。
        """
        a = (answer or "").strip()
        if not a:
            return True
        # 1) 过长：答案是短语，不是段落
        if len(a) > cls._SUSPICIOUS_ANSWER_LEN:
            return True
        # 2) 成句：出现句号或推理连接词，说明抽到的是叙述而非结论
        if "。" in a or "．" in a:
            return True
        for pat in cls._NARRATIVE_PAT:
            if re.search(pat, a):
                return True
        # 3) 推导链：**链式等号** `a = b = c`（两个等号之间没有被逗号分隔）。
        #    用"中间无逗号"把推导链与并列赋值区分开：
        #      - "S = 1 + 2 + 3 = 6"  → 链式，是计算过程
        #      - "x = 2, y = 3"       → 并列，是合法的多值答案
        if re.search(r"=[^,，]*=", a):
            return True
        return False

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
        return Candidate(id=cid, reasoning=raw, answer=answer)

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
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("Compressed solve failed: %s", e)
            return None

    # ----------------------------------------------------------
    # 初始求解（蓝图分解 + 领域提示）
    # ----------------------------------------------------------
    def _generate_initial(self, ctx: TaskContext, count: int = None,
                          temperatures: list = None) -> None:
        """生成初始候选。

        参数:
            count: 候选数；None 时回退 config.policy_sample_times
                   （难题深度通道由 orchestrator 按档位传入）
            temperatures: 温度分层列表；None 时用默认 [0.1, 0.3, 0.5]
        """
        # 档位候选数：ctx.state.sample_times 优先（RunState 应急覆盖），config 兜底
        if count is None:
            if getattr(ctx.state, 'sample_times', None) is not None:
                count = ctx.state.sample_times
            else:
                tier_tbl = getattr(self.config, 'tier_sample_times', None)
                if tier_tbl:
                    count = tier_tbl.get(getattr(ctx, 'tier', 'standard'),
                                         self.config.policy_sample_times)
                else:
                    count = self.config.policy_sample_times
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

        if self.config.use_blueprint:
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
        #
        # 2026-08-30（#51 答案定型）：基线 45 题实测——**仅 7/45（15.6%）的推理里
        # 出现 \boxed{}**，5 题抽出的答案超过 60 字符（明显抽到了推理文本），
        # 且 `reference_matched` 精确匹配 45/45 全 False。本地宽松 LLM 判分能"看懂"，
        # 平台判分看不懂——这是「本地 46.7% vs 平台 20%」落差里可控性最高的一块。
        # 模型本身具备给出简洁答案的能力（#21 材料结论：模型可到 90 分），
        # 缺的是**强制定界**，故在提示词侧要求 \boxed{}，而非让抽取器去猜。
        _ANSWER_GUIDE = (
            "\n\n请严格按系统提示的四章节格式输出完整解答，"
            "确保【最终答案】章节给出明确、简洁的最终结论。"
        )
        if getattr(self.config, 'enable_answer_boxed', True):
            _ANSWER_GUIDE += (
                "\n【最终答案】章节中，最终结论必须且只能用 \\boxed{...} 包裹，"
                "并在其后另起一行给出不含任何公式标记的最简形式"
                "（例如：\\boxed{42}；最简形式：42）。"
                "\\boxed{} 内只放答案本身，不要放推导过程、单位说明或多余文字。"
            )
        user_content = user_content + _ANSWER_GUIDE

        # 题型差异化策略注入（v2.6）：
        #   选择题→选项逆推验证；判断题→不确定时合理猜测；
        #   证明题→逐步反复校验；解答题→附带答案结果检测；填空题→只输出结果。
        #
        # 2026-08-30（#45）：老师要求移除按题型分流、让 AI 按自身流程作答
        # （IMO 基本全为证明题，题型分支实测反而拉低证明题正确率）。
        # 此处改为 `enable_question_type_hint` 控制，**默认关闭**；需要 A/B
        # 对比或回归旧行为时置 True 即可，无需改代码。
        # 注：选择题的选项格式化属"输入信息补全"而非策略分流，故始终保留。
        if getattr(ctx, 'question_type', ''):
            from .question_type import get_question_type_hint, format_options
            if ctx.question_type == "选择题":
                opts = format_options(ctx.problem)
                if opts:
                    user_content = user_content + opts
            if getattr(self.config, 'enable_question_type_hint', False):
                qtype_hint = get_question_type_hint(ctx.question_type)
                if qtype_hint:
                    user_content = user_content + qtype_hint

        base_cid = len(ctx.candidates)
        if temperatures is None:
            tier_tbl = getattr(self.config, 'tier_temperatures', None)
            temperatures = (tier_tbl.get(getattr(ctx, 'tier', 'standard'), [0.1, 0.3, 0.5])
                            if tier_tbl else [0.1, 0.3, 0.5])
        _STRATIFIED_TEMPS = temperatures

        def _make_one(i: int):
            cid = base_cid + i
            # 温度分层：按索引轮转取值（count>=3 时生效；deep 档 4 温度 0.1/0.3/0.5/0.7）
            base_temp = _STRATIFIED_TEMPS[i % len(_STRATIFIED_TEMPS)] if count >= 3 else self.config.policy_temperature
            # 候选 2+ 追加微扰动提示，引导不同解题思路
            _perturb_hints = [
                "",  # 候选 0: 无扰动（直接求解）
                "\n请特别注意计算过程中的每一步细节，确保数值精确。",  # 候选 1: 精度
                "\n如果可以，尝试用另一种方法重新审视这个问题。",  # 候选 2: 换方法
                "\n请先列出解题关键思路与可能用到的定理/公式，再逐步求解。",  # 候选 3: 计划先行
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
                    current_user = user_content + (_perturb_hints[i % len(_perturb_hints)] if retry == 0 else "")
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
            # 2026-08-30（#51）：上述兜底仍拿到"疑似推理文本"时，做一次**定向重问**，
            # 而不是把长文本当答案交给判分器。
            # 依据：基线 45 题有 5 题抽出的答案 >60 字符（含整段计算步骤与结论句），
            # 本地宽松判分能看懂、平台判分看不懂。模型具备给出简洁答案的能力，
            # 缺的是一次明确要求——成本仅一次短调用，收益是消除平台侧的格式性丢分。
            if (getattr(self.config, 'enable_answer_reask', True)
                    and ctx.budget is not None and ctx.budget.can_spend(1)):
                answer = self._reask_final_answer(ctx, resp, answer)
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
    # Step 2 无条件自改进（IMO2025 验证-精炼论文，2026-08-29）
    # ----------------------------------------------------------
    def improve_candidates(self, ctx: TaskContext) -> int:
        """对已有候选做一遍 review+improve（论文流水线 Step 2）。

        论文（Huang & Yang 2025）观测：初始解质量普遍低，Step 2 给模型
        注入第二段推理预算后输出显著改进。与 revise 的关键区别：
        revise 是**验证失败才修正**（有条件），自改进是**无条件先做一遍**。

        成本：每候选 1 次 LLM 调用，默认最多 self_improve_max=3 个候选
        （fast 档与应急模式由调用方跳过）。改进成功返回候选数。
        """
        cands = [c for c in ctx.candidates
                 if getattr(c, "reasoning", "") and not c.reasoning.startswith("[")]
        limit = int(getattr(self.config, "self_improve_max", 3))
        targets = cands[:limit]
        if not targets:
            return 0

        n_ok = 0
        for cand in targets:
            if ctx.budget is not None and not ctx.budget.can_spend(1):
                break
            user_content = SELF_IMPROVE_USER.format(
                problem=ctx.problem,
                candidate_solution=cand.reasoning,
            )
            resp = self._compressed_solve(
                ctx,
                get_policy_system(use_blueprint=getattr(self.config, "use_blueprint", True)),
                user_content,
                temperature=0.1,
                max_tokens=min(
                    self._adaptive_max_tokens(ctx, self.config.policy_max_tokens),
                    16384,
                ),
            )
            if not resp or not resp.strip():
                continue
            if _is_refusal(resp):
                continue
            # 改进版比原版还差（明显更短/空壳）则丢弃
            if len(resp.strip()) < max(40, len(cand.reasoning) // 3):
                continue
            answer = extract_final_answer(resp)
            if not answer or len(answer) > 300:
                answer = rescue_final_answer(resp)[0]
            if not answer:
                answer = smart_fallback_answer(resp)
            cand.reasoning = resp
            if answer:
                cand.answer = answer
            n_ok += 1
            time.sleep(0.3)  # 速率限制

        if n_ok:
            self.record(ctx, "self_improve",
                        f"Step2 自改进 {n_ok}/{len(targets)} 个候选")
        return n_ok

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
