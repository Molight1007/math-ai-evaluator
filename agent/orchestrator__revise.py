# -*- coding: utf-8 -*-
"""深复核 / revise 回环职责簇（2026-10-09 批12：从 agent/orchestrator.py 逐字搬出）。

搬出方法：_review_bug_feedback / _deep_revise_loop / _deep_revise_loop_inner /
_build_revise_feedback / _revise_rounds / _update_accept_gate

**纯搬迁**：方法体逐字搬入（tokenize-aware 去缩进，多行 docstring 字符串值不变），
签名原样保留；Orchestrator 内保留**同名一行委托** ⇒ 调用点零改。

耦合处理：
  · `TaskContext`（.base）与 `_clip_review_prose`（.verifier，verifier 不 import
    orchestrator，无环）⇒ 新模块顶层同名导入（同源）；
  · 引用 orchestrator **模块级**函数 `_sw_bool_or`/`_sw_num_or`/
    `_merge_review_into_feedback`/`_answer_fingerprint` ⇒ 各自函数内**加惰性 import**
    （本仓既定模式，单一来源仍在 orchestrator，非复制）。
"""
from __future__ import annotations

import time

from .base import TaskContext
from .verifier import _clip_review_prose


def _review_bug_feedback(self, ctx: TaskContext, feedback: str) -> str:
    """Step 4：让模型复核验证器的缺陷反馈，可驳回误报（论文流水线）。

        论文（Huang & Yang 2025）：验证器产出的 bug report 不一定全对，
        模型复核后可驳回误报——避免好答案被错误反馈引导改坏。
        返回复核后**保留的缺陷清单**（非空）；复核失败/复核判定无实质缺陷时
        返回**空串**（由调用方据此结束 revise）。

        ★ 2026-10-06 修（**模型裸输出无上限直接灌进提示词**）：
          实测 official112-007 本题，本函数返回了 **157,550 字符**
          （英文独白 + 同一条 Lean 消息重复几十遍）；随后经 `ctx.revise_feedback`
          被 `solver._generate_revise` **原样拼进提示词** ⇒ 提示词被灌爆。
          现对返回加长度上限，并**保头**截断（复核结论在开头：要么「无实质缺陷」、
          要么「保留的缺陷清单」）。上限与 verifier 复核反馈同口径，
          精确数字见下方 `_cap` 注释。
        """
    if not feedback or len(feedback) < 10:
        return feedback
    if not getattr(self.config, 'enable_feedback_review', True):
        return feedback
    # 候选：用最佳候选的 reasoning 作复核依据
    cand_text = ""
    bc = getattr(ctx, '_best_cluster', None)
    if bc is not None and getattr(bc, 'rep_candidate', None) is not None:
        cand_text = str(getattr(bc.rep_candidate, 'reasoning', ''))[:900]
    if not cand_text and ctx.candidates:
        cand_text = str(getattr(ctx.candidates[0], 'reasoning', ''))[:900]
    user_msg = (
        f"【题目】\n{ctx.problem}\n\n"
        f"【当前解答（节选）】\n{cand_text}\n\n"
        f"【验证器给出的缺陷反馈】\n{feedback}\n\n"
        "请逐条复核上述缺陷反馈是否属实：\n"
        "- 属实（真实存在且影响正确性）→ 保留该条\n"
        "- 误报（与解答不符或判断错误）→ 驳回该条\n"
        "只输出复核后保留的缺陷清单，若全部误报则输出：无实质缺陷")
    raw = self.llm(ctx, [
        {"role": "system",
         "content": "你是严谨的数学复核员，只客观判断缺陷反馈是否属实。"},
        {"role": "user", "content": user_msg},
    ], temperature=0.0, max_tokens=32768)
    if not raw or not raw.strip():
        return feedback
    reviewed = raw.strip()
    # ★ 2026-10-06 长度上限（治「157,550 字符裸输出」）。
    # 口径与 verifier 的复核反馈**保持一致**（已核实确切数字）：
    #   · `verifier.py:1821` 结构化分支（缺陷清单 + 复核依据）= `[:8000]`；
    #   · `verifier.py:1825` 单行标签分支（标签 + 复核推理）= `[:6000]`。
    # 本函数产出的是**缺陷清单**（与结构化分支同类产物），故取 **8000**。
    # 保头截断（结论在开头），末尾加标记；开关 `feedback_review_max_chars`
    # 默认 8000，置 0 = 不截断（回退旧行为的 A/B 抓手）。
    _reviewed_raw_len = len(reviewed)
    if "无实质缺陷" in reviewed:
        # ★ 2026-09-17（泛化句）：返回**空串** = "复核未发现实质缺陷"。
        # 原返回一句泛化建议「解答已较完整，请重新审题核对计算细节后给出最终答案。」，
        # 它被当作 revise 反馈 ⇒ **信息量为零的盲目重解**（实测 099 的
        # `diag.revise_feedback[0]` 正是这句），白烧一轮"生成 + 验证"。
        # 改由调用方据此**结束 revise**，而不是拿它去空转。
        self.record(ctx, "review",
                    f"复核判定无实质缺陷 → 不做盲目重解（2026-09-17）"
                    f"（原始 {_reviewed_raw_len} 字符）")
        return ""
    # ★★ 2026-10-06 C 项（**复核者的「越权结论 + 重做正文」被模型照抄**）：
    #   实测题 000 复核输出含「① 原答案 40 错误，**正确答案应为 0。下面给出
    #   严谨证明。** 证明：设 G 为题中描述的图…（其后 2000+ 字符是复核者自己
    #   重做了一遍的解答）」；trace 完整记录：`[review] 反馈复核完成：…正确答案
    #   应为 0…` → `[revise] 重解启动` → **最终答 `\boxed{0}`，标准答案 20460**。
    #   ⇒ 模型照抄了复核者给出的"正确答案"。两重问题：
    #     ①「正确答案应为 X」是**结论性断言**（验证器越权替解答下结论，违反其
    #        系统提示词「绝不要试图纠正你发现的错误或填补漏洞」）；
    #     ② 其后附**完整重做正文**，模型可整段照抄。
    #   verifier 侧已有 `_clip_review_prose` 专裁这两样，但只作用于 verifier 的
    #   深复核原文；本函数产出并**并入反馈**的复核清单此前**没走这道清洗**。
    #   现直接复用同一函数（不复制正则，避免两处口径分叉）。
    #   开关 `feedback_review_clip` 默认 True；`_clip_review_prose` 是**保守**的：
    #   无标记时原样返回，只裁「重做正文」与「越权结论断言」，不误删缺陷清单
    #   （缺陷清单形态「位置：… 问题：…」不含那两类标记）。
    if getattr(self.config, 'feedback_review_clip', True):
        reviewed = _clip_review_prose(reviewed)
    _cap = int(getattr(self.config, 'feedback_review_max_chars', 8000) or 0)
    if _cap > 0 and len(reviewed) > _cap:
        reviewed = reviewed[:_cap] + "\n…（已截断）"
    self.record(ctx, "review",
                f"反馈复核完成: {reviewed[:60]}"
                f"（原始 {_reviewed_raw_len} 字符 → 清洗+截断后 "
                f"{len(reviewed)} 字符）")
    return reviewed


def _deep_revise_loop(self, ctx: TaskContext, ver_result: dict,
                      tier_votes: int, force: bool = False) -> bool:
    """revise 自纠错回环的**计时包装**（2026-10-07，问题 2.8 修复）。

        背景：`_deep_revise_loop` 由 4 个阶段共享调用（P1@4_verify / 4.6 对抗 /
        5 / 5.5），而 `_stage_start` 只在阶段入口打点 ⇒ revise 的耗时被记进**调用方
        阶段**。实测题 001 `4_verify=5546s` vs `5_revise_or_fallback=7.4e-06s`
        （revise_round=4）；题 000 从 5 段调用则记进 5 段（3683s）—— 同机制两种归属。
        本包装把回环实际墙钟统一归到 `5_revise_or_fallback`，并从调用方阶段扣减
        （见 `_reassign_stage_time`）。开关 `stage_timer_reassign_revise`=0 回退旧埋点。
        行为（返回值/流程）与包装前完全一致。
        """
    from .orchestrator import _sw_bool_or  # noqa: F401 （惰性；单一来源仍在 orchestrator）
    _t0 = time.time()
    try:
        return self._deep_revise_loop_inner(ctx, ver_result, tier_votes,
                                            force=force)
    finally:
        try:
            if _sw_bool_or("stage_timer_reassign_revise", True):
                self._reassign_stage_time(
                    ctx, "5_revise_or_fallback", time.time() - _t0)
        except Exception:  # noqa: BLE001  纯埋点，绝不阻断
            pass


def _deep_revise_loop_inner(self, ctx: TaskContext, ver_result: dict,
                            tier_votes: int, force: bool = False) -> bool:
    """deep 档 0 正确票时的 revise 自纠错回环。

        用验证器反馈驱动定向修正：最多 deep_revise_rounds 轮，
        每轮 solver 走 _generate_revise 重解 + verifier 重新验证。
        返回是否在回环中获得至少 1 个候选获得正确票。
        """
    # ★ 2026-10-13 **接线 C**（方案 v4 §3.9.5）：把「池空错误总账」转成重解反馈。
    #   为什么：`ctx.pool_empty_errors`（批次 4）此前**只落盘、无消费者**（审核报告点名）。
    #   走**既有** `audit_reject_feedback` 管道（`_generate_revise` 会读取它）——
    #   不新增管道、不改 `_generate_revise` 签名。
    #   目的（用户 Q32/Q33）：让模型**先看到全部错误点 → 再重新生成**。
    try:
        _pe = list(getattr(ctx, "pool_empty_errors", None) or [])
        if _pe and not getattr(ctx, "_pool_empty_feedback_used", False):
            _lines = ["【候选池为空 —— 各环节淘汰原因汇总"
                      "（请先据此定位自己的错误点，再重解）】"]
            for _it in _pe[:12]:
                if isinstance(_it, dict):
                    _lines.append("- [%s] %s" % (
                        _it.get("stage") or "?", str(_it.get("error") or "")[:200]))
            ctx.audit_reject_feedback = list(
                getattr(ctx, "audit_reject_feedback", None) or []) + _lines
            ctx._pool_empty_feedback_used = True
            self.record(ctx, "pool_empty",
                        "池空错误总账已转成重解反馈（%d 条，经 audit_reject_feedback 管道）"
                        % len(_pe))
    except Exception as _e_c:  # noqa: BLE001  接线是增益，绝不阻断
        self.record(ctx, "pool_empty",
                    "池空反馈接线异常（已忽略）: %s" % str(_e_c)[:100])
    from .orchestrator import _merge_review_into_feedback  # noqa: F401 （惰性；单一来源仍在 orchestrator）
    max_rounds = getattr(self.config, 'deep_revise_rounds', 1)
    if max_rounds <= 0 or ctx.state.emergency:
        # ★ 2026-10-07 分支静默跳过埋点（问题总账 §2.6「隐形门控」）：原为裸
        #   `return False` ⇒ revise 回环被这道闸挡下时**0 痕迹**（与"回环跑了但
        #   没拿到正确票"不可区分）。此处仅记录原因，返回值与行为不变。
        self.record(ctx, "revise",
                    "revise 回环跳过："
                    + ("deep_revise_rounds<=0" if max_rounds <= 0
                       else "emergency 状态"))
        return False
    # 2026-09-02 老师需求：revise 全局轮数上限 5（revise_round 跨主路径累计）
    # ★ 2026-09-17（Audit-1）：全局轮数上限改由 `max_revise_rounds` 提供
    #（原先硬编码 5，而同名 config 字段全仓零读取点 ⇒ `--revise_rounds` 静默失效）。
    # 默认 5 与旧行为一致；`<=0` 表示不设全局上限（研究阶段可选）。
    _max_total = int(getattr(self.config, 'max_revise_rounds', 5) or 5)
    if _max_total > 0 and getattr(ctx, 'revise_round', 0) >= _max_total:
        self.record(ctx, "revise",
                    f"revise 已达全局上限 {_max_total} 轮（max_revise_rounds），不再继续")
        return False
    # ★ 2026-09-17（Z6）：**同一次「轮次 + 答案」不重复 revise**。
    # 实测 5) 段（全 0 票强制重解）与 5.5（低置信强制复核）会在**同一趟流程**里
    # 先后调用本函数；全 0 票时两处触发条件同时成立 ⇒ 同一批候选、同一答案被
    # revise 两遍，第二轮必然拿到同样的反馈、做同样的事。
    # 量级：`5_revise_or_fallback 1705s + 5.5_low_conf 1942s` 合计占全量 21.6%。
    # 去重键 = (revise_round, final_response)：相同即本趟已跑过，直接返回。
    # `force=True`（P1 应急重解）是调用方**显式要求**的，不参与去重。
    if not force:
        # ★ 2026-09-21 修复去重键：**去掉 revise_round** —— 它由本函数自身在
        #   下方 `ctx.revise_round += 1` 递增，拿它入键等于**自毁去重**：
        #   5) 段跑完 revise_round 变 1，5.5 段带着 1 再进来键就不同 ⇒ 必然
        #   重复整轮回环。实测 0921 arm2c2t 001：`5_revise_or_fallback` 668s
        #   + `5.5_low_conf` 655s = 1323s，占该题 41%（两段各跑一次完整回环）。
        #   去重语义本就是"本趟对**同一答案**不重复 revise"，答案相同即命中；
        #   轮次仅用于日志展示（下方 record 仍打印当前 round）。
        _pass_key = str(getattr(ctx, "final_response", "") or "")
        _seen = getattr(ctx, "_revise_pass_keys", None)
        if not isinstance(_seen, set):
            _seen = set()
            try:
                ctx._revise_pass_keys = _seen
            except Exception:  # noqa: BLE001
                _seen = None
        if _seen is not None:
            if _pass_key in _seen:
                self.record(ctx, "revise",
                            "同一答案（round=%d）本趟已 revise 过 → 跳过重复回环"
                            "（Z6 去重键修复 2026-09-21）"
                            % int(getattr(ctx, "revise_round", 0) or 0))
                return False
            _seen.add(_pass_key)
    feedback = self._build_revise_feedback(ctx, ver_result, force)
    # Step 4：复核验证器反馈（可驳回误报），避免被错误反馈误导修正。
    # 仅当反馈非空且预算允许时做（deep 档 +1 次调用，回环前只做一次）。
    _reviewed_empty = False
    if (not ctx.is_time_critical()
            and len(feedback) > 10):
        _rv = self._review_bug_feedback(ctx, feedback)
        if _rv:
            # ★★ 2026-10-06 修（**复核把深复核推理整段摘要掉，两处修复互相抵消**）：
            #   上游 `verifier.py:1819-1821` 已把「深复核推理」保留进 feedback ——
            #   尾段 6000 字符推理 + 判定段，以
            #   `【复核依据（判错报告原文摘录）】` 为标题，整体上限 8000
            #   （`_clip_review_prose` + `[:8000]`，见 verifier.py:1817-1821）。
            #   但此处原为 `feedback = _rv` **整段覆盖** ⇒ 刚被保留的 2.5–6 万
            #   字符推理又被摘要成短清单 ⇒ 实测 q1–q6 最终 `diag.revise_feedback`
            #   最长仅 2.4–3.0k，且**不含 `【复核依据（判错报告原文摘录）】` 段**
            #   ⇒ 深复核推理**始终没到模型手上**。
            #   现改为**附加**（`_merge_review_into_feedback`）：复核只做
            #   "是否属实"的判定与标注，其产物以 `【复核意见…】` 段并入，
            #   **不替换/不摘要掉**原有推理。
            feedback = _merge_review_into_feedback(
                feedback, _rv,
                getattr(self.config, 'feedback_review_append', True))
        else:
            _reviewed_empty = True
    # 注入各客观审核环节（3.6 AuditGate / 4.6 对抗 / 4.5 Oracle）淘汰反馈，
    # 驱动定向修正（audit_reject_feedback 为通用 revise 反馈通道）
    audit_fb = getattr(ctx, "audit_reject_feedback", None)
    if audit_fb:
        feedback = feedback + "\n" + "\n".join(audit_fb)
    # ★ 2026-09-17：复核判定"无实质缺陷"且无审核反馈 ⇒ **没有可修正的目标**，
    # 继续只会盲目重解（信息量为零，却要付一轮"生成 + 验证"）。直接结束回环。
    if _reviewed_empty and not audit_fb:
        self.record(ctx, "revise",
                    "复核无实质缺陷且无审核反馈 → 结束 revise"
                    "（避免零信息空转，2026-09-17）")
        return False
    return self._revise_rounds(ctx, max_rounds, feedback, force, tier_votes)


def _build_revise_feedback(self, ctx: TaskContext, ver_result: dict,
                           force: bool) -> str:
    """构造 revise 反馈：force 走结构化诊断报告，否则取 ver_result.feedback。

        纯搬迁自 ``_deep_revise_loop_inner``（2026-10-08 批8 原地拆分），语句逐字不变。
        """
    if force:
        # P1 应急重解：构造**结构化错误诊断报告**（2026-09-11 用户指正：
        # "不能光检测错误，要把错误情况总结后返回给大模型，否则等于没检查"）。
        # 实测依据（v10 的 002/004/022）：原反馈是「所有候选均未获验证通过，请重新
        # 审题…」这类无信息量默认句 + 验证代码细节 → 重解等于重来一遍，正确率无变化。
        # 这里改为逐条定性 + 可操作指引：① 当前答案是什么（要推翻什么）
        # ② 数值攻击的「声称值 vs 采样反例」矛盾 ③ Lean/AuditGate 的具体缺陷。
        _parts = ["【本次重解必须修正以下已检测到的具体问题（逐条回应，勿泛泛重来）】"]
        try:
            _cands0 = list(ctx.candidates or [])
            _cur_ans = str(getattr(_cands0[0], "answer", "") or "")[:300] if _cands0 else ""
        except Exception:  # noqa: BLE001
            _cur_ans = ""
        if _cur_ans:
            _parts.append(f"① 当前答案（已验证不通过，需重新推导）：{_cur_ans}")
        _bvf = str(getattr(ctx, "blueprint_value_false", "") or "")
        if _bvf:
            _parts.append(
                f"② 数值攻击证伪：{_bvf[:280]}\n"
                "    → 含义：原推导中该**极值/边界结论与数值采样矛盾**。"
                "请重新独立推导该量的真实取值，不要沿用原结论；"
                "若判定为浮点噪声（差异 < 1e-6），须说明理由方可保留。")
        _audit_fb = list(getattr(ctx, "audit_reject_feedback", None) or [])
        if _audit_fb:
            # 2026-09-12：单项截断 280 → 500。理由同 lean_gate：desc 末尾现在
            # 带「修法提示」，280 会把可操作部分切掉。条数仍限 3，避免 prompt 膨胀。
            _parts.append("③ 验证/审核环节给出的具体缺陷：\n"
                          + "\n".join(f"    - {str(x)[:500]}" for x in _audit_fb[:3]))
        # B2（2026-09-11）：从既有 Lean 反馈里提取【当前待证目标】(⊢ ...) 注入。
        # 依据：P1 虽已能触发重解，但反馈里缺"还差什么" → 模型只能盲目重算。
        # 目标状态是 Lean 独有信息（bridge/mcp 输出中的 `⊢` 行），定向价值最高。
        _goals: list = []
        for _x in _audit_fb:
            for _ln in str(_x).splitlines():
                _s = _ln.strip()
                if "⊢" in _s and _s not in _goals:
                    _goals.append(_s[:200])
        if _goals:
            _parts.append(
                "④ Lean 给出的**当前待证目标**（据此定向修正，勿另起炉灶）：\n"
                + "\n".join(f"    {g}" for g in _goals[:3]))
        # 2026-09-12 新增（用户要求）：把 **Lean 编译器发现的逻辑缺陷**单独成条，
        # 与 ③ 的混合反馈区分开 —— 让模型明确知道"哪些是明显逻辑错误"，
        # 从而优先、定向地修正该处，而不是笼统重算一遍。
        _lean_fb_sep = list(getattr(ctx, "lean_reject_feedback", None) or [])
        if _lean_fb_sep:
            _parts.append(
                "⑤ **Lean 编译器发现的逻辑缺陷**（属明显错误，必须优先修正；"
                "来自形式化验证，非数值误差）：\n"
                + "\n".join(f"    - {str(x)[:500]}" for x in _lean_fb_sep[:3]))
        _parts.append(
            "【要求】逐条回应 ②③⑤：指出原推理中出错的具体步骤、重新推导，"
            "并给出与新证据一致的最终答案（置于 \\boxed{} 内）；"
            "若某条证据判定为误报，必须明确说明理由。")
        feedback = "\n".join(_parts)
    else:
        feedback = ver_result.get("feedback", "")
        if not feedback:
            feedback = "所有候选均未获验证通过，请重新审题并纠正推理错误。"
    return feedback


def _revise_rounds(self, ctx: TaskContext, max_rounds: int,
                   feedback: str, force: bool, tier_votes: int) -> bool:
    """revise 主循环（最多 max_rounds 轮）：重解 → 复验 → 门控判定。

        纯搬迁自 ``_deep_revise_loop_inner``（2026-10-08 批8 原地拆分），语句逐字不变。
        """
    from .orchestrator import _answer_fingerprint  # noqa: F401 （惰性；单一来源仍在 orchestrator）
    for r in range(max_rounds):
        # 2026-09-06：升级 gen_time_up——revise 回环 = solver.run 生成 +
        # verifier 验证，单轮可烧 200-400s，须按生成侧软截止更早收手。
        # 2026-09-11：force=True 跳过该软截止 —— P1 硬信号"应急重解"专用。
        #   根因（10 题实测 002）：P1 外部条件（剩余 >150s）通过并调用了本函数，
        #   但此处 `gen_time_up()` 依据生成侧软截止（deadline − verify_reserve = 720s）
        #   在累计 814s 时必为 True → **第一轮就 break**，重解从未真正发生。
        #   应急重解只受硬墙约束，由调用方（P1）保证剩余时间充足。
        # ⚠ 2026-09-16 修复（与 5.5 闸门同一病灶）：`gen_time_up()` 是
        #   「**生成**侧软截止」（deadline − verify_reserve），而 revise 回环是
        #   **验证之后的修正**，正是 verify_reserve 要保护的时段 ⇒ 口径错配。
        #   预算偏紧时（如 standard 档 540s、verify_reserve 480s ⇒ _gen_deadline 仅 60s）
        #   它**恒为 True** ⇒ 回环**第一轮就 break**。
        #   ⚠ 实测澄清：在**当前无预算上限**配置下（max_time_per_question=86400）
        #   它不会触发（实测 revise_round 达 2 / 6），所以并非"永久禁用"；
        #   但一旦收紧预算就会复现 —— 故仍改为与 5.5 一致的 `is_time_critical()`。
        if ctx.is_time_critical() and not force:
            self.record(ctx, "revise", "revise 回环预算不足，提前终止")
            break
        # ★★ 2026-09-16 修复（把只写不读的字段接上）：调用方 P1 在
        #   "重解后答案未变化"时置位 `ctx._revise_no_progress_answer`
        #   （见 :1566，注释承诺"后续同源的 revise（4.6 对抗 / 5 全0票 /
        #   5.5 低置信）不再对**同一个答案**重复重解"），
        #   但**全仓没有任何读取点** ⇒ 该保护从未生效。
        #   实测代价（official112-003）：`deep 档 revise 自纠错 第1~6轮`
        #   连跑 6 轮、中间三次 `revise 回环 2 轮仍未获得正确票`，
        #   而 `P1 重解成效：答案未变化（0→0 字符）` ⇒
        #   **6 轮全部无效**，约占该题 4148s 墙钟的 22%。
        #   语义：仅对非 force 调用生效（force 是调用方明确要求的应急重解）；
        #   答案一旦变化，`_npa == _cur` 自然不成立 ⇒ 标记自动失效。
        if not force:
            _npa = getattr(ctx, "_revise_no_progress_answer", None)
            # ★ 2026-10-05：改用候选答案指纹（原 ctx.final_response 此处恒为 ""）
            _cur_ans = _answer_fingerprint(ctx)
            if _npa is not None and _cur_ans and _npa == _cur_ans:
                self.record(ctx, "revise",
                            "该答案此前重解后**未发生变化** → 跳过重复 revise"
                            "（无进展保护，:1566 置位）")
                break
        ctx.revise_round += 1
        # ★ 2026-10-05：改用候选答案指纹（原 ctx.final_response 此处恒为 ""）
        _ans_before = _answer_fingerprint(ctx)
        ctx.revise_feedback = [feedback]
        self.record(ctx, "revise",
                    f"deep 档 revise 自纠错 第{ctx.revise_round}轮",
                    round=ctx.revise_round)
        self.solver.run(ctx)  # 走 _generate_revise 路径
        # 2026-09-13（用户原则："无用功要保证检测并截断，但要保证原有环节功能
        # 不受影响"）：**轮间无进展即停**。
        # 依据：本轮"生成 + 验证"实测量级 200-400s；若生成后答案与上轮**完全
        # 相同**，说明这一轮没有产出任何新东西，继续下一轮只是重复同一次空转
        # （实测 010：P1 强制重解跑满 2 轮，答案始终 `\boxed{0}`，白花 366s，
        #   最终成效埋点仍记"答案未变化"）。
        # 保守性：**只在答案完全未变时停**，且**第 1 轮永远保留**（有可能一次
        # 改对）；答案一旦变化即视为有进展，继续跑满剩余轮数 —— 原有功能不变。
        # ★ 2026-10-05：改用候选答案指纹（原 ctx.final_response 此处恒为 ""，
        #   导致该"round 间无进展"保护恒短路边、从未生效）
        _ans_after = _answer_fingerprint(ctx)
        if (_ans_before and _ans_after and _ans_before == _ans_after
                and ctx.revise_round >= 1):
            self.record(
                ctx, "revise",
                f"revise 第{ctx.revise_round}轮无进展（答案未变 "
                f"{_ans_before[:20]}）→ 提前终止，不再空转")
            break
        ver2 = self.verifier.run(
            ctx, problem=ctx.problem, candidates=ctx.candidates,
            use_clustering=True,
            use_scoring=self.config.use_scoring,
            is_proof=(getattr(ctx, 'question_type', '') == '证明题' or getattr(ctx, 'domain', '') in ('证明', '证明题')),
            use_playoff=ctx.state.playoff_enabled,
            use_deterministic=getattr(self.config, 'enable_deterministic', True),
            use_rubric=getattr(self.config, 'use_rubric', False),
            use_challenge=getattr(self.config, 'use_challenge', False),
            voting_times=tier_votes,
        )
        ctx.verdicts = self._verdicts_from_ver_result(ver2, ctx.candidates)
        ctx._best_cluster = ver2.get("best_cluster")
        ctx._cluster_data = ver2.get("cluster_data", [])
        # v2.8 AcceptGate：按本轮结果更新门控，连续重大缺陷达阈值 → 提前放弃
        decision = self._update_accept_gate(
            ctx, is_proof=(getattr(ctx, 'question_type', '') == '证明题' or getattr(ctx, 'domain', '') in ('证明', '证明题')))
        # 2026-09-02 老师需求：≥4 个候选获得正确票才算通过（防 1 票假阳性误收）
        n_pass = sum(1 for v in ctx.verdicts
                     if getattr(v, 'correct_votes', 0) > 0)
        if n_pass >= 4:
            self.record(ctx, "revise",
                        f"revise 第{ctx.revise_round}轮 {n_pass} 个候选通过（≥4）")
            return True
        if decision == "REJECT":
            self.record(ctx, "revise", "AcceptGate 连续重大缺陷达阈值，放弃 revise")
            return False
        # ★ 2026-10-07（fix-gate-timing-diag 问题 2.3）：消费 ACCEPT。
        #   旧代码只消费 REJECT ⇒ 即便门判 ACCEPT（本轮 best_cluster 已达标）
        #   也**无人理会**，继续跑满轮数 ⇒ ACCEPT 是死分支。现让 ACCEPT 真正
        #   改变行为：本轮复验已给出达标答案 ⇒ 结束回环并采纳（返回 True）。
        #   仅在 `accept_gate_enforce` 打开时可达（默认阈值 = 5/10 结构性不可达，
        #   见 `_update_accept_gate`）。
        if decision == "ACCEPT":
            self.record(ctx, "revise",
                        f"AcceptGate=ACCEPT（连续通过 "
                        f"{ctx.round_state.consecutive_pass} 次）→ 采纳本轮答案，"
                        "结束 revise")
            return True
        feedback = ver2.get("feedback") or feedback
    self.record(ctx, "revise", f"revise 回环 {max_rounds} 轮仍未获得正确票")
    return False


def _update_accept_gate(self, ctx: TaskContext, is_proof: bool = False) -> str:
    """按本轮验证结果更新 AcceptGate（RoundState），返回最新 decision。

        - is_pass：best_cluster 置信度 >= accept_confidence；
        - has_major_defect：证明题全部 0 正确票，或常规题置信度 < 0.3。

        ★ 2026-10-07（fix-gate-timing-diag 问题 2.3）根因与修法
        ----------------------------------------------------------
        「题 000 `HOLD(pass=1,defect=0)` 判定自相矛盾」的表象，实为**两项独立缺陷**：

        ① 判定映射本身**不错**（`RoundState.update` 忠实于其契约）：
           `is_pass` 只重置缺陷计数、并累加 `consecutive_pass`；只要
           `consecutive_pass < ACCEPT_PASS_THRESHOLD(=5)` 就仍返回 `HOLD`
           ⇒ `pass=1` 出 HOLD 是**契约内**行为，不是状态机 bug。

        ② 真正的缺陷是**阈值结构性不可达**：`ACCEPT_PASS_THRESHOLD=5` /
           `REJECT_DEFECT_THRESHOLD=10`（见 `agent/base.py::RoundState`）是按
           「无上限连续回环」标定的；而本函数的唯一调用点是 `_deep_revise_loop_inner`
           的每轮复验，受 `max_revise_rounds`(=5) 全局上限约束 ⇒ 单题最多被调用
           **≤5 次**（smoke10 实测 ≤2 次）。于是 `consecutive_pass`/`defect` 永远
           到不了 5/10 ⇒ **decision 恒为 HOLD**：smoke10 10/10 题只出现 HOLD，
           ACCEPT/REJECT 一次未出现 ⇒ AcceptGate 是**空闸门**（"无约束力"的根因）。
           叠加缺陷：`ACCEPT` 分支当时**无任何消费者**（只有 REJECT 被消费）
           ⇒ 即便可达也是死分支。
           ⚠ 特别说明：题 000 第二次的 `pass=1, defect=0` 与题 006 的
           `pass=0, defect=0` 都是**契约内**的中间态（后者 = 本轮未通过但未达
           "重大缺陷"，即 `accept_confidence > conf >= 0.3` 的灰区）。

        修法（`accept_gate_enforce` 开关，注册制四件套）：
          · 打开时把阈值改为**可达口径**（实例级覆盖，不动 base.py 契约）：
            连续通过 `accept_gate_pass_threshold`(默认 1) 次 → ACCEPT；
            连续重大缺陷 `accept_gate_reject_defect_threshold`(默认 2) 次 → REJECT；
          · ACCEPT/REJECT 均已在 `_deep_revise_loop_inner` 被消费（改变行为）；
          · 每轮终态写入 `ctx._accept_gate_final` ⇒ diag 可见"是 ACCEPT 采纳
            还是 HOLD 带疑提交"（HOLD 不再是无声通过）。
          · `=0` 回退旧行为（阈值 5/10、恒 HOLD、无约束）做 A/B。
        """
    from .orchestrator import _sw_bool_or, _sw_num_or  # noqa: F401 （惰性；单一来源仍在 orchestrator）
    accept_conf = getattr(self.config, 'accept_confidence', 0.6)
    bc = getattr(ctx, '_best_cluster', None)
    conf = bc.confidence if bc is not None else 0.0
    is_pass = conf >= accept_conf
    has_major = False
    if is_proof:
        has_major = bool(ctx.verdicts) and all(v.correct_votes == 0 for v in ctx.verdicts)
    elif conf < 0.3:
        has_major = True
    # 阈值可达化（实例级覆盖；默认 5/10 保持旧契约，不动 base.py）
    _enforce = _sw_bool_or("accept_gate_enforce", True)
    try:
        rs = ctx.round_state
        if _enforce:
            rs.ACCEPT_PASS_THRESHOLD = max(
                1, int(_sw_num_or("accept_gate_pass_threshold", 1.0)))
            rs.REJECT_DEFECT_THRESHOLD = max(
                1, int(_sw_num_or("accept_gate_reject_defect_threshold", 2.0)))
    except Exception:  # noqa: BLE001
        _enforce = False
    decision = ctx.round_state.update(is_pass=is_pass, has_major_defect=has_major)
    self.record(
        ctx, "accept_gate",
        f"AcceptGate={decision} (pass={ctx.round_state.consecutive_pass}, "
        f"defect={ctx.round_state.consecutive_major_defect})",
        confidence=round(conf, 3),
    )
    # 终态留痕（供 diag）：HOLD 也要能看出"是带疑提交"
    try:
        ctx._accept_gate_final = {
            "decision": str(decision),
            "rounds": int(getattr(ctx.round_state, "rounds", 0) or 0),
            "consecutive_pass": int(getattr(ctx.round_state, "consecutive_pass", 0) or 0),
            "consecutive_major_defect": int(
                getattr(ctx.round_state, "consecutive_major_defect", 0) or 0),
            "last_confidence": round(float(conf), 3),
            "enforce": bool(_enforce),
            "threshold_pass": int(getattr(ctx.round_state, "ACCEPT_PASS_THRESHOLD", 5) or 5),
            "threshold_defect": int(getattr(ctx.round_state, "REJECT_DEFECT_THRESHOLD", 10) or 10),
        }
    except Exception:  # noqa: BLE001
        pass
    return decision
