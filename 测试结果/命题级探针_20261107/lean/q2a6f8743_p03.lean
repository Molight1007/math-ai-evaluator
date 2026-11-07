import Mathlib.Tactic

example (a : ℕ) (ha : 0 < a) : (∃ b : ℕ, 0 < b ∧ b^2 + a * b + (7*a^2 - (a+1)^3) = 0) ↔ (∃ k : ℕ, k^2 = 4*a^3 - 15*a^2 + 12*a + 4) := by sorry
