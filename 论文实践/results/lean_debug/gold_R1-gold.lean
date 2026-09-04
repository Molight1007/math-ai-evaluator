import Mathlib.Tactic

example (n : ℕ) : (∑ i in Finset.range n, (2 * i + 1)) = n^2 := by
  induction n with
  | zero => simp
  | succ n ih =>
      rw [Finset.sum_range_succ]
      rw [ih]
      ring
