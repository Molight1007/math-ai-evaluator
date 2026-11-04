# -*- coding: utf-8 -*-
"""`replay_lean_close` 的纯函数单测（不调 Lean，可在任何机器跑）。

★ 用例刻意**不取自被修数据**，只锁语义：
  1. 切分必须找**括号深度为 0 的第一个冒号**
  2. `unsolved goals` 是「合法但没证出」，不是「命题写不出来」
  3. 退化命题（True / A=A / ∈ Set.univ / ∃x,x=...）必须单列，不能算 PASS
  4. `prop == False` 是反证式，不是「假命题」
  5. 五分类互斥，`LEGAL` 绝不能被算成 `PASS`

本轮补这几组是因为第一版四分类的 6 条 PASS 与 8 条 REFUTED 抽验后
**全部被推翻**；单测原本没锁这两个语义，等于没测。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import replay_lean_close as R


# --- 切分 ---

def test_split_sig_type_annotation_not_split():
    head, prop = R.split_sig("example (x : ℝ) : x ^ 2 ≥ 0 := by sorry")
    assert head == "example (x : ℝ)"
    assert prop == "x ^ 2 ≥ 0"


def test_split_sig_multiple_annotations():
    head, prop = R.split_sig(
        "example (a b : ℝ) (h : a = b) : a - b = 0 := by sorry")
    assert head == "example (a b : ℝ) (h : a = b)"
    assert prop == "a - b = 0"


def test_split_sig_nested_colon():
    """`∀ k : ℕ, ...` 里冒号更靠右，从右往左找会被切开。"""
    head, prop = R.split_sig("example : ∀ k : ℕ, k + 0 = k := by sorry")
    assert head == "example"
    assert prop == "∀ k : ℕ, k + 0 = k"


def test_split_sig_rejects_non_sorry():
    assert R.split_sig("example : True := by trivial") is None


def test_split_sig_admit():
    head, prop = R.split_sig("example : 1 = 1 := by admit")
    assert (head, prop) == ("example", "1 = 1")


# --- 退化命题 ---

def test_trivial_true():
    assert R.is_trivial_prop("True") == "命题就是True"


def test_trivial_reflexive_eq():
    assert R.is_trivial_prop("(180 / Nat.gcd α 180) = (180 / Nat.gcd α 180)")


def test_trivial_set_univ():
    assert R.is_trivial_prop("(2^k - 2^l : ℤ) ∈ (Set.univ : Set ℤ)")


def test_trivial_exists_witness():
    assert R.is_trivial_prop("∃ (k : ℕ), k = 360 / Nat.gcd 360 (2 * θ)")


def test_trivial_identity_function():
    assert R.is_trivial_prop(
        "∀ n m : ℕ+, (fun x : ℕ+ => x) ((fun x : ℕ+ => x) n + (fun x : ℕ+ => x) m) = n + m"
    ) == "恒等函数"


def test_nontrivial_lambda_not_flagged():
    """`(fun x => x+1)` 不是恒等函数，不该被误标。"""
    assert R.is_trivial_prop("∀ x : ℕ, (fun y : ℕ => y + 1) x = x + 1") == ""


def test_nontrivial_prop_not_flagged():
    """保守判据：不认识的一律不标 TRIVIAL，留给人工抽验。"""
    assert R.is_trivial_prop("∀ x : ℝ, x ^ 2 ≥ 0") == ""


# --- 编译结果分类 ---

def test_classify_pass():
    assert R.classify("", "", 0)[0] == "PASS"


def test_classify_timeout_is_not_illegal():
    assert R.classify("TIMEOUT", "TIMEOUT", 1)[0] == "TIMEOUT"


def test_classify_unsolved_is_legal_not_illegal():
    assert R.classify("error: unsolved goals", "error: unsolved goals\n⊢ x = y", 1)[0] == "LEGAL"


def test_classify_fatal_error_wins_over_unsolved():
    """完整错误文本里同时有 unsolved goals 和致命错 ⇒ 必须归 ILLEGAL。"""
    full = "error: unsolved goals\nerror: unknown identifier 'Φ'"
    assert R.classify("error: unsolved goals", full, 1)[0] == "ILLEGAL"


def test_classify_application_mismatch_not_legal():
    """★ 回归：Lean 报 Application type mismatch 后仍会留 unsolved goals，
    第一版因此误放 12 条非法命题为 LEGAL（抽验 12/12 全错）。"""
    full = ("error: Application type mismatch: The argument\n"
            "error: unsolved goals\n⊢ True")
    assert R.classify("error: Application type mismatch", full, 1)[0] == "ILLEGAL"


def test_classify_invalid_field_not_legal():
    full = "error(lean.invalidField): Invalid field notation\nerror: unsolved goals"
    assert R.classify("error: Invalid field notation", full, 1) == ("ILLEGAL", "字段/应用不存在")


def test_classify_unknown_constant_case_insensitive():
    """Lean 写 `Unknown constant`（大写 U），旧正则小写匹配不到。"""
    full = "error(lean.unknownIdentifier): Unknown constant `Nat.abs`"
    assert R.classify(full, full, 1) == ("ILLEGAL", "未定义符号")


def test_classify_only_unsolved_is_legal():
    """真正只有 unsolved goals 时才判 LEGAL。"""
    full = "error: unsolved goals\n⊢ x = y"
    assert R.classify("error: unsolved goals", full, 1) == ("LEGAL", "")


def test_classify_illegal_uses_full_error():
    """第一行是 Function expected，但完整文本里有 unknown identifier ⇒ 归未定义符号。"""
    full = "error: Function expected at\nerror: unknown identifier 'rotate_cw'"
    assert R.classify("error: Function expected at", full, 1) == ("ILLEGAL", "未定义符号")


def test_classify_illegal_undefined():
    assert R.classify("error: unknown identifier 'Φ'", "error: unknown identifier 'Φ'", 1) == (
        "ILLEGAL", "未定义符号")


def test_classify_illegal_syntax():
    assert R.classify("error: unexpected token 'in'", "error: unexpected token 'in'", 1) == (
        "ILLEGAL", "语法/括号")


def test_classify_illegal_instance():
    assert R.classify("error: failed to synthesize", "error: failed to synthesize", 1) == (
        "ILLEGAL", "类型实例缺失")


def test_illegal_kind_unknown_falls_back():
    assert R.illegal_kind("error: maximum recursion depth has been reached") == "其它"


# --- 反证式：judge_one 不该把它叫「假命题」 ---
# 需要真编译才能测，这里锁一个可单测的等价不变量：
# 「prop == False」不能由 classify 判成 ILLEGAL/PASS，也不会出现在 TRIVIAL 规则里。

def test_false_prop_is_not_trivial():
    assert R.is_trivial_prop("False") == ""


def test_false_prop_is_not_a_false_conclusion():
    """文档级锁：`False` 命题的处置必须是 CONTRADICTION 常量，不许改名成 REFUTED。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "replay_lean_close.py"), encoding="utf-8").read()
    assert 'cat="CONTRADICTION"' in src
    assert '"REFUTED"' not in src and "cat=\"REFUTED\"" not in src


def test_categories_are_distinct():
    cats = {R.classify("", "", 0)[0],
            R.classify("error: unsolved goals", "error: unsolved goals", 1)[0],
            R.classify("error: unexpected token ','", "error: unexpected token ','", 1)[0],
            R.classify("TIMEOUT", "TIMEOUT", 1)[0]}
    assert cats == {"PASS", "LEGAL", "ILLEGAL", "TIMEOUT"}
