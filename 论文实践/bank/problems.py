# -*- coding: utf-8 -*-
"""四类思想实验题库。

这是整个实验的**核心资产**：每道题都经过"结构标注"——
不仅标注标准答案，还标注它依赖的**数学结构**、以及会诱导模型的**错误模板**。

设计原则（对应老师的问题"它能否观察到更本质的数学结构"）：
- A 组：源题与目标题**结构同构、表层不同** → 测"联想/类比"能否发生
- B 组：表层像模板 X、实则需要结构 Y → 测类比是否**用错了地方**
- C 组：解完后能否**命名**所用结构（元认知）+ 反向用 Lean 造最小示例（真懂的硬判据）
- D 组：具体⇄一般 的双向抽象能力

⚠️ 环境约束（2026-09-03 实测）：Mathlib 闭包只有 Mathlib.Tactic，
**不含 BigOperators 的 ∑ 记号**，也不含大量分析/拓扑模块。
因此凡涉及求和式、极限、连续性的题目，`gold_lean` 留空（表示该题不做 Lean 判定，
由文本标记或人工复核判分）。这类题正是"组合/几何难以低成本形式化"这一
方法局限的体现，论文 limitations 必须写明。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- 通用
STRUCTURE_OPTIONS: list[str] = [
    "抽屉原理 / 鸽巢原理",
    "不变量与染色",
    "数学归纳法",
    "极端原理",
    "反证法与构造反例",
    "配方法与平方和非负",
    "双射与计数",
    "同余与模运算",
    "对称性与群作用",
    "单调性与极值",
    "均值不等式（AM-GM / Cauchy）",
    "生成函数",
]

_LEAN_HEADER = "import Mathlib.Tactic\n\n"


def _lean(body: str) -> str:
    """给证明体补上 Mathlib 导入头。"""
    return _LEAN_HEADER + body.strip() + "\n"


# ================================================================
# A 组：同构迁移（Isomorphic Transfer）
# ================================================================
@dataclass
class TransferPair:
    pid: str
    kind: str            # near=近迁移 / cross=跨域迁移 / control=正对照
    desc: str            # 这一对"同构"在哪里
    core: str            # 共享的数学结构核心（人类可读）
    core_family: list[str]  # 共享结构对应的 Lean 指纹族（判迁移的基准）
    source_statement: str
    target_statement: str
    source_gold_lean: str
    target_gold_lean: str


TRANSFER_PAIRS: list[TransferPair] = [
    TransferPair(
        pid="A1",
        kind="near",
        desc="二元→三元：同一'平方和非负'核心，变量数不同",
        core="移项后配成若干个完全平方之和，用平方非负得证",
        core_family=["nlinarith", "sq_nonneg"],
        source_statement=(
            "证明：对任意实数 a, b，都有 (a + b)² ≥ 4ab。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        target_statement=(
            "证明：对任意实数 a, b, c，都有 (a + b + c)² ≥ 3(ab + bc + ca)。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        source_gold_lean=_lean(
            "example (a b : ℝ) : (a + b)^2 ≥ 4 * a * b := by\n"
            "  nlinarith [sq_nonneg (a - b)]"
        ),
        target_gold_lean=_lean(
            "example (a b c : ℝ) : (a + b + c)^2 ≥ 3 * (a * b + b * c + c * a) := by\n"
            "  nlinarith [sq_nonneg (a - b), sq_nonneg (b - c), sq_nonneg (c - a)]"
        ),
    ),
    TransferPair(
        pid="A2",
        kind="near",
        desc="平方差→立方和：同一'多项式展开恒等变形'核心",
        core="把两边展开成标准多项式后逐项相等，用环上的恒等判别",
        core_family=["ring"],
        source_statement=(
            "证明：对任意整数 n，都有 n² - 1 = (n - 1)(n + 1)。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        target_statement=(
            "证明：对任意整数 n，都有 n³ + 1 = (n + 1)(n² - n + 1)。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        source_gold_lean=_lean(
            "example (n : ℤ) : n^2 - 1 = (n - 1) * (n + 1) := by\n"
            "  ring"
        ),
        target_gold_lean=_lean(
            "example (n : ℤ) : n^3 + 1 = (n + 1) * (n^2 - n + 1) := by\n"
            "  ring"
        ),
    ),
    TransferPair(
        pid="A3",
        kind="cross",
        desc="跨域迁移：双变量对称不等式 → 单变量二次型配方（表层从'不等式'变为'函数恒非负'）",
        core="把式子配成完全平方 (x-1)²，用平方非负得证",
        core_family=["nlinarith", "sq_nonneg"],
        source_statement=(
            "证明：对任意实数 x, y，都有 x² + y² ≥ 2xy。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        target_statement=(
            "证明：对任意实数 x，二次函数 f(x) = x² - 2x + 1 的值恒非负，"
            "即 x² - 2x + 1 ≥ 0 恒成立。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        source_gold_lean=_lean(
            "example (x y : ℝ) : x^2 + y^2 ≥ 2 * x * y := by\n"
            "  nlinarith [sq_nonneg (x - y)]"
        ),
        target_gold_lean=_lean(
            "example (x : ℝ) : x^2 - 2 * x + 1 ≥ 0 := by\n"
            "  nlinarith [sq_nonneg (x - 1)]"
        ),
    ),
    TransferPair(
        pid="A4",
        kind="near",
        desc="绝对值三角不等式：两项 → 三项（同一引理连用两次）",
        core="反复使用 |u+v| ≤ |u|+|v|，再用线性算术合并",
        # 实测：闭包内引理名是 abs_add_le，不是 abs_add（2026-09-03）
        core_family=["abs_add_le", "linarith"],
        source_statement=(
            "证明：对任意实数 a, b，都有 |a + b| ≤ |a| + |b|。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        target_statement=(
            "证明：对任意实数 a, b, c，都有 |a + b + c| ≤ |a| + |b| + |c|。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        source_gold_lean=_lean(
            "example (a b : ℝ) : |a + b| ≤ |a| + |b| := by\n"
            "  exact abs_add_le a b"
        ),
        target_gold_lean=_lean(
            "example (a b c : ℝ) : |a + b + c| ≤ |a| + |b| + |c| := by\n"
            "  have h1 : |a + b + c| ≤ |a + b| + |c| := by\n"
            "    simpa [add_assoc] using abs_add_le (a + b) c\n"
            "  have h2 : |a + b| ≤ |a| + |b| := abs_add_le a b\n"
            "  linarith"
        ),
    ),
    TransferPair(
        pid="A5",
        kind="control",
        desc="正对照：同一线性算术模板，只换系数（预期迁移率接近 100%，用于界定指标上限）",
        core="带下界条件的线性不等式，交给算术判定过程",
        core_family=["omega"],
        source_statement=(
            "证明：对任意自然数 n，若 n ≥ 5，则 2n + 5 ≤ 3n。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        target_statement=(
            "证明：对任意自然数 n，若 n ≥ 10，则 5n + 10 ≤ 6n。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        source_gold_lean=_lean(
            "example (n : ℕ) (h : n ≥ 5) : 2 * n + 5 ≤ 3 * n := by omega"
        ),
        target_gold_lean=_lean(
            "example (n : ℕ) (h : n ≥ 10) : 5 * n + 10 ≤ 6 * n := by omega"
        ),
    ),
    TransferPair(
        pid="A6",
        kind="near",
        desc="配方：首项系数为 1 → 首项系数为 4（同一配方核心，需识别 (2x+1)²）",
        core="把二次式配成完全平方，用平方非负得证",
        core_family=["nlinarith", "sq_nonneg"],
        source_statement=(
            "证明：对任意实数 x，都有 x² + 2x + 1 ≥ 0。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        target_statement=(
            "证明：对任意实数 x，都有 4x² + 4x + 1 ≥ 0。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        source_gold_lean=_lean(
            "example (x : ℝ) : x^2 + 2 * x + 1 ≥ 0 := by\n"
            "  nlinarith [sq_nonneg (x + 1)]"
        ),
        target_gold_lean=_lean(
            "example (x : ℝ) : 4 * x^2 + 4 * x + 1 ≥ 0 := by\n"
            "  nlinarith [sq_nonneg (2 * x + 1)]"
        ),
    ),
    TransferPair(
        pid="A7",
        kind="near",
        desc="分式化简：同一'通分去分母 + 环上化简'核心，被化简的式子不同",
        core="先通分消去分母，再用环上恒等判别收尾",
        core_family=["field_simp", "ring"],
        source_statement=(
            "证明：对任意非零实数 x，都有 (x + 1)/x = 1 + 1/x。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        target_statement=(
            "证明：对任意非零实数 x，都有 (x² + x)/x = x + 1。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        # 注意：field_simp [hx] 本身就能解完目标，若再单独写一行 ring 会报
        # "No goals to be solved"。用 <;> ring 才能两种情况都安全。
        source_gold_lean=_lean(
            "example (x : ℝ) (hx : x ≠ 0) : (x + 1) / x = 1 + 1 / x := by\n"
            "  field_simp [hx] <;> ring"
        ),
        target_gold_lean=_lean(
            "example (x : ℝ) (hx : x ≠ 0) : (x^2 + x) / x = x + 1 := by\n"
            "  field_simp [hx] <;> ring"
        ),
    ),
    TransferPair(
        pid="A8",
        kind="cross",
        desc="跨域迁移：从'平方和非负'到'平方和为零则各项为零'——结论强度升级，需多走一步推理",
        core="平方非负；若平方和恰为 0，则每个平方项都只能是 0",
        core_family=["nlinarith", "sq_nonneg"],
        source_statement=(
            "证明：对任意实数 a, b，都有 a² + b² ≥ 0。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        target_statement=(
            "证明：对任意实数 a, b，若 a² + b² = 0，则 a = 0。\n"
            "请给出完整的 Lean 4 证明代码（以 example 开头，能编译通过）。"
        ),
        source_gold_lean=_lean(
            "example (a b : ℝ) : a^2 + b^2 ≥ 0 := by\n"
            "  nlinarith [sq_nonneg a, sq_nonneg b]"
        ),
        target_gold_lean=_lean(
            "example (a b : ℝ) (h : a^2 + b^2 = 0) : a = 0 := by\n"
            "  nlinarith [sq_nonneg a, sq_nonneg b]"
        ),
    ),
]


# ================================================================
# B 组：陷阱题（Trap）
# ================================================================
@dataclass
class TrapItem:
    tid: str
    statement: str
    trap_desc: str            # 陷阱机制（诱导模型用什么错误模板）
    trap_markers: list[str]   # 命中 → 判定"被套路"
    gold_markers: list[str]   # 命中 → 判定"识破"（优先于 trap 判定）
    gold_answer: str
    gold_structure: str
    gold_lean: str            # 空串 = 该题不做 Lean 判定（见文件头说明）


TRAP_ITEMS: list[TrapItem] = [
    TrapItem(
        tid="B1",
        statement=(
            "求函数 f(x) = x² + 2/x 在 x > 0 时的最小值，并指出在哪个 x 处取到。\n"
            "请先给出推理，再在最后一行用『最小值：M，取到时 x = t』的格式给出结论。"
        ),
        trap_desc=(
            "表层像'两项 AM-GM'，直接套 a+b ≥ 2√(ab) 会得到 2√(2x) —— 含 x 不是常数，"
            "或硬算成 2√2 ≈ 2.828。正解需拆成三项：x² + 1/x + 1/x ≥ 3（x=1 取等）。"
        ),
        trap_markers=["2√2", "2*√2", "2sqrt2", "2.828", "2√", "√(2x)", "sqrt(2x)"],
        gold_markers=["3", "x = 1", "x=1"],
        gold_answer="最小值 3（x = 1）",
        gold_structure="配方法与平方和非负",
        gold_lean=_lean(
            "example (x : ℝ) (hx : 0 < x) : x^2 + 2 / x ≥ 3 := by\n"
            "  have hxne : x ≠ 0 := ne_of_gt hx\n"
            "  have hsq : 0 ≤ (x - 1)^2 := sq_nonneg (x - 1)\n"
            "  have hx2 : 0 < x + 2 := by linarith\n"
            "  have hprod : 0 ≤ (x - 1)^2 * (x + 2) :=\n"
            "    mul_nonneg hsq (le_of_lt hx2)\n"
            "  have hpoly : 0 ≤ x^3 - 3 * x + 2 := by nlinarith\n"
            "  have hmul : 0 ≤ x * (x^2 + 2 / x - 3) := by\n"
            "    have hiden : x * (x^2 + 2 / x - 3) = x^3 - 3 * x + 2 := by\n"
            "      field_simp [hxne]\n"
            "      ring\n"
            "    rw [hiden]\n"
            "    exact hpoly\n"
            "  have hnonneg : 0 ≤ x^2 + 2 / x - 3 :=\n"
            "    (mul_nonneg_iff_of_pos_left hx).mp hmul\n"
            "  linarith"
        ),
    ),
    TrapItem(
        tid="B2",
        statement=(
            "对任意正整数 n，n² + n + 41 都是素数吗？\n"
            "如果成立，请给出证明思路；如果不成立，请给出最小的正整数反例 n 并验证。\n"
            "最后一行用『结论：成立 / 不成立（n = ?）』的格式给出。"
        ),
        trap_desc=(
            "这是欧拉素数多项式：n = 0..39 时取值全是素数。模型极易被'前 40 项全成立'"
            "诱导，用归纳/模式外推断言恒成立。实际 n = 40 时 40²+40+41 = 1681 = 41²。"
        ),
        trap_markers=["结论：成立", "恒成立", "都是素数", "恒为素数", "无法构造反例"],
        gold_markers=["40", "1681", "41²", "41^2", "不成立"],
        gold_answer="不成立，n = 40（1681 = 41²）",
        gold_structure="反证法与构造反例",
        gold_lean=_lean(
            "example : 40^2 + 40 + 41 = 41^2 := by norm_num"
        ),
    ),
    TrapItem(
        tid="B3",
        statement=(
            "命题：若整数 n 满足 n² 能被 4 整除，则 n 一定能被 4 整除。\n"
            "这个命题对吗？若对请证明，若不对请给出具体反例。\n"
            "最后一行用『结论：对 / 不对（n = ?）』的格式给出。"
        ),
        trap_desc=(
            "表层极像欧几里得引理'p 为素数时 p|a² ⟹ p|a'。但 4 不是素数，"
            "盲目类比会答'对'。实际反例：n = 2（4 | 4，但 4 ∤ 2）。"
            "这题测的正是**类比是否用错了地方**——老师关心的核心。"
        ),
        trap_markers=["结论：对", "命题成立", "该命题正确", "一定成立", "是正确的"],
        gold_markers=["n = 2", "n=2", "取 n=2", "不对", "反例"],
        gold_answer="不对，反例 n = 2",
        gold_structure="反证法与构造反例",
        gold_lean=_lean(
            "example : 4 ∣ (2:ℤ)^2 ∧ ¬ 4 ∣ (2:ℤ) := by norm_num"
        ),
    ),
    TrapItem(
        tid="B4",
        statement=(
            "命题：对一切正整数 n，都有 2ⁿ > n²。\n"
            "这个命题成立吗？如果成立请用数学归纳法证明；如果不成立，"
            "请指出使它失效的 n 并说明原因。\n"
            "最后一行用『结论：成立 / 不成立（n = ?）』的格式给出。"
        ),
        trap_desc=(
            "'指数最终碾压多项式'是正确的直觉，极易诱导模型断言归纳可证。"
            "但 n = 2 时 2² = 4 = 2²（相等，非严格大于），n = 4 时 2⁴ = 16 = 4²。"
            "真正成立需要 n ≥ 5。这是'归纳起步点没验证'的经典陷阱。"
        ),
        trap_markers=["结论：成立", "对一切正整数成立", "归纳法可证", "恒成立"],
        gold_markers=["n = 2", "n=2", "n = 4", "n=4", "不成立", "n ≥ 5"],
        gold_answer="不成立（n = 2 与 n = 4 处取等；仅当 n ≥ 5 时成立）",
        gold_structure="反证法与构造反例",
        gold_lean=_lean(
            "example : ¬ (2^2 > (2:ℕ)^2) := by norm_num"
        ),
    ),
    TrapItem(
        tid="B5",
        statement=(
            "函数 f(x) = x + 1/x 在其**整个定义域**（即 x ≠ 0 的一切实数）上，"
            "是否存在最小值？若存在请给出最小值，若不存在请说明原因。\n"
            "最后一行用『结论：存在（最小值 M） / 不存在』的格式给出。"
        ),
        trap_desc=(
            "经典结论'x + 1/x ≥ 2（x > 0）'广为人知。把定义域换成整个 ℝ\\{0} 后，"
            "当 x → 0⁻ 时 f(x) → −∞，最小值**不存在**。模型极易把正区间结论"
            "错误迁移到全定义域——这是'类比用错地方'在**定义域维度**上的体现。"
        ),
        trap_markers=["最小值 2", "最小值为 2", "最小值：2", "最小值是 2", "最小值为2"],
        gold_markers=["不存在", "没有最小值", "无最小值", "−∞", "-∞", "负无穷"],
        gold_answer="不存在最小值（x → 0⁻ 时趋于 −∞）",
        gold_structure="单调性与极值",
        gold_lean="",   # 涉及极限，闭包内难以低成本形式化 → 由文本标记判定
    ),
    TrapItem(
        tid="B6",
        statement=(
            "袋中有 3 个红球和 3 个蓝球，球除颜色外完全相同。\n"
            "至少取出多少个球，才能**保证**取出的球中一定有 2 个红球？\n"
            "最后一行用『结论：n 个』的格式给出。"
        ),
        trap_desc=(
            "题面是标准的'袋子取球'表述，强烈诱导套抽屉原理（2 种颜色 → 答 3 个）。"
            "但问的是**保证有 2 个红球**，不是保证有 2 个同色球："
            "最坏情况是先取完 3 个蓝球，再取 2 个红球，共需 5 个。"
            "正解需要**最坏情况分析（极端原理）**，而非简单鸽巢。组合类的经典误用。"
        ),
        trap_markers=["结论：2 个", "结论：2个", "结论：3 个", "结论：3个",
                      "2 个即可", "3 个即可"],
        gold_markers=["5", "五个", "5 个"],
        gold_answer="5 个（最坏情况：取完 3 个蓝球后再取 2 个红球）",
        gold_structure="极端原理",
        gold_lean="",   # 组合计数，闭包内难形式化 → 由文本标记判定
    ),
]


# ================================================================
# C 组：结构指认（Structure Articulation）
# ================================================================
@dataclass
class StructItem:
    sid: str
    statement: str
    gold_option: str
    note: str = ""


STRUCT_ITEMS: list[StructItem] = [
    StructItem(
        sid="C1",
        statement=(
            "8×8 国际象棋棋盘去掉两个**对角**上的格子后，能否用 31 张 1×2 骨牌完全覆盖？"
            "请回答能否，并说明你用的核心数学结构是什么。"
        ),
        gold_option="不变量与染色",
        note="对角两格同色，剩下 32 黑 30 白（或反之），每张骨牌必覆盖一黑一白 → 不可能",
    ),
    StructItem(
        sid="C2",
        statement=(
            "证明：任意 6 个人中，必有 3 个人两两互相认识或两两互相不认识。"
            "请说明你用的核心数学结构是什么。"
        ),
        gold_option="抽屉原理 / 鸽巢原理",
        note="Ramsey R(3,3)=6：固定一人，其余 5 人分入'认识/不认识'两个抽屉",
    ),
    StructItem(
        sid="C3",
        statement=(
            "证明：1 + 2 + … + n = n(n+1)/2 对一切正整数 n 成立。"
            "请说明你用的核心数学结构是什么。"
        ),
        gold_option="数学归纳法",
        note="基础步 + 归纳步",
    ),
    StructItem(
        sid="C4",
        statement=(
            "平面上给定有限个点，且它们不全共线。证明：存在一条直线，恰好经过其中两个点，"
            "而其余所有点都严格位于这条直线的同一侧。请说明你用的核心数学结构是什么。"
        ),
        gold_option="极端原理",
        note="取距离某条基准直线最近/最远的点对，或用旋转直线法（凸包的一条边）",
    ),
    StructItem(
        sid="C5",
        statement=(
            "n² + n + 41 是否对所有正整数 n 都是素数？请回答，"
            "并说明你用的核心数学结构是什么。"
        ),
        gold_option="反证法与构造反例",
        note="n = 40 给出反例 1681 = 41²",
    ),
    StructItem(
        sid="C6",
        statement=(
            "证明：对任意实数 a, b, c，都有 (a+b+c)² ≥ 3(ab+bc+ca)。"
            "请说明你用的核心数学结构是什么。"
        ),
        gold_option="配方法与平方和非负",
        note="等价于 ½[(a-b)² + (b-c)² + (c-a)²] ≥ 0",
    ),
    StructItem(
        sid="C7",
        statement=(
            "证明：任意 5 个整数中，必有两个数之差能被 4 整除。"
            "请说明你用的核心数学结构是什么。"
        ),
        gold_option="抽屉原理 / 鸽巢原理",
        note="按模 4 的余数分成 4 类，5 个数必有两者同类 → 差被 4 整除",
    ),
    StructItem(
        sid="C8",
        statement=(
            "证明：√2 是无理数。请说明你用的核心数学结构是什么。"
        ),
        gold_option="反证法与构造反例",
        note="假设 √2 = p/q 既约 → 推出 p, q 皆为偶数，与既约矛盾",
    ),
    StructItem(
        sid="C9",
        statement=(
            "证明：在一群人中，认识奇数个人的人数一定是偶数。"
            "（认识关系是相互的）请说明你用的核心数学结构是什么。"
        ),
        gold_option="双射与计数",
        note="握手定理：把所有人的'认识关系数'求和，每条关系被数了两次 → 总和为偶数",
    ),
    StructItem(
        sid="C10",
        statement=(
            "证明：方程 x² + y² = 3 没有整数解。请说明你用的核心数学结构是什么。"
        ),
        gold_option="同余与模运算",
        note="平方数模 4 只能是 0 或 1，两平方和模 4 不可能是 3",
    ),
]


@dataclass
class ReverseTask:
    """反向任务：给结构名，要求用 Lean 写出体现该结构的最小可编译示例。

    这是'是否真懂'的硬判据——比选择题更能区分"背过名词"和"掌握结构"。
    """
    rid: str
    structure: str
    lean_task: str
    expected_family: list[str]
    gold_lean: str


REVERSE_TASKS: list[ReverseTask] = [
    ReverseTask(
        rid="R1",
        structure="数学归纳法",
        lean_task=(
            "用 Lean 4 写一条**最小**命题及其证明，用来体现『数学归纳法』这一结构。"
            "要求：能编译通过，且证明中必须真正使用 induction。"
        ),
        expected_family=["induction"],
        # 注意：闭包只有 Mathlib.Tactic，不带 BigOperators 的 ∑ 记号，
        # 故这里用"递归定义 = 闭式"这一同样纯正的归纳结构来命题。
        gold_lean=_lean(
            "def dbl : Nat → Nat\n"
            "  | 0 => 0\n"
            "  | n+1 => dbl n + 2\n"
            "\n"
            "example (n : Nat) : dbl n = 2 * n := by\n"
            "  induction n with\n"
            "  | zero => simp [dbl]\n"
            "  | succ n ih => simp [dbl, ih] <;> omega"
        ),
    ),
    ReverseTask(
        rid="R2",
        structure="配方法与平方和非负",
        lean_task=(
            "用 Lean 4 写一条**最小**命题及其证明，用来体现『配方法与平方和非负』这一结构。"
            "要求：能编译通过，且证明中必须用到平方非负。"
        ),
        expected_family=["sq_nonneg", "nlinarith"],
        gold_lean=_lean(
            "example (x : ℝ) : 0 ≤ (x - 1)^2 := by\n"
            "  exact sq_nonneg (x - 1)"
        ),
    ),
    ReverseTask(
        rid="R3",
        structure="反证法与构造反例",
        lean_task=(
            "用 Lean 4 写一条**最小**命题及其证明，用来体现『构造反例』这一结构："
            "即证明某个全称命题不成立（用具体反例）。要求能编译通过。"
        ),
        expected_family=["norm_num", "use", "push_neg"],
        gold_lean=_lean(
            "example : ¬ (∀ n : ℕ, Nat.Prime (n^2 + n + 41)) := by\n"
            "  push_neg\n"
            "  use 40\n"
            "  norm_num"
        ),
    ),
    ReverseTask(
        rid="R4",
        structure="同余与模运算",
        lean_task=(
            "用 Lean 4 写一条**最小**命题及其证明，用来体现『同余与模运算』这一结构："
            "即证明某个具体的整除/余数结论。要求能编译通过。"
        ),
        expected_family=["norm_num", "omega"],
        gold_lean=_lean(
            "example : 3 ∣ (7^3 - 7 : ℤ) := by norm_num"
        ),
    ),
]


# ================================================================
# D 组：抽象 ⇄ 实例化（Abstraction）
# ================================================================
@dataclass
class AbsItem:
    aid: str
    direction: str          # c2g=具体→一般 / g2c=一般→具体
    statement: str
    gold_answer: str
    answer_patterns: list[str]  # 正则，命中任一即判抽象正确
    gold_lean: str
    note: str = ""


ABS_ITEMS: list[AbsItem] = [
    AbsItem(
        aid="D1",
        direction="c2g",
        statement=(
            "观察下列等式：\n"
            "1³ = 1 = 1²\n"
            "1³ + 2³ = 9 = 3² = (1+2)²\n"
            "1³ + 2³ + 3³ = 36 = 6² = (1+2+3)²\n"
            "请抽象出一般的公式（用 n 表示），并说明它为何成立。"
        ),
        gold_answer="1³ + 2³ + … + n³ = (1+2+…+n)² = [n(n+1)/2]²",
        answer_patterns=[
            r"n\s*\(\s*n\s*\+\s*1\s*\)\s*/\s*2\s*\)\s*\^?\s*2",
            r"\(\s*n\s*\(\s*n\s*\+\s*1\s*\)\s*/\s*2\s*\)\s*\^?\s*2",
            r"n\s*\^?\s*2\s*\(\s*n\s*\+\s*1\s*\)\s*\^?\s*2\s*/\s*4",
            r"\(\s*1\s*\+\s*2\s*\+\s*…?\.{0,3}\s*\+\s*n\s*\)\s*\^?\s*2",
            r"\[\s*n\s*\(\s*n\s*\+\s*1\s*\)\s*/\s*2\s*\]\s*\^?\s*2",
        ],
        gold_lean=_lean(
            "example : (1:ℕ)^3 + (2:ℕ)^3 + (3:ℕ)^3 + (4:ℕ)^3 = (4 * 5 / 2)^2 := by\n"
            "  norm_num"
        ),
        note="立方和等于和的平方；Lean 用 n=4 的具体实例做客观校验",
    ),
    AbsItem(
        aid="D2",
        direction="g2c",
        statement=(
            "已知欧几里得引理：若 p 是素数且 p | ab，则 p | a 或 p | b。\n"
            "现在把定理中的素数 p 换成合数 6，命题『若 6 | ab，则 6 | a 或 6 | b』"
            "还成立吗？若成立请说明理由，若不成立请给出具体的整数反例 a, b。"
        ),
        gold_answer="不成立。反例 a = 2, b = 3（6 | 6，但 6 ∤ 2 且 6 ∤ 3）",
        answer_patterns=[
            r"a\s*=\s*2.{0,20}b\s*=\s*3",
            r"2.{0,15}和.{0,5}3",
            r"2\s*×\s*3\s*=\s*6",
        ],
        gold_lean=_lean(
            "example : 6 ∣ (2:ℤ) * (3:ℤ) ∧ ¬ 6 ∣ (2:ℤ) ∧ ¬ 6 ∣ (3:ℤ) := by\n"
            "  norm_num"
        ),
        note="测'是否理解定理条件的必要性'——抽象理解的核心",
    ),
    AbsItem(
        aid="D3",
        direction="c2g",
        statement=(
            "观察下列勾股数：3² + 4² = 5²，5² + 12² = 13²，8² + 15² = 17²。\n"
            "请抽象出勾股数的一般参数化公式：用两个整数参数 m, n 表示出 a, b, c，"
            "使得 a² + b² = c² 恒成立。"
        ),
        gold_answer="a = m² - n², b = 2mn, c = m² + n²",
        answer_patterns=[
            r"m\s*\^?\s*2\s*-\s*n\s*\^?\s*2",
            r"2\s*\*?\s*m\s*\*?\s*n",
            r"m\s*\^?\s*2\s*\+\s*n\s*\^?\s*2",
        ],
        gold_lean=_lean(
            "example (m n : ℤ) : (m^2 - n^2)^2 + (2*m*n)^2 = (m^2 + n^2)^2 := by\n"
            "  ring"
        ),
        note="最强客观判据：模型给出的参数化若正确，Lean 用 ring 一步验证恒等式",
    ),
    AbsItem(
        aid="D4",
        direction="g2c",
        statement=(
            "费马小定理：若 p 是素数且 p 不整除 a，则 a^(p-1) ≡ 1 (mod p)。\n"
            "现在把素数 p 换成**合数 4**，取 a = 2：式子 2^(4-1) = 2³ ≡ 1 (mod 4) "
            "是否成立？若不成立，请给出 2³ 除以 4 的实际余数。"
        ),
        gold_answer="不成立。2³ = 8，8 mod 4 = 0，不等于 1",
        answer_patterns=[
            r"8\s*.*\s*4.{0,10}(余|mod|≡).{0,5}0",
            r"余数.{0,5}0",
            r"=\s*0",
            r"不成立",
        ],
        gold_lean=_lean(
            "example : ¬ (((2:ℤ)^3) % 4 = 1) := by norm_num"
        ),
        note="测'素数条件是否为定理成立的必要前提'——与 D2 同族但换到费马小定理",
    ),
    AbsItem(
        aid="D5",
        direction="c2g",
        statement=(
            "观察下列等式：\n"
            "1 = 1 = 1²\n"
            "1 + 3 = 4 = 2²\n"
            "1 + 3 + 5 = 9 = 3²\n"
            "1 + 3 + 5 + 7 = 16 = 4²\n"
            "请抽象出一般的公式（用 n 表示前 n 个奇数之和），并说明它为何成立。"
        ),
        gold_answer="前 n 个奇数之和 = n²，即 1 + 3 + 5 + … + (2n-1) = n²",
        answer_patterns=[
            r"1\s*\+\s*3\s*\+\s*5\s*\+\s*…?\.{0,3}\s*\+\s*\(\s*2\s*\*?\s*n\s*-\s*1\s*\)",
            r"2\s*\*?\s*n\s*-\s*1",
            r"前\s*n\s*个奇数",
            r"n\s*\^?\s*2",
        ],
        gold_lean=_lean(
            "example : 1 + 3 + 5 + 7 = (4:ℕ)^2 := by norm_num"
        ),
        note="与 D1 同属'求和闭式'抽象族，可对照看模型在两个不同序列上的抽象稳定性",
    ),
]


def all_gold_lean() -> list[tuple[str, str]]:
    """返回 (标识, gold_lean) 列表，供 gold 自检模式离线验证判据链路。

    gold_lean 为空串的题（组合/分析类，闭包内难以低成本形式化）会被跳过，
    它们不走 Lean 判定，只由文本标记或人工复核判分。
    """
    out: list[tuple[str, str]] = []
    for p in TRANSFER_PAIRS:
        out.append((f"{p.pid}-source", p.source_gold_lean))
        out.append((f"{p.pid}-target", p.target_gold_lean))
    for t in TRAP_ITEMS:
        out.append((f"{t.tid}-gold", t.gold_lean))
    for r in REVERSE_TASKS:
        out.append((f"{r.rid}-gold", r.gold_lean))
    for a in ABS_ITEMS:
        out.append((f"{a.aid}-gold", a.gold_lean))
    return [(k, v) for k, v in out if v.strip()]
