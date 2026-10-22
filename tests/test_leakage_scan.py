# -*- coding: utf-8 -*-
"""泄漏筛查（tools/leakage_scan.py）单测 —— 2026-10-22。

覆盖：题号/单题分支/答案原文三类硬泄漏、单题常量只作提示、
干净文本不误报（防「天天告警 → 被忽略」）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.leakage_scan import scan, verdict  # noqa: E402

EMPTY_FREQ: dict = {}


def _scan(text, golds=(), freq=None):
    return scan(text, list(golds), freq if freq is not None else EMPTY_FREQ)


# ------------------------------------------------------------ 硬泄漏
def test_task_id_detected():
    h = _scan("if x == 'official112-073': pass")
    assert h["TASK_ID"] and h["TASK_ID"][0]["match"] == "official112-073"


def test_task_id_hash_and_imo_forms():
    h = _scan("id='q1234abcd' or 'imo-bench-number_theory-075'")
    kinds = {x["kind"] for x in h["TASK_ID"]}
    assert "题号哈希" in kinds and "imo-bench 题号" in kinds


def test_branch_on_task_id_detected():
    h = _scan('if task_id == "official112-073":\n    answer = 1')
    assert h["BRANCH"]


def test_gold_answer_in_code_detected():
    golds = [("official112-008", "603729")]
    h = _scan("ANSWER = 603729", golds)
    assert h["GOLD"] and h["GOLD"][0]["task"] == "official112-008"


def test_clean_code_has_no_hard_leak():
    h = _scan("def f(n):\n    return n * 2  # 通用逻辑\n")
    level, _msg = verdict(h)
    assert level == "CLEAN"


# ------------------------------------------------------------ 常量（仅提示）
def test_single_task_constant_is_hint_only():
    h = _scan("LIMIT = 12345", freq={"12345": 1})
    assert h["CONST"]
    # ★ 只有常量命中 ⇒ 不升级为 LEAK（否则注释里的示例数字天天告警）
    level, msg = verdict(h)
    assert level == "CLEAN" and "仅作提示" in msg


def test_constant_shared_by_many_tasks_ignored():
    h = _scan("LIMIT = 12345", freq={"12345": 30})
    assert h["CONST"] == []


def test_benign_year_constant_ignored():
    h = _scan("YEAR = 2026", freq={"2026": 1})
    assert h["CONST"] == []


# ------------------------------------------------------------ 分级
def test_verdict_leak_when_hard_hit():
    h = _scan("if tid == 'official112-001': pass")
    level, msg = verdict(h)
    assert level == "LEAK" and "硬泄漏" in msg


def test_verdict_empty_text_is_clean():
    level, _msg = verdict(_scan(""))
    assert level == "CLEAN"
