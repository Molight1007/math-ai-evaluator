"""截图 #9 落实测试：投票选「最像答案」+ 候选数量指标 + 可信度门槛。

用户原话：
  「投票要选出里面最像答案的一个，候选数量与逻辑通顺度都要是指标，
    同时要有可信度要求（太低＝全军覆没）」

本文件覆盖三件事：
  ① `_answer_support` / `_support_of`：把「候选数量」变成可计算的口径
     （= 池里有几个**独立候选**写出了同一结论，而非单候选自评票数）；
  ② `_rank_key` 的五键序：票数 → **独立复现数** → 置信度 → 答案形态 → 紧凑度；
  ③ `_passes_confidence_floor`：「可信度太低」的判定口径（含"全弃权票=故障不算反证"）。

⚠ 每个核心断言都配**阳性对照**：若把机制退化成"恒等/永远放行"，对应用例必须红。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.base import Candidate
from agent.formatter import (
    _answer_form_score,
    _answer_support,
    _attach_support,
    _passes_confidence_floor,
    _rank_key,
    _support_of,
)


def _c(ans, cv=0, tv=0, conf=0.0, reason="", cid=0):
    """构造测试用 Candidate。

    ⚠ `Candidate`（agent/base.py:229）只有 id/answer/reasoning/revised/origin
    —— **票数字段在 `Verdict` 上**，不在 Candidate 上。运行期由
    `_verdicts_from_ver_result` / `_pick_best_raw` 的簇分支**动态挂载**到候选对象，
    `_rank_key` 用 `getattr(..., 0)` 读。
    本助手因此用 setattr 复现运行期的状态，而不是伪造一个不存在的构造签名。
    """
    c = Candidate(id=cid, answer=ans, reasoning=reason)
    c.correct_votes = int(cv)
    c.total_votes = int(tv)
    c.confidence = float(conf)
    return c


class AnswerSupportTest(unittest.TestCase):
    """① 独立复现数：口径本身。"""

    def test_counts_distinct_candidates_per_conclusion(self):
        """★ 核心：3 个候选写出同一结论 ⇒ support=3（这是"候选数量"指标）。"""
        m = _answer_support([_c("5"), _c("5"), _c("5"), _c("7")])
        self.assertEqual(m.get("5"), 3)
        self.assertEqual(m.get("7"), 1)

    def test_strips_wrappers_before_counting(self):
        """★ `\\boxed{5}` 与 `5` 是**同一结论**，不得算成两个。"""
        m = _answer_support([_c("\\boxed{5}"), _c("5"), _c(" 5 ")])
        self.assertEqual(len(m), 1)
        self.assertEqual(list(m.values())[0], 3)

    def test_non_answer_text_does_not_count(self):
        """过程叙述 / 工具标签不得被当成一个"结论"占票。"""
        m = _answer_support([_c("步骤8：重新思考——正确的下界构造"), _c("5")])
        self.assertEqual(m.get("5"), 1)
        self.assertNotIn("步骤8：重新思考——正确的下界构造".lower(), m)

    def test_empty_pool_returns_empty(self):
        self.assertEqual(_answer_support([]), {})
        self.assertEqual(_answer_support(None), {})

    def test_never_raises_on_junk(self):
        """垃圾输入绝不抛异常（择优路径不能被埋点搞挂）。"""
        for junk in ([object()], [None], [{}, _c(None)]):
            try:
                _answer_support(junk)
            except Exception as e:  # noqa: BLE001
                self.fail(f"_answer_support 不应抛异常: {e!r}")

    def test_support_of_defaults_to_one(self):
        """查不到时记 1 —— 候选自己就是一票，不罚也不奖。"""
        self.assertEqual(_support_of(_c("999"), {}), 1)
        self.assertEqual(_support_of(_c("5"), {"5": 4}), 4)

    def test_positive_control_identity_map_would_fail(self):
        """★ 阳性对照：若 support 退化成"恒 1"，下面的断言应红。"""
        m = _answer_support([_c("5"), _c("5"), _c("5")])
        self.assertNotEqual(m.get("5"), 1, "support 若恒 1 则本机制毫无作用")


class RankKeyOrderTest(unittest.TestCase):
    """② 五键序：独立复现数必须**压过**置信度，但**不越过**票数。"""

    def test_more_support_wins_at_equal_votes(self):
        """★ 核心：票数相同（都 0 票）时，被 3 个候选复现的结论胜出。"""
        a = _c("5", reason="短")
        b = _c("7", conf=0.99, reason="长")
        setattr(a, "_support_n", 3)
        setattr(b, "_support_n", 1)
        self.assertGreater(_rank_key(a), _rank_key(b))

    def test_votes_still_dominate_support(self):
        """⚠ 票数是第 1 键：1 张真正确票必须胜过"3 个候选只是互相复现"。"""
        a = _c("5", cv=1)
        b = _c("7")
        setattr(a, "_support_n", 1)
        setattr(b, "_support_n", 3)
        self.assertGreater(_rank_key(a), _rank_key(b))

    def test_form_score_is_third_after_support_and_confidence(self):
        """「最像答案」在 support/conf 之后 —— 证据优先，形态其次。"""
        boxed = _c("\\boxed{5}")
        prose = _c("经过推导可得答案为 5")
        setattr(boxed, "_support_n", 1)
        setattr(prose, "_support_n", 1)
        self.assertGreater(_rank_key(boxed), _rank_key(prose))

    def test_missing_support_attr_defaults_to_one(self):
        """★ 兼容性：未挂 `_support_n` 的旧调用点行为与改动前一致。"""
        a = _c("5", cv=2, conf=1.0)
        b = _c("7", cv=1, conf=1.0)
        self.assertGreater(_rank_key(a), _rank_key(b))

    def test_attach_support_is_idempotent(self):
        """重复挂载不改变结果（幂等）。"""
        cs = [_c("5", cid=1), _c("5", cid=2), _c("7", cid=3)]
        _attach_support(cs)
        first = [_rank_key(x) for x in cs]
        _attach_support(cs)
        self.assertEqual(first, [_rank_key(x) for x in cs])
        self.assertEqual(getattr(cs[0], "_support_n"), 2)

    def test_attach_support_never_raises(self):
        try:
            _attach_support(None)
            _attach_support([None])
        except Exception as e:  # noqa: BLE001
            self.fail(f"_attach_support 不应抛异常: {e!r}")

    def test_positive_control_old_order_would_fail(self):
        """★ 阳性对照：若 `_rank_key` 仍只有四键（无 support），本断言应红。"""
        a = _c("5")
        b = _c("7", conf=0.9)
        setattr(a, "_support_n", 3)
        setattr(b, "_support_n", 1)
        self.assertEqual(len(_rank_key(a)), 5, "键数必须是 5（新增 support）")
        self.assertGreater(_rank_key(a), _rank_key(b))


class ConfidenceFloorTest(unittest.TestCase):
    """③ 可信度门槛：太低 ⇒ 显式标记（而非静默提交）。"""

    def test_floor_disabled_always_passes(self):
        """默认 0.0 = 关闭 ⇒ 恒放行（行为与改动前一致）。"""
        ok, why = _passes_confidence_floor(_c("5"), 0.0)
        self.assertTrue(ok)
        self.assertEqual(why, "floor_disabled")

    def test_high_confidence_passes(self):
        ok, why = _passes_confidence_floor(_c("5", cv=3, tv=3, conf=1.0), 0.6)
        self.assertTrue(ok)
        self.assertEqual(why, "confidence_ok")

    def test_low_confidence_is_rejected(self):
        """★ 核心：0 正确票 ⇒ 低于门槛。"""
        ok, why = _passes_confidence_floor(_c("5", cv=0, tv=3, conf=0.0), 0.6)
        self.assertFalse(ok)
        self.assertEqual(why, "below_floor")

    def test_at_least_one_correct_vote_passes(self):
        """★ 有一张真正确票即放行 —— 门槛不该把"多数否决但有人支持"一棒打死。"""
        ok, why = _passes_confidence_floor(_c("5", cv=1, tv=3, conf=0.333), 0.6)
        self.assertTrue(ok)
        self.assertEqual(why, "has_correct_vote")

    def test_all_abstain_is_infrastructure_failure_not_disproof(self):
        """★★ 关键：全弃权票（total_votes=0）= LLM 故障，**不是**"答案错"。

        若把故障当反证，会在大面积超时的一轮里把所有题都标成"不可信"
        —— 与 `Verdict.abstain` 的既有三态口径矛盾。
        """
        ok, why = _passes_confidence_floor(_c("5", cv=0, tv=0, conf=0.0), 0.6)
        self.assertTrue(ok)
        self.assertEqual(why, "no_effective_votes")

    def test_never_raises_on_junk(self):
        for junk in (object(), None):
            try:
                _passes_confidence_floor(junk, 0.6)
            except Exception as e:  # noqa: BLE001
                self.fail(f"_passes_confidence_floor 不应抛异常: {e!r}")

    def test_positive_control_always_pass_would_fail(self):
        """★ 阳性对照：若门槛退化成"恒放行"，本断言应红。"""
        ok, _ = _passes_confidence_floor(_c("5", cv=0, tv=3, conf=0.0), 0.6)
        self.assertFalse(ok, "门槛若恒放行则本机制毫无作用")


class AnswerFormScoreSanityTest(unittest.TestCase):
    """「最像答案」的既有口径回归（本次未改，仅锁住契约防被顺手改坏）。"""

    def test_boxed_beats_prose(self):
        self.assertGreater(_answer_form_score("\\boxed{5}"),
                           _answer_form_score("因此答案是五"))

    def test_short_math_beats_prose(self):
        self.assertGreater(_answer_form_score("1012"),
                           _answer_form_score("通过上述推导可以得出结论为1012"))

    def test_empty_is_zero(self):
        self.assertEqual(_answer_form_score(""), 0)


if __name__ == "__main__":
    unittest.main()
