-- 题目ID: gen_e8e745df
-- 评测时间: 20260725_233211
-- 编译结果: FAILED
-- 原始问题: 求函数 $f(x) = x^3 - 3x + 1$ 在区间 $[-2, 2]$ 上的最大值和最小值。

{
  "lean_code": "import Mathlib\n\nopen Set\n\ndef f (x : ℝ) : ℝ := x^3 - 3*x + 1\n\ntheorem max_min_f :\n    (∃ x ∈ Icc (-2 : ℝ) 2, f x = 3) ∧ (∃ x ∈ Icc (-2 : ℝ) 2, f x = -1) ∧\n    (∀ x ∈ Icc (-2 : ℝ) 2, -1 ≤ f x ∧ f x ≤ 3) :=\nby\n  refine ⟨?_, ?_, ?_⟩\n  · refine ⟨2, ?_, ?_, ?_⟩\n    · norm_num\n    · norm_num\n    · unfold f; ring\n  · refine ⟨1, ?_, ?_, ?_⟩\n    · norm_num\n    · norm_num\n    · unfold f; ring\n  · intro x hx\n    rcases hx with ⟨hx1, hx2⟩\n    constructor\n    · -- f x ≥ -1\n      have hfactor : f x + 1 = (x + 2) * (x - 1)^2 := by\n        dsimp [f]; ring\n      have h_nonneg_sq : 0 ≤ (x - 1)^2 := pow_two_nonneg _\n      have h_nonneg_xplus2 : 0 ≤ x + 2 := by linarith\n      have h_nonneg : 0 ≤ f x + 1 := by\n        rw [hfactor]\n        exact mul_nonneg h_nonneg_xplus2 h_nonneg_sq\n      linarith\n    · -- f x ≤ 3\n      have hfactor : f x - 3 = (x - 2) * (x + 1)^2 := by\n        dsimp [f]; ring\n      have h_nonneg_s