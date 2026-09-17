# -*- coding: utf-8 -*-
"""error_lessons 消融开关 + domain 过滤移除 + 极值正则收紧的回归测试。

背景（2026-09-15，归因报告 v1.1 §7.2 落地）：
  1) 新增三条 lesson（E-count / E-bound / E-magnitude）接入 `ERROR_LESSONS_EXTRA`
     消融开关，用于逐条 A/B；
  2) ★ 原「domain 白名单硬过滤」被移除 —— 实测白名单只覆盖题库 16.1%（18/112），
     最大域「离散数学」（51 题）与 25 道空 domain 题整域静默失效，
     机制对 89 道错题仅 14.6% 生效。本测试锁死该回归。
  3) E-extreme / E-bound 的极值正则原先含**裸** `max|min`，会误匹配
     examine / determine 等普通词，已收紧为词边界 + 完整词形。
"""
import pytest

from prompts.error_lessons import (_EXTRA_IDS, LESSONS, lesson_ids,
                                   match_lessons)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个用例都在干净的 ERROR_LESSONS_EXTRA 环境下运行。"""
    monkeypatch.delenv("ERROR_LESSONS_EXTRA", raising=False)
    yield


def _ids(prob, qt="解答题", dom=""):
    return lesson_ids(dom, qt, prob)


def test_lessons_total_count():
    """lesson 总数 = 原有 4 条 + 新增 3 条。"""
    assert len(LESSONS) == 7
    assert set(_EXTRA_IDS) == {"E-count", "E-bound", "E-magnitude"}


class TestAblation:
    def test_default_all_on(self):
        """默认全部启用（三条各用匹配的题面分别验证）。"""
        assert "E-count" in _ids("求共有多少种不同方案")
        assert "E-bound" in _ids("求 f(x) 的最大值")
        assert "E-magnitude" in _ids("计算该表达式的值")

    def test_none_turns_off_new_three(self, monkeypatch):
        monkeypatch.setenv("ERROR_LESSONS_EXTRA", "none")
        assert "E-count" not in _ids("求共有多少种不同方案")
        assert "E-bound" not in _ids("求 f(x) 的最大值")
        assert "E-magnitude" not in _ids("计算该表达式的值")
        assert "E-check" in _ids("计算该表达式的值"), "原有 4 条不应受消融开关影响"

    def test_subset_selection(self, monkeypatch):
        monkeypatch.setenv("ERROR_LESSONS_EXTRA", "count")
        got = _ids("求共有多少种方案")
        assert "E-count" in got
        assert "E-magnitude" not in got

    def test_full_id_accepted(self, monkeypatch):
        monkeypatch.setenv("ERROR_LESSONS_EXTRA", "E-magnitude")
        got = _ids("计算该表达式的值")
        assert "E-magnitude" in got
        assert "E-count" not in got

    def test_unknown_value_falls_back_to_all(self, monkeypatch):
        monkeypatch.setenv("ERROR_LESSONS_EXTRA", "garbage")
        assert "E-count" in _ids("求共有多少种不同方案"), \
            "无法识别的取值应回退为全开（不得静默失效）"
        assert "E-magnitude" in _ids("计算该表达式的值")


class TestDomainNoLongerFilters:
    """★ 回归防护：这些域此前被静默过滤，导致机制整域失效。"""

    @pytest.mark.parametrize("dom", [
        "离散数学", "非基础及进阶课程", "运筹学", "统计推断",
        "线性回归", "概率论", "随机过程", "线性回归/统计推断", "",
    ])
    def test_all_real_domains_hit(self, dom):
        got = _ids("Find the smallest positive integer n satisfying the "
                   "following property", dom=dom)
        assert got, "域 %r 被静默过滤（应命中）" % dom

    def test_original_lessons_also_hit_discrete_math(self):
        got = _ids("求所有实数解", dom="离散数学")
        assert "E-check" in got or "E-eq" in got

    def test_empty_domain_not_filtered(self):
        assert _ids("求最大值为多少", dom="") != []
        assert _ids("求最大值为多少") != []


class TestRegexTightening:
    def test_examine_does_not_trigger_extreme(self):
        """裸 min 会误匹配 examine —— 收紧后不应触发极值类清单。"""
        got = _ids("Examine the following sequence and describe its behaviour")
        assert "E-extreme" not in got
        assert "E-bound" not in got

    def test_determine_does_not_trigger_extreme(self):
        got = _ids("Determine whether the given series converges")
        assert "E-bound" not in got

    @pytest.mark.parametrize("prob", [
        "Find the maximum value of f(x)",
        "求 f(x) 的最小值",
        "Find the smallest positive integer n",
        "Find the largest n such that at least one solution exists",
        "What is the minimum possible number of moves",
        "求 m 的最大值",
    ])
    def test_extreme_phrasings_still_trigger(self, prob):
        got = _ids(prob)
        assert "E-bound" in got, "极值表述未触发: %s" % prob


class TestConsistency:
    def test_match_and_ids_same_source(self):
        prob = "Find the maximum value, and how many ways are there"
        ids = lesson_ids("离散数学", "解答题", prob)
        blk = match_lessons("离散数学", "解答题", prob)
        assert ids and blk
        assert "易错自查清单" in blk

    def test_no_hit_returns_empty_string(self):
        """无命中必须返回空串（防误伤三原则之一）。

        选择题不在任何 lesson 的 qtypes 内 ⇒ 必须零注入。
        """
        prob = "Which of the following statements is correct"
        assert match_lessons("离散数学", "选择题", prob) == ""
        assert lesson_ids("离散数学", "选择题", prob) == []
