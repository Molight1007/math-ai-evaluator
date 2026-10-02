from __future__ import annotations

# 2026-10-01 开关注册制（审查 A 级第 2 条）：开关统一走 switch_registry，
# 不再裸读 os.environ —— 既保持 env 优先级（行为不变），又能被 diag/报告还原。
try:
    from agent.switch_registry import (
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)
except ImportError:
    from switch_registry import (
        get_bool as _sw_bool, get_num as _sw_num, get_str as _sw_str)
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
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import (
    BaseAgent, TaskContext, Candidate,
    detect_hallucination, detect_truncated,
    detect_template_leak,
    next_candidate_id,           # 2026-09-17：候选 id 单一来源（防腾位后 id 冲突）
    pick_best_candidates,        # 2026-09-17：腾位按票数选优（单一来源）
)
from prompts.policy import (
    SELF_IMPROVE_USER,
    get_policy_system,
    get_domain_hint,
    build_blueprint_user_message,
)
from prompts.revise import REVISE_SYSTEM, REVISE_USER_TEMPLATE
from prompts.proof import PROOF_SYSTEM, PROOF_TEMPLATE
from prompts.symbolic_model import (
    SYMBOLIC_MODEL_SYSTEM, SYMBOLIC_MODEL_USER, SYMBOLIC_JSON_SEED,
    SYMBOLIC_SOLVE_SYSTEM, SYMBOLIC_SOLVE_USER, SYMBOLIC_SOLVE_SEED,
    SYMBOLIC_SOLVE_RETRY_SYSTEM, SYMBOLIC_SOLVE_RETRY_USER,
    SYMBOLIC_FEEDBACK_SYSTEM, SYMBOLIC_FEEDBACK_USER,
)

try:
    from .symbolic_model import parse_symbolic_payload, evaluate_payload
except ImportError:  # 提交包（submit/）路径兜底
    try:
        from symbolic_model import parse_symbolic_payload, evaluate_payload
    except ImportError:
        parse_symbolic_payload = None
        evaluate_payload = None

# 2026-09-12 符号化方程求解通道：数值剥离 → 符号建模 → 硬校验 → 工具求解。
# 模型只交方程，数值一律由本地 SymPy 算出（模型不参与计算）。
try:
    from .symbolic_solve import (
        strip_given_numbers, parse_symbolic_solve, validate_payload,
        solve_with_tool)
except ImportError:  # 提交包（submit/）路径兜底
    try:
        from symbolic_solve import (
            strip_given_numbers, parse_symbolic_solve, validate_payload,
            solve_with_tool)
    except ImportError:
        strip_given_numbers = None
        parse_symbolic_solve = None
        validate_payload = None
        solve_with_tool = None

# 2026-10-01：原 `agent/calc_tool.py` 的纯数学求值内核（B 类）已迁至
# `utils/math_eval.py`；`<calc>` 协议/工具化计算板块（A 类）已整体删除。
# 此处只保留符号核验通道所需的精确数值化入口。
try:
    from utils.math_eval import to_exact_number
except ImportError:  # 提交包（submit/）路径兜底
    try:
        from math_eval import to_exact_number
    except ImportError:
        to_exact_number = None
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
        remaining = 6 - len(getattr(ctx, 'candidates', None) or [])
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

    def add_candidates(self, ctx: TaskContext, count: int = None) -> TaskContext:
        """中置信度分支：补充生成普通候选（默认与初始采样数一致）"""
        self._generate_initial(ctx, count or self.config.policy_sample_times)
        return ctx

    @staticmethod
    def _adaptive_count(ctx: TaskContext, default_count: int) -> int:
        """根据题目领域自适应调整候选数量"""
        domain = (ctx.domain or "").lower()
        # 难题深度通道：deep 档保持多候选（3 候选，不做缩减）
        if getattr(ctx, 'tier', 'standard') == 'deep':
            return default_count
        # 证明题 → 减少候选（精确推演比广度采样更重要）
        proof_keywords = ["proof", "prove", "证明", "证明题", "不等式证明", "几何证明"]
        if any(k in domain for k in proof_keywords):
            return max(1, default_count // 3)
        # P0-4 修复：不再为高难度题提高候选数——3 候选 × 3 重试曾耗尽单题
        # 300s 预算导致 45 error。保持 default_count（配置=2），省预算保产出。
        # 2026-09-12 定型前审核精简：此处原本有一段 hard_signals 判定
        # （题长 / 微分方程 / 级数 / 积分 / 客观题 → 意图给高难题更多候选），
        # 但上面的 P0-4 修复已取消"难题多给候选"策略，使该块的
        # **三个分支全部 `return default_count`** —— 计算了 12 行却零效果，
        # 属典型的"逻辑堆叠后残留"。整块删除（零行为变化）。
        return default_count

    @staticmethod
    def _adaptive_max_tokens(ctx: TaskContext, base_tokens: int) -> int:
        """2026-09-04：比赛不限制模型 token → 各档统一返回 base_tokens（=policy_max_tokens=65536）。

        原分级（简单题 8192 / 难题 24576）在平台单题 1200s 时间墙下大量
        finish_reason=length 答案被腰斩（2534334 平台实测 truncated 238 次、
        64 题 invalid）——截断比多花时间更丢分。上限只作保险，prefill 压缩下
        模型实际输出仍克制；真正边界是 1200s 时间墙而非 token 帽。
        """
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
        """把已求得的子目标结论渲染成文本块，供**主求解**在子目标基础上整合答案。

        数据源：`ctx.subgoal_trace`（SubGoalSolver 在 2.7 / 3_solve(P&E) 阶段写入；
        每项为 dict，含 id/title/description/type/expected_output/result）。

        空安全：无子目标 / 全部 result 为空 → 返回 ""（退回原主求解，零噪音）。
        开关：`enable_subgoal_findings`（已登记 switch_registry，默认 True）为
        False → 返回 ""。
        """
        if not _sw_bool("enable_subgoal_findings"):
            return ""
        trace = getattr(ctx, "subgoal_trace", None) or []
        if not isinstance(trace, list) or not trace:
            return ""
        items: list[str] = []
        for sg in trace:
            if not isinstance(sg, dict):
                continue
            _res = str(sg.get("result", "") or "").strip()
            if not _res:
                continue  # 空结论不注入（不占位、不制造"看起来有数据"的假象）
            _sid = sg.get("id", "")
            _title = str(sg.get("title", "") or "").strip()
            _exp = str(sg.get("expected_output", "") or "").strip()
            if len(_res) > self._SUBGOAL_FINDING_ITEM_CHARS:
                _res = _res[: self._SUBGOAL_FINDING_ITEM_CHARS].rstrip() + "…（截断）"
            _head = f"- 子目标 {_sid}「{_title}」"
            if _exp:
                _head += f"（应产出：{_exp}）"
            items.append(_head + f"\n  结论：{_res}")
        if not items:
            return ""
        body = "\n".join(items)
        if len(body) > self._SUBGOAL_FINDINGS_MAX_CHARS:
            body = (body[: self._SUBGOAL_FINDINGS_MAX_CHARS].rstrip()
                    + "\n…（其余子目标结论因过长省略）")
        # ★ 3.3：主求解指令 —— 在已确立的子目标结论基础上整合最终答案，且允许纠错。
        return (
            "【已确立的子目标结论】\n"
            "（以下为前面逐步求得的**关键中间数据 / 条件**，是本题求解的基础）\n"
            + body
            + "\n\n★ 请在**上面已确立的子目标结论**基础上，整合出本题的最终答案：\n"
            "  1) 这些结论就是要用的数据，**直接使用、不要从头再推一遍**；\n"
            "  2) 若整合过程中发现**某条子目标结论明显有误**（算错 / 前提误 /"
            " 与题意矛盾 / 明显不自洽），可以**指出并纠正**它，再据修正后的结论"
            "给出最终答案 —— **不要被错误的子目标结论绑死**；\n"
            "  3) 最终答案必须**建立在这些已确立结论之上**（一致时直接整合；"
            "不一致时说明以哪个为准及理由）。\n"
        )

    def _apply_subgoal_findings(self, ctx: TaskContext, text: str) -> str:
        """把子目标结论块追加到 `text` 末尾，并落 trace / metadata（三路径共用）。

        三条主求解生成路径（初始 `_generate_initial` / 证明 `_generate_proof` /
        重解 `_generate_revise`）都调用本方法，**复用同一渲染与埋点逻辑**，
        避免"只改一处路径=没改"（本项目已多次踩到）。

        空块（无子目标结论 / 开关关）→ **原样返回 `text`**（零改动、零噪音）。
        """
        block = self._render_subgoal_findings(ctx)
        if not block:
            return text
        _n = sum(
            1 for s in (getattr(ctx, "subgoal_trace", None) or [])
            if isinstance(s, dict) and str(s.get("result", "") or "").strip())
        self.record(ctx, "subgoal_findings",
                    "求解路径注入子目标结论 %d 字符（%d 条）"
                    % (len(block), _n))
        # 3.4：diag 埋点（由 orchestrator._collect_diag 导出为
        # `subgoal_findings_injected: {count, chars}`）。
        try:
            if isinstance(getattr(ctx, "metadata", None), dict):
                ctx.metadata["subgoal_findings_injected"] = {
                    "count": _n, "chars": len(block)}
        except Exception:  # noqa: BLE001
            pass
        return text + "\n\n" + block

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
        """表达式范式（2026-09-12，用户要求「默认生成方程式、不心算」）。

        解析模型输出的两行（【变量赋值】/【最终表达式】）：
            【变量赋值】x=5, y=3
            【最终表达式】2*x + y
        把赋值代入表达式 → **用本地精确计算内核（utils.math_eval）求值** → **答案取工具值**
        （模型原先写的数值被丢弃，仅在 reasoning 里留痕）。

        设计要点：模型**只负责建模**（设符号、给出算式），数值代入与运算
        全部由本地完成 —— 与"剥离"通道互补：剥离适用于题面有具体数据的题，
        本通道适用于参数是变量的题（B 类）。
        无这两行 / 求值失败 / 开关关闭 → 原样返回（零风险）。
        """
        try:
            if not getattr(self.config, "symbolic_solve_adopt", True):
                return resp, answer
            # 2026-09-12 逻辑堆叠治理③：客观题（选择/判断）的答案是选项字母或
            # 判断值，不是数值 —— 本关"工具代入求值"根本不适用。若模型按
            # 误写了【最终表达式】，会把选项答案改写成数值而丢分。
            _qt = getattr(ctx, "question_type", "") or ""
            # 2026-09-12 补漏：填空题同属客观题 —— 多空答案形如 `1, 2`，
            # 被本关覆盖成单个工具值会丢分（选择/判断上一轮已设防，填空漏了）。
            if _qt in ("选择题", "判断题", "填空题"):
                return resp, answer
            if not resp or "【最终表达式】" not in resp:
                return resp, answer
            import re as _re3
            m_e = _re3.search(r"【最终表达式】\s*(.+?)(?:\n|$)", resp)
            if not m_e:
                return resp, answer
            expr = m_e.group(1).strip().strip("$").strip().rstrip("。.")
            if not expr or len(expr) > 300:
                return resp, answer
            assigns: dict = {}
            m_v = _re3.search(r"【变量赋值】\s*(.+?)(?:\n|$)", resp)
            if m_v:
                for part in _re3.split(r"[,，;；、]", m_v.group(1)):
                    if "=" in part:
                        _k, _v = part.split("=", 1)
                        _k = _k.strip().strip("$").strip()
                        _v = _v.strip().strip("$").strip().rstrip("。.")
                        if _k and _v:
                            assigns[_k] = _v
            # ============================================================
            # 2026-09-13 修复（q3_mcp 实测实锤）：符号答案不得被数值代入覆盖。
            # 实况（official112 #001）：gold `2-2m`，模型原答 `\boxed{-2(m-1)}`
            # —— 二者恒等，**答案是对的**；但响应里同时写了自造的
            # 【变量赋值】m=3 与【最终表达式】-2*(3-1)，本关遂以工具值 -4
            # **覆盖**模型答案 → 判 expr_wrong。根因：参数题的答案含自由变量，
            # 对变量代一个具体值只是"特例"，根本不是题目要的答案。
            # 判据（零后悔）：模型自己的答案若**不是纯数值**（即符号式/含自由变量）
            # → 代入求值不可能产出答案 → 弃权，保留模型原答案，交下游既有把关。
            # 开关 EXPR_EVAL_GROUNDING_GUARD=0 可恢复旧行为（A/B 对照用）。
            # ============================================================
            if (_sw_bool("expr_eval_grounding_guard")
                    and answer and to_exact_number is not None
                    and to_exact_number(str(answer)) is None):
                self.record(
                    ctx, "expression_eval_skip",
                    f"表达式范式：模型答案为符号式（{str(answer)[:24]}），"
                    f"代入求值不适用，弃权保留模型原答案")
                return resp, answer
            # 符号 → 数值 代入（整词匹配，避免 x 误伤 exp）
            sub = expr
            for _k, _v in assigns.items():
                sub = _re3.sub(
                    r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % _re3.escape(_k),
                    "(%s)" % _v, sub)
            try:
                from utils.math_eval import safe_eval as _safe_eval_fn
            except ImportError:  # 提交包（submit/）路径兜底
                try:
                    from math_eval import safe_eval as _safe_eval_fn
                except ImportError:
                    return resp, answer
            raw = str(_safe_eval_fn(sub) or "")
            # 2026-09-12 定型前审核修复：**只采纳纯数值结果**。
            # 原实现用 findall 抓"最后一个数字"，当工具结果不是纯数值时会抓
            # 到碎片 —— `3*sqrt(5)`（精确根式）→ 取到 "5"、`2*x+3`（含变量）
            # → 取到 "3"、`WARN: …12…` → 取到 "12"；而本函数会把该值**直接
            # 写进【最终答案】**，等于把答案覆盖成一个错数。必须整串是数值才
            # 采纳，否则零后悔弃权（保留模型原答案）。
            _val_txt = raw.strip()
            for _pre in ("≈", "~", "="):
                _val_txt = _val_txt.lstrip(_pre).strip()
            if to_exact_number is None or to_exact_number(_val_txt) is None:
                self.record(ctx, "expression_eval_skip",
                            f"表达式范式：{expr[:60]} 工具结果非纯数值"
                            f"（{raw[:40]}），弃权保留模型原答案")
                return resp, answer
            val = _val_txt
            # 2026-09-12 逻辑堆叠治理（定型前审核）：本关已用本地计算器产出答案，
            # 登记标记让下游**不再重复处理**同一次计算：
            #   · _maybe_symbolic_solve 不会再重复建模/求解一遍并覆盖该答案。
            # 两者都是"答案取工具值"的同族机制，叠加只会白烧 LLM 时间与互相覆盖。
            if ctx is not None:
                try:
                    setattr(ctx, "_expr_eval_adopted", True)
                except Exception:  # noqa: BLE001  标记失败不影响主流程
                    pass
            self.record(ctx, "expression_eval",
                        f"表达式范式：{expr[:60]} 代入 {assigns} → {val}"
                        f"（答案取工具值，模型不参与计算；原答 {str(answer)[:24]}）")
            # 2026-09-12 逻辑堆叠治理②：resp 里若**已有**最终答案区块，必须
            # **替换**而不是在末尾追加 —— 否则会留下两个互相矛盾的【最终答案】
            # 标记，而下游 extract_final_answer 的正则取的是**第一个**（模型的
            # 心算旧值），本关刚采纳的工具值会被完全架空（已实测该正则行为：
            # `re.search(r"【最终答案】\s*\n?\s*([\s\S]+)")` 命中首个标记，
            # 且 first_line 分支直接返回其首行）；reasoning 注入下游时也会歧义。
            _new_resp = resp
            if "【最终答案】" in _new_resp:
                _new_resp = _re3.sub(r"【最终答案】[\s\S]*$",
                                     "【最终答案】" + str(val), _new_resp)
            else:
                _new_resp = _new_resp + "\n\n【最终答案】" + str(val)
            return _new_resp, val
        except Exception as exc:  # noqa: BLE001
            logger.debug("[solver] expression_eval 失败，保留原输出: %s",
                         str(exc)[:120])
            return resp, answer

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
        try:
            if not getattr(self.config, "symbolic_crosscheck_enabled", False):
                return resp, answer
            if (parse_symbolic_payload is None or evaluate_payload is None
                    or to_exact_number is None):
                return resp, answer
            if getattr(ctx, "_sym_cross_checked", False):
                return resp, answer
            want = to_exact_number(answer)
            if want is None:                    # 非纯数值答案 → 本关卡不适用
                return resp, answer
            problem = (getattr(ctx, "problem", "") or "").strip()
            if not problem:
                return resp, answer
            try:
                from .question_type import classify_question_type
            except ImportError:
                from question_type import classify_question_type
            if classify_question_type(problem) == "证明题":
                return resp, answer             # 证明题无数值答案，不适用
            if ctx is not None and ctx.gen_time_up():
                self.record(ctx, "symbolic_crosscheck", "跳过：生成侧时间到")
                return resp, answer
            setattr(ctx, "_sym_cross_checked", True)   # 每题只做一次
            raw = self._compressed_solve(
                ctx, SYMBOLIC_MODEL_SYSTEM,
                SYMBOLIC_MODEL_USER.format(problem=problem[:3000]),
                temperature=0.0,
                # 2026-10-02 DeepSeek 适配：兜底值 512 ⇒ 8192，与 config 默认同步。
                max_tokens=int(getattr(self.config, "symbolic_max_tokens", 8192)),
                prefill_seed=SYMBOLIC_JSON_SEED,
            )
            payload = parse_symbolic_payload(raw or "")
            value, why = (evaluate_payload(payload) if payload
                          else (None, "未解析出建模结果"))
            if value is None:
                self.record(ctx, "symbolic_crosscheck", f"跳过：{why}")
                return resp, answer
            got = to_exact_number(value)
            if got == want:
                self.record(ctx, "symbolic_crosscheck_pass",
                            f"独立建模复核一致：{why}；与答案 {str(answer)[:30]} 相符")
                return resp, answer
            self.record(ctx, "symbolic_crosscheck_mismatch",
                        f"独立建模得 {value}（{why}），与答案 "
                        f"{str(answer)[:30]} 不符，定向重问")
            if ctx is not None and ctx.gen_time_up():
                return resp, answer
            system = (
                "你是数学解题助手。有人**只依据题目条件**独立建模，把给定数值"
                f"抽象为变量后算出目标量应为 {value}，与你的最终答案不一致。"
                "请核对：若你的答案错了，请修正推导并给出新答案；"
                "若你认为独立建模有误，请指出其建模错在哪里，并维持你的答案。"
                "请核对后重写解答，并在末尾用【最终答案】给出结论。"
            )
            user = (f"题目：\n{problem[:2000]}\n\n"
                    f"你的解答片段：\n{(resp[-1200:] if len(resp) > 1200 else resp)}\n\n"
                    f"独立建模给出的目标量值为：{value}（依据：{why}）\n"
                    "请核对后重写解答并给出【最终答案】。")
            new_raw = self._compressed_solve(
                ctx, system, user, temperature=0.0,
                max_tokens=int(getattr(self.config, 'max_answer_tokens', 4096)),
            )
            if not new_raw or len(new_raw.strip()) < 10:
                return resp, answer
            new_ans = extract_final_answer(new_raw)
            if to_exact_number(new_ans) != got:
                self.record(ctx, "symbolic_crosscheck_keep",
                            "重问结果未落到独立建模真值 → 保留原答案")
                return resp, answer
            self.record(ctx, "symbolic_crosscheck_fix",
                        f"答案经独立建模修正：{str(answer)[:30]} → {value}")
            return new_raw, new_ans
        except Exception as exc:  # noqa: BLE001  失败保留原输出
            logger.debug("[solver] symbolic crosscheck 失败，保留原输出: %s",
                         str(exc)[:120])
            return resp, answer

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
        try:
            if not getattr(self.config, "symbolic_solve_enabled", False):
                return resp, answer
            if (strip_given_numbers is None or parse_symbolic_solve is None
                    or validate_payload is None or solve_with_tool is None
                    or to_exact_number is None):
                return resp, answer
            if getattr(ctx, "_sym_solve_done", False):
                return resp, answer
            # 2026-09-12 逻辑堆叠治理（定型前审核）：答案已由表达式范式（本地
            # 计算器）产出 —— 不再重复做一次符号建模 + 求解，避免同一答案被
            # 两条同族机制先后覆盖（谁生效取决于顺序，且白烧一次建模调用）。
            if getattr(ctx, "_expr_eval_adopted", False):
                self.record(ctx, "symbolic_solve_skip",
                            "答案已由表达式范式（本地计算器）产出，跳过重复建模求解")
                return resp, answer
            problem = (getattr(ctx, "problem", "") or "").strip()
            if not problem:
                return resp, answer
            # 只对"数值型答案"题目生效（证明题/文字结论不适用）
            want = to_exact_number(answer)
            if want is None:
                return resp, answer
            try:
                from .question_type import classify_question_type
            except ImportError:
                from question_type import classify_question_type
            if classify_question_type(problem) == "证明题":
                return resp, answer
            if ctx.gen_time_up():
                self.record(ctx, "symbolic_solve", "跳过：生成侧时间到")
                return resp, answer
            setattr(ctx, "_sym_solve_done", True)   # 每题只做一次

            # ① 数值剥离（本地，零 LLM）：题面 → 符号题面 + 本地参数表
            strip = strip_given_numbers(problem)
            if strip is None:
                self.record(ctx, "symbolic_solve_skip",
                            "题面无「显式给定参数」可剥离，本通道不适用")
                return resp, answer

            # ② 符号建模（1 次短调用；不合格带**具体原因**重试 1 次）
            # 2026-10-02 DeepSeek 适配：兜底值 384 ⇒ 8192，与 config 默认同步。
            max_tok = int(getattr(self.config, "symbolic_solve_max_tokens", 8192))
            payload, reason, previous = None, "", ""
            for attempt in range(2):
                if attempt == 0:
                    sys_p = SYMBOLIC_SOLVE_SYSTEM
                    usr_p = SYMBOLIC_SOLVE_USER.format(
                        problem=strip.problem[:3000])
                else:
                    sys_p = SYMBOLIC_SOLVE_RETRY_SYSTEM
                    usr_p = SYMBOLIC_SOLVE_RETRY_USER.format(
                        problem=strip.problem[:3000],
                        previous=(previous or "")[:600], reason=reason)
                if ctx.gen_time_up():
                    self.record(ctx, "symbolic_solve", "跳过：建模前生成侧时间到")
                    return resp, answer
                raw = self._compressed_solve(
                    ctx, sys_p, usr_p, temperature=0.0, max_tokens=max_tok,
                    prefill_seed=SYMBOLIC_SOLVE_SEED,
                )
                previous = raw or ""
                payload = parse_symbolic_solve(previous)
                ok, reason = validate_payload(payload, strip.params)
                if ok:
                    break
                self.record(ctx, "symbolic_solve_validate_fail",
                            f"第 {attempt + 1} 次建模不合格：{reason}")
                if payload is None:
                    break
            if payload is None:
                return resp, answer
            ok, reason = validate_payload(payload, strip.params)
            if not ok:
                self.record(ctx, "symbolic_solve_reject",
                            f"建模两次不合格，弃权：{reason}")
                return resp, answer

            # ③/④ 工具求解（本地，零 LLM）：数值回代 → 解方程（组）→ 精确值
            value, why = solve_with_tool(payload, strip.params)
            if value is None:
                self.record(ctx, "symbolic_solve_reject",
                            f"工具求解未成功：{why}")
                return resp, answer
            got = to_exact_number(value)
            if got is None:
                self.record(ctx, "symbolic_solve_reject",
                            f"工具结果非精确数值，弃权：{value}")
                return resp, answer
            self.record(ctx, "symbolic_solve_solved",
                        f"符号建模+工具求解成功：{why}")

            # ★ 2026-09-12 用户要求「把计算从模型手里拿走」（方案④正解）：
            # **工具求解成功 → 答案直接取工具值**，模型不参与计算。
            # 原设计只在"一致"时放行、"分歧"时才回传 → 最终答案仍可能是模型
            # 心算出来的值（工具只是事后核对，没有"接管"计算）。
            # 现改为：只要本地 SymPy 求出精确值，该值**就是**最终答案，
            # 模型原先给的数值被丢弃（保留在 reasoning 里供追溯）。
            # 回退：`--symbolic_solve_adopt false`（恢复"仅比对/回传"旧行为）。
            if getattr(self.config, "symbolic_solve_adopt", True):
                _tgt = str(payload.get("target") or "")
                _note = (f"\n\n【工具精确计算】{_tgt} = {value}"
                         "（该数值由本地计算器代入求解得出，非模型心算）")
                new_raw = ((resp or "") + _note) if (resp or "") else _note.strip()
                self.record(ctx, "symbolic_solve_adopt",
                            f"答案改用工具精确计算值 {value}"
                            f"（原答案 {str(answer)[:30]}；模型不参与计算）")
                return new_raw, value

            if got == want:
                self.record(ctx, "symbolic_solve_pass",
                            f"工具值与答案一致（{value}），模型未参与计算")
                return resp, answer

            # 分歧 → 1 次短回传（可关：symbolic_solve_feedback=0）
            if not getattr(self.config, "symbolic_solve_feedback", True):
                self.record(ctx, "symbolic_solve_mismatch",
                            f"工具值 {value} 与答案 {str(answer)[:30]} 不一致"
                            "（未回传）")
                return resp, answer
            if ctx.gen_time_up():
                self.record(ctx, "symbolic_solve_mismatch",
                            f"工具值 {value} 与答案不一致，但生成侧时间到，"
                            "保留原答案")
                return resp, answer
            eqs_txt = "\n".join(payload.get("equations") or []) or "（以 TARGET 为准）"
            new_raw = self._compressed_solve(
                ctx, SYMBOLIC_FEEDBACK_SYSTEM,
                SYMBOLIC_FEEDBACK_USER.format(
                    problem=problem[:1500], equations=eqs_txt,
                    target=payload.get("target") or "", value=value),
                temperature=0.0,
                max_tokens=int(getattr(self.config, "max_answer_tokens", 4096)),
            )
            if not new_raw or len(new_raw.strip()) < 10:
                self.record(ctx, "symbolic_solve_mismatch",
                            f"回传结果为空，保留原答案（工具值 {value}）")
                return resp, answer
            new_ans = extract_final_answer(new_raw)
            # 三重保险（防"盲从工具值"造成掉分）：
            #   ① 模型必须**显式确认建模正确**（ADOPT）；REJECT/无标记一律维持原答案
            #   ② 新答案的数值必须**正好落在工具值上**（模型不得改动数值）
            upper = new_raw.upper()
            if "ADOPT" not in upper:
                self.record(ctx, "symbolic_solve_keep",
                            f"模型未确认建模正确"
                            f"（{'REJECT' if 'REJECT' in upper else '无标记'}）"
                            f" → 保留原答案（工具值 {value}）")
                return resp, answer
            if to_exact_number(new_ans) != got:
                self.record(ctx, "symbolic_solve_keep",
                            f"回传后答案未落到工具值 {value} → 保留原答案")
                return resp, answer
            self.record(ctx, "symbolic_solve_fix",
                        f"答案按工具结果修正：{str(answer)[:30]} → {value}")
            return new_raw, new_ans
        except Exception as exc:  # noqa: BLE001  失败保留原输出
            logger.debug("[solver] symbolic solve 失败，保留原输出: %s",
                         str(exc)[:120])
            return resp, answer

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

        # ★ 2026-10-02（阶段一：子目标结论 → 主求解）：把 2.7 / 3_solve(P&E) 阶段
        # 已求得的子目标结论作为**中间数据**注入主求解提示词，让主答案建立在子目标
        # 之上（用户设计原话：「主求解一定要在子目标的基础上」）。
        # 位置：题目之后、答案格式引导之前 —— 紧贴题目，作为"已知数据"被读；不放
        #   提示词最末尾（避免模型进入续写模式，历史教训）也不早于题目（需贴题干语义）。
        # 空安全：无子目标结论时零噪音、零行为变化（helper 内部兜底）。
        # 只拼一次（与 error_lessons 同口径），retry / 多候选不重复注入。
        user_content = self._apply_subgoal_findings(ctx, user_content)

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

        # ★ 2026-09-29（截图 #3+#4）：Mathlib 定理检索结果注入。
        #
        # 背景（用户重点关切）：1.2_theorem_hint 阶段用 leansearch 到 Mathlib 检索
        # "本题该用的定理"，但在此之前 `ctx.theorem_hint_block` 只是**算出来放着**，
        # 从未拼进任何提示词 ⇒ 检索对大模型的实际影响恒为 0，A/B 必然测出"无差异"，
        # 用户要回答的「定理对大模型的推理效果如何」在结构上就无法被回答。
        # 本注入是该功能**产生作用**的唯一通道，没有它整条链只是空转埋点。
        #
        # 位置：题目之后、答案格式之后，但**早于** error_lessons / objective。
        #   · 不放最末尾：避免模型把定理清单当成"待续写的前文"；
        #   · 不早于题目：定理必须紧贴题目语义才可读。
        # 长度：检索侧已限制 top_k(5) × max_queries(2)，实测块长约 200–400 字符，
        #   相对题干本身不构成噪音；无命中时 block 为空串 ⇒ **零成本零噪音**。
        # 开关：`enable_theorem_hint`（与检索侧同一开关，关掉即整条链关闭）。
        if getattr(self.config, 'enable_theorem_hint', True):
            _th_block = (getattr(ctx, 'theorem_hint_block', '') or '').strip()
            if _th_block:
                user_content = user_content + "\n\n" + _th_block
                self.record(ctx, "theorem_hint",
                            "solver 主路径注入定理清单 %d 字符（%d 条）"
                            % (len(_th_block), len(getattr(ctx, 'theorem_hints', []) or [])))
                try:
                    if isinstance(getattr(ctx, "metadata", None), dict):
                        ctx.metadata["theorem_hint_injected"] = {
                            "len": len(_th_block),
                            "n": len(getattr(ctx, 'theorem_hints', []) or []),
                        }
                except Exception:  # noqa: BLE001
                    pass

        # 2026-09-06 易错点记忆注入（A 档轻量经验，prompts/error_lessons.py）：
        # 命中题型/关键词才注入自查清单（无命中返回空串=零噪音）。
        # 放 user 侧题目之后、_make_one 并行之前——只拼一次，retry 不加倍。
        if getattr(self.config, 'enable_error_lessons', True):
            lessons_block = error_lessons_block(ctx)
            if lessons_block:
                user_content = user_content + "\n\n" + lessons_block
                self.record(ctx, "error_lesson",
                            f"注入历史易错自查清单 {error_lesson_ids(ctx)}")


        # 题型差异化策略注入（v2.6）：
        #   选择题→选项逆推验证；判断题→不确定时合理猜测；
        #   证明题→逐步反复校验；解答题→附带答案结果检测；填空题→只输出结果。
        #
        # 2026-08-30（#45）：老师要求移除按题型分流、让 AI 按自身流程作答
        # （IMO 基本全为证明题，题型分支实测反而拉低证明题正确率）。
        # 此处改为 `enable_question_type_hint` 控制，**默认关闭**；需要 A/B
        # 对比或回归旧行为时置 True 即可，无需改代码。
        # 注：选择题的选项格式化属"输入信息补全"而非策略分流，故始终保留。
        # 2026-09-12 客观题特化（用户要求"保证能检测到题型并采取特化解题技巧"）：
        #   · 客观题（选择 / 判断 / 填空）与证明题的解题流程互斥，给它们注入
        #     特化纪律不触碰上面"证明题不分流"的既有结论；
        #   · 实测依据（official112 基线）：15 道客观题仅对 4 道——093/103 漏读
        #     E 项而缺项、101/111 判断方向反、102/106/110 概念题凭印象作答；
        #   · 开关 `objective_tactic_enabled`（默认 True）可一键回退旧行为，
        #     `enable_question_type_hint`（默认 False）仍可全题型强制开启。
        if getattr(ctx, 'question_type', ''):
            from .question_type import objective_injection
            _is_obj = ctx.question_type in ("选择题", "判断题", "填空题")
            _hint_on = bool(
                getattr(self.config, 'enable_question_type_hint', False)
                or (_is_obj and getattr(self.config, 'objective_tactic_enabled', True))
            )
            _inj = objective_injection(ctx.problem, ctx.question_type, _hint_on)
            if _inj:
                user_content = user_content + _inj
            # 埋点：客观题路由证据（题型 / 是否注入特化纪律 / 注入文本长度）。
            # 目的：让"是否真的走了特化策略"可被事后核验，而不是靠日志反推。
            try:
                if isinstance(getattr(ctx, "metadata", None), dict):
                    ctx.metadata["objective_route"] = {
                        "type": ctx.question_type,
                        "hint_injected": bool(_inj),
                        "injection_len": len(_inj),
                    }
                if _is_obj:
                    logger.info("[客观题路由] 题型=%s 注入=%d字符",
                                ctx.question_type, len(_inj))
            except Exception:  # noqa: BLE001
                pass

        # ★ 2026-09-15 补：**答案形态要求此前只注入子目标 / 蓝图路径，solver 主路径缺失**。
        # 本项目教训「只改一处路径 = 没改」：solver 是一条**独立的生成路径**，
        # 而上面注入的 `objective_injection` 只覆盖客观题（选择/判断/填空），
        # 于是解答题的形态要求（求所有→必须枚举 / 具体值→禁条件式 / 极值→严格性 /
        # 2026-09-15 新增的「哪些→完备性」）在**纯 solver 路径下根本没注入**。
        # 实测对应错题：099（"…离散化方法**有哪些**"，正解为多个，只答了一个）。
        # ⚠ 位置刻意放在 objective 注入之后、_ANSWER_GUIDE 之前：既不在提示词最末尾
        #   （避免模型进入续写模式），也不与客观题特化冲突（该函数对选择题/证明题返回空串）。
        try:
            from .question_type import answer_form_requirement as _afr_sv
            _afr_txt = _afr_sv(ctx.problem, getattr(ctx, 'question_type', '') or '')
            if _afr_txt:
                user_content = user_content + _afr_txt
                if isinstance(getattr(ctx, "metadata", None), dict):
                    ctx.metadata["answer_form_injected_solver"] = len(_afr_txt)
                self.record(ctx, "answer_form",
                            "solver 主路径注入答案形态要求 %d 字符" % len(_afr_txt))
        except Exception:  # noqa: BLE001
            pass

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
                # 2026-09-13 循环时间检查（防卡死）：单题上限已从 1200s 放开到
                # 3600s，必须在循环边界查时间，否则"单次 LLM 200-300s × 多次重试"
                # 会悄悄穿掉整题预算（实测 3_solve 曾超预算 1.7×）。
                # 只对"重试"生效（retry>0），保证首轮一定被尝试。
                if retry > 0 and ctx.gen_time_up():
                    self.record(ctx, "solver",
                                f"候选 {cid} 生成重试因时间到点提前停止")
                    break
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
                    # 9/4：平台不限 token，去 16384 帽（截断=腰斩丢分），收敛到 policy_max_tokens
                    max_tokens=self._adaptive_max_tokens(
                        ctx, self.config.policy_max_tokens),
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
        # 2026-09-13 修复（实测"单题预算被跨墙 421s"的根因）：
        # 原实现**一次性把 count(6) 个候选全部 submit**，而线程池只有 2 个 worker
        # ⇒ 6 / 2 × 单次最坏 360s（`LLMClient` 180s × 重试 1）= **最坏 1080s**；
        # 且 `as_completed` 循环内**没有任何时间检查**、已提交任务**无法取消**
        # ⇒ 生成侧软截止 `gen_time_up()` 在这一整段**完全失效**。
        # 实测后果：004 实耗 1171s 而其 `soft_budget` 只有 750s（**超 421s**）、
        # 010 超 182s、016 超 87s —— 每题都越过自己的软预算。
        # 改为**分批提交 + 批间检查**：每批 `max_workers` 个，批间查生成侧截止，
        # 到点即停止提交剩余候选；**已产出的候选照常进入后续验证**（既有语义不变）。
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            _pending = list(range(count))
            while _pending:
                if results and ctx.gen_time_up():
                    self.record(ctx, "solver",
                                f"生成侧时间到，跳过剩余 {len(_pending)} 个候选"
                                f"（已完成 {len(results)}/{count}）")
                    break
                _batch, _pending = _pending[:max_workers], _pending[max_workers:]
                _futs = [pool.submit(_make_one, i) for i in _batch]
                for _f in as_completed(_futs):
                    results.append(_f.result())
        results.sort(key=lambda x: x[0])

        for cid, resp, is_fallback in results:
            if resp is None or (is_fallback and _is_refusal(resp)):
                # 2026-09-13 晚（用户硬要求「无论超没超时都要把答案生成出来」）：
                # 原实现在此 append 一个
                #   Candidate(id=cid, answer="",
                #             reasoning="[生成失败] 调用受限或模型拒绝回答")
                # 的**占位候选**，造成两个后果（4 题实测里 010/016 全中）：
                #   ① `ctx.candidates` 因此**非空** ⇒ orchestrator 的
                #      「Solver 未产出候选 → 触发兜底直接求解」（orchestrator.py:1158）
                #      永不触发；`_emergency_direct_solve` 那一整条路被绕开；
                #   ② formatter 的 `_REFUSAL_RE` 旧版不含这几个词 ⇒ 占位文本被当作
                #      合法答案直接提交，`predicted` 就是这串占位符。
                # 现改为：先尽力从残缺响应里抢救一个真实答案；抢救不到就**不 append**，
                # 让 `ctx.candidates` 保持空，把控制权交给下游兜底链
                # （orchestrator `_fallback_direct` → formatter `_emergency_answer`
                #  → user_agent 最终兜底）。
                _salvaged = ""
                if resp is not None and str(resp).strip():
                    _txt = str(resp)
                    try:
                        _salvaged = extract_final_answer(_txt) or ""
                        if not _salvaged and rescue_final_answer is not None:
                            _salvaged = rescue_final_answer(_txt)[0] or ""
                        if not _salvaged and smart_fallback_answer is not None:
                            _salvaged = smart_fallback_answer(_txt) or ""
                    except Exception:  # noqa: BLE001
                        _salvaged = ""
                _salvaged = (_salvaged or "").strip()
                if _salvaged and not _is_refusal(_salvaged) and len(_salvaged) <= 300:
                    ctx.candidates.append(Candidate(
                        id=cid, answer=_salvaged, reasoning=str(resp)))
                    logger.warning(
                        "Candidate %d 生成失败但抢救到答案: %s", cid, _salvaged[:60])
                else:
                    logger.warning(
                        "Candidate %d generation failed/skipped（无可用答案，"
                        "交由下游兜底）", cid)
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
                    and not ctx.gen_time_up()):
                answer = self._reask_final_answer(ctx, resp, answer)
            # ★ 表达式范式（默认形态，9/12 用户要求）：模型只建模（设符号+给算式），
            # 数值代入与运算由本地完成 → 答案取工具值。
            resp, answer = self._maybe_expression_eval(ctx, resp, answer)
            # 2026-09-10 L2：独立符号建模复核（默认关；每题最多一次）
            resp, answer = self._maybe_symbolic_crosscheck(ctx, resp, answer)
            # 2026-09-12 符号化方程求解通道（默认关）：模型只交方程（组）+ 目标，
            # 数值一律由本地 SymPy 回代求出（模型不参与计算），异议时回传工具结果。
            resp, answer = self._maybe_symbolic_solve(ctx, resp, answer)
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
    def _generate_revise(self, ctx: TaskContext, cap: int = None) -> None:
        feedback_text = "\n".join(f"- {fb}" for fb in ctx.revise_feedback)
        # 2026-09-06 易错点记忆注入（revise 补救侧）：修订时同步带上同类题
        # 历史易错自查清单（命中才注入），让重解不只针对反馈、也避开已知坑。
        if getattr(self.config, 'enable_error_lessons', True):
            lessons_block = error_lessons_block(ctx)
            if lessons_block:
                feedback_text = feedback_text + "\n" + lessons_block
                self.record(ctx, "error_lesson",
                            f"revise 注入历史易错自查清单 {error_lesson_ids(ctx)}")
        count = cap if cap is not None else self.config.revise_sample_times
        # ⚠ A 修复（2026-09-12）：**候选池满时先腾位，而不是静默 return**。
        # 依据：6.5 的「拒绝 → 换候选 / 重解」是唯一的纠错回路，但 candidates
        # 常态就是 6 个 → `6 - len(candidates)` = 0 → count=0 → return
        # → **最需要重解时反而重解不了**（实测 revise_round 恒为 0，反馈白给）。
        _room = 6 - len(getattr(ctx, "candidates", None) or [])
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
            _room = 6 - len(ctx.candidates)
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

        # ★ 2026-09-17（M7）：把「上一轮解答」**真正**喂给 revise。
        # REVISE_SYSTEM 第 1/3 条明确要求“认真阅读【上一轮错误解答】”「保留正确的
        # 推理部分」，但 user 模板此前**只有题目 + 反馈** ⇒ 模型无从保留，只能整题
        # 重解。这正是 revise 越改越差的机制之一（013 蓝图 d=50 → revise 改成 19、
        # 025 蓝图 4 → 直答 509040-2*169680）。此处给出上一轮各候选的答案清单
        # 与主推理尾部，使“保留正确部分”成为可执行指令。
        _prev_lines = []
        for _pc in (getattr(ctx, "candidates", None) or [])[:6]:
            _pa = str(getattr(_pc, "answer", "") or "").strip()
            if _pa:
                _prev_lines.append("· 候选#%s 答案：%s"
                                   % (getattr(_pc, "id", "?"), _pa))
        _cs_all = list(getattr(ctx, "candidates", None) or [])
        _main_reasoning = ""
        if _cs_all:
            _main_reasoning = max(
                (str(getattr(_c2, "reasoning", "") or "") for _c2 in _cs_all),
                key=len)
        _prev_block = "\n".join(_prev_lines) or "（无——本轮无既有候选答案）"
        if _main_reasoning:
            _prev_block += ("\n\n（上一轮主推理尾部 1200 字，供沿用正确结论）\n"
                            + _main_reasoning[-1200:])

        def _make_one(i: int):
            cid = base_cid + i
            user_content = REVISE_USER_TEMPLATE.format(
                problem=ctx.problem, feedback=feedback_text,
                prev_answer=_prev_block)
            # ★ 2026-09-29：revise 是**独立于 _generate_initial 的生成路径**，
            # 不注入则"重解一次"会把定理线索丢掉（本项目教训：只改一处路径=没改）。
            if getattr(self.config, 'enable_theorem_hint', True):
                _th = (getattr(ctx, 'theorem_hint_block', '') or '').strip()
                if _th:
                    user_content = user_content + "\n\n" + _th
            # ★ 2026-10-02（阶段一补）：重解同属"主求解"，不带子目标结论=又从头推
            # 一遍。复用同一注入逻辑（含 diag 埋点）。
            user_content = self._apply_subgoal_findings(ctx, user_content)
            for retry in range(3):
                # 2026-09-13 循环时间检查（防卡死）：同 _generate_initial 处说明。
                # 本函数在线程池内并行执行，到点即 break，避免"重试 × 并行"叠加穿预算。
                if retry > 0 and ctx.gen_time_up():
                    self.record(ctx, "revise",
                                f"revise 候选 {cid} 重试因时间到点提前停止")
                    break
                # v2.4.1：revise 也走 prefill（完整 CoT 在本环境必然超时）
                # 2026-09-04：prefill 种子与 REVISE_SYSTEM 五段格式对齐——【错误分析】开头
                resp = self._compressed_solve(
                    ctx, REVISE_SYSTEM, user_content,
                    temperature=self.config.policy_temperature,
                    max_tokens=self._adaptive_max_tokens(
                        ctx, self.config.policy_max_tokens),
                    prefill_seed="【错误分析】\n",
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
        # 2026-09-13：与 `_generate_initial` 同款修复 —— 改**分批提交 + 批间检查**。
        # 原实现一次性提交全部候选且 `as_completed` 内无任何时间检查、已提交任务无法取消
        # ⇒ 生成侧软截止 `gen_time_up()` 在这段失效（该病理已在 3_solve 实测造成
        # 单题超出软预算 421s，见 `_generate_initial` 处注释）。
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            _pending = list(range(count))
            while _pending:
                if results and ctx.gen_time_up():
                    self.record(ctx, "revise",
                                f"生成侧时间到，跳过剩余 {len(_pending)} 个修正候选"
                                f"（已完成 {len(results)}/{count}）")
                    break
                _batch, _pending = _pending[:max_workers], _pending[max_workers:]
                _futs = [pool.submit(_make_one, i) for i in _batch]
                for _f in as_completed(_futs):
                    results.append(_f.result())
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

        n_ok = 0
        _imp_min_remaining = float(
            getattr(self.config, "improve_min_remaining", 0.0) or 0.0)
        for cand in targets:
            # 2026-09-06：升级 gen_time_up——仅 is_time_critical 会在单候选
            # 300s 级 LLM 调用前放行最后 1-2 个候选，烧穿剩余预算（冒烟
            # nt-031 3.3=595s / algebra-003 3.3=325s 实证），须按生成侧软截止停。
            # N1''（2026-09-11 修正）：**改回硬墙口径**。原因：外层（orchestrator）
            # 已判定 3.3 该跑（用 time_remaining 门槛放行），但 3.3 排在 2.7/3_solve
            # 之后，而 gen_time_up() 用的是 _gen_deadline(=deadline−480s)=720s——
            # 走到这里必然已越过 → 内层立刻 break → 外层放行被作废（smoke6_v2
            # 六题 3.3 恒为 0s 的最终原因）。改为只防"逼近 1200s 硬墙"。
            if ctx.is_time_critical():
                break
            # 2026-09-07（A，冒烟 alg-060 3.3=640s 烧穿实证）：单候选改进
            # 是一次 200-300s 不可打断的 LLM 调用——仅靠 gen_time_up（=烧到
            # 生成软截止才停）会让"正在跑的最后一个候选"把验证预留吃光，
            # 6.5 终局 Lean/Audit 闸门 time_critical 饿死。
            # 预留 single-call 最坏成本：距生成软截止不足 improve_min_remaining
            # （默认 300s）即停手不再开新候选，把验证预算完整留给 4_verify+6.5。
            # N1''（2026-09-11 修正）：**基准改为硬墙 deadline，而非 _gen_deadline**。
            # 原因同 L37：_gen_deadline(720s) 是"生成类"的统一截止，3.3 走到这里
            # 必然已越过，用它做差会出现负值 → 恒 break（第三层拦截，实测默认
            # improve_min_remaining=300 时 100% 触发）。改用 deadline(1200s) 起算，
            # 语义仍是"给单候选最坏成本留够余量"，但不会在 3.3 处必然失败。
            _hd = float(getattr(ctx, "deadline", 0.0) or 0.0)
            if (_imp_min_remaining > 0 and _hd >= 10**8
                    and _hd - time.time() < _imp_min_remaining):
                # ⚠ 2026-09-30 修正阶段名：原写 `"paper_pacer"` —— 但这里判的是
                #   **单题硬墙余量**，与已删除的 PaperPacer（全卷配速）毫无关系。
                #   错误阶段名的后果：诊断按 step 聚合时，这条记录会被算进
                #   `paper_pacer` 桶，而该桶在 PaperPacer 删除后本应只剩全卷配速
                #   那几行 ⇒ 归因时把"自改进因时间停手"误读成"全卷配速在收紧"。
                self.record(ctx, "self_improve",
                            f"Step2 自改进停手：距硬墙 {_hd - time.time():.0f}s < "
                            f"{_imp_min_remaining:.0f}s（单候选最坏成本预留），"
                            f"不再改进剩余候选")
                break
            user_content = SELF_IMPROVE_USER.format(
                problem=ctx.problem,
                candidate_solution=cand.reasoning,
            )
            # 2026-09-04：prefill 种子与 SELF_IMPROVE_USER 三步法对齐——【第一步：诊断】开头
            resp = self._compressed_solve(
                ctx,
                get_policy_system(use_blueprint=getattr(self.config, "use_blueprint", True)),
                user_content,
                temperature=0.1,
                max_tokens=self._adaptive_max_tokens(
                    ctx, self.config.policy_max_tokens),
                prefill_seed="【第一步：诊断】\n",
            )
            if not resp or not resp.strip():
                # 观测埋点（2026-09-11）：3.3 此前只报"完成 N 个"，失败出口
                # （空/拒绝/过短）**全部静默 continue** → 跑了几百秒却看到 n_imp=0
                # 却无从定位（smoke6_v3 实证：3.3=365s 但"自改进完成"0 条）。
                self.record(ctx, "self_improve",
                            f"Step2 丢弃候选#{getattr(cand, 'id', '?')}：空响应")
                continue
            if _is_refusal(resp):
                self.record(ctx, "self_improve",
                            f"Step2 丢弃候选#{getattr(cand, 'id', '?')}：模型拒绝作答")
                continue
            # 改进版比原版还差（明显更短/空壳）则丢弃
            _thr = max(40, len(cand.reasoning) // 3)
            if len(resp.strip()) < _thr:
                self.record(ctx, "self_improve",
                            f"Step2 丢弃候选#{getattr(cand, 'id', '?')}：输出过短"
                            f"（{len(resp.strip())} < 门槛 {_thr}）")
                continue
            answer = extract_final_answer(resp)
            if not answer or len(answer) > 300:
                answer = rescue_final_answer(resp)[0]
            if not answer:
                answer = smart_fallback_answer(resp)
            # B 方案（2026-09-11，本地实验）：**覆盖前先把原版保留为独立候选**。
            # 依据：smoke6_v3 实证 098 原候选答 B（正确），3.3 自改进后被改成 D
            # （错误）——「无条件替换」会把好答案直接改坏，且没有任何回退机制。
            # 现在改为"原版 + 改进版并存"，交由下游验证/投票择优（不改变下游逻辑）。
            # 开关：SELF_IMPROVE_KEEP_ORIGINAL（默认 1）。
            if _sw_bool("self_improve_keep_original"):
                try:
                    import copy as _copy
                    _orig = _copy.copy(cand)
                    _orig.id = 1 + max(
                        [int(getattr(c, "id", 0) or 0) for c in ctx.candidates] or [0])
                    _orig.self_improved = True      # 防对同一份再改进
                    _orig.source = (getattr(cand, "source", "") or "") + "+pre_improve"
                    ctx.candidates.append(_orig)
                    self.record(ctx, "self_improve",
                                f"Step2 保留原版候选#{_orig.id}"
                                f"（答案 {str(getattr(_orig, 'answer', ''))[:30]}），"
                                f"改进版写入#{getattr(cand, 'id', '?')}")
                except Exception as _ce:  # noqa: BLE001
                    self.record(ctx, "self_improve",
                                f"Step2 保留原版失败（{type(_ce).__name__}）→ 走覆盖")
            cand.reasoning = resp
            if answer:
                cand.answer = answer
            # 2026-09-01（SU-01 优化 2）：标记 self_improved，下次再调 Step2 跳过此候选
            cand.self_improved = True
            n_ok += 1
            time.sleep(0.3)  # 速率限制

        if n_ok:
            self.record(ctx, "self_improve",
                        f"Step2 自改进 {n_ok}/{len(targets)} 个候选"
                        f"（无条件={not bool(getattr(self.config, 'self_improve_conditional', False))}）")
        elif targets:
            self.record(ctx, "self_improve",
                        f"Step2 本轮 {len(targets)} 个候选全部未产出改进")
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
                    new_list.append(new_c)
                    completed += 1
                    self.record(ctx, "complete", f"候选 #{c.id} 截断续写成功")
                    continue
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
