# -*- coding: utf-8 -*-
"""P2 子目标类型路由（calc_kind 打标规则）单测（2026-09-09）。

打标是纯函数 _calc_kind_of（宁 inline 勿误 terminal，防把推理子目标截成
表达式翻译）；router 行为（专用模板/轻校验）由 10 题评测实证，不进单测。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.sub_goal_solver import SubGoalSolverAgent  # noqa: E402

K = SubGoalSolverAgent._calc_kind_of


def _via_parse(subgoals_raw):
    """走真实解析链路（含打标注入）验证字段存在。"""
    out = SubGoalSolverAgent._parse_subgoal_plan(
        {"subgoals": subgoals_raw}, max_subgoals=6)
    return out


def test_terminal_action_kw():
    # 明确求值动作词 → terminal
    assert K("compute", "代入 x=5 求值", "结果") == "terminal"
    assert K("compute", "计算组合数总和", "19600") == "terminal"
    assert K("compute", "化简该表达式", "x+1") == "terminal"
    assert K("compute", "求积分值", "1/3") == "terminal"


def test_terminal_short_numeric_output():
    # expected_output 是短数值形态（数字/负号/等号/括号开头）→ terminal
    assert K("compute", "解出数值", "27") == "terminal"
    assert K("compute", "数值", "-3/4") == "terminal"
    assert K("compute", "值", "= 1024") == "terminal"


def test_inline_proof_or_reasoning():
    # 证明/推理型 → inline（即使含'算'等字）
    assert K("prove", "证明单调性", "结论") == "inline"
    assert K("derive", "推导通项", "通项公式") == "inline"
    assert K("verify", "验证上一步", "") == "inline"


def test_inline_no_signal():
    # compute 但无求值信号且 output 非短数值 → inline（宁漏勿误）
    assert K("compute", "分析两种情形", "完整分类讨论过程") == "inline"
    assert K("compute", "确定取值范围", "答案") == "inline"


def test_parse_injects_calc_kind():
    rows = [
        {"id": 1, "title": "计算分母", "type": "compute",
         "expected_output": "19600", "depends_on": []},
        {"id": 2, "title": "证明结论", "type": "prove",
         "expected_output": "证明过程", "depends_on": [1]},
    ]
    out = _via_parse(rows)
    assert out and len(out) == 2
    assert out[0]["calc_kind"] == "terminal"
    assert out[1]["calc_kind"] == "inline"
