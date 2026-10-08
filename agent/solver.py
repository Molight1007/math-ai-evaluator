from __future__ import annotations

# 2026-10-01 开关注册制（审查 A 级第 2 条）：开关统一走 switch_registry，
# 不再裸读 os.environ —— 既保持 env 优先级（行为不变），又能被 diag/报告还原。
try:
    from agent.switch_registry import (
        get_num as _sw_num, get_str as _sw_str)
except ImportError:
    from switch_registry import (
        get_num as _sw_num, get_str as _sw_str)
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
import os
import re
import time

from .base import (
    BaseAgent, TaskContext, Candidate,
    detect_hallucination, detect_truncated,
    next_candidate_id,           # 2026-09-17：候选 id 单一来源（防腾位后 id 冲突）
    pick_best_candidates,        # 2026-09-17：腾位按票数选优（单一来源）
)
# 2026-10-08 拆分批4：`_pool_gate_v2_on` 的唯一使用点（`_normalize_and_check_answer`）
# 已随候选池簇迁至 `agent/solver__pool.py`（该模块从 `.base` 直接导入），此处删除。
# 2026-10-08：`get_domain_hint` / `build_blueprint_user_message` 随段 4–7 迁至
# `agent/solver__prompt.py`，此处不再需要。
# 2026-10-08 拆分：`REVISE_SYSTEM` / `REVISE_USER_TEMPLATE`（随 `_generate_revise`
# 段 3–6 迁至 `agent/solver__revise.py`）与 `SELF_IMPROVE_USER` / `get_policy_system`
# （随 `_improve_candidates_once` 段 4–尾 迁至 `agent/solver__improve.py`）在本文件
# 已无使用者，一并删除，避免"双份导入"。
from prompts.proof import PROOF_SYSTEM, PROOF_TEMPLATE
# 2026-10-08 拆分：符号化「本地计算接管答案」三通道
# （表达式范式 / L2 独立符号建模复核 / 符号化方程求解）已整体迁至
# `agent/solver__symbolic.py`；其 prompts（SYMBOLIC_*）、symbolic_model、
# symbolic_solve、utils.math_eval（to_exact_number）依赖一并在该模块顶部导入。
from utils.extract import (
    extract_final_answer,
    smart_fallback_answer,
    rescue_final_answer,
    is_valid_final_answer,
)
from utils.prefill import prefill_messages, stitch

# 2026-10-08 拆分：`_generate_initial` 的提示词装配与并行采样已抽到独立模块
# （逐字搬 / 整段同迁），本文件只保留 `_generate_initial` 主控与一行委托调用。
from .solver__prompt import (          # noqa: E402
    _build_initial_prompt, _inject_initial_context,
)
from .solver__sample import _run_initial_sampling  # noqa: E402

# 2026-10-08 拆分：`_generate_revise` 的「上一轮解答装配 + 并行重解 + 结果入池」
# 与 `_improve_candidates_once` 的「单轮自改进主循环」已抽到独立模块（逐字搬）。
from .solver__revise import _revise_run_sampling       # noqa: E402
from .solver__improve import _improve_loop             # noqa: E402
# 2026-10-08 拆分批4：候选池/规模/入场门槛 与 lemma 上下文已抽到独立模块（逐字搬）。
from .solver__pool import _pool_room                    # noqa: E402

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


# ------------------------------------------------------------------
# 2026-09-29：**"生成前算式预计算"（方案 B，阶段 2.65_calc_prewarm）已删除**。
# ------------------------------------------------------------------
# 用户决策原话：「这个预计算没必要，且不合逻辑删了。之后对于计算部分我们会再想办法。」
#
# 原设计（2026-09-13 方案 B）在首个生成阶段前先让 LLM 只列算式、SymPy 算好，
# 再把 `[计算] 精确值` 回填进 prompt。删除理由：
#   ① **不合逻辑**：它把"计算"从模型的推理链里剥离成独立前置步骤，掩盖了模型
#      真实的计算能力 —— 而研究阶段的目标恰恰是测量并提升模型自身能力；
#   ② 实测相关性弱（原注释自陈"解题前猜不出真正需要的算式，偶发纯四则噪音"）；
#   ③ 成本可观（000 实测 125s；010 实测吃掉 364s ≈ 全题预算 36%）。
#
# ⚠ 计算部分将另行设计（用户："之后对于计算部分我们会再想办法"）。
# 2026-10-01：`_CALC_GUIDE` / `_CALC_SHORT_HINT` / `_calc_trace_block` /
#   `has_hard_op` 及整个 `<calc>` 计算工具板块亦已按用户决策删除
#   （`agent/calc_tool.py` 一并移除；纯数学求值内核迁至 `utils/math_eval.py`）。
#   连带 `_maybe_answer_selfcheck` 一并移除 —— 其内含原 L4 记录的
#   「calc_inconsistent（计算冲突）检测不可达」死路径；该检测唯一来源即
#   `<calc>` 的"工具来源 / 裸数值断言"判据，已随板块消失。
# ==================================================================



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


# 2026-09-06 易错点记忆（A 档轻量经验注入）：prompts/error_lessons 惰性加载，
# 由 orchestrator/solver 在初始生成与 revise 时拼接（命中才注入）。
_LESSON_MOD = None


def _lesson_module():
    global _LESSON_MOD
    if _LESSON_MOD is None:
        from prompts.error_lessons import match_lessons, lesson_ids  # noqa: PLC0415
        _LESSON_MOD = (match_lessons, lesson_ids)
    return _LESSON_MOD


def error_lessons_block(ctx) -> str:
    """命中当前题的自查清单片段（无命中=空串，零噪音）。"""
    if getattr(ctx, "state", None) is not None and getattr(
            getattr(ctx, "state", None), "emergency", False):
        return ""  # 应急模式不注入，把预算全给解题
    match_lessons, _ = _lesson_module()
    return match_lessons(domain=getattr(ctx, "domain", "") or "",
                         question_type=getattr(ctx, "question_type", "") or "",
                         problem=ctx.problem or "")


def error_lesson_ids(ctx) -> list:
    """命中的 lesson id 列表（record 诊断用）。"""
    _, lesson_ids = _lesson_module()
    return lesson_ids(domain=getattr(ctx, "domain", "") or "",
                      question_type=getattr(ctx, "question_type", "") or "",
                      problem=ctx.problem or "")


class SolverAgent(BaseAgent):
    name = "Solver"

    def run(self, ctx: TaskContext) -> TaskContext:
        """根据当前上下文状态决定初始求解还是纠错重解"""
        # 2026-09-02 老师需求：候选池统一封顶（无论初始/revise/自改进/playoff 从哪条路径追加）。
        # 历史：13→8→5→8（003 退步分析——cap5 曾砍掉好候选后 0 票直答退化成
        # No such function，改回 8 保好候选）。
        # 2026-09-04：cap 8→6（deep 候选 4→3 配套，验证成本 -25%）。此时初始池
        # 只到 3、revise 补 ≤3，总量天然 ≤6，封顶不再主动砍候选，无 003 式风险。
        # count 只传 remaining 上限，adaptive 缩小在 _generate_initial 内部做。
        # ★ 2026-10-04 修（D7）：原硬编码 `6 - len(...)`，与 orchestrator 自称
        #   「已按研究期标尺删除封顶、不再截断候选」矛盾。统一读 `candidate_pool_limit`
        #   （0 = 不限，研究期默认）—— 三处同源，见模块级 `_pool_room`。
        remaining = _pool_room(self.config, ctx)
        # ★ 2026-09-17（M1）：池满时**不要在这里 return**。
        # 腾位逻辑写在 `_generate_revise` 内部（其 `_room <= 0` 分支），而本函数
        # 在 `remaining <= 0` 时直接返回 ⇒ **那段腾位结构性不可达**。
        # 实测后果：official112-003 的 `revise_round=4`，但 6 个候选
        # `revised` **全为 False** —— 4 轮修订一个候选都没生成，却烧掉
        # `5_revise_or_fallback 688.5s + 5.5_low_conf 805.6s = 1494s`。
        # 修法：仅"非修订轮且池满"才早退；修订轮池满时把 cap 置 None，
        # 交给 `_generate_revise` 自行腾位后决定 count。
        _is_revise = bool(ctx.revise_round > 0 and ctx.revise_feedback)
        if remaining <= 0 and not _is_revise:
            return ctx
        if _is_revise:
            self._generate_revise(ctx, cap=(remaining if remaining > 0 else None))
        else:
            self._generate_initial(ctx, count=remaining)
        return ctx

    def add_candidates(self, ctx: TaskContext, count: int = None,
                       temperatures: list = None) -> TaskContext:
        """补充生成普通候选。

        ★★ 2026-10-06 扩参（**把"建好没接线"的能力接上**）：
        本方法的 docstring 一直写着「中置信度分支调用 `add_candidates` 补充采样」，
        但**全仓没有任何调用点** —— 又一例"建好没接线"。
        新增 `temperatures` 参数：用于**零多样性**场景下**高温度补采**求差异
        （否则补采只会再得到同一个答案，等于白跑）。
        """
        self._generate_initial(ctx, count or self.config.policy_sample_times,
                               temperatures=temperatures)
        return ctx

    @staticmethod
    def _adaptive_count(ctx: TaskContext, default_count: int) -> int:
        # 2026-10-08 拆分批4：实现迁至 agent/solver__pool.py（逐字搬，见该模块）。
        from .solver__pool import _adaptive_count as _impl
        return _impl(ctx, default_count)

    @staticmethod
    def _adaptive_max_tokens(ctx: TaskContext, base_tokens: int) -> int:
        # 2026-10-08 拆分批4：实现迁至 agent/solver__pool.py（逐字搬，见该模块）。
        from .solver__pool import _adaptive_max_tokens as _impl
        return _impl(ctx, base_tokens)

    def _normalize_and_check_answer(self, ctx: TaskContext, cid,
                                    answer) -> tuple:
        # 2026-10-08 拆分批4：实现迁至 agent/solver__pool.py（逐字搬，见该模块）。
        from .solver__pool import _normalize_and_check_answer as _impl
        return _impl(self, ctx, cid, answer)

    def _answer_is_usable(self, ctx: TaskContext, cid, answer) -> bool:
        # 2026-10-08 拆分批4：实现迁至 agent/solver__pool.py（逐字搬，见该模块）。
        from .solver__pool import _answer_is_usable as _impl
        return _impl(self, ctx, cid, answer)

    def _use_lemma(self, ctx: TaskContext) -> bool:
        # 2026-10-08 拆分批4：实现迁至 agent/solver__lemma.py（逐字搬，见该模块）。
        from .solver__lemma import _use_lemma as _impl
        return _impl(self, ctx)

    def _collect_lemma_context(self, ctx: TaskContext) -> str:
        # 2026-10-08 拆分批4：实现迁至 agent/solver__lemma.py（逐字搬，见该模块）。
        from .solver__lemma import _collect_lemma_context as _impl
        return _impl(self, ctx)

    # ==========================================================
    # 阶段一（2026-10-02）：子目标结论 → 主求解 信息流
    # ==========================================================
    # 用户设计的权威定义（原话）：
    #   「子目标的设立是大模型先计划怎么求解，需要得到哪些条件与数据才能解出问题。
    #     然后设立对应的子目标得到对应的数据，然后根据数据解出答案。
    #     所以主求解一定要在子目标的基础上。」
    #
    # 背景：2.7_subgoal_main 阶段（及 deep 档 3_solve 内的 P&E）已把逐步求得的子
    # 目标结论写入 `ctx.subgoal_trace`，但**主求解（solver）此前从不读取它** ——
    # 子目标白做，主答案仍是"从零再推一遍"。本注入把子目标结论作为**中间数据**喂给
    # 主求解，并明确要求"在此基础上整合出最终答案"。
    #
    # 边界（用户拍板，只改信息流，不改任何行为）：不动投票 / 采样 / 终答 / 阈值；
    # "允许纠错"同样是信息层面的提示（防被错误子目标绑死），不是代码侧的答案改写。
    # 开关：`enable_subgoal_findings`（已登记 switch_registry，缺省 True；
    #       置 False 可一键回退到"不注入"）。
    # 单条子目标结论渲染上限（防某步 result 过长挤爆主求解提示词）。
    _SUBGOAL_FINDING_ITEM_CHARS = 1200
    # 子目标结论注入块整体上限（超限截断并留痕）。
    _SUBGOAL_FINDINGS_MAX_CHARS = 8000

    def _render_subgoal_findings(self, ctx: TaskContext) -> str:
        # 2026-10-08 拆分：实现迁至 agent/solver__subgoal.py（逐字搬，见该模块）。
        from .solver__subgoal import _render_subgoal_findings as _impl
        return _impl(self, ctx)

    def _apply_subgoal_findings(self, ctx: TaskContext, text: str) -> str:
        # 2026-10-08 拆分：实现迁至 agent/solver__subgoal.py（逐字搬，见该模块）。
        from .solver__subgoal import _apply_subgoal_findings as _impl
        return _impl(self, ctx, text)

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

    # 2026-09-29：`_prewarm_applicable()` 与 `prewarm_calcs()` 已删除
    # （"生成前算式预计算"/方案 B，对应阶段 2.65_calc_prewarm）。
    # 删除理由见上方常量区注释（用户决策：没必要、不合逻辑）。
    # 计算部分将另行设计。
    # ============================================================

    # ============================================================
    # 2026-09-12 表达式范式核验
    # （原 L1 `<calc>` 计算纪律关卡已整体删除；本机制不依赖 `<calc>` 标记，
    #  靠【变量赋值】/【最终表达式】两行 + 本地精确求值内核。）
    # ============================================================
    def _maybe_expression_eval(self, ctx: TaskContext, resp: str,
                               answer: str) -> tuple[str, str]:
        # 2026-10-08 拆分：实现迁至 agent/solver__symbolic.py（逐字搬，见该模块）。
        from .solver__symbolic import _maybe_expression_eval as _impl
        return _impl(self, ctx, resp, answer)

    # 2026-09-10 L2：独立符号建模复核（默认关，symbolic_crosscheck_enabled 开）
    # ------------------------------------------------------------
    # 用户 9/10 思路 + 李平老师 9/9 建议合并：让模型当"数学问题拆解助手"，
    # 把题面**给定的具体数值**抽象成变量、只输出**目标量的表达式**（禁止自算），
    # 再由本地精确计算器代入求真值，与主链答案比对。
    #   - 一致   → 记 pass（独立路径旁证，增强置信）
    #   - 不一致 → 打回一次（带上独立建模真值）；采纳新答案**仅当**它落回该真值
    #   - 求不出 / 无法建模 / 证明题 / 时间紧 → 直接放行（宁漏勿误）
    # 与表达式范式正交：后者查"答案是否等于本地计算值"，L2 用**独立于解答**的
    # 一次建模重建"关系式→精确值"（推理旁证）。每题最多触发一次（ctx 标记）。
    # 求值走 utils/math_eval（毫秒级精确）而非 Lean —— 纯算术不必付 21s/次的 Lean 前置。
    # ============================================================
    def _maybe_symbolic_crosscheck(self, ctx: TaskContext, resp: str,
                                   answer: str) -> tuple[str, str]:
        # 2026-10-08 拆分：实现迁至 agent/solver__symbolic.py（逐字搬，见该模块）。
        from .solver__symbolic import _maybe_symbolic_crosscheck as _impl
        return _impl(self, ctx, resp, answer)

    # ============================================================
    # 2026-09-12 符号化方程求解通道（默认关，symbolic_solve_enabled 开）
    # ------------------------------------------------------------
    # 用户 9/11 需求：模型根据题目逻辑推导出**方程式类型**的答案，具体数值由
    # 智能体调用工具执行计算 —— 智能体把数据剥离存本地，给模型的是"未知数
    # 类型"题面，模型只交方程（组）+ 目标，数值一律由本地 SymPy 回代算出。
    #
    # 省时间设计（用户 9/12 硬要求："为模型减少浪费时间而不是加时间"）：
    #   - 剥离 / 校验 / 求解 **全部本地**（毫秒~秒级，daemon 线程 5s 超时）；
    #   - 只加 **1 次短建模调用**（≈120 tokens，不是完整求解调用）；
    #   - 工具值与主链答案**一致** → 记 pass 直接放行，**0 额外调用**；
    #   - 仅当**分歧**时才追加 1 次短回传（把工具结果交回模型定稿，即
    #     "将计算方程式给工具并接收工具返回的结果"）；
    #   - **不新增候选** → 不触发下游验证/Lean 闸门的任何额外成本。
    # 硬性保证（用户 9/12）：最终答案的数值必须与工具返回一致 —— 模型不参与计算。
    # ============================================================
    def _maybe_symbolic_solve(self, ctx: TaskContext, resp: str,
                              answer: str) -> tuple[str, str]:
        # 2026-10-08 拆分：实现迁至 agent/solver__symbolic.py（逐字搬 + 拆尾部，见该模块）。
        from .solver__symbolic import _maybe_symbolic_solve as _impl
        return _impl(self, ctx, resp, answer)

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
                # 2026-10-02 DeepSeek 适配：原 256 ⇒ 8192。⚠ 该键全仓无 config 声明，
                # 故此处 getattr 兜底即为唯一默认值。原值假设「重问只需一行最简形式」，
                # 对 reasoning 模型必然截断（reasoning 先吃满预算、正文为空）。
                max_tokens=int(getattr(self.config, 'answer_reask_max_tokens', 8192)),
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
        from .base import Candidate, next_candidate_id
        conditions = "见题目"
        strategy_hint = "选择最合适的证明方法（直接证明/反证法/归纳法/构造法）"
        user = PROOF_TEMPLATE.format(
            problem=ctx.problem, conditions=conditions, strategy_hint=strategy_hint
        )
        # ★ 2026-09-29：证明题是定理检索**最该受益**的题型（结论要被某条 Mathlib
        # 定理支撑），证明通道却是独立路径，必须单独注入。
        if getattr(self.config, 'enable_theorem_hint', True):
            _th = (getattr(ctx, 'theorem_hint_block', '') or '').strip()
            if _th:
                user = user + "\n\n" + _th
        # ★ 2026-10-02（阶段一补）：证明题**最需要**子目标结论 —— 证明链本身就是
        # 逐步结论的串联。本通道独立于 _generate_initial，必须同样注入
        # （本项目教训：只改一处路径=没改）。位置：题目/定理之后、prefill 求解之前。
        user = self._apply_subgoal_findings(ctx, user)
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
            # 2026-09-17：与文件内其它答案路径统一口径 —— **切片前先剥壳**。
            # 否则 `raw[-500:]` 会把尾部工具残留（实测 official112-025：
            # `</tool_call>`）当作答案落盘。惰性 import + 兜底：剥壳失败退回原切片。
            _raw_clean = raw
            try:
                from utils.extract import (_strip_calc_markers,
                                           _strip_toolcall_markers)
                _raw_clean = _strip_toolcall_markers(_strip_calc_markers(raw))
            except Exception:  # noqa: BLE001  剥壳失败不阻断
                pass
            answer = _raw_clean.strip()[-500:]
        cid = next_candidate_id(ctx.candidates)
        return Candidate(id=cid, reasoning=raw, answer=answer)

    def _compressed_solve(self, ctx: TaskContext, system: str, user: str,
                          temperature: float = 0.1,
                          max_tokens: int = 8192,
                          prefill_seed: str = "## 问题分析\n") -> str | None:
        """ICMA 同款压缩求解：prefill 种子抑制 CoT，快速产出答案。

        v2.4.1 起为本环境**主求解路径**：诊断实测完整 CoT 单次调用 >200s 不返回
        （780s 仍读超时），而 prefill 压缩求解 36.7s 即返回 ~2000 tokens 结构化解答。
        prefill 答案前置：即使输出被截断，也只损失思考、不损失答案。

        2026-09-04：prefill_seed 改为可配参数（默认 "## 问题分析\n" 适配主求解/证明
        四章节格式；revise 传 "【错误分析】\n"、self-improve 传 "【第一步：诊断】\n"
        与各自 system 要求的输出开头对齐，避免格式错位）。
        """
        try:
            msgs = prefill_messages(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                prefill_seed,
            )
            # 2026-09-09 试点起：满足工具循环条件（enable_web_search）走原生工具循环
            resp = self._maybe_tool_llm(ctx, msgs, temperature, max_tokens)
            if resp:
                return stitch(prefill_seed, resp)
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
                # ★★ 2026-10-07（2.4 v2 入口穷举 · 入口①）：**证明通道此前不过门槛**
                #   —— 它是独立于主路径的一条 append，上一轮只改了主路径（"只改一处
                #   = 没改"）。此处与主路径同口径，不合格则**不入池、继续走通用求解**。
                _pans, _pok = self._normalize_and_check_answer(
                    ctx, proof_cand.id, proof_cand.answer)
                if _pok:
                    proof_cand.answer = _pans
                    ctx.candidates.append(proof_cand)
                    self.record(ctx, "generate",
                                f"证明题专用通道生成候选 #{proof_cand.id}")
                    return
                self.record(ctx, "generate",
                            "证明题专用通道候选不含最终答案 → 弃用，回退通用求解")
            else:
                self.record(ctx, "generate", "证明题专用通道未产出有效候选，回退通用求解")

        # 2026-10-08 拆分（段 4–7）：lemma/蓝图/子目标结论/答案格式装配 →
        # `agent/solver__prompt.py::_build_initial_prompt`（逐字搬）。
        system_prompt, user_content = _build_initial_prompt(self, ctx)
        # 2026-10-08 拆分（段 8–11）：定理/易错点/客观题特化/答案形态注入 →
        # `agent/solver__prompt.py::_inject_initial_context`（逐字搬）。
        user_content = _inject_initial_context(self, ctx, user_content)
        # ★ 2026-09-17（M4）：id 基线改为 `max(已有 id)+1`。
        # 原用 `len(ctx.candidates)`，而腾位会让 len 变小 ⇒ 新 id 与旧 id 重叠
        # （实测 013 出现**两个 id=3**、025 出现 id=7）。下游按 id 匹配的地方
        # （`orchestrator` 的 `_gate_tried`、`formatter` 的簇内候选匹配）随之错位。
        base_cid = next_candidate_id(ctx.candidates)
        if temperatures is None:
            tier_tbl = getattr(self.config, 'tier_temperatures', None)
            temperatures = (tier_tbl.get(getattr(ctx, 'tier', 'standard'), [0.1, 0.3, 0.5])
                            if tier_tbl else [0.1, 0.3, 0.5])
        _STRATIFIED_TEMPS = temperatures

        # 2026-10-08 拆分（段 13–16）：`_make_one` 并行采样 + 候选落盘 →
        # `agent/solver__sample.py::_run_initial_sampling`（整段同迁）。
        _run_initial_sampling(
            self, ctx, count, base_cid, _STRATIFIED_TEMPS, system_prompt, user_content)
        self.record(
            ctx, "solve",
            f"生成 {len(ctx.candidates)} 个候选解答 "
            f"(蓝图={self.config.use_blueprint}, 领域={ctx.domain})",
            count=len(ctx.candidates),
        )

    # ----------------------------------------------------------
    # 纠错重解（revise 模式）
    # ----------------------------------------------------------
    def _generate_revise(self, ctx: TaskContext, cap: int = None) -> None:
        # ★★ 2026-10-06 修（**反馈被重复灌入** —— 实测暴露）：
        #   题 000/001 的 `ctx.revise_feedback` 都是 **15 条、去重后只有 9 条**
        #   —— 同一条 706 字符的块**重复了 7 次**（6.5 重做循环每轮追加一次
        #   `audit_reject_feedback`、每轮闸门各追加一条 Lean 建议，**没有全局去重**）。
        #   后果：提示词里同一内容重复 7 遍 ⇒ **信噪比崩溃**，模型注意力被单一噪声占满，
        #   真正带定位的结构化 bug report 被淹没（实测题 000 的 15 条里
        #   「疑似自证」占 12 条、结构化「位置：」占 **0** 条）。
        #   修法：在**渲染进提示词之前**统一去重（按归一化前 160 字，保留首次出现顺序）。
        #   ⚠ 放在渲染处而不是各追加点：**一处修，覆盖所有来源**，
        #     将来新增反馈通道也不会再漏（这是"只改一处=没改"教训的正向用法）。
        #   ⚠ 关键：**归一化掉"候选编号"**。实测那 12 条「疑似自证」并非逐字相同
        #     （分别写着 `候选 8` / `候选 6` / `候选 7`），若按原文去重一条都去不掉。
        #     它们讲的是**同一件事**（验证代码没锚定题目数字），必须折叠成一条。
        import re as _re_fb
        _seen_fb, _uniq_fb = set(), []
        for _fb in (ctx.revise_feedback or []):
            _key = " ".join(str(_fb).split())
            _key = _re_fb.sub(r"候选\s*\d+", "候选", _key)
            _key = _re_fb.sub(r"#\d+", "#", _key)
            _key = _key[:160]
            if not _key or _key in _seen_fb:
                continue
            _seen_fb.add(_key)
            _uniq_fb.append(_fb)
        if len(_uniq_fb) < len(ctx.revise_feedback or []):
            self.record(ctx, "revise",
                        "反馈去重：%d 条 → %d 条（同一内容重复灌入会压低信噪比）"
                        % (len(ctx.revise_feedback or []), len(_uniq_fb)))
        feedback_text = "\n".join(f"- {fb}" for fb in _uniq_fb)
        # 2026-09-06 易错点记忆注入（revise 补救侧）：修订时同步带上同类题
        # 历史易错自查清单（命中才注入），让重解不只针对反馈、也避开已知坑。
        if getattr(self.config, 'enable_error_lessons', True):
            lessons_block = error_lessons_block(ctx)
            if lessons_block:
                feedback_text = feedback_text + "\n" + lessons_block
                self.record(ctx, "error_lesson",
                            f"revise 注入历史易错自查清单 {error_lesson_ids(ctx)}")
        # ★★ 2026-10-06 修（**重做力度逐轮衰减** —— 实测驱动）：
        #   `count` 原为 `cap`（= `_pool_room()` = 池剩余容量 = limit − len(candidates)），
        #   而 revise 每轮都会往池里加候选 ⇒ **剩余容量单调递减** ⇒ 实测题 000 的
        #   `重解启动：count=` 逐轮为 **4 → 2 → 1**，最后一轮只剩 1 个候选。
        #   后果：**越到后面重做力度越小，改对的机会越少**（而这恰恰是最需要多试的时候）。
        #   修法：给 revise 设**候选数下限** `revise_min_candidates`（默认 3）。
        #   ⚠ 允许略微超出 `candidate_pool_limit` —— 该上限是**软帽**（池满时
        #     `_generate_revise` 内部本就会自行腾位），而"最后一轮只试 1 个"的代价更大。
        _revise_floor = int(getattr(self.config, "revise_min_candidates", 3) or 3)
        count = max(cap if cap is not None else self.config.revise_sample_times,
                    _revise_floor)
        # ⚠ A 修复（2026-09-12）：**候选池满时先腾位，而不是静默 return**。
        # 依据：6.5 的「拒绝 → 换候选 / 重解」是唯一的纠错回路，但 candidates
        # 常态就是 6 个 → `6 - len(candidates)` = 0 → count=0 → return
        # → **最需要重解时反而重解不了**（实测 revise_round 恒为 0，反馈白给）。
        # ★ 2026-10-04 修（D7）：硬编码 6 → `candidate_pool_limit`（0 = 不限）。
        _room = _pool_room(self.config, ctx)
        if _room <= 0 and getattr(ctx, "revise_feedback", None):
            # ★ 2026-09-17（M3）：腾位改为**按验证票数保留最优 3 个** ——
            # 口径与实现统一在 `base.pick_best_candidates`（可被单测直接覆盖）。
            # 原规则 `[-3:]` 按 id 尾部保留"最新"的 3 个，与正确性无关：若新追加
            # 的候选恰好最差，就会留下最差 3 个、丢掉初始解（通常较好）。
            _keep = pick_best_candidates(ctx.candidates,
                                         getattr(ctx, "verdicts", None), k=3)
            self.record(ctx, "revise",
                        f"候选池满（{len(ctx.candidates)} 个）→ 腾位至 3 个，"
                        f"为重解让出槽位（A 修复 2026-09-12）")
            ctx.candidates = _keep
            # ★ 2026-10-04 修（D7）：腾位后重算槽位，同样走 `candidate_pool_limit`。
            _room = _pool_room(self.config, ctx)
        count = max(0, min(count, _room))
        # B 埋点（2026-09-12）：把「重解到底跑没跑、为什么没跑」全部记下来——
        # 此前三处静默路径（候选满 / 时间不足 / 反馈空）无法区分，
        # 导致「反馈给了模型却仍答错」无法定位。
        if count <= 0:
            self.record(ctx, "revise",
                        f"重解**未启动**：可用槽位 {count}"
                        f"（候选 {len(getattr(ctx, 'candidates', None) or [])} 个、"
                        f"反馈 {len(getattr(ctx, 'revise_feedback', None) or [])} 条、"
                        f"cap={cap}）")
            return
        self.record(ctx, "revise",
                    f"重解**启动**：count={count}、"
                    f"反馈 {len(ctx.revise_feedback)} 条、"
                    f"revise_round={getattr(ctx, 'revise_round', 0)}、"
                    f"报文首 {str(feedback_text)[:80]}")

        # ★ 2026-09-17（M4）：id 基线改为 `max(已有 id)+1`。
        # 原用 `len(ctx.candidates)`，而腾位会让 len 变小 ⇒ 新 id 与旧 id 重叠
        # （实测 013 出现**两个 id=3**、025 出现 id=7）。下游按 id 匹配的地方
        # （`orchestrator` 的 `_gate_tried`、`formatter` 的簇内候选匹配）随之错位。
        base_cid = next_candidate_id(ctx.candidates)

        _revise_run_sampling(self, ctx, count, base_cid, feedback_text)

        self.record(
            ctx, "revise",
            f"纠错重解 第{ctx.revise_round}轮：生成 {count} 个修正候选",
            round=ctx.revise_round,
        )

        # ★★ 2026-09-30（截图 #9）：**revise 之后接一次无条件自改进**。
        #   用户原话：「错误点返回大模型重新生成，**可否加无条件自改**」。
        #
        #   为什么在 revise **之后**加（而不是别处）：
        #     revise = "**告诉模型错哪了**"（有条件、带定向反馈）；
        #     自改进 = "**给模型第二段推理预算，不管它看起来对不对**"（无条件）。
        #     把两者串起来，正是用户描述的完整闭环：
        #       错误点返回重生成 → 对重生成的结果**再无条件过一遍**。
        #     反过来（自改进 → revise）会浪费：自改进还没被验证，没有错误点可返。
        #
        #   为什么是**新开关**而不是复用 `self_improve_rounds`：
        #     `3.3_improve` 是流水线里**独立的一道**（在 3_solve 之后、验证之前），
        #     其"遍数"语义是"对初始解改几遍"；本处是"revise 产出后再补一遍"，
        #     属于**不同环节、不同成本口径**。合并成一个字段会让 A/B 无法正交
        #     （改一个动两处），违反"一次只改一项"。
        #     ⇒ 新增 `self_improve_after_revise`，默认 **False**（行为与改动前逐字一致）。
        #
        #   ⚠ 成本提示（写进注释以免后人误开）：
        #     每候选 1 次 LLM 调用，且 revise 与 5.5/6.5 都排在流程后段，
        #     本处若开启会把 `verify_reserve` 进一步压缩 —— 开启前先确认
        #     `improve_min_remaining` 与 `is_time_critical()` 两道护栏仍在生效
        #     （下面直接复用 `improve_candidates`，其内层护栏原样保留，不另写一套）。
        if bool(getattr(self.config, "self_improve_after_revise", False)):
            if not ctx.is_time_critical():
                try:
                    _n_late = self.improve_candidates(ctx)
                    self.record(
                        ctx, "self_improve",
                        f"revise 后无条件自改进（self_improve_after_revise="
                        f"True）：本轮改进 {_n_late} 个候选",
                        round=int(getattr(ctx, "revise_round", 0) or 0))
                except Exception as _e_imp:  # noqa: BLE001
                    # 自改进是**可选增强**，任何异常都不得阻断 revise 主流程
                    self.record(ctx, "self_improve",
                                f"revise 后自改进异常跳过: {str(_e_imp)[:120]}")
            else:
                self.record(ctx, "self_improve",
                            "revise 后自改进跳过：已进入时间紧迫区间"
                            "（保 4_verify / 6.5 终局闸门）")

    # ----------------------------------------------------------
    # Step 2 无条件自改进（IMO2025 验证-精炼论文，2026-08-29）
    # ----------------------------------------------------------
    def improve_candidates(self, ctx: TaskContext) -> int:
        """对已有候选做 review+improve（论文流水线 Step 2），可多轮。

        论文（Huang & Yang 2025）观测：初始解质量普遍低，Step 2 给模型
        注入第二段推理预算后输出显著改进。与 revise 的关键区别：
        revise 是**验证失败才修正**（有条件），自改进是**无条件先做一遍**。

        2026-09-29 用户决策（截图 #7）：
          · **恢复真无条件** —— `self_improve_conditional` 默认 False，
            即默认不对候选做「看起来有问题才改」的过滤；
          · **遍数可配** —— `self_improve_rounds` 默认 1，可设 2 做 A/B。
            第 N 轮的输入是第 N-1 轮的产物（对同一批候选再注入一次推理预算）。

        返回本次累计改进成功的候选次数（跨轮累加）。
        """
        rounds = max(1, int(getattr(self.config, "self_improve_rounds", 1) or 1))
        total = 0
        for r in range(rounds):
            # 2026-09-29：每轮开始前重置 `self_improved` 标记 —— 否则第 2 轮
            # 会被第 1 轮设下的标记全部过滤掉（`not self_improved` 恒假 → 空转）。
            # 仅在第 2 轮及以后重置，避免影响其它调用方对标记的语义预期。
            if r > 0:
                for _c in ctx.candidates:
                    try:
                        _c.self_improved = False
                    except Exception:  # noqa: BLE001
                        pass
                self.record(ctx, "self_improve",
                            f"Step2 第 {r + 1}/{rounds} 轮开始（重置改进标记）")
            n = self._improve_candidates_once(ctx)
            total += n
            if n == 0:
                # 本轮无候选可改进 ⇒ 后续轮次必然同样空转，提前收敛省一次遍历。
                self.record(ctx, "self_improve",
                            f"Step2 第 {r + 1}/{rounds} 轮无改进产出 → 停止")
                break
        if total:
            self.record(ctx, "self_improve",
                        f"Step2 自改进累计 {total} 个候选（{rounds} 轮上限）")
        return total

    def _improve_candidates_once(self, ctx: TaskContext) -> int:
        """单轮自改进（原 `improve_candidates` 主体）。

        成本：每候选 1 次 LLM 调用，默认最多 self_improve_max 个候选。

        2026-09-01（SU-01 优化 2，论文 §3.3 防递归）：
        跳过已 self_improved=True 的候选（防"对同一候选循环调用 Step2"，
        论文 SU-01 不递归入队失败精炼，对齐此约束）。
        """
        def _needs_improve(c) -> bool:
            """候选缺陷过滤（**2026-09-29 起默认关闭**）。

            历史依据（2026-09-11 A2）：smoke6_v3 实测「无条件改进」只有成本
            没有收益 —— 3.3 占单题 29~45% 耗时（总耗时 +34%），而正确率 1/6
            完全不变，且 098 被从正确答案改错。故当时改为**条件触发**。

            2026-09-29 用户决策：恢复真无条件（默认 `self_improve_conditional
            = False`），在「统一 deep 档 + 原版保留 + 下游投票择优」的新配置
            下重新验证。设 `self_improve_conditional=True` 可回到条件化行为。
            """
            if not bool(getattr(self.config, "self_improve_conditional", False)):
                return True                                    # 真无条件
            # 2026-10-01：**刻意不进 switch_registry** —— 本行是叠加在配置字段之上的
            # 「环境变量覆盖」分支，其 env 默认 "1" 与 AgentConfig 字段默认 False 语义相反，
            # 若经 registry 读取会被 bind_config 绑成配置值从而**改变行为**。
            # 保持原样直读 env（已登记为待厘清项）。
            if os.environ.get("SELF_IMPROVE_CONDITIONAL", "1") == "0":
                return True                                    # 环境变量覆盖（兼容旧用法）
            _ans = str(getattr(c, "answer", "") or "").strip()
            _rs = str(getattr(c, "reasoning", "") or "")
            if not _ans or len(_ans) < 2:                     # ① 答案缺失/过短
                return True
            if any(k in _rs for k in ("...", "[已截断]", "未完成", "待续")):
                return True                                    # ② 推理被截断
            if len(_rs) < 400:                                 # ③ 推理过短（未充分展开）
                return True
            return False                                       # 看起来完整 → 不改

        cands = [c for c in ctx.candidates
                 if getattr(c, "reasoning", "")
                 and not c.reasoning.startswith("[")
                 and not getattr(c, "self_improved", False)
                 and _needs_improve(c)]
        limit = int(getattr(self.config, "self_improve_max", 3))
        targets = cands[:limit]
        if not targets:
            return 0

        return _improve_loop(self, ctx, targets)

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
        # 2026-09-13 修复（截断重试提示从未生效）：消息必须**每轮现建** —— 原先
        # 循环外先建好 base_msgs，下面的截断重试只改了 user_content，实际发出的
        # 仍是 base_msgs，续写提示从未进入模型调用。

        for attempt in range(3):
            # 2026-09-13 循环时间检查（防卡死）：兜底路径是"最后防线"，故用**最
            # 宽松**口径 —— 只在**单题硬超时**时才停（而非生成侧软截止），保证
            # "无论如何先出一个答案"的兜底价值不被削弱；同时防止 3 次重试
            # （单次可达 180s+）叠加穿掉单题上限。
            if attempt > 0 and ctx.is_timed_out():
                self.record(ctx, "direct_solve", "单题已超时，停止兜底重试")
                break
            try:
                _msgs = [
                    {"role": "system", "content": direct_system},
                    {"role": "user", "content": user_content},
                ]
                resp = self.llm(
                    ctx,
                    prefill_messages(_msgs, "最终答案："),
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
            # 预算允许才续写（2026-09-06 升级 gen_time_up）
            if not ctx.gen_time_up():
                new_c = self.complete_answer(ctx, c)
                if new_c is not c and new_c.answer and len(new_c.answer) > 1:
                    # ★★ 2026-10-07（2.4 v2 入口穷举 · 入口⑤）：**截断续写产物
                    #   此前不过门槛** —— 续写/答案前置重问走的是
                    #   `extract/rescue/smart_fallback` 三条抢救函数，同样可能吐回
                    #   推理句。不合格 ⇒ **保留原候选 c**（它入池时已过门槛），
                    #   不用"续写出的非答案"替换。
                    _cans, _cok = self._normalize_and_check_answer(ctx, c.id, new_c.answer)
                    if _cok:
                        new_c.answer = _cans
                        new_list.append(new_c)
                        completed += 1
                        self.record(ctx, "complete", f"候选 #{c.id} 截断续写成功")
                        continue
                    self.record(ctx, "complete",
                                f"候选 #{c.id} 续写结果不是最终答案 → 保留原候选")
            new_list.append(c)
        ctx.candidates = new_list
        return completed

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
                    # ★ 2026-10-02：4096→8192（DeepSeek 适配方案 A）。本处为"断点续写"，
                    #   产出本身就是长推理，reasoning 模型下 4096 极易二次截断。
                    8192,
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
            direct = self.llm(ctx, _prefill_msgs, 0.0, 32768)
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
