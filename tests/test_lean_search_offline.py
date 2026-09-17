# -*- coding: utf-8 -*-
"""LeanSearch 重启相关单元测试（2026-09-15）。

背景
----
老师建议「求解子目标关键在定理的 Mathlib 搜索」，而实测发现历史 3 批共 202 题
`mathlib_usage_stats.search_calls` **恒为 0** —— LeanSearch 从未真正运行。三重静默失效：
  ① 主仓 `tools/lean_local/` 下没有 `lean_search.py`（只有 vendor 归档副本）；
  ② `AgentConfig` 没有 `use_leansearch` 字段 ⇒ `getattr(..., False)` 永远 False；
  ③ `lean_gate`/`lean_refiner` 的 import 被裸 `except` 吞掉（只打 debug）。
本测试覆盖修复后的行为，并且**全程离线**（不依赖 leansearch.net）。

覆盖:
- `TheoremCallStats`: #44 四维埋点（调用次数/命中数/去重后条数/被采用条数）+ 落盘
- 源码扫描后端：合成 mathlib 目录、top-k、状态上报
- 检索器总入口的降级语义（无 root、无命中时不抛异常）
- 验证器注入（方案 A）：开关矩阵、缓存、单题次数上限、跳过时间紧张
- 提示词槽位 `{theorem_context}` 存在且可格式化
- `orchestrator._summarize_leansearch`: 按题聚合
"""
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from agent.base import TaskContext
from agent.verifier import VerifierAgent
from prompts.verifier import VERIFIER_USER_TEMPLATE
from tools.lean_local.lean_search import (
    MathlibTheoremSearcher,
    TheoremCallStats,
    normalize_query,
)


def make_ctx(problem="probe"):
    return TaskContext(problem=problem, metadata={})


def make_verifier(**cfg):
    base = {
        "use_leansearch": True,
        "leansearch_inject_verifier": True,
        "leansearch_top_k": 5,
        "leansearch_max_calls_per_q": 2,
    }
    base.update(cfg)
    return VerifierAgent(client=object(), config=SimpleNamespace(**base))


FAKE_RESULTS = [
    {"name": "Mathlib.Algebra.EuclideanDomain.gcd_dvd",
     "kind": "theorem", "snippet": "(a b : R) : gcd a b ∣ a ∧ gcd a b ∣ b",
     "file": "Mathlib/Algebra/EuclideanDomain/Basic.lean", "line": 1},
    {"name": "Mathlib.Algebra.EuclideanDomain.gcd_dvd_right",
     "kind": "theorem", "snippet": "(a b : R) : gcd a b ∣ b",
     "file": "Mathlib/Algebra/EuclideanDomain/Basic.lean", "line": 2},
]


class _StubSearcher:
    """离线替身：绝不触网，可控制返回条数。"""

    calls = 0

    def __init__(self, *a, **kw):
        pass

    def search(self, query, limit=5):
        _StubSearcher.calls += 1
        return {"status": "ok", "root": "stub://offline",
                "results": FAKE_RESULTS[:max(1, int(limit))]}

    def status(self):
        return {"available": True, "root": "stub://offline",
                "indexed_declarations": len(FAKE_RESULTS), "official": False}


class _EmptySearcher(_StubSearcher):
    def search(self, query, limit=5):
        _StubSearcher.calls += 1
        return {"status": "ok", "root": "stub://offline", "results": []}


class TheoremCallStatsTest(unittest.TestCase):
    """老师 #44：埋点必须能回答四个维度。"""

    def test_record_accumulates_four_dimensions(self):
        st = TheoremCallStats()
        st.record("q1", "official", FAKE_RESULTS, elapsed_ms=100.0)
        st.record("q2", "official", FAKE_RESULTS[:1], elapsed_ms=50.0)
        s = st.summary()
        self.assertEqual(s["calls"], 2)          # 调用次数
        self.assertEqual(s["hits"], 3)           # 命中条数（累加）
        self.assertEqual(s["unique"], 2)         # 去重后条数
        self.assertEqual(s["adopted"], 0)
        self.assertEqual(s["total_ms"], 150.0)
        self.assertEqual(s["by_backend"], {"official": 2})

    def test_empty_result_counted(self):
        st = TheoremCallStats()
        st.record("q", "local", [], elapsed_ms=10.0)
        s = st.summary()
        self.assertEqual(s["calls"], 1)
        self.assertEqual(s["hits"], 0)
        self.assertEqual(s["empty_calls"], 1)

    def test_ratios_answer_call_frequency_question(self):
        """老师原话：「调用次数频繁但调用的定理个数并不多」——比值要能看出来。"""
        st = TheoremCallStats()
        st.record("q", "official", FAKE_RESULTS, elapsed_ms=10.0)
        st.record("q", "official", FAKE_RESULTS, elapsed_ms=10.0)
        st.note_adopted(["Mathlib.Algebra.EuclideanDomain.gcd_dvd"])
        s = st.summary()
        self.assertEqual(s["hits_per_call"], 2.0)
        self.assertEqual(s["unique_per_call"], 1.0)   # 2 次调用只碰到 1 种定理
        self.assertEqual(s["adopted_ratio"], 0.5)
        self.assertEqual(s["adopted"], 1)

    def test_note_adopted_accepts_str(self):
        st = TheoremCallStats()
        st.note_adopted("Foo.bar")
        self.assertEqual(st.summary()["adopted"], 1)

    def test_flush_writes_jsonl_and_resets_events(self):
        st = TheoremCallStats()
        st.record("q", "official", FAKE_RESULTS, elapsed_ms=1.0)
        st.note_adopted(["Foo.bar"])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "calls.jsonl")
            self.assertTrue(st.flush(p))
            with open(p, encoding="utf-8") as fh:
                lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 3)          # call + adopted + summary
        self.assertIn('"type": "summary"', lines[-1])
        # 落盘后事件清空，避免下次重复写
        self.assertEqual(st._events, [])

    def test_flush_without_path_returns_false(self):
        self.assertFalse(TheoremCallStats().flush())


class SourceScanBackendTest(unittest.TestCase):
    """离线源码扫描后端：合成 mathlib 目录，全程不触网。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ls_offline_")
        ml = os.path.join(cls.tmp, "Mathlib", "Algebra")
        os.makedirs(ml, exist_ok=True)
        with open(os.path.join(ml, "Gcd.lean"), "w", encoding="utf-8") as fh:
            fh.write(
                "theorem gcd_dvd (a b : R) : gcd a b ∣ a ∧ gcd a b ∣ b := by\n"
                "  sorry\n"
                "theorem square_free_aux (n : Nat) : True := by\n"
                "  trivial\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _searcher(self, **kw):
        return MathlibTheoremSearcher(roots=[self.tmp], use_official=False, **kw)

    def test_finds_declaration_offline(self):
        s = self._searcher()
        r = s.search("gcd dvd", limit=5)
        self.assertEqual(r["status"], "ok")
        names = [x["name"] for x in r["results"]]
        self.assertIn("gcd_dvd", names)

    def test_respects_top_k(self):
        s = self._searcher()
        self.assertLessEqual(len(s.search("gcd dvd", limit=1)["results"]), 1)

    def test_unrelated_query_returns_empty(self):
        s = self._searcher()
        self.assertEqual(s.search("zzzqqq nonexistenttoken", limit=5)["results"], [])

    def test_status_reports_available_and_index_size(self):
        st = self._searcher().status()
        self.assertTrue(st["available"])
        self.assertGreaterEqual(st["indexed_declarations"], 2)

    def test_no_root_returns_unavailable_not_raise(self):
        """没有可用源码根时必须安全降级，绝不抛异常。"""
        s = MathlibTheoremSearcher(roots=["/nonexistent/root"], use_official=False)
        s._roots = []
        r = s.search("anything", limit=3)
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["results"], [])

    def test_search_records_stats(self):
        s = self._searcher()
        before = s.stats.calls
        s.search("gcd dvd", limit=2)
        self.assertEqual(s.stats.calls, before + 1)

    def test_normalize_query_is_str_tuple(self):
        aug, strong = normalize_query("prove that gcd a b divides a")
        self.assertIsInstance(aug, str)
        self.assertIsInstance(strong, list)


class VerifierInjectionTest(unittest.TestCase):
    """方案 A：把检索到的定理原文注入验证器（开关矩阵 + 缓存 + 上限）。"""

    def setUp(self):
        _StubSearcher.calls = 0

    def _patch(self, stub=_StubSearcher):
        return mock.patch(
            "tools.lean_local.lean_search.MathlibTheoremSearcher", stub)

    def test_disabled_switch_returns_empty(self):
        v = make_verifier(use_leansearch=False)
        self.assertEqual(v._prepare_theorem_context(make_ctx(), "p"), "")

    def test_inject_switch_off_returns_empty(self):
        v = make_verifier(leansearch_inject_verifier=False)
        self.assertEqual(v._prepare_theorem_context(make_ctx(), "p"), "")

    def test_enabled_returns_formatted_theorems(self):
        v = make_verifier(leansearch_top_k=2)
        with self._patch():
            out = v._prepare_theorem_context(make_ctx(), "gcd divides")
        self.assertIn("Mathlib.Algebra.EuclideanDomain.gcd_dvd", out)
        self.assertIn("theorem", out)
        self.assertEqual(_StubSearcher.calls, 1)

    def test_result_cached_per_question(self):
        v = make_verifier()
        ctx = make_ctx()
        with self._patch():
            v._prepare_theorem_context(ctx, "p")
            v._prepare_theorem_context(ctx, "p")
        self.assertEqual(_StubSearcher.calls, 1, "同一题不应重复检索")

    def test_max_calls_per_question_enforced(self):
        v = make_verifier(leansearch_max_calls_per_q=1)
        ctx = make_ctx()
        with self._patch():
            v._prepare_theorem_context(ctx, "p")
            ctx._leansearch_ctx = None          # 清缓存，模拟第二次触发
            v._prepare_theorem_context(ctx, "p")
        self.assertEqual(_StubSearcher.calls, 1, "超过单题上限应跳过检索")

    def test_empty_hits_gives_empty_context(self):
        v = make_verifier()
        with self._patch(_EmptySearcher):
            out = v._prepare_theorem_context(make_ctx(), "p")
        self.assertEqual(out, "")

    def test_search_exception_is_swallowed(self):
        class _Boom(_StubSearcher):
            def search(self, query, limit=5):
                raise RuntimeError("network down")

        v = make_verifier()
        with self._patch(_Boom):
            out = v._prepare_theorem_context(make_ctx(), "p")
        self.assertEqual(out, "", "检索异常必须降级为空，不影响验证行为")

    def test_used_theorems_recorded_on_ctx(self):
        v = make_verifier()
        ctx = make_ctx()
        with self._patch():
            v._prepare_theorem_context(ctx, "p")
        self.assertTrue(ctx.used_theorems)
        self.assertEqual(ctx.mathlib_usage_stats["search_calls"], 1)

    def test_trace_records_hits_and_ms(self):
        v = make_verifier()
        ctx = make_ctx()
        with self._patch():
            v._prepare_theorem_context(ctx, "p")
        ev = [t for t in ctx.trace if t.get("step") == "leansearch"]
        self.assertTrue(ev)
        self.assertIn("n_hits", ev[-1])
        self.assertIn("elapsed_ms", ev[-1])


class PromptSlotTest(unittest.TestCase):
    """提示词必须带 `{theorem_context}` 槽位，否则 .format() 会 KeyError。"""

    def test_slot_exists_and_formats(self):
        out = VERIFIER_USER_TEMPLATE.format(
            problem="P", candidate_answer="C", theorem_context="(无)")
        self.assertIn("相关 Mathlib 定理原文", out)
        self.assertIn("(无)", out)

    def test_real_injection_text_renders(self):
        out = VERIFIER_USER_TEMPLATE.format(
            problem="P", candidate_answer="C",
            theorem_context="- Foo.bar (theorem): x = y")
        self.assertIn("Foo.bar", out)


class DiagSummaryTest(unittest.TestCase):
    """`_summarize_leansearch` 按题聚合（不混用进程累计值）。"""

    def test_aggregates_per_question(self):
        from agent.orchestrator import _summarize_leansearch
        ctx = SimpleNamespace(trace=[
            {"step": "answer_form", "content": "x"},
            {"step": "leansearch", "n_hits": 3, "elapsed_ms": 100.0,
             "root": "https://leansearch.net/search",
             "names": ["A.b", "A.c", "A.d"]},
            {"step": "leansearch", "n_hits": 0, "elapsed_ms": 20.0},
        ])
        s = _summarize_leansearch(ctx)
        self.assertEqual(s["calls"], 2)
        self.assertEqual(s["hits"], 3)
        self.assertEqual(s["unique"], 3)
        self.assertEqual(s["elapsed_ms"], 120.0)

    def test_empty_and_missing_trace(self):
        from agent.orchestrator import _summarize_leansearch
        self.assertEqual(_summarize_leansearch(SimpleNamespace(trace=[]))["calls"], 0)
        self.assertEqual(_summarize_leansearch(SimpleNamespace())["calls"], 0)


class DeSilencedFailureTest(unittest.TestCase):
    """lean_gate 的埋点失败必须可见（一次性 warning），不再静默。"""

    def test_flag_exists_in_lean_gate(self):
        from tools.lean_local import lean_gate
        self.assertTrue(hasattr(lean_gate, "_LEANSEARCH_WARNED"))

    def test_flag_exists_in_lean_refiner(self):
        from tools.lean_local import lean_refiner
        self.assertTrue(hasattr(lean_refiner, "_LEANSEARCH_WARNED"))

    def test_import_failure_logs_warning(self):
        from tools.lean_local import lean_gate
        lean_gate._LEANSEARCH_WARNED = False
        with mock.patch.dict("sys.modules",
                             {"tools.lean_local.lean_search": None}):
            with mock.patch.object(lean_gate.logger, "warning") as w:
                gate = object.__new__(lean_gate.LeanGate)
                gate._note_theorems_adopted(["Foo.bar"])
                self.assertTrue(w.called, "首次失败必须打 warning")
                self.assertTrue(lean_gate._LEANSEARCH_WARNED)


if __name__ == "__main__":
    unittest.main()
