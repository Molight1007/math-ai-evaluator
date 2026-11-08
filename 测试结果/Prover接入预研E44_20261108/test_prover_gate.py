# -*- coding: utf-8 -*-
"""E44 · prover_gate 的离线单测（不连模型、不连服务器）"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prover_gate as G  # noqa: E402

SIG = ("example (x : ℝ) (h : x^2 = 2) : x > 0 := by sorry")
FULL_REPLY = """### Proof plan
Use `nlinarith` after squaring.

```lean4
import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat

theorem probe_q01 (x : ℝ) (h : x^2 = 2) : x > 0 := by
  nlinarith [sq_pos_of_ne_zero (show x ≠ 0 by nlinarith)]
```
"""


def test_formal_statement_rewrites_example_only():
    s = G.to_formal_statement(SIG, "probe_q01")
    assert s.startswith("import Mathlib\nimport Aesop")
    assert "theorem probe_q01 (x : ℝ)" in s
    assert "example" not in s
    assert "x^2 = 2) : x > 0" in s       # 命题正文一字未改


def test_formal_statement_rejects_bad_name():
    with pytest.raises(ValueError):
        G.to_formal_statement(SIG, "q-01")
    with pytest.raises(ValueError):
        G.to_formal_statement("not a declaration", "ok")


def test_prompt_matches_official_template():
    p = G.build_prompt(G.to_formal_statement(SIG, "probe_q01"))
    # 官方原文是 ```lean4 {}``` —— 围栏后直接接 statement，中间没有换行
    assert p.startswith(
        "Complete the following Lean 4 code:\n```lean4 import Mathlib")
    assert "Before producing the Lean 4 code" in p
    assert "detailed proof plan" in p
    assert "import Aesop" in p and "theorem probe_q01" in p


def test_extract_lean_block_skips_plan_prose():
    b = G.extract_lean_block(FULL_REPLY)
    assert b.startswith("import Mathlib")
    assert "Proof plan" not in b
    assert "nlinarith" in b


def test_extract_lean_block_missing():
    assert G.extract_lean_block("just prose, no code") == ""
    assert G.extract_lean_block("") == ""


def test_adapt_to_server_import_and_heartbeats():
    b = G.extract_lean_block(FULL_REPLY)
    c = G.adapt_to_server(b)
    assert "import Mathlib.Tactic" in c
    assert "import Aesop" not in c
    assert "import Mathlib\n" not in c
    assert "set_option maxHeartbeats 200000" in c
    assert "maxHeartbeats 0" not in c


def test_adapt_adds_import_when_model_gave_body_only():
    c = G.adapt_to_server("theorem t : True := by trivial")
    assert c.startswith("import Mathlib.Tactic")


def test_has_sorry():
    assert G.has_sorry("theorem t : True := by sorry") is True
    assert G.has_sorry("theorem t : True := by trivial") is False


def test_build_verify_unit_ok():
    u = G.build_verify_unit(SIG, FULL_REPLY, "probe_q01")
    assert u["precheck"] == "OK"
    assert "import Mathlib.Tactic" in u["code"]


@pytest.mark.parametrize("reply,expect", [
    ("no code here", "NO_LEAN_BLOCK"),
    ("```lean4\nimport Mathlib\n```", "NO_PROOF_BODY"),
    ("```lean4\ntheorem t : True := by sorry\n```", "SORRY_IN_CODE"),
])
def test_build_verify_unit_precheck(reply, expect):
    assert G.build_verify_unit(SIG, reply, "probe_q01")["precheck"] == expect


def test_units_shape_is_stable():
    u = G.build_verify_unit(SIG, FULL_REPLY, "probe_q01")
    assert set(u) == {"name", "sig", "code", "precheck", "reply_len"}
    json.dumps(u, ensure_ascii=False)     # 可落盘
