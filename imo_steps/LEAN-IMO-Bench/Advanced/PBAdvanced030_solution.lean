import Mathlib
def IsConsecutive {m : ℕ} (A : Finset (Fin m)) : Prop :=
  A.Nonempty ∧ ∃ (start : Fin m) (len : ℕ),
    A.card = len ∧ len > 0 ∧
    ∀ k : Fin m, k ∈ A ↔ ∃ i < len, k = start + i
def satisfies_partition_condition {m n : ℕ} (scores : Fin n → Fin m → ℝ) : Prop :=
  ∀ (p : Fin n),
    ∃ (groups : Fin n → Finset (Fin m)),
      (∀ i : Fin n, IsConsecutive (groups i)) ∧
      (∀ c : Fin m, ∃! i : Fin n, c ∈ groups i) ∧
      (∀ i : Fin n, Finset.sum (groups i) (fun c => scores p c) ≥ 1)
def exists_good_distribution {m n : ℕ} (scores : Fin n → Fin m → ℝ) : Prop :=
  ∃ (D : Fin m → Fin n),
    ∀ (p : Fin n),
      let received_cupcakes : Finset (Fin m) := Finset.univ.filter (fun c => D c = p)
      Finset.sum received_cupcakes (fun c => scores p c) ≥ 1

def group_maxes {m n : ℕ} (groups : Fin n → Finset (Fin m))
  (h_cons : ∀ i, IsConsecutive (groups i)) : Finset (Fin m) :=
  Finset.image (fun i => (groups i).max' (h_cons i).1) Finset.univ

theorem PBAdvanced030_eq {m n : ℕ} (scores : Fin n → Fin m → ℝ) (hm : 1 ≤ m) (hn : 1 ≤ n)
    (hmn : n = m) (h_nonneg : ∀ (p : Fin n) (c : Fin m), 0 ≤ scores p c)
    (h_part : satisfies_partition_condition scores) :
    exists_good_distribution scores :=
by
  subst hmn
  dsimp [exists_good_distribution]
  use id
  intro p

  -- ensure our target is cleanly presented without local 'let' barriers blocking rewrites
  change Finset.sum (Finset.filter (fun c => id c = p) Finset.univ) (fun c => scores p c) ≥ 1

  have h_rc : Finset.filter (fun c => id c = p) Finset.univ = {p} := by
    ext c
    rw [Finset.mem_filter, Finset.mem_singleton]
    exact ⟨fun h => h.2, fun h => ⟨Finset.mem_univ c, h⟩⟩

  have h_part_p := h_part p
  obtain ⟨groups, h_cons, h_part_c, h_sum⟩ := h_part_p

  have H1 : (Finset.univ : Finset (Fin n)) = Finset.biUnion Finset.univ groups := by
    ext c
    rw [Finset.mem_biUnion]
    obtain ⟨i, hi, _⟩ := h_part_c c
    exact iff_of_true (Finset.mem_univ c) ⟨i, Finset.mem_univ i, hi⟩

  have H2 : (↑(Finset.univ : Finset (Fin n)) : Set (Fin n)).PairwiseDisjoint groups := by
    intro x _ y _ hne
    -- resolve 'Function.onFun' wrapper generated strictly by the definition of PairwiseDisjoint
    change Disjoint (groups x) (groups y)
    rw [Finset.disjoint_left]
    intro a ha_x ha_y
    obtain ⟨i, hi, h_uniq⟩ := h_part_c a
    have hx := h_uniq x ha_x
    have hy := h_uniq y ha_y
    have h_eq : x = y := Eq.trans hx hy.symm
    exact hne h_eq

  have h_card_univ : (Finset.univ : Finset (Fin n)).card = n := Fintype.card_fin n
  have h_card_biUnion := Finset.card_biUnion H2
  rw [← H1, h_card_univ] at h_card_biUnion

  have h_ne : ∀ x, 1 ≤ (groups x).card := by
    intro x
    have ⟨h_nonempty, _⟩ := h_cons x
    have h_pos := Finset.card_pos.mpr h_nonempty
    omega

  have h_card_eq_one : ∀ x, (groups x).card = 1 := by
    intro x
    have H_diff_sum : ∑ y : Fin n, (((groups y).card : ℝ) - 1) = 0 := by
      rw [Finset.sum_sub_distrib]
      have h1 : ∑ y : Fin n, ((groups y).card : ℝ) = (n : ℝ) := by
        have h_sum_nat : ∑ y : Fin n, (groups y).card = n := h_card_biUnion.symm
        -- Avoid rewriting `n` universally since it forms part of the index bound type `Fin n`.
        have h_cast : ((∑ y : Fin n, (groups y).card) : ℝ) = (n : ℝ) := by exact_mod_cast h_sum_nat
        calc
          ∑ y : Fin n, ((groups y).card : ℝ) = ((∑ y : Fin n, (groups y).card) : ℝ) := by push_cast; rfl
          _ = (n : ℝ) := h_cast
      have h2 : ∑ y : Fin n, (1 : ℝ) = (n : ℝ) := by
        rw [Finset.sum_const, h_card_univ]
        simp
      rw [h1, h2, sub_self]

    have H_diff_nonneg : ∀ y ∈ (Finset.univ : Finset (Fin n)), (0 : ℝ) ≤ ((groups y).card : ℝ) - 1 := by
      intro y _
      have h_card_y := h_ne y
      have H_le : (1 : ℝ) ≤ ((groups y).card : ℝ) := by exact_mod_cast h_card_y
      linarith

    have H_sum_iff := Finset.sum_eq_zero_iff_of_nonneg H_diff_nonneg
    have H_all_zero := H_sum_iff.mp H_diff_sum
    have H_diff_eq_zero : (((groups x).card : ℝ) - 1) = 0 := H_all_zero x (Finset.mem_univ x)

    have H_eq_1_cast : ((groups x).card : ℝ) = 1 := by linarith
    exact_mod_cast H_eq_1_cast

  obtain ⟨i, hi, _⟩ := h_part_c p
  have h_groups_i : groups i = {p} := by
    have hc := h_card_eq_one i
    obtain ⟨a, ha⟩ := Finset.card_eq_one.mp hc
    have hi2 := hi
    rw [ha] at hi2
    have h_eq : a = p := (Finset.mem_singleton.mp hi2).symm
    rw [h_eq] at ha
    exact ha

  have h_sum_i := h_sum i
  rw [h_groups_i] at h_sum_i
  rw [Finset.sum_singleton] at h_sum_i

  rw [h_rc]
  rw [Finset.sum_singleton]
  exact h_sum_i

theorem card_group_maxes {m n : ℕ} (groups : Fin n → Finset (Fin m))
  (h_cons : ∀ i, IsConsecutive (groups i))
  (h_part : ∀ c, ∃! i, c ∈ groups i) :
  (group_maxes groups h_cons).card = n :=
by
  dsimp [group_maxes]
  have h_inj : Function.Injective (fun i => (groups i).max' (h_cons i).1) := by
    intro i j hij
    -- Beta-reduce the injectivity assumption to make it readable for `rw`
    change (groups i).max' (h_cons i).1 = (groups j).max' (h_cons j).1 at hij

    have hi : (groups i).max' (h_cons i).1 ∈ groups i := Finset.max'_mem (groups i) (h_cons i).1
    have hj : (groups j).max' (h_cons j).1 ∈ groups j := Finset.max'_mem (groups j) (h_cons j).1
    rw [hij] at hi

    have h_ex := h_part ((groups j).max' (h_cons j).1)
    obtain ⟨k, hk⟩ := h_ex
    have eq_i := hk.2 i hi
    have eq_j := hk.2 j hj
    exact eq_i.trans eq_j.symm

  rw [Finset.card_image_of_injective Finset.univ h_inj]
  rw [Finset.card_univ, Fintype.card_fin]

theorem exists_strictMono_surj_of_card_eq {m n : ℕ} (S : Finset (Fin m)) (h : S.card = n) :
  ∃ R : Fin n → Fin m, StrictMono R ∧ (∀ k, R k ∈ S) ∧ (∀ c ∈ S, ∃ k, R k = c) :=
by
  let e := Finset.orderIsoOfFin S h
  use fun k => (e k).val
  refine ⟨?_, ?_, ?_⟩
  · intro x y hxy
    exact e.strictMono hxy
  · intro k
    exact (e k).property
  · intro c hc
    use e.symm ⟨c, hc⟩
    simp

theorem le_R_of_mem {m n : ℕ}
  (groups : Fin n → Finset (Fin m))
  (h_cons : ∀ i, IsConsecutive (groups i))
  (R : Fin n → Fin m)
  (P : Fin n → Fin n)
  (h_R_eq_max_P : ∀ k, R k = (groups (P k)).max' (h_cons (P k)).1)
  {k : Fin n} {c : Fin m} (hc : c ∈ groups (P k)) :
  c ≤ R k :=
by
  rw [h_R_eq_max_P k]
  have h_iff := Finset.max'_eq_iff (groups (P k)) (h_cons (P k)).1 ((groups (P k)).max' (h_cons (P k)).1)
  exact (h_iff.mp rfl).2 c hc

theorem R_lt_of_lt_of_mem {m n : ℕ}
  (groups : Fin n → Finset (Fin m))
  (h_cons : ∀ i, IsConsecutive (groups i))
  (h_part : ∀ c, ∃! i, c ∈ groups i)
  (R : Fin n → Fin m)
  (P : Fin n → Fin n)
  (h_R_strictMono : StrictMono R)
  (h_R_eq_max_P : ∀ k, R k = (groups (P k)).max' (h_cons (P k)).1)
  {j k : Fin n} (hjk : j < k) {c : Fin m} (hc : c ∈ groups (P k)) :
  R j < c :=
by
  by_contra h_not_lt
  have h_le : c ≤ R j := by omega

  have h_Rk_mem : R k ∈ groups (P k) := by
    rw [h_R_eq_max_P k]
    exact Finset.max'_mem _ _

  have h_Rj_mem_j : R j ∈ groups (P j) := by
    rw [h_R_eq_max_P j]
    exact Finset.max'_mem _ _

  have h_Rj_lt_Rk : R j < R k := h_R_strictMono hjk

  -- Extract the 6 flattened parameters logically unpacked from `IsConsecutive`
  obtain ⟨_, start_k, len_k, _, _, h_iff_k⟩ := h_cons (P k)

  obtain ⟨i_c, hic_lt, hc_eq⟩ := (h_iff_k c).mp hc
  obtain ⟨i_k, hik_lt, hRk_eq⟩ := (h_iff_k (R k)).mp h_Rk_mem

  -- Because `c ≤ R j < R k` and both `c` and `R k` are in the consecutive sequence, `R j` must be as well.
  have h_Rj_mem_k : R j ∈ groups (P k) := by
    apply (h_iff_k (R j)).mpr
    use (R j : ℕ) - (start_k : ℕ)
    constructor
    · omega
    · omega

  -- Uniqueness given by the strict partition
  have h_P_eq : P j = P k := by
    obtain ⟨i, _, hi_unique⟩ := h_part (R j)
    have hj_eq : P j = i := hi_unique (P j) h_Rj_mem_j
    have hk_eq : P k = i := hi_unique (P k) h_Rj_mem_k
    exact hj_eq.trans hk_eq.symm

  have h_R_eq : R j = R k := by
    have h1 := h_R_eq_max_P j
    have h2 := h_R_eq_max_P k
    rw [h_P_eq] at h1
    exact h1.trans h2.symm

  -- We found `R j = R k`, which severely contradicts our initial deduction that `R j < R k`
  omega

theorem P_surj {m n : ℕ}
  (groups : Fin n → Finset (Fin m))
  (h_cons : ∀ i, IsConsecutive (groups i))
  (h_part : ∀ c, ∃! i, c ∈ groups i)
  (R : Fin n → Fin m)
  (P : Fin n → Fin n)
  (h_R_eq_max_P : ∀ k, R k = (groups (P k)).max' (h_cons (P k)).1)
  (h_R_surj : ∀ c ∈ group_maxes groups h_cons, ∃ k, R k = c)
  (i : Fin n) :
  ∃ j : Fin n, P j = i :=
by
  let c_i := (groups i).max' (h_cons i).1
  have hc_i_in_groups : c_i ∈ groups i := Finset.max'_mem (groups i) (h_cons i).1
  have hc_i_in_maxes : c_i ∈ group_maxes groups h_cons := by
    unfold group_maxes
    rw [Finset.mem_image]
    exact ⟨i, Finset.mem_univ i, rfl⟩
  obtain ⟨j, hj⟩ := h_R_surj c_i hc_i_in_maxes
  have h_R_j_in_groups : R j ∈ groups (P j) := by
    rw [h_R_eq_max_P j]
    exact Finset.max'_mem (groups (P j)) (h_cons (P j)).1
  have hc_i_in_groups_P_j : c_i ∈ groups (P j) := hj ▸ h_R_j_in_groups
  exact ⟨j, ExistsUnique.unique (h_part c_i) hc_i_in_groups_P_j hc_i_in_groups⟩

theorem le_R_of_mem_aux {m n : ℕ}
  (groups : Fin n → Finset (Fin m))
  (h_cons : ∀ i, IsConsecutive (groups i))
  (R : Fin n → Fin m)
  (P : Fin n → Fin n)
  (h_R_eq_max_P : ∀ k, R k = (groups (P k)).max' (h_cons (P k)).1)
  {c : Fin m} {j : Fin n}
  (hc : c ∈ groups (P j)) :
  c ≤ R j :=
by
  rw [h_R_eq_max_P j]
  exact Finset.le_max' (groups (P j)) c hc

theorem R_lt_of_lt_of_mem_aux {m n : ℕ}
  (groups : Fin n → Finset (Fin m))
  (h_cons : ∀ i, IsConsecutive (groups i))
  (h_part : ∀ c, ∃! i, c ∈ groups i)
  (R : Fin n → Fin m)
  (P : Fin n → Fin n)
  (h_R_strictMono : StrictMono R)
  (h_R_eq_max_P : ∀ k, R k = (groups (P k)).max' (h_cons (P k)).1)
  {k j : Fin n} {c : Fin m}
  (hkj : k < j)
  (hc : c ∈ groups (P j)) :
  R k < c :=
by
  -- Proof by contradiction: assume R k ≥ c
  by_contra hcontra
  push_neg at hcontra

  -- Strict monotonicity gives R k < R j
  have h_R_mono : R k < R j := h_R_strictMono hkj

  -- R j is the maximum of groups (P j), thus is an element of groups (P j)
  have h_R_j_mem : R j ∈ groups (P j) := by
    rw [h_R_eq_max_P j]
    exact Finset.max'_mem _ _

  -- Similarly, R k is an element of groups (P k)
  have h_R_k_mem : R k ∈ groups (P k) := by
    rw [h_R_eq_max_P k]
    exact Finset.max'_mem _ _

  -- Since groups (P j) is consecutive, any value strictly between its elements is also in the group
  have h_Rk_in_Pj : R k ∈ groups (P j) := by
    obtain ⟨h_nonempty, start, len, hcard, hlen_pos, h_iff⟩ := h_cons (P j)
    have hc_in := (h_iff c).mp hc
    have hRj_in := (h_iff (R j)).mp h_R_j_mem
    obtain ⟨ic, hic_len, hic_eq⟩ := hc_in
    obtain ⟨iR, hiR_len, hiR_eq⟩ := hRj_in
    apply (h_iff (R k)).mpr
    use (R k : ℕ) - (start : ℕ)
    constructor
    · omega
    · omega

  -- Since groups form a partition, R k belonging to both groups (P k) and groups (P j) implies P k = P j
  have h_Pk_eq_Pj : P k = P j := by
    obtain ⟨i, hi, h_unique⟩ := h_part (R k)
    have h1 := h_unique (P k) h_R_k_mem
    have h2 := h_unique (P j) h_Rk_in_Pj
    exact h1.trans h2.symm

  -- The equality of the groups implies the equality of their maximums
  have h_Rk_eq_Rj : R k = R j := by
    have eq1 := h_R_eq_max_P k
    have eq2 := h_R_eq_max_P j
    rw [h_Pk_eq_Pj] at eq1
    exact eq1.trans eq2.symm

  -- This creates a direct contradiction with R k < R j
  omega

theorem mem_group_P_of_bounds {m n : ℕ}
  (groups : Fin n → Finset (Fin m))
  (h_cons : ∀ i, IsConsecutive (groups i))
  (h_part : ∀ c, ∃! i, c ∈ groups i)
  (R : Fin n → Fin m)
  (P : Fin n → Fin n)
  (h_R_strictMono : StrictMono R)
  (h_R_eq_max_P : ∀ k, R k = (groups (P k)).max' (h_cons (P k)).1)
  (h_R_surj : ∀ c ∈ group_maxes groups h_cons, ∃ k, R k = c)
  (k : Fin n) (c : Fin m)
  (hc_lt : ∀ j < k, R j < c)
  (hc_le : c ≤ R k) :
  c ∈ groups (P k) :=
by
  have ⟨i, hi, _⟩ := h_part c
  have ⟨j, hj⟩ := P_surj groups h_cons h_part R P h_R_eq_max_P h_R_surj i
  have hc_mem : c ∈ groups (P j) := by rwa [hj]
  rcases lt_trichotomy j k with hjk | eq | hkj
  · have h1 : R j < c := hc_lt j hjk
    have h2 : c ≤ R j := le_R_of_mem_aux groups h_cons R P h_R_eq_max_P hc_mem
    omega
  · rw [← eq]
    exact hc_mem
  · have h1 : R k < c := R_lt_of_lt_of_mem_aux groups h_cons h_part R P h_R_strictMono h_R_eq_max_P hkj hc_mem
    omega

theorem filter_R_eq_group_P_lem {m n : ℕ}
  (groups : Fin n → Finset (Fin m))
  (h_cons : ∀ i, IsConsecutive (groups i))
  (h_part : ∀ c, ∃! i, c ∈ groups i)
  (R : Fin n → Fin m)
  (P : Fin n → Fin n)
  (h_R_strictMono : StrictMono R)
  (h_R_eq_max_P : ∀ k, R k = (groups (P k)).max' (h_cons (P k)).1)
  (h_R_surj : ∀ c ∈ group_maxes groups h_cons, ∃ k, R k = c)
  (k : Fin n) :
  @Finset.filter (Fin m) (fun c => (∀ j < k, R j < c) ∧ c ≤ R k) (Classical.decPred _) Finset.univ =
  groups (P k) :=
by
  ext c
  simp only [Finset.mem_filter, Finset.mem_univ, true_and]
  constructor
  · rintro ⟨hc_lt, hc_le⟩
    exact mem_group_P_of_bounds groups h_cons h_part R P h_R_strictMono h_R_eq_max_P h_R_surj k c hc_lt hc_le
  · intro hc
    constructor
    · intro j hj
      exact R_lt_of_lt_of_mem groups h_cons h_part R P h_R_strictMono h_R_eq_max_P hj hc
    · exact le_R_of_mem groups h_cons R P h_R_eq_max_P hc

theorem exists_R_all {m n : ℕ} (scores : Fin n → Fin m → ℝ)
    (h_part : satisfies_partition_condition scores) :
    ∃ R : Fin n → Fin n → Fin m,
      (∀ p, StrictMono (R p)) ∧
      (∀ p k,
        let I := @Finset.filter (Fin m) (fun c => (∀ (j : Fin n), j < k → R p j < c) ∧ c ≤ R p k) (Classical.decPred _) Finset.univ;
        Finset.sum I (scores p) ≥ 1) :=
by
  let chosen_groups : Fin n → Fin n → Finset (Fin m) := fun p => Classical.choose (h_part p)
  have chosen_groups_cons : ∀ p i, IsConsecutive (chosen_groups p i) :=
    fun p => (Classical.choose_spec (h_part p)).1
  have chosen_groups_part : ∀ p c, ∃! i, c ∈ chosen_groups p i :=
    fun p => (Classical.choose_spec (h_part p)).2.1
  have chosen_groups_sum : ∀ p i, Finset.sum (chosen_groups p i) (scores p) ≥ 1 :=
    fun p => (Classical.choose_spec (h_part p)).2.2

  have card_group_maxes_lem : ∀ p, (group_maxes (chosen_groups p) (chosen_groups_cons p)).card = n :=
    fun p => card_group_maxes (chosen_groups p) (chosen_groups_cons p) (chosen_groups_part p)

  have exists_strictMono : ∀ p, ∃ R : Fin n → Fin m,
    StrictMono R ∧
    (∀ k, R k ∈ group_maxes (chosen_groups p) (chosen_groups_cons p)) ∧
    (∀ c ∈ group_maxes (chosen_groups p) (chosen_groups_cons p), ∃ k, R k = c) :=
    fun p => exists_strictMono_surj_of_card_eq _ (card_group_maxes_lem p)

  let global_R : Fin n → Fin n → Fin m := fun p => Classical.choose (exists_strictMono p)
  have R_strictMono : ∀ p, StrictMono (global_R p) := fun p => (Classical.choose_spec (exists_strictMono p)).1
  have R_mem : ∀ p k, global_R p k ∈ group_maxes (chosen_groups p) (chosen_groups_cons p) := fun p k => (Classical.choose_spec (exists_strictMono p)).2.1 k
  have R_surj : ∀ p c, c ∈ group_maxes (chosen_groups p) (chosen_groups_cons p) → ∃ k, global_R p k = c := fun p => (Classical.choose_spec (exists_strictMono p)).2.2

  let P : Fin n → Fin n → Fin n := fun p k => Classical.choose (Finset.mem_image.mp (R_mem p k))
  have R_eq_max_P : ∀ p k, global_R p k = (chosen_groups p (P p k)).max' (chosen_groups_cons p (P p k)).1 :=
    fun p k => (Classical.choose_spec (Finset.mem_image.mp (R_mem p k))).2.symm

  use global_R
  constructor
  · intro p
    exact R_strictMono p
  · intro p k
    have H : @Finset.filter (Fin m) (fun c => (∀ j < k, global_R p j < c) ∧ c ≤ global_R p k) (Classical.decPred _) Finset.univ = chosen_groups p (P p k) :=
      filter_R_eq_group_P_lem (chosen_groups p) (chosen_groups_cons p) (chosen_groups_part p) (global_R p) (P p) (R_strictMono p) (R_eq_max_P p) (R_surj p) k
    exact H.symm ▸ chosen_groups_sum p (P p k)

theorem greedy_matching_exists {m n : ℕ} (R : Fin n → Fin n → Fin m) :
    ∃ P : Fin n → Fin n, Function.Bijective P ∧
      ∀ j k : Fin n, j < k → R (P j) j ≤ R (P k) j :=
by
  have H_ind : ∀ (j : ℕ) (hj : j ≤ n), ∃ P : Fin j → Fin n,
      Function.Injective P ∧
      ∀ (a : Fin j) (x : Fin n), (∀ i : Fin j, i.val < a.val → x ≠ P i) →
        R (P a) ⟨a.val, by omega⟩ ≤ R x ⟨a.val, by omega⟩ := by
    intro j
    induction' j with j ih
    · intro hj
      use fun i => Fin.elim0 i
      constructor
      · intro i1 i2 heq
        exact Fin.elim0 i1
      · intro a x h_x
        exact Fin.elim0 a
    · intro hj1
      have hj : j ≤ n := by omega
      have hj_lt : j < n := by omega
      rcases ih hj with ⟨P, hP_inj, hP_min⟩
      have H_not_surj : ¬ (∀ y : Fin n, ∃ i : Fin j, y = P i) := by
        intro h_surj
        have h1 : (Finset.univ : Finset (Fin n)) ⊆ Finset.image P (Finset.univ : Finset (Fin j)) := by
          intro y _
          rcases h_surj y with ⟨i, hi⟩
          rw [Finset.mem_image]
          exact ⟨i, Finset.mem_univ i, hi.symm⟩
        have h2 : (Finset.univ : Finset (Fin n)).card ≤ (Finset.image P Finset.univ).card := Finset.card_le_card h1
        have h3 : (Finset.image P Finset.univ).card ≤ (Finset.univ : Finset (Fin j)).card := Finset.card_image_le
        simp only [Finset.card_univ, Fintype.card_fin] at h2 h3
        omega
      push_neg at H_not_surj
      let pred := fun v => ∃ y : Fin n, (∀ i : Fin j, y ≠ P i) ∧ (R y ⟨j, hj_lt⟩).val = v
      have Hdec : DecidablePred pred := fun v => Classical.propDecidable _
      have H_ex : ∃ v, pred v := by
        rcases H_not_surj with ⟨y0, hy0⟩
        exact ⟨(R y0 ⟨j, hj_lt⟩).val, y0, hy0, rfl⟩
      let v_min := @Nat.find pred Hdec H_ex
      have H_vmin := @Nat.find_spec pred Hdec H_ex
      rcases H_vmin with ⟨y, hy_notmem, hy_val⟩
      let P' : Fin (j + 1) → Fin n := fun i =>
        if h : i.val < j then P ⟨i.val, h⟩ else y
      have P'_val : ∀ i, P' i = if h : i.val < j then P ⟨i.val, h⟩ else y := fun i => rfl
      use P'
      constructor
      · intro i1 i2 heq
        by_cases h1 : i1.val < j
        · by_cases h2 : i2.val < j
          · rw [P'_val i1, dif_pos h1, P'_val i2, dif_pos h2] at heq
            have : (⟨i1.val, h1⟩ : Fin j) = ⟨i2.val, h2⟩ := hP_inj heq
            apply Fin.ext
            exact congrArg (fun x : Fin j => x.val) this
          · rw [P'_val i1, dif_pos h1, P'_val i2, dif_neg h2] at heq
            exfalso
            exact hy_notmem ⟨i1.val, h1⟩ heq.symm
        · by_cases h2 : i2.val < j
          · rw [P'_val i1, dif_neg h1, P'_val i2, dif_pos h2] at heq
            exfalso
            exact hy_notmem ⟨i2.val, h2⟩ heq
          · apply Fin.ext
            omega
      · intro a x h_x
        by_cases ha : a.val < j
        · have H1 : P' a = P ⟨a.val, ha⟩ := by rw [P'_val a, dif_pos ha]
          have h_x_P : ∀ i : Fin j, i.val < a.val → x ≠ P i := by
            intro i hi
            have hi2 : (i.val : ℕ) < j := i.2
            have hi3 : (i.val : ℕ) < a.val := hi
            have H2 : P' ⟨i.val, by omega⟩ = P i := by rw [P'_val _, dif_pos hi2]
            have H3 := h_x ⟨i.val, by omega⟩ hi3
            rw [H2] at H3
            exact H3
          have H_ind_step := hP_min ⟨a.val, ha⟩ x h_x_P
          rw [H1]
          exact H_ind_step
        · have ha_eq : a.val = j := by omega
          have H1 : P' a = y := by rw [P'_val a, dif_neg ha]
          have h_x_P : ∀ i : Fin j, x ≠ P i := by
            intro i
            have hi : (i.val : ℕ) < a.val := by omega
            have hi2 : (i.val : ℕ) < j := i.2
            have H2 : P' ⟨i.val, by omega⟩ = P i := by rw [P'_val _, dif_pos hi2]
            have H3 := h_x ⟨i.val, by omega⟩ hi
            rw [H2] at H3
            exact H3
          have H_x_valid : pred (R x ⟨j, hj_lt⟩).val := ⟨x, h_x_P, rfl⟩
          have H_le := @Nat.find_min' pred Hdec H_ex (R x ⟨j, hj_lt⟩).val H_x_valid
          rw [← hy_val] at H_le
          rw [H1]
          have H_idx : (⟨a.val, by omega⟩ : Fin n) = ⟨j, hj_lt⟩ := by apply Fin.ext; exact ha_eq
          rw [H_idx]
          exact H_le
  have hn : n ≤ n := le_refl n
  rcases H_ind n hn with ⟨P, hP_inj, hP_min⟩
  have hP_bij : Function.Bijective P := by
    refine ⟨hP_inj, ?_⟩
    intro y
    by_contra hy
    have h_not_mem : y ∉ Finset.image P (Finset.univ : Finset (Fin n)) := by
      intro h
      rw [Finset.mem_image] at h
      rcases h with ⟨x, _, hx⟩
      exact hy ⟨x, hx⟩
    have h1 : (Finset.image P (Finset.univ : Finset (Fin n))) ⊂ Finset.univ := by
      rw [Finset.ssubset_iff_subset_ne]
      refine ⟨Finset.subset_univ _, ?_⟩
      intro heq
      rw [heq] at h_not_mem
      exact h_not_mem (Finset.mem_univ y)
    have h2 : (Finset.image P (Finset.univ : Finset (Fin n))).card < (Finset.univ : Finset (Fin n)).card := Finset.card_lt_card h1
    have h3 : (Finset.image P (Finset.univ : Finset (Fin n))).card = n := by
      have : (Finset.image P (Finset.univ : Finset (Fin n))).card = (Finset.univ : Finset (Fin n)).card := Finset.card_image_of_injective _ hP_inj
      rw [this, Finset.card_univ, Fintype.card_fin]
    rw [Finset.card_univ, Fintype.card_fin] at h2
    omega
  use P
  constructor
  · exact hP_bij
  · intro j k h_jk
    have h_not_in_range : ∀ (i : Fin n), i.val < j.val → P k ≠ P i := by
      intro i hi
      have hik : i.val < k.val := by omega
      have h_neq : k ≠ i := by
        intro heq
        rw [heq] at hik
        omega
      intro heq2
      exact h_neq (hP_inj heq2)
    have H_min := hP_min j (P k) h_not_in_range
    have H_idx : (⟨j.val, by omega⟩ : Fin n) = j := by apply Fin.ext; rfl
    rw [H_idx] at H_min
    exact H_min

theorem prove_good_distribution {m n : ℕ} (scores : Fin n → Fin m → ℝ)
    (hm : 1 ≤ m) (hn : 1 ≤ n) (hmn : n < m)
    (h_nonneg : ∀ (p : Fin n) (c : Fin m), 0 ≤ scores p c)
    (R : Fin n → Fin n → Fin m)
    (hR_mono : ∀ p, StrictMono (R p))
    (hR_sum : ∀ p k,
        let I := @Finset.filter (Fin m) (fun c => (∀ (j : Fin n), j < k → R p j < c) ∧ c ≤ R p k) (Classical.decPred _) Finset.univ;
        Finset.sum I (scores p) ≥ 1)
    (P : Fin n → Fin n)
    (hP_bij : Function.Bijective P)
    (hP_le : ∀ j k : Fin n, j < k → R (P j) j ≤ R (P k) j) :
    exists_good_distribution scores :=
by
  classical
  use fun c =>
    let S := Finset.univ.filter (fun j => c ≤ R (P j) j)
    if h : S.Nonempty then P (S.min' h) else P ⟨0, by omega⟩
  intro p
  obtain ⟨k, hk⟩ := hP_bij.2 p
  have H_I_sub : (@Finset.filter (Fin m) (fun c => (∀ (j : Fin n), j < k → R p j < c) ∧ c ≤ R p k) (Classical.decPred _) Finset.univ) ⊆ Finset.univ.filter (fun c => (let S := Finset.univ.filter (fun j => c ≤ R (P j) j); if h : S.Nonempty then P (S.min' h) else P ⟨0, by omega⟩) = p) := by
    intro c hc
    have hc' : c ∈ Finset.univ ∧ ((∀ (j : Fin n), j < k → R p j < c) ∧ c ≤ R p k) :=
      (@Finset.mem_filter (Fin m) (fun c => (∀ (j : Fin n), j < k → R p j < c) ∧ c ≤ R p k) (Classical.decPred _) Finset.univ c).mp hc
    apply Finset.mem_filter.mpr
    refine ⟨hc'.1, ?_⟩
    have h_k_in : k ∈ Finset.univ.filter (fun j => c ≤ R (P j) j) := by
      apply Finset.mem_filter.mpr
      refine ⟨Finset.mem_univ _, ?_⟩
      rw [hk]
      exact hc'.2.2
    have h_nonempty : (Finset.univ.filter (fun j => c ≤ R (P j) j)).Nonempty := ⟨k, h_k_in⟩
    change (if h : (Finset.univ.filter (fun j => c ≤ R (P j) j)).Nonempty then P ((Finset.univ.filter (fun j => c ≤ R (P j) j)).min' h) else P ⟨0, by omega⟩) = p
    rw [dif_pos h_nonempty]
    rw [← hk]
    apply congrArg
    let min_k := (Finset.univ.filter (fun j => c ≤ R (P j) j)).min' h_nonempty
    have h_min_le : min_k ≤ k := Finset.min'_le _ _ h_k_in
    have h_min_eq : min_k = k := by
      by_contra h_neq
      have h_lt : min_k < k := lt_of_le_of_ne h_min_le h_neq
      have h_min_in := Finset.min'_mem _ h_nonempty
      have h_c_le_R : c ≤ R (P min_k) min_k := (Finset.mem_filter.mp h_min_in).2
      have h_R_le : R (P min_k) min_k ≤ R (P k) min_k := hP_le min_k k h_lt
      have h_c_le : c ≤ R p min_k := by
        rw [hk] at h_R_le
        exact le_trans h_c_le_R h_R_le
      have h_lt_c : R p min_k < c := hc'.2.1 min_k h_lt
      exact lt_irrefl c (lt_of_le_of_lt h_c_le h_lt_c)
    exact h_min_eq
  have H_sum_le : Finset.sum (@Finset.filter (Fin m) (fun c => (∀ (j : Fin n), j < k → R p j < c) ∧ c ≤ R p k) (Classical.decPred _) Finset.univ) (fun c => scores p c) ≤ Finset.sum (Finset.univ.filter (fun c => (let S := Finset.univ.filter (fun j => c ≤ R (P j) j); if h : S.Nonempty then P (S.min' h) else P ⟨0, by omega⟩) = p)) (fun c => scores p c) := by
    apply Finset.sum_le_sum_of_subset_of_nonneg H_I_sub
    intro c _ _
    exact h_nonneg p c
  exact le_trans (hR_sum p k) H_sum_le

theorem PBAdvanced030_lt {m n : ℕ} (scores : Fin n → Fin m → ℝ) (hm : 1 ≤ m) (hn : 1 ≤ n)
    (hmn : n < m) (h_nonneg : ∀ (p : Fin n) (c : Fin m), 0 ≤ scores p c)
    (h_part : satisfies_partition_condition scores) :
    exists_good_distribution scores :=
by
  obtain ⟨R, hR_mono, hR_sum⟩ := exists_R_all scores h_part
  obtain ⟨P, hP_bij, hP_le⟩ := greedy_matching_exists R
  exact prove_good_distribution scores hm hn hmn h_nonneg R hR_mono hR_sum P hP_bij hP_le

theorem PBAdvanced030 {m n : ℕ} (scores : Fin n → Fin m → ℝ) (hm : 1 ≤ m) (hn : 1 ≤ n)
    (hmn : n ≤ m) (h_nonneg : ∀ (p : Fin n) (c : Fin m), 0 ≤ scores p c) : satisfies_partition_condition scores →
  exists_good_distribution scores :=
by
  intro h_part
  by_cases h : n = m
  · exact PBAdvanced030_eq scores hm hn h h_nonneg h_part
  · have h_lt : n < m := by omega
    exact PBAdvanced030_lt scores hm hn h_lt h_nonneg h_part
