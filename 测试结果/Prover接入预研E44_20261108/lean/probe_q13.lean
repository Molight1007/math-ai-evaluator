import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q13 (a : ℕ → ℕ) (h : ∀ p, a (a (a p)) = a (p + 1) + 1) (h_a1 : a 1 = 1) (h_mono : ∀ n, a n < a (n + 1)) : ∀ n, 1 ≤ n → a n = n + 1 := by sorry
