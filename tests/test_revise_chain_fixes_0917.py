# -*- coding: utf-8 -*-
"""revise 执行链修复的行为级回归测试（2026-09-17）。

覆盖（每条对应一个已修缺陷，防回退）：
  M1  候选池满时**修订轮仍必须真正生成**候选（此前 `remaining<=0` 直接 return，
      腾位逻辑结构性不可达 ⇒ 003 的 4 轮修订一个候选都没生成，白烧 1494s）
  M3  腾位按**验证票数**保留最优（此前 `[-3:]` 按 id 尾部保留"最新"）
  M4  /  M-1  候选 id 不得与既有 id 冲突（此前用 `len(candidates)`，腾位后重叠：
      013 出现两个 id=3、025 出现 id=7）
  M6  orchestrator 不得再引用不存在的 `ctx.final_answer`（真实字段是 `final_response`）
  M2  审核未试过任何候选时**不得清空候选池**
  泛化句  `_review_bug_feedback` 判"无实质缺陷"时返回空串（由调用方结束 revise）
"""
import io
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.base import (
    Candidate,
    TaskContext,
    next_candidate_id,
    pick_best_candidates,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   errors="replace").read()


# ============================ M4 / M-1：id 不冲突 ============================
def test_next_candidate_id_empty():
    assert next_candidate_id([]) == 0
    assert next_candidate_id(None) == 0


def test_next_candidate_id_dense():
    cs = [Candidate(id=i, answer=str(i), reasoning="") for i in range(3)]
    assert next_candidate_id(cs) == 3


def test_next_candidate_id_with_gaps_not_len():
    """关键：腾位/删除后 id 有空洞时，必须取 max+1 而不是 len（否则重叠）。"""
    cs = [Candidate(id=0, answer="a", reasoning=""),
          Candidate(id=5, answer="b", reasoning="")]
    assert len(cs) == 2
    assert next_candidate_id(cs) == 6, "必须 max(id)+1，用 len 会与 id=5 冲突"


def test_next_candidate_id_tolerates_bad_ids():
    cs = [Candidate(id=0, answer="a", reasoning=""),
          SimpleNamespace(id="x"), SimpleNamespace(id=7)]
    assert next_candidate_id(cs) == 8


def test_no_len_based_id_generation_left():
    """全仓禁止再用 `len(ctx.candidates)` 作候选 id（M4/M-1 的系统性收口）。"""
    for rel in ("agent/solver.py", "agent/collaborative_solver.py",
                "agent/sub_goal_solver.py"):
        src = _src(rel)
        assert "id=len(ctx.candidates)" not in src, rel
        assert "cid = len(ctx.candidates)" not in src, rel


# ============================ M3：腾位按票数 ============================
def _c(cid, ans, rlen=10):
    return Candidate(id=cid, answer=ans, reasoning="r" * rlen)


def test_pick_best_candidates_prefers_votes():
    cs = [_c(0, "wrong", 500), _c(1, "right", 10), _c(2, "meh", 20)]
    vs = [SimpleNamespace(id=0, correct_votes=0),
          SimpleNamespace(id=1, correct_votes=3),
          SimpleNamespace(id=2, correct_votes=1)]
    assert pick_best_candidates(cs, vs, k=1)[0].answer == "right"


def test_pick_best_candidates_falls_back_to_reasoning_length():
    """无 verdict 时全部 0 票 ⇒ 退化为"推理最长优先"（量级与旧行为相当）。"""
    cs = [_c(0, "short", 5), _c(1, "long", 500)]
    assert pick_best_candidates(cs, [], k=1)[0].answer == "long"


def test_pick_best_candidates_respects_k():
    cs = [_c(i, str(i), 10) for i in range(6)]
    assert len(pick_best_candidates(cs, [], k=3)) == 3


def test_solver_keep_uses_votes_not_tail():
    """solver 的腾位点必须调用 pick_best_candidates，而不是 `[-3:]`。"""
    src = _src("agent/solver.py")
    assert "pick_best_candidates(ctx.candidates" in src
    assert "_keep = list(ctx.candidates or [])[-3:]" not in src


# ============================ M1：池满时修订仍要生成 ============================
def _bare_solver():
    from agent.solver import SolverAgent
    a = SolverAgent.__new__(SolverAgent)
    a.config = SimpleNamespace(revise_sample_times=3)
    return a


def _ctx(pool_n, revise):
    c = TaskContext(problem="p", metadata={})
    c.candidates = [_c(i, str(i)) for i in range(pool_n)]
    if revise:
        c.revise_round = 1
        c.revise_feedback = ["缺陷：第 3 步符号错"]
    return c


def test_M1_full_pool_revise_still_generates():
    """池满 + 修订轮 ⇒ **必须**调用 _generate_revise，且 cap=None 让内部腾位。"""
    from agent.solver import SolverAgent
    seen = {}

    def _fake_revise(self, ctx, cap=None):
        seen["cap"] = cap

    with patch.object(SolverAgent, "_generate_revise", _fake_revise):
        _bare_solver().run(_ctx(6, revise=True))

    assert "cap" in seen, "池满时修订轮被提前 return（M1 回归）"
    assert seen["cap"] is None, "池满时应传 cap=None，由 _generate_revise 自行腾位"


def test_M1_full_pool_non_revise_still_early_returns():
    """非修订轮且池满 ⇒ 仍应早退（保持原语义，不额外生成）。"""
    from agent.solver import SolverAgent
    seen = {}

    def _fake_init(self, ctx, count=None):
        seen["count"] = count

    with patch.object(SolverAgent, "_generate_initial", _fake_init):
        _bare_solver().run(_ctx(6, revise=False))

    assert "count" not in seen, "非修订轮池满不应触发生成"


def test_M1_partial_pool_revise_passes_positive_cap():
    from agent.solver import SolverAgent
    seen = {}

    def _fake_revise(self, ctx, cap=None):
        seen["cap"] = cap

    with patch.object(SolverAgent, "_generate_revise", _fake_revise):
        _bare_solver().run(_ctx(4, revise=True))

    assert seen.get("cap") == 2, "池内 4 个 ⇒ cap=2"


# ============================ M6：幽灵字段 ============================
def test_M6_no_phantom_final_answer_field():
    """TaskContext 没有 final_answer；orchestrator 不得再引用它。"""
    src = _src("agent/orchestrator.py")
    assert 'getattr(ctx, "final_answer"' not in src
    assert 'ctx.final_answer' not in src
    assert not hasattr(TaskContext(problem="p", metadata={}), "final_answer")
    assert hasattr(TaskContext(problem="p", metadata={}), "final_response")


# ============================ M2：禁止清空候选池 ============================
def test_M2_guard_present():
    """腾位赋值必须被 `if _pass_cands:` 守卫（否则 `_gate_tried` 为空时会清空池）。"""
    src = _src("agent/orchestrator.py")
    i_guard = src.find("if _pass_cands:")
    i_assign = src.find("ctx.candidates = _pass_cands[:3]")
    assert i_guard >= 0, "M2 守卫 `if _pass_cands:` 缺失"
    assert i_assign > i_guard, "腾位赋值未被守卫包裹（M2 回归）"


# ============================ 泛化句：结束而非空转 ============================
def test_generic_sentence_returns_empty():
    from agent.orchestrator import Orchestrator

    class C:
        def __init__(self, rs):
            self._r = list(rs)

        def chat(self, messages=None, temperature=0.0, max_tokens=0, **kw):
            return self._r.pop(0) if self._r else ""

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = SimpleNamespace(enable_feedback_review=True)
    orch.client = C(["无实质缺陷"])
    ctx = TaskContext(problem="p", metadata={})
    ctx.candidates = [_c(0, "2")]

    out = orch._review_bug_feedback(ctx, "缺陷：x = 2 是错误答案（实际正确）")
    assert out == "", "判断为误报时须返回空串，由调用方结束 revise（防零信息空转）"


def test_revise_loop_ends_on_empty_review():
    src = _src("agent/orchestrator.py")
    assert "_reviewed_empty and not audit_fb" in src, "缺少「结束 revise」守卫"


# ============================ M7：上一轮解答进提示词 ============================
def test_M7_revise_template_carries_prev_answer():
    from prompts.revise import REVISE_USER_TEMPLATE as T
    r = T.format(problem="P", feedback="F", prev_answer="A")
    assert "上一轮被判定有误的解答" in r
    assert "修正纪律" in r
    assert "{prev_answer}" not in r


def test_M7_solver_passes_prev_answer():
    assert "prev_answer=_prev_block" in _src("agent/solver.py")
