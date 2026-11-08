import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q25 (x : ℕ → ℝ) (h : ∀ i, 0 ≤ x i ∧ x i ≤ 777) (D : ℝ) (hcond : ∀ m n, m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) : D ≤ 777 ^ 2 / 2 := by sorry
