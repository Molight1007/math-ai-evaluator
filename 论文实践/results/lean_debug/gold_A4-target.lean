import Mathlib.Tactic

example (a b c : ℝ) : |a + b + c| ≤ |a| + |b| + |c| := by
  have h1 : |a + b + c| ≤ |a + b| + |c| := by
    simpa [add_assoc] using abs_add (a + b) c
  have h2 : |a + b| ≤ |a| + |b| := abs_add a b
  linarith
