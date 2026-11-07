import Mathlib.Tactic

example (a b c d e f : ℝ) :
  (a * d + b * e + c * f)^2 ≤ (a^2 + b^2 + c^2) * (d^2 + e^2 + f^2) ∧
  ((a * d + b * e + c * f)^2 = (a^2 + b^2 + c^2) * (d^2 + e^2 + f^2) ↔
    ∃ (k : ℝ), a = k * d ∧ b = k * e ∧ c = k * f) := by sorry
