# -*- coding: utf-8 -*-
"""leansearch 查询规范化单元测试（2026-08-29 修复"中文查询全空"）。

覆盖:
- ``normalize_query``: 中文/LaTeX → mathlib 风格英文关键词
- 强信号词提取与过泛词剔除
- 规范化后的检索能命中真实相关定理（素数→IsPrimePow、最大公约数→gcd_dvd）
"""
import sys
import unittest

sys.path.insert(0, ".")


class NormalizeQueryTest(unittest.TestCase):
    def test_chinese_to_english(self) -> None:
        from agent.lean_search import normalize_query
        aug, strong = normalize_query("素数有无穷多个")
        self.assertIn("prime", aug)
        self.assertIn("prime", strong)

    def test_latex_to_keywords(self) -> None:
        from agent.lean_search import normalize_query
        aug, strong = normalize_query("x^2 >= 0")
        self.assertIn("sq", aug)
        self.assertIn("greater", aug)
        self.assertTrue(strong)  # 有强信号词

    def test_weak_keywords_excluded(self) -> None:
        """real/integer 等泛词不当强信号，避免噪声命中。"""
        from agent.lean_search import normalize_query, _WEAK_KEYWORDS
        aug, strong = normalize_query("对所有实数 x 证明不等式")
        self.assertTrue(strong)
        for w in strong:
            self.assertNotIn(w, _WEAK_KEYWORDS)

    def test_gcd_query_extracts_strong(self) -> None:
        from agent.lean_search import normalize_query
        aug, strong = normalize_query("证明两个数的最大公约数整除它们的和")
        self.assertIn("gcd", strong)
        self.assertIn("dvd", strong)

    def test_empty_query(self) -> None:
        from agent.lean_search import normalize_query
        self.assertEqual(normalize_query(""), ("", []))
        self.assertEqual(normalize_query(None), ("", []))


class SearchRelevanceTest(unittest.TestCase):
    """真实检索相关性（需要本地 mathlib 源码；环境缺失时跳过）。"""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from agent.lean_search import MathlibTheoremSearcher
            cls.searcher = MathlibTheoremSearcher()
        except Exception:  # noqa: BLE001
            cls.searcher = None

    def _hits(self, q: str) -> list[str]:
        if self.searcher is None:
            self.skipTest("mathlib 源码不可用")
        r = self.searcher.search(q, limit=3)
        return [x["name"] for x in (r.get("results") or [])]

    def test_prime_query_hits(self) -> None:
        names = self._hits("素数有无穷多个")
        self.assertTrue(any("Prime" in n for n in names),
                        f"素数查询应命中 Prime 相关定理: {names}")

    def test_gcd_query_hits(self) -> None:
        names = self._hits("证明两个数的最大公约数整除它们的和")
        self.assertTrue(any("gcd" in n.lower() for n in names),
                        f"最大公约数查询应命中 gcd 相关定理: {names}")


if __name__ == "__main__":
    unittest.main()
