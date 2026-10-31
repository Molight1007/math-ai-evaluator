# -*- coding: utf-8 -*-
"""2.7 拆法约束（`blueprint_goal_kind_guidance`）测试。

覆盖三件事：
1. **目标种类判定**：用本轮 4 道池空题的**真实题面**做正/负样本
   —— 3 道该命中 `instance`，最值/计数的 3593/2163/1322/1633 必须**不**命中。
2. **注入位置**：约束块必须在「输出格式」小节**之前**，且提示词结尾逐字不变
   （追加到末尾会破坏「只输出 JSON」的收尾结构，诱使模型进入续写模式）。
3. **开关关断**：`BLUEPRINT_GOAL_KIND_GUIDANCE=0` ⇒ 提示词逐字回到改动前。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.blueprint_decomposition import (
    KIND_FAMILY, KIND_INSTANCE,
    _OUTPUT_SECTION_ANCHOR, goal_kind, guidance_block,
    inject_into_system, scope_leak_nodes,
)
from prompts.blueprint import BLUEPRINT_DAG_SYSTEM


# ---------------------------------------------------------------- 题面样本
# 直接抄自 `题库/omni8_20261027.jsonl` 的原文（本轮 A/B 用的那批），
# 保证判据不是照着想象中的题面写的。
_P3556 = ("Find an integer $n$, where $100 \\leq n \\leq 1997$, such that \n"
          "\\[ \\frac{2^n+2}{n}  \\] \nis also an integer.")
_P3876 = ("Let $ f(n)$ be a function defined on the set of all positive integers "
          "and having its values in the same set. Suppose that "
          "$ f(f(n) \\plus{} f(m)) \\equal{} m \\plus{} n$ for all positive "
          "integers $ n,m.$ Find the possible value for $ f(1988).$")
_P1352 = ("Ten positive integers are arranged around a circle. Each number is one "
          "more than the greatest common divisor of its two neighbors. What is the "
          "sum of the ten numbers?")
_P3593 = ("Every pair of communities in a county are linked directly by one mode of "
          "transportation; bus, train, or airplane. All three methods of "
          "transportation are used in the county with no community being serviced by "
          "all three modes and no three communities being linked pairwise by the same "
          "mode. Determine the largest number of communities in this county.")
_P2163 = "What is the minimum possible number of illuminated cells?"
_P1322 = ("Determine the number of roots of unity that are also roots of "
          "$z^{2}+a z+b=0$ for some integers $a,b$.")
_P1633 = "Determine the number of possible configurations made by drawing segments."


def _ctx(problem: str):
    return SimpleNamespace(problem=problem)


# ---------------------------------------------------------------- 目标种类
@pytest.mark.parametrize("name,text", [
    ("omni-3556", _P3556),
    ("omni-3876", _P3876),   # 题干含 `for all`，但那是**条件**不是目标
    ("omni-1352", _P1352),
])
def test_instance_detected(name, text):
    assert goal_kind(_ctx(text)) == KIND_INSTANCE, name


@pytest.mark.parametrize("name,text", [
    ("omni-3593", _P3593),   # 最值
    ("omni-2163", _P2163),   # 最值
    ("omni-1322", _P1322),   # 计数
    ("omni-1633", _P1633),   # 计数
])
def test_optimum_and_count_not_constrained(name, text):
    """最值 / 计数题**本来就需要全称论证** ⇒ 必须不注入条件层。

    这是本轮唯一的误伤风险点：要求它们"只做构造验证"会帮倒忙。
    """
    assert goal_kind(_ctx(text)) == "", name


def test_family_detected():
    assert goal_kind(_ctx("Find all functions $A:\\mathbb{R}\\to\\mathbb{R}$ such "
                          "that $A(p)A(q)=A(p+q)$.")) == KIND_FAMILY


def test_proof_not_constrained():
    for t in ("证明：对任意正整数 n，n^3-n 能被 6 整除。",
              "Prove that there are infinitely many primes."):
        assert goal_kind(_ctx(t)) == "", t


def test_empty_problem_returns_blank():
    assert goal_kind(_ctx("")) == ""


# ---------------------------------------------------------------- 注入位置
def test_anchor_present():
    """系统提示词改版时会先在这里炸，而不是静默失去约束。"""
    assert _OUTPUT_SECTION_ANCHOR in BLUEPRINT_DAG_SYSTEM


def test_block_goes_before_output_section():
    out = inject_into_system(BLUEPRINT_DAG_SYSTEM, KIND_INSTANCE)
    assert out != BLUEPRINT_DAG_SYSTEM
    assert out.index("陈述纪律") < out.index("输出格式（必须严格遵循")
    assert out.index("本题拆法") < out.index("输出格式（必须严格遵循")


def test_tail_unchanged():
    """★ 提示词**结尾必须逐字不变** —— 模型靠这个尾巴收束成纯 JSON。"""
    out = inject_into_system(BLUEPRINT_DAG_SYSTEM, KIND_INSTANCE)
    assert out.endswith(BLUEPRINT_DAG_SYSTEM[-400:])


def test_base_rule_always_present_even_without_kind():
    """判不出目标种类 ⇒ 仍注入无条件层（陈述纪律），但不注入条件层。"""
    blk = guidance_block("")
    assert "陈述纪律" in blk
    assert "本题拆法" not in blk


def test_family_gets_its_own_block():
    blk = guidance_block(KIND_FAMILY)
    assert "完整刻画一整类对象" in blk
    assert "本题拆法" in blk


def test_missing_anchor_returns_base():
    """锚点缺失时原样返回，不抛异常（提示词是内容资产，改版不该崩主链）。"""
    assert inject_into_system("没有锚点的提示词", KIND_INSTANCE) == "没有锚点的提示词"


# ---------------------------------------------------------------- 开关
def test_switch_off_returns_base(monkeypatch):
    from agent.blueprint_planner import _system_for
    monkeypatch.setenv("BLUEPRINT_GOAL_KIND_GUIDANCE", "0")
    assert _system_for(_ctx(_P3556)) == BLUEPRINT_DAG_SYSTEM


def test_switch_on_injects(monkeypatch):
    from agent.blueprint_planner import _system_for
    monkeypatch.setenv("BLUEPRINT_GOAL_KIND_GUIDANCE", "1")
    out = _system_for(_ctx(_P3556))
    assert out != BLUEPRINT_DAG_SYSTEM
    assert "本题拆法" in out


# ---------------------------------------------------------------- 观测
class _Node:
    def __init__(self, statement):
        self.statement = statement


class _Dag:
    def __init__(self, root_id, nodes):
        self.root_id = root_id
        self.nodes = nodes


def test_scope_leak_nodes_finds_universal_and_skips_root():
    dag = _Dag("g", {
        "g": _Node("求最小的整数 n"),                                  # 根：跳过
        "n1": _Node("证明满足 n|2^n+2 的 n 必为偶数"),                  # 全称，但**正确**
        "n2": _Node("证明若 m 为奇数且 m|2^{2m-1}+1，则 m 必整除 15"),  # 越界引理
        "n3": _Node("计算 2^5+1 = 33"),                                # 普通
    })
    hit = dict(scope_leak_nodes(dag))
    assert "g" not in hit
    assert "n2" in hit
    assert "n3" not in hit


def test_scope_leak_nodes_never_raises():
    """观测逻辑绝不阻断：坏输入一律返回空列表。"""
    assert scope_leak_nodes(object()) == []
    assert scope_leak_nodes(None) == []
