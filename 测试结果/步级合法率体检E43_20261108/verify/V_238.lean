import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (x y z : ℝ) (hx : 0 < x) (hy : 0 < y) (hz : 0 < z) (hxy : y ≤ x) (hyz : z ≤ y) (h1 : x^2 + y^2 + z^2 = 3) (h2 : x*y^3 + y*z^3 + z*x^3 = 3) : x = 1 ∧ y = 1 ∧ z = 1 := by
  have h3 : (x - 1)^2 + (y - 1)^2 + (z - 1)^2 = 0 := by
  ring
  rw [h1]
  norm_num
#eval "MARK_238"
