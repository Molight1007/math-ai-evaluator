# -*- coding: utf-8 -*-
"""求解族阶段（2026-10-07 阶段C4：从 agent/orchestrator.py 的 Orchestrator.run 抽出）。

已抽出段（按 run 内顺序）：
  · 2.7_subgoal_main —— 子目标细化主路径 + C-lite 蓝图数值攻击

**纯搬迁**：段内源码逐字搬入（仅去 8 空格缩进），调用点由 `run` 改为一行委托。
`run` 保留 `self._stage_start(ctx, "2.7_subgoal_main")` 打点**原位不动**
（阶段名是稳定契约，被 tools/stage_audit.py / tools/test_report.py 按名聚合）。

耦合实测（AST 自由变量分析）：2.7 段对 `run` 的局部变量依赖**仅为 `ctx` 与 `tier`**；
段内 4 个局部名（`_p4_cap` / `_p4_saved_dl` / `_p4_t0` / `exc`）**零外泄**、
无 `return`/`yield`/`break`/`continue`。其余外部符号全部经 `self` 访问
（`self.record` / `self._phase_budget` / `self._phase_deadline_guard` /
`self._phase_deadline_restore` / `self.sub_goal_solver` / `self._value_attack_blueprint` /
`self.config`）与模块级 `time` / `logger`，无其它依赖。

返回 None；结果全部写回 `ctx`（`_subgoal_main_done` / 蓝图 / 候选等）。
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("MathPilot")


def subgoal_main_path(self, ctx, tier: str) -> None:
    """2.7 子目标细化主路径（含 P4 阶段预算）+ C-lite 蓝图数值攻击。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`），
    `ctx` 为 `TaskContext`，`tier` 为当前档位（本项目恒为 "deep"）。
    """
    # 2.7) 子目标细化主路径（v2.9）：统一档位下先跑一次子目标分解逐步求解
    # 2026-09-06：时间判断升级 gen_time_up（生成侧软截止，给验证留预算）
    if (getattr(self.config, 'enable_subgoal_main_path', True)
            and not ctx.state.emergency
            and not ctx.gen_time_up()):
        self.record(ctx, "control",
                    "子目标细化主路径先行（前置形式化已校准题意）")
        # P4（2026-09-11）：2.7 阶段预算上限——把超额时间让给验证与重解。
        # 数据依据（official112 冒烟实测）：2.7 单阶段耗 753–1078s（占 1200s 硬顶的
        #   63–90%），波动可达 base 均值(513s)的 2 倍；致 3.x / 4 验证 / 4.6 对抗 /
        #   P1 重解全部无预算（P1 三次前移均因时间耗尽而未触发）。
        # 口径：档位软预算 × ratio（默认 0.55 → standard≈297s / deep≈660s），
        #   且不低于 240s（保证子目标链有基本时间）；ratio 可经 config 覆盖
        #   （subgoal_phase_budget_ratio，设 1.0 等价于关闭本限制，便于 A/B 对照）。
        # 实现：临时收紧 ctx.deadline（子目标链内部的时间判断随之生效），
        #   finally 恢复原 deadline，不影响后续阶段。
        # 2026-09-13 预算修复（两处问题）：
        # ① 原用 `soft_budget × ratio`，**未扣除 reserve** ⇒ deep 档 660s
        #    直接吃掉本该留给后段（4_verify/4.6/6.5）的配额；
        # ② 默认 0.55 过大（实测 2.7 常跑到 816s，预算形同虚设）。
        # 现统一走 `_phase_budget`（(soft − reserve) × ratio）并下调到 0.30
        # ⇒ deep：(1200−420)×0.30 = **234s**，为 3_solve / 3.3 / 后段留空间。
        # 2026-09-13：改走**实测上限**口径（旧的比例切分 ratio 无实测依据，
        # 且把单题预算切成 234s 碎块、砍掉有用工作 —— 详见 `_phase_budget`
        # docstring）。本阶段上限 = 实测 max 1168s × 余量。
        _p4_cap = self._phase_budget(ctx, stage="2.7_subgoal_main")
        _p4_t0, _p4_saved_dl = self._phase_deadline_guard(ctx, _p4_cap)
        try:
            self.sub_goal_solver.run(ctx)
        finally:
            self._phase_deadline_restore(ctx, _p4_saved_dl)
        ctx._subgoal_main_done = True
        self.record(ctx, "control",
                    f"2.7 阶段预算 {_p4_cap:.0f}s"
                    f"（实耗 {time.time() - _p4_t0:.0f}s）")

    # C-lite（2026-09-03）：子目标蓝图 merge 产出后、候选生成前，
    # 数值攻击蓝图极值声称——009 型"蓝图心算错值"在求解前就证伪。
    # 审核修正（2026-09-03）：原读 `_blueprint_value_false`（带下划线），
    # 写入处是 `blueprint_value_false`（无下划线）→ 幂等守卫从未生效。
    if not getattr(ctx, "blueprint_value_false", None):
        try:
            self._value_attack_blueprint(ctx, tier)
        except Exception as exc:  # noqa: BLE001  数值攻击失败不阻断主链路
            # 2026-09-03 审核：原为 `pass` 无日志 → v17 全程 0 痕迹时
            # 无法区分"未触发"与"异常被吞"（与 lean_gate 吞 AttributeError
            # 同型）。改为 warning + 埋点，任何失败都留证据。
            logger.warning("[C-lite] 数值攻击异常（已跳过）: %s: %s",
                           type(exc).__name__, exc)
            self.record(ctx, "value_attack",
                        f"数值攻击异常跳过: {type(exc).__name__}: {exc}")


def complete_truncated(self, ctx, tier: str) -> None:
    """3.2 截断候选续写（统一档位 max_completions 个，emergency/verify_only 跳过）。

    参数 `self` 即 `Orchestrator` 实例（沿用方法体原文，故保留名 `self`），
    `ctx` 为 `TaskContext`，`tier` 为当前档位（本项目恒为 "deep"）。
    返回 None；结果写回 `ctx.candidates`。
    """
    # 3.2) 截断候选续写：统一档位 max_completions 个，应急模式跳过
    if (getattr(ctx, 'candidates', None)
            and not ctx.state.emergency
            and not ctx.state.verify_only):
        max_comp = self.config.tier_max_completions.get(tier, 1)
        if max_comp > 0:
            n_completed = self.solver.complete_truncated_candidates(
                ctx, max_count=max_comp)
            if n_completed > 0:
                self.record(ctx, "control",
                            f"截断续写完成 {n_completed} 个候选")
        else:
            # ★ 2026-10-07 分支静默跳过埋点（问题总账 §2.6「隐形门控」）：原
            #   `if max_comp > 0:` 无 else ⇒ max_completions 配 0 时**静默跳过
            #   整个 3.2**，阶段耗时为 0 却看不出"是配置 0 还是没触发"。
            self.record(ctx, "control",
                        f"3.2 截断续写跳过：档位 {tier} max_completions="
                        f"{max_comp}（<=0 ⇒ 本阶段不执行）")
    else:
        self.record(ctx, "control",
                    "3.2 截断续写跳过："
                    + ("无候选" if not getattr(ctx, "candidates", None) else
                       ("emergency 状态" if ctx.state.emergency else
                        "verify_only 状态")))
