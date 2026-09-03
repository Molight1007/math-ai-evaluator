import Mathlib

open Real
set_option linter.unusedVariables.analyzeTactics true


lemma sin_mul_cos
  (x y : ℝ) :
  Real.sin x * Real.cos y = (sin (x + y) + sin (x - y)) / 2 := by
    rw [sin_add, sin_sub]
    simp

theorem imo_1963_p5 :
  Real.cos (π / 7) - Real.cos (2 * π / 7) + Real.cos (3 * π / 7) = 1 / 2 := by
  let S:ℝ := Real.cos (π / 7) - Real.cos (2 * π / 7) + Real.cos (3 * π / 7)
  have h₀: Real.sin (π / 7) * (S * 2) = Real.sin (π / 7) := by
    ring_nf
    have h₀₀: sin (π * (1 / 7)) * cos (π * (1 / 7)) * 2 = sin (2 * (π * (1 / 7))) := by
      rw [Real.sin_two_mul]
      exact (mul_rotate 2 (sin (π * (1 / 7))) (cos (π * (1 / 7)))).symm
    rw [h₀₀, sin_mul_cos, sin_mul_cos]
    rw [← mul_add, ← mul_sub, ← mul_add, ← mul_sub]
    norm_num
    ring_nf
    have h₀₁: -sin (π * (3 / 7)) + sin (π * (4 / 7)) = 0 := by
      rw [add_comm]
      refine add_neg_eq_of_eq_add ?_
      simp
      refine sin_eq_sin_iff.mpr ?_
      use 0
      right
      ring
    linarith
  have h₁: S = 1 / 2 := by
    refine eq_div_of_mul_eq (by norm_num) ?_
    nth_rewrite 2 [← mul_one (sin (π / 7))] at h₀
    refine (mul_right_inj' ?_).mp h₀
    refine sin_ne_zero_iff.mpr ?_
    intro n
    ring_nf
    rw [mul_comm]
    simp
    push_neg
    constructor
    . by_contra! hc₀
      have hc₁: 7 * (↑n:ℝ) = 1 := by
        rw [mul_comm]
        exact (mul_eq_one_iff_eq_inv₀ (by norm_num)).mpr hc₀
      norm_cast at hc₁
      have g₀: 0 < n := by linarith
      linarith
    . exact pi_ne_zero
  exact h₁
