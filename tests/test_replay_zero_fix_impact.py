# -*- coding: utf-8 -*-
"""重判工具的口径边界 —— 「只重判零判定分支」这件事本身要有测试。

为什么需要
----------
`_judge_subgoal_objective` 有多条分支（多候选符号多数 / 契约等式 / <check> 断言）。
零判定修复只影响后两条。如果重判时无差别地把所有行都重跑一遍，
「多 agent 符号多数」等分支的结果会被覆盖 —— 那样算出来的前后对比里
混进了与本次修复无关的变化，结论就不可信。
"""
import re

import pytest

import replay_zero_fix_impact as R


# ------------------------------------------------------- B1 判词范围过滤
@pytest.mark.parametrize("reason", [
    "本步结论等式经 SymPy 客观判定**不成立**（两侧展开后相差 f - 1，并非恒等）",
    "结果中 <check> 断言「18*100 + 10 = 1810」客观判定不成立（左式实际值应为 1810）",
])
def test_target_reason_matches(reason):
    assert R._TARGET_REASON.match(reason)


@pytest.mark.parametrize("reason", [
    "多候选符号多数（多 agent 路径已判定）",
    "等式断言经 SymPy 判定成立（恒等/数值为真）",
    "结论为『判定 = 真』型自然语言判定，无外部真值可比对，客观手段判不出真伪",
    "",
])
def test_target_reason_excludes_other_branches(reason):
    assert not R._TARGET_REASON.match(reason)


# ------------------------------------------------------- B2 重判行为
def _row(reason, verdict, result, answers=None):
    return {"objective_reason": reason, "objective_verdict": verdict,
            "result": result, "candidate_answers": answers or []}


def test_rejudge_flips_false_positive():
    """算式断言算对却判 incorrect ⇒ 重判应翻案，且不改 out-of-scope 行。"""
    shim = R._Shim()
    rows = [
        _row("结果中 <check> 断言「18*100 + 10 = 1810」客观判定不成立（左式实际值应为 1810）",
             "incorrect",
             "本步结论: 判定 = 真\n本步依据: 本步推导\n<check>18*100 + 10 = 1810</check>"),
        _row("多候选符号多数（多 agent 路径已判定）", "correct", "本步结论: 判定 = 真"),
    ]
    new, st = R.rejudge(rows, shim)
    assert st["in_scope"] == 1
    assert st["incorrect_to_other"] == 1
    assert st["other_to_incorrect"] == 0
    assert new[0]["objective_verdict"] != "incorrect"
    # 范围外那行必须原样保留（同一个对象语义，不改判）
    assert new[1] is rows[1]


def test_rejudge_keeps_true_error():
    """真算错的断言不得被放过。"""
    shim = R._Shim()
    rows = [
        _row("结果中 <check> 断言「18*100 + 10 = 1811」客观判定不成立（左式实际值应为 1810）",
             "incorrect",
             "本步结论: 判定 = 真\n本步依据: 本步推导\n<check>18*100 + 10 = 1811</check>"),
    ]
    new, st = R.rejudge(rows, shim)
    assert st["same"] == 1
    assert st["incorrect_to_other"] == 0
    assert new[0]["objective_verdict"] == "incorrect"
