# -*- coding: utf-8 -*-
"""探针 B：陷阱题（Trap）—— 测类比**是否用错了地方**。

A 组测"能不能联想"，B 组测更锋利的一面：模型会被表层相似骗到吗？
每题的构造原则：**表层极像模板 X，实则需要结构 Y**。

三层判据（互相印证，避免单靠正则误判）：
  1. 文本标记：结论区命中"套路化错误结果" → trapped；命中正确结论 → escaped
  2. Lean 客观验证：模型给出的形式化验证能否编译通过
  3. 人工可复核：raw 原文全量落盘，报告里可直接翻

诚实说明：文本标记法会有 mixed / other 两类，报告中单列，不做强行归类。
"""
from __future__ import annotations

from bank.problems import TRAP_ITEMS
from llm.client import LLMClient
from probes.base import VERIFY_SUFFIX, run_once
from record import Record
from util import hits_any

# 只看结论区（模型可能在推理中提到又否定了某个错误答案）
CONCLUSION_CHARS = 1200


def _label(region: str, trap_markers: list[str], gold_markers: list[str]) -> tuple[str, list[str], list[str]]:
    trap_hits = hits_any(region, trap_markers)
    gold_hits = hits_any(region, gold_markers)
    if gold_hits and not trap_hits:
        return "escaped", trap_hits, gold_hits
    if trap_hits and not gold_hits:
        return "trapped", trap_hits, gold_hits
    if trap_hits and gold_hits:
        return "mixed", trap_hits, gold_hits
    return "other", trap_hits, gold_hits


def run(
    client: LLMClient,
    repeat: int = 0,
    ids: list[str] | None = None,
    use_lean: bool = True,
) -> list[Record]:
    """跑 B 组全部陷阱题。"""
    out: list[Record] = []
    for item in TRAP_ITEMS:
        if ids and item.tid not in ids:
            continue
        # 组合 / 分析类陷阱题（极限、最坏情况计数）在闭包内难以低成本形式化，
        # 这类题 gold_lean 为空 → 不要求模型交 Lean 代码，也不做 Lean 判定，
        # 只由文本标记 + 人工复核判分（见 bank/problems.py 文件头说明）。
        has_lean = bool(item.gold_lean.strip())
        prompt = item.statement + (VERIFY_SUFFIX if has_lean else "")
        rec = run_once(
            client, "B", item.tid, "trap", prompt, repeat,
            use_lean and has_lean,
        )
        region = rec.raw[-CONCLUSION_CHARS:] if rec.raw else ""
        label, trap_hits, gold_hits = _label(
            region, item.trap_markers, item.gold_markers
        )
        rec.metrics = {
            "label": label,
            "escaped": int(label == "escaped"),
            "trapped": int(label == "trapped"),
            "gold_answer": item.gold_answer,
            "gold_structure": item.gold_structure,
            "trap_hits": trap_hits,
            "gold_hits": gold_hits,
            "has_lean": int(has_lean),
            "lean_ok": int(rec.lean_ok),
        }
        out.append(rec)
    return out
