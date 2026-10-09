# -*- coding: utf-8 -*-
"""开关 env 桥守卫（2026-10-09）。

本文件防的是什么错
==================
`contracts/switch_registry.py` 白纸黑字承诺开关的读取优先级是：

    环境变量  >  AgentConfig 覆盖（CLI / kwargs）  >  默认值

但此前只有两段接线：`kwargs → config`（`ReasoningAgent.__init__`）与
`config → registry`（`bind_config`），**缺 env → config 这一段**。后果：

  · 对**只被 `getattr(self.config, X)` 读取**的开关，env **完全无效**：
        env `DIVERSITY_RESAMPLE=0` ⇒ 注册表认了 `False`，而
        `AgentConfig().diversity_resample_enabled` 仍是 `True`；
  · 连带的第二处缺陷：`agent/param_usage.py::_SPEC` 的 cap_fn 全是
    `getattr(cfg, _f, _d)` ⇒ 上报的是 **config 值而非生效值**，
    于是同一份 `diag` 里 `switch_snapshot`（对）与 `param_usage`（错）自相矛盾。

修法：`AgentConfig.__post_init__` 末尾调用
`contracts.switch_registry.apply_env_to_config(self)`，把 env 里**确实存在**的
开关写回同名字段 ⇒ `getattr(config, 字段)` 恒等于注册表生效值（`param_usage`
因读 `getattr(cfg, ...)` 随之自动纠正）。

本文件把这条不变式**逐名**固化为断言：
  · 每个「注册名 ∩ AgentConfig 字段」：设一个**与默认值不同**的 env ⇒
    `getattr(AgentConfig(), 字段) == 注册表生效值`（且 ≠ 默认值，证明确实生效）；
  · env 不设时 ⇒ 字段值 == 该字段的声明默认值（不破坏「config > 默认值」这半语义）。

判别力自证（必做）
==================
把 `user_agent__config.py::__post_init__` 末尾对 `apply_env_to_config` 的调用
注释掉 ⇒ 本文件 `test_env_overrides_config_field[...]` 必须**变红**；加回 ⇒ 变绿。
（否则本守卫就是橡皮图章。）
"""
from __future__ import annotations

import dataclasses
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from contracts.switch_registry import (  # noqa: E402
    SWITCHES,
    get_bool,
    get_num,
    get_str,
)
from user_agent__config import AgentConfig  # noqa: E402

# ---------------------------------------------------------------------------
# 抽取：注册名 ∩ AgentConfig 字段（本守卫的靶点集）
# ---------------------------------------------------------------------------
_FIELDS = tuple(sorted(f for f in SWITCHES if f in AgentConfig.__dataclass_fields__))
_ALL_ENV_KEYS = tuple(sorted({m[0] for m in SWITCHES.values()}))

assert _FIELDS, "未抽到任何「注册名 ∩ AgentConfig 字段」（抽取逻辑已失效）"


def _declared_default(field: str):
    """字段的**声明默认值**（dataclass 层面，与任何 env 无关）。"""
    d = AgentConfig.__dataclass_fields__[field]
    if d.default is not dataclasses.MISSING:
        return d.default
    if d.default_factory is not dataclasses.MISSING:
        return d.default_factory()
    return None


def _alt_env_value(field: str, base_val) -> str:
    """给该字段造一个**与默认值不同**的 env 值。"""
    kind, default = SWITCHES[field][1], SWITCHES[field][2]
    if kind == "bool":
        return "0" if default else "1"
    if kind in ("num", "int"):
        # 默认值 ± 1：恒与默认值不同（含 -1 → 0、0 → 1 等边界）。
        return repr(float(default) + 1.0)
    # str
    if isinstance(base_val, (list, tuple)):
        # 形如 lemma_domains：消费方按列表读，env 用逗号分隔。
        return "Algebra,代数"
    return "__probe__" + str(default) + "__"


def _expected_effective(field: str, base_val):
    """注册表的生效值（口径与 `snapshot()` 一致：bool→get_bool、其余数值→get_num、
    字符串→get_str；仅当字段本体是 list/tuple 时把 str 按逗号切分以匹配字段类型）。"""
    kind = SWITCHES[field][1]
    if kind == "bool":
        return get_bool(field)
    if kind in ("num", "int"):
        return get_num(field)
    s = get_str(field)
    if isinstance(base_val, (list, tuple)):
        return [p.strip() for p in s.split(",") if p.strip()]
    return s


@pytest.fixture()
def _clean_env(monkeypatch):
    """清空全部开关 env，保证每个用例互不串味。"""
    for k in _ALL_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


# ===========================================================================
# 1. env 设置时：字段值必须等于注册表生效值（且确实被 env 改变）
# ===========================================================================
@pytest.mark.parametrize("field", _FIELDS)
def test_env_overrides_config_field(field, _clean_env, monkeypatch):
    env_key = SWITCHES[field][0]
    base_val = getattr(AgentConfig(), field)          # env 已清 ⇒ 默认值
    alt = _alt_env_value(field, base_val)
    monkeypatch.setenv(env_key, alt)

    actual = getattr(AgentConfig(), field)
    expected = _expected_effective(field, base_val)

    assert actual == expected, (
        f"开关 `{field}`（env `{env_key}={alt}`）的 config 字段值 {actual!r} "
        f"≠ 注册表生效值 {expected!r} ⇒ env→config 桥未生效")
    assert actual != base_val, (
        f"开关 `{field}`（env `{env_key}={alt}`）设了 env 却没改变字段值"
        f"（仍为默认 {base_val!r}）⇒ env 对该字段静默失效")


# ===========================================================================
# 2. env 不设时：字段值必须等于声明默认值（不破坏「config > 默认值」这半语义）
# ===========================================================================
@pytest.mark.parametrize("field", _FIELDS)
def test_env_unset_equals_default(field, _clean_env):
    actual = getattr(AgentConfig(), field)
    expected = _declared_default(field)
    assert actual == expected, (
        f"开关 `{field}` 在 env 未设置时 config 值 {actual!r} ≠ 声明默认值 "
        f"{expected!r} ⇒ env→config 桥越权改写了未被 env 指定的字段")


# ===========================================================================
# 3. 锚点：三个 team-lead 复现缺陷的开关（防止靶点集被清空后退化成真空通过）
# ===========================================================================
_ANCHORS = ("diversity_resample_enabled", "strict_all_rejected",
            "phase_budget_enabled", "lean_verify")


def test_anchors_present():
    missing = [f for f in _ANCHORS if f not in _FIELDS]
    assert not missing, (
        "锚点开关不在靶点集（疑似改名/删除，守卫会真空通过）：%r" % missing)


@pytest.mark.parametrize("field,env_key,env_val,expect", [
    ("diversity_resample_enabled", "DIVERSITY_RESAMPLE", "0", False),
    ("strict_all_rejected", "STRICT_ALL_REJECTED", "1", True),
    ("phase_budget_enabled", "PHASE_BUDGET_ENABLED", "1", True),
    ("lean_verify", "LEAN_VERIFY", "0", False),
])
def test_team_lead_repro(field, env_key, env_val, expect, _clean_env, monkeypatch):
    """逐条复现 team-lead 的缺陷表：env 必须落到 config 字段（= 生效值）。"""
    monkeypatch.setenv(env_key, env_val)
    actual = getattr(AgentConfig(), field)
    assert actual is expect, (
        f"env `{env_key}={env_val}` ⇒ `{field}` 应为 {expect}，实得 {actual!r}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
