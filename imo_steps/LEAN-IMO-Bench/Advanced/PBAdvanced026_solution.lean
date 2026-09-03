import Mathlib

open Polynomial
open scoped Polynomial

def HasAllDistinctRoots (p : ℝ[X]) : Prop :=
  p.roots.toFinset.card = p.natDegree

open scoped Classical

theorem exists_subset_roots (P : ℝ[X]) (k : ℕ) (hP' : (P.aroots ℂ).Nodup)
    (hkn : k < P.natDegree) (h_contra : ∀ z ∈ P.aroots ℂ, z.im = 0) :
    ∃ S : Finset ℝ, S.card = k.succ ∧ ∀ x ∈ S, P.IsRoot x :=
by
  let S_all : Finset ℂ := ⟨P.aroots ℂ, hP'⟩
  have h_card : S_all.card = P.natDegree := by
    change (P.aroots ℂ).card = P.natDegree
    exact IsAlgClosed.card_aroots_eq_natDegree
  have h_le : k.succ ≤ S_all.card := by omega

  obtain ⟨S_C, hS_C_sub, hS_C_card⟩ := Finset.exists_subset_card_eq h_le

  have h_inj : Set.InjOn Complex.re S_C := by
    intro z₁ hz₁ z₂ hz₂ hre
    have hz1_root : z₁ ∈ P.aroots ℂ := hS_C_sub hz₁
    have hz2_root : z₂ ∈ P.aroots ℂ := hS_C_sub hz₂
    have h1 : z₁.im = 0 := h_contra z₁ hz1_root
    have h2 : z₂.im = 0 := h_contra z₂ hz2_root
    apply Complex.ext
    · exact hre
    · rw [h1, h2]

  use S_C.image Complex.re
  constructor
  · rw [Finset.card_image_of_injOn h_inj, hS_C_card]
  · intro x hx
    rw [Finset.mem_image] at hx
    rcases hx with ⟨z, hz, rfl⟩
    have hz_root : z ∈ P.aroots ℂ := hS_C_sub hz
    have hz_im : z.im = 0 := h_contra z hz_root
    rw [Polynomial.mem_aroots] at hz_root

    -- Show that z is exactly the mapped real component representation
    have hz_eq : z = algebraMap ℝ ℂ z.re := by
      apply Complex.ext
      · change z.re = (Complex.ofReal z.re).re
        rw [Complex.ofReal_re]
      · change z.im = (Complex.ofReal z.re).im
        rw [hz_im, Complex.ofReal_im]

    -- Evaluate the definitionally rewritten formulation explicitly
    have haeval : Polynomial.aeval (algebraMap ℝ ℂ z.re) P = 0 := by
      rw [← hz_eq]
      exact hz_root.2

    -- Use the general evaluation theorem over an embedded field
    have h_aeval_eq : Polynomial.aeval (algebraMap ℝ ℂ z.re) P = algebraMap ℝ ℂ (P.eval z.re) :=
      Polynomial.aeval_algebraMap_apply_eq_algebraMap_eval z.re P

    -- Connect both proofs, changing form explicitly so we don't trip context mismatch
    rw [h_aeval_eq] at haeval
    change Complex.ofReal (P.eval z.re) = 0 at haeval
    exact Complex.ofReal_eq_zero.mp haeval

theorem exists_shared_zero_coeff (P : ℝ[X]) (k : ℕ) (hP : P.coeff 0 ≠ 0)
    (S : Finset ℝ) (hS_card : S.card = k.succ)
    (hS_roots : ∀ x ∈ S, P.IsRoot x)
    (H : ∀ Q, Q ∣ P → Q.natDegree ≤ k → ∏ i ∈ Finset.range k.succ, Q.coeff i = 0) :
    ∃ (x y : ℝ) (m : ℕ), x ∈ S ∧ y ∈ S ∧ x ≠ y ∧ m.succ < k ∧
      (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z)).coeff m.succ = 0 ∧
      (∏ z ∈ S.erase y, (Polynomial.X - Polynomial.C z)).coeff m.succ = 0 :=
by

  have hP_nz : P ≠ 0 := by
    intro h
    rw [h] at hP
    revert hP
    simp

  have h_exists : ∀ x ∈ S, ∃ m : ℕ, m.succ < k ∧ (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X])).coeff m.succ = 0 := by
    intro x hx
    have H_multiset : (Multiset.map (fun a => (Polynomial.X : ℝ[X]) - Polynomial.C a) (S.erase x).val).prod ∣ P := by
      refine (Multiset.prod_X_sub_C_dvd_iff_le_roots hP_nz ((S.erase x).val)).mpr ?_
      rw [Multiset.le_iff_count]
      intro a
      by_cases ha : a ∈ (S.erase x).val
      · have ha_finset : a ∈ S.erase x := ha
        have hz : P.IsRoot a := hS_roots a (Finset.mem_erase.mp ha_finset).2
        have har : a ∈ P.roots := (Polynomial.mem_roots hP_nz).mpr hz
        have h1 : 0 < Multiset.count a P.roots := Multiset.count_pos.mpr har
        have h2 : Multiset.count a (S.erase x).val ≤ 1 := Multiset.nodup_iff_count_le_one.mp (Finset.nodup (S.erase x)) a
        omega
      · have hc : Multiset.count a (S.erase x).val = 0 := Multiset.count_eq_zero.mpr ha
        omega

    have hdvd : (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X])) ∣ P := H_multiset

    have h_ne_zero : ∀ i ∈ S.erase x, (Polynomial.X - Polynomial.C i : ℝ[X]) ≠ 0 := by
      intro i _
      exact (Polynomial.monic_X_sub_C i).ne_zero

    have hQ_monic : (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X])).Monic := by
      apply Polynomial.monic_prod_of_monic
      intro z _
      exact Polynomial.monic_X_sub_C z

    have hQ_natDegree : (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X])).natDegree = k := by
      have h_deg : (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X])).natDegree = ∑ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X]).natDegree := by
        exact Polynomial.natDegree_prod (S.erase x) _ h_ne_zero
      rw [h_deg]
      have h_deg2 : ∑ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X]).natDegree = ∑ z ∈ S.erase x, 1 := by
        apply Finset.sum_congr rfl
        intro i _
        exact Polynomial.natDegree_X_sub_C i
      rw [h_deg2]
      have h_sum : ∑ z ∈ S.erase x, 1 = (S.erase x).card := by simp
      rw [h_sum, Finset.card_erase_of_mem hx, hS_card]
      omega

    have H_Q := H (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X])) hdvd (le_of_eq hQ_natDegree)

    have H_prod : ∃ i ∈ Finset.range k.succ, (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X])).coeff i = 0 := by
      exact Finset.prod_eq_zero_iff.mp H_Q

    rcases H_prod with ⟨i, hi_mem, hi_zero⟩

    have hi_lt : i < k.succ := by
      rw [Finset.mem_range] at hi_mem
      exact hi_mem

    have hik : i ≠ k := by
      rintro rfl
      have h_lead : (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X])).leadingCoeff = 1 := hQ_monic
      have h_lead_def : (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X])).coeff (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z : ℝ[X])).natDegree = 1 := h_lead
      rw [hQ_natDegree] at h_lead_def
      rw [h_lead_def] at hi_zero
      exact one_ne_zero hi_zero

    cases i with
    | zero =>
      rcases hdvd with ⟨R, hR⟩
      have hP0 : P.coeff 0 = 0 := by
        rw [hR, Polynomial.mul_coeff_zero, hi_zero, zero_mul]
      exact False.elim (hP hP0)
    | succ m =>
      use m
      constructor
      · omega
      · exact hi_zero

  let T := (Finset.range k).filter (fun m => m.succ < k)
  let f (x : ℝ) : ℕ := if hx : x ∈ S then Classical.choose (h_exists x hx) else 0

  have h_maps : ∀ x ∈ S, f x ∈ T := by
    intro x hx
    have hfx : f x = Classical.choose (h_exists x hx) := dif_pos hx
    rw [hfx]
    have hm := (Classical.choose_spec (h_exists x hx)).1
    rw [Finset.mem_filter, Finset.mem_range]
    exact ⟨by omega, hm⟩

  have h_card_lt : T.card < S.card := by
    calc T.card
      _ ≤ (Finset.range k).card := Finset.card_filter_le _ _
      _ = k := Finset.card_range k
      _ < k.succ := Nat.lt_succ_self k
      _ = S.card := hS_card.symm

  have h_ph : ∃ x ∈ S, ∃ y ∈ S, x ≠ y ∧ f x = f y := by
    apply Finset.exists_ne_map_eq_of_card_lt_of_maps_to h_card_lt
    intro x hx
    exact h_maps x hx

  rcases h_ph with ⟨x, hx, y, hy, hxy, hfxy⟩

  use x, y, (f x)
  refine ⟨hx, hy, hxy, ?_, ?_, ?_⟩
  · have hf_in := h_maps x hx
    rw [Finset.mem_filter] at hf_in
    exact hf_in.2
  · have hfx_eq : f x = Classical.choose (h_exists x hx) := dif_pos hx
    rw [hfx_eq]
    exact (Classical.choose_spec (h_exists x hx)).2
  · rw [hfxy]
    have hfy_eq : f y = Classical.choose (h_exists y hy) := dif_pos hy
    rw [hfy_eq]
    exact (Classical.choose_spec (h_exists y hy)).2

theorem consecutive_zeros_of_shared_index (S : Finset ℝ) (x y : ℝ) (hxy : x ≠ y)
    (hxS : x ∈ S) (hyS : y ∈ S) (m : ℕ)
    (hx : (∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z)).coeff m.succ = 0)
    (hy : (∏ z ∈ S.erase y, (Polynomial.X - Polynomial.C z)).coeff m.succ = 0) :
    (∏ z ∈ (S.erase x).erase y, (Polynomial.X - Polynomial.C z)).coeff m.succ = 0 ∧
    (∏ z ∈ (S.erase x).erase y, (Polynomial.X - Polynomial.C z)).coeff m = 0 :=
by
  set Q := ∏ z ∈ (S.erase x).erase y, (Polynomial.X - Polynomial.C z)

  have hy_in_erase_x : y ∈ S.erase x := by
    rw [Finset.mem_erase]
    exact ⟨hxy.symm, hyS⟩

  have hx_in_erase_y : x ∈ S.erase y := by
    rw [Finset.mem_erase]
    exact ⟨hxy, hxS⟩

  have hPx : (Polynomial.X - Polynomial.C y) * Q = ∏ z ∈ S.erase x, (Polynomial.X - Polynomial.C z) := by
    exact Finset.mul_prod_erase (S.erase x) (fun z => Polynomial.X - Polynomial.C z) hy_in_erase_x

  have hPy : (Polynomial.X - Polynomial.C x) * Q = ∏ z ∈ S.erase y, (Polynomial.X - Polynomial.C z) := by
    have H : (Polynomial.X - Polynomial.C x) * ∏ z ∈ (S.erase y).erase x, (Polynomial.X - Polynomial.C z) = ∏ z ∈ S.erase y, (Polynomial.X - Polynomial.C z) :=
      Finset.mul_prod_erase (S.erase y) (fun z => Polynomial.X - Polynomial.C z) hx_in_erase_y
    have H2 : (S.erase y).erase x = (S.erase x).erase y := by
      ext z
      simp only [Finset.mem_erase]
      tauto
    rw [H2] at H
    exact H

  have eq1 : Q.coeff m - y * Q.coeff m.succ = 0 := by
    have H : ((Polynomial.X - Polynomial.C y) * Q).coeff m.succ = Q.coeff m - y * Q.coeff m.succ := by
      change ((Polynomial.X - Polynomial.C y) * Q).coeff (m + 1) = Q.coeff m - y * Q.coeff (m + 1)
      rw [sub_mul, Polynomial.coeff_sub, Polynomial.coeff_X_mul, Polynomial.coeff_C_mul]
    rw [← H, hPx, hx]

  have eq2 : Q.coeff m - x * Q.coeff m.succ = 0 := by
    have H : ((Polynomial.X - Polynomial.C x) * Q).coeff m.succ = Q.coeff m - x * Q.coeff m.succ := by
      change ((Polynomial.X - Polynomial.C x) * Q).coeff (m + 1) = Q.coeff m - x * Q.coeff (m + 1)
      rw [sub_mul, Polynomial.coeff_sub, Polynomial.coeff_X_mul, Polynomial.coeff_C_mul]
    rw [← H, hPy, hy]

  have eq3 : (x - y) * Q.coeff m.succ = 0 := by
    calc (x - y) * Q.coeff m.succ
      _ = (Q.coeff m - y * Q.coeff m.succ) - (Q.coeff m - x * Q.coeff m.succ) := by ring
      _ = 0 - 0 := by rw [eq1, eq2]
      _ = 0 := by ring

  have hxy_sub : x - y ≠ 0 := sub_ne_zero.mpr hxy

  have h_succ : Q.coeff m.succ = 0 := by
    match mul_eq_zero.mp eq3 with
    | Or.inl h => exact False.elim (hxy_sub h)
    | Or.inr h => exact h

  have h_m : Q.coeff m = 0 := by
    calc Q.coeff m
      _ = Q.coeff m - y * Q.coeff m.succ + y * Q.coeff m.succ := by ring
      _ = 0 + y * 0 := by rw [eq1, h_succ]
      _ = 0 := by ring

  exact ⟨h_succ, h_m⟩

theorem poly_coeff_zero_eq_prod (S : Finset ℝ) :
    (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).coeff 0 = ∏ z ∈ S, (-z) :=
by
  have H : (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).coeff 0 = Polynomial.aeval (0 : ℝ) (∏ z ∈ S, (Polynomial.X - Polynomial.C z)) := by
    have h := Polynomial.coeff_zero_eq_aeval_zero' (R := ℝ) (A := ℝ) (∏ z ∈ S, (Polynomial.X - Polynomial.C z))
    simpa using h
  rw [H, map_prod]
  apply Finset.prod_congr rfl
  intro x _
  have H2 : (Polynomial.X - Polynomial.C x).coeff 0 = Polynomial.aeval (0 : ℝ) (Polynomial.X - Polynomial.C x) := by
    have h := Polynomial.coeff_zero_eq_aeval_zero' (R := ℝ) (A := ℝ) (Polynomial.X - Polynomial.C x)
    simpa using h
  rw [← H2]
  simp

theorem prod_roots_neq_zero (S : Finset ℝ) (hS_nonzero : ∀ z ∈ S, z ≠ 0) :
    ∏ z ∈ S, (-z) ≠ 0 :=
by
  intro h
  rw [Finset.prod_eq_zero_iff] at h
  obtain ⟨z, hz, hz_zero⟩ := h
  have hz_eq_zero : z = 0 := by linarith
  exact hS_nonzero z hz hz_eq_zero

theorem P_natDegree (S : Finset ℝ) :
    (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).natDegree = S.card :=
by
  exact Polynomial.natDegree_multiset_prod_X_sub_C_eq_card S.val

theorem P_coeff_natDegree (S : Finset ℝ) :
    (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).coeff S.card = 1 :=
by
  have Hmonic : (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).Monic := by
    apply Polynomial.monic_prod_of_monic
    intro i _
    exact Polynomial.monic_X_sub_C i

  have Hdeg : (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).natDegree = S.card := by
    -- The degree of a product of monic polynomials equals the sum of their degrees
    have h_prod : (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).natDegree = ∑ z ∈ S, (Polynomial.X - Polynomial.C z).natDegree := by
      apply Polynomial.natDegree_prod_of_monic
      intro i _
      exact Polynomial.monic_X_sub_C i
    rw [h_prod]

    -- Each term has degree 1
    have h_deg : ∀ z ∈ S, (Polynomial.X - Polynomial.C z).natDegree = 1 := by
      intro z _
      exact Polynomial.natDegree_X_sub_C z

    -- Substitute the degrees into the sum and simplify
    rw [Finset.sum_congr rfl h_deg]
    simp

  -- Using definition of Monic, the coefficient at natDegree is equal to 1.
  rw [← Hdeg]
  exact Hmonic

theorem deriv_ne_zero_of_natDegree_pos {p : ℝ[X]} (hp : 0 < p.natDegree) :
    derivative p ≠ 0 :=
by
  intro h
  -- If the derivative is 0, the natural degree of the polynomial must be 0.
  have h_deg : p.natDegree = 0 := natDegree_eq_zero_of_derivative_eq_zero h
  -- This contradicts the hypothesis that 0 < p.natDegree.
  omega

theorem card_roots_toFinset_le_natDegree (p : ℝ[X]) : p.roots.toFinset.card ≤ p.natDegree :=
le_trans (Multiset.toFinset_card_le p.roots) (Polynomial.card_roots' p)

theorem card_sdiff_roots_le (p : ℝ[X]) :
    ((derivative p).roots.toFinset \ p.roots.toFinset).card ≤ (derivative p).roots.toFinset.card :=
by
  exact Finset.card_le_card Finset.sdiff_subset

theorem card_roots_deriv_ge {p : ℝ[X]} (hp_deriv : derivative p ≠ 0) :
    p.roots.toFinset.card ≤ (derivative p).roots.toFinset.card + 1 :=
by
  have h1 := Polynomial.card_roots_toFinset_le_card_roots_derivative_diff_roots_succ p
  have h2 := card_sdiff_roots_le p
  omega

theorem card_eq_natDegree_of_hasAllDistinctRoots {p : ℝ[X]} (h : HasAllDistinctRoots p) :
    p.roots.toFinset.card = p.natDegree :=
h

theorem hasAllDistinctRoots_of_card_eq_natDegree {p : ℝ[X]} (h : p.roots.toFinset.card = p.natDegree) :
    HasAllDistinctRoots p :=
h

theorem HasAllDistinctRoots_deriv_and_degree {p : ℝ[X]} (h : HasAllDistinctRoots p) (hp : 0 < p.natDegree) :
    HasAllDistinctRoots (derivative p) ∧ p.natDegree = (derivative p).natDegree + 1 :=
by
  have h_deriv_ne_zero : derivative p ≠ 0 := deriv_ne_zero_of_natDegree_pos hp
  have H1 : (derivative p).roots.toFinset.card ≤ (derivative p).natDegree := card_roots_toFinset_le_natDegree (derivative p)
  have H2 : p.roots.toFinset.card ≤ (derivative p).roots.toFinset.card + 1 := card_roots_deriv_ge h_deriv_ne_zero
  have H3 : (derivative p).natDegree ≤ p.natDegree - 1 := Polynomial.natDegree_derivative_le p
  have h_card : p.roots.toFinset.card = p.natDegree := card_eq_natDegree_of_hasAllDistinctRoots h
  have eq1 : (derivative p).roots.toFinset.card = (derivative p).natDegree := by omega
  have eq2 : p.natDegree = (derivative p).natDegree + 1 := by omega
  exact ⟨hasAllDistinctRoots_of_card_eq_natDegree eq1, eq2⟩

theorem iterate_deriv_succ_eq (p : ℝ[X]) (m : ℕ) :
    derivative^[m.succ] p = derivative (derivative^[m] p) :=
by
  exact Function.iterate_succ_apply' derivative m p

theorem HasAllDistinctRoots_iterate_deriv_and_degree {p : ℝ[X]} (h : HasAllDistinctRoots p) (m : ℕ) (hm : m ≤ p.natDegree) :
    HasAllDistinctRoots (derivative^[m] p) ∧ p.natDegree = (derivative^[m] p).natDegree + m :=
by
  induction m with
  | zero =>
    exact ⟨h, rfl⟩
  | succ k ih =>
    have hk : k ≤ p.natDegree := by omega
    have ih_res := ih hk
    have ih_roots := ih_res.1
    have ih_deg := ih_res.2

    -- Ensure the degree is strictly positive before differentiating
    have hpos : 0 < (derivative^[k] p).natDegree := by omega

    -- Apply the single differentiation step logic
    have H := HasAllDistinctRoots_deriv_and_degree ih_roots hpos
    have H_roots := H.1
    have H_deg := H.2

    -- Expose the iterative definition boundary and rewrite
    have h_eq : derivative^[k + 1] p = derivative (derivative^[k] p) := iterate_deriv_succ_eq p k
    rw [h_eq]

    -- Close the structural distinct roots and addition-bounded degree constraints
    exact ⟨H_roots, by omega⟩

theorem HasAllDistinctRoots_iterate_deriv {p : ℝ[X]} (h : HasAllDistinctRoots p) (m : ℕ) (hm : m ≤ p.natDegree) :
    HasAllDistinctRoots (derivative^[m] p) :=
by
  have h_iter := HasAllDistinctRoots_iterate_deriv_and_degree h m hm
  exact h_iter.1

theorem isRoot_of_mem_toFinset {p : ℝ[X]} {x : ℝ} (hx : x ∈ p.roots.toFinset) :
    IsRoot p x :=
by
  -- Convert membership in the Finset back to membership in the original Multiset of roots
  have h_mem : x ∈ p.roots := Multiset.mem_toFinset.mp hx
  -- Any element inside the multiset of roots is a valid root of the polynomial
  exact isRoot_of_mem_roots h_mem

theorem exists_mul_of_isRoot {p : ℝ[X]} {x : ℝ} (h : IsRoot p x) :
    ∃ q : ℝ[X], p = (X - C x) * q :=
by
  exact Polynomial.dvd_iff_isRoot.mpr h

theorem eval_derivative_X_sub_C_mul (q : ℝ[X]) (x : ℝ) :
    Polynomial.eval x (derivative ((X - C x) * q)) = Polynomial.eval x q :=
by
  simp

theorem isRoot_of_isRoot_mul_left_of_isRoot_deriv {p q : ℝ[X]} {x : ℝ}
    (hp : p = (X - C x) * q) (h_deriv : IsRoot (derivative p) x) :
    IsRoot q x :=
by
  rw [IsRoot.def] at h_deriv ⊢
  rw [hp] at h_deriv
  rw [eval_derivative_X_sub_C_mul] at h_deriv
  exact h_deriv

theorem exists_eq_sq_mul_of_isRoot_of_isRoot_deriv {p : ℝ[X]} {x : ℝ} (h0 : IsRoot p x) (h1 : IsRoot (derivative p) x) :
    ∃ q : ℝ[X], p = (X - C x)^2 * q :=
by
  -- Since x is a root of p, we can factor it out
  rcases exists_mul_of_isRoot h0 with ⟨q1, hq1⟩

  -- Show that x is also a root of the factor q1
  have hq1_root : IsRoot q1 x := isRoot_of_isRoot_mul_left_of_isRoot_deriv hq1 h1

  -- Since x is a root of q1, we can factor it out again
  rcases exists_mul_of_isRoot hq1_root with ⟨q2, hq2⟩

  -- Provide q2 as our witness
  use q2

  -- Substitute the factorizations backward
  rw [hq1, hq2]

  -- Close the algebraic equality with the `ring` tactic
  ring

theorem q_ne_zero_of_p_ne_zero {p q : ℝ[X]} {x : ℝ} (hp : p ≠ 0) (h : p = (X - C x)^2 * q) : q ≠ 0 :=
by
  rintro rfl
  rw [mul_zero] at h
  exact hp h

theorem X_sub_C_sq_ne_zero (x : ℝ) : ((X - C x)^2 : ℝ[X]) ≠ 0 :=
by
  intro h
  have h1 : (X - C x : ℝ[X]) * (X - C x) = 0 := by
    calc (X - C x) * (X - C x) = (X - C x)^2 := by ring
    _ = 0 := h
  have h2 : (X - C x : ℝ[X]) = 0 :=
    Or.elim (mul_eq_zero.mp h1) (fun h' => h') (fun h' => h')
  exact Polynomial.X_sub_C_ne_zero x h2

theorem natDegree_X_sub_C_sq (x : ℝ) : ((X - C x)^2 : ℝ[X]).natDegree = 2 :=
by
  -- Show that (X - C x) is Monic (leading coefficient is 1)
  have h_eq : (X - C x : ℝ[X]) = X + C (-x) := by
    rw [sub_eq_add_neg, ← map_neg]
  have h_monic : (X - C x : ℝ[X]).Monic := by
    change (X - C x : ℝ[X]).leadingCoeff = 1
    rw [h_eq, Polynomial.leadingCoeff_X_add_C]

  -- Show that the natural degree of (X - C x) is exactly 1
  have h_deg : (X - C x : ℝ[X]).natDegree = 1 := by
    have : (X - C x : ℝ[X]) = X ^ 1 - C x := by rw [pow_one]
    rw [this, Polynomial.natDegree_X_pow_sub_C]

  -- Compute the degree of the squared polynomial
  calc
    ((X - C x)^2 : ℝ[X]).natDegree = 2 * (X - C x : ℝ[X]).natDegree := Polynomial.Monic.natDegree_pow h_monic 2
    _ = 2 * 1 := by rw [h_deg]
    _ = 2 := rfl

theorem natDegree_mul_of_ne_zero {p q : ℝ[X]} (hp : p ≠ 0) (hq : q ≠ 0) :
    (p * q).natDegree = p.natDegree + q.natDegree :=
by
  exact Polynomial.natDegree_mul hp hq

theorem natDegree_eq_of_eq_sq_mul {p q : ℝ[X]} {x : ℝ} (hp : p ≠ 0) (h : p = (X - C x)^2 * q) :
    p.natDegree = 2 + q.natDegree :=
by
  have hq : q ≠ 0 := q_ne_zero_of_p_ne_zero hp h
  have hsq_ne_zero : ((X - C x)^2 : ℝ[X]) ≠ 0 := X_sub_C_sq_ne_zero x
  have hsq_deg : ((X - C x)^2 : ℝ[X]).natDegree = 2 := natDegree_X_sub_C_sq x
  rw [h]
  rw [natDegree_mul_of_ne_zero hsq_ne_zero hq]
  rw [hsq_deg]

theorem common_root_implies_eq_mul {p : ℝ[X]} {x : ℝ} (hp : p ≠ 0) (h0 : IsRoot p x) (h1 : IsRoot (derivative p) x) :
    ∃ q : ℝ[X], p = (X - C x)^2 * q ∧ p.natDegree = 2 + q.natDegree :=
by
  -- Obtain the factorization polynomial `q` and the equality proof `hq`
  obtain ⟨q, hq⟩ := exists_eq_sq_mul_of_isRoot_of_isRoot_deriv h0 h1
  -- Provide the witness `q`, the equality `hq`, and the derived degree equality
  exact ⟨q, hq, natDegree_eq_of_eq_sq_mul hp hq⟩

theorem roots_toFinset_mul {A B : ℝ[X]} (h : A * B ≠ 0) :
    (A * B).roots.toFinset = A.roots.toFinset ∪ B.roots.toFinset :=
by
  rw [Polynomial.roots_mul h]
  rw [Multiset.toFinset_add]

theorem natDegree_X_sub_C_eq_one (x : ℝ) : ((X - C x) : ℝ[X]).natDegree = 1 :=
by
  exact Polynomial.natDegree_X_sub_C x

theorem X_sub_C_ne_zero (x : ℝ) : (X - C x : ℝ[X]) ≠ 0 :=
by
  intro h
  have h1 := natDegree_X_sub_C_eq_one x
  rw [h, Polynomial.natDegree_zero] at h1
  contradiction

theorem X_sub_C_mul_X_sub_C_ne_zero (x : ℝ) : ((X - C x) * (X - C x) : ℝ[X]) ≠ 0 :=
mul_ne_zero (_root_.X_sub_C_ne_zero x) (_root_.X_sub_C_ne_zero x)

theorem sq_roots_toFinset_eq (x : ℝ) : ((X - C x)^2 : ℝ[X]).roots.toFinset = (X - C x).roots.toFinset :=
by
  have h1 : ((X - C x)^2 : ℝ[X]) = (X - C x) * (X - C x) := by ring
  rw [h1]
  rw [roots_toFinset_mul (X_sub_C_mul_X_sub_C_ne_zero x)]
  ext a
  simp

theorem card_roots_X_sub_C_le_one (x : ℝ) : ((X - C x) : ℝ[X]).roots.toFinset.card ≤ 1 :=
by
  have h := card_roots_toFinset_le_natDegree ((X - C x) : ℝ[X])
  rw [natDegree_X_sub_C_eq_one x] at h
  exact h

theorem card_roots_sq_X_sub_C_le (x : ℝ) : ((X - C x)^2 : ℝ[X]).roots.toFinset.card ≤ 1 :=
by
  have h1 := sq_roots_toFinset_eq x
  have h2 := card_roots_X_sub_C_le_one x
  rw [h1]
  exact h2

theorem finset_card_union_le {α : Type*} [DecidableEq α] (s t : Finset α) :
    (s ∪ t).card ≤ s.card + t.card :=
by
  exact Finset.card_union_le s t

theorem card_roots_le_of_eq_mul {p q : ℝ[X]} {x : ℝ} (hp : p ≠ 0) (h : p = (X - C x)^2 * q) :
    p.roots.toFinset.card ≤ 1 + q.roots.toFinset.card :=
by
  -- Substitute the factorization of p into both the goal and the non-zero hypothesis
  rw [h]
  rw [h] at hp

  -- Break the Finset of roots into the union of the roots of each polynomial factor
  rw [roots_toFinset_mul hp]

  -- Bound the cardinality of the combined distinct roots
  have h_union := finset_card_union_le ((X - C x)^2 : ℝ[X]).roots.toFinset q.roots.toFinset
  have h_sq := card_roots_sq_X_sub_C_le x

  -- Conclude the inequality using Lean's linear integer arithmetic solver
  omega

theorem card_roots_toFinset_lt_natDegree_of_common_root {p : ℝ[X]} {x : ℝ}
    (hp : p ≠ 0) (h0 : IsRoot p x) (h1 : IsRoot (derivative p) x) :
    p.roots.toFinset.card < p.natDegree :=
by
  -- 1. Extract the quotient polynomial q and the related linear degree property
  obtain ⟨q, hpq, hdeg⟩ := common_root_implies_eq_mul hp h0 h1

  -- 2. Bound the cardinality of roots of p by (1 + cardinality of roots of q)
  have h_card := card_roots_le_of_eq_mul hp hpq

  -- 3. Bound the cardinality of roots of q by its degree
  have h_deg_q := card_roots_toFinset_le_natDegree q

  -- 4. Solve the linear arithmetic inequalities naturally with omega
  omega

theorem disjoint_zero_roots : Disjoint (derivative (0 : ℝ[X])).roots.toFinset (0 : ℝ[X]).roots.toFinset :=
by
  simp

theorem disjoint_of_no_common_elements {α : Type*} {s t : Finset α}
    (h : ∀ x, x ∈ s → x ∈ t → False) : Disjoint s t :=
by
  rw [Finset.disjoint_left]
  intro x hx hxt
  exact h x hx hxt

theorem disjoint_roots_of_HasAllDistinctRoots {p : ℝ[X]} (h : HasAllDistinctRoots p) :
    Disjoint (derivative p).roots.toFinset p.roots.toFinset :=
by
  by_cases hp : p = 0
  · rw [hp]
    exact disjoint_zero_roots
  · apply disjoint_of_no_common_elements
    intro x hx hx_p
    have h0 := isRoot_of_mem_toFinset hx_p
    have h1 := isRoot_of_mem_toFinset hx
    have h_lt := card_roots_toFinset_lt_natDegree_of_common_root hp h0 h1
    have h_eq := card_eq_natDegree_of_hasAllDistinctRoots h
    omega

theorem P_HasAllDistinctRoots (S : Finset ℝ) :
    HasAllDistinctRoots (∏ z ∈ S, (Polynomial.X - Polynomial.C z)) :=
by
  unfold HasAllDistinctRoots
  simp [Polynomial.roots_prod_X_sub_C]

theorem iterate_succ_apply_deriv (m : ℕ) (p : ℝ[X]) :
    derivative^[m + 1] p = derivative^[m] (derivative p) :=
by
  exact Function.iterate_succ_apply _ m p

theorem factorial_mul_deriv_coeff (m : ℕ) (p : ℝ[X]) :
    (Nat.factorial m : ℝ) * (derivative p).coeff m = (Nat.factorial (m + 1) : ℝ) * p.coeff (m + 1) :=
by
  -- Rewrite the derivative coefficient: (derivative p).coeff m = p.coeff (m + 1) * (m + 1)
  rw [Polynomial.coeff_derivative]

  -- Expand the factorial definition for the successor
  have h : Nat.factorial (m + 1) = (m + 1) * Nat.factorial m := rfl
  rw [h]

  -- Push all natural number coercions to real numbers down to additions and multiplications
  push_cast

  -- The resulting equality is a straightforward real arithmetic identity
  ring

theorem iterate_deriv_coeff_zero (m : ℕ) (p : ℝ[X]) :
    (derivative^[m] p).coeff 0 = (Nat.factorial m : ℝ) * p.coeff m :=
by
  induction m generalizing p with
  | zero =>
    simp
  | succ m ih =>
    -- We state the goal replacing `Nat.succ m` with `m + 1` to cleanly align with our lemmas
    change (derivative^[m + 1] p).coeff 0 = (Nat.factorial (m + 1) : ℝ) * p.coeff (m + 1)

    -- 1. Shift the derivative evaluation inside
    rw [iterate_succ_apply_deriv m p]

    -- 2. Apply the induction hypothesis specialized to the polynomial (derivative p)
    rw [ih (derivative p)]

    -- 3. Restructure the factorial product algebraically using the helper lemma
    rw [factorial_mul_deriv_coeff m p]

theorem isRoot_iterate_deriv_of_coeff_zero {p : ℝ[X]} {m : ℕ} (h : p.coeff m = 0) :
    IsRoot (derivative^[m] p) 0 :=
by
  -- 1. Unfold the definition of IsRoot (evaluating the polynomial at 0 equals 0)
  rw [Polynomial.IsRoot.def]

  -- 2. Evaluating any polynomial at 0 is identical to extracting its 0-th coefficient
  rw [← Polynomial.coeff_zero_eq_eval_zero]

  -- 3. The 0-th coefficient of the m-th derivative corresponds to m! * p_m
  rw [iterate_deriv_coeff_zero]

  -- 4. Substitute our hypothesis that the m-th coefficient of p is 0
  rw [h]

  -- 5. Complete the proof by multiplying by zero
  rw [mul_zero]

theorem iterate_deriv_coeff_eq (p : ℝ[X]) (m k : ℕ) :
  (derivative^[m] p).coeff k = ((k + m).descFactorial m : ℝ) * p.coeff (k + m) :=
by
  rw [Polynomial.coeff_iterate_derivative, nsmul_eq_mul]

theorem nat_descFactorial_add_ne_zero (k m : ℕ) :
  ((k + m).descFactorial m : ℝ) ≠ 0 :=
by
  have H : (k + m).descFactorial m ≠ 0 := by
    induction m with
    | zero =>
      have h_zero : (k + 0).descFactorial 0 = 1 := rfl
      rw [h_zero]
      omega
    | succ m ih =>
      -- Shift definitions syntactically from `Nat.succ x` to `x + 1` to match Mathlib lemmas
      change (k + m + 1).descFactorial (m + 1) ≠ 0
      rw [Nat.succ_descFactorial_succ]
      intro h
      cases mul_eq_zero.mp h with
      | inl h1 => omega
      | inr h2 => exact ih h2
  exact_mod_cast H

theorem coeff_natDegree_ne_zero {p : ℝ[X]} (hp : p ≠ 0) :
  p.coeff p.natDegree ≠ 0 :=
Polynomial.leadingCoeff_ne_zero.mpr hp

theorem iterate_deriv_coeff_ne_zero_of_add_eq_natDegree (p : ℝ[X]) (m k : ℕ)
  (h_sum : k + m = p.natDegree) (hp : p ≠ 0) :
  (derivative^[m] p).coeff k ≠ 0 :=
by
  rw [iterate_deriv_coeff_eq p m k]
  apply mul_ne_zero
  · exact nat_descFactorial_add_ne_zero k m
  · rw [h_sum]
    exact coeff_natDegree_ne_zero hp

theorem iterate_deriv_neq_zero {p : ℝ[X]} (h : HasAllDistinctRoots p) (h_deg : 0 < p.natDegree) (m : ℕ) (hm : m ≤ p.natDegree) :
    derivative^[m] p ≠ 0 :=
by
  -- 1. Deduce that p is not the zero polynomial based on its strictly positive natural degree.
  have hp : p ≠ 0 := Polynomial.ne_zero_of_natDegree_gt h_deg

  -- 2. Extract the additive complement `k` avoiding `-` operators on `ℕ`.
  -- Lean 4's `Nat.exists_eq_add_of_le` gives `∃ k, p.natDegree = m + k` from `m ≤ p.natDegree`.
  obtain ⟨k, hk⟩ := Nat.exists_eq_add_of_le hm
  have hk_sum : k + m = p.natDegree := by omega

  -- 3. Apply the core mathematical property helper.
  have h_coeff_ne := iterate_deriv_coeff_ne_zero_of_add_eq_natDegree p m k hk_sum hp

  -- 4. Proceed by contradiction on the final polynomial equality.
  intro h_eq_zero
  rw [h_eq_zero] at h_coeff_ne
  simp only [Polynomial.coeff_zero] at h_coeff_ne

  -- `h_coeff_ne` is now logically equivalent to `0 ≠ 0`, which is universally false.
  exact h_coeff_ne rfl

theorem mem_roots_of_isRoot {p : ℝ[X]} {x : ℝ} (h_root : IsRoot p x) (h_neq : p ≠ 0) :
    x ∈ p.roots.toFinset :=
by
  rw [Multiset.mem_toFinset, Polynomial.mem_roots']
  exact ⟨h_neq, h_root⟩

theorem disjoint_contradiction {α : Type*} {s t : Finset α} {x : α}
    (h_disj : Disjoint s t) (hx_s : x ∈ s) (hx_t : x ∈ t) : False :=
Finset.disjoint_left.mp h_disj hx_s hx_t

theorem zero_neq_one_real (h : (0 : ℝ) = 1) : False :=
zero_ne_one h

theorem consecutive_zeros_impl_prev_zero (S : Finset ℝ) (k : ℕ)
    (hk_bound : k < S.card)
    (hk1 : (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).coeff k.succ.succ = 0)
    (hk0 : (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).coeff k.succ = 0) :
    (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).coeff k = 0 :=
by
  let P := ∏ z ∈ S, (Polynomial.X - Polynomial.C z)
  have hP_deg : P.natDegree = S.card := P_natDegree S

  have h_cases : k.succ = S.card ∨ k.succ < S.card := by omega

  rcases h_cases with hk_eq | hk_lt
  · -- Case 1: k+1 reaches exactly the degree of the polynomial
    have h1 : P.coeff S.card = 1 := P_coeff_natDegree S
    have h2 : P.coeff k.succ = 1 := by
      rw [hk_eq]
      exact h1
    have h3 : (1 : ℝ) = 0 := by
      calc (1 : ℝ) = P.coeff k.succ := h2.symm
        _ = 0 := hk0
    exfalso
    exact zero_neq_one_real h3.symm

  · -- Case 2: k+1 is strictly less than the degree
    have hk_lt2 : k.succ.succ ≤ S.card := by omega
    have hk_le : k.succ ≤ S.card := by omega

    have hP_dist : HasAllDistinctRoots P := P_HasAllDistinctRoots S
    have h_deg_pos : 0 < P.natDegree := by
      rw [hP_deg]
      omega

    let Q := derivative^[k.succ] P
    have hQ_dist : HasAllDistinctRoots Q := by
      apply HasAllDistinctRoots_iterate_deriv hP_dist
      rw [hP_deg]
      exact hk_le

    have hQ_disj : Disjoint (derivative Q).roots.toFinset Q.roots.toFinset :=
      disjoint_roots_of_HasAllDistinctRoots hQ_dist

    have hQ_root : IsRoot Q 0 := isRoot_iterate_deriv_of_coeff_zero hk0
    have hQ_neq : Q ≠ 0 := by
      apply iterate_deriv_neq_zero hP_dist h_deg_pos
      rw [hP_deg]
      exact hk_le
    have h0_in_Q : (0 : ℝ) ∈ Q.roots.toFinset := mem_roots_of_isRoot hQ_root hQ_neq

    have hQ_deriv_eq : derivative Q = derivative^[k.succ.succ] P := by
      exact (iterate_deriv_succ_eq P k.succ).symm

    have hQ_deriv_root : IsRoot (derivative Q) 0 := by
      rw [hQ_deriv_eq]
      exact isRoot_iterate_deriv_of_coeff_zero hk1

    have hQ_deriv_neq : derivative Q ≠ 0 := by
      rw [hQ_deriv_eq]
      apply iterate_deriv_neq_zero hP_dist h_deg_pos
      rw [hP_deg]
      exact hk_lt2

    have h0_in_Q_deriv : (0 : ℝ) ∈ (derivative Q).roots.toFinset :=
      mem_roots_of_isRoot hQ_deriv_root hQ_deriv_neq

    -- Reached a contradiction, meaning such polynomials cannot have two consecutive internal zero coefficients!
    exfalso
    exact disjoint_contradiction hQ_disj h0_in_Q_deriv h0_in_Q

theorem consecutive_zeros_impl_const_zero (S : Finset ℝ) (m : ℕ)
    (hm : m < S.card)
    (h1 : (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).coeff m.succ = 0)
    (h2 : (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).coeff m = 0) :
    (∏ z ∈ S, (Polynomial.X - Polynomial.C z)).coeff 0 = 0 :=
by
  revert hm h1 h2
  induction m with
  | zero =>
    intro _ _ h2
    exact h2
  | succ k ih =>
    intro hm h1 h2
    apply ih
    · omega
    · exact h2
    · apply consecutive_zeros_impl_prev_zero S k
      · omega
      · exact h1
      · exact h2

theorem real_poly_no_consecutive_zero_coeffs (S_rem : Finset ℝ) (hS_nonzero : ∀ z ∈ S_rem, z ≠ 0)
    (m : ℕ) (hm : m < S_rem.card)
    (h1 : (∏ z ∈ S_rem, (Polynomial.X - Polynomial.C z)).coeff m.succ = 0)
    (h2 : (∏ z ∈ S_rem, (Polynomial.X - Polynomial.C z)).coeff m = 0) :
    False :=
by
  have h_const_zero := consecutive_zeros_impl_const_zero S_rem m hm h1 h2
  have h_const_prod := poly_coeff_zero_eq_prod S_rem
  rw [h_const_prod] at h_const_zero
  have h_prod_neq_zero := prod_roots_neq_zero S_rem hS_nonzero
  exact h_prod_neq_zero h_const_zero

theorem poly_coeff_zero (P : ℝ[X]) : P.coeff 0 = P.eval 0 :=
by
  exact Polynomial.coeff_zero_eq_eval_zero P

theorem S_rem_card_eq (S : Finset ℝ) (k : ℕ) (hS_card : S.card = k.succ) (x y : ℝ)
    (hx : x ∈ S) (hy : y ∈ S) (hxy : x ≠ y) : ((S.erase x).erase y).card + 1 = k :=
by
  have hy_in : y ∈ S.erase x := Finset.mem_erase_of_ne_of_mem hxy.symm hy
  have h1 : ((S.erase x).erase y).card + 1 = (S.erase x).card := Finset.card_erase_add_one hy_in
  have h2 : (S.erase x).card + 1 = S.card := Finset.card_erase_add_one hx
  omega

theorem m_lt_card (k m : ℕ) (hm : m.succ < k) (S_rem : Finset ℝ) (hcard : S_rem.card + 1 = k) :
    m < S_rem.card :=
by
  omega

theorem PBAdvanced026 (P : ℝ[X]) (hP : P.coeff 0 ≠ 0) (hP' : (P.aroots ℂ).Nodup)
    (k : ℕ) (hk : 0 < k) (hkn : k < P.natDegree)
    (H : ∀ Q, Q ∣ P → Q.natDegree ≤ k →
      ∏ i ∈ Finset.range k.succ, Q.coeff i = 0) : ∃ z, z.im ≠ 0 ∧ z ∈ P.aroots ℂ :=
by
  by_contra h_contra
  have h_contra' : ∀ z ∈ P.aroots ℂ, z.im = 0 := by
    intro z hz
    by_contra h
    exact h_contra ⟨z, h, hz⟩

  have hS_ex := exists_subset_roots P k hP' hkn h_contra'
  rcases hS_ex with ⟨S, hS_card, hS_roots⟩

  have h_shared := exists_shared_zero_coeff P k hP S hS_card hS_roots H
  rcases h_shared with ⟨x, y, m, hxS, hyS, hxy, hm, hx_zero, hy_zero⟩

  have h_cons := consecutive_zeros_of_shared_index S x y hxy hxS hyS m hx_zero hy_zero
  rcases h_cons with ⟨h1, h2⟩

  let S_rem := (S.erase x).erase y
  have hS_rem_nonzero : ∀ z ∈ S_rem, z ≠ 0 := by
    intro z hz
    have h1 : z ∈ S.erase x := (Finset.mem_erase.mp hz).2
    have hz_in_S : z ∈ S := (Finset.mem_erase.mp h1).2
    have hz_root := hS_roots z hz_in_S
    intro hz_zero
    have h_eval : P.eval z = 0 := hz_root
    rw [hz_zero] at h_eval
    rw [← poly_coeff_zero P] at h_eval
    exact hP h_eval

  have hS_rem_card : S_rem.card + 1 = k := S_rem_card_eq S k hS_card x y hxS hyS hxy
  have hm_lt : m < S_rem.card := m_lt_card k m hm S_rem hS_rem_card

  exact real_poly_no_consecutive_zero_coeffs S_rem hS_rem_nonzero m hm_lt h1 h2
