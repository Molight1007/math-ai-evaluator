import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q08 (D : ℝ) (x : ℕ → ℝ) (hD : ∀ m n, 0 < m → m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) (hx : ∀ i, 0 ≤ x i ∧ x i ≤ 777) : D ≤ 777 ^ 2 := by sorry
