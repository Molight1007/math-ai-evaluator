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
def test_f1_switch_defaults_off():
    from agent.base import _TEXT_TOOLCALL_FALLBACK
    assert _TEXT_TOOLCALL_FALLBACK is False, "F1 直接改主链，必须默认关"


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


def test_f1_parser_calc_form():
    from agent.base import _parse_text_toolcall
    assert _parse_text_toolcall(
        "<tool_call><function=calc_eval><parameter=expr>36*101+74"
        "</parameter></function></tool_call>") == ("calc_eval", {"expr": "36*101+74"})


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


def test_f1_wired_into_text_branch():
    """解析器必须真的接进「无原生 tool_calls」的分支，否则等于没写。"""
    src = _src("agent/base.py")
    i = src.find("F1，开关 TOOLCALL_TEXT_FALLBACK")
    assert i > 0
    seg = src[i:i + 2600]
    assert "_parse_text_toolcall(" in seg
    assert "continue" in seg
    assert 'self.record(ctx, "toolcall_text_exec"' in seg


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
