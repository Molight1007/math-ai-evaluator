# -*- coding: utf-8 -*-
"""P1-B~F 三、四批回归测试（2026-09-17）。

  Z1   `value_attack` 前置跳过离散领域（不再先付一次 32768-token 调用）
  Z5   非数学对象答案在 LeanGate 层短路（不再送 LLM 翻译 + 编译）
  Audit-2  tier_budget 四套口径收敛（注释/兜底与 AgentConfig 默认一致）
  Audit-4  `_p1_triggered` 恒真分支已显式标注
  L1   守卫②去 `<calc>` 依赖，且**正则回退只能确认、不能否决**
  L2   分数答案（`\frac{a}{b}`）专项锚定
  L4   `calc_inconsistent` 结构性不可达已显式标注
  P1-F `diag_completeness` 三态（未执行 / 执行无产出 / 有产出）
  P1-C 分歧候选簇写入 `_pick_diag`（只保留可见性，不改选答）
  P1-D 多答案并集（硬约束：仅"求所有"题、只并无反对票簇、上限 3、加法非替换）
"""
import io
import os
from types import SimpleNamespace

import pytest

from agent.base import TaskContext
from agent.formatter import FormatterAgent, _looks_like_non_answer
from agent.orchestrator import _diag_completeness
from tools.lean_local.lean_bridge import _answer_embedded

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   errors="replace").read()


# ============================ Z1 ============================
def test_z1_discrete_domain_precheck_present():
    src = _src("agent/orchestrator.py")
    assert "前置跳过，未付出 LLM 调用" in src
    i = src.find("前置跳过，未付出 LLM 调用")
    seg = src[max(0, i - 2000):i]
    # 判定必须出现在 LLM 调用之前
    assert 'raw = self.llm(ctx, prefill_messages(' in src[i:i + 600]


# ============================ Z5 ============================
def test_z5_non_math_short_circuit_present():
    src = _src("tools/lean_local/lean_gate.py")
    assert 'entry["degraded"] = "non_math_answer"' in src
    assert "from agent.formatter import _looks_like_non_answer" in src


def test_z5_gate_agrees_with_single_source_of_truth():
    """Z5 用的判据必须就是 formatter 的那一个（防口径分叉）。"""
    for s in ("</tool_call>", "步骤8：重新思考——正确的下界构造", ""):
        assert _looks_like_non_answer(s) is True
    for s in (r"\boxed{506}", "有限差分法", "506"):
        assert _looks_like_non_answer(s) is False


# ============================ Audit-2 ============================
def test_audit2_no_stale_tier_budget_numbers():
    """四套口径收敛：不得再残留 540/1200/1320 这类与真源不符的**兜底值**。"""
    pacer = _src("agent/paper_pacer.py")
    assert '{"fast": 300.0, "standard": 750.0, "deep": 1150.0}' in pacer
    assert '{"fast": 120.0, "standard": 540.0, "deep": 1200.0}' not in pacer
    ua = _src("user_agent.py")
    assert "{fast:300, standard:750, deep:1150}" in ua
    assert "{fast:120, standard:540, deep:1320}" not in ua


def test_audit2_agentconfig_default_matches_declaration():
    import re
    ua = _src("user_agent.py")
    m = re.search(r'self\.tier_budget = \{"fast": ([\d.]+), "standard": ([\d.]+), '
                  r'"deep": ([\d.]+)\}', ua)
    assert m, "未找到 __post_init__ 的 tier_budget 赋值"
    assert (m.group(1), m.group(2), m.group(3)) == ("300.0", "750.0", "1150.0")


# ============================ Audit-4 ============================
def test_audit4_inert_guard_is_documented():
    src = _src("agent/orchestrator.py")
    assert "当前恒为真分支（守卫无效）" in src


# ============================ L1 ============================
def test_l1_fallback_exists_and_only_confirms():
    """L1 的核心安全性质：正则回退**只能确认、不能否决**。"""
    src = _src("tools/lean_local/lean_bridge.py")
    assert "_from_marker" in src
    i = src.find("if not _from_marker:")
    assert i > 0
    seg = src[i:i + 400]
    assert "return None" in seg, "回退来源必须返回 None（不作否决）"


def test_l1_marker_path_still_can_reject():
    """显式标记来源仍保留"矛盾 ⇒ 判错"的能力（不因 L1 被削弱）。"""
    src = _src("tools/lean_local/lean_bridge.py")
    i = src.find("if not _from_marker:")
    seg = src[i:i + 400]
    assert seg.count("return False") >= 1


# ============================ L2 ============================
def test_l2_fraction_answer_anchored():
    code = "example : (1:ℚ)/2 = 1/2 := by norm_num"
    assert _answer_embedded(code, r"\boxed{\frac{1}{2}}") is True


def test_l2_fraction_mismatch_still_detected():
    assert _answer_embedded("example : 3 = 3 := by norm_num",
                            r"\boxed{\frac{1}{2}}") is False


def test_l2_dfrac_form():
    code = "lemma h : (3:ℚ)/4 = 3/4 := by norm_num  -- \\dfrac{3}{4}"
    assert _answer_embedded(code, r"\boxed{\dfrac{3}{4}}") is True


# ============================ L4 ============================
def test_l4_dead_path_is_documented():
    src = _src("agent/solver.py")
    assert "连带 calc_inconsistent 检测不可达" in src
    orch = _src("agent/orchestrator.py")
    assert "calc_inconsistent 判据在当前配置下不可达" in orch


# ============================ P1-F ============================
def test_p1f_three_states():
    c = TaskContext(problem="p", metadata={})
    d = _diag_completeness(c)
    assert set(d.values()) == {"not_ran"}, "空 ctx 应全为 not_ran"
    c.trace = [{"step": "value_attack", "content": "x"},
               {"step": "pick_diag"}]
    d = _diag_completeness(c)
    assert d["value_attack"] == "ran_with_data"
    assert d["pick_diag"] == "ran_no_output"
    assert d["lemma_repo"] == "not_ran"


def test_p1f_diag_exposes_completeness():
    assert '"diag_completeness": _diag_completeness(ctx),' in _src("agent/orchestrator.py")


# ============================ P1-C / P1-D ============================
def _cl(ans, size, cv, tv):
    return SimpleNamespace(answer_norm=ans, size=size, confidence=1.0,
                           vote_correct=cv, vote_total=tv)


def _fmt():
    return FormatterAgent.__new__(FormatterAgent)


def _ctx_with(problem, clusters):
    c = TaskContext(problem=problem, metadata={})
    c._cluster_data = clusters
    return c


def test_p1d_union_on_multi_answer_question():
    c = _ctx_with("Find all possible value of x",
                  [_cl("A", 2, 3, 3), _cl("B", 1, 3, 3)])
    assert _fmt()._maybe_union_enumerated(c, "A") == "A, B"


def test_p1d_uses_ascii_comma_only():
    """必须用 ASCII 逗号（run_eval._split_multi 只按它拆，顿号拆不出多项）。"""
    c = _ctx_with("Find all possible value of x",
                  [_cl("A", 2, 3, 3), _cl("B", 1, 3, 3)])
    out = _fmt()._maybe_union_enumerated(c, "A")
    assert "," in out and "、" not in out


def test_p1d_skips_clusters_with_dissent():
    c = _ctx_with("Find all possible value of x",
                  [_cl("A", 2, 3, 3), _cl("C", 1, 0, 3)])
    assert _fmt()._maybe_union_enumerated(c, "A") is None


def test_p1d_requires_current_in_a_full_vote_cluster():
    c = _ctx_with("Find all possible value of x",
                  [_cl("A", 2, 3, 3), _cl("B", 1, 3, 3)])
    assert _fmt()._maybe_union_enumerated(c, "Z") is None


def test_p1d_not_triggered_on_non_multi_answer():
    c = _ctx_with("Compute 1+1", [_cl("A", 2, 3, 3), _cl("B", 1, 3, 3)])
    assert _fmt()._maybe_union_enumerated(c, "A") is None


def test_p1d_rejects_non_answer_items():
    c = _ctx_with("Find all possible value of x",
                  [_cl("A", 2, 3, 3), _cl("</tool_call>", 1, 3, 3)])
    assert _fmt()._maybe_union_enumerated(c, "A") is None


def test_p1c_divergent_clusters_recorded():
    src = _src("agent/formatter.py")
    assert '"divergent_clusters"' in src
    assert "全项目零读取点" in src
