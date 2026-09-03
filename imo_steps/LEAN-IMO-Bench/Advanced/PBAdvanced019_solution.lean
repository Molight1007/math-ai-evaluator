import Mathlib
noncomputable def S (n : ℕ) (x : ℝ) : ℤ := ∑ k ∈ Finset.Icc 1 n, ⌊(k : ℝ) * x⌋

noncomputable def S_sum (n : ℕ) (x : ℝ) : ℤ := ∑ k ∈ Finset.Icc 1 n, ⌊(k : ℝ) * x⌋

theorem condition_iff_dvd_aux (A : ℝ → ℝ) (hA : ∀ r, A r = Int.fract (2 * r))
    (B : ℕ → ℝ → ℝ) (hB : ∀ n r, B n r = ∑ k ∈ Finset.Icc 1 n, A (k * r))
    (r : ℝ) :
    (∀ n > 0, ∃ (m : ℤ), n * (n + 1) * r - B n r = n * m) ↔
    (∀ (n : ℕ), n > 0 → (n : ℤ) ∣ S_sum n (2 * r)) :=
by
  -- Auxiliary lemma: sum of the first `n` integers evaluated within the Reals
  have h_sum2 : ∀ n : ℕ, ∑ k ∈ Finset.Icc 1 n, (k : ℝ) = (n : ℝ) * ((n : ℝ) + 1) / 2 := by
    intro n
    induction n with
    | zero =>
      have H_emp : Finset.Icc 1 0 = ∅ := Finset.Icc_eq_empty (by omega)
      rw [H_emp, Finset.sum_empty]
      push_cast
      ring
    | succ m ih =>
      have H : Finset.Icc 1 (m + 1) = Finset.Icc 1 m ∪ {m + 1} := by
        ext x
        simp only [Finset.mem_Icc, Finset.mem_union, Finset.mem_singleton]
        omega
      have H_disj : Disjoint (Finset.Icc 1 m) {m + 1} := by
        rw [Finset.disjoint_left]
        intro a ha ha2
        simp only [Finset.mem_Icc, Finset.mem_singleton] at ha ha2
        omega
      rw [H, Finset.sum_union H_disj, ih, Finset.sum_singleton]
      push_cast
      ring

  -- Auxiliary lemma: explicitly evaluated structure of B n r
  have h_B : ∀ n : ℕ, B n r = (n : ℝ) * ((n : ℝ) + 1) * r - (S_sum n (2 * r) : ℝ) := by
    intro n
    rw [hB]
    have hA_sub : ∀ k ∈ Finset.Icc 1 n, A ((k : ℝ) * r) = (k : ℝ) * (2 * r) - (⌊(k : ℝ) * (2 * r)⌋ : ℝ) := by
      intro k _
      rw [hA]
      have H1 : 2 * ((k : ℝ) * r) = (k : ℝ) * (2 * r) := by ring
      rw [H1]
      rfl
    rw [Finset.sum_congr rfl hA_sub]
    rw [Finset.sum_sub_distrib]
    have h_left : ∑ k ∈ Finset.Icc 1 n, ((k : ℝ) * (2 * r)) = (∑ k ∈ Finset.Icc 1 n, (k : ℝ)) * (2 * r) := by
      rw [← Finset.sum_mul]
    rw [h_left, h_sum2]
    have h_right : ∑ k ∈ Finset.Icc 1 n, (⌊(k : ℝ) * (2 * r)⌋ : ℝ) = (S_sum n (2 * r) : ℝ) := by
      unfold S_sum
      norm_cast
    rw [h_right]
    ring

  constructor
  · intro h n hn
    rcases h n hn with ⟨m, hm⟩
    have hm2 : (S_sum n (2 * r) : ℝ) = n * (n + 1) * r - B n r := by
      rw [h_B n]
      push_cast
      ring
    -- Transitivity combines hm2 and hm, avoiding cumbersome structural exact_mod_cast calc rewrites
    have hm3 : (S_sum n (2 * r) : ℝ) = n * m := hm2.trans hm
    exact ⟨m, by exact_mod_cast hm3⟩

  · intro h n hn
    rcases h n hn with ⟨m, hm⟩
    use m
    have h_S : (S_sum n (2 * r) : ℝ) = n * m := by
      exact_mod_cast hm
    calc
      n * (n + 1) * r - B n r = n * (n + 1) * r - ((n : ℝ) * ((n : ℝ) + 1) * r - (S_sum n (2 * r) : ℝ)) := by rw [h_B n]
      _ = (S_sum n (2 * r) : ℝ) := by push_cast; ring
      _ = n * m := h_S

theorem r_decomp (r : ℝ) : ∃ k : ℤ, ∃ y : ℝ, 2 * r = (k : ℝ) + y ∧ 0 ≤ y ∧ y < 1 :=
by
  use ⌊2 * r⌋
  use Int.fract (2 * r)
  constructor
  · exact (Int.floor_add_fract (2 * r)).symm
  · constructor
    · exact Int.fract_nonneg (2 * r)
    · exact Int.fract_lt_one (2 * r)

theorem r_int_part_even (k : ℤ) (y : ℝ) (h_y : 0 ≤ y ∧ y < 1)
  (h : ∀ n : ℕ, n > 0 → (n : ℤ) ∣ S_sum n ((k : ℝ) + y)) :
  ∃ m : ℤ, k = 2 * m :=
by
  obtain ⟨hy_ge, hy_lt⟩ := h_y

  -- Define K based on the inverse of (1 - y)
  have hy_sub : (0 : ℝ) < 1 - y := by linarith
  have h_inv : ((1 : ℤ) : ℝ) ≤ 1 / (1 - y) := by
    have : (1 : ℝ) ≤ 1 / (1 - y) := by
      rw [le_div_iff₀ hy_sub]
      linarith
    exact_mod_cast this

  set K : ℤ := ⌊1 / (1 - y)⌋
  have hK : 1 ≤ K := Int.le_floor.mpr h_inv

  have hK_le : (K : ℝ) ≤ 1 / (1 - y) := Int.floor_le (1 / (1 - y))
  have hK_lt : 1 / (1 - y) < (K : ℝ) + 1 := Int.lt_floor_add_one (1 / (1 - y))

  set K_nat := K.toNat
  have hK_eq : (K_nat : ℤ) = K := Int.toNat_of_nonneg (by linarith)
  have hK_nat_pos : K_nat ≥ 1 := by omega

  -- We smartly choose n = 2 * K_nat, avoiding powers of 2 entirely!
  set n_nat := 2 * K_nat
  have hn_gt : n_nat > K_nat := by omega
  have hn_pos : n_nat > 0 := by omega
  have hn_ge_1 : n_nat ≥ 1 := by omega
  have hn_eq : (n_nat : ℤ) = 2 * (K_nat : ℤ) := by
    have : n_nat = 2 * K_nat := rfl
    exact_mod_cast this

  have h_y_floor : ∀ j : ℕ, 1 ≤ j → j ≤ n_nat →
    ⌊(j : ℝ) * y⌋ = (j : ℤ) - 1 - if j > K_nat then (1 : ℤ) else (0 : ℤ) := by
    intro j hj1 hjn
    by_cases hjK : j > K_nat
    · have h_if : (if j > K_nat then (1 : ℤ) else (0 : ℤ)) = 1 := if_pos hjK
      rw [h_if, sub_sub]
      apply Int.floor_eq_iff.mpr
      constructor
      · have hj_bound : (j : ℤ) ≤ 2 * K := by
          calc (j : ℤ) ≤ (n_nat : ℤ) := by exact_mod_cast hjn
          _ = 2 * (K_nat : ℤ) := hn_eq
          _ = 2 * K := by rw [hK_eq]
        have h_cast : ((j : ℤ) : ℝ) ≤ ((2 * K : ℤ) : ℝ) := by exact_mod_cast hj_bound
        push_cast at h_cast
        have h_2K_le : 2 * (K : ℝ) * (1 - y) ≤ 2 := by
          have h1 : (K : ℝ) * (1 - y) ≤ 1 := (le_div_iff₀ hy_sub).mp hK_le
          linarith
        have h_j_mul_le : (j : ℝ) * (1 - y) ≤ 2 := by
          have h2 : (j : ℝ) * (1 - y) ≤ 2 * (K : ℝ) * (1 - y) := by
            have h_nonneg : 0 ≤ 1 - y := by linarith
            exact mul_le_mul_of_nonneg_right h_cast h_nonneg
          linarith
        have h_j_mul_le_exp : (j : ℝ) - (j : ℝ) * y ≤ 2 := by
          calc (j : ℝ) - (j : ℝ) * y = (j : ℝ) * (1 - y) := by ring
          _ ≤ 2 := h_j_mul_le
        push_cast
        linarith
      · have hj_b : K + 1 ≤ (j : ℤ) := by
          have h1 : K_nat + 1 ≤ j := by omega
          calc K + 1 = (K_nat : ℤ) + 1 := by rw [hK_eq]
          _ ≤ (j : ℤ) := by exact_mod_cast h1
        have h_cast : ((K + 1 : ℤ) : ℝ) ≤ ((j : ℤ) : ℝ) := by exact_mod_cast hj_b
        push_cast at h_cast
        have h_K_add_1_mul : 1 < ((K : ℝ) + 1) * (1 - y) := by
          have h_lt : 1 / (1 - y) < (K : ℝ) + 1 := hK_lt
          exact (div_lt_iff₀ hy_sub).mp h_lt
        have h_j_mul_gt : 1 < (j : ℝ) * (1 - y) := by
          have h1 : ((K : ℝ) + 1) * (1 - y) ≤ (j : ℝ) * (1 - y) := by
            have h_nonneg : 0 ≤ 1 - y := by linarith
            exact mul_le_mul_of_nonneg_right h_cast h_nonneg
          linarith
        have h_j_mul_gt_exp : 1 < (j : ℝ) - (j : ℝ) * y := by
          calc 1 < (j : ℝ) * (1 - y) := h_j_mul_gt
          _ = (j : ℝ) - (j : ℝ) * y := by ring
        push_cast
        linarith
    · have h_if : (if j > K_nat then (1 : ℤ) else (0 : ℤ)) = 0 := if_neg hjK
      rw [h_if, sub_zero]
      apply Int.floor_eq_iff.mpr
      constructor
      · have hj_b : (j : ℤ) ≤ K := by
          have h1 : j ≤ K_nat := by omega
          calc (j : ℤ) ≤ (K_nat : ℤ) := by exact_mod_cast h1
          _ = K := hK_eq
        have h_cast : ((j : ℤ) : ℝ) ≤ ((K : ℤ) : ℝ) := by exact_mod_cast hj_b
        push_cast at h_cast
        have h_j_mul_le : (j : ℝ) * (1 - y) ≤ 1 := by
          have h1 : (j : ℝ) * (1 - y) ≤ (K : ℝ) * (1 - y) := by
            have h_nonneg : 0 ≤ 1 - y := by linarith
            exact mul_le_mul_of_nonneg_right h_cast h_nonneg
          have h2 : (K : ℝ) * (1 - y) ≤ 1 := (le_div_iff₀ hy_sub).mp hK_le
          linarith
        have h_j_mul_le_exp : (j : ℝ) - (j : ℝ) * y ≤ 1 := by
          calc (j : ℝ) - (j : ℝ) * y = (j : ℝ) * (1 - y) := by ring
          _ ≤ 1 := h_j_mul_le
        push_cast
        linarith
      · have hj_pos : (j : ℝ) > 0 := by
          have h1 : 1 ≤ j := hj1
          have h2 : (1 : ℝ) ≤ (j : ℝ) := by exact_mod_cast h1
          linarith
        have h_j_y_lt : (j : ℝ) * y < (j : ℝ) := by
          have h1 : y < 1 := hy_lt
          calc
            (j : ℝ) * y < (j : ℝ) * 1 := mul_lt_mul_of_pos_left h1 hj_pos
            _ = (j : ℝ) := by ring
        push_cast
        linarith

  have h_S_sum : S_sum n_nat ((k : ℝ) + y) = ∑ j ∈ Finset.Icc 1 n_nat, ((j : ℤ) * k + (j : ℤ) - 1 - if j > K_nat then (1 : ℤ) else (0 : ℤ)) := by
    unfold S_sum
    apply Finset.sum_congr rfl
    intro j hj
    rw [Finset.mem_Icc] at hj
    have h_add : (j : ℝ) * ((k : ℝ) + y) = (j : ℝ) * y + (((j : ℤ) * k : ℤ) : ℝ) := by
      push_cast
      ring
    rw [h_add]
    have h_floor_add : ⌊(j : ℝ) * y + (((j : ℤ) * k : ℤ) : ℝ)⌋ = ⌊(j : ℝ) * y⌋ + (j : ℤ) * k := by
      exact Int.floor_add_intCast ((j : ℝ) * y) ((j : ℤ) * k)
    rw [h_floor_add, h_y_floor j hj.1 hj.2]
    ring

  have h_ones : ∀ m : ℕ, m ≥ 1 → ∑ j ∈ Finset.Icc 1 m, (1 : ℤ) = (m : ℤ) := by
    intro m
    induction m with
    | zero => intro h; omega
    | succ d hd =>
      intro hd_ge
      have h_le : 1 ≤ d + 1 := by omega
      rw [Finset.sum_Icc_succ_top h_le]
      by_cases h_d0 : d = 0
      · subst h_d0
        simp
      · have hd_pos : d ≥ 1 := by omega
        rw [hd hd_pos]
        push_cast
        ring

  have h_sum_if : ∀ m : ℕ, m ≥ 1 → ∑ j ∈ Finset.Icc 1 m, (if j > K_nat then (1 : ℤ) else (0 : ℤ)) = if m > K_nat then ((m : ℤ) - (K_nat : ℤ)) else 0 := by
    intro m
    induction m with
    | zero => intro h; omega
    | succ d hd =>
      intro hd_ge
      have h_le : 1 ≤ d + 1 := by omega
      rw [Finset.sum_Icc_succ_top h_le]
      by_cases h_d0 : d = 0
      · subst h_d0
        have h_not_gt : ¬ (1 > K_nat) := by omega
        have h1 : (if 1 > K_nat then (1:ℤ) else 0) = 0 := if_neg h_not_gt
        have h2 : (if 1 > K_nat then (((1:ℕ):ℤ) - (K_nat:ℤ)) else 0) = 0 := if_neg h_not_gt
        rw [h1, h2]
        simp
      · have hd_pos : d ≥ 1 := by omega
        rw [hd hd_pos]
        by_cases hk : d + 1 > K_nat
        · have : d > K_nat ∨ d = K_nat := by omega
          rcases this with h_gt | h_eq
          · have h1 : (if d > K_nat then ((d:ℤ) - (K_nat:ℤ)) else 0) = (d:ℤ) - (K_nat:ℤ) := if_pos h_gt
            have h2 : (if d + 1 > K_nat then (1 : ℤ) else 0) = 1 := if_pos hk
            have h3 : (if d + 1 > K_nat then (((d + 1 : ℕ) : ℤ) - (K_nat : ℤ)) else 0) = ((d + 1 : ℕ) : ℤ) - (K_nat : ℤ) := if_pos hk
            rw [h1, h2, h3]
            push_cast
            ring
          · have h_not_gt : ¬ (d > K_nat) := by omega
            have h1 : (if d > K_nat then ((d:ℤ) - (K_nat:ℤ)) else 0) = 0 := if_neg h_not_gt
            have h2 : (if d + 1 > K_nat then (1 : ℤ) else 0) = 1 := if_pos hk
            have h3 : (if d + 1 > K_nat then (((d + 1 : ℕ) : ℤ) - (K_nat : ℤ)) else 0) = ((d + 1 : ℕ) : ℤ) - (K_nat : ℤ) := if_pos hk
            rw [h1, h2, h3]
            push_cast
            omega
        · have h_not_gt : ¬ (d > K_nat) := by omega
          have h1 : (if d > K_nat then ((d:ℤ) - (K_nat:ℤ)) else 0) = 0 := if_neg h_not_gt
          have h2 : (if d + 1 > K_nat then (1 : ℤ) else 0) = 0 := if_neg hk
          have h3 : (if d + 1 > K_nat then (((d + 1 : ℕ) : ℤ) - (K_nat : ℤ)) else 0) = 0 := if_neg hk
          rw [h1, h2, h3]
          ring

  have h_sum_if_n : ∑ j ∈ Finset.Icc 1 n_nat, (if j > K_nat then (1 : ℤ) else (0 : ℤ)) = (n_nat : ℤ) - (K_nat : ℤ) := by
    rw [h_sum_if n_nat hn_ge_1, if_pos hn_gt]

  have h_sum_j : ∀ m : ℕ, m ≥ 1 → 2 * ∑ j ∈ Finset.Icc 1 m, (j : ℤ) = (m : ℤ) * ((m : ℤ) + 1) := by
    intro m
    induction m with
    | zero => intro h; omega
    | succ d hd =>
      intro hd_ge
      have h_le : 1 ≤ d + 1 := by omega
      rw [Finset.sum_Icc_succ_top h_le, mul_add]
      by_cases h_d0 : d = 0
      · subst h_d0
        simp
      · have hd_pos : d ≥ 1 := by omega
        rw [hd hd_pos]
        push_cast
        ring

  have H_sum_eval : S_sum n_nat ((k : ℝ) + y) = (k + 1) * (∑ j ∈ Finset.Icc 1 n_nat, (j : ℤ)) - (n_nat : ℤ) - ((n_nat : ℤ) - (K_nat : ℤ)) := by
    rw [h_S_sum]
    calc
      ∑ j ∈ Finset.Icc 1 n_nat, ((j : ℤ) * k + (j : ℤ) - 1 - if j > K_nat then (1 : ℤ) else (0 : ℤ))
      _ = ∑ j ∈ Finset.Icc 1 n_nat, ((k + 1) * (j : ℤ) - 1 - if j > K_nat then (1 : ℤ) else (0 : ℤ)) := by
        apply Finset.sum_congr rfl
        intro j _
        have h_poly : (j : ℤ) * k + (j : ℤ) = (k + 1) * (j : ℤ) := by ring
        rw [h_poly]
      _ = (∑ j ∈ Finset.Icc 1 n_nat, ((k + 1) * (j : ℤ) - 1)) - ∑ j ∈ Finset.Icc 1 n_nat, (if j > K_nat then (1 : ℤ) else (0 : ℤ)) := by
        rw [Finset.sum_sub_distrib]
      _ = (∑ j ∈ Finset.Icc 1 n_nat, ((k + 1) * (j : ℤ))) - (∑ j ∈ Finset.Icc 1 n_nat, (1 : ℤ)) - ∑ j ∈ Finset.Icc 1 n_nat, (if j > K_nat then (1 : ℤ) else (0 : ℤ)) := by
        have h_sub : ∑ j ∈ Finset.Icc 1 n_nat, ((k + 1) * (j : ℤ) - 1) = (∑ j ∈ Finset.Icc 1 n_nat, ((k + 1) * (j : ℤ))) - (∑ j ∈ Finset.Icc 1 n_nat, (1 : ℤ)) := by rw [Finset.sum_sub_distrib]
        rw [h_sub]
      _ = (k + 1) * (∑ j ∈ Finset.Icc 1 n_nat, (j : ℤ)) - (∑ j ∈ Finset.Icc 1 n_nat, (1 : ℤ)) - ∑ j ∈ Finset.Icc 1 n_nat, (if j > K_nat then (1 : ℤ) else (0 : ℤ)) := by
        have h_mul : ∑ j ∈ Finset.Icc 1 n_nat, ((k + 1) * (j : ℤ)) = (k + 1) * ∑ j ∈ Finset.Icc 1 n_nat, (j : ℤ) := by
          calc ∑ j ∈ Finset.Icc 1 n_nat, ((k + 1) * (j : ℤ))
            _ = ∑ j ∈ Finset.Icc 1 n_nat, ((j : ℤ) * (k + 1)) := by
              apply Finset.sum_congr rfl
              intro x _
              ring
            _ = (∑ j ∈ Finset.Icc 1 n_nat, (j : ℤ)) * (k + 1) := by rw [Finset.sum_mul]
            _ = (k + 1) * ∑ j ∈ Finset.Icc 1 n_nat, (j : ℤ) := by ring
        rw [h_mul]
      _ = (k + 1) * (∑ j ∈ Finset.Icc 1 n_nat, (j : ℤ)) - (n_nat : ℤ) - ((n_nat : ℤ) - (K_nat : ℤ)) := by
        have H_ones : ∑ j ∈ Finset.Icc 1 n_nat, (1 : ℤ) = (n_nat : ℤ) := h_ones n_nat hn_ge_1
        rw [H_ones, h_sum_if_n]

  have H_2S : 2 * S_sum n_nat ((k : ℝ) + y) = (k + 1) * (2 * ∑ j ∈ Finset.Icc 1 n_nat, (j : ℤ)) - 2 * (n_nat : ℤ) - 2 * ((n_nat : ℤ) - (K_nat : ℤ)) := by
    calc 2 * S_sum n_nat ((k : ℝ) + y)
      _ = 2 * ((k + 1) * (∑ j ∈ Finset.Icc 1 n_nat, (j : ℤ)) - (n_nat : ℤ) - ((n_nat : ℤ) - (K_nat : ℤ))) := by rw [H_sum_eval]
      _ = (k + 1) * (2 * ∑ j ∈ Finset.Icc 1 n_nat, (j : ℤ)) - 2 * (n_nat : ℤ) - 2 * ((n_nat : ℤ) - (K_nat : ℤ)) := by ring

  have H_2S_eval : 2 * S_sum n_nat ((k : ℝ) + y) = (k + 1) * (n_nat : ℤ) * ((n_nat : ℤ) + 1) - 2 * (n_nat : ℤ) - 2 * ((n_nat : ℤ) - (K_nat : ℤ)) := by
    have h_subst : 2 * ∑ j ∈ Finset.Icc 1 n_nat, (j : ℤ) = (n_nat : ℤ) * ((n_nat : ℤ) + 1) := h_sum_j n_nat hn_ge_1
    rw [H_2S, h_subst]
    ring

  by_contra h_not_even
  have h_k_mod : k % 2 = 1 := by
    have h_mod : k % 2 = 0 ∨ k % 2 = 1 := by omega
    rcases h_mod with h0 | h1
    · exfalso
      apply h_not_even
      use k / 2
      omega
    · exact h1

  set c := k / 2
  have hk_val : k = 2 * c + 1 := by omega
  have hk_plus_1 : k + 1 = 2 * (c + 1) := by linarith

  have H_2S_subst : 2 * S_sum n_nat ((k : ℝ) + y) = 2 * ((c + 1) * (n_nat : ℤ) * ((n_nat : ℤ) + 1) - (n_nat : ℤ) - ((n_nat : ℤ) - (K_nat : ℤ))) := by
    rw [H_2S_eval, hk_plus_1]
    ring

  have H_S_final : S_sum n_nat ((k : ℝ) + y) = (c + 1) * (n_nat : ℤ) * ((n_nat : ℤ) + 1) - (n_nat : ℤ) - ((n_nat : ℤ) - (K_nat : ℤ)) := by
    linarith [H_2S_subst]

  have h_div := h n_nat hn_pos
  obtain ⟨A, hA⟩ := h_div

  have h_K_div : (n_nat : ℤ) * (A - (c + 1) * ((n_nat : ℤ) + 1) + 2) = (K_nat : ℤ) := by
    have h_S : S_sum n_nat ((k : ℝ) + y) = (c + 1) * (n_nat : ℤ) * ((n_nat : ℤ) + 1) - (n_nat : ℤ) - ((n_nat : ℤ) - (K_nat : ℤ)) := H_S_final
    calc
      (n_nat : ℤ) * (A - (c + 1) * ((n_nat : ℤ) + 1) + 2)
      _ = (n_nat : ℤ) * A - (c + 1) * (n_nat : ℤ) * ((n_nat : ℤ) + 1) + 2 * (n_nat : ℤ) := by ring
      _ = S_sum n_nat ((k : ℝ) + y) - (c + 1) * (n_nat : ℤ) * ((n_nat : ℤ) + 1) + 2 * (n_nat : ℤ) := by rw [← hA]
      _ = ((c + 1) * (n_nat : ℤ) * ((n_nat : ℤ) + 1) - (n_nat : ℤ) - ((n_nat : ℤ) - (K_nat : ℤ))) - (c + 1) * (n_nat : ℤ) * ((n_nat : ℤ) + 1) + 2 * (n_nat : ℤ) := by rw [h_S]
      _ = (K_nat : ℤ) := by ring

  have h_K_div_2 : (K_nat : ℤ) * (2 * (A - (c + 1) * ((n_nat : ℤ) + 1) + 2)) = (K_nat : ℤ) * 1 := by
    calc
      (K_nat : ℤ) * (2 * (A - (c + 1) * ((n_nat : ℤ) + 1) + 2))
      _ = (2 * (K_nat : ℤ)) * (A - (c + 1) * ((n_nat : ℤ) + 1) + 2) := by ring
      _ = (n_nat : ℤ) * (A - (c + 1) * ((n_nat : ℤ) + 1) + 2) := by rw [← hn_eq]
      _ = (K_nat : ℤ) := h_K_div
      _ = (K_nat : ℤ) * 1 := by ring

  have hK_neq_zero : (K_nat : ℤ) ≠ 0 := by omega
  have h_2B : 2 * (A - (c + 1) * ((n_nat : ℤ) + 1) + 2) = 1 := mul_left_cancel₀ hK_neq_zero h_K_div_2

  omega

theorem r_frac_part_zero (k : ℤ) (y : ℝ) (m : ℤ) (hk : k = 2 * m) (h_y : 0 ≤ y ∧ y < 1)
  (h : ∀ n : ℕ, n > 0 → (n : ℤ) ∣ S_sum n ((k : ℝ) + y)) :
  y = 0 :=
by

  have h1 : ∀ j : ℕ, ⌊(j : ℝ) * ((k : ℝ) + y)⌋ = (j : ℤ) * k + ⌊(j : ℝ) * y⌋ := by
    intro j
    have h_eq : (j : ℝ) * ((k : ℝ) + y) = (j : ℝ) * y + (j : ℝ) * (k : ℝ) := by ring
    rw [h_eq, Int.floor_eq_iff]
    have h_rfl : ⌊(j : ℝ) * y⌋ = ⌊(j : ℝ) * y⌋ := rfl
    have h_floor_y := Int.floor_eq_iff.mp h_rfl
    push_cast
    constructor
    · linarith
    · linarith

  have h2 : ∀ n : ℕ, S_sum n ((k : ℝ) + y) = (∑ j ∈ Finset.Icc 1 n, (j : ℤ)) * k + S_sum n y := by
    intro n
    unfold S_sum
    have : (∑ j ∈ Finset.Icc 1 n, ⌊(j : ℝ) * ((k : ℝ) + y)⌋) = ∑ j ∈ Finset.Icc 1 n, ((j : ℤ) * k + ⌊(j : ℝ) * y⌋) := by
      apply Finset.sum_congr rfl
      intro j _
      exact h1 j
    rw [this, Finset.sum_add_distrib, ← Finset.sum_mul]

  have h_sum : ∀ n : ℕ, (∑ j ∈ Finset.Icc 1 n, (j : ℤ)) * 2 = (n : ℤ) * (n + 1 : ℤ) := by
    intro n
    induction n with
    | zero =>
      simp
    | succ n ih =>
      have h_eq : Finset.Icc 1 (n + 1) = insert (n + 1) (Finset.Icc 1 n) := by
        ext a
        simp only [Finset.mem_Icc, Finset.mem_insert]
        omega
      have h_not_mem : n + 1 ∉ Finset.Icc 1 n := by
        intro h_mem
        rw [Finset.mem_Icc] at h_mem
        omega
      rw [h_eq, Finset.sum_insert h_not_mem, add_mul, ih]
      push_cast
      ring

  have h4 : ∀ n : ℕ, n > 0 → (n : ℤ) ∣ S_sum n y := by
    intro n hn
    have hn_dvd : (n : ℤ) ∣ S_sum n ((k : ℝ) + y) := h n hn
    rw [h2 n] at hn_dvd
    have h_k_sum : (∑ j ∈ Finset.Icc 1 n, (j : ℤ)) * k = (n : ℤ) * ((n + 1 : ℤ) * m) := by
      calc (∑ j ∈ Finset.Icc 1 n, (j : ℤ)) * k
        _ = (∑ j ∈ Finset.Icc 1 n, (j : ℤ)) * (2 * m) := by rw [hk]
        _ = ((∑ j ∈ Finset.Icc 1 n, (j : ℤ)) * 2) * m := by ring
        _ = ((n : ℤ) * (n + 1 : ℤ)) * m := by rw [h_sum n]
        _ = (n : ℤ) * ((n + 1 : ℤ) * m) := by ring
    rw [h_k_sum] at hn_dvd
    have hdvd2 : (n : ℤ) ∣ (n : ℤ) * ((n + 1 : ℤ) * m) := ⟨(n + 1 : ℤ) * m, rfl⟩
    have h_sub := dvd_sub hn_dvd hdvd2
    have h_ring : (n : ℤ) * ((n + 1 : ℤ) * m) + S_sum n y - (n : ℤ) * ((n + 1 : ℤ) * m) = S_sum n y := by ring
    rw [h_ring] at h_sub
    exact h_sub

  by_contra hy_not
  have hy_pos : y > 0 := lt_of_le_of_ne h_y.1 (Ne.symm hy_not)

  have h_arch : ∃ n : ℕ, n > 0 ∧ (n : ℝ) * y ≥ 1 := by
    obtain ⟨n, hn⟩ := exists_nat_gt ((1 : ℝ) / y)
    have hy_pos_real : y > 0 := hy_pos
    have h1y : 0 < (1 : ℝ) / y := one_div_pos.mpr hy_pos_real
    have hn_pos : 0 < (n : ℝ) := lt_trans h1y hn
    have hn_pos_nat : n > 0 := by
      by_contra h_le
      have h_zero : n = 0 := by omega
      rw [h_zero] at hn_pos
      push_cast at hn_pos
      linarith
    use n, hn_pos_nat
    have h_mul : 1 < (n : ℝ) * y := by
      have h_cancel : ((1 : ℝ) / y) * y = 1 := div_mul_cancel₀ (1 : ℝ) (ne_of_gt hy_pos_real)
      have h_lt : ((1 : ℝ) / y) * y < (n : ℝ) * y := mul_lt_mul_of_pos_right hn hy_pos_real
      calc (1 : ℝ) = ((1 : ℝ) / y) * y := h_cancel.symm
        _ < (n : ℝ) * y := h_lt
    exact le_of_lt h_mul

  have h_ex_min : ∃ N : ℕ, (N > 0 ∧ (N : ℝ) * y ≥ 1) ∧ ∀ j < N, ¬(j > 0 ∧ (j : ℝ) * y ≥ 1) := by
    classical
    let P := fun n : ℕ => n > 0 ∧ (n : ℝ) * y ≥ 1
    have h_ex : ∃ n, P n := h_arch
    use Nat.find h_ex
    exact ⟨Nat.find_spec h_ex, fun j hj => Nat.find_min h_ex hj⟩

  obtain ⟨N, hN_P, hN_min⟩ := h_ex_min

  have hN_ge2 : N ≥ 2 := by
    by_contra h_lt
    have hN_pos := hN_P.1
    have h_eq_1 : N = 1 := by omega
    have h_ge_1 : (N : ℝ) * y ≥ 1 := hN_P.2
    rw [h_eq_1] at h_ge_1
    push_cast at h_ge_1
    rw [one_mul] at h_ge_1
    linarith [h_y.2]

  have h_floor_zero : ∀ j ∈ Finset.Ico 1 N, ⌊(j : ℝ) * y⌋ = 0 := by
    intro j hj
    simp only [Finset.mem_Ico] at hj
    have hj_lt_N : j < N := hj.2
    have h_not_P := hN_min j hj_lt_N
    have hj_pos : j > 0 := hj.1
    have h_lt_1 : (j : ℝ) * y < 1 := by
      by_contra h_ge
      have h_P_j : j > 0 ∧ (j : ℝ) * y ≥ 1 := ⟨hj_pos, not_lt.mp h_ge⟩
      exact h_not_P h_P_j
    have h_ge_0 : (j : ℝ) * y ≥ 0 := by
      apply mul_nonneg
      · exact Nat.cast_nonneg j
      · exact h_y.1
    rw [Int.floor_eq_iff]
    push_cast
    exact ⟨h_ge_0, by linarith⟩

  have hN_lt2 : (N : ℝ) * y < 2 := by
    obtain ⟨M, hM_eq⟩ : ∃ M : ℕ, N = M + 1 := ⟨N - 1, by omega⟩
    have hM_lt_N : M < N := by omega
    have hM_pos : M > 0 := by omega
    have h_not_P := hN_min M hM_lt_N
    have h_lt_1 : (M : ℝ) * y < 1 := by
      by_contra h_ge
      have h_P_M : M > 0 ∧ (M : ℝ) * y ≥ 1 := ⟨hM_pos, not_lt.mp h_ge⟩
      exact h_not_P h_P_M
    have h_eq : (N : ℝ) * y = (M : ℝ) * y + y := by
      calc (N : ℝ) * y = ((M + 1 : ℕ) : ℝ) * y := by rw [hM_eq]
        _ = (M : ℝ) * y + y := by push_cast; ring
    linarith [h_y.2, h_lt_1, h_eq]

  have hN_floor : ⌊(N : ℝ) * y⌋ = 1 := by
    rw [Int.floor_eq_iff]
    push_cast
    exact ⟨hN_P.2, by linarith⟩

  have h_S_N : S_sum N y = 1 := by
    unfold S_sum
    have h_split : Finset.Icc 1 N = insert N (Finset.Ico 1 N) := by
      ext a
      simp only [Finset.mem_Icc, Finset.mem_insert, Finset.mem_Ico]
      omega
    have h_not_mem : N ∉ Finset.Ico 1 N := by
      intro h_mem
      rw [Finset.mem_Ico] at h_mem
      omega
    rw [h_split, Finset.sum_insert h_not_mem]
    have h_sum_zero : (∑ k_1 ∈ Finset.Ico 1 N, ⌊(k_1 : ℝ) * y⌋) = 0 := by
      apply Finset.sum_eq_zero
      exact h_floor_zero
    rw [h_sum_zero, hN_floor]
    ring

  have h_dvd : (N : ℤ) ∣ 1 := by
    have := h4 N hN_P.1
    rw [h_S_N] at this
    exact this

  obtain ⟨c, hc⟩ := h_dvd
  have hc_pos : c > 0 := by
    by_contra h_c
    have h_c_le_0 : c ≤ 0 := by omega
    have hN_pos := hN_P.1
    have h_N_pos_int : (N : ℤ) > 0 := by omega
    have h_mul_le_0 : (N : ℤ) * c ≤ 0 := by nlinarith
    linarith [hc]

  have hc_ge_1 : 1 ≤ c := by omega
  have h_bound : (N : ℤ) * c ≥ 2 := by
    have h_N_ge_2 : (N : ℤ) ≥ 2 := by omega
    calc (N : ℤ) * c ≥ (N : ℤ) * 1 := mul_le_mul_of_nonneg_left hc_ge_1 (by omega)
      _ = (N : ℤ) := mul_one (N : ℤ)
      _ ≥ 2 := h_N_ge_2

  linarith [hc, h_bound]

theorem r_is_int_aux (r : ℝ) (h_dvd : ∀ (n : ℕ), n > 0 → (n : ℤ) ∣ S_sum n (2 * r)) :
    ∃ (m : ℤ), r = (m : ℝ) :=
by
  have h_decomp := r_decomp r
  rcases h_decomp with ⟨k, y, h_eq, h_y⟩

  have h_dvd2 : ∀ n : ℕ, n > 0 → (n : ℤ) ∣ S_sum n ((k : ℝ) + y) := by
    intro n hn
    rw [← h_eq]
    exact h_dvd n hn

  have h_even := r_int_part_even k y h_y h_dvd2
  rcases h_even with ⟨m, hm⟩

  have h_y0 := r_frac_part_zero k y m hm h_y h_dvd2

  use m
  have h_final : 2 * r = 2 * (m : ℝ) := by
    rw [h_eq, hm, h_y0]
    push_cast
    ring
  linarith

theorem r_is_int_of_eq (A : ℝ → ℝ) (hA : ∀ r, A r = Int.fract (2 * r))
    (B : ℕ → ℝ → ℝ) (hB : ∀ n r, B n r = ∑ k ∈ Finset.Icc 1 n, A (k * r))
    (r : ℝ) (h : ∀ n > 0, ∃ (m : ℤ), n * (n + 1) * r - B n r = n * m) :
    ∃ (m : ℤ), r = (m : ℝ) :=
by
  exact r_is_int_aux r ((condition_iff_dvd_aux A hA B hB r).mp h)

theorem lhs_subset (A : ℝ → ℝ) (hA : ∀ r, A r = Int.fract (2 * r))
    (B : ℕ → ℝ → ℝ) (hB : ∀ n r, B n r = ∑ k ∈ Finset.Icc 1 n, A (k * r)) :
    {r : ℝ | 0 < r ∧ ∀ n > 0, ∃ (m : ℤ), n * (n + 1) * r - B n r = n * m}
    ⊆ {(n : ℝ) | (n : ℕ) (_ : 0 < n)} :=
by
  intro r hr
  obtain ⟨hpos, heq⟩ := hr

  -- Step 1: Deduce that `r` is an integer `m_int` using the unified helper lemma
  have hint : ∃ m : ℤ, r = (m : ℝ) := r_is_int_of_eq A hA B hB r heq
  obtain ⟨m_int, hm⟩ := hint

  -- Step 2: Prove that the integer `m_int` is strictly positive by translating from the reals
  have h_m_pos : (0 : ℝ) < (m_int : ℝ) := by
    rw [← hm]
    exact hpos

  have hm_pos_int : 0 < m_int := by exact_mod_cast h_m_pos

  -- Step 3: Extract the natural number `m` robustly out of the strictly positive integer `m_int`
  have hex : ∃ m : ℕ, m_int = (m : ℤ) := by
    use m_int.toNat
    omega
  obtain ⟨m, hm_eq⟩ := hex

  -- Step 4: Show that `m` inherits strict positivity and prove that `r = (m : ℝ)`
  have hm_pos_nat : 0 < m := by
    have h_pos_cast : 0 < (m : ℤ) := by
      rw [← hm_eq]
      exact hm_pos_int
    exact_mod_cast h_pos_cast

  have hr_eq : r = (m : ℝ) := by
    rw [hm, hm_eq]
    push_cast
    rfl

  -- Step 5: Robustly supply `m` to satisfy the set builder existential structure
  simp only [Set.mem_setOf_eq]
  first
    | exact ⟨m, hm_pos_nat, hr_eq.symm⟩
    | exact ⟨m, hm_pos_nat, hr_eq⟩
    | exact ⟨m, hr_eq.symm, hm_pos_nat⟩
    | exact ⟨m, hr_eq, hm_pos_nat⟩
    | exact ⟨m, ⟨hm_pos_nat, hr_eq.symm⟩⟩
    | exact ⟨m, ⟨hm_pos_nat, hr_eq⟩⟩
    | exact ⟨m, ⟨hr_eq.symm, hm_pos_nat⟩⟩
    | exact ⟨m, ⟨hr_eq, hm_pos_nat⟩⟩

theorem rhs_subset (A : ℝ → ℝ) (hA : ∀ r, A r = Int.fract (2 * r))
    (B : ℕ → ℝ → ℝ) (hB : ∀ n r, B n r = ∑ k ∈ Finset.Icc 1 n, A (k * r)) :
    {(n : ℝ) | (n : ℕ) (_ : 0 < n)}
    ⊆ {r : ℝ | 0 < r ∧ ∀ n > 0, ∃ (m : ℤ), n * (n + 1) * r - B n r = n * m} :=
by
  intro r hr
  -- Unpack the set comprehension representations
  simp only [Set.mem_setOf_eq] at hr ⊢
  rcases hr with ⟨x, hx_pos, rfl⟩

  constructor
  · -- Prove that the real cast of the positive integer is strictly positive
    exact_mod_cast hx_pos
  · -- Prove the main equation loop for any chosen positive integer n
    intro n _

    -- First, we show that B n ↑x evaluates to 0
    have hB_zero : B n (x : ℝ) = 0 := by
      rw [hB]
      apply Finset.sum_eq_zero
      intro k _
      rw [hA]

      -- Reformulate the argument of `A` into an explicit integer cast
      have h_eq : 2 * ((k : ℝ) * (x : ℝ)) = ((2 * k * x : ℕ) : ℝ) := by
        push_cast
        ring
      rw [h_eq]

      -- Fractional part of any integer cast is 0
      exact Int.fract_natCast (2 * k * x)

    rw [hB_zero]

    -- Provide the closed-form integer witness for m
    use ((n : ℤ) + 1) * (x : ℤ)

    -- Simplify the residual real polynomial equation
    push_cast
    ring

theorem PBAdvanced019 (A : ℝ → ℝ) (hA : ∀ r, A r = Int.fract (2 * r))
    (B : ℕ → ℝ → ℝ) (hB : ∀ n r, B n r = ∑ k ∈ Finset.Icc 1 n, A (k * r)) : {r : ℝ | 0 < r ∧ ∀ n > 0, ∃ (m : ℤ), n * (n + 1) * r - B n r = n * m}
      = {(n : ℝ) | (n : ℕ) (_ : 0 < n)} :=
by
  exact Set.Subset.antisymm (lhs_subset A hA B hB) (rhs_subset A hA B hB)
