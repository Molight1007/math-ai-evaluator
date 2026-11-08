import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q20 (q : ℕ) (hq : Nat.Prime q) (h3 : q > 3) : q ∣ 6 * Nat.factorial q - 1 := by sorry
