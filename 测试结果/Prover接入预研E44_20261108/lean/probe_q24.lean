import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q24 (y : ℕ → ℝ) (h : ∀ n, 0 ≤ y n ∧ y n ≤ 777^2) : ∃ (s : Set ℕ), Infinite s ∧ (∀ i ∈ s, 0 ≤ y i ∧ y i ≤ 777^2/2) ∨ (∀ i ∈ s, 777^2/2 < y i ∧ y i ≤ 777^2) := by sorry
