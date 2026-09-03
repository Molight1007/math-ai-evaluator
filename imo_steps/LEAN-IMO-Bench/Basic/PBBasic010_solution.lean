import Mathlib

theorem PBBasic010 (A B : Finset ℕ) (hdisj : Disjoint A B) (hunion : A ∪ B = Finset.Icc 1 2022)
    (ha : A.card = 1011) (hb : B.card = 1011) : ∑ a ∈ A, ∑ b ∈ B, (b - a : ℕ) ≠
    ∑ a ∈ A, ∑ b ∈ B, (a - b : ℕ) :=
by
  intro h_eq

  -- Helper 1: The difference of truncating subtractions is standard integer subtraction
  have h1 : ∑ a ∈ A, ∑ b ∈ B, (((b - a : ℕ) : ℤ) - ((a - b : ℕ) : ℤ)) = ∑ a ∈ A, ∑ b ∈ B, ((b : ℤ) - (a : ℤ)) := by
    apply Finset.sum_congr rfl
    intro a _
    apply Finset.sum_congr rfl
    intro b _
    omega

  -- Cast the assumption to integers effortlessly
  have h_eq_Z : ∑ a ∈ A, ∑ b ∈ B, ((b - a : ℕ) : ℤ) = ∑ a ∈ A, ∑ b ∈ B, ((a - b : ℕ) : ℤ) := by
    exact_mod_cast h_eq

  -- Show that the double sum of differences is 0 by applying distributive laws recursively
  have h4 : ∑ a ∈ A, ∑ b ∈ B, ((b : ℤ) - (a : ℤ)) = 0 := by
    rw [← h1]
    simp_rw [Finset.sum_sub_distrib]
    rw [h_eq_Z, sub_self]

  -- Expand the sum in terms of A and B cardinalities
  have h5 : ∑ a ∈ A, ∑ b ∈ B, ((b : ℤ) - (a : ℤ)) = 1011 * ∑ x ∈ B, (x : ℤ) - 1011 * ∑ x ∈ A, (x : ℤ) := by
    simp_rw [Finset.sum_sub_distrib]
    have h_b : ∑ a ∈ A, ∑ b ∈ B, (b : ℤ) = 1011 * ∑ x ∈ B, (x : ℤ) := by
      rw [Finset.sum_comm]
      have : ∀ b ∈ B, ∑ a ∈ A, (b : ℤ) = (1011 : ℤ) * (b : ℤ) := by
        intro b _
        rw [Finset.sum_const, ha, nsmul_eq_mul]
        push_cast
        rfl
      rw [Finset.sum_congr rfl this, ← Finset.mul_sum]
    have h_a : ∑ a ∈ A, ∑ b ∈ B, (a : ℤ) = 1011 * ∑ x ∈ A, (x : ℤ) := by
      have : ∀ a ∈ A, ∑ b ∈ B, (a : ℤ) = (1011 : ℤ) * (a : ℤ) := by
        intro a _
        rw [Finset.sum_const, hb, nsmul_eq_mul]
        push_cast
        rfl
      rw [Finset.sum_congr rfl this, ← Finset.mul_sum]
    rw [h_b, h_a]

  -- Deduce the sums of A and B are equal
  have h7 : ∑ x ∈ B, (x : ℤ) = ∑ x ∈ A, (x : ℤ) := by
    have h_mul : (1011 : ℤ) * (∑ x ∈ B, (x : ℤ) - ∑ x ∈ A, (x : ℤ)) = 0 := by
      calc (1011 : ℤ) * (∑ x ∈ B, (x : ℤ) - ∑ x ∈ A, (x : ℤ))
        _ = (1011 : ℤ) * ∑ x ∈ B, (x : ℤ) - (1011 : ℤ) * ∑ x ∈ A, (x : ℤ) := by rw [mul_sub]
        _ = ∑ a ∈ A, ∑ b ∈ B, ((b : ℤ) - (a : ℤ)) := h5.symm
        _ = 0 := h4
    have h_non_zero : (1011 : ℤ) ≠ 0 := by norm_num
    have h_or := mul_eq_zero.mp h_mul
    cases h_or with
    | inl h => exact False.elim (h_non_zero h)
    | inr h => exact sub_eq_zero.mp h

  -- Sum of A ∪ B
  have h8 : ∑ x ∈ A ∪ B, (x : ℤ) = ∑ x ∈ A, (x : ℤ) + ∑ x ∈ B, (x : ℤ) := by
    exact Finset.sum_union hdisj

  have h9 : ∑ x ∈ A ∪ B, (x : ℤ) = 2 * ∑ x ∈ A, (x : ℤ) := by
    calc
      ∑ x ∈ A ∪ B, (x : ℤ) = ∑ x ∈ A, (x : ℤ) + ∑ x ∈ B, (x : ℤ) := h8
      _ = ∑ x ∈ A, (x : ℤ) + ∑ x ∈ A, (x : ℤ) := by rw [h7]
      _ = 2 * ∑ x ∈ A, (x : ℤ) := by ring

  -- Compute sum of the arithmetic progression from 1 to n (Avoid omega limitation by safely using algebraic `ring`)
  have h_sum_form : ∀ n : ℕ, 2 * ∑ x ∈ Finset.Ico 1 (n + 1), (x : ℤ) = (n : ℤ) * ((n : ℤ) + 1) := by
    intro n
    induction n with
    | zero =>
      have h_empty : Finset.Ico 1 (0 + 1) = ∅ := by
        ext x
        constructor
        · intro h
          rw [Finset.mem_Ico] at h
          omega
        · intro h
          exact False.elim (Finset.notMem_empty x h)
      rw [h_empty, Finset.sum_empty]
      norm_num
    | succ k ih =>
      have hk : 1 ≤ k + 1 := by omega
      rw [Finset.sum_Ico_succ_top hk]
      rw [mul_add]
      rw [ih]
      push_cast
      ring

  -- Rewrite safe Icc to strictly inclusive Ico equivalence
  have hIcc : Finset.Icc 1 2022 = Finset.Ico 1 (2022 + 1) := by
    ext x
    constructor
    · intro h
      rw [Finset.mem_Ico]
      rw [Finset.mem_Icc] at h
      omega
    · intro h
      rw [Finset.mem_Icc]
      rw [Finset.mem_Ico] at h
      omega

  -- Conclude the contradiction: generalization ensures `omega` treats it explicitly as integer algebra
  have h_contra : 4 * ∑ x ∈ A, (x : ℤ) = 4090506 := by
    have eq1 : 4 * ∑ x ∈ A, (x : ℤ) = 2 * (2 * ∑ x ∈ A, (x : ℤ)) := by ring
    rw [eq1]
    rw [← h9]
    rw [hunion]
    rw [hIcc]
    rw [h_sum_form 2022]
    norm_num

  -- Extract the sum cleanly into an integer variable S so omega can effortlessly prove contradiction natively in ℤ
  have ⟨S, hS⟩ : ∃ S : ℤ, 4 * S = 4090506 := ⟨∑ x ∈ A, (x : ℤ), h_contra⟩
  omega
