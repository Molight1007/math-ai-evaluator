# -*- coding: utf-8 -*-
"""通用小工具：从模型输出里抽取代码 / 答案。零依赖。"""
from __future__ import annotations

import re

_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.DOTALL)


def strip_fences(text: str) -> str:
    """去掉 Markdown 代码围栏，返回内部内容（无围栏则原样返回）。"""
    if not text:
        return ""
    blocks = _FENCE_RE.findall(text)
    if blocks:
        # 取最长的代码块：模型常先写一小段示例，再给正式代码
        return max(blocks, key=len).strip()
    return text.strip()


def extract_lean(text: str) -> str:
    """从模型输出中抽取 Lean 4 代码。

    优先 ```lean 围栏 → 任意围栏 → 裸代码（以 import/example/theorem 开头的一段）。
    """
    if not text:
        return ""
    m = re.search(r"```lean\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    blocks = _FENCE_RE.findall(text)
    if blocks:
        cand = max(blocks, key=len).strip()
        if _looks_like_lean(cand):
            return cand
    return _raw_code(text)


def _looks_like_lean(code: str) -> bool:
    return bool(
        re.search(r"^\s*(import|example|theorem|lemma|def|open)\b", code, re.M)
    )


def _raw_code(text: str) -> str:
    """无围栏时，从第一个 import/example/theorem 起截到文本末尾。"""
    m = re.search(r"^\s*(import\s+Mathlib|example|theorem|lemma)\b.*$",
                  text, re.M)
    if not m:
        return ""
    return text[m.start():].strip()


def extract_answer(text: str) -> str:
    """抽取"最终答案"：优先最后一行结论，退而取全文尾段。"""
    if not text:
        return ""
    # 去掉代码块，只在自然语言里找结论
    body = _FENCE_RE.sub(" ", text)
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if not lines:
        return ""
    return lines[-1][:300]


def hits_any(text: str, markers: list[str]) -> list[str]:
    """返回命中的标记列表（用于陷阱检测：答案里出现了套路化的错误结果）。"""
    if not text:
        return []
    low = text.replace(" ", "")
    out: list[str] = []
    for mk in markers:
        m2 = mk.replace(" ", "")
        if m2 and (m2 in low or m2.lower() in low.lower()):
            out.append(mk)
    return out


def safe_id(s: str) -> str:
    """把任意字符串转成可作文件名的安全 ID。"""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)
