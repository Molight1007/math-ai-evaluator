# -*- coding: utf-8 -*-
"""#44 定理调用埋点（TheoremCallStats）单元测试。

覆盖老师要回答的核心问题：「调用次数频繁但调用的定理个数并不多」——
即 calls / hits / unique / adopted 四维统计是否口径正确。
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from tools.lean_local.lean_search import MathlibTheoremSearcher, TheoremCallStats


def _res(*names: str) -> list[dict]:
    """构造归一化检索结果（只需 name 字段参与去重统计）。"""
    return [{"name": n, "kind": "theorem", "file": "", "line": 0, "snippet": ""}
            for n in names]


class TestTheoremCallStats:
    """埋点收集器本身的口径测试（不依赖外部服务）。"""

    def test_empty_summary_is_safe(self):
        """零调用时汇总不应除零，各字段有默认值。"""
        s = TheoremCallStats()
        d = s.summary()
        assert d["calls"] == 0
        assert d["hits"] == 0
        assert d["unique"] == 0
        assert d["adopted"] == 0
        assert d["avg_ms_per_call"] == 0.0
        assert d["hits_per_call"] == 0.0
        assert d["unique_per_call"] == 0.0

    def test_calls_and_hits_accumulate(self):
        """调用次数累加；命中条数为每次返回结果数的累加（不去重）。"""
        s = TheoremCallStats()
        s.record("q1", "local", _res("a", "b"), 10.0)
        s.record("q2", "local", _res("b", "c"), 20.0)
        d = s.summary()
        assert d["calls"] == 2
        assert d["hits"] == 4          # 2 + 2，含重复
        assert d["total_ms"] == 30.0
        assert d["avg_ms_per_call"] == 15.0

    def test_unique_dedups_across_calls(self):
        """去重后条数按定理全名跨调用去重——这是老师问题的关键维度。"""
        s = TheoremCallStats()
        for _ in range(5):
            s.record("same query", "local", _res("a", "b"), 1.0)
        d = s.summary()
        assert d["calls"] == 5
        assert d["hits"] == 10
        assert d["unique"] == 2        # 反复调用只命中同 2 个定理
        assert d["unique_per_call"] == pytest.approx(0.4)

    def test_adopted_is_fourth_dimension(self):
        """最终被采用条数由上层回记，且给出采纳率。"""
        s = TheoremCallStats()
        s.record("q", "local", _res("a", "b", "c"), 1.0)
        s.note_adopted(["a"])
        d = s.summary()
        assert d["unique"] == 3
        assert d["adopted"] == 1
        # adopted_ratio 按 3 位小数落库，断言需与之一致
        assert d["adopted_ratio"] == pytest.approx(0.333, abs=1e-3)

    def test_note_adopted_accepts_single_string(self):
        """上层可能传单个字符串而非列表，不应静默丢数据。"""
        s = TheoremCallStats()
        s.note_adopted("EuclideanDomain.gcd_dvd")
        assert s.summary()["adopted"] == 1

    def test_empty_calls_counted(self):
        """空结果调用次数单独统计（LeanSearch v2 空集信号的数据来源）。"""
        s = TheoremCallStats()
        s.record("q1", "official", [], 1.0)
        s.record("q2", "official", _res("a"), 1.0)
        d = s.summary()
        assert d["empty_calls"] == 1
        assert d["by_backend"] == {"official": 2}

    def test_flush_writes_jsonl_and_clears_events(self):
        """落盘为 JSONL：每条事件一行，末尾附汇总行；写后清空事件缓冲。"""
        s = TheoremCallStats()
        s.record("q", "local", _res("a", "b"), 1.0)
        s.note_adopted(["a"])
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "stats.jsonl")
            assert s.flush(path) is True
            with open(path, "r", encoding="utf-8") as fh:
                lines = [json.loads(x) for x in fh if x.strip()]
        assert len(lines) == 3                     # call + adopted + summary
        assert lines[0]["type"] == "call"
        assert lines[1]["type"] == "adopted"
        assert lines[2]["type"] == "summary"
        assert lines[2]["unique"] == 2
        assert s._events == []                     # 落盘后缓冲清空

    def test_flush_without_path_returns_false(self):
        """未配置落盘路径时返回 False，不抛异常。"""
        s = TheoremCallStats()
        assert s.flush() is False


class TestSearcherWiring:
    """埋点与 search() 的接线测试：入口改包装层后行为不能变。"""

    def test_search_records_stats(self, monkeypatch):
        """search() 每次调用都应记一笔埋点，且返回值与原实现一致。"""
        searcher = MathlibTheoremSearcher(roots=[])
        stats = TheoremCallStats()
        searcher.stats = stats          # 用独立收集器，避免污染全局

        monkeypatch.setattr(
            searcher, "_search_impl",
            lambda q, limit=5: {"status": "ok", "query": q,
                                "results": _res("x", "y"), "official": False},
        )
        res = searcher.search("some query", limit=5)

        assert res["status"] == "ok"
        assert len(res["results"]) == 2
        d = stats.summary()
        assert d["calls"] == 1
        assert d["hits"] == 2
        assert d["unique"] == 2
        assert d["by_backend"] == {"local": 1}

    def test_search_marks_official_backend(self, monkeypatch):
        """官方后端返回的 official 标记应体现在 by_backend 里。"""
        searcher = MathlibTheoremSearcher(roots=[])
        stats = TheoremCallStats()
        searcher.stats = stats
        monkeypatch.setattr(
            searcher, "_search_impl",
            lambda q, limit=5: {"status": "ok", "query": q,
                                "results": _res("z"), "official": True},
        )
        searcher.search("q")
        assert stats.summary()["by_backend"] == {"official": 1}

    def test_search_exception_still_records_and_reraises(self, monkeypatch):
        """检索抛异常时：埋点照记，异常照抛（不改变原语义）。"""
        searcher = MathlibTheoremSearcher(roots=[])
        stats = TheoremCallStats()
        searcher.stats = stats

        def _boom(q, limit=5):
            raise RuntimeError("backend down")

        monkeypatch.setattr(searcher, "_search_impl", _boom)
        with pytest.raises(RuntimeError):
            searcher.search("q")
        assert stats.summary()["calls"] == 1
        assert stats.summary()["by_backend"] == {"error": 1}

    def test_stats_failure_never_breaks_search(self, monkeypatch):
        """埋点自身出错必须被吞掉，绝不能阻断检索主流程。"""
        searcher = MathlibTheoremSearcher(roots=[])
        monkeypatch.setattr(
            searcher, "_search_impl",
            lambda q, limit=5: {"status": "ok", "results": _res("a"), "official": False},
        )

        class _BrokenStats(TheoremCallStats):
            def record(self, *a, **kw):
                raise RuntimeError("stats broken")

        searcher.stats = _BrokenStats()
        res = searcher.search("q")          # 不应抛出
        assert res["status"] == "ok"
        assert len(res["results"]) == 1
