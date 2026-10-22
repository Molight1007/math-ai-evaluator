# -*- coding: utf-8 -*-
"""子目标「产出为空」的两条缺陷（2026-10-22）。

实测背景：628 个子目标里 103 个 `result` 为空（占真失败的 88.8%）。
代码层查出两条会**把有内容变成空串**的路径：

  ① 空响应只拦 `None` —— `resp == ""` 会一路落成空 result；
  ② 正则 `【本步结果】\\s*\\n?(.*?)(?:$|【)` 在模型紧接着写「【推导过程】」
     时匹配到**空内容**（非贪婪 + 紧随标记），尽管后文有大段推导。

修复后的契约：
  · 空响应 / 剥壳后仍空 ⇒ `[子目标求解失败]`（绝不留空串给 merge）；
  · 结果段为空但推导段有内容 ⇒ 取推导段；
  · 正常单段结果 ⇒ 原样返回。
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.sub_goal_solver__solve import _call_step  # noqa: E402

PLACEHOLDER = "[子目标求解失败]"


class _Ctx:
    problem = "题"
    theorem_hint_block = ""


class _Solver:
    """最小桩：只提供 `_call_step` 用到的四个成员。"""

    config = SimpleNamespace(enable_theorem_hint=False)

    def __init__(self, resp):
        self._resp = resp

    def _multi_agent_n(self, ctx):
        return 1

    def _maybe_tool_llm(self, *a, **k):
        return self._resp

    def _strip_tool_residue(self, s):
        return s


def _run(resp):
    return _call_step(_Solver(resp), _Ctx(), "x")


def test_empty_response_returns_placeholder_not_empty_string():
    """空串必须变成显式失败标记 —— 这是 103 个空 result 的直接来源之一。"""
    assert _run("") == PLACEHOLDER


def test_whitespace_only_response_is_treated_as_empty():
    assert _run("   \n\t ") == PLACEHOLDER


def test_single_result_section_is_kept():
    out = _run("【本步结果】\n本步结论: 值 = 5")
    assert "本步结论" in out


def test_empty_result_section_falls_back_to_derivation():
    """★ 关键：`【本步结果】` 后紧跟 `【推导过程】` 时，不能返回空串。"""
    out = _run("【本步结果】\n【推导过程】\n设 y_n=x_n^2，取任意 N，排序后得 y_π(1)≤…")
    assert out and out != PLACEHOLDER
    assert "y_n=x_n^2" in out


def test_no_marker_falls_back_to_tail():
    out = _run("直接给一段没有标记的推导内容，长度足够。")
    assert out and out != PLACEHOLDER


def test_short_result_section_keeps_derivation():
    """★ 实测：prefill 后模型不重复「【本步结果】」，只写结论两行 + 【推导过程】。
    旧实现截到下一个 `【` 就把**整段推导丢了**（1753 字 → 40 字）。"""
    resp = ("【本步结果】\n本步结论: 值 = 5\n本步依据: 题设\n"
            "【推导过程】\n设 x=1，代入得 1+4=5，故结论为 5。")
    out = _run(resp)
    assert "本步结论" in out
    assert "设 x=1" in out, "推导段被丢弃 ⇒ merge 只能拿到一句结论"
    assert "【推导过程】" in out


def test_long_result_section_not_duplicated():
    """结果段本身够长（已含推导）⇒ 不再重复拼接推导段。"""
    body = "本步结论: 值 = 5\n" + ("推导内容" * 20)
    out = _run("【本步结果】\n" + body + "\n【推导过程】\n另一段")
    assert out.count("推导内容") >= 20
    assert "另一段" not in out
