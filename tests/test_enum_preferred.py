# -*- coding: utf-8 -*-
"""`enum_preferred` 枚举优先分支的回归测试（2026-09-16）。

## 背景（用户直接质问"为什么有正确答案却选了错的"）

实测 `official112-003` 的真实候选：

| 候选 | 答案 | 票数 | 置信度 |
|---|---|---|---|
| 0 | `\\boxed{2025}` | 1/3 | 0.333 |
| **1** | **`\\boxed{2026}`** | **2/3** | **0.667** | ← 2026 是**正确答案之一** |
| 2 | `\\boxed{2026}` | 0/3 | 0.000 |
| 3 | `\\boxed{}`（空） | 0/3 | 0.000 |
| 4 | `\\boxed{1013}` | 0/3 | 0.000 |
| 5 | `\\boxed{0,1,2,3,\\ldots}` | **0/3** | **0.000** |

标准答案是 `2026, 2030`。**旧实现却选中了候选 5**（`pick_diag.branch="enum_preferred"`）。

### 旧实现的三重缺陷
1. **"枚举"判据只是"含逗号"** ⇒ 省略号糊弄式伪答案 `0,1,2,3,\\ldots` 也算枚举；
2. **排序只看 `len(reasoning)`** ⇒ 完全无视票数/置信度 ⇒ 0 票的长文本胜过 2 票的正确答案；
3. **直接 `return`** ⇒ 绕过后面全部正常选答逻辑（聚类 → 置信度 → 多数票）。

### 修法
- 新增 `_PSEUDO_ENUM_RE` 过滤伪枚举（省略号 / "等等" / "以此类推" …）；
- 排序改为 `(correct_votes, confidence, len(reasoning))` 词典序；
- 判据与排序都保留原设计意图：题面求"所有"时，**合法**枚举确实优于单值。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.formatter import _PSEUDO_ENUM_RE  # noqa: E402


class PseudoEnumRegexTest(unittest.TestCase):
    """伪枚举识别：省略号/未写全的形式不是合法枚举答案。"""

    def test_rejects_ellipsis_forms(self):
        for s in (r"0,1,2,3,\ldots", r"1,2,3,...", r"0,1,2,\cdots",
                  "0,1,2,…", r"1,2,\ldots,n", "a,b,等等", "x,y,以此类推"):
            with self.subTest(s=s):
                self.assertTrue(_PSEUDO_ENUM_RE.search(s),
                                "%r 应被判为伪枚举" % s)

    def test_accepts_real_enumerations(self):
        for s in ("0,2026", "2026, 2030", "10,20,30", "2026、2030",
                  "a, b, c", "1,2,3"):
            with self.subTest(s=s):
                self.assertFalse(_PSEUDO_ENUM_RE.search(s),
                                 "%r 是合法枚举，不该被排除" % s)


class EnumSelectionOrderingTest(unittest.TestCase):
    """排序必须优先看票数/置信度，而不是推理长度。"""

    class _C:
        def __init__(self, answer, votes, conf, rlen):
            self.answer = answer
            self.correct_votes = votes
            self.confidence = conf
            self.reasoning = "x" * rlen

    def _pick(self, cands):
        """复刻 formatter 的枚举优先排序逻辑（与生产代码同序）。"""
        enum_c = []
        for c in cands:
            core = c.answer
            if "," in core or "，" in core:
                if _PSEUDO_ENUM_RE.search(core):
                    continue
                enum_c.append(c)
        if not enum_c:
            return None
        enum_c.sort(key=lambda c: (c.correct_votes, c.confidence,
                                   len(c.reasoning)), reverse=True)
        return enum_c[0]

    def test_pseudo_enum_is_excluded_and_falls_through(self):
        """★ 核心回归：003 的真实候选分布下，不该再选中伪枚举。"""
        cands = [
            self._C(r"\boxed{2025}", 1, 0.333, 900),
            self._C(r"\boxed{2026}", 2, 0.667, 500),
            self._C(r"\boxed{2026}", 0, 0.0, 400),
            self._C(r"\boxed{}", 0, 0.0, 100),
            self._C(r"\boxed{1013}", 0, 0.0, 300),
            self._C(r"\boxed{0,1,2,3,\ldots}", 0, 0.0, 99999),  # 推理最长
        ]
        self.assertIsNone(
            self._pick(cands),
            "伪枚举必须被排除 ⇒ 枚举候选为空 ⇒ 落回正常选答（置信度）")

    def test_real_enum_wins_over_longer_pseudo(self):
        """有**合法**枚举时，票数/置信度高者胜，而不是推理最长者。"""
        cands = [
            self._C(r"\boxed{2026}", 2, 0.667, 100),
            self._C(r"\boxed{10,20,30}", 1, 0.333, 99999),
        ]
        got = self._pick(cands)
        self.assertIsNotNone(got)
        self.assertEqual(got.answer, r"\boxed{10,20,30}",
                         "题面求『所有』时合法枚举优先于单值")

    def test_tie_broken_by_confidence_then_length(self):
        cands = [
            self._C(r"\boxed{1,2}", 2, 0.5, 10),
            self._C(r"\boxed{3,4}", 2, 0.9, 10),
        ]
        self.assertEqual(self._pick(cands).answer, r"\boxed{3,4}",
                         "同票数时按置信度")


if __name__ == "__main__":
    unittest.main()
