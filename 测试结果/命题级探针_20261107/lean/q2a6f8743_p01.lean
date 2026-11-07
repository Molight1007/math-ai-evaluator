import Mathlib.Tactic

example (a b : ℕ) (ha : 0 < a) (hb : 0 < b) (h : (7 * a ^ 2 + a * b + b ^ 2) ^ (1 / 3 : ℝ) = a + 1) : 7 * a ^ 2 + a * b + b ^ 2 = (a + 1) ^ 3 := by sorry
