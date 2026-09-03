import Mathlib
set_option linter.unusedVariables.analyzeTactics true

open Real


lemma le_a_sq
  (a b c : ℝ) :
  (a + b - c) * (a + c - b) ≤ a ^ 2 := by
  have h1: (a + b - c) * (a + c - b) = a ^ 2 - (b - c) ^ 2 := by
    linarith
  have h2: 0 ≤ (b - c) ^ 2 := by exact pow_two_nonneg (b - c)
  rw [h1]
  exact sub_le_self _ h2


theorem imo_1964_p2
  (a b c : ℝ)
  (h₀ : 0 < a ∧ 0 < b ∧ 0 < c)
  (h₁ : c < a + b)
  (h₂ : b < a + c)
  (h₃ : a < b + c) :
  a ^ 2 * (b + c - a) + b ^ 2 * (c + a - b) + c ^ 2 * (a + b - c) ≤ 3 * a * b * c := by
  have ha : 0 < b + c - a := by exact sub_pos.mpr h₃
  have hb : 0 < a + c - b := by exact sub_pos.mpr h₂
  have hc : 0 < a + b - c := by exact sub_pos.mpr h₁
  have h₄: ((a + b - c) * (a + c - b) * (b + c - a)) ^ 2 ≤ (a * b * c) ^ 2 := by
    have h₄₁: (a + b - c) * (a + c - b) ≤ a ^ 2 := by
      exact le_a_sq a b c
    have h₄₂: (a + b - c) * (b + c - a) ≤ b ^ 2 := by
      rw [add_comm a b]
      exact le_a_sq b a c
    have h₄₃: (a + c - b) * (b + c - a) ≤ c ^ 2 := by
      rw [add_comm a c, add_comm b c]
      exact le_a_sq c a b
    have h₄₄: ((a + b - c) * (a + c - b) * (b + c - a)) ^ 2 = ((a + b - c) * (a + c - b)) *
        ((a + b - c) * (b + c - a)) * ((a + c - b) * (b + c - a)) := by
      linarith
    rw [h₄₄]
    repeat rw [mul_pow]
    refine mul_le_mul ?_ h₄₃ ?_ ?_
    . refine mul_le_mul h₄₁ h₄₂ ?_ ?_
      . refine le_of_lt ?_
        exact mul_pos hc ha
      . exact sq_nonneg a
    . refine le_of_lt ?_
      exact mul_pos hb ha
    . refine le_of_lt ?_
      simp_all only [sub_pos, gt_iff_lt, pow_pos, mul_pos_iff_of_pos_left]
  have h₅: (a + b - c) * (a + c - b) * (b + c - a) ≤ a * b * c := by
    refine le_of_pow_le_pow_left₀ (by norm_num) ?_ h₄
    refine le_of_lt ?_
    refine mul_pos ?_ h₀.2.2
    exact mul_pos h₀.1 h₀.2.1
  linarith
