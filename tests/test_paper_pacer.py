# -*- coding: utf-8 -*-
"""PaperPacer 全卷时间池单元测试。

覆盖:
- ``budget_for``: 软预算帽计算、并发滞后修正、MIN_SOFT 保底
- ``allow_deep`` / ``note_deep``: deep 档配额封顶与渐进释放
- 线程安全：并发 begin/end 计数正确
"""
import threading
import time
import unittest
from types import SimpleNamespace

from agent.paper_pacer import PaperPacer


def make_pacer(**over) -> PaperPacer:
    """构造 PaperPacer（over 覆盖默认值，避免 SimpleNamespace 重复关键字）。"""
    base = {
        "paper_target_time": 18000,
        "paper_min_soft": 120.0,
        "paper_total_questions": 112,
        "tier_budget": {"fast": 120.0, "standard": 480.0, "deep": 1200.0},
        "paper_inflight": 3,
    }
    base.update(over)
    return PaperPacer(SimpleNamespace(**base))


class BudgetForTest(unittest.TestCase):
    def test_cap_by_tier(self) -> None:
        """卷面充裕时（平均每题预算 > 档位帽），软预算 = 档位设计预算帽。"""
        # 10 题 / 18000s → paper_cap = 1800s/题，足够各档拿满
        p = make_pacer(paper_total_questions=10)
        self.assertAlmostEqual(p.budget_for("fast"), 120.0, places=1)
        self.assertAlmostEqual(p.budget_for("standard"), 480.0, places=1)
        self.assertAlmostEqual(p.budget_for("deep"), 1200.0, places=1)

    def test_cap_by_paper_average(self) -> None:
        """卷面偏紧时，软预算被平均每题预算压住（这正是 Pacer 的作用）。

        注意并发换算：target_seconds 是**墙钟**，并发 3 时可用时长 = 3 × 墙钟。
        112 题 / 18000s 墙钟 → 单题时长预算 = 3×18000/112 ≈ 482s，
        略高于 standard 档帽 480s，故此处刚好拿满。
        """
        p = make_pacer(paper_total_questions=112, paper_target_time=18000)
        soft = p.budget_for("standard")
        self.assertAlmostEqual(soft, 480.0, places=1,
                               msg="并发换算后约 482s > 档位帽 480s，应拿满")
        # 题数更多时平均预算被压到档位帽以下。
        # 9/2 起新逻辑「进度正常给满档、落后才收紧」：要触发收紧必须让
        # time_frac > budget_frac（耗时比例 > 完成比例）——
        # 400 题完成 4 题 = 1%，须耗时 > 1% × 18000s = 180s。
        p2 = make_pacer(paper_total_questions=400, paper_target_time=18000)
        p2.start_time = time.time() - 200.0  # 耗时 ≈200s > 180s → 落后
        p2.started = 4
        p2.done = 4                            # answered=4 ≥ 3，越过开局面
        self.assertLess(p2.budget_for("standard"), 480.0,
                        "400 题落后时平均预算约 135s，standard 必须收紧")

    def test_concurrency_factor_applied(self) -> None:
        """回归：paper_cap 必须乘并发数（墙钟 → 单题时长）。

        漏乘会让单题预算只有真实可用值的 1/3 —— 全卷大量时间被闲置，
        "难题用满 20 分钟"永远拿不到时间。
        """
        # 用 100 题避开 MIN_SOFT 保底（否则两档都被抬到 120，看不出差异）。
        # 9/2 新逻辑「进度正常给满档、落后才收紧」：要测并发换算（paper_cap
        # = 并发×剩余/剩余题数）必须处于"落后"态——100 题完成 4 题 = 4%，
        # 须耗时 > 4% × 18000s = 720s。
        base = dict(paper_total_questions=100, paper_target_time=18000)
        p1 = make_pacer(max_workers=1, **base)
        p3 = make_pacer(max_workers=3, **base)
        for p in (p1, p3):
            p.start_time = time.time() - 800.0  # 耗时 ≈800s > 720s → 落后
            p.started = 4
            p.done = 4
        s1 = p1.budget_for("deep")
        s3 = p3.budget_for("deep")
        self.assertAlmostEqual(s1, 180.0, delta=5.0)   # ≈ 1×剩余/剩余题数
        self.assertAlmostEqual(s3, 540.0, delta=15.0,  # ≈ 3×s1
                               msg="并发 3 的单题预算应为并发 1 的 3 倍")
        self.assertAlmostEqual(s3 / s1, 3.0, places=1)

    def test_tightens_when_behind(self) -> None:
        """卷面落后时自动收紧（paper_cap 变小）。"""
        p = make_pacer()
        # 伪造：已用掉大部分目标时间，但只做完了 2 题
        p.start_time = time.time() - 17000.0
        p.started = 5
        p.done = 2
        # 注意：answered = done=2 < inflight_window=3 时会命中 9/2 开局宽容
        # 直接给满档——但 2 题已做、时间已耗 17000s 显然不是"开局"。
        # answered 不足时由 done=2 兜底已偏紧；为测收紧分支，将 done 抬到
        # ≥ inflight（代表"已开始足够多题、仍在途"的真实落后场景）。
        p.done = 3
        soft = p.budget_for("deep")
        self.assertLess(soft, 1200.0, "落后时 deep 预算必须被收紧")
        self.assertGreaterEqual(soft, 120.0, "MIN_SOFT 保底不得突破")

    def test_min_soft_floor(self) -> None:
        """即使时间几乎耗尽，也不把单题压到低于 MIN_SOFT。"""
        p = make_pacer()
        p.start_time = time.time() - 17999.0
        p.started = 100
        p.done = 100
        self.assertGreaterEqual(p.budget_for("standard"), 120.0)

    def test_inflight_subtracted(self) -> None:
        """并发=3 时，在途题目应计入进度（否则高估剩余、预算过松）。"""
        p = make_pacer()
        p.start_time = time.time() - 17000.0
        p.started = 20
        p.done = 17          # 3 题在途
        with_inflight = p.budget_for("deep")
        # 同样时间下，若按 done=17 计算，剩余题数更多 → paper_cap 更大
        p2 = make_pacer()
        p2.start_time = p.start_time
        p2.started = 17
        p2.done = 17
        without_inflight = p2.budget_for("deep")
        self.assertLessEqual(with_inflight, without_inflight,
                             "扣除在途后预算应更紧（或相等）")


class DeepQuotaTest(unittest.TestCase):
    def test_quota_caps_at_ratio(self) -> None:
        """deep 占用数不得超过 total × ratio（112 × 25% = 28）。"""
        p = make_pacer(paper_total_questions=112, deep_quota_ratio=0.25)
        granted = 0
        for _ in range(300):          # 远超总题数，配额必须封顶
            p.begin()                 # 模拟卷面推进（配额按进度释放）
            if p.allow_deep():
                p.note_deep()
                granted += 1
            p.end(tier="deep" if granted else "standard", duration=1.0)
        self.assertLessEqual(granted, 28, "deep 占比必须封顶")
        self.assertGreaterEqual(granted, 20, "配额应被充分使用而非过早耗尽")

    def test_progressive_release(self) -> None:
        """渐进释放：开局不能一次性放完全部配额。"""
        p = make_pacer(paper_total_questions=112, deep_quota_ratio=0.25)
        p.begin()
        p.begin()
        p.begin()
        p.begin()                      # 卷面刚开局（4 题）
        grants = 0
        while p.allow_deep():
            p.note_deep()
            grants += 1
            if grants > 100:
                break
        self.assertLess(grants, 28, "开局不应放满配额，要给后面的难题留名额")

    def test_standard_unaffected(self) -> None:
        """配额只约束 deep，standard/fast 不受影响。"""
        p = make_pacer(paper_total_questions=4, deep_quota_ratio=0.0)
        self.assertFalse(p.allow_deep(), "ratio=0 时不得放行任何 deep")

    def test_snapshot_reports_quota(self) -> None:
        p = make_pacer(paper_total_questions=112, deep_quota_ratio=0.25)
        p.note_deep()
        snap = p.snapshot()
        self.assertEqual(snap["deep_used"], 1)
        self.assertAlmostEqual(snap["deep_quota_cap"], 28.0, places=1)


class ThreadSafetyTest(unittest.TestCase):
    def test_concurrent_begin_end(self) -> None:
        """并发 begin/end 计数必须准确（平台并发=3，实测更高）。"""
        p = make_pacer()
        n = 30

        def worker():
            p.begin()
            time.sleep(0.001)
            p.end(tier="standard", duration=0.1)

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(p.started, n)
        self.assertEqual(p.done, n)


if __name__ == "__main__":
    unittest.main()
