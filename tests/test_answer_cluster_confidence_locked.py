"""锁死 `AnswerCluster.confidence` 的**只读属性**语义。

背景（2026-10-05 实测事故）：
    2026-10-05 18:23 起的全量修复版评测，在跑到第 1 题约 3 小时处整轮崩溃：

        ERROR: Orchestrator run failed:
        property 'confidence' of 'AnswerCluster' object has no setter

    根因：修复"深复核判错后结构化报告被旧可信度挡掉"时，误把
    `AnswerCluster.confidence` 当成可写字段（依据是误读了 `agent/base.py:317`，
    那是**另一个类**的 dataclass 字段），于是写了

        best_cluster.confidence = 0.0

    而 `AnswerCluster`（`agent/verifier.py`）用 `__slots__` + `@property`，
    `confidence` 由 `vote_correct / vote_total` **计算得出**、**只读**
    ⇒ 赋值抛 AttributeError ⇒ 整轮评测 0 条结果。

    正确做法：**只需** `vote_correct = 0`，`confidence` 会自动变成 0.0
    （`_extract_revise_feedback` 的 `confidence >= 0.5` 门槛因此自然放行）。

本文件是该事故的回归防线：一旦有人再把 `confidence` 当可写字段，或改了
计算口径，这里会先红。
"""

from __future__ import annotations

import pytest

from agent.verifier import AnswerCluster


def _cluster(correct: int, total: int) -> AnswerCluster:
    c = AnswerCluster("42")
    c.candidate_ids = [0, 1, 2]
    c.vote_correct = correct
    c.vote_total = total
    return c


def test_confidence_is_computed_from_votes():
    """confidence 必须 = vote_correct / vote_total（计算属性，非常量字段）。"""
    assert _cluster(3, 3).confidence == 1.0
    assert _cluster(1, 3).confidence == pytest.approx(1 / 3)
    assert _cluster(0, 3).confidence == 0.0


def test_confidence_is_read_only():
    """★ 核心契约：confidence **不可赋值**。

    这条会在有人把它改回可写字段（或新增 setter）时变红 ——
    因为那正是 2026-10-05 事故的成因。
    """
    c = _cluster(3, 3)
    with pytest.raises(AttributeError):
        c.confidence = 0.0  # type: ignore[misc]


def test_zero_vote_total_does_not_crash():
    """vote_total == 0 时必须返回 0.0（而不是 ZeroDivisionError）。"""
    c = AnswerCluster("42")
    c.candidate_ids = []
    c.vote_correct = 0
    c.vote_total = 0
    assert c.confidence == 0.0


def test_clearing_vote_correct_is_sufficient():
    """★ 复现事故的**正确修法**：只清 `vote_correct`，confidence 自动归零。

    这正是"深复核判错"分支需要的行为：清票之后
    `_extract_revise_feedback` 的 `if confidence >= 0.5: return ""` 会放行，
    结构化 bug report 得以进入反馈。**不需要也不允许**给 confidence 赋值。
    """
    c = _cluster(3, 3)
    assert c.confidence == 1.0
    # 深复核判错分支的全部动作（与 agent/verifier.py 保持一致）：
    c.vote_correct = 0
    c.vote_total = max(1, c.vote_total)
    assert c.confidence == 0.0, "清票后 confidence 必须自动为 0，否则反馈门槛仍会挡住结构化报告"


def test_slots_reject_arbitrary_attributes():
    """`__slots__` 生效：不能凭空挂属性（防止有人把 confidence 当字段塞回去）。"""
    c = AnswerCluster("42")
    with pytest.raises(AttributeError):
        c.confidence = 1.0  # type: ignore[misc]
