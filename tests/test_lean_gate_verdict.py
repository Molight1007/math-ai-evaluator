# -*- coding: utf-8 -*-
"""LeanGate 判定分级单测 —— 2026-10-22。

核心契约：``proof_invalid`` 不再一律淘汰，只有失败原因是 ``refuted``
（Lean 明确输出 `⊢ False`）才判「答案错」；``unproved`` / ``translation``
/ ``env`` 改判 ``unknown`` 并保留候选（degraded=lean_<kind> 留痕）。
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.lean_local.lean_gate import LeanGate  # noqa: E402


class _Cand:
    id = 1
    answer = "1"
    answer_norm = "1"


def _report(verdict="proof_invalid", **attrs):
    r = SimpleNamespace(verdict=verdict, findings=[], suggestion="")
    for k, v in attrs.items():
        setattr(r, k, v)
    return r


def _apply(report):
    gate = LeanGate(client=None, config=SimpleNamespace())
    entry, kept, fbs = {}, [], []
    streak = gate._apply_verdict(
        ctx=None, cand=_Cand(), report=report, entry=entry, used_names=[],
        domain="", is_proof=True, kept=kept, feedbacks=fbs, _unknown_streak=0)
    return entry, kept, fbs, streak


def test_proof_invalid_refuted_is_rejected():
    """被证伪 ⇒ 淘汰（不进 kept），verdict 保持 proof_invalid。"""
    entry, kept, fbs, _ = _apply(_report(failure_kind="refuted"))
    assert kept == []
    assert entry["verdict"] == "proof_invalid"
    assert entry["failure_kind"] == "refuted"
    assert fbs   # 有反馈注入


def test_proof_invalid_unproved_is_kept_as_unknown():
    """没证出来 ⇒ 不淘汰，改判 unknown，degraded 留痕。"""
    entry, kept, _fbs, streak = _apply(_report(failure_kind="unproved"))
    assert [c.id for c in kept] == [1]
    assert entry["verdict"] == "unknown"
    assert entry["degraded"] == "lean_unproved"
    assert streak == 1


def test_proof_invalid_env_and_translation_kept():
    for kind in ("env", "translation"):
        entry, kept, _f, _s = _apply(_report(failure_kind=kind))
        assert [c.id for c in kept] == [1], kind
        assert entry["degraded"] == "lean_" + kind


def test_proof_invalid_without_failure_kind_keeps_old_behavior():
    """没有分类信息（旧 report / 老数据）⇒ 按旧语义淘汰，不擅自放宽。"""
    entry, kept, _f, _s = _apply(_report())
    assert kept == []
    assert entry["verdict"] == "proof_invalid"


def test_switch_off_restores_old_behavior(monkeypatch):
    """lean_failure_kind_split=0 ⇒ 一律淘汰（A/B 回退路径）。"""
    import tools.lean_local.lean_gate as lg
    monkeypatch.setattr(lg, "_sw_bool", lambda name: False)
    entry, kept, _f, _s = _apply(_report(failure_kind="unproved"))
    assert kept == []
    assert entry["verdict"] == "proof_invalid"
