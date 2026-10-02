# -*- coding: utf-8 -*-
"""领域 → 定理检索（agent/theorem_hint.py）单测（2026-09-29，截图 #3+#4）。

覆盖：
  · query 构造（数学术语优先、领域词降级为末位、噪声词过滤）
  · 检索接口的**永不抛异常**契约（后端不可用/开关关闭/客观题 → 降级返回）
  · 命中比对（required 召回、大小写/全名短名兼容、位次）

★ 全部用 mock，**不做真检索**（真检索依赖本机 mathlib 源码树，20s+，
  且 CI/他机不一定有 ⇒ 断言不能依赖本机环境，这是项目铁律）。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.theorem_hint import (  # noqa: E402
    TheoremHit, TheoremRetrieval,
    build_queries, domain_keywords, question_keywords,
    match_against_ground_truth, retrieve_theorems_for_question,
)


class QueryBuildTest(unittest.TestCase):
    def test_math_terms_take_priority_over_generic_words(self) -> None:
        """题干含数学术语时，关键词应取术语而非 'set/number' 这类通用词。"""
        q = ("Let S be the set of all ordered pairs. Compute the number of "
             "permutations of a polynomial with distinct roots.")
        kws = question_keywords(q)
        self.assertIn("permutation", kws)
        self.assertIn("polynomial", kws)
        self.assertIn("root", kws)
        # 通用噪声词不应主导
        self.assertNotIn("number", kws)

    def test_domain_query_is_last(self) -> None:
        """★ 回归：领域 query 必须**排在最后**。

        实测教训（8 题）：领域 query 排第一时，其宽泛命中（离散数学→Finset.card
        →card_perms_of_finset）会占满 rank-1，导致同领域不同题命中列表雷同。
        """
        q = "Compute the number of permutations of a set with 19 elements."
        qs = build_queries(q, domain="离散数学")
        self.assertTrue(qs, "应至少产出一条 query")
        self.assertNotIn("Finset.card", qs[0],
                         "领域关键词不应出现在首条 query")

    def test_unknown_domain_still_yields_question_query(self) -> None:
        """未收录领域 → 仍能靠题干英文词出 query（不能因为领域未知就空转）。"""
        q = "Find the minimum value of the polynomial roots."
        qs = build_queries(q, domain="某个没收录的领域")
        self.assertTrue(any("polynomial" in x for x in qs), qs)

    def test_tex_noise_filtered(self) -> None:
        """LaTeX 残渣（ldots/leq/frac）不得进入 query。"""
        q = r"Let $a_0, a_1, \ldots$ be a sequence with $x \leq y$ and \frac{1}{2}."
        kws = question_keywords(q)
        for bad in ("ldots", "leq", "frac"):
            self.assertNotIn(bad, kws, f"{bad} 是 TeX 噪声，不应进 query")

    def test_chinese_only_problem_uses_domain(self) -> None:
        """纯中文题干抽不出英文词 → 回退领域词（保证仍有 query）。"""
        qs = build_queries("求所有正整数解。", domain="数论")
        self.assertTrue(qs, "纯中文题应回退到领域词")

    def test_answer_format_boilerplate_is_stripped(self) -> None:
        """★ 回归（真实缺陷，12 题撞车）：答案格式样板词必须当噪声剔除。

        实测 official112 的 096/101/103~111 共 12 道中文题的题干里，**唯一**
        的英文就是样板句「Remember to put your final answer within \\boxed{}」。
        不剔除时 12 题抽出完全相同的关键词 ⇒ 检索结果雷同、标注表报废
        （实测 12x 重复簇 ('upper_mem','TheoremForm','pi_le_four','form')）。
        """
        q = "在统计学中，用来表示数据分散程度的一个指标是 Remember to put your final answer within \\boxed{}."
        kws = question_keywords(q)
        for bad in ("remember", "put", "your", "final", "within", "boxed"):
            self.assertNotIn(bad, kws, f"{bad} 是答案格式样板词，必须剔除")
        # 且必须抽出有效的中文术语（而不是空的）
        self.assertTrue(kws, "中文数学题不应抽不出关键词")

    def test_chinese_math_terms_are_mapped(self) -> None:
        """★ 回归：中文数学术语必须映射成英文（否则中文题检索无效）。"""
        cases = [
            ("关于线性规划的对偶问题，下列说法正确的是", "programming"),
            ("时间序列的构成要素有", "series"),
            ("异方差性会导致参数估计量的方差", "variance"),
            ("求这个多项式的根", "polynomial"),
            ("证明这个三角形的内角和为180度", "triangle"),
        ]
        for text, must in cases:
            kws = question_keywords(text)
            self.assertTrue(
                any(must in k for k in kws),
                f"{text!r} 应抽出含 {must!r} 的关键词，实得 {kws}")

    def test_distinct_questions_yield_distinct_keywords(self) -> None:
        """★ 核心不变量：不同题目的关键词必须不同（防检索退化）。"""
        questions = [
            "求矩阵的行列式",
            "求这个数列的极限",
            "证明这个图是二分图",
            "计算组合数的值",
        ]
        seen = [tuple(question_keywords(q)) for q in questions]
        self.assertEqual(len(set(seen)), len(questions),
                         f"不同题目的关键词不应相同: {seen}")


class RetrievalContractTest(unittest.TestCase):
    """检索接口的核心契约：**任何情况下都不抛异常**。"""

    def test_disabled_by_config_returns_empty(self) -> None:
        cfg = SimpleNamespace(enable_theorem_hint=False)
        r = retrieve_theorems_for_question(
            "Compute the number of permutations.", domain="离散数学", config=cfg)
        self.assertFalse(r.ok)
        self.assertEqual(r.hits, [])
        self.assertIn("开关关闭", r.reason)

    def test_objective_question_skipped(self) -> None:
        """选择题/判断题 → 不检索（答案是选项字母/真值，定理无意义）。"""
        for qt in ("选择题", "判断题"):
            r = retrieve_theorems_for_question(
                "Which of the following is true? A. 1 B. 2 C. 3",
                domain="离散数学", question_type=qt)
            self.assertFalse(r.ok, qt)
            self.assertIn(qt, r.reason)

    def test_empty_problem_returns_empty(self) -> None:
        r = retrieve_theorems_for_question("", domain="数论")
        self.assertFalse(r.ok)
        self.assertIn("题干为空", r.reason)

    def test_backend_unavailable_degrades_gracefully(self) -> None:
        """★ 后端不可用 → 降级返回，**不抛异常**（主流程必须照常跑）。"""
        fake = SimpleNamespace(status=lambda: {"available": False})
        with patch("tools.lean_local.lean_search.MathlibTheoremSearcher",
                   return_value=fake):
            r = retrieve_theorems_for_question(
                "Compute the number of permutations of a set.",
                domain="离散数学")
        self.assertFalse(r.ok)
        self.assertEqual(r.hits, [])
        self.assertIn("不可用", r.reason)

    def test_import_failure_degrades_gracefully(self) -> None:
        """★ lean_search 导入失败 → 降级，不抛异常。"""
        with patch.dict(sys.modules, {"tools.lean_local.lean_search": None}):
            r = retrieve_theorems_for_question(
                "Compute the number of permutations.", domain="离散数学")
        self.assertFalse(r.ok)
        self.assertEqual(r.hits, [])

    def test_search_exception_degrades_gracefully(self) -> None:
        """★ 检索本身抛异常 → 被吞掉并降级（不允许冒泡）。"""
        class _Boom:
            def status(self):
                return {"available": True}

            def search(self, q, limit=5):
                raise RuntimeError("backend exploded")

        with patch("tools.lean_local.lean_search.MathlibTheoremSearcher",
                   return_value=_Boom()):
            r = retrieve_theorems_for_question(
                "Compute the number of permutations of a set.",
                domain="离散数学")
        # 不允许抛异常；应返回 ok=False 或 ok=True 但零命中
        self.assertEqual(r.hits, [])

    def test_hits_sorted_by_rank_across_queries(self) -> None:
        """★ 回归：多 query 命中必须**按位次重排**后返回。

        原实现"先到先得"会让第一条 query 的结果占满，题干 query 的命中被挤掉
        （实测同领域三题命中列表完全相同）。
        """
        calls = {"n": 0}

        class _TwoBackend:
            def status(self):
                return {"available": True}

            def search(self, q, limit=5):
                calls["n"] += 1
                if calls["n"] == 1:
                    # 第一条 query：只有 rank1 一条，且"不相关"
                    return {"results": [{"name": "Mathlib.Aaa.dom1"}]}
                # 第二条 query：rank1 是更该被保留的
                return {"results": [{"name": "Mathlib.Bbb.specific"},
                                    {"name": "Mathlib.Ccc.other"}]}

        with patch("tools.lean_local.lean_search.MathlibTheoremSearcher",
                   return_value=_TwoBackend()):
            r = retrieve_theorems_for_question(
                "Compute the number of permutations of a polynomial.",
                domain="离散数学", max_queries=2, top_k=3)
        self.assertTrue(r.ok)
        self.assertTrue(r.hits, "应有命中")
        # 两条 rank1 的（dom1 与 specific）都应在前排，且按 (rank, name) 排序
        ranks = [h.rank for h in r.hits]
        self.assertEqual(ranks, sorted(ranks), f"应按位次升序: {ranks}")


class MatchGroundTruthTest(unittest.TestCase):
    def _ret(self, names):
        r = TheoremRetrieval(ok=True, domain="d")
        r.hits = [TheoremHit(name=n, short=n.rsplit(".", 1)[-1], rank=i)
                  for i, n in enumerate(names, 1)]
        return r

    def test_all_required_hit(self) -> None:
        r = self._ret(["Mathlib.Data.Nat.Choose.Basic.Nat.choose",
                       "Mathlib.X.card_perms_of_finset"])
        m = match_against_ground_truth(
            r, {"required": ["Nat.choose", "card_perms_of_finset"]})
        self.assertEqual(m["required_hit"], 2)
        self.assertTrue(m["all_required_hit"])
        self.assertEqual(m["hit_rate"], 1.0)
        self.assertEqual(m["best_rank"], 1)

    def test_partial_hit_reports_missing_names(self) -> None:
        r = self._ret(["Mathlib.X.card_perms_of_finset"])
        m = match_against_ground_truth(
            r, {"required": ["Nat.choose", "card_perms_of_finset"]})
        self.assertEqual(m["required_hit"], 1)
        self.assertFalse(m["all_required_hit"])
        self.assertEqual(m["required_miss"], ["Nat.choose"])
        self.assertEqual(m["hit_rate"], 0.5)

    def test_full_name_in_gt_also_matches(self) -> None:
        """预标注写全名时也应命中（不能只支持短名）。"""
        full = "Mathlib.Data.Nat.Choose.Basic.Nat.choose"
        r = self._ret([full])
        m = match_against_ground_truth(r, {"required": [full]})
        self.assertEqual(m["required_hit"], 1)

    def test_empty_required_gives_none_rate(self) -> None:
        """无必中定理（如概念题）→ hit_rate 为 None，不参与 avg。"""
        r = self._ret(["Mathlib.X.foo"])
        m = match_against_ground_truth(r, {"required": []})
        self.assertIsNone(m["hit_rate"])
        self.assertFalse(m["all_required_hit"])

    def test_optional_counted_separately(self) -> None:
        r = self._ret(["Mathlib.X.foo", "Mathlib.Y.bar"])
        m = match_against_ground_truth(
            r, {"required": ["foo"], "optional": ["bar", "nope"]})
        self.assertEqual(m["optional_n"], 2)
        self.assertEqual(m["optional_hit"], 1)


class GroundTruthFileTest(unittest.TestCase):
    """预标注表格式契约（若已生成）。"""

    PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "theorem_ground_truth", "official112_theorems.jsonl")

    def test_file_parses_and_has_required_keys(self) -> None:
        if not os.path.isfile(self.PATH):
            self.skipTest("预标注表尚未生成（先跑 tools/build_theorem_gt.py）")
        n = 0
        for line in open(self.PATH, encoding="utf-8"):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            d = json.loads(s)
            self.assertIn("id", d)
            self.assertIn("required", d)
            self.assertIsInstance(d["required"], list)
            n += 1
        self.assertGreater(n, 0, "预标注表不应为空")


if __name__ == "__main__":
    unittest.main()
