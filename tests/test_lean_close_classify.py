# -*- coding: utf-8 -*-
"""`replay_lean_close` 的纯函数单测（不调 Lean，可在任何机器跑）。

★ 用例刻意**不取自被修数据**，只锁三种语义：
  1. 切分必须从右往左找冒号（否则 `example (x : ℝ) : P` 被切开）
  2. `unsolved goals` 是「合法但没证出」，不是「命题写不出来」
  3. 四分类必须分开，`LEGAL` 绝不能被算成 `PASS`
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import replay_lean_close as R


def test_split_sig_type_annotation_not_split():
    """类型标注里的冒号不能被当成分隔符。"""
    head, prop = R.split_sig("example (x : ℝ) : x ^ 2 ≥ 0 := by sorry")
    assert head == "example (x : ℝ)"
    assert prop == "x ^ 2 ≥ 0"


def test_split_sig_multiple_annotations():
    head, prop = R.split_sig(
        "example (a b : ℝ) (h : a = b) : a - b = 0 := by sorry")
    assert head == "example (a b : ℝ) (h : a = b)"
    assert prop == "a - b = 0"


def test_split_sig_nested_colon():
    """`∀ k : ℕ, ...` 里的冒号也不能被当分隔符。"""
    head, prop = R.split_sig("example : ∀ k : ℕ, k + 0 = k := by sorry")
    assert head == "example"
    assert prop == "∀ k : ℕ, k + 0 = k"


def test_split_sig_rejects_non_sorry():
    assert R.split_sig("example : True := by trivial") is None


def test_split_sig_admit():
    """admit 与 sorry 同义，都必须认。"""
    head, prop = R.split_sig("example : 1 = 1 := by admit")
    assert (head, prop) == ("example", "1 = 1")


def test_classify_pass():
    assert R.classify("", 0)[0] == "PASS"


def test_classify_unsolved_is_legal_not_illegal():
    """核心语义：证不出来 ≠ 命题写不出来。"""
    cat, kind = R.classify("error: unsolved goals\n⊢ x = y", 1)
    assert cat == "LEGAL"
    assert kind == ""


def test_classify_illegal_undefined():
    cat, kind = R.classify("error: unknown identifier 'Φ'", 1)
    assert cat == "ILLEGAL"
    assert kind == "未定义符号"


def test_classify_illegal_syntax():
    cat, kind = R.classify("error: unexpected token 'in'; expected ','", 1)
    assert (cat, kind) == ("ILLEGAL", "语法/括号")


def test_classify_illegal_instance():
    cat, kind = R.classify("error: failed to synthesize instance of type Abs ℤ", 1)
    assert (cat, kind) == ("ILLEGAL", "类型实例缺失")


def test_illegal_kind_unknown_falls_back():
    assert R.illegal_kind("error: maximum recursion depth has been reached") == "其它"


def test_four_categories_are_distinct():
    """四分类互斥且无遗漏 —— 防止有人把 LEGAL 并进 PASS 报数。"""
    cats = {R.classify("", 0)[0],
            R.classify("error: unsolved goals", 1)[0],
            R.classify("error: unexpected token ','", 1)[0]}
    assert cats == {"PASS", "LEGAL", "ILLEGAL"}
    assert "REFUTED" not in cats  # REFUTED 需要反证编译，单条字符串判不出来
