import Mathlib

open Real
set_option linter.unusedVariables.analyzeTactics true


theorem imo_1962_p2
  (x : ℝ)
  (h₀ : 0 ≤ 3 - x)
  (h₁ : 0 ≤ x + 1)
  (h₂ : 1 / 2 < Real.sqrt (3 - x) - Real.sqrt (x + 1)) :
  -1 ≤ x ∧ x < 1 - Real.sqrt 31 / 8 := by
  constructor
  . exact neg_le_iff_add_nonneg.mpr h₁
  have h₃: (2 *sqrt (3 - x) * sqrt (x + 1)) ^ 2 < (4 - 1 / 4) ^ 2 := by
    refine' pow_lt_pow_left₀ _ _ (by norm_num)
    . refine lt_tsub_iff_left.mpr ?_
      refine lt_tsub_iff_right.mp ?_
      suffices g₀: 4 - 2 * sqrt (3 - x) * sqrt (x + 1) = (sqrt (3 - x) - sqrt (x + 1)) ^ 2
      . rw [g₀]
        have g₁:  (1:ℝ) / 4 = (1/2)^2 := by norm_num
        rw [g₁]
        exact pow_lt_pow_left₀ h₂ (by norm_num) (by norm_num)
      rw [sub_sq]
      rw [sq_sqrt h₀, sq_sqrt h₁]
      ring_nf
    . refine' mul_nonneg _ _
      . refine mul_nonneg (by norm_num) ?_
        exact sqrt_nonneg (3 - x)
      . exact sqrt_nonneg (x + 1)
  have h₄: 4 * (x + 1) * (3 - x) < 225 / 16 := by
    norm_num at h₃
    suffices g₀: 4 * (x + 1) * (3 - x) = (2 * sqrt (3 - x) * sqrt (x + 1)) ^ 2
    . exact Eq.trans_lt g₀ h₃
    . rw [mul_pow, mul_pow, sq_sqrt h₀, sq_sqrt h₁]
      norm_num
      exact mul_right_comm 4 (x + 1) (3 - x)
  have hx1: x < 1 := by
    suffices g₀: x + 1 < 3 - x
    . linarith
    . rw [← sq_sqrt h₀, ← sq_sqrt h₁]
      refine' pow_lt_pow_left₀ _ _ (by norm_num)
      . linarith
      exact sqrt_nonneg (x + 1)
  have h₅: x < 1 - sqrt 31 / 8 ∨ 1 + sqrt 31 / 8 < x := by
    ring_nf at h₄
    have g₀: 0 < x * x + -2 * x + 33 / 64 := by linarith
    let a:ℝ := sqrt 31 / 8
    have g₁: x * x + -2 * x + 33 / 64 = (x - (1 + a)) * (x - (1 - a)) := by
      simp
      ring_nf
      norm_num
      linarith
    rw [g₁] at g₀
    by_cases g₂: (x - (1 - a)) < 0
    . left
      exact sub_neg.mp g₂
    push_neg at g₂
    right
    have g₃: 0 < (x - (1 + a)) := by exact pos_of_mul_pos_left g₀ g₂
    exact sub_pos.mp g₃
  cases h₅ with
  | inl h₅ => exact h₅
  | inr h₅ => linarith
