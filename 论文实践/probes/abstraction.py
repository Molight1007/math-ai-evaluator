# -*- coding: utf-8 -*-
"""探针 D：抽象 ⇄ 实例化（Abstraction）—— 测抽象层级。

两个方向：
  c2g（具体→一般）：给若干具体实例，要求抽象出一般公式（如立方和、勾股数参数化）
  g2c（一般→具体）：给一条定理，要求判断去掉/改变某个条件后是否仍成立，并构造反例

客观判据亮点：D3（勾股数参数化）是四类探针里判据最强的一题 ——
模型给出的参数化若正确，`ring` 一步就能验证恒等式 (m²-n²)²+(2mn)²=(m²+n²)²；
若给错，Lean 立刻编译失败。**不需要人去读它的推导。**
"""
from __future__ import annotations

import re

from bank.problems import ABS_ITEMS
from llm.client import LLMClient
from probes.base import VERIFY_SUFFIX, run_once
from record import Record


def run(
    client: LLMClient,
    repeat: int = 0,
    ids: list[str] | None = None,
    use_lean: bool = True,
) -> list[Record]:
    """跑 D 组：抽象与实例化。"""
    out: list[Record] = []
    for item in ABS_ITEMS:
        if ids and item.aid not in ids:
            continue
        prompt = (
            item.statement
            + "\n\n请给出你的结论，并说明理由。"
            + VERIFY_SUFFIX
        )
        rec = run_once(
            client, "D", item.aid, item.direction, prompt, repeat, use_lean
        )
        # 公式可能出现在推理任何位置，故全文匹配
        matched = [
            p for p in item.answer_patterns
            if re.search(p, rec.raw or "", re.IGNORECASE)
        ]
        rec.metrics = {
            "direction": item.direction,
            "gold": item.gold_answer,
            "pattern_hit": int(bool(matched)),
            "n_matched": len(matched),
            "n_patterns": len(item.answer_patterns),
            "lean_ok": int(rec.lean_ok),
            "note": item.note,
        }
        out.append(rec)
    return out
