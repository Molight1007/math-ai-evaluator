# -*- coding: utf-8 -*-
"""E31 真判接线的**构造用例**验证（服务器历史数据不可验的那一档）。

为什么必须有这张床：`replay_gate_enforce.py` 在历史产物上只能验门 A / 门 B，
门 C 需要求解侧补完的证明体，而历史盘上 90 条是 NO_PROOF（工具一次没跑）。
⇒ 真判「会不会把不该否决的否掉」不能靠历史数据回答，只能逐路径构造。

覆盖的是 `_tool_declared_verify` 的分支，而不是只测契约层纯函数：
  · 无签名 / 非 lean 工具 ⇒ 闸门**不适用**，不得写 sig_gate_allowed（防误杀）
  · 有签名但没跑 Lean ⇒ UNVERIFIED（没验 ≠ 验过）
  · 三道门全过 ⇒ 才允许写 pass
  · 证明体带 sorry / 门 A 编译不可用 / 命题不可陈述 ⇒ 一律不认
  · 历史产物无 sig_gate_allowed 字段 ⇒ closure_of 逐字不变

★ E27 教训：数字漂亮挡不住抽验。这里每条用例都是「人工可读的判据链一层」，
  不是覆盖率数字。
"""
from __future__ import annotations

import pytest

import agent.sub_goal_solver__lean as M
from contracts.closure import closure_of, CLOSURE_HARD, CLOSURE_OPEN
from contracts.formal_sig_gate import evaluate, proof_credential

SIG = "example (n : Nat) (h : n = 3) : n + 1 = 4 := by sorry"
PROOF_OK = "example (n : Nat) (h : n = 3) : n + 1 = 4 := by omega"
PROOF_SORRY = "example (n : Nat) (h : n = 3) : n + 1 = 4 := by sorry"
LEAN_BLOCK = "```lean\nexample (n : Nat) : n = n := by rfl\n```"


class _Ctx:
    def __init__(self):
        self.metadata = {}

    def gen_time_up(self):
        return False


class _Self:
    """只实现 tool=sympy / numeric 分支会用到的方法，lean 分支不需要。"""

    def _extract_check_asserts(self, result):
        return [("1", "1")]

    def _sympy_verify_pairs(self, result):
        return ""

    def _extract_lean_assert_pairs(self, result):
        return []


def _run_verify(sg, result):
    return M._tool_declared_verify(_Self(), _Ctx(), sg, result)


# ---------------------------------------------------------------------------
# 一、闸门「不适用」的路径 —— 这里写错就是真误杀
# ---------------------------------------------------------------------------
def test_no_signature_does_not_write_gate_fields():
    """无签名子目标走旧路径，闸门不得插手。"""
    sg = {"tool": "lean", "formal_sig": ""}
    assert _run_verify(sg, "普通文本") == ""
    assert "sig_gate_allowed" not in sg
    assert sg["tool_ran"] is False
    assert sg["tool_verdict"] == ""


def test_non_lean_tool_with_signature_is_not_rejected():
    """★ 关键防误杀：sympy/numeric 有签名也不该被形式签名闸门否决。"""
    sg = {"tool": "sympy", "formal_sig": SIG}
    assert _run_verify(sg, "<check>1 = 1</check>") == ""
    assert "sig_gate_allowed" not in sg
    assert sg["tool_ran"] is True
    assert sg["tool_verdict"] == "pass"
    assert closure_of(sg)[0] == CLOSURE_HARD


def test_llm_tool_is_not_touched():
    sg = {"tool": "llm", "formal_sig": SIG}
    assert _run_verify(sg, "叙述型结果") == ""
    assert "sig_gate_allowed" not in sg
    assert sg["tool_verdict"] == ""


# ---------------------------------------------------------------------------
# 二、有签名但工具没跑 —— UNVERIFIED，不是 pass
# ---------------------------------------------------------------------------
def test_signature_without_lean_block_is_unverified():
    sg = {"tool": "lean", "formal_sig": SIG}
    assert _run_verify(sg, "模型没写 Lean 代码块") == ""
    assert sg["sig_gate_allowed"] is False
    assert sg["sig_gate_stage"] == "UNVERIFIED"
    assert sg["tool_verdict"].startswith("unknown: sig_gate=UNVERIFIED")
    assert closure_of(sg) == (CLOSURE_OPEN, "sig_gate_rejected")


def test_trivial_prop_is_rejected_before_any_compile():
    sg = {"tool": "lean", "formal_sig": "example : True := by sorry"}
    _run_verify(sg, "无代码块")
    assert sg["sig_gate_stage"] == "NONTRIVIAL"
    assert sg["sig_gate_allowed"] is False


def test_bad_signature_shape_is_rejected():
    """不带 `:= by sorry` 的签名形态不合规 ⇒ SHAPE，不静默放行。"""
    sg = {"tool": "lean", "formal_sig": "theorem foo : 1 = 1"}
    _run_verify(sg, "无代码块")
    assert sg["sig_gate_stage"] == "SHAPE"
    assert sg["sig_gate_allowed"] is False


# ---------------------------------------------------------------------------
# 三、合成链：三道门全过才允许写 pass
# ---------------------------------------------------------------------------
def test_all_three_gates_pass_allows_pass(monkeypatch):
    def fake(self, ctx, result, sg):
        M._commit_sig_gate(sg, SIG, (0, ""), PROOF_OK)
        return ""

    monkeypatch.setattr(M, "_lean_block_verify", fake)
    sg = {"tool": "lean", "formal_sig": SIG}
    assert _run_verify(sg, LEAN_BLOCK) == ""
    assert sg["sig_gate_stage"] == "READY"
    assert sg["sig_gate_allowed"] is True
    assert sg["tool_verdict"] == "pass"


def test_proof_body_with_sorry_is_rejected(monkeypatch):
    """S2：求解侧把 sorry 原样交回来 = 作弊，工具说通过也不认。"""
    def fake(self, ctx, result, sg):
        M._commit_sig_gate(sg, SIG, (0, ""), PROOF_SORRY)
        return ""

    monkeypatch.setattr(M, "_lean_block_verify", fake)
    sg = {"tool": "lean", "formal_sig": SIG}
    _run_verify(sg, LEAN_BLOCK)
    assert sg["sig_gate_stage"] == "PROOF"
    assert sg["sig_gate_allowed"] is False
    assert "sorry" in sg["tool_verdict"] or "sig_gate=PROOF" in sg["tool_verdict"]


def test_missing_compile_result_is_unverified_even_with_good_proof(monkeypatch):
    """★ 没验 ≠ 验过：门 A 编译不可用，证明体再好也不放行。"""
    def fake(self, ctx, result, sg):
        M._commit_sig_gate(sg, SIG, None, PROOF_OK)
        return ""

    monkeypatch.setattr(M, "_lean_block_verify", fake)
    sg = {"tool": "lean", "formal_sig": SIG}
    _run_verify(sg, LEAN_BLOCK)
    assert sg["sig_gate_stage"] == "UNVERIFIED"
    assert sg["sig_gate_allowed"] is False
    assert sg["tool_verdict"] != "pass"


def test_illegal_prop_is_rejected(monkeypatch):
    def fake(self, ctx, result, sg):
        M._commit_sig_gate(sg, SIG, (1, "error: unknown identifier 'Phi'"), PROOF_OK)
        return ""

    monkeypatch.setattr(M, "_lean_block_verify", fake)
    sg = {"tool": "lean", "formal_sig": SIG}
    _run_verify(sg, LEAN_BLOCK)
    assert sg["sig_gate_stage"] == "STATED"
    assert sg["sig_gate_allowed"] is False


def test_lean_unavailable_keeps_unverified(monkeypatch):
    """★ 已知观测性缺口：环境不可用时理由写成「未提供编译结果」，
    语义正确（没验≠验过）但不精确。P1 补埋点时应单独记原因。"""
    def fake(self, ctx, result, sg):
        sg["tool_not_run_reason"] = "lean-unavailable"
        return ""

    monkeypatch.setattr(M, "_lean_block_verify", fake)
    sg = {"tool": "lean", "formal_sig": SIG}
    _run_verify(sg, LEAN_BLOCK)
    assert sg["sig_gate_stage"] == "UNVERIFIED"
    assert sg["sig_gate_allowed"] is False
    assert sg["tool_ran"] is False


# ---------------------------------------------------------------------------
# 四、契约层与归档回放的边界
# ---------------------------------------------------------------------------
def test_historical_item_without_gate_field_is_unchanged():
    """历史产物没有 sig_gate_allowed ⇒ closure_of 逐字沿用旧判定。
    这是「回放结论不受 E31 影响」的依据，不得改成回落或默认值。"""
    hist = {"tool_ran": True, "tool_verdict": "pass",
            "objective_verdict": "incorrect"}
    assert closure_of(hist)[0] == CLOSURE_HARD
    assert closure_of(dict(hist, sig_gate_allowed=False)) == (
        CLOSURE_OPEN, "sig_gate_rejected")


def test_proof_credential_distinguishes_s1_s2_s3():
    """S1 签名占位合法（由 split_sig 剥掉），S2 证明体 sorry 必须拒。"""
    assert proof_credential("")[0] == "EMPTY"
    assert proof_credential(PROOF_OK)[0] == "OK"
    assert proof_credential(PROOF_SORRY)[0] == "SORRY"
    assert proof_credential("by axiom foo")[0] == "SORRY"


def test_evaluate_default_proof_code_is_none_not_empty():
    """E31：默认值改为 None ⇒ NO_PROOF（尚未交付证明体），
    不是 PROOF(EMPTY)。影子期的旧默认值会让分类整体左移一格。"""
    v = evaluate(SIG, compile_result=(0, ""))
    assert v["stage"] == "NO_PROOF"
    assert v["allowed"] is False


# ---------------------------------------------------------------------------
# 五、E32：闸门否决字段必须落盘（P0 静态核对发现的断链）
# ---------------------------------------------------------------------------
def _base_sg():
    return {
        "id": 1, "title": "t", "description": "d", "type": "inline",
        "calc_kind": "inline", "depends_on": [], "expected_output": "",
        "candidates": [], "conclusion": "", "conclusion_kind": "",
        "conclusion_support": "", "conclusion_contract_ok": False,
        "has_derivation": False, "derivation_chars": 0,
        "objective_verdict": "", "objective_reason": "",
        "check_protocol_violations": [], "tool": "lean",
        "tool_ran": False, "tool_verdict": "",
    }


def test_trace_item_persists_gate_fields():
    """落盘是子目标记录的唯一出口；闸门判过就得带字段走。"""
    from agent.sub_goal_solver__format import _build_trace_item
    sg = _base_sg()
    sg.update(sig_gate_allowed=False, sig_gate_stage="STATED",
              sig_gate_reasons=["命题不可陈述：ILLEGAL / 未定义符号"],
              sig_gate_prop="1 = 1", tool_verdict="unknown: sig_gate=STATED")
    item = _build_trace_item(sg, "本步结果")
    assert item["sig_gate_allowed"] is False
    assert item["sig_gate_stage"] == "STATED"
    assert item["sig_gate_reasons"] == sg["sig_gate_reasons"]
    assert item["sig_gate_prop"] == "1 = 1"
    assert closure_of(item) == (CLOSURE_OPEN, "sig_gate_rejected")


def test_trace_item_does_not_invent_gate_fields():
    """★ 无签名/非 lean 条目闸门不适用 ⇒ 不得补 False 默认值，否则全量误杀。"""
    from agent.sub_goal_solver__format import _build_trace_item
    sg = _base_sg()
    sg.update(tool="sympy", tool_ran=True, tool_verdict="pass")
    item = _build_trace_item(sg, "本步结果")
    assert "sig_gate_allowed" not in item
    assert closure_of(item)[0] == CLOSURE_HARD


def test_closure_rejection_does_not_depend_on_fail_words():
    """★ 决定性反例：verdict 文本不含任何失败词，显式字段仍判 OPEN。
    若落盘丢字段，这条会退化成 HARD（假硬闭合）。"""
    from agent.sub_goal_solver__format import _build_trace_item
    sg = _base_sg()
    sg.update(sig_gate_allowed=False, sig_gate_stage="PROOF",
              sig_gate_reasons=[], sig_gate_prop="",
              tool_verdict="OK", tool_ran=True)
    item = _build_trace_item(sg, "本步结果")
    assert not any(w in item["tool_verdict"].lower()
                   for w in ("fail", "unknown", "sorry", "error", "错"))
    assert closure_of(item) == (CLOSURE_OPEN, "sig_gate_rejected")
