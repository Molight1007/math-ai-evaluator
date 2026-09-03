import Mathlib
noncomputable def K_seq (N k : ℕ) : ℚ :=
  ∑ m ∈ Finset.Icc 1 N, if (2:ℕ)^k ∣ m then (1:ℚ) else (0:ℚ)

-- Lemma 1: Rewriting the fraction of the greatest odd divisor directly into its indicator sum form.

theorem sum_geom_half_Icc (r : ℕ) :
    ∑ k ∈ Finset.Icc 1 r, (1 : ℚ) / (2 : ℚ)^k = (1 : ℚ) - (1 : ℚ) / (2 : ℚ)^r :=
by
  induction r with
  | zero => simp
  | succ r ih =>
    change ∑ k ∈ Finset.Icc 1 (r + 1), (1 : ℚ) / (2 : ℚ)^k = (1 : ℚ) - (1 : ℚ) / (2 : ℚ)^(r + 1)
    have h_le : 1 ≤ r + 1 := by omega
    rw [Finset.sum_Icc_succ_top h_le]
    rw [ih]
    have heq : (2 : ℚ) ^ (r + 1) = (2 : ℚ) ^ r * (2 : ℚ) := by rw [pow_add, pow_one]
    rw [heq]
    have hx : (2 : ℚ) ^ r ≠ 0 := by positivity
    have hx2 : (2 : ℚ) ^ r * (2 : ℚ) ≠ 0 := by positivity
    field_simp
    ring

theorem sum_ite_dvd_eq_sum_Icc (n N : ℕ) (hn : n ∈ Finset.Icc 1 N) :
    ∑ k ∈ Finset.Icc 1 N, (if (2 : ℕ)^k ∣ n then (1 : ℚ) else (0 : ℚ)) / (2 : ℚ)^k =
    ∑ k ∈ Finset.Icc 1 (padicValNat 2 n), (1 : ℚ) / (2 : ℚ)^k :=
by
  have inst : Fact (Nat.Prime 2) := ⟨Nat.prime_two⟩
  have hn_pos : 0 < n := by
    have h1 := (Finset.mem_Icc.mp hn).1
    omega
  have hn0 : n ≠ 0 := by omega

  have h_pos_pow : ∀ v : ℕ, 1 ≤ (2 : ℕ) ^ v := by
    intro v
    induction v with
    | zero =>
      have h0 : (2 : ℕ) ^ 0 = 1 := rfl
      omega
    | succ v ih =>
      have h_eq : (2 : ℕ) ^ (v + 1) = (2 : ℕ) ^ v * 2 := by rw [Nat.pow_succ]
      omega

  have h_le_pow : ∀ v : ℕ, v ≤ (2 : ℕ) ^ v := by
    intro v
    induction v with
    | zero => exact Nat.zero_le _
    | succ v ih =>
      have h1 := h_pos_pow v
      have h_eq : (2 : ℕ) ^ (v + 1) = (2 : ℕ) ^ v * 2 := by rw [Nat.pow_succ]
      omega

  -- Use the correct Mathlib 4 term `padicValNat_dvd_iff_le`
  have hdvd : (2:ℕ) ^ padicValNat 2 n ∣ n := by
    exact (padicValNat_dvd_iff_le hn0).mpr (Nat.le_refl _)
  have hle : (2:ℕ) ^ padicValNat 2 n ≤ n := Nat.le_of_dvd hn_pos hdvd
  have h_pow : padicValNat 2 n ≤ (2:ℕ) ^ padicValNat 2 n := h_le_pow (padicValNat 2 n)
  have hn_le : n ≤ N := (Finset.mem_Icc.mp hn).2

  have hs : Finset.Icc 1 (padicValNat 2 n) ⊆ Finset.Icc 1 N := by
    intro k hk
    rw [Finset.mem_Icc] at hk ⊢
    omega

  -- First, we trim the upper bounds to the p-adic valuation bound where items are 0.
  have eq1 : ∑ k ∈ Finset.Icc 1 (padicValNat 2 n), (if (2:ℕ)^k ∣ n then (1:ℚ) else (0:ℚ)) / (2:ℚ)^k =
             ∑ k ∈ Finset.Icc 1 N, (if (2:ℕ)^k ∣ n then (1:ℚ) else (0:ℚ)) / (2:ℚ)^k := by
    apply Finset.sum_subset hs
    intro x hx_s2 hx_not_s1
    have h_pos : 1 ≤ x := (Finset.mem_Icc.mp hx_s2).1
    have h_not : ¬(x ≤ padicValNat 2 n) := by
      intro h_le
      apply hx_not_s1
      rw [Finset.mem_Icc]
      exact ⟨h_pos, h_le⟩
    have hndvd : ¬ ((2:ℕ)^x ∣ n) := by
      intro hdvd_x
      have H := (padicValNat_dvd_iff_le hn0).mp hdvd_x
      exact h_not H
    have h_if : (if (2:ℕ)^x ∣ n then (1:ℚ) else (0:ℚ)) = (0:ℚ) := if_neg hndvd
    rw [h_if, zero_div]

  -- Then we simplify the indicator sums because the elements remaining satisfy the bounds.
  have eq2 : ∑ k ∈ Finset.Icc 1 (padicValNat 2 n), (if (2:ℕ)^k ∣ n then (1:ℚ) else (0:ℚ)) / (2:ℚ)^k =
             ∑ k ∈ Finset.Icc 1 (padicValNat 2 n), (1 : ℚ) / (2 : ℚ)^k := by
    apply Finset.sum_congr rfl
    intro x hx
    rw [Finset.mem_Icc] at hx
    have hdvd_x : (2:ℕ)^x ∣ n := by
      exact (padicValNat_dvd_iff_le hn0).mpr hx.2
    have h_if : (if (2:ℕ)^x ∣ n then (1:ℚ) else (0:ℚ)) = (1:ℚ) := if_pos hdvd_x
    rw [h_if]

  -- Merge equalities backwards
  exact (eq2.symm.trans eq1).symm

theorem exists_eq_mul_two_pow_padic (n : ℕ) : ∃ c : ℕ, n = 2 ^ padicValNat 2 n * c :=
by
  exact pow_padicValNat_dvd

theorem delta_eq_c_of_eq_mul_two_pow_padic (n c : ℕ) (hn : 0 < n) (δ : ℕ → ℕ)
    (hδ : ∀ m, δ m = (m.divisors.filter Odd).sup id)
    (h_eq : n = 2 ^ padicValNat 2 n * c) :
    δ n = c :=
by
  have hc0 : c ≠ 0 := by
    intro hc
    rw [hc] at h_eq
    simp only [mul_zero] at h_eq
    omega
  have hc_pos : 0 < c := by omega

  have h_odd : Odd c := by
    have h_cases : c % 2 = 0 ∨ c % 2 = 1 := by omega
    rcases h_cases with h0 | h1
    · exfalso
      set k := c / 2
      have hk : c = 2 * k := by omega
      have hk0 : k ≠ 0 := by omega

      haveI hp : Fact (Nat.Prime 2) := ⟨Nat.prime_two⟩
      haveI hq : Fact (Nat.Prime 3) := ⟨by norm_num⟩
      have hp_pow : ∀ m, padicValNat 2 (2 ^ m) = m := by
        intro m
        have h := padicValNat_mul_pow_left (p := 2) (q := 3) m 0 (by decide)
        rw [pow_zero, mul_one] at h
        exact h

      have h_padic : padicValNat 2 n = padicValNat 2 (2 ^ padicValNat 2 n * c) := congrArg (padicValNat 2) h_eq
      have h2pow_pos : 2 ^ padicValNat 2 n ≠ 0 := by positivity
      have hp_mul : padicValNat 2 (2 ^ padicValNat 2 n * c) = padicValNat 2 (2 ^ padicValNat 2 n) + padicValNat 2 c :=
        padicValNat.mul h2pow_pos hc0

      have hc_val2 : padicValNat 2 c = padicValNat 2 (2 * k) := congrArg (padicValNat 2) hk
      have h2_mul : padicValNat 2 (2 * k) = padicValNat 2 2 + padicValNat 2 k :=
        padicValNat.mul (by decide) hk0
      have h2_two : padicValNat 2 2 = 1 := by
        have h := hp_pow 1
        rw [pow_one] at h
        exact h

      rw [hp_mul, hp_pow] at h_padic
      rw [h2_mul, h2_two] at hc_val2
      omega
    · use c / 2
      omega

  have hc_mem : c ∈ n.divisors.filter Odd := by
    rw [Finset.mem_filter, Nat.mem_divisors]
    have hc_dvd : c ∣ n := ⟨2 ^ padicValNat 2 n, by
      calc n = 2 ^ padicValNat 2 n * c := h_eq
           _ = c * 2 ^ padicValNat 2 n := mul_comm _ _⟩
    have hn_ne : n ≠ 0 := by omega
    exact ⟨⟨hc_dvd, hn_ne⟩, h_odd⟩

  have h_le_c : ∀ x ∈ n.divisors.filter Odd, x ≤ c := by
    intro x hx
    rw [Finset.mem_filter, Nat.mem_divisors] at hx
    rcases hx with ⟨⟨hc_dvd_x, hn_ne⟩, hx_odd⟩
    rcases hc_dvd_x with ⟨m, hm⟩
    have h_eq2 : 2 ^ padicValNat 2 n * c = x * m := by
      calc 2 ^ padicValNat 2 n * c = n := h_eq.symm
           _ = x * m := hm
    have h_dvd_mul : x ∣ 2 ^ padicValNat 2 n * c := ⟨m, h_eq2⟩

    have hc_coprime : Nat.Coprime x (2 ^ padicValNat 2 n) := by
      have h2x : Nat.Coprime 2 x := by
        have h_div : Nat.gcd 2 x ∣ 2 := Nat.gcd_dvd_left 2 x
        have h_div_x : Nat.gcd 2 x ∣ x := Nat.gcd_dvd_right 2 x
        have h_le : Nat.gcd 2 x ≤ 2 := Nat.le_of_dvd (by decide) h_div
        have h_zero : Nat.gcd 2 x ≠ 0 := by
          intro hz
          rw [hz] at h_div
          rcases h_div with ⟨k, hk⟩
          simp only [zero_mul] at hk
          omega
        have h_cases : Nat.gcd 2 x = 1 ∨ Nat.gcd 2 x = 2 := by omega
        cases h_cases with
        | inl h1 => exact h1
        | inr h2 =>
          exfalso
          rw [h2] at h_div_x
          obtain ⟨kx, hkx⟩ := hx_odd
          obtain ⟨mx, hmx⟩ := h_div_x
          rw [hkx] at hmx
          omega
      have hx2 : Nat.Coprime x 2 := h2x.symm
      exact Nat.Coprime.pow_right (padicValNat 2 n) hx2

    have h_x_dvd_c : x ∣ c := Nat.Coprime.dvd_of_dvd_mul_left hc_coprime h_dvd_mul
    exact Nat.le_of_dvd hc_pos h_x_dvd_c

  rw [hδ]
  apply le_antisymm
  · exact Finset.sup_le (f := (id : ℕ → ℕ)) h_le_c
  · exact Finset.le_sup (f := (id : ℕ → ℕ)) hc_mem

theorem c_ne_zero_of_eq_mul_two_pow_padic {n c : ℕ} (hn : 0 < n) (h_eq : n = 2 ^ padicValNat 2 n * c) : c ≠ 0 :=
by
  intro hc
  subst hc
  simp at h_eq
  omega

theorem rational_eval_lemma (k c : ℕ) (hc : c ≠ 0) :
    (c : ℚ) / ((2 ^ k * c : ℕ) : ℚ) = (1 : ℚ) / (2 : ℚ) ^ k :=
by
  have hcQ : (c : ℚ) ≠ 0 := Nat.cast_ne_zero.mpr hc
  have h2 : (2 : ℚ) ≠ 0 := by norm_num
  have h2k : (2 : ℚ) ^ k ≠ 0 := pow_ne_zero k h2
  have hDenom : (2 : ℚ) ^ k * (c : ℚ) ≠ 0 := mul_ne_zero h2k hcQ
  push_cast
  field_simp [hcQ, h2k, hDenom]

theorem delta_div_n_eq_one_div_two_pow (n : ℕ) (hn : 0 < n) (δ : ℕ → ℕ)
    (hδ : ∀ m, δ m = (m.divisors.filter Odd).sup id) :
    (δ n : ℚ) / n = (1 : ℚ) / (2 : ℚ)^(padicValNat 2 n) :=
by
  -- 1. Extract the odd cofactor part of `n`
  have ⟨c, hc⟩ := exists_eq_mul_two_pow_padic n

  -- 2. Obtain key equivalence properties for substitution
  have hδn : δ n = c := delta_eq_c_of_eq_mul_two_pow_padic n c hn δ hδ hc
  have hcnz : c ≠ 0 := c_ne_zero_of_eq_mul_two_pow_padic hn hc

  -- 3. We use `congrArg` to coerce `n` carefully, strictly avoiding rewriting the `n` present in `padicValNat 2 n`
  have h_denom : (n : ℚ) = ((2 ^ padicValNat 2 n * c : ℕ) : ℚ) := congrArg (fun x : ℕ => (x : ℚ)) hc

  -- 4. Rewrite terms and resolve target via the rational algebraic lemma
  rw [hδn, h_denom]
  exact rational_eval_lemma (padicValNat 2 n) c hcnz

theorem delta_div_n_eq_sum (N n : ℕ) (hn : n ∈ Finset.Icc 1 N)
    (δ : ℕ → ℕ) (hδ : ∀ m, δ m = (m.divisors.filter Odd).sup id) :
    (δ n : ℚ) / n = (1 : ℚ) - ∑ k ∈ Finset.Icc 1 N, (if (2:ℕ)^k ∣ n then (1:ℚ) else (0:ℚ)) / (2:ℚ)^k :=
by
  have hn_pos : 0 < n := by
    have h1 := Finset.mem_Icc.mp hn
    exact h1.1
  rw [delta_div_n_eq_one_div_two_pow n hn_pos δ hδ]
  rw [sum_ite_dvd_eq_sum_Icc n N hn]
  rw [sum_geom_half_Icc]
  ring

theorem sum_sub_distrib_and_swap_K_seq (N : ℕ) :
    ∑ n ∈ Finset.Icc 1 N, ((1 : ℚ) - ∑ k ∈ Finset.Icc 1 N, (if (2:ℕ)^k ∣ n then (1:ℚ) else (0:ℚ)) / (2:ℚ)^k) =
    (N : ℚ) - ∑ k ∈ Finset.Icc 1 N, K_seq N k / (2 : ℚ)^k :=
by
  calc
    ∑ n ∈ Finset.Icc 1 N, ((1 : ℚ) - ∑ k ∈ Finset.Icc 1 N, (if (2:ℕ)^k ∣ n then (1:ℚ) else (0:ℚ)) / (2:ℚ)^k)
      = (∑ n ∈ Finset.Icc 1 N, (1 : ℚ)) - ∑ n ∈ Finset.Icc 1 N, ∑ k ∈ Finset.Icc 1 N, (if (2:ℕ)^k ∣ n then (1:ℚ) else (0:ℚ)) / (2:ℚ)^k := by
        rw [Finset.sum_sub_distrib]
    _ = (N : ℚ) - ∑ n ∈ Finset.Icc 1 N, ∑ k ∈ Finset.Icc 1 N, (if (2:ℕ)^k ∣ n then (1:ℚ) else (0:ℚ)) / (2:ℚ)^k := by
        have H : ∑ n ∈ Finset.Icc 1 N, (1 : ℚ) = (N : ℚ) := by
          rw [Finset.sum_const, Nat.card_Icc]
          have h_eq : N + 1 - 1 = N := by omega
          rw [h_eq]
          simp
        rw [H]
    _ = (N : ℚ) - ∑ k ∈ Finset.Icc 1 N, ∑ n ∈ Finset.Icc 1 N, (if (2:ℕ)^k ∣ n then (1:ℚ) else (0:ℚ)) / (2:ℚ)^k := by
        rw [Finset.sum_comm]
    _ = (N : ℚ) - ∑ k ∈ Finset.Icc 1 N, K_seq N k / (2:ℚ)^k := by
        unfold K_seq
        simp_rw [Finset.sum_div]

theorem sum_delta_div_n (δ : ℕ → ℕ) (hδ : ∀ n, δ n = (n.divisors.filter Odd).sup id) (N : ℕ) (hN : 0 < N) :
    (∑ n ∈ Finset.Icc 1 N, (δ n : ℚ) / n) = (N : ℚ) - ∑ k ∈ Finset.Icc 1 N, K_seq N k / (2 : ℚ)^k :=
by
  have h_eq : ∑ n ∈ Finset.Icc 1 N, (δ n : ℚ) / n = ∑ n ∈ Finset.Icc 1 N, ((1 : ℚ) - ∑ k ∈ Finset.Icc 1 N, (if (2:ℕ)^k ∣ n then (1:ℚ) else (0:ℚ)) / (2:ℚ)^k) := by
    refine Finset.sum_congr rfl ?_
    intro n hn
    exact delta_div_n_eq_sum N n hn δ hδ
  rw [h_eq]
  exact sum_sub_distrib_and_swap_K_seq N

theorem sum_upper_bound_lem (N : ℕ) :
  ∑ k ∈ Finset.Icc 1 N, K_seq N k / (2 : ℚ)^k ≤ (N : ℚ) / (3 : ℚ) - (N : ℚ) / ((3 : ℚ) * (4 : ℚ)^N) :=
by

  have H_card_Icc : ∀ m : ℕ, (Finset.Icc 1 m).card = m := by
    intro m
    induction' m with m ih
    · have h_emp : Finset.Icc 1 0 = ∅ := Finset.Icc_eq_empty (by omega)
      rw [h_emp, Finset.card_empty]
    · have h_union : Finset.Icc 1 (m + 1) = insert (m + 1) (Finset.Icc 1 m) := by
        ext x
        simp only [Finset.mem_Icc, Finset.mem_insert]
        omega
      have h_not_mem : m + 1 ∉ Finset.Icc 1 m := by
        simp only [Finset.mem_Icc]
        omega
      rw [h_union, Finset.card_insert_of_notMem h_not_mem, ih]

  have H_card : ∀ k ∈ Finset.Icc 1 N, (Finset.filter (fun m => (2:ℕ)^k ∣ m) (Finset.Icc 1 N)).card = N / (2:ℕ)^k := by
    intro k _
    let d := (2:ℕ)^k
    have hd : d > 0 := by positivity
    have H_image : Finset.filter (fun m => d ∣ m) (Finset.Icc 1 N) = (Finset.Icc 1 (N / d)).image (fun j => d * j) := by
      ext m
      simp only [Finset.mem_filter, Finset.mem_Icc, Finset.mem_image]
      constructor
      · rintro ⟨⟨hm1, hm2⟩, hj_div⟩
        rcases hj_div with ⟨j, hj_eq⟩
        use j
        have hj1 : 1 ≤ j := by
          by_contra! h
          have : j = 0 := by omega
          have hm0 : m = 0 := by
            calc m = d * j := hj_eq
                 _ = d * 0 := by rw [this]
                 _ = 0 := Nat.mul_zero d
          omega
        have hj2 : j ≤ N / d := by
          rw [Nat.le_div_iff_mul_le hd]
          calc j * d = d * j := Nat.mul_comm j d
               _ = m := hj_eq.symm
               _ ≤ N := hm2
        exact ⟨⟨hj1, hj2⟩, hj_eq.symm⟩
      · rintro ⟨j, ⟨hj1, hj2⟩, rfl⟩
        refine ⟨⟨?_, ?_⟩, ⟨j, rfl⟩⟩
        · have hd1 : 1 ≤ d := hd
          calc 1 ≤ j := hj1
               _ = 1 * j := (Nat.one_mul j).symm
               _ ≤ d * j := Nat.mul_le_mul_right j hd1
        · rw [Nat.mul_comm, ← Nat.le_div_iff_mul_le hd]
          exact hj2
    rw [H_image]
    have h_inj : Function.Injective (fun (j : ℕ) => d * j) := by
      intro j1 j2 heq
      exact Nat.eq_of_mul_eq_mul_left hd heq
    rw [Finset.card_image_of_injective _ h_inj]
    rw [H_card_Icc]

  have H_K_seq_eq : ∀ k ∈ Finset.Icc 1 N, K_seq N k = ((N / (2:ℕ)^k : ℕ) : ℚ) := by
    intro k hk
    unfold K_seq
    let d := (2:ℕ)^k
    calc (∑ m ∈ Finset.Icc 1 N, if d ∣ m then (1:ℚ) else 0)
      _ = ∑ m ∈ Finset.filter (fun m => d ∣ m) (Finset.Icc 1 N), (1:ℚ) := by rw [← Finset.sum_filter]
      _ = ((Finset.filter (fun m => d ∣ m) (Finset.Icc 1 N)).card : ℚ) := by simp only [Finset.sum_const, nsmul_eq_mul, mul_one]
      _ = ((N / d : ℕ) : ℚ) := by rw [H_card k hk]

  have H_K_seq_le : ∀ k ∈ Finset.Icc 1 N, K_seq N k ≤ (N:ℚ) / ((2:ℚ)^k) := by
    intro k hk
    rw [H_K_seq_eq k hk]
    have h_div_mod : (2:ℕ)^k * (N / (2:ℕ)^k) + N % (2:ℕ)^k = N := Nat.div_add_mod N ((2:ℕ)^k)
    have h_le_1 : (2:ℕ)^k * (N / (2:ℕ)^k) ≤ N := by omega
    have h_le : N / (2:ℕ)^k * (2:ℕ)^k ≤ N := by
      rw [Nat.mul_comm]
      exact h_le_1
    have h_le_q1 : (((N / (2:ℕ)^k * (2:ℕ)^k : ℕ) : ℚ)) ≤ (N : ℚ) := Nat.cast_le.mpr h_le
    have h_cast : ((N / (2:ℕ)^k : ℕ) : ℚ) * (2:ℚ)^k = (((N / (2:ℕ)^k * (2:ℕ)^k : ℕ) : ℚ)) := by push_cast; rfl
    have h_le_q : ((N / (2:ℕ)^k : ℕ) : ℚ) * (2:ℚ)^k ≤ (N : ℚ) := by
      rw [h_cast]
      exact h_le_q1
    have hd_q : (0:ℚ) < (2:ℚ)^k := by positivity
    exact (le_div_iff₀ hd_q).mpr h_le_q

  have H_sum_le : (∑ k ∈ Finset.Icc 1 N, K_seq N k / (2:ℚ)^k) ≤
      ∑ k ∈ Finset.Icc 1 N, (N:ℚ) / (4:ℚ)^k := by
    apply Finset.sum_le_sum
    intro k hk
    have h1 : K_seq N k ≤ (N:ℚ) / (2:ℚ)^k := H_K_seq_le k hk

    have h3 : K_seq N k / (2:ℚ)^k ≤ ((N:ℚ) / (2:ℚ)^k) / (2:ℚ)^k := by
      have hc : (0:ℚ) < (2:ℚ)^k := by positivity
      have hne : (2:ℚ)^k ≠ 0 := ne_of_gt hc
      rw [le_div_iff₀ hc]
      rw [div_mul_cancel₀ _ hne]
      exact h1

    have h4 : ((N:ℚ) / (2:ℚ)^k) / (2:ℚ)^k = (N:ℚ) / (4:ℚ)^k := by
      rw [div_div]
      have h_pow2 : (2:ℚ)^k * (2:ℚ)^k = (4:ℚ)^k := by
        calc (2:ℚ)^k * (2:ℚ)^k = (2 * 2 : ℚ)^k := by rw [← mul_pow]
          _ = (4:ℚ)^k := by norm_num
      rw [h_pow2]

    rwa [h4] at h3

  have H_geom_ind : ∀ n : ℕ, (∑ k ∈ Finset.Icc 1 n, (1:ℚ) / (4:ℚ)^k) = (1:ℚ)/(3:ℚ) - (1:ℚ)/ ((3:ℚ) * (4:ℚ)^n) := by
    intro n
    induction' n with n ih
    · have h_emp : Finset.Icc 1 0 = ∅ := Finset.Icc_eq_empty (by omega)
      rw [h_emp]
      simp only [Finset.sum_empty, Nat.zero_eq, pow_zero, mul_one]
      norm_num
    · have h_union : Finset.Icc 1 (n + 1) = insert (n + 1) (Finset.Icc 1 n) := by
        ext x
        simp only [Finset.mem_Icc, Finset.mem_insert]
        omega
      have h_not_mem : n + 1 ∉ Finset.Icc 1 n := by
        simp only [Finset.mem_Icc]
        omega
      rw [h_union, Finset.sum_insert h_not_mem, ih]
      have h_pow_eq : (4:ℚ)^(n+1) = (4:ℚ)^n * (4:ℚ) := by
        rw [pow_add, pow_one]
      rw [h_pow_eq]
      have h1 : (4:ℚ)^n * (4:ℚ) ≠ 0 := by positivity
      have h2 : (3:ℚ) * (4:ℚ)^n ≠ 0 := by positivity
      have h3 : (3:ℚ) * ((4:ℚ)^n * (4:ℚ)) ≠ 0 := by positivity
      have h4 : (3:ℚ) ≠ 0 := by norm_num
      field_simp
      ring

  have H_sum_eq : (∑ k ∈ Finset.Icc 1 N, (N:ℚ) / (4:ℚ)^k) =
      (N:ℚ) * ∑ k ∈ Finset.Icc 1 N, (1:ℚ) / (4:ℚ)^k := by
    rw [Finset.mul_sum]
    refine Finset.sum_congr rfl ?_
    intro x _
    ring

  calc (∑ k ∈ Finset.Icc 1 N, K_seq N k / (2:ℚ)^k) ≤ ∑ k ∈ Finset.Icc 1 N, (N:ℚ) / (4:ℚ)^k := H_sum_le
    _ = (N:ℚ) * ∑ k ∈ Finset.Icc 1 N, (1:ℚ) / (4:ℚ)^k := H_sum_eq
    _ = (N:ℚ) * ((1:ℚ)/(3:ℚ) - (1:ℚ)/ ((3:ℚ) * (4:ℚ)^N)) := by rw [H_geom_ind N]
    _ = (N:ℚ) / (3:ℚ) - (N:ℚ) / ((3:ℚ) * (4:ℚ)^N) := by ring

theorem sum_lower_bound_lem (N : ℕ) (hN : 0 < N) :
  (N : ℚ) / (3 : ℚ) - (N : ℚ) / ((3 : ℚ) * (4 : ℚ)^N) - (1 : ℚ) + (1 : ℚ) / (2 : ℚ)^N <
  ∑ k ∈ Finset.Icc 1 N, K_seq N k / (2 : ℚ)^k :=
by

  -- Establish the fundamental counting bounds on the indicator sum in ℕ
  have H_nat : ∀ n k : ℕ, (∑ x ∈ Finset.Icc 1 n, if 2^k ∣ x then 1 else 0) * 2^k ≤ n ∧
                           n < (∑ x ∈ Finset.Icc 1 n, if 2^k ∣ x then 1 else 0) * 2^k + 2^k := by
    intro n k
    induction' n with d hd
    · have hc : 0 < 2^k := by positivity
      simp [hc]
    · rcases hd with ⟨h1, h2⟩
      have h_le : 1 ≤ d + 1 := Nat.succ_le_succ (Nat.zero_le d)
      have hsum : (∑ x ∈ Finset.Icc 1 (d + 1), if 2^k ∣ x then 1 else 0) =
                  (∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) + if 2^k ∣ d + 1 then 1 else 0 :=
        Finset.sum_Icc_succ_top h_le _
      rw [hsum]
      by_cases hc : 2^k ∣ d + 1
      · rw [if_pos hc]
        rcases hc with ⟨m, hm⟩
        have h_lt : (∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) * 2^k < m * 2^k := by
          calc _ ≤ d := h1
               _ < d + 1 := by omega
               _ = 2^k * m := hm
               _ = m * 2^k := mul_comm _ _
        have hc_pos : 0 < 2^k := by positivity
        have h_lt_div : (∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) < m := (Nat.mul_lt_mul_right hc_pos).mp h_lt
        have h_le_div : (∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) + 1 ≤ m := h_lt_div
        have h_le_mul : ((∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) + 1) * 2^k ≤ m * 2^k :=
          Nat.mul_le_mul_right (2^k) h_le_div
        have h_eq : ((∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) + 1) * 2^k = d + 1 := by
          apply le_antisymm
          · calc ((∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) + 1) * 2^k ≤ m * 2^k := h_le_mul
                 _ = 2^k * m := mul_comm _ _
                 _ = d + 1 := hm.symm
          · calc d + 1 ≤ (∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) * 2^k + 2^k := h2
                 _ = ((∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) + 1) * 2^k := by ring
        constructor
        · exact le_of_eq h_eq
        · rw [h_eq]
          exact lt_add_of_pos_right _ hc_pos
      · rw [if_neg hc, add_zero]
        constructor
        · omega
        · have h_neq : d + 1 ≠ (∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) * 2^k + 2^k := by
            intro contra
            have h_dvd : 2^k ∣ d + 1 := by
              use ((∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) + 1)
              calc d + 1 = (∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) * 2^k + 2^k := contra
                   _ = ((∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) + 1) * 2^k := by ring
                   _ = 2^k * ((∑ x ∈ Finset.Icc 1 d, if 2^k ∣ x then 1 else 0) + 1) := mul_comm _ _
            exact hc h_dvd
          omega

  -- Bridge the strict natural number bound up to ℚ
  have H_rat : ∀ n k : ℕ, (n : ℚ) / (2:ℚ)^k - 1 < K_seq n k := by
    intro n k
    have h_K : K_seq n k = ((∑ x ∈ Finset.Icc 1 n, if 2^k ∣ x then 1 else 0 : ℕ) : ℚ) := by
      unfold K_seq
      simp only [Nat.cast_sum, Nat.cast_ite, Nat.cast_one, Nat.cast_zero]
    rw [h_K]
    have h_nat := (H_nat n k).2
    have h2_rat : (n : ℚ) < ((∑ x ∈ Finset.Icc 1 n, if 2^k ∣ x then 1 else 0 : ℕ) : ℚ) * (2:ℚ)^k + (2:ℚ)^k := by
      calc (n : ℚ) = ((n : ℕ) : ℚ) := by rfl
           _ < (((∑ x ∈ Finset.Icc 1 n, if 2^k ∣ x then 1 else 0) * 2^k + 2^k : ℕ) : ℚ) := Nat.cast_lt.mpr h_nat
           _ = ((∑ x ∈ Finset.Icc 1 n, if 2^k ∣ x then 1 else 0 : ℕ) : ℚ) * (2:ℚ)^k + (2:ℚ)^k := by push_cast; ring
    have h_pos : (0:ℚ) < (2:ℚ)^k := by positivity
    have h3_rat : (n : ℚ) / (2:ℚ)^k < ((∑ x ∈ Finset.Icc 1 n, if 2^k ∣ x then 1 else 0 : ℕ) : ℚ) + 1 := by
      rw [div_lt_iff₀ h_pos]
      calc (n : ℚ) < ((∑ x ∈ Finset.Icc 1 n, if 2^k ∣ x then 1 else 0 : ℕ) : ℚ) * (2:ℚ)^k + (2:ℚ)^k := h2_rat
           _ = (((∑ x ∈ Finset.Icc 1 n, if 2^k ∣ x then 1 else 0 : ℕ) : ℚ) + 1) * (2:ℚ)^k := by ring
    linarith

  -- Divide by 2^k properly formatted
  have h_bound : ∀ k ∈ Finset.Icc 1 N, (N : ℚ) / (4:ℚ)^k - (1:ℚ) / (2:ℚ)^k < K_seq N k / (2:ℚ)^k := by
    intro k _
    have h1 := H_rat N k
    have h_pos : (0:ℚ) < (2:ℚ)^k := by positivity
    have h2 : ((N : ℚ) / (2:ℚ)^k - 1) / (2:ℚ)^k < K_seq N k / (2:ℚ)^k := by
      rw [div_lt_iff₀ h_pos]
      have h_cancel : K_seq N k / (2:ℚ)^k * (2:ℚ)^k = K_seq N k := div_mul_cancel₀ _ (ne_of_gt h_pos)
      rw [h_cancel]
      exact h1
    have h3 : ((N : ℚ) / (2:ℚ)^k - 1) / (2:ℚ)^k = (N : ℚ) / (4:ℚ)^k - (1:ℚ) / (2:ℚ)^k := by
      have h2k : (2:ℚ)^k * (2:ℚ)^k = (4:ℚ)^k := by rw [← mul_pow]; norm_num
      calc ((N : ℚ) / (2:ℚ)^k - 1) / (2:ℚ)^k
         = ((N : ℚ) / (2:ℚ)^k) / (2:ℚ)^k - 1 / (2:ℚ)^k := sub_div _ _ _
       _ = (N : ℚ) / ((2:ℚ)^k * (2:ℚ)^k) - 1 / (2:ℚ)^k := by rw [div_div]
       _ = (N : ℚ) / (4:ℚ)^k - (1:ℚ) / (2:ℚ)^k := by rw [h2k]
    rwa [h3] at h2

  -- Geometric series bounds evaluations over Finset.Icc 1 M directly
  have h_geom2 : ∀ M : ℕ, ∑ k ∈ Finset.Icc 1 M, (1:ℚ)/(2:ℚ)^k = 1 - (1:ℚ)/(2:ℚ)^M := by
    intro M
    induction' M with d hd
    · simp
    · have h1 : 1 ≤ d + 1 := Nat.succ_le_succ (Nat.zero_le d)
      rw [Finset.sum_Icc_succ_top h1, hd]
      have hpow : (2:ℚ)^(d + 1) = (2:ℚ)^d * 2 := by rw [pow_add, pow_one]
      calc 1 - 1 / (2:ℚ)^d + 1 / (2:ℚ)^(d + 1)
         = 1 - 1 / (2:ℚ)^d + 1 / ((2:ℚ)^d * 2) := by rw [hpow]
       _ = 1 - 1 / ((2:ℚ)^d * 2) := by ring
       _ = 1 - 1 / (2:ℚ)^(d + 1) := by rw [hpow]

  have h_geom4 : ∀ M : ℕ, ∑ k ∈ Finset.Icc 1 M, (1:ℚ)/(4:ℚ)^k = (1:ℚ)/3 - (1:ℚ)/(3 * (4:ℚ)^M) := by
    intro M
    induction' M with d hd
    · simp
    · have h1 : 1 ≤ d + 1 := Nat.succ_le_succ (Nat.zero_le d)
      rw [Finset.sum_Icc_succ_top h1, hd]
      have hpow : (4:ℚ)^(d+1) = (4:ℚ)^d * 4 := by rw [pow_add, pow_one]
      calc (1:ℚ)/3 - 1 / (3 * (4:ℚ)^d) + 1 / (4:ℚ)^(d+1)
         = (1:ℚ)/3 - 1 / (3 * (4:ℚ)^d) + 1 / ((4:ℚ)^d * 4) := by rw [hpow]
       _ = (1:ℚ)/3 - 1 / (3 * ((4:ℚ)^d * 4)) := by ring
       _ = (1:ℚ)/3 - 1 / (3 * (4:ℚ)^(d+1)) := by rw [hpow]

  -- Formulate the target sum
  have h_sum_lt : ∑ k ∈ Finset.Icc 1 N, ((N : ℚ) / (4:ℚ)^k - (1:ℚ) / (2:ℚ)^k) < ∑ k ∈ Finset.Icc 1 N, K_seq N k / (2:ℚ)^k := by
    apply Finset.sum_lt_sum
    · intro i hi
      exact le_of_lt (h_bound i hi)
    · use 1
      have h1N : 1 ≤ N := hN
      have hmem : 1 ∈ Finset.Icc 1 N := Finset.mem_Icc.mpr ⟨le_refl 1, h1N⟩
      exact ⟨hmem, h_bound 1 hmem⟩

  have h_split : ∑ k ∈ Finset.Icc 1 N, ((N : ℚ) / (4:ℚ)^k - (1:ℚ) / (2:ℚ)^k) =
      (N : ℚ) * (∑ k ∈ Finset.Icc 1 N, (1:ℚ) / (4:ℚ)^k) - (∑ k ∈ Finset.Icc 1 N, (1:ℚ) / (2:ℚ)^k) := by
    rw [Finset.sum_sub_distrib]

    -- Correctly applying equivalence & pulling out the product reliably.
    have h_mul : ∑ k ∈ Finset.Icc 1 N, (N : ℚ) / (4:ℚ)^k = (N : ℚ) * ∑ k ∈ Finset.Icc 1 N, (1:ℚ) / (4:ℚ)^k := by
      have h_eq : ∀ k ∈ Finset.Icc 1 N, (N : ℚ) / (4:ℚ)^k = ((1:ℚ) / (4:ℚ)^k) * (N : ℚ) := by
        intro k _
        ring
      rw [Finset.sum_congr rfl h_eq]
      rw [← Finset.sum_mul]
      ring
    rw [h_mul]

  -- Conclude the proof by algebraic combination
  rw [h_geom4 N, h_geom2 N] at h_split
  have h_final : (N : ℚ) * ((1:ℚ)/3 - (1:ℚ)/(3 * (4:ℚ)^N)) - (1 - (1:ℚ)/(2:ℚ)^N) =
                 (N : ℚ) / (3 : ℚ) - (N : ℚ) / ((3 : ℚ) * (4 : ℚ)^N) - (1 : ℚ) + (1 : ℚ) / (2 : ℚ)^N := by ring
  rw [h_final] at h_split
  rw [← h_split]
  exact h_sum_lt

theorem sum_k_bounds (N : ℕ) (hN : 0 < N) :
    ∑ k ∈ Finset.Icc 1 N, K_seq N k / (2 : ℚ)^k ≤ (N : ℚ) / (3 : ℚ) - (N : ℚ) / ((3 : ℚ) * (4 : ℚ)^N) ∧
    (N : ℚ) / (3 : ℚ) - (N : ℚ) / ((3 : ℚ) * (4 : ℚ)^N) - (1 : ℚ) + (1 : ℚ) / (2 : ℚ)^N < ∑ k ∈ Finset.Icc 1 N, K_seq N k / (2 : ℚ)^k :=
⟨sum_upper_bound_lem N, sum_lower_bound_lem N hN⟩

theorem N_bound_helper (N : ℕ) :
    (0 : ℚ) ≤ (N : ℚ) / ((3 : ℚ) * (4 : ℚ)^N) ∧ (N : ℚ) / ((3 : ℚ) * (4 : ℚ)^N) < (1 : ℚ) / (2 : ℚ)^N :=
by
  constructor
  · positivity
  · have hN : (N : ℚ) < (3 : ℚ) * (2 : ℚ)^N := by
      induction N with
      | zero => norm_num
      | succ n ih =>
        have h1 : (1 : ℚ) ≤ (2 : ℚ)^n := by
          clear ih -- Clear the outer hypothesis so it isn't generalized into an implication
          induction n with
          | zero => norm_num
          | succ k ih_inner =>
            rw [pow_succ]
            linarith
        push_cast
        rw [pow_succ]
        linarith

    have h4 : (4 : ℚ)^N = (2 : ℚ)^N * (2 : ℚ)^N := by
      have h22 : (4 : ℚ) = (2 : ℚ) * (2 : ℚ) := by norm_num
      rw [h22, mul_pow]

    have h_pos34_inv : (0 : ℚ) < ((3 : ℚ) * (4 : ℚ)^N)⁻¹ := by positivity

    have h_div : (N : ℚ) / ((3 : ℚ) * (4 : ℚ)^N) < ((3 : ℚ) * (2 : ℚ)^N) / ((3 : ℚ) * (4 : ℚ)^N) := by
      calc (N : ℚ) / ((3 : ℚ) * (4 : ℚ)^N) = (N : ℚ) * ((3 : ℚ) * (4 : ℚ)^N)⁻¹ := by rw [div_eq_mul_inv]
        _ < ((3 : ℚ) * (2 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N)⁻¹ := mul_lt_mul_of_pos_right hN h_pos34_inv
        _ = ((3 : ℚ) * (2 : ℚ)^N) / ((3 : ℚ) * (4 : ℚ)^N) := by rw [← div_eq_mul_inv]

    have hB : (3 : ℚ) * (4 : ℚ)^N ≠ 0 := by positivity
    have hD : (2 : ℚ)^N ≠ 0 := by positivity

    have h_LHS : (((3 : ℚ) * (2 : ℚ)^N) / ((3 : ℚ) * (4 : ℚ)^N)) * ((3 : ℚ) * (4 : ℚ)^N) = (3 : ℚ) * (2 : ℚ)^N := by
      calc (((3 : ℚ) * (2 : ℚ)^N) / ((3 : ℚ) * (4 : ℚ)^N)) * ((3 : ℚ) * (4 : ℚ)^N)
        _ = (((3 : ℚ) * (2 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N)⁻¹) * ((3 : ℚ) * (4 : ℚ)^N) := by rw [div_eq_mul_inv]
        _ = ((3 : ℚ) * (2 : ℚ)^N) * (((3 : ℚ) * (4 : ℚ)^N)⁻¹ * ((3 : ℚ) * (4 : ℚ)^N)) := by rw [mul_assoc]
        _ = ((3 : ℚ) * (2 : ℚ)^N) * 1 := by
          have h_inv : ((3 : ℚ) * (4 : ℚ)^N)⁻¹ * ((3 : ℚ) * (4 : ℚ)^N) = 1 := inv_mul_cancel₀ hB
          rw [h_inv]
        _ = (3 : ℚ) * (2 : ℚ)^N := by rw [mul_one]

    have h_RHS : ((1 : ℚ) / (2 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N) = (3 : ℚ) * (2 : ℚ)^N := by
      calc ((1 : ℚ) / (2 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N)
        _ = ((1 : ℚ) / (2 : ℚ)^N) * ((3 : ℚ) * ((2 : ℚ)^N * (2 : ℚ)^N)) := by rw [h4]
        _ = (1 : ℚ) * ((2 : ℚ)^N)⁻¹ * ((3 : ℚ) * ((2 : ℚ)^N * (2 : ℚ)^N)) := by rw [div_eq_mul_inv]
        _ = (1 : ℚ) * (3 : ℚ) * (((2 : ℚ)^N)⁻¹ * (2 : ℚ)^N) * (2 : ℚ)^N := by ring
        _ = (1 : ℚ) * (3 : ℚ) * 1 * (2 : ℚ)^N := by
          have h_inv : ((2 : ℚ)^N)⁻¹ * (2 : ℚ)^N = 1 := inv_mul_cancel₀ hD
          rw [h_inv]
        _ = (3 : ℚ) * (2 : ℚ)^N := by ring

    have h_eq_mul : (((3 : ℚ) * (2 : ℚ)^N) / ((3 : ℚ) * (4 : ℚ)^N)) * ((3 : ℚ) * (4 : ℚ)^N) = ((1 : ℚ) / (2 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N) := by
      rw [h_LHS, h_RHS]

    have h_eq : ((3 : ℚ) * (2 : ℚ)^N) / ((3 : ℚ) * (4 : ℚ)^N) = (1 : ℚ) / (2 : ℚ)^N := by
      calc ((3 : ℚ) * (2 : ℚ)^N) / ((3 : ℚ) * (4 : ℚ)^N)
        _ = (((3 : ℚ) * (2 : ℚ)^N) / ((3 : ℚ) * (4 : ℚ)^N)) * (((3 : ℚ) * (4 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N)⁻¹) := by
          have h_inv : ((3 : ℚ) * (4 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N)⁻¹ = 1 := mul_inv_cancel₀ hB
          rw [h_inv, mul_one]
        _ = (((3 : ℚ) * (2 : ℚ)^N) / ((3 : ℚ) * (4 : ℚ)^N)) * ((3 : ℚ) * (4 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N)⁻¹ := by rw [← mul_assoc]
        _ = ((1 : ℚ) / (2 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N)⁻¹ := by rw [h_eq_mul]
        _ = ((1 : ℚ) / (2 : ℚ)^N) * (((3 : ℚ) * (4 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N)⁻¹) := by rw [mul_assoc]
        _ = ((1 : ℚ) / (2 : ℚ)^N) * 1 := by
          have h_inv : ((3 : ℚ) * (4 : ℚ)^N) * ((3 : ℚ) * (4 : ℚ)^N)⁻¹ = 1 := mul_inv_cancel₀ hB
          rw [h_inv]
        _ = (1 : ℚ) / (2 : ℚ)^N := by rw [mul_one]

    rw [h_eq] at h_div
    exact h_div

theorem PBBasic019 (δ : ℕ → ℕ) (hδ : ∀ n, δ n = (n.divisors.filter Odd).sup id)
    (N : ℕ) (hN : 0 < N) : |∑ n ∈ Finset.Icc 1 N, (δ n : ℚ) / n - 2 / 3 * N| < 1 :=
by
  have H_eq := sum_delta_div_n δ hδ N hN
  have ⟨H_up, H_low⟩ := sum_k_bounds N hN
  have ⟨H_N1, H_N2⟩ := N_bound_helper N
  rw [abs_lt]
  constructor
  · linarith
  · linarith
