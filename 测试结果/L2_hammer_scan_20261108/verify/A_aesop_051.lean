import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (f : ℕ+ → ℕ+) (h : ∀ n m : ℕ+, f (f n + f m) = n + m) : Function.Injective f := by
  intro a b
  intro h_eq
  have h1 := h a a
  have h2 := h a b
  aesop
#eval "MARK_51"

