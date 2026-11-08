import Mathlib.Tactic

set_option maxHeartbeats 200000

open BigOperators Real Nat Topology Rat

theorem probe_q21 (θ : ℕ) (hθ : 0 < θ ∧ θ < 90) : ∃ (k : ℕ), k = 360 / Nat.gcd 360 (2 * θ) := by sorry
