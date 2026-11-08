import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q26 (m : ℕ) (ho : Odd m) (hd : (2^(2*m - 1) + 1) % m = 0) : m % 3 = 0 := by sorry
