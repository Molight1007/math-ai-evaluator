import Mathlib
variable (a : Fin 18 → ℝ)
noncomputable
def m : ℝ := (∑ i : Fin 18, a i) / 18
noncomputable
def A : ℕ :=
    { (i, j, k) : Fin 18 × Fin 18 × Fin 18 |
    i < j ∧ j < k ∧ a i + a j + a k ≥ 3 * (m a) }.ncard

def a0 : Fin 18 → ℝ := fun i => if i.val = 17 then (18 : ℝ) else (0 : ℝ)

def equiv_6_3_18 : Fin 6 × Fin 3 ≃ Fin 18 where
  toFun p := ⟨p.1.val * 3 + p.2.val, by
    have h1 := p.1.isLt
    have h2 := p.2.isLt
    omega⟩
  invFun i := (⟨i.val / 3, by have := i.isLt; omega⟩, ⟨i.val % 3, by have := i.isLt; omega⟩)
  left_inv p := by
    ext
    · dsimp; omega
    · dsimp; omega
  right_inv i := by
    ext
    dsimp
    omega

noncomputable def T_set (a : Fin 18 → ℝ) : Finset (Finset (Fin 18)) :=
  @Finset.filter (Finset (Fin 18))
    (fun t => ∑ i ∈ t, a i ≥ 3 * m a)
    (fun _ => Classical.propDecidable _)
    ((Finset.univ : Finset (Fin 18)).powerset.filter (fun t => t.card = 3))

def is_good_trip (a : Fin 18 → ℝ) (σ : Equiv.Perm (Fin 18)) (c : Fin 6) : Prop :=
  ∑ k : Fin 3, a (σ (equiv_6_3_18 (c, k))) ≥ 3 * m a

noncomputable def is_good_trip_ind (a : Fin 18 → ℝ) (σ : Equiv.Perm (Fin 18)) (c : Fin 6) : ℕ :=
  @ite ℕ (is_good_trip a σ c) (Classical.propDecidable _) 1 0

def B_c (c : Fin 6) : Finset (Fin 18) :=
  Finset.image (fun k : Fin 3 => equiv_6_3_18 (c, k)) Finset.univ

def trip_finset : Finset (Fin 18 × Fin 18 × Fin 18) :=
  Finset.univ.filter (fun t => t.1 < t.2.1 ∧ t.2.1 < t.2.2)

noncomputable def S_finset (a : Fin 18 → ℝ) : Finset (Fin 18 × Fin 18 × Fin 18) :=
  trip_finset.filter (fun t => a t.1 + a t.2.1 + a t.2.2 ≥ 3 * m a)

def trip_to_finset (t : Fin 18 × Fin 18 × Fin 18) : Finset (Fin 18) :=
  {t.1, t.2.1, t.2.2}

theorem A_a0 : A a0 = 136 :=
by
  have m_a0_eq : m a0 = 1 := by
    dsimp [m, a0]
    have h_sum : ∑ i : Fin 18, (if i.val = 17 then (18 : ℝ) else 0) = 18 := by
      rw [Finset.sum_eq_single (17 : Fin 18)]
      · have h_eq : (17 : Fin 18).val = 17 := rfl
        rw [if_pos h_eq]
      · intro b _ hb
        have h_neq : b.val ≠ 17 := fun hc => hb (Fin.ext hc)
        rw [if_neg h_neq]
      · intro h
        exfalso
        apply h
        exact Finset.mem_univ _
    rw [h_sum]
    norm_num

  dsimp [A]
  have h_set : { (i, j, k) : Fin 18 × Fin 18 × Fin 18 | i < j ∧ j < k ∧ a0 i + a0 j + a0 k ≥ 3 * m a0 } =
    { p : Fin 18 × Fin 18 × Fin 18 | p.1 < p.2.1 ∧ p.2.1 < p.2.2 ∧ p.2.2 = (17 : Fin 18) } := by
    ext ⟨i, j, k⟩
    simp only [Set.mem_setOf_eq]
    rw [m_a0_eq]
    have h_mul : 3 * (1 : ℝ) = 3 := by norm_num
    rw [h_mul]
    apply and_congr_right; intro hi
    apply and_congr_right; intro hj
    constructor
    · intro h
      by_contra hk
      have hk_lt : k.val < 18 := k.isLt
      have hk_val : k.val ≠ 17 := fun hc => hk (Fin.ext hc)
      have hi_val : i.val ≠ 17 := by omega
      have hj_val : j.val ≠ 17 := by omega
      have h_ai : a0 i = 0 := by
        dsimp [a0]
        rw [if_neg hi_val]
      have h_aj : a0 j = 0 := by
        dsimp [a0]
        rw [if_neg hj_val]
      have h_ak : a0 k = 0 := by
        dsimp [a0]
        rw [if_neg hk_val]
      rw [h_ai, h_aj, h_ak] at h
      linarith
    · intro hk
      have hk_val : k.val = 17 := congrArg Fin.val hk
      have h_ak : a0 k = 18 := by
        dsimp [a0]
        rw [if_pos hk_val]
      have hi_val : i.val ≠ 17 := by omega
      have hj_val : j.val ≠ 17 := by omega
      have h_ai : a0 i = 0 := by
        dsimp [a0]
        rw [if_neg hi_val]
      have h_aj : a0 j = 0 := by
        dsimp [a0]
        rw [if_neg hj_val]
      rw [h_ai, h_aj, h_ak]
      linarith

  rw [h_set]
  change Nat.card { p : Fin 18 × Fin 18 × Fin 18 // p.1 < p.2.1 ∧ p.2.1 < p.2.2 ∧ p.2.2 = (17 : Fin 18) } = 136

  let equiv_17_18 :
      { p : Fin 18 × Fin 18 × Fin 18 // p.1 < p.2.1 ∧ p.2.1 < p.2.2 ∧ p.2.2 = (17 : Fin 18) } ≃
      { p : Fin 17 × Fin 17 // p.1 < p.2 } :=
    { toFun := fun ⟨(i, j, k), h⟩ =>
        ⟨(⟨i.val, by
            have h1 : i.val < j.val := h.1
            have h2 : j.val < k.val := h.2.1
            have h3 : k = 17 := h.2.2
            have h3' : k.val = 17 := congrArg Fin.val h3
            omega⟩,
          ⟨j.val, by
            have h2 : j.val < k.val := h.2.1
            have h3 : k = 17 := h.2.2
            have h3' : k.val = 17 := congrArg Fin.val h3
            omega⟩),
         by
           have h1 : i.val < j.val := h.1
           exact h1⟩
      invFun := fun ⟨(i, j), h⟩ =>
        ⟨(⟨i.val, by have := i.isLt; omega⟩,
          ⟨j.val, by have := j.isLt; omega⟩,
          (17 : Fin 18)),
         by
           have h1 : i.val < j.val := h
           have h2 : j.val < 17 := j.isLt
           exact ⟨h1, h2, rfl⟩⟩
      left_inv := fun ⟨(i, j, k), h⟩ => by
        apply Subtype.ext
        dsimp
        have h3 : k = 17 := h.2.2
        rw [h3]
      right_inv := fun ⟨(i, j), h⟩ => by
        apply Subtype.ext
        rfl }

  have h_card_eq : Nat.card { p : Fin 18 × Fin 18 × Fin 18 // p.1 < p.2.1 ∧ p.2.1 < p.2.2 ∧ p.2.2 = (17 : Fin 18) } = Nat.card { p : Fin 17 × Fin 17 // p.1 < p.2 } := by
    exact Nat.card_congr equiv_17_18
  rw [h_card_eq]

  let e1 : { p : Fin 17 × Fin 17 // p.1 < p.2 } ≃ Σ i : Fin 17, { j : Fin 17 // i < j } :=
    { toFun := fun ⟨(i, j), h⟩ => ⟨i, ⟨j, h⟩⟩
      invFun := fun ⟨i, ⟨j, h⟩⟩ => ⟨(i, j), h⟩
      left_inv := fun ⟨(i, j), h⟩ => rfl
      right_inv := fun ⟨i, ⟨j, h⟩⟩ => rfl }

  have h_card1 : Nat.card { p : Fin 17 × Fin 17 // p.1 < p.2 } = Nat.card (Σ i : Fin 17, { j : Fin 17 // i < j }) :=
    Nat.card_congr e1

  rw [h_card1]
  rw [Nat.card_sigma]
  simp_rw [Nat.card_eq_fintype_card]
  decide

theorem S_finset_subset (a : Fin 18 → ℝ) : S_finset a ⊆ trip_finset :=
by
  intro x hx
  rw [S_finset, Finset.mem_filter] at hx
  exact hx.1

theorem injOn_trip_to_finset :
  Set.InjOn trip_to_finset ↑trip_finset :=
by
  intro x hx y hy h
  rcases x with ⟨x1, x2, x3⟩
  rcases y with ⟨y1, y2, y3⟩
  simp [trip_finset] at hx hy
  change ({x1, x2, x3} : Finset (Fin 18)) = {y1, y2, y3} at h

  have h1 : x1 ∈ ({y1, y2, y3} : Finset (Fin 18)) := by
    rw [← h]
    simp only [Finset.mem_insert, Finset.mem_singleton]
    exact Or.inl trivial

  have h2 : x2 ∈ ({y1, y2, y3} : Finset (Fin 18)) := by
    rw [← h]
    simp only [Finset.mem_insert, Finset.mem_singleton]
    exact Or.inr (Or.inl trivial)

  have h3 : x3 ∈ ({y1, y2, y3} : Finset (Fin 18)) := by
    rw [← h]
    simp only [Finset.mem_insert, Finset.mem_singleton]
    exact Or.inr (Or.inr trivial)

  have h4 : y1 ∈ ({x1, x2, x3} : Finset (Fin 18)) := by
    rw [h]
    simp only [Finset.mem_insert, Finset.mem_singleton]
    exact Or.inl trivial

  have h6 : y3 ∈ ({x1, x2, x3} : Finset (Fin 18)) := by
    rw [h]
    simp only [Finset.mem_insert, Finset.mem_singleton]
    exact Or.inr (Or.inr trivial)

  simp only [Finset.mem_insert, Finset.mem_singleton] at h1 h2 h3 h4 h6

  have e1 : x1 = y1 := by
    rcases h1 with e | e | e
    · exact e
    · rcases h4 with e4 | e4 | e4 <;> omega
    · rcases h4 with e4 | e4 | e4 <;> omega

  have e3 : x3 = y3 := by
    rcases h3 with e | e | e
    · rcases h6 with e6 | e6 | e6 <;> omega
    · rcases h6 with e6 | e6 | e6 <;> omega
    · exact e

  have e2 : x2 = y2 := by
    rcases h2 with e | e | e
    · omega
    · exact e
    · omega

  rw [e1, e2, e3]

theorem T_set_eq_image (a : Fin 18 → ℝ) : T_set a = (S_finset a).image trip_to_finset :=
by
  ext T; constructor
  · intro hT
    have hT_unfold : T ∈ T_set a := hT
    dsimp [T_set] at hT_unfold
    simp only [Finset.mem_filter, Finset.mem_powerset] at hT_unfold
    obtain ⟨⟨_, hcard⟩, hsum⟩ := hT_unfold

    have h1 : 0 < T.card := by omega
    have hT_ne : T.Nonempty := Finset.card_pos.mp h1
    let i := T.min' hT_ne
    have hi : i ∈ T := Finset.min'_mem T hT_ne

    let T2 := T.erase i
    have h2 : T2.card = 2 := by
      have hc := Finset.card_erase_of_mem hi
      dsimp [T2]
      omega
    have hT2_pos : 0 < T2.card := by omega
    have hT2_ne : T2.Nonempty := Finset.card_pos.mp hT2_pos
    let j := T2.min' hT2_ne
    have hj : j ∈ T2 := Finset.min'_mem T2 hT2_ne

    let T3 := T2.erase j
    have h3 : T3.card = 1 := by
      have hc := Finset.card_erase_of_mem hj
      dsimp [T3]
      omega
    have hT3_pos : 0 < T3.card := by omega
    have hT3_ne : T3.Nonempty := Finset.card_pos.mp hT3_pos
    let k := T3.min' hT3_ne
    have hk : k ∈ T3 := Finset.min'_mem T3 hT3_ne

    have hij : i < j := by
      have hj_mem : j ∈ T := (Finset.mem_erase.mp hj).2
      have hj_ne : j ≠ i := (Finset.mem_erase.mp hj).1
      exact lt_of_le_of_ne (Finset.min'_le T j hj_mem) hj_ne.symm
    have hjk : j < k := by
      have hk_mem : k ∈ T2 := (Finset.mem_erase.mp hk).2
      have hk_ne : k ≠ j := (Finset.mem_erase.mp hk).1
      exact lt_of_le_of_ne (Finset.min'_le T2 k hk_mem) hk_ne.symm

    have h4 : T3 = {k} := by
      rcases Finset.card_eq_one.mp h3 with ⟨x, hx⟩
      have hk2 : k ∈ T3 := hk
      rw [hx, Finset.mem_singleton] at hk2
      rw [hx, hk2]

    have h_eq : T = {i, j, k} := by
      ext x
      simp only [Finset.mem_insert, Finset.mem_singleton]
      constructor
      · intro hx
        rcases eq_or_ne x i with rfl | hxi
        · left; rfl
        rcases eq_or_ne x j with rfl | hxj
        · right; left; rfl
        right; right
        have hx_T2 : x ∈ T2 := Finset.mem_erase.mpr ⟨hxi, hx⟩
        have hx_T3 : x ∈ T3 := Finset.mem_erase.mpr ⟨hxj, hx_T2⟩
        rw [h4, Finset.mem_singleton] at hx_T3
        exact hx_T3
      · rintro (rfl | h)
        · exact hi
        · rcases h with rfl | rfl
          · exact (Finset.mem_erase.mp hj).2
          · have hk_in_T2 := (Finset.mem_erase.mp hk).2
            exact (Finset.mem_erase.mp hk_in_T2).2

    have h_k_notin : j ∉ ({k} : Finset (Fin 18)) := by
      rw [Finset.mem_singleton]
      intro h_eq_jk
      rw [h_eq_jk] at hjk
      exact lt_irrefl _ hjk
    have h_j_notin : i ∉ ({j, k} : Finset (Fin 18)) := by
      rw [Finset.mem_insert, Finset.mem_singleton]
      rintro (h_eq_ij | h_eq_ik)
      · rw [h_eq_ij] at hij; exact lt_irrefl _ hij
      · rw [h_eq_ik] at hij; exact lt_irrefl _ (hij.trans hjk)

    have h_sum_eq : ∑ x ∈ T, a x = a i + a j + a k := by
      rw [h_eq, Finset.sum_insert h_j_notin, Finset.sum_insert h_k_notin, Finset.sum_singleton]
      ring

    rw [Finset.mem_image]
    use (i, j, k)
    refine ⟨?_, ?_⟩
    · dsimp [S_finset, trip_finset]
      simp only [Finset.mem_filter, Finset.mem_univ, true_and]
      refine ⟨⟨hij, hjk⟩, ?_⟩
      have h_goal : a i + a j + a k ≥ 3 * m a := by
        rw [← h_sum_eq]
        exact hsum
      exact h_goal
    · dsimp [trip_to_finset]
      exact h_eq.symm

  · intro h_img
    rw [Finset.mem_image] at h_img
    obtain ⟨⟨i, ⟨j, k⟩⟩, ht, rfl⟩ := h_img
    dsimp [S_finset, trip_finset] at ht
    simp only [Finset.mem_filter, Finset.mem_univ, true_and] at ht
    obtain ⟨⟨hij, hjk⟩, hsum⟩ := ht
    dsimp [trip_to_finset]

    have h_k_notin : j ∉ ({k} : Finset (Fin 18)) := by
      rw [Finset.mem_singleton]
      intro h_eq_jk
      rw [h_eq_jk] at hjk
      exact lt_irrefl _ hjk
    have h_j_notin : i ∉ ({j, k} : Finset (Fin 18)) := by
      rw [Finset.mem_insert, Finset.mem_singleton]
      rintro (h_eq_ij | h_eq_ik)
      · rw [h_eq_ij] at hij; exact lt_irrefl _ hij
      · rw [h_eq_ik] at hij; exact lt_irrefl _ (hij.trans hjk)

    have h_card : ({i, j, k} : Finset (Fin 18)).card = 3 := by
      rw [Finset.card_insert_of_notMem h_j_notin, Finset.card_insert_of_notMem h_k_notin, Finset.card_singleton]
    have h_sum_eq : ∑ x ∈ ({i, j, k} : Finset (Fin 18)), a x = a i + a j + a k := by
      rw [Finset.sum_insert h_j_notin, Finset.sum_insert h_k_notin, Finset.sum_singleton]
      ring

    dsimp [T_set]
    simp only [Finset.mem_filter, Finset.mem_powerset]
    refine ⟨⟨Finset.subset_univ _, h_card⟩, ?_⟩
    have h_goal : ∑ x ∈ {i, j, k}, a x ≥ 3 * m a := by
      rw [h_sum_eq]
      exact hsum
    exact h_goal

theorem A_eq_S_finset_card (a : Fin 18 → ℝ) :
  A a = (S_finset a).card :=
by
  change { (i, j, k) : Fin 18 × Fin 18 × Fin 18 | i < j ∧ j < k ∧ a i + a j + a k ≥ 3 * (m a) }.ncard = (S_finset a).card
  have h_eq : { (i, j, k) : Fin 18 × Fin 18 × Fin 18 | i < j ∧ j < k ∧ a i + a j + a k ≥ 3 * (m a) } =
    (S_finset a : Set (Fin 18 × Fin 18 × Fin 18)) := by
    ext ⟨i, j, k⟩
    simp [S_finset, trip_finset]
    tauto
  rw [h_eq]
  exact Set.ncard_coe_finset (S_finset a)

theorem A_eq_T_set_card (a : Fin 18 → ℝ) : A a = (T_set a).card :=
by
  rw [A_eq_S_finset_card a]
  rw [T_set_eq_image a]
  have h_inj : Set.InjOn trip_to_finset (S_finset a) := by
    intro x hx y hy hxy
    apply injOn_trip_to_finset
    · exact S_finset_subset a hx
    · exact S_finset_subset a hy
    · exact hxy
  exact (Finset.card_image_of_injOn h_inj).symm

theorem sum_one_eq_fact_18 : (∑ σ : Equiv.Perm (Fin 18), 1 : ℕ) = Nat.factorial 18 :=
by
  rw [← Fintype.card_eq_sum_ones]
  simp [Fintype.card_perm]

theorem sum_is_good_trip_ind_ge_one (a : Fin 18 → ℝ) (σ : Equiv.Perm (Fin 18)) :
  1 ≤ ∑ c : Fin 6, is_good_trip_ind a σ c :=
by
  by_contra h_contra
  push_neg at h_contra
  have h_zero : ∑ c : Fin 6, is_good_trip_ind a σ c = 0 := by omega
  have h_all_zero : ∀ c : Fin 6, is_good_trip_ind a σ c = 0 := by
    intro c
    exact Finset.sum_eq_zero_iff.mp h_zero c (Finset.mem_univ c)

  have h_not_good : ∀ c : Fin 6, ¬ is_good_trip a σ c := by
    intro c h_good
    have hz := h_all_zero c
    dsimp [is_good_trip_ind] at hz
    rw [if_pos h_good] at hz
    omega

  have h_lt : ∀ c : Fin 6, ∑ k : Fin 3, a (σ (equiv_6_3_18 (c, k))) < 3 * m a := by
    intro c
    have hng := h_not_good c
    dsimp [is_good_trip] at hng
    push_neg at hng
    exact hng

  have h_sum_lt : (∑ c : Fin 6, ∑ k : Fin 3, a (σ (equiv_6_3_18 (c, k)))) < ∑ c : Fin 6, (3 * m a) :=
    Finset.sum_lt_sum
      (fun c _ => le_of_lt (h_lt c))
      ⟨0, Finset.mem_univ 0, h_lt 0⟩

  have h_lhs : ∑ c : Fin 6, ∑ k : Fin 3, a (σ (equiv_6_3_18 (c, k))) = 18 * m a := by
    have h1 : (∑ p : Fin 6 × Fin 3, a (σ (equiv_6_3_18 p))) = ∑ c : Fin 6, ∑ k : Fin 3, a (σ (equiv_6_3_18 (c, k))) :=
      Finset.sum_finset_product (Finset.univ : Finset (Fin 6 × Fin 3)) (Finset.univ : Finset (Fin 6)) (fun _ => Finset.univ : Fin 6 → Finset (Fin 3)) (fun _ => iff_of_true (Finset.mem_univ _) ⟨Finset.mem_univ _, Finset.mem_univ _⟩)
    have h3 : ∑ p : Fin 6 × Fin 3, a (σ (equiv_6_3_18 p)) = ∑ i : Fin 18, a (σ i) :=
      Finset.sum_bijective equiv_6_3_18
        (Equiv.bijective equiv_6_3_18)
        (fun _ => iff_of_true (Finset.mem_univ _) (Finset.mem_univ _))
        (fun _ _ => rfl)
    have h4 : ∑ i : Fin 18, a (σ i) = ∑ i : Fin 18, a i :=
      Finset.sum_bijective σ
        (Equiv.bijective σ)
        (fun _ => iff_of_true (Finset.mem_univ _) (Finset.mem_univ _))
        (fun _ _ => rfl)
    have h5 : ∑ i : Fin 18, a i = 18 * m a := by
      dsimp [m]
      ring
    rw [← h1, h3, h4, h5]

  have h_rhs : ∑ c : Fin 6, (3 * m a) = 18 * m a := by
    simp only [Finset.sum_const, Finset.card_univ, Fintype.card_fin, nsmul_eq_mul]
    ring

  rw [h_lhs, h_rhs] at h_sum_lt
  linarith

theorem sum_is_good_trip_ge (a : Fin 18 → ℝ) :
  (Nat.factorial 18 : ℕ) ≤ ∑ σ : Equiv.Perm (Fin 18), ∑ c : Fin 6, is_good_trip_ind a σ c :=
by
  rw [← sum_one_eq_fact_18]
  exact Finset.sum_le_sum (fun σ _ => sum_is_good_trip_ind_ge_one a σ)

theorem B_c_card (c : Fin 6) : (B_c c).card = 3 :=
by
  unfold B_c
  have h_inj : Function.Injective (fun k : Fin 3 => equiv_6_3_18 (c, k)) := by
    intro x y h
    have eq : (c, x) = (c, y) := Equiv.injective equiv_6_3_18 h
    exact congr_arg Prod.snd eq
  rw [Finset.card_image_of_injective Finset.univ h_inj]
  rfl

theorem sum_is_good_trip_ind_eq_card (a : Fin 18 → ℝ) (c : Fin 6) :
  ∑ σ : Equiv.Perm (Fin 18), is_good_trip_ind a σ c =
  (@Finset.filter (Equiv.Perm (Fin 18)) (fun σ => is_good_trip a σ c) (fun _ => Classical.propDecidable _) Finset.univ).card :=
by
  unfold is_good_trip_ind
  rw [Finset.sum_boole]
  simp

theorem filter_is_good_trip_eq_bUnion (a : Fin 18 → ℝ) (c : Fin 6) :
  @Finset.filter (Equiv.Perm (Fin 18)) (fun σ => is_good_trip a σ c) (fun _ => Classical.propDecidable _) Finset.univ =
  (T_set a).biUnion (fun T => Finset.filter (fun σ => Finset.image (fun x => σ x) (B_c c) = T) Finset.univ) :=
by
  ext σ
  rw [Finset.mem_biUnion]
  have mem_LHS : σ ∈ @Finset.filter (Equiv.Perm (Fin 18)) (fun σ => is_good_trip a σ c) (fun _ => Classical.propDecidable _) Finset.univ ↔ σ ∈ Finset.univ ∧ is_good_trip a σ c :=
    @Finset.mem_filter (Equiv.Perm (Fin 18)) (fun σ => is_good_trip a σ c) (fun _ => Classical.propDecidable _) Finset.univ σ
  have h_inj_σ : Function.Injective (fun x => σ x) := Equiv.injective σ
  have h_inj_eq : Function.Injective (fun k : Fin 3 => equiv_6_3_18 (c, k)) := fun x y hxy => congr_arg Prod.snd (Equiv.injective equiv_6_3_18 hxy)
  have H_card : (Finset.image (fun x => σ x) (B_c c)).card = 3 := by
    dsimp [B_c]
    rw [Finset.card_image_of_injective _ h_inj_σ]
    rw [Finset.card_image_of_injective _ h_inj_eq]
    exact rfl
  have H_sum : ∑ i ∈ Finset.image (fun x => σ x) (B_c c), a i = ∑ k : Fin 3, a (σ (equiv_6_3_18 (c, k))) := by
    dsimp [B_c]
    rw [Finset.sum_image (fun x _ y _ h => h_inj_σ h)]
    rw [Finset.sum_image (fun x _ y _ h => h_inj_eq h)]
  have mem_T_set (X : Finset (Fin 18)) : X ∈ T_set a ↔ X ∈ (Finset.univ : Finset (Fin 18)).powerset.filter (fun t => t.card = 3) ∧ ∑ i ∈ X, a i ≥ 3 * m a := by
    change X ∈ @Finset.filter (Finset (Fin 18)) (fun t => ∑ i ∈ t, a i ≥ 3 * m a) (fun _ => Classical.propDecidable _) ((Finset.univ : Finset (Fin 18)).powerset.filter (fun t => t.card = 3)) ↔ _
    exact @Finset.mem_filter (Finset (Fin 18)) (fun t => ∑ i ∈ t, a i ≥ 3 * m a) (fun _ => Classical.propDecidable _) ((Finset.univ : Finset (Fin 18)).powerset.filter (fun t => t.card = 3)) X
  have H_iff : is_good_trip a σ c ↔ Finset.image (fun x => σ x) (B_c c) ∈ T_set a := by
    dsimp [is_good_trip]
    rw [mem_T_set]
    rw [Finset.mem_filter, Finset.mem_powerset]
    constructor
    · intro h
      refine ⟨⟨Finset.subset_univ _, H_card⟩, ?_⟩
      rwa [H_sum]
    · rintro ⟨_, h⟩
      rwa [H_sum] at h
  constructor
  · intro h
    rw [mem_LHS] at h
    rcases h with ⟨huniv, hgood⟩
    rw [H_iff] at hgood
    refine ⟨Finset.image (fun x => σ x) (B_c c), hgood, ?_⟩
    rw [Finset.mem_filter]
    exact ⟨huniv, rfl⟩
  · rintro ⟨T, hT, hT2⟩
    rw [Finset.mem_filter] at hT2
    rcases hT2 with ⟨huniv, hEq⟩
    rw [mem_LHS]
    refine ⟨huniv, ?_⟩
    rw [H_iff, hEq]
    exact hT

theorem disjoint_image_filters (S : Finset (Fin 18)) {T1 T2 : Finset (Fin 18)} (h : T1 ≠ T2) :
  Disjoint (Finset.filter (fun σ : Equiv.Perm (Fin 18) => Finset.image (fun x => σ x) S = T1) Finset.univ)
           (Finset.filter (fun σ : Equiv.Perm (Fin 18) => Finset.image (fun x => σ x) S = T2) Finset.univ) :=
by
  rw [Finset.disjoint_left]
  intro σ h1 h2
  rw [Finset.mem_filter] at h1 h2
  exact h (h1.2.symm.trans h2.2)

theorem T_set_mem_card_eq_3 (a : Fin 18 → ℝ) {T : Finset (Fin 18)} (hT : T ∈ T_set a) :
  T.card = 3 :=
by
  rw [T_set] at hT
  simp only [Finset.mem_filter] at hT
  rcases hT with ⟨⟨_, h_card⟩, _⟩
  exact h_card

theorem fintype_card_coe_finset_eq {α : Type*} [Fintype α] (S : Finset α) :
  Fintype.card ↥S = S.card :=
by
  exact Fintype.card_coe S

theorem card_compl_of_card_eq_three (S : Finset (Fin 18)) (h : S.card = 3) :
  Sᶜ.card = 15 :=
by
  rw [Finset.card_compl, Fintype.card_fin, h]

theorem card_equiv_of_card_eq {α β : Type*} [Fintype α] [Fintype β] [DecidableEq α] [DecidableEq β]
    (h : Fintype.card α = Fintype.card β) :
    Fintype.card (α ≃ β) = (Fintype.card α).factorial :=
by
  have e : α ≃ β := Fintype.equivOfCardEq h
  exact Fintype.card_equiv e

theorem card_subtype_perm_eq_prod (S T : Finset (Fin 18)) :
    Fintype.card { σ : Equiv.Perm (Fin 18) // Finset.image (fun x => σ x) S = T } =
    Fintype.card (↥S ≃ ↥T) * Fintype.card (↥Sᶜ ≃ ↥Tᶜ) :=
by
  let e : { σ : Equiv.Perm (Fin 18) // Finset.image (fun x => σ x) S = T } ≃ ((↥S ≃ ↥T) × (↥Sᶜ ≃ ↥Tᶜ)) :=
    { toFun := fun p =>
        ({ toFun := fun x => ⟨p.val x.val, by
             have hx := x.property
             have hx_im : p.val x.val ∈ Finset.image (fun x => p.val x) S :=
               Finset.mem_image_of_mem (fun x => p.val x) hx
             have eq1 : Finset.image (fun x => p.val x) S = T := p.property
             rw [eq1] at hx_im
             exact hx_im⟩,
           invFun := fun y => ⟨p.val.symm y.val, by
             have hy := y.property
             have hy_im : y.val ∈ Finset.image (fun x => p.val x) S := by
               have eq1 : Finset.image (fun x => p.val x) S = T := p.property
               rw [eq1]
               exact hy
             rw [Finset.mem_image] at hy_im
             rcases hy_im with ⟨z, hz, hzy⟩
             have h_eq : p.val.symm y.val = z := by
               rw [← hzy, Equiv.symm_apply_apply]
             rw [h_eq]
             exact hz⟩,
           left_inv := fun x => Subtype.ext (Equiv.symm_apply_apply p.val x.val),
           right_inv := fun y => Subtype.ext (Equiv.apply_symm_apply p.val y.val) },
         { toFun := fun x => ⟨p.val x.val, by
             have hx := x.property
             simp only [Finset.mem_compl] at hx ⊢
             intro h
             have eq1 : Finset.image (fun x => p.val x) S = T := p.property
             have h_im : p.val x.val ∈ Finset.image (fun x => p.val x) S := by
               rw [eq1]
               exact h
             rw [Finset.mem_image] at h_im
             rcases h_im with ⟨z, hz, hzy⟩
             have h_eq : z = x.val := by
               have h1 := congrArg p.val.symm hzy
               rw [Equiv.symm_apply_apply, Equiv.symm_apply_apply] at h1
               exact h1
             rw [h_eq] at hz
             exact hx hz⟩,
           invFun := fun y => ⟨p.val.symm y.val, by
             have hy := y.property
             simp only [Finset.mem_compl] at hy ⊢
             intro h
             have h_im : p.val (p.val.symm y.val) ∈ Finset.image (fun x => p.val x) S :=
               Finset.mem_image_of_mem (fun x => p.val x) h
             rw [Equiv.apply_symm_apply] at h_im
             have eq1 : Finset.image (fun x => p.val x) S = T := p.property
             rw [eq1] at h_im
             exact hy h_im⟩,
           left_inv := fun x => Subtype.ext (Equiv.symm_apply_apply p.val x.val),
           right_inv := fun y => Subtype.ext (Equiv.apply_symm_apply p.val y.val) }),
      invFun := fun p =>
        ⟨{ toFun := fun x => if h : x ∈ S then (p.1 ⟨x, h⟩).val else (p.2 ⟨x, Finset.mem_compl.mpr h⟩).val,
           invFun := fun y => if h : y ∈ T then (p.1.symm ⟨y, h⟩).val else (p.2.symm ⟨y, Finset.mem_compl.mpr h⟩).val,
           left_inv := fun x => by
             by_cases hx : x ∈ S
             · have eq1 : (if h : x ∈ S then (p.1 ⟨x, h⟩).val else (p.2 ⟨x, Finset.mem_compl.mpr h⟩).val) = (p.1 ⟨x, hx⟩).val := dif_pos hx
               change (fun y => if h : y ∈ T then (p.1.symm ⟨y, h⟩).val else (p.2.symm ⟨y, Finset.mem_compl.mpr h⟩).val) (if h : x ∈ S then (p.1 ⟨x, h⟩).val else (p.2 ⟨x, Finset.mem_compl.mpr h⟩).val) = x
               rw [eq1]
               dsimp only
               have hy : (p.1 ⟨x, hx⟩).val ∈ T := (p.1 ⟨x, hx⟩).property
               have eq2 : (if h : (p.1 ⟨x, hx⟩).val ∈ T then (p.1.symm ⟨(p.1 ⟨x, hx⟩).val, h⟩).val else (p.2.symm ⟨(p.1 ⟨x, hx⟩).val, Finset.mem_compl.mpr h⟩).val) = (p.1.symm ⟨(p.1 ⟨x, hx⟩).val, hy⟩).val := dif_pos hy
               rw [eq2]
               exact congrArg Subtype.val (Equiv.symm_apply_apply p.1 ⟨x, hx⟩)
             · have hx_compl : x ∈ Sᶜ := Finset.mem_compl.mpr hx
               have eq1 : (if h : x ∈ S then (p.1 ⟨x, h⟩).val else (p.2 ⟨x, Finset.mem_compl.mpr h⟩).val) = (p.2 ⟨x, hx_compl⟩).val := dif_neg hx
               change (fun y => if h : y ∈ T then (p.1.symm ⟨y, h⟩).val else (p.2.symm ⟨y, Finset.mem_compl.mpr h⟩).val) (if h : x ∈ S then (p.1 ⟨x, h⟩).val else (p.2 ⟨x, Finset.mem_compl.mpr h⟩).val) = x
               rw [eq1]
               dsimp only
               have hy_not : (p.2 ⟨x, hx_compl⟩).val ∉ T := Finset.mem_compl.mp (p.2 ⟨x, hx_compl⟩).property
               have eq2 : (if h : (p.2 ⟨x, hx_compl⟩).val ∈ T then (p.1.symm ⟨(p.2 ⟨x, hx_compl⟩).val, h⟩).val else (p.2.symm ⟨(p.2 ⟨x, hx_compl⟩).val, Finset.mem_compl.mpr h⟩).val) = (p.2.symm ⟨(p.2 ⟨x, hx_compl⟩).val, Finset.mem_compl.mpr hy_not⟩).val := dif_neg hy_not
               rw [eq2]
               exact congrArg Subtype.val (Equiv.symm_apply_apply p.2 ⟨x, hx_compl⟩),
           right_inv := fun y => by
             by_cases hy : y ∈ T
             · have eq1 : (if h : y ∈ T then (p.1.symm ⟨y, h⟩).val else (p.2.symm ⟨y, Finset.mem_compl.mpr h⟩).val) = (p.1.symm ⟨y, hy⟩).val := dif_pos hy
               change (fun x => if h : x ∈ S then (p.1 ⟨x, h⟩).val else (p.2 ⟨x, Finset.mem_compl.mpr h⟩).val) (if h : y ∈ T then (p.1.symm ⟨y, h⟩).val else (p.2.symm ⟨y, Finset.mem_compl.mpr h⟩).val) = y
               rw [eq1]
               dsimp only
               have hx : (p.1.symm ⟨y, hy⟩).val ∈ S := (p.1.symm ⟨y, hy⟩).property
               have eq2 : (if h : (p.1.symm ⟨y, hy⟩).val ∈ S then (p.1 ⟨(p.1.symm ⟨y, hy⟩).val, h⟩).val else (p.2 ⟨(p.1.symm ⟨y, hy⟩).val, Finset.mem_compl.mpr h⟩).val) = (p.1 ⟨(p.1.symm ⟨y, hy⟩).val, hx⟩).val := dif_pos hx
               rw [eq2]
               exact congrArg Subtype.val (Equiv.apply_symm_apply p.1 ⟨y, hy⟩)
             · have hy_compl : y ∈ Tᶜ := Finset.mem_compl.mpr hy
               have eq1 : (if h : y ∈ T then (p.1.symm ⟨y, h⟩).val else (p.2.symm ⟨y, Finset.mem_compl.mpr h⟩).val) = (p.2.symm ⟨y, hy_compl⟩).val := dif_neg hy
               change (fun x => if h : x ∈ S then (p.1 ⟨x, h⟩).val else (p.2 ⟨x, Finset.mem_compl.mpr h⟩).val) (if h : y ∈ T then (p.1.symm ⟨y, h⟩).val else (p.2.symm ⟨y, Finset.mem_compl.mpr h⟩).val) = y
               rw [eq1]
               dsimp only
               have hx_not : (p.2.symm ⟨y, hy_compl⟩).val ∉ S := Finset.mem_compl.mp (p.2.symm ⟨y, hy_compl⟩).property
               have eq2 : (if h : (p.2.symm ⟨y, hy_compl⟩).val ∈ S then (p.1 ⟨(p.2.symm ⟨y, hy_compl⟩).val, h⟩).val else (p.2 ⟨(p.2.symm ⟨y, hy_compl⟩).val, Finset.mem_compl.mpr h⟩).val) = (p.2 ⟨(p.2.symm ⟨y, hy_compl⟩).val, Finset.mem_compl.mpr hx_not⟩).val := dif_neg hx_not
               rw [eq2]
               exact congrArg Subtype.val (Equiv.apply_symm_apply p.2 ⟨y, hy_compl⟩) },
          by
            ext y
            simp only [Finset.mem_image]
            constructor
            · rintro ⟨x, hx, hxy⟩
              have eq1 : (if h : x ∈ S then (p.1 ⟨x, h⟩).val else (p.2 ⟨x, Finset.mem_compl.mpr h⟩).val) = (p.1 ⟨x, hx⟩).val := dif_pos hx
              change (if h : x ∈ S then (p.1 ⟨x, h⟩).val else (p.2 ⟨x, Finset.mem_compl.mpr h⟩).val) = y at hxy
              rw [eq1] at hxy
              rw [← hxy]
              exact (p.1 ⟨x, hx⟩).property
            · intro hy
              use (p.1.symm ⟨y, hy⟩).val
              have hx : (p.1.symm ⟨y, hy⟩).val ∈ S := (p.1.symm ⟨y, hy⟩).property
              refine ⟨hx, ?_⟩
              change (if h : (p.1.symm ⟨y, hy⟩).val ∈ S then (p.1 ⟨(p.1.symm ⟨y, hy⟩).val, h⟩).val else (p.2 ⟨(p.1.symm ⟨y, hy⟩).val, Finset.mem_compl.mpr h⟩).val) = y
              have eq1 : (if h : (p.1.symm ⟨y, hy⟩).val ∈ S then (p.1 ⟨(p.1.symm ⟨y, hy⟩).val, h⟩).val else (p.2 ⟨(p.1.symm ⟨y, hy⟩).val, Finset.mem_compl.mpr h⟩).val) = (p.1 ⟨(p.1.symm ⟨y, hy⟩).val, hx⟩).val := dif_pos hx
              rw [eq1]
              exact congrArg Subtype.val (Equiv.apply_symm_apply p.1 ⟨y, hy⟩)⟩,
      left_inv := fun p => by
        apply Subtype.ext
        apply Equiv.ext
        intro x
        dsimp
        split_ifs
        · rfl
        · rfl,
      right_inv := fun p => by
        refine Prod.ext ?_ ?_
        · apply Equiv.ext
          intro a
          apply Subtype.ext
          dsimp
          exact dif_pos a.property
        · apply Equiv.ext
          intro a
          apply Subtype.ext
          dsimp
          have h : a.val ∉ S := Finset.mem_compl.mp a.property
          exact dif_neg h }
  rw [Fintype.card_congr e, Fintype.card_prod]

theorem card_filter_univ_eq_card_subtype {α : Type*} [Fintype α] (p : α → Prop) [DecidablePred p] :
  (Finset.filter p Finset.univ).card = Fintype.card {x // p x} :=
by
  symm
  apply Fintype.card_of_subtype
  intro x
  rw [Finset.mem_filter]
  exact and_iff_right (Finset.mem_univ x)

theorem card_perms_mapping_set (S T : Finset (Fin 18)) (hS : S.card = 3) (hT : T.card = 3) :
  (Finset.filter (fun σ : Equiv.Perm (Fin 18) => Finset.image (fun x => σ x) S = T) Finset.univ).card =
    Nat.factorial 3 * Nat.factorial 15 :=
by
  rw [card_filter_univ_eq_card_subtype]
  rw [card_subtype_perm_eq_prod S T]
  have hST : Fintype.card ↥S = Fintype.card ↥T := by
    rw [fintype_card_coe_finset_eq S, fintype_card_coe_finset_eq T, hS, hT]
  have hScTc : Fintype.card ↥Sᶜ = Fintype.card ↥Tᶜ := by
    rw [fintype_card_coe_finset_eq Sᶜ, fintype_card_coe_finset_eq Tᶜ]
    rw [card_compl_of_card_eq_three S hS, card_compl_of_card_eq_three T hT]
  rw [card_equiv_of_card_eq hST, card_equiv_of_card_eq hScTc]
  have hS_card : Fintype.card ↥S = 3 := by
    rw [fintype_card_coe_finset_eq S, hS]
  have hSc_card : Fintype.card ↥Sᶜ = 15 := by
    rw [fintype_card_coe_finset_eq Sᶜ, card_compl_of_card_eq_three S hS]
  rw [hS_card, hSc_card]

theorem sum_const_nat_proof {α : Type*} (s : Finset α) (c : ℕ) : ∑ i ∈ s, c = s.card * c :=
by
  exact Finset.sum_const_nat (fun _ _ => rfl)

theorem perm_sum_eq_T_card (a : Fin 18 → ℝ) (c : Fin 6) :
  ∑ σ : Equiv.Perm (Fin 18), is_good_trip_ind a σ c =
  (T_set a).card * (Nat.factorial 3 * Nat.factorial 15) :=
by
  rw [sum_is_good_trip_ind_eq_card]
  rw [filter_is_good_trip_eq_bUnion]
  have h_disj : Set.PairwiseDisjoint (↑(T_set a)) (fun T => Finset.filter (fun σ : Equiv.Perm (Fin 18) => Finset.image (fun x => σ x) (B_c c) = T) Finset.univ) := by
    intro T1 _ T2 _ hne
    exact disjoint_image_filters (B_c c) hne
  rw [Finset.card_biUnion h_disj]
  have h_sum : ∑ T ∈ T_set a, (Finset.filter (fun σ : Equiv.Perm (Fin 18) => Finset.image (fun x => σ x) (B_c c) = T) Finset.univ).card =
               ∑ T ∈ T_set a, (Nat.factorial 3 * Nat.factorial 15) := by
    apply Finset.sum_congr rfl
    intro T hT
    exact card_perms_mapping_set (B_c c) T (B_c_card c) (T_set_mem_card_eq_3 a hT)
  rw [h_sum]
  exact sum_const_nat_proof (T_set a) (Nat.factorial 3 * Nat.factorial 15)

theorem lower_bound (a : Fin 18 → ℝ) : 136 ≤ A a :=
by
  rw [A_eq_T_set_card a]
  have h1 := sum_is_good_trip_ge a
  have h2 : ∑ σ : Equiv.Perm (Fin 18), ∑ c : Fin 6, is_good_trip_ind a σ c = ∑ c : Fin 6, ∑ σ : Equiv.Perm (Fin 18), is_good_trip_ind a σ c := Finset.sum_comm
  rw [h2] at h1
  have h3 : ∑ c : Fin 6, ∑ σ : Equiv.Perm (Fin 18), is_good_trip_ind a σ c = ∑ c : Fin 6, ((T_set a).card * (Nat.factorial 3 * Nat.factorial 15)) := by
    apply Finset.sum_congr rfl
    intro c _
    exact perm_sum_eq_T_card a c
  rw [h3] at h1
  have h4 : ∑ c : Fin 6, ((T_set a).card * (Nat.factorial 3 * Nat.factorial 15)) = 6 * ((T_set a).card * (Nat.factorial 3 * Nat.factorial 15)) := by
    rw [Finset.sum_const, Finset.card_univ, Fintype.card_fin]
    rfl
  rw [h4] at h1
  revert h1
  generalize (T_set a).card = C
  intro h1
  have h5 : (Nat.factorial 18 : ℕ) = 6402373705728000 := by rfl
  have h6 : (Nat.factorial 3 : ℕ) = 6 := by rfl
  have h7 : (Nat.factorial 15 : ℕ) = 1307674368000 := by rfl
  rw [h5, h6, h7] at h1
  omega

theorem PBBasic009 : iInf A = 136 :=
by
  apply le_antisymm
  · have hBdd : BddBelow (Set.range A) := ⟨0, fun y ⟨x, hx⟩ => hx ▸ Nat.zero_le (A x)⟩
    have h1 := ciInf_le hBdd a0
    rw [A_a0] at h1
    exact h1
  · exact le_ciInf fun a => lower_bound a
