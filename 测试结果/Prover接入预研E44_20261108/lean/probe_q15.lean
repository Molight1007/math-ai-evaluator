import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q15 (X : Set ℤ) (hNeg1 : -1 ∈ X) (hRich : ∀ (n : ℕ) (x : Fin (n+1) → ℤ), (∀ i, x i ∈ X) → ∀ r : ℤ, (∑ i : Fin (n+1), x i * r ^ (i : ℕ)) = 0 → r ∈ X) : ∀ r : ℤ, r ∈ X := by sorry
