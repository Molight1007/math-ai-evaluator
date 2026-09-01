# -*- coding: utf-8 -*-
"""跨题定理复用记忆（TheoremMemory）单元测试。

覆盖:
- record_hit: 按域记录 + 命中计数
- top_theorems: 按 hits 降序返回高频定理
- 持久化: 重新加载后数据仍在（模拟跨进程）
- 原子写: 多次写入后文件仍是合法 JSON
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TheoremMemoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.path = os.path.join(self._tmp, "theorem_memory.json")

    def test_record_and_rank(self) -> None:
        from agent.theorem_memory import TheoremMemory
        m = TheoremMemory(self.path)
        m.record_hit("Number theory", "gcd_dvd")
        m.record_hit("Number theory", "gcd_dvd")
        m.record_hit("Number theory", "IsPrimePow")
        m.record_hit("Algebra", "sq_nonneg")
        self.assertEqual(m.top_theorems("Number theory", 3),
                         ["gcd_dvd", "IsPrimePow"])  # 按命中数降序
        self.assertEqual(m.top_theorems("Algebra", 3), ["sq_nonneg"])
        self.assertEqual(m.top_theorems("Geometry", 3), [])  # 空域

    def test_persistence_across_instances(self) -> None:
        from agent.theorem_memory import TheoremMemory
        TheoremMemory(self.path).record_hit("Number theory", "dvd_add")
        m2 = TheoremMemory(self.path)  # 重新加载 = 模拟新进程
        self.assertIn("dvd_add", m2.top_theorems("Number theory", 5))

    def test_atomic_write_valid_json(self) -> None:
        from agent.theorem_memory import TheoremMemory
        m = TheoremMemory(self.path)
        for i in range(20):
            m.record_hit("Number theory", f"thm_{i % 5}")
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)  # 必须是合法 JSON
        self.assertEqual(data["Number theory"]["thm_0"]["hits"], 4)

    def test_ignore_unknown_domain(self) -> None:
        from agent.theorem_memory import TheoremMemory
        m = TheoremMemory(self.path)
        m.record_hit("", "gcd_dvd")     # 空域忽略
        m.record_hit("unknown", "gcd_dvd")  # unknown 忽略
        m.record_hit("Number theory", "")  # 空定理名忽略
        self.assertEqual(m.domain_summary(), {})

    # ---- 9/1 增：陈旧过滤（staleness）测试 ----
    def test_stale_days_filter(self) -> None:
        """stale_days>0 时，last_seen 超过阈值的定理被排除；不影响未过期的定理。"""
        from agent.theorem_memory import TheoremMemory
        m = TheoremMemory(self.path)
        now = int(time.time())
        with m._lock:
            # 注入：old_thm 60 天前用过；recent_thm 昨天用过
            m._data["Number theory"] = {
                "old_thm":   {"hits": 10, "first_seen": now - 90*86400,
                              "last_seen": now - 60*86400},
                "recent_thm": {"hits": 1,  "first_seen": now - 86400,
                               "last_seen": now - 86400},
            }
        # 默认（关闭）：返回按 hits 降序全集
        self.assertEqual(m.top_theorems("Number theory", 5),
                         ["old_thm", "recent_thm"])
        # stale_days=30：old_thm 被排除；recent_thm 保留
        self.assertEqual(m.top_theorems("Number theory", 5, stale_days=30),
                         ["recent_thm"])
        # stale_days=0 / None：明确关闭
        self.assertEqual(m.top_theorems("Number theory", 5, stale_days=0),
                         ["old_thm", "recent_thm"])
        self.assertEqual(m.top_theorems("Number theory", 5, stale_days=None),
                         ["old_thm", "recent_thm"])

    def test_stale_days_fallback_when_all_stale(self) -> None:
        """退路保护：全集都陈旧时退回全集（防冷启动/数据稀疏时静默丢失）。"""
        from agent.theorem_memory import TheoremMemory
        m = TheoremMemory(self.path)
        now = int(time.time())
        with m._lock:
            m._data["Number theory"] = {
                "very_old": {"hits": 5, "first_seen": now - 200*86400,
                             "last_seen": now - 100*86400},
            }
        # stale_days=30 → 应过滤；过滤后空 → 退回全集
        self.assertEqual(m.top_theorems("Number theory", 5, stale_days=30),
                         ["very_old"])


if __name__ == "__main__":
    unittest.main()
