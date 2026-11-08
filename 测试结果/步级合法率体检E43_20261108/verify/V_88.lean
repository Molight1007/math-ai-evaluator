import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (m : ℕ) (ho : Odd m) (hd : (2^(2*m - 1) + 1) % m = 0) : m % 3 = 0 := by
  obtain ⟨k, hk⟩ := ho
  rw [hk]
#eval "MARK_88"
