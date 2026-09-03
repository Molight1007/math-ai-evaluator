import Mathlib

theorem sum_f_ge_ind (n : ℕ) (hn : 2 ≤ n) (a b : ℕ → ℝ)
  (ha : ∀ i ∈ Finset.Icc 1 n, 0 < a i)
  (ha' : ∏ i ∈ Finset.Icc 1 n, a i = 1)
  (ha'' : MonotoneOn a (Finset.Icc 1 n))
  (hb : ∀ i, b i = 2 ^ i * (1 + a i ^ (2 ^ i))) :
  ∀ m, 1 ≤ m → m ≤ n →
    ∑ i ∈ Finset.Icc 1 m, (1:ℝ) / b i ≥
    ∑ i ∈ Finset.Ico 1 m, (1:ℝ) / (2:ℝ)^(i+1) +
    (1:ℝ) / ((2:ℝ)^m * ((1:ℝ) + (∏ i ∈ Finset.Icc 1 m, a i)^((2:ℕ)^m))) :=
by
  intro m hm1 hmn
  induction m with
  | zero => linarith
  | succ k ih =>
    by_cases hk0 : k = 0
    · subst hk0
      have h_LHS : ∑ i ∈ Finset.Icc 1 1, (1:ℝ) / b i = 1 / b 1 := by
        rw [Finset.Icc_self, Finset.sum_singleton]
      have h_RHS : ∑ i ∈ Finset.Ico 1 1, (1:ℝ) / (2:ℝ)^(i+1) = 0 := by
        rw [Finset.Ico_self, Finset.sum_empty]
      have h_prod : ∏ i ∈ Finset.Icc 1 1, a i = a 1 := by
        rw [Finset.Icc_self, Finset.prod_singleton]
      have h_eq : (1:ℝ) / b 1 = ∑ i ∈ Finset.Ico 1 1, (1:ℝ) / (2:ℝ)^(i+1) + (1:ℝ) / ((2:ℝ)^1 * (1 + (∏ i ∈ Finset.Icc 1 1, a i) ^ (2:ℕ)^1)) := by
        rw [h_RHS, h_prod, hb 1]
        ring
      rw [h_LHS]
      exact le_of_eq h_eq.symm
    · have hk1 : 1 ≤ k := by omega
      have hkn : k ≤ n := by omega
      have ih_k := ih hk1 hkn

      let x := (∏ i ∈ Finset.Icc 1 k, a i) ^ ((2:ℕ) ^ k)
      let y := a (k+1) ^ ((2:ℕ) ^ k)

      have hPk_pos : 0 < ∏ i ∈ Finset.Icc 1 k, a i := by
        apply Finset.prod_pos
        intro i hi
        apply ha i
        rw [Finset.mem_Icc] at hi ⊢
        omega

      have hx_pos : 0 ≤ x := by
        have H_base : 0 ≤ ∏ i ∈ Finset.Icc 1 k, a i := le_of_lt hPk_pos
        exact pow_nonneg H_base ((2:ℕ)^k)

      have hPk_le_one : ∏ i ∈ Finset.Icc 1 k, a i ≤ 1 := by
        by_contra! h_gt
        have h_ex : ∃ i ∈ Finset.Icc 1 k, 1 < a i := by
          by_contra! h_le
          have h1 : ∀ j ∈ Finset.Icc 1 k, (0:ℝ) ≤ a j := by
            intro j hj
            have hj_in : j ∈ Finset.Icc 1 n := by rw [Finset.mem_Icc] at hj ⊢; omega
            exact le_of_lt (ha j hj_in)
          have : ∏ i ∈ Finset.Icc 1 k, a i ≤ 1 := by
            calc
              ∏ i ∈ Finset.Icc 1 k, a i ≤ ∏ i ∈ Finset.Icc 1 k, (1:ℝ) := Finset.prod_le_prod h1 h_le
              _ = 1 := by simp
          linarith
        rcases h_ex with ⟨i, hi, hai⟩
        have hi_in : i ∈ Finset.Icc 1 n := by rw [Finset.mem_Icc] at hi ⊢; omega
        have hk_in : k ∈ Finset.Icc 1 n := by rw [Finset.mem_Icc]; omega
        have hak : (1:ℝ) < a k := lt_of_lt_of_le hai (ha'' hi_in hk_in (by rw [Finset.mem_Icc] at hi; omega))

        have h_rest_ge : 1 ≤ ∏ j ∈ Finset.Icc (k+1) n, a j := by
          have h1 : ∀ j ∈ Finset.Icc (k+1) n, (0:ℝ) ≤ 1 := fun _ _ => zero_le_one
          have h2 : ∀ j ∈ Finset.Icc (k+1) n, (1:ℝ) ≤ a j := by
            intro j hj
            have hj_in : j ∈ Finset.Icc 1 n := by rw [Finset.mem_Icc] at hj ⊢; omega
            exact le_of_lt (lt_of_lt_of_le hak (ha'' hk_in hj_in (by rw [Finset.mem_Icc] at hj; omega)))
          calc
            (1:ℝ) = ∏ j ∈ Finset.Icc (k+1) n, (1:ℝ) := by simp
            _ ≤ ∏ j ∈ Finset.Icc (k+1) n, a j := Finset.prod_le_prod h1 h2

        have h_union : Finset.Icc 1 k ∪ Finset.Icc (k+1) n = Finset.Icc 1 n := by
          ext x_eq
          simp only [Finset.mem_union, Finset.mem_Icc]
          constructor
          · rintro (⟨h1, h2⟩ | ⟨h1, h2⟩)
            · exact ⟨h1, by omega⟩
            · exact ⟨by omega, h2⟩
          · intro h_x
            by_cases hxk : x_eq ≤ k
            · left; exact ⟨h_x.1, hxk⟩
            · right; exact ⟨by omega, h_x.2⟩

        have h_disj : Disjoint (Finset.Icc 1 k) (Finset.Icc (k+1) n) := by
          rw [Finset.disjoint_left]
          intro x_eq hx hy
          rw [Finset.mem_Icc] at hx hy
          omega

        have h_split : ∏ j ∈ Finset.Icc 1 n, a j = (∏ j ∈ Finset.Icc 1 k, a j) * (∏ j ∈ Finset.Icc (k+1) n, a j) := by
          rw [← h_union, Finset.prod_union h_disj]
        rw [ha'] at h_split

        have h_contra : 1 < (∏ j ∈ Finset.Icc 1 k, a j) * (∏ j ∈ Finset.Icc (k+1) n, a j) := by
          calc
            (1:ℝ) = 1 * 1 := by ring
            _ ≤ 1 * (∏ j ∈ Finset.Icc (k+1) n, a j) := mul_le_mul_of_nonneg_left h_rest_ge zero_le_one
            _ < (∏ j ∈ Finset.Icc 1 k, a j) * (∏ j ∈ Finset.Icc (k+1) n, a j) := by
              have h_pos_rest : 0 < ∏ j ∈ Finset.Icc (k+1) n, a j := by linarith [h_rest_ge]
              exact mul_lt_mul_of_pos_right h_gt h_pos_rest
        linarith [h_split, h_contra]

      have h_pow : ∀ c : ℕ, (∏ i ∈ Finset.Icc 1 k, a i) ^ c ≤ 1 := by
        intro c
        induction c with
        | zero => simp
        | succ c ih_c =>
          have hc_pos : 0 ≤ (∏ i ∈ Finset.Icc 1 k, a i) ^ c := by
            have H_base : 0 ≤ ∏ i ∈ Finset.Icc 1 k, a i := le_of_lt hPk_pos
            exact pow_nonneg H_base c
          calc
            (∏ i ∈ Finset.Icc 1 k, a i) ^ (c + 1) = (∏ i ∈ Finset.Icc 1 k, a i) ^ c * (∏ i ∈ Finset.Icc 1 k, a i) := by rw [pow_add, pow_one]
            _ ≤ (∏ i ∈ Finset.Icc 1 k, a i) ^ c * 1 := mul_le_mul_of_nonneg_left hPk_le_one hc_pos
            _ = (∏ i ∈ Finset.Icc 1 k, a i) ^ c := mul_one _
            _ ≤ 1 := ih_c

      have hx : x ≤ 1 := h_pow ((2:ℕ)^k)

      have h_pow_succ_real : (2:ℝ)^(k+1) = (2:ℝ)^k * 2 := by rw [pow_add, pow_one]
      have H2k : (2:ℝ)^k ≠ 0 := by positivity
      have H2k_mul_2 : (2:ℝ)^k * 2 ≠ 0 := by positivity
      have H3 : (1:ℝ) + x ≠ 0 := by linarith [hx_pos]
      have H4 : (1:ℝ) + y^2 ≠ 0 := ne_of_gt (by positivity)
      have H5 : (1:ℝ) + x^2 * y^2 ≠ 0 := ne_of_gt (by positivity)

      have h_alg_eq : (1:ℝ) / ((2:ℝ)^k * (1+x)) + (1:ℝ) / ((2:ℝ)^(k+1) * (1+y^2)) - ((1:ℝ) / (2:ℝ)^(k+1) + (1:ℝ) / ((2:ℝ)^(k+1) * (1+x^2 * y^2))) =
        (1 - x) * (1 - x * y^2)^2 / ((2:ℝ)^(k+1) * (1+x) * (1+y^2) * (1+x^2 * y^2)) := by
        rw [h_pow_succ_real]
        field_simp [H2k, H2k_mul_2, H3, H4, H5]
        ring

      have h_alg_ge : (1:ℝ) / ((2:ℝ)^k * (1+x)) + (1:ℝ) / ((2:ℝ)^(k+1) * (1+y^2)) ≥ (1:ℝ) / (2:ℝ)^(k+1) + (1:ℝ) / ((2:ℝ)^(k+1) * (1+x^2 * y^2)) := by
        have h_diff_ge : 0 ≤ (1 - x) * (1 - x * y^2)^2 / ((2:ℝ)^(k+1) * (1+x) * (1+y^2) * (1+x^2 * y^2)) := by
          apply div_nonneg
          · exact mul_nonneg (by linarith [hx]) (sq_nonneg (1 - x * y^2))
          · have d2 : 0 ≤ 1 + x := by linarith [hx_pos]
            positivity
        linarith [h_alg_eq, h_diff_ge]

      have h_prod_succ : ∏ i ∈ Finset.Icc 1 (k+1), a i = (∏ i ∈ Finset.Icc 1 k, a i) * a (k+1) := by
        have H_union : Finset.Icc 1 k ∪ {k+1} = Finset.Icc 1 (k+1) := by
          ext x_eq
          simp only [Finset.mem_union, Finset.mem_Icc, Finset.mem_singleton]
          constructor
          · rintro (⟨h1, h2⟩ | h2)
            · exact ⟨h1, by omega⟩
            · subst h2; exact ⟨by omega, by omega⟩
          · intro h_x
            by_cases hxk : x_eq ≤ k
            · left; exact ⟨h_x.1, hxk⟩
            · right; omega
        have H_disj : Disjoint (Finset.Icc 1 k) {k+1} := by
          rw [Finset.disjoint_left]
          intro z hz hz_eq
          rw [Finset.mem_Icc] at hz
          rw [Finset.mem_singleton] at hz_eq
          omega
        rw [← H_union, Finset.prod_union H_disj, Finset.prod_singleton]

      have h_pow_succ_nat : (2:ℕ)^(k+1) = (2:ℕ)^k + (2:ℕ)^k := by
        rw [pow_add, pow_one]
        ring

      have h_x2y2 : (∏ i ∈ Finset.Icc 1 (k+1), a i) ^ ((2:ℕ) ^ (k+1)) = x^2 * y^2 := by
        calc
          (∏ i ∈ Finset.Icc 1 (k+1), a i) ^ ((2:ℕ) ^ (k+1)) = ((∏ i ∈ Finset.Icc 1 k, a i) * a (k+1)) ^ ((2:ℕ)^k + (2:ℕ)^k) := by rw [h_prod_succ, h_pow_succ_nat]
          _ = x^2 * y^2 := by
            rw [pow_add]
            simp only [mul_pow]
            ring

      have hb_succ : b (k+1) = (2:ℝ)^(k+1) * (1 + y^2) := by
        have hy2 : a (k+1) ^ ((2:ℕ)^(k+1)) = y^2 := by
          calc
            a (k+1) ^ ((2:ℕ)^(k+1)) = a (k+1) ^ ((2:ℕ)^k + (2:ℕ)^k) := by rw [h_pow_succ_nat]
            _ = y^2 := by
              rw [pow_add]
              ring
        rw [hb (k+1), hy2]

      have H_LHS_step : ∑ i ∈ Finset.Icc 1 (k+1), (1:ℝ) / b i = ∑ i ∈ Finset.Icc 1 k, (1:ℝ) / b i + (1:ℝ) / b (k+1) := by
        rw [Finset.sum_Icc_succ_top (by omega)]

      calc
        ∑ i ∈ Finset.Icc 1 (k+1), (1:ℝ) / b i
          = ∑ i ∈ Finset.Icc 1 k, (1:ℝ) / b i + (1:ℝ) / b (k+1) := H_LHS_step
        _ ≥ (∑ i ∈ Finset.Ico 1 k, (1:ℝ) / (2:ℝ)^(i+1) + (1:ℝ) / ((2:ℝ)^k * (1 + x))) + (1:ℝ) / b (k+1) := by
          linarith [ih_k]
        _ = ∑ i ∈ Finset.Ico 1 k, (1:ℝ) / (2:ℝ)^(i+1) + ((1:ℝ) / ((2:ℝ)^k * (1 + x)) + (1:ℝ) / ((2:ℝ)^(k+1) * (1 + y^2))) := by
          rw [hb_succ]
          ring
        _ ≥ ∑ i ∈ Finset.Ico 1 k, (1:ℝ) / (2:ℝ)^(i+1) + ((1:ℝ) / (2:ℝ)^(k+1) + (1:ℝ) / ((2:ℝ)^(k+1) * (1 + x^2 * y^2))) := by
          linarith [h_alg_ge]
        _ = (∑ i ∈ Finset.Ico 1 k, (1:ℝ) / (2:ℝ)^(i+1) + (1:ℝ) / (2:ℝ)^(k+1)) + (1:ℝ) / ((2:ℝ)^(k+1) * (1 + x^2 * y^2)) := by
          ring
        _ = ∑ i ∈ Finset.Ico 1 (k+1), (1:ℝ) / (2:ℝ)^(i+1) + (1:ℝ) / ((2:ℝ)^(k+1) * (1 + x^2 * y^2)) := by
          have H_sum : ∑ i ∈ Finset.Ico 1 (k+1), (1:ℝ) / (2:ℝ)^(i+1) = ∑ i ∈ Finset.Ico 1 k, (1:ℝ) / (2:ℝ)^(i+1) + (1:ℝ) / (2:ℝ)^(k+1) := by
            rw [Finset.sum_Ico_succ_top (by omega)]
          rw [← H_sum]
        _ = ∑ i ∈ Finset.Ico 1 (k+1), (1:ℝ) / (2:ℝ)^(i+1) + (1:ℝ) / ((2:ℝ)^(k+1) * (1 + (∏ i ∈ Finset.Icc 1 (k+1), a i)^((2:ℕ)^(k+1)))) := by
          rw [← h_x2y2]

theorem geom_sum_half (n : ℕ) (hn : 1 ≤ n) :
  ∑ i ∈ Finset.Ico 1 n, (1:ℝ) / (2:ℝ)^(i+1) = (1:ℝ) / (2:ℝ) - (1:ℝ) / (2:ℝ)^n :=
by
  have H : ∀ k, ∑ i ∈ Finset.Ico 1 (k + 1), (1:ℝ) / (2:ℝ)^(i+1) = (1:ℝ) / (2:ℝ) - (1:ℝ) / (2:ℝ)^(k+1) := by
    intro k
    induction k with
    | zero =>
      simp
    | succ k ih =>
      have hle : 1 ≤ k + 1 := by omega
      rw [Finset.sum_Ico_succ_top hle]
      rw [ih]
      have h_pow : (2 : ℝ) ^ (k + 1 + 1) = (2 : ℝ) ^ (k + 1) * 2 := by
        calc (2 : ℝ) ^ (k + 1 + 1)
          _ = (2 : ℝ) ^ (k + 1) * (2 : ℝ) ^ 1 := by rw [pow_add]
          _ = (2 : ℝ) ^ (k + 1) * 2 := by rw [pow_one]
      rw [h_pow]
      have h2 : (2 : ℝ) ≠ 0 := by norm_num
      have hk : (2 : ℝ) ^ (k + 1) ≠ 0 := by positivity
      have hk2 : (2 : ℝ) ^ (k + 1) * 2 ≠ 0 := by positivity
      field_simp [h2, hk, hk2]
      ring
  cases n with
  | zero => omega
  | succ k => exact H k

theorem final_alg_simp (n : ℕ) :
  (1:ℝ) / (2:ℝ) - (1:ℝ) / (2:ℝ)^n + (1:ℝ) / ((2:ℝ)^n * ((1:ℝ) + (1:ℝ)^((2:ℕ)^n))) =
  (1:ℝ) / (2:ℝ) - (1:ℝ) / (2:ℝ) ^ (n + 1) :=
by
  -- 1 raised to any natural number is 1
  have h_one : (1:ℝ) ^ ((2:ℕ) ^ n) = (1:ℝ) := by rw [one_pow]
  rw [h_one]

  -- Express 2^(n + 1) as 2^n * 2 to match the denominator shapes
  have h_pow : (2:ℝ) ^ (n + 1) = (2:ℝ) ^ n * (2:ℝ) := by
    rw [pow_add, pow_one]
  rw [h_pow]

  -- Simplify the explicit addition 1 + 1 = 2
  have h_add : (1:ℝ) + (1:ℝ) = (2:ℝ) := by norm_num
  rw [h_add]

  -- Verify all encountered denominators are strictly non-zero
  -- in order to clear out fractions
  have h1 : (2:ℝ) ≠ 0 := by norm_num
  have h2 : (2:ℝ) ^ n ≠ 0 := by positivity
  have h3 : (2:ℝ) ^ n * (2:ℝ) ≠ 0 := by positivity

  -- Clear all denominators using field simplification
  field_simp [h1, h2, h3]

  -- After denominators are fully cleared, it reduces to a basic polynomial equality
  ring

theorem PBAdvanced013 (n : ℕ) (hn : 2 ≤ n) (a b : ℕ → ℝ)
    (ha : ∀ i ∈ Finset.Icc 1 n, 0 < a i)
    (ha' : ∏ i ∈ Finset.Icc 1 n, a i = 1)
    (ha'' : MonotoneOn a (Finset.Icc 1 n))
    (hb : ∀ i, b i = 2 ^ i * (1 + a i ^ (2 ^ i))) : 1 / 2 - 1 / 2 ^ (n + 1) ≤ ∑ i ∈ Finset.Icc 1 n, 1 / b i :=
by
  have hn1 : 1 ≤ n := by linarith
  have h1 := sum_f_ge_ind n hn a b ha ha' ha'' hb n hn1 (by linarith)
  have h2 := geom_sum_half n hn1
  rw [ha'] at h1
  rw [h2] at h1
  have h3 := final_alg_simp n
  rw [h3] at h1
  exact h1
