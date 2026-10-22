# -*- coding: utf-8 -*-
"""证据落地校验（agent/evidence_grounding.py）单测 —— 2026-10-22。

覆盖：引文核对（整段/分段/太短/编造）、错误位置语义（空/步骤号/原文），
以及 4.2 机检证书的「题面依据」过滤（`AnswerFalsifier._drop_ungrounded`）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.evidence_grounding import (  # noqa: E402
    check_location, check_quote, is_step_ref, norm_text)

SRC = "由 n^2+1=(n+1)(n-1)+2 可得 n+1 必须整除 2，因此 n 只能取 1。"


# ------------------------------------------------------------ 引文核对
def test_exact_quote_passes():
    ok, ratio, miss = check_quote("n+1 必须整除 2", SRC)
    assert ok is True and ratio == 1.0 and miss == []


def test_quote_with_whitespace_and_punct_passes():
    # 空白/全角标点被归一化，不影响核对
    ok, _r, _m = check_quote("n+1   必须整除 2，因此", SRC)
    assert ok is True


def test_elided_quote_passes_by_segments():
    # 省略中间部分（模型常见），分段命中率达标即算摘录
    ok, ratio, _m = check_quote("由 n^2+1=(n+1)(n-1)+2 … 因此 n 只能取 1", SRC)
    assert ok is True and ratio >= 0.6


def test_fabricated_quote_fails():
    ok, _r, miss = check_quote("原文根本没有出现的这一句推导", SRC)
    assert ok is False and miss


def test_too_short_quote_is_undecidable():
    # 太短无法判定（返回 None），调用方按「证据不成立」处理
    ok, _r, _m = check_quote("n=1", SRC)
    assert ok is None


def test_empty_source_fails():
    ok, _r, _m = check_quote("n+1 必须整除 2", "")
    assert ok is False


# ------------------------------------------------------------ 错误位置
def test_step_ref_detected():
    for s in ("第二步", "第 2 步", "步骤3", "step 4", "2"):
        assert is_step_ref(s) is True
    for s in ("n+1 必须整除 2", "因此 n 只能取 1"):
        assert is_step_ref(s) is False


def test_location_missing_or_step_ref_is_not_evidence():
    assert check_location("", SRC)[0] is None
    assert check_location("第二步", SRC)[0] is None


def test_location_grounded():
    assert check_location("n+1 必须整除 2", SRC)[0] is True


def test_norm_text_strips_latex_and_case():
    assert norm_text("$A B$") == "ab"
    assert norm_text(" a，b。c ") == "abc"


# -------------------------------------------------- 4.2 机检证书的题面依据
def test_cert_checks_without_problem_basis_dropped():
    from agent.answer_falsifier import AnswerFalsifier as F
    problem = "求所有正整数 n 使 n^2+1 被 n+1 整除。"
    kept, dropped = F._drop_ungrounded(
        [{"desc": "来自条件：x=0", "lhs": "1+1", "rhs": "3"}], problem)
    assert kept == [] and len(dropped) == 1


def test_cert_checks_with_literal_quote_kept():
    from agent.answer_falsifier import AnswerFalsifier as F
    problem = "求所有正整数 n 使 n^2+1 被 n+1 整除。"
    kept, dropped = F._drop_ungrounded(
        [{"desc": "来自条件：n^2+1 被 n+1 整除", "lhs": "1^2+1", "rhs": "2"}],
        problem)
    assert len(kept) == 1 and dropped == []


def test_cert_check_without_desc_dropped():
    from agent.answer_falsifier import AnswerFalsifier as F
    kept, dropped = F._drop_ungrounded(
        [{"desc": "", "lhs": "1+1", "rhs": "3"}], "题面")
    assert kept == [] and dropped[0]["note"] == "no_desc"
