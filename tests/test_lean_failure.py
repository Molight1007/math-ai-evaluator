# -*- coding: utf-8 -*-
"""Lean 编译失败原因分类（tools/lean_local/lean_failure.py）单测 —— 2026-10-22。

覆盖：四类语义的判定边界、refuted 优先级、空输入兜底，
以及 4.3 分级开关是否真的落到判定上（只有 refuted 才允许淘汰）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.lean_local.lean_failure import (  # noqa: E402
    ENV, REFUTED, TRANSLATION, UNKNOWN, UNPROVED,
    classify_compile_error, evidences_refutation)


# ------------------------------------------------------------ 逐类判定
def test_refuted_is_detected_from_false_goal():
    assert classify_compile_error("probe.lean:3:29: error: unsolved goals\n⊢ False") == REFUTED
    assert classify_compile_error("error: unsolved goals\n|- False") == REFUTED
    assert classify_compile_error("decide proved the proposition is false") == REFUTED


def test_refuted_takes_priority_over_other_markers():
    # 同时含 unsolved goals 与 unknown module —— refuted 优先（最强结论）
    txt = "unknown module prefix 'X'\nerror: unsolved goals\n⊢ False"
    assert classify_compile_error(txt) == REFUTED


def test_unproved_when_goal_not_false():
    # 代码合法、只是没证出来 ⇒ 与「答案错」无关
    assert classify_compile_error(
        "error: unsolved goals\nn : ℕ\nh : n > 3\n⊢ n ≥ 4") == UNPROVED
    assert classify_compile_error(
        "error: linarith failed to find a contradiction") == UNPROVED
    assert classify_compile_error("error: norm_num failed") == UNPROVED
    assert classify_compile_error("error: type mismatch") == UNPROVED


def test_env_when_dependency_missing():
    assert classify_compile_error(
        "error: unknown module prefix 'Batteries'") == ENV
    assert classify_compile_error(
        "error: object file 'X/Mathlib/Tactic.olean' does not exist") == ENV
    assert classify_compile_error("error: bad import 'Mathlib.Foo'") == ENV


def test_translation_when_generated_code_invalid():
    assert classify_compile_error("error: unknown identifier 'foo'") == TRANSLATION
    assert classify_compile_error("error: unknown tactic 'magic'") == TRANSLATION
    assert classify_compile_error(
        "error: unexpected token ';'; expected ')'") == TRANSLATION
    assert classify_compile_error("error: invalid syntax") == TRANSLATION


def test_empty_and_unknown_fall_back_to_unknown():
    assert classify_compile_error("") == UNKNOWN
    assert classify_compile_error(None) == UNKNOWN
    assert classify_compile_error("something completely different") == UNKNOWN


# ------------------------------------------------------------ 淘汰资格
def test_only_refuted_evidences_refutation():
    assert evidences_refutation(REFUTED) is True
    for k in (UNPROVED, TRANSLATION, ENV, UNKNOWN, "", None):
        assert evidences_refutation(k) is False


# ------------------------------------------------------------ 开关落地
def test_failure_kind_split_switch_default_true():
    from contracts.switch_registry import get_bool
    assert get_bool("lean_failure_kind_split") is True
