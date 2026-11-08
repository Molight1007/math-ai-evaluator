import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example : ¬ ∃ (x y z : ℝ), x ≠ y ∧ y ≠ z ∧ z ≠ x ∧ x^2 + y^2 + z^2 = 3 ∧ x*y^3 + y*z^3 + z*x^3 = 3 := by
  intro h
#eval "MARK_0"
