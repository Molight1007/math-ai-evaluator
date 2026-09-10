# -*- coding: utf-8 -*-
"""子目标交叉核对 ③（2026-09-08 老师建议3）确定性冲突闸单测。

只测 0-LLM 部分（_cross_conflicts / _collect_claims / _rhs_const），
纯函数级、不启动 LLM/评测。B 方向（LLM 交叉核对轮）需真实模型调用，
由后续 10 题/45 题评测实证，不进单测。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.sub_goal_solver import SubGoalSolverAgent  # noqa: E402


def _solver():
    """裸实例：不跑 __init__，仅用类级正则与纯方法。"""
    return SubGoalSolverAgent.__new__(SubGoalSolverAgent)


def _sg(sid, result):
    return {"id": sid, "title": f"子目标{sid}", "result": result}


def _run(subgoals):
    rm = {s["id"]: s["result"] for s in subgoals}
    return _solver()._cross_conflicts(subgoals, rm)


# ---------- 显式冲突（应检出） ----------
def test_same_var_diff_const():
    """同名 x 在不同子目标取 1 与 2 → 显式矛盾（calc 回填带前缀自然语言）。"""
    sgs = [
        _sg(1, "解得 [计算] x = 1"),
        _sg(2, "由第二条件得 <check>x = 2</check> 成立"),
    ]
    c = _run(sgs)
    assert len(c) == 1
    assert "x" in c[0] and "子目标 #1" in c[0] and "子目标 #2" in c[0]


def test_plain_text_fragment_caught():
    """纯文本结论行（无 calc/<check> 标记）"解得 x = 1" 也能收集比对。"""
    sgs = [
        _sg(1, "第一步解得 x = 1，代回验证成立。"),
        _sg(2, "再解方程得 x = 2。"),
    ]
    c = _run(sgs)
    assert len(c) == 1 and "x" in c[0]


def test_diff_var_no_conflict():
    """xy=25 与 D=2 不共用变量名 → 纯规则抓不到（alg-060 盲区，如实漏）。"""
    sgs = [
        _sg(1, "得 [计算] xy = 25"),
        _sg(2, "判别式 [计算] D = 2"),
    ]
    assert _run(sgs) == []


def test_case_marker_excluded():
    """分支讨论（当 k=1 / 若 x=2）前缀 → 不参与冲突判定（防分支误报）。"""
    sgs = [
        _sg(1, "当 k = 1 时，代入解得…"),
        _sg(2, "情形 k = 2 单独讨论…"),
    ]
    assert _run(sgs) == []


# ---------- 同值不同写法（不应误报） ----------
def test_same_value_diff_notation():
    """0.5 与 1/2、sqrt(45) 与 3*sqrt(5) 同值 → 不报。"""
    sgs = [
        _sg(1, "得 [计算] a = 0.5"),
        _sg(2, "得 <check>a = 1/2</check>"),
    ]
    assert _run(sgs) == []
    sgs = [
        _sg(1, "得 [计算] a = sqrt(45)"),
        _sg(2, "得 [计算] a = 3*sqrt(5)"),
    ]
    assert _run(sgs) == []


# ---------- 规则盲区/边界（宁漏勿误报） ----------
def test_composite_lhs_skipped():
    """x^2=4 vs x^2=9 是复合 LHS（± 分支），不做常量冲突判定。"""
    sgs = [
        _sg(1, "得 [计算] x^2 = 4"),
        _sg(2, "得 [计算] x^2 = 9"),
    ]
    assert _run(sgs) == []


def test_rhs_with_var_skipped():
    """x = n+1（RHS 带自由符号）→ 不比较。"""
    sgs = [
        _sg(1, "得 [计算] x = n + 1"),
        _sg(2, "得 [计算] x = 2"),
    ]
    assert _run(sgs) == []


def test_chinese_lhs_skipped():
    """LHS 非 ASCII 标识符（面积 = 25）→ 不做常量冲突判定（防误报）。"""
    sgs = [
        _sg(1, "得 [计算] 面积 = 25"),
        _sg(2, "得 [计算] 面积 = 30"),
    ]
    assert _run(sgs) == []


def test_no_claims_empty():
    """无 calc/<check>/等式断言 → 空清单。"""
    sgs = [_sg(1, "结论：无解"), _sg(2, "（子目标 2 已求解）")]
    assert _run(sgs) == []


def test_same_subgoal_self_conflict_not_reported():
    """同一子目标内 x=1 又 x=2（分支枚举/自我修正）→ 不报，merge 兜底。"""
    sgs = [_sg(3, "解得 x = 1；或取 x = 2 两种可能")]
    assert _run(sgs) == []


def test_failed_subgoal_marker_ignored():
    """失败占位标记（无断言）不参与冲突。"""
    sgs = [
        _sg(1, "（子目标 #1 求解失败未产出有效结论）"),
        _sg(2, "得 [计算] x = 3"),
    ]
    assert _run(sgs) == []


def test_conflict_only_other_subgoal_value():
    """三方取值：子目标1 说 x=1；子目标2/3 都说 x=2 → 报一对即可。"""
    sgs = [
        _sg(1, "得 x = 1"),
        _sg(2, "得 x = 2"),
        _sg(3, "验证 [计算] x = 2"),
    ]
    c = _run(sgs)
    assert len(c) == 1 and "子目标 #1" in c[0] and "子目标 #2" in c[0]
