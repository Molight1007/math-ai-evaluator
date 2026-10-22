# -*- coding: utf-8 -*-
"""Lean 编译失败原因分类（纯函数，无依赖）—— 2026-10-22。

为什么需要它
============
4.3 的判定链只有一个结论 ``proof_invalid``（淘汰）与 ``unknown``（放行），
而 Lean 编译失败的**四种语义**被压成前一种：

| 语义 | 典型输出 | 与「答案错」的关系 |
|---|---|---|
| ``refuted`` | ``⊢ False`` / decide 判假 | **有关**：命题确实为假 |
| ``unproved`` | ``unsolved goals ⊢ n = 2`` / ``linarith failed`` | **无关**：命题可能为真，只是证明没写出来 |
| ``translation`` | ``unknown identifier`` / ``unexpected token`` | **无关**：LLM 翻译出的代码不合法 |
| ``env`` | ``unknown module prefix 'Batteries'`` / olean 不存在 | **无关**：本机/云端环境缺依赖 |

历史实测（10-07 记录）：73 条 ``proof_invalid`` 里 51 条 ``compiled == true``，
属「形式化不充分」却被当成「命题为假」⇒ 正确候选被淘汰。本模块把「没证出来」
从「证出是假」里剥出来，让淘汰只在 ``refuted`` 时发生。

分层：本模块只用标准库，可被 ``tools/`` 与 ``agent/`` 共用；
不反向依赖 ``agent``。
"""
from __future__ import annotations

import re

# 结论码（稳定契约：写入 diag.lean_gate[i].failure_kind，报表按它聚合）
REFUTED = "refuted"          # 命题为假（唯一可淘汰的语义）
UNPROVED = "unproved"        # 代码合法但未证出
TRANSLATION = "translation"  # 生成/翻译出的代码不合法
ENV = "env"                  # 环境缺依赖/找不到文件
UNKNOWN = "unknown"          # 判不出（保守：不淘汰）

ALL_KINDS = (REFUTED, UNPROVED, TRANSLATION, ENV, UNKNOWN)

# 逐条判据按「强度」排序：先认最强的 refuted，最后兜底 unknown。
# 每条线索都取自 Lean 的实际报错原文（本机 Lean 4.31.0 实测 + 历史日志）。
_REFUTED_PATTERNS = (
    re.compile(r"⊢\s*false\b"),
    re.compile(r"\|\-\s*false\b"),
    re.compile(r"decide\s+proved\s+the\s+proposition\s+is\s+false"),
    re.compile(r"the\s+proposition\s+is\s+false"),
)

_ENV_PATTERNS = (
    re.compile(r"unknown\s+module\s+prefix"),
    re.compile(r"object\s+file\b.*\bdoes\s+not\s+exist"),
    re.compile(r"bad\s+import"),
    re.compile(r"lean\s+executable\s+not\s+found"),
    re.compile(r"could\s+not\s+resolve\s+import"),
    re.compile(r"no\s+such\s+file\s+or\s+directory"),
)

_TRANSLATION_PATTERNS = (
    re.compile(r"unknown\s+identifier"),
    re.compile(r"unknown\s+constant"),
    re.compile(r"unknown\s+tactic"),
    re.compile(r"unexpected\s+token"),
    re.compile(r"unexpected\s+identifier"),
    re.compile(r"invalid\s+syntax"),
    re.compile(r"unsupported\s+syntax"),
    re.compile(r"invalid\s+field\s+notation"),
    re.compile(r"function\s+expected"),
)

_UNPROVED_PATTERNS = (
    re.compile(r"unsolved\s+goals"),
    re.compile(r"\bfailed\b"),          # linarith/norm_num/rewrite/omega failed
    re.compile(r"^\s*made\s+no\s+progress", re.M),
    re.compile(r"type\s+mismatch"),     # example 里目标类型写错也归此类
)


def classify_compile_error(text) -> str:
    """把 Lean 的报错文本归类为 :data:`ALL_KINDS` 之一。

    判定顺序（强 → 弱）：refuted → env → translation → unproved → unknown。
    「refuted 优先」是刻意的：只要报错里出现 ``⊢ False``，无论同时还夹带
    什么其它信息，都说明 Lean 已经把命题本身证伪了，这是最强结论。

    空输入 / 无任何特征 ⇒ ``unknown``（调用方按「不淘汰」处理）。
    """
    t = str(text or "").lower()
    if not t.strip():
        return UNKNOWN
    for pat in _REFUTED_PATTERNS:
        if pat.search(t):
            return REFUTED
    for pat in _ENV_PATTERNS:
        if pat.search(t):
            return ENV
    for pat in _TRANSLATION_PATTERNS:
        if pat.search(t):
            return TRANSLATION
    for pat in _UNPROVED_PATTERNS:
        if pat.search(t):
            return UNPROVED
    return UNKNOWN


def evidences_refutation(kind: str) -> bool:
    """该结论码是否足以支撑「答案错」的淘汰（只有 refuted 可以）。"""
    return str(kind or "") == REFUTED
