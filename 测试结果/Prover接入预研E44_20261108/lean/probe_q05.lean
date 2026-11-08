import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q05 (a : ℕ) (h : a ≥ 7) : ¬ (∃ k : ℕ, k^2 = 4*a^3 - a^2 - 12*a - 4) := by sorry
