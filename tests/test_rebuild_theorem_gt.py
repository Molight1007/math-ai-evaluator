"""标注表重建（tools/rebuild_theorem_gt.py）单测。

背景（用户 2026-09-29 提问「每题才 2-4 个定理是不是不够，太少了」）
------------------------------------------------------------------
追下去发现两层问题：

1. **截断**：`build_theorem_gt.py:134` 写的是 `req = hits[:top_n]`，
   `top_n` 默认 4。而检索实测命中 5-10 条（题干越长命中越多）。
   基准被硬砍成 4 条 —— 这才是"太少"的直接原因。

2. **第一轮修法用错了药**：`theorem_gt_dedup.py` 拿「横跨 >5 题就降级」
   当泛化判据，一刀切 ⇒ 24 题只剩 1 条 required，基准失去区分度。

3. **实现层噪音**：检索是纯关键词匹配，题干含 "choose" 就匹到
   `Tactic.Choose.ChooseArg.name` —— 那是 Lean 战术的实现代码，
   不是数学定理。

本文件的职责：把「不截断 + 只剔通用词 + 剔实现层」这三件事钉死。
"""

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.dirname(_HERE)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.rebuild_theorem_gt import (  # noqa: E402
    analyze, is_non_theorem, last_segment, UNIVERSAL, NON_THEOREM_MARKERS)


# --------------------------------------------------------------------------
# is_non_theorem：实现层声明识别
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "Mathlib.Tactic.Choose.elabChoose",
    "Tactic.Choose.ChooseArg.name",
    "Mathlib.Meta.NormNum.evalMul",
    "Mathlib.Simp.Attr.simp",
    "Mathlib.Syntax.Macro.toSyntax",
    "Mathlib.LibraryNote.foo",
    "Mathlib.MinImports.basic",
])
def test_detects_lean_implementation_declarations(name):
    """实测案例：题干含 "choose four distinct numbers" ⇒ 匹到 choose 战术实现。"""
    assert is_non_theorem(name) is True


@pytest.mark.parametrize("name", [
    "Mathlib.Data.Fintype.Perm.card_perms_of_finset",
    "Mathlib.Order.Rearrangement.Monovary.sum_comp_perm_smul_le_sum_smul",
    "Mathlib.Analysis.SpecialFunctions.Gamma.Basic",
    "Mathlib.Topology.Continuous.Continuous.tendsto",
])
def test_does_not_flag_real_theorems(name):
    """反向对照：真数学定理必须不被误杀。

    注意 `Mathlib.Topology.Continuous.Continuous.tendsto` 里没有 `.Tactic.`，
    但路径里有 `Continuous` —— 若黑名单写成宽松的 `Choice`/`Continuous`
    就会误伤。这里钉住"只按路径片段匹配"。
    """
    assert is_non_theorem(name) is False


def test_non_theorem_markers_are_path_fragments_not_bare_words():
    """黑名单必须是**带点的路径片段**，否则 `map` 之类会误伤一切。"""
    for k in NON_THEOREM_MARKERS:
        assert "." in k, f"黑名单项 {k!r} 太宽松，会误伤真定理"


# --------------------------------------------------------------------------
# last_segment：黑名单匹配用（**不是**展示用，别搞混）
# --------------------------------------------------------------------------

def test_last_segment_is_for_blacklist_matching():
    """`last_segment` 取末段，专供黑名单匹配 —— 因此它**故意**不区分同名。"""
    a = "Mathlib.Data.Finite.Perm.Nat.card_perm"
    b = "Mathlib.Data.Fintype.Perm.Fintype.card_perm"
    assert last_segment(a) == last_segment(b) == "card_perm"
    assert last_segment(a) in UNIVERSAL   # 正是靠这个匹配上黑名单


def test_review_sheet_short_of_is_disambiguating():
    """展示用的短名必须可区分（两个末段同名的定理不能显示成同一行）。

    这是实际踩过的坑：审核清单里出现两行一模一样的 `card_perm`，
    人无法判断该删哪一个。
    """
    from tools.theorem_review_sheet import disambiguate
    names = ["Mathlib.Data.Finite.Perm.Nat.card_perm",
             "Mathlib.Data.Fintype.Perm.Fintype.card_perm"]
    disp = [d for d, _ in disambiguate(names, {})]
    assert len(set(disp)) == 2, f"显示名冲突未解决：{disp}"


# --------------------------------------------------------------------------
# analyze：核心重建逻辑
# --------------------------------------------------------------------------

def _probe(**hits_by_q):
    return {q: {"hits": h} for q, h in hits_by_q.items()}


def test_does_not_truncate_required():
    """★ 核心回归：命中 10 条就保留 10 条，绝不砍到 4。"""
    hits = [f"Mathlib.X.T{i}" for i in range(10)]
    rows = [{"id": "q1", "domain": "d"}]
    res = analyze(rows, _probe(q1=hits), universal_span_ratio=0.30)
    assert len(res["rows_out"][0]["required"]) == 10


def test_universal_words_go_to_optional():
    """横跨超阈值的通用词移到 optional，不算 required。"""
    # 3 道题都命中 common ⇒ 跨度 3；阈值 ratio=0.30 * 3 题 = 0（int 截断）
    # 用 10 题更清晰：阈值 = 3 题
    hits = {f"q{i}": ["Mathlib.Common.c", f"Mathlib.Specific.s{i}"]
            for i in range(10)}
    # 让 common 出现在全部 10 题 ⇒ 跨度 10 > 3
    rows = [{"id": f"q{i}", "domain": "d"} for i in range(10)]
    res = analyze(rows, _probe(**hits), universal_span_ratio=0.30)
    for r in res["rows_out"]:
        assert "Mathlib.Common.c" not in r["required"]
        assert "Mathlib.Common.c" in r["optional"]


def test_blacklist_matches_by_short_name():
    """黑名单按末段短名匹配：`...Finset.card` 也应被识为通用词。"""
    hits = {"q1": ["Mathlib.Data.Finset.Card.Finset.card", "Mathlib.X.Real_t1"]}
    rows = [{"id": "q1", "domain": "d"}]
    res = analyze(rows, _probe(**hits), universal_span_ratio=0.99)
    assert "Mathlib.Data.Finset.Card.Finset.card" in res["rows_out"][0]["optional"]
    assert last_segment("Mathlib.Data.Finset.Card.Finset.card") in UNIVERSAL


def test_non_theorem_hits_are_dropped_from_both_sides():
    """实现层声明既不在 required 也不在 optional —— 它根本不是定理。"""
    hits = {"q1": ["Tactic.Choose.ChooseArg.name", "Mathlib.X.Real_t1"]}
    rows = [{"id": "q1", "domain": "d"}]
    res = analyze(rows, _probe(**hits), universal_span_ratio=0.99)
    r = res["rows_out"][0]
    assert "Tactic.Choose.ChooseArg.name" not in r["required"]
    assert "Tactic.Choose.ChooseArg.name" not in r["optional"]
    assert r["evidence"]["n_dropped_non_theorem"] == 1


def test_span_is_recorded_for_manual_review():
    """每条命中都要带跨度，人工审核靠它判断"题目特异 vs 泛化"。"""
    hits = {"q1": ["Mathlib.A.a", "Mathlib.B.b"],
            "q2": ["Mathlib.A.a"]}
    rows = [{"id": "q1", "domain": "d"}, {"id": "q2", "domain": "d"}]
    res = analyze(rows, _probe(**hits), universal_span_ratio=0.99)
    sp = res["rows_out"][0]["span"]
    assert sp["Mathlib.A.a"] == 2      # 跨 2 题
    assert sp["Mathlib.B.b"] == 1      # 跨 1 题


def test_every_question_keeps_at_least_one_required():
    """剔除不能把某题清空 —— 空 required 的题不可评。"""
    hits = {"q1": ["Mathlib.X.Real_t1", "Mathlib.X.Real_t2"]}
    rows = [{"id": "q1", "domain": "d"}]
    res = analyze(rows, _probe(**hits), universal_span_ratio=0.99)
    assert res["rows_out"][0]["required"]


def test_question_with_no_hits_is_reported_not_crashed():
    hits = {"q1": []}
    rows = [{"id": "q1", "domain": "d"}]
    res = analyze(rows, _probe(**hits), universal_span_ratio=0.30)
    assert res["rows_out"][0]["required"] == []
    assert res["stats"]["n_q_without_required"] == 1


# --------------------------------------------------------------------------
# 真实数据护栏
# --------------------------------------------------------------------------

_GT = os.path.join(_SRC, "data", "theorem_ground_truth",
                   "official112_theorems.jsonl")


@pytest.mark.skipif(not os.path.exists(_GT), reason="标注表不在本机")
def test_real_gt_is_not_over_truncated():
    """★ 回归护栏：真实标注表不得再退化成"每题 2-4 条"。"""
    import io
    import json
    rows = []
    for l in io.open(_GT, encoding="utf-8"):
        s = l.strip()
        if s and not s.startswith("#"):
            rows.append(json.loads(s))
    assert len(rows) == 112
    n_req = [len(r.get("required") or []) for r in rows]
    assert sum(n_req) / len(n_req) >= 5.0, (
        f"required 平均只剩 {sum(n_req)/len(n_req):.2f} 条/题，疑似又被截断"
    )
    assert all(n >= 1 for n in n_req), "有题的 required 被清空了"


@pytest.mark.skipif(not os.path.exists(_GT), reason="标注表不在本机")
def test_real_gt_contains_no_implementation_declarations():
    """真实标注表里不应有任何 Tactic/Meta 层实现声明。"""
    import io
    import json
    bad = []
    for l in io.open(_GT, encoding="utf-8"):
        s = l.strip()
        if s and not s.startswith("#"):
            r = json.loads(s)
            for nm in (r.get("required") or []):
                if is_non_theorem(nm):
                    bad.append((r["id"], nm))
    assert bad == [], f"标注表混入实现层声明：{bad[:5]}"
