# -*- coding: utf-8 -*-
"""截断埋点测试（2026-08-31 L2.1 任务卡）。

平台 23.21% 评测日志显示 14.2% 调用被截断（truncated_count=434/3061），
但本地 `llm_client` 丢弃了 `finish_reason`，无法定位集中点。
`base._record_truncation_suspect` 在响应长度 ≥ max_tokens × 0.95 时
按 `self.name` 计数。本测试确保：
  1. 计数正确（按 agent 分桶）
  2. reset 干净
  3. 短响应不触发
  4. 并发安全
"""

from __future__ import annotations

import threading

import pytest

from agent import base
from agent.base import (
    _TRUNCATION_LOG,
    _TRUNCATION_RATIO,
    _record_truncation_suspect,
    get_truncation_log,
    reset_truncation_log,
    set_truncation_enabled,
)


@pytest.fixture(autouse=True)
def _clean_state():
    """每个测试前后清空埋点 + 恢复 enabled。"""
    reset_truncation_log()
    set_truncation_enabled(True)
    yield
    reset_truncation_log()
    set_truncation_enabled(True)


def test_short_response_not_recorded():
    """响应长度 < max_tokens × 0.95 不算截断。"""
    _record_truncation_suspect("agent_a", resp_len=400, max_tokens=1024)
    assert get_truncation_log() == []


def test_long_response_recorded():
    """响应长度 ≥ max_tokens × 0.95 触发计数。"""
    _record_truncation_suspect("agent_a", resp_len=975, max_tokens=1024)  # 0.952
    log = get_truncation_log()
    assert len(log) == 1
    assert log[0]["agent"] == "agent_a"
    assert log[0]["resp_len"] == 975
    assert log[0]["max_tokens"] == 1024


def test_at_threshold_recorded():
    """边界：恰好等于 max_tokens × ratio 视为截断。"""
    max_tokens = 1000
    at_threshold = int(max_tokens * _TRUNCATION_RATIO)
    _record_truncation_suspect("agent_b", resp_len=at_threshold, max_tokens=max_tokens)
    assert len(get_truncation_log()) == 1


def test_just_below_threshold_not_recorded():
    max_tokens = 1000
    just_below = int(max_tokens * _TRUNCATION_RATIO) - 1
    _record_truncation_suspect("agent_b", resp_len=just_below, max_tokens=max_tokens)
    assert get_truncation_log() == []


def test_max_tokens_zero_no_record():
    """max_tokens=0 视为不限制，不触发（防御性）。"""
    _record_truncation_suspect("agent_a", resp_len=10000, max_tokens=0)
    assert get_truncation_log() == []


def test_max_tokens_none_no_record():
    _record_truncation_suspect("agent_a", resp_len=10000, max_tokens=None)
    assert get_truncation_log() == []


def test_distinct_agents_separate_buckets():
    """多 agent 计数各自独立。"""
    _record_truncation_suspect("verifier", 975, 1024)
    _record_truncation_suspect("verifier", 980, 1024)
    _record_truncation_suspect("solver", 975, 1024)
    log = get_truncation_log()
    assert len(log) == 3
    by_agent = {}
    for e in log:
        by_agent[e["agent"]] = by_agent.get(e["agent"], 0) + 1
    assert by_agent == {"verifier": 2, "solver": 1}


def test_reset_clears_log():
    """reset 后计数清零。"""
    _record_truncation_suspect("a", 975, 1024)
    _record_truncation_suspect("b", 975, 1024)
    assert len(get_truncation_log()) == 2
    reset_truncation_log()
    assert get_truncation_log() == []


def test_disabled_globally_skips_recording():
    """set_truncation_enabled(False) 时不再记录。"""
    set_truncation_enabled(False)
    _record_truncation_suspect("a", 975, 1024)
    assert get_truncation_log() == []


def test_concurrent_recording_is_thread_safe():
    """并发调用不丢记录（threading.Lock 保护 _TRUNCATION_LOG）。"""
    N_THREADS = 8
    PER_THREAD = 50

    def worker(tid: int):
        for i in range(PER_THREAD):
            _record_truncation_suspect(f"agent_{tid}", 975, 1024)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    log = get_truncation_log()
    assert len(log) == N_THREADS * PER_THREAD, (
        f"期望 {N_THREADS * PER_THREAD} 条，"
        f"实际 {len(log)} 条（并发丢记录）"
    )


def test_module_exports_present():
    """公共接口存在且可调用（防御 import 误删）。"""
    for name in ("get_truncation_log", "reset_truncation_log",
                "set_truncation_enabled", "_record_truncation_suspect"):
        assert hasattr(base, name), f"agent.base 缺接口：{name}"
    assert hasattr(base, "_TRUNCATION_LOG")
    assert isinstance(_TRUNCATION_RATIO, float)
    assert 0.0 < _TRUNCATION_RATIO <= 1.0
