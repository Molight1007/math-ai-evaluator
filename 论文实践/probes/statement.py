# -*- coding: utf-8 -*-
"""探针 E：定理陈述完整性（Statement Completeness）。

测"严格理解"最硬的一层：**陈述**。

- B / D 测的是**判断**：给一个被改坏的定理，模型能否识破 + 构造反例（被动）
- E 测的是**陈述**：让模型**自己**完整精确地说出定理的全部条件（主动）

**能判断 ≠ 能精确陈述。** 例如拉格朗日中值定理，识破"去掉可导条件"是一回事，
自己写出"闭区间连续 **且** 开区间可导"是另一回事。

混合判据（闭包只有 Mathlib.Tactic，纯形式化覆盖面不够）：
  ① 文本条件完整率 —— 按 `key_conditions` 关键条件清单逐项正则匹配
  ② Lean 特例编译率 —— 让模型写该定理在**一个具体特例**下的形式化命题并证明

详见 `探针E_陈述层_设计方案.md`。
"""
from __future__ import annotations

import re

from bank.problems import E_ITEMS
from llm.client import LLMClient
from probes.base import run_once
from record import Record
from util import normalize_math

LEAN_TAIL = (
    "\n\n最后，请用 Lean 4 写出该定理在**一个具体特例**下的形式化命题并证明它："
    "用 ```lean 围栏包裹，代码以 example 开头，并 import Mathlib.Tactic。"
)


def _score(raw: str, item) -> list[int]:
    """逐项匹配关键条件清单，返回 0/1 命中向量。

    **必须先看 `util.normalize_math()` 的注释**：模型写范数可能是 `‖u‖` /
    `||u||` / `|u|`，写内积可能是 `⟨u,v⟩` / `<u,v>` / `\\langle u,v\\rangle`。
    不归一化就匹配，会让**所有模型被系统性误判为漏条件**——且不报错，
    只是静默地得出错误的论文结论。
    """
    text = normalize_math(raw)
    hits: list[int] = []
    for pats in item.condition_patterns:
        hit = any(re.search(p, text, re.IGNORECASE) for p in pats)
        hits.append(int(hit))
    return hits


def run(
    client: LLMClient,
    repeat: int = 0,
    ids: list[str] | None = None,
    use_lean: bool = True,
) -> list[Record]:
    """跑 E 组：让模型完整陈述定理条件 + 写特例 Lean 命题。"""
    out: list[Record] = []
    for item in E_ITEMS:
        if ids and item.eid not in ids:
            continue

        has_lean = bool(item.gold_lean.strip())
        prompt = item.statement + (LEAN_TAIL if has_lean else "")
        rec = run_once(
            client, "E", item.eid, item.dimension, prompt, repeat,
            use_lean and has_lean,
        )

        hits = _score(rec.raw, item)
        n = len(item.key_conditions) or 1
        completeness = round(sum(hits) / n, 3)
        full = int(bool(hits) and all(hits))
        lean_ok = int(rec.lean_ok)

        # 无 Lean 判据的题（如涉及极限的一致收敛）只按文本完整性判定
        both = int(full and lean_ok) if has_lean else int(full)

        missing = [c for c, h in zip(item.key_conditions, hits) if not h]

        rec.metrics = {
            "theorem": item.theorem,
            "dimension": item.dimension,
            "key_conditions": item.key_conditions,
            "cond_hits": hits,
            "condition_completeness": completeness,
            "full_conditions": full,
            "missing_conditions": missing,
            "has_lean": int(has_lean),
            "lean_ok": lean_ok,
            "both_pass": both,
            "note": item.note,
        }
        out.append(rec)
    return out
