# -*- coding: utf-8 -*-
"""求解前准备族（prep）（2026-10-07 阶段C6：从 agent/orchestrator.py 的 Orchestrator.run 抽出）。

已抽出段（按 run 内顺序）：
  · 1.2_theorem_hint —— 领域→定理检索（leansearch/source_scan 命中定理写入 ctx）
  · 2.6_pre_audit    —— 题意理解确认（Lean 前置形式化 / AuditGate 复核）

**纯搬迁**：段内源码逐字搬入（仅去 12 空格缩进），调用点由 `run` 改为一行委托。
`run` 保留各自的 `self._stage_start(ctx, "<阶段名>")` 打点**原位不动**
（阶段名是稳定契约，被 tools/stage_audit.py / tools/test_report.py 按名聚合）。

耦合实测（AST 作用域感知 —— Py3.14 下 symtable 会把推导式变量漏进外层作用域，
故不用 symtable）：两段对 run 局部变量依赖均为空（只用 self/ctx 参数）；
段内绑定仅异常名/推导式变量（内层作用域）；无 return / 无循环。
2.6 引用 orchestrator 模块级 `_artifact_put` ⇒ 函数内惰性 import（单一来源仍不复制）。
"""
from __future__ import annotations


def theorem_hint_stage(self, ctx) -> None:
    """1.2 领域→定理检索（命中定理写入 ctx，供 2.6 前置理解 / 3_solve 提示词使用）。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`）；
    `ctx` 为 `TaskContext`。返回 None；结果写回 `ctx`（theorem_hint_block 等）。
    """
    if (getattr(self.config, "enable_theorem_hint", True)
            and not ctx.state.emergency):
        self._retrieve_theorem_hints(ctx)


def pre_audit_stage(self, ctx, tier: str) -> None:
    """2.6 题意理解确认（Lean 前置形式化校验 / AuditGate 可选 LLM 复核）。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`）；
    `ctx` 为 `TaskContext`，`tier` 为当前档位（用于 `lean_preverify_tiers` 判断）。
    返回 None；结果写回 `ctx`（trace / metadata）。
    """

    from .orchestrator import _artifact_put

    # 2.6) 题意理解确认（2026-09-06 晚恢复 Lean 前置形式化：lean 可用且
    # 命中档位 → 题目转 Lean 声明编译校验理解，失败带错误强制重新审题；
    # lean 不可用/档位不命中 → AuditGate 可选 LLM 题意复核，默认关闭，
    # 失败不阻断主流程，由下游 revise/重理解兜底）。
    if not ctx.state.emergency:
        if (self._lean_active()
                and self._lean_applicable(ctx)
                and getattr(self.config, "enable_lean_preverify", True)
                and tier in tuple(getattr(
                    self.config, "lean_preverify_tiers", ("deep",)))):
            try:
                self.lean_pre_verifier.run(ctx)
            except Exception as _e2:  # noqa: BLE001
                self.record(ctx, "lean_preverify",
                            f"前置形式化异常（跳过，不阻断）: "
                            f"{type(_e2).__name__}: {str(_e2)[:120]}")
        else:
            self.audit_gate.confirm_understanding(ctx)
    
    # ★ 2026-10-02 hook 01：题意理解确认后落盘（2.6_pre_audit → 01_understanding）。
    _artifact_put(ctx, "01_understanding", {
        "question_type": getattr(ctx, "question_type", ""),
        "domain": getattr(ctx, "domain", ""),
        "lean_applicable": (ctx.metadata or {}).get("lean_applicable"),
        "lean_skip_reason": (ctx.metadata or {}).get("lean_skip_reason"),
        "trace": [t for t in (getattr(ctx, "trace", None) or [])
                  if isinstance(t, dict)
                  and t.get("step") in ("classify_type",
                                        "confirm_understanding",
                                        "lean_preverify")][-20:],
    })


def prep_tier_budget(self, ctx) -> str:
    """2.5 档位/预算初始化（2026-09-29 起统一单一档位，恒为 "deep"）。

    **搬迁说明**：本块原为 `Orchestrator.run` 内**无阶段打点**的前置块
    （`2.5` 难度路由已删除，只余档位/预算赋值），故不属 15 个 `_stage_start` 段。
    搬出后由 `run` 以 `tier = prep_tier_budget(self, ctx)` 承接返回值。
    ⚠ **非纯逐字搬**：末尾**新增** `return tier`（原为隐式把 `tier` 留在 run 作用域）。
    """
    # 2.5) 2026-09-29：**难度路由已删除，统一为单一档位**（用户决策）。
    # 原 DifficultyRouter 静态预判 + LLM 自评 → fast/standard/deep 三档，
    # 档位再决定候选数/投票数/子目标数/预算等"方法集"——违背"用全部方法
    # 测试大模型能力"的初衷。现 `ctx.tier` 恒为 "deep"（= 原最强档配置），
    # 不再有任何按难度分流的分支。
    # ⚠ 同时删除的还有：应急降档（emergency → standard）、deep 全卷配额闸
    #   （allow_deep()，`deep_quota_ratio=0.25` × 112 = 28 恰等于实测 deep 题数，
    #   即"研究档下仍按配额裁剪方法"的头号来源）。
    ctx.tier = "deep"
    tier = "deep"
    # 2026-10-01 按用户决策：研究期不限时 —— **删除"单题按剩余时间收紧 deadline"
    # 的降级路径**（原 `min(硬顶, 档位软预算)` 会把单题拦腰截断）。
    # 现单题只受 `max_time_per_question`（86400，仅防挂死）约束，不再按预算降级。
    # soft_budget 仅保留为诊断字段（值=档位预算，已=86400）。
    ctx.soft_budget = float(
        (getattr(self.config, 'tier_budget', None) or {}).get("deep", 86400.0))
    # 尾部阈值：统一取 deep 档值 60s（把时间用得更尽）。
    # 2026-09-29：原 `if tier == 'deep'` 分支已因统一档位删除。
    ctx.critical_tail_seconds = float(
        getattr(self.config, 'deep_critical_tail_seconds', 60.0))
    # 2026-10-01 按用户决策：研究期不限时 —— **删除"生成侧软截止 (verify_reserve)"
    # 降级路径**。原逻辑预留 540s 给验证侧、逼生成在同一截止点前停手；
    # 研究期不省资源，生成/验证不再互相掐预算。
    # `_gen_deadline` 保持未设（0.0）⇒ `gen_time_up()` 回退 `is_time_critical()`，
    # 而单题 deadline 已达 86400 ⇒ 实际不再触发任何"按剩余时间降级"。
    ctx._gen_deadline = 0.0
    # 按档位调整 LLM 调用预算（deep 档需要更多调用次数）
    max_calls = self.config.tier_max_calls.get(
        tier, self.config.max_total_calls)
    if ctx.budget is not None:
        ctx.budget.set_max_calls(max_calls)
    else:
        # ★ 2026-10-07 分支静默跳过埋点（问题总账 §2.6「隐形门控」）：原
        #   `if ctx.budget is not None:` 无 else ⇒ 无 budget 时调用预算**静默
        #   不设**，而下方 record 仍会打印 max_calls，造成"看起来设了其实没设"。
        self.record(ctx, "paper_pacer",
                    f"调用预算未设置（ctx.budget 为空，跳过 set_max_calls，"
                    f"计划值 {max_calls}）")
    # ⚠ `paper_pacer` 是遗留 event 标签（PaperPacer 已于 2026-09-29 删除），
    #   内容（档位/调用预算）仍有效，2026-10-02 起仅作标签保留，勿据此判断全卷配速存在。
    self.record(ctx, "paper_pacer",
                f"档位 {tier} 软预算帽 {ctx.soft_budget:.0f}s "
                f"(调用预算 {max_calls})",
                tier=tier, soft_budget=round(ctx.soft_budget))
    return tier
