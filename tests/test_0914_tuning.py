# -*- coding: utf-8 -*-
"""2026-09-14 两项调优的回归测试。

改动一：`enable_calc_prewarm` 默认 True → **False**（**2026-09-29 已整体废弃**）
  2026-09-29：生成前算式预计算（方案 B / 阶段 2.65_calc_prewarm）已按用户决策
  **整体删除**（「没必要，且不合逻辑」）⇒ 本文件原 `PrewarmDefaultTest` 三个
  用例失去被测对象，已删除。历史结论留档：12/12 题都跑了预计算，只有 1 题与
  答案相关；根因是"让模型在解题前凭题面猜该算什么"这个前提不成立；成本 30–111s/题。

改动二：服务端过载 `-20014 书生体验过于火爆` 加入 `_RATE_LIMIT_MARKERS`
  此前未被识别 ⇒ 只退避 2s；而 `max_retries=1` 意味着**只有一次重试机会**，
  2s 后大概率仍撞墙 ⇒ 白烧一次调用（每次最多 120s）。
"""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch


def _resp(status: int, text: str):
    r = Mock()
    r.status_code = status
    r.text = text
    return r


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
