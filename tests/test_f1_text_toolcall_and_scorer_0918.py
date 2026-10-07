# -*- coding: utf-8 -*-
"""2026-09-18 第三批修改的回归测试。

  ① F1 文本通道工具调用解析器 `_parse_text_toolcall`（默认关，供 A/B）
  ② 判分器 S1（`\\text{}` 剥壳，默认开）/ S2（顿号，默认开）/ S3（α-等价，默认关）
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   errors="replace").read()


# ============================ ① F1 ============================
def test_f1_switch_defaults_on(monkeypatch):
    """2026-10-07 决策：F1 **默认开**。

    依据（2026-10-06 smoke10 实测）：10 题 `toolcall_text_detected` 共 93 条
    （题 000=18、007=16、003=15、004=11），而 `tool_calls.web_search.calls` 多数题
    为 0 ⇒ 模型写在正文里的工具调用**一次都没执行**，含题 000 明确发出的自纠错检索
    请求。执行侧有 web_search 白名单 + 必填参数 + 幂等 + max_rounds 限流 ⇒ 风险可控。
    实测 93/93 采样实例皆为真实调用意图，未见"讲解语法"式举例。
    """
    from agent.base import _text_toolcall_fallback_enabled
    monkeypatch.delenv("TOOLCALL_TEXT_FALLBACK", raising=False)
    assert _text_toolcall_fallback_enabled() is True, "F1 默认开（=0 可回退做 A/B）"


def test_f1_switch_reads_live_env(monkeypatch):
    """开关必须**调用时实时读** —— 否则 `bind_config` 写进 registry 的
    CLI/AgentConfig 覆盖读不到（原实现为模块级常量，import 时冻结）。"""
    from agent.base import _text_toolcall_fallback_enabled
    monkeypatch.setenv("TOOLCALL_TEXT_FALLBACK", "0")
    assert _text_toolcall_fallback_enabled() is False
    monkeypatch.setenv("TOOLCALL_TEXT_FALLBACK", "1")
    assert _text_toolcall_fallback_enabled() is True


def test_f1_default_registered_consistently():
    """四件套默认值必须一致（switch_registry / user_agent / param_usage）。"""
    from agent.switch_registry import SWITCHES
    import user_agent as UA
    assert SWITCHES["toolcall_text_fallback"][2] is True
    assert UA.AgentConfig().toolcall_text_fallback is True
    src = _src("agent/param_usage.py")
    assert '_f="toolcall_text_fallback", _d=True' in src


def test_f1_parser_closed_form():
    from agent.base import _parse_text_toolcall
    got = _parse_text_toolcall(
        "<tool_call><function=web_search><parameter=query>"
        "tiling rectangle domino</parameter></function></tool_call>")
    assert got == ("web_search", {"query": "tiling rectangle domino"})


def test_f1_parser_unclosed_form():
    """实测 025/032 的候选 reasoning 里 `</parameter>` 常常缺失。"""
    from agent.base import _parse_text_toolcall
    got = _parse_text_toolcall(
        "<tool_call><function=web_search><parameter=query>\n"
        "splitting field of x^4+5 over Q degree Galois group\n")
    assert got is not None
    assert got[0] == "web_search"
    assert "splitting field" in got[1]["query"]


def test_f1_parser_tolerates_spaces():
    from agent.base import _parse_text_toolcall
    got = _parse_text_toolcall(
        "<function = web_search ><parameter = query >test</parameter>")
    assert got == ("web_search", {"query": "test"})


@pytest.mark.parametrize("text", [
    "",
    None,
    "这是一段普通答案，没有工具调用",
    r"\boxed{2026}",
    "<tool_call></tool_call>",
])
def test_f1_parser_returns_none_for_non_toolcall(text):
    from agent.base import _parse_text_toolcall
    assert _parse_text_toolcall(text) is None


# ---------- 执行准入（白名单 + 必填参数），走文本通道不放宽权限 ----------
def test_f1_acceptable_whitelist_and_required():
    from agent.base import _text_toolcall_acceptable as A
    assert A("web_search", {"query": "x"}) == (True, "")
    ok, why = A("web_search", {"query": "   "})
    assert ok is False and "missing_required_arg" in why
    ok, why = A("os_system", {"cmd": "rm -rf /"})
    assert ok is False and why.startswith("unknown_function")
    ok, why = A("", {})
    assert ok is False and why.startswith("unknown_function")


def test_f1_wired_into_text_branch():
    """解析器必须真的接进「无原生 tool_calls」的分支，否则等于没写。"""
    src = _src("agent/base.py")
    i = src.find("文本通道工具调用回填")
    assert i > 0, "找不到文本通道回填分支（注释锚点被改？）"
    seg = src[i:i + 5200]
    assert "_parse_text_toolcall(last_text)" in seg
    assert "_text_toolcall_acceptable(" in seg
    assert "_seen_text_calls" in seg
    assert '"toolcall_text_exec"' in seg
    assert "continue" in seg
    assert 'self.record(ctx, "toolcall_text_detected"' in seg


# ---------- 端到端：文本通道真的执行 + 回填 + 幂等 + 不执行白名单外 ----------
class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def chat(self, messages=None, **kw):
        self.sent.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return "（兜底）"


def _make_agent(config, responses):
    from agent.base import BaseAgent

    class _A(BaseAgent):
        name = "T1"

        def run(self, ctx):
            return ctx

    return _A(_FakeClient(responses), config)


def _cfg(**kw):
    import types
    base = dict(enable_web_search=True, toolcall_text_fallback=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _text_call(q="tiling rectangle domino"):
    return ("推理……\n<tool_call>\n<function=web_search>\n<parameter=query>\n"
            "%s\n</parameter>\n</function>\n</tool_call>" % q)


def test_f1_text_call_executed_and_refilled(monkeypatch):
    from agent.base import TaskContext
    ag = _make_agent(_cfg(), [_text_call(), "最终答案 42"])
    ran = []
    ag._web_search_tool_exec = lambda q: (ran.append(q), "【联网检索结果】stub")[1]
    ctx = TaskContext(problem="p", metadata={})
    out = ag.llm_with_tools(ctx, [{"role": "user", "content": "q"}])
    assert out == "最终答案 42", "必须基于工具结果继续生成并返回后续文本"
    assert ran == ["tiling rectangle domino"], "文本通道调用必须真的执行"
    steps = [t.get("step") for t in ctx.trace]
    assert "toolcall_text_exec" in steps
    assert "toolcall_text_summary" in steps
    # 回填：第二轮请求里必须带上工具执行结果（role=user）
    sent2 = ag.client.sent[1]
    assert any(m.get("role") == "user" and "系统工具执行结果" in str(m.get("content", ""))
               for m in sent2 if isinstance(m, dict)), "结果未回填进对话"


def test_f1_unknown_function_not_executed(monkeypatch):
    """白名单外（如 os_system）**绝不执行**，只留痕。"""
    from agent.base import TaskContext
    evil = ("<tool_call><function=os_system><parameter=cmd>rm -rf /</parameter>"
            "</function></tool_call>")
    ag = _make_agent(_cfg(), [evil])
    ran = []
    ag._web_search_tool_exec = lambda q: (ran.append(q), "stub")[1]
    ctx = TaskContext(problem="p", metadata={})
    ag.llm_with_tools(ctx, [{"role": "user", "content": "q"}])
    assert ran == [], "白名单外函数被执行 ⇒ 权限被放宽"
    det = [t for t in ctx.trace if t.get("step") == "toolcall_text_detected"]
    assert det and "unknown_function" in det[0].get("content", "")


def test_f1_empty_query_not_executed():
    from agent.base import TaskContext
    tc = "<tool_call><function=web_search><parameter=query>  </parameter></function></tool_call>"
    ag = _make_agent(_cfg(), [tc])
    ran = []
    ag._web_search_tool_exec = lambda q: (ran.append(q), "stub")[1]
    ctx = TaskContext(problem="p", metadata={})
    ag.llm_with_tools(ctx, [{"role": "user", "content": "q"}])
    assert ran == [], "空检索式不得打网络"


def test_f1_duplicate_call_not_executed_twice():
    """同一 (工具, 检索式) 在同一次工具循环内只执行一次（幂等）。

    注意每次 `llm_with_tools` 是独立一次调用，跨调用不去重（正确：不同轮
    的重复请求属新意图）。重复调用**不再执行**，直接以模型文本收尾。
    """
    from agent.base import TaskContext
    ag = _make_agent(_cfg(), [_text_call("dup"), _text_call("dup"), "done"])
    ran = []
    ag._web_search_tool_exec = lambda q: (ran.append(q), "stub")[1]
    ctx = TaskContext(problem="p", metadata={})
    out = ag.llm_with_tools(ctx, [{"role": "user", "content": "q"}])
    assert ran == ["dup"], "重复调用被重复执行（幂等失效）"
    det = [t for t in ctx.trace if t.get("step") == "toolcall_text_detected"]
    assert det and "duplicate_call" in det[0].get("content", "")
    assert "<tool_call>" in out


def test_f1_native_precedence_no_double_exec(monkeypatch):
    """同一条响应里**同时**有原生 tool_calls 与文本 <tool_call> ⇒ 只执行原生一次。"""
    from agent.base import TaskContext
    resp = {
        "content": _text_call("from-text"),
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "web_search",
                                     "arguments": '{"query": "from-native"}'}}],
    }
    ag = _make_agent(_cfg(), [resp, "done"])
    ran = []
    ag._web_search_tool_exec = lambda q: (ran.append(q), "stub")[1]
    ctx = TaskContext(problem="p", metadata={})
    ag.llm_with_tools(ctx, [{"role": "user", "content": "q"}])
    assert ran == ["from-native"], "原生通道优先，文本通道不得重复执行"
    assert not [t for t in ctx.trace if t.get("step") == "toolcall_text_exec"]


def test_f1_switch_off_keeps_legacy_detect_only(monkeypatch):
    """`TOOLCALL_TEXT_FALLBACK=0`：回退旧行为 —— 检测到但不执行，仍留痕。"""
    from agent.base import TaskContext
    monkeypatch.setenv("TOOLCALL_TEXT_FALLBACK", "0")
    ag = _make_agent(_cfg(), [_text_call()])
    ran = []
    ag._web_search_tool_exec = lambda q: (ran.append(q), "stub")[1]
    ctx = TaskContext(problem="p", metadata={})
    out = ag.llm_with_tools(ctx, [{"role": "user", "content": "q"}])
    assert ran == [], "开关关时不得执行"
    assert "<tool_call>" in out
    det = [t for t in ctx.trace if t.get("step") == "toolcall_text_detected"]
    assert det and "fallback_off" in det[0].get("content", "")


# ============================ ② 判分器 ============================
def test_s1_text_wrapper_stripped():
    """086：gold `\\text{是}` 与模型 `是` 必须能匹配。"""
    from run_eval import answers_match, _norm_candidate
    assert "\\text" not in _norm_candidate(r"\(\text{是}\)")
    assert answers_match(
        r"\boxed{\mathbb{Q}(\sqrt[4]{5}, i), 8, 是}",
        r"\(\mathbb{Q}(\sqrt[4]{5},\,i),\ 8,\ \text{是}\)") is True


def test_s2_default_on_and_safe():
    """S2（顿号）默认开；且**不得**把"只答一项"判成对（099 的误判方向）。"""
    import run_eval as E
    assert E._EVAL_SPLIT_CN is True
    assert E.answers_match(
        r"\boxed{有限差分法}",
        "有限差分法、有限元法（或有限体积法）") is False, \
        "模型只答一项却被判对 ⇒ S2 引入误判"


def test_s3_default_off():
    import run_eval as E
    assert E._EVAL_ALPHA_EQUIV is False


def test_s3_guard_rejects_non_expression():
    """S3 的**关键守卫**：中文串不得被 sympify 当成 Symbol 后判等（曾把 099 误判为对）。"""
    import run_eval as E
    assert E._alpha_equivalent("有限差分法", "有限差分法、有限元法") is False
    assert E._alpha_equivalent("是", "否") is False
