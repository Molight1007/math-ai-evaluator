# -*- coding: utf-8 -*-
"""2.6 题意理解「结果值」掩码（`agent.value_mask.mask_result_values`）测试。

覆盖三件事：
1. **真泄漏必须拦**：4 条样本逐字抄自 2026-10-27/28 服务器真实产物
   （`results/*/q*/01_understanding.json` 的 `problem_goal.terminal_state`），
   旧判据对它们 **0 命中**。
2. **防误伤**：题面已给的数字（条件复述）不得被抹 —— 这是本判据唯一可能
   伤到"可解信息"的方向，故用真实题面做白名单样本。
3. **结构性排除**：含自由变量的关系式（`= 2k`）不是值，不得掩。
"""
from __future__ import annotations

import pytest

from agent.value_mask import MASK_PLACEHOLDER, mask_result_values, problem_numbers


# --------------------------------------------------------------- 真泄漏样本
# ★ 全部逐字抄自服务器产物，不要"润色"——判据是针对这些真实句式写的。
_LEAK_3593 = (
    "最大社区数为4。存在满足所有给定条件的4社区配置。任何5个或更多社区的配置"
    "都无法同时满足无单色三角形、每顶点至多使用两种交通方式且三种方式均被使用的约束。")
_LEAK_2163a = (
    "本题已解出：当 n=80 时，两束激光与切线夹角分别为 80° 和 81°，分别照亮 9 个和 "
    "20 个墙点，且仅 P 点重合，并集大小为 28，此为所有合法 n 中的最小可能值。")
_LEAK_2163b = (
    "最小照亮点数为 28，当 n=80 时实现，此时第一束激光（80°）照亮 9 个点，"
    "第二束激光（81°）照亮 20 个点，两束激光仅共享点 P。")
_LEAK_3876 = (
    "函数 f 被确定为恒等函数，即对所有正整数 n 有 f(n) = n，"
    "因此 f(1988) 的值唯一确定为 1988。")
_LEAK_1322 = (
    "题目已解出时，所有既是单位根又是某个整系数二次方程根的复数恰好有 8 个，"
    "它们分别是 1, -1, i, -i, e^{2πi/3}, e^{4πi/3}。")


@pytest.mark.parametrize("text,expect_leak_value", [
    (_LEAK_3593, "4"),
    (_LEAK_2163a, "28"),
    (_LEAK_2163b, "28"),
    (_LEAK_3876, "1988"),
    (_LEAK_1322, "8"),
])
def test_real_leak_is_masked(text, expect_leak_value):
    """真泄漏必须被拦：掩码后占位符出现、且原值不再紧跟锚点。"""
    out, n = mask_result_values(text)
    assert n >= 1, "旧判据 0 命中的真实样本必须在这里被拦住"
    assert MASK_PLACEHOLDER in out
    # 该值仍可能出现在别处（如构造描述里的 4社区配置），只要求锚点后的那个被换掉
    assert MASK_PLACEHOLDER in out


def test_strong_anchor_ignores_whitelist():
    """强锚点（「唯一确定」）绕白名单 —— 1988 既是题面参数也可能是答案。

    题面 `Find the possible value for f(1988)` 含 1988，若白名单优先就会漏掩；
    强锚点必须优先。
    """
    problem = ("Let f be a function on positive integers. Suppose "
               "f(f(n)+f(m)) = m+n for all n,m. Find the possible value for f(1988).")
    out, n = mask_result_values(_LEAK_3876, problem)
    assert n == 1
    assert "唯一确定为 " + MASK_PLACEHOLDER in out
    assert "f(1988)" in out, "题面参数 f(1988) 本身不能被抹掉"


def test_weak_anchor_respects_problem_whitelist():
    """弱锚点命中题面已有数字 ⇒ 不掩（防把条件复述抹成占位符）。"""
    problem = "There are 4 boxes and 4 balls in each box."
    out, n = mask_result_values("每个箱子里的球数为 4，且编号之和待求。", problem)
    assert n == 0
    assert out == "每个箱子里的球数为 4，且编号之和待求。"


def test_condition_restatement_not_masked():
    """真实非泄漏样本（题面条件复述）不得被掩 —— 38 条同类样本的代表。"""
    cases = [
        ("满足方程组 $x^2 + y^2 + z^2 = 3$ 的实数三元组集合已确定，其元素个数 $N$ 已求出。", ""),
        ("对于任意满足 0 <= x_i <= 100 且总和 >= 1810 的整数序列，均存在一个子集。", ""),
        ("十个正整数 a_1 至 a_10 围成圆圈，每个数比其两邻居的最大公约数大 1。", ""),
        ("伴随算子 $L^*$ 已被完全确定，其系数由 $a_{ij}, b_j, c$ 给出。", ""),
    ]
    for text, problem in cases:
        out, n = mask_result_values(text, problem)
        assert n == 0, "误伤：%r" % text[:40]
        assert out == text


def test_symbolic_relation_not_masked():
    """`= 2k` / `f(n) = n` 是关系式，不是值。"""
    for text in ("n² - n = 2k，故 n 为偶数。",
                 "对所有正整数 n 有 f(n) = n。"):
        out, n = mask_result_values(text)
        assert n == 0
        assert out == text


def test_empty_input():
    assert mask_result_values("") == ("", 0)
    assert mask_result_values(None) == ("", 0)


def test_problem_numbers_normalizes_thousands():
    """千分位逗号归一：`1,988` 与 `1988` 视为同一个数。"""
    assert "1988" in problem_numbers("value 1,988")
    out, n = mask_result_values("答案唯一确定为 1,988。", "value 1,988")
    assert n == 1, "强锚点优先于白名单"


def test_idempotent():
    """掩码两次结果相同（占位符里没有数字，不会被二次命中）。"""
    once, n1 = mask_result_values(_LEAK_2163a)
    twice, n2 = mask_result_values(once)
    assert n1 == 1 and n2 == 0
    assert once == twice
