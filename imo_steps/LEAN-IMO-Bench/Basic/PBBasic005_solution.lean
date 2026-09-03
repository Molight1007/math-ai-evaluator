import Mathlib
open Polynomial
noncomputable def D_poly (N k : ℕ) : ℝ[X] :=
  X ^ (N + k) + X ^ (N - k) - C ((1 : ℝ) / 2) * X ^ (N - k) * ((X ^ 2 + 1) ^ k + (X ^ 2 - 1) ^ k)

-- Step 1: Establish the degree bound from the functional property unconditionally.

theorem poly_cases {P : ℝ[X]} (hM : P.Monic) (h_deg : P.natDegree ≤ 4)
  (h3 : P.coeff 3 = 0) (h1 : P.coeff 1 = 0) (h0 : P.coeff 0 = (6 : ℝ) * P.coeff 4) :
  P ∈ {X ^ 4 + a • X ^ 2 + 6 | (a : ℝ)} ∪ {X ^ 2} :=
by
  have h_deg' : P.natDegree = 0 ∨ P.natDegree = 1 ∨ P.natDegree = 2 ∨ P.natDegree = 3 ∨ P.natDegree = 4 := by omega
  have h_lead : P.coeff P.natDegree = 1 := hM
  rcases h_deg' with hd | hd | hd | hd | hd
  · have hM0 : P.coeff 0 = 1 := by
      have h_lead_copy := h_lead
      rw [hd] at h_lead_copy
      exact h_lead_copy
    have hc4 : P.coeff 4 = 0 := Polynomial.coeff_eq_zero_of_natDegree_lt (by omega)
    rw [hc4, mul_zero] at h0
    rw [hM0] at h0
    linarith
  · have hM1 : P.coeff 1 = 1 := by
      have h_lead_copy := h_lead
      rw [hd] at h_lead_copy
      exact h_lead_copy
    rw [h1] at hM1
    linarith
  · right
    have hM2 : P.coeff 2 = 1 := by
      have h_lead_copy := h_lead
      rw [hd] at h_lead_copy
      exact h_lead_copy
    have hc4 : P.coeff 4 = 0 := Polynomial.coeff_eq_zero_of_natDegree_lt (by omega)
    have hc0 : P.coeff 0 = 0 := by
      rw [hc4, mul_zero] at h0
      exact h0
    ext m
    rcases m with _ | _ | _ | m
    · have h_lhs : P.coeff 0 = 0 := hc0
      rw [h_lhs]
      simp [Polynomial.coeff_X_pow, smul_eq_mul] <;> try ring <;> try norm_num
    · have h_lhs : P.coeff 1 = 0 := h1
      rw [h_lhs]
      simp [Polynomial.coeff_X_pow, smul_eq_mul] <;> try ring <;> try norm_num
    · have h_lhs : P.coeff 2 = 1 := hM2
      rw [h_lhs]
      simp [Polynomial.coeff_X_pow, smul_eq_mul] <;> try ring <;> try norm_num
    · have h_lhs : P.coeff (m + 3) = 0 := Polynomial.coeff_eq_zero_of_natDegree_lt (by omega)
      rw [h_lhs]
      have h_ne2 : 2 ≠ m + 3 := by omega
      have h_ne2' : m + 3 ≠ 2 := by omega
      simp [Polynomial.coeff_X_pow, smul_eq_mul, h_ne2, h_ne2'] <;> try ring <;> try norm_num
  · have hM3 : P.coeff 3 = 1 := by
      have h_lead_copy := h_lead
      rw [hd] at h_lead_copy
      exact h_lead_copy
    rw [h3] at hM3
    linarith
  · left
    use P.coeff 2
    have hM4 : P.coeff 4 = 1 := by
      have h_lead_copy := h_lead
      rw [hd] at h_lead_copy
      exact h_lead_copy
    have hc0 : P.coeff 0 = 6 := by
      rw [hM4] at h0
      linarith
    ext m
    rcases m with _ | _ | _ | _ | _ | m
    · have h_lhs : P.coeff 0 = 6 := hc0
      rw [h_lhs]
      simp [Polynomial.coeff_X_pow, smul_eq_mul] <;> try ring <;> try norm_num
    · have h_lhs : P.coeff 1 = 0 := h1
      rw [h_lhs]
      simp [Polynomial.coeff_X_pow, smul_eq_mul] <;> try ring <;> try norm_num
    · simp [Polynomial.coeff_X_pow, smul_eq_mul] <;> try ring <;> try norm_num
    · have h_lhs : P.coeff 3 = 0 := h3
      rw [h_lhs]
      simp [Polynomial.coeff_X_pow, smul_eq_mul] <;> try ring <;> try norm_num
    · have h_lhs : P.coeff 4 = 1 := hM4
      rw [h_lhs]
      simp [Polynomial.coeff_X_pow, smul_eq_mul] <;> try ring <;> try norm_num
    · have h_lhs : P.coeff (m + 5) = 0 := Polynomial.coeff_eq_zero_of_natDegree_lt (by omega)
      rw [h_lhs]
      have h_ne4 : 4 ≠ m + 5 := by omega
      have h_ne4' : m + 5 ≠ 4 := by omega
      have h_ne2 : 2 ≠ m + 5 := by omega
      have h_ne2' : m + 5 ≠ 2 := by omega
      have h_ne0 : 0 ≠ m + 5 := by omega
      have h_ne0' : m + 5 ≠ 0 := by omega
      simp [Polynomial.coeff_X_pow, smul_eq_mul, h_ne4, h_ne4', h_ne2, h_ne2', h_ne0, h_ne0'] <;> try ring <;> try norm_num

theorem coeff_D_poly_lt_eq_zero (m k : ℕ) (hk : k < m + 5) :
  (D_poly (m + 5) k).coeff (2 * m + 6) = 0 :=
by
  have h_add_pow1 : (X ^ 2 + 1 : ℝ[X]) ^ k = ∑ i ∈ Finset.range (k + 1), (k.choose i : ℝ[X]) * X ^ (2 * i) := by
    rw [add_pow]
    apply Finset.sum_congr rfl
    intro i _
    simp only [one_pow, mul_one]
    rw [← pow_mul]
    ring
  have h_add_pow2 : (X ^ 2 - 1 : ℝ[X]) ^ k = ∑ i ∈ Finset.range (k + 1), (k.choose i : ℝ[X]) * X ^ (2 * i) * (-1 : ℝ[X]) ^ (k - i) := by
    have h_eq : (X ^ 2 - 1 : ℝ[X]) = X ^ 2 + (-1 : ℝ[X]) := by ring
    rw [h_eq, add_pow]
    apply Finset.sum_congr rfl
    intro i _
    rw [← pow_mul]
    ring
  have h_sum : (X ^ 2 + 1 : ℝ[X]) ^ k + (X ^ 2 - 1 : ℝ[X]) ^ k =
      ∑ i ∈ Finset.range (k + 1), (k.choose i : ℝ[X]) * X ^ (2 * i) * (1 + (-1 : ℝ[X]) ^ (k - i)) := by
    rw [h_add_pow1, h_add_pow2, ← Finset.sum_add_distrib]
    apply Finset.sum_congr rfl
    intro i _
    ring
  have h_mul : C (1 / 2 : ℝ) * X ^ (m + 5 - k) * ((X ^ 2 + 1 : ℝ[X]) ^ k + (X ^ 2 - 1 : ℝ[X]) ^ k) =
      ∑ i ∈ Finset.range (k + 1), C ((1 / 2 : ℝ) * (k.choose i : ℝ) * (1 + (-1 : ℝ) ^ (k - i))) * X ^ (m + 5 - k + 2 * i) := by
    rw [h_sum, Finset.mul_sum]
    apply Finset.sum_congr rfl
    intro i _
    have hc : C (1 / 2 : ℝ) * (k.choose i : ℝ[X]) * (1 + (-1 : ℝ[X]) ^ (k - i)) =
        C ((1 / 2 : ℝ) * (k.choose i : ℝ) * (1 + (-1 : ℝ) ^ (k - i))) := by
      simp only [map_mul, map_add, map_pow, map_one, map_neg, map_natCast]
    calc C (1 / 2 : ℝ) * X ^ (m + 5 - k) * ((k.choose i : ℝ[X]) * X ^ (2 * i) * (1 + (-1 : ℝ[X]) ^ (k - i)))
      _ = (C (1 / 2 : ℝ) * (k.choose i : ℝ[X]) * (1 + (-1 : ℝ[X]) ^ (k - i))) * (X ^ (m + 5 - k) * X ^ (2 * i)) := by ring
      _ = C ((1 / 2 : ℝ) * (k.choose i : ℝ) * (1 + (-1 : ℝ) ^ (k - i))) * (X ^ (m + 5 - k) * X ^ (2 * i)) := by rw [hc]
      _ = C ((1 / 2 : ℝ) * (k.choose i : ℝ) * (1 + (-1 : ℝ) ^ (k - i))) * X ^ (m + 5 - k + 2 * i) := by rw [pow_add]
  have h_sum_split : ∑ i ∈ Finset.range (k + 1), C ((1 / 2 : ℝ) * (k.choose i : ℝ) * (1 + (-1 : ℝ) ^ (k - i))) * X ^ (m + 5 - k + 2 * i) =
      (∑ i ∈ Finset.range k, C ((1 / 2 : ℝ) * (k.choose i : ℝ) * (1 + (-1 : ℝ) ^ (k - i))) * X ^ (m + 5 - k + 2 * i)) + X ^ (m + 5 + k) := by
    rw [Finset.sum_range_succ]
    congr 1
    have h_exp : m + 5 - k + 2 * k = m + 5 + k := by omega
    have h_choose : (k.choose k : ℝ) = 1 := by rw [Nat.choose_self, Nat.cast_one]
    have h_pow : (-1 : ℝ) ^ (k - k) = 1 := by rw [Nat.sub_self, pow_zero]
    rw [h_exp, h_choose, h_pow]
    have : C ((1 / 2 : ℝ) * 1 * (1 + 1)) = 1 := by
      have h_in : (1 / 2 : ℝ) * 1 * (1 + 1) = 1 := by ring
      rw [h_in, map_one]
    rw [this, one_mul]
  have h_D_poly : D_poly (m + 5) k = X ^ (m + 5 - k) - ∑ i ∈ Finset.range k, C ((1 / 2 : ℝ) * (k.choose i : ℝ) * (1 + (-1 : ℝ) ^ (k - i))) * X ^ (m + 5 - k + 2 * i) := by
    unfold D_poly
    rw [h_mul, h_sum_split]
    ring
  rw [h_D_poly, Polynomial.coeff_sub, Polynomial.finset_sum_coeff]
  have h_X_pow : (X ^ (m + 5 - k) : ℝ[X]).coeff (2 * m + 6) = 0 := by
    rw [Polynomial.coeff_X_pow]
    split_ifs with h
    · exfalso; omega
    · rfl
  have h_sum_zero : (∑ i ∈ Finset.range k, (C ((1 / 2 : ℝ) * (k.choose i : ℝ) * (1 + (-1 : ℝ) ^ (k - i))) * X ^ (m + 5 - k + 2 * i)).coeff (2 * m + 6)) = 0 := by
    apply Finset.sum_eq_zero
    intro i hi
    have hi_lt : i < k := Finset.mem_range.mp hi
    rw [Polynomial.coeff_C_mul, Polynomial.coeff_X_pow]
    split_ifs with h_eq
    · have h_ki : k - i = 1 := by omega
      have h_neg1 : (-1 : ℝ) ^ (k - i) = -1 := by rw [h_ki, pow_one]
      rw [h_neg1]
      ring
    · ring
  rw [h_X_pow, h_sum_zero]
  ring

theorem sum_coeff_D_poly_lt_eq_zero_helper (P : ℝ[X]) (m : ℕ) :
  ∑ k ∈ Finset.range (m + 5), (P.coeff k • D_poly (m + 5) k).coeff (2 * m + 6) = 0 :=
by
  apply Finset.sum_eq_zero
  intro k hk
  rw [Finset.mem_range] at hk
  rw [Polynomial.coeff_smul, coeff_D_poly_lt_eq_zero m k hk, smul_zero]

theorem coeff_D_poly_self_helper (m : ℕ) :
  (D_poly (m + 5) (m + 5)).coeff (2 * m + 6) = - (Nat.choose (m + 5) 2 : ℝ) :=
by

  have eval_coeff (c : ℕ) (k n : ℕ) : ((c : ℝ[X]) * X ^ k).coeff n = if k = n then (c : ℝ) else 0 := by
    have h_rearr : ((c : ℝ[X]) * X ^ k).coeff n = (C (c : ℝ) * X ^ k).coeff n := by
      have hc : (c : ℝ[X]) = C (c : ℝ) := (Polynomial.C_eq_natCast c).symm
      rw [hc]
    rw [h_rearr, Polynomial.coeff_C_mul, Polynomial.coeff_X_pow]
    by_cases h : k = n
    · subst h
      simp
    · have h' : n ≠ k := ne_comm.mp h
      simp [h, h']

  have eval_coeff_minus (c : ℕ) (k n p : ℕ) : ((c : ℝ[X]) * X ^ k * (-1 : ℝ[X]) ^ p).coeff n = if k = n then (c : ℝ) * (-1 : ℝ) ^ p else 0 := by
    have h_rearr : ((c : ℝ[X]) * X ^ k * (-1 : ℝ[X]) ^ p).coeff n = (C ((c : ℝ) * (-1 : ℝ) ^ p) * X ^ k).coeff n := by
      have hc : (c : ℝ[X]) = C (c : ℝ) := (Polynomial.C_eq_natCast c).symm
      have h1 : (-1 : ℝ[X]) = C (-1 : ℝ) := by
        have h_one : (1 : ℝ[X]) = C (1 : ℝ) := (map_one (C : ℝ →+* ℝ[X])).symm
        calc (-1 : ℝ[X]) = - (1 : ℝ[X]) := rfl
          _ = - C (1 : ℝ) := by rw [h_one]
          _ = C (-1 : ℝ) := (map_neg (C : ℝ →+* ℝ[X]) 1).symm
      have h_eq : ((c : ℝ[X]) * X ^ k * (-1 : ℝ[X]) ^ p) = C ((c : ℝ) * (-1 : ℝ) ^ p) * X ^ k := by
        rw [hc, h1, ← map_pow (C : ℝ →+* ℝ[X])]
        have h_reorder : C (c : ℝ) * X ^ k * C ((-1 : ℝ) ^ p) = C (c : ℝ) * C ((-1 : ℝ) ^ p) * X ^ k := by ring
        rw [h_reorder, ← map_mul (C : ℝ →+* ℝ[X])]
      rw [h_eq]
    rw [h_rearr, Polynomial.coeff_C_mul, Polynomial.coeff_X_pow]
    by_cases h : k = n
    · subst h
      simp
    · have h' : n ≠ k := ne_comm.mp h
      simp [h, h']

  have h_plus_eq : (X ^ 2 + 1 : ℝ[X]) ^ (m + 5) = ∑ i ∈ Finset.range (m + 6), (Nat.choose (m + 5) i : ℝ[X]) * X ^ (2 * i) := by
    first
    | rw [add_pow]
      apply Finset.sum_congr rfl
      intro i _
      simp only [one_pow, mul_one, one_mul, ← pow_mul]
      ring
    | have h_add : (X ^ 2 + 1 : ℝ[X]) = 1 + X ^ 2 := add_comm _ _
      rw [h_add, add_pow]
      apply Finset.sum_congr rfl
      intro i _
      simp only [one_pow, mul_one, one_mul, ← pow_mul]
      ring

  have h_minus_eq : (X ^ 2 - 1 : ℝ[X]) ^ (m + 5) = ∑ i ∈ Finset.range (m + 6), (Nat.choose (m + 5) i : ℝ[X]) * X ^ (2 * i) * (-1 : ℝ[X]) ^ (m + 5 - i) := by
    first
    | have h_sub : (X ^ 2 - 1 : ℝ[X]) = X ^ 2 + (-1 : ℝ[X]) := by ring
      rw [h_sub, add_pow]
      apply Finset.sum_congr rfl
      intro i _
      simp only [← pow_mul]
      ring
    | have h_sub : (X ^ 2 - 1 : ℝ[X]) = -1 + X ^ 2 := by ring
      rw [h_sub, add_pow]
      apply Finset.sum_congr rfl
      intro i _
      simp only [← pow_mul]
      ring

  have h_coeff_plus : ((X ^ 2 + 1 : ℝ[X]) ^ (m + 5)).coeff (2 * m + 6) = (Nat.choose (m + 5) (m + 3) : ℝ) := by
    rw [h_plus_eq, Polynomial.finset_sum_coeff]
    rw [Finset.sum_eq_single (m + 3)]
    · have h_idx : 2 * (m + 3) = 2 * m + 6 := by omega
      rw [h_idx, eval_coeff]
      simp
    · intro i _ h_neq
      have h_idx : 2 * i ≠ 2 * m + 6 := by omega
      rw [eval_coeff]
      simp [h_idx]
    · intro h_notin
      exfalso
      apply h_notin
      rw [Finset.mem_range]
      omega

  have h_coeff_minus : ((X ^ 2 - 1 : ℝ[X]) ^ (m + 5)).coeff (2 * m + 6) = (Nat.choose (m + 5) (m + 3) : ℝ) := by
    rw [h_minus_eq, Polynomial.finset_sum_coeff]
    rw [Finset.sum_eq_single (m + 3)]
    · have h_idx : 2 * (m + 3) = 2 * m + 6 := by omega
      have h_pow : m + 5 - (m + 3) = 2 := by omega
      rw [h_idx, h_pow, eval_coeff_minus]
      have : (-1 : ℝ) ^ 2 = 1 := by ring
      simp [this]
    · intro i _ h_neq
      have h_idx : 2 * i ≠ 2 * m + 6 := by omega
      rw [eval_coeff_minus]
      simp [h_idx]
    · intro h_notin
      exfalso
      apply h_notin
      rw [Finset.mem_range]
      omega

  unfold D_poly
  have h_sub : m + 5 - (m + 5) = 0 := Nat.sub_self _
  have h_add : m + 5 + (m + 5) = 2 * m + 10 := by omega
  rw [h_sub, h_add]

  simp only [pow_zero, mul_one, one_mul, Polynomial.coeff_add, Polynomial.coeff_sub]

  have h_X1 : (X ^ (2 * m + 10) : ℝ[X]).coeff (2 * m + 6) = 0 := by
    rw [Polynomial.coeff_X_pow]
    have : 2 * m + 10 ≠ 2 * m + 6 := by omega
    have : 2 * m + 6 ≠ 2 * m + 10 := by omega
    simp [*]

  have h_X2 : (1 : ℝ[X]).coeff (2 * m + 6) = 0 := by
    have h1 : (1 : ℝ[X]) = X ^ 0 := (pow_zero X).symm
    rw [h1, Polynomial.coeff_X_pow]
    have : 0 ≠ 2 * m + 6 := by omega
    have : 2 * m + 6 ≠ 0 := by omega
    simp [*]

  have h_third : (C ((1 : ℝ) / 2) * ((X ^ 2 + 1 : ℝ[X]) ^ (m + 5) + (X ^ 2 - 1 : ℝ[X]) ^ (m + 5))).coeff (2 * m + 6) = (Nat.choose (m + 5) (m + 3) : ℝ) := by
    rw [Polynomial.coeff_C_mul, Polynomial.coeff_add, h_coeff_plus, h_coeff_minus]
    ring

  rw [h_X1, h_X2, h_third]

  have h_symm : (Nat.choose (m + 5) (m + 3) : ℝ) = (Nat.choose (m + 5) 2 : ℝ) := by
    have h_le : 2 ≤ m + 5 := by omega
    have h_eq : m + 5 - 2 = m + 3 := by omega
    have h_choose := Nat.choose_symm h_le
    rw [h_eq] at h_choose
    rw [h_choose]

  rw [h_symm]
  ring

theorem coeff_sum_smul_D_poly (P : ℝ[X]) (m : ℕ) :
  (∑ k ∈ Finset.range (m + 5 + 1), P.coeff k • D_poly (m + 5) k).coeff (2 * m + 6) =
  P.coeff (m + 5) * (- (Nat.choose (m + 5) 2 : ℝ)) :=
by
  -- 1. Push the coefficient extraction inside the sum over the specified Finset.range.
  rw [Polynomial.finset_sum_coeff]
  -- 2. Split the summation for range (m + 5 + 1) into the range (m + 5) piece plus the (m + 5) last term.
  rw [Finset.sum_range_succ]
  -- 3. Replace the extracted range (m + 5) sum entirely with 0 using our helper lemma.
  rw [sum_coeff_D_poly_lt_eq_zero_helper P m]
  -- 4. Eliminate the resulting 0 +.
  rw [zero_add]
  -- 5. Pull the scalar weight (P.coeff) outside of the remaining term's coefficient extraction.
  rw [Polynomial.coeff_smul]
  -- 6. Evaluate the D_poly term directly at its matched degree matching our self helper lemma.
  rw [coeff_D_poly_self_helper m]
  -- 7. Convert the module scalar multiplication (•) over ℝ seamlessly to standard multiplication (*).
  rw [smul_eq_mul]

theorem choose_two_ne_zero (m : ℕ) :
  (- (Nat.choose (m + 5) 2 : ℝ)) ≠ 0 :=
by
  have h2 : 2 ≤ m + 5 := by omega
  have h3 : 0 < Nat.choose (m + 5) 2 := Nat.choose_pos h2
  have h4 : (0 : ℝ) < (Nat.choose (m + 5) 2 : ℝ) := Nat.cast_pos.mpr h3
  linarith

theorem eval_sum_D_poly {P : ℝ[X]} (N : ℕ) (x : ℝ) (hx : x ≠ (0 : ℝ)) :
  (∑ k ∈ Finset.range (N + 1), P.coeff k • D_poly N k).eval x =
    x ^ N * ( ∑ k ∈ Finset.range (N + 1), P.coeff k * x ^ k +
              ∑ k ∈ Finset.range (N + 1), P.coeff k * ((1 : ℝ) / x) ^ k -
              ((1 : ℝ) / 2) * ( ∑ k ∈ Finset.range (N + 1), P.coeff k * (x + (1 : ℝ) / x) ^ k +
                                ∑ k ∈ Finset.range (N + 1), P.coeff k * (x - (1 : ℝ) / x) ^ k ) ) :=
by
  have step1 : (∑ k ∈ Finset.range (N + 1), P.coeff k • D_poly N k).eval x = ∑ k ∈ Finset.range (N + 1), P.coeff k * (D_poly N k).eval x := by
    have : (∑ k ∈ Finset.range (N + 1), P.coeff k • D_poly N k).eval x = (Polynomial.evalRingHom x) (∑ k ∈ Finset.range (N + 1), P.coeff k • D_poly N k) := rfl
    rw [this, map_sum]
    apply Finset.sum_congr rfl
    intro k _
    change (P.coeff k • D_poly N k).eval x = P.coeff k * (D_poly N k).eval x
    rw [Polynomial.eval_smul, smul_eq_mul]

  have step2 : x ^ N * ( ∑ k ∈ Finset.range (N + 1), P.coeff k * x ^ k +
          ∑ k ∈ Finset.range (N + 1), P.coeff k * ((1 : ℝ) / x) ^ k -
          ((1 : ℝ) / 2) * ( ∑ k ∈ Finset.range (N + 1), P.coeff k * (x + (1 : ℝ) / x) ^ k +
                            ∑ k ∈ Finset.range (N + 1), P.coeff k * (x - (1 : ℝ) / x) ^ k ) ) =
      ∑ k ∈ Finset.range (N + 1), x ^ N * (P.coeff k * x ^ k + P.coeff k * ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * (P.coeff k * (x + (1 : ℝ) / x) ^ k + P.coeff k * (x - (1 : ℝ) / x) ^ k)) := by
    simp only [← Finset.sum_add_distrib, ← Finset.sum_sub_distrib, Finset.mul_sum]

  rw [step1, step2]
  apply Finset.sum_congr rfl
  intro k hk

  have h_k_le_N : k ≤ N := Nat.le_of_lt_succ (Finset.mem_range.mp hk)

  have H2 : x ^ N * ((1 : ℝ) / x) ^ k = x ^ (N - k) := by
    symm
    calc x ^ (N - k)
      _ = x ^ (N - k) * 1 := by rw [mul_one]
      _ = x ^ (N - k) * (1 : ℝ) ^ k := by rw [one_pow]
      _ = x ^ (N - k) * (x * x⁻¹) ^ k := by
        have h_inv : (1 : ℝ) = x * x⁻¹ := (mul_inv_cancel₀ hx).symm
        rw [h_inv]
      _ = x ^ (N - k) * (x ^ k * (x⁻¹) ^ k) := by rw [mul_pow]
      _ = x ^ (N - k) * x ^ k * (x⁻¹) ^ k := by rw [← mul_assoc]
      _ = x ^ (N - k + k) * (x⁻¹) ^ k := by rw [← pow_add]
      _ = x ^ N * (x⁻¹) ^ k := by rw [Nat.sub_add_cancel h_k_le_N]
      _ = x ^ N * ((1 : ℝ) / x) ^ k := by
        have h3 : x⁻¹ = (1 : ℝ) / x := by rw [one_div]
        rw [h3]

  have H3 : x ^ (N - k) * (x ^ 2 + 1) ^ k = x ^ N * (x + (1 : ℝ) / x) ^ k := by
    have h1 : (x ^ 2 + 1) = x * (x + x⁻¹) := by
      calc x ^ 2 + 1
        _ = x * x + 1 := by ring
        _ = x * x + x * x⁻¹ := by
          have h_inv : (1 : ℝ) = x * x⁻¹ := (mul_inv_cancel₀ hx).symm
          rw [h_inv]
        _ = x * (x + x⁻¹) := by ring
    rw [h1, mul_pow, ← mul_assoc, ← pow_add, Nat.sub_add_cancel h_k_le_N]
    have h3 : x + x⁻¹ = x + (1 : ℝ) / x := by rw [one_div]
    rw [h3]

  have H4 : x ^ (N - k) * (x ^ 2 - 1) ^ k = x ^ N * (x - (1 : ℝ) / x) ^ k := by
    have h1 : (x ^ 2 - 1) = x * (x - x⁻¹) := by
      calc x ^ 2 - 1
        _ = x * x - 1 := by ring
        _ = x * x - x * x⁻¹ := by
          have h_inv : (1 : ℝ) = x * x⁻¹ := (mul_inv_cancel₀ hx).symm
          rw [h_inv]
        _ = x * (x - x⁻¹) := by ring
    rw [h1, mul_pow, ← mul_assoc, ← pow_add, Nat.sub_add_cancel h_k_le_N]
    have h3 : x - x⁻¹ = x - (1 : ℝ) / x := by rw [one_div]
    rw [h3]

  calc P.coeff k * (D_poly N k).eval x
    _ = P.coeff k * (x ^ (N + k) + x ^ (N - k) - ((1 : ℝ) / 2) * (x ^ (N - k) * (x ^ 2 + 1) ^ k + x ^ (N - k) * (x ^ 2 - 1) ^ k)) := by
      have hD : (D_poly N k).eval x = x ^ (N + k) + x ^ (N - k) - ((1 : ℝ) / 2) * x ^ (N - k) * ((x ^ 2 + 1) ^ k + (x ^ 2 - 1) ^ k) := by
        simp [D_poly]
      rw [hD]
      ring
    _ = P.coeff k * (x ^ N * x ^ k + x ^ N * ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * (x ^ N * (x + (1 : ℝ) / x) ^ k + x ^ N * (x - (1 : ℝ) / x) ^ k)) := by
      have h_pow_add : x ^ (N + k) = x ^ N * x ^ k := by rw [pow_add]
      rw [h_pow_add, H3, H4, ← H2]
    _ = x ^ N * (P.coeff k * x ^ k + P.coeff k * ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * (P.coeff k * (x + (1 : ℝ) / x) ^ k + P.coeff k * (x - (1 : ℝ) / x) ^ k)) := by ring

theorem eval_sum_D_poly_eq_zero_of_hyp {P : ℝ[X]} {N : ℕ} (hdeg : P.natDegree ≤ N)
  (h : ∀ x ≠ (0 : ℝ), P.eval x + P.eval ((1 : ℝ) / x) = ((1 : ℝ) / 2) * (P.eval (x + (1 : ℝ) / x) + P.eval (x - (1 : ℝ) / x)))
  (x : ℝ) (hx : x ≠ (0 : ℝ)) :
  (∑ k ∈ Finset.range (N + 1), P.coeff k • D_poly N k).eval x = (0 : ℝ) :=
by

  have hP_eval (y : ℝ) : P.eval y = ∑ k ∈ Finset.range (N + 1), P.coeff k * y ^ k := by
    let P_sum := ∑ i ∈ Finset.range (P.natDegree + 1), Polynomial.C (P.coeff i) * Polynomial.X ^ i
    have h1 : P = P_sum := Polynomial.as_sum_range_C_mul_X_pow P
    have h_sum1 : P.eval y = ∑ i ∈ Finset.range (P.natDegree + 1), P.coeff i * y ^ i := by
      let f := Polynomial.evalRingHom y
      have h_eval_sum : f P_sum = ∑ i ∈ Finset.range (P.natDegree + 1), f (Polynomial.C (P.coeff i) * Polynomial.X ^ i) := map_sum f _ _
      have h2 : P.eval y = f P_sum := by
        change P.eval y = P_sum.eval y
        rw [h1]
      rw [h2, h_eval_sum]
      apply Finset.sum_congr rfl
      intro i _
      change (Polynomial.C (P.coeff i) * Polynomial.X ^ i).eval y = P.coeff i * y ^ i
      rw [eval_mul, eval_C, eval_pow, eval_X]
    rw [h_sum1]
    apply Finset.sum_subset
    · intro i hi
      rw [Finset.mem_range] at hi ⊢
      omega
    · intro i hi hni
      rw [Finset.mem_range] at hi hni
      have hk_deg : P.natDegree < i := by omega
      have h_zero : P.coeff i = 0 := Polynomial.coeff_eq_zero_of_natDegree_lt hk_deg
      rw [h_zero, zero_mul]

  have h_sum : (∑ k ∈ Finset.range (N + 1), P.coeff k • D_poly N k).eval x =
    ∑ k ∈ Finset.range (N + 1), P.coeff k * (D_poly N k).eval x := by
    let f_x := Polynomial.evalRingHom x
    have h_eq : (∑ k ∈ Finset.range (N + 1), P.coeff k • D_poly N k).eval x = f_x (∑ k ∈ Finset.range (N + 1), P.coeff k • D_poly N k) := rfl
    rw [h_eq, map_sum]
    apply Finset.sum_congr rfl
    intro k _
    change (P.coeff k • D_poly N k).eval x = P.coeff k * (D_poly N k).eval x
    rw [Algebra.smul_def]
    have h_algMap : algebraMap ℝ ℝ[X] (P.coeff k) = Polynomial.C (P.coeff k) := rfl
    rw [h_algMap, eval_mul, eval_C]

  have hD : ∀ k ∈ Finset.range (N + 1), (D_poly N k).eval x =
      x ^ N * (x ^ k + ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * ((x + ((1 : ℝ) / x)) ^ k + (x - ((1 : ℝ) / x)) ^ k)) := by
    intro k hk
    have hk_le : k ≤ N := Finset.mem_range_succ_iff.mp hk
    have h_pow : x ^ (N - k) * x ^ k = x ^ N := by rw [← pow_add, tsub_add_cancel_of_le hk_le]
    have h_add : x ^ (N + k) = x ^ N * x ^ k := pow_add x N k

    have h1 : x * (x + (1 : ℝ) / x) = x ^ 2 + 1 := by
      have h_mul : x * ((1 : ℝ) / x) = 1 := mul_one_div_cancel hx
      calc x * (x + (1 : ℝ) / x) = x * x + x * ((1 : ℝ) / x) := mul_add x x ((1 : ℝ) / x)
        _ = x ^ 2 + 1 := by rw [← sq, h_mul]

    have h2 : x * (x - (1 : ℝ) / x) = x ^ 2 - 1 := by
      have h_mul : x * ((1 : ℝ) / x) = 1 := mul_one_div_cancel hx
      calc x * (x - (1 : ℝ) / x) = x * x - x * ((1 : ℝ) / x) := mul_sub x x ((1 : ℝ) / x)
        _ = x ^ 2 - 1 := by rw [← sq, h_mul]

    have h_inv : x ^ (N - k) = x ^ N * ((1 : ℝ) / x) ^ k := by
      have eq1 : x ^ (N - k) = x ^ (N - k) * (x * ((1 : ℝ) / x)) ^ k := by
        have h_mul : x * ((1 : ℝ) / x) = 1 := mul_one_div_cancel hx
        rw [h_mul, one_pow, mul_one]
      calc x ^ (N - k) = x ^ (N - k) * (x * ((1 : ℝ) / x)) ^ k := eq1
        _ = x ^ (N - k) * (x ^ k * ((1 : ℝ) / x) ^ k) := by rw [mul_pow]
        _ = x ^ (N - k) * x ^ k * ((1 : ℝ) / x) ^ k := by rw [← mul_assoc]
        _ = x ^ N * ((1 : ℝ) / x) ^ k := by rw [h_pow]

    have h_pos : x ^ (N - k) * (x ^ 2 + 1) ^ k = x ^ N * (x + (1 : ℝ) / x) ^ k := by
      calc x ^ (N - k) * (x ^ 2 + 1) ^ k = x ^ (N - k) * (x * (x + (1 : ℝ) / x)) ^ k := by rw [← h1]
        _ = x ^ (N - k) * (x ^ k * (x + (1 : ℝ) / x) ^ k) := by rw [mul_pow]
        _ = x ^ (N - k) * x ^ k * (x + (1 : ℝ) / x) ^ k := by rw [← mul_assoc]
        _ = x ^ N * (x + (1 : ℝ) / x) ^ k := by rw [h_pow]

    have h_neg : x ^ (N - k) * (x ^ 2 - 1) ^ k = x ^ N * (x - (1 : ℝ) / x) ^ k := by
      calc x ^ (N - k) * (x ^ 2 - 1) ^ k = x ^ (N - k) * (x * (x - (1 : ℝ) / x)) ^ k := by rw [← h2]
        _ = x ^ (N - k) * (x ^ k * (x - (1 : ℝ) / x) ^ k) := by rw [mul_pow]
        _ = x ^ (N - k) * x ^ k * (x - (1 : ℝ) / x) ^ k := by rw [← mul_assoc]
        _ = x ^ N * (x - (1 : ℝ) / x) ^ k := by rw [h_pow]

    calc (D_poly N k).eval x
      _ = x ^ (N + k) + x ^ (N - k) - ((1 : ℝ) / 2) * x ^ (N - k) * ((x ^ 2 + 1) ^ k + (x ^ 2 - 1) ^ k) := by simp [D_poly]
      _ = x ^ N * x ^ k + x ^ N * ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * x ^ (N - k) * ((x ^ 2 + 1) ^ k + (x ^ 2 - 1) ^ k) := by rw [h_add, h_inv]
      _ = x ^ N * x ^ k + x ^ N * ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * (x ^ (N - k) * ((x ^ 2 + 1) ^ k + (x ^ 2 - 1) ^ k)) := by ring
      _ = x ^ N * x ^ k + x ^ N * ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * (x ^ (N - k) * (x ^ 2 + 1) ^ k + x ^ (N - k) * (x ^ 2 - 1) ^ k) := by rw [mul_add]
      _ = x ^ N * x ^ k + x ^ N * ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * (x ^ N * (x + ((1 : ℝ) / x)) ^ k + x ^ N * (x - ((1 : ℝ) / x)) ^ k) := by rw [h_pos, h_neg]
      _ = x ^ N * (x ^ k + ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * ((x + ((1 : ℝ) / x)) ^ k + (x - ((1 : ℝ) / x)) ^ k)) := by ring

  rw [h_sum]

  have h_sum2 : ∑ k ∈ Finset.range (N + 1), P.coeff k * (D_poly N k).eval x =
      ∑ k ∈ Finset.range (N + 1), P.coeff k * (x ^ N * (x ^ k + ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * ((x + ((1 : ℝ) / x)) ^ k + (x - ((1 : ℝ) / x)) ^ k))) := by
    apply Finset.sum_congr rfl
    intro k hk
    rw [hD k hk]

  have h_sum3 : ∑ k ∈ Finset.range (N + 1), P.coeff k * (x ^ N * (x ^ k + ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * ((x + ((1 : ℝ) / x)) ^ k + (x - ((1 : ℝ) / x)) ^ k))) =
      x ^ N * (∑ k ∈ Finset.range (N + 1), P.coeff k * x ^ k
               + ∑ k ∈ Finset.range (N + 1), P.coeff k * ((1 : ℝ) / x) ^ k
               - ((1 : ℝ) / 2) * (∑ k ∈ Finset.range (N + 1), P.coeff k * (x + ((1 : ℝ) / x)) ^ k
                                + ∑ k ∈ Finset.range (N + 1), P.coeff k * (x - ((1 : ℝ) / x)) ^ k)) := by
    calc ∑ k ∈ Finset.range (N + 1), P.coeff k * (x ^ N * (x ^ k + ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * ((x + ((1 : ℝ) / x)) ^ k + (x - ((1 : ℝ) / x)) ^ k)))
      _ = ∑ k ∈ Finset.range (N + 1), (x ^ N * (P.coeff k * x ^ k) + x ^ N * (P.coeff k * ((1 : ℝ) / x) ^ k) - (x ^ N * ((1 : ℝ) / 2)) * (P.coeff k * (x + ((1 : ℝ) / x)) ^ k) - (x ^ N * ((1 : ℝ) / 2)) * (P.coeff k * (x - ((1 : ℝ) / x)) ^ k)) := by
        apply Finset.sum_congr rfl
        intro k _
        ring
      _ = ∑ k ∈ Finset.range (N + 1), x ^ N * (P.coeff k * x ^ k) + ∑ k ∈ Finset.range (N + 1), x ^ N * (P.coeff k * ((1 : ℝ) / x) ^ k) - ∑ k ∈ Finset.range (N + 1), (x ^ N * ((1 : ℝ) / 2)) * (P.coeff k * (x + ((1 : ℝ) / x)) ^ k) - ∑ k ∈ Finset.range (N + 1), (x ^ N * ((1 : ℝ) / 2)) * (P.coeff k * (x - ((1 : ℝ) / x)) ^ k) := by
        simp only [Finset.sum_add_distrib, Finset.sum_sub_distrib]
      _ = x ^ N * ∑ k ∈ Finset.range (N + 1), P.coeff k * x ^ k + x ^ N * ∑ k ∈ Finset.range (N + 1), P.coeff k * ((1 : ℝ) / x) ^ k - (x ^ N * ((1 : ℝ) / 2)) * ∑ k ∈ Finset.range (N + 1), P.coeff k * (x + ((1 : ℝ) / x)) ^ k - (x ^ N * ((1 : ℝ) / 2)) * ∑ k ∈ Finset.range (N + 1), P.coeff k * (x - ((1 : ℝ) / x)) ^ k := by
        simp only [← Finset.mul_sum]
      _ = x ^ N * (∑ k ∈ Finset.range (N + 1), P.coeff k * x ^ k + ∑ k ∈ Finset.range (N + 1), P.coeff k * ((1 : ℝ) / x) ^ k - ((1 : ℝ) / 2) * (∑ k ∈ Finset.range (N + 1), P.coeff k * (x + ((1 : ℝ) / x)) ^ k + ∑ k ∈ Finset.range (N + 1), P.coeff k * (x - ((1 : ℝ) / x)) ^ k)) := by ring

  rw [h_sum2, h_sum3]

  have e1 : ∑ k ∈ Finset.range (N + 1), P.coeff k * x ^ k = P.eval x := (hP_eval x).symm
  have e2 : ∑ k ∈ Finset.range (N + 1), P.coeff k * ((1 : ℝ) / x) ^ k = P.eval ((1 : ℝ) / x) := (hP_eval ((1 : ℝ) / x)).symm
  have e3 : ∑ k ∈ Finset.range (N + 1), P.coeff k * (x + ((1 : ℝ) / x)) ^ k = P.eval (x + ((1 : ℝ) / x)) := (hP_eval (x + ((1 : ℝ) / x))).symm
  have e4 : ∑ k ∈ Finset.range (N + 1), P.coeff k * (x - ((1 : ℝ) / x)) ^ k = P.eval (x - ((1 : ℝ) / x)) := (hP_eval (x - ((1 : ℝ) / x))).symm

  rw [e1, e2, e3, e4]

  have h_hyp := h x hx
  calc x ^ N * (P.eval x + P.eval ((1 : ℝ) / x) - ((1 : ℝ) / 2) * (P.eval (x + ((1 : ℝ) / x)) + P.eval (x - ((1 : ℝ) / x))))
    _ = x ^ N * ((((1 : ℝ) / 2) * (P.eval (x + ((1 : ℝ) / x)) + P.eval (x - ((1 : ℝ) / x)))) - ((1 : ℝ) / 2) * (P.eval (x + ((1 : ℝ) / x)) + P.eval (x - ((1 : ℝ) / x)))) := by rw [h_hyp]
    _ = 0 := by ring

theorem poly_eq_zero_of_eval_eq_zero_forall_ne_zero (Q : ℝ[X]) (hQ : ∀ x : ℝ, x ≠ (0 : ℝ) → Q.eval x = (0 : ℝ)) : Q = 0 :=
by
  have h_mul : Q * X = 0 := by
    refine Polynomial.zero_of_eval_zero (Q * X) ?_
    intro x
    simp only [Polynomial.eval_mul, Polynomial.eval_X]
    by_cases hx : x = (0 : ℝ)
    · rw [hx, mul_zero]
    · rw [hQ x hx, zero_mul]
  have hX : (X : ℝ[X]) ≠ 0 := by
    intro h
    have h1 : (X : ℝ[X]).eval (1 : ℝ) = 0 := by
      rw [h]
      simp
    rw [Polynomial.eval_X] at h1
    exact one_ne_zero h1
  have h_or : Q = 0 ∨ (X : ℝ[X]) = 0 := mul_eq_zero.mp h_mul
  cases h_or with
  | inl hQ_eq => exact hQ_eq
  | inr hX_eq => exact False.elim (hX hX_eq)

theorem sum_D_poly_eq_zero_of_le_aux {P : ℝ[X]}
  (h : ∀ x ≠ (0 : ℝ), P.eval x + P.eval ((1 : ℝ) / x) = (1 : ℝ) / 2 * (P.eval (x + (1 : ℝ) / x) + P.eval (x - (1 : ℝ) / x)))
  (N : ℕ) (hdeg : P.natDegree ≤ N) :
  ∑ k ∈ Finset.range (N + 1), P.coeff k • D_poly N k = 0 :=
by
  apply poly_eq_zero_of_eval_eq_zero_forall_ne_zero
  intro x hx
  exact eval_sum_D_poly_eq_zero_of_hyp hdeg h x hx

theorem coeff_leading_eq_zero_of_deg_ge_5 {P : ℝ[X]}
  (h : ∀ x ≠ (0 : ℝ), P.eval x + P.eval ((1 : ℝ) / x) = (1 : ℝ) / 2 * (P.eval (x + (1 : ℝ) / x) + P.eval (x - (1 : ℝ) / x)))
  (n : ℕ) (hn : P.natDegree = n) (hn5 : 5 ≤ n) : P.coeff n = 0 :=
by
  -- Abstract out `n` as `m + 5` properly using bounded existential addition to adhere to natural number arithmetic constraints
  obtain ⟨m, hm⟩ := Nat.exists_eq_add_of_le hn5
  have hn_eq : n = m + 5 := by omega

  -- Re-evaluate P's degree in terms of m + 5
  have hdeg : P.natDegree ≤ m + 5 := by
    rw [hn_eq] at hn
    exact le_of_eq hn

  -- Retrieve the full summative identity corresponding to the functional equation
  have h_sum := sum_D_poly_eq_zero_of_le_aux h (m + 5) hdeg

  -- Extract and evaluate the target polynomial coefficient relation
  have h_coeff : P.coeff (m + 5) * (- (Nat.choose (m + 5) 2 : ℝ)) = 0 := by
    rw [← coeff_sum_smul_D_poly P m]
    rw [h_sum]
    exact Polynomial.coeff_zero (2 * m + 6)

  -- Substitute back to our target n and apply the logical disjunction resolution
  rw [hn_eq]
  cases mul_eq_zero.mp h_coeff with
  | inl h_P =>
    exact h_P
  | inr h_choose =>
    exact False.elim (choose_two_ne_zero m h_choose)

theorem natDegree_le_4_of_prop {P : ℝ[X]}
  (h : ∀ x ≠ (0 : ℝ), P.eval x + P.eval ((1 : ℝ) / x) = (1 : ℝ) / 2 * (P.eval (x + (1 : ℝ) / x) + P.eval (x - (1 : ℝ) / x))) :
  P.natDegree ≤ 4 :=
by
  by_contra h_deg
  have hn5 : 5 ≤ P.natDegree := by omega
  have h_coeff : P.coeff P.natDegree = 0 := coeff_leading_eq_zero_of_deg_ge_5 h P.natDegree rfl hn5
  have h_lead : P.leadingCoeff = 0 := h_coeff
  have h_P_eq_0 : P = 0 := Polynomial.leadingCoeff_eq_zero.mp h_lead
  rw [h_P_eq_0] at hn5
  rw [Polynomial.natDegree_zero] at hn5
  omega

theorem poly_id_of_prop {P : ℝ[X]}
  (hdeg : P.natDegree ≤ 4)
  (h : ∀ x ≠ (0 : ℝ), P.eval x + P.eval ((1 : ℝ) / x) = (1 : ℝ) / 2 * (P.eval (x + (1 : ℝ) / x) + P.eval (x - (1 : ℝ) / x))) :
  C (P.coeff 0 - (6 : ℝ) * P.coeff 4) * X ^ 4 + C (P.coeff 1 - (3 : ℝ) * P.coeff 3) * X ^ 3 + C (P.coeff 3) * X = 0 :=
by

  have hP : P = C (P.coeff 4) * X ^ 4 + C (P.coeff 3) * X ^ 3 + C (P.coeff 2) * X ^ 2 + C (P.coeff 1) * X + C (P.coeff 0) := by
    ext i
    simp only [coeff_add, coeff_C_mul, coeff_X_pow, coeff_X, coeff_C, mul_ite, mul_one, mul_zero]
    rcases i with _ | _ | _ | _ | _ | i
    · simp
    · simp
    · simp
    · simp
    · simp
    · have h1 : P.natDegree < i + 5 := by omega
      have h2 : P.coeff (i + 5) = 0 := Polynomial.coeff_eq_zero_of_natDegree_lt h1
      simp [h2]

  have heval : ∀ x : ℝ, P.eval x = P.coeff 4 * x ^ 4 + P.coeff 3 * x ^ 3 + P.coeff 2 * x ^ 2 + P.coeff 1 * x + P.coeff 0 := by
    intro x
    calc P.eval x = (C (P.coeff 4) * X ^ 4 + C (P.coeff 3) * X ^ 3 + C (P.coeff 2) * X ^ 2 + C (P.coeff 1) * X + C (P.coeff 0)).eval x := by rw [← hP]
      _ = P.coeff 4 * x ^ 4 + P.coeff 3 * x ^ 3 + P.coeff 2 * x ^ 2 + P.coeff 1 * x + P.coeff 0 := by simp only [eval_add, eval_mul, eval_C, eval_pow, eval_X]

  have h_eq : ∀ x : ℝ, x ≠ 0 →
      P.coeff 4 * x ^ 4 + P.coeff 3 * x ^ 3 + P.coeff 2 * x ^ 2 + P.coeff 1 * x + P.coeff 0 +
      (P.coeff 4 * ((1 : ℝ) / x) ^ 4 + P.coeff 3 * ((1 : ℝ) / x) ^ 3 + P.coeff 2 * ((1 : ℝ) / x) ^ 2 + P.coeff 1 * ((1 : ℝ) / x) + P.coeff 0) =
      (1 : ℝ) / 2 * (
        P.coeff 4 * (x + (1 : ℝ) / x) ^ 4 + P.coeff 3 * (x + (1 : ℝ) / x) ^ 3 + P.coeff 2 * (x + (1 : ℝ) / x) ^ 2 + P.coeff 1 * (x + (1 : ℝ) / x) + P.coeff 0 +
        (P.coeff 4 * (x - (1 : ℝ) / x) ^ 4 + P.coeff 3 * (x - (1 : ℝ) / x) ^ 3 + P.coeff 2 * (x - (1 : ℝ) / x) ^ 2 + P.coeff 1 * (x - (1 : ℝ) / x) + P.coeff 0)
      ) := by
    intro x hx
    have h1 := h x hx
    simp only [heval] at h1
    exact h1

  have h_eq2 : ∀ x : ℝ, x ≠ 0 →
      (P.coeff 0 - (6 : ℝ) * P.coeff 4) * x ^ 4 + (P.coeff 1 - (3 : ℝ) * P.coeff 3) * x ^ 3 + P.coeff 3 * x = 0 := by
    intro x hx
    have h_XY : (P.coeff 0 - (6 : ℝ) * P.coeff 4) * x ^ 4 + (P.coeff 1 - (3 : ℝ) * P.coeff 3) * x ^ 3 + P.coeff 3 * x =
      ( ( P.coeff 4 * x ^ 4 + P.coeff 3 * x ^ 3 + P.coeff 2 * x ^ 2 + P.coeff 1 * x + P.coeff 0 +
          (P.coeff 4 * ((1 : ℝ) / x) ^ 4 + P.coeff 3 * ((1 : ℝ) / x) ^ 3 + P.coeff 2 * ((1 : ℝ) / x) ^ 2 + P.coeff 1 * ((1 : ℝ) / x) + P.coeff 0) ) -
        (1 : ℝ) / 2 * (
          P.coeff 4 * (x + (1 : ℝ) / x) ^ 4 + P.coeff 3 * (x + (1 : ℝ) / x) ^ 3 + P.coeff 2 * (x + (1 : ℝ) / x) ^ 2 + P.coeff 1 * (x + (1 : ℝ) / x) + P.coeff 0 +
          (P.coeff 4 * (x - (1 : ℝ) / x) ^ 4 + P.coeff 3 * (x - (1 : ℝ) / x) ^ 3 + P.coeff 2 * (x - (1 : ℝ) / x) ^ 2 + P.coeff 1 * (x - (1 : ℝ) / x) + P.coeff 0)
        ) ) * x ^ 4 := by
      field_simp [hx, div_pow, one_pow]
      ring

    have h_zero : P.coeff 4 * x ^ 4 + P.coeff 3 * x ^ 3 + P.coeff 2 * x ^ 2 + P.coeff 1 * x + P.coeff 0 +
      (P.coeff 4 * ((1 : ℝ) / x) ^ 4 + P.coeff 3 * ((1 : ℝ) / x) ^ 3 + P.coeff 2 * ((1 : ℝ) / x) ^ 2 + P.coeff 1 * ((1 : ℝ) / x) + P.coeff 0) -
      (1 : ℝ) / 2 * (
        P.coeff 4 * (x + (1 : ℝ) / x) ^ 4 + P.coeff 3 * (x + (1 : ℝ) / x) ^ 3 + P.coeff 2 * (x + (1 : ℝ) / x) ^ 2 + P.coeff 1 * (x + (1 : ℝ) / x) + P.coeff 0 +
        (P.coeff 4 * (x - (1 : ℝ) / x) ^ 4 + P.coeff 3 * (x - (1 : ℝ) / x) ^ 3 + P.coeff 2 * (x - (1 : ℝ) / x) ^ 2 + P.coeff 1 * (x - (1 : ℝ) / x) + P.coeff 0)
      ) = 0 := sub_eq_zero.mpr (h_eq x hx)

    rw [h_XY, h_zero, zero_mul]

  have e1 : (P.coeff 0 - (6 : ℝ) * P.coeff 4) * 1 ^ 4 + (P.coeff 1 - (3 : ℝ) * P.coeff 3) * 1 ^ 3 + P.coeff 3 * 1 = 0 := h_eq2 1 (by norm_num)
  have e2 : (P.coeff 0 - (6 : ℝ) * P.coeff 4) * (-1) ^ 4 + (P.coeff 1 - (3 : ℝ) * P.coeff 3) * (-1) ^ 3 + P.coeff 3 * (-1) = 0 := h_eq2 (-1) (by norm_num)
  have e3 : (P.coeff 0 - (6 : ℝ) * P.coeff 4) * 2 ^ 4 + (P.coeff 1 - (3 : ℝ) * P.coeff 3) * 2 ^ 3 + P.coeff 3 * 2 = 0 := h_eq2 2 (by norm_num)

  have e1' : (P.coeff 0 - (6 : ℝ) * P.coeff 4) + (P.coeff 1 - (3 : ℝ) * P.coeff 3) + P.coeff 3 = 0 := by
    calc (P.coeff 0 - (6 : ℝ) * P.coeff 4) + (P.coeff 1 - (3 : ℝ) * P.coeff 3) + P.coeff 3 = (P.coeff 0 - (6 : ℝ) * P.coeff 4) * 1 ^ 4 + (P.coeff 1 - (3 : ℝ) * P.coeff 3) * 1 ^ 3 + P.coeff 3 * 1 := by ring
    _ = 0 := e1

  have e2' : (P.coeff 0 - (6 : ℝ) * P.coeff 4) - (P.coeff 1 - (3 : ℝ) * P.coeff 3) - P.coeff 3 = 0 := by
    calc (P.coeff 0 - (6 : ℝ) * P.coeff 4) - (P.coeff 1 - (3 : ℝ) * P.coeff 3) - P.coeff 3 = (P.coeff 0 - (6 : ℝ) * P.coeff 4) * (-1) ^ 4 + (P.coeff 1 - (3 : ℝ) * P.coeff 3) * (-1) ^ 3 + P.coeff 3 * (-1) := by ring
    _ = 0 := e2

  have e3' : 16 * (P.coeff 0 - (6 : ℝ) * P.coeff 4) + 8 * (P.coeff 1 - (3 : ℝ) * P.coeff 3) + 2 * P.coeff 3 = 0 := by
    calc 16 * (P.coeff 0 - (6 : ℝ) * P.coeff 4) + 8 * (P.coeff 1 - (3 : ℝ) * P.coeff 3) + 2 * P.coeff 3 = (P.coeff 0 - (6 : ℝ) * P.coeff 4) * 2 ^ 4 + (P.coeff 1 - (3 : ℝ) * P.coeff 3) * 2 ^ 3 + P.coeff 3 * 2 := by ring
    _ = 0 := e3

  have hA : P.coeff 0 - (6 : ℝ) * P.coeff 4 = 0 := by linarith
  have hB : P.coeff 1 - (3 : ℝ) * P.coeff 3 = 0 := by linarith
  have hC : P.coeff 3 = 0 := by linarith

  rw [hA, hB, hC]
  simp only [map_zero, zero_mul, zero_add]

theorem constraints_of_eq_zero {c : ℕ → ℝ}
  (h : C (c 0 - (6 : ℝ) * c 4) * X ^ 4 + C (c 1 - (3 : ℝ) * c 3) * X ^ 3 + C (c 3) * X = 0) :
  c 3 = 0 ∧ c 1 = 0 ∧ c 0 = (6 : ℝ) * c 4 :=
by
  have h_ext : ∀ n, Polynomial.coeff (C (c 0 - (6 : ℝ) * c 4) * X ^ 4 + C (c 1 - (3 : ℝ) * c 3) * X ^ 3 + C (c 3) * X) n = 0 := by
    intro n
    rw [h]
    exact Polynomial.coeff_zero n

  have h1 : c 3 = 0 := by
    have h1_eval := h_ext 1
    simp [Polynomial.coeff_mul_X_pow'] at h1_eval
    linarith

  have h3 : c 1 = 0 := by
    have h3_eval := h_ext 3
    simp [Polynomial.coeff_mul_X_pow'] at h3_eval
    linarith

  have h4 : c 0 = (6 : ℝ) * c 4 := by
    have h4_eval := h_ext 4
    simp [Polynomial.coeff_mul_X_pow'] at h4_eval
    linarith

  exact ⟨h1, h3, h4⟩

theorem prop_to_constraints {P : ℝ[X]}
  (h : ∀ x ≠ (0 : ℝ), P.eval x + P.eval ((1 : ℝ) / x) = (1 : ℝ) / 2 * (P.eval (x + (1 : ℝ) / x) + P.eval (x - (1 : ℝ) / x))) :
  P.natDegree ≤ 4 ∧ P.coeff 3 = 0 ∧ P.coeff 1 = 0 ∧ P.coeff 0 = (6 : ℝ) * P.coeff 4 :=
by
  -- 1. Bound the degree
  have hdeg : P.natDegree ≤ 4 := natDegree_le_4_of_prop h

  -- 2. Obtain the polynomial equation by evaluating the coefficients
  have heq : C (P.coeff 0 - (6 : ℝ) * P.coeff 4) * X ^ 4 + C (P.coeff 1 - (3 : ℝ) * P.coeff 3) * X ^ 3 + C (P.coeff 3) * X = 0 :=
    poly_id_of_prop hdeg h

  -- 3. Extract the coefficient constraints
  have h_constraints : P.coeff 3 = 0 ∧ P.coeff 1 = 0 ∧ P.coeff 0 = (6 : ℝ) * P.coeff 4 :=
    constraints_of_eq_zero heq

  -- 4. Unpack the final components to satisfy the objective exactly
  exact ⟨hdeg, h_constraints.1, h_constraints.2.1, h_constraints.2.2⟩

theorem subset_sols :
  {P : ℝ[X] | P.Monic ∧ ∀ x ≠ 0, P.eval x + P.eval (1 / x) = 1 / 2 * (P.eval (x + 1 / x) + P.eval (x - 1 / x))}
    ⊆ {X ^ 4 + a • X ^ 2 + 6 | (a : ℝ)} ∪ {X ^ 2} :=
by
  intro P hP
  have hM : P.Monic := hP.1
  have hProp := hP.2
  have h_const := prop_to_constraints hProp
  have h_deg := h_const.1
  have h3 := h_const.2.1
  have h1 := h_const.2.2.1
  have h0 := h_const.2.2.2
  exact poly_cases hM h_deg h3 h1 h0

theorem sols_subset :
  {X ^ 4 + a • X ^ 2 + 6 | (a : ℝ)} ∪ {X ^ 2}
    ⊆ {P : ℝ[X] | P.Monic ∧ ∀ x ≠ 0, P.eval x + P.eval (1 / x) = 1 / 2 * (P.eval (x + 1 / x) + P.eval (x - 1 / x))} :=
by
  intro P hP
  cases hP with
  | inl hP =>
    rcases hP with ⟨a, rfl⟩
    constructor
    · have h_eq : X ^ 4 + a • X ^ 2 + (6 : ℝ[X]) = X ^ 4 + (C a * X ^ 2 + 6) := by
        simp only [Polynomial.smul_eq_C_mul]
        ring
      rw [h_eq]
      have hdeg : degree (C a * X ^ 2 + (6 : ℝ[X])) < degree (X ^ 4 : ℝ[X]) := by
        compute_degree
        rw [Polynomial.degree_X_pow]
        norm_num
      change (X ^ 4 + (C a * X ^ 2 + 6)).leadingCoeff = 1
      rw [Polynomial.leadingCoeff_add_of_degree_lt' hdeg]
      exact Polynomial.monic_X_pow 4
    · intro x hx
      simp [smul_eq_mul]
      field_simp
      ring
  | inr hP =>
    rw [Set.mem_singleton_iff] at hP
    subst hP
    constructor
    · exact Polynomial.monic_X_pow 2
    · intro x hx
      simp [smul_eq_mul]
      field_simp
      ring

theorem PBBasic005 : {P : ℝ[X] | P.Monic ∧ ∀ x ≠ 0, P.eval x + P.eval (1 / x)
      = 1 / 2 * (P.eval (x + 1 / x) + P.eval (x - 1 / x))}
    = {X ^ 4 + a • X ^ 2 + 6 | (a : ℝ) } ∪ {X ^ 2} :=
by
  ext P
  exact ⟨fun h => subset_sols h, fun h => sols_subset h⟩
