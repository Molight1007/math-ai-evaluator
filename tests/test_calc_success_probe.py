# -*- coding: utf-8 -*-
"""回归：`diag.calc_tool_calls` 必须真的能被填充（2026-09-14 修复）。

背景
----
`diag.calc_tool_calls` 由 `agent/orchestrator.py` 的 `_collect_diag()` 按 trace 里的
`step == "calc_tool_call"` 过滤导出，但**全代码库从未 record 过这个 step 名**
（只 record 了 `calc_tool_mode` / `solver_calc_rewrite`）
⇒ 该字段**结构性恒空**，会把「工具从来没成功算过」误读成事实。

2026-09-14 就因此误导读过一次归因：第一遍扫出「工具成功 0 次 / 拒收 266 次」，
差点当成结论上报。与 `calc_prewarm` 白名单缺失同源（埋点写了、导不出来）。

修复：`BaseAgent.record_calc_successes()` —— 与 `audit_calc_fallbacks`（记失败）镜像，
在 7 处 `<calc>` 求解点处记录**成功项**。
"""
from __future__ import annotations

import os
import re
import unittest

from agent.base import TaskContext

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Recorder:
    """借用 BaseAgent.record_calc_successes 而不构造完整 Agent。"""

    from agent.base import BaseAgent as _B
    record_calc_successes = _B.record_calc_successes
    name = "T"

    def record(self, ctx, step, content, **extra):
        entry = {"agent": self.name, "step": step, "content": content}
        entry.update(extra)
        ctx.trace.append(entry)


class TestCalcSuccessProbe(unittest.TestCase):
    def _ctx(self):
        return TaskContext(problem="x", metadata={})

    def test_only_successes_are_recorded(self) -> None:
        """WARN:/ERROR: 项必须被跳过（它们由 calc_fallback 记录）。"""
        ctx = self._ctx()
        n = _Recorder().record_calc_successes(ctx, [
            ("27**2", "729"),
            ("comb(50,3)", "19600"),
            ("bad", "ERROR: 不允许的语法节点"),
            ("sin(1)", "WARN: 不支持函数 sin()"),
        ])
        steps = [t for t in ctx.trace if t["step"] == "calc_tool_call"]
        self.assertEqual(n, 2)
        self.assertEqual(len(steps), 2)
        self.assertTrue(all("ERROR" not in s["content"] for s in steps))
        self.assertTrue(all("WARN" not in s["content"] for s in steps))

    def test_empty_and_none_are_safe(self) -> None:
        ctx = self._ctx()
        self.assertEqual(_Recorder().record_calc_successes(ctx, []), 0)
        self.assertEqual(_Recorder().record_calc_successes(ctx, None), 0)
        self.assertEqual(ctx.trace, [])

    def test_step_name_matches_orchestrator_export_filter(self) -> None:
        """**核心不变量**：record 的 step 名必须与 orchestrator 导出时的过滤名一致。

        这两处曾经不一致（导出按 `calc_tool_call`、却没人 record 它），
        导致字段恒空。本测试把两者钉在一起，防止再次脱钩。
        """
        src = open(os.path.join(ROOT, "agent", "orchestrator.py"),
                   encoding="utf-8").read()
        self.assertIn('t.get("step") == "calc_tool_call"', src,
                      "orchestrator 的导出过滤名变了 —— 请同步 record 的 step 名")

        ctx = self._ctx()
        _Recorder().record_calc_successes(ctx, [("1+1", "2")])
        self.assertEqual(ctx.trace[0]["step"], "calc_tool_call")

    def test_every_recorded_calc_success_step_is_exported(self) -> None:
        """反向校验：record 出来的条目，能被 orchestrator 的导出逻辑取到。"""
        ctx = self._ctx()
        _Recorder().record_calc_successes(ctx, [("27**2", "729")])
        exported = [str(t.get("content", ""))[:120]
                    for t in ctx.trace
                    if isinstance(t, dict) and t.get("step") == "calc_tool_call"]
        self.assertEqual(len(exported), 1)
        self.assertIn("729", exported[0])


class TestResolveThenRecord(unittest.TestCase):
    """端到端：`resolve_all_calcs` 算出的成功项，必须能被埋点取到。"""

    def test_real_resolve_populates_probe(self) -> None:
        from agent.calc_tool import resolve_all_calcs
        ctx = TaskContext(problem="x", metadata={})
        resolved_text, resolved = resolve_all_calcs("最终答案 <calc>27**2</calc> = 729")
        self.assertIn("[计算]", resolved_text)
        n = _Recorder().record_calc_successes(ctx, resolved)
        self.assertGreaterEqual(n, 1)
        steps = [t for t in ctx.trace if t["step"] == "calc_tool_call"]
        self.assertTrue(steps)
        self.assertIn("729", steps[0]["content"])


if __name__ == "__main__":
    unittest.main()
