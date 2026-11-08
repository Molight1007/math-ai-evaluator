# -*- coding: utf-8 -*-
"""严格编译判据的单测（E43）。用 pytest 单独跑：

    pytest 测试结果/步级合法率体检E43_20261108/test_compile_check_strict.py -q

样本格式来自服务器 Lean 4.31 真实日志（`probe_e43_20261108/out/S_*.log`）。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compile_check_strict import (  # noqa: E402
    STATES, collect_diags, classify_compile)

F = "lean/S_full.lean"

# 只有 unsolved goals：合法但未闭合
RAW_OPEN = (
    "%s:9:2: error: unsolved goals\n"
    "case h\n"
    "n : Nat\n"
    "⊢ n = n\n" % F
)
# ★ 核心：硬错误 + Lean 错误恢复留下的 unsolved goals（旧判据在这里翻车）
RAW_HARD_RECOVER = (
    "%s:18:14: error(lean.unknownIdentifier): Unknown identifier `sq_add_sq`\n"
    "%s:18:2: error: unsolved goals\n"
    "⊢ n = n\n" % (F, F)
)
RAW_HARD_ONLY = (
    "%s:44:27: error: numerals are data in Lean, but the expected type is a proposition\n"
    "%s:45:4: error(lean.unknownIdentifier): Unknown identifier `nlinarith`\n" % (F, F)
)
RAW_SORRY = "%s:9:0: warning: declaration uses 'sorry'\n" % F


def test_states_unchanged():
    """★ 单变量：状态集合不许新增，旧调用方 run_one 才不会把新状态当 UNSOLVED。"""
    assert STATES == frozenset({"CLOSED", "UNSOLVED", "ERROR", "TIMEOUT"})


def test_only_unsolved_goals_is_unsolved():
    r = classify_compile(1, RAW_OPEN)
    assert r["status"] == "UNSOLVED"
    assert "⊢ n = n" in r["goal"]
    assert r["error"] == ""


def test_hard_error_with_recovery_must_be_error():
    """★ 本轮修复的洞：硬错误后的 unsolved goals 不能当合法步。"""
    r = classify_compile(1, RAW_HARD_RECOVER)
    assert r["status"] == "ERROR"
    assert "Unknown identifier" in r["brief"]
    assert r["goal"] == ""


def test_paren_error_format_is_recognized():
    """Lean 4.31 的 `error(lean.xxx):` 格式，旧 ANY_ERR 正则会全漏。"""
    hard, unsolved, _ = collect_diags(RAW_HARD_RECOVER)
    assert len(hard) == 1 and len(unsolved) == 1
    assert "Unknown identifier" in hard[0]
    assert classify_compile(1, RAW_HARD_ONLY)["status"] == "ERROR"


def test_closed_requires_rc0_and_no_error():
    assert classify_compile(0, "")["status"] == "CLOSED"
    assert classify_compile(0, "some linter note")["status"] == "CLOSED"


def test_rc0_with_hard_error_is_not_closed():
    """防假闭合：即便 rc 侥幸为 0，有 error 诊断就不能 CLOSED。"""
    assert classify_compile(0, RAW_HARD_RECOVER)["status"] == "ERROR"


def test_sorry_warning_is_not_closed():
    assert classify_compile(0, RAW_SORRY)["status"] == "ERROR"


def test_only_unsolved_but_rc0_is_unsolved():
    assert classify_compile(0, RAW_OPEN)["status"] == "UNSOLVED"


def test_timeout_wins():
    assert classify_compile(1, RAW_HARD_RECOVER, timed_out=True)["status"] == "TIMEOUT"


def test_no_diagnostics_and_nonzero_rc_is_error():
    r = classify_compile(1, "")
    assert r["status"] == "ERROR" and "rc=1" in r["brief"]


def test_goal_extraction_stops_at_next_diag():
    raw = (RAW_OPEN + "%s:20:2: error: unsolved goals\n⊢ m = m\n" % F)
    r = classify_compile(1, raw)
    assert r["status"] == "UNSOLVED"
    assert "⊢ n = n" in r["goal"] and "⊢ m = m" not in r["goal"]


def test_old_probe_order_reproduces_the_bug():
    """回归锚：把旧判据顺序原样复刻，证明它确实会把硬错误误判为 UNSOLVED。

    这条测试**故意断言旧行为是错的**，防止以后有人再把顺序换回去。
    """
    import re
    old_unsolved = re.compile(r"error:\s*unsolved goals\s*\n")
    old_any_err = re.compile(r":\d+:\d+: error:")
    raw = RAW_HARD_RECOVER
    # 旧顺序：CLOSED 判据（ANY_ERR 漏掉括号格式）→ UNSOLVED 命中就 return
    old_closed = (1 == 0 and not old_any_err.search(raw))
    old_status = "CLOSED" if old_closed else (
        "UNSOLVED" if old_unsolved.search(raw) else "ERROR")
    assert old_status == "UNSOLVED"          # 旧版真的翻车
    assert classify_compile(1, raw)["status"] == "ERROR"   # 新版翻回来


def test_dropin_shape_matches_old_probe():
    """drop-in 返回形状与旧 compile_check 一致，run_one 不用改一行。"""
    from compile_check_strict import compile_check
    r = compile_check("example : True := by trivial", "t",
                      runner=lambda code, tag, timeout: (0, "", False))
    assert set(r) == {"status", "brief", "goal", "error", "compile_sec"}
    assert r["status"] == "CLOSED"


def test_dropin_hard_error_maps_to_error_not_unsolved():
    """★ 端到端：注入真实诊断文本，drop-in 必须判 ERROR（旧版会判 UNSOLVED）。"""
    from compile_check_strict import compile_check
    r = compile_check("example : False := by foo", "t",
                      runner=lambda code, tag, timeout: (1, RAW_HARD_RECOVER, False))
    assert r["status"] == "ERROR"
    assert r["goal"] == ""
    r2 = compile_check("example : 1=1 := by rfl", "t",
                       runner=lambda code, tag, timeout: (1, RAW_OPEN, False))
    assert r2["status"] == "UNSOLVED" and "⊢ n = n" in r2["goal"]


def test_dropin_timeout():
    from compile_check_strict import compile_check
    r = compile_check("", "t",
                      runner=lambda code, tag, timeout: (1, "", True))
    assert r["status"] == "TIMEOUT"
