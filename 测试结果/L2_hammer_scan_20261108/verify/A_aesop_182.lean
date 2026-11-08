import Mathlib.Tactic

set_option maxHeartbeats 200000 in
example (y : ℕ → ℝ) (h : ∀ n, 0 ≤ y n ∧ y n ≤ 777^2) : ∃ (s : Set ℕ), Infinite s ∧ (∀ i ∈ s, 0 ≤ y i ∧ y i ≤ 777^2/2) ∨ (∀ i ∈ s, 777^2/2 < y i ∧ y i ≤ 777^2) := by
  use {i : ℕ | y i ≤ 777 ^ 2 / 2}
  left
  constructor
  apply Set.infinite_of_unbounded_forall_nat
  aesop
#eval "MARK_182"

