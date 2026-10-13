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
5. 除 JSON 外不要输出任何解释或 Markdown 代码块。

6. **必须避免的常见编译错误**（历次 112 题实测高频，出现任一即整段失效）：
   - **不要臆造 API/字段**：如 `Finset.Nodup` 并不存在（应写 `s.Nodup`，其中 `s : Finset α`；若用 `Set` 则用 `Set.InjOn`/`Set.Pairwise` 等）。**不确定的 API 一律退化为最基础的类型**（`Set` / `List` / 显式量词），宁可表达朴素也不要臆造名字。
   - **`Fin` 下标与边界**：`Fin (m - 1)` 与 `Fin m` 是不同类型，不可互传；避免在同一表达式里混用。需要相邻项时，优先用 `∀ i : Fin m, ...` 配 `∑ i : Fin m, f i` 的整体量化，或显式给出 `⟨i, by omega⟩` 并用 `omega`/`linarith` 关闭目标。
   - **求和语法**：`∑ i in s, f i` 的 `in` 只用于 `Finset`；`∑ i : Fin n, f i` 不带 `in`。二者不可混写，否则报 `unexpected token 'in'`。
   - **不要引用未定义的自定义谓词**（如 `reachable_in_steps`）：若题意确需辅助定义，**必须先 `def` 出来**，且该 `def` 自身要能编译。
   - **括号与换行**：多行 `theorem` 声明中，每个参数/假设行末尾注意逗号与括号配对，避免 `expected ';' or line break`。
   - **数值字面量类型**：在 `ℝ` 语境中必要时显式标注 `(2 : ℝ)`；整除法 `m / n` 在 `ℕ` 与 `ℝ` 下语义不同，按题意选类型。
   - **优先可编译性**：若某个华丽形式化写法有风险，改用更朴素的 `Prop` 组合（`∧`/`∨`/`∀`/`∃` + `Set`），**保证能编译通过**比表达精巧更重要。"""

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


# ---------------------------------------------------------------------------
# 题意前置理解升级（2026-10-12 用户设计 D1–D4）
#   ① 终态构建 ② 逻辑链 + Lean 自检 ③ 无条件反复理解（= 一致性复推，Q7）
#   ④ 缺口 A/B 分类
# ---------------------------------------------------------------------------

UNDERSTANDING_TERMINAL_SYSTEM = """你是数学题意校准专家。任务分两步：**先构建"这道题已经做完之后的情形"**，再把它写成一条可检验的逻辑链。

只输出一个 JSON 对象（无任何解释、无 Markdown 围栏），字段如下：

1. "terminal_state"：**假设本题已解出**（未知量已确定 / 命题已证成）时，题目里哪些事实必然同时成立。用自然语言，1–3 句。
2. "answer_slot"：所求对象的**符号化**表达。**禁止写出具体数值/具体答案**（值只能留作待定符号）。例如：
   · 求最大 n ⇒ `∃ n, P(n) ∧ ∀ m, m > n → ¬P(m)`（必须同时体现**可行性**与**严格性**）；
   · 求某值 ⇒ `f(x) = ?`（待定符号）；
   · 证明题 ⇒ 待证命题本身的符号形式。
3. "chain"：把"从题面条件推出终态"写成**有序逻辑链**，每节形如
   {"premises": ["题面条件或更早结论"], "conclusion": "由此推出的结论"}。
   最后一节的 conclusion 必须等价于 terminal_state。
4. "gaps"：为了推出终态所**缺少的东西**，每条形如 {"kind": "A"|"B", "detail": "..."}：
   ⚠ **本步不要输出 Lean 代码**（Lean 骨架由后续单独一步生成）——
     2026-10-13 实测：把 lean_code 一并要求会让输出超 32768 token 被截断，
     导致整个 JSON 不可解析（008/013 两题即因此空转）。
   · kind="A" = **题面确实没有给**的条件/数据（需假设才能推进）；
   · kind="B" = **题面已经给了、但本轮没有提取到**的条件/数据（属"我没读到"）。

硬性纪律：
- **禁止在 answer_slot 写具体数值**——提前写死数值会锁死后续推理（本项目 K11 根因）。
- 每节 premises 必须来自「题面条件」或「更早的结论」，不得悬空。
- 某节若难可靠形式化，改写为最朴素的 Prop 组合（∧/∨/∀/∃ + Set），宁可朴素也要能编译。
- 只输出 JSON。"""

UNDERSTANDING_LEAN_CODE_SYSTEM = """你是 Lean 4 形式化助手。给你一条**已确定的逻辑链**，请把它写成 Lean 4 骨架声明。

只输出一个 JSON 对象：{"lean_code": "..."}。
lean_code 结构：先 `import Mathlib`，随后链上**每一节**写一条
`lemma step_i (前提) : 结论 := by sorry`，最后写 `theorem final_state : <终态命题> := by sorry`。
全部用 `sorry` 占位（本阶段只校验声明是否 well-typed，不要求证明）。
**只输出 JSON，不要解释、不要 markdown 围栏。**"""

UNDERSTANDING_LEAN_CODE_USER = """## 原题
{problem}

## 已确定的逻辑链
{chain_text}

## 终态命题
{terminal_state}

请输出 {{"lean_code": "..."}}。"""


UNDERSTANDING_TERMINAL_USER = """## 原题
{problem}

## 领域
{domain}

请输出终态、逻辑链、Lean 骨架与缺口清单的 JSON。"""

UNDERSTANDING_REFINE_USER = """## 原题
{problem}

## 领域
{domain}

## 你上一轮的结论（请在此基础上再推一遍）
终态：{terminal_state}
答案槽：{answer_slot}

链：
{chain_text}

## 本轮任务（**不是纠错，是在已知该结果的前提下重推一遍**）
1. **假设上面的结论成立**，从头把这道题再推一遍：重推是否会得到与上面**一致**的结果？
2. 一致 ⇒ `"consistent": true`，chain 保持或细化即可。
3. 不一致 ⇒ `"consistent": false`，并在 `"diffs"` 里逐条写明**哪一节不同、为什么不同**
   （这通常说明上一轮对题意或条件的理解有偏差）。
4. 若发现题面有**没读到的条件**，归入 gaps 的 `kind="B"`。
5. 输出**同结构 JSON**（terminal_state / answer_slot / chain / lean_code / gaps / consistent / diffs）。"""
