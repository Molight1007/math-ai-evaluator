import Mathlib.Tactic

example (t : ℝ) (h : t^2 ≤ 3) : t^6 ≤ 3 * t^4 ∧ (t^6 = 3 * t^4 ↔ t^2 = 0 ∨ t^2 = 3) := by sorry
