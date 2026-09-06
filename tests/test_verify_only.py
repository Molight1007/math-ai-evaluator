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

import os
import re

import pytest

from agent.base import RunState
from user_agent import AgentConfig


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
    "self.audit_gate.audit_candidates(",
]


def test_generation_steps_all_gated_by_verify_only():
    """候选生成类步骤必须全部被 verify_only 门禁（防漏改）。

    启发式：对每个生成步骤，检查它所在最近的 if 块（向前 400 字符）里
    出现 `verify_only`。防止新增生成步骤时忘记加门禁。
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "agent", "orchestrator.py")
    src = open(path, encoding="utf-8").read()

    for needle in _GENERATION_STEPS:
        idx = src.find(needle)
        assert idx >= 0, f"找不到生成步骤锚点：{needle}（代码可能重构，请更新测试）"
        # solver.run 前有长注释（2026-09-06 超时修复），回溯窗口放宽到 700 字符
        back = 700 if needle == "self.solver.run(ctx)" else 400
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
        # sub_goal_solver 有两处：2.7 子目标主路径在 verify_only 判定**之前**
        # （属预期不门禁，因为它消耗的时间会体现在剩余时间上，触发 3.1 判定）；
        # 3.5 补充候选在判定之后，必须门禁。锚定 3.5 的那次调用。
        if needle == "self.sub_goal_solver.run(ctx)":
            anchor = src.find("3.5) 子目标分解补充候选")
            assert anchor >= 0, "找不到 3.5 注释锚点"
            tail = src[anchor:anchor + 900]
            assert "verify_only" in tail, \
                "3.5 子目标补充候选没有 verify_only 门禁 —— L1 漏改"
            continue
        assert "verify_only" in window, (
            f"{needle} 的调用窗口内没有 verify_only 门禁 —— "
            f"L1 漏改了这个生成步骤（{needle}）"
        )


def test_verify_only_skips_audit_filter():
    """AuditGate 候选审核（3.6）：verify_only 分支里有显式的跳过记录。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "agent", "orchestrator.py")
    src = open(path, encoding="utf-8").read()
    assert "ctx.state.verify_only" in src
    assert "L1 验证优先：跳过 AuditGate 候选审核（时间不足）" in src
