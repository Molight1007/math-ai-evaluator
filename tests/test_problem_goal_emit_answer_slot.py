# -*- coding: utf-8 -*-
"""题意理解下发接线（`problem_goal_emit_answer_slot`）测试。

背景（2026-10-29）：`answer_slot` 是唯一按 prompt 契约**禁写具体值**的字段
（纯符号），但改动前 `render_problem_goal` 只渲染 `terminal_state`
—— 恰好是泄漏最重、最易漂移的那个。实测 `omni-3556` 三次跑出三种槽形态，
其中两种把约束链当成目标本身，导致蓝图分不清「目标是 n」还是「目标是满足
条件的对象」。

覆盖：
1. 默认（开关开）⇒ 下发 `answer_slot`，且带「约束条件不等于目标」的显式限定；
2. 开关关 ⇒ 输出**逐字**回到改动前（A/B 对照组，顺序与文案都不变）；
3. `answer_slot` 为空 ⇒ 不产生空行（不能出现「· 所求对象（…）：」后面空着）；
4. 渲染顺序稳定：`所求对象` 在 `目标情形` 之前（先给符号、再给自然语言描述）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.problem_goal import render_problem_goal


def _ctx(**kw):
    base = {
        "problem_goal": {
            "question_type": "解答题",
            "task": "求出题目所要求的量，给出具体的值 / 对象",
            "options": [],
            "n_correct": "",
            "answer_form": "value",
            "terminal_state": "已确定一个整数 n 落在区间内，且满足 n 整除 2^n+2。",
            "answer_slot": "n",
            "goal_statement": "求出题目所要求的量；目标情形：……",
        }
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_emits_answer_slot_by_default():
    out = render_problem_goal(_ctx())
    assert "所求对象" in out
    assert "n" in out
    # 必须带显式限定，否则模型会把符号当成"已求出"
    assert "不得当作已求出" in out
    assert "约束条件不等于目标" in out


def test_order_slot_before_terminal_state():
    out = render_problem_goal(_ctx())
    assert out.index("所求对象") < out.index("目标情形")


def test_switch_off_falls_back_verbatim(monkeypatch):
    """关断后必须逐字回到改动前 —— 用于 A/B 对照，任何多字/少字都算破坏。"""
    monkeypatch.setenv("PROBLEM_GOAL_EMIT_ANSWER_SLOT", "0")
    out = render_problem_goal(_ctx())
    assert "所求对象" not in out
    expected_tail = "· 目标情形（题目完成后的情形；其中答案槽是**假设**"
    assert expected_tail in out


def test_switch_on_explicitly(monkeypatch):
    monkeypatch.setenv("PROBLEM_GOAL_EMIT_ANSWER_SLOT", "1")
    assert "所求对象" in render_problem_goal(_ctx())


def test_empty_slot_no_blank_line():
    c = _ctx()
    c.problem_goal["answer_slot"] = ""
    out = render_problem_goal(c)
    assert "所求对象" not in out
    assert "\n\n" not in out


def test_truncates_long_slot():
    """答案槽上限 200 字（与 terminal_state 的 400 上限同一惯例，防止撑爆提示词）。"""
    c = _ctx()
    c.problem_goal["answer_slot"] = "x" * 500
    out = render_problem_goal(c)
    line = [ln for ln in out.splitlines() if "所求对象" in ln][0]
    assert len(line) < 260


def test_no_problem_goal_returns_empty():
    assert render_problem_goal(SimpleNamespace(problem_goal={})) == ""
