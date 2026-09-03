import Mathlib

open Affine
open Simplex
open EuclideanGeometry
local notation "ℝ²" => EuclideanSpace ℝ (Fin 2)

theorem cospherical_def' {s : Set ℝ²} (h : Cospherical s) : ∃ (O : ℝ²) (R : ℝ), ∀ p ∈ s, ‖p - O‖ = R :=
by
  rcases (cospherical_def s).mp h with ⟨O, R, hR⟩
  use O, R
  intro p hp
  rw [← dist_eq_norm p O, hR p hp]

theorem power_of_point_span {A B C O : ℝ²} {R : ℝ}
    (hA : ‖A - O‖ = R) (hB : ‖B - O‖ = R)
    (hC : C ∈ affineSpan ℝ ({A, B} : Set ℝ²)) :
    inner ℝ (A - C) (B - C) = ‖C - O‖^2 - R^2 :=
by
  obtain ⟨t, ht⟩ := mem_affineSpan_pair_iff_exists_lineMap_eq.mp hC

  have hC_eq : C = t • (B - A) + A := ht.symm

  have hAC : A - C = -(t • (B - A)) := by
    calc A - C = A - (t • (B - A) + A) := by rw [hC_eq]
         _ = -(t • (B - A)) := by abel

  have hBC : B - C = (1 - t) • (B - A) := by
    calc B - C = B - (t • (B - A) + A) := by rw [hC_eq]
         _ = B - A - t • (B - A) := by abel
         _ = (1 - t) • (B - A) := by rw [sub_smul, one_smul]

  have hBA : B - A = (B - O) - (A - O) := by abel

  have hCO : C - O = t • ((B - O) - (A - O)) + (A - O) := by
    calc C - O = t • (B - A) + A - O := by rw [hC_eq]
         _ = t • ((B - O) - (A - O)) + A - O := by rw [hBA]
         _ = t • ((B - O) - (A - O)) + (A - O) := by abel

  have H2 : ‖C - O‖ ^ 2 = inner ℝ (C - O) (C - O) :=
    (real_inner_self_eq_norm_sq (C - O)).symm

  have H3 : inner ℝ (A - O) (A - O) = R ^ 2 := by
    calc inner ℝ (A - O) (A - O) = ‖A - O‖ ^ 2 := real_inner_self_eq_norm_sq (A - O)
         _ = R ^ 2 := by rw [hA]

  have H4 : inner ℝ (B - O) (B - O) = R ^ 2 := by
    calc inner ℝ (B - O) (B - O) = ‖B - O‖ ^ 2 := real_inner_self_eq_norm_sq (B - O)
         _ = R ^ 2 := by rw [hB]

  -- Subtitute equivalent expressions up to this point
  rw [hAC, hBC, H2, hCO, hBA]

  -- Temporarily revert hypotheses that depend on A - O and B - O to safely swap the terms
  revert H3 H4
  generalize hd1 : A - O = a
  generalize hd2 : B - O = b
  intro hx hy

  -- Now simplify freely, letting the expansion rule only process `a` and `b` holistically.
  simp only [inner_add_left, inner_add_right, inner_sub_left, inner_sub_right,
    inner_smul_left, inner_smul_right, real_inner_smul_left, real_inner_smul_right,
    inner_neg_left, inner_neg_right, starRingEnd_apply, star_trivial, RCLike.star_def]

  -- Rewrite squared radii magnitudes correctly
  rw [hx, hy, real_inner_comm b a]

  -- Offload pure polynomial calculation over ℝ to the ring automation
  ring

theorem altitudeFoot_two_eq (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C]) :
    altitudeFoot ⟨![A, B, C], tri⟩ 2 = ↑(orthogonalProjection (affineSpan ℝ ({A, B} : Set ℝ²)) C) :=
by
  -- Explicitly prove the image of the opposite face's points is exactly {A, B}
  have h_img : Set.range ((⟨![A, B, C], tri⟩ : Affine.Simplex ℝ ℝ² 2).faceOpposite 2).points = ({A, B} : Set ℝ²) := by
    ext x
    simp only [Set.mem_range, Set.mem_insert_iff, Set.mem_singleton_iff]
    constructor
    · rintro ⟨y, rfl⟩
      -- Prove y evaluates safely over Nat ranges to cleanly exhaust Fin 2 without definitional clashes
      have hy_cases : y = 0 ∨ y = 1 := by
        have : y.val = 0 ∨ y.val = 1 := by omega
        rcases this with h0 | h1
        · left; apply Fin.ext; exact h0
        · right; apply Fin.ext; exact h1
      rcases hy_cases with rfl | rfl
      · left
        rw [Affine.Simplex.faceOpposite_point_eq_point_succAbove]
        have h_idx : ∀ h, Fin.succAbove (2 : Fin 3) (Fin.cast h (0 : Fin (2 - 1 + 1))) = 0 := by intro h; apply Fin.ext; rfl
        rw [h_idx]
        rfl
      · right
        rw [Affine.Simplex.faceOpposite_point_eq_point_succAbove]
        have h_idx : ∀ h, Fin.succAbove (2 : Fin 3) (Fin.cast h (1 : Fin (2 - 1 + 1))) = 1 := by intro h; apply Fin.ext; rfl
        rw [h_idx]
        rfl
    · rintro (rfl | rfl)
      · exact ⟨0, by
          rw [Affine.Simplex.faceOpposite_point_eq_point_succAbove]
          have h_idx : ∀ h, Fin.succAbove (2 : Fin 3) (Fin.cast h (0 : Fin (2 - 1 + 1))) = 0 := by intro h; apply Fin.ext; rfl
          rw [h_idx]
          rfl⟩
      · exact ⟨1, by
          rw [Affine.Simplex.faceOpposite_point_eq_point_succAbove]
          have h_idx : ∀ h, Fin.succAbove (2 : Fin 3) (Fin.cast h (1 : Fin (2 - 1 + 1))) = 1 := by intro h; apply Fin.ext; rfl
          rw [h_idx]
          rfl⟩

  -- Unfold the geometric projections cleanly simplifying dependent coercions iteratively
  dsimp [altitudeFoot, Affine.Simplex.orthogonalProjectionSpan]
  -- Resolve the geometric target spanning through the established set equivalence
  simp only [h_img]

theorem B_ne_C (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C]) : B ≠ C :=
by
  intro h
  have h_inj := AffineIndependent.injective tri
  have h_eq : ![A, B, C] 1 = ![A, B, C] 2 := h
  have h12 : (1 : Fin 3) = (2 : Fin 3) := h_inj h_eq
  revert h12
  decide

theorem orthocenter_inner_eq_zero (A B C H : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (hH : H = Triangle.orthocenter ⟨![A, B, C], tri⟩) :
    inner ℝ (H - A) (B - C) = (0 : ℝ) :=
by
  let T : Affine.Triangle ℝ ℝ² := ⟨![A, B, C], tri⟩
  let O := T.circumcenter
  have h_sum := Affine.Triangle.orthocenter_vsub_circumcenter_eq_sum_vsub T

  have h_sum_eval : ∑ i : Fin 3, (![A, B, C] i - O) = (A - O) + ((B - O) + (C - O)) := by
    rw [Fin.sum_univ_succ, Fin.sum_univ_succ, Fin.sum_univ_succ]
    rw [Fin.sum_univ_zero, add_zero]
    rfl

  have h_sum' : H - O = ∑ i : Fin 3, (![A, B, C] i - O) := by
    calc H - O = H -ᵥ O := rfl
      _ = (Triangle.orthocenter ⟨![A, B, C], tri⟩) -ᵥ O := by rw [hH]
      _ = T.orthocenter -ᵥ T.circumcenter := rfl
      _ = ∑ i : Fin 3, (T.points i -ᵥ T.circumcenter) := h_sum
      _ = ∑ i : Fin 3, (![A, B, C] i - O) := rfl

  have h_ortho2 : H - O = (A - O) + (B - O) + (C - O) := by
    calc H - O = ∑ i : Fin 3, (![A, B, C] i - O) := h_sum'
      _ = (A - O) + ((B - O) + (C - O)) := h_sum_eval
      _ = (A - O) + (B - O) + (C - O) := by rw [← add_assoc]

  have hHA : H - A = (B - O) + (C - O) := by
    calc H - A = (H - O) - (A - O) := by abel
      _ = (A - O) + (B - O) + (C - O) - (A - O) := by rw [h_ortho2]
      _ = (B - O) + (C - O) := by abel

  have hBC : B - C = (B - O) - (C - O) := by abel

  have h_inner : inner ℝ (H - A) (B - C) = inner ℝ (B - O) (B - O) - inner ℝ (C - O) (C - O) := by
    rw [hHA, hBC]
    generalize hU : B - O = U
    generalize hV : C - O = V
    simp only [inner_add_left, inner_sub_right]
    rw [← real_inner_comm U V]
    ring

  have hd1 := Affine.Simplex.dist_circumcenter_eq_circumradius T 1
  change dist B O = T.circumradius at hd1

  have hd2 := Affine.Simplex.dist_circumcenter_eq_circumradius T 2
  change dist C O = T.circumradius at hd2

  have h_dist_eq : dist B O = dist C O := hd1.trans hd2.symm

  have hB2 : inner ℝ (B - O) (B - O) = dist B O ^ 2 := by
    rw [real_inner_self_eq_norm_sq]
    rw [← dist_eq_norm B O]

  have hC2 : inner ℝ (C - O) (C - O) = dist C O ^ 2 := by
    rw [real_inner_self_eq_norm_sq]
    rw [← dist_eq_norm C O]

  rw [h_inner, hB2, hC2, h_dist_eq, sub_self]

theorem proj_inner_eq_zero (A B C D : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    inner ℝ (A - D) (B - C) = (0 : ℝ) :=
by
  have hB : B ∈ affineSpan ℝ ({B, C} : Set ℝ²) := mem_affineSpan ℝ (by simp)
  have hC : C ∈ affineSpan ℝ ({B, C} : Set ℝ²) := mem_affineSpan ℝ (by simp)
  haveI : Nonempty (affineSpan ℝ ({B, C} : Set ℝ²)) := ⟨⟨B, hB⟩⟩
  have h_ortho := EuclideanGeometry.vsub_orthogonalProjection_mem_direction_orthogonal (affineSpan ℝ ({B, C} : Set ℝ²)) A
  have h_vsub : B -ᵥ C ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).direction := AffineSubspace.vsub_mem_direction hB hC
  rw [← hD] at h_ortho
  have h_inner := (Submodule.mem_orthogonal' (affineSpan ℝ ({B, C} : Set ℝ²)).direction (A -ᵥ D)).mp h_ortho (B -ᵥ C) h_vsub
  change inner ℝ (A - D) (B - C) = (0 : ℝ) at h_inner
  exact h_inner

theorem inner_H_D_B_C_eq_zero (A B C D H : ℝ²)
    (h1 : inner ℝ (H - A) (B - C) = (0 : ℝ))
    (h2 : inner ℝ (A - D) (B - C) = (0 : ℝ)) :
    inner ℝ (H - D) (B - C) = (0 : ℝ) :=
by
  have h : H - D = (H - A) + (A - D) := by abel
  rw [h, inner_add_left, h1, h2, add_zero]


theorem D_mem_span_B_C (A B C D : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    D ∈ affineSpan ℝ ({B, C} : Set ℝ²) :=
by
  rw [hD]
  exact SetLike.coe_mem _

theorem proj_eq_of_inner_eq_zero (B C H D : ℝ²) (hBC : B ≠ C)
    (hD_span : D ∈ affineSpan ℝ ({B, C} : Set ℝ²))
    (h_inner : inner ℝ (H - D) (B - C) = (0 : ℝ)) :
    D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) H) :=
by
  -- Provide the Nonempty instance for the affine span, as it's required for the projection lemmas
  have h_nonempty : Nonempty ↥(affineSpan ℝ ({B, C} : Set ℝ²)) := ⟨⟨D, hD_span⟩⟩

  -- Transform the goal into showing that D is in the span and H - D is orthogonal to its direction
  rw [eq_comm, EuclideanGeometry.coe_orthogonalProjection_eq_iff_mem]
  refine ⟨hD_span, ?_⟩

  -- Explicitly construct the target affine subspace to extract its direction
  let S : AffineSubspace ℝ ℝ² := AffineSubspace.mk' C (Submodule.span ℝ {B - C})

  have hB : B ∈ S := by
    -- Deleted the rw! Lean 4 knows B ∈ S is definitionally B - C ∈ Submodule
    change B - C ∈ Submodule.span ℝ {B - C}
    exact Submodule.subset_span (Set.mem_singleton (B - C))

  have hC : C ∈ S := by
    -- Deleted the rw here too!
    change C - C ∈ Submodule.span ℝ {B - C}
    rw [sub_self]
    exact Submodule.zero_mem _

  have h_sub : {B, C} ⊆ (S : Set ℝ²) := by
    intro x hx
    rcases hx with rfl | rfl
    · exact hB
    · exact hC

  -- Bound the direction of the affine span of {B, C} by the direction of S
  have H_le : affineSpan ℝ ({B, C} : Set ℝ²) ≤ S := by
    first | exact affineSpan_le.mpr h_sub | exact sInf_le h_sub
  have H_dir_le : (affineSpan ℝ ({B, C} : Set ℝ²)).direction ≤ S.direction :=
    AffineSubspace.direction_le H_le
  rw [AffineSubspace.direction_mk'] at H_dir_le

  -- Prove that H - D is orthogonal to any vector in the direction of the affine span
  rw [Submodule.mem_orthogonal]
  intro x hx
  have hx_span : x ∈ Submodule.span ℝ {B - C} := H_dir_le hx
  rw [Submodule.mem_span_singleton] at hx_span
  rcases hx_span with ⟨c, rfl⟩

  -- Calculate the inner product to be 0
  have h1 : inner ℝ (H - D) (c • (B - C)) = (0 : ℝ) := by
    rw [inner_smul_right, h_inner]
    simp
  have h2 : inner ℝ (c • (B - C)) (H - D) = (0 : ℝ) := by
    first | rw [real_inner_comm, h1] | { rw [inner_comm]; simp [h1] }

  -- Resolve the orthogonal goal regardless of which side the vector is applied in the library
  first | exact h1 | exact h2

theorem orthocenter_proj_eq (A B C H D : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (hH : H = Triangle.orthocenter ⟨![A, B, C], tri⟩)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) H) :=
by
  have hBC : B ≠ C := B_ne_C A B C tri
  have hD_span : D ∈ affineSpan ℝ ({B, C} : Set ℝ²) := D_mem_span_B_C A B C D hD
  have h1 : inner ℝ (H - A) (B - C) = (0 : ℝ) := orthocenter_inner_eq_zero A B C H tri hH
  have h2 : inner ℝ (A - D) (B - C) = (0 : ℝ) := proj_inner_eq_zero A B C D hD
  have h3 : inner ℝ (H - D) (B - C) = (0 : ℝ) := inner_H_D_B_C_eq_zero A B C D H h1 h2
  exact proj_eq_of_inner_eq_zero B C H D hBC hD_span h3

theorem reflection_eq_sub (B C H D P : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) H))
    (hP : P = reflection (affineSpan ℝ ({B, C} : Set ℝ²)) H) :
    P - D = -(H - D) :=
by
  -- Show that the affine span is nonempty because it contains B
  have hB : B ∈ ({B, C} : Set ℝ²) := by simp
  have hB_in : B ∈ affineSpan ℝ ({B, C} : Set ℝ²) := subset_affineSpan ℝ ({B, C} : Set ℝ²) hB
  haveI : Nonempty ↥(affineSpan ℝ ({B, C} : Set ℝ²)) := ⟨⟨B, hB_in⟩⟩

  -- Rewrite P using the explicitly projected geometric definition of a reflection
  rw [hP, EuclideanGeometry.reflection_apply']

  -- Substitute the orthogonal projection term with D
  rw [← hD]

  -- Convert affine vector additions (+ᵥ) and subtractions (-ᵥ) into standard module operations (+, -)
  -- Since ℝ² is a vector space, affine vector operations are definitionally just addition and subtraction.
  change ((D - H) + D) - D = -(H - D)

  -- Resolve the linear arithmetic relation
  abel

theorem inner_A_D_P_D (A H D P : ℝ²) (hP : P - D = -(H - D)) :
    inner ℝ (A - D) (P - D) = -inner ℝ (A - D) (H - D) :=
by
  rw [hP, inner_neg_right]

theorem inner_A_D_C_D_eq_zero (A B C D : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    inner ℝ (A - D) (C - D) = 0 :=
by
  have hC_mem : C ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
    apply mem_affineSpan
    exact Or.inr rfl

  have hD_mem : D ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
    rw [hD]
    exact SetLike.coe_mem (orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)

  have hCD_dir : C - D ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).direction := by
    exact (AffineSubspace.vsub_left_mem_direction_iff_mem hC_mem D).mpr hD_mem

  have h_proj : D = ↑((affineSpan ℝ ({B, C} : Set ℝ²)).direction.orthogonalProjection (A - C)) + C := by
    have h_apply := EuclideanGeometry.orthogonalProjection_apply_mem (affineSpan ℝ ({B, C} : Set ℝ²)) hC_mem (p := A) (x := C)
    rw [← hD] at h_apply
    exact h_apply

  have hAD : A - D = A - C - (affineSpan ℝ ({B, C} : Set ℝ²)).direction.orthogonalProjectionFn (A - C) := by
    change A - D = A - C - ↑((affineSpan ℝ ({B, C} : Set ℝ²)).direction.orthogonalProjection (A - C))
    rw [h_proj, sub_add_eq_sub_sub, sub_right_comm]

  rw [hAD]
  exact Submodule.orthogonalProjectionFn_inner_eq_zero (A - C) (C - D) hCD_dir

theorem inner_H_D_B_D_eq_zero (B C H D : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) H)) :
    inner ℝ (B - D) (H - D) = 0 :=
by
  let S := affineSpan ℝ ({B, C} : Set ℝ²)
  have hD_S : D = ↑(orthogonalProjection S H) := hD
  have hB_mem : B ∈ ({B, C} : Set ℝ²) := Set.mem_insert B {C}
  have hB : B ∈ S := mem_affineSpan ℝ hB_mem
  have hD_mem : D ∈ S := by
    rw [hD_S]
    first
    | exact (orthogonalProjection S H).property
    | exact Subtype.mem (orthogonalProjection S H)
    | exact SetLike.coe_mem (orthogonalProjection S H)
  have hBD : B - D ∈ S.direction := by
    have h_vsub := AffineSubspace.vsub_mem_direction hB hD_mem
    first | exact h_vsub | rw [vsub_eq_sub] at h_vsub; exact h_vsub
  have h_ortho : H - D ∈ S.directionᗮ := by
    first
    | have h1 := orthogonalProjection_vsub_mem_direction_orthogonal S H
      first | rw [vsub_eq_sub] at h1 | change ↑(orthogonalProjection S H) - H ∈ S.directionᗮ at h1
      rw [← hD_S] at h1
      have h2 : -(D - H) ∈ S.directionᗮ := by
        first | exact Submodule.neg_mem _ h1 | exact neg_mem h1
      rw [neg_sub] at h2
      exact h2
    | have h1 := vsub_orthogonalProjection_mem_direction_orthogonal S H
      first | rw [vsub_eq_sub] at h1 | change H - ↑(orthogonalProjection S H) ∈ S.directionᗮ at h1
      rw [← hD_S] at h1
      exact h1
  first
  | rw [Submodule.mem_orthogonal] at h_ortho
    have h_inner := h_ortho (B - D) hBD
    first | exact h_inner | rw [real_inner_comm] at h_inner; exact h_inner
  | rw [Submodule.mem_orthogonal'] at h_ortho
    have h_inner := h_ortho (B - D) hBD
    first | exact h_inner | rw [real_inner_comm] at h_inner; exact h_inner
  | have h_inner := h_ortho (B - D) hBD
    first | exact h_inner | rw [real_inner_comm] at h_inner; exact h_inner

theorem orthocenter_inner_B_sub_A_C_sub_H_eq_zero (A B C H : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (hH : H = Triangle.orthocenter ⟨![A, B, C], tri⟩) :
    inner ℝ (B - A) (C - H) = 0 :=
by
  let t : Affine.Triangle ℝ ℝ² := ⟨![A, B, C], tri⟩
  let O := Affine.Simplex.circumcenter t

  have h2 : H - O = (A - O) + (B - O) + (C - O) := by
    have h_sum := Affine.Triangle.orthocenter_vsub_circumcenter_eq_sum_vsub t
    rw [← hH] at h_sum
    have h_sum2 : ∑ i, (t.points i -ᵥ O) = (A -ᵥ O) + (B -ᵥ O) + (C -ᵥ O) := by
      have p0 : t.points 0 = A := rfl
      have p1 : t.points 1 = B := rfl
      have p2 : t.points 2 = C := rfl
      calc ∑ i, (t.points i -ᵥ O) = (t.points 0 -ᵥ O) + (t.points 1 -ᵥ O) + (t.points 2 -ᵥ O) := Fin.sum_univ_three _
           _ = (A -ᵥ O) + (B -ᵥ O) + (C -ᵥ O) := by rw [p0, p1, p2]
    rw [h_sum2] at h_sum
    simp only [vsub_eq_sub] at h_sum
    exact h_sum

  have dAB : dist A O = dist B O := by
    have h0 := t.dist_circumcenter_eq_circumradius 0
    have h1 := t.dist_circumcenter_eq_circumradius 1
    have p0 : t.points 0 = A := rfl
    have p1 : t.points 1 = B := rfl
    rw [p0] at h0
    rw [p1] at h1
    have dA : dist A O = t.circumradius := by
      first | exact h0 | (rw [dist_comm]; exact h0)
    have dB : dist B O = t.circumradius := by
      first | exact h1 | (rw [dist_comm]; exact h1)
    rw [dA, dB]

  have nAB : ‖A - O‖ = ‖B - O‖ := by
    calc ‖A - O‖ = dist A O := (dist_eq_norm A O).symm
         _       = dist B O := dAB
         _       = ‖B - O‖ := dist_eq_norm B O

  have h_inner : inner ℝ (B - O) (B - O) = inner ℝ (A - O) (A - O) := by
    rw [real_inner_self_eq_norm_sq, real_inner_self_eq_norm_sq, nAB]

  have e1 : B - A = (B - O) - (A - O) := by abel
  have e2 : C - H = - (B - O) - (A - O) := by
    calc C - H = (C - O) - (H - O) := by abel
         _ = (C - O) - ((A - O) + (B - O) + (C - O)) := by rw [h2]
         _ = - (B - O) - (A - O) := by abel

  rw [e1, e2]
  -- Generalize B - O and A - O into individual units to prevent misfiring of `inner_sub_right` and simplify reading
  generalize hu : B - O = u at h_inner ⊢
  generalize hv : A - O = v at h_inner ⊢

  calc inner ℝ (u - v) (-u - v) = inner ℝ u (-u - v) - inner ℝ v (-u - v) := by rw [inner_sub_left]
    _ = (inner ℝ u (-u) - inner ℝ u v) - (inner ℝ v (-u) - inner ℝ v v) := by rw [inner_sub_right, inner_sub_right]
    _ = (-inner ℝ u u - inner ℝ u v) - (-inner ℝ v u - inner ℝ v v) := by rw [inner_neg_right, inner_neg_right]
    _ = -inner ℝ u u - inner ℝ u v + inner ℝ v u + inner ℝ v v := by ring
    _ = -inner ℝ u u - inner ℝ u v + inner ℝ u v + inner ℝ v v := by rw [real_inner_comm v u]
    _ = -inner ℝ u u + inner ℝ v v := by ring
    _ = -inner ℝ v v + inner ℝ v v := by rw [h_inner]
    _ = 0 := by ring

theorem inner_B_D_C_D_algebra (A B C H D : ℝ²)
    (h_ortho : inner ℝ (B - A) (C - H) = 0)
    (h_AD_CD : inner ℝ (A - D) (C - D) = 0)
    (h_BD_HD : inner ℝ (B - D) (H - D) = 0) :
    inner ℝ (B - D) (C - D) = -inner ℝ (A - D) (H - D) :=
by
  have h1 : B - A = (B - D) - (A - D) := by abel
  have h2 : C - H = (C - D) - (H - D) := by abel
  have h3 : inner ℝ ((B - D) - (A - D)) ((C - D) - (H - D)) = 0 := by
    rw [← h1, ← h2]
    exact h_ortho

  -- We establish an independent expansion lemma to prevent `rw` from looking inside our desired sub-expressions
  have h4 : ∀ (x y z w : ℝ²), inner ℝ (x - y) (z - w) = inner ℝ x z - inner ℝ x w - inner ℝ y z + inner ℝ y w := by
    intro x y z w
    rw [inner_sub_left, inner_sub_right, inner_sub_right]
    ring

  -- Now we confidently rewrite using `h4` while leaving the inner variables intact
  rw [h4] at h3

  -- The expression now flawlessly fits our remaining hypotheses
  rw [h_AD_CD, h_BD_HD] at h3

  -- Real arithmetic wraps up the rest
  linarith

theorem inner_B_D_C_D (A B C H D : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (hH : H = Triangle.orthocenter ⟨![A, B, C], tri⟩)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    inner ℝ (B - D) (C - D) = -inner ℝ (A - D) (H - D) :=
by
  have hD_H := orthocenter_proj_eq A B C H D tri hH hD
  have h_AD_CD := inner_A_D_C_D_eq_zero A B C D hD
  have h_BD_HD := inner_H_D_B_D_eq_zero B C H D hD_H
  have h_ortho := orthocenter_inner_B_sub_A_C_sub_H_eq_zero A B C H tri hH
  exact inner_B_D_C_D_algebra A B C H D h_ortho h_AD_CD h_BD_HD

theorem inner_A_B_F_B (A B C F : ℝ²)
    (hF : F = ↑(orthogonalProjection (affineSpan ℝ ({A, B} : Set ℝ²)) C)) :
    inner ℝ (A - B) (F - B) = inner ℝ (A - B) (C - B) :=
by
  -- A and B are both in the affine span of {A, B}
  have hA : A ∈ affineSpan ℝ ({A, B} : Set ℝ²) :=
    subset_spanPoints ℝ ({A, B} : Set ℝ²) (Or.inl rfl)

  have hB : B ∈ affineSpan ℝ ({A, B} : Set ℝ²) :=
    subset_spanPoints ℝ ({A, B} : Set ℝ²) (Or.inr rfl)

  -- Ensure Lean knows the span is nonempty for projection calculations
  haveI : Nonempty ↥(affineSpan ℝ ({A, B} : Set ℝ²)) := ⟨⟨A, hA⟩⟩

  -- Apply the core property of an orthogonal projection directly using the vector difference
  have h_FC_ortho : F - C ∈ (affineSpan ℝ ({A, B} : Set ℝ²)).directionᗮ := by
    have h_vsub := EuclideanGeometry.orthogonalProjection_vsub_mem_direction_orthogonal (affineSpan ℝ ({A, B} : Set ℝ²)) C
    rw [← hF] at h_vsub
    exact h_vsub

  -- The vector A - B lies in the direction space of our affine span
  have h_AB_dir : A - B ∈ (affineSpan ℝ ({A, B} : Set ℝ²)).direction :=
    AffineSubspace.vsub_mem_direction hA hB

  -- Hence, A - B is orthogonal to the residual vector (F - C)
  -- Note: Provide the explicit arguments for the submodule and vector to `mem_orthogonal`
  have h_ortho : inner ℝ (A - B) (F - C) = (0 : ℝ) :=
    (Submodule.mem_orthogonal (affineSpan ℝ ({A, B} : Set ℝ²)).direction (F - C)).mp h_FC_ortho (A - B) h_AB_dir

  -- Simple algebraic decomposition of the vector F - B
  have h_FB : F - B = (C - B) + (F - C) := by abel

  -- Stitch it all back together leveraging the linearity of the inner product
  calc inner ℝ (A - B) (F - B)
    _ = inner ℝ (A - B) ((C - B) + (F - C)) := by rw [h_FB]
    _ = inner ℝ (A - B) (C - B) + inner ℝ (A - B) (F - C) := by rw [inner_add_right]
    _ = inner ℝ (A - B) (C - B) + 0 := by rw [h_ortho]
    _ = inner ℝ (A - B) (C - B) := by rw [add_zero]

theorem inner_D_B_C_B (A B C D : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    inner ℝ (D - B) (C - B) = inner ℝ (A - B) (C - B) :=
by
  have hC : C ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
    have h_sub : ({B, C} : Set ℝ²) ⊆ ↑(affineSpan ℝ ({B, C} : Set ℝ²)) := subset_affineSpan ℝ ({B, C} : Set ℝ²)
    have h_mem : C ∈ ({B, C} : Set ℝ²) := by simp
    exact h_sub h_mem

  have hB : B ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
    have h_sub : ({B, C} : Set ℝ²) ⊆ ↑(affineSpan ℝ ({B, C} : Set ℝ²)) := subset_affineSpan ℝ ({B, C} : Set ℝ²)
    have h_mem : B ∈ ({B, C} : Set ℝ²) := by simp
    exact h_sub h_mem

  have h_CB_dir : C - B ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).direction :=
    AffineSubspace.vsub_mem_direction hC hB

  have h_AD_ortho : A - D ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).directionᗮ := by
    rw [hD]
    exact EuclideanGeometry.vsub_orthogonalProjection_mem_direction_orthogonal (affineSpan ℝ ({B, C} : Set ℝ²)) A

  have eq1 : A - B = (A - D) + (D - B) := by abel
  rw [eq1]
  rw [inner_add_left]
  have eq2 : inner ℝ (A - D) (C - B) = 0 := by
    have h_ortho := h_AD_ortho
    rw [Submodule.mem_orthogonal] at h_ortho
    have h_inner := h_ortho (C - B) h_CB_dir
    rw [real_inner_comm]
    exact h_inner
  rw [eq2, zero_add]

theorem A_sub_D_ne_zero (A B C D : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    A - D ≠ 0 :=
by
  intro hAD
  have hA_eq_D : A = D := sub_eq_zero.mp hAD
  have hA_eq : ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A) = A := by
    rw [← hD, ← hA_eq_D]
  have hA_mem : A ∈ affineSpan ℝ ({B, C} : Set ℝ²) :=
    EuclideanGeometry.orthogonalProjection_eq_self_iff.mp hA_eq
  have h_not_mem := tri.notMem_affineSpan_diff 0 Set.univ
  have h_img : ![A, B, C] '' (Set.univ \ {0}) = ({B, C} : Set ℝ²) := by
    ext x
    simp only [Set.mem_image, Set.mem_diff, Set.mem_univ, Set.mem_singleton_iff, true_and, Set.mem_insert_iff]
    constructor
    · rintro ⟨i, hi, rfl⟩
      have h12 : i = 1 ∨ i = 2 := by
        obtain ⟨val, isLt⟩ := i
        have h_neq : val ≠ 0 := fun h => hi (Fin.ext h)
        have h_eq : val = 1 ∨ val = 2 := by omega
        rcases h_eq with rfl | rfl
        · left; exact Fin.ext rfl
        · right; exact Fin.ext rfl
      rcases h12 with rfl | rfl
      · left; rfl
      · right; rfl
    · rintro (rfl | rfl)
      · exact ⟨1, by decide, rfl⟩
      · exact ⟨2, by decide, rfl⟩
  rw [h_img] at h_not_mem
  exact h_not_mem hA_mem

theorem C_sub_B_ne_zero (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C]) :
    C - B ≠ 0 :=
by
  intro h
  have hCB : C = B := sub_eq_zero.mp h
  have h_eq : ![A, B, C] 2 = ![A, B, C] 1 := hCB
  have h_contra : (2 : Fin 3) = (1 : Fin 3) := tri.injective h_eq
  revert h_contra
  decide

theorem orthogonal_A_D_C_B (A B C D : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    inner ℝ (A - D) (C - B) = (0 : ℝ) :=
by
  let s := affineSpan ℝ ({B, C} : Set ℝ²)

  have hB_in : B ∈ s := by
    apply mem_affineSpan ℝ
    simp

  have hC_in : C ∈ s := by
    apply mem_affineSpan ℝ
    simp

  have hCB_dir : C - B ∈ s.direction := by
    exact AffineSubspace.vsub_mem_direction hC_in hB_in

  have hAD_ortho : A - D ∈ s.directionᗮ := by
    rw [hD]
    -- By definition of affine properties over modules, subtraction `A - D` is defeq to vector subtraction `A -ᵥ D`
    exact vsub_orthogonalProjection_mem_direction_orthogonal (affineSpan ℝ ({B, C} : Set ℝ²)) A

  -- `A - D ∈ s.directionᗮ` is definitionally equivalent to `∀ u ∈ s.direction, inner ℝ u (A - D) = 0`
  -- We can hence apply `hAD_ortho` directly as a function to our direction vector and membership proof.
  have h_inner : inner ℝ (C - B) (A - D) = (0 : ℝ) := hAD_ortho (C - B) hCB_dir

  -- The target equation asks for `inner ℝ (A - D) (C - B) = 0`, so we use the symmetric property of real inner products.
  rw [real_inner_comm]
  exact h_inner

theorem orthogonal_H_D_C_B (B C H D : ℝ²)
    (hH_proj : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) H)) :
    inner ℝ (H - D) (C - B) = (0 : ℝ) :=
by
  let s := affineSpan ℝ ({B, C} : Set ℝ²)
  have hB_in : B ∈ ({B, C} : Set ℝ²) := Or.inl rfl
  have hC_in : C ∈ ({B, C} : Set ℝ²) := Or.inr rfl
  have hs_B : B ∈ s := subset_affineSpan ℝ ({B, C} : Set ℝ²) hB_in
  have hs_C : C ∈ s := subset_affineSpan ℝ ({B, C} : Set ℝ²) hC_in
  have h_dir' : C -ᵥ B ∈ s.direction := AffineSubspace.vsub_mem_direction hs_C hs_B
  have h_dir : C - B ∈ s.direction := h_dir'
  haveI : Nonempty s := ⟨⟨B, hs_B⟩⟩
  have h_ortho_D : H - D ∈ s.directionᗮ := by
    rw [hH_proj]
    exact vsub_orthogonalProjection_mem_direction_orthogonal s H
  -- Since `H - D ∈ s.directionᗮ` is definitionally `∀ u ∈ s.direction, inner u (H - D) = 0`,
  -- we can just apply `h_ortho_D` to our direction vector `C - B` directly.
  have h2 : inner ℝ (C - B) (H - D) = (0 : ℝ) := h_ortho_D (C - B) h_dir

  -- Swap the inner product arguments to match `h2` precisely.
  rw [real_inner_comm]
  exact h2

theorem orthogonal_P_D_C_B (B C H D P : ℝ²)
    (hH_ortho : inner ℝ (H - D) (C - B) = (0 : ℝ))
    (hP : P - D = -(H - D)) :
    inner ℝ (P - D) (C - B) = (0 : ℝ) :=
by
  rw [hP, inner_neg_left, hH_ortho, neg_zero]

theorem cross_eq_zero_of_orthogonal (u v w : ℝ²) (hu : u ≠ 0)
    (hvu : inner ℝ v u = (0 : ℝ)) (hwu : inner ℝ w u = (0 : ℝ)) :
    v (0 : Fin 2) * w (1 : Fin 2) - v (1 : Fin 2) * w (0 : Fin 2) = 0 :=
by
  have h1 : v (0 : Fin 2) * u (0 : Fin 2) + v (1 : Fin 2) * u (1 : Fin 2) = 0 := by
    calc
      v (0 : Fin 2) * u (0 : Fin 2) + v (1 : Fin 2) * u (1 : Fin 2)
        = ∑ i : Fin 2, v i * u i := (Fin.sum_univ_two (fun i => v i * u i)).symm
      _ = inner ℝ v u := by simp [inner]; ring
      _ = 0 := hvu

  have h2 : w (0 : Fin 2) * u (0 : Fin 2) + w (1 : Fin 2) * u (1 : Fin 2) = 0 := by
    calc
      w (0 : Fin 2) * u (0 : Fin 2) + w (1 : Fin 2) * u (1 : Fin 2)
        = ∑ i : Fin 2, w i * u i := (Fin.sum_univ_two (fun i => w i * u i)).symm
      _ = inner ℝ w u := by simp [inner]; ring
      _ = 0 := hwu

  have hc0 : (v (0 : Fin 2) * w (1 : Fin 2) - v (1 : Fin 2) * w (0 : Fin 2)) * u (0 : Fin 2) = 0 := by
    linear_combination w (1 : Fin 2) * h1 - v (1 : Fin 2) * h2

  have hc1 : (v (0 : Fin 2) * w (1 : Fin 2) - v (1 : Fin 2) * w (0 : Fin 2)) * u (1 : Fin 2) = 0 := by
    linear_combination v (0 : Fin 2) * h2 - w (0 : Fin 2) * h1

  have hu_or : u (0 : Fin 2) ≠ 0 ∨ u (1 : Fin 2) ≠ 0 := by
    by_contra contra
    push_neg at contra
    have hu_eq : u = 0 := by
      ext i
      induction i using Fin.cases with
      | zero => exact contra.1
      | succ j =>
        induction j using Fin.cases with
        | zero => exact contra.2
        | succ k => exact k.elim0
    exact hu hu_eq

  cases hu_or with
  | inl hu0 =>
    cases mul_eq_zero.mp hc0 with
    | inl hC => exact hC
    | inr h_eq => exact absurd h_eq hu0
  | inr hu1 =>
    cases mul_eq_zero.mp hc1 with
    | inl hC => exact hC
    | inr h_eq => exact absurd h_eq hu1

theorem smul_of_cross_eq_zero (v w : ℝ²) (hv : v ≠ 0)
    (hcross : v (0 : Fin 2) * w (1 : Fin 2) - v (1 : Fin 2) * w (0 : Fin 2) = 0) :
    ∃ c : ℝ, w = c • v :=
by
  by_cases h0 : v (0 : Fin 2) = 0
  · have hv1 : v (1 : Fin 2) ≠ 0 := by
      intro h1
      apply hv
      ext i
      revert i
      rw [Fin.forall_fin_two]
      exact ⟨h0, h1⟩
    have h1 : v (0 : Fin 2) * w (1 : Fin 2) = v (1 : Fin 2) * w (0 : Fin 2) := sub_eq_zero.mp hcross
    rw [h0, zero_mul] at h1
    have h2 : w (0 : Fin 2) * v (1 : Fin 2) = 0 := by
      rw [mul_comm (w (0 : Fin 2)) (v (1 : Fin 2)), ← h1]
    have hw0 : w (0 : Fin 2) = 0 := by
      rcases mul_eq_zero.mp h2 with hw0 | hv1'
      · exact hw0
      · contradiction
    use w (1 : Fin 2) / v (1 : Fin 2)
    ext i
    revert i
    rw [Fin.forall_fin_two]
    constructor
    · calc w (0 : Fin 2) = 0 := hw0
        _ = (w (1 : Fin 2) / v (1 : Fin 2)) * 0 := (mul_zero (w (1 : Fin 2) / v (1 : Fin 2))).symm
        _ = (w (1 : Fin 2) / v (1 : Fin 2)) * v (0 : Fin 2) := by rw [← h0]
        _ = ( (w (1 : Fin 2) / v (1 : Fin 2)) • v ) (0 : Fin 2) := rfl
    · calc w (1 : Fin 2) = (w (1 : Fin 2) / v (1 : Fin 2)) * v (1 : Fin 2) := (div_mul_cancel₀ _ hv1).symm
        _ = ( (w (1 : Fin 2) / v (1 : Fin 2)) • v ) (1 : Fin 2) := rfl
  · use w (0 : Fin 2) / v (0 : Fin 2)
    ext i
    revert i
    rw [Fin.forall_fin_two]
    constructor
    · calc w (0 : Fin 2) = (w (0 : Fin 2) / v (0 : Fin 2)) * v (0 : Fin 2) := (div_mul_cancel₀ _ h0).symm
        _ = ( (w (0 : Fin 2) / v (0 : Fin 2)) • v ) (0 : Fin 2) := rfl
    · have hc : v (0 : Fin 2) * w (1 : Fin 2) = v (1 : Fin 2) * w (0 : Fin 2) := sub_eq_zero.mp hcross
      have h_calc : v (0 : Fin 2) * w (1 : Fin 2) = v (0 : Fin 2) * ((w (0 : Fin 2) / v (0 : Fin 2)) * v (1 : Fin 2)) := by
        calc v (0 : Fin 2) * w (1 : Fin 2) = v (1 : Fin 2) * w (0 : Fin 2) := hc
          _ = v (1 : Fin 2) * (w (0 : Fin 2) / v (0 : Fin 2) * v (0 : Fin 2)) := by rw [div_mul_cancel₀ (w (0 : Fin 2)) h0]
          _ = v (0 : Fin 2) * ((w (0 : Fin 2) / v (0 : Fin 2)) * v (1 : Fin 2)) := by ring
      calc w (1 : Fin 2) = (w (0 : Fin 2) / v (0 : Fin 2)) * v (1 : Fin 2) := mul_left_cancel₀ h0 h_calc
        _ = ( (w (0 : Fin 2) / v (0 : Fin 2)) • v ) (1 : Fin 2) := rfl

theorem orthogonalProjection_mem_span (A B C : ℝ²) :
    ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A) ∈ affineSpan ℝ ({B, C} : Set ℝ²) :=
by
  exact SetLike.coe_mem (orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)

theorem inner_D_C_B_C (A B C D : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    inner ℝ (D - C) (B - C) = inner ℝ (A - C) (B - C) :=
by
  have h_subset : ({B, C} : Set ℝ²) ⊆ (affineSpan ℝ ({B, C} : Set ℝ²) : Set ℝ²) :=
    affineSpan_le.mp le_rfl
  have hB : B ∈ affineSpan ℝ ({B, C} : Set ℝ²) :=
    h_subset (Set.mem_insert B {C})
  have hC : C ∈ affineSpan ℝ ({B, C} : Set ℝ²) :=
    h_subset (Set.mem_insert_of_mem B (Set.mem_singleton C))
  have hBC : B -ᵥ C ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).direction :=
    AffineSubspace.vsub_mem_direction hB hC

  haveI : Nonempty (affineSpan ℝ ({B, C} : Set ℝ²)) := ⟨⟨B, hB⟩⟩

  have h_ortho : A -ᵥ D ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).directionᗮ := by
    rw [hD]
    exact vsub_orthogonalProjection_mem_direction_orthogonal (affineSpan ℝ ({B, C} : Set ℝ²)) A

  have h_inner : inner ℝ (A - D) (B - C) = 0 := by
    have h1 : inner ℝ (B - C) (A - D) = 0 := h_ortho (B -ᵥ C) hBC
    rw [real_inner_comm] at h1
    exact h1

  have h_add : A - C = (A - D) + (D - C) := by abel
  rw [h_add, inner_add_left, h_inner, zero_add]

theorem inner_A_B_C_B_pos (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (h_acute : AcuteAngled ⟨![A, B, C], tri⟩) :
    0 < inner ℝ (A - B) (C - B) :=
by
  -- Extract the angle inequality from the acute-angled hypothesis
  have h_angles := Affine.Triangle.acuteAngled_iff_angle_lt.mp h_acute
  have h1_raw := h_angles.1
  -- The geometric angle A B C is definitionally the inner product angle between (A - B) and (C - B)
  have h1 : InnerProductGeometry.angle (A - B) (C - B) < Real.pi / 2 := h1_raw

  -- Use affine independence to show that the points A, B, and C are distinct
  have h_inj : Function.Injective ![A, B, C] := tri.injective

  have hAB : A - B ≠ 0 := by
    intro h
    have heq : A = B := sub_eq_zero.mp h
    have heq2 : ![A, B, C] 0 = ![A, B, C] 1 := heq
    have : (0 : Fin 3) = 1 := h_inj heq2
    revert this; decide

  have hCB : C - B ≠ 0 := by
    intro h
    have heq : C = B := sub_eq_zero.mp h
    have heq2 : ![A, B, C] 2 = ![A, B, C] 1 := heq
    have : (2 : Fin 3) = 1 := h_inj heq2
    revert this; decide

  -- The angle is non-negative by definition
  have h_angle_nonneg : 0 ≤ InnerProductGeometry.angle (A - B) (C - B) :=
    InnerProductGeometry.angle_nonneg (A - B) (C - B)

  -- Show the angle is strictly within (-(π / 2), π / 2)
  have hpi : 0 < Real.pi / 2 := by positivity
  have h_left : -(Real.pi / 2) < InnerProductGeometry.angle (A - B) (C - B) := by linarith
  have h_mem : InnerProductGeometry.angle (A - B) (C - B) ∈ Set.Ioo (-(Real.pi / 2)) (Real.pi / 2) :=
    Set.mem_Ioo.mpr ⟨h_left, h1⟩

  -- Conclude that the cosine of the angle is positive
  have h_cos_pos : 0 < Real.cos (InnerProductGeometry.angle (A - B) (C - B)) :=
    Real.cos_pos_of_mem_Ioo h_mem

  -- Relate the cosine of the angle to the inner product and norms
  have h_cos_eq : Real.cos (InnerProductGeometry.angle (A - B) (C - B)) = inner ℝ (A - B) (C - B) / (norm (A - B) * norm (C - B)) :=
    InnerProductGeometry.cos_angle (A - B) (C - B)
  rw [h_cos_eq] at h_cos_pos

  -- Since the vectors are non-zero, their norms are strictly positive
  have h_norm_AB : 0 < norm (A - B) := norm_pos_iff.mpr hAB
  have h_norm_CB : 0 < norm (C - B) := norm_pos_iff.mpr hCB
  have h_norm_mul : 0 < norm (A - B) * norm (C - B) := mul_pos h_norm_AB h_norm_CB

  -- Multiply the positive cosine expression by the positive product of the norms
  have h_mul : (inner ℝ (A - B) (C - B) / (norm (A - B) * norm (C - B))) * (norm (A - B) * norm (C - B)) > 0 :=
    mul_pos h_cos_pos h_norm_mul

  -- Cancel out the norms to isolate the inner product
  have h_cancel : (inner ℝ (A - B) (C - B) / (norm (A - B) * norm (C - B))) * (norm (A - B) * norm (C - B)) = inner ℝ (A - B) (C - B) := by
    apply div_mul_cancel₀
    exact ne_of_gt h_norm_mul

  rwa [h_cancel] at h_mul

theorem inner_A_C_B_C_pos (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (h_acute : AcuteAngled ⟨![A, B, C], tri⟩) :
    0 < inner ℝ (A - C) (B - C) :=
by
  have h_acute_iff := Affine.Triangle.acuteAngled_iff_angle_lt.mp h_acute
  have h2 : EuclideanGeometry.angle B C A < Real.pi / 2 := h_acute_iff.2.1
  have h_angle_eq : EuclideanGeometry.angle B C A = InnerProductGeometry.angle (A - C) (B - C) :=
    InnerProductGeometry.angle_comm (B - C) (A - C)
  rw [h_angle_eq] at h2

  have h_angle_nonneg : 0 ≤ InnerProductGeometry.angle (A - C) (B - C) :=
    InnerProductGeometry.angle_nonneg (A - C) (B - C)
  have h_pi_pos : (0 : ℝ) < Real.pi / 2 := by positivity
  have h_angle_mem : InnerProductGeometry.angle (A - C) (B - C) ∈ Set.Ioo (-(Real.pi / 2)) (Real.pi / 2) := by
    exact Set.mem_Ioo.mpr ⟨by linarith, h2⟩
  have h_cos_pos : 0 < Real.cos (InnerProductGeometry.angle (A - C) (B - C)) :=
    Real.cos_pos_of_mem_Ioo h_angle_mem

  have h_inj : Function.Injective ![A, B, C] := AffineIndependent.injective tri
  have hA_neq_C : A ≠ C := by
    intro h
    have h_eq : ![A, B, C] 0 = ![A, B, C] 2 := h
    have h_eq_idx : (0 : Fin 3) = (2 : Fin 3) := h_inj h_eq
    revert h_eq_idx
    decide
  have hB_neq_C : B ≠ C := by
    intro h
    have h_eq : ![A, B, C] 1 = ![A, B, C] 2 := h
    have h_eq_idx : (1 : Fin 3) = (2 : Fin 3) := h_inj h_eq
    revert h_eq_idx
    decide

  have hA_sub_ne_zero : A - C ≠ 0 := sub_ne_zero.mpr hA_neq_C
  have hB_sub_ne_zero : B - C ≠ 0 := sub_ne_zero.mpr hB_neq_C

  have h_normA : 0 < ‖A - C‖ := norm_pos_iff.mpr hA_sub_ne_zero
  have h_normB : 0 < ‖B - C‖ := norm_pos_iff.mpr hB_sub_ne_zero
  have h_denom_pos : 0 < ‖A - C‖ * ‖B - C‖ := mul_pos h_normA h_normB

  have h_cos_eq : Real.cos (InnerProductGeometry.angle (A - C) (B - C)) =
    inner ℝ (A - C) (B - C) / (‖A - C‖ * ‖B - C‖) :=
      InnerProductGeometry.cos_angle (A - C) (B - C)

  have h_div_pos : 0 < inner ℝ (A - C) (B - C) / (‖A - C‖ * ‖B - C‖) := by
    rw [← h_cos_eq]
    exact h_cos_pos

  have h_mul : 0 < (inner ℝ (A - C) (B - C) / (‖A - C‖ * ‖B - C‖)) * (‖A - C‖ * ‖B - C‖) :=
    mul_pos h_div_pos h_denom_pos

  have h_cancel : (inner ℝ (A - C) (B - C) / (‖A - C‖ * ‖B - C‖)) * (‖A - C‖ * ‖B - C‖) = inner ℝ (A - C) (B - C) := by
    exact div_mul_cancel₀ _ (ne_of_gt h_denom_pos)

  rwa [h_cancel] at h_mul

theorem D_sub_B_eq_smul (B C D : ℝ²) (hD : D ∈ affineSpan ℝ ({B, C} : Set ℝ²)) :
    ∃ t : ℝ, D - B = t • (C - B) :=
by
  have hB : B ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
    apply subset_affineSpan
    exact Or.inl rfl
  have hd := AffineSubspace.vsub_mem_direction hD hB

  -- The direction of an affine span is the vector span of its generating set
  rw [direction_affineSpan] at hd

  -- The vector span of a 2-point set {B, C} is the module span of their difference (B - C)
  rw [vectorSpan_pair] at hd

  -- Being in the span of a single element is equivalent to being a scalar multiple of it
  rw [Submodule.mem_span_singleton] at hd

  -- Destructure the existential to get the specific scalar witness
  obtain ⟨t, ht⟩ := hd

  -- The witness for our goal will be the negated scalar
  use -t

  -- In an AddTorsor module over itself, `vsub` (-ᵥ) is definitionally equivalent to `sub` (-)
  simp only [vsub_eq_sub] at ht

  -- Rearrange the signs to match the target equation `D - B = -t • (C - B)`
  rw [neg_smul, ← smul_neg, neg_sub]

  -- Close the goal with the symmetric identity of our restructured hypothesis
  exact ht.symm

theorem t_bounds_of_inner_pos (A B C D : ℝ²) (t : ℝ)
    (hD : D - B = t • (C - B))
    (h1 : 0 < inner ℝ (A - B) (C - B))
    (h2 : inner ℝ (D - B) (C - B) = inner ℝ (A - B) (C - B))
    (h3 : 0 < inner ℝ (A - C) (B - C))
    (h4 : inner ℝ (D - C) (B - C) = inner ℝ (A - C) (B - C)) :
    0 < t ∧ 0 < 1 - t :=
by
  constructor
  · have h2' : 0 < t * inner ℝ (C - B) (C - B) := by
      calc 0 < inner ℝ (A - B) (C - B) := h1
        _ = inner ℝ (D - B) (C - B) := h2.symm
        _ = inner ℝ (t • (C - B)) (C - B) := by rw [hD]
        _ = t * inner ℝ (C - B) (C - B) := by rw [real_inner_smul_left]
    have h_nonneg : 0 ≤ inner ℝ (C - B) (C - B) := real_inner_self_nonneg
    by_contra h_contra
    nlinarith
  · have hDC : D - C = (1 - t) • (B - C) := by
      have h_eq : D - C = (D - B) + (B - C) := by abel
      rw [h_eq, hD]
      have h_eq2 : t • (C - B) + (B - C) = (1 - t) • (B - C) := by
        rw [sub_smul, one_smul, smul_sub, smul_sub]
        abel
      exact h_eq2
    have h4' : 0 < (1 - t) * inner ℝ (B - C) (B - C) := by
      calc 0 < inner ℝ (A - C) (B - C) := h3
        _ = inner ℝ (D - C) (B - C) := h4.symm
        _ = inner ℝ ((1 - t) • (B - C)) (B - C) := by rw [hDC]
        _ = (1 - t) * inner ℝ (B - C) (B - C) := by rw [real_inner_smul_left]
    have h_nonneg2 : 0 ≤ inner ℝ (B - C) (B - C) := real_inner_self_nonneg
    by_contra h_contra
    nlinarith

theorem inner_B_D_C_D_neg_of_t (B C D : ℝ²) (t : ℝ)
    (hD : D - B = t • (C - B))
    (ht : 0 < t ∧ 0 < 1 - t)
    (hBC : C - B ≠ 0) :
    inner ℝ (B - D) (C - D) < 0 :=
by
  -- Express B - D in terms of C - B
  have h1 : B - D = (-t) • (C - B) := by
    rw [neg_smul, ← hD, neg_sub]

  -- Express C - D in terms of C - B
  have h2 : C - D = (1 - t) • (C - B) := by
    rw [sub_smul, one_smul, ← hD]
    abel

  -- Expand the inner product using bilinearity over ℝ
  have h_expand : inner ℝ (B - D) (C - D) = -(t * (1 - t) * inner ℝ (C - B) (C - B)) := by
    rw [h1, h2]
    rw [real_inner_smul_left]
    have h_comm : inner ℝ (C - B) ((1 - t) • (C - B)) = inner ℝ ((1 - t) • (C - B)) (C - B) := real_inner_comm _ _
    rw [h_comm]
    rw [real_inner_smul_left]
    ring

  -- The inner product of C - B with itself is strictly positive
  have h_inner_pos : 0 < inner ℝ (C - B) (C - B) := real_inner_self_pos.mpr hBC

  -- The scalar multiplier t * (1 - t) is strictly positive
  have ht1 : 0 < t := ht.1
  have ht2 : 0 < 1 - t := ht.2
  have h_scalar_pos : 0 < t * (1 - t) := mul_pos ht1 ht2

  -- Therefore, their product is strictly positive
  have h_prod_pos : 0 < t * (1 - t) * inner ℝ (C - B) (C - B) := mul_pos h_scalar_pos h_inner_pos

  -- Conclude the final strict negativity from the expansion
  rw [h_expand]
  linarith

theorem inner_B_sub_H_C_sub_A_eq_zero (A B C H : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (hH : H = Triangle.orthocenter ⟨![A, B, C], tri⟩) :
    inner ℝ (B - H) (C - A) = (0 : ℝ) :=
by
  let s : Affine.Triangle ℝ ℝ² := ⟨![A, B, C], tri⟩

  have h_monge : s.mongePoint = H := by
    calc s.mongePoint = Triangle.orthocenter s := (Affine.Triangle.orthocenter_eq_mongePoint s).symm
      _ = H := hH.symm

  have h_centroid : Finset.centroid ℝ ({2, 0}ᶜ : Finset (Fin 3)) s.points = B := by
    have h_eq : ({2, 0}ᶜ : Finset (Fin 3)) = {1} := by
      ext x
      revert x
      decide
    rw [h_eq]
    simp only [Finset.centroid_singleton]
    rfl

  have h_inner := Affine.Simplex.inner_mongePoint_vsub_face_centroid_vsub s (i₁ := (2 : Fin 3)) (i₂ := (0 : Fin 3))
  rw [h_monge, h_centroid] at h_inner

  -- Convert affine vector subtractions to standard vector space subtractions
  change inner ℝ (H - B) (C - A) = (0 : ℝ) at h_inner

  rw [← neg_sub H B, inner_neg_left, h_inner]
  exact neg_zero

theorem inner_B_sub_D_A_sub_D_eq_zero (A B C D : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    inner ℝ (B - D) (A - D) = (0 : ℝ) :=
by
  have hD_in_S : D ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
    rw [hD]
    exact SetLike.coe_mem (orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)

  have hB_in_S : B ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
    apply subset_affineSpan
    -- B ∈ {B, C} is definitionally B = B ∨ B ∈ {C}
    exact Or.inl rfl

  have h_dir : B - D ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).direction :=
    AffineSubspace.vsub_mem_direction hB_in_S hD_in_S

  have h_ortho : A - D ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).directionᗮ := by
    rw [hD]
    exact vsub_orthogonalProjection_mem_direction_orthogonal (affineSpan ℝ ({B, C} : Set ℝ²)) A

  -- Since v ∈ Uᗮ is defeq to ∀ u ∈ U, ⟪u, v⟫_ℝ = 0, we can apply h_ortho directly
  exact h_ortho (B - D) h_dir

theorem inner_A_sub_D_C_sub_D_eq_zero (A B C D : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    inner ℝ (A - D) (C - D) = (0 : ℝ) :=
by
  let s := affineSpan ℝ ({B, C} : Set ℝ²)
  let b_sub := Classical.arbitrary ↥s
  let b : ℝ² := ↑b_sub
  let K := s.direction
  let proj_sub := K.orthogonalProjection (A - b)
  let proj : ℝ² := ↑proj_sub

  have hD_eq : D = proj + b := by
    rw [hD, EuclideanGeometry.orthogonalProjection_apply s]
    rfl

  have hC_s : C ∈ s := by
    have h : {B, C} ⊆ (s : Set ℝ²) := subset_affineSpan ℝ {B, C}
    apply h
    exact Or.inr rfl

  have hD_s : D ∈ s := by
    rw [hD]
    exact Subtype.coe_prop (orthogonalProjection s A)

  have hCD_K : C - D ∈ K := by
    exact AffineSubspace.vsub_mem_direction hC_s hD_s

  have hA : A - D = A - b - proj := by
    rw [hD_eq, sub_add_eq_sub_sub, sub_right_comm]

  have h_proj_eq : inner ℝ (C - D) proj = inner ℝ (C - D) (A - b) := by
    exact Submodule.inner_orthogonalProjection_eq_of_mem_left (⟨C - D, hCD_K⟩ : ↥K) (A - b)

  rw [hA]
  rw [real_inner_comm (C - D) (A - b - proj)]
  rw [inner_sub_right]
  rw [h_proj_eq]
  exact sub_self _

theorem inner_B_D_C_D_eq_inner_A_D_A_D (A B C H D : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (hH : H = Triangle.orthocenter ⟨![A, B, C], tri⟩)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A))
    (h_H_eq : H - D = -(A - D)) :
    inner ℝ (B - D) (C - D) = inner ℝ (A - D) (A - D) :=
by
  have h1 : inner ℝ (B - H) (C - A) = (0 : ℝ) := inner_B_sub_H_C_sub_A_eq_zero A B C H tri hH

  -- Vector arithmetic decomposition
  have h_BH1 : B - H = (B - D) - (H - D) := by abel
  have h_BH2 : (B - D) - (H - D) = (B - D) - -(A - D) := by rw [h_H_eq]
  have h_BH3 : (B - D) - -(A - D) = (B - D) + (A - D) := by abel
  have h_BH : B - H = (B - D) + (A - D) := by rw [h_BH1, h_BH2, h_BH3]
  have h_CA : C - A = (C - D) - (A - D) := by abel

  -- Substitution into the orthogonality equation
  rw [h_BH, h_CA] at h1

  -- Obtain the relevant zeroes from spatial orthogonality
  have h2 : inner ℝ (B - D) (A - D) = (0 : ℝ) := inner_B_sub_D_A_sub_D_eq_zero A B C D hD
  have h3 : inner ℝ (A - D) (C - D) = (0 : ℝ) := inner_A_sub_D_C_sub_D_eq_zero A B C D hD

  -- Expand the inner product via bilinearity with explicit arguments to avoid overlapping matching errors
  have h_part1 : inner ℝ (B - D) ((C - D) - (A - D)) = inner ℝ (B - D) (C - D) - inner ℝ (B - D) (A - D) :=
    inner_sub_right (B - D) (C - D) (A - D)
  have h_part2 : inner ℝ (A - D) ((C - D) - (A - D)) = inner ℝ (A - D) (C - D) - inner ℝ (A - D) (A - D) :=
    inner_sub_right (A - D) (C - D) (A - D)
  have h_add : inner ℝ ((B - D) + (A - D)) ((C - D) - (A - D)) = inner ℝ (B - D) ((C - D) - (A - D)) + inner ℝ (A - D) ((C - D) - (A - D)) :=
    inner_add_left (B - D) (A - D) ((C - D) - (A - D))

  rw [h_add, h_part1, h_part2] at h1

  -- Eliminate cross terms that are perpendicular
  rw [h2, h3] at h1

  -- The remaining scalar algebraic equation leads exactly to the goal
  linarith

theorem inner_A_D_A_D_pos (A B C D : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    0 < inner ℝ (A - D) (A - D) :=
by
  have h_proj_iff := EuclideanGeometry.coe_orthogonalProjection_eq_iff_mem (s := affineSpan ℝ ({B, C} : Set ℝ²)) (p := A) (q := D)
  have h_proj : D ∈ affineSpan ℝ ({B, C} : Set ℝ²) ∧ A -ᵥ D ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).directionᗮ := by
    apply h_proj_iff.mp
    exact hD.symm
  have hD_mem : D ∈ affineSpan ℝ ({B, C} : Set ℝ²) := h_proj.1

  have h_not_mem : A ∉ affineSpan ℝ ({B, C} : Set ℝ²) := by
    have h1 := tri.notMem_affineSpan_diff 0 Set.univ
    have h2 : ![A, B, C] '' (Set.univ \ {0}) = ({B, C} : Set ℝ²) := by
      ext x
      simp only [Set.mem_image, Set.mem_diff, Set.mem_univ, Set.mem_singleton_iff, true_and, Set.mem_insert_iff]
      constructor
      · rintro ⟨i, hi, rfl⟩
        have h_val : i.val = 1 ∨ i.val = 2 := by
          have h_lt : i.val < 3 := i.isLt
          have h_ne : i.val ≠ 0 := by
            intro contra
            apply hi
            ext
            exact contra
          omega
        rcases h_val with h1 | h2
        · left
          have hi1 : i = 1 := by ext; exact h1
          rw [hi1]
          rfl
        · right
          have hi2 : i = 2 := by ext; exact h2
          rw [hi2]
          rfl
      · rintro (rfl | rfl)
        · refine ⟨1, ?_, rfl⟩
          decide
        · refine ⟨2, ?_, rfl⟩
          decide
    change ![A, B, C] 0 ∉ affineSpan ℝ ({B, C} : Set ℝ²)
    rw [← h2]
    exact h1

  have hAD : A - D ≠ 0 := by
    intro h_eq
    have h_eq' : A = D := sub_eq_zero.mp h_eq
    have hA_mem : A ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
      rw [h_eq']
      exact hD_mem
    exact h_not_mem hA_mem

  exact real_inner_self_pos.mpr hAD

theorem inner_B_D_C_D_pos_of_P_eq_A (A B C H D P : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (hH : H = Triangle.orthocenter ⟨![A, B, C], tri⟩)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A))
    (hP : P - D = -(H - D))
    (hPA : P = A) :
    0 < inner ℝ (B - D) (C - D) :=
by
  have h_H_eq : H - D = -(A - D) := by
    rw [← hPA, hP, neg_neg]
  rw [inner_B_D_C_D_eq_inner_A_D_A_D A B C H D tri hH hD h_H_eq]
  exact inner_A_D_A_D_pos A B C D tri hD

theorem P_ne_A_of_acute (A B C H D P : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (h_acute : AcuteAngled ⟨![A, B, C], tri⟩)
    (hH : H = Triangle.orthocenter ⟨![A, B, C], tri⟩)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A))
    (hP : P - D = -(H - D)) :
    P ≠ A :=
by
  intro hPA
  have h_pos : 0 < inner ℝ (B - D) (C - D) :=
    inner_B_D_C_D_pos_of_P_eq_A A B C H D P tri hH hD hP hPA
  have hD_mem : D ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
    rw [hD]
    exact orthogonalProjection_mem_span A B C
  obtain ⟨t, ht⟩ := D_sub_B_eq_smul B C D hD_mem
  have h1 : 0 < inner ℝ (A - B) (C - B) := inner_A_B_C_B_pos A B C tri h_acute
  have h2 : inner ℝ (D - B) (C - B) = inner ℝ (A - B) (C - B) := inner_D_B_C_B A B C D hD
  have h3 : 0 < inner ℝ (A - C) (B - C) := inner_A_C_B_C_pos A B C tri h_acute
  have h4 : inner ℝ (D - C) (B - C) = inner ℝ (A - C) (B - C) := inner_D_C_B_C A B C D hD
  have ht_bounds : 0 < t ∧ 0 < 1 - t := t_bounds_of_inner_pos A B C D t ht h1 h2 h3 h4
  have hBC : C - B ≠ 0 := C_sub_B_ne_zero A B C tri
  have h_neg : inner ℝ (B - D) (C - D) < 0 := inner_B_D_C_D_neg_of_t B C D t ht ht_bounds hBC
  linarith

theorem mem_span_of_smul (A D P : ℝ²) (c : ℝ)
    (h : P - D = c • (A - D)) (hPA : P ≠ A) :
    D ∈ affineSpan ℝ ({A, P} : Set ℝ²) :=
by
  have hc : c ≠ 1 := by
    intro hc1
    have h2 : P - D = A - D := by
      calc P - D = c • (A - D) := h
        _ = (1 : ℝ) • (A - D) := by rw [hc1]
        _ = A - D := one_smul ℝ (A - D)
    have h3 : P = A := by
      calc P = (P - D) + D := (sub_add_cancel P D).symm
        _ = (A - D) + D := by rw [h2]
        _ = A := sub_add_cancel A D
    exact hPA h3

  have h1c : 1 - c ≠ 0 := by
    intro contra
    apply hc
    linarith

  have h4 : c • (A - P) = (1 - c) • (P - D) := by
    calc c • (A - P) = c • (A - D - (P - D)) := by congr 1; abel
      _ = c • (A - D) - c • (P - D) := smul_sub c (A - D) (P - D)
      _ = (P - D) - c • (P - D) := by rw [← h]
      _ = (1 : ℝ) • (P - D) - c • (P - D) := by
          congr 1
          exact (one_smul ℝ (P - D)).symm
      _ = (1 - c) • (P - D) := (sub_smul 1 c (P - D)).symm

  let r := -c * (1 - c)⁻¹
  have h_mul : (1 - c) * r = -c := by
    calc (1 - c) * r = (1 - c) * (-c * (1 - c)⁻¹) := rfl
      _ = -c * ((1 - c) * (1 - c)⁻¹) := by ring
      _ = -c * 1 := by rw [mul_inv_cancel₀ h1c]
      _ = -c := by ring

  have eq2 : (1 - c) • (r • (A - P) + (P - D)) = 0 := by
    calc (1 - c) • (r • (A - P) + (P - D))
      _ = (1 - c) • (r • (A - P)) + (1 - c) • (P - D) := smul_add (1 - c) (r • (A - P)) (P - D)
      _ = ((1 - c) * r) • (A - P) + (1 - c) • (P - D) := by
          congr 1
          exact (mul_smul (1 - c) r (A - P)).symm
      _ = -c • (A - P) + (1 - c) • (P - D) := by rw [h_mul]
      _ = -c • (A - P) + c • (A - P) := by rw [← h4]
      _ = (-c + c) • (A - P) := (add_smul (-c) c (A - P)).symm
      _ = (0 : ℝ) • (A - P) := by congr 1; ring
      _ = 0 := zero_smul ℝ (A - P)

  have eq3 : r • (A - P) + (P - D) = 0 := by
    have h_or := smul_eq_zero.mp eq2
    cases h_or with
    | inl h_scalar => exact False.elim (h1c h_scalar)
    | inr h_vec => exact h_vec

  have eq4 : r • (A - P) + P = D := by
    calc r • (A - P) + P = (r • (A - P) + P) - D + D := (sub_add_cancel (r • (A - P) + P) D).symm
      _ = r • (A - P) + (P - D) + D := by rw [add_sub_assoc]
      _ = 0 + D := by rw [eq3]
      _ = D := zero_add D

  rw [Set.pair_comm A P]
  convert smul_vsub_vadd_mem_affineSpan_pair r P A using 1
  exact eq4.symm

theorem D_mem_span_A_P (A B C H D P : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (h_acute : AcuteAngled ⟨![A, B, C], tri⟩)
    (hH : H = Triangle.orthocenter ⟨![A, B, C], tri⟩)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A))
    (hP : P - D = -(H - D)) :
    D ∈ affineSpan ℝ ({A, P} : Set ℝ²) :=
by
  have hH_proj : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) H) :=
    orthocenter_proj_eq A B C H D tri hH hD
  have h_ortho_A : inner ℝ (A - D) (C - B) = (0 : ℝ) :=
    orthogonal_A_D_C_B A B C D hD
  have h_ortho_H : inner ℝ (H - D) (C - B) = (0 : ℝ) :=
    orthogonal_H_D_C_B B C H D hH_proj
  have h_ortho_P : inner ℝ (P - D) (C - B) = (0 : ℝ) :=
    orthogonal_P_D_C_B B C H D P h_ortho_H hP
  have hCB_ne_zero : C - B ≠ 0 :=
    C_sub_B_ne_zero A B C tri
  have h_cross : (A - D) (0 : Fin 2) * (P - D) (1 : Fin 2) - (A - D) (1 : Fin 2) * (P - D) (0 : Fin 2) = 0 :=
    cross_eq_zero_of_orthogonal (C - B) (A - D) (P - D) hCB_ne_zero h_ortho_A h_ortho_P
  have hAD_ne_zero : A - D ≠ 0 :=
    A_sub_D_ne_zero A B C D tri hD
  have h_smul : ∃ c : ℝ, P - D = c • (A - D) :=
    smul_of_cross_eq_zero (A - D) (P - D) hAD_ne_zero h_cross
  obtain ⟨c, hc⟩ := h_smul
  have hPA : P ≠ A :=
    P_ne_A_of_acute A B C H D P tri h_acute hH hD hP
  exact mem_span_of_smul A D P c hc hPA

theorem F_mem_span_A_B (A B C F : ℝ²)
    (hF : F = ↑(orthogonalProjection (affineSpan ℝ ({A, B} : Set ℝ²)) C)) :
    F ∈ affineSpan ℝ ({A, B} : Set ℝ²) :=
by
  rw [hF]
  exact (orthogonalProjection (affineSpan ℝ ({A, B} : Set ℝ²)) C).property

theorem B_sub_A_mem_direction (A B : ℝ²) : B - A ∈ (affineSpan ℝ ({A, B} : Set ℝ²)).direction :=
by
  -- Show that B and A are in the affine span of the set {A, B}.
  -- `subset_affineSpan ℝ s` implies that any element in `s` is also in the generated `affineSpan`.
  have hB : B ∈ affineSpan ℝ ({A, B} : Set ℝ²) :=
    subset_affineSpan ℝ ({A, B} : Set ℝ²) (Or.inr rfl)

  have hA : A ∈ affineSpan ℝ ({A, B} : Set ℝ²) :=
    subset_affineSpan ℝ ({A, B} : Set ℝ²) (Or.inl rfl)

  -- `vsub_left_mem_direction_iff_mem` states that `B -ᵥ A ∈ s.direction ↔ A ∈ s` (given B ∈ s).
  -- Note: In EuclideanSpace, the vector difference operator `-ᵥ` is definitionally equal to `-`.
  exact (AffineSubspace.vsub_left_mem_direction_iff_mem hB A).mpr hA

theorem inner_sub_orthogonalProjection_eq_zero (s : AffineSubspace ℝ ℝ²)
    [Nonempty ↥s] [s.direction.HasOrthogonalProjection] (C v : ℝ²) (hv : v ∈ s.direction) :
    inner ℝ (C - ↑(orthogonalProjection s C)) v = (0 : ℝ) :=
by
  -- The projection of C onto s is an element of s.
  have hP_in_s : (↑(orthogonalProjection s C) : ℝ²) ∈ s :=
    (orthogonalProjection s C).property

  -- By the properties of orthogonal projection, projecting a point already in s yields the same point.
  -- We establish this by showing the distance between them is zero.
  have h_dist : dist (↑(orthogonalProjection s C)) ↑(orthogonalProjection s ↑(orthogonalProjection s C)) = 0 :=
    EuclideanGeometry.dist_orthogonalProjection_eq_zero_iff.mpr hP_in_s

  have h_eq : (↑(orthogonalProjection s C) : ℝ²) = ↑(orthogonalProjection s ↑(orthogonalProjection s C)) :=
    dist_eq_zero.mp h_dist

  -- Promote the equality of values back to an equality of the subtypes.
  have h_eq_s : orthogonalProjection s C = orthogonalProjection s ↑(orthogonalProjection s C) := by
    apply Subtype.ext
    exact h_eq

  -- Using the provided iff lemma, since projecting C and projecting its projection yield the same result,
  -- their difference vector must lie in the orthogonal complement of the subspace's direction.
  have h_vsub : C -ᵥ ↑(orthogonalProjection s C) ∈ s.directionᗮ :=
    EuclideanGeometry.orthogonalProjection_eq_orthogonalProjection_iff_vsub_mem.mp h_eq_s

  -- In a normed add torsor over itself like ℝ², vsub (-ᵥ) is definitionally equivalent to subtraction (-).
  have h_vsub2 : C - ↑(orthogonalProjection s C) ∈ s.directionᗮ :=
    h_vsub

  -- By definition of the orthogonal complement, the inner product of any vector in s.direction
  -- and our difference vector is zero. We commute the inner product to match the goal exactly.
  rw [real_inner_comm]
  exact h_vsub2 v hv

theorem inner_C_F_B_A_eq_zero (A B C F : ℝ²)
    (hF : F = ↑(orthogonalProjection (affineSpan ℝ ({A, B} : Set ℝ²)) C)) :
    inner ℝ (C - F) (B - A) = (0 : ℝ) :=
by
  rw [hF]
  have h_dir : B - A ∈ (affineSpan ℝ ({A, B} : Set ℝ²)).direction := B_sub_A_mem_direction A B
  exact inner_sub_orthogonalProjection_eq_zero (affineSpan ℝ ({A, B} : Set ℝ²)) C (B - A) h_dir

theorem B_ne_A_of_AffineIndependent (A B C : ℝ²)
    (tri : AffineIndependent ℝ ![A, B, C]) : B ≠ A :=
by
  intro h
  have h_eq : ![A, B, C] 0 = ![A, B, C] 1 := h.symm
  have h_idx_eq : (0 : Fin 3) = 1 := AffineIndependent.injective tri h_eq
  have h_idx_neq : (0 : Fin 3) ≠ 1 := by decide
  exact h_idx_neq h_idx_eq

theorem C_ne_A_of_AffineIndependent (A B C : ℝ²)
    (tri : AffineIndependent ℝ ![A, B, C]) : C ≠ A :=
by
  intro h
  have heq : ![A, B, C] 2 = ![A, B, C] 0 := by
    calc
      ![A, B, C] 2 = C := rfl
      _ = A := h
      _ = ![A, B, C] 0 := rfl
  have contra : (2 : Fin 3) = (0 : Fin 3) := tri.injective heq
  have hne : (2 : Fin 3) ≠ (0 : Fin 3) := by decide
  exact hne contra

theorem angle_eq_pi_div_two_of_inner_eq_zero (A B C : ℝ²)
    (h_inner : inner ℝ (C - A) (B - A) = (0 : ℝ))
    (hAB : B ≠ A) (hAC : C ≠ A) :
    EuclideanGeometry.angle C A B = Real.pi / 2 :=
by
  -- Provide the explicit vectors (C - A) and (B - A) to the iff theorem
  -- before applying .mp to transition from the inner product to the angle.
  exact (InnerProductGeometry.inner_eq_zero_iff_angle_eq_pi_div_two (C - A) (B - A)).mp h_inner

theorem acute_angle_C_A_B (A B C : ℝ²)
    (tri : AffineIndependent ℝ ![A, B, C])
    (h_acute : AcuteAngled ⟨![A, B, C], tri⟩) :
    EuclideanGeometry.angle C A B < Real.pi / 2 :=
by
  rw [Affine.Triangle.acuteAngled_iff_angle_lt] at h_acute
  exact h_acute.2.2

theorem F_ne_A (A B C F : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (h_acute : AcuteAngled ⟨![A, B, C], tri⟩)
    (hF : F = ↑(orthogonalProjection (affineSpan ℝ ({A, B} : Set ℝ²)) C)) :
    F ≠ A :=
by
  intro h
  have h1 : inner ℝ (C - F) (B - A) = (0 : ℝ) := inner_C_F_B_A_eq_zero A B C F hF
  have h2 : inner ℝ (C - A) (B - A) = (0 : ℝ) := by
    rw [h] at h1
    exact h1
  have hAB : B ≠ A := B_ne_A_of_AffineIndependent A B C tri
  have hAC : C ≠ A := C_ne_A_of_AffineIndependent A B C tri
  have h3 : EuclideanGeometry.angle C A B = Real.pi / 2 := angle_eq_pi_div_two_of_inner_eq_zero A B C h2 hAB hAC
  have h4 : EuclideanGeometry.angle C A B < Real.pi / 2 := acute_angle_C_A_B A B C tri h_acute
  rw [h3] at h4
  exact lt_irrefl _ h4

theorem mem_span_A_F_of_F_mem_span_A_B (A B F : ℝ²)
    (hF : F ∈ affineSpan ℝ ({A, B} : Set ℝ²)) (hFA : F ≠ A) :
    B ∈ affineSpan ℝ ({A, F} : Set ℝ²) :=
by
  -- Translate the span inclusion into the existence of a scalar `t` via the line map
  rw [mem_affineSpan_pair_iff_exists_lineMap_eq] at hF
  rcases hF with ⟨t, ht⟩
  rw [AffineMap.lineMap_apply] at ht

  -- Show that t cannot be zero, otherwise F would equal A
  have ht0 : t ≠ 0 := by
    rintro rfl
    rw [zero_smul, zero_vadd] at ht
    exact hFA ht.symm

  -- Rewrite the line equation equivalently into vector differences
  have eq1 : t • (B -ᵥ A) = F -ᵥ A := by
    rw [← ht, vadd_vsub]

  -- Express point B as an affine combination of A and F
  have eq2 : B = t⁻¹ • (F -ᵥ A) +ᵥ A := by
    rw [← eq1, smul_smul, inv_mul_cancel₀ ht0, one_smul, vsub_vadd]

  -- Substitute B in our target goal and use the provided helper lemma to close the proof
  rw [eq2]
  exact smul_vsub_vadd_mem_affineSpan_pair t⁻¹ A F

theorem B_mem_span_A_F (A B C F : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (h_acute : AcuteAngled ⟨![A, B, C], tri⟩)
    (hF : F = ↑(orthogonalProjection (affineSpan ℝ ({A, B} : Set ℝ²)) C)) :
    B ∈ affineSpan ℝ ({A, F} : Set ℝ²) :=
by
  have h_F_span : F ∈ affineSpan ℝ ({A, B} : Set ℝ²) := F_mem_span_A_B A B C F hF
  have h_FA : F ≠ A := F_ne_A A B C F tri h_acute hF
  exact mem_span_A_F_of_F_mem_span_A_B A B F h_F_span h_FA

theorem X_Y_in_span_B_C (B C X Y : ℝ²) (hCol : Collinear ℝ ({X, Y, B, C} : Set ℝ²)) (hXY : X ≠ Y) (hBC : B ≠ C) :
    X ∈ affineSpan ℝ ({B, C} : Set ℝ²) ∧ Y ∈ affineSpan ℝ ({B, C} : Set ℝ²) :=
by
  have hX : X ∈ ({X, Y, B, C} : Set ℝ²) := by simp
  have hY : Y ∈ ({X, Y, B, C} : Set ℝ²) := by simp
  have hB : B ∈ ({X, Y, B, C} : Set ℝ²) := by simp
  have hC : C ∈ ({X, Y, B, C} : Set ℝ²) := by simp
  constructor
  · exact Collinear.mem_affineSpan_of_mem_of_ne hCol hB hC hX hBC
  · exact Collinear.mem_affineSpan_of_mem_of_ne hCol hB hC hY hBC

theorem spans_eq_of_collinear (B C X Y D : ℝ²)
    (hCol : Collinear ℝ ({X, Y, B, C} : Set ℝ²)) (hXY : X ≠ Y) (hBC : B ≠ C)
    (hD : D ∈ affineSpan ℝ ({B, C} : Set ℝ²)) :
    B ∈ affineSpan ℝ ({X, Y} : Set ℝ²) ∧ D ∈ affineSpan ℝ ({X, Y} : Set ℝ²) :=
by
  have hXs : X ∈ ({X, Y, B, C} : Set ℝ²) := by simp
  have hYs : Y ∈ ({X, Y, B, C} : Set ℝ²) := by simp
  have hBs : B ∈ ({X, Y, B, C} : Set ℝ²) := by simp
  have hCs : C ∈ ({X, Y, B, C} : Set ℝ²) := by simp

  have hB : B ∈ affineSpan ℝ ({X, Y} : Set ℝ²) :=
    Collinear.mem_affineSpan_of_mem_of_ne hCol hXs hYs hBs hXY

  have h1 : affineSpan ℝ ({B, C} : Set ℝ²) = affineSpan ℝ ({X, Y, B, C} : Set ℝ²) :=
    Collinear.affineSpan_eq_of_ne hCol hBs hCs hBC

  have h2 : affineSpan ℝ ({X, Y} : Set ℝ²) = affineSpan ℝ ({X, Y, B, C} : Set ℝ²) :=
    Collinear.affineSpan_eq_of_ne hCol hXs hYs hXY

  have h3 : affineSpan ℝ ({B, C} : Set ℝ²) = affineSpan ℝ ({X, Y} : Set ℝ²) :=
    h1.trans h2.symm

  have hD' : D ∈ affineSpan ℝ ({X, Y} : Set ℝ²) := by
    rw [← h3]
    exact hD

  exact ⟨hB, hD'⟩

theorem angle_A_B_C_lt_pi_div_two (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (h_acute : AcuteAngled ⟨![A, B, C], tri⟩) :
    EuclideanGeometry.angle A B C < Real.pi / 2 :=
(Affine.Triangle.acuteAngled_iff_angle_lt.mp h_acute).1

theorem inner_A_B_C_B_eq_zero_of_D_eq_B (A B C D : ℝ²)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A))
    (h : D = B) :
    inner ℝ (A - B) (C - B) = (0 : ℝ) :=
by
  -- Show that the projection evaluated perfectly at B
  have hB : ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A) = B := by
    rw [h] at hD
    exact hD.symm

  -- Obtain the orthogonal property of the projection A -ᵥ Projection ∈ directionᗮ
  have h_proj : A -ᵥ ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A) ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).directionᗮ :=
    vsub_orthogonalProjection_mem_direction_orthogonal (affineSpan ℝ ({B, C} : Set ℝ²)) A

  -- Carefully rewrite the projection to B exclusively in `h_proj`
  rw [hB] at h_proj

  -- Explicitly verify that C - B belongs to the direction space
  have hC : C ∈ ({B, C} : Set ℝ²) := Set.mem_insert_iff.mpr (Or.inr rfl)
  have hB_set : B ∈ ({B, C} : Set ℝ²) := Set.mem_insert_iff.mpr (Or.inl rfl)
  have h_dir : C -ᵥ B ∈ (affineSpan ℝ ({B, C} : Set ℝ²)).direction := by
    rw [direction_affineSpan]
    exact vsub_mem_vectorSpan ℝ hC hB_set

  -- Apply the submodule's orthogonal condition inner(v, u) = 0 for vectors in the direction
  -- We use mem_orthogonal' which places the vectors in exactly the inner(v, u) orientation we need
  have h_ans : inner ℝ (A -ᵥ B) (C -ᵥ B) = (0 : ℝ) := by
    have h_ortho_iff := Submodule.mem_orthogonal' (affineSpan ℝ ({B, C} : Set ℝ²)).direction (A -ᵥ B)
    exact h_ortho_iff.mp h_proj (C -ᵥ B) h_dir

  -- Convert standard vector subtraction (-ᵥ) to regular subtraction (-) because ℝ² acts over itself
  have h_sub_A : A -ᵥ B = A - B := rfl
  have h_sub_C : C -ᵥ B = C - B := rfl
  rw [h_sub_A, h_sub_C] at h_ans

  exact h_ans

theorem A_ne_B (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C]) : A ≠ B :=
by
  intro h
  have h_eq : ![A, B, C] (0 : Fin 3) = ![A, B, C] (1 : Fin 3) := h
  have h_idx : (0 : Fin 3) = (1 : Fin 3) := AffineIndependent.injective tri h_eq
  revert h_idx
  decide

theorem C_ne_B (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C]) : C ≠ B :=
by
  intro h
  have h_inj := AffineIndependent.injective tri
  have h_neq : (2 : Fin 3) ≠ (1 : Fin 3) := by decide
  apply h_neq
  apply h_inj
  exact h

theorem D_ne_B (A B C D : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (h_acute : AcuteAngled ⟨![A, B, C], tri⟩)
    (hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)) :
    D ≠ B :=
by
  intro h
  have hA : A ≠ B := A_ne_B A B C tri
  have hC : C ≠ B := C_ne_B A B C tri
  have h1 : inner ℝ (A - B) (C - B) = (0 : ℝ) := inner_A_B_C_B_eq_zero_of_D_eq_B A B C D hD h
  have h2 : EuclideanGeometry.angle A B C = Real.pi / 2 := angle_eq_pi_div_two_of_inner_eq_zero B C A h1 hC hA
  have h3 : EuclideanGeometry.angle A B C < Real.pi / 2 := angle_A_B_C_lt_pi_div_two A B C tri h_acute
  rw [h2] at h3
  exact lt_irrefl _ h3

theorem algebraic_identity (X Y B C D : ℝ²)
    (h1 : inner ℝ (X - B) (Y - B) = inner ℝ (D - B) (C - B))
    (h2 : inner ℝ (X - D) (Y - D) = inner ℝ (B - D) (C - D))
    (hD_line : D ∈ affineSpan ℝ ({B, C} : Set ℝ²))
    (hX_line : X ∈ affineSpan ℝ ({B, C} : Set ℝ²))
    (hY_line : Y ∈ affineSpan ℝ ({B, C} : Set ℝ²))
    (hD_ne_B : D ≠ B) :
    C = midpoint ℝ X Y :=
by
  have ⟨x, hx⟩ : ∃ x : ℝ, x • (C - B) = X - B := by
    have eq : (X - B) +ᵥ B = X := by
      rw [vadd_eq_add, sub_add_cancel]
    have h1_X : (X - B) +ᵥ B ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
      rw [eq]
      exact hX_line
    exact vadd_left_mem_affineSpan_pair.mp h1_X

  have ⟨y, hy⟩ : ∃ y : ℝ, y • (C - B) = Y - B := by
    have eq : (Y - B) +ᵥ B = Y := by
      rw [vadd_eq_add, sub_add_cancel]
    have h1_Y : (Y - B) +ᵥ B ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
      rw [eq]
      exact hY_line
    exact vadd_left_mem_affineSpan_pair.mp h1_Y

  have ⟨d, hd⟩ : ∃ d : ℝ, d • (C - B) = D - B := by
    have eq : (D - B) +ᵥ B = D := by
      rw [vadd_eq_add, sub_add_cancel]
    have h1_D : (D - B) +ᵥ B ∈ affineSpan ℝ ({B, C} : Set ℝ²) := by
      rw [eq]
      exact hD_line
    exact vadd_left_mem_affineSpan_pair.mp h1_D

  have eq1 : inner ℝ (X - B) (Y - B) = (x * y) * inner ℝ (C - B) (C - B) := by
    calc inner ℝ (X - B) (Y - B)
      _ = inner ℝ (x • (C - B)) (y • (C - B)) := by rw [← hx, ← hy]
      _ = x * inner ℝ (C - B) (y • (C - B)) := by rw [real_inner_smul_left]
      _ = x * inner ℝ (y • (C - B)) (C - B) := by rw [real_inner_comm]
      _ = x * (y * inner ℝ (C - B) (C - B)) := by rw [real_inner_smul_left]
      _ = (x * y) * inner ℝ (C - B) (C - B) := by ring

  have eq2 : inner ℝ (D - B) (C - B) = d * inner ℝ (C - B) (C - B) := by
    calc inner ℝ (D - B) (C - B)
      _ = inner ℝ (d • (C - B)) (C - B) := by rw [← hd]
      _ = d * inner ℝ (C - B) (C - B) := by rw [real_inner_smul_left]

  have hCB_ne_zero : C - B ≠ 0 := by
    intro h
    have hd_zero : D - B = 0 := by
      rw [← hd, h, smul_zero]
    have : D = B := by exact sub_eq_zero.mp hd_zero
    exact hD_ne_B this

  have h_inner_ne_zero : inner ℝ (C - B) (C - B) ≠ (0 : ℝ) := by
    intro h
    have h1 : ‖C - B‖ ^ 2 = (0 : ℝ) := by
      rw [← real_inner_self_eq_norm_sq (C - B), h]
    have h2 : ‖C - B‖ * ‖C - B‖ = 0 := by
      calc ‖C - B‖ * ‖C - B‖
        _ = ‖C - B‖ ^ 2 := by ring
        _ = 0 := h1
    cases mul_eq_zero.mp h2 with
    | inl h_zero => exact hCB_ne_zero (norm_eq_zero.mp h_zero)
    | inr h_zero => exact hCB_ne_zero (norm_eq_zero.mp h_zero)

  have h_xy_eq_d : x * y = d := by
    have h1_sub : (x * y - d) * inner ℝ (C - B) (C - B) = 0 := by
      calc
        (x * y - d) * inner ℝ (C - B) (C - B) = (x * y) * inner ℝ (C - B) (C - B) - d * inner ℝ (C - B) (C - B) := by ring
        _ = inner ℝ (X - B) (Y - B) - inner ℝ (D - B) (C - B) := by rw [← eq1, ← eq2]
        _ = 0 := by rw [h1, sub_self]
    cases mul_eq_zero.mp h1_sub with
    | inl h_zero => exact sub_eq_zero.mp h_zero
    | inr h_zero => exact False.elim (h_inner_ne_zero h_zero)

  have hXD : X - D = (x - d) • (C - B) := by
    calc
      X - D = (X - B) - (D - B) := by abel
      _ = x • (C - B) - d • (C - B) := by rw [← hx, ← hd]
      _ = (x - d) • (C - B) := (sub_smul x d (C - B)).symm

  have hYD : Y - D = (y - d) • (C - B) := by
    calc
      Y - D = (Y - B) - (D - B) := by abel
      _ = y • (C - B) - d • (C - B) := by rw [← hy, ← hd]
      _ = (y - d) • (C - B) := (sub_smul y d (C - B)).symm

  have hBD : B - D = (-d) • (C - B) := by
    calc
      B - D = - (D - B) := by abel
      _ = - (d • (C - B)) := by rw [← hd]
      _ = (-d) • (C - B) := (neg_smul d (C - B)).symm

  have hCD : C - D = ((1 : ℝ) - d) • (C - B) := by
    calc
      C - D = (C - B) - (D - B) := by abel
      _ = (C - B) - d • (C - B) := by rw [← hd]
      _ = (1 : ℝ) • (C - B) - d • (C - B) := by rw [one_smul]
      _ = ((1 : ℝ) - d) • (C - B) := (sub_smul (1 : ℝ) d (C - B)).symm

  have eq3 : inner ℝ (X - D) (Y - D) = ((x - d) * (y - d)) * inner ℝ (C - B) (C - B) := by
    calc inner ℝ (X - D) (Y - D)
      _ = inner ℝ ((x - d) • (C - B)) ((y - d) • (C - B)) := by rw [hXD, hYD]
      _ = (x - d) * inner ℝ (C - B) ((y - d) • (C - B)) := by rw [real_inner_smul_left]
      _ = (x - d) * inner ℝ ((y - d) • (C - B)) (C - B) := by rw [real_inner_comm]
      _ = (x - d) * ((y - d) * inner ℝ (C - B) (C - B)) := by rw [real_inner_smul_left]
      _ = ((x - d) * (y - d)) * inner ℝ (C - B) (C - B) := by ring

  have eq4 : inner ℝ (B - D) (C - D) = ((-d) * ((1 : ℝ) - d)) * inner ℝ (C - B) (C - B) := by
    calc inner ℝ (B - D) (C - D)
      _ = inner ℝ ((-d) • (C - B)) (((1 : ℝ) - d) • (C - B)) := by rw [hBD, hCD]
      _ = (-d) * inner ℝ (C - B) (((1 : ℝ) - d) • (C - B)) := by rw [real_inner_smul_left]
      _ = (-d) * inner ℝ (((1 : ℝ) - d) • (C - B)) (C - B) := by rw [real_inner_comm]
      _ = (-d) * (((1 : ℝ) - d) * inner ℝ (C - B) (C - B)) := by rw [real_inner_smul_left]
      _ = ((-d) * ((1 : ℝ) - d)) * inner ℝ (C - B) (C - B) := by ring

  have h2_sub : ((x - d) * (y - d) - (-d) * ((1 : ℝ) - d)) * inner ℝ (C - B) (C - B) = 0 := by
    calc
      ((x - d) * (y - d) - (-d) * ((1 : ℝ) - d)) * inner ℝ (C - B) (C - B)
        = ((x - d) * (y - d)) * inner ℝ (C - B) (C - B) - ((-d) * ((1 : ℝ) - d)) * inner ℝ (C - B) (C - B) := by ring
      _ = inner ℝ (X - D) (Y - D) - inner ℝ (B - D) (C - D) := by rw [← eq3, ← eq4]
      _ = 0 := by rw [h2, sub_self]

  have h_poly : (x - d) * (y - d) = (-d) * ((1 : ℝ) - d) := by
    cases mul_eq_zero.mp h2_sub with
    | inl h_zero => exact sub_eq_zero.mp h_zero
    | inr h_zero => exact False.elim (h_inner_ne_zero h_zero)

  have hd_ne_zero : d ≠ 0 := by
    intro h
    have : D - B = 0 := by rw [← hd, h, zero_smul]
    have : D = B := sub_eq_zero.mp this
    exact hD_ne_B this

  have h_sum : x + y = (2 : ℝ) := by
    have h_alg : d * (x + y - (2 : ℝ)) = (x * y - d) - ((x - d) * (y - d) - (-d) * ((1 : ℝ) - d)) := by ring
    have h_xy_sub : x * y - d = 0 := sub_eq_zero.mpr h_xy_eq_d
    have h_poly_sub : (x - d) * (y - d) - (-d) * ((1 : ℝ) - d) = 0 := sub_eq_zero.mpr h_poly
    rw [h_xy_sub, h_poly_sub, sub_zero] at h_alg
    cases mul_eq_zero.mp h_alg with
    | inl h_zero => exact False.elim (hd_ne_zero h_zero)
    | inr h_zero => exact sub_eq_zero.mp h_zero

  have h_mid : midpoint ℝ X Y - B = C - B := by
    have h_vsub : midpoint ℝ X Y -ᵥ B = (⅟(2 : ℝ)) • (X -ᵥ B) + (⅟(2 : ℝ)) • (Y -ᵥ B) := midpoint_vsub X Y B
    calc midpoint ℝ X Y - B
      _ = midpoint ℝ X Y -ᵥ B := (vsub_eq_sub (midpoint ℝ X Y) B).symm
      _ = (⅟(2 : ℝ)) • (X -ᵥ B) + (⅟(2 : ℝ)) • (Y -ᵥ B) := h_vsub
      _ = (⅟(2 : ℝ)) • (X - B) + (⅟(2 : ℝ)) • (Y - B) := by rw [vsub_eq_sub, vsub_eq_sub]
      _ = (⅟(2 : ℝ)) • (x • (C - B)) + (⅟(2 : ℝ)) • (y • (C - B)) := by rw [← hx, ← hy]
      _ = ((⅟(2 : ℝ)) * x) • (C - B) + ((⅟(2 : ℝ)) * y) • (C - B) := by rw [smul_smul, smul_smul]
      _ = ((⅟(2 : ℝ)) * x + (⅟(2 : ℝ)) * y) • (C - B) := by rw [← add_smul]
      _ = ((⅟(2 : ℝ)) * (x + y)) • (C - B) := by
        have h_coeff : (⅟(2 : ℝ)) * x + (⅟(2 : ℝ)) * y = (⅟(2 : ℝ)) * (x + y) := by ring
        rw [h_coeff]
      _ = ((⅟(2 : ℝ)) * (2 : ℝ)) • (C - B) := by rw [h_sum]
      _ = (1 : ℝ) • (C - B) := by
        have h_inv : (⅟(2 : ℝ)) * (2 : ℝ) = 1 := invOf_mul_self (2 : ℝ)
        rw [h_inv]
      _ = C - B := by rw [one_smul]

  calc
    C = (C - B) + B := (sub_add_cancel C B).symm
    _ = (midpoint ℝ X Y - B) + B := by rw [← h_mid]
    _ = midpoint ℝ X Y := sub_add_cancel (midpoint ℝ X Y) B

theorem mem_five_set_1 {α : Type*} (a b c d e : α) : a ∈ ({a, b, c, d, e} : Set α) :=
by
  simp

theorem mem_five_set_2 {α : Type*} (a b c d e : α) : b ∈ ({a, b, c, d, e} : Set α) :=
by
  exact Or.inr (Or.inl rfl)

theorem mem_five_set_3 {α : Type*} (a b c d e : α) : c ∈ ({a, b, c, d, e} : Set α) :=
by
  simp

theorem mem_five_set_4 {α : Type*} (a b c d e : α) : d ∈ ({a, b, c, d, e} : Set α) :=
by
  simp

theorem mem_five_set_5 {α : Type*} (a b c d e : α) : e ∈ ({a, b, c, d, e} : Set α) :=
by
  simp

theorem PBAdvanced028 (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (h_acute : AcuteAngled ⟨![A, B, C], tri⟩)
    (H : ℝ²) (hH : H = Triangle.orthocenter ⟨![A, B, C], tri⟩)
    (F : ℝ²) (hF : F = altitudeFoot ⟨![A, B, C], tri⟩ 2)
    (P : ℝ²) (hP : P = reflection (affineSpan ℝ {B, C}) H)
    (X Y : ℝ²) (hXY : X ≠ Y ∧ Collinear ℝ {X, Y, B, C} ∧ Cospherical {X, Y, A, F, P}) : C = midpoint ℝ X Y :=
by

  let D : ℝ² := ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A)
  have hD : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) A) := rfl

  have hBC : B ≠ C := B_ne_C A B C tri
  have hD_in_BC : D ∈ affineSpan ℝ ({B, C} : Set ℝ²) := orthogonalProjection_mem_span A B C

  have hX_in_BC : X ∈ affineSpan ℝ ({B, C} : Set ℝ²) := (X_Y_in_span_B_C B C X Y hXY.2.1 hXY.1 hBC).1
  have hY_in_BC : Y ∈ affineSpan ℝ ({B, C} : Set ℝ²) := (X_Y_in_span_B_C B C X Y hXY.2.1 hXY.1 hBC).2

  have hB_in_XY : B ∈ affineSpan ℝ ({X, Y} : Set ℝ²) := (spans_eq_of_collinear B C X Y D hXY.2.1 hXY.1 hBC hD_in_BC).1
  have hD_in_XY : D ∈ affineSpan ℝ ({X, Y} : Set ℝ²) := (spans_eq_of_collinear B C X Y D hXY.2.1 hXY.1 hBC hD_in_BC).2

  have hD_proj_H : D = ↑(orthogonalProjection (affineSpan ℝ ({B, C} : Set ℝ²)) H) := orthocenter_proj_eq A B C H D tri hH hD
  have hP_sub_D : P - D = -(H - D) := reflection_eq_sub B C H D P hD_proj_H hP

  have hD_in_AP : D ∈ affineSpan ℝ ({A, P} : Set ℝ²) := D_mem_span_A_P A B C H D P tri h_acute hH hD hP_sub_D

  have hF_proj : F = ↑(orthogonalProjection (affineSpan ℝ ({A, B} : Set ℝ²)) C) := Eq.trans hF (altitudeFoot_two_eq A B C tri)
  have hB_in_AF : B ∈ affineSpan ℝ ({A, F} : Set ℝ²) := B_mem_span_A_F A B C F tri h_acute hF_proj

  have hCosph : ∃ O R, ∀ p ∈ ({X, Y, A, F, P} : Set ℝ²), ‖p - O‖ = R := cospherical_def' hXY.2.2
  rcases hCosph with ⟨O, R, hOR⟩

  have hX_O : ‖X - O‖ = R := hOR X (mem_five_set_1 X Y A F P)
  have hY_O : ‖Y - O‖ = R := hOR Y (mem_five_set_2 X Y A F P)
  have hA_O : ‖A - O‖ = R := hOR A (mem_five_set_3 X Y A F P)
  have hF_O : ‖F - O‖ = R := hOR F (mem_five_set_4 X Y A F P)
  have hP_O : ‖P - O‖ = R := hOR P (mem_five_set_5 X Y A F P)

  -- Extract the first power of point relation mapping
  have hXYD : inner ℝ (X - D) (Y - D) = ‖D - O‖^2 - R^2 := power_of_point_span hX_O hY_O hD_in_XY
  have hAPD : inner ℝ (A - D) (P - D) = ‖D - O‖^2 - R^2 := power_of_point_span hA_O hP_O hD_in_AP
  have hXYD_eq_APD : inner ℝ (X - D) (Y - D) = inner ℝ (A - D) (P - D) := Eq.trans hXYD hAPD.symm

  have hAPD_eq_neg_AHD : inner ℝ (A - D) (P - D) = -inner ℝ (A - D) (H - D) := inner_A_D_P_D A H D P hP_sub_D
  have hBD_CD : inner ℝ (B - D) (C - D) = -inner ℝ (A - D) (H - D) := inner_B_D_C_D A B C H D tri hH hD

  have hXYD_eq_BDCD : inner ℝ (X - D) (Y - D) = inner ℝ (B - D) (C - D) := by
    rw [hXYD_eq_APD]
    rw [hAPD_eq_neg_AHD]
    rw [← hBD_CD]

  -- Extract the second power of point relation mapping
  have hXYB : inner ℝ (X - B) (Y - B) = ‖B - O‖^2 - R^2 := power_of_point_span hX_O hY_O hB_in_XY
  have hAFB : inner ℝ (A - B) (F - B) = ‖B - O‖^2 - R^2 := power_of_point_span hA_O hF_O hB_in_AF
  have hXYB_eq_AFB : inner ℝ (X - B) (Y - B) = inner ℝ (A - B) (F - B) := Eq.trans hXYB hAFB.symm

  have hABFB : inner ℝ (A - B) (F - B) = inner ℝ (A - B) (C - B) := inner_A_B_F_B A B C F hF_proj
  have hDBCB : inner ℝ (D - B) (C - B) = inner ℝ (A - B) (C - B) := inner_D_B_C_B A B C D hD

  have hXYB_eq_DBCB : inner ℝ (X - B) (Y - B) = inner ℝ (D - B) (C - B) := by
    rw [hXYB_eq_AFB]
    rw [hABFB]
    rw [← hDBCB]

  have hD_ne_B : D ≠ B := D_ne_B A B C D tri h_acute hD

  exact algebraic_identity X Y B C D hXYB_eq_DBCB hXYD_eq_BDCD hD_in_BC hX_in_BC hY_in_BC hD_ne_B
