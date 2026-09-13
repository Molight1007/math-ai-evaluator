# -*- coding: utf-8 -*-
"""原生工具调用循环（calc_eval）单测（2026-09-09 用户洞察试点）。

mock client.chat：首轮返回带 tool_calls 的 dict（OpenAI 形态）→ 验证执行
calc_tool 并以 tool 消息回传 → 次轮返回文本结束。真实 Intern API 遵从度由
2 题评测实证。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import BaseAgent  # noqa: E402


class _Cfg:
    tool_calc_enabled = False


class _Ctx:
    deadline = None
    budget = None
    trace = []

    def gen_time_up(self):
        return False


class FakeClient:
    """脚本化 client：按脚本依次返回响应，记录每次 tools 参数。"""

    def __init__(self, script):
        self.script = list(script)
        self.seen_tools = []

    def chat(self, messages, temperature=None, max_tokens=None, tools=None, **kw):
        self.seen_tools.append(tools)
        if not self.script:
            return "END"
        return self.script.pop(0)


class _Impl(BaseAgent):
    def __init__(self):
        super().__init__(None, _Cfg())

    def run(self, ctx):
        return ctx


def _agent(client):
    a = _Impl()
    a.name = "TestAgent"
    a.client = client
    a.config = _Cfg()
    a.record = lambda *x, **k: None
    return a


def test_calc_tool_exec_basic():
    assert BaseAgent._calc_tool_exec("1/2+1/3") == "5/6"
    assert BaseAgent._calc_tool_exec("sqrt(45)") == "3*sqrt(5)"
    assert BaseAgent._calc_tool_exec("sin(1)").startswith("WARN:")
    assert BaseAgent._calc_tool_exec("a = 7\nb = 8") == "8"   # 2026-09-13 策略B：纯赋值块回填末条赋值


def test_tool_loop_executes_and_continues():
    tool_msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "calc_eval",
                         "arguments": '{"expr": "comb(50,3)*2**10"}'},
        }],
    }
    client = FakeClient([tool_msg, "总和是 1960000，因此答案为 1960000"])
    a = _agent(client)
    out = a.llm_with_calc(_Ctx(), [{"role": "user", "content": "求总和"}])
    assert out == "总和是 1960000，因此答案为 1960000"
    assert client.seen_tools and client.seen_tools[0] is not None


def test_tool_loop_result_injected():
    """tool 执行结果确实以 tool 角色消息回传（内容含回填值）。"""
    captured = {}

    class C(FakeClient):
        def chat(self, messages, temperature=None, max_tokens=None, tools=None, **kw):
            captured["last_messages"] = list(messages)
            return super().chat(messages, temperature, max_tokens, tools, **kw)

    tool_msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_9",
            "type": "function",
            "function": {"name": "calc_eval", "arguments": '{"expr": "2^10"}'},
        }],
    }
    client = C([tool_msg, "完成"])
    a = _agent(client)
    a.llm_with_calc(_Ctx(), [{"role": "user", "content": "q"}])
    roles = [m.get("role") for m in captured["last_messages"]]
    assert roles == ["system", "user", "assistant", "tool"]   # system=自动注入工具说明
    assert "calc_eval" in str(captured["last_messages"][0].get("content"))
    tool_msg_sent = captured["last_messages"][-1]
    assert tool_msg_sent.get("tool_call_id") == "call_9"
    assert "1024" in tool_msg_sent.get("content", "")


def test_tool_loop_fallback_on_no_tools_support():
    """平台 client 不支持 tools → 回落普通 llm，不抛异常。"""

    class NoToolsClient(FakeClient):
        def chat(self, messages, temperature=None, max_tokens=None, tools=None, **kw):
            raise TypeError("unexpected keyword 'tools'")

    client = NoToolsClient([])
    a = _agent(client)
    out = a.llm_with_calc(_Ctx(), [{"role": "user", "content": "hi"}])
    assert out is None or isinstance(out, str)
