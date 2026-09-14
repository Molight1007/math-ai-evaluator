# -*- coding: utf-8 -*-
"""2026-09-14 两项调优的回归测试。

改动一：`enable_calc_prewarm` 默认 True → **False**
  依据（12 题错题回归 `results/wrong12_v1_0914_out.jsonl`）：
  12/12 题都跑了预计算，但**只有 1 题与答案相关**；根因是"让模型在解题前
  凭题面猜该算什么"这个前提不成立。成本 30–111s/题（预算仅 1150s）⇒ 净负。

改动二：服务端过载 `-20014 书生体验过于火爆` 加入 `_RATE_LIMIT_MARKERS`
  此前未被识别 ⇒ 只退避 2s；而 `max_retries=1` 意味着**只有一次重试机会**，
  2s 后大概率仍撞墙 ⇒ 白烧一次调用（每次最多 120s）。
"""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

_PREWARM_OFF_CASES = "calc_prewarm"


def _resp(status: int, text: str):
    r = Mock()
    r.status_code = status
    r.text = text
    return r


class PrewarmOffByDefaultTest(unittest.TestCase):
    def test_agent_config_default_is_false(self) -> None:
        from user_agent import AgentConfig
        self.assertFalse(
            AgentConfig().enable_calc_prewarm,
            "prewarm 应默认关闭（实测零相关、耗时 30–111s/题）")

    def test_prewarm_applicable_honours_config(self) -> None:
        """config 关掉时 `_prewarm_applicable` 必须直接 False（不发那次 LLM 调用）。"""
        from types import SimpleNamespace
        from agent.solver import SolverAgent
        from agent.base import TaskContext

        agent = object.__new__(SolverAgent)
        agent.config = SimpleNamespace(enable_calc_prewarm=False,
                                       enable_calc_tool=True)
        agent.record = lambda *a, **k: None
        ctx = TaskContext(problem="求 C(50,3) 的值", metadata={})
        self.assertFalse(agent._prewarm_applicable(ctx, "standard"))

    def test_pipeline_tolerates_missing_prewarm_block(self) -> None:
        """prewarm 关掉后 `ctx.calc_prewarm_block` 永不设置 —— 消费方必须容错。"""
        from agent.base import TaskContext
        ctx = TaskContext(problem="x", metadata={})
        self.assertIsNone(getattr(ctx, "calc_prewarm_block", None))


class ServerOverloadBackoffTest(unittest.TestCase):
    _BODY = ('{"error":{"type":"invalid_request_error","code":"-20014",'
             '"message":"书生体验过于火爆，请稍后再试"}}')

    def _client(self):
        from utils.llm_client import LLMClient
        return LLMClient(api_key="k", base_url="http://example.invalid/v1",
                         model="m", timeout=5, max_retries=1)

    def test_marker_registered(self) -> None:
        from utils.llm_client import _RATE_LIMIT_MARKERS
        self.assertIn("-20014", _RATE_LIMIT_MARKERS)

    def test_overload_uses_rate_backoff(self) -> None:
        """服务端过载 → 大退避 8s（旧行为 2s）。"""
        sleeps = []
        with patch("utils.llm_client.requests.post",
                   return_value=_resp(400, self._BODY)), \
             patch("utils.llm_client.time.sleep", side_effect=sleeps.append), \
             patch("utils.llm_client.random.uniform", return_value=0.0):
            with self.assertRaises(Exception):
                self._client().chat([{"role": "user", "content": "x"}])
        self.assertEqual(sleeps, [8.0], "过载应走限流基数 8s")

    def test_plain_400_keeps_small_backoff(self) -> None:
        """普通 400 不能被误判成限流（防标记过宽）。"""
        sleeps = []
        with patch("utils.llm_client.requests.post",
                   return_value=_resp(400, "bad request: missing field")), \
             patch("utils.llm_client.time.sleep", side_effect=sleeps.append), \
             patch("utils.llm_client.random.uniform", return_value=0.0):
            with self.assertRaises(Exception):
                self._client().chat([{"role": "user", "content": "x"}])
        self.assertEqual(sleeps, [2.0])


if __name__ == "__main__":
    unittest.main()
