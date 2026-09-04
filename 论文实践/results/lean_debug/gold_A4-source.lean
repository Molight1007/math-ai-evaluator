import Mathlib.Tactic

example (a b : ℝ) : |a + b| ≤ |a| + |b| := by
  exact abs_add a b
