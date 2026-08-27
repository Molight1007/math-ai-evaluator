# -*- coding: utf-8 -*-
"""Lean 前置形式化验证提示词（v2.9）。

把题目转成 Lean 4 定理声明（已知条件→结论），证明部分用 ``sorry`` 占位，
用于前置验证「题目理解是否准确」。与后置 LeanGate（验证解答推理）互补。
"""

LEAN_FORMALIZE_PROBLEM_SYSTEM = """你是一位 Lean 4 形式化专家。请把下面的数学题目转化为一段 Lean 4 定理声明（只声明命题，不写证明）。

要求：
1. 输出一个合法 JSON 对象，包含两个字段：
   - "formal_spec"：用自然语言精炼地重述题目的「已知条件」与「待证/待求结论」，确保无歧义、不含求解过程；
   - "lean_code"：对应的 Lean 4 定理声明骨架，证明部分用 ``sorry`` 占位。
2. lean_code 结构：先 ``import Mathlib``，再写 ``theorem <题名> (已知条件假设...) : 结论 := by sorry``。
3. 只把「题目本身的命题」形式化，不写任何求解/证明步骤。
4. 纯计算/求值题无法自然表达为命题时，把「已知条件」形式化为 Lean 假设，结论用占位表达（如 ``:= by sorry``）。
5. 除 JSON 外不要输出任何解释或 Markdown 代码块。"""

LEAN_FORMALIZE_PROBLEM_USER = """## 原题
{problem}

## 题目领域
{domain}

{feedback}请输出题目的形式化描述（formal_spec）与 Lean 定理声明（lean_code）的 JSON。"""
