# -*- coding: utf-8 -*-
"""限流退避回归测试（2026-09-11）。

背景（`Bug清单_团队提交de90cedc_0911.md` §5）：
  1. `utils/llm_client.py` 的退避守卫写死模块常量 `_MAX_RETRIES`，而不是
     `self.max_retries` → 调用方传非默认重试次数时循环次数与守卫不一致；
  2. 服务端 `-20048 请求过于频繁` 未单独识别 → 固定 2s 退避（实测两次失败
     间隔 2.1s）对服务端节流等于没有退避；
  3. 无抖动 → 并发的多个候选同时重试，自激放大限流。

本测试锁定修复后的三条契约：重试次数服从配置、限流走更大退避基数、
退避带抖动（并发错峰）。
"""
import json
import unittest
from unittest.mock import Mock, patch

import requests


def _resp(status=429, text="-20048 请求过于频繁"):
    r = Mock()
    r.status_code = status
    r.text = text
    return r


def _resp_429(text="-20048 请求过于频繁"):
    """限流响应（状态码 429 + body 带 -20048）。"""
    return _resp(429, text)


class UtilsLLMClientBackoffTest(unittest.TestCase):
    """`utils/llm_client.py` → LLMClient（run_eval / 本地评测链路使用）。"""

    def _client(self, max_retries):
        from utils.llm_client import LLMClient
        return LLMClient(api_key="k", base_url="http://example.invalid/v1",
                         model="m", timeout=5, max_retries=max_retries)

    def test_retry_count_follows_self_max_retries(self) -> None:
        """重试次数必须服从 self.max_retries（旧代码写死模块常量 → 不一致）。"""
        sleeps = []
        with patch("utils.llm_client.requests.post", return_value=_resp_429()), \
             patch("utils.llm_client.time.sleep", side_effect=sleeps.append), \
             patch("utils.llm_client.random.uniform", return_value=0.0):
            c = self._client(max_retries=3)
            with self.assertRaises(Exception):
                c.chat([{"role": "user", "content": "x"}])
        # 4 次尝试 = max_retries + 1 → 3 次退避
        self.assertEqual(len(sleeps), 3)

    def test_rate_limit_uses_larger_backoff(self) -> None:
        """限流（-20048）必须走更大退避基数，且逐次指数增长。"""
        sleeps = []
        with patch("utils.llm_client.requests.post", return_value=_resp_429()), \
             patch("utils.llm_client.time.sleep", side_effect=sleeps.append), \
             patch("utils.llm_client.random.uniform", return_value=0.0):
            c = self._client(max_retries=2)
            with self.assertRaises(Exception):
                c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(sleeps, [8.0, 16.0])   # 限流基数 8s，8 → 16

    def test_non_rate_error_uses_default_backoff(self) -> None:
        """普通故障（无 -20048 / 429 标识）走默认 2s 基数。

        注意：判据是「状态码 + body」联合串，因此普通故障必须用非 429 状态码，
        否则状态码本身就会命中限流标识。
        """
        sleeps = []
        with patch("utils.llm_client.requests.post",
                   return_value=_resp(500, "internal server error")), \
             patch("utils.llm_client.time.sleep", side_effect=sleeps.append), \
             patch("utils.llm_client.random.uniform", return_value=0.0):
            c = self._client(max_retries=2)
            with self.assertRaises(Exception):
                c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(sleeps, [2.0, 4.0])

    def test_backoff_has_jitter(self) -> None:
        """退避必须带抖动 —— 并发候选错峰重试，避免同步撞限流。"""
        sleeps = []
        with patch("utils.llm_client.requests.post", return_value=_resp_429()), \
             patch("utils.llm_client.time.sleep", side_effect=sleeps.append), \
             patch("utils.llm_client.random.uniform", return_value=3.0):
            c = self._client(max_retries=1)
            with self.assertRaises(Exception):
                c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(sleeps, [11.0])   # 8.0（基数）+ 3.0（抖动）


class RootInternClientBackoffTest(unittest.TestCase):
    """根 `llm_client.py` → InternChatClient（main.py 链路）。"""

    def _client(self):
        import os
        os.environ["INTERN_API_KEY"] = "test-token"
        os.environ["INTERN_MODEL"] = "test-model"
        from llm_client import InternChatClient
        return InternChatClient(retry=3)

    def _http_error(self):
        r = _resp_429()
        err = requests.exceptions.HTTPError("429 Client Error")
        err.response = r
        return err

    def test_rate_limit_body_is_visible_and_backoff_grows(self) -> None:
        """限流标识在 body 里（raise_for_status 的异常串看不到）→ 必须取
        exc.response.text 才能识别，并据此走更大退避。"""
        sleeps = []
        post = Mock()
        post.return_value.raise_for_status.side_effect = self._http_error()
        with patch("llm_client.requests.post", post), \
             patch("llm_client.time.sleep", side_effect=sleeps.append), \
             patch("llm_client.random.uniform", return_value=0.0):
            c = self._client()
            with self.assertRaises(RuntimeError):
                c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(sleeps, [8.0, 16.0])

    def test_retry_count_is_honored(self) -> None:
        sleeps = []
        post = Mock()
        post.return_value.raise_for_status.side_effect = self._http_error()
        with patch("llm_client.requests.post", post), \
             patch("llm_client.time.sleep", side_effect=sleeps.append), \
             patch("llm_client.random.uniform", return_value=0.0):
            c = self._client()
            with self.assertRaises(RuntimeError):
                c.chat([{"role": "user", "content": "x"}])
        self.assertEqual(post.call_count, 3)
        self.assertEqual(len(sleeps), 2)


if __name__ == "__main__":
    unittest.main()
