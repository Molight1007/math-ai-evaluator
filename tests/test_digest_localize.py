# -*- coding: utf-8 -*-
"""L2 机械摘要（digest）与环节定位（localize）测试（2026-10-27）。

这两个工具的价值全在**判据准不准**：
  · digest 的 `suspect_stage` 是机械猜测，猜反了会把人引到错的环节；
  · localize 的档位标错（把 B 档提示词标成 A 档可机改）会让人以为机器能改，
    实际提案器碰不到 —— 这正是「假可编辑面」。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tools.digest as dg  # noqa: E402
import tools.localize as lc  # noqa: E402


def _row(**kw):
    d = {"id": "q1", "domain": "组合数学", "correct": False, "error_class": "value_wrong",
         "elapsed_sec": 100.0, "gold": "42",
         "candidates": [{"answer": "\\boxed{41}"}, {"answer": "\\boxed{41}"}],
         "diag": {"question_type": "解答题", "tier": "deep",
                  "n_candidates": 2, "stage_timers": {"3_solve": 50.0, "4_verify": 20.0}}}
    d.update(kw)
    return d


# ---------------------------------------------------------------- digest
def test_01_strip_boxed():
    assert dg._norm_answer("\\boxed{2026}") == "2026"
    assert dg._norm_answer(" $ 3.5 ") == "3.5"


def test_02_empty_pool_points_to_solve():
    r = _row(candidates=[], diag={"n_candidates": 0})
    out = dg.digest_one(r)
    assert out["suspect_stage"] == "3_solve"


def test_03_gold_missing_points_to_solve():
    r = _row(candidates=[{"answer": "41"}, {"answer": "43"}])
    out = dg.digest_one(r)
    assert out["pool"]["gold_in_pool"] is False
    assert out["suspect_stage"] == "3_solve"


def test_04_lean_invalid_points_to_lean_gate():
    r = _row(candidates=[{"answer": "42"}],
             diag={"lean_gate": [{"verdict": "answer_invalid"}, {"verdict": "answer_valid"}]})
    out = dg.digest_one(r)
    assert out["gates"]["lean"]["invalid"] == 1
    assert out["suspect_stage"] == "4.3_lean_check"


def test_05_zero_vote_points_to_vote():
    r = _row(candidates=[{"answer": "42"}],
             diag={"pick_diag": {"branch": "zero_vote_fallback_direct"}})
    out = dg.digest_one(r)
    assert out["suspect_stage"] == "4.5_vote"


def test_06_truncation_is_announced():
    long_answers = [{"answer": "x" * 200} for _ in range(60)]
    r = _row(candidates=long_answers)
    out = dg.digest_one(r, max_chars=200)
    assert out["truncated"] is True and "已截断" in out["text"]


def test_07_text_has_key_lines():
    out = dg.digest_one(_row())
    for kw in ("候选池", "票型", "疑点"):
        assert kw in out["text"]


def test_08_cli_writes_jsonl(tmp_path):
    p = tmp_path / "res.jsonl"
    p.write_text(json.dumps(_row()) + "\n", encoding="utf-8")
    out = tmp_path / "d.jsonl"
    rc = dg.main(["--result", str(p), "--out", str(out)])
    assert rc == 0
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["qid"] == "q1" and row["schema"] == "digest/1"


def test_09_analyze_counts_suspects_and_pool_miss():
    ds = [dg.digest_one(_row(id="a")),
          dg.digest_one(_row(id="b", candidates=[{"answer": "42"}],
                             gold="42", correct=True)),
          dg.digest_one(_row(id="c", candidates=[], diag={"n_candidates": 0}))]
    a = dg.analyze(ds)
    assert a["n"] == 3 and a["n_wrong"] == 2
    assert dict(a["suspect_stage_dist"])["3_solve"] == 2
    # a（gold 42 但池里是 41）与 c（池空）都算「gold 没进池」
    assert a["gold_missing_from_pool"] == 2
    assert a["method"] == "mechanical", "必须标明是机械汇总，不能冒充 LLM 分析"
    assert "疑点环节" in dg.render_analysis(a)


def test_10_analyze_empty_is_safe():
    assert dg.analyze([])["n"] == 0
    assert "没有摘要" in dg.render_analysis(dg.analyze([]))


# ---------------------------------------------------------------- localize
def test_10_unknown_stage_raises():
    with pytest.raises(KeyError):
        lc.locate("9.9")


def test_11_a_tier_is_machine_editable():
    d = lc.locate("4.1")
    assert d["stage"].startswith("4.1")
    a_rows = [r for r in d["config"] if r["tier"] == "A"]
    assert a_rows and all(r["editable"] for r in a_rows)
    # A 档必须是 params.json a 段里的真键
    doc = lc._params()
    assert all(r["key"] in doc["a"] for r in a_rows)


def test_12_prompts_are_b_tier_only():
    d = lc.locate("4.1")
    assert d["prompts"], "4.1 应该扫到提示词"
    assert all(p["tier"] == "B" for p in d["prompts"])
    assert any(str(p["eu"]).startswith("prompt.self_audit") for p in d["prompts"])


def test_13_thin_shell_expands_delegates():
    """2.7 是薄壳（57 行），必须把下挂的 17 个模块列出来，否则会让人以为只有 1 个参数。"""
    d = lc.locate("2.7")
    assert d["counts"]["delegate_files"] >= 5
    assert d["counts"]["delegate_A"] >= 3


def test_14_observability_two_paths():
    d = lc.locate("4.1")
    # 4.1 不直接写 diag，而是 self.record(ctx, "self_audit", ...) → diag_export 汇总
    assert "self_audit" in d["trace_steps"]


def test_15_render_has_all_sections():
    md = lc.render(lc.locate("4.1"))
    for kw in ("① 控制流参数", "② 提示词", "③ 工具", "⑤ 上下文", "可观测"):
        assert kw in md
