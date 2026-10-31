# -*- coding: utf-8 -*-
"""`agent/bounded_search.py` 的回归测试。

样本来源：真实题库原文（`题库/omni8_20261027.jsonl` 的 omni-3556）为主，
其余为按同一形态构造的最小例 —— 目的是钉住**判据边界**，不是刷覆盖率。
"""
from __future__ import annotations

import pytest

from agent.bounded_search import (detect, render_block, run_search, summary)

# omni-3556 原题（LaTeX 原文，含换行与 `\[ ... \]`）
_Q3556 = (
    "Find an integer $n$, where $100 \\leq n \\leq 1997$, such that \n"
    "\\[ \\frac{2^n+2}{n}  \\] \n"
    "is also an integer.\n"
)


# ---------------------------------------------------------------- 识别
def test_detect_3556():
    spec = detect(_Q3556)
    assert spec is not None
    assert (spec["var"], spec["lo"], spec["hi"]) == ("n", 100, 1997)
    assert spec["tag"] == "frac_integer"


def test_detect_mid_form():
    spec = detect(r"Find $n$ with $1 \le n \le 30$ such that $n \mid 2^n+2$.")
    assert spec is not None and spec["var"] == "n"
    assert (spec["lo"], spec["hi"]) == (1, 30)


def test_detect_congruence_form():
    spec = detect(r"$1 \le n \le 30$, $n \equiv 0 \pmod{7}$.")
    assert spec is not None
    assert (spec["den"], spec["num"]) == ("7", "n")


def test_detect_slash_form_onesided_positive():
    spec = detect(r"positive integers n \le 100 such that (3^n - 3)/n is an integer.")
    assert spec is not None
    assert (spec["lo"], spec["hi"]) == (1, 100)
    assert spec["tag"] == "slash_integer"


def test_detect_rejects_two_symbols():
    # 两个变量 ⇒ 本模块不认（宁可 refuse，不可错认）
    assert detect(r"$100 \le n \le 1997$, $\frac{2^n+2}{m}$ is an integer.") is None


def test_detect_rejects_no_domain():
    assert detect(r"$\frac{2^n+2}{n}$ is an integer.") is None


def test_detect_rejects_no_condition():
    assert detect(r"Find the largest $n$ with $1 \le n \le 99$.") is None


def test_detect_rejects_plain_english_divides():
    # 英文自然语言 `n divides 2^n+2` 不认（算子边界易切错 ⇒ 不猜）
    assert detect("Find n with 1 <= n <= 30 such that n divides 2^n+2.") is None


# ---------------------------------------------------------------- 搜索
def test_search_3556_unique_hit():
    res = run_search(detect(_Q3556))
    assert res["ok"] and res["exclusive"]
    assert res["hits"] == [946]
    assert res["checked"] == 1898       # 全部候选都判过，不是提前 break
    assert res["unevaluated"] == 0


def test_search_3556_certificate_recomputable():
    res = run_search(detect(_Q3556))
    cert = res["certificate"][0]
    assert cert["n"] == 946
    assert cert["factorization"] == [(2, 1), (11, 1), (43, 1)]
    for q, r in cert["residues"]:
        assert r == 0                    # 每个素数幂都独立复算过
    assert [q for q, _ in cert["residues"]] == [2, 11, 43]


def test_search_empty_hit_set_is_still_exclusive():
    # 区间内无解也必须给「已全部检验」的结论，而不是「没找到」
    # （实测 `n | 2^n+2` 在 [100, 200] 上确实一个都没有）
    res = run_search(detect(r"$100 \le n \le 200$ such that $\frac{2^n+2}{n}$ "
                            r"is an integer."))
    assert res["ok"] and res["exclusive"]
    assert res["hits"] == []


def test_search_range_too_large_refuses():
    spec = detect(r"$1 \le n \le 99999999$ such that $\frac{2^n}{n}$ is an integer.")
    res = run_search(spec, cap=1000)
    assert not res["ok"]
    assert res["reason"].startswith("range_too_large")


def test_search_unsupported_expr_refuses():
    # 指数是 n 的幂 ⇒ 会撞 `_MAX_EXP`，必须 refuse 而不是给出半截结果
    spec = {"var": "n", "lo": 1, "hi": 5, "num": "2^{10^n}", "den": "n",
            "tag": "t", "predicate": "n | 2^{10^n}"}
    res = run_search(spec)
    assert not res["ok"]
    assert res["reason"].startswith("unevaluated")


def test_search_bad_expr_refuses():
    spec = {"var": "n", "lo": 1, "hi": 5, "num": "\\sqrt{n}", "den": "n",
            "tag": "t", "predicate": "n | sqrt(n)"}
    res = run_search(spec)
    assert not res["ok"] and res["reason"] == "unsupported_expr"


# ---------------------------------------------------------------- 渲染
def test_render_contains_exclusion_record():
    block = render_block(run_search(detect(_Q3556)))
    assert "946" in block
    assert "排除记录" in block
    assert "1897" in block                # 其余 1897 个已检验


def test_render_empty_hits_says_no_solution():
    block = render_block(run_search(detect(
        r"$100 \le n \le 200$ such that $\frac{2^n+2}{n}$ is an integer.")))
    assert "空集" in block


def test_render_none_is_empty_string():
    assert render_block(None) == ""
    assert render_block({"ok": False, "reason": "unsupported_expr"}) == ""


def test_summary_lines():
    assert "未命中" in summary(None)
    assert "refuse" in summary({"ok": False, "reason": "timeout(2.0s)"})
    assert "946" in summary(run_search(detect(_Q3556)))


# ---------------------------------------------------------------- 接线
def test_ensure_caches_and_records_on_ctx():
    from agent.bounded_search import ensure

    class _Ctx:
        problem = _Q3556

    ctx = _Ctx()
    first = ensure(ctx)
    assert first is not None and first["hits"] == [946]
    second = ensure(ctx)
    assert second is first                # 只算一次
    assert getattr(ctx, "_bounded_search_done", False) is True


def test_ensure_switch_off_returns_none(monkeypatch):
    from agent import bounded_search as bs

    monkeypatch.setattr(bs, "enabled", lambda config=None: False)

    class _Ctx:
        problem = _Q3556

    assert bs.ensure(_Ctx()) is None


@pytest.mark.parametrize("text", ["", "   ", "Find the value of $x+y$."])
def test_detect_blank_or_irrelevant(text):
    assert detect(text) is None
