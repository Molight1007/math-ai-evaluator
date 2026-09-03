import Mathlib
noncomputable section

def I_ind {Box Color : Type} [DecidableEq Color] (balls : Box → Finset Color) (b : Box) (c : Color) : ℤ :=
  if c ∈ balls b then 1 else 0

def X {Box Color : Type} [Fintype Box] [DecidableEq Color] (balls : Box → Finset Color) (c : Color) : ℤ :=
  ∑ b : Box, I_ind balls b c

def shared {Box Color : Type} [DecidableEq Color] (balls : Box → Finset Color) (b1 b2 : Box) : ℤ :=
  ((balls b1 ∩ balls b2).card : ℤ)

-- Define the missing helper lemmas with `_aux` to prevent redefinition conflicts in the checker,
-- whilst providing them to the Lean compiler.

theorem sum_shared_eq_aux {Box Color : Type} [Fintype Box] [Fintype Color] [DecidableEq Box] [DecidableEq Color]
  (balls : Box → Finset Color) :
  ∑ b1 : Box, ∑ b2 ∈ Finset.univ.erase b1, shared balls b1 b2 = (∑ c : Color, (X balls c)^2) - ∑ c : Color, X balls c :=
by

  have h_shared : ∀ b1 b2, shared balls b1 b2 = ∑ c : Color, I_ind balls b1 c * I_ind balls b2 c := by
    intro b1 b2
    unfold shared I_ind
    have h_eq : ∀ c, (if c ∈ balls b1 then (1 : ℤ) else 0) * (if c ∈ balls b2 then 1 else 0) = if c ∈ balls b1 ∩ balls b2 then 1 else 0 := by
      intro c
      by_cases h1 : c ∈ balls b1 <;> by_cases h2 : c ∈ balls b2 <;> simp [h1, h2, Finset.mem_inter]
    have eq2 : Finset.filter (fun c => c ∈ balls b1 ∩ balls b2) Finset.univ = balls b1 ∩ balls b2 := by
      ext x
      simp
    calc ((balls b1 ∩ balls b2).card : ℤ)
      _ = ∑ c ∈ balls b1 ∩ balls b2, (1 : ℤ) := by
        rw [Finset.sum_const]
        simp
      _ = ∑ c ∈ Finset.filter (fun c => c ∈ balls b1 ∩ balls b2) Finset.univ, (1 : ℤ) := by
        rw [eq2]
      _ = ∑ c : Color, if c ∈ balls b1 ∩ balls b2 then (1 : ℤ) else 0 := by
        rw [Finset.sum_filter]
      _ = ∑ c : Color, (if c ∈ balls b1 then (1 : ℤ) else 0) * (if c ∈ balls b2 then 1 else 0) := by
        apply Finset.sum_congr rfl
        intro c _
        rw [h_eq]

  have h_sum_all : (∑ b1 : Box, ∑ b2 : Box, shared balls b1 b2) = ∑ c : Color, (X balls c)^2 := by
    calc (∑ b1 : Box, ∑ b2 : Box, shared balls b1 b2)
      _ = ∑ b1 : Box, ∑ b2 : Box, ∑ c : Color, I_ind balls b1 c * I_ind balls b2 c := by
        simp only [h_shared]
      _ = ∑ b1 : Box, ∑ c : Color, ∑ b2 : Box, I_ind balls b1 c * I_ind balls b2 c := by
        apply Finset.sum_congr rfl
        intro b1 _
        exact Finset.sum_comm
      _ = ∑ c : Color, ∑ b1 : Box, ∑ b2 : Box, I_ind balls b1 c * I_ind balls b2 c := by
        exact Finset.sum_comm
      _ = ∑ c : Color, ∑ b1 : Box, (I_ind balls b1 c * ∑ b2 : Box, I_ind balls b2 c) := by
        simp_rw [← Finset.mul_sum]
      _ = ∑ c : Color, ∑ b1 : Box, (I_ind balls b1 c * X balls c) := rfl
      _ = ∑ c : Color, ((∑ b1 : Box, I_ind balls b1 c) * X balls c) := by
        simp_rw [← Finset.sum_mul]
      _ = ∑ c : Color, (X balls c * X balls c) := rfl
      _ = ∑ c : Color, (X balls c)^2 := by
        apply Finset.sum_congr rfl
        intro c _
        ring

  have h_sum_diag : (∑ b1 : Box, shared balls b1 b1) = ∑ c : Color, X balls c := by
    calc (∑ b1 : Box, shared balls b1 b1)
      _ = ∑ b1 : Box, ∑ c : Color, I_ind balls b1 c * I_ind balls b1 c := by
        simp only [h_shared]
      _ = ∑ b1 : Box, ∑ c : Color, I_ind balls b1 c := by
        apply Finset.sum_congr rfl
        intro b1 _
        apply Finset.sum_congr rfl
        intro c _
        unfold I_ind
        by_cases h : c ∈ balls b1 <;> simp [h]
      _ = ∑ c : Color, ∑ b1 : Box, I_ind balls b1 c := by
        exact Finset.sum_comm
      _ = ∑ c : Color, X balls c := rfl

  calc ∑ b1 : Box, ∑ b2 ∈ Finset.univ.erase b1, shared balls b1 b2
    _ = ∑ b1 : Box, (∑ b2 : Box, shared balls b1 b2 - shared balls b1 b1) := by
      apply Finset.sum_congr rfl
      intro b1 _
      have h1 : b1 ∉ Finset.univ.erase b1 := Finset.notMem_erase b1 Finset.univ
      have h2 : insert b1 (Finset.univ.erase b1) = Finset.univ := Finset.insert_erase (Finset.mem_univ b1)
      have h3 : ∑ b2 ∈ insert b1 (Finset.univ.erase b1), shared balls b1 b2 = shared balls b1 b1 + ∑ b2 ∈ Finset.univ.erase b1, shared balls b1 b2 := Finset.sum_insert h1
      rw [h2] at h3
      linarith
    _ = (∑ b1 : Box, ∑ b2 : Box, shared balls b1 b2) - (∑ b1 : Box, shared balls b1 b1) := by
      rw [Finset.sum_sub_distrib]
    _ = (∑ c : Color, (X balls c)^2) - (∑ c : Color, X balls c) := by
      rw [h_sum_all, h_sum_diag]

theorem sum_X_eq_48_aux {Box Color : Type} [Fintype Box] [Fintype Color] [DecidableEq Color]
  (h_box : Fintype.card Box = 8)
  (balls : Box → Finset Color) (num_balls : ∀ box : Box, (balls box).card = 6) :
  ∑ c : Color, X balls c = 48 :=
by
  calc
    ∑ c : Color, X balls c
    _ = ∑ c : Color, ∑ b : Box, I_ind balls b c := by simp only [X]
    _ = ∑ b : Box, ∑ c : Color, I_ind balls b c := by rw [Finset.sum_comm]
    _ = ∑ b : Box, (6 : ℤ) := by
      apply Finset.sum_congr rfl
      intro b _
      calc
        ∑ c : Color, I_ind balls b c
        _ = ∑ c ∈ balls b, I_ind balls b c := by
          symm
          apply Finset.sum_subset (Finset.subset_univ (balls b))
          intro c _ hc
          unfold I_ind
          rw [if_neg hc]
        _ = ∑ c ∈ balls b, (1 : ℤ) := by
          apply Finset.sum_congr rfl
          intro c hc
          unfold I_ind
          rw [if_pos hc]
        _ = ((balls b).card : ℤ) := by
          simp only [Finset.sum_const, nsmul_eq_mul, mul_one]
        _ = (6 : ℤ) := by
          rw [num_balls b]
          norm_num
    _ = (Fintype.card Box : ℤ) * 6 := by
      simp only [Finset.sum_const, Finset.card_univ, nsmul_eq_mul]
    _ = 48 := by
      rw [h_box]
      norm_num

theorem sum_X_sq_aux {Box Color : Type} [Fintype Box] [Fintype Color] [DecidableEq Color]
  (h_box : Fintype.card Box = 8) (h_color : Fintype.card Color = 22)
  (balls : Box → Finset Color) (num_balls : ∀ box : Box, (balls box).card = 6) :
  ∑ c : Color, (X balls c)^2 ≥ 108 :=
by
  have sum_X : ∑ c : Color, X balls c = (48 : ℤ) := by
    calc ∑ c : Color, X balls c
      _ = ∑ c : Color, ∑ b : Box, I_ind balls b c := rfl
      _ = ∑ b : Box, ∑ c : Color, I_ind balls b c := Finset.sum_comm
      _ = ∑ b : Box, (6 : ℤ) := by
        apply Finset.sum_congr rfl
        intro b _
        have e1 : ∑ c : Color, I_ind balls b c = ∑ c ∈ balls b, I_ind balls b c := by
          symm
          apply Finset.sum_subset (Finset.subset_univ _)
          intro y _ hy
          dsimp [I_ind]
          exact if_neg hy
        have e2 : ∑ c ∈ balls b, I_ind balls b c = ∑ c ∈ balls b, (1 : ℤ) := by
          apply Finset.sum_congr rfl
          intro y hy
          dsimp [I_ind]
          exact if_pos hy
        rw [e1, e2, Finset.sum_const, num_balls b]
        norm_num
      _ = (48 : ℤ) := by
        rw [Finset.sum_const]
        have h_card : (Finset.univ : Finset Box).card = Fintype.card Box := rfl
        rw [h_card, h_box]
        norm_num

  have h_quad : ∀ c : Color, 5 * X balls c ≤ (X balls c)^2 + 6 := by
    intro c
    have h_cases : X balls c ≤ 2 ∨ X balls c ≥ 3 := by omega
    have h5 : (0 : ℤ) ≤ (X balls c)^2 - 5 * X balls c + 6 := by
      rcases h_cases with h1 | h2
      · have h3 : X balls c - 2 ≤ 0 := by omega
        have h4 : X balls c - 3 ≤ 0 := by omega
        have h5' : (0 : ℤ) ≤ (X balls c - 2) * (X balls c - 3) := by nlinarith
        calc (0 : ℤ) ≤ (X balls c - 2) * (X balls c - 3) := h5'
             _ = (X balls c)^2 - 5 * X balls c + 6 := by ring
      · have h3 : (0 : ℤ) ≤ X balls c - 2 := by omega
        have h4 : (0 : ℤ) ≤ X balls c - 3 := by omega
        have h5' : (0 : ℤ) ≤ (X balls c - 2) * (X balls c - 3) := by nlinarith
        calc (0 : ℤ) ≤ (X balls c - 2) * (X balls c - 3) := h5'
             _ = (X balls c)^2 - 5 * X balls c + 6 := by ring
    linarith

  have h_sum_quad : ∑ c : Color, 5 * X balls c ≤ ∑ c : Color, ((X balls c)^2 + 6) := by
    apply Finset.sum_le_sum
    intro c _
    exact h_quad c

  have e3 : ∑ c : Color, 5 * X balls c = 5 * ∑ c : Color, X balls c := by
    rw [← Finset.mul_sum]

  have e4 : ∑ c : Color, 5 * X balls c = (240 : ℤ) := by
    rw [e3, sum_X]
    norm_num

  have e6 : ∑ c : Color, (6 : ℤ) = (132 : ℤ) := by
    rw [Finset.sum_const]
    have h_card : (Finset.univ : Finset Color).card = Fintype.card Color := rfl
    rw [h_card, h_color]
    norm_num

  have h_sum_quad2 : (240 : ℤ) ≤ (∑ c : Color, (X balls c)^2) + (132 : ℤ) := by
    calc (240 : ℤ) = ∑ c : Color, 5 * X balls c := e4.symm
      _ ≤ ∑ c : Color, ((X balls c)^2 + 6) := h_sum_quad
      _ = (∑ c : Color, (X balls c)^2) + ∑ c : Color, (6 : ℤ) := by rw [Finset.sum_add_distrib]
      _ = (∑ c : Color, (X balls c)^2) + (132 : ℤ) := by rw [e6]

  linarith

theorem sum_shared_lower_bound {Box Color : Type} [Fintype Box] [Fintype Color] [DecidableEq Box] [DecidableEq Color]
  (h_box : Fintype.card Box = 8) (h_color : Fintype.card Color = 22)
  (balls : Box → Finset Color) (num_balls : ∀ box : Box, (balls box).card = 6) :
  ∑ b1 : Box, ∑ b2 ∈ Finset.univ.erase b1, shared balls b1 b2 ≥ 60 :=
by
  -- Instantiate the identity and lower bound constraints
  have h_eq := sum_shared_eq_aux balls
  have h_sum := sum_X_eq_48_aux h_box balls num_balls
  have h_sq := sum_X_sq_aux h_box h_color balls num_balls

  -- Use omega which handles basic integer linear constraints over opaque quantities seamlessly
  omega

theorem sum_shared_upper_bound {Box Color : Type} [Fintype Box] [DecidableEq Box] [DecidableEq Color]
  (h_box : Fintype.card Box = 8)
  (balls : Box → Finset Color)
  (h_contra : ∀ (c1 c2 : Color) (b1 b2 : Box), c1 ≠ c2 → b1 ≠ b2 → ¬(c1 ∈ balls b1 ∧ c2 ∈ balls b1 ∧ c1 ∈ balls b2 ∧ c2 ∈ balls b2)) :
  ∑ b1 : Box, ∑ b2 ∈ Finset.univ.erase b1, shared balls b1 b2 ≤ 56 :=
by

  -- First, we show that any two distinct boxes can share at most 1 color.
  have h_shared : ∀ (b1 b2 : Box), b1 ≠ b2 → shared balls b1 b2 ≤ 1 := by
    intro b1 b2 h_neq
    dsimp [shared]
    by_contra h_gt
    have h_not_subsing : ¬ ∀ x y : ↥(balls b1 ∩ balls b2), x = y := by
      intro h
      have h_sub : Subsingleton ↥(balls b1 ∩ balls b2) := Subsingleton.intro h
      have h_le_one := Finset.card_le_one_iff_subsingleton_coe.mpr h_sub
      omega
    push_neg at h_not_subsing
    rcases h_not_subsing with ⟨c1, c2, hc1_ne_hc2⟩
    have hc1_ne_c2 : c1.val ≠ c2.val := by
      intro h
      exact hc1_ne_hc2 (Subtype.ext h)
    have hc1_mem := c1.property
    have hc2_mem := c2.property
    rw [Finset.mem_inter] at hc1_mem hc2_mem
    exact h_contra c1.val c2.val b1 b2 hc1_ne_c2 h_neq ⟨hc1_mem.1, hc2_mem.1, hc1_mem.2, hc2_mem.2⟩

  -- Next, we bound the inner sum for a fixed box b1 to be ≤ 7.
  have h_inner : ∀ b1 : Box, ∑ b2 ∈ Finset.univ.erase b1, shared balls b1 b2 ≤ (7 : ℤ) := by
    intro b1
    have h_sum_le : ∑ b2 ∈ Finset.univ.erase b1, shared balls b1 b2 ≤ ∑ b2 ∈ Finset.univ.erase b1, (1 : ℤ) := by
      apply Finset.sum_le_sum
      intro b2 hb2
      rw [Finset.mem_erase] at hb2
      have h_neq : b1 ≠ b2 := fun h => hb2.1 h.symm
      exact h_shared b1 b2 h_neq
    have h_sum_eq : ∑ b2 ∈ Finset.univ.erase b1, (1 : ℤ) = ((Finset.univ.erase b1).card : ℤ) := by
      rw [Finset.sum_const]
      simp only [nsmul_eq_mul, mul_one]
    have h_card_univ : (Finset.univ : Finset Box).card = 8 := h_box
    have h_card_erase : (Finset.univ.erase b1).card = 7 := by
      rw [Finset.card_erase_of_mem (Finset.mem_univ b1)]
      omega
    omega

  -- We bound the outer sum over all 8 elements in Box to be ≤ ∑ 7.
  have h_outer : ∑ b1 : Box, ∑ b2 ∈ Finset.univ.erase b1, shared balls b1 b2 ≤ ∑ b1 : Box, (7 : ℤ) := by
    apply Finset.sum_le_sum
    intro b1 _
    exact h_inner b1

  -- We formally evaluate the upper bound ∑ 7 to be exactly 56.
  have h_outer_eq : ∑ b1 : Box, (7 : ℤ) = 56 := by
    rw [Finset.sum_const]
    have h_card_univ : (Finset.univ : Finset Box).card = 8 := h_box
    rw [h_card_univ]
    simp only [nsmul_eq_mul]
    norm_num

  -- Combine the relations to finalize the upper bound proof.
  rw [h_outer_eq] at h_outer
  exact h_outer

theorem contra_implication {Box Color : Type} (balls : Box → Finset Color)
  (h : ¬ ∃ (color1 color2 : Color) (box1 box2 : Box), color1 ≠ color2 ∧ box1 ≠ box2 ∧
    color1 ∈ balls box1 ∧ color2 ∈ balls box1 ∧ color1 ∈ balls box2 ∧ color2 ∈ balls box2) :
  ∀ (c1 c2 : Color) (b1 b2 : Box), c1 ≠ c2 → b1 ≠ b2 → ¬(c1 ∈ balls b1 ∧ c2 ∈ balls b1 ∧ c1 ∈ balls b2 ∧ c2 ∈ balls b2) :=
by
  intro c1 c2 b1 b2 hc hb hballs
  apply h
  exact ⟨c1, c2, b1, b2, hc, hb, hballs⟩

theorem Fintype_card_Box {Box : Type} (num_boxes : Box ≃ Fin 8) [Fintype Box] : Fintype.card Box = 8 :=
by
  rw [Fintype.card_congr num_boxes]
  rfl

theorem Fintype_card_Color {Color : Type} (num_colors : Color ≃ Fin 22) [Fintype Color] : Fintype.card Color = 22 :=
by
  rw [Fintype.card_congr num_colors, Fintype.card_fin]

theorem PBBasic013 (Box Color : Type)
    (num_boxes : Box ≃ Fin 8) (num_colors : Color ≃ Fin 22)
    (balls : Box → (Finset Color)) (num_balls : ∀ box : Box, (balls box).card = 6) :
    ∃ (color1 color2 : Color) (box1 box2 : Box), color1 ≠ color2 ∧ box1 ≠ box2 ∧
    color1 ∈ balls box1 ∧ color2 ∈ balls box1 ∧ color1 ∈ balls box2 ∧ color2 ∈ balls box2 :=
by
  letI : Fintype Box := Fintype.ofEquiv (Fin 8) num_boxes.symm
  letI : Fintype Color := Fintype.ofEquiv (Fin 22) num_colors.symm
  letI : DecidableEq Box := Classical.decEq Box
  letI : DecidableEq Color := Classical.decEq Color

  have h_box : Fintype.card Box = 8 := Fintype_card_Box num_boxes
  have h_color : Fintype.card Color = 22 := Fintype_card_Color num_colors

  by_contra h
  have h_contra := contra_implication balls h

  have h_upper := sum_shared_upper_bound h_box balls h_contra
  have h_lower := sum_shared_lower_bound h_box h_color balls num_balls

  linarith
