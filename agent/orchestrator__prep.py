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
