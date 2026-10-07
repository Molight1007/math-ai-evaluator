# -*- coding: utf-8 -*-
"""2026-10-07：终答选择两条**阻断级**修复的回归锁定。

依据（smoke10 2026-10-06 实测，`run_2026-10-06_smoke10_1006_2347.jsonl`）
----------------------------------------------------------------------
问题 2.1（同源）：official112-002 的 `diag.pick_diag.picked` =
`证明这个最小值就是所求的 $T$，并验证其最优性`（计划句），而被评分的
`predicted` = `\\boxed{\\dfrac{\\sqrt{5}-1}{2}}`。
⇒ 分叉点在 orchestrator 6.5 审核闸门：`formatter.run` 写 `_pick_diag` 之后，
闸门经 `_set_final_response` → `adopt_single` 改写 `ctx.final_response`，却不动记录。
真值 = 提交串；修法 = 令记录侧向它对齐（开关 `final_answer_single_source`）。

问题 2.2（未验证候选胜出）：official112-007 的 `\\boxed{0}`（gold=1）
**无任何验证记录**（confidence/correct_votes/total_votes 全 None），却参与投票，
并在 1:1 平票后由**推理长度**裁决胜出；且 `picked` 不在任何 cluster 内。
修法 = 选择机制识别"未验证"（开关 `final_select_verify_aware`）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.base import Candidate, TaskContext, Verdict  # noqa: E402
import agent.final_selector as fs  # noqa: E402


class _Cl:
    """最小 AnswerCluster 替身（只需 answer_norm / size / confidence / 票数）。"""

    def __init__(self, answer_norm, size=1, vc=0, vt=0, n_distinct=1):
        self.answer_norm = answer_norm
        self.candidate_ids = list(range(size))
        self.vote_correct = vc
        self.vote_total = vt
        self.n_distinct = n_distinct

    @property
    def size(self):
        return len(self.candidate_ids)

    @property
    def confidence(self):
        return (self.vote_correct / self.vote_total) if self.vote_total else 0.0


def _llm_single(ctx, msgs, t, mt):
    """步②判单一答案；步④行不含 `候选 N` ⇒ 判不出 ⇒ 落到 ⑤。"""
    return '{"multiple": false}'


def _on(monkeypatch):
    monkeypatch.setenv("FINAL_ANSWER_SINGLE_SOURCE", "1")
    monkeypatch.setenv("FINAL_SELECT_VERIFY_AWARE", "1")


# ================= 问题 2.2：未验证候选 =================
def test_unverified_excluded_when_verified_exists(monkeypatch):
    """有已验证候选时，未验证候选**不参与胜出**（"跳过"）。"""
    _on(monkeypatch)
    ctx = TaskContext(problem="p", metadata={})
    c_unv = Candidate(id=1, answer="\\boxed{0}", reasoning="long " * 200)
    c_ver = Candidate(id=2, answer="\\boxed{7}", reasoning="short")
    ctx.candidates = [c_unv, c_ver]
    ctx.verdicts = [Verdict(id=0, answer="\\boxed{7}", confidence=1.0,
                            correct_votes=3, total_votes=3)]
    res = fs.select_final_answer(ctx, ctx.candidates, _llm_single,
                                 record=lambda *a, **k: None)
    assert res["branch"] == "verified_only_single"
    assert res["answer"] == "\\boxed{7}", "已验证候选应胜出"
    pool = res["diag"]["pool"]
    assert pool["restricted"] is True
    assert any(x["answer"] == "\\boxed{0}" for x in pool["excluded_unverified"])


def test_all_unverified_marked_and_form_tiebreak(monkeypatch):
    """全部未验证 ⇒ 显式留痕；投票并列**不再**按推理长度裁决（007 场景）。"""
    _on(monkeypatch)
    ctx = TaskContext(problem="p", metadata={})
    c_plan = Candidate(id=0, answer="实际上……让我搜索一下这类问题的标准解法。",
                       reasoning="x" * 10)
    c_proc = Candidate(id=2, answer="- 子问题4：求和并验证结果", reasoning="y" * 400)
    c_box = Candidate(id=3, answer="\\boxed{0}", reasoning="z" * 20)
    ctx.candidates = [c_plan, c_proc, c_box]
    # 只有计划句有验证记录（且 0 票）；\boxed{0} 与过程句**完全无记录**
    ctx.verdicts = [Verdict(id=0, answer=c_plan.answer, confidence=0.0,
                            correct_votes=0, total_votes=4)]
    res = fs.select_final_answer(ctx, ctx.candidates, _llm_single,
                                 record=lambda *a, **k: None)
    assert res["diag"]["pool"]["all_unverified"] is True
    assert res["diag"]["verification"]["n_unverified"] == 2
    assert res["diag"]["vote"]["tie_break"] != "reasoning_length(legacy)"
    # 过程句推理长 400、\boxed{0} 只有 20 ⇒ 旧逻辑会选过程句；新逻辑按答案形态选。
    assert res["answer"] == "\\boxed{0}"


def test_verify_aware_off_uses_legacy_vote(monkeypatch):
    """开关 OFF ⇒ ⑤投票逐字回退（并列按推理长度）。"""
    monkeypatch.setenv("FINAL_SELECT_VERIFY_AWARE", "0")
    a, _c, diag = fs._vote([("- 子问题4：求和并验证结果", "y" * 400, None),
                            ("\\boxed{0}", "z" * 20, None)],
                           verified=set(), verify_aware=False)
    assert a == "- 子问题4：求和并验证结果"
    assert diag["tie_break"] == "reasoning_length(legacy)"


# ================= 问题 2.1：单一来源 =================
def test_gate_swap_syncs_pick_diag_to_final(monkeypatch):
    """6.5 闸门经 `_set_final_response`→`adopt_single` 换候选后，记录=提交值。"""
    _on(monkeypatch)
    from agent.orchestrator import Orchestrator
    ctx = TaskContext(problem="p", metadata={})
    ctx.final_response = "证明这个最小值就是所求的 $T$，并验证其最优性"
    ctx._pick_diag = {"branch": "final_select_objective_single",
                      "picked": ctx.final_response}
    ctx.candidates = [Candidate(id=9, answer="\\boxed{X}", reasoning="r")]
    final = "\\boxed{\\dfrac{\\sqrt{5}-1}{2}}"
    assert Orchestrator._set_final_response(ctx, final, "gate_next") is True
    assert ctx.final_response == final
    assert ctx._pick_diag["picked"] == final, "决策记录必须与提交值逐字一致"
    assert ctx._pick_diag["picked_decision"] == "证明这个最小值就是所求的 $T$，并验证其最优性"
    assert ctx._pick_diag["final_submit"] == final
    assert "gate_next" in ctx._pick_diag["final_submit_source"]


def test_single_source_off_keeps_legacy(monkeypatch):
    """开关 OFF ⇒ picked 不被同步（完全回退改动前）。"""
    monkeypatch.setenv("FINAL_ANSWER_SINGLE_SOURCE", "0")
    from agent.orchestrator import Orchestrator
    ctx = TaskContext(problem="p", metadata={})
    ctx.final_response = "plan"
    ctx._pick_diag = {"branch": "b", "picked": "plan"}
    ctx.candidates = [Candidate(id=9, answer="\\boxed{X}", reasoning="r")]
    assert Orchestrator._set_final_response(ctx, "\\boxed{X}", "gate_next") is True
    assert ctx._pick_diag["picked"] == "plan"
    assert "picked_decision" not in ctx._pick_diag


def test_public_sync_helper_for_postprocess_path(monkeypatch):
    """`sync_pick_diag_to_final`：供 orchestrator 后处理路径接入的一行同步。"""
    _on(monkeypatch)
    ctx = TaskContext(problem="p", metadata={})
    ctx._pick_diag = {"branch": "b", "picked": "旧值"}
    ctx.final_response = "\\boxed{1012}"
    fs.sync_pick_diag_to_final(ctx, "postprocess")
    assert ctx._pick_diag["picked"] == "\\boxed{1012}"
    assert ctx._pick_diag["final_submit_source"] == "postprocess"

    # OFF ⇒ 什么都不做
    monkeypatch.setenv("FINAL_ANSWER_SINGLE_SOURCE", "0")
    ctx2 = TaskContext(problem="p", metadata={})
    ctx2._pick_diag = {"branch": "b", "picked": "旧值"}
    ctx2.final_response = "\\boxed{1012}"
    fs.sync_pick_diag_to_final(ctx2, "postprocess")
    assert ctx2._pick_diag["picked"] == "旧值"


# ================= cluster 可追溯 =================
def test_record_pick_cluster_match_and_missing(monkeypatch):
    _on(monkeypatch)
    ctx = TaskContext(problem="p", metadata={})
    ctx._pick_diag = {"picked": "\\boxed{BD}"}
    ctx._cluster_data = [_Cl("\\boxed{BD}", size=3, vc=8, vt=11)]
    fs.record_pick_cluster(ctx)
    assert ctx._pick_diag["picked_cluster"]["size"] == 3
    assert ctx._pick_diag["picked_cluster"]["correct_votes"] == 8

    ctx2 = TaskContext(problem="p", metadata={})
    ctx2._pick_diag = {"picked": "\\boxed{0}"}
    ctx2._cluster_data = [_Cl("某个完全不同的计划句")]
    fs.record_pick_cluster(ctx2)
    assert ctx2._pick_diag["picked_cluster"] is None
    assert "未归入任何 cluster" in ctx2._pick_diag["picked_cluster_missing"]

    ctx3 = TaskContext(problem="p", metadata={})
    ctx3._pick_diag = {"picked": "\\boxed{0}"}
    fs.record_pick_cluster(ctx3)
    assert "无 cluster 数据" in ctx3._pick_diag["picked_cluster_missing"]
