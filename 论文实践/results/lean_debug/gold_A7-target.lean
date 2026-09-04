import Mathlib.Tactic

example (x : ℝ) (hx : x ≠ 0) : (x^2 + x) / x = x + 1 := by
  field_simp [hx]
  ring
