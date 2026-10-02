"""标注表特异性过滤（tools/theorem_gt_dedup.py）单测。

背景（为什么必须做这件事）：
    tools/build_theorem_gt.py 早期版本把 **LeanSearch 检索结果的前 N 条**
    直接当作 required（"解本题必须用到的定理"）。而检索是**关键词泛化匹配**——
    一个短名（如 card_perms_of_finset）会被几十道题共同命中。
    于是"标准答案"与"被评测的检索结果"同源 ⇒ 命中率变成循环自证。
    官方 112 题实测：7 条定理横跨 >5 题，占 448 个 required 槽位的 32.1%。

本文件的职责：把"跨度过滤"这件事的正确性钉死，防止以后有人改回去。
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.dirname(_HERE)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tools.theorem_gt_dedup import analyze, demote, _load  # noqa: E402


# --------------------------------------------------------------------------
# 夹具
# --------------------------------------------------------------------------

def _rows(*specs):
    """specs: (req_list, opt_list) 可变长；返回可直接喂给 analyze 的行。"""
    return [
        {"id": f"q{i:03d}", "required": list(req), "optional": list(opt)}
        for i, (req, opt) in enumerate(specs)
    ]


# --------------------------------------------------------------------------
# analyze：跨度统计
# --------------------------------------------------------------------------

def test_analyze_counts_span_across_questions():
    rows = _rows(
        (["wide", "solo1"], []),
        (["wide", "solo2"], []),
        (["wide"], []),
    )
    info = analyze(rows, max_span=2)
    assert info["span_of"]["wide"] == 3
    assert info["too_common"] == ["wide"]          # 3 > 2
    assert info["n_required_slots"] == 5
    assert info["polluted_slots"] == 3             # wide 出现在 3 题
    assert info["polluted_ratio"] == pytest.approx(3 / 5)


def test_analyze_counts_span_per_question_not_per_slot():
    """同一题里 required 重复写两次，只能算 1 题跨度（否则会误伤）。"""
    rows = _rows((["dup", "dup"], []), (["other"], []), (["dup"], []))
    info = analyze(rows, max_span=1)
    # dup 出现在 2 道题里（q000 写了两遍仍算 1），所以跨度是 2 而不是 3
    assert info["span_of"]["dup"] == 2
    assert "dup" in info["too_common"]


def test_analyze_boundary_is_strictly_greater_than():
    """阈值语义：跨度 == max_span 时**不**降级（必须是 > ）。"""
    rows = _rows((["edge"], []), (["edge"], []))
    info = analyze(rows, max_span=2)
    assert "edge" not in info["too_common"]
    info2 = analyze(rows, max_span=1)
    assert "edge" in info2["too_common"]


def test_analyze_handles_empty_required():
    rows = [{"id": "q1"}, {"id": "q2", "required": None}]
    info = analyze(rows, max_span=5)
    assert info["n_required_slots"] == 0
    assert info["polluted_ratio"] == 0.0           # 不能除零
    assert info["too_common"] == []


def test_analyze_orders_too_common_by_descending_span():
    rows = _rows((["a", "b", "c"], []),
                 (["a", "b"], []),
                 (["a"], []))
    info = analyze(rows, max_span=1)
    # a 跨 3 题 -> 降级；b 跨 2 题 -> 降级；c 只跨 1 题（=阈值，不降级）
    assert info["too_common"] == ["a", "b"]
    assert info["span_of"] == {"a": 3, "b": 2}


# --------------------------------------------------------------------------
# demote：执行降级
# --------------------------------------------------------------------------

def test_demote_moves_from_required_to_optional():
    rows = _rows((["wide", "keep"], []), (["wide"], []), (["wide"], []))
    changed, moved, info = demote(rows, max_span=2)
    assert changed == 3 and moved == 3
    assert rows[0]["required"] == ["keep"]
    assert "wide" in rows[0]["optional"]
    assert rows[1]["required"] == []


def test_demote_never_drops_a_theorem_entirely():
    """降级不是删除：定理必须仍能在 optional 里找到（可追溯）。"""
    rows = _rows((["wide", "keep"], []), (["wide"], []), (["wide"], []))
    demote(rows, max_span=2)
    for r in rows:
        assert "wide" in r["optional"]


def test_demote_does_not_duplicate_an_existing_optional_entry():
    rows = _rows((["wide"], ["wide"]), (["wide"], []), (["wide"], []))
    demote(rows, max_span=2)
    assert rows[0]["optional"].count("wide") == 1


def test_demote_preserves_order_of_surviving_required():
    rows = _rows((["z", "wide", "a"], []), (["wide"], []), (["wide"], []))
    demote(rows, max_span=2)
    assert rows[0]["required"] == ["z", "a"]


def test_demote_leaves_untouched_rows_identical():
    rows = _rows((["wide"], []), (["wide"], []), (["wide"], []),
                 (["rare"], []))
    demote(rows, max_span=2)
    assert rows[3]["required"] == ["rare"]
    assert rows[3]["optional"] == []


def test_demote_is_idempotent():
    """跑两遍结果必须一致（去掉 --dry-run 后手滑重跑不会二次污染）。"""
    rows = _rows((["wide", "keep"], []), (["wide"], []), (["wide"], []))
    demote(rows, max_span=2)
    snap = json.dumps(rows, sort_keys=True, ensure_ascii=False)
    changed2, moved2, _ = demote(rows, max_span=2)
    assert changed2 == 0 and moved2 == 0
    assert json.dumps(rows, sort_keys=True, ensure_ascii=False) == snap


def test_demote_noop_when_nothing_is_over_threshold():
    rows = _rows((["only"], []))
    changed, moved, _ = demote(rows, max_span=5)
    assert changed == 0 and moved == 0
    assert rows[0]["required"] == ["only"]


# --------------------------------------------------------------------------
# 真实数据的回归护栏（防止有人把阈值调回去 / 把逻辑改回去）
# --------------------------------------------------------------------------

_GT = os.path.join(_SRC, "data", "theorem_ground_truth",
                   "official112_theorems.jsonl")


@pytest.mark.skipif(not os.path.exists(_GT), reason="标注表不在本机")
def test_real_gt_has_no_theorem_crossing_thirty_percent_of_questions():
    """真实标注表：required 里不应再有横跨 >30% 题目的通用词。

    ⚠ 判据演进（2026-09-29 晚，勿改回去）：
      第一轮本测试断言的是「横跨 >5 题」—— 那是个**过紧的一刀切**，
      实测把 24 题削到只剩 1 条 required，基准失去区分度
      （用户原话「每题才 2-4 个定理是不是不够，太少了」）。
      现行判据见 `tools/rebuild_theorem_gt.py`：按 **30%** 出题量划通用词，
      并额外剔除 Tactic/Meta 等实现层声明。故本护栏同步放宽到 30%。
    """
    _, rows = _load(_GT)
    assert len(rows) == 112
    max_span = int(len(rows) * 0.30)          # = 33
    info = analyze(rows, max_span=max_span)
    assert info["too_common"] == [], (
        f"标注表被通用词污染了（横跨 >{max_span} 题）：{info['span_of']}"
    )


@pytest.mark.skipif(not os.path.exists(_GT), reason="标注表不在本机")
def test_real_gt_every_question_still_has_at_least_one_required():
    """降级不能把某题清空——否则该题变成不可评。"""
    _, rows = _load(_GT)
    empty = [r["id"] for r in rows if not (r.get("required") or [])]
    assert empty == [], f"这些题降级后没有 required 了：{empty}"
