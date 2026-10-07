# -*- coding: utf-8 -*-
"""候选客观审核（2026-10-07 阶段C3a：从 agent/orchestrator.py 的 Orchestrator.run 抽出 3.6_audit_filter 段）。

**纯搬迁**：段内源码逐字搬入（仅去 8 空格的缩进），调用点由 `run` 改为一行委托。
`run` 保留 `self._stage_start(ctx, "3.6_audit_filter")` 打点**原位不动**（阶段名是稳定
契约，被 tools/stage_audit.py / tools/test_report.py 按名聚合）。

耦合实测（AST 自由变量分析）：本段对 `run` 的局部变量依赖**仅为 `ctx` 与 `tier`**；
段内 6 个局部名**零外泄**、无 `return`/`yield`、无循环。
其余外部符号全部经 `self` 访问（`self.record` / `self._lean_active` /
`self._lean_applicable` / `self.lean_gate` / `self.audit_gate` / `self.config`），
无模块级符号依赖 ⇒ 本模块无需任何 import。

返回 None；结果全部写回 `ctx`（candidates / audit_reject_feedback /
lean_reject_feedback / _gate_all_rejected）。
"""
from __future__ import annotations


def audit_filter_candidates(self, ctx, tier: str) -> None:
    """3.6 候选客观审核（Lean 双通道 + AuditGate 串行）。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`），
    `ctx` 为 `TaskContext`，`tier` 为当前档位（本项目恒为 "deep"）。
    """
    # 3.6) 候选客观审核（2026-09-06 晚：Lean 双通道 + AuditGate 串行）。
    # lean 可用 → 先 LeanGate.apply（内部按题型/档位自判：证明题全档整题
    # verify 淘汰 proof_invalid 并收 revise 反馈；非证明题 lean_gate_nonproof
    # 默认关 → 秒级记录跳过，零成本）；随后 AuditGate.audit_candidates 照跑
    # （证明题 rubric 默认关 → 空转零成本；非证明题 Level0 数值代回核验照旧，
    # 与去 Lean 期完全一致）。lean 不可用 → 纯 AuditGate（现状 AI 判分链）。
    # L1：verify_only 时跳过（把剩余时间留给验证投票）。
    if ctx.state.verify_only:
        self.record(ctx, "audit_gate",
                    "L1 验证优先：跳过 AuditGate 候选审核（时间不足）")
    else:
        _audit_total = len(ctx.candidates)
        # 2026-09-10：适用性豁免题（选项字母/判断值/概念文字答案）不进
        # LeanGate（结构上无从形式化）；下方 AuditGate.audit_candidates
        # 仍照跑（Level0 数值代回等），即「豁免 Lean，不豁免检测」。
        if self._lean_active() and self._lean_applicable(ctx):
            _lt = len(ctx.candidates)
            lean_kept, lean_fb = self.lean_gate.apply(
                ctx, tier, ctx.candidates)
            if lean_kept:
                ctx.candidates = lean_kept
                self.record(ctx, "lean_gate",
                            f"Lean 硬验证通过 {len(lean_kept)}/{_lt} 候选")
            else:
                # ★★ 2026-10-06 修（**「全拒 = 全留」** —— 门等于没作用）：
                #   原写法 `if lean_kept: ctx.candidates = lean_kept`，
                #   当门把候选**全部拒掉**时 `lean_kept` 是**空列表（falsy）**
                #   ⇒ **`ctx.candidates` 保持原样、一个都没淘汰**。
                #   后果：门跑了、日志有记录，但**对候选池零影响** = 假执行
                #   （实测题 000 的 `degraded="non_math_answer"` 条目就是这样）。
                #   现改为：**显式标记 + 明确留痕**，不再静默保留；
                #   置 `strict_all_rejected=True` 时进一步清空候选池，
                #   交给下游兜底/重生成链（该链已存在：orchestrator 的
                #   "Solver 未产出候选 → 兜底直接求解"）。
                ctx._gate_all_rejected = True
                self.record(ctx, "lean_gate",
                            f"⚠ Lean 门把 {_lt} 个候选**全部拒掉** → "
                            f"不再静默保留（原先此处等于没过滤）；"
                            f"已标记 _gate_all_rejected 交给下游处置")
                if bool(getattr(self.config,
                                "strict_all_rejected", False)):
                    ctx.candidates = []
                    self.record(ctx, "control",
                                "strict_all_rejected=True → 清空候选池，"
                                "触发下游兜底/重生成链")
            if lean_fb:
                ctx.audit_reject_feedback = list(
                    getattr(ctx, "audit_reject_feedback", []) or []
                ) + lean_fb
                # 2026-09-12 新增（用户要求「把 Lean 发现的错误总结并反馈
                # 大模型、筛掉明显逻辑错误的候选」）：**单独留一份** Lean
                # 反馈，供 revise prompt 区分「Lean 编译器发现的形式化/逻辑
                # 缺陷」与「AuditGate 的数值/格式缺陷」——原先两者混在
                # 同一条 ③ 里，模型无从判断哪条才是"逻辑错了"。
                try:
                    ctx.lean_reject_feedback = list(lean_fb)
                except Exception as _e_lrf:  # noqa: BLE001
                    # ★ 2026-10-07 观测补齐（问题总账 §2.6「纯空吞异常」A 类）：
                    #   原为裸 `pass`，一旦这条"单独留存的 Lean 反馈"赋值失败，
                    #   revise 提示词里**再也区分不出**「形式化/逻辑缺陷」与
                    #   「AuditGate 数值/格式缺陷」（本条存在的唯一目的），
                    #   且日志 0 痕迹 ⇒ 事后无法判断"没触发"还是"被吞"。
                    self.record(ctx, "lean_gate",
                                f"Lean 候选级淘汰反馈单独留存失败"
                                f"（{type(_e_lrf).__name__}: {str(_e_lrf)[:120]}）"
                                f"→ revise 将丢失 Lean 专属反馈")
                self.record(ctx, "lean_gate",
                            f"Lean 硬验证淘汰 {len(lean_fb)} 候选，"
                            f"revise 将注入 Lean 反馈")
        audit_kept, audit_feedbacks = self.audit_gate.audit_candidates(
            ctx, tier, ctx.candidates)
        if audit_kept:
            ctx.candidates = audit_kept
            self.record(ctx, "audit_gate",
                        f"客观审核通过 {len(audit_kept)}/{_audit_total} 候选")
        else:
            # ★★ 2026-10-06 修（**「全拒 = 全留」**，与 Lean 门同源）：
            #   同上 —— `if audit_kept:` 在**全拒**（空列表）时**不更新候选池**
            #   ⇒ 门等于没作用。现显式留痕，不静默。
            ctx._gate_all_rejected = True
            self.record(ctx, "audit_gate",
                        f"⚠ 客观审核把 {_audit_total} 个候选**全部拒掉** → "
                        f"不再静默保留；已标记 _gate_all_rejected")
            if bool(getattr(self.config,
                            "strict_all_rejected", False)):
                ctx.candidates = []
                self.record(ctx, "control",
                            "strict_all_rejected=True → 清空候选池，"
                            "触发下游兜底/重生成链")
        if audit_feedbacks:
            ctx.audit_reject_feedback = list(
                getattr(ctx, "audit_reject_feedback", []) or []
            ) + audit_feedbacks
            self.record(ctx, "audit_gate",
                        f"客观审核淘汰 {len(audit_feedbacks)} 候选，"
                        f"revise 将注入审核反馈")
