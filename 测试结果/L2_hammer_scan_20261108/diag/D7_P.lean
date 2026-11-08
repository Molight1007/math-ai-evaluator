import Mathlib.Tactic
set_option maxErrors 1000000

example (x y z : ℝ) (hx : 0 < x) (hy : 0 < y) (hz : 0 < z) (hxy : y ≤ x) (hyz : z ≤ y) (h1 : x^2 + y^2 + z^2 = 3) (h2 : x*y^3 + y*z^3 + z*x^3 = 3) : x = 1 ∧ y = 1 ∧ z = 1 := by
  have h3 : x = 1 := by
  have := calc x ^ 2 ≤ x * y ^ 2 := by
    have := pow_le_pow hxy 2
    nlinarith
  ... ≤ x * y * z := by
    have := mul_le_mul_left hyz y
    nlinarith
  ... ≤ z * x ^ 2 := by
    have := mul_le_mul_left hxy z
    nlinarith
  ... ≤ x ^ 2 := by
    have := pow_le_pow hyz 2
    nlinarith
  exact le_antisymm this (le_of_eq h1.symm)
