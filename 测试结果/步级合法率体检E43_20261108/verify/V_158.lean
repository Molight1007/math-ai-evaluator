import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (D : ℝ) (x : ℕ → ℝ) (hD : 0 < D) (hx : ∀ m n, m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) (h2 : ∀ n, 2 ≤ n → x n ^ 2 ≤ D / (n + 1)) : ∀ k, 2 ≤ k → x k = 0 := by
  intro k
  intro hk
  have h2k := h2 k hk
#eval "MARK_158"
