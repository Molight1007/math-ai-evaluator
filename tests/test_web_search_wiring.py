# -*- coding: utf-8 -*-
"""联网搜索工具接线测试（2026-09-16）。

背景：`tools/web_search.py` 此前**已实现但全仓无调用者**（代码审计发现）⇒
`tool_calls.web_search` 恒为"未调用"，能力形同虚设。
现已接进 `agent/base.py::llm_with_calc` 的原生 tool_calls 循环，
由 `config.enable_web_search`（默认 **False**）控制是否注册。

本文件**不联网**（执行器真调用已在开发时手工验证），只锁接线契约与降级语义。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import BaseAgent as B  # noqa: E402


class WebSearchToolSchemaTest(unittest.TestCase):

    def test_schema_shape(self):
        s = B.WEB_SEARCH_TOOL_SCHEMA
        self.assertEqual(s["type"], "function")
        fn = s["function"]
        self.assertEqual(fn["name"], "web_search")
        self.assertEqual(fn["parameters"]["required"], ["query"])
        self.assertIn("query", fn["parameters"]["properties"])

    def test_calc_schema_still_present(self):
        """反向保护：接线不能把原有 calc_eval 工具挤掉。"""
        self.assertEqual(B.CALC_TOOL_SCHEMA["function"]["name"], "calc_eval")


class WebSearchToolExecTest(unittest.TestCase):

    def test_executor_never_raises_on_empty(self):
        """空查询必须返回可读文本，不得抛异常打断求解。"""
        out = B._web_search_tool_exec("")
        self.assertIsInstance(out, str)
        self.assertTrue(out)

    def test_executor_returns_str_on_failure(self):
        """即使检索失败也要返回字符串（模型可据此继续）。"""
        out = B._web_search_tool_exec("   ")
        self.assertIsInstance(out, str)
        self.assertTrue(len(out) > 0)


class WebSearchSwitchTest(unittest.TestCase):
    """开关默认必须为 False —— 不经 A/B 不得改变主链行为。"""

    def test_default_off(self):
        import user_agent as U
        self.assertFalse(U.AgentConfig().enable_web_search)

    def test_declared_and_whitelisted(self):
        import inspect
        import user_agent as U
        self.assertTrue(hasattr(U.AgentConfig(), "enable_web_search"))
        src = inspect.getsource(U.ReasoningAgent.__init__)
        self.assertIn('"enable_web_search"', src,
                      "必须在 kwargs 白名单里，否则 CLI 传参被静默丢弃")
        self.assertIn('"enable_question_type_hint"', src)
        self.assertIn('"verify_reserve_seconds"', src)

    def test_cli_arg_exists(self):
        import io
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "run_eval.py")
        t = io.open(p, encoding="utf-8").read()
        self.assertIn("--enable_web_search", t)
        self.assertIn("--enable_question_type_hint", t)
        self.assertIn("--verify_reserve_seconds", t)


class DeadFieldRemovalTest(unittest.TestCase):
    """审计删除的死字段不得回归（全仓 0 读取点）。"""

    def test_dead_fields_gone(self):
        import user_agent as U
        c = U.AgentConfig()
        for k in ("extraction_mode", "max_tokens", "temperature"):
            self.assertFalse(hasattr(c, k), "死字段 %s 不该再存在于 AgentConfig" % k)


if __name__ == "__main__":
    unittest.main()
