# -*- coding: utf-8 -*-
"""L0 参数层（params.json）守卫测试（2026-10-27）。

本文件防的是什么错
==================
三体架构把「参数层」定为地基：候选 = `params.json` 的 diff。地基错一处，
上面三层（提案 / 判定 / 账本）全部记在错的东西上。本文件钉住四条不变式：

  1. **A 档必须是真能改的**：标量、已声明、在覆盖白名单内、有真实读取点。
     缺任何一条都会变成「改了不生效」——比没有参数层更糟（有假象）。
  2. **参数层必须行为等价**：`AgentConfig(**DEFAULT)` 与
     `AgentConfig(**DEFAULT, **params.a)` 的**全部字段逐一相等**。
     不等就说明 params.json 与当前代码/评测基线漂移，候选是在错基线上评的。
  3. **AST 抽取 == 运行时真值**：`tools/params_export.py` 不 import
     `AgentConfig`（分层纪律），若 AST 解析写错，整份 params.json 都是错的
     ⇒ 必须与 dataclass 真值逐字段比对。
  4. **注入链端到端通**：env `MP_PARAMS_JSON` → 注册表 → EvalEngine →
     `agent.config`。项目曾出现「四处登记齐全但没人调 bind_config」的静默失效，
     故这里用 `__new__` 跳过重依赖，只验注入与回读。
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import dataclasses  # noqa: E402

from contracts.params_io import (  # noqa: E402
    ParamsError, a_values, fingerprint, load as load_params, validate,
)
from user_agent__config import AgentConfig  # noqa: E402
from user_agent import _CONFIG_OVERRIDE_KEYS  # noqa: E402
from run_eval__engine import DEFAULT_AGENT_OVERRIDES, EvalEngine  # noqa: E402
import tools.params_export as pe  # noqa: E402

PARAMS = os.path.join(REPO, "params.json")


@pytest.fixture(scope="module")
def doc():
    assert os.path.isfile(PARAMS), "params.json 不存在，先跑 tools/params_export.py build"
    return load_params(PARAMS)


# ---------------------------------------------------------------- 1. 分档不变式
def test_01_schema_and_counts(doc):
    assert doc["schema"] == pe.SCHEMA
    c = doc["counts"]
    assert c["A"] == len(doc["a"]) and c["B"] == len(doc["b"]) and c["C"] == len(doc["c"])
    assert c["A"] > 0, "A 档为空 ⇒ 机器可改空间为零，候选无处落地"


def test_02_a_keys_are_really_editable(doc):
    """A 档四条件：标量 + 已声明 + 在白名单 + 有读取点。"""
    cfg = pe.scan_config()
    wl = pe.scan_whitelist()
    usage = pe.build_usage_index(set(doc["a"]))
    bad = []
    for name, ent in doc["a"].items():
        if name not in cfg:
            bad.append((name, "不在 AgentConfig 声明里"))
        elif not cfg[name]["scalar"]:
            bad.append((name, "类型 %s 非标量" % cfg[name]["type"]))
        elif name not in wl:
            bad.append((name, "不在 _CONFIG_OVERRIDE_KEYS"))
        elif not [p for p in usage.get(name, [])
                  if not p.endswith(cfg[name]["source"].split("::")[0])]:
            bad.append((name, "0 读取点（死配置）"))
        elif isinstance(ent.get("value"), (dict, list, tuple)):
            bad.append((name, "value 非标量"))
    assert not bad, "以下 A 档条目不满足「真能改」：\n" + "\n".join(
        "    - %s: %s" % (n, r) for n, r in bad)


def test_03_b_c_tiers_are_not_a(doc):
    a_keys = set(doc["a"])
    overlap = a_keys & (set(doc["b"]) | set(doc["c"]))
    assert not overlap, "同一单元同时出现在 A 段与 B/C 段：%s" % sorted(overlap)[:5]
    for k, v in doc["c"].items():
        assert v["tier"] == "C", "%s 在 C 段但 tier=%r" % (k, v["tier"])


# ---------------------------------------------------------------- 2. 行为等价
def test_10_params_layer_is_behaviour_neutral(doc):
    """核心判据：叠加参数层前后，AgentConfig 全部字段逐一相等。"""
    vals = {k: v for k, v in a_values(doc).items() if k in _CONFIG_OVERRIDE_KEYS}
    before = AgentConfig(**dict(DEFAULT_AGENT_OVERRIDES))
    after = AgentConfig(**dict(DEFAULT_AGENT_OVERRIDES, **vals))
    diffs = [(f.name, getattr(before, f.name), getattr(after, f.name))
             for f in dataclasses.fields(before)
             if getattr(before, f.name) != getattr(after, f.name)]
    assert not diffs, (
        "参数层与当前基线漂移（候选会在错基线上评测），%d 处：\n%s"
        % (len(diffs), "\n".join("    - %s: %r → %r" % d for d in diffs[:10])))


def test_11_strict_check_passes(doc):
    probs = pe.check(doc, strict=True)
    assert not probs, "tools/params_export.py check --strict 不通过：\n" + \
        "\n".join("    - " + p for p in probs)


# ---------------------------------------------------------------- 3. AST == 真值
def test_20_ast_defaults_match_dataclass():
    cfg = pe.scan_config()
    bad = []
    for f in dataclasses.fields(AgentConfig):
        if f.name not in cfg:
            bad.append((f.name, "AST 未扫到"))
            continue
        if f.default is not dataclasses.MISSING:
            want = f.default
        elif f.default_factory is not dataclasses.MISSING:
            want = f.default_factory()
        else:  # pragma: no cover
            continue
        got = cfg[f.name]["default"]
        if got != want:
            bad.append((f.name, "AST=%r 真值=%r" % (got, want)))
    assert not bad, "AST 抽取与 dataclass 真值不一致：\n" + "\n".join(
        "    - %s: %s" % b for b in bad[:10])


def test_21_switch_defaults_match_config():
    """注册表默认值 == 配置声明默认值（list 字段按逗号切分，与四件套守卫同口径）。"""
    sw = pe.scan_switches()
    cfg = pe.scan_config()
    bad = []
    for n, m in sw.items():
        if n not in cfg:
            continue
        want = cfg[n]["default"]
        got = m["default"]
        if isinstance(want, (list, tuple)) and isinstance(got, str):
            got = [p.strip() for p in got.split(",") if p.strip()]
        if got != want:
            bad.append((n, m["default"], want))
    assert not bad, "注册表默认值与配置声明漂移：%s" % bad[:5]


# ---------------------------------------------------------------- 4. 注入链
def test_30_export_is_deterministic():
    a = json.dumps(pe.build(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(pe.build(), ensure_ascii=False, sort_keys=True)
    assert a == b, "同一份代码两次导出不一致 ⇒ params.json 的 diff 不可信"


def test_40_injection_reaches_config(monkeypatch, doc, tmp_path):
    """env → 注册表 → EvalEngine → agent.config，端到端一次。"""
    p = tmp_path / "params.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("MP_PARAMS_JSON", str(p))

    eng = EvalEngine.__new__(EvalEngine)          # 跳过 LLMClient 等重依赖
    overrides = dict(DEFAULT_AGENT_OVERRIDES)
    eng._apply_params_layer(overrides, {})
    assert eng._params_layer["enabled"] is True
    assert eng._params_layer["n_a"] == len(doc["a"])
    assert eng._params_layer["sha"] == fingerprint(doc)

    eng._effective_overrides = overrides
    eng.agent = SimpleNamespace(config=AgentConfig(**overrides))
    eng._verify_params_layer()                     # 不一致会抛
    assert eng._params_layer["dropped"] == []


def test_41_cli_overrides_win_over_params(monkeypatch, tmp_path):
    """显式 CLI 值必须压过参数层，且被记为 shadowed（不能静默）。"""
    small = {"schema": pe.SCHEMA, "a": {
        "policy_sample_times": {"tier": "A", "value": 5, "status": "ok"}},
        "b": {}, "c": {}, "counts": {"A": 1, "B": 0, "C": 0}}
    p = tmp_path / "p.json"
    p.write_text(json.dumps(small), encoding="utf-8")
    monkeypatch.setenv("MP_PARAMS_JSON", str(p))

    eng = EvalEngine.__new__(EvalEngine)
    overrides = dict(DEFAULT_AGENT_OVERRIDES)
    eng._apply_params_layer(overrides, {"policy_sample_times": 2})
    assert eng._params_layer["shadowed"] == ["policy_sample_times"]
    overrides.update({"policy_sample_times": 2})
    assert overrides["policy_sample_times"] == 2, "CLI 值被参数层覆盖了"


def test_42_unknown_key_fails_loudly(monkeypatch, tmp_path):
    """模型发明的新参数必须硬失败（否则注入后被静默丢弃 = 假 A/B）。"""
    bad = {"schema": pe.SCHEMA, "a": {
        "make_up_a_param": {"tier": "A", "value": 1, "status": "ok"}},
        "b": {}, "c": {}, "counts": {"A": 1, "B": 0, "C": 0}}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setenv("MP_PARAMS_JSON", str(p))
    eng = EvalEngine.__new__(EvalEngine)
    with pytest.raises(RuntimeError, match="不可注入"):
        eng._apply_params_layer(dict(DEFAULT_AGENT_OVERRIDES), {})


def test_50_params_io_rejects_bad_docs():
    with pytest.raises(ParamsError):
        validate({"schema": "params/0", "a": {}})
    with pytest.raises(ParamsError):
        validate({"schema": pe.SCHEMA, "a": {"x": {"tier": "A", "value": [1, 2]}}})
    with pytest.raises(ParamsError):
        validate({"schema": pe.SCHEMA, "a": {"x": {"tier": "B", "value": 1}}})
