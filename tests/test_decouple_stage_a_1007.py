# -*- coding: utf-8 -*-
"""阶段 A（切断 utils → agent）四态验证：LLMClient 的开关注入。

背景（架构解耦方案 2026-10-07 §2 / §A3）
=========================================
`utils/llm_client.py` 原先自行 `from agent.switch_registry import get_bool/get_num`
读 `llm_timeout` / `llm_retry_on_timeout` ⇒ `utils/` 依赖 `agent/`（违反分层 §2.4，
且是 `agent → utils → agent` 环的一环）。

解耦后改为**依赖倒置**：两个开关变成 `LLMClient.__init__` 的显式参数，由**构造点**
（`run_eval.py`）从注册表读后注入。本文件锁死四态，证明开关**仍然生效**：

    ① 默认（无 env / 无 config）→ 注册表默认值
    ② env 覆盖               → env 优先
    ③ bind_config config 覆盖 → config 覆盖（且优先级低于 env）
    ④ 显式传参               → 显式值最高优先

外加一条**反证**：`LLMClient()` 不再自读 env（解耦前会读；解耦后未注入即回落兜底）。
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import agent.switch_registry as sr
from agent.switch_registry import bind_config


def _inject_timeout() -> int:
    """复刻 run_eval.py 构造点的注入：`timeout=int(_sw_num("llm_timeout"))`。"""
    return int(sr.get_num("llm_timeout"))


def _inject_retry():
    """复刻 run_eval.py 构造点的注入：`retry_on_timeout=lambda: _sw_bool(...)`。"""
    return lambda: sr.get_bool("llm_retry_on_timeout")


class _EnvUnset:
    """临时移除若干 env 键（保持其它环境不变），退出时还原。"""

    def __init__(self, *keys):
        self._keys = keys
        self._saved = {}

    def __enter__(self):
        for k in self._keys:
            self._saved[k] = os.environ.pop(k, None)
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


class StageAInjectionTest(unittest.TestCase):
    def setUp(self):
        # 保存并清空 config 覆盖，避免与其它用例相互污染（bind_config 是全局态）
        self._saved_overrides = dict(sr._overrides)
        sr._overrides.clear()

    def tearDown(self):
        sr._overrides.clear()
        sr._overrides.update(self._saved_overrides)

    # ---- ① 默认 ----
    def test_01_default(self) -> None:
        from utils.llm_client import LLMClient
        with _EnvUnset("LLM_TIMEOUT", "LLM_RETRY_ON_TIMEOUT"):
            c = LLMClient(timeout=_inject_timeout(),
                          retry_on_timeout=_inject_retry())
            self.assertEqual(c.timeout, 120)
            self.assertFalse(sr.get_bool("llm_retry_on_timeout"))

    # ---- ② env 覆盖 ----
    def test_02_env_override(self) -> None:
        from utils.llm_client import LLMClient
        with patch.dict(os.environ, {"LLM_TIMEOUT": "55",
                                     "LLM_RETRY_ON_TIMEOUT": "1"}):
            c = LLMClient(timeout=_inject_timeout(),
                          retry_on_timeout=_inject_retry())
            self.assertEqual(c.timeout, 55)
            self.assertTrue(sr.get_bool("llm_retry_on_timeout"))

    # ---- ③ config 覆盖（bind_config），且 env 仍更优先 ----
    def test_03_config_override(self) -> None:
        from user_agent import AgentConfig
        from utils.llm_client import LLMClient
        cfg = AgentConfig()
        cfg.llm_timeout = 77
        cfg.llm_retry_on_timeout = True
        bind_config(cfg)
        with _EnvUnset("LLM_TIMEOUT", "LLM_RETRY_ON_TIMEOUT"):
            c = LLMClient(timeout=_inject_timeout(),
                          retry_on_timeout=_inject_retry())
            self.assertEqual(c.timeout, 77)
            self.assertTrue(sr.get_bool("llm_retry_on_timeout"))
        # env 优先级高于 config（行为不变）
        with patch.dict(os.environ, {"LLM_TIMEOUT": "33"}):
            self.assertEqual(_inject_timeout(), 33)

    # ---- ④ 显式传参（最高优先）----
    def test_04_explicit_param(self) -> None:
        from utils.llm_client import LLMClient
        with patch.dict(os.environ, {"LLM_TIMEOUT": "55",
                                     "LLM_RETRY_ON_TIMEOUT": "0"}):
            c = LLMClient(timeout=9, retry_on_timeout=lambda: True)
            self.assertEqual(c.timeout, 9)      # 显式 > env
            self.assertTrue(c._retry_on_timeout())  # 显式 > env

    # ---- 反证：LLMClient 不再自读 env ----
    def test_05_client_no_longer_reads_env(self) -> None:
        """解耦后未注入即回落兜底 —— 证明"读开关"已移出 utils/。"""
        from utils.llm_client import LLMClient
        with patch.dict(os.environ, {"LLM_TIMEOUT": "55",
                                     "LLM_RETRY_ON_TIMEOUT": "1"}):
            c = LLMClient()                     # 不注入
            self.assertEqual(c.timeout, 120)    # 字面兜底，而非 env 的 55
            self.assertFalse(bool(c._retry_on_timeout))  # None → 兜底 False


if __name__ == "__main__":
    unittest.main()
