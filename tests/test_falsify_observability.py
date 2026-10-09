# -*- coding: utf-8 -*-
"""证伪器观测守卫（2026-10-09 P0）。

缺陷（观测缺口）
================
证伪器**命中**时写 `step == "falsify"`，**未命中 / 被前置条件挡住**时写
`step == "falsify_miss"`（`orchestrator__oracle._falsify_rejects`）。而
`diag_export.falsify_events` **只过滤命中键** ⇒ `falsify_miss` 一条都不落盘
⇒ "没调用 / 调了没命中 / 被前置条件挡住"三者不可区分。实测 smoke10：
`falsify_events == 0` 但 `oracle_review_events` 里明明有
"证伪器命中（sympy）" ⇒ 命题成立但导出缺失。

修复后的契约（本测试锁定）
==========================
1. `falsify_events`      —— 命中键，**旧口径 / 220 截断保持不变**；
2. `falsify_hit_events`  —— 命中的**显式命名**键，与 (1) **逐条一致**（口径未漂移）；
3. `falsify_miss_events` —— **未命中**键（新），与 (1) 同 220 截断。

并锁定 `_falsify_rejects` 的**每一个失败出口**恰好写一条 `falsify_miss`
（"没调用 / 调了没命中 / 被前置条件挡住"必须可区分且各留一条痕）。
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from agent.base import TaskContext
from agent.diag_export import collect_diag
from agent.orchestrator import Orchestrator


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def _ctx_with_trace(steps) -> TaskContext:
    """构造带指定 (step, content) 序列的 TaskContext（trace 为列表）。"""
    ctx = TaskContext(problem="p", metadata={})
    for step, content in steps:
        ctx.trace.append({"agent": "t", "step": step, "content": content})
    return ctx


def _orch(enable_falsifier: bool = True) -> Orchestrator:
    o = Orchestrator(MagicMock(), MagicMock())
    o.config.enable_answer_falsifier = enable_falsifier
    return o


def _count(ctx, step: str) -> int:
    return sum(1 for t in (ctx.trace or [])
               if isinstance(t, dict) and t.get("step") == step)


def _diag(ctx) -> dict:
    """直调 diag_export 导出函数（stage_durs 给最小可调用桩，避免依赖 orchestrator）。"""
    return collect_diag(ctx, config=MagicMock(), stage_durs=lambda _c: {})


# ----------------------------------------------------------------------
# 1) diag_export：三个键的条数 / 内容 / 口径
# ----------------------------------------------------------------------
def test_three_falsify_keys_extracted_from_trace():
    """命中键 2 条 + 未命中键 3 条，逐键条数与内容正确，互不污染。"""
    ctx = _ctx_with_trace([
        ("falsify_miss", "证伪未命中（放行）：未取得证伪证书"),
        ("falsify", "证伪命中：候选答案代回题目条件后出现确定性矛盾"),
        ("falsify_miss", "证伪未命中（放行）：证书无可机检等式"),
        ("falsify", "证伪命中：第二条"),
        ("oracle_review", "证伪器命中（sympy）：不得混入实现键"),  # 噪声
        ("falsify_miss", "证伪未命中（放行）：答案过长，非数值型"),
    ])
    diag = _diag(ctx)

    assert len(diag["falsify_events"]) == 2, diag["falsify_events"]
    assert len(diag["falsify_hit_events"]) == 2, diag["falsify_hit_events"]
    assert len(diag["falsify_miss_events"]) == 3, diag["falsify_miss_events"]

    # 内容正确
    assert "证伪命中" in diag["falsify_hit_events"][0]
    assert "未取得证伪证书" in diag["falsify_miss_events"][0]
    assert "证书无可机检等式" in diag["falsify_miss_events"][1]
    assert "答案过长" in diag["falsify_miss_events"][2]

    # 不得互相污染：命中键里无"未命中"，未命中键里无"命中："（注意"未命中（"含"命中"）
    assert all("未命中" not in e for e in diag["falsify_events"])
    assert all("命中：" not in e for e in diag["falsify_miss_events"])
    # oracle_review 噪声不得混入任何一个 falsify_* 键
    assert all("不得混入" not in e
               for k in ("falsify_events", "falsify_hit_events",
                         "falsify_miss_events")
               for e in diag[k])


def test_hit_key_equals_legacy_falsify_events():
    """口径未漂移：`falsify_events`（旧）与 `falsify_hit_events`（新）逐条一致。"""
    ctx = _ctx_with_trace([
        ("falsify", "A"), ("falsify_miss", "B"), ("falsify", "C"),
    ])
    diag = _diag(ctx)
    assert diag["falsify_events"] == diag["falsify_hit_events"]
    assert diag["falsify_events"] == ["A", "C"]
    assert diag["falsify_miss_events"] == ["B"]


def test_all_three_keys_truncate_to_220():
    """三个键同按 220 字符截断（命中键截断长度不得因本次改动而变）。"""
    ctx = _ctx_with_trace([("falsify_miss", "m" * 500), ("falsify", "h" * 500)])
    diag = _diag(ctx)
    assert len(diag["falsify_miss_events"][0]) == 220
    assert len(diag["falsify_hit_events"][0]) == 220
    assert len(diag["falsify_events"][0]) == 220


def test_empty_trace_all_three_keys_empty():
    """无 trace 时三键皆空列表（getattr 兜底、不崩）。"""
    diag = _diag(_ctx_with_trace([]))
    assert diag["falsify_events"] == []
    assert diag["falsify_hit_events"] == []
    assert diag["falsify_miss_events"] == []


# ----------------------------------------------------------------------
# 2) _falsify_rejects：每个失败出口恰好一条 falsify_miss
# ----------------------------------------------------------------------
def test_exit_config_off_records_one_miss():
    """出口「证伪器已关闭（前置拦截）」→ 恰好一条 miss。"""
    ctx = TaskContext(problem="p", metadata={})
    assert _orch(enable_falsifier=False)._falsify_rejects(ctx, "42") is False
    assert _count(ctx, "falsify_miss") == 1
    assert _count(ctx, "falsify") == 0
    assert "已关闭" in ctx.trace[-1]["content"]


def test_exit_empty_answer_records_one_miss():
    """出口「答案为空白（前置拦截）」→ 恰好一条 miss。"""
    ctx = TaskContext(problem="p", metadata={})
    assert _orch(True)._falsify_rejects(ctx, "   ") is False
    assert _count(ctx, "falsify_miss") == 1
    assert _count(ctx, "falsify") == 0
    assert "空白" in ctx.trace[-1]["content"]


def test_exit_time_critical_records_one_miss():
    """出口「时间不足（前置拦截）」→ 恰好一条 miss。"""
    ctx = TaskContext(problem="p", metadata={})
    ctx.deadline = time.time() - 100.0        # 真实 epoch 且已过期（>=1e8）
    ctx.critical_tail_seconds = 120.0
    assert ctx.is_time_critical() is True, "前置条件未生效，测试无效"
    assert _orch(True)._falsify_rejects(ctx, "42") is False
    assert _count(ctx, "falsify_miss") == 1
    assert _count(ctx, "falsify") == 0
    assert "时间不足" in ctx.trace[-1]["content"]


def test_exit_inner_unknown_records_one_miss(monkeypatch):
    """出口「证伪器返回 unknown（调了没命中）」→ 恰好一条 miss。"""
    from agent.answer_falsifier import AnswerFalsifier, FalsifyResult

    def _fake_falsify(self, ctx, cand, problem=""):  # noqa: ANN001
        return FalsifyResult(reason="未取得证伪证书")

    monkeypatch.setattr(AnswerFalsifier, "falsify", _fake_falsify)
    ctx = TaskContext(problem="p", metadata={})
    assert _orch(True)._falsify_rejects(ctx, "42") is False
    assert _count(ctx, "falsify_miss") == 1
    assert _count(ctx, "falsify") == 0
    assert "未取得证伪证书" in ctx.trace[-1]["content"]


def test_exit_inner_incorrect_records_hit_not_miss(monkeypatch):
    """对照：证伪器返回 incorrect（命中）→ 一条 hit、零 miss（互斥）。"""
    from agent.answer_falsifier import AnswerFalsifier, FalsifyResult

    def _fake_falsify(self, ctx, cand, problem=""):  # noqa: ANN001
        return FalsifyResult(verdict="incorrect", reason="确定性矛盾",
                             witness="w", oracle_type="sympy")

    monkeypatch.setattr(AnswerFalsifier, "falsify", _fake_falsify)
    ctx = TaskContext(problem="p", metadata={})
    assert _orch(True)._falsify_rejects(ctx, "42") is True
    assert _count(ctx, "falsify_miss") == 0
    assert _count(ctx, "falsify") == 1


def test_exit_falsifier_exception_records_one_miss(monkeypatch):
    """出口「证伪器异常（兜底 except）」→ 恰好一条 miss（不静默消失）。"""
    from agent.answer_falsifier import AnswerFalsifier

    def _boom(self, ctx, cand, problem=""):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr(AnswerFalsifier, "falsify", _boom)
    ctx = TaskContext(problem="p", metadata={})
    assert _orch(True)._falsify_rejects(ctx, "42") is False
    assert _count(ctx, "falsify_miss") == 1
    assert _count(ctx, "falsify") == 0
    assert "异常" in ctx.trace[-1]["content"]
    assert "RuntimeError" in ctx.trace[-1]["content"]
