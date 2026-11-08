import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (θ : ℕ) (hθ : 0 < θ ∧ θ < 90) : ∃ (k : ℕ), k = 360 / Nat.gcd 360 (2 * θ) := by
  aesop
#eval "MARK_80"

