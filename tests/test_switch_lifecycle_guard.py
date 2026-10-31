# -*- coding: utf-8 -*-
"""开关「出口制」守卫（2026-10-31）。

本文件防的是什么错
==================
`switch_registry` 只规定**入口**（新增开关四处同步），历史上没有任何机制管**出口**。
用 133 个历史开关 + 103 个题次的全量回放量化后果：

  · 真正删掉 11 个（8%）；
  · 现存 101/109 个值从未变过；
  · doc 自称「可做 A/B」的 36 个里，真正验证过 4 个（其中 2 个是环境兜底）。

⇒ 结论：这套机制原本是「只进不出」的。本文件把出口固化成断言。

两级守卫
========
**第一级 · 机制正确性**（`TestMechanism`）—— 用注入的假注册表测判定逻辑本身：
  过期判定边界、幽灵条目、登记不全、有结论无证据、闸刀/参数不追出口。

**第二级 · 真实注册表守卫**（`TestRealRegistry`）—— 对 `contracts.switch_registry`
  实际内容断言：
  · **无幽灵**（登记的开关必须还在注册表里，删了开关要销账）；
  · **无登记不全**（experiment 的 opened/question/verify_by/expires 必须齐）；
  · **过期未决必须为空**——除非在 `KNOWN_OVERDUE` 白名单里。

★ 白名单为什么不是橡皮图章
--------------------------
`KNOWN_OVERDUE` 里每条都**自带处置截止日**。一旦 `today >= LEGACY_DEADLINE`，
白名单整体失效 ⇒ 边「豁免」边到期，到期后测试必红。
这正是本文件要防的：上一轮的问题不是「没有约定」，而是约定里没有日期。

★ 新增开关零宽限
----------------
`KNOWN_OVERDUE` 只覆盖已登记的存量债。任何**新**开关一旦被判为 experiment
而未登记出口，`ab_claimed_untracked` 里出现、且白名单不含它 ⇒ 立即失败。
"""
from __future__ import annotations

import contextlib
import datetime
import sys

import pytest

from contracts import switch_lifecycle as sl
from contracts.switch_registry import SWITCHES


# ---------------------------------------------------------------------------
# 已登记、但当天尚未处置的存量债。每条必须写清「什么时候必须处置完」。
# 严格早于 LEGACY_DEADLINE 的日期由测试校验（见 test_whitelist_has_deadlines）。
# ---------------------------------------------------------------------------
KNOWN_OVERDUE = {
    "blueprint_goal_kind_guidance": "2026-11-10",
    "blueprint_merge_value_mask": "2026-11-10",
    "bounded_search": "2026-11-10",
    "step_verification_audit": "2026-11-10",
}

# ---------------------------------------------------------------------------
# 允许「自称可做 A/B 但暂无出口」的名单 —— 存量，仅到 LEGACY_DEADLINE 为止。
# 新增开关**不得**加进这里：加了就等于给新债开白条。
# ---------------------------------------------------------------------------
KNOWN_AB_UNTRACKED = frozenset()


# ===========================================================================
# 第一级 · 机制正确性
# ===========================================================================
def _sw(name, val_kind="bool", default=True, doc="doc"):
    """单个开关的注入注册表。"""
    return {name: ("ENV_" + name.upper(), val_kind, default, doc)}


@contextlib.contextmanager
def lifecycle_patch(entries):
    """临时替换 ``sl.LIFECYCLE``（测试隔离，退出即还原）。"""
    saved = dict(sl.LIFECYCLE)
    try:
        sl.LIFECYCLE.clear()
        sl.LIFECYCLE.update(entries)
        yield
    finally:
        sl.LIFECYCLE.clear()
        sl.LIFECYCLE.update(saved)


def _audit_one(name, today, val_kind="bool", doc="doc", **entry):
    """「只含一个开关」的完整审计：临时登记 LIFECYCLE 后审计，退出即还原。"""
    with lifecycle_patch({name: entry} if entry else {}):
        return sl.audit(today=today, switches=_sw(name, val_kind, True, doc))


class TestMechanism:
    def test_expired_becomes_error(self):
        rep = _audit_one("x_demo", datetime.date(2026, 10, 31),
                         kind=sl.KIND_EXPERIMENT, opened="2026-10-01",
                         question="q", verify_by="v", expires="2026-10-20",
                         decision="pending", evidence="")
        assert [e["field"] for e in rep["expired"]] == ["x_demo"]
        assert rep["expired"][0]["overdue_days"] == 11
        assert any("已过期未决" in e for e in rep["errors"])

    def test_due_today_is_not_overdue(self):
        """到期当天不算逾期 —— 当天还没过完，次日才算。"""
        rep = _audit_one("x_demo", datetime.date(2026, 10, 31),
                         kind=sl.KIND_EXPERIMENT, opened="2026-10-01",
                         question="q", verify_by="v", expires="2026-10-31",
                         decision="pending", evidence="")
        assert rep["expired"] == []

    def test_resolved_experiment_needs_evidence(self):
        """decision 已给但 evidence 空 ⇒ 等于没结，仍算错误。"""
        rep = _audit_one("x_demo", datetime.date(2026, 10, 31),
                         kind=sl.KIND_EXPERIMENT, opened="2026-10-01",
                         question="q", verify_by="v", expires="2026-10-20",
                         decision="removed", evidence="")
        assert rep["expired"] == []
        assert rep["incomplete"] and "evidence" in rep["incomplete"][0]["missing"][0]

    def test_resolved_with_evidence_is_clean(self):
        rep = _audit_one("x_demo", datetime.date(2026, 10, 31),
                         kind=sl.KIND_EXPERIMENT, opened="2026-10-01",
                         question="q", verify_by="v", expires="2026-10-20",
                         decision="removed", evidence="边际贡献 0，已删")
        assert rep["errors"] == []

    def test_missing_fields_is_error(self):
        rep = _audit_one("x_demo", datetime.date(2026, 10, 31),
                         kind=sl.KIND_EXPERIMENT, opened="2026-10-01",
                         expires="2026-10-20", decision="pending")
        assert rep["incomplete"]
        missing = set(rep["incomplete"][0]["missing"])
        assert {"question", "verify_by"} <= missing

    def test_ghost_is_error(self):
        """登记了但注册表已无 ⇒ 删开关没销账。"""
        sw = {"other": ("ENV_OTHER", "bool", True, "doc")}
        saved = dict(sl.LIFECYCLE)
        try:
            sl.LIFECYCLE.clear()
            sl.LIFECYCLE.update({"deleted_one": {"kind": sl.KIND_EXPERIMENT,
                                                 "opened": "2026-10-01",
                                                 "question": "q", "verify_by": "v",
                                                 "expires": "2026-10-20",
                                                 "decision": "pending"}})
            rep = sl.audit(today=datetime.date(2026, 10, 31), switches=sw)
        finally:
            sl.LIFECYCLE.clear()
            sl.LIFECYCLE.update(saved)
        assert rep["ghosts"] == ["deleted_one"]
        assert any("幽灵登记" in e for e in rep["errors"])

    @pytest.mark.parametrize("field,val_kind,doc", [
        ("some_timeout", "num", ""),
        ("some_chars", "int", ""),
        ("eval_split_cn", "bool", ""),
        ("five_gate_vote", "bool", "=0 关闭做 A/B"),
        ("lean_verify", "bool", "可回退"),
        ("enable_foo", "bool", ""),
        ("answer_form_gate", "bool", ""),
    ])
    def test_non_experiment_kinds_are_not_chased(self, field, val_kind, doc):
        """闸刀 / 参数不追出口：即使 doc 带 A/B 套话也不报。"""
        assert sl.infer_kind(field, val_kind, 0, doc) != sl.KIND_EXPERIMENT

    def test_ab_claim_on_plain_feature_is_experiment(self):
        assert sl.infer_kind("blueprint_merge_value_mask", "bool", True,
                             "归并时不带值掩码；=0 回退做 A/B") == sl.KIND_EXPERIMENT

    def test_untracked_experiment_warns_before_deadline_errors_after(self):
        """存量宽限：截止前只告警，截止后转硬错误。"""
        sw = {"plain_feature": ("ENV_PLAIN", "bool", True, "=0 关闭做 A/B")}
        saved = dict(sl.LIFECYCLE)
        try:
            sl.LIFECYCLE.clear()
            rep_before = sl.audit(today=sl.LEGACY_DEADLINE - datetime.timedelta(days=1),
                                  switches=sw)
            rep_after = sl.audit(today=sl.LEGACY_DEADLINE, switches=sw)
        finally:
            sl.LIFECYCLE.clear()
            sl.LIFECYCLE.update(saved)
        assert rep_before["ab_claimed_untracked"] == ["plain_feature"]
        assert rep_before["errors"] == []
        assert any("存量宽限已过" in e for e in rep_after["errors"])

    def test_human_kind_overrides_inference(self):
        """人工登记优先：把 doc 带 A/B 的开关登记成 gate，就不再追出口。"""
        rep = _audit_one("plain_feature", datetime.date(2026, 10, 31),
                         kind=sl.KIND_GATE, doc="=0 关闭做 A/B")
        assert rep["counts"][sl.KIND_GATE] == 1
        assert rep["ab_claimed_untracked"] == []

    def test_lifecycle_of_unknown_field_is_ghost(self):
        lc = sl.lifecycle_of("no_such_switch_xyz", switches={})
        assert lc["source"] == "ghost" and lc["in_registry"] is False


# ===========================================================================
# 第二级 · 真实注册表守卫
# ===========================================================================
class TestRealRegistry:
    def test_no_ghost_entries(self):
        rep = sl.audit(switches=SWITCHES)
        assert rep["ghosts"] == [], (
            "LIFECYCLE 登记了注册表里已不存在的开关（删开关要销账）：%s" % rep["ghosts"]
        )

    def test_registered_experiments_are_complete(self):
        rep = sl.audit(switches=SWITCHES)
        assert rep["incomplete"] == [], (
            "实验开关出口登记不全：%s" % rep["incomplete"]
        )

    def test_overdue_must_be_zero_outside_whitelist(self):
        """过期未决必须为空 —— 白名单里的存量债除外。"""
        rep = sl.audit(switches=SWITCHES)
        overdue = {e["field"] for e in rep["expired"]}
        unexpected = overdue - set(KNOWN_OVERDUE)
        assert not unexpected, (
            "实验开关已过期未决且不在白名单：%s\n每一条都必须给出 kept/removed 结论 + 证据"
            % sorted(unexpected)
        )

    def test_whitelist_entries_are_real(self):
        """白名单里不能有空条目（处置完了就要销号，否则白名单会无限增长）。"""
        live = {e["field"] for e in sl.audit(switches=SWITCHES)["expired"]}
        stale = set(KNOWN_OVERDUE) - live
        assert not stale, (
            "白名单里这些已不再逾期（已处置或未被判为 experiment），请销号：%s" % sorted(stale)
        )

    def test_whitelist_has_deadlines(self):
        """★ 白名单不是橡皮图章：每条都要有早于 LEGACY_DEADLINE 的处置截止日。"""
        for field, deadline_s in KNOWN_OVERDUE.items():
            d = sl._parse_date(deadline_s)
            assert d is not None, "%s 的处置截止日格式非法：%r" % (field, deadline_s)
            assert d <= sl.LEGACY_DEADLINE, (
                "%s 的处置截止日 %s 晚于存量宽限 %s —— 白名单不得自我延期"
                % (field, deadline_s, sl.LEGACY_DEADLINE)
            )

    def test_whitelisted_debt_cleared_by_its_own_deadline(self):
        """★ 每条存量债到**自己的处置截止日**就必须已处置 —— 白名单不能自我延期。

        与 `test_whitelist_has_deadlines`（格式与上限校验）互补：那条防「写个远期日期」，
        这条防「日期到了还赖着」。今天之前一律通过，到期当天起该条必须从 expired 消失。
        """
        today = datetime.date.today()
        live = {e["field"] for e in sl.audit(switches=SWITCHES)["expired"]}
        overdue = []
        for field, deadline_s in KNOWN_OVERDUE.items():
            d = sl._parse_date(deadline_s)
            if d is not None and today >= d and field in live:
                overdue.append("%s（截止 %s）" % (field, deadline_s))
        assert not overdue, (
            "存量债已到处置截止日仍未给结论：%s" % "、".join(overdue)
        )

    def test_new_switches_have_no_grace(self):
        """新增 experiment 不得靠白名单开白条。"""
        rep = sl.audit(switches=SWITCHES)
        smuggled = set(rep["ab_claimed_untracked"]) & set(KNOWN_AB_UNTRACKED)
        assert smuggled == set(), (
            "这些开关自称可做 A/B 却被塞进白名单，等于给新债开白条：%s" % sorted(smuggled)
        )

    def test_report_is_renderable(self):
        """audit() 与 format_report() 口径一致，且报告能渲染（CLI 复用同一函数）。"""
        rep = sl.audit(switches=SWITCHES)
        text = sl.format_report(rep)
        assert "开关出口审计" in text
        assert "结论：" in text
