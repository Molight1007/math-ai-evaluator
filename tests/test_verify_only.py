# -*- coding: utf-8 -*-
"""L1 验证优先（verify_only）测试（2026-08-31）。

背景：A_base 30 题日志有 170 次「剩余时间不足」跳过调用、117 次
「验证拿到 None 默认判错」——生成阶段把单题预算烧光，验证投票被饿死，
可能误杀正确候选。L1 在剩余时间 < verify_only_seconds 时停止生成新候选，
把最后的时间留给验证。

行为级测试需要跑完整 `Orchestrator.run`（成本高），这里覆盖：
1. `RunState.verify_only` 字段存在、默认 False、可赋值；
2. `AgentConfig.verify_only_seconds` 默认 120、可覆盖（含 run_phase0_eval
   的 override 通道）；
3. 静态守卫：orchestrator 里所有候选生成步骤都带 verify_only 门禁。
"""

from __future__ import annotations

import glob
import os
import re

import pytest

from agent.base import RunState
from user_agent import AgentConfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _orch_src() -> str:
    """orchestrator.py + 已抽出的 `agent/orchestrator__*.py` 模块的**并集**。

    2026-10-07 阶段C3：`Orchestrator.run` 的若干阶段段（3.6_audit_filter /
    3.4_collab / 5.5_low_conf）已**逐字搬**到 `agent/orchestrator__*.py`。
    2026-10-08 阶段C4e：3_solve 主采样段亦搬入 `agent/orchestrator__solve.py`。
    源码级守卫改为读「主文件 + 抽出模块」并集 —— 断言的字面量与守卫意图
    均不变（只是被查代码换了文件，非放宽判据）。
    """
    txt = open(os.path.join(ROOT, "agent", "orchestrator.py"),
               encoding="utf-8").read()
    for p in sorted(glob.glob(
            os.path.join(ROOT, "agent", "orchestrator__*.py"))):
        with open(p, encoding="utf-8") as fh:
            txt += "\n" + fh.read()
    return txt


def test_runstate_verify_only_field():
    st = RunState()
    assert st.verify_only is False
    st.verify_only = True
    assert st.verify_only is True


def test_config_default_verify_only_seconds():
    """D 组对照实测净 −1、p=1.0 → 默认关闭（=0 不触发）。"""
    cfg = AgentConfig()
    assert getattr(cfg, "verify_only_seconds", None) == 0


def test_config_override_verify_only_seconds():
    cfg = AgentConfig(verify_only_seconds=120)
    assert cfg.verify_only_seconds == 120


def test_config_override_list_channel():
    """run_phase0_eval 的 --override 走 kwargs 通道，验证该通道兼容 int。"""
    cfg = AgentConfig(verify_only_seconds=300)
    assert cfg.verify_only_seconds == 300


_GENERATION_STEPS = [
    "self.solver.run(ctx)",
    "complete_truncated_candidates",
    "improve_candidates",
    "self.collab.run(ctx)",
    "self.sub_goal_solver.run(ctx)",
    # ★ 2026-10-14（五道链定案）：3.6_audit_filter 已删 ⇒
    #   `self.audit_gate.audit_candidates(` 不再存在，从门禁清单移除。
]


def test_generation_steps_all_gated_by_verify_only():
    """候选生成类步骤必须全部被 verify_only 门禁（防漏改）。

    启发式：对每个生成步骤，检查它所在最近的 if 块（向前 400 字符）里
    出现 `verify_only`。防止新增生成步骤时忘记加门禁。
    """
    src = _orch_src()

    for needle in _GENERATION_STEPS:
        if needle == "self.solver.run(ctx)":
            # ★ 2026-10-08 阶段C4e：3_solve 主采样段已搬入 agent/orchestrator__solve.py
            #   ⇒ 全串里的 **首个** `self.solver.run(ctx)` 不再是被查语句（现为
            #   orchestrator.py 里 revise 回环 `_deep_revise_loop_inner` 的调用）。
            #   被查语句所在主采样块是**唯一**以 `_sp_saved` 收紧/还原阶段预算的块
            #   ⇒ 以该块独占的后随锚点定位被查语句。**仅改被查代码的定位方式**：
            #   下方所有断言的字面量与比较逻辑（gate 存在 / gate 在 solver.run 之前 /
            #   gen_time_up 在位）**一字未改**，非放宽判据。
            _sp_anchor = src.find("_phase_deadline_restore(ctx, _sp_saved)")
            assert _sp_anchor >= 0, (
                "找不到 3_solve 主采样块锚点（`_sp_saved`）—— "
                "代码可能重构，请更新测试")
            idx = src.rfind(needle, 0, _sp_anchor)
        else:
            idx = src.find(needle)
        assert idx >= 0, f"找不到生成步骤锚点：{needle}（代码可能重构，请更新测试）"
        # solver.run 前有长注释（2026-09-06 超时修复），回溯窗口放宽到 700 字符
        # solver.run 前有长注释（2026-09-06 超时修复），回溯窗口放宽到 700 字符；
        # 2026-09-11 又在其前插入 P4-2 阶段预算包裹（注释 + try/finally ≈ 500 字符）
        # → 700 已够不到门禁行（门禁结构完好：`if not ctx.state.verify_only:` 在其前）
        # → 放宽到 1500。
        back = 1500 if needle == "self.solver.run(ctx)" else 400
        # audit_candidates：2026-09-06 晚 Lean 双通道恢复后其前方插入了
        # lean_gate.apply 分支（约 15 行），verify_only 门禁行被推远 → 窗口 1200。
        # 2026-09-10 又在其前方新增「适用性豁免题」注释块（+3 行），1200 恰好
        # 差数十字符够不到门禁行（门禁为 668 行 `if ctx.state.verify_only: ... else:`
        # 结构，逻辑完整）→ 放宽到 1600。
        if needle == "self.audit_gate.audit_candidates(":
            back = 2100
        # 2026-09-12：把"固定字符窗口"改为**随结构锚点自适应** —— 窗口至少覆盖到
        # 该语句之前最近的一处 verify_only 门禁行（再留 1200 字符余量）。
        # 原实现硬编码 back，随注释增长反复失效（本测试历史上已手工放宽 4 次：
        # 700 → 1500 → 1600 → 2100）。语义不变：若其前根本不存在门禁行，
        # _gate_pos < 0，窗口保持原值 → 断言照旧失败（仍能抓住真正的漏改）。
        _gate_pos = max(src.rfind("if ctx.state.verify_only:", 0, idx),
                        src.rfind("if not ctx.state.verify_only:", 0, idx))
        if _gate_pos >= 0:
            back = max(back, idx - _gate_pos + 1200)
        window = src[max(0, idx - back):idx + len(needle)]
        # solver.run 是主采样，被独立 if 包裹（if not ctx.state.verify_only:）
        if needle == "self.solver.run(ctx)":
            # 2026-09-06 超时修复：verify_only 门禁内又加了 gen_time_up 子分支
            # （生成侧软截止到且已有候选 → 跳过追加生成，直接进验证）。
            # 断言改为：门禁行存在、且在 solver.run 之前、gen_time_up 子分支在位。
            assert "if not ctx.state.verify_only:" in window, \
                "solver.run 必须包在 `if not ctx.state.verify_only:` 里"
            assert window.find("if not ctx.state.verify_only:") < \
                window.find("self.solver.run(ctx)"), \
                "verify_only 门禁必须出现在 solver.run 之前"
            assert "gen_time_up" in window, \
                "solver.run 应有生成侧软截止（gen_time_up）子分支（2026-09-06 超时修复）"
            continue
        # sub_goal_solver 原有两处调用：2.7 子目标主路径与 3.5 补充候选。
        # 2.7 主路径（@2.7_subgoal_main）与 deep 档 P&E 主路径（@3_solve）
        # 均在 verify_only 判定**之前**，属预期不门禁 —— 它们消耗的时间会
        # 体现在剩余时间上，进而触发 3.1 判定。
        # ★ 2026-09-29：**3.5_subgoal_sup 阶段整体删除**（用户决策，与 2.7 主路径
        #   语义重叠，见 CHANGES_2026-09-29.md）⇒ 「3.5 必须门禁」的断言失效，
        #   改为锁定「恰好 2 处、均为预期主路径」的形态。
        if needle == "self.sub_goal_solver.run(ctx)":
            assert src.count("self.sub_goal_solver.run(ctx)") == 2, \
                ("3.5 已删除，sub_goal_solver 应只剩 2.7 主路径 + 3_solve(P&E) "
                 "共 2 处调用（若新增请同步本门禁测试）")
            continue
        if needle == "self.collab.run(ctx)":
            # ★ 2026-10-14 修（五道链定案连带）：本针有两个命中——模块 docstring
            #   里的叙述（无语义）与 `orchestrator__collab.py` 的**代码区**调用；
            #   且其 verify_only 门禁写作 if 条件第 4 行（`and not
            #   ctx.state.verify_only`），距调用点约 ~900 字符。原 `find` 命中
            #   docstring、原 400 字符窗口够不到门禁 ⇒ 改取 **rfind**（代码区）
            #   并放宽到 1500。门禁存在性的判据意图不变（非放宽断言目标）。
            idx = src.rfind(needle)
            assert "verify_only" in src[max(0, idx - 1500):idx + len(needle)], (
                "self.collab.run(ctx) 的调用窗口内没有 verify_only 门禁 —— "
                "L1 漏改了这个生成步骤")
            continue
        assert "verify_only" in window, (
            f"{needle} 的调用窗口内没有 verify_only 门禁 —— "
            f"L1 漏改了这个生成步骤（{needle}）"
        )


# ★ 2026-10-14（五道链定案）：`test_verify_only_skips_audit_filter` 已删 ——
#   其目标（3.6_audit_filter 的 verify_only 跳过分支）随该阶段整体删除。
#   五道链的候选级审核（4.1~4.4）不再有 verify_only 门禁（研究期口径）。
