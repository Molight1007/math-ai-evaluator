import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (D : ℝ) (x : ℕ → ℝ) (hD : 0 < D) (hx : ∀ m n, m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) (hzero : ∀ n, x n = 0) : False := by
  have h1 := hx 0 1 (by norm_num)
  rw [hzero 0, hzero 1] at h1
  norm_num at h1
  linarith
#eval "MARK_46"

