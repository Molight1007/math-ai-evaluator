# -*- coding: utf-8 -*-
"""逻辑缺口分析测试（2026-09-29，截图 #6）。

用户原话：
> 可不可以用 lean 来检测有没有 sorry 的地方，**像这种缺少的逻辑点是不是就是
> 大模型需要推理出来的点呢**？这个要思考一下。

本模块（`agent/gap_analyzer.py`）的全部价值在于**区分**：
  · 「纯逻辑跳跃」（前提齐全却推不出）→ 真·推理瓶颈，是子目标分解该解决的；
  · 「形式化 / 缺引理 / 计算」→ 工具链问题，**不该计入推理能力评估**。

★ 这个区分错了，后续所有优化决策都会建立在错误归因上：
    把译题错误当推理不行 → 去调解题提示词（该修的是 translator）；
    把检索问题当推理不行 → 去加推理步数（该做的是定理注入）。
  所以本测试的重点**不是覆盖率**，而是**分类边界的正确性**。

沿用项目「阳性对照」纪律：每条断言都要能真的失败（见 negation 用例）。
"""
from __future__ import annotations

import os
import sys

import pytest

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agent.gap_analyzer import (  # noqa: E402
    aggregate_gaps, classify_gap, classify_subgoal_gap, counts_as_reasoning,
    extract_gaps, extract_lean_dag_gaps, extract_subgoal_gaps, gap_meaning,
    is_subgoal_failed, merge_gap_sources,
)


# ----------------------------------------------------------------------
# 1) Lean 报错分类（消费 refine_result）
# ----------------------------------------------------------------------
@pytest.mark.parametrize("error,expected", [
    # 形式化/译题问题 —— 不该算推理瓶颈
    ("unknown identifier 'foo'", "formalization"),
    ("unknown namespace Nat.Foo", "formalization"),
    ("type mismatch: expected Nat got Int", "formalization"),
    ("failed to synthesize instance", "formalization"),
    ("unexpected token ';'", "formalization"),
    # 缺引理 —— 检索问题
    ("unknown theorem Nat.foo", "missing_lemma"),
    ("Try this: exact Nat.choose_le", "missing_lemma"),
    ("did you mean Nat.succ?", "missing_lemma"),
    # 计算问题
    ("linarith failed to prove", "computation"),
    ("norm_num failed", "computation"),
    # ★ 真·推理瓶颈
    ("unsolved goals\n⊢ a + b = b + a", "logical_jump"),
    ("tactic 'ring' failed", "logical_jump"),
    # 兜底
    ("", "unknown"),
    ("some unrecognizable text", "unknown"),
])
def test_classify_gap(error, expected):
    assert classify_gap(error) == expected


def test_only_logical_jump_counts_as_reasoning():
    """★ 核心契约：四类缺口里**只有 logical_jump 算推理瓶颈**。"""
    assert counts_as_reasoning("logical_jump") is True
    for non_reasoning in ("formalization", "missing_lemma", "computation"):
        assert counts_as_reasoning(non_reasoning) is False, (
            f"{non_reasoning} 被算成了推理瓶颈 —— 会把优化方向引错"
        )
    assert counts_as_reasoning("unknown") is None   # 未知，不臆断


def test_gap_meaning_covers_every_kind():
    """每个 kind 都必须有中文释义与优化建议（不能出现空说明）。"""
    for kind in ("logical_jump", "missing_lemma", "formalization",
                 "computation", "unknown"):
        meaning, advice = gap_meaning(kind)
        assert meaning and advice, f"{kind} 缺释义或建议"


def test_meaning_of_unknown_kind_falls_back():
    meaning, advice = gap_meaning("not_a_real_kind")
    assert meaning == "未能归类"
    assert advice


# ----------------------------------------------------------------------
# 2) extract_gaps：从 refine_result 提缺口
# ----------------------------------------------------------------------
def _refine_result(nodes: dict, done: int, failed: int) -> dict:
    per_node = {}
    for nid, err in nodes.items():
        per_node[nid] = {"ok": err is None, "theorem": f"node_{nid}",
                         "error": err or "", "attempts": 2}
    return {"verdict": "partial" if failed else "ok", "per_node": per_node,
            "done": done, "failed": failed}


def test_extract_gaps_splits_reasoning_from_non_reasoning():
    rr = _refine_result({
        "n1": None,                                            # 补上了
        "n2": "unsolved goals ⊢ x = y",                        # 推理瓶颈
        "n3": "unknown identifier 'foo'",                      # 形式化
        "n4": "Try this: exact Nat.foo",                       # 缺引理
    }, done=1, failed=3)
    out = extract_gaps(rr)

    assert out["ok"] is True
    assert out["n_nodes"] == 4 and out["n_done"] == 1 and out["n_failed"] == 3
    assert out["reasoning_gaps"] == 1
    assert out["non_reasoning_gaps"] == 2
    assert out["by_kind"] == {"logical_jump": 1, "formalization": 1,
                              "missing_lemma": 1}
    assert "不应计入推理能力评估" in out["diagnosis"]


def test_extract_gaps_attaches_statement_from_blueprint():
    rr = _refine_result({"n1": "unsolved goals"}, done=0, failed=1)
    bp = {"nodes": [{"id": "n1", "statement": "对任意 n，P(n) 成立"}]}
    out = extract_gaps(rr, blueprint=bp)
    assert out["gaps"][0]["statement"] == "对任意 n，P(n) 成立"


def test_extract_gaps_all_done():
    rr = _refine_result({"n1": None, "n2": None}, done=2, failed=0)
    out = extract_gaps(rr)
    assert out["n_failed"] == 0
    assert out["gaps"] == []
    assert "无遗漏子目标" in out["diagnosis"]


def test_extract_gaps_degrades_without_data():
    for bad in (None, {}, {"verdict": "ok"}):
        out = extract_gaps(bad)
        assert out["ok"] is False
        assert out["diagnosis"]          # 必须给一句话说明，不能静默


# ----------------------------------------------------------------------
# 3) 子目标运行期缺口（消费 subgoal_trace，不依赖 Lean）
# ----------------------------------------------------------------------
def test_is_subgoal_failed_recognizes_upstream_markers():
    """必须与 sub_goal_solver 的既有判据**口径一致**。"""
    for marker in ("[子目标求解失败]", "该步未产出有效结论", "仍为空转占位",
                   "[子目标 3 失败]", ""):
        assert is_subgoal_failed(marker) is True, marker


def test_is_subgoal_failed_recognizes_self_reported_failure():
    """★ 回归：模型自陈"没做出来"也必须算失败。

    实测教训：首版只认占位符，导致「计算未能完成」「前提缺少，无法确定」
    这类被当作**成功结论**记入，缺口统计系统性偏低 —— 把"没解出来"
    读成了"解出来了"。
    """
    for txt in ("计算未能完成", "该步依赖前一步，前提缺少，无法确定",
                "无法化简", "推不出所需结论", "未能求出该值"):
        assert is_subgoal_failed(txt) is True, txt


def test_is_subgoal_failed_does_not_flag_real_conclusions():
    """★ 反向对照：真结论**不得**被判为失败（否则缺口虚高）。"""
    for txt in ("设 a=3, b=4, c=5", "答案是 42",
                "结论：x=3，验证成立", "面积为 6",
                r"a_n = n \text{ for all } n \ge 0"):
        assert is_subgoal_failed(txt) is False, txt


@pytest.mark.parametrize("result,expected", [
    ("[子目标求解失败]", "logical_jump"),
    ("仍为空转占位", "logical_jump"),
    ("该步依赖前一步，前提缺少，无法确定", "formalization"),
    ("计算未能完成，化简失败", "computation"),
])
def test_classify_subgoal_gap(result, expected):
    assert classify_subgoal_gap(result) == expected


def test_extract_subgoal_gaps_counts_and_diagnoses():
    trace = [
        {"id": "sg1", "title": "设元", "description": "d1", "result": "设 a=x"},
        {"id": "sg2", "title": "证明", "description": "d2",
         "result": "[子目标求解失败]"},
        {"id": "sg3", "title": "代入", "description": "d3",
         "result": "前提缺少，无法确定"},
        {"id": "sg4", "title": "算积分", "description": "d4",
         "result": "计算未能完成"},
    ]
    out = extract_subgoal_gaps(trace)
    assert out["n_nodes"] == 4 and out["n_done"] == 1 and out["n_failed"] == 3
    assert out["reasoning_gaps"] == 1
    assert out["non_reasoning_gaps"] == 2
    assert out["source"] == "subgoal_trace"
    assert out["by_kind"] == {"logical_jump": 1, "formalization": 1,
                              "computation": 1}


def test_extract_subgoal_gaps_all_success_means_decomposition_worked():
    """全部成功 ⇒ 明确给出「子目标分解有效」的结论（用户 #6 的第一问）。"""
    trace = [{"id": f"s{i}", "title": f"t{i}", "description": "d",
              "result": f"结论 {i}"} for i in range(4)]
    out = extract_subgoal_gaps(trace)
    assert out["n_failed"] == 0
    assert "子目标分解有效" in out["diagnosis"]


def test_extract_subgoal_gaps_degrades_gracefully():
    for bad in (None, [], "not a list", {}):
        out = extract_subgoal_gaps(bad)
        assert out["ok"] is False
        assert out["diagnosis"]


def test_subgoal_gap_keeps_structural_metadata():
    """缺口条目要带上 sg_type / calc_kind / depends_on —— 归因时才知"哪类子目标爱失败"。"""
    trace = [{"id": "sg7", "title": "证明", "description": "d",
              "type": "proof", "calc_kind": "inline", "depends_on": ["sg1"],
              "result": "[子目标求解失败]"}]
    g = extract_subgoal_gaps(trace)["gaps"][0]
    assert g["sg_type"] == "proof"
    assert g["calc_kind"] == "inline"
    assert g["depends_on"] == ["sg1"]


# ----------------------------------------------------------------------
# 4) 双源合并：交集才是高置信度瓶颈
# ----------------------------------------------------------------------
def test_merge_finds_nodes_failed_in_both_sources():
    """★ 两个独立视角都失败 ⇒ 高置信度推理瓶颈（本模块最强信号）。"""
    trace = [
        {"id": "sg1", "title": "a", "description": "d", "result": "OK 结论"},
        {"id": "sg2", "title": "b", "description": "d",
         "result": "[子目标求解失败]"},
        {"id": "sg3", "title": "c", "description": "d",
         "result": "仍为空转占位"},
    ]
    src_a = extract_subgoal_gaps(trace)
    # 源 B：只有 sg2 失败（sg3 在 Lean 侧补上了）⇒ 交集应只剩 sg2
    rr = _refine_result({"sg2": "unsolved goals", "sg3": None}, done=1, failed=1)
    src_b = extract_gaps(rr)
    src_b["source"] = "refine_result"

    m = merge_gap_sources(src_a, src_b)
    assert m["ok"] is True
    assert "subgoal_trace" in m["sources"] and "refine_result" in m["sources"]
    assert m["in_both_failed"] == ["sg2"], m["in_both_failed"]
    assert "双源一致" in m["diagnosis"]


def test_merge_with_single_source_has_no_intersection():
    src = extract_subgoal_gaps([{"id": "s1", "title": "t", "description": "d",
                                 "result": "仍为空转占位"}])
    m = merge_gap_sources(src)
    assert m["in_both_failed"] == []
    assert m["ok"] is True


def test_merge_with_no_valid_source():
    m = merge_gap_sources({}, None)
    assert m["ok"] is False
    assert "无任何可用缺口数据源" in m["diagnosis"]


# ----------------------------------------------------------------------
# 5) 多题汇总
# ----------------------------------------------------------------------
def test_aggregate_orders_advice_by_frequency():
    per_q = []
    for i in range(3):
        trace = [
            {"id": f"a{i}", "title": "t", "description": "d",
             "result": "[子目标求解失败]"},          # logical_jump
            {"id": f"b{i}", "title": "t", "description": "d",
             "result": "前提缺少"},                   # formalization
        ]
        per_q.append(extract_subgoal_gaps(trace))
    agg = aggregate_gaps(per_q)
    assert agg["n_q"] == 3
    assert agg["total_failed"] == 6
    assert agg["by_kind"]["logical_jump"] == 3
    # 建议按频次降序 —— 让"最该优化什么"一眼可见
    assert agg["top_advice"][0]["kind"] == "logical_jump"


def test_aggregate_skips_invalid_entries():
    agg = aggregate_gaps([{"ok": False}, None, "junk"])
    assert agg["n_q"] == 0
    assert agg["top_advice"] == []


# ----------------------------------------------------------------------
# 6) 阳性对照：断言必须能真的失败
# ----------------------------------------------------------------------
def test_negation_control_would_catch_a_wrong_classifier():
    """证明上面那些断言不是"恒真"的 —— 故意用错误的期望值应导致不等。"""
    # 若把 formalization 误当成推理瓶颈，本断言会红
    assert counts_as_reasoning("formalization") is False
    assert counts_as_reasoning("formalization") is not True
    # 若把正常结论误判为失败，本断言会红
    assert is_subgoal_failed("答案是 42") is False


# ----------------------------------------------------------------------
# 7) Lean 侧缺口：extract_lean_dag_gaps（2026-09-30，截图 #6 下半问）
# ----------------------------------------------------------------------
# 数据源 = 求解前 Lean 逻辑检查（`example : (expr) := by sorry` 编译结果）。
# ★ 三个状态**必须区分**（本项目反复吃亏的地方）：
#     · 没跑            → ok=False，"不能据此判定蓝图无缺陷"
#     · 跑了且全通过    → ok=True,  n_failed=0   ← 好信号
#     · 跑了且有失败    → ok=True,  n_failed>0
#   把「没跑」当「没问题」是致命的假阴性。
# ----------------------------------------------------------------------
def test_lean_gaps_not_run_is_not_a_pass():
    """★ 关键：检查未触发 ≠ 通过。绝不能返回 ok=True / n_failed=0 的"全通过"形态。"""
    r = extract_lean_dag_gaps({}, [])
    assert r["ok"] is False
    assert "未触发" in r["diagnosis"]
    assert "不能据此判定" in r["diagnosis"]


def test_lean_gaps_ran_and_all_passed():
    r = extract_lean_dag_gaps({}, ["n1", "n2", "n3"])
    assert r["ok"] is True
    assert r["n_checked"] == 3
    assert r["n_failed"] == 0
    assert r["n_done"] == 3
    assert "全部通过" in r["diagnosis"]


def test_lean_gaps_formalization_is_not_reasoning():
    """★ 核心：`by sorry` 编译失败 ⇒ 命题本身写得不成立 ⇒ **不是**推理瓶颈。"""
    r = extract_lean_dag_gaps(
        {"n1": "unknown identifier 'foo'", "n2": "type mismatch: Nat vs Int"},
        ["n1", "n2", "n3"])
    assert r["ok"] is True
    assert r["by_kind"] == {"formalization": 2}
    assert r["reasoning_gaps"] == 0
    assert r["non_reasoning_gaps"] == 2
    assert "形式化缺陷" in r["diagnosis"]
    assert "不是模型该推出来的点" in r["diagnosis"]


def test_lean_gaps_logical_jump_does_count():
    """反向对照：真正推不出来的（unsolved goals）**要**算推理瓶颈。"""
    r = extract_lean_dag_gaps({"n1": "unsolved goals"}, ["n1"])
    assert r["reasoning_gaps"] == 1
    assert r["reasoning_share"] == 1.0


def test_lean_gaps_restores_statement_from_blueprint():
    bp = {"nodes": {"n1": {"statement": "设 x > 0 且 x + 1/x = 3"}}}
    r = extract_lean_dag_gaps({"n1": "unknown identifier 'y'"}, ["n1"], bp)
    assert r["gaps"][0]["statement"] == "设 x > 0 且 x + 1/x = 3"
    # list 形态的 nodes 也要能还原
    bp2 = {"nodes": [{"id": "n1", "statement": "s2"}]}
    r2 = extract_lean_dag_gaps({"n1": "unknown identifier 'y'"}, ["n1"], bp2)
    assert r2["gaps"][0]["statement"] == "s2"


def test_lean_gaps_never_raises_on_junk():
    """诊断路径绝不能因脏数据崩（本项目铁律）。"""
    for junk in (None, [], "str", 42):
        r = extract_lean_dag_gaps(junk, None)
        assert r["ok"] is False
    r = extract_lean_dag_gaps({"n1": None}, None)
    assert r["ok"] is True          # 有 fails 就算跑过
    assert r["gaps"][0]["kind"] == "unknown"


def test_lean_gaps_can_merge_with_subgoal_gaps():
    """两源可汇总：merge_gap_sources 认 ok=True 的源，不认未触发的源。"""
    lg = extract_lean_dag_gaps({"n1": "unknown identifier 'x'"}, ["n1"])
    sg = extract_subgoal_gaps(
        [{"id": "n1", "title": "t", "description": "d", "result": "推不出"}])
    m = merge_gap_sources(sg, lg)
    assert m["ok"] is True
    assert "lean_dag_check" in m["sources"]
    # 同一个 node_id 两边都失败 ⇒ 高置信推理瓶颈候选
    assert "n1" in m["in_both_failed"]
