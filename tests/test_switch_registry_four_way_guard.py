# -*- coding: utf-8 -*-
"""开关注册「四处同步」守卫（2026-10-08）。

本文件防的是什么错
==================
本项目铁律：新增一个配置开关，必须**四处同时登记**，缺一不算完成。四处分别在哪里：

  ① 注册表      ``contracts/switch_registry.py::SWITCHES``
                （``agent/switch_registry.py`` 是它的**纯 re-export shim**，同一对象）
  ② 配置字段    ``AgentConfig`` —— 声明在 ``user_agent__config_base.py`` +
                ``user_agent__config.py``，由 ``user_agent.py`` 原位 re-export
  ③ 覆盖白名单  ``user_agent.py::_CONFIG_OVERRIDE_KEYS``
  ④ 参数用量表  ``agent/param_usage.py::_SPEC``

每一处缺失的后果**都是静默失败**（不报错、不崩溃，只是"看起来正常但没接上"）：

  · 缺 ①：开关改了不生效、``diag`` 的 ``switch_snapshot`` 查不到、报告还原不出来；
  · 缺 ②：``bind_config`` 用 ``getattr(cfg, field)`` 取不到该字段 ⇒ "配置覆盖"
          这一层读取链是死的（env > config > 默认 里的中间那层被架空）；
  · 缺 ③：CLI / kwargs 传入被 ``ReasoningAgent.__init__`` **静默丢弃**
          （本项目历史踩坑最多的一类）；
  · 缺 ④：启动统计 / 参数用量表看不到该开关的生效值（注册制第 ③ 件落空）。

四处漂移没有自动检查、全靠人记 ⇒ 本文件把"四处同步"固化为断言，**逐名定位**：
失败信息里带开关名 + 缺在哪一处。

真实不变式（2026-10-08 实测，见交付说明）
========================================
记 A=注册表名集、B=AgentConfig 字段集、C=白名单集、D=``_SPEC`` 名集：

  · ``A ⊆ B``  —— 当前成立；
  · ``A ⊆ C``  —— 当前成立；
  · ``A ⊆ D``  —— **当前不成立**：恰好缺 1 个 ``strict_all_rejected``
                 （已登记 ①②③、漏 ④）。该缺口**已在交付说明中如实上报**，
                 本任务只加测试、**不修生产代码**，故此处不写 ``A ⊆ D`` 的硬断言，
                 而用**已知缺口白名单** ``KNOWN_REGISTRY_NOT_IN_SPEC`` 显式钉住：
                 缺口**只能缩小、不能新增**（新增别名的登记缺失 ⇒ 测试立即变红）。
  · ``_SPEC`` 的**开关型**条目（``exact is None``）``⊆ A`` —— 当前成立
                 （``_SPEC`` 里不得出现账外的开关型条目）。

★ 本文件刻意**不用**"四处都能 import 就算过"这类橡皮图章断言：每一条都会
  在两个集合之差非空时逐名报出，且带"缺在哪一处"的定位。
"""
from __future__ import annotations

import ast
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from contracts.switch_registry import SWITCHES  # noqa: E402
from user_agent__config import AgentConfig  # noqa: E402
from agent.param_usage import _SPEC  # noqa: E402

# ---------------------------------------------------------------------------
# 已知缺口白名单（**不是**"允许不同步"，是"已上报、待处置的既有欠账"）
#   · strict_all_rejected：① contracts/switch_registry.py:286 有；②
#     user_agent__config_base.py:234 有；③ user_agent.py:164 有；④ _SPEC **缺**。
#   · 该集合**只可缩小**：若将来 ④ 补齐，本集合可删空（⊆ 判定仍绿）；
#     若有人再漏登记一个**新**开关到 _SPEC，名字不在本集合 ⇒ 立即变红。
# ---------------------------------------------------------------------------
KNOWN_REGISTRY_NOT_IN_SPEC = frozenset({"strict_all_rejected"})

# 锚点开关：跨类别各取一个，防止"集合被清空 ⇒ 断言真空通过"的退化。
_ANCHOR_SWITCHES = (
    "lean_verify",               # orchestrator 主通道总开关
    "toolcall_text_fallback",    # agent/base.py 文本工具调用
    "minimal_mode",              # user_agent.py 最小基础模式
    "artifact_store_enabled",    # agent/artifact_store.py
    "enable_final_answer_selection",
    "pool_gate_v2",
)


# ---------------------------------------------------------------------------
# 抽取四个集合
# ---------------------------------------------------------------------------
def _registry_names() -> set:
    """① 注册表名集（contracts 权威对象）。"""
    return set(SWITCHES)


def _config_field_names() -> set:
    """② AgentConfig 全部声明字段名（dataclass 继承合并后的字段集）。"""
    return set(AgentConfig.__dataclass_fields__)


def _override_whitelist() -> set:
    """③ 覆盖白名单（AST 读 user_agent.py 的模块级常量，非 import、非正则）。"""
    with open(os.path.join(REPO, "user_agent.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    keys: set = set()
    consumed_by_init = False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_CONFIG_OVERRIDE_KEYS"
                for t in node.targets):
            if isinstance(node.value, (ast.Tuple, ast.List)):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        keys.add(elt.value)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ReasoningAgent":
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "__init__":
                    for sub in ast.walk(fn):
                        if isinstance(sub, ast.Name) and sub.id == "_CONFIG_OVERRIDE_KEYS":
                            consumed_by_init = True
    assert keys, "未找到覆盖白名单常量 _CONFIG_OVERRIDE_KEYS（user_agent.py）"
    assert consumed_by_init, (
        "ReasoningAgent.__init__ 未引用 _CONFIG_OVERRIDE_KEYS ⇒ 白名单已失效")
    return keys


def _spec_all_names() -> set:
    """④ 参数用量表全部键名（含开关型与 cap 型）。"""
    return {row[0] for row in _SPEC}


def _spec_switch_names() -> set:
    """④ 中「开关型」条目（``exact is None``）的键名。"""
    return {row[0] for row in _SPEC if row[5] is None}


# ---------------------------------------------------------------------------
# 失败信息格式化：逐名 + 指出缺在哪一处
# ---------------------------------------------------------------------------
_PLACE = {
    "B": "② AgentConfig 配置字段（user_agent__config_base.py / user_agent__config.py）",
    "C": "③ 覆盖白名单 user_agent.py::_CONFIG_OVERRIDE_KEYS",
    "D": "④ 参数用量表 agent/param_usage.py::_SPEC",
    "A": "① 注册表 contracts/switch_registry.py::SWITCHES",
}


def _report(missing, place_key: str, *, direction: str) -> str:
    lines = [f"以下开关未登记（缺在 {_PLACE[place_key]}）："]
    for n in sorted(missing):
        lines.append(f"    - {n}")
    lines.append(
        f"（判定：{direction}；共缺 {len(missing)} 个。新增开关必须四处同时登记，"
        "缺一不算完成。）")
    return "\n".join(lines)


# ===========================================================================
# 0. 非空 / 锚点健全性：防止"集合被清空 ⇒ 断言真空通过"
# ===========================================================================
def test_00_registry_has_anchors_and_is_nonempty():
    A = _registry_names()
    assert len(A) >= 50, f"注册表开关数异常（{len(A)}），疑似被误清空"
    missing = [n for n in _ANCHOR_SWITCHES if n not in A]
    assert not missing, (
        "注册表缺少锚点开关（疑似被误删/改名，会导致后续断言真空通过）：\n"
        + "\n".join(f"    - {n}" for n in missing))


def test_01_all_four_sources_extract_nonempty():
    A = _registry_names()
    B = _config_field_names()
    C = _override_whitelist()
    D = _spec_all_names()
    sizes = {"①注册表": len(A), "②配置字段": len(B), "③白名单": len(C), "④_SPEC": len(D)}
    assert all(v > 0 for v in sizes.values()), f"某处抽取为空：{sizes}"


# ===========================================================================
# 1. A ⊆ B ：注册表每个开关都必须是已声明的 AgentConfig 字段
#    （否则 bind_config 的 getattr 取不到 ⇒ 配置覆盖层静默失效）
# ===========================================================================
def test_10_registry_subset_of_config_fields():
    A = _registry_names()
    B = _config_field_names()
    missing = A - B
    assert not missing, _report(
        missing, "B", direction="注册表 A ⊆ 配置字段 B")


# ===========================================================================
# 2. A ⊆ C ：注册表每个开关都必须在覆盖白名单内（否则 CLI/kwargs 被静默丢弃）
# ===========================================================================
def test_20_registry_subset_of_override_whitelist():
    A = _registry_names()
    C = _override_whitelist()
    missing = A - C
    assert not missing, _report(
        missing, "C", direction="注册表 A ⊆ 覆盖白名单 C")


# ===========================================================================
# 3. A ⊆ D（带已知缺口白名单）：注册表每个开关都必须在参数用量表内
#    当前恰缺 1 个 strict_all_rejected（已上报，未修）——以白名单显式钉住，
#    缺口只能缩小、不能新增。
# ===========================================================================
def test_30_registry_subset_of_param_usage_spec():
    A = _registry_names()
    D = _spec_all_names()
    missing = A - D
    unexpected = missing - KNOWN_REGISTRY_NOT_IN_SPEC
    assert not unexpected, _report(
        unexpected, "D",
        direction="注册表 A ⊆ 参数用量表 D（扣除已知缺口 "
                  f"{sorted(KNOWN_REGISTRY_NOT_IN_SPEC)} 后）")
    # 已知缺口本身必须仍是"真缺口"：若它已被补齐，请从白名单移除该名
    # （否则白名单会变成永久的橡皮图章）。
    stale = KNOWN_REGISTRY_NOT_IN_SPEC - missing
    assert not stale, (
        "已知缺口白名单已过期：下列名字现已登记进 _SPEC，应从 "
        f"KNOWN_REGISTRY_NOT_IN_SPEC 中删除：{sorted(stale)}")


def test_31_known_gap_is_still_a_registered_switch():
    """钉住已知缺口的名字仍是注册表里的真开关（防止白名单挂着一个不存在的名字）。"""
    A = _registry_names()
    bogus = KNOWN_REGISTRY_NOT_IN_SPEC - A
    assert not bogus, (
        "已知缺口白名单含未注册的名字（疑似改名/删除后未同步）："
        f"{sorted(bogus)}")


# ===========================================================================
# 4. 反向：_SPEC 的「开关型」条目 ⊆ A
#    （_SPEC 里不得出现账外的开关型条目；cap 型条目不受此约束）
# ===========================================================================
def test_40_spec_switch_entries_are_registered():
    A = _registry_names()
    sw = _spec_switch_names()
    assert sw, "未抽取到 _SPEC 开关型条目（exact is None），判定逻辑可能已失效"
    extra = sw - A
    assert not extra, (
        "以下「开关型」条目出现在 _SPEC 但**未进注册表**（账外开关，"
        "应补登记到 contracts/switch_registry.py::SWITCHES）：\n"
        + "\n".join(f"    - {n}" for n in sorted(extra)))


# ===========================================================================
# 5. shim 与实现同一对象（④之外的结构不变式，顺带守住"注册表只有一份"）
# ===========================================================================
def test_50_agent_shim_is_same_switches_object():
    import agent.switch_registry as asr
    import contracts.switch_registry as csr
    assert asr.SWITCHES is csr.SWITCHES, (
        "agent/switch_registry.py 必须是对 contracts/switch_registry.py 的"
        "纯 re-export shim（SWITCHES 必须是同一对象，不是拷贝）")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
