import Mathlib
variable (Googler Color : Type) (flags : Googler → Finset Color)
def tripleCond : Prop :=
  ∀ triple : Finset Googler, triple.card = 3 →
    ∃ g1 ∈ triple, ∃ g2 ∈ triple, g1 ≠ g2 ∧ ¬ Disjoint (flags g1) (flags g2)

theorem PBBasic014 (num_googlers : Googler ≃ Fin 2024)
    (num_flags : ∀ googler, (flags googler).card ≤ 5)
    (cond : tripleCond Googler Color flags) : ∃ color : Color, Nat.card {g : Googler | color ∈ flags g } ≥ 200 :=
by
  classical
  by_contra h_contra
  push_neg at h_contra

  haveI : Fintype Googler := Fintype.ofEquiv _ num_googlers.symm
  have hG_card : Fintype.card Googler = 2024 := by
    rw [Fintype.card_congr num_googlers]
    exact Fintype.card_fin 2024

  let C (x : Googler) : Finset Googler :=
    (flags x).biUnion (fun c => Finset.filter (fun g => c ∈ flags g) Finset.univ)

  have hC : ∀ x : Googler, (C x).card ≤ 995 := by
    intro x
    have h1 : (C x).card ≤ ∑ c ∈ flags x, (Finset.filter (fun g => c ∈ flags g) Finset.univ).card := Finset.card_biUnion_le
    have h2 : ∑ c ∈ flags x, (Finset.filter (fun g => c ∈ flags g) Finset.univ).card ≤ ∑ c ∈ flags x, 199 := by
      apply Finset.sum_le_sum
      intro c _
      have eq : (Finset.filter (fun g => c ∈ flags g) Finset.univ).card = Nat.card {g : Googler | c ∈ flags g} := by
        rw [Nat.card_eq_fintype_card]
        change (Finset.filter (fun g => c ∈ flags g) Finset.univ).card = Fintype.card {g : Googler // c ∈ flags g}
        exact (Fintype.card_subtype (fun g => c ∈ flags g)).symm
      rw [eq]
      have h_lt := h_contra c
      omega
    have h3 : ∑ c ∈ flags x, 199 = (flags x).card * 199 := by
      simp only [Finset.sum_const, smul_eq_mul, nsmul_eq_mul]
    have h_flags : (flags x).card ≤ 5 := num_flags x
    omega

  let B (x : Googler) : Finset Googler := insert x (C x)
  have hB : ∀ x : Googler, (B x).card ≤ 996 := by
    intro x
    have : (B x).card ≤ (C x).card + 1 := Finset.card_insert_le x (C x)
    have : (C x).card ≤ 995 := hC x
    omega

  -- Since `num_googlers` provides an explicit equivalence and `0 < 2024`,
  -- we can robustly extract our first element.
  let g1 : Googler := num_googlers.symm 0

  have h_diff1 : 0 < (Finset.univ \ B g1).card := by
    have h_sub : (B g1) ⊆ Finset.univ := Finset.subset_univ _
    rw [Finset.card_sdiff_of_subset h_sub]
    have : (Finset.univ : Finset Googler).card = 2024 := hG_card
    have : (B g1).card ≤ 996 := hB g1
    omega
  have h_ex2 : (Finset.univ \ B g1).Nonempty := Finset.card_pos.mp h_diff1
  obtain ⟨g2, hg2_diff⟩ := h_ex2
  have hg2_notin : g2 ∉ B g1 := by
    have h_in := hg2_diff
    rw [Finset.mem_sdiff] at h_in
    exact h_in.2

  let B12 := B g1 ∪ B g2
  have h_B12_card : B12.card ≤ 1992 := by
    have h1 : B12.card ≤ (B g1).card + (B g2).card := Finset.card_union_le (B g1) (B g2)
    have h2 : (B g1).card ≤ 996 := hB g1
    have h3 : (B g2).card ≤ 996 := hB g2
    omega
  have h_diff2 : 0 < (Finset.univ \ B12).card := by
    have h_sub : B12 ⊆ Finset.univ := Finset.subset_univ _
    rw [Finset.card_sdiff_of_subset h_sub]
    have : (Finset.univ : Finset Googler).card = 2024 := hG_card
    omega
  have h_ex3 : (Finset.univ \ B12).Nonempty := Finset.card_pos.mp h_diff2
  obtain ⟨g3, hg3_diff⟩ := h_ex3
  have hg3_notin : g3 ∉ B12 := by
    have h_in := hg3_diff
    rw [Finset.mem_sdiff] at h_in
    exact h_in.2

  have hg2_neq_g1 : g2 ≠ g1 := by
    intro heq
    rw [heq] at hg2_notin
    have h_B : g1 ∈ B g1 := Finset.mem_insert_self g1 (C g1)
    exact hg2_notin h_B

  have hg3_neq_g1 : g3 ≠ g1 := by
    intro heq
    rw [heq] at hg3_notin
    have h_B : g1 ∈ B g1 := Finset.mem_insert_self g1 (C g1)
    have h_B12 : g1 ∈ B12 := Finset.mem_union.mpr (Or.inl h_B)
    exact hg3_notin h_B12

  have hg3_neq_g2 : g3 ≠ g2 := by
    intro heq
    rw [heq] at hg3_notin
    have h_B : g2 ∈ B g2 := Finset.mem_insert_self g2 (C g2)
    have h_B12 : g2 ∈ B12 := Finset.mem_union.mpr (Or.inr h_B)
    exact hg3_notin h_B12

  let T3 : Finset Googler := insert g1 (insert g2 {g3})

  have h1 : g2 ∉ ({g3} : Finset Googler) := by
    simp only [Finset.mem_singleton]
    exact hg3_neq_g2.symm

  have h2 : g1 ∉ insert g2 ({g3} : Finset Googler) := by
    simp only [Finset.mem_insert, Finset.mem_singleton]
    push_neg
    exact ⟨hg2_neq_g1.symm, hg3_neq_g1.symm⟩

  have hc3 : T3.card = 3 := by
    change (insert g1 (insert g2 {g3} : Finset Googler)).card = 3
    rw [Finset.card_insert_of_notMem h2]
    rw [Finset.card_insert_of_notMem h1]
    rw [Finset.card_singleton]

  obtain ⟨x, hx_mem, y, hy_mem, hxy_neq, hxy_ndisj⟩ := cond T3 hc3

  have hx_cases : x = g1 ∨ x = g2 ∨ x = g3 := by
    have h_in : x ∈ T3 := hx_mem
    change x ∈ insert g1 (insert g2 ({g3} : Finset Googler)) at h_in
    simp only [Finset.mem_insert, Finset.mem_singleton] at h_in
    exact h_in

  have hy_cases : y = g1 ∨ y = g2 ∨ y = g3 := by
    have h_in : y ∈ T3 := hy_mem
    change y ∈ insert g1 (insert g2 ({g3} : Finset Googler)) at h_in
    simp only [Finset.mem_insert, Finset.mem_singleton] at h_in
    exact h_in

  have hd12 : Disjoint (flags g1) (flags g2) := by
    rw [Finset.disjoint_left]
    intro c hc_g1 hc_g2
    have h_in : g2 ∈ C g1 := by
      rw [Finset.mem_biUnion]
      use c
      refine ⟨hc_g1, ?_⟩
      rw [Finset.mem_filter]
      exact ⟨Finset.mem_univ g2, hc_g2⟩
    have h_B : g2 ∈ B g1 := Finset.mem_insert.mpr (Or.inr h_in)
    exact hg2_notin h_B

  have hd13 : Disjoint (flags g1) (flags g3) := by
    rw [Finset.disjoint_left]
    intro c hc_g1 hc_g3
    have h_in : g3 ∈ C g1 := by
      rw [Finset.mem_biUnion]
      use c
      refine ⟨hc_g1, ?_⟩
      rw [Finset.mem_filter]
      exact ⟨Finset.mem_univ g3, hc_g3⟩
    have h_B : g3 ∈ B g1 := Finset.mem_insert.mpr (Or.inr h_in)
    have h_B12 : g3 ∈ B12 := Finset.mem_union.mpr (Or.inl h_B)
    exact hg3_notin h_B12

  have hd23 : Disjoint (flags g2) (flags g3) := by
    rw [Finset.disjoint_left]
    intro c hc_g2 hc_g3
    have h_in : g3 ∈ C g2 := by
      rw [Finset.mem_biUnion]
      use c
      refine ⟨hc_g2, ?_⟩
      rw [Finset.mem_filter]
      exact ⟨Finset.mem_univ g3, hc_g3⟩
    have h_B : g3 ∈ B g2 := Finset.mem_insert.mpr (Or.inr h_in)
    have h_B12 : g3 ∈ B12 := Finset.mem_union.mpr (Or.inr h_B)
    exact hg3_notin h_B12

  rcases hx_cases with rfl | rfl | rfl
  · rcases hy_cases with rfl | rfl | rfl
    · exact hxy_neq rfl
    · exact hxy_ndisj hd12
    · exact hxy_ndisj hd13
  · rcases hy_cases with rfl | rfl | rfl
    · exact hxy_ndisj hd12.symm
    · exact hxy_neq rfl
    · exact hxy_ndisj hd23
  · rcases hy_cases with rfl | rfl | rfl
    · exact hxy_ndisj hd13.symm
    · exact hxy_ndisj hd23.symm
    · exact hxy_neq rfl
