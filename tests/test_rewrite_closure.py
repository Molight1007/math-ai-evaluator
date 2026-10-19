# -*- coding: utf-8 -*-
"""检错闭环（4.6 重写触发扩展）回归 —— 2026-10-19。"""
import os, sys
from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.rewrite_gate import _should_rewrite, _best_confidence  # noqa: E402


def _ctx(cands=True, vote_correct=0, vote_total=4, ad_rej=0, mc_fail=0):
    return SimpleNamespace(
        candidates=[object()] if cands else [],
        vote_gate={"best_cluster": {"vote_correct": vote_correct, "vote_total": vote_total}},
        adversarial_gate={"n_rejected": ad_rej},
        math_check={"n_fail": mc_fail},
    )


def _cfg():
    return SimpleNamespace(config=SimpleNamespace(rewrite_conf_threshold=0.0))


def test_empty_pool_always_rewrites():
    assert _should_rewrite(_cfg(), _ctx(cands=False)) is True


def test_low_conf_with_reject_rewrites():
    # 有淘汰证据 + 置信度 0 ⇒ 重写（不放行错答案）
    assert _should_rewrite(_cfg(), _ctx(vote_correct=0, vote_total=4, ad_rej=3)) is True
    assert _should_rewrite(_cfg(), _ctx(vote_correct=0, vote_total=4, mc_fail=5)) is True


def test_low_conf_without_reject_does_not_rewrite():
    # 置信度 0 但无淘汰证据 ⇒ 不重写（避免每题都重写）
    assert _should_rewrite(_cfg(), _ctx(vote_correct=0, vote_total=4, ad_rej=0, mc_fail=0)) is False


def test_conf_above_threshold_does_not_rewrite():
    assert _should_rewrite(_cfg(), _ctx(vote_correct=2, vote_total=4, ad_rej=3)) is False


def test_no_vote_info_does_not_rewrite():
    c = _ctx(); c.vote_gate = {}
    assert _should_rewrite(_cfg(), c) is False


def test_best_confidence_none_when_missing():
    assert _best_confidence(SimpleNamespace(vote_gate={})) is None
    assert _best_confidence(_ctx(vote_correct=2, vote_total=4)) == 0.5
