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

from agent.base import Candidate, TaskContext
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


# ----------------------------------------------------------------------
# 3) _falsify_candidates：逐候选恰好一条痕（命中/未命中/异常互斥）+ 带候选标识
# ----------------------------------------------------------------------
def _mk_candidates(n: int):
    """构造 n 个带 id 的候选（id = 0..n-1）。"""
    return [Candidate(id=i, answer="ans%d" % i, reasoning="") for i in range(n)]


def _has_tag(events, i: int) -> bool:
    """事件里是否含候选 #i 的标识（命中格式 `#i：`，未命中格式 `#i（`）。"""
    return any(("#%d：" % i) in e or ("#%d（" % i) in e for e in events)


def test_falsify_candidates_each_candidate_exactly_one_trace(monkeypatch):
    """N 候选：1 个可证伪、N-1 个不可 ⇒ hit 恰 1 条、miss 恰 N-1 条，且都带候选标识。"""
    from agent.answer_falsifier import AnswerFalsifier, FalsifyResult

    N = 4
    _HIT_ID = 2

    def _fake(self, ctx, cand, problem=""):  # noqa: ANN001
        if getattr(cand, "id", None) == _HIT_ID:
            return FalsifyResult(verdict="incorrect", reason="确定性矛盾",
                                 witness="w", oracle_type="sympy")
        return FalsifyResult(reason="未取得证伪证书")

    monkeypatch.setattr(AnswerFalsifier, "falsify", _fake)
    ctx = TaskContext(problem="p", metadata={})
    ctx.candidates = _mk_candidates(N)

    avail, n_surv = _orch(True)._falsify_candidates(ctx)
    assert avail is True and n_surv == N - 1

    diag = _diag(ctx)
    hit = diag["falsify_events"]
    miss = diag["falsify_miss_events"]
    assert len(hit) == 1, hit
    assert _has_tag(hit, _HIT_ID) and "证伪命中" in hit[0]
    assert len(miss) == N - 1, miss
    # 逐候选：命中候选不出现在 miss；其余每个都带各自标识（互斥、不漏记）
    for i in range(N):
        assert _has_tag(miss, i) == (i != _HIT_ID), (i, miss)
    # 总痕数 == N（命中 1 + 未命中 N-1）
    assert len(hit) + len(miss) == N
    # 命中键与显式命名键逐条一致
    assert diag["falsify_hit_events"] == hit
    # 整批汇总已改记 `control`，不再污染 `falsify` 键
    assert all("个候选被客观证伪" not in e for e in hit)
    assert any("个候选被客观证伪" in str(t.get("content", ""))
               for t in ctx.trace if t.get("step") == "control")


def test_falsify_candidates_tag_falls_back_to_index(monkeypatch):
    """候选无 id ⇒ 用列表下标作标识。"""
    from types import SimpleNamespace

    from agent.answer_falsifier import AnswerFalsifier, FalsifyResult

    monkeypatch.setattr(AnswerFalsifier, "falsify",
                        lambda self, c, problem="": FalsifyResult(reason="x"))
    ctx = TaskContext(problem="p", metadata={})
    ctx.candidates = [SimpleNamespace(answer="a"), SimpleNamespace(answer="b")]
    _orch(True)._falsify_candidates(ctx)
    miss = _diag(ctx)["falsify_miss_events"]
    assert len(miss) == 2, miss
    assert _has_tag(miss, 0) and _has_tag(miss, 1)


def test_falsify_candidates_per_candidate_exception(monkeypatch):
    """某候选证伪抛异常 ⇒ 该候选记 `证伪异常 #<id>`（miss 键），不静默消失。"""
    from agent.answer_falsifier import AnswerFalsifier, FalsifyResult

    def _flaky(self, ctx, cand, problem=""):  # noqa: ANN001
        if getattr(cand, "id", None) == 1:
            raise RuntimeError("boom")
        return FalsifyResult(reason="未取得证伪证书")

    monkeypatch.setattr(AnswerFalsifier, "falsify", _flaky)
    ctx = TaskContext(problem="p", metadata={})
    ctx.candidates = _mk_candidates(3)
    avail, n_surv = _orch(True)._falsify_candidates(ctx)
    assert avail is True and n_surv == 3          # 异常候选算未被证伪 ⇒ 幸存
    miss = _diag(ctx)["falsify_miss_events"]
    assert len(miss) == 3, miss
    assert any("证伪异常 #1" in e and "RuntimeError" in e for e in miss)


def test_falsify_candidates_inloop_time_critical_skip(monkeypatch):
    """循环中时间变紧 ⇒ 剩余候选各记 1 条 miss（等价旧 break，返回值不变）。"""
    from agent.answer_falsifier import AnswerFalsifier, FalsifyResult

    def _fake(self, ctx, cand, problem=""):  # noqa: ANN001
        ctx.deadline = time.time() - 100.0        # 首个候选处理后即 critical
        return FalsifyResult(reason="未取得证伪证书")

    monkeypatch.setattr(AnswerFalsifier, "falsify", _fake)
    ctx = TaskContext(problem="p", metadata={})
    ctx.critical_tail_seconds = 120.0
    ctx.candidates = _mk_candidates(3)
    avail, n_surv = _orch(True)._falsify_candidates(ctx)
    assert avail is True and n_surv == 3
    miss = _diag(ctx)["falsify_miss_events"]
    assert len(miss) == 3, miss
    assert any("时间不足，跳过" in e for e in miss)


def test_falsify_candidates_batch_guard_config_off():
    """开关关 ⇒ 整批跳过，1 条批级 miss（无候选被尝试）。"""
    ctx = TaskContext(problem="p", metadata={})
    ctx.candidates = _mk_candidates(3)
    assert _orch(False)._falsify_candidates(ctx) == (False, 0)
    diag = _diag(ctx)
    assert diag["falsify_events"] == []
    assert len(diag["falsify_miss_events"]) == 1
    assert "已关闭" in diag["falsify_miss_events"][0]


def test_falsify_candidates_batch_guard_empty_pool():
    """空候选池 ⇒ 整批跳过，1 条批级 miss。"""
    ctx = TaskContext(problem="p", metadata={})   # candidates 默认 []
    assert _orch(True)._falsify_candidates(ctx) == (False, 0)
    diag = _diag(ctx)
    assert len(diag["falsify_miss_events"]) == 1
    assert "候选池为空" in diag["falsify_miss_events"][0]


def test_falsify_candidates_batch_guard_preloop_time_critical():
    """进循环前时间不足 ⇒ 整批跳过，1 条批级 miss。"""
    ctx = TaskContext(problem="p", metadata={})
    ctx.candidates = _mk_candidates(2)
    ctx.deadline = time.time() - 100.0
    ctx.critical_tail_seconds = 120.0
    assert ctx.is_time_critical() is True, "前置条件未生效，测试无效"
    assert _orch(True)._falsify_candidates(ctx) == (False, 0)
    diag = _diag(ctx)
    assert diag["falsify_events"] == []
    assert len(diag["falsify_miss_events"]) == 1
    assert "整批跳过" in diag["falsify_miss_events"][0]
