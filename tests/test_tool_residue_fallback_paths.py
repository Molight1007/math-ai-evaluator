# -*- coding: utf-8 -*-
"""回归：工具调用 XML 残留在**三条兜底路径**上都不得成为答案。

背景（official112-013 实测，2026-09-17）
----------------------------------------
E 轮 013 的 6 个候选中 **4 个 `answer == '</tool_call>'`**、其完整推导（2683 字）
留在 `reasoning` 里被丢弃 ⇒ 池里只剩垃圾 + 一个错值 ⇒ 该题必然判错。

根因是**两条路径口径不一致**：
  · `extract_final_answer()` 在出口剥工具 XML（2026-09-17 加的）；
  · `rescue_final_answer()` / `smart_fallback_answer()` **不剥**。
而调用方（`solver.py:1824-1830`、`formatter.py:552`）在
`extract_final_answer` 返回空时**立即回退**到这两个函数 ⇒ 标签照样落盘。

本测试锁死「三条路径必须同口径」，防止再次漂移。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.extract import (  # noqa: E402
    extract_final_answer,
    rescue_final_answer,
    smart_fallback_answer,
)

# 纯工具残留：三条路径都必须返回空（否则标签会成为答案）
_PURE_RESIDUES = [
    "</tool_call>",
    "<tool_call>\n</tool_call>",
    "<tool_calls>\n</tool_calls>",
    "<parameter=query>\nsubset sum approximation target 1810\n</parameter>",
    "<tool_call>\n<function=web_search>\n<parameter=query>\nq\n</parameter>\n</function>\n</tool_call>",
]

# 正文 + 残留：必须把**正文答案**救出来，且不得带标签
_BODY_WITH_RESIDUE = [
    ("所以最小 d 是 48。\n</tool_call>", "48"),
    (r"答案为 \boxed{48}" + "\n<tool_call>\n</tool_call>", "48"),
]


def test_pure_tool_residue_never_becomes_answer():
    """纯工具残留不得成为答案（三条路径一致）。"""
    for raw in _PURE_RESIDUES:
        assert extract_final_answer(raw) == "", (
            f"extract_final_answer 未拦住纯残留: {raw!r} -> "
            f"{extract_final_answer(raw)!r}")
        assert rescue_final_answer(raw)[0] == "", (
            f"rescue_final_answer 未拦住纯残留（013 的直接成因）: {raw!r} -> "
            f"{rescue_final_answer(raw)[0]!r}")
        assert smart_fallback_answer(raw) == "", (
            f"smart_fallback_answer 未拦住纯残留: {raw!r} -> "
            f"{smart_fallback_answer(raw)!r}")


def test_answer_survives_when_residue_appended():
    """残留只是尾部噪声时，正文里的答案仍要能救出来。"""
    for raw, want in _BODY_WITH_RESIDUE:
        got = extract_final_answer(raw)
        assert want in got, f"extract 丢了正文答案: {raw!r} -> {got!r}"
        got_r = rescue_final_answer(raw)[0]
        assert want in got_r, f"rescue 丢了正文答案: {raw!r} -> {got_r!r}"
        got_f = smart_fallback_answer(raw)
        assert want in got_f, f"fallback 丢了正文答案: {raw!r} -> {got_f!r}"


def test_no_path_returns_bare_tag():
    """全局不变式：任何路径都不得返回只由标签构成的字符串。"""
    bad = ("</tool_call>", "<tool_call>", "</parameter>", "</function>",
           "</tool_calls>", "<parameter=query>")
    texts = _PURE_RESIDUES + [t for t, _ in _BODY_WITH_RESIDUE]
    for raw in texts:
        for out in (extract_final_answer(raw),
                    rescue_final_answer(raw)[0],
                    smart_fallback_answer(raw)):
            assert out not in bad, f"标签泄漏成答案: {raw!r} -> {out!r}"


def test_normal_answer_unaffected():
    """不得误伤正常答案（含单字符/负数/分数等边界）。"""
    assert extract_final_answer(r"答案为 \boxed{48}") == "48"
    assert extract_final_answer(r"\boxed{A}") == "A"
    assert extract_final_answer(r"\boxed{-3}") == "-3"
    assert extract_final_answer(r"\boxed{\frac{1}{2}}").endswith("}")
    # 正文里没有 \boxed 时，尾部行兜底仍要给出正文（而不是空）
    body = "所以最小 d 是 48。\n</tool_call>"
    assert "48" in extract_final_answer(body)
    assert "48" in rescue_final_answer(body)[0]
    assert "48" in smart_fallback_answer(body)
