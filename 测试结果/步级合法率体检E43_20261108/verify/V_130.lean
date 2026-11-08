import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (D : ℝ) (x : ℕ → ℝ) (hD : 0 < D) (hx : ∀ m n, m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) (hbound : ∀ n, 0 ≤ x n ∧ x n ≤ 777) : x 1 = 0 := by
  by_contra h1_ne
  have h1_pos := (hbound 1).1
  have h2 := hx 0 1
  have h2' := h2 (by norm_num)
  have h3 := hx 0 2, have h3' := h3 (by norm_num), norm_num at h2', h3'
#eval "MARK_130"
