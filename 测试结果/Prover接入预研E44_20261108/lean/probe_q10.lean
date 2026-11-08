import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q10 (D : ℝ) (x : ℕ → ℝ) (hD : 0 < D) (hx : ∀ m n, m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) (hzero : ∀ n, x n = 0) : False := by sorry
