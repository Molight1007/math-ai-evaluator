import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (f : ℕ+ → ℕ+) (h : ∀ n m : ℕ+, f (f n + f m) = n + m) : Function.Injective f := by
  intro n m
  intro h_eq
  have h1 := h n m
  aesop
#eval "MARK_153"

