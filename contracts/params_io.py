# -*- coding: utf-8 -*-
"""L0 参数层读取器 —— 把 `params.json` 的 A 段变成可注入的配置覆盖（零依赖）。

在三体架构里的位置
==================
    L0 参数层（params.json，由 tools/params_export.py 生成）
      │  A 段 = 机器可改的标量值（白名单已验证）
      ▼
    L1 主智能体（本模块把 A 段并入 `DEFAULT_AGENT_OVERRIDES` → `ReasoningAgent(**overrides)`）

为什么单独放在 `contracts/`
==========================
`contracts/` 是分层里的最低层（`contracts ← utils ← tools ← agent ← 根`），
只有 stdlib 依赖 ⇒ `run_eval` / 未来的提案器 / 判定层都能读，不会反向依赖。

优先级（与「四件套」口径一致）
============================
    环境变量  >  CLI/实验臂（显式覆盖）  >  **params.json（本层）**  >  dataclass 默认值
「显式覆盖」指 `_collect_arg_overrides` / `MP_ARM` 产出的键 —— 人临时指定的一律优先，
否则「改了参数没生效」会再次发生（历史踩坑最多的一类）。

本模块**不 fallback**：文件缺失/格式错一律抛 `ParamsError`，由调用方决定
是「警告并跳过」还是「直接拒绝」。参数层静默失效比崩溃更难查。
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = "params/1"


class ParamsError(Exception):
    """params.json 结构非法（schema/字段类型不符）。"""


def fingerprint(doc: dict) -> str:
    """A 段的稳定指纹（12 位 sha1）：同一批候选值 → 同一指纹，可写进结果元数据。"""
    seg = json.dumps(doc.get("a") or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(seg.encode("utf-8")).hexdigest()[:12]


def validate(doc: dict) -> dict:
    """结构校验（只查格式，不查键是否真实存在 —— 那是 tools/params_export.py check 的事）。"""
    if not isinstance(doc, dict):
        raise ParamsError("params.json 顶层不是对象")
    if doc.get("schema") != SCHEMA:
        raise ParamsError("schema 应为 %r，实际 %r" % (SCHEMA, doc.get("schema")))
    a = doc.get("a")
    if not isinstance(a, dict):
        raise ParamsError("缺少 a 段（或不是对象）：A 档是候选空间，不能为空")
    for key, ent in a.items():
        if not isinstance(ent, dict):
            raise ParamsError("a.%s 不是对象" % key)
        if ent.get("tier") != "A":
            raise ParamsError("a.%s 的 tier 不是 A（%r）" % (key, ent.get("tier")))
        if "value" not in ent:
            raise ParamsError("a.%s 缺 value" % key)
        if isinstance(ent["value"], (dict, list, tuple, set)):
            raise ParamsError("a.%s 的值是非标量（%s）—— A 档只允许标量"
                              % (key, type(ent["value"]).__name__))
    return doc


def load(path: str) -> dict:
    """读并校验；任何异常包成 ParamsError（调用方只需 catch 一种）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError as e:
        raise ParamsError("读不到 %s：%s" % (path, e)) from e
    except ValueError as e:
        raise ParamsError("%s 不是合法 JSON：%s" % (path, e)) from e
    return validate(doc)


def a_values(doc: dict) -> dict:
    """A 段取值：{config_key: value}（供 overrides 使用）。"""
    return {k: v["value"] for k, v in (doc.get("a") or {}).items()}


def a_keys(doc: dict) -> list:
    return sorted(doc.get("a") or {})


def summary(doc: dict) -> dict:
    """写进结果元数据的紧凑摘要（不含全部取值，避免刷屏）。"""
    counts = doc.get("counts") or {}
    return {
        "schema": SCHEMA,
        "sha": fingerprint(doc),
        "n_a": len(doc.get("a") or {}),
        "counts": counts,
    }
