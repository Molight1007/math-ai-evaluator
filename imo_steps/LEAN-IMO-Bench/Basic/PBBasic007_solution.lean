import Mathlib
open Polynomial
def max_coeff_prop (f : ℤ[X]) (n : ℕ) (M : ℤ) : Prop :=
  (∀ i < n, |f.coeff i| ≤ M) ∧ (∃ k < n, |f.coeff k| = M)

theorem target_poly_in_set :
  (3 * X ^ 2 + 1 * X - 1 : ℤ[X]) ∈
  { f : ℤ[X] | f.leadingCoeff = 3 ∧ 1 ≤ f.degree ∧
    ∀ (i : ℕ), i < f.degree → f.coeff (i + 1) = f.eval (f.coeff i) } :=
by
  simp only [Set.mem_setOf_eq]

  -- Step 1: Write the polynomial purely in terms of explicit X powers to unify calculations
  have h_poly : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]) = X ^ 2 + X ^ 2 + X ^ 2 + X - 1 := by ring

  -- Step 2: Establish the natural degree of the polynomial via le_antisymm
  have h_natDeg : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).natDegree = 2 := by
    apply le_antisymm
    · rw [Polynomial.natDegree_le_iff_coeff_eq_zero]
      intro m hm
      have h2 : m = 2 ↔ False := iff_false_intro (by omega)
      have h1 : m = 1 ↔ False := iff_false_intro (by omega)
      have h0 : m = 0 ↔ False := iff_false_intro (by omega)
      have h2' : 2 = m ↔ False := iff_false_intro (by omega)
      have h1' : 1 = m ↔ False := iff_false_intro (by omega)
      have h0' : 0 = m ↔ False := iff_false_intro (by omega)
      rw [h_poly]
      simp only [Polynomial.coeff_sub, Polynomial.coeff_add, Polynomial.coeff_X_pow, Polynomial.coeff_X, Polynomial.coeff_one]
      simp only [h2, h1, h0, h2', h1', h0', ite_false, if_false, add_zero, zero_add, sub_zero, zero_sub]
    · by_contra h
      have h_lt : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).natDegree < 2 := not_le.mp h
      have h_zero := Polynomial.coeff_eq_zero_of_natDegree_lt h_lt
      have h_two : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).coeff 2 = 3 := by
        rw [h_poly]
        norm_num [Polynomial.coeff_sub, Polynomial.coeff_add, Polynomial.coeff_X_pow, Polynomial.coeff_one, Polynomial.coeff_X]
      rw [h_two] at h_zero
      norm_num at h_zero

  -- Step 3: Compute the Leading Coefficient natively using its definition and `natDegree`
  have h_lc : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).leadingCoeff = 3 := by
    have h_lc_def : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).leadingCoeff = (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).coeff (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).natDegree := rfl
    rw [h_lc_def, h_natDeg, h_poly]
    norm_num [Polynomial.coeff_sub, Polynomial.coeff_add, Polynomial.coeff_X_pow, Polynomial.coeff_one, Polynomial.coeff_X]

  -- Step 4: Validate the Polynomial degree using `natDegree`
  have h_ne : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]) ≠ 0 := by
    intro h
    have hc : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).coeff 2 = 0 := by rw [h, Polynomial.coeff_zero]
    have hc2 : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).coeff 2 = 3 := by
      rw [h_poly]
      norm_num [Polynomial.coeff_sub, Polynomial.coeff_add, Polynomial.coeff_X_pow, Polynomial.coeff_one, Polynomial.coeff_X]
    rw [hc2] at hc
    norm_num at hc

  have h_deg : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).degree = 2 := by
    rw [Polynomial.degree_eq_natDegree h_ne, h_natDeg]
    rfl

  -- Step 5: Refine the target structure
  refine ⟨h_lc, ?_, ?_⟩
  · rw [h_deg]
    exact_mod_cast (by decide : 1 ≤ 2)
  · intro i hi
    rw [h_deg] at hi
    have hi_lt : i < 2 := by exact_mod_cast hi
    have hi2 : i = 0 ∨ i = 1 := by omega
    rcases hi2 with rfl | rfl
    · -- Evaluation for i = 0
      have hc1 : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).coeff (0 + 1) = 1 := by
        rw [h_poly]
        norm_num [Polynomial.coeff_sub, Polynomial.coeff_add, Polynomial.coeff_X_pow, Polynomial.coeff_one, Polynomial.coeff_X]
      have hc0 : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).coeff 0 = -1 := by
        rw [h_poly]
        norm_num [Polynomial.coeff_sub, Polynomial.coeff_add, Polynomial.coeff_X_pow, Polynomial.coeff_one, Polynomial.coeff_X]
      rw [hc1, hc0]
      have heval0 : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).eval (-1) = 1 := by
        rw [h_poly]
        norm_num [Polynomial.eval_sub, Polynomial.eval_add, Polynomial.eval_pow, Polynomial.eval_one, Polynomial.eval_X]
      rw [heval0]
    · -- Evaluation for i = 1
      have hc2 : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).coeff (1 + 1) = 3 := by
        rw [h_poly]
        norm_num [Polynomial.coeff_sub, Polynomial.coeff_add, Polynomial.coeff_X_pow, Polynomial.coeff_one, Polynomial.coeff_X]
      have hc1 : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).coeff 1 = 1 := by
        rw [h_poly]
        norm_num [Polynomial.coeff_sub, Polynomial.coeff_add, Polynomial.coeff_X_pow, Polynomial.coeff_one, Polynomial.coeff_X]
      rw [hc2, hc1]
      have heval1 : (3 * X ^ 2 + 1 * X - 1 : ℤ[X]).eval 1 = 3 := by
        rw [h_poly]
        norm_num [Polynomial.eval_sub, Polynomial.eval_add, Polynomial.eval_pow, Polynomial.eval_one, Polynomial.eval_X]
      rw [heval1]

theorem natDegree_neq_one {f : ℤ[X]}
  (hf_lead : f.leadingCoeff = 3)
  (hf_deg : 1 ≤ f.degree)
  (hf_eval : ∀ (i : ℕ), i < f.degree → f.coeff (i + 1) = f.eval (f.coeff i)) :
  f.natDegree ≠ 1 :=
by
  intro h

  have h_lead : f.leadingCoeff = 3 := hf_lead
  have hl : f.coeff 1 = 3 := by
    change f.coeff f.natDegree = 3 at h_lead
    rwa [h] at h_lead

  have h_deg_le : f.degree ≤ 1 := by
    have hd := Polynomial.degree_le_natDegree (p := f)
    rwa [h] at hd

  have h_deg_eq : f.degree = 1 := le_antisymm h_deg_le hf_deg

  have hz : (0 : ℕ) < f.degree := by
    rw [h_deg_eq]
    norm_num

  have heval0 : f.coeff 1 = f.eval (f.coeff 0) := hf_eval 0 hz

  have heval_expand : f.eval (f.coeff 0) = f.coeff 0 + f.coeff 1 * f.coeff 0 := by
    rw [Polynomial.eval_eq_sum_range, h]
    simp [Finset.sum_range_succ]

  have h_eq : 3 = 4 * f.coeff 0 := by
    calc
      3 = f.coeff 1 := hl.symm
      _ = f.eval (f.coeff 0) := heval0
      _ = f.coeff 0 + f.coeff 1 * f.coeff 0 := heval_expand
      _ = f.coeff 0 + 3 * f.coeff 0 := by rw [hl]
      _ = 4 * f.coeff 0 := by ring

  omega

theorem max_coeff_exists (f : ℤ[X]) (n : ℕ) (hn : 0 < n) :
  ∃ M : ℤ, max_coeff_prop f n M :=
by
  have h0 : |f.coeff 0| ∈ (Finset.range n).image (fun i => |f.coeff i|) := by
    simp only [Finset.mem_image, Finset.mem_range]
    exact ⟨0, hn, rfl⟩

  have hS : ((Finset.range n).image (fun i => |f.coeff i|)).Nonempty := ⟨|f.coeff 0|, h0⟩

  use ((Finset.range n).image (fun i => |f.coeff i|)).max' hS
  unfold max_coeff_prop
  constructor
  · intro i hi
    apply Finset.le_max'
    simp only [Finset.mem_image, Finset.mem_range]
    exact ⟨i, hi, rfl⟩
  · have hM_mem := Finset.max'_mem ((Finset.range n).image (fun i => |f.coeff i|)) hS
    simp only [Finset.mem_image, Finset.mem_range] at hM_mem
    rcases hM_mem with ⟨k, hk_mem, hk_eq⟩
    exact ⟨k, hk_mem, hk_eq⟩

theorem max_coeff_le_one {f : ℤ[X]} {n : ℕ} {M : ℤ}
  (hn : f.natDegree = n) (hn2 : 2 ≤ n) (hM : max_coeff_prop f n M)
  (hf_lead : f.leadingCoeff = 3)
  (hf_eval : ∀ (i : ℕ), i < n → f.coeff (i + 1) = f.eval (f.coeff i)) :
  M ≤ 1 :=
by
  by_contra h_contra
  push_neg at h_contra

  rcases hM.right with ⟨k_idx, hk_idx_lt, hk_idx_eq⟩
  let x := f.coeff k_idx
  have hx_def : f.coeff k_idx = x := rfl

  have hx : |x| = M := by
    have h1 : |f.coeff k_idx| = M := hk_idx_eq
    rw [hx_def] at h1
    exact h1

  have H_sum : ∀ k, k ≤ n → |(Finset.range k).sum (fun i => f.coeff i * x ^ i)| ≤ 2 * M ^ k - 2 := by
    intro k
    induction k with
    | zero =>
      intro _
      simp only [Finset.range_zero, Finset.sum_empty, abs_zero, pow_zero]
      omega
    | succ k ih =>
      intro hk
      have hk1 : k ≤ n := by omega
      have h_ih := ih hk1
      rw [Finset.sum_range_succ]
      have h_tri := abs_add_le ((Finset.range k).sum (fun i => f.coeff i * x ^ i)) (f.coeff k * x ^ k)
      have hck : |f.coeff k| ≤ M := hM.left k (by omega)
      have h_term : |f.coeff k * x ^ k| ≤ M * M ^ k := by
        rw [abs_mul, abs_pow, hx]
        have h_M_nonneg : 0 ≤ M := by omega
        have hm_pow_pos : 0 ≤ M ^ k := by positivity
        nlinarith
      have h_M_nonneg : 0 ≤ M := by omega
      have hm_pow_pos : 0 ≤ M ^ k := by positivity
      have h_M2 : 2 ≤ M := by omega
      have h_bound : 2 * M ^ k ≤ M * M ^ k := by nlinarith
      have h_pow : M ^ (k + 1) = M * M ^ k := by
        calc M ^ (k + 1) = M ^ k * M ^ 1 := by rw [pow_add]
          _ = M ^ k * M := by rw [pow_one]
          _ = M * M ^ k := by ring
      linarith

  have H_eval_sum : f.eval x = (Finset.range (n + 1)).sum (fun i => f.coeff i * x ^ i) := by
    have h_eq : f.eval x = f.support.sum (fun i => f.coeff i * x ^ i) := Polynomial.eval_eq_sum
    rw [h_eq]
    have H_supp : f.support ⊆ Finset.range (n + 1) := by
      intro i hi
      rw [Finset.mem_range]
      have h_le := Polynomial.le_natDegree_of_ne_zero (Polynomial.mem_support_iff.mp hi)
      omega
    have H_subset : f.support.sum (fun i => f.coeff i * x ^ i) = (Finset.range (n + 1)).sum (fun i => f.coeff i * x ^ i) := by
      apply Finset.sum_subset H_supp
      intro i _ h_not_supp
      have h_zero : f.coeff i = 0 := by
        by_contra h_nz
        apply h_not_supp
        exact Polynomial.mem_support_iff.mpr h_nz
      rw [h_zero, zero_mul]
    exact H_subset

  have H_eval_split : f.eval x = (Finset.range n).sum (fun i => f.coeff i * x ^ i) + f.coeff n * x ^ n := by
    rw [H_eval_sum, Finset.sum_range_succ]

  have h_cn : f.coeff n = 3 := by
    rw [← hn]
    exact hf_lead

  have H_bound1 : |3 * x ^ n| ≤ |f.eval x| + |(Finset.range n).sum (fun i => f.coeff i * x ^ i)| := by
    have h_eq : 3 * x ^ n = f.eval x - (Finset.range n).sum (fun i => f.coeff i * x ^ i) := by
      rw [H_eval_split, h_cn]
      ring
    rw [h_eq]
    have h_sub_add : f.eval x - (Finset.range n).sum (fun i => f.coeff i * x ^ i) = f.eval x + - (Finset.range n).sum (fun i => f.coeff i * x ^ i) := by ring
    rw [h_sub_add]
    have h_tri := abs_add_le (f.eval x) (-(Finset.range n).sum (fun i => f.coeff i * x ^ i))
    have h_neg : |-(Finset.range n).sum (fun i => f.coeff i * x ^ i)| = |(Finset.range n).sum (fun i => f.coeff i * x ^ i)| := by rw [abs_neg]
    rw [h_neg] at h_tri
    exact h_tri

  have H_3xn : |3 * x ^ n| = 3 * M ^ n := by
    calc |3 * x ^ n| = |(3 : ℤ)| * |x| ^ n := by rw [abs_mul, abs_pow]
      _ = 3 * M ^ n := by
        rw [hx]
        have h3 : |(3 : ℤ)| = 3 := rfl
        rw [h3]

  have H_Sn_bound : |(Finset.range n).sum (fun i => f.coeff i * x ^ i)| ≤ 2 * M ^ n - 2 := H_sum n (by omega)

  have H_eval_lower : M ^ n + 2 ≤ |f.eval x| := by
    have h1 := H_bound1
    rw [H_3xn] at h1
    have h2 := H_Sn_bound
    linarith

  have hk_idx_cases : k_idx + 1 < n ∨ k_idx + 1 = n := by omega

  have H_one_le_pow : ∀ m, 1 ≤ M ^ m := by
    intro m
    induction m with
    | zero =>
      simp only [pow_zero, le_refl]
    | succ m ih =>
      have h_pow : M ^ (m + 1) = M * M ^ m := by
        calc M ^ (m + 1) = M ^ m * M ^ 1 := by rw [pow_add]
          _ = M ^ m * M := by rw [pow_one]
          _ = M * M ^ m := by ring
      rw [h_pow]
      have hM2 : 2 ≤ M := by omega
      nlinarith

  rcases hk_idx_cases with hk_lt | hk_eq
  · have h_c_next := hM.left (k_idx + 1) hk_lt
    have h_eval_next := hf_eval k_idx hk_idx_lt
    rw [hx_def] at h_eval_next

    have H_eval_x_le : |f.eval x| ≤ M := by
      rw [← h_eval_next]
      exact h_c_next

    have H_M_le_pow : ∀ m ≥ 1, M ≤ M ^ m := by
      intro m hm
      induction m with
      | zero => omega
      | succ m ih =>
        by_cases h_m : m = 0
        · have h_m1 : m + 1 = 1 := by omega
          rw [h_m1, pow_one]
        · have hm1 : m ≥ 1 := by omega
          have h_ih := ih hm1
          have h_pow : M ^ (m + 1) = M * M ^ m := by
            calc M ^ (m + 1) = M ^ m * M ^ 1 := by rw [pow_add]
              _ = M ^ m * M := by rw [pow_one]
              _ = M * M ^ m := by ring
          rw [h_pow]
          have h_M2 : 2 ≤ M := by omega
          have h_one_le : 1 ≤ M ^ m := H_one_le_pow m
          nlinarith

    have h_Mn : M ≤ M ^ n := H_M_le_pow n (by omega)
    linarith

  · have h_eval_next := hf_eval k_idx hk_idx_lt
    rw [hx_def] at h_eval_next
    rw [hk_eq] at h_eval_next
    rw [h_cn] at h_eval_next

    have H_M_sq_le : 4 ≤ M ^ n := by
      obtain ⟨m, hm⟩ : ∃ m, n = m + 2 := ⟨n - 2, by omega⟩
      have h2 : 2 ≤ M := by omega
      have h_pow2 : M ^ 2 = M * M := by ring
      have h_pow_full : M ^ n = M ^ m * (M * M) := by
        calc M ^ n = M ^ (m + 2) := by rw [hm]
          _ = M ^ m * M ^ 2 := by rw [pow_add]
          _ = M ^ m * (M * M) := by rw [h_pow2]
      rw [h_pow_full]
      have h1 : 1 ≤ M ^ m := H_one_le_pow m
      have h_M_sq : 4 ≤ M * M := by nlinarith
      nlinarith

    have h_abs_eval : |f.eval x| = 3 := by
      have h_eq : f.eval x = 3 := h_eval_next.symm
      rw [h_eq]
      rfl

    linarith

theorem abs_le_one_mem_set (x : ℤ) (h : |x| ≤ 1) : x ∈ ({-1, 0, 1} : Set ℤ) :=
by
  simp only [Set.mem_insert_iff, Set.mem_singleton_iff]
  have ⟨h1, h2⟩ := abs_le.mp h
  omega

theorem my_coeff_in_range {f : ℤ[X]} {n : ℕ}
  (hn : f.natDegree = n) (hn2 : 2 ≤ n)
  (hf_lead : f.leadingCoeff = 3)
  (hf_eval : ∀ (i : ℕ), i < n → f.coeff (i + 1) = f.eval (f.coeff i)) :
  ∀ i < n, f.coeff i ∈ ({-1, 0, 1} : Set ℤ) :=
by
  intro i hi
  have hn_pos : 0 < n := by omega

  -- 1. Extract the max coefficient bound M
  obtain ⟨M, hM⟩ := max_coeff_exists f n hn_pos

  -- 2. Prove that this bound is strictly ≤ 1 using the provided prerequisite
  have hM_le : M ≤ 1 := max_coeff_le_one hn hn2 hM hf_lead hf_eval

  -- 3. Extract the bound constraint for the specific arbitrary index `i`
  have h_bound : |f.coeff i| ≤ M := hM.1 i hi

  -- 4. Chain the inequalities mathematically via le_trans
  have h_abs : |f.coeff i| ≤ 1 := le_trans h_bound hM_le

  -- 5. Final Set conclusion
  exact abs_le_one_mem_set (f.coeff i) h_abs

theorem exists_add_eq_of_le {a b : ℕ} (h : a ≤ b) : ∃ c : ℕ, a + c = b :=
by
  induction h with
  | refl => exact ⟨0, by omega⟩
  | step _ ih =>
    obtain ⟨c, hc⟩ := ih
    exact ⟨c + 1, by omega⟩

theorem coeff_eq_of_cycle {f : ℤ[X]} {n : ℕ}
  (hf_eval : ∀ (k : ℕ), k < n → f.coeff (k + 1) = f.eval (f.coeff k))
  (i j : ℕ) (hi : i ≤ j) (heq : f.coeff i = f.coeff j) (d : ℕ) :
  j + d ≤ n → f.coeff (i + d) = f.coeff (j + d) :=
by
  induction d with
  | zero =>
    intro _
    change f.coeff i = f.coeff j
    exact heq
  | succ d ih =>
    intro hd
    have h1 : j + d ≤ n := by omega
    have h2 : i + d < n := by omega
    have h3 : j + d < n := by omega
    change f.coeff (i + d + 1) = f.coeff (j + d + 1)
    rw [hf_eval (i + d) h2, hf_eval (j + d) h3, ih h1]

theorem my_no_cycle_in_coeff {f : ℤ[X]} {n : ℕ}
  (hn : f.natDegree = n) (hn2 : 2 ≤ n)
  (hf_lead : f.leadingCoeff = 3)
  (hf_eval : ∀ (i : ℕ), i < n → f.coeff (i + 1) = f.eval (f.coeff i)) :
  ∀ i j, i < j → j < n → f.coeff i ≠ f.coeff j :=
by
  intro i j hi hj heq
  have hi_le : i ≤ j := by omega
  have hj_le_n : j ≤ n := by omega

  -- Obtain the offset d such that j + d = n, strictly avoiding natural number subtraction.
  obtain ⟨d, hd_eq⟩ := exists_add_eq_of_le hj_le_n
  have hd_le : j + d ≤ n := by omega

  -- Apply our cyclic relation offset up to the highest degree using the obtained addition delta.
  have h_cycle := coeff_eq_of_cycle hf_eval i j hi_le heq d hd_le

  -- The lower shifted index falls strictly within range boundaries constraints.
  have eq_k : i + d < n := by omega
  rw [hd_eq] at h_cycle

  -- Match leadingCoeff definition mapping to natDegree using standard polynomial equalities.
  have h_n_deg : f.coeff n = 3 := by
    rw [← hn]
    rw [Polynomial.coeff_natDegree]
    exact hf_lead

  rw [h_n_deg] at h_cycle

  -- Gather the known value bounds from the environment's `my_coeff_in_range` lemma to trigger the contradiction.
  have h_range := my_coeff_in_range hn hn2 hf_lead hf_eval (i + d) eq_k
  rw [h_cycle] at h_range

  -- Simplifying the inherent bounds from Set to an easily branchable logic for `omega`
  simp only [Set.mem_insert_iff, Set.mem_singleton_iff] at h_range

  -- The contradiction implies 3 is one of {-1, 0, 1}, which mathematically evaluates to False
  rcases h_range with h | h | h
  · omega
  · omega
  · omega

theorem pigeonhole_principle_coeffs_of_four (c : ℕ → ℤ)
  (h_range : ∀ i < 4, c i ∈ ({-1, 0, 1} : Set ℤ))
  (h_inj : ∀ i j, i < j → j < 4 → c i ≠ c j) : False :=
by
  have get_range : ∀ (i : ℕ), i < 4 → c i = -1 ∨ c i = 0 ∨ c i = 1 := by
    intro i hi
    have h := h_range i hi
    simp only [Set.mem_insert_iff, Set.mem_singleton_iff] at h
    exact h

  have h0 := get_range 0 (by decide)
  have h1 := get_range 1 (by decide)
  have h2 := get_range 2 (by decide)
  have h3 := get_range 3 (by decide)

  have h01 := h_inj 0 1 (by decide) (by decide)
  have h02 := h_inj 0 2 (by decide) (by decide)
  have h03 := h_inj 0 3 (by decide) (by decide)
  have h12 := h_inj 1 2 (by decide) (by decide)
  have h13 := h_inj 1 3 (by decide) (by decide)
  have h23 := h_inj 2 3 (by decide) (by decide)

  rcases h0 with h0 | h0 | h0 <;>
  rcases h1 with h1 | h1 | h1 <;>
  rcases h2 with h2 | h2 | h2 <;>
  rcases h3 with h3 | h3 | h3 <;>
  omega

theorem natDegree_lt_four {f : ℤ[X]} {n : ℕ}
  (hn : f.natDegree = n) (hn2 : 2 ≤ n)
  (hf_lead : f.leadingCoeff = 3)
  (hf_eval : ∀ (i : ℕ), i < n → f.coeff (i + 1) = f.eval (f.coeff i)) :
  n ≤ 3 :=
by
  by_contra h

  -- Gather properties from our sub-lemmas using the theorem's hypotheses.
  have H_range := my_coeff_in_range hn hn2 hf_lead hf_eval
  have H_inj := my_no_cycle_in_coeff hn hn2 hf_lead hf_eval

  -- Restrict the range bounds precisely to the first 4 indices.
  have h_range_4 : ∀ i < 4, f.coeff i ∈ ({-1, 0, 1} : Set ℤ) := by
    intro i hi
    have hin : i < n := by omega
    exact H_range i hin

  -- Restrict the injectivity rule precisely to the first 4 indices.
  have h_inj_4 : ∀ i j, i < j → j < 4 → f.coeff i ≠ f.coeff j := by
    intro i j hij hj
    have hjn : j < n := by omega
    exact H_inj i j hij hjn

  -- We now have 4 strictly distinct integers mapping to a set of 3 integers.
  -- This triggers the explicit contradiction via the Pigeonhole principle.
  exact pigeonhole_principle_coeffs_of_four f.coeff h_range_4 h_inj_4

theorem eval_poly_natDegree_three (f : ℤ[X]) (h : f.natDegree = 3) (x : ℤ) :
  f.eval x = f.coeff 3 * x^3 + f.coeff 2 * x^2 + f.coeff 1 * x + f.coeff 0 :=
by
  have h_deg : f.natDegree < 4 := by omega
  have H := Polynomial.eval_eq_sum_range' h_deg x
  rw [H]
  have r4 : Finset.range 4 = Finset.range (3 + 1) := rfl
  rw [r4, Finset.sum_range_succ]
  have r3 : Finset.range 3 = Finset.range (2 + 1) := rfl
  rw [r3, Finset.sum_range_succ]
  have r2 : Finset.range 2 = Finset.range (1 + 1) := rfl
  rw [r2, Finset.sum_range_succ]
  have r1 : Finset.range 1 = Finset.range (0 + 1) := rfl
  rw [r1, Finset.sum_range_succ]
  rw [Finset.sum_range_zero]
  ring

theorem cubic_coeffs_contradiction (c0 c1 c2 : ℤ)
  (heq1 : c1 = 3 * c0^3 + c2 * c0^2 + c1 * c0 + c0)
  (heq2 : c2 = 3 * c1^3 + c2 * c1^2 + c1 * c1 + c0)
  (heq3 : 3 = 3 * c2^3 + c2 * c2^2 + c1 * c2 + c0) : False :=
by
  -- We prove the contradiction by projecting the system of equations modulo 2.
  -- The `decide` tactic is capable of checking all 8 possibilities natively.
  have contradiction_lemma : ∀ (x y z : ZMod 2),
    y = 3 * x^3 + z * x^2 + y * x + x →
    z = 3 * y^3 + z * y^2 + y * y + x →
    (3 : ZMod 2) = 3 * z^3 + z * z^2 + y * z + x →
    False := by decide

  have h1_mod : (c1 : ZMod 2) = 3 * (c0 : ZMod 2)^3 + (c2 : ZMod 2) * (c0 : ZMod 2)^2 + (c1 : ZMod 2) * (c0 : ZMod 2) + (c0 : ZMod 2) := by
    have h := congrArg (fun a : ℤ ↦ (a : ZMod 2)) heq1
    push_cast at h
    exact h

  have h2_mod : (c2 : ZMod 2) = 3 * (c1 : ZMod 2)^3 + (c2 : ZMod 2) * (c1 : ZMod 2)^2 + (c1 : ZMod 2) * (c1 : ZMod 2) + (c0 : ZMod 2) := by
    have h := congrArg (fun a : ℤ ↦ (a : ZMod 2)) heq2
    push_cast at h
    exact h

  have h3_mod : (3 : ZMod 2) = 3 * (c2 : ZMod 2)^3 + (c2 : ZMod 2) * (c2 : ZMod 2)^2 + (c1 : ZMod 2) * (c2 : ZMod 2) + (c0 : ZMod 2) := by
    have h := congrArg (fun a : ℤ ↦ (a : ZMod 2)) heq3
    push_cast at h
    exact h

  exact contradiction_lemma (c0 : ZMod 2) (c1 : ZMod 2) (c2 : ZMod 2) h1_mod h2_mod h3_mod

theorem natDegree_neq_three {f : ℤ[X]}
  (hn : f.natDegree = 3)
  (hf_lead : f.leadingCoeff = 3)
  (hf_eval : ∀ (i : ℕ), i < 3 → f.coeff (i + 1) = f.eval (f.coeff i)) :
  False :=
by
  have h_lead : f.coeff 3 = 3 := by
    have h1 : f.coeff f.natDegree = f.leadingCoeff := rfl
    rw [hn] at h1
    rw [h1, hf_lead]

  have heq1 : f.coeff 1 = f.eval (f.coeff 0) := hf_eval 0 (by decide)
  have heq2 : f.coeff 2 = f.eval (f.coeff 1) := hf_eval 1 (by decide)
  have heq3 : f.coeff 3 = f.eval (f.coeff 2) := hf_eval 2 (by decide)

  have h_eval1 := eval_poly_natDegree_three f hn (f.coeff 0)
  have h_eval2 := eval_poly_natDegree_three f hn (f.coeff 1)
  have h_eval3 := eval_poly_natDegree_three f hn (f.coeff 2)

  rw [h_lead] at h_eval1 h_eval2 h_eval3

  rw [h_eval1] at heq1
  rw [h_eval2] at heq2
  rw [h_eval3] at heq3
  rw [h_lead] at heq3

  exact cubic_coeffs_contradiction (f.coeff 0) (f.coeff 1) (f.coeff 2) heq1 heq2 heq3

theorem natDegree_ge_one {f : ℤ[X]} (hf_deg : 1 ≤ f.degree) : 1 ≤ f.natDegree :=
by
  by_contra h
  have h1 : f.natDegree ≤ 0 := by omega
  have h2 : f.degree ≤ ↑(0 : ℕ) := Polynomial.natDegree_le_iff_degree_le.mp h1
  have h3 : ((1 : ℕ) : WithBot ℕ) ≤ ((0 : ℕ) : WithBot ℕ) := le_trans hf_deg h2
  have h4 : (1 : ℕ) ≤ 0 := by exact_mod_cast h3
  omega

theorem eval_cond_of_degree {f : ℤ[X]}
  (hf_eval : ∀ (i : ℕ), i < f.degree → f.coeff (i + 1) = f.eval (f.coeff i)) :
  ∀ (i : ℕ), i < f.natDegree → f.coeff (i + 1) = f.eval (f.coeff i) :=
by
  intro i hi
  apply hf_eval
  have hf : f ≠ 0 := by
    intro h
    subst h
    rw [Polynomial.natDegree_zero] at hi
    omega
  rw [Polynomial.degree_eq_natDegree hf]
  exact_mod_cast hi

theorem poly_natDegree_eq_two {f : ℤ[X]}
  (hf_lead : f.leadingCoeff = 3)
  (hf_deg : 1 ≤ f.degree)
  (hf_eval : ∀ (i : ℕ), i < f.degree → f.coeff (i + 1) = f.eval (f.coeff i)) :
  f.natDegree = 2 :=
by
  have h_ge1 : 1 ≤ f.natDegree := natDegree_ge_one hf_deg
  have h_neq1 : f.natDegree ≠ 1 := natDegree_neq_one hf_lead hf_deg hf_eval
  have hn_ge2 : 2 ≤ f.natDegree := by omega
  have h_eval_n : ∀ (i : ℕ), i < f.natDegree → f.coeff (i + 1) = f.eval (f.coeff i) := eval_cond_of_degree hf_eval
  have h_lt4 : f.natDegree ≤ 3 := natDegree_lt_four rfl hn_ge2 hf_lead h_eval_n
  have h_neq3 : f.natDegree ≠ 3 := by
    intro h
    have h_eval3 : ∀ (i : ℕ), i < 3 → f.coeff (i + 1) = f.eval (f.coeff i) := by
      intro i hi
      apply h_eval_n
      rw [h]
      exact hi
    exact natDegree_neq_three h hf_lead h_eval3
  omega

theorem poly_eq_target_of_degree_two {f : ℤ[X]}
  (hf_lead : f.leadingCoeff = 3)
  (hf_deg : f.natDegree = 2)
  (hf_eval : ∀ (i : ℕ), i < f.degree → f.coeff (i + 1) = f.eval (f.coeff i)) :
  f = 3 * X ^ 2 + 1 * X - 1 :=
by
  have hf_ne_zero : f ≠ 0 := by
    intro h
    have h1 : f.natDegree = 0 := by
      rw [h]
      exact Polynomial.natDegree_zero
    rw [hf_deg] at h1
    omega

  have h_deg_eq : f.degree = ↑(2 : ℕ) := by
    rw [Polynomial.degree_eq_natDegree hf_ne_zero, hf_deg]

  have hc2 : f.coeff 2 = 3 := by
    have h_nat : f.natDegree = 2 := hf_deg
    have h_lead : f.leadingCoeff = 3 := hf_lead
    calc f.coeff 2 = f.coeff f.natDegree := by rw [h_nat]
         _ = f.leadingCoeff := Polynomial.coeff_natDegree.symm
         _ = 3 := h_lead

  let b := f.coeff 1
  let c := f.coeff 0

  have f_eq : f = C (3 : ℤ) * X ^ 2 + C b * X + C c := by
    ext n
    have h1 : (C (3 : ℤ) * X ^ 2).coeff n = if n = 2 then (3 : ℤ) else 0 := Polynomial.coeff_C_mul_X_pow (3 : ℤ) 2 n
    have h2 : (C b * X).coeff n = if n = 1 then b else 0 := by
      have hX : C b * X = C b * X ^ 1 := by rw [pow_one]
      rw [hX, Polynomial.coeff_C_mul_X_pow]
    have h3 : (C c).coeff n = if n = 0 then c else 0 := by
      have hX0 : C c = C c * X ^ 0 := by rw [pow_zero, mul_one]
      rw [hX0, Polynomial.coeff_C_mul_X_pow]
    simp only [Polynomial.coeff_add, h1, h2, h3]
    have h_gt : ∀ m : ℕ, m > 2 → f.coeff m = 0 := by
      intro m hm
      apply Polynomial.coeff_eq_zero_of_natDegree_lt
      omega
    by_cases hn0 : n = 0
    · subst hn0
      simp
      rfl
    · by_cases hn1 : n = 1
      · subst hn1
        simp
        rfl
      · by_cases hn2 : n = 2
        · subst hn2
          simp [hc2]
        · have hn_gt : n > 2 := by omega
          have h_f : f.coeff n = 0 := h_gt n hn_gt
          rw [h_f]
          simp [hn0, hn1, hn2]

  have h_eval : ∀ x : ℤ, f.eval x = 3 * x ^ 2 + b * x + c := by
    intro x
    calc f.eval x = (C (3 : ℤ) * X ^ 2 + C b * X + C c).eval x := by rw [f_eq]
         _ = 3 * x ^ 2 + b * x + c := by
           simp only [Polynomial.eval_add, Polynomial.eval_mul, Polynomial.eval_C, Polynomial.eval_X, Polynomial.eval_pow]

  have h_eval1 : f.coeff 2 = f.eval b := by
    have h_one_plus_one : (1 : ℕ) + 1 = 2 := rfl
    have h_lt : ↑(1 : ℕ) < f.degree := by
      rw [h_deg_eq]
      decide
    have h_step := hf_eval 1 h_lt
    rw [h_one_plus_one] at h_step
    exact h_step

  have h_eval0 : b = f.eval c := by
    have h_zero_plus_one : (0 : ℕ) + 1 = 1 := rfl
    have h_lt : ↑(0 : ℕ) < f.degree := by
      rw [h_deg_eq]
      decide
    have h_step := hf_eval 0 h_lt
    rw [h_zero_plus_one] at h_step
    exact h_step

  have hb_eq : 3 = 3 * b ^ 2 + b * b + c := by
    calc 3 = f.coeff 2 := hc2.symm
         _ = f.eval b := h_eval1
         _ = 3 * b ^ 2 + b * b + c := h_eval b

  have hb_eq2 : b = 3 * c ^ 2 + b * c + c := by
    calc b = f.eval c := h_eval0
         _ = 3 * c ^ 2 + b * c + c := h_eval c

  have hc_eq : c = 3 - 4 * b ^ 2 := by
    calc c = (3 * b ^ 2 + b * b + c) - 4 * b ^ 2 := by ring
         _ = 3 - 4 * b ^ 2 := by rw [← hb_eq]

  have hb_eq3 : b = 3 * (3 - 4 * b ^ 2) ^ 2 + b * (3 - 4 * b ^ 2) + (3 - 4 * b ^ 2) := by
    calc b = 3 * c ^ 2 + b * c + c := hb_eq2
         _ = 3 * (3 - 4 * b ^ 2) ^ 2 + b * (3 - 4 * b ^ 2) + (3 - 4 * b ^ 2) := by rw [hc_eq]

  have hb_poly : 2 * ((b - 1) * (24 * b ^ 3 + 22 * b ^ 2 - 16 * b - 15)) = 0 := by
    calc 2 * ((b - 1) * (24 * b ^ 3 + 22 * b ^ 2 - 16 * b - 15))
       = (3 * (3 - 4 * b ^ 2) ^ 2 + b * (3 - 4 * b ^ 2) + (3 - 4 * b ^ 2)) - b := by ring
     _ = b - b := by rw [← hb_eq3]
     _ = 0 := by ring

  have hb_poly2 : (b - 1) * (24 * b ^ 3 + 22 * b ^ 2 - 16 * b - 15) = 0 := by
    have h_two : (2 : ℤ) ≠ 0 := by decide
    have h_mul := hb_poly
    rw [mul_eq_zero] at h_mul
    cases h_mul with
    | inl h => omega
    | inr h => exact h

  have hb_cases : b - 1 = 0 ∨ 24 * b ^ 3 + 22 * b ^ 2 - 16 * b - 15 = 0 := mul_eq_zero.mp hb_poly2

  have h_parity : 24 * b ^ 3 + 22 * b ^ 2 - 16 * b - 15 ≠ 0 := by
    intro h_eq
    have h_odd : 2 * (12 * b ^ 3 + 11 * b ^ 2 - 8 * b - 7) = 1 := by
      calc 2 * (12 * b ^ 3 + 11 * b ^ 2 - 8 * b - 7)
         = (24 * b ^ 3 + 22 * b ^ 2 - 16 * b - 15) + 1 := by ring
       _ = 0 + 1 := by rw [h_eq]
       _ = 1 := by ring
    omega

  have hb_one : b = 1 := by
    cases hb_cases with
    | inl h => omega
    | inr h => exact False.elim (h_parity h)

  have hc_minus_one : c = -1 := by
    calc c = 3 - 4 * b ^ 2 := hc_eq
         _ = 3 - 4 * 1 ^ 2 := by rw [hb_one]
         _ = -1 := by norm_num

  rw [f_eq, hb_one, hc_minus_one]
  have eq3 : C (3 : ℤ) = 3 := by
    have h_int : (3 : ℤ) = 1 + 1 + 1 := by ring
    have h_poly : (3 : ℤ[X]) = 1 + 1 + 1 := by ring
    calc C (3 : ℤ) = C (1 + 1 + 1) := by rw [h_int]
         _ = C 1 + C 1 + C 1 := by simp only [map_add]
         _ = 1 + 1 + 1 := by simp only [map_one]
         _ = 3 := by rw [h_poly]
  have eq1 : C (1 : ℤ) = 1 := by simp only [map_one]
  have eqm1 : C (-1 : ℤ) = -1 := by
    calc C (-1 : ℤ) = C (-(1 : ℤ)) := rfl
         _ = - C 1 := by simp only [map_neg]
         _ = -1 := by simp only [map_one]
  rw [eq3, eq1, eqm1]
  ring

theorem PBBasic007 : { f : ℤ[X] | f.leadingCoeff = 3 ∧ 1 ≤ f.degree ∧
      ∀ (i : ℕ), i < f.degree → f.coeff (i + 1) = f.eval (f.coeff i) } =
    {3 * X ^ 2 + 1 * X - 1} :=
by
  ext f
  constructor
  · intro h
    simp only [Set.mem_setOf_eq] at h
    have h_lead : f.leadingCoeff = 3 := h.1
    have h_deg : 1 ≤ f.degree := h.2.1
    have h_eval : ∀ (i : ℕ), i < f.degree → f.coeff (i + 1) = f.eval (f.coeff i) := h.2.2
    have h_natDeg : f.natDegree = 2 := poly_natDegree_eq_two h_lead h_deg h_eval
    have h_eq : f = 3 * X ^ 2 + 1 * X - 1 := poly_eq_target_of_degree_two h_lead h_natDeg h_eval
    simp only [Set.mem_singleton_iff]
    exact h_eq
  · intro h
    simp only [Set.mem_singleton_iff] at h
    subst h
    exact target_poly_in_set
