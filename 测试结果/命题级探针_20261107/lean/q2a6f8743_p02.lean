import Mathlib.Tactic

example (a b : ℝ) (ha : 0 < a) (hb : 0 < b) : 
  (7 * a^2 + a * b + b^2)^(1/3) = a + 1 ↔ 
  b^2 + a * b + (4 * a^2 - a^3 - 3 * a - 1) = 0 := by sorry
