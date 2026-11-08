import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q11 (f : ℕ+ → ℕ+) (h : ∀ n m : ℕ+, f (f n + f m) = n + m) : Function.Injective f := by sorry
