# -*- coding: utf-8 -*-
"""通用联网搜索工具的契约测试（2026-09-16）。

背景
----
用户要求「补充联网搜索工具」。此前仓库内**没有任何通用联网检索能力**。

后端选择是**实测**定的，不是猜的（见 `tools/web_search.py` 注释）：
  · Math StackExchange API ✓ 质量最佳（数学专用）
  · arXiv API ✓ 论文
  · Bing △ 能连通但**结果不可用**（经沙箱代理对 "domino tiling recurrence"
    返回「多米诺披萨官网」、对英文查询返回「Hotmail 登录」）⇒ 降为兜底
  · DuckDuckGo / Wikipedia / Google ✗ ProxyError

本模块**不联网**（避免测试依赖外网稳定性），只锁定接口契约与降级语义；
真实连通性由 `python -m tools.web_search "<query>"` 手动验证。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.web_search as W  # noqa: E402


class WebSearchContractTest(unittest.TestCase):

    def test_backend_priority_is_math_first(self):
        """数学题优先用数学专用后端；Bing 必须排在最后（质量最差）。"""
        self.assertEqual(W._BACKENDS[0], "mathse")
        self.assertEqual(W._BACKENDS[-1], "bing")

    def test_empty_query_returns_error_not_exception(self):
        r = W.web_search("")
        self.assertEqual(r["status"], "error")
        self.assertEqual(r["error"], "empty_query")
        r2 = W.web_search("   ")
        self.assertEqual(r2["status"], "error")

    def test_result_shape(self):
        r = W.web_search("test", limit=1)
        for k in ("status", "query", "backend", "results"):
            self.assertIn(k, r)

    def test_unknown_backend_degrades_gracefully(self):
        """未知后端不得抛异常，且必须走到 error 分支。"""
        r = W.web_search("anything", backend="__nope__")
        self.assertEqual(r["status"], "error")
        self.assertIn("unknown_backend", r["error"])

    def test_block_empty_when_no_results(self):
        """`web_search_block` 无结果必须返回空串（与 error_lessons_block 同约定）。"""
        orig = W.web_search
        try:
            W.web_search = lambda *a, **k: {"status": "error", "results": []}
            self.assertEqual(W.web_search_block("x"), "")
            W.web_search = lambda *a, **k: {"status": "ok", "results": []}
            self.assertEqual(W.web_search_block("x"), "")
        finally:
            W.web_search = orig

    def test_block_renders_caveat(self):
        """注入提示词的块**必须**带"须自行验证"警示，避免模型照搬网帖。"""
        orig = W.web_search
        try:
            W.web_search = lambda *a, **k: {
                "status": "ok",
                "results": [{"title": "T", "url": "http://u", "snippet": "S"}],
            }
            blk = W.web_search_block("q")
            self.assertIn("仅供查证", blk)
            self.assertIn("不得直接照搬", blk)
            self.assertIn("http://u", blk)
        finally:
            W.web_search = orig

    def test_stats_shape(self):
        s = W.web_search_stats()
        for k in ("calls", "ok", "fail", "seconds", "results"):
            self.assertIn(k, s)

    def test_note_counts(self):
        before = W.web_search_stats()["calls"]
        W._note(0.1, True, 3)
        after = W.web_search_stats()
        self.assertEqual(after["calls"], before + 1)
        self.assertEqual(after["results"] >= 3, True)

    def test_snippet_is_bounded_and_clean(self):
        long_html = "<p>" + ("x" * 2000) + "</p>"
        cleaned = W._clean(long_html)
        self.assertNotIn("<", cleaned)
        self.assertLessEqual(len(cleaned), 2000)


class RunEvalInstrumentationTest(unittest.TestCase):

    def test_web_snapshot_shape(self):
        import run_eval as R
        s = R._web_call_snapshot()
        for k in ("calls", "ok", "fail", "seconds", "results"):
            self.assertIn(k, s)

    def test_tool_calls_contains_both_tools(self):
        from run_eval import EvalEngine
        eng = object.__new__(EvalEngine)

        class _A:
            def solve(self, *a, **k):
                return {"final_response": "x"}

        eng.agent = _A()
        row = eng.solve_one({"id": "t", "question": "q", "answer": "x"})
        self.assertIn("lean_mcp", row["tool_calls"])
        self.assertIn("web_search", row["tool_calls"])
        self.assertIn("verdict", row["tool_calls"]["web_search"])


if __name__ == "__main__":
    unittest.main()
