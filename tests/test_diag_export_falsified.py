# -*- coding: utf-8 -*-
"""diag_export 回归测试（2026-10-17 p0b5_r3 崩溃修复）。

背景：`falsified_answers` 列表可能混入**字符串**（证伪淘汰链不同路径 append
形态不一），原导出代码一律 `x.get("answer")` ⇒ diag 导出阶段 AttributeError
⇒ 整题结果被 fallback 吞成 ERROR（p0b5_r3 实测 2/10 题因此丢答案）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.diag_export import _diag_blueprint_review  # noqa: E402


class _Ctx:
    def __init__(self, falsified):
        self.problem = "测试题"
        self.metadata = {"falsified_answers": falsified}
        self.trace = []
        self.blueprint_nodes = []
        self.blueprint_merge = {}
        self.dag_review = {}
        self.blueprint_self_review_events = []


def test_falsified_answers_mixed_types_do_not_crash():
    """★ 混入 str / dict 都不崩，且两者都能被导出。"""
    ctx = _Ctx([{"answer": "42"}, "裸字符串答案", 123, None])
    d = _diag_blueprint_review(ctx, None)
    fa = d.get("falsified_answers")
    assert isinstance(fa, list) and len(fa) == 4
    assert "42" in fa[0] and "裸字符串答案" in fa[1]


def test_falsified_answers_empty_ok():
    ctx = _Ctx([])
    d = _diag_blueprint_review(ctx, None)
    assert d.get("falsified_answers") == []
