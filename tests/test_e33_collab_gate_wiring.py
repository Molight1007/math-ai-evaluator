# -*- coding: utf-8 -*-
"""E33：协作路径工具核验与三道门真判接线的构造用例 + 长期门禁。

背景：E31 把真判接在旧循环的工具核验入口，而生产固定策略恒走三角色协作
路径 ⇒ 真判是死代码。2026-11-05 首轮真实运行实测：5 个子目标里
tool=lean 4 条 / formal_sig 4 条 / 规划期 sig_gate_shape 5 条，而归档 04 里
tool_ran / tool_verdict / sig_gate_allowed 全为 0。

本文件锁三件事（不靠覆盖率数字，逐条是人工可读的判据链一层）：
  ① 协作路径两处写入口都必须调用唯一核验入口（源码级门禁，防再次绕过）
  ② 核验落盘后字段能被归档出口抄进去，且闭合判定正确（含决定性反例）
  ③ 不加开关、不额外重解（单变量对照），异常时显式否决而非静默放行
"""
from __future__ import annotations

import inspect

import agent.subgoal_collab as C
from agent.sub_goal_solver__format import _build_trace_item
from contracts.closure import closure_of, CLOSURE_OPEN, CLOSURE_SOFT
from contracts.policy import POLICY

SIG = "example (n : Nat) (h : n = 3) : n + 1 = 4 := by sorry"


class _Ctx:
    def __init__(self):
        self.metadata = {}


class _Solver:
    """只实现协作用到的两个方法；_tool_declared_verify 由用例注入。"""

    def __init__(self, fn=None):
        self.records = []
        self._fn = fn

    def _tool_declared_verify(self, ctx, sg, text):
        return self._fn(ctx, sg, text) if self._fn else ""

    def record(self, ctx, stage, msg):
        self.records.append((stage, msg))


def _sg(**kw):
    d = {
        "id": 1, "title": "t", "description": "d", "type": "prove",
        "depends_on": [], "expected_output": "e", "candidates": [],
        "candidate_answers": [], "conclusion": "", "conclusion_kind": "",
        "conclusion_support": "", "has_derivation": True,
        "objective_verdict": "correct", "objective_reason": "",
        "tool": "lean", "formal_sig": SIG,
    }
    d.update(kw)
    return d


def _reject(ctx, sg, text):
    sg.update({
        "tool_ran": True,
        "tool_verdict": "unknown: sig_gate=NO_PROOF 尚未交付证明体",
        "sig_gate_allowed": False,
        "sig_gate_stage": "NO_PROOF",
        "sig_gate_reasons": ["尚未交付证明体"],
        "sig_gate_prop": "n + 1 = 4",
    })
    return "【形式签名未闭合】"


# ---------------------------------------------------------------- ① 门禁
def test_collab_wires_verifier_at_both_write_points():
    """生产恒走协作路径 ⇒ 两处归档写入口都不能绕过核验。"""
    src = open(C.__file__, encoding="utf-8").read()
    assert POLICY["subgoal_collab_mode"] is True, "生产策略值变了，须重新论证"
    assert src.count("verify_and_mark(") >= 3, "定义 1 处 + 调用 2 处"
    main = src.index("verify_and_mark(solver, ctx, sg, _out)")
    strip = src.index("_out = solver._strip_check_tags(_out) or _out")
    build = src.index("ctx.subgoal_trace.append(solver._build_trace_item")
    assert main < strip, "核验必须在剥 <check> 标签之前"
    assert main < build, "核验必须在归档出口之前"
    assert src.index("verify_and_mark(solver, ctx, sg, step_result)") < \
        src.index("_build_trace_item(sg, step_result, reused=True)"), \
        "复用分支同样要核验"


def test_helper_adds_no_switch_and_no_extra_regen():
    """单变量对照：只加核验与落盘，不新增开关 / 不改策略 / 不多跑一次求解。"""
    src = inspect.getsource(C.verify_and_mark)
    for banned in ("POLICY[", "os.environ", "_solve_subgoal", "getenv",
                   "getattr(solver.config", "AB_OVERRIDES"):
        assert banned not in src, "接线里出现新变量：%s" % banned


# ---------------------------------------------------------------- ② 落盘
def test_gate_fields_reach_archive_and_close_as_open():
    sg = _sg()
    C.verify_and_mark(_Solver(_reject), _Ctx(), sg, "结果正文")
    item = _build_trace_item(sg, "结果正文")
    assert item["sig_gate_allowed"] is False
    assert item["sig_gate_stage"] == "NO_PROOF"
    assert item["sig_gate_reasons"] == ["尚未交付证明体"]
    assert item["sig_gate_prop"] == "n + 1 = 4"
    assert closure_of(item)[0] == CLOSURE_OPEN


def test_decisive_counterexample_ok_verdict_still_open():
    """★ 工具说通过 / 没有失败词，闸门否决仍必须压到最前判 OPEN。"""
    def _fake(ctx, sg, text):
        sg.update({"tool_ran": True, "tool_verdict": "OK",
                   "sig_gate_allowed": False,
                   "sig_gate_stage": "ILLEGAL",
                   "sig_gate_reasons": ["命题不可陈述"],
                   "sig_gate_prop": ""})
        return ""

    sg = _sg()
    C.verify_and_mark(_Solver(_fake), _Ctx(), sg, "结果正文")
    item = _build_trace_item(sg, "结果正文")
    assert item["tool_verdict"] == "OK"
    assert closure_of(item)[0] == CLOSURE_OPEN, "闸门否决被失败词子串巧合吞掉了"


def test_no_signature_does_not_invent_gate_fields():
    """E32 口径：无签名 / 非 lean ⇒ 闸门不适用，绝不补 False 默认值。"""
    def _fake(ctx, sg, text):
        sg["tool_ran"] = False
        sg["tool_verdict"] = ""
        return ""

    sg = _sg(tool="llm", formal_sig="")
    C.verify_and_mark(_Solver(_fake), _Ctx(), sg, "结果正文")
    item = _build_trace_item(sg, "结果正文")
    assert not any(k.startswith("sig_gate_") for k in item)
    assert closure_of(item)[0] == CLOSURE_SOFT, "历史判定被无端改写"


# ---------------------------------------------------------------- ③ 失败
def test_verifier_exception_fails_closed_with_trace():
    """契约层不可用 ⇒ 显式否决并留痕，绝不静默放行。"""
    def _boom(ctx, sg, text):
        raise RuntimeError("bridge down")

    sg = _sg()
    solver = _Solver(_boom)
    C.verify_and_mark(solver, _Ctx(), sg, "结果正文")
    item = _build_trace_item(sg, "结果正文")
    assert item["sig_gate_allowed"] is False
    assert item["sig_gate_stage"] == "UNAVAILABLE"
    assert "协作路径工具核验入口异常" in item["sig_gate_reasons"][0]
    assert "sig_gate=UNAVAILABLE" in item["tool_verdict"]
    assert item["tool_ran"] is False
    assert closure_of(item)[0] == CLOSURE_OPEN
    assert any("显式否决留痕" in m for _, m in solver.records)


def test_feedback_is_recorded_but_result_untouched():
    """核验反馈只留痕，不改求解文本 ⇒ 不引入额外 LLM 调用变量。"""
    text = "本步结果\n<check>1=1</check>"
    sg = _sg()
    solver = _Solver(_reject)
    C.verify_and_mark(solver, _Ctx(), sg, text)
    assert sg.get("result") is None, "接线不应碰存储层"
    assert any("工具核验未过" in m for _, m in solver.records)
