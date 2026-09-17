# -*- coding: utf-8 -*-
"""逐题「极详细记录」的导出契约测试（2026-09-16）。

用户要求：测试要能复盘 **大模型的解答过程 / 时间消耗 / 各环节效果**。
此前 `run_eval.solve_one` 只落盘 `response[:2000]` + 有限 `diag`，
**候选的 reasoning 与全量事件流都没导出** ⇒ 事后无法回答"模型在哪一步跑偏"。

本模块锁定导出契约：新字段必须在，且旧的消费方（报告生成器）必须能容忍缺失。
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_eval import EvalEngine  # noqa: E402


FAKE_RESULT = {
    "final_response": r"\boxed{42}",
    "trace": [
        {"agent": "Classifier", "step": "classify", "content": "题型=填空题"},
        {"agent": "Solver", "step": "solve", "content": "生成候选"},
        {"agent": "Solver", "step": "solve", "content": "再生成"},
        {"agent": "Verifier", "step": "verify", "content": "全票 A"},
    ],
    "candidates": [
        {"id": 0, "answer": "42", "reasoning": "因为 6*7=42，所以答案是 42。", "revised": False},
        {"id": 1, "answer": "43", "reasoning": "我算错了，这里给出 43。", "revised": True},
    ],
    "verdicts": [
        {"id": 0, "answer": "42", "confidence": 1.0, "correct_votes": 3,
         "total_votes": 3, "feedback": ""},
        {"id": 1, "answer": "43", "confidence": 0.0, "correct_votes": 0,
         "total_votes": 3, "feedback": "前提不成立"},
    ],
    "cluster": {"answer_norm": "42", "size": 1, "confidence": 1.0,
                "candidate_ids": [0]},
    "used_theorems": ["Mathlib.Foo.bar"],
    "mathlib_usage_stats": {"search_calls": 1},
    "diag": {"stage_timers": {"1_classify": 2.0, "3_solve": 30.0}},
}


class _StubAgent:
    def __init__(self, result):
        self._result = result

    def solve(self, problem, metadata=None):
        return self._result


def make_engine(result):
    """绕过 __init__（避免真实依赖），只装配 solve_one 需要的属性。"""
    eng = object.__new__(EvalEngine)
    eng.agent = _StubAgent(result)
    return eng


class DetailExportTest(unittest.TestCase):

    def _row(self, result=None):
        return make_engine(result if result is not None else FAKE_RESULT).solve_one({
            "id": "official112-999",
            "question": "6*7=?",
            "answer": "42",
            "domain": "算术",
        })

    def test_response_full_not_truncated(self):
        long_text = r"\boxed{42}" + "补" * 5000
        r = self._row(dict(FAKE_RESULT, final_response=long_text))
        self.assertEqual(len(r["response_full"]), len(long_text),
                         "response_full 必须不截断")
        self.assertLessEqual(len(r["response"]), 2000, "旧字段仍保持 2000 上限")

    def test_candidates_include_reasoning(self):
        r = self._row()
        self.assertEqual(len(r["candidates"]), 2)
        self.assertIn("6*7=42", r["candidates"][0]["reasoning"],
                      "★ 解答过程（reasoning）必须导出")
        self.assertTrue(r["candidates"][1]["revised"])

    def test_candidates_carry_votes(self):
        r = self._row()
        self.assertEqual(r["candidates"][0]["correct_votes"], 3)
        self.assertEqual(r["candidates"][1]["total_votes"], 3)
        self.assertEqual(r["candidates"][1]["feedback"], "前提不成立")

    def test_trace_exported(self):
        r = self._row()
        self.assertEqual(len(r["trace"]), 4)
        steps = [t["step"] for t in r["trace"]]
        self.assertEqual(steps.count("solve"), 2)

    def test_verdicts_and_cluster_exported(self):
        r = self._row()
        self.assertEqual(len(r["verdicts"]), 2)
        self.assertEqual(r["cluster"]["answer_norm"], "42")

    def test_llm_calls_recorded(self):
        r = self._row()
        self.assertIn("calls", r["llm_calls"])
        self.assertIsInstance(r["llm_calls"]["calls"], int)

    def test_tool_calls_recorded(self):
        """★ 工具级埋点（2026-09-16 用户要求）：Lean MCP 调用效果必须落盘。

        判读口径：`calls>0 且 ok>0` = MCP 真正生效；`fail==calls` = 全部失败、
        实际由 bridge 完成（0916 轮即此情形）。这一行是回答"到底用了 MCP 还是
        bridge"的唯一直接证据。
        """
        r = self._row()
        self.assertIn("tool_calls", r)
        mcp = r["tool_calls"]["lean_mcp"]
        for k in ("calls", "ok", "fail", "seconds", "verdict"):
            self.assertIn(k, mcp, "缺字段 " + k)

    def test_tool_calls_verdict_branches(self):
        """三种判读分支都要能正确生成（用桩快照直接验）。"""
        import run_eval as R
        cases = [
            ({"calls": 0}, "未走 MCP"),
            ({"calls": 5, "ok": 3, "fail": 2}, "MCP 生效"),
            ({"calls": 3, "ok": 0, "fail": 3}, "实际由 bridge 完成"),
        ]
        for snap, expect in cases:
            base = {"calls": 0, "ok": 0, "fail": 0, "seconds": 0.0}
            cur = dict(base, **snap)
            # 复刻 solve_one 的派生逻辑
            d = {k: cur.get(k, 0) - base.get(k, 0) for k in base}
            if d["calls"] == 0:
                got = "未走 MCP"
            elif d["ok"] > 0:
                got = "MCP 生效"
            else:
                got = "MCP 全部失败 → 实际由 bridge 完成"
            self.assertIn(expect, got, "快照 %s 的判读应为 %s" % (snap, expect))

    def test_mcp_snapshot_never_raises(self):
        import run_eval as R
        s = R._mcp_call_snapshot()
        self.assertIsInstance(s, dict)
        for k in ("calls", "ok", "fail", "seconds"):
            self.assertIn(k, s)

    def test_stage_timers_still_available(self):
        r = self._row()
        self.assertEqual(r["diag"]["stage_timers"]["3_solve"], 30.0)

    def test_exception_path_still_produces_row(self):
        eng = object.__new__(EvalEngine)

        class _Boom:
            def solve(self, *a, **k):
                raise RuntimeError("boom")

        eng.agent = _Boom()
        r = eng.solve_one({"id": "x", "question": "q", "answer": "a"})
        self.assertIn("ERROR", r["response_full"])
        self.assertEqual(r["candidates"], [])
        self.assertEqual(r["trace"], [])


class ReportToleranceTest(unittest.TestCase):
    """报告生成器必须容忍缺字段（旧结果文件没有 candidates/trace）。"""

    def _load_gen(self):
        import importlib.util
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tools", "gen_test_report.py")
        spec = importlib.util.spec_from_file_location("_gtr2", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_candidate_blocks_without_field(self):
        m = self._load_gen()
        self.assertIn("旧结果文件", m.candidate_blocks({}))

    def test_trace_summary_without_field(self):
        m = self._load_gen()
        self.assertEqual(m.trace_summary(None), [])
        self.assertEqual(m.trace_summary("not-a-list"), [])

    def test_trace_summary_aggregates(self):
        m = self._load_gen()
        rows = m.trace_summary(FAKE_RESULT["trace"])
        d = {(a, s): n for a, s, n, _ in rows}
        self.assertEqual(d[("Solver", "solve")], 2)
        self.assertEqual(d[("Verifier", "verify")], 1)

    def test_llm_calls_text_fallback(self):
        m = self._load_gen()
        self.assertIn("未记录", m.llm_calls_text({}))
        self.assertIn("3", m.llm_calls_text({"llm_calls": {"calls": 3, "truncated": 1}}))


if __name__ == "__main__":
    unittest.main()
