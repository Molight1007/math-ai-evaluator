# -*- coding: utf-8 -*-
"""跨模型独立检错回归（2026-10-17）。只测纯逻辑分支，不真调网络。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.cross_model_check import _parse_json, cross_check  # noqa: E402


def test_parse_json_picks_last():
    assert _parse_json('{"wrong": true, "evidence": "a"}')["wrong"] is True
    d = _parse_json('示例 {"wrong": true}\n结论 {"wrong": false, "evidence": ""}')
    assert d["wrong"] is False          # 取最后一个（结论在后）


def test_no_key_returns_unknown(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    r = cross_check("题目", "答案")
    assert r["verdict"] == "unknown"
    assert "no DEEPSEEK_API_KEY" in r["error"]


def test_empty_answer_unknown(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    r = cross_check("题目", "")
    assert r["verdict"] == "unknown" and r["error"] == "empty answer"
