# -*- coding: utf-8 -*-
"""题意前置理解回归测试（2026-10-12；★ 2026-10-14 收敛重写）。

用户设计（方案 v4 §3.5，Q6–Q10）**已按 2026-10-14 口径收敛**：
  「题意理解只做『让模型注意到我们所需要求解的部分』，对题目整体的理解归蓝图构建」
  ⇒ 只保留 **终态 + 答案槽（纯符号）+ 缺口 A/B** 三联产出；
  ⇒ 删「逻辑链 chain + 一致性复推 + 链的 Lean 自检」（与 2.7 蓝图 DAG 同层同义）；
  ⇒ answer_slot / terminal_state 由代码**机械剥离**被写死的数值（K11 防泄漏）。
★ 2026-10-14（同日晚，用户决策「涉及大模型的地方生成三遍 —— 再生成后再在生成的基础
  上重新生成两遍，然后采取第三遍的结果」）：LLM 生成改**多遍迭代**（默认 3 遍）——
  第 1 遍从零生成，第 2…N 遍喂回上一遍结果要求重新生成，**采用最后一遍**；
  某遍不可解析即停、沿用最近一遍可用结果。遍数=1 回退单轮旧行为。

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

def _cfg(passes=3, enabled=True):
    return SimpleNamespace(enable_understanding_chain=enabled,
                           understanding_passes=passes)


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


def _payload(tag, slot=None):
    """每遍产出的 JSON（tag 用于区分第几遍，便于断言"取的是最后一遍"）。"""
    return json.dumps(
        {"terminal_state": "终态-" + tag,
         "answer_slot": slot or ("待求量 " + tag),
         "gaps": [{"kind": "A", "detail": "缺上界-" + tag}]},
        ensure_ascii=False)


def test_disabled_short_circuit_does_not_call_llm():
    calls = []
    v = LeanPreVerifier.__new__(LeanPreVerifier)
    v.config = _cfg(passes=3, enabled=False)
    v.llm = lambda *a, **k: calls.append(1)
    v.record = lambda *a, **k: None
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)
    assert ctx.understanding_chain == {"enabled": False}
    assert calls == [], "开关关闭时不得调用 LLM"


def test_empty_problem_short_circuit():
    v = LeanPreVerifier.__new__(LeanPreVerifier)
    v.config = _cfg()
    v.llm = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应调用"))
    v.record = lambda *a, **k: None
    ctx = _mk_ctx(problem="   ")
    v.run_understanding_chain(ctx)
    assert ctx.understanding_chain["verdict"] == "unknown"


def test_three_passes_takes_last_one():
    """★ 2026-10-14：三遍生成（第 2/3 遍在上一遍基础上重新生成）⇒ 采用**第三遍**结果。"""
    v = _mk_verifier(_cfg(3), [_payload("1"), _payload("2"), _payload("3")])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)
    out = ctx.understanding_chain
    assert out["verdict"] == "ok"
    assert out["passes"] == 3 and out["rounds"] == 3
    assert out["terminal_state"] == "终态-3"
    assert out["answer_slot"] == "待求量 3"
    # 每遍原始产出留痕（供对比"第 1 遍 vs 第 3 遍"）
    assert [h["pass"] for h in out["pass_history"]] == [1, 2, 3]
    assert [h["terminal_state"] for h in out["pass_history"]] == \
        ["终态-1", "终态-2", "终态-3"]
    assert ctx.understanding_rounds == 3
    # 旧机制字段**必须仍不存在**（链已随收敛删除）
    for dead in ("chain", "consistent", "diffs", "lean_code", "lean_verdict"):
        assert dead not in out, "字段 %s 应随题意理解收敛删除" % dead
    assert out["gaps_a"] and not out["gaps_b"]
    assert ctx.understanding_gaps[0]["kind"] == "A"


def test_later_pass_receives_previous_result():
    """「在生成的基础上重新生成」⇒ 第 2/3 遍的提示词里必须带**上一遍结果**。"""
    seen = []
    v = _mk_verifier(_cfg(3), [_payload("1"), _payload("2"), _payload("3")])
    _inner = v.llm

    def _cap(ctx, msgs, t=0.1, mt=8192):
        seen.append(msgs[-1]["content"])
        return _inner(ctx, msgs, t, mt)

    v.llm = _cap
    v.run_understanding_chain(_mk_ctx())
    assert len(seen) == 3, "默认 3 遍 ⇒ 3 次 LLM 调用"
    assert "终态-1" not in seen[0], "第 1 遍必须从零生成（不喂上一遍结果）"
    assert "终态-1" in seen[1], "第 2 遍必须带上第 1 遍结果"
    assert "终态-2" in seen[2], "第 3 遍必须带上第 2 遍结果"
    assert "第 3 遍" in seen[2] and "共 3 遍" in seen[2]


def test_passes_one_falls_back_to_single_round():
    """=1 ⇒ 回退单轮旧行为（消融对照）。"""
    v = _mk_verifier(_cfg(1), [_payload("1")])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)
    out = ctx.understanding_chain
    assert out["passes"] == 1 and out["rounds"] == 1
    assert out["terminal_state"] == "终态-1"
    assert len(out["pass_history"]) == 1


def test_passes_defaults_to_three_when_config_field_missing():
    """兜底值必须与 AgentConfig.understanding_passes(=3) 一致（"两套默认值"纪律）。"""
    v = _mk_verifier(SimpleNamespace(enable_understanding_chain=True),
                     [_payload("1"), _payload("2"), _payload("3")])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)
    assert ctx.understanding_chain["passes"] == 3
    assert ctx.understanding_chain["rounds"] == 3


def test_unparseable_later_pass_keeps_previous_result():
    """第 3 遍不可解析 ⇒ 停在第 2 遍（沿用最近一遍可用结果），不判 unknown。"""
    v = _mk_verifier(_cfg(3), [_payload("1"), _payload("2"), "这不是 JSON"])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)
    out = ctx.understanding_chain
    assert out["verdict"] == "ok" and out["rounds"] == 2
    assert out["terminal_state"] == "终态-2"
    assert "第 3 遍输出不可解析" in out["reason"]


def test_understanding_passes_registered_everywhere():
    """四处同步：注册表 / 配置字段 / 覆盖白名单 / 参数用量表（门禁按注册表比对）。"""
    places = {"① 注册表": "contracts/switch_registry.py",
              "② 配置字段": "user_agent__config.py",
              "③ 覆盖白名单": "user_agent.py",
              "④ 参数用量表": "agent/param_usage.py"}
    for label, rel in places.items():
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            assert "understanding_passes" in fh.read(), \
                "开关 understanding_passes 未在%s登记（四处同步纪律）" % label


def test_answer_slot_values_are_mechanically_masked():
    """★ 2026-10-14：LLM 无视提示词禁令写死数值时，代码必须兜底剥离（K11）。"""
    bad = json.dumps({"terminal_state": "T 的最大值为 1/2",
                      "answer_slot": r"T = \frac{\sqrt{5}-1}{2}", "gaps": []},
                     ensure_ascii=False)
    v = _mk_verifier(_cfg(3), [_payload("1"), _payload("2"), bad])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)
    out = ctx.understanding_chain
    assert "frac" not in out["answer_slot"], "答案槽里的 LaTeX 值必须被剥离"
    assert "1/2" not in out["terminal_state"]


def test_unparseable_llm_output_degrades_without_raise():
    v = _mk_verifier(_cfg(3), ["这不是 JSON", "也不是"])
    ctx = _mk_ctx()
    v.run_understanding_chain(ctx)          # 不得抛异常
    out = ctx.understanding_chain
    assert out["verdict"] == "unknown"
    # 2026-10-13：文案更新（新增「降级重试」）⇒ 断言同步。
    # ⚠ 非放宽判据：仍要求「不可解析」被显式记录；并新增「重试用过」的断言（更严）。
    assert out["reason"].startswith("LLM 输出不可解析")
    assert out.get("retry_used") is True, "首遍解析失败应触发一次降级重试"
    # ★ 2026-10-14 多遍化后语义更严：无任何一遍产出可用结果 ⇒ rounds=0
    #   （旧实现无条件写 1，会把"烧了一轮但什么都没产出"伪装成"跑了 1 轮"）。
    assert out["rounds"] == 0
    assert ctx.understanding_rounds == 0
    assert out["pass_history"] == []
