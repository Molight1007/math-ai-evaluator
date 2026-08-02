-- 题目ID: 多元函数微分学_035
-- 评测时间: 20260725_233211
-- 编译结果: FAILED
-- 原始问题: 设函数 $u = xz + ay^3$（$z \geq 0$），且 $x^2 + y^2 + z^2 = 1$。(1) 当 $a = 0$ 时，求 $u$ 的最大值；(2) 当 $a = t$（$t$

{
  "lean_code": "import Mathlib\n\nopen Real\n\ndef u (t : ℝ) (x y z : ℝ) : ℝ := x * z + t * y ^ 3\n\ntheorem max_u (t : ℝ) : ∃ (x y z : ℝ), x^2 + y^2 + z^2 = 1 ∧ z ≥ 0 ∧ u t x y z = max (1/2 : ℝ) (|t|) ∧ ∀ (x' y' z' : ℝ), x'^2 + y'^2 + z'^2 = 1 → z' ≥ 0 → u t x' y' z' ≤ max (1/2 : ℝ) (|t|) :=\nby\n  by_cases h : |t| ≤ 1/2\n  · -- case |t| ≤ 1/2, maximum is 1/2\n    have hmax : max (1/2 : ℝ) (|t|) = 1/2 := by\n      rw [max_eq_left h]\n    refine ⟨Real.sqrt (1/2), 0, Real.sqrt