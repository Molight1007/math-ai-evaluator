import Mathlib.Tactic

example (t : ℕ) (ht : 0 < t) : ∃ (a b : ℕ) (ha : 0 < a) (hb : 0 < b), (7 * a^2 + a * b + b^2)^(1/3 : ℝ) = a + 1 ∧ a = t * (t + 1) := by sorry
