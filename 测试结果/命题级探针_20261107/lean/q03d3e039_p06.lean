import Mathlib.Tactic

example (x y z : ℝ) (h : ∃! v : {x, y, z}, v ^ 2 = 3 ∧ ∀ w : {x, y, z}, w ≠ v → w = 0) :
  x * y ^ 3 + y * z ^ 3 + z * x ^ 3 = 0 := by sorry
