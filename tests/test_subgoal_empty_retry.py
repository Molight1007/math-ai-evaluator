# -*- coding: utf-8 -*-
"""子目标「空返回必须重做」（2026-10-22）。

实测背景：628 个子目标里 135 个失败（21.5%），其中 **95 个是 `result == ""`**。
旧实现的重做条件只有 `step_result.startswith("[子目标")`——空串不匹配，
于是这些空结果**从不重试**，直接进 `results_map` 被 merge 当有效输入。

本文件锁两件事：
  ① 判定层：空/纯空白 属于「未产出有效结论」（`is_subgoal_failed`）；
  ② 执行层：循环里空返回与占位符走**同一条**重做路径（读源守卫，防误删）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.gap_analyzer import is_subgoal_failed  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_empty_result_counts_as_failure():
    assert is_subgoal_failed("") is True
    assert is_subgoal_failed("   \n\t ") is True
    assert is_subgoal_failed(None) is True


def test_placeholder_and_plan_err_count_as_failure():
    assert is_subgoal_failed("[子目标3 求解失败]") is True
    assert is_subgoal_failed("本步无法推出，缺前提") is True


def test_real_conclusion_is_not_failure():
    assert is_subgoal_failed("本步结论: 值 = 5\n本步依据: 题设\n代入得 2+3=5。") is False


def test_loop_retries_on_empty_result():
    """执行层的重做条件必须覆盖空返回（旧实现只认 `[子目标` 前缀）。"""
    src = open(os.path.join(_ROOT, "agent", "sub_goal_solver__loop.py"),
               encoding="utf-8").read()
    assert 'or not str(step_result or "").strip()' in src, \
        "空返回未被纳入重做条件 ⇒ 95 个空结果会再次静默流入 merge"
    assert "subgoal_failed_retry_rounds" in src


def test_retry_rounds_switch_default():
    from contracts.switch_registry import get_num
    assert int(get_num("subgoal_failed_retry_rounds")) == 2


def test_failed_retry_writes_explicit_placeholder():
    """重做仍空 ⇒ 写显式占位符，而不是留空串（下游才能识别「本步无结论」）。"""
    src = open(os.path.join(_ROOT, "agent", "sub_goal_solver__loop.py"),
               encoding="utf-8").read()
    assert '[子目标%s 求解失败]' in src
