# -*- coding: utf-8 -*-
"""工具⑤ SMT(Z3) 命题验证回归（2026-10-18）。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.agent_toolkit.smt_check import verify_smt  # noqa: E402


def test_sat_counterexample():
    r = verify_smt("(declare-const x Int) (assert (> x 1))")
    assert r["verdict"] == "sat"


def test_unsat_valid():
    r = verify_smt("(declare-const x Int) (assert (and (> x 1) (< x 0)))")
    assert r["verdict"] == "unsat"


def test_implication_counterexample():
    # 命题「x>3 ⇒ x>5」有反例（x=4）
    r = verify_smt("(declare-const x Int) (assert (not (=> (> x 3) (> x 5))))")
    assert r["verdict"] == "sat"


def test_implication_valid():
    # 命题「x>3 ⇒ x>1」恒真 ⇒ unsat
    r = verify_smt("(declare-const x Int) (assert (not (=> (> x 3) (> x 1))))")
    assert r["verdict"] == "unsat"


def test_empty_and_garbage():
    assert verify_smt("")["verdict"] == "unknown"
    assert verify_smt("这不是 SMT")["verdict"] in ("error", "unknown")
