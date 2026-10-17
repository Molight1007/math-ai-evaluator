# -*- coding: utf-8 -*-
"""自审输出解析回归（2026-10-17 p0b5_r3 84/88 unparsed 修复）。

根因：原解析取「第一个 `{` 到最后一个 `}`」，模型输出「推理 + JSON」或
「多个 JSON 片段」时跨段非法 ⇒ 恒解析失败（unparsed）。现改为 raw_decode
逐 `{` 尝试。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.self_auditor import parse_self_audit_json as P  # noqa: E402


def test_pure_json():
    d = P('{"logic_error": false, "error_desc": "", "error_at": ""}')
    assert d and d["logic_error"] is False


def test_json_with_leading_reasoning():
    """★ 模型先写推理再给 JSON —— 原实现必然失败，现在要能提取。"""
    raw = ('让我检查一下这份解答……\n第 2 步用了一个题面没有的条件。\n'
           '{"logic_error": true, "error_desc": "前提误用：使用了题面不存在的条件", '
           '"error_at": "步骤2"}')
    d = P(raw)
    assert d and d["logic_error"] is True
    assert "前提误用" in d["error_desc"]


def test_two_json_objects_picks_valid_one():
    raw = ('示例格式：{"logic_error": true}\n实际结论：\n'
           '{"logic_error": false, "error_desc": "", "error_at": ""}')
    d = P(raw)
    assert d and d["logic_error"] is False


def test_markdown_fenced():
    raw = '```json\n{"logic_error": true, "error_desc": "跳步", "error_at": "3"}\n```'
    d = P(raw)
    assert d and d["logic_error"] is True


def test_unparseable_returns_empty():
    assert P("完全不是 JSON 的输出") == {}
    assert P('{"foo": 1}') == {}      # 缺 logic_error 键
    assert P("") == {}
