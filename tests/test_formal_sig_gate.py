# -*- coding: utf-8 -*-
"""形式签名三道门的纯函数单测（不依赖 Lean、不依赖网络）。

★ 用例刻意取自**与被测数据无关**的表达式：E25 的教训是「用例抄自被判词
  原文 ⇒ 单测全绿是循环论证」。这里只锁语义，不锁历史样本的判词。
★ 双向锁死：该放行的要放行、该拒的要拒，避免只测一个自由度。
"""
import pytest

from contracts import formal_sig_gate as G

SIG = "example (n : ℕ) (h : n = 3) : n + 1 = 4 := by sorry"


# ---------------------------------------------------------------- split_sig
def test_split_simple():
    got = G.split_sig(SIG)
    assert got == ("example (n : ℕ) (h : n = 3)", "n + 1 = 4")


def test_split_type_annotation_not_split():
    """非贪婪/平扫都会在 (x : ℝ) 处切开。"""
    got = G.split_sig("example (x : ℝ) : x + 1 > x := by sorry")
    assert got[0] == "example (x : ℝ)"
    assert got[1] == "x + 1 > x"


def test_split_forall_type_annotation_not_split():
    """从右往左找最后一个冒号会在 `∀ k : ℕ` 处切开。"""
    got = G.split_sig("example : ∀ k : ℕ, k = k := by sorry")
    assert got[1] == "∀ k : ℕ, k = k"


def test_split_no_tail_returns_none():
    assert G.split_sig("example : True") is None


# ------------------------------------------------------------ is_trivial_prop
@pytest.mark.parametrize("prop,reason", [
    ("True", "命题就是True"),
    ("(180 / Nat.gcd α 180) = (180 / Nat.gcd α 180)", "A=A重言式"),
    ("(2^k - 2^l : ℤ) ∈ (Set.univ : Set ℤ)", "属于Set.univ"),
    ("∃ (k : ℕ), k = 360 / Nat.gcd 360 (2 * θ)", "存在性直接取等"),
    ("(fun x : ℕ+ => x) (n + m) = n + m", "恒等函数"),
])
def test_e29_six_trivial_shapes_are_caught(prop, reason):
    assert G.is_trivial_prop(prop) == reason


@pytest.mark.parametrize("prop", [
    "n + 1 = 4",
    "False",                       # ★ E29：反证式，不是退化命题
    "∀ n : ℕ, n + 1 > n",
    "(fun y : ℕ => y + 1) 3 = 4",  # 恒等函数规则不能误伤
    "∃ k : ℕ, k^2 = 4",           # 存在性但不是「直接取等」
])
def test_nontrivial_prop_not_flagged(prop):
    assert G.is_trivial_prop(prop) == ""


def test_trivial_is_lower_bound_not_a_proof_of_nontriviality():
    """空串只表示「看不出」，调用方不得据此宣称非平凡。"""
    assert G.is_trivial_prop("some opaque predicate P x") == ""
    assert "保守" in G.__doc__ and "下界" in G.__doc__


# ------------------------------------------------------------ classify_stated
def test_statable_when_only_sorry_warning():
    """Lean 4 把 `declaration uses 'sorry'` 记为 warning，returncode 仍为 0。"""
    err = "warning: declaration uses 'sorry'\n"
    assert G.classify_stated(0, err) == ("STATABLE", "")


def test_statable_on_clean_zero_exit():
    assert G.classify_stated(0, "") == ("STATABLE", "")


def test_illegal_on_unknown_identifier():
    err = "t.lean:3:5: error: Unknown constant 'Φ'\n"
    assert G.classify_stated(1, err)[0] == "ILLEGAL"
    assert G.classify_stated(1, err)[1] == "未定义符号"


def test_illegal_kind_case_insensitive():
    err = "t.lean:1:1: error: unknown identifier 'rotate_cw'\n"
    assert G.classify_stated(1, err)[1] == "未定义符号"


def test_illegal_kind_syntax():
    err = "t.lean:2:9: error: unexpected token ','; expected term\n"
    assert G.classify_stated(1, err)[1] == "语法/括号"


def test_zero_exit_with_error_line_still_illegal():
    """rc=0 但出现 error 行 ⇒ 不认可陈述（防脏对照）。"""
    assert G.classify_stated(0, "error: unexpected token")[0] == "ILLEGAL"


def test_warning_line_with_word_error_is_not_fatal():
    err = "warning: this error-like message is only a warning\n"
    assert G.classify_stated(0, err)[0] == "STATABLE"


def test_timeout():
    assert G.classify_stated(1, "TIMEOUT")[0] == "TIMEOUT"


def test_nonzero_exit_without_error_line_is_illegal():
    assert G.classify_stated(1, "killed")[0] == "ILLEGAL"


# ----------------------------------------------------------- proof_credential
def test_proof_empty():
    assert G.proof_credential("")[0] == "EMPTY"


@pytest.mark.parametrize("code", [
    "example : 1 = 1 := by sorry",
    "example : 1 = 1 := by admit",
    "axiom bogus : False",
])
def test_proof_with_untrusted_construct_rejected(code):
    assert G.proof_credential(code)[0] == "SORRY"


def test_clean_proof_passes_credential():
    assert G.proof_credential(
        "example (n : ℕ) (h : n = 3) : n + 1 = 4 := by omega") == ("OK", "")


def test_signature_placeholder_must_be_stripped_before_check():
    """门 C 传的是拼接后的最终代码；签名占位不该残留。"""
    composed = SIG.replace(":= by sorry", ":= by omega")
    assert G.proof_credential(composed) == ("OK", "")


# ------------------------------------------------------------------- evaluate
def test_absent_signature_is_not_a_rejection():
    v = G.evaluate("")
    assert v["stage"] == "ABSENT" and not v["allowed"]
    assert "不是被拒" in v["reasons"][0]


def test_bad_shape_short_circuits_before_compile():
    v = G.evaluate("example : True")
    assert v["stage"] == "SHAPE" and not v["allowed"]


def test_trivial_short_circuits_before_compile():
    v = G.evaluate("example : True := by sorry", compile_result=None)
    assert v["stage"] == "NONTRIVIAL" and not v["allowed"]
    assert "True" in v["prop"]


def test_missing_compile_result_is_unverified_not_allowed():
    """★ E27 教训：静默放行会让分母塌掉。缺编译结果必须显式留痕。"""
    v = G.evaluate(SIG)
    assert v["stage"] == "UNVERIFIED" and not v["allowed"]


def test_illegal_prop_rejected_at_stated():
    v = G.evaluate(SIG, compile_result=(1, "error: Unknown constant 'Φ'"))
    assert v["stage"] == "STATED" and not v["allowed"]


def test_statable_but_no_proof_is_not_ready():
    v = G.evaluate(SIG, compile_result=(0, "warning: declaration uses 'sorry'"))
    assert v["stage"] == "NO_PROOF" and not v["allowed"]


def test_proof_with_sorry_rejected():
    v = G.evaluate(SIG, compile_result=(0, ""),
                   proof_code="example : True := by sorry")
    assert v["stage"] == "PROOF" and not v["allowed"]


def test_all_three_gates_pass():
    v = G.evaluate(SIG, compile_result=(0, ""),
                   proof_code="example (n : ℕ) (h : n = 3) : n + 1 = 4 := by omega")
    assert v["stage"] == "READY" and v["allowed"]
    assert v["prop"] == "n + 1 = 4"


def test_allowed_true_only_on_ready():
    assert not any(G.evaluate(SIG, compile_result=(rc, err))["allowed"]
                   for rc, err in [(0, ""), (1, "error: x"), (None, "")])


# ---------------------------------------------------------------------------
# E31 真判接线：判定 → 落盘字段 → tool_verdict → 闭合准入
# ★ 全部零配额、不需要 Lean：编译结果以 (rc, err) 注入。
# ---------------------------------------------------------------------------
PROOF_OK = "example (n : ℕ) (h : n = 3) : n + 1 = 4 := by omega"


def test_verdict_text_pass_only_on_ready():
    assert G.verdict_text(G.evaluate(SIG, (0, ""), PROOF_OK)) == "pass"
    txt = G.verdict_text(G.evaluate(SIG))
    assert txt != "pass" and "unknown" in txt and "UNVERIFIED" in txt


def test_gate_fields_shape_is_stable():
    f = G.gate_fields(G.evaluate(SIG))
    assert set(f) == {"sig_gate_allowed", "sig_gate_stage",
                      "sig_gate_reasons", "sig_gate_prop"}
    assert f["sig_gate_allowed"] is False and f["sig_gate_stage"] == "UNVERIFIED"


def test_closure_explicitly_rejects_gate_veto():
    """★ 工具说 pass 也不行：带 sorry 的证明能编译通过，必须靠显式字段挡住。"""
    from contracts.closure import CLOSURE_HARD, CLOSURE_OPEN, closure_of
    item = {"tool_ran": True, "tool_verdict": "pass",
            "sig_gate_allowed": False}
    assert closure_of(item)[0] == CLOSURE_OPEN
    assert closure_of(item)[1] == "sig_gate_rejected"


def test_closure_legacy_rows_unchanged():
    """历史产物没有 sig_gate_allowed ⇒ 旧判定逐字不变（归档回放结论不受影响）。"""
    from contracts.closure import CLOSURE_HARD, closure_of
    assert closure_of({"tool_ran": True, "tool_verdict": "pass"})[0] == CLOSURE_HARD
    assert closure_of({"tool_ran": True, "tool_verdict": "fail"})[0] != CLOSURE_HARD


def test_project_closed_drops_vetoed_items():
    from contracts.closure import project_closed
    rows = [
        {"id": 1, "tool_ran": True, "tool_verdict": "pass"},
        {"id": 2, "tool_ran": True, "tool_verdict": "pass",
         "sig_gate_allowed": False},
    ]
    assert [r["id"] for r in project_closed(rows)] == [1]


def test_live_wiring_end_to_end():
    """规划期预检 → 求解侧门 A/C 合成 → verdict 文本，一条完整链路。"""
    from agent.sub_goal_solver__lean import (
        _init_sig_gate, _commit_sig_gate, _verdict_text_of)
    sg = {"formal_sig": SIG, "tool": "lean"}
    _init_sig_gate(sg)
    assert sg["sig_gate_allowed"] is False           # 规划期尚未验
    assert _verdict_text_of(sg) != "pass"

    _commit_sig_gate(sg, SIG, (0, ""), PROOF_OK)     # 门 A 过 + 门 C 过
    assert sg["sig_gate_allowed"] is True
    assert sg["sig_gate_stage"] == "READY"
    assert _verdict_text_of(sg) == "pass"


def test_live_wiring_sorry_never_becomes_pass():
    from agent.sub_goal_solver__lean import (
        _init_sig_gate, _commit_sig_gate, _verdict_text_of)
    sg = {"formal_sig": SIG, "tool": "lean"}
    _init_sig_gate(sg)
    _commit_sig_gate(sg, SIG, (0, ""), "example : True := by sorry")
    assert sg["sig_gate_allowed"] is False
    assert sg["sig_gate_stage"] == "PROOF"
    assert _verdict_text_of(sg) != "pass"


def test_live_wiring_missing_compile_never_becomes_pass():
    """Lean 不可用 ⇒ compile_result=None ⇒ 没验 ≠ 验过。"""
    from agent.sub_goal_solver__lean import (
        _init_sig_gate, _commit_sig_gate, _verdict_text_of)
    sg = {"formal_sig": SIG, "tool": "lean"}
    _init_sig_gate(sg)
    _commit_sig_gate(sg, SIG, None, PROOF_OK)
    assert sg["sig_gate_allowed"] is False
    assert sg["sig_gate_stage"] == "UNVERIFIED"


def test_no_formal_sig_does_not_arm_the_gate():
    """无签名走「求解侧自写整段 Lean」旧路径 ⇒ 不误杀原有工具级闭合。"""
    from agent.sub_goal_solver__lean import _init_sig_gate
    sg = {"formal_sig": "", "tool": "lean"}
    _init_sig_gate(sg)
    assert "sig_gate_allowed" not in sg


def test_compile_stated_unavailable_returns_none():
    """编译器不可用必须返回 None（→ UNVERIFIED），不得伪造成功。"""
    from agent.sub_goal_solver__lean import _compile_stated

    class _BrokenBridge:
        def _mathlib_ready(self):
            raise RuntimeError("no lean")

        def _compile(self, *a, **kw):
            raise RuntimeError("no lean")

    assert _compile_stated(_BrokenBridge(), "/tmp", SIG, "x.lean") is None
