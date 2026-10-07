# -*- coding: utf-8 -*-
"""验证族阶段（4.x）（2026-10-07 阶段C4：从 agent/orchestrator.py 的 Orchestrator.run 抽出）。

已抽出段：  · 4.5_oracle

**纯搬迁**：段内源码逐字搬入（仅去 8 空格缩进），调用点由 `run` 改为一行委托。
`run` 保留各自的 `self._stage_start(ctx, "<阶段名>")` 打点**原位不动**
（阶段名是稳定契约，被 tools/stage_audit.py / tools/test_report.py 按名聚合）。

耦合实测（AST 自由变量分析）：4.5 段对 `run` 的依赖为 `ctx` + `tier` +
**只读** `ver_result` / `tier_votes`（两者均由 4_verify 段赋值，本段只读透传）；
段内**无任何局部绑定**、无 `return`/`yield`/`break`/`continue`。外部符号全部经
`self` 访问（`self._enhance_window_ok` / `self._oracle_review_best`），
无模块级符号依赖 ⇒ 本模块无需任何 import。
"""
from __future__ import annotations


def oracle_review_stage(self, ctx, tier: str, ver_result, tier_votes) -> None:
    """4.5 deep 档 AnswerOracle 客观复核 best_cluster（区别于投票同源自评）。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`），
    `ctx` 为 `TaskContext`，`tier` 为当前档位；`ver_result` / `tier_votes` 为
    4_verify 段算出、本段**只读**使用（透传给 `self._oracle_review_best`）。
    返回 None；结果写回 `ctx`。
    """
    # 4.5) deep 档：AnswerOracle 客观复核 best_cluster（区别于投票同源自评）
    # 2026-09-06 超时修复（验证暴露残留洞）：oracle 复核单次可达 300s+，
    # 原只在内部查 is_time_critical（deadline-60s）→ algebra-003 修复后
    # verify 提前完成反而给 oracle 打开 365s 烧穿窗口（elapsed 1402s）。
    # oracle 是"4_verify 之后的复核增强"，到生成侧软截止即弃——
    # verify 已投过票，放弃复核不损失主验证，只少一层 deep 深查。
    # ★ 2026-09-17（Audit-3）：口径统一为 `is_time_critical()`（真实剩余时间）。
    # `gen_time_up()` 是**生成**侧软截止（deadline − verify_reserve）；4.5 Oracle
    # 属"4_verify 之后的复核"，用生成时钟闸它是口径错配，与已修好的 5.5 不一致。
    # 真正的耗时护栏是本行的 `_enhance_window_ok`（要求剩余 ≥ 360+tail+30），
    # 故换时钟不会重新打开烧穿窗口。
    if (tier == 'deep'
            and getattr(ctx, '_best_cluster', None) is not None
            and not ctx.is_time_critical()
            and self._enhance_window_ok(ctx, "oracle")):
        self._oracle_review_best(ctx, ver_result, tier_votes)
