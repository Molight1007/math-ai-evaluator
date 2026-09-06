# -*- coding: utf-8 -*-
"""生成侧软截止 _gen_deadline / gen_time_up() 测试（2026-09-06 超时修复）。

背景：冒烟 4/5 题烧穿 1200s（stage_timers 实证）——生成类模块（improve/
collab/sub_goal）单次 LLM 可达 200-300s，循环只在候选边界查 is_time_critical
（= deadline-120/60s），最后一段生成必然烧穿 deadline → 4_verify 投票全跳、
答案零验证裸提交。orchestrator 现在按档位设 _gen_deadline = deadline -
verify_reserve，生成循环边界改查 gen_time_up()，到点即停、把 reserve 时间
留给验证/审核。

行为契约：
1. 未设 _gen_deadline（默认 0.0）→ gen_time_up() 完全回退 is_time_critical()；
2. 设了真实 epoch 的 _gen_deadline 且已过 → True（即使 is_time_critical 未到）；
3. 设了但未到 → False；
4. 测试 fixture 的伪 epoch deadline（< 1e8）→ 永远 False（时间无限语义，
   与 time_remaining() 口径一致，避免测试里生成步骤被误报"预算耗尽"）。
"""

from __future__ import annotations

import time

from agent.base import TaskContext


def _mk(deadline: float, gen_deadline: float = 0.0) -> TaskContext:
    ctx = TaskContext(problem="x", metadata={})
    ctx.deadline = deadline
    ctx._gen_deadline = gen_deadline
    return ctx


def test_gen_time_up_unset_degrades_to_is_time_critical():
    """未设 _gen_deadline → 与 is_time_critical 完全一致（零行为变化）。"""
    now = time.time()
    # deadline 30s 后（is_time_critical 阈值 120 → 未临界）
    ctx = _mk(now + 300)
    assert ctx.gen_time_up() is ctx.is_time_critical()
    assert ctx.gen_time_up() is False
    # deadline 已过 10s → 临界
    ctx2 = _mk(now - 10)
    assert ctx2.gen_time_up() is True


def test_gen_time_up_fires_before_is_time_critical():
    """_gen_deadline 已过但 is_time_critical 未到 → gen_time_up=True。"""
    now = time.time()
    # deadline 300s 后，_gen_deadline = now（软截止刚过）→ 生成必须停手，
    # 而 is_time_critical（剩 300s > 120s）仍是 False。
    ctx = _mk(now + 300, gen_deadline=now - 1)
    assert ctx.is_time_critical() is False
    assert ctx.gen_time_up() is True


def test_gen_time_up_not_reached_yet():
    """_gen_deadline 未到 → False。"""
    now = time.time()
    ctx = _mk(now + 300, gen_deadline=now + 60)
    assert ctx.gen_time_up() is False


def test_gen_time_up_pseudo_epoch_deadline_never_fires():
    """测试 fixture 伪 epoch（deadline < 1e8）→ 永不触发（无限时间）。"""
    ctx = _mk(123456.0, gen_deadline=123456.0 - 10)
    assert ctx.gen_time_up() is False
    assert ctx.is_time_critical() is False
