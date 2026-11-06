# -*- coding: utf-8 -*-
"""E36：把「为什么没真跑」落盘到 04 归档 —— 纯观测字段的构造用例 + 门禁。

背景（2026-11-05 22:05 → 11-06 05:19 真实运行，results/20261105-220521）：
  4 条被闸门否决的 tool=lean 子目标里，q03d3e039#6 与 q2a6f8743#4 明明写了
  ````lean 代码块，归档却只有 tool_ran=False / sig_gate_stage=UNVERIFIED，
  无法区分「编译额度超限」「Lean 环境不可用」「桥初始化失败」；
  q03d3e039#5 则是模型压根没写 lean 块（5 万字符散文后自认推不出）。
  sg 上本就有 tool_not_run_reason 区分前几种，但 `_build_trace_item`
  的白名单没抄 ⇒ 唯一的观测证据在归档出口丢失。

锁四件事：
  ① 原因字段确实到得了归档（含 5 种已知原因与空值）
  ② 与 E32 同口径：只在字段存在时条件写入，绝不补默认值
  ③ 纯观测：不参与 closure_of 的任何判据，历史产物判定逐字不变
  ④ 不新增开关、不引入第二个判据读取点
"""
from __future__ import annotations

import inspect

import pytest

from agent.sub_goal_solver__format import _build_trace_item
from contracts import closure as CL
from contracts.closure import closure_of, CLOSURE_HARD, CLOSURE_SOFT, CLOSURE_OPEN

# `sub_goal_solver__lean.py::_lean_block_verify` 目前会写入的全部原因。
KNOWN_REASONS = (
    "lean-cap",
    "lean-bridge-import",
    "lean-bridge-init",
    "lean-unavailable",
    "lean-no-workdir",
)


def _sg(**kw):
    d = {
        "id": 1, "title": "t", "description": "d", "type": "prove",
        "depends_on": [], "expected_output": "e", "candidates": [],
        "candidate_answers": [], "conclusion": "", "conclusion_kind": "",
        "conclusion_support": "", "has_derivation": True,
        "objective_verdict": "correct", "objective_reason": "",
        "tool": "lean", "tool_ran": False, "tool_verdict": "",
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------- ① 落盘
@pytest.mark.parametrize("reason", KNOWN_REASONS)
def test_known_reasons_reach_archive(reason):
    sg = _sg(tool_not_run_reason=reason)
    item = _build_trace_item(sg, "结果正文")
    assert item["tool_not_run_reason"] == reason
    assert item["tool_ran"] is False


def test_reason_coexists_with_gate_fields():
    """归因字段与三道门字段互不遮蔽（真实运行里两者同现）。"""
    sg = _sg(
        tool_not_run_reason="lean-cap",
        sig_gate_allowed=False, sig_gate_stage="UNVERIFIED",
        sig_gate_reasons=["未提供命题编译结果"], sig_gate_prop="P",
        tool_verdict="unknown: sig_gate=UNVERIFIED 未提供命题编译结果",
    )
    item = _build_trace_item(sg, "结果正文")
    assert item["tool_not_run_reason"] == "lean-cap"
    assert item["sig_gate_allowed"] is False
    assert item["sig_gate_stage"] == "UNVERIFIED"
    assert closure_of(item)[0] == CLOSURE_OPEN


def test_empty_reason_is_kept_explicitly():
    """字段存在但为空 ⇒ 写空串，不写 None / 不猜一个原因。"""
    item = _build_trace_item(_sg(tool_not_run_reason=""), "结果正文")
    assert "tool_not_run_reason" in item
    assert item["tool_not_run_reason"] == ""


# ---------------------------------------------------------------- ② 不补默认值
def test_no_reason_field_does_not_invent_one():
    """★ 历史产物（含模型没写 lean 块这一形态）不得凭空长出原因字段。"""
    item = _build_trace_item(_sg(), "结果正文")
    assert "tool_not_run_reason" not in item
    assert not any(k.startswith("sig_gate_") for k in item)


def test_historical_rows_classify_identically_with_and_without_reason():
    """判据逐字不变：同一条历史记录，补不补观测字段都是同一闭合层级。"""
    base = dict(
        id=1, tool="lean", tool_ran=False, has_derivation=True,
        objective_verdict="correct",
        tool_verdict="unknown: sig_gate=UNVERIFIED 未提供命题编译结果",
        sig_gate_allowed=False, sig_gate_stage="UNVERIFIED",
        sig_gate_reasons=[], sig_gate_prop="",
    )
    for extra, expect in (
        ({}, CLOSURE_OPEN),
        ({"tool_not_run_reason": "lean-cap"}, CLOSURE_OPEN),
        ({"tool_not_run_reason": "lean-unavailable"}, CLOSURE_OPEN),
    ):
        item = dict(base)
        item.update(extra)
        assert closure_of(item)[0] == expect


# ---------------------------------------------------------------- ③ 纯观测
def test_reason_never_changes_any_closure_branch():
    """四级闭合的每一档，加不加归因字段都必须同档。"""
    cases = [
        (dict(tool_ran=True, tool_verdict="pass",
              objective_verdict="wrong"), CLOSURE_HARD),
        (dict(tool_ran=False, objective_verdict="correct",
              has_derivation=True), CLOSURE_SOFT),
        (dict(tool_ran=False, objective_verdict="wrong"), CLOSURE_OPEN),
        # 失败词只挡 HARD，判对+有推导仍按现行口径落 SOFT（不改动判据）
        (dict(tool_ran=True, tool_verdict="sorry",
              objective_verdict="correct"), CLOSURE_SOFT),
    ]
    for fields, expect in cases:
        a = _build_trace_item(_sg(**fields), "结果正文")
        b = _build_trace_item(
            _sg(**dict(fields, tool_not_run_reason="lean-cap")), "结果正文")
        assert closure_of(a)[0] == expect
        assert closure_of(b)[0] == expect


def test_decisive_counterexample_gate_reject_still_open():
    """E32 决定性反例：工具说 OK + 闸门否决 ⇒ OPEN，不被观测字段救回。"""
    sg = _sg(
        tool_ran=True, tool_verdict="OK",
        sig_gate_allowed=False, sig_gate_stage="ILLEGAL",
        sig_gate_reasons=["命题不可陈述"], sig_gate_prop="",
        tool_not_run_reason="lean-bridge-init",
    )
    assert closure_of(_build_trace_item(sg, "结果正文"))[0] == CLOSURE_OPEN


def test_closure_module_does_not_read_reason():
    """契约层单一权威：闭合判定里不许出现这个字段名。"""
    src = inspect.getsource(CL)
    assert "tool_not_run_reason" not in src, "观测字段渗进判据了"


# ---------------------------------------------------------------- ④ 门禁
def test_projection_adds_no_switch():
    src = inspect.getsource(_build_trace_item)
    for banned in ("POLICY[", "os.environ", "getenv", "AB_OVERRIDES",
                   "getattr(self.config"):
        assert banned not in src, "投影里出现新变量：%s" % banned


def test_reason_vocabulary_stays_in_sync_with_solver():
    """求解侧新增原因必须同步登记，否则归因又会出现无法解释的字面值。"""
    from agent import sub_goal_solver__lean as L
    src = inspect.getsource(L)
    import re
    found = set(re.findall(r'"(lean-[a-z-]+)"', src))
    assert found == set(KNOWN_REASONS), \
        "原因词表漂移：%s" % (found ^ set(KNOWN_REASONS))
