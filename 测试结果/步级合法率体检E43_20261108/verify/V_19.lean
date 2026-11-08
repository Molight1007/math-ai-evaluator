import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (D : ℝ) (x : ℕ → ℝ) (hD : 0 < D) (hx : ∀ m n, m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) (hbound : ∀ n, 0 ≤ x n ∧ x n ≤ 777) : x 1 = 0 := by
  have h1 := hx 0 1 (by norm_num)
  have h2 : |x 1 ^ 2 - x 0 ^ 2| ≥ D := by { rw [Nat.cast_zero, Nat.cast_one, add_zero] at h1, exact h1 }
#eval "MARK_19"
