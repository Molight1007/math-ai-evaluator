# -*- coding: utf-8 -*-
"""探针 C：结构指认（Structure Articulation）—— 测元认知。

老师问"它能否观察到更本质的数学结构"。这组分正反两手：

正向（选择题）：解完题后问"你用的核心结构是什么"，与人工标注的 gold 比对。
   —— 这是最直觉的测法，但模型可以靠"背名词"蒙对，所以不够。

反向（造最小 Lean 示例）：**给结构名，要求写出体现该结构的最小可编译 Lean 代码**。
   —— 这是硬判据：能命名 ≠ 能构造。要写出 `induction` 才算真懂归纳法，
      要能写出 `sq_nonneg` 才算真懂平方和非负。编译不通过就是不懂。

反向任务是本实验相对"选择题自评"类工作的主要区别点。
"""
from __future__ import annotations

import re

from bank.problems import REVERSE_TASKS, STRUCT_ITEMS, STRUCTURE_OPTIONS
from llm.client import LLMClient
from probes.base import run_once
from record import Record

CHOICE_TAIL = (
    "\n\n请完成上述任务，然后从下列结构中选出**最核心**的一项：\n"
    + "\n".join(f"{i+1}. {o}" for i, o in enumerate(STRUCTURE_OPTIONS))
    + "\n\n最后一行严格用『结构：编号. 名称』给出你的选择。"
)

REVERSE_TAIL = "\n\n只输出 Lean 4 代码，用 ```lean 围栏包裹，不要额外解释。"


def _pick(region: str) -> tuple[str, int]:
    """从结论区解析模型选了哪个结构。返回 (选择, 是否歧义)。"""
    m = re.search(r"结构\s*[:：]\s*(\d+)", region)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(STRUCTURE_OPTIONS):
            return STRUCTURE_OPTIONS[idx], 0
    hits = [o for o in STRUCTURE_OPTIONS if o in region]
    if len(hits) == 1:
        return hits[0], 0
    if len(hits) > 1:
        return hits[0], 1
    return "未识别", 0


def run(
    client: LLMClient,
    repeat: int = 0,
    ids: list[str] | None = None,
    use_lean: bool = True,
) -> list[Record]:
    """跑 C 组：正向指认 + 反向构造。"""
    out: list[Record] = []

    # ---- 正向：结构指认 ----
    for item in STRUCT_ITEMS:
        if ids and item.sid not in ids:
            continue
        rec = run_once(
            client, "C", item.sid, "articulate",
            item.statement + CHOICE_TAIL, repeat, use_lean=False,
        )
        region = rec.raw[-1000:] if rec.raw else ""
        pick, ambiguous = _pick(region)
        rec.metrics = {
            "task": "articulate",
            "gold": item.gold_option,
            "pick": pick,
            "correct": int(pick == item.gold_option),
            "ambiguous": ambiguous,
            "note": item.note,
        }
        out.append(rec)

    # ---- 反向：给结构名，造最小 Lean 示例 ----
    for task in REVERSE_TASKS:
        if ids and task.rid not in ids:
            continue
        rec = run_once(
            client, "C", task.rid, "reverse_lean",
            task.lean_task + REVERSE_TAIL, repeat, use_lean,
        )
        fp = set(rec.fingerprint)
        want = set(task.expected_family)
        rec.metrics = {
            "task": "reverse_lean",
            "structure": task.structure,
            "expected_family": task.expected_family,
            "family_hit": int(bool(fp & want)),
            "family_hit_count": len(fp & want),
            "lean_ok": int(rec.lean_ok),
        }
        out.append(rec)

    return out
