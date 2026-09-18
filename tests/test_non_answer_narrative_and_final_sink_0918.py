# -*- coding: utf-8 -*-
"""2026-09-18 复测暴露的两个缺口修复：非答案判据补「过程叙述」+ final_response 单一入口。

背景：09-18 复测中，020/032/025 的**最终答案**变成过程叙述，例如
  · `搜索已知结论：这个问题看起来像是一个已知的组合数学问题。也许答案是 $2^{k+1}$ 之类的。让我用 web_search 查找类似问题。`
  · `继续找规律，目前 type B：2, 8, 10。`
  · `步骤11：搜索已知结论`
根因两条：
  ① `_STEP_LABEL_RE` 只写了 `让我们`，**漏了 `让我`**；且这些句子含 `$` ⇒ has_math 闸门放行；
  ② `ctx.final_response` 有三个**无校验**的赋值点（零票直答 / 6.5 重做 / 6.5 换候选），
     而 6.5 在 formatter **之后**运行 ⇒ 可以把脏文本覆盖成最终答案
     （证据：`pick_diag.picked` 与实际 pred 不一致）。
"""
import io
import os

import pytest

from agent.base import TaskContext
from agent.formatter import _looks_like_non_answer
from agent.orchestrator import Orchestrator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   errors="replace").read()


# ================= ① 过程叙述判据 =================
PROSE = [
    "搜索已知结论：这个问题看起来像是一个已知的组合数学问题。"
    "也许答案是 $2^{k+1}$ 之类的。让我用 web_search 查找类似问题。",
    "继续找规律，目前 type B：2, 8, 10。",
    "步骤11：搜索已知结论",
    "让我搜索 $x^4 + 5$ 的分裂域次数。",
    '文本提到 S-tetramino 是 "2×3 去掉两个对角角" 的形状',
    "这变得复杂。让我尝试证明$a_1 = 2$是必须的。",
    "实际上，让我重新审视。也许 type B 数有特定的模式。让我搜索一下这个经典问题",
    "继续寻找规律",
]

LEGIT = [
    r"\boxed{2026}",
    r"\boxed{有限差分法}",
    r"\boxed{\dfrac{1}{2}}",
    "506",
    "有限元法",
    r"\boxed{\mathbb{Q}(\sqrt[4]{5}, i), 8, 是}",
    "2026, 2030",
    r"\hat{f}(\omega) = \frac{2e^{i\omega}}{1+\omega^{2}}",
]


@pytest.mark.parametrize("t", PROSE)
def test_process_narrative_flagged(t):
    assert _looks_like_non_answer(t) is True, t


@pytest.mark.parametrize("t", LEGIT)
def test_legit_answers_still_pass(t):
    assert _looks_like_non_answer(t) is False, t


def test_wo_men_gap_closed():
    """一字之差是本次漏检的直接原因：`让我们` 有、`让我` 无。"""
    assert _looks_like_non_answer("让我们来看这道题") is True
    assert _looks_like_non_answer("让我搜索相关资料") is True


# ================= ② final_response 单一入口 =================
def test_set_final_response_rejects_prose():
    c = TaskContext(problem="p", metadata={})
    assert Orchestrator._set_final_response(
        c, "继续找规律，目前 type B：2, 8, 10。") is False
    assert c.final_response == "", "脏答案不得写入"


def test_set_final_response_rejects_empty():
    c = TaskContext(problem="p", metadata={})
    c.final_response = "旧值"
    assert Orchestrator._set_final_response(c, "   ") is False
    assert c.final_response == "旧值", "空答案不得覆盖已有值"


def test_set_final_response_accepts_legit():
    c = TaskContext(problem="p", metadata={})
    assert Orchestrator._set_final_response(c, r"\boxed{506}") is True
    assert c.final_response == r"\boxed{506}"


def test_all_final_response_writes_are_guarded():
    """6 个赋值点里，3 个原先无校验的必须已改用 `_set_final_response`。"""
    src = _src("agent/orchestrator.py")
    # 不得再有裸写
    for bare in ("ctx.final_response = _fresh.answer",
                 "ctx.final_response = _next.answer",
                 "ctx.final_response = direct_answer"):
        assert bare not in src, "仍有未过闸门的裸写：%s" % bare
    # 且必须存在单一入口
    assert "def _set_final_response" in src
    assert src.count("self._set_final_response(") >= 4
