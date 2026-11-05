# -*- coding: utf-8 -*-
"""E35：固定蓝图回放台 / 统一审计台的构造用例（决定性反例优先）。

锁死三件事
----------
  1. 单变量：只有 `tool=lean` + 反馈非空 + 无「未真跑」标记时才走闭环；
     sympy/numeric/llm 的失败一律不重解，两臂逐字一致。
  2. 口径唯一：失败判据复用契约层词表，不准回放床自写一份
     （旧散落脚本用 startswith("fail") 漏判 "unknown: ... ILLEGAL"）。
  3. 归档缺口：合成反馈、假设标记都要显式可辨；日志计数 0 不等于没失败。
"""
import json

import pytest

import replay_fixed_blueprint as FBP
import replay_run_audit as RA
from agent import subgoal_collab as COLLAB
from contracts.closure import FAIL_WORDS, CLOSURE_OPEN


def _row(tool="lean", **kw):
    r = {"id": 7, "tool": tool, "tool_ran": True,
         "tool_verdict": "fail: type mismatch",
         "objective_verdict": "correct", "has_derivation": True,
         "result": "证明正文 " * 12, "title": "子目标"}
    r.update(kw)
    return r


# ---------------------------------------------------------------- 1 单变量
def test_reclose_only_triggers_for_lean_real_failure():
    rec = FBP.run_pair(_row(), FBP.SYNTHETIC_FB, False)
    assert rec["reclose"]["triggered"] is True
    assert rec["reclose"]["n_resolve"] == 1
    assert rec["baseline"]["n_resolve"] == 0
    assert rec["unexplained"] is False


@pytest.mark.parametrize("tool", ["sympy", "numeric", "llm", ""])
def test_non_lean_never_resolves_and_arms_stay_identical(tool):
    rec = FBP.run_pair(_row(tool=tool), FBP.SYNTHETIC_FB, False)
    assert rec["reclose"]["triggered"] is False
    assert rec["reclose"]["n_resolve"] == 0
    assert rec["baseline"]["sg"] == rec["reclose"]["sg"]
    assert rec["unexplained"] is False


def test_not_run_reason_blocks_reclose():
    rec = FBP.run_pair(_row(tool_not_run_reason="compile_cap"),
                       FBP.SYNTHETIC_FB, False)
    assert rec["reclose"]["triggered"] is False
    assert rec["reclose"]["n_resolve"] == 0


def test_empty_feedback_blocks_reclose():
    assert FBP.run_pair(_row(), "", False)["reclose"]["triggered"] is False


def test_short_rewrite_is_rejected_by_production_function():
    s = FBP.RecordingSolver()
    s._solve_subgoal = lambda *a, **k: "too short"
    out = COLLAB._maybe_lean_reclose(
        s, None, _row(), FBP.SYNTHETIC_FB, "", "", "子目标")
    assert out == ""


def test_assume_not_run_applies_to_both_arms_no_fake_diff():
    """2026-11-05 实测过的缺陷：假设只加一臂会凭空造 16 条伪差异。"""
    rec = FBP.run_pair(_row(), FBP.SYNTHETIC_FB, True)
    assert rec["reclose"]["triggered"] is False
    assert rec["unexplained"] is False
    assert (rec["baseline"]["sg"]["tool_not_run_reason"]
            == rec["reclose"]["sg"]["tool_not_run_reason"])


def test_gate_veto_blocks_counterfactual_hard():
    """E32 决定性反例：工具说 pass + 闸门否决 ⇒ OPEN，闭环也翻不了案。"""
    r = _row(sig_gate_allowed=False, sig_gate_stage="STATED",
             tool_verdict="pass")
    rec = FBP.run_pair(r, FBP.SYNTHETIC_FB, False)
    assert rec["closure_observed"] == CLOSURE_OPEN
    assert rec["reclose"]["closure"] == CLOSURE_OPEN


def test_run_pair_does_not_mutate_input():
    r = _row()
    before = json.dumps(r, ensure_ascii=False, sort_keys=True)
    FBP.run_pair(r, FBP.SYNTHETIC_FB, False)
    FBP.run_pair(r, FBP.SYNTHETIC_FB, True)
    assert json.dumps(r, ensure_ascii=False, sort_keys=True) == before


# ---------------------------------------------------------------- 2 口径唯一
def test_fail_words_are_the_contract_ones():
    assert tuple(FBP.FAIL_WORDS) == tuple(FAIL_WORDS)
    assert tuple(RA.FAIL_WORDS) == tuple(FAIL_WORDS)


def test_unknown_illegal_is_counted_as_fail():
    """旧脚本 startswith("fail") 漏判这一行，实测归档里确有此形态。"""
    tv = "unknown: sig_gate=STATED 命题不可陈述：ILLEGAL"
    assert FBP.is_fail_verdict(tv) is True
    assert FBP.is_fail_verdict("pass") is False


def test_run_audit_uses_contract_words(tmp_path):
    qd = tmp_path / "qtest"
    qd.mkdir()
    (qd / "04_subgoal_results.jsonl").write_text(
        json.dumps({"id": 1, "tool": "lean", "tool_ran": True,
                    "tool_verdict": "unknown: ILLEGAL",
                    "objective_verdict": "correct",
                    "has_derivation": True}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    st = RA.audit_qdir(str(qd))
    assert st["verdict_fail"] == 1
    assert st["verdict_pass"] == 0
    assert st["closure"] == {"SOFT_CLOSED": 1}


# ---------------------------------------------------------------- 3 归档缺口
def test_synthetic_values_are_explicitly_marked():
    assert "SYNTHETIC" in FBP.SYNTHETIC_FB
    assert "SYNTHETIC" in FBP.SYNTHETIC_REWRITE
    assert len(FBP.SYNTHETIC_REWRITE) > 40


def test_log_zero_is_not_evidence_of_no_failure(tmp_path):
    p = tmp_path / "empty.log"
    p.write_text("no marks here\n", encoding="utf-8")
    info = FBP.log_verify_marks(str(p))
    assert info["n"] == 0
    assert "不等于没有失败" in info["note"]
    assert "未提供日志" in FBP.log_verify_marks("/nonexistent/path")["note"]


def test_audit_part_no_unexplained_diff(tmp_path):
    run = tmp_path / "run"
    for qid in ("qa", "qb"):
        qd = run / qid
        qd.mkdir(parents=True)
        rows = [_row(id=1, tool="sympy"), _row(id=2, tool="lean")]
        (qd / "04_subgoal_results.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
            encoding="utf-8")
    part = FBP.audit_part([str(run / "qa"), str(run / "qb")],
                          FBP.SYNTHETIC_FB, False)
    assert part["n_rows"] == 4
    assert part["n_triggered"] == 2
    assert part["unexplained"] == []


def test_holdout_split_keeps_all_qdirs(tmp_path):
    run = tmp_path / "run"
    dirs = []
    for i in range(5):
        qd = run / ("q%d" % i)
        qd.mkdir(parents=True)
        (qd / "04").write_text("x", encoding="utf-8")
        dirs.append(str(qd))
    dev, hold = FBP.split_holdout(dirs)
    assert len(dev) + len(hold) == 5
    assert set(dev + hold) == set(dirs)
    assert len(hold) >= 1
