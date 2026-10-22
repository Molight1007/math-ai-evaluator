# -*- coding: utf-8 -*-
"""检测链端到端装配测试 —— 2026-10-22。

目的：把「正确候选留下、错误候选淘汰」这条**跨环节契约**钉成回归测试。
单点单测（test_self_auditor / test_math_check_gate）只验一个环节，
这里验的是「4.0 → 4.1 → 4.4 串起来之后，噪声候选池是否被收敛到正确答案」。

LLM 用桩（按候选标记返回判定），因此测试零外部依赖、可进 CI；
真实 API 下的同款验证见 2026-10-22 的端到端探针（6 题 18 候选，误杀 0 / 漏杀 0）。
"""
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.answer_normalizer import normalize_stage  # noqa: E402
from agent.base import Candidate  # noqa: E402
from agent.math_check_gate import math_check_stage  # noqa: E402
from agent.self_auditor import self_audit_stage  # noqa: E402

PROBLEM = "求 777^2 的值。"
# 推理里带 `[[BAD]]` 标记 ⇒ 桩判逻辑错；否则通过。真实 LLM 按语义判断，
# 这里模拟「能不能指出原文里的具体错误」这一契约。
GOOD_REASON = "777^2 = 777*777 = 603729。"
BAD_REASON = "777^2 = 777*777 = 603730。[[BAD]]"


class _Ctx:
    def __init__(self, cands):
        self.problem = PROBLEM
        self.candidates = list(cands)
        self.trace = []
        self.domain = ""
        self.question_type = ""
        self.start_time = time.time()
        self.deadline = 0
        self.metadata = {}
        self.budget = None

    def gen_time_up(self):
        return False


class _Orch:
    """最小 Orchestrator：只提供 4.0/4.1/4.4 用到的 record / llm。"""

    def __init__(self):
        from user_agent__config import AgentConfig
        self.config = AgentConfig(audit_obligation_ledger=False)
        self.client = None
        self.events = []

    def record(self, ctx, step, msg, **kw):
        self.events.append((step, msg))

    def llm(self, ctx, messages, temperature=0.0, max_tokens=1024):
        user = ""
        for m in messages:
            if m.get("role") == "user":
                user = str(m.get("content") or "")
        if "[[BAD]]" in user:
            # error_at 逐字引用原文 ⇒ 通过证据落地门（2026-10-22 新增）
            return ('{"logic_error": true, "error_desc": "算术结果与断言不符",'
                    ' "error_at": "777^2 = 777*777 = 603730。",'
                    ' "obligation_id": ""}')
        return '{"logic_error": false, "error_desc": "", "error_at": ""}'


def _run(cands):
    orch = _Orch()
    ctx = _Ctx(cands)
    normalize_stage(orch, ctx)
    self_audit_stage(orch, ctx)
    math_check_stage(orch, ctx)
    return ctx, [c.id for c in ctx.candidates]


def test_chain_keeps_correct_and_drops_logic_error():
    cands = [Candidate(id=1, answer="603729", reasoning=GOOD_REASON),
             Candidate(id=2, answer="603730", reasoning=BAD_REASON)]
    ctx, alive = _run(cands)
    assert alive == [1]
    assert ctx.self_audit["n_rejected"] == 1


def test_chain_keeps_correct_answer_untouched():
    """正确答案不许被任何一道淘汰（误杀检查）。"""
    cands = [Candidate(id=1, answer="603729", reasoning=GOOD_REASON)]
    _ctx, alive = _run(cands)
    assert alive == [1]


def test_arithmetic_checked_by_math_gate_not_self_audit():
    """推理自洽但算术写错：自审放行、**4.4 必须接住**（这是两环互补的核心）。"""
    cands = [Candidate(id=1, answer="603730",
                       reasoning="777^2 = 777*777 = 603730。")]
    ctx, alive = _run(cands)
    assert alive == []                       # 被 4.4 淘汰
    assert ctx.math_check["n_rejected"] == 1
    assert ctx.math_check["n_by_method"].get("calc_verify") == 1
    assert ctx.self_audit["n_rejected"] == 0


def test_correct_arithmetic_not_killed():
    cands = [Candidate(id=1, answer="603729", reasoning=GOOD_REASON)]
    ctx, alive = _run(cands)
    assert alive == [1]
    assert ctx.math_check["n_rejected"] == 0


def test_mixed_pool_converges_to_single_correct():
    """混合池：正确 + 逻辑错 + 算术错 ⇒ 只剩正确的那一个。"""
    cands = [
        Candidate(id=1, answer="603729", reasoning=GOOD_REASON),
        Candidate(id=2, answer="603730", reasoning="777^2 = 777*777 = 603730。"),
        Candidate(id=3, answer="603729", reasoning=BAD_REASON),
    ]
    _ctx, alive = _run(cands)
    assert alive == [1]


def test_empty_pool_does_not_crash():
    _ctx, alive = _run([])
    assert alive == []


def test_multivalue_answer_survives_normalize():
    """多值答案不该被 4.0 判成 unparseable（否则正确答案直接被剔除）。"""
    cands = [Candidate(id=1, answer="2,3", reasoning="x^2-5x+6=(x-2)(x-3)。")]
    ctx, alive = _run(cands)
    assert alive == [1]
    assert getattr(cands[0], "answer_kind", "") == "multi"
