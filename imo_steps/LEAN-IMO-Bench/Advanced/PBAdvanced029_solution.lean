import Mathlib
open scoped BigOperators

theorem helper_odd (k : ℕ) (hk : ¬ Even k)
  (h : ∀ n > (0 : ℕ), ∃ (m : ℕ), 1 / (n + 1 : ℚ) * ∑ i ∈ Finset.range (n + 1), n.choose i ^ k = m) :
  False :=
by
  -- Use the correct Mathlib theorem name and extract the algebraic form of the odd number
  have hk_odd : Odd k := Nat.not_even_iff_odd.mp hk
  obtain ⟨c, hc⟩ := hk_odd
  have hk_eq : k = 2 * c + 1 := hc

  -- Specialize the hypothesis to n = 2
  obtain ⟨m, hm⟩ := h 2 (by norm_num)

  -- Evaluate the sum strictly in the natural numbers to avoid coercion mismatches
  have h_sum_nat : ∑ i ∈ Finset.range (2 + 1), Nat.choose 2 i ^ k = 2 + 2 ^ k := by
    rw [Finset.sum_range_succ, Finset.sum_range_succ, Finset.sum_range_succ, Finset.sum_range_zero]
    rw [zero_add]
    have h0 : Nat.choose 2 0 = 1 := rfl
    have h1 : Nat.choose 2 1 = 2 := rfl
    have h2 : Nat.choose 2 2 = 1 := rfl
    rw [h0, h1, h2]
    rw [one_pow]
    ring

  -- Rewrite the sum in the main hypothesis
  rw [h_sum_nat] at hm

  -- Reframe equation back cleanly to ℚ
  have hm_cast : ((2 + 2 ^ k : ℕ) : ℚ) = ((3 * m : ℕ) : ℚ) := by
    calc ((2 + 2 ^ k : ℕ) : ℚ) = (3 : ℚ) * (1 / (((2 : ℕ) : ℚ) + 1) * ((2 + 2 ^ k : ℕ) : ℚ)) := by
          have : 1 / (((2 : ℕ) : ℚ) + 1) = 1 / (3 : ℚ) := by norm_num
          rw [this]
          ring
      _ = (3 : ℚ) * (m : ℚ) := by rw [hm]
      _ = ((3 * m : ℕ) : ℚ) := by push_cast; ring

  -- Cast down into Natural numbers seamlessly
  have hm_nat : 2 + 2 ^ k = 3 * m := by
    exact_mod_cast hm_cast

  -- Map the algebraic equality into ZMod 3 to deduce a quick contradiction
  have h_zmod : ((2 + 2 ^ k : ℕ) : ZMod 3) = ((3 * m : ℕ) : ZMod 3) := by
    exact congrArg (fun x : ℕ => (x : ZMod 3)) hm_nat

  -- Simplify the left hand side in modulo arithmetic utilizing k = 2*c + 1
  have h_lhs : ((2 + 2 ^ k : ℕ) : ZMod 3) = (1 : ZMod 3) := by
    push_cast
    rw [hk_eq]
    have h_pow : (2 : ZMod 3) ^ (2 * c + 1) = (2 : ZMod 3) := by
      calc (2 : ZMod 3) ^ (2 * c + 1) = (2 : ZMod 3) ^ (2 * c) * (2 : ZMod 3) ^ 1 := by rw [pow_add]
        _ = ((2 : ZMod 3) ^ 2) ^ c * (2 : ZMod 3) := by rw [pow_mul, pow_one]
        _ = (1 : ZMod 3) ^ c * (2 : ZMod 3) := by
          -- Replaced norm_num with explicitly computed kernel evaluation via `rfl`
          have h_sq : (2 : ZMod 3) ^ 2 = (1 : ZMod 3) := by
            calc (2 : ZMod 3) ^ 2 = (2 : ZMod 3) * (2 : ZMod 3) := by ring
              _ = (1 : ZMod 3) := rfl
          rw [h_sq]
        _ = (1 : ZMod 3) * (2 : ZMod 3) := by rw [one_pow]
        _ = (2 : ZMod 3) := by ring
    rw [h_pow]
    -- 2 + 2 is identically computed to 1 in ZMod 3
    exact rfl

  -- Simplify the right hand side in modulo arithmetic
  have h_rhs : ((3 * m : ℕ) : ZMod 3) = (0 : ZMod 3) := by
    push_cast
    have h3 : (3 : ZMod 3) = (0 : ZMod 3) := rfl
    rw [h3]
    ring

  -- Replace values to reveal 1 = 0 in ZMod 3
  rw [h_lhs, h_rhs] at h_zmod

  -- The contradiction strictly follows as 1 ≠ 0
  exact one_ne_zero h_zmod

theorem choose_pow_sub_dvd (k n j : ℕ) (hk : Even k) :
  (((n + 1).choose (j + 1) : ℕ) : ℤ) ∣
    ((n.choose (j + 1) : ℕ) : ℤ) ^ k - ((n.choose j : ℕ) : ℤ) ^ k :=
by
  obtain ⟨m, hm⟩ := hk
  have h_choose : (((n + 1).choose (j + 1) : ℕ) : ℤ) = ((n.choose (j + 1) : ℕ) : ℤ) + ((n.choose j : ℕ) : ℤ) := by
    rw [Nat.choose_succ_succ n j]
    push_cast
    ring
  rw [h_choose]
  have h1 : ((n.choose (j + 1) : ℕ) : ℤ) + ((n.choose j : ℕ) : ℤ) ∣ ((n.choose (j + 1) : ℕ) : ℤ) ^ 2 - ((n.choose j : ℕ) : ℤ) ^ 2 := by
    use ((n.choose (j + 1) : ℕ) : ℤ) - ((n.choose j : ℕ) : ℤ)
    ring
  have h2 : ((n.choose (j + 1) : ℕ) : ℤ) ^ 2 - ((n.choose j : ℕ) : ℤ) ^ 2 ∣ ((n.choose (j + 1) : ℕ) : ℤ) ^ k - ((n.choose j : ℕ) : ℤ) ^ k := by
    have hp : ((n.choose (j + 1) : ℕ) : ℤ) ^ k - ((n.choose j : ℕ) : ℤ) ^ k = (((n.choose (j + 1) : ℕ) : ℤ) ^ 2) ^ m - (((n.choose j : ℕ) : ℤ) ^ 2) ^ m := by
      rw [hm]
      ring
    rw [hp]
    exact sub_dvd_pow_sub_pow (((n.choose (j + 1) : ℕ) : ℤ) ^ 2) (((n.choose j : ℕ) : ℤ) ^ 2) m
  exact dvd_trans h1 h2

theorem succ_mul_choose_pow_sub_dvd (k n j : ℕ) (hk : Even k) :
  (n + 1 : ℤ) ∣
    (j + 1 : ℤ) * (((n.choose (j + 1) : ℕ) : ℤ) ^ k - ((n.choose j : ℕ) : ℤ) ^ k) :=
by
  have h_pow : (-((n.choose j : ℕ) : ℤ)) ^ k = ((n.choose j : ℕ) : ℤ) ^ k := by
    obtain ⟨m, hm⟩ := hk
    have hk_eq : k = 2 * m := by omega
    rw [hk_eq, pow_mul, pow_mul]
    have : (-((n.choose j : ℕ) : ℤ)) ^ 2 = ((n.choose j : ℕ) : ℤ) ^ 2 := by ring
    rw [this]

  have h1 : ((n.choose (j + 1) : ℕ) : ℤ) - (-((n.choose j : ℕ) : ℤ)) ∣ ((n.choose (j + 1) : ℕ) : ℤ) ^ k - (-((n.choose j : ℕ) : ℤ)) ^ k :=
    sub_dvd_pow_sub_pow ((n.choose (j + 1) : ℕ) : ℤ) (-((n.choose j : ℕ) : ℤ)) k

  have h2 : ((n.choose (j + 1) : ℕ) : ℤ) - (-((n.choose j : ℕ) : ℤ)) = (((n + 1).choose (j + 1) : ℕ) : ℤ) := by
    have h_nat : n.choose (j + 1) + n.choose j = (n + 1).choose (j + 1) := by
      rw [add_comm]
      rfl
    calc ((n.choose (j + 1) : ℕ) : ℤ) - (-((n.choose j : ℕ) : ℤ))
      _ = ((n.choose (j + 1) : ℕ) : ℤ) + ((n.choose j : ℕ) : ℤ) := by ring
      _ = ((n.choose (j + 1) + n.choose j : ℕ) : ℤ) := by push_cast; rfl
      _ = (((n + 1).choose (j + 1) : ℕ) : ℤ) := by rw [h_nat]

  have h3 : ((n.choose (j + 1) : ℕ) : ℤ) ^ k - (-((n.choose j : ℕ) : ℤ)) ^ k = ((n.choose (j + 1) : ℕ) : ℤ) ^ k - ((n.choose j : ℕ) : ℤ) ^ k := by
    rw [h_pow]

  rw [h2, h3] at h1
  obtain ⟨C, hC⟩ := h1

  have h4 : (j + 1 : ℤ) * (((n + 1).choose (j + 1) : ℕ) : ℤ) = (n + 1 : ℤ) * ((n.choose j : ℕ) : ℤ) := by
    have h_nat := Nat.add_one_mul_choose_eq n j
    calc (j + 1 : ℤ) * (((n + 1).choose (j + 1) : ℕ) : ℤ)
      _ = (((n + 1).choose (j + 1) : ℕ) : ℤ) * (j + 1 : ℤ) := mul_comm _ _
      _ = (((n + 1).choose (j + 1) * (j + 1) : ℕ) : ℤ) := by push_cast; rfl
      _ = (((n + 1) * n.choose j : ℕ) : ℤ) := by rw [← h_nat]
      _ = (n + 1 : ℤ) * ((n.choose j : ℕ) : ℤ) := by push_cast; rfl

  rw [hC]
  have h5 : (j + 1 : ℤ) * ((((n + 1).choose (j + 1) : ℕ) : ℤ) * C) = (n + 1 : ℤ) * (((n.choose j : ℕ) : ℤ) * C) := by
    calc (j + 1 : ℤ) * ((((n + 1).choose (j + 1) : ℕ) : ℤ) * C)
      _ = ((j + 1 : ℤ) * (((n + 1).choose (j + 1) : ℕ) : ℤ)) * C := by rw [mul_assoc]
      _ = ((n + 1 : ℤ) * ((n.choose j : ℕ) : ℤ)) * C := by rw [h4]
      _ = (n + 1 : ℤ) * (((n.choose j : ℕ) : ℤ) * C) := by rw [mul_assoc]
  rw [h5]
  exact dvd_mul_right (n + 1 : ℤ) (((n.choose j : ℕ) : ℤ) * C)

theorem sum_choose_pow_eq (k n : ℕ) :
  (∑ i ∈ Finset.range (n + 1), ((n.choose i : ℕ) : ℤ) ^ k) =
    (n + 1 : ℤ) - ∑ j ∈ Finset.range n, (j + 1 : ℤ) * (((n.choose (j + 1) : ℕ) : ℤ) ^ k - ((n.choose j : ℕ) : ℤ) ^ k) :=
by
  let A (i : ℕ) : ℤ := ((n.choose i : ℕ) : ℤ) ^ k
  let f (i : ℕ) : ℤ := (i : ℤ) * A i

  have h_An : A n = 1 := by
    dsimp [A]
    rw [Nat.choose_self]
    simp

  have h_f0 : f 0 = 0 := by
    dsimp [f]
    simp

  have h_fn : f n = (n : ℤ) := by
    dsimp [f]
    rw [h_An]
    ring

  have h_f_diff : ∀ j : ℕ, (j + 1 : ℤ) * (A (j + 1) - A j) = (f (j + 1) - f j) - A j := by
    intro j
    dsimp [f]
    push_cast
    ring

  have h_succ_eq : ∑ x ∈ Finset.range n, f (x + 1) = ∑ x ∈ Finset.range (n + 1), f x := by
    rw [Finset.sum_range_succ', h_f0, add_zero]

  have h_telescope : ∑ x ∈ Finset.range n, (f (x + 1) - f x) = (n : ℤ) := by
    calc ∑ x ∈ Finset.range n, (f (x + 1) - f x)
      _ = (∑ x ∈ Finset.range n, f (x + 1)) - ∑ x ∈ Finset.range n, f x := by rw [Finset.sum_sub_distrib]
      _ = (∑ x ∈ Finset.range (n + 1), f x) - ∑ x ∈ Finset.range n, f x := by rw [h_succ_eq]
      _ = ((∑ x ∈ Finset.range n, f x) + f n) - ∑ x ∈ Finset.range n, f x := by rw [Finset.sum_range_succ]
      _ = f n := by ring
      _ = (n : ℤ) := h_fn

  have h_sum : ∑ j ∈ Finset.range n, (j + 1 : ℤ) * (A (j + 1) - A j) = (n : ℤ) - ∑ j ∈ Finset.range n, A j := by
    calc ∑ j ∈ Finset.range n, (j + 1 : ℤ) * (A (j + 1) - A j)
      _ = ∑ j ∈ Finset.range n, ((f (j + 1) - f j) - A j) := by
        apply Finset.sum_congr rfl
        intro j _
        exact h_f_diff j
      _ = (∑ j ∈ Finset.range n, (f (j + 1) - f j)) - ∑ j ∈ Finset.range n, A j := by rw [Finset.sum_sub_distrib]
      _ = (n : ℤ) - ∑ j ∈ Finset.range n, A j := by rw [h_telescope]

  calc ∑ i ∈ Finset.range (n + 1), ((n.choose i : ℕ) : ℤ) ^ k
    _ = ∑ i ∈ Finset.range (n + 1), A i := rfl
    _ = (∑ i ∈ Finset.range n, A i) + A n := by rw [Finset.sum_range_succ]
    _ = (∑ i ∈ Finset.range n, A i) + 1 := by rw [h_An]
    _ = (n + 1 : ℤ) - ((n : ℤ) - ∑ i ∈ Finset.range n, A i) := by ring
    _ = (n + 1 : ℤ) - ∑ j ∈ Finset.range n, (j + 1 : ℤ) * (A (j + 1) - A j) := by rw [← h_sum]
    _ = (n + 1 : ℤ) - ∑ j ∈ Finset.range n, (j + 1 : ℤ) * (((n.choose (j + 1) : ℕ) : ℤ) ^ k - ((n.choose j : ℕ) : ℤ) ^ k) := rfl

theorem sum_choose_pow_even_dvd (k n : ℕ) (hk : Even k) :
  (n + 1) ∣ ∑ i ∈ Finset.range (n + 1), n.choose i ^ k :=
by
  suffices H : (n + 1 : ℤ) ∣ ∑ i ∈ Finset.range (n + 1), ((n.choose i : ℕ) : ℤ) ^ k by
    exact_mod_cast H
  rw [sum_choose_pow_eq k n]
  apply _root_.dvd_sub
  · exact dvd_rfl
  · apply Finset.dvd_sum
    intro j _
    exact succ_mul_choose_pow_sub_dvd k n j hk

theorem helper_even_cast {n S x : ℕ} (hn : n > (0 : ℕ)) (hx : S = (n + 1) * x) :
  1 / (n + 1 : ℚ) * S = x :=
by
  have h_ne : (n + 1 : ℚ) ≠ 0 := by positivity
  field_simp [h_ne]
  rw [hx]
  push_cast
  ring

theorem helper_even (k : ℕ) (hk : Even k) (n : ℕ) (hn : n > (0 : ℕ)) :
  ∃ (m : ℕ), 1 / (n + 1 : ℚ) * ∑ i ∈ Finset.range (n + 1), n.choose i ^ k = m :=
by
  -- 1. Extract the existential multiple from the divisibility property
  obtain ⟨m, hm⟩ := sum_choose_pow_even_dvd k n hk

  -- 2. Provide the integer witness and perfectly match the algebraic helper
  exact ⟨m, helper_even_cast hn hm⟩

theorem PBAdvanced029 : {(k : ℕ) | 0 < k ∧ ∀ n > (0 : ℕ), ∃ (m : ℕ),
      1 / (n + 1 : ℚ) * ∑ i ∈ Finset.range (n + 1), n.choose i ^ k = m }
    = {(k : ℕ) | 0 < k ∧ Even k} :=
by
  -- Convert set equality to logical equivalence for elements.
  ext k
  simp only [Set.mem_setOf_eq]
  constructor
  · -- Left-to-Right: Assume k > 0 and the property holds. Prove Even k.
    rintro ⟨hk0, h⟩
    refine ⟨hk0, ?_⟩
    -- Proceed by contradiction; assume k is NOT even, and leverage `helper_odd` to reach `False`.
    by_contra h_odd
    exact helper_odd k h_odd h
  · -- Right-to-Left: Assume k > 0 and Even k. Prove the sum property.
    rintro ⟨hk0, hk_even⟩
    refine ⟨hk0, fun n hn => helper_even k hk_even n hn⟩
