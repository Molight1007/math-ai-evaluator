# -*- coding: utf-8 -*-
"""VerifierAgent 结构化拆分（S1–S5）的硬契约守卫。

为什么需要这个文件
------------------
`agent/verifier.py::VerifierAgent` 是全仓最大的类（1606 行 / 35 方法），重构方案是
按职责把方法体搬进协作对象、类上只留同名跳板。但该类同时是 **5 处实例级
`mock.patch.object`** 的覆写目标（见 `PATCH_TARGETS`）。一旦协作对象**内部**用
`self.<方法>` 调到自己、而不是经由 `VerifierAgent` 实例，打在 `VerifierAgent`
**实例**上的 patch 就会**静默失效** —— 测试仍可能绿，但语义已变。

本文件把"patch 必须能被内部调用看见"固化为断言，四类：

  A. 5 个 patch 靶点必须仍能在 `VerifierAgent` 上取到（真方法，而不是被删/搬空）；
  B. **真·穿透性**：patch `VerifierAgent` 实例的方法后，走对应路径必须确实命中
     被 patch 的版本（协作对象若绕过实例 patch，这里会红）；
  C. 签名一致性（跳板不得改签名；S2 落地后自动升级为"跳板 == 实现"）；
  D. 导入面不变（外部 `from agent.verifier import <name>` 的名字全部仍在）。

⚠ 判据是"**能失败**"：B 类断言在把 `_deep_final_review` 内部的 `self._deep_llm`
改成绕过实例属性查找（如 `VerifierAgent._deep_llm(self, ...)`）后会变红 —— 已实测。
"""
from __future__ import annotations

import inspect
import time
from types import SimpleNamespace
from unittest import mock

import pytest

import agent.verifier as verifier_mod
from agent.base import TaskContext
from agent.verifier import VerifierAgent


# ---------------------------------------------------------------------------
# A. patch 靶点仍存在于 VerifierAgent 上
# ---------------------------------------------------------------------------
# 自有（定义在 VerifierAgent.__dict__）：方法体必须留在类上，不可改成外部函数。
PATCH_TARGETS_OWN = (
    "_deep_llm",                    # test_verifier_deep_review.py:103..196
    "_deterministic_check",         # test_verifier.py:359/375/394
    "_challenge_counterexample",    # test_verifier.py:538 + test_audit_gate.py:159
    "_vote_one_rubric",             # test_audit_gate.py:176/197/270/281
)
# 继承自 BaseAgent（patch.object 只要求该属性可解析；不动 base.py 即可）。
PATCH_TARGETS_INHERITED = ("llm",)


def _defining_class(cls: type, name: str) -> type | None:
    """返回在 MRO 中真正定义 `name` 的类（用于区分"自有"与"继承"）。"""
    for c in cls.__mro__:
        if name in c.__dict__:
            return c
    return None


@pytest.mark.parametrize("name", PATCH_TARGETS_OWN)
def test_patch_target_defined_on_verifier(name):
    """实例级 patch 靶点必须是 VerifierAgent 类上的真方法（不可搬成跳板/外函数）。"""
    assert name in VerifierAgent.__dict__, (
        f"{name} 不在 VerifierAgent.__dict__ —— 它是实例级 mock.patch.object 靶点，"
        "拆分时不能把函数体搬离本类（否则 patch 静默失效）"
    )
    defined = VerifierAgent.__dict__[name]
    assert callable(defined) or isinstance(defined, (staticmethod, classmethod)), (
        f"{name} 必须是可调用的方法（当前 {type(defined).__name__}）"
    )


@pytest.mark.parametrize("name", PATCH_TARGETS_INHERITED)
def test_patch_target_resolvable(name):
    """继承来的 patch 靶点（llm）必须仍能从 VerifierAgent 解析到且可调用。"""
    assert hasattr(VerifierAgent, name), (
        f"VerifierAgent.{name} 不可解析 —— 实例级 mock.patch.object 会直接 AttributeError"
    )
    assert callable(getattr(VerifierAgent, name))
    assert _defining_class(VerifierAgent, name) is not None


# ---------------------------------------------------------------------------
# B. patch 穿透性（最关键：协作对象不得绕过打在实例上的 patch）
# ---------------------------------------------------------------------------
def _ctx(problem: str = "probe", deadline=None) -> TaskContext:
    return TaskContext(problem=problem, metadata={}, deadline=deadline)


def _deep_verifier(**cfg) -> VerifierAgent:
    base = {
        "verifier_deep_final_enabled": True,
        "verifier_deep_final_min_remaining": 150.0,
        "verifier_deep_review_max_tokens": 4096,
    }
    base.update(cfg)
    return VerifierAgent(client=object(), config=SimpleNamespace(**base))


def _long_review(verdict_line: str = "VERDICT: B（方法不适用）", pad: int = 300) -> str:
    """构造长于 `verifier_deep_review_min_chars`（默认 200）的伪复核输出。"""
    body = "第 1 步 · 独立重算：重新计算并逐项比对，未发现差异。\n"
    while len(body) < pad:
        body += "补充核查：逐条对照定义与题设条件，未发现不一致之处。\n"
    return body + "\n" + verdict_line


class _SeqClient:
    """按调用序返回响应的假 client（耗尽后重复最后一个）。"""

    def __init__(self, responses):
        self._r = responses if isinstance(responses, list) else [responses]
        self.calls = 0

    def chat(self, messages=None, temperature=0.0, max_tokens=0, **kw):
        i = min(self.calls, len(self._r) - 1)
        self.calls += 1
        return self._r[i]


def _vote_verifier(responses, **cfg):
    base = {
        "max_workers": 2,
        "verifier_voting_times": 1,
        "use_scoring": False,
        "use_bug_report_feedback": False,
        "verifier_deep_final_enabled": False,
    }
    base.update(cfg)
    v = VerifierAgent(client=_SeqClient(responses), config=SimpleNamespace(**base))
    ctx = TaskContext(problem="求 x^2 - 4 = 0 的解", metadata={}, deadline=0.0)
    return v, ctx


_CAND = {"id": 0, "answer": "2", "reasoning": "由 x^2=4 得 x=2"}


def test_deep_llm_patch_penetrates_deep_final_review():
    """patch `v._deep_llm` → `v._deep_final_review` 内部必须调用被 patch 的版本。"""
    v = _deep_verifier()
    ctx = _ctx(deadline=time.time() + 900)
    with mock.patch.object(v, "_deep_llm", return_value=_long_review()) as m:
        raw = v._deep_final_review(ctx, "p", SimpleNamespace(answer_norm="42"))
    m.assert_called()   # ← 若内部绕过实例属性查找（协作对象 self._deep_llm），此处红
    assert "VERDICT: B" in raw


def test_llm_patch_penetrates_deep_llm():
    """patch `v.llm` → `v._deep_llm` 的非流式兜底路径必须命中它。"""
    v = _deep_verifier()
    ctx = _ctx(deadline=time.time() + 900)
    with mock.patch.object(v, "llm", return_value="VERDICT: A") as m:
        out = v._deep_llm(ctx, [{"role": "user", "content": "x"}], 0.0, 4096)
    assert out == "VERDICT: A"
    m.assert_called_once()


def test_vote_one_rubric_patch_penetrates_vote_rubric():
    """patch `v._vote_one_rubric` → `v._vote_rubric` 内部必须调用被 patch 的版本。"""
    v, ctx = _vote_verifier('{"verdict":"A","confidence":0.9}')
    with mock.patch.object(
        v, "_vote_one_rubric",
        return_value={"verdict": "B", "confidence": 0.9,
                      "error_type": "计算错", "step_index": 1,
                      "reason": "展开错"}) as m:
        votes = v._vote_rubric(ctx, ctx.problem, dict(_CAND),
                               use_deterministic=False)
    m.assert_called_once()                 # ← 绕过实例 patch 时此处红
    assert votes and votes[0].correct is False


def test_deterministic_check_patch_penetrates_vote_rubric():
    """patch `v._deterministic_check` → `v._vote_rubric` 的确定性旁证必须命中它。"""
    v, ctx = _vote_verifier('{"verdict":"A","confidence":0.9}')
    with mock.patch.object(v, "_vote_one_rubric",
                           return_value={"verdict": "A", "confidence": 0.9}), \
            mock.patch.object(v, "_deterministic_check",
                              return_value={"verdict": "fail",
                                            "evidence": "2^2=4≠2",
                                            "method": "sympy"}) as m:
        votes = v._vote_rubric(ctx, ctx.problem, dict(_CAND),
                               use_deterministic=True)
    m.assert_called_once()                 # ← 绕过实例 patch 时此处红
    assert any(getattr(x, "raw", "") == "deterministic_fail" for x in votes)


def test_challenge_counterexample_patch_penetrates_run():
    """patch `v._challenge_counterexample` → `v.run(use_challenge=True)` 必须命中它。"""
    v, ctx = _vote_verifier(
        '{"verdict":"B","confidence":0.8,"error_type":"概念错误",'
        '"step_index":null,"reason":"结论不成立"}')
    with mock.patch.object(
        v, "_challenge_counterexample",
        return_value={"hard_fail": True, "evidence": "n=0 处反例"}) as m:
        out = v.run(ctx, ctx.problem, [dict(_CAND, answer="x^2>=x")],
                    use_rubric=True, use_challenge=True, use_deterministic=False)
    m.assert_called_once()                 # ← 绕过实例 patch 时此处红
    raws = [getattr(x, "raw", "") for x in out["verdicts"][0]]
    assert "counterexample_fail" in raws


# ---------------------------------------------------------------------------
# C. 签名一致性
# ---------------------------------------------------------------------------
# C1：始终生效 —— 5 个 patch 靶点 + 两个公开入口的参数名必须锁定（跳板不得改签名）。
EXPECTED_PARAMS = {
    "_deep_llm": ["self", "ctx", "messages", "temperature", "max_tokens"],
    "llm": ["self", "ctx", "messages", "temperature", "max_tokens"],
    "_deterministic_check": ["self", "ctx", "problem", "candidate"],
    "_challenge_counterexample": ["self", "ctx", "problem", "candidate_text", "answer"],
    "_vote_one_rubric": ["self", "ctx", "problem", "candidate_text", "temperature"],
    "structured_report_for": ["self", "ctx", "problem", "candidate", "tool_findings"],
    "run": ["self", "ctx", "problem", "candidates", "use_clustering", "use_scoring",
            "is_proof", "use_playoff", "voting_times", "use_deterministic",
            "use_rubric", "use_challenge"],
}


@pytest.mark.parametrize("name", sorted(EXPECTED_PARAMS))
def test_signature_locked(name):
    params = list(inspect.signature(getattr(VerifierAgent, name)).parameters)
    assert params == EXPECTED_PARAMS[name], (
        f"{name} 调用签名被改动：期望 {EXPECTED_PARAMS[name]}，实际 {params}"
    )


# C2：前向守卫 —— S2 落地"同名跳板 → 目标模块实现"后自动生效。
# 比较时**跳过第 1 个参数**（跳板是 self，目标实现可能是 owner/receiver），
# 其余参数名必须逐一相同。模块/符号不存在时 skip（S1 阶段恒 skip）。
_SHIM_SPECS = (
    ("_normalize_answer_text", "agent.verifier__cluster"),
    ("_are_answers_equivalent", "agent.verifier__cluster"),
    ("_equiv_group", "agent.verifier__cluster"),
    ("_cluster_candidates", "agent.verifier__cluster"),
    ("_prepare_theorem_context", "agent.verifier__lemma"),
    ("_extract_bug_report", "agent.verifier__report"),
    ("_format_bug_report", "agent.verifier__report"),
    ("structured_report_for", "agent.verifier__report"),
    ("_vote_one", "agent.verifier__vote"),
    ("_vote", "agent.verifier__vote"),
    ("_vote_profile", "agent.verifier__vote"),
    # S4（2026-10-09）：深复核 / 反馈 / 投票三簇续搬（新增 verifier__deep）。
    ("_deep_final_review", "agent.verifier__deep"),
    ("_deep_review_finalize", "agent.verifier__deep"),
    ("_extract_feedback", "agent.verifier__report"),
    ("_oracle_sanity_feedback", "agent.verifier__report"),
    ("_extract_revise_feedback", "agent.verifier__report"),
    ("_is_correct_vote", "agent.verifier__vote"),
    ("_vote_one_scoring", "agent.verifier__vote"),
    ("_vote_rubric", "agent.verifier__vote"),
    ("_error_type_dist", "agent.verifier__vote"),
    ("_record_error_types", "agent.verifier__vote"),
)


@pytest.mark.parametrize("name,modpath", _SHIM_SPECS)
def test_shim_signature_matches_impl(name, modpath):
    mod = pytest.importorskip(modpath, reason="S2 尚未落地，目标模块不存在")
    impl = getattr(mod, name, None)
    if impl is None:
        pytest.skip(f"{modpath} 未导出 {name}（S2 命名尚未落定）")
    shim_params = list(inspect.signature(getattr(VerifierAgent, name)).parameters)[1:]
    impl_params = list(inspect.signature(impl).parameters)[1:]
    assert shim_params == impl_params, (
        f"{name} 跳板与 {modpath} 实现的参数不一致：{shim_params} vs {impl_params}"
    )


# ---------------------------------------------------------------------------
# D. 导入面不变
# ---------------------------------------------------------------------------
# 全仓外部 `from agent.verifier import ...` 实际用到的名字（含 orchestrator/agent.__init__）。
_IMPORT_SURFACE = (
    "VerifierAgent",
    "AnswerCluster",
    "ERROR_TYPE_TAGS",
    "_extract_error_type",
    "_last_verdict_ab",
    "_clip_review_prose",
)


@pytest.mark.parametrize("name", _IMPORT_SURFACE)
def test_import_surface_intact(name):
    assert hasattr(verifier_mod, name), (
        f"agent.verifier.{name} 被外部导入，拆分时不得消失（需原位保留或 re-export）"
    )


def test_external_importers_still_work():
    """消费方的最小冒烟：agent 包与 orchestrator 侧的名字仍可导入。"""
    import agent  # agent/__init__.py: from .verifier import VerifierAgent
    from agent.verifier import VerifierAgent as V2, _clip_review_prose
    assert getattr(agent, "VerifierAgent", None) is VerifierAgent, (
        "agent/__init__.py 必须继续 re-export VerifierAgent"
    )
    assert V2 is VerifierAgent
    assert callable(_clip_review_prose)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
