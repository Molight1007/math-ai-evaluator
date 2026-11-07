import Mathlib.Tactic

example (x y z : ℝ) (h1 : x^2 + y^2 + z^2 = 3) (h2 : x^6 + y^6 + z^6 = 3) :
  ((x^2 = 0 ∨ x^2 = 3) ∧ (y^2 = 0 ∨ y^2 = 3) ∧ (z^2 = 0 ∨ z^2 = 3)) ∧
  ([x^2, y^2, z^2].count 3 = 1) := by sorry
