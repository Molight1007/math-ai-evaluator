import Mathlib.Tactic
set_option autoImplicit false

example (a : ℤ) (ha : a ≠ 2) : (∃ d : ℤ, d * d = D) ↔ (∃ k : ℤ, k * k = 4 * a + 1) := by sorry
