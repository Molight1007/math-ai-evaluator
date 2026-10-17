# -*- coding: utf-8 -*-
"""题意前置理解回归测试（2026-10-12；★ 2026-10-14 收敛重写）。

用户设计（方案 v4 §3.5，Q6–Q10）**已按 2026-10-14 口径收敛**：
  「题意理解只做『让模型注意到我们所需要求解的部分』，对题目整体的理解归蓝图构建」
  ⇒ 只保留 **终态 + 答案槽（纯符号）+ 缺口 A/B** 三联产出；
  ⇒ 删「逻辑链 chain + 一致性复推 + 链的 Lean 自检」（与 2.7 蓝图 DAG 同层同义）；
  ⇒ answer_slot / terminal_state 由代码**机械剥离**被写死的数值（K11 防泄漏）。

本测试不依赖 Lean 环境与真实 LLM（全部用桩），只验证**纯逻辑与开关契约**。
"""
import json
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.lean_local.lean_pre_verifier import (  # noqa: E402
    LeanPreVerifier, _mask_answer_values, split_gaps)


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


def test_mask_answer_values_strips_concrete_values():
    """★ 2026-10-14：代码机械剥离被写死的数值（K11 防泄漏）。"""
    # 实测泄漏原句（official112-002，gold=1/2）—— 激进口径必须掩掉整个赋值
    m = _mask_answer_values(r"T = \frac{\sqrt{5}-1}{2}", aggressive=True)
    assert "frac" not in m and "5" not in m
    # 基础口径（终态）：掩「…等于 N」形态……
    assert _mask_answer_values("最大值为 42") != "最大值为 42"
    # ……但不误伤符号等式
    assert _mask_answer_values("n² - n = 2k") == "n² - n = 2k"
    # 纯符号槽本就不受影响
    assert _mask_answer_values("∃ n, P(n) ∧ ∀ m, m > n → ¬P(m)") == \
        "∃ n, P(n) ∧ ∀ m, m > n → ¬P(m)"
    assert _mask_answer_values("") == ""
    # 激进口径只给 answer_slot 用；非激进时 `X = 42` 不被掩（避免误伤终态里的符号）
    assert _mask_answer_values("f(x) = 42") == "f(x) = 42"


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


def test_single_round_terminal_slot_and_gaps_only():
    """★ 2026-10-14：单轮定案 = 终态 + 答案槽 + 缺口 A/B；**不再有 chain/复推**。"""
    payload = {"terminal_state": "n 为最大可行值", "answer_slot": "待求量 n_max",
               "gaps": [{"kind": "A", "detail": "缺上界"},
                        {"kind": "B", "detail": "题面已给 a>0 但本轮没读到"}]}
    v = _mk_verifier(SimpleNamespace(enable_understanding_chain=True),
                     [json.dumps(payload, ensure_ascii=False)])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)
    out = ctx.understanding_chain
    # ★ 2026-10-17（089 误读修复）：gaps_a 非空 ⇒ verdict=assumption_required
    #   （原实现只看到"有终态"就判 ok，忽略题面歧义）
    assert out["verdict"] == "assumption_required"
    assert out["rounds"] == 1
    assert out["terminal_state"] == "n 为最大可行值"
    assert out["answer_slot"] == "待求量 n_max"
    # 链 / 一致性 / 差异 三个字段**必须已消失**（题链已随收敛删除）
    for dead in ("chain", "consistent", "diffs", "lean_code", "lean_verdict"):
        assert dead not in out, "字段 %s 应随题意理解收敛删除" % dead
    assert out["gaps_a"] and out["gaps_b"]
    assert ctx.understanding_gaps[0]["kind"] == "A"
    assert ctx.understanding_rounds == 1


def test_answer_slot_values_are_mechanically_masked():
    """★ 2026-10-14：LLM 无视提示词禁令写死数值时，代码必须兜底剥离（K11）。"""
    payload = {"terminal_state": "T 的最大值为 1/2",
               "answer_slot": r"T = \frac{\sqrt{5}-1}{2}", "gaps": []}
    v = _mk_verifier(SimpleNamespace(enable_understanding_chain=True),
                     [json.dumps(payload, ensure_ascii=False)])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)
    out = ctx.understanding_chain
    assert "frac" not in out["answer_slot"], "答案槽里的 LaTeX 值必须被剥离"
    assert "1/2" not in out["terminal_state"]


def test_unparseable_llm_output_degrades_without_raise():
    v = _mk_verifier(SimpleNamespace(enable_understanding_chain=True),
                     ["这不是 JSON", "也不是"])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)          # 不得抛异常
    out = ctx.understanding_chain
    assert out["verdict"] == "unknown"
    # 2026-10-13：文案更新（新增「降级重试」）⇒ 断言同步。
    # ⚠ 非放宽判据：仍要求「不可解析」被显式记录；并新增「重试用过」的断言（更严）。
    assert out["reason"].startswith("LLM 输出不可解析")
    assert out.get("retry_used") is True, "首轮解析失败应触发一次降级重试"
    assert out["rounds"] == 1
