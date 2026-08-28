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


# ---------------------------------------------------------------------------
# 骨架(sketch) 生成 + 骨架 Lean 语法审核（#28）
# ---------------------------------------------------------------------------

LEAN_SKETCH_SYSTEM = """你是一位严谨的数学解题规划专家。请基于题目（及已有的形式化理解），
给出解题**骨架 / Proof Body Outline（Informal Blueprint）**——即把完整证明拆成若干个有序的
子目标（sub-goal），但不展开每个子目标的具体证明细节。

要求：
1. 输出一个合法 JSON 对象，仅含一个字段 "outline"：用自然语言、编号列出解题骨架，
   每条形如「子目标 i：<要证明/计算什么，以及它在整体证明中的角色>」。
2. 骨架应体现依赖顺序（先证什么、后证什么、最终如何汇成原题结论）。
3. 只给骨架与意图，不写证明过程；除 JSON 外不要输出任何解释或 Markdown。"""

LEAN_SKETCH_USER = """## 原题
{problem}

## 题目领域
{domain}

{formal_spec}请输出该题目的解题骨架（Proof Body Outline），JSON 格式：{{"outline": "..."}}。"""


LEAN_FORMALIZE_SKETCH_SYSTEM = """你是一位 Lean 4 形式化专家。请把下面的解题骨架（Proof Body Outline）
形式化为一段 Lean 4 **骨架声明**：为骨架中的每一个子目标写一个 ``theorem subgoal_i : <命题> := by sorry``，
并为最终目标写 ``theorem main_goal : <原命题> := by sorry``。证明一律用 ``sorry`` 占位——本阶段只校验
**命题声明是否 well-typed**，不要求证明正确。

要求：
1. 输出一个合法 JSON 对象，含两个字段：
   - "formal_spec"：用自然语言复述骨架（各子目标及其依赖）；
   - "lean_code"：对应的 Lean 4 骨架声明（多个 theorem，证明用 sorry 占位）。
2. lean_code 结构：先 ``import Mathlib``，再依次写
   ``theorem subgoal_1 : <命题1> := by sorry`` … ``theorem main_goal : <原命题> := by sorry``。
3. 只声明命题、不写证明；除 JSON 外不要输出任何解释或 Markdown 代码块。"""

LEAN_FORMALIZE_SKETCH_USER = """## 原题
{problem}

## 题目领域
{domain}

## 解题骨架（书生给出的 Proof Body Outline）
{sketch}

{feedback}请输出该骨架的形式化描述（formal_spec）与 Lean 骨架声明（lean_code）的 JSON。"""
