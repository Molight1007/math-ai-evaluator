import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (x : ℕ → ℝ) (h : ∀ i, 0 ≤ x i ∧ x i ≤ 777) (D : ℝ) (hcond : ∀ m n, m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) : D ≤ 777 ^ 2 / 2 := by
  have h777 : ∀ (i : ℕ), x i ^ 2 ≤ 777 ^ 2 := by
  intro i
  have := h i
  exact pow_le_pow (le_of_lt (lt_of_le_of_right this.1)) (le_of_lt (lt_of_le_of_right this.2)) 2
#eval "MARK_84"
