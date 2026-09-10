# -*- coding: utf-8 -*-
"""tests 共享 fixture（2026-09-06 晚 Lean 双通道恢复后加入）。

Lean 通道（orchestrator 2.6 preverify / 3.6 LeanGate / 6.5 最终闸门）依赖
真实 Lean 环境与 LLM 翻译，属集成行为——单元测试一律关闭（LEAN_VERIFY=0），
避免单测误走 lean 分支（真编译 5-21s/次拖垮测试 / mock client 无翻译能力）。
需要显式测 lean 通道的用例自行 monkeypatch.setenv("LEAN_VERIFY","1") 并
提供真实/打桩 LeanBridge。
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _lean_verify_off():
    os.environ["LEAN_VERIFY"] = "0"
    yield
