# -*- coding: utf-8 -*-
"""4.5 投票消费 4.4 机器核验状态（2026-10-22）。

背景：4.4 把 `verify_math`（逐式复算是否全一致）写在候选上，但**没有任何消费方**
读它 ⇒ 检测环节的结论到不了选择层。现接入为票数并列时的次级依据：
    (是否 verified, 支持数, 是否算术已核, 形态分, −答案长度)

契约：
  · 只在**票数并列**时起作用，不压过票数（「算术对」≠「答案对」）；
  · 开关 `five_gate_verify_tiebreak=0` ⇒ 回到只按形态分/长度。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.final_selector import _vote  # noqa: E402


def _cand(mark=""):
    """最小候选桩：只带 `verify_math`。"""
    class _C:
        pass
    c = _C()
    if mark:
        c.verify_math = mark
    return c


def test_tie_prefers_machine_ok():
    """两答案各 1 票 ⇒ 优先选「算术已核」的那个。"""
    survivors = [("5", "推理A", _cand("unknown")),
                 ("7", "推理B", _cand("pass"))]
    a, _c, d = _vote(survivors, verified=set(), verify_aware=True,
                     machine_ok={"7"})
    assert a == "7"
    assert "machine_ok" in d["tie_break"]
    assert d["n_machine_ok"] == 1


def test_support_still_beats_machine_ok():
    """票数优先：2 票但未核 vs 1 票但已核 ⇒ 选 2 票的。"""
    survivors = [("5", "A", _cand("unknown")), ("5", "A2", _cand("unknown")),
                 ("7", "B", _cand("pass"))]
    a, _c, _d = _vote(survivors, verified=set(), verify_aware=True,
                      machine_ok={"7"})
    assert a == "5"


def test_verified_still_beats_machine_ok():
    """verifier 验证（更强信号）优先于机器核验。"""
    survivors = [("5", "A", _cand("unknown")), ("7", "B", _cand("pass"))]
    a, _c, _d = _vote(survivors, verified={"5"}, verify_aware=True,
                      machine_ok={"7"})
    assert a == "5"


def test_no_machine_ok_keeps_old_order():
    """不传 machine_ok ⇒ 行为与改动前一致（只在形态分/长度上取舍）。"""
    survivors = [("5", "A", None), ("7", "B", None)]
    a1, _c1, d1 = _vote(survivors, verified=set(), verify_aware=True)
    a2, _c2, d2 = _vote(survivors, verified=set(), verify_aware=True,
                        machine_ok=set())
    assert a1 == a2
    assert "machine_ok" not in d1["tie_break"]
    assert d2["n_machine_ok"] == 0


def test_switch_default_true():
    from contracts.switch_registry import get_bool
    assert get_bool("five_gate_verify_tiebreak") is True
