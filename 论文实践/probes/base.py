# -*- coding: utf-8 -*-
"""探针共用逻辑：一次"提问 → 抽代码 → Lean 判定 → 抽指纹"。"""
from __future__ import annotations

import time

from judge import fingerprint as fpmod
from judge import lean as lean_judge
from llm.client import LLMClient
from record import Record
from util import extract_answer, extract_lean

SYSTEM = (
    "你是一位严谨的数学家，同时精通 Lean 4 形式化证明。"
    "请严格按用户要求的格式作答，关键推理步骤不要省略。"
)

VERIFY_SUFFIX = (
    "\n\n最后，请给出一段**完整可编译**的 Lean 4 代码来形式化验证你的结论："
    "用 ```lean 围栏包裹，代码以 example 开头，并 import Mathlib.Tactic。"
)


def run_once(
    client: LLMClient,
    probe: str,
    item_id: str,
    variant: str,
    prompt: str,
    repeat: int = 0,
    use_lean: bool = True,
    system: str = SYSTEM,
) -> Record:
    """跑一次提问，返回带 Lean 判定与指纹的 Record。"""
    t0 = time.time()
    rep = client.ask(prompt, system=system)
    rec = Record(
        probe=probe,
        item_id=item_id,
        variant=variant,
        model=client.model_key,
        repeat=repeat,
        prompt=prompt,
        raw=rep.content,
        reasoning=rep.reasoning,
        truncated=rep.truncated,
        error=rep.error,
    )
    rec.answer = extract_answer(rep.content)

    if use_lean and not rep.error:
        code = extract_lean(rep.content)
        rec.lean_code = code
        if code:
            res = lean_judge.check(code, tag=f"{probe}_{item_id}_{variant}")
            rec.lean_ok = res.ok
            rec.lean_compiled = res.compiled
            rec.lean_sorry = res.sorry
            rec.lean_error = "; ".join(res.errors[:3]) or res.note
        else:
            rec.lean_error = "未抽取到 Lean 代码"
        rec.fingerprint = sorted(fpmod.fingerprint(code))

    rec.elapsed = round(time.time() - t0, 2)
    return rec
