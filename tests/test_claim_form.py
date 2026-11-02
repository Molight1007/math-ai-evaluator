# -*- coding: utf-8 -*-
"""节点声明形态判定（2026-11-02）。

被测对象只做一件事：给定一段自然语言，判定它像「提问」还是「宣告」。
它不判数学对错，也不判死任何节点 —— 所以样本必须覆盖的是**判定顺序**，
而不是数学正确性。

最重要的一条：判定顺序不可交换。
先问「有没有提问动词」，再问「像不像赋值等式」——反序会把
「证明 x = 42」判成结论（它是目标）。历史宽口径值断言检测 32.4%
的假阳性正是这个反序造成的（题设方程被当成断言）。
"""
from __future__ import annotations

import pytest

from utils.claim_form import (
    FORM_AMBIGUOUS,
    FORM_GOAL,
    FORM_RESULT,
    FORMALITY_FULL,
    FORMALITY_NONE,
    FORMALITY_PARTIAL,
    classify_claim,
    formality_of,
    is_question_form,
    summarize,
)


# ---------------------------------------------------------------- Q1 目标形态
@pytest.mark.parametrize("text", [
    "证明对所有正整数 n 有 a_n > 0",
    "求证：该级数收敛",
    "求所有满足条件的正整数对 (a,b)",
    "确定参数 k 的取值范围",
    "是否存在正整数解？",
    "计算该行列式的值",
    "判断该数列是否单调",
    "构造一个满足条件的例子",
    "Prove that the sum converges.",
    "Find all integers n such that n^2 + 1 is prime.",
    "How many such permutations are there?",
    "该命题是否成立？",
])
def test_goal_form(text):
    r = classify_claim(text)
    assert r["form"] == FORM_GOAL, r
    # 必须留下证据，否则判定不可复核
    assert r["evidence"], r


# --------------------------------------------------------------- Q2 结论形态
@pytest.mark.parametrize("text", [
    "a_n = n+1",
    "T = (\\sqrt{5}-1)/2",
    "x_1 = 42",
    "结论：a_n = n+1",
    "因此 T 等于 1/2",
    "最终答案：42",
    "Therefore the answer is 946.",
    "答案是 946",
])
def test_result_form(text):
    r = classify_claim(text)
    assert r["form"] == FORM_RESULT, r


# ----------------------------------------------- Q3 假阳性防护（历史 7 倍偏差源）
@pytest.mark.parametrize("text", [
    # 题设方程：左侧不是单一符号 ⇒ 不是「断言了某个值」
    "由 x^2 + y^2 + z^2 = 3 建立范围约束",
    "x^2 + y^2 + z^2 = 3",
    "a + b = 1",
    # 推导片段：既无提问动词，也不是赋值
    "代入后化简得到剩余部分",
    "利用 AM-GM 不等式放缩",
    "",
    "   ",
])
def test_not_result_no_false_positive(text):
    r = classify_claim(text)
    assert r["form"] == FORM_AMBIGUOUS, r


# --------------------------------------------- Q4 「证明 x = 42」必须是目标
def test_prove_assignment_is_goal_not_result():
    """判定顺序的核心回归：带提问动词的赋值，是目标不是结论。"""
    for t in ("证明 x = 42", "求证 a_n = n+1", "验证 T = 1/2"):
        r = classify_claim(t)
        assert r["form"] == FORM_GOAL, (t, r)


# ------------------------------------------------- Q5 陈述式目标归入 ambiguous
def test_declarative_goal_is_ambiguous():
    """陈述式目标（「对任意 n，a_n > 0」）文本上无法与断言区分。

    ★ 这是**诚实的边界**，不是缺陷：恰恰说明「目标」与「结论」在同一槽位
      里不可区分 —— 本模块把这类归入 ambiguous 正是要把这个不可区分
      显式暴露出来，而不是硬猜一个。
    """
    r = classify_claim("对任意 n，a_n > 0")
    assert r["form"] == FORM_AMBIGUOUS, r
    assert r["formality"] == FORMALITY_FULL


# ------------------------------------------------------------- Q6 可形式化等级
@pytest.mark.parametrize("text,want", [
    ("证明 a_n > 0", FORMALITY_FULL),
    ("a_n = n+1", FORMALITY_FULL),
    ("对所有 n，n | (n^3 - n)", FORMALITY_FULL),
    ("for all x, f(x) >= 0", FORMALITY_FULL),
    ("讨论该函数的单调性", FORMALITY_PARTIAL),
    ("作图并画出三角形 ABC 的三条高", FORMALITY_NONE),
    ("设计一个 O(n log n) 的算法", FORMALITY_NONE),
    ("写出程序求该数列第 n 项", FORMALITY_NONE),
    ("", FORMALITY_NONE),
])
def test_formality(text, want):
    assert formality_of(text) == want


def test_formality_long_text_is_partial():
    """超长文本可能含多个命题 ⇒ 不足以写成单条形式命题。"""
    long_text = "证明" + "a" * 300 + " = 1"
    assert formality_of(long_text) == FORMALITY_PARTIAL


# ----------------------------------------------------------------- Q7 空输入
def test_empty_input():
    r = classify_claim("")
    assert r["form"] == FORM_AMBIGUOUS
    assert r["formality"] == FORMALITY_NONE
    assert r["text_len"] == 0
    assert not is_question_form("")
    assert not is_question_form(None)


# --------------------------------------------------------------- Q8 汇总计数
def test_summarize():
    rows = [
        classify_claim("证明 a_n > 0"),
        classify_claim("a_n = n+1"),
        classify_claim("x^2 + y^2 = 3"),
        classify_claim("作图"),
    ]
    s = summarize(rows)
    assert s["n"] == 4
    assert s["forms"][FORM_GOAL] == 1
    assert s["forms"][FORM_RESULT] == 1
    assert s["forms"][FORM_AMBIGUOUS] == 2
    assert s["formality"][FORMALITY_FULL] == 3   # 证明式 / 赋值 / 题设方程都含关系符
    assert s["formality"][FORMALITY_NONE] == 1
    # 分形态交叉表：goal 那条是 full
    assert s["forms_by_formality"][FORM_GOAL][FORMALITY_FULL] == 1


def test_summarize_ignores_garbage():
    s = summarize([None, 1, {"form": "nope"}, {"form": FORM_GOAL}])
    assert s["n"] == 1
    assert s["forms"][FORM_GOAL] == 1


def test_summarize_empty():
    s = summarize([])
    assert s["n"] == 0
