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
    """返回命中的标记列表（用于陷阱检测：答案里出现了套路化的错误结果）。

    匹配前先 `normalize_math()`：模型可能写 `41²` 或 `41^2`、写 `1,681` 或 `1681`，
    不归一就会有"明明答对了却判为被套路"的静默误判。
    """
    if not text:
        return []
    low = normalize_math(text).replace(" ", "")
    out: list[str] = []
    for mk in markers:
        m2 = normalize_math(mk).replace(" ", "")
        if m2 and m2.lower() in low.lower():
            out.append(mk)
    return out


def safe_id(s: str) -> str:
    """把任意字符串转成可作文件名的安全 ID。"""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)


# ---------------------------------------------------------------- 记号归一
# **为什么要有这一步（2026-09-05 实测踩出来的真 bug）**：
# 同一句数学话，模型的写法差异极大——范数会写 `‖u‖` / `||u||` / `|u|`，
# 内积会写 `⟨u,v⟩` / `<u,v>` / `\langle u,v\rangle`，不等号会写 `≤` / `<=` / `\leq`。
# 若判据正则只认其中一种，**所有模型都会被系统性误判为"漏条件"**。
# 这种错误不会报错、不会失败，只会让论文结论**静默地错**——危害远大于崩溃。
# 因此：任何基于正则的文本判据，匹配前必须先 `normalize_math()`。

_LATEX_RES = (
    (re.compile(r"\\leq\b|\\le\b"), "<="),
    (re.compile(r"\\geq\b|\\ge\b"), ">="),
    (re.compile(r"\\neq\b|\\ne\b"), "!="),
    (re.compile(r"\\cdot\b"), "*"),
    (re.compile(r"\\times\b"), "*"),
    (re.compile(r"\\langle\b"), "<"),
    (re.compile(r"\\rangle\b"), ">"),
    (re.compile(r"\\\|"), "|"),
    (re.compile(r"\\in\b"), " in "),
)

_UNICODE_MAP = (
    # 范数 / 绝对值：全部归一到单竖线
    ("‖", "|"), ("∣", "|"), ("❘", "|"),
    # 内积括号
    ("⟨", "<"), ("⟩", ">"), ("〈", "<"), ("〉", ">"),
    # 乘号
    ("·", "*"), ("⋅", "*"), ("∙", "*"), ("×", "*"),
    # 关系符（∤ 与 ≡ 刻意**不**归一：E2 的正则依赖它们原样出现）
    ("≤", "<="), ("≥", ">="), ("≠", "!="),
    ("∈", " in "), ("∉", " notin "),
    # 减号变体
    ("−", "-"), ("－", "-"), ("–", "-"), ("—", "-"),
    # 全角标点
    ("（", "("), ("）", ")"), ("，", ","), ("。", "."),
    ("：", ":"), ("；", ";"),
    ("\u00a0", " "),
)

_MULTI_BAR_RE = re.compile(r"\|{2,}")


def normalize_math(text: str) -> str:
    """把数学记号的 LaTeX / Unicode 变体统一成 ASCII，供文本判据匹配。

    归一规则：
      - `\\|`、`‖`、`||` → `|`（范数与绝对值统一成单竖线）
      - `⟨ ⟩` → `< >`；`· × ⋅` → `*`；`≤ ≥ ≠` → `<= >= !=`
      - **刻意保留** `∤` 与 `≡`：E2 的正则（`p ∤ a`、`a^(p-1) ≡ 1`）依赖原样
    """
    if not text:
        return ""
    s = text
    for pat, rep in _LATEX_RES:
        s = pat.sub(rep, s)
    for a, b in _UNICODE_MAP:
        s = s.replace(a, b)
    s = _MULTI_BAR_RE.sub("|", s)
    return s
