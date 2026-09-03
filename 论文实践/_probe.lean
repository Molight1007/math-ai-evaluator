import Mathlib.Tactic
example : (2:ℝ) + 2 = 4 := by norm_num
example (x : ℝ) : x + 0 = x := by ring
