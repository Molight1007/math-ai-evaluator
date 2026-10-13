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
import glob
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
    txt = io.open(os.path.join(ROOT, rel), encoding="utf-8",
                  errors="replace").read()
    # 2026-10-07 阶段C2：run 的 6.5_audit_gate 段已逐字搬到
    # agent/orchestrator__final_gate.py。读 orchestrator.py 的源码级守卫改为读
    #「主文件 + 抽取模块」并集 —— 断言字面量与守卫意图均不变（非放宽判据）。
    # 2026-10-08 批9：改为读**全部** agent/orchestrator__*.py（glob 并集，原先只
    # 显式列 final_gate）；后续新抽的 orchestrator__oracle.py 等自动纳入
    # —— 仍非放宽判据（断言字符串与比较逻辑一字不改）。
    if rel.replace("\\", "/") == "agent/orchestrator.py":
        for _p in sorted(glob.glob(
                os.path.join(ROOT, "agent", "orchestrator__*.py"))):
            txt += "\n" + io.open(
                _p, encoding="utf-8", errors="replace").read()
    # 2026-10-08 拆分：`_generate_revise` 的「池满腾位（pick_best_candidates）」与
    # 「上一轮解答注入（prev_answer=_prev_block）」两段已逐字搬到
    # agent/solver__revise.py。读 solver.py 的源码级守卫改为读「主文件 + 抽取模块」
    # 并集 —— 断言字面量与守卫意图均不变（非放宽判据）。
    if rel.replace("\\", "/") == "agent/solver.py":
        txt += "\n" + io.open(
            os.path.join(ROOT, "agent", "solver__revise.py"),
            encoding="utf-8", errors="replace").read()
    return txt


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
    # ★ 2026-10-09：**显式钉住 test-local 的池上限 = 6**。
    #   背景：`candidate_pool_limit` 全仓默认 6→12（用户拍板），而本组用例的
    #   "池满" 语义是"池内 6 个"；此前它靠 `SimpleNamespace` 缺字段 ⇒ 落到
    #   `_pool_room` 的 `getattr(..., 6.0)` 兜底，默认一变就**被动跟着漂**。
    #   此处把假设显式写进测试（不再依赖全局默认），使 M1 三条用例与默认值解耦。
    a.config = SimpleNamespace(revise_sample_times=3, candidate_pool_limit=6)
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
# ★ 2026-10-14（五道链定案）：`test_M2_guard_present` 已删 —— 其目标
#   （`ctx.candidates = _pass_cands[:3]` 腾位赋值）随 revise/6.5 重做链整体删除。


# ============================ 泛化句：结束而非空转 ============================
# ★ 2026-10-14（五道链定案）：`test_generic_sentence_returns_empty` 与
#   `test_revise_loop_ends_on_empty_review` 已删 —— 其目标
#   （`_review_bug_feedback` / 「结束 revise」守卫）随 revise 回环整体删除。


# ============================ M7：上一轮解答进提示词 ============================
def test_M7_revise_template_carries_prev_answer():
    from prompts.revise import REVISE_USER_TEMPLATE as T
    r = T.format(problem="P", feedback="F", prev_answer="A")
    assert "上一轮被判定有误的解答" in r
    assert "修正纪律" in r
    assert "{prev_answer}" not in r


def test_M7_solver_passes_prev_answer():
    assert "prev_answer=_prev_block" in _src("agent/solver.py")
