# -*- coding: utf-8 -*-
"""阶段 A/B2 验证：`utils/llm_client.py` 直读 `contracts.switch_registry`。

背景
====
`utils/llm_client.py` 原先 `from agent.switch_registry import ...` ⇒ `utils/` 依赖
`agent/`（违反分层 §2.4，且是 `agent → utils → agent` 环的一环）。

★ 2026-10-07 采用**下沉**而非注入：零依赖的 `switch_registry` 移入 `contracts/`，
`agent/switch_registry.py` 留纯 re-export shim。于是 `utils/` 直接
`from contracts.switch_registry import ...`（contracts 不在 §2.4 禁令内）即合规，
且**读取点仍在 utils 内**（与改前一致）。

本文件锁死三件事：
  ① **开关仍然可覆盖**：默认 / env / `bind_config` config / 显式传参（四态）；
  ② **`utils` 不拉 agent 包**（`import utils.llm_client` 后 `agent` 不在 `sys.modules`）；
  ③ **shim 与实现是同一份状态**：`agent.switch_registry.* is contracts.switch_registry.*`，
     且经任一侧 `bind_field` 设值，另一侧读得到。
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import contracts.switch_registry as csr
from contracts.switch_registry import bind_config


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


class StageASwitchTest(unittest.TestCase):
    def setUp(self):
        self._saved_overrides = dict(csr._overrides)
        csr._overrides.clear()

    def tearDown(self):
        csr._overrides.clear()
        csr._overrides.update(self._saved_overrides)

    # ---- ① 四态 ----
    def test_01_default(self) -> None:
        from utils.llm_client import LLMClient
        with _EnvUnset("LLM_TIMEOUT", "LLM_RETRY_ON_TIMEOUT"):
            self.assertEqual(LLMClient().timeout, 120)
            self.assertFalse(csr.get_bool("llm_retry_on_timeout"))

    def test_02_env_override(self) -> None:
        from utils.llm_client import LLMClient
        with patch.dict(os.environ, {"LLM_TIMEOUT": "55",
                                     "LLM_RETRY_ON_TIMEOUT": "1"}):
            self.assertEqual(LLMClient().timeout, 55)          # utils 直读注册表 → env
            self.assertTrue(csr.get_bool("llm_retry_on_timeout"))

    def test_03_config_override(self) -> None:
        from user_agent import AgentConfig
        from utils.llm_client import LLMClient
        cfg = AgentConfig()
        cfg.llm_timeout = 77
        cfg.llm_retry_on_timeout = True
        bind_config(cfg)
        with _EnvUnset("LLM_TIMEOUT", "LLM_RETRY_ON_TIMEOUT"):
            self.assertEqual(LLMClient().timeout, 77)
            self.assertTrue(csr.get_bool("llm_retry_on_timeout"))
        # env 优先级高于 config（行为不变）
        with patch.dict(os.environ, {"LLM_TIMEOUT": "33"}):
            self.assertEqual(LLMClient().timeout, 33)

    def test_04_explicit_param(self) -> None:
        from utils.llm_client import LLMClient
        with patch.dict(os.environ, {"LLM_TIMEOUT": "55"}):
            self.assertEqual(LLMClient(timeout=9).timeout, 9)   # 显式 > env

    # ---- ② utils 不拉 agent ----
    def test_05_utils_does_not_import_agent(self) -> None:
        code = ("import sys; import utils.llm_client; "
                "print('AGENT_IMPORTED=' + str('agent' in sys.modules))")
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, cwd=os.getcwd())
        self.assertIn("AGENT_IMPORTED=False", out.stdout,
                      "utils.llm_client 不应拉起 agent 包：%s%s" % (out.stdout, out.stderr))

    # ---- ③ shim 同一份状态 ----
    def test_06_shim_same_object_and_state(self) -> None:
        import agent.switch_registry as asr
        for name in ("get_bool", "get_num", "get_str", "bind_config",
                     "bind_field", "snapshot", "source_of", "summary_line", "SWITCHES"):
            self.assertIs(getattr(asr, name), getattr(csr, name),
                          "shim.%s 与实现非同一对象" % name)
        asr.bind_field("lean_gate_parallel", False)
        self.assertFalse(csr.get_bool("lean_gate_parallel"), "agent 侧设值 contracts 读不到")
        csr.bind_field("lean_gate_parallel", True)
        self.assertTrue(asr.get_bool("lean_gate_parallel"), "contracts 侧设值 agent 读不到")


if __name__ == "__main__":
    unittest.main()
