import Mathlib
open Polynomial

theorem RHS_subset_LHS :
    {(X - C a) ^ d | (a : ℤ) (d : ℕ) (_ : d ∣ 2024)} ∪
    {(- X - C a) ^ d | (a : ℤ) (d : ℕ) (_ : d ∣ 2024)} ⊆
    {P : ℤ[X] | ∀ n ≥ 0, ∃ x, P.eval x = n ^ 2024} :=
by
  rintro P (⟨a, d, hd, rfl⟩ | ⟨a, d, hd, rfl⟩)
  · intro n hn
    rcases hd with ⟨c, hc⟩
    use n ^ c + a
    have h1 : ((X - C a) ^ d).eval (n ^ c + a) = (n ^ c + a - a) ^ d := by
      simp only [Polynomial.eval_pow, Polynomial.eval_sub, Polynomial.eval_add, Polynomial.eval_neg, Polynomial.eval_X, Polynomial.eval_C]
    have h2 : (n ^ c + a - a) ^ d = (n ^ c) ^ d := by ring
    have h3 : (n ^ c) ^ d = n ^ (c * d) := by rw [← pow_mul]
    have h4 : n ^ (c * d) = n ^ (d * c) := by rw [mul_comm c d]
    have h5 : n ^ (d * c) = n ^ 2024 := by rw [← hc]
    rw [h1, h2, h3, h4, h5]
  · intro n hn
    rcases hd with ⟨c, hc⟩
    use - (n ^ c) - a
    have h1 : ((-X - C a) ^ d).eval (- (n ^ c) - a) = (- (- (n ^ c) - a) - a) ^ d := by
      simp only [Polynomial.eval_pow, Polynomial.eval_sub, Polynomial.eval_add, Polynomial.eval_neg, Polynomial.eval_X, Polynomial.eval_C]
    have h2 : (- (- (n ^ c) - a) - a) ^ d = (n ^ c) ^ d := by ring
    have h3 : (n ^ c) ^ d = n ^ (c * d) := by rw [← pow_mul]
    have h4 : n ^ (c * d) = n ^ (d * c) := by rw [mul_comm c d]
    have h5 : n ^ (d * c) = n ^ 2024 := by rw [← hc]
    rw [h1, h2, h3, h4, h5]

theorem exists_zero_root (P : ℤ[X]) (h : ∀ (n : ℤ), n ≥ 0 → ∃ (x : ℤ), P.eval x = n ^ 2024) :
  ∃ c : ℤ, P.eval c = 0 :=
by
  have h0 : (0 : ℤ) ≥ 0 := by omega
  obtain ⟨c, hc⟩ := h 0 h0
  use c
  rw [hc]
  norm_num

theorem prime_fiber_condition (P : ℤ[X]) (c : ℤ) (hc : P.eval c = 0)
  (hP : ∀ (n : ℤ), n ≥ 0 → ∃ (x : ℤ), P.eval x = n ^ 2024) :
  ∀ p : ℕ, Nat.Prime p →
  ∃ (ε : ℤ) (r : ℕ), (ε = 1 ∨ ε = -1) ∧ r ≤ 2024 ∧ P.eval (c + ε * (p : ℤ) ^ r) = (p : ℤ) ^ 2024 :=
by
  intro p hp

  -- Show that p as an integer is non-negative
  have hp_pos : (p : ℤ) ≥ 0 := by omega

  -- Obtain the integer x from the hypothesis hP
  obtain ⟨x, hx⟩ := hP (p : ℤ) hp_pos

  -- Apply the fundamental property that (x - c) divides P(x) - P(c)
  have h_dvd : x - c ∣ P.eval x - P.eval c := Polynomial.sub_dvd_eval_sub x c P

  -- Simplify using P(c) = 0 and P(x) = p^2024
  rw [hc, sub_zero, hx] at h_dvd

  -- Establish divisibility of natural absolute values
  have h_dvd2 : (x - c).natAbs ∣ p ^ 2024 := by
    obtain ⟨k, hk⟩ := h_dvd
    use k.natAbs
    have h_cast : ((p : ℤ) ^ 2024) = ((p ^ 2024 : ℕ) : ℤ) := by push_cast; rfl
    have h_eq : ((p : ℤ) ^ 2024).natAbs = p ^ 2024 := by
      rw [h_cast]
      omega
    calc p ^ 2024 = ((p : ℤ) ^ 2024).natAbs := h_eq.symm
    _ = ((x - c) * k).natAbs := by rw [hk]
    _ = (x - c).natAbs * k.natAbs := Int.natAbs_mul (x - c) k

  -- Prime p implies p > 0, which gives p^2024 ≠ 0
  have hp_pos_nat : 0 < p := by
    have h_two : 2 ≤ p := Nat.Prime.two_le hp
    omega
  have hp3 : p ^ 2024 ≠ 0 := by
    have h_pow_pos : 0 < p ^ 2024 := by positivity
    exact ne_of_gt h_pow_pos

  -- Convert divisibility to membership in the divisors Finset
  have h_mem : (x - c).natAbs ∈ (p ^ 2024).divisors := by
    rw [Nat.mem_divisors]
    exact ⟨h_dvd2, hp3⟩

  -- Use the provided helper theorem to extract the prime power structure
  obtain ⟨r, hr_le, hr_eq⟩ := (Nat.mem_divisors_prime_pow hp 2024).mp h_mem

  -- Conclude that x - c is either +p^r or -p^r
  have h_cases : x - c = (p : ℤ) ^ r ∨ x - c = -((p : ℤ) ^ r) := by
    have h_pr : ((p ^ r : ℕ) : ℤ) = (p : ℤ) ^ r := by push_cast; rfl
    rw [← h_pr]
    have h_abs : ∃ k : ℕ, p ^ r = k := ⟨p ^ r, rfl⟩
    obtain ⟨k, hk_eq⟩ := h_abs
    have hr_eq2 : (x - c).natAbs = k := by rw [← hk_eq]; exact hr_eq
    have h_goal : x - c = (k : ℤ) ∨ x - c = -(k : ℤ) := by omega
    rw [← hk_eq] at h_goal
    exact h_goal

  -- Case split on the sign to construct the final witnesses
  rcases h_cases with h_eq_pos | h_eq_neg
  · use (1 : ℤ), r
    refine ⟨by left; rfl, hr_le, ?_⟩
    have hx_eq : c + (1 : ℤ) * (p : ℤ) ^ r = x := by
      calc c + (1 : ℤ) * (p : ℤ) ^ r = c + (p : ℤ) ^ r := by ring
      _ = c + (x - c) := by rw [← h_eq_pos]
      _ = x := by ring
    rw [hx_eq, hx]
  · use (-1 : ℤ), r
    refine ⟨by right; rfl, hr_le, ?_⟩
    have hx_eq : c + (-1 : ℤ) * (p : ℤ) ^ r = x := by
      calc c + (-1 : ℤ) * (p : ℤ) ^ r = c + -((p : ℤ) ^ r) := by ring
      _ = c + (x - c) := by rw [← h_eq_neg]
      _ = x := by ring
    rw [hx_eq, hx]

theorem exists_infinite_fiber_of_primes (P : ℤ[X]) (c : ℤ)
  (h : ∀ p : ℕ, Nat.Prime p → ∃ (ε : ℤ) (r : ℕ), (ε = 1 ∨ ε = -1) ∧ r ≤ 2024 ∧ P.eval (c + ε * (p : ℤ) ^ r) = (p : ℤ) ^ 2024) :
  ∃ (ε : ℤ) (r : ℕ), (ε = 1 ∨ ε = -1) ∧ r ≤ 2024 ∧
  Set.Infinite {s : ℤ | P.eval (c + ε * s ^ r) = s ^ 2024} :=
by

  let ε_of (p : ℕ) (hp : p.Prime) : ℤ := Classical.choose (h p hp)
  let r_of (p : ℕ) (hp : p.Prime) : ℕ := Classical.choose (Classical.choose_spec (h p hp))
  have prop_of (p : ℕ) (hp : p.Prime) : (ε_of p hp = 1 ∨ ε_of p hp = -1) ∧ r_of p hp ≤ 2024 ∧ P.eval (c + ε_of p hp * (p : ℤ) ^ r_of p hp) = (p : ℤ) ^ 2024 :=
    Classical.choose_spec (Classical.choose_spec (h p hp))

  let f : ℕ → ℤ × ℕ := fun p => if hp : p.Prime then (ε_of p hp, r_of p hp) else (1, 0)
  let s : ℤ × ℕ → Set ℕ := fun i => { p | p.Prime ∧ f p = i }

  have h_disj : Pairwise fun i j => Disjoint (s i) (s j) := by
    intro i j hij
    rw [Set.disjoint_iff]
    rintro p ⟨⟨hp1, hf1⟩, ⟨hp2, hf2⟩⟩
    have hi_eq_j : i = j := by rw [← hf1, ← hf2]
    exact hij hi_eq_j

  have h_Union : (⋃ i, s i) = {p : ℕ | p.Prime} := by
    ext p
    simp only [Set.mem_iUnion, Set.mem_setOf_eq]
    constructor
    · rintro ⟨i, hp, _⟩
      exact hp
    · rintro hp
      exact ⟨f p, hp, rfl⟩

  have h_Union_inf : (⋃ i, s i).Infinite := by
    rw [h_Union]
    exact Nat.infinite_setOf_prime

  have h_supp : {i | (s i).Nonempty} ⊆ ({1, -1} : Set ℤ) ×ˢ (Set.Iic 2024 : Set ℕ) := by
    rintro i ⟨p, hp, hf⟩
    have h_prop := prop_of p hp
    dsimp [f] at hf
    rw [dif_pos hp] at hf
    rw [← hf]
    have h1 : ε_of p hp = 1 ∨ ε_of p hp = -1 := h_prop.1
    have h2 : r_of p hp ≤ 2024 := h_prop.2.1
    simp only [Set.mem_prod, Set.mem_insert_iff, Set.mem_singleton_iff, Set.mem_Iic]
    exact ⟨h1, h2⟩

  have h_eps_fin : ({1, -1} : Set ℤ).Finite := Set.finite_insert.mpr (Set.finite_singleton _)
  have h_supp_fin : {i | (s i).Nonempty}.Finite :=
    (h_eps_fin.prod (Set.finite_Iic 2024)).subset h_supp

  have h_iff := Set.finite_iUnion_iff (s := s) h_disj
  have h_not_fin : ¬((∀ (i : ℤ × ℕ), (s i).Finite) ∧ {i | (s i).Nonempty}.Finite) := by
    intro H
    have := h_iff.mpr H
    exact h_Union_inf this

  have h_ex : ∃ i, ¬ (s i).Finite := by
    by_contra h_all
    push_neg at h_all
    exact h_not_fin ⟨h_all, h_supp_fin⟩

  obtain ⟨i, hi⟩ := h_ex
  use i.1, i.2

  have hi_nonempty : (s i).Nonempty := by
    by_contra h_empty
    rw [Set.not_nonempty_iff_eq_empty] at h_empty
    rw [h_empty] at hi
    exact hi Set.finite_empty

  have hi_props := h_supp hi_nonempty
  have h_eps : i.1 = 1 ∨ i.1 = -1 := hi_props.1
  have h_r : i.2 ≤ 2024 := hi_props.2

  refine ⟨h_eps, h_r, ?_⟩

  let T := {x : ℤ | P.eval (c + i.1 * x ^ i.2) = x ^ 2024}
  have h_sub : s i ⊆ (Nat.cast : ℕ → ℤ) ⁻¹' T := by
    rintro p ⟨hp, hf_eq⟩
    have h_prop := prop_of p hp
    dsimp [f] at hf_eq
    rw [dif_pos hp] at hf_eq
    have heq1 : ε_of p hp = i.1 := congr_arg Prod.fst hf_eq
    have heq2 : r_of p hp = i.2 := congr_arg Prod.snd hf_eq
    change P.eval (c + i.1 * (p : ℤ) ^ i.2) = (p : ℤ) ^ 2024
    rw [← heq1, ← heq2]
    exact h_prop.2.2

  have h_preimage_inf : ¬ (((Nat.cast : ℕ → ℤ) ⁻¹' T).Finite) := by
    intro h_fin
    exact hi (h_fin.subset h_sub)

  intro h_T_fin
  let S := (Nat.cast : ℕ → ℤ) ⁻¹' T
  have h_inj : Function.Injective (fun (p : S) => (⟨(p.val : ℤ), p.property⟩ : T)) := by
    intro a b hab
    ext
    have hab_val := congr_arg Subtype.val hab
    exact Nat.cast_injective hab_val

  haveI : Finite T := h_T_fin
  haveI : Finite S := Finite.of_injective _ h_inj
  have h_S_fin : S.Finite := Set.toFinite S
  exact h_preimage_inf h_S_fin

theorem poly_comp_eq_pow_of_infinite_roots (P : ℤ[X]) (c ε : ℤ) (r : ℕ)
  (h_inf : Set.Infinite {s : ℤ | P.eval (c + ε * s ^ r) = s ^ 2024}) :
  P.comp (C c + C ε * X ^ r) = X ^ 2024 :=
by
  have h_eq : {s : ℤ | P.eval (c + ε * s ^ r) = s ^ 2024} = {x : ℤ | (P.comp (C c + C ε * X ^ r) - X ^ 2024).IsRoot x} := by
    ext x
    simp only [Set.mem_setOf_eq, Polynomial.IsRoot, Polynomial.eval_sub,
      Polynomial.eval_comp, Polynomial.eval_add, Polynomial.eval_mul,
      Polynomial.eval_C, Polynomial.eval_pow, Polynomial.eval_X, sub_eq_zero]
  rw [h_eq] at h_inf
  by_contra h_neq
  have h_sub_neq : P.comp (C c + C ε * X ^ r) - X ^ 2024 ≠ 0 := by
    intro h_zero
    apply h_neq
    exact sub_eq_zero.mp h_zero
  have h_fin := Polynomial.finite_setOf_isRoot h_sub_neq
  exact h_inf h_fin

theorem poly_shift_comp (P : ℤ[X]) (c ε : ℤ) (r : ℕ)
  (h : P.comp (C c + C ε * X ^ r) = X ^ 2024) :
  (P.comp (X + C c)).comp (C ε * X ^ r) = X ^ 2024 :=
by
  rw [Polynomial.comp_assoc]
  have h1 : (X + C c).comp (C ε * X ^ r) = C c + C ε * X ^ r := by
    rw [Polynomial.add_comp, Polynomial.X_comp, Polynomial.C_comp]
    ring
  rw [h1, h]

theorem poly_comp_eq_pow_lem (Q : ℤ[X]) (ε : ℤ) (r : ℕ) (hε : ε = 1 ∨ ε = -1)
    (h : Q.comp (C ε * X ^ r) = X ^ 2024) :
    ∃ (d : ℕ), d ∣ 2024 ∧ Q = (C ε * X) ^ d :=
by
  have he0 : ε ≠ 0 := by rcases hε with rfl | rfl <;> decide
  have h_lc_C : (C ε).leadingCoeff = ε := Polynomial.leadingCoeff_C ε
  have h_lc_X : (X ^ r : ℤ[X]).leadingCoeff = 1 := Polynomial.leadingCoeff_X_pow r
  have h_lc_mul : (C ε).leadingCoeff * (X ^ r : ℤ[X]).leadingCoeff ≠ 0 := by
    rw [h_lc_C, h_lc_X, mul_one]
    exact he0

  -- Use natDegree_mul' which expects the leading coefficient product to be non-zero
  have hP_deg : (C ε * X ^ r).natDegree = r := by
    rw [Polynomial.natDegree_mul' h_lc_mul]
    have h1 : (C ε).natDegree = 0 := Polynomial.natDegree_C ε
    have h2 : (X ^ r : ℤ[X]).natDegree = r := Polynomial.natDegree_X_pow r
    rw [h1, h2, zero_add]

  have hP_lc : (C ε * X ^ r).leadingCoeff = ε := by
    rw [Polynomial.leadingCoeff_mul' h_lc_mul, h_lc_C, h_lc_X, mul_one]

  have h_deg : (Q.comp (C ε * X ^ r)).natDegree = 2024 := by
    rw [h, Polynomial.natDegree_X_pow 2024]

  have hQ_ne_zero : Q ≠ 0 := by
    intro hQ
    have : Q.comp (C ε * X ^ r) = 0 := by
      let F := Polynomial.eval₂RingHom Polynomial.C (C ε * X ^ r)
      have hF_Q : Q.comp (C ε * X ^ r) = F Q := rfl
      rw [hF_Q, hQ, map_zero]
    rw [this, Polynomial.natDegree_zero] at h_deg
    revert h_deg
    decide

  have hQ_lc : Q.leadingCoeff ≠ 0 := Polynomial.leadingCoeff_ne_zero.mpr hQ_ne_zero

  have he_pow_eq : ∀ n : ℕ, ε ^ n = 1 ∨ ε ^ n = -1 := by
    intro n
    rcases hε with rfl | rfl
    · left; exact one_pow n
    · induction n with
      | zero => left; rfl
      | succ n ih =>
        rcases ih with h1 | h2
        · right
          rw [pow_succ, h1]
          ring
        · left
          rw [pow_succ, h2]
          ring

  have he_pow_ne_zero_lem : ∀ n : ℕ, ε ^ n ≠ 0 := by
    intro n
    rcases he_pow_eq n with h1 | h2
    · rw [h1]; decide
    · rw [h2]; decide

  have he_pow_ne_zero : (C ε * X ^ r).leadingCoeff ^ Q.natDegree ≠ 0 := by
    rw [hP_lc]
    exact he_pow_ne_zero_lem Q.natDegree

  have h_lc_comp : Q.leadingCoeff * (C ε * X ^ r).leadingCoeff ^ Q.natDegree ≠ 0 := mul_ne_zero hQ_lc he_pow_ne_zero

  have h_deg_eq : (Q.comp (C ε * X ^ r)).natDegree = Q.natDegree * (C ε * X ^ r).natDegree :=
    Polynomial.natDegree_comp_eq_of_mul_ne_zero h_lc_comp

  rw [h_deg, hP_deg] at h_deg_eq

  let d := Q.natDegree
  use d
  constructor
  · exact ⟨r, h_deg_eq⟩
  · let S := (C ε * X) ^ d
    have hS_comp : S.comp (C ε * X ^ r) = X ^ 2024 := by
      let F := Polynomial.eval₂RingHom Polynomial.C (C ε * X ^ r)
      have hF_S : S.comp (C ε * X ^ r) = F S := rfl
      rw [hF_S]
      change F ((C ε * X) ^ d) = _
      rw [map_pow, map_mul]
      have hC : F (C ε) = C ε := by
        change Polynomial.eval₂ Polynomial.C (C ε * X ^ r) (C ε) = C ε
        exact Polynomial.eval₂_C Polynomial.C (C ε * X ^ r)
      have hX : F X = C ε * X ^ r := by
        change Polynomial.eval₂ Polynomial.C (C ε * X ^ r) X = C ε * X ^ r
        exact Polynomial.eval₂_X Polynomial.C (C ε * X ^ r)
      rw [hC, hX]
      rw [← mul_assoc]
      have he2 : C ε * C ε = 1 := by
        rcases hε with rfl | rfl
        · rw [map_one, mul_one]
        · rw [map_neg, map_one]
          ring
      rw [he2, one_mul]
      rw [← pow_mul]
      have hdr : r * d = 2024 := by
        rw [mul_comm]
        exact h_deg_eq.symm
      rw [hdr]

    let R := Q - S
    have hR_comp : R.comp (C ε * X ^ r) = 0 := by
      let F := Polynomial.eval₂RingHom Polynomial.C (C ε * X ^ r)
      have hF_R : R.comp (C ε * X ^ r) = F R := rfl
      rw [hF_R]
      change F (Q - S) = _
      rw [map_sub]
      have hF_Q : F Q = Q.comp (C ε * X ^ r) := rfl
      have hF_S : F S = S.comp (C ε * X ^ r) := rfl
      rw [hF_Q, hF_S]
      rw [h, hS_comp, sub_self]

    have hr_pos : (C ε * X ^ r).natDegree > 0 := by
      rw [hP_deg]
      by_contra h_le
      have hr0 : r = 0 := by omega
      have h_zero : 2024 = 0 := by
        calc 2024 = Q.natDegree * r := h_deg_eq
          _ = Q.natDegree * 0 := by rw [hr0]
          _ = 0 := mul_zero Q.natDegree
      revert h_zero; decide

    have hR_deg_zero : R.natDegree = 0 := by
      by_contra hR_deg_ne_zero
      have hR_ne_zero : R ≠ 0 := by
        intro hR0
        rw [hR0, Polynomial.natDegree_zero] at hR_deg_ne_zero
        exact hR_deg_ne_zero rfl
      have hR_lc : R.leadingCoeff ≠ 0 := Polynomial.leadingCoeff_ne_zero.mpr hR_ne_zero
      have he_pow_R : (C ε * X ^ r).leadingCoeff ^ R.natDegree ≠ 0 := by
        rw [hP_lc]
        exact he_pow_ne_zero_lem R.natDegree
      have h_lc_R_comp : R.leadingCoeff * (C ε * X ^ r).leadingCoeff ^ R.natDegree ≠ 0 := mul_ne_zero hR_lc he_pow_R
      have h_R_comp_deg : (R.comp (C ε * X ^ r)).natDegree = R.natDegree * (C ε * X ^ r).natDegree :=
        Polynomial.natDegree_comp_eq_of_mul_ne_zero h_lc_R_comp
      rw [hR_comp, Polynomial.natDegree_zero] at h_R_comp_deg
      have h_mul : R.natDegree * (C ε * X ^ r).natDegree = 0 := h_R_comp_deg.symm
      rcases mul_eq_zero.mp h_mul with h1 | h2
      · exact hR_deg_ne_zero h1
      · exfalso
        linarith [hr_pos, h2]

    have hR_eq_C : R = C (R.coeff 0) := by
      apply Polynomial.ext
      intro n
      cases n with
      | zero =>
        rw [Polynomial.coeff_C]
        rw [if_pos rfl]
      | succ n =>
        have h_lt : R.natDegree < n + 1 := by
          rw [hR_deg_zero]
          exact Nat.zero_lt_succ n
        have h1 : R.coeff (n + 1) = 0 := Polynomial.coeff_eq_zero_of_natDegree_lt h_lt
        have h2 : (C (R.coeff 0)).coeff (n + 1) = 0 := by
          rw [Polynomial.coeff_C]
          have hne : n + 1 ≠ 0 := Nat.succ_ne_zero n
          rw [if_neg hne]
        rw [h1, h2]

    have hR_comp_C : R.comp (C ε * X ^ r) = C (R.coeff 0) := by
      calc R.comp (C ε * X ^ r) = (C (R.coeff 0)).comp (C ε * X ^ r) := congr_arg (fun P => P.comp (C ε * X ^ r)) hR_eq_C
        _ = C (R.coeff 0) := Polynomial.C_comp

    rw [hR_comp_C] at hR_comp
    have hR_coeff_zero : R.coeff 0 = 0 := Polynomial.C_eq_zero.mp hR_comp
    rw [hR_coeff_zero, Polynomial.C_0] at hR_eq_C
    exact sub_eq_zero.mp hR_eq_C

theorem poly_eq_of_comp_shift (P : ℤ[X]) (c ε : ℤ) (d : ℕ)
  (h : P.comp (X + C c) = (C ε * X) ^ d) :
  P = (C ε * X - C ε * C c) ^ d :=
by
  have h_C_pow_comp : ∀ n : ℕ, ((C ε) ^ n).comp (X - C c) = (C ε) ^ n := by
    intro n
    induction n with
    | zero => simp
    | succ k ih =>
      rw [pow_succ, Polynomial.mul_comp, ih]
      simp
  calc
    P = P.comp X := by
      symm
      exact Polynomial.comp_X
    _ = P.comp ((X + C c).comp (X - C c)) := by
      have hX : (X + C c).comp (X - C c) = X := by
        simp only [Polynomial.add_comp, Polynomial.X_comp, Polynomial.C_comp]
        ring
      rw [hX]
    _ = (P.comp (X + C c)).comp (X - C c) := by rw [← Polynomial.comp_assoc]
    _ = ((C ε * X) ^ d).comp (X - C c) := by rw [h]
    _ = ((C ε) ^ d * X ^ d).comp (X - C c) := by rw [mul_pow]
    _ = ((C ε) ^ d).comp (X - C c) * (X ^ d).comp (X - C c) := by rw [Polynomial.mul_comp]
    _ = (C ε) ^ d * (X - C c) ^ d := by rw [h_C_pow_comp d, Polynomial.X_pow_comp]
    _ = (C ε * (X - C c)) ^ d := by rw [← mul_pow]
    _ = (C ε * X - C ε * C c) ^ d := by
      have h_base : C ε * (X - C c) = C ε * X - C ε * C c := by ring
      rw [h_base]

theorem poly_mem_RHS (c ε : ℤ) (d : ℕ) (hε : ε = 1 ∨ ε = -1) (hd : d ∣ 2024) :
  (C ε * X - C ε * C c) ^ d ∈
    {(X - C a) ^ d | (a : ℤ) (d : ℕ) (_ : d ∣ 2024)} ∪
    {(- X - C a) ^ d | (a : ℤ) (d : ℕ) (_ : d ∣ 2024)} :=
by
  rcases hε with rfl | rfl
  · left
    simp only [Set.mem_setOf_eq]
    use c, d, hd
    simp [map_one, map_neg]
  · right
    simp only [Set.mem_setOf_eq]
    use -c, d, hd
    simp [map_one, map_neg]

theorem LHS_subset_RHS :
    {P : ℤ[X] | ∀ n ≥ 0, ∃ x, P.eval x = n ^ 2024} ⊆
    {(X - C a) ^ d | (a : ℤ) (d : ℕ) (_ : d ∣ 2024)} ∪
    {(- X - C a) ^ d | (a : ℤ) (d : ℕ) (_ : d ∣ 2024)} :=
by
  intro P hP
  simp only [Set.mem_setOf_eq] at hP

  obtain ⟨c, hc⟩ := exists_zero_root P hP

  have h_p := prime_fiber_condition P c hc hP

  obtain ⟨ε, r, hε, hr, h_inf⟩ := exists_infinite_fiber_of_primes P c h_p

  have h_comp1 := poly_comp_eq_pow_of_infinite_roots P c ε r h_inf

  have h_comp2 := poly_shift_comp P c ε r h_comp1

  obtain ⟨d, hd, hd_eq⟩ := poly_comp_eq_pow_lem (P.comp (X + C c)) ε r hε h_comp2

  have hP_eq := poly_eq_of_comp_shift P c ε d hd_eq

  exact hP_eq.symm ▸ poly_mem_RHS c ε d hε hd

theorem PBBasic022 : {P : ℤ[X] | ∀ n ≥ 0, ∃ x, P.eval x = n ^ 2024} =
      {(X - C a) ^ d | (a : ℤ) (d : ℕ) (_ : d ∣ 2024)}
        ∪ {(- X - C a) ^ d | (a : ℤ) (d : ℕ) (_ : d ∣ 2024)} :=
by
  ext P
  constructor
  · apply LHS_subset_RHS
  · apply RHS_subset_LHS
