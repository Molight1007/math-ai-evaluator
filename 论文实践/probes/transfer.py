# -*- coding: utf-8 -*-
"""探针 A：同构迁移（Isomorphic Transfer）—— 直接测"联想"能不能发生。

实验范式（每题组跑 3 次提问）：
  1. source            ：先让模型解源题
  2. target_with_source：把模型的源题解答作为上下文，再让它解结构同构的目标题
  3. target_baseline   ：不给源题，直接解目标题（对照条件）

核心指标：
  - 迁移增益   = 条件2正确率 - 条件3正确率（>0 说明"做过一遍确实有用"）
  - 核心迁移率 = 目标题指纹 ∩ 共享结构核心 / 共享结构核心
                 （**直接量化"它有没有把方法搬过去"**，这是本实验最原创的量）
  - 方法继承率 = 目标题指纹 ∩ 源题指纹 / 源题指纹
"""
from __future__ import annotations

from bank.problems import TRANSFER_PAIRS
from judge import fingerprint as fpmod
from llm.client import LLMClient
from probes.base import run_once
from record import Record

# 给模型的上下文长度上限（避免超长 prompt）
SRC_SNIPPET = 3000


def _context_prompt(pair, src_raw: str) -> str:
    return (
        "你刚刚解决了下面这道题：\n\n"
        f"【原题】\n{pair.source_statement}\n\n"
        f"【你给出的解答】\n{(src_raw or '（无）')[:SRC_SNIPPET]}\n\n"
        "现在请解决下面这道**新题**。提示：新题与原题在数学结构上可能相关，"
        "你可以借鉴刚才用到的方法，但必须独立给出适用于新题的完整推理，"
        "以及能编译通过的 Lean 4 代码。\n\n"
        f"【新题】\n{pair.target_statement}"
    )


def run(
    client: LLMClient,
    repeat: int = 0,
    pids: list[str] | None = None,
    use_lean: bool = True,
) -> list[Record]:
    """跑 A 组全部题对。"""
    out: list[Record] = []
    for pair in TRANSFER_PAIRS:
        if pids and pair.pid not in pids:
            continue

        base_meta = {"kind": pair.kind, "core": pair.core}

        # 1) 源题
        src = run_once(
            client, "A", pair.pid, "source", pair.source_statement,
            repeat, use_lean,
        )
        src.metrics = {**base_meta, "role": "source"}
        out.append(src)

        src_fp = set(src.fingerprint)

        # 2) 目标题（带源题上下文）
        tw = run_once(
            client, "A", pair.pid, "target_with_source",
            _context_prompt(pair, src.raw), repeat, use_lean,
        )
        tw_fp = set(tw.fingerprint)
        tw.metrics = {
            **base_meta,
            "role": "target_with_source",
            "src_lean_ok": int(src.lean_ok),
            **fpmod.transfer_scores(src_fp, tw_fp, pair.core_family),
        }
        out.append(tw)

        # 3) 目标题（无源题，基线）
        tb = run_once(
            client, "A", pair.pid, "target_baseline",
            pair.target_statement, repeat, use_lean,
        )
        tb_fp = set(tb.fingerprint)
        tb.metrics = {
            **base_meta,
            "role": "target_baseline",
            **fpmod.transfer_scores(src_fp, tb_fp, pair.core_family),
        }
        out.append(tb)

    return out
