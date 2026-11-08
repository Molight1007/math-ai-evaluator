import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q04 (a t : ℕ) : (a * (a - 1) * (24 - a) = t ^ 2) ↔ ((a - 1) * (24 - a) = (t / a) ^ 2) := by sorry
