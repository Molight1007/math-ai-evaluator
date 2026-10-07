# -*- coding: utf-8 -*-
"""低置信度强制复核（2026-10-07 阶段C3b：从 agent/orchestrator.py 的 Orchestrator.run 抽出 5.5_low_conf 段）。

**纯搬迁**：段内源码逐字搬入（仅去 8 空格的缩进），调用点由 `run` 改为一行委托。
`run` 保留 `self._stage_start(ctx, "5.5_low_conf")` 打点**原位不动**（阶段名是稳定
契约，被 tools/stage_audit.py / tools/test_report.py 按名聚合）。

耦合实测（AST 自由变量分析）：本段对 `run` 的依赖为 `ctx` + **只读** `ver_result` /
`tier_votes`（两者均在 5.5 之前由 4_verify 段赋值，只读不写）；段内 3 个局部名
**零外泄**、无 `return`/`yield`、无循环。其余外部符号全部经 `self` 访问，无模块级
符号依赖 ⇒ 本模块无需任何 import。

返回 None；结果全部写回 `ctx`（candidates / 触发 `solver.add_candidates` 补采等）。
"""
from __future__ import annotations


def low_confidence_recheck(self, ctx, ver_result, tier_votes) -> None:
    """5.5 低置信度强制复核（v2.6：杀掉虚高置信度；含"零多样性"补充采样）。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`），
    `ctx` 为 `TaskContext`；`ver_result` / `tier_votes` 为 4_verify 段算出、
    本段**只读**使用（透传给 `self._deep_revise_loop`）。
    """
    # 5.5) 低置信度强制复核（v2.6 杀掉虚高置信度）：
    #   deep 档 best_cluster 置信度 < 0.5（正确票未过半，验证器自身都不确定）
    #   且时间/预算宽裕时，不自信接受低共识答案，而是触发 revise 提升共识。
    # 所有档位（不只 deep）启用低置信度强制复核：
    # 只要投票共识 < 0.5（验证器自身都不确定），就不再"自信接受"错答案，
    # 而是触发 revise 反复验证，直到获得正确票或超时/预算耗尽。
    _bc = getattr(ctx, '_best_cluster', None)
    # ★★ 2026-09-16 修复关键断点：此处**绝对不能用 `gen_time_up()`**。
    # 实测（0916 轮 111 题，standard 档）：
    #   · paper_pacer 把单题预算收紧到 540s；
    #   · verify_reserve=480s ⇒ `_gen_deadline` 只剩 **60s**；
    #   · `2.5_difficulty`(23.6s) + `2.7_subgoal_main`(47s) 就已耗尽 60s
    #     ⇒ 验证阶段开始时 `gen_time_up()` **早已恒为 True**。
    # 后果：**5.5 低置信度强制复核被永久禁用**——验证器把唯一候选投成
    #   0/2 票（+带推理复核判 B），却无人消费，错答直接提交。
    #   trace 实证：「全部 0 正确票，触发兜底直接求解」之后
    #   `5.5_low_conf` 阶段耗时 **9.5e-06 秒**（＝根本没执行），
    #   `revise_round=0`。
    # ⇒ 口径错配：`gen_time_up()` 是「**生成**侧软截止」，用于闸**生成**；
    #   而 5.5 是**验证之后的修正**，正是那 480s `verify_reserve` 要保护的时段。
    #   用生成时钟闸修正环节，等于把预留的验证时间作废。
    # 改判 `is_time_critical()`（真实剩余时间），与 4.5/4.6 之外的验证侧一致。
    # ★★ 2026-10-06 新增（**"零多样性"分支** —— 把假高置信度变成可处置的信号）：
    #   与下面的 `confidence < 0.5` 是**两种不同的病理**，必须分开处置：
    #     · 置信度低（有分歧、无共识）⇒ 重写求共识（现有逻辑，合理）
    #     · **零多样性（全题只有 1 种答案）⇒ 没有分歧可裁决**，
    #       重写也无从对比 ⇒ 应当**去补充采样，创造分歧**
    #   实测依据（题 000）：5 个候选答案**完全相同**（`\boxed{0}` ×5）⇒
    #   一致率 15/15 ⇒ 置信度被刷到 **1.00** ⇒ 直接放行，而正确答案从未出现。
    #   ★ "答案一致"在采样无多样性时**是采样失败的信号，不是答案可靠的证据** ——
    #     它说明系统**从未探索到其他可能**。
    #   ⇒ 接到 `solver.add_candidates()`（**此前全仓零调用**）做**高温度补采**，
    #     让投票真正有可裁决的对象。这才是把该机制从"给个数字"变成"能用的工具"。
    _n_distinct = int(getattr(_bc, "n_distinct", 0) or 0)
    if (_bc is not None and 0 < _n_distinct <= 1
            and not ctx.state.emergency
            and not ctx.is_time_critical()
            and bool(getattr(self.config,
                             "diversity_resample_enabled", True))):
        _need = max(2, int(getattr(self.config,
                                   "diversity_resample_count", 3) or 3))
        self.record(
            ctx, "control",
            f"候选**零多样性**（全题仅 {_n_distinct} 种答案）→ "
            f"触发补充采样 {_need} 个（高温度 0.8/0.9/1.0）以创造分歧")
        try:
            self.solver.add_candidates(
                ctx, count=_need, temperatures=[0.8, 0.9, 1.0])
            self.record(ctx, "diversity_resample",
                        f"补充采样完成：候选池 {len(ctx.candidates)} 个")
        except Exception as _e_dr:  # noqa: BLE001  补采失败不阻断主流程
            self.record(ctx, "diversity_resample",
                        f"补充采样失败（{type(_e_dr).__name__}）→ 继续原流程")

    if (_bc is not None
            and getattr(_bc, 'confidence', 1.0) < 0.5
            and not ctx.state.emergency
            and not ctx.is_time_critical()):
        self.record(
            ctx, "control",
            f"deep 档低置信度({_bc.confidence:.2f})，强制 revise 复核提升共识",
        )
        self._deep_revise_loop(ctx, ver_result, tier_votes)
