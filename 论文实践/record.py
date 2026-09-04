# -*- coding: utf-8 -*-
"""统一的实验记录结构。所有探针都产出 Record，交给 analysis 汇总。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Record:
    probe: str                  # A / B / C / D
    item_id: str                # 题号
    variant: str = ""           # 条件：source / target_with_source / target_baseline ...
    model: str = ""
    repeat: int = 0
    prompt: str = ""
    raw: str = ""               # 模型原始输出（完整，供人工复核）
    reasoning: str = ""         # 推理模型的思维链
    answer: str = ""            # 抽取的结论行
    lean_code: str = ""
    lean_ok: bool = False
    lean_compiled: bool = False
    lean_sorry: bool = False
    lean_error: str = ""
    fingerprint: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    truncated: bool = False
    error: str = ""
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        return {
            "probe": self.probe,
            "item_id": self.item_id,
            "variant": self.variant,
            "model": self.model,
            "repeat": self.repeat,
            "raw": self.raw,
            "reasoning": self.reasoning,
            "answer": self.answer,
            "lean_code": self.lean_code,
            "lean_ok": self.lean_ok,
            "lean_compiled": self.lean_compiled,
            "lean_sorry": self.lean_sorry,
            "lean_error": self.lean_error,
            "fingerprint": self.fingerprint,
            "metrics": self.metrics,
            "truncated": self.truncated,
            "error": self.error,
            "elapsed": round(self.elapsed, 2),
        }

    def to_row(self) -> dict:
        """扁平化成 CSV 一行（metrics 展开，raw/lean_code 截断）。"""
        row = {
            "probe": self.probe,
            "item_id": self.item_id,
            "variant": self.variant,
            "model": self.model,
            "repeat": self.repeat,
            "lean_ok": int(self.lean_ok),
            "lean_compiled": int(self.lean_compiled),
            "lean_sorry": int(self.lean_sorry),
            "truncated": int(self.truncated),
            "error": self.error,
            "elapsed": round(self.elapsed, 2),
            "fingerprint": "|".join(sorted(self.fingerprint)),
            "answer": (self.answer or "")[:120],
            "lean_error": (self.lean_error or "")[:160],
        }
        for k, v in self.metrics.items():
            if isinstance(v, (str, int, float, bool)):
                row[f"m_{k}"] = v
            else:
                row[f"m_{k}"] = json.dumps(v, ensure_ascii=False)
        return row
