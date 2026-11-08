import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (q : ℕ) (hq : Nat.Prime q) (h3 : q > 3) : q ∣ 6 * Nat.factorial q - 1 := by
  apply Nat.dvd_sub
  · exact Nat.dvd_mul_right 6 q
#eval "MARK_197"
