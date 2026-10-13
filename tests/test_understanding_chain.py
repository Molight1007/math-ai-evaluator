# -*- coding: utf-8 -*-
"""题意前置理解升级（终态逻辑链 + Lean 自检 + 一致性复推）回归测试（2026-10-12）。

用户设计（方案 v4 §3.5，Q6–Q10）：
  · 终态用**符号槽**（禁写具体值）；
  · **无条件反复理解** = 带着上一轮结论重推并报告是否一致（Q7）；
  · 缺口强制二分：A=题面没给 / B=题面给了但没读到。
本测试不依赖 Lean 环境与真实 LLM（全部用桩），只验证**纯逻辑与开关契约**。
"""
import json
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.lean_local.lean_pre_verifier import (  # noqa: E402
    LeanPreVerifier, _canonical_chain, split_gaps)


# ---------------------------------------------------------------- 纯函数

def test_split_gaps_binary_classification():
    a, b = split_gaps([
        {"kind": "A", "detail": "题面未给出 n 的上界"},
        {"kind": "B", "detail": "题面已给 a>0 但本轮没用到"},
        {"kind": "b", "detail": "小写也应识别为 B"},
        {"detail": "无 kind ⇒ 保守归 A"},
        {"kind": "A", "detail": "   "},          # 空 detail 丢弃
    ])
    assert [g["detail"] for g in a] == ["题面未给出 n 的上界", "无 kind ⇒ 保守归 A"]
    assert [g["detail"] for g in b] == ["题面已给 a>0 但本轮没用到", "小写也应识别为 B"]
    assert split_gaps(None) == ([], [])
    assert split_gaps(["裸字符串缺口"]) == ([{"kind": "A", "detail": "裸字符串缺口"}], [])


def test_canonical_chain_ignores_whitespace_and_key_order():
    c1 = [{"premises": ["a > 0"], "conclusion": "b > 0"}]
    c2 = [{"conclusion": "b>0", "premises": ["a>0"]}]
    assert _canonical_chain(c1) == _canonical_chain(c2)
    c3 = [{"premises": ["a > 0"], "conclusion": "b >= 0"}]
    assert _canonical_chain(c1) != _canonical_chain(c3)
    assert _canonical_chain(None) == ""
    assert _canonical_chain([{"premises": "x", "conclusion": "y"}]) == "x=>y"


# ---------------------------------------------------------------- 契约

def _mk_verifier(cfg, replies):
    """构造不走 __init__ 的实例（避开 BaseAgent 的 client 依赖）。"""
    v = LeanPreVerifier.__new__(LeanPreVerifier)
    v.config = cfg
    v.llm = lambda ctx, msgs, t=0.1, mt=8192: replies.pop(0) if replies else ""
    v.record = lambda ctx, step, msg, **kw: None
    return v


def _mk_ctx(**kw):
    d = dict(problem="求最大的 n 使得 P(n) 成立", domain="数论",
             is_time_critical=lambda: False,
             understanding_chain=None, understanding_gaps=[], understanding_rounds=0)
    d.update(kw)
    return SimpleNamespace(**d)


def test_disabled_short_circuit_does_not_call_llm():
    calls = []
    v = LeanPreVerifier.__new__(LeanPreVerifier)
    v.config = SimpleNamespace(enable_understanding_chain=False)
    v.llm = lambda *a, **k: calls.append(1)
    v.record = lambda *a, **k: None
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)
    assert ctx.understanding_chain == {"enabled": False}
    assert calls == [], "开关关闭时不得调用 LLM"


def test_empty_problem_short_circuit():
    v = LeanPreVerifier.__new__(LeanPreVerifier)
    v.config = SimpleNamespace(enable_understanding_chain=True)
    v.llm = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应调用"))
    v.record = lambda *a, **k: None
    ctx = _mk_ctx(problem="   ")
    v.run_understanding_chain(ctx)
    assert ctx.understanding_chain["verdict"] == "unknown"


def test_refine_loop_runs_and_stops_on_no_gain():
    """两轮返回同一条链 ⇒ 无增益早停应在第 2 轮结束（不跑满 3 轮）。"""
    same = {"terminal_state": "n 为最大可行值", "answer_slot": "∃ n, P(n)",
            "chain": [{"premises": ["P(k) 成立"], "conclusion": "k ≤ n"}],
            "lean_code": "", "gaps": [{"kind": "A", "detail": "缺上界"}]}
    nxt = dict(same, consistent=True, diffs=[])
    v = _mk_verifier(SimpleNamespace(
        enable_understanding_chain=True, understanding_refine_rounds=3,
        understanding_no_gain_stop=True, understanding_chain_lean_check=False),
        [json.dumps(same, ensure_ascii=False),
         json.dumps(nxt, ensure_ascii=False),
         json.dumps(nxt, ensure_ascii=False)])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)
    out = ctx.understanding_chain
    assert out["verdict"] == "ok"
    assert out["rounds"] == 2, "无增益早停应在第 2 轮生效，实际 %d" % out["rounds"]
    assert out["consistent"] is True
    assert len(out["chain"]) == 1
    assert out["gaps_a"] and not out["gaps_b"]
    assert ctx.understanding_gaps[0]["kind"] == "A"
    assert out["lean_verdict"] == "skipped", "关闭 Lean 检查时应为 skipped"


def test_unparseable_llm_output_degrades_without_raise():
    v = _mk_verifier(SimpleNamespace(
        enable_understanding_chain=True, understanding_refine_rounds=3,
        understanding_no_gain_stop=True, understanding_chain_lean_check=False),
        ["这不是 JSON", "也不是", "仍不是"])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)          # 不得抛异常
    out = ctx.understanding_chain
    assert out["verdict"] == "unknown"
    # 2026-10-13：文案更新（新增「降级重试」）⇒ 断言同步。
    # ⚠ 非放宽判据：仍要求「不可解析」被显式记录；并新增「重试用过」的断言（更严）。
    assert out["reason"].startswith("LLM 输出不可解析")
    assert out.get("retry_used") is True, "首轮解析失败应触发一次降级重试"
    assert out["rounds"] == 1
