import Mathlib.Tactic

example (x : ℝ) (hx : x ≠ 0) : (x + 1) / x = 1 + 1 / x := by
  field_simp [hx]
  ring
