import Mathlib
open Real
open Affine
open Simplex
open EuclideanGeometry
local notation "ℝ²" => EuclideanSpace ℝ (Fin 2)

theorem altitudeFoot_1_mem_span (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C]) :
  altitudeFoot ⟨![A, B, C], tri⟩ 1 ∈ affineSpan ℝ {A, C} :=
by
  have h := Affine.Simplex.altitudeFoot_mem_affineSpan_faceOpposite ⟨![A, B, C], tri⟩ 1
  have h_range : Set.range (Affine.Simplex.faceOpposite ⟨![A, B, C], tri⟩ 1).points = {A, C} := by
    -- Expand to the image of the original simplex points to avoid getting stuck on `Fin.succAbove`'s internal conditional
    rw [Affine.Simplex.range_faceOpposite_points]
    ext x
    simp only [Set.mem_image, Set.mem_compl_iff, Set.mem_singleton_iff, Set.mem_insert_iff]
    constructor
    · rintro ⟨y, hy, rfl⟩
      fin_cases y
      · exact Or.inl rfl
      · exact False.elim (hy rfl)
      · exact Or.inr rfl
    · rintro (rfl | rfl)
      · exact ⟨0, by decide, rfl⟩
      · exact ⟨2, by decide, rfl⟩
  rw [h_range] at h
  exact h

theorem B_sub_altitudeFoot_1_ortho_A_sub_C (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C]) :
  inner ℝ (B - altitudeFoot ⟨![A, B, C], tri⟩ 1) (A - C) = (0 : ℝ) :=
by
  let S : Affine.Simplex ℝ ℝ² 2 := ⟨![A, B, C], tri⟩
  let D := altitudeFoot S 1
  have hD : S.altitudeFoot 1 = D := rfl

  -- The tactic sequence runs linearly on proper formats
  have h0 : (1 : Fin 3) ≠ (0 : Fin 3) := by decide
  have h2 : (1 : Fin 3) ≠ (2 : Fin 3) := by decide

  -- Let Lean infer the type natively to prevent the `whnf` timeout
  have H1 := Affine.Simplex.inner_vsub_vsub_altitudeFoot_eq_height_sq S h0
  have H2 := Affine.Simplex.inner_vsub_vsub_altitudeFoot_eq_height_sq S h2

  -- Combine the equalities algebraically
  have h3 := Eq.trans H2 (Eq.symm H1)
  have h4 : _ - _ = (0 : ℝ) := sub_eq_zero.mpr h3

  have hp0 : S.points 0 = A := rfl
  have hp1 : S.points 1 = B := rfl
  have hp2 : S.points 2 = C := rfl

  -- Systematically eliminate `vsub` and apply standard simplex points to match our variables
  simp only [vsub_eq_sub] at h4
  simp only [hD, hp0, hp1, hp2] at h4
  simp only [inner_sub_left, inner_sub_right] at h4

  -- Unfold goal definitions to identically match our standard vectors
  show inner ℝ (B - D) (A - C) = (0 : ℝ)
  simp only [inner_sub_left, inner_sub_right]

  -- Symmetrize the inner products into standardized pairs to allow `linarith` to map out the equations.
  -- Notice the alignment: `real_inner_comm A B` outputs type `inner ℝ B A = inner ℝ A B`.
  have hBA : inner ℝ B A = inner ℝ A B := real_inner_comm A B
  have hCA : inner ℝ C A = inner ℝ A C := real_inner_comm A C
  have hDA : inner ℝ D A = inner ℝ A D := real_inner_comm A D
  have hCB : inner ℝ C B = inner ℝ B C := real_inner_comm B C
  have hDB : inner ℝ D B = inner ℝ B D := real_inner_comm B D
  have hDC : inner ℝ D C = inner ℝ C D := real_inner_comm C D

  simp only [hBA, hCA, hDA, hCB, hDB, hDC] at h4 ⊢

  -- The transformed `h4` restriction constraint matches algebraically precisely with the Goal
  linarith

theorem exists_k_of_mem_span_pair_r2 (A C D : ℝ²) (h : D ∈ affineSpan ℝ {A, C}) :
  ∃ k : ℝ, D - C = k • (A - C) :=
by
  have hC : C ∈ affineSpan ℝ {A, C} := right_mem_affineSpan_pair ℝ A C
  have hdir : D -ᵥ C ∈ (affineSpan ℝ {A, C}).direction := AffineSubspace.vsub_mem_direction h hC
  rw [direction_affineSpan] at hdir
  rw [vectorSpan_pair ℝ A C] at hdir
  rw [Submodule.mem_span_singleton] at hdir
  rcases hdir with ⟨k, hk⟩
  use k
  -- By definition, `vsub` (-ᵥ) in the vector space acting on itself is just subtraction (-).
  -- Thus, `hk : k • (A - C) = D - C` definitionally.
  exact hk.symm

theorem sub_sub_sub_cancel_r2 (B C D : ℝ²) :
  B - D = (B - C) - (D - C) :=
by
  abel

theorem inner_sub_left_r2 (x y z : ℝ²) :
  inner ℝ (x - y) z = inner ℝ x z - inner ℝ y z :=
by
  exact inner_sub_left x y z

theorem D_prop (A B C D : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
  (hD : D = altitudeFoot ⟨![A, B, C], tri⟩ 1) :
  inner ℝ (D - C) (A - C) = inner ℝ (B - C) (A - C) ∧ ∃ k : ℝ, D - C = k • (A - C) :=
by
  constructor
  · -- Subgoal 1: Inner Product Equality
    have h1 : inner ℝ (B - D) (A - C) = (0 : ℝ) := by
      rw [hD]
      exact B_sub_altitudeFoot_1_ortho_A_sub_C A B C tri

    -- Express (B - D) as (B - C) - (D - C) and split the inner product
    rw [sub_sub_sub_cancel_r2 B C D, inner_sub_left_r2] at h1

    -- Using the derived `inner ℝ (B - C) (A - C) - inner ℝ (D - C) (A - C) = 0`, linarith deduces equality
    linarith

  · -- Subgoal 2: Existence of the Scalar Witness
    have h_span : D ∈ affineSpan ℝ {A, C} := by
      rw [hD]
      exact altitudeFoot_1_mem_span A B C tri

    exact exists_k_of_mem_span_pair_r2 A C D h_span

theorem E_sub_C_ortho_A_sub_B (A B C E : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
  (hE : E = altitudeFoot ⟨![A, B, C], tri⟩ 2) :
  inner ℝ (E - C) (A - B) = (0 : ℝ) :=
by
  let s : Affine.Simplex ℝ ℝ² 2 := ⟨![A, B, C], tri⟩

  -- The inner product spanning from altitude vertex to other vertices identically matches the squared height.
  have hA' : (2 : Fin 3) ≠ (0 : Fin 3) := by decide
  have hA := Affine.Simplex.inner_vsub_vsub_altitudeFoot_eq_height_sq s hA'

  have hB' : (2 : Fin 3) ≠ (1 : Fin 3) := by decide
  have hB := Affine.Simplex.inner_vsub_vsub_altitudeFoot_eq_height_sq s hB'

  -- Map structural coordinates to original variables
  have hc : s.points (2 : Fin 3) = C := rfl
  have ha : s.points (0 : Fin 3) = A := rfl
  have hb : s.points (1 : Fin 3) = B := rfl
  have he : s.altitudeFoot (2 : Fin 3) = E := hE.symm

  rw [ha, hc, he] at hA
  change inner ℝ (C - A) (C - E) = s.height (2 : Fin 3) ^ 2 at hA

  rw [hb, hc, he] at hB
  change inner ℝ (C - B) (C - E) = s.height (2 : Fin 3) ^ 2 at hB

  -- Decompose the differences algebraically
  have h1 : A - B = (C - B) - (C - A) := by abel
  have h2 : E - C = -(C - E) := by abel

  -- Subsitute definitions back into the primary target
  calc inner ℝ (E - C) (A - B)
    _ = inner ℝ (A - B) (E - C) := by rw [real_inner_comm (E - C) (A - B)]
    _ = inner ℝ ((C - B) - (C - A)) (E - C) := by rw [h1]
    _ = inner ℝ ((C - B) - (C - A)) (-(C - E)) := by rw [h2]
    _ = - inner ℝ ((C - B) - (C - A)) (C - E) := by rw [inner_neg_right]
    _ = - (inner ℝ (C - B) (C - E) - inner ℝ (C - A) (C - E)) := by rw [inner_sub_left]
    _ = - (s.height (2 : Fin 3) ^ 2 - s.height (2 : Fin 3) ^ 2) := by rw [hB, hA]
    _ = (0 : ℝ) := by ring

theorem E_prop_1_main (A B C E : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
  (hE : E = altitudeFoot ⟨![A, B, C], tri⟩ 2) :
  inner ℝ (E - C) (A - C) = inner ℝ (E - C) (B - C) :=
by
  -- Obtain the orthogonality relation from the lemma
  have h1 : inner ℝ (E - C) (A - B) = (0 : ℝ) := E_sub_C_ortho_A_sub_B A B C E tri hE

  -- Vector decomposition of the base
  have h2 : A - B = (A - C) - (B - C) := by abel

  -- Substitute the decomposition into the orthogonality relation
  rw [h2] at h1

  -- Distribute the inner product over the vector subtraction
  rw [inner_sub_right] at h1

  -- Rearrange to conclude the final goal
  exact sub_eq_zero.mp h1

theorem inner_E_sub_C_A_sub_E (A B C E : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
  (hE : E = altitudeFoot ⟨![A, B, C], tri⟩ 2) :
  inner ℝ (E - C) (A - E) = (0 : ℝ) :=
by
  let s : Affine.Simplex ℝ ℝ² 2 := ⟨![A, B, C], tri⟩

  -- Obtain the projection property of the altitude over the chosen face (C pointing to A)
  have h_neq : (2 : Fin 3) ≠ (0 : Fin 3) := by decide
  have h1 := s.inner_vsub_vsub_altitudeFoot_eq_height_sq h_neq

  -- Rewrite evaluations directly with respect to geometric parameter E
  have hE_eq : s.altitudeFoot (2 : Fin 3) = E := hE.symm
  rw [hE_eq] at h1

  -- Coerce underlying affine point differences (vsub) into standard Euclidean vector displacements (sub)
  have h_vsub1 : s.points (2 : Fin 3) -ᵥ s.points (0 : Fin 3) = C - A := by
    rw [vsub_eq_sub]
    rfl
  have h_vsub2 : s.points (2 : Fin 3) -ᵥ E = C - E := by
    rw [vsub_eq_sub]
    rfl
  rw [h_vsub1, h_vsub2] at h1

  -- Evaluate definition of height dynamically via orthogonal projection distance
  have h2 : s.height (2 : Fin 3) = dist C E := by
    change dist (s.points (2 : Fin 3)) (s.altitudeFoot (2 : Fin 3)) = dist C E
    rw [hE_eq]
    rfl
  rw [h2] at h1

  -- Re-convert the Euclidean distance to standard inner product norm expansion
  have h3 : dist C E ^ 2 = inner ℝ (C - E) (C - E) := by
    rw [dist_eq_norm]
    rw [← real_inner_self_eq_norm_sq (C - E)]

  rw [h3] at h1

  -- Reframe the goal vectors E - C and A - E structurally into derivations of C - E and C - A
  have h4 : A - E = (C - E) - (C - A) := by abel
  have h5 : E - C = - (C - E) := (neg_sub C E).symm

  -- Substitute the calculated evaluation to conclude the proof
  rw [h4, h5]
  rw [inner_sub_right]
  simp only [inner_neg_left]
  rw [← h1]
  rw [real_inner_comm (C - E) (C - A)]
  ring

theorem A_sub_C_eq_A_sub_E_add_E_sub_C (A C E : ℝ²) :
  A - C = (A - E) + (E - C) :=
by
  abel

theorem E_prop_2_main (A B C E : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
  (hE : E = altitudeFoot ⟨![A, B, C], tri⟩ 2) :
  inner ℝ (E - C) (E - C) = inner ℝ (E - C) (A - C) :=
by
  -- 1. Decompose the target vector (A - C) passing through E
  rw [A_sub_C_eq_A_sub_E_add_E_sub_C A C E]
  -- 2. Expand the inner product via bilinearity across the addition
  rw [inner_add_right]
  -- 3. Substitute the established orthogonality condition to eliminate the first term
  rw [inner_E_sub_C_A_sub_E A B C E tri hE]
  -- 4. Simplify the resulting 0 + inner ℝ (E - C) (E - C) to close the equality
  rw [zero_add]

theorem inner_E_sub_C_self_eq (A B C E : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
  (hE : E = altitudeFoot ⟨![A, B, C], tri⟩ 2) :
  inner ℝ (E - C) (E - C) = inner ℝ (E - C) (A - C) :=
by
  let s : Affine.Simplex ℝ ℝ² 2 := ⟨![A, B, C], tri⟩

  have h1 : inner ℝ (C - A) (C - E) = s.height 2 ^ 2 := by
    have H := Affine.Simplex.inner_vsub_vsub_altitudeFoot_eq_height_sq s (i := 2) (j := 0) (by decide)
    have h_pts2 : s.points 2 = C := rfl
    have h_pts0 : s.points 0 = A := rfl
    rw [h_pts2, h_pts0, ← hE] at H
    -- The underlying operation of subtraction in an affine subspace equates to standard vector subtraction
    change inner ℝ (C - A) (C - E) = s.height 2 ^ 2 at H
    exact H

  have h_height : s.height 2 = dist C E := by
    -- Expand definition of the vertex altitude height
    change dist (s.points 2) (s.altitudeFoot 2) = dist C E
    have h_pts2 : s.points 2 = C := rfl
    rw [h_pts2, ← hE]

  have h2 : inner ℝ (C - E) (C - E) = s.height 2 ^ 2 := by
    rw [h_height]
    -- Because metric structures in NormedAddCommGroups define `dist C E` as `‖C - E‖`,
    -- we can perform a definitional change to the squared norm
    change inner ℝ (C - E) (C - E) = ‖C - E‖ ^ 2
    exact real_inner_self_eq_norm_sq (C - E)

  have h3 : inner ℝ (C - A) (C - E) = inner ℝ (C - E) (C - E) := by
    rw [h1, h2]

  -- Restructure via negations to match targeted orientations
  have eq1 : E - C = -(C - E) := (neg_sub C E).symm
  have eq2 : A - C = -(C - A) := (neg_sub C A).symm

  rw [eq1, eq2]
  simp only [inner_neg_left, inner_neg_right, neg_neg]
  rw [real_inner_comm (C - A) (C - E)]
  exact h3.symm

theorem C_ne_E_of_altitudeFoot (A B C E : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
  (hE : E = altitudeFoot ⟨![A, B, C], tri⟩ 2) :
  C ≠ E :=
by
  rw [hE]
  exact Affine.Simplex.ne_altitudeFoot ⟨![A, B, C], tri⟩ 2

theorem E_prop_3_main (A B C E : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
  (hE : E = altitudeFoot ⟨![A, B, C], tri⟩ 2) :
  inner ℝ (E - C) (A - C) ≠ (0 : ℝ) :=
by
  intro h
  -- Bring in the equality from the sub-lemma
  have h2 : inner ℝ (E - C) (E - C) = inner ℝ (E - C) (A - C) := inner_E_sub_C_self_eq A B C E tri hE

  -- Transitivity links the inner product to 0
  have h3 : inner ℝ (E - C) (E - C) = 0 := Eq.trans h2 h

  -- Apply positive definiteness of the inner product to deduce the vector is zero
  have h4 : E - C = 0 := inner_self_eq_zero.mp h3

  -- Transform vector subtraction equal to zero into points equality
  have h5 : E = C := sub_eq_zero.mp h4

  -- Introduce our non-equality helper sub-lemma
  have h6 : C ≠ E := C_ne_E_of_altitudeFoot A B C E tri hE

  -- The final exact contradiction: C ≠ E contradicts C = E
  exact h6 h5.symm

theorem E_prop (A B C E : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
  (acute : AcuteAngled ⟨![A, B, C], tri⟩)
  (hE : E = altitudeFoot ⟨![A, B, C], tri⟩ 2) :
  inner ℝ (E - C) (A - C) = inner ℝ (E - C) (B - C) ∧
  inner ℝ (E - C) (E - C) = inner ℝ (E - C) (A - C) ∧
  inner ℝ (E - C) (A - C) ≠ 0 :=
by
  refine ⟨?_, ?_, ?_⟩
  · exact E_prop_1_main A B C E tri hE
  · exact E_prop_2_main A B C E tri hE
  · exact E_prop_3_main A B C E tri hE

theorem mem_affineSpan_pair_of_eq_smul_add_r2 (A C P : ℝ²) (k : ℝ)
  (hP : P = k • (A - C) + C) : P ∈ affineSpan ℝ {A, C} :=
by
  rw [hP]
  have h := smul_vsub_vadd_mem_affineSpan_pair k C A
  rwa [Set.pair_comm C A] at h

theorem mul_inner_eq_inner_r2 (A C E : ℝ²) :
  (((inner ℝ (E - C) (A - C)) / inner ℝ (A - C) (A - C)) : ℝ) * inner ℝ (A - C) (A - C) = inner ℝ (E - C) (A - C) :=
by
  by_cases h : A - C = 0
  · simp [h]
  · apply div_mul_cancel₀
    intro hc
    apply h
    exact inner_self_eq_zero.mp hc

theorem inner_sub_smul_add_r2 (A C E P : ℝ²) (k : ℝ)
  (hP : P = k • (A - C) + C)
  (hk : k * inner ℝ (A - C) (A - C) = inner ℝ (E - C) (A - C)) :
  inner ℝ (E - P) (A - C) = (0 : ℝ) :=
by
  have h1 : E - P = (E - C) - k • (A - C) := by
    rw [hP]
    abel
  rw [h1]
  rw [inner_sub_left]
  rw [real_inner_smul_left]
  rw [hk]
  ring

theorem orthogonal_direction_of_inner_zero_r2 (A C E P : ℝ²)
  (h_ortho : inner ℝ (E - P) (A - C) = (0 : ℝ)) :
  ∀ v ∈ (affineSpan ℝ {A, C}).direction, inner ℝ (E - P) v = (0 : ℝ) :=
by
  intro v hv
  -- Rewrite the direction of the affine span to just the vector span
  rw [direction_affineSpan] at hv

  -- Express v as a scalar multiple of the difference between A and C
  rw [mem_vectorSpan_pair] at hv
  rcases hv with ⟨r, rfl⟩

  -- Definitionally change the torsor subtraction (-ᵥ) to vector subtraction (-)
  change inner ℝ (E - P) (r • (A - C)) = (0 : ℝ)

  -- Factor out the scalar 'r' and substitute the orthogonality hypothesis
  rw [inner_smul_right]
  rw [h_ortho]
  rw [mul_zero]

theorem orthogonalProjection_eq_of_mem_of_orthogonal_r2 (s : AffineSubspace ℝ ℝ²) (E P : ℝ²)
  [Nonempty s] [CompleteSpace s.direction]
  (hP_mem : P ∈ s)
  (hP_ortho : ∀ v ∈ s.direction, inner ℝ (E - P) v = (0 : ℝ)) :
  (orthogonalProjection s E : ℝ²) = P :=
by
  -- Apply the characterization of the orthogonal projection onto an affine subspace
  rw [EuclideanGeometry.coe_orthogonalProjection_eq_iff_mem]
  refine ⟨hP_mem, ?_⟩

  -- Show that E - P is in the orthogonal complement of the direction of s
  intro u hu
  -- Convert affine vector subtraction to regular subtraction
  rw [vsub_eq_sub]
  -- Use the symmetry of the real inner product to match the hypothesis
  rw [real_inner_comm]

  -- Conclude using the orthogonality assumption
  exact hP_ortho u hu

theorem reflection_apply_eq_two_smul_proj_sub_r2 (s : AffineSubspace ℝ ℝ²) (E : ℝ²)
  [Nonempty s] [CompleteSpace s.direction] :
  reflection s E = (2 : ℝ) • (orthogonalProjection s E : ℝ²) - E :=
by
  rw [EuclideanGeometry.reflection_apply']
  have h2 : (2 : ℝ) = 1 + 1 := by norm_num
  rw [h2, add_smul, one_smul]
  change (orthogonalProjection s E : ℝ²) - E + (orthogonalProjection s E : ℝ²) = (orthogonalProjection s E : ℝ²) + (orthogonalProjection s E : ℝ²) - E
  abel

theorem reflection_formula_algebra_r2 (A C E P E' : ℝ²) (k : ℝ)
  (hk : k = inner ℝ (E - C) (A - C) / inner ℝ (A - C) (A - C))
  (hP : P = k • (A - C) + C)
  (hE' : E' = (2 : ℝ) • P - E) :
  E' - C = (((2 : ℝ) * inner ℝ (E - C) (A - C)) / inner ℝ (A - C) (A - C)) • (A - C) - (E - C) :=
by
  -- Substitute the definitions into the goal
  rw [hE', hP, hk]
  -- Distribute the scalar multiplication over the addition
  rw [smul_add]
  -- Combine the scalar multiplications on the direction vector
  rw [← mul_smul]

  -- Reorganize the scalar term to match the right hand side
  have h_scalar : (2 : ℝ) * (inner ℝ (E - C) (A - C) / inner ℝ (A - C) (A - C)) =
    ((2 : ℝ) * inner ℝ (E - C) (A - C)) / inner ℝ (A - C) (A - C) := by ring
  rw [h_scalar]

  -- Expand the scalar multiplication on C
  have hC : (2 : ℝ) • C = C + C := by
    have h_two : (2 : ℝ) = 1 + 1 := by norm_num
    calc
      (2 : ℝ) • C = (1 + 1 : ℝ) • C := by rw [h_two]
      _ = (1 : ℝ) • C + (1 : ℝ) • C := by rw [add_smul]
      _ = C + C := by simp only [one_smul]
  rw [hC]

  -- Conclude the vector identity using the abelian group structure
  abel

theorem reflection_formula (A C E E' : ℝ²)
  (hE : E' = reflection (affineSpan ℝ {A, C}) E) :
  E' - C = (((2 : ℝ) * inner ℝ (E - C) (A - C)) / inner ℝ (A - C) (A - C)) • (A - C) - (E - C) :=
by
  -- Define the projection coefficient and orthogonal projection point
  let k := inner ℝ (E - C) (A - C) / inner ℝ (A - C) (A - C)
  let P := k • (A - C) + C

  -- Extract definitions into local assumptions
  have hk : k = inner ℝ (E - C) (A - C) / inner ℝ (A - C) (A - C) := rfl
  have hP_def : P = k • (A - C) + C := rfl

  -- Prove the geometry sequence using our lemmas
  have hP_mem : P ∈ affineSpan ℝ {A, C} :=
    mem_affineSpan_pair_of_eq_smul_add_r2 A C P k hP_def

  have hk_mul : k * inner ℝ (A - C) (A - C) = inner ℝ (E - C) (A - C) :=
    mul_inner_eq_inner_r2 A C E

  have h_ortho1 : inner ℝ (E - P) (A - C) = (0 : ℝ) :=
    inner_sub_smul_add_r2 A C E P k hP_def hk_mul

  have h_ortho2 : ∀ v ∈ (affineSpan ℝ {A, C}).direction, inner ℝ (E - P) v = (0 : ℝ) :=
    orthogonal_direction_of_inner_zero_r2 A C E P h_ortho1

  have h_proj : (orthogonalProjection (affineSpan ℝ {A, C}) E : ℝ²) = P :=
    orthogonalProjection_eq_of_mem_of_orthogonal_r2 (affineSpan ℝ {A, C}) E P hP_mem h_ortho2

  have h_refl : reflection (affineSpan ℝ {A, C}) E = (2 : ℝ) • (orthogonalProjection (affineSpan ℝ {A, C}) E : ℝ²) - E :=
    reflection_apply_eq_two_smul_proj_sub_r2 (affineSpan ℝ {A, C}) E

  -- Bridge the identities purely symmetrically
  have hE'_eq : E' = (2 : ℝ) • P - E := by
    rw [hE, h_refl, h_proj]

  -- Final pure algebraic identity closure
  exact reflection_formula_algebra_r2 A C E P E' k hk hP_def hE'_eq

theorem E1_E2_prop (A B C E E₁ E₂ : ℝ²)
  (hE1 : E₁ = reflection (affineSpan ℝ {A, C}) E)
  (hE2 : E₂ = reflection (affineSpan ℝ {B, C}) E) :
  E₁ - C = (((2 : ℝ) * inner ℝ (E - C) (A - C)) / inner ℝ (A - C) (A - C)) • (A - C) - (E - C) ∧
  E₂ - C = (((2 : ℝ) * inner ℝ (E - C) (B - C)) / inner ℝ (B - C) (B - C)) • (B - C) - (E - C) :=
by
  constructor
  · exact reflection_formula A C E E₁ hE1
  · exact reflection_formula B C E E₂ hE2

theorem O_prop (A B C E E₁ E₂ O : ℝ²)
  (hE1 : E₁ - C = (((2 : ℝ) * inner ℝ (E - C) (A - C)) / inner ℝ (A - C) (A - C)) • (A - C) - (E - C))
  (hE2 : E₂ - C = (((2 : ℝ) * inner ℝ (E - C) (B - C)) / inner ℝ (B - C) (B - C)) • (B - C) - (E - C))
  (hE_inner : inner ℝ (E - C) (E - C) = inner ℝ (E - C) (A - C))
  (hE_eq : inner ℝ (E - C) (A - C) = inner ℝ (E - C) (B - C))
  (hE_ne_zero : inner ℝ (E - C) (A - C) ≠ 0)
  (tri2 : AffineIndependent ℝ ![C, E₁, E₂])
  (hO : O = circumcenter ⟨![C, E₁, E₂], tri2⟩) :
  ∃ t : ℝ, inner ℝ (O - C) (A - C) = t * inner ℝ (A - C) (A - C) ∧
           inner ℝ (O - C) (B - C) = t * inner ℝ (B - C) (B - C) ∧
           (4 : ℝ) * t * inner ℝ (E - C) (A - C) - (2 : ℝ) * inner ℝ (O - C) (E - C) = inner ℝ (E - C) (A - C) :=
by
  let s : Affine.Simplex ℝ ℝ² 2 := ⟨![C, E₁, E₂], tri2⟩

  have d1 : dist C O = dist E₁ O := by
    have h0 : dist C O = dist (s.points 0) O := rfl
    have h1 : dist E₁ O = dist (s.points 1) O := rfl
    rw [h0, h1, hO, s.dist_circumcenter_eq_circumradius 0, s.dist_circumcenter_eq_circumradius 1]

  have h2 : ‖C - O‖ = ‖E₁ - O‖ := by
    calc ‖C - O‖ = dist C O := dist_eq_norm C O |>.symm
      _ = dist E₁ O := d1
      _ = ‖E₁ - O‖ := dist_eq_norm E₁ O

  have h3 : inner ℝ (C - O) (C - O) = inner ℝ (E₁ - O) (E₁ - O) := by
    have h4 : ‖C - O‖ ^ 2 = ‖E₁ - O‖ ^ 2 := by rw [h2]
    rwa [← real_inner_self_eq_norm_sq (C - O), ← real_inner_self_eq_norm_sq (E₁ - O)] at h4

  have h_E1_O : E₁ - O = (E₁ - C) - (O - C) := by abel

  have exp1 : inner ℝ ((E₁ - C) - (O - C)) ((E₁ - C) - (O - C)) =
      inner ℝ (E₁ - C) (E₁ - C) - inner ℝ (E₁ - C) (O - C) - inner ℝ (O - C) (E₁ - C) + inner ℝ (O - C) (O - C) := by
    generalize hu : E₁ - C = u
    generalize hv : O - C = v
    simp only [inner_sub_left, inner_sub_right]
    ring

  have exp2 : inner ℝ (C - O) (C - O) = inner ℝ (O - C) (O - C) := by
    rw [← neg_sub O C, inner_neg_left, inner_neg_right, neg_neg]

  have h_eq1 : inner ℝ (O - C) (O - C) = inner ℝ (E₁ - C) (E₁ - C) - inner ℝ (E₁ - C) (O - C) - inner ℝ (O - C) (E₁ - C) + inner ℝ (O - C) (O - C) := by
    calc inner ℝ (O - C) (O - C) = inner ℝ (C - O) (C - O) := exp2.symm
      _ = inner ℝ (E₁ - O) (E₁ - O) := h3
      _ = inner ℝ ((E₁ - C) - (O - C)) ((E₁ - C) - (O - C)) := by rw [h_E1_O]
      _ = _ := exp1

  have h_eq2 : (2 : ℝ) * inner ℝ (O - C) (E₁ - C) = inner ℝ (E₁ - C) (E₁ - C) := by
    have h_comm : inner ℝ (E₁ - C) (O - C) = inner ℝ (O - C) (E₁ - C) := real_inner_comm (O - C) (E₁ - C)
    linarith [h_eq1, h_comm]

  have hA_ne_zero : inner ℝ (A - C) (A - C) ≠ 0 := by
    intro h
    have hAC : A - C = 0 := inner_self_eq_zero.mp h
    have h_zero : inner ℝ (E - C) (A - C) = 0 := by rw [hAC, inner_zero_right]
    exact hE_ne_zero h_zero

  let lamA := ((2 : ℝ) * inner ℝ (E - C) (A - C)) / inner ℝ (A - C) (A - C)
  have hE1_sub : E₁ - C = lamA • (A - C) - (E - C) := hE1

  have h_lamA : lamA * inner ℝ (A - C) (A - C) = (2 : ℝ) * inner ℝ (E - C) (A - C) := by
    exact div_mul_cancel₀ _ hA_ne_zero

  have exp3 : inner ℝ (E₁ - C) (E₁ - C) = lamA * lamA * inner ℝ (A - C) (A - C) - lamA * inner ℝ (A - C) (E - C) - lamA * inner ℝ (E - C) (A - C) + inner ℝ (E - C) (E - C) := by
    rw [hE1_sub]
    generalize hu : A - C = u
    generalize hv : E - C = v
    simp only [inner_sub_left, inner_sub_right]
    simp only [real_inner_smul_left, real_inner_smul_right]
    ring

  have exp4 : inner ℝ (E₁ - C) (E₁ - C) = inner ℝ (E - C) (E - C) := by
    have h_comm2 : inner ℝ (A - C) (E - C) = inner ℝ (E - C) (A - C) := real_inner_comm (E - C) (A - C)
    calc inner ℝ (E₁ - C) (E₁ - C) = lamA * lamA * inner ℝ (A - C) (A - C) - lamA * inner ℝ (A - C) (E - C) - lamA * inner ℝ (E - C) (A - C) + inner ℝ (E - C) (E - C) := exp3
      _ = lamA * (lamA * inner ℝ (A - C) (A - C)) - lamA * inner ℝ (A - C) (E - C) - lamA * inner ℝ (E - C) (A - C) + inner ℝ (E - C) (E - C) := by ring
      _ = lamA * ((2 : ℝ) * inner ℝ (E - C) (A - C)) - lamA * inner ℝ (E - C) (A - C) - lamA * inner ℝ (E - C) (A - C) + inner ℝ (E - C) (E - C) := by rw [h_lamA, h_comm2]
      _ = inner ℝ (E - C) (E - C) := by ring

  have exp5 : inner ℝ (O - C) (E₁ - C) = lamA * inner ℝ (O - C) (A - C) - inner ℝ (O - C) (E - C) := by
    rw [hE1_sub]
    generalize hu : A - C = u
    generalize hv : E - C = v
    simp only [inner_sub_right, real_inner_smul_right]

  let t := inner ℝ (O - C) (A - C) / inner ℝ (A - C) (A - C)
  have htA : inner ℝ (O - C) (A - C) = t * inner ℝ (A - C) (A - C) := by
    exact (div_mul_cancel₀ _ hA_ne_zero).symm

  have h_goal3 : (4 : ℝ) * t * inner ℝ (E - C) (A - C) - (2 : ℝ) * inner ℝ (O - C) (E - C) = inner ℝ (E - C) (A - C) := by
    have h_eq : (2 : ℝ) * (lamA * inner ℝ (O - C) (A - C) - inner ℝ (O - C) (E - C)) = inner ℝ (E - C) (A - C) := by
      calc (2 : ℝ) * (lamA * inner ℝ (O - C) (A - C) - inner ℝ (O - C) (E - C)) = (2 : ℝ) * inner ℝ (O - C) (E₁ - C) := by rw [← exp5]
        _ = inner ℝ (E₁ - C) (E₁ - C) := h_eq2
        _ = inner ℝ (E - C) (E - C) := exp4
        _ = inner ℝ (E - C) (A - C) := hE_inner
    have h_lamA_sub : lamA * inner ℝ (O - C) (A - C) = (2 : ℝ) * t * inner ℝ (E - C) (A - C) := by
      calc lamA * inner ℝ (O - C) (A - C) = lamA * (t * inner ℝ (A - C) (A - C)) := by rw [htA]
        _ = t * (lamA * inner ℝ (A - C) (A - C)) := by ring
        _ = t * ((2 : ℝ) * inner ℝ (E - C) (A - C)) := by rw [h_lamA]
        _ = (2 : ℝ) * t * inner ℝ (E - C) (A - C) := by ring
    linarith [h_eq, h_lamA_sub]

  have hB_ne_zero : inner ℝ (B - C) (B - C) ≠ 0 := by
    intro h
    have hBC : B - C = 0 := inner_self_eq_zero.mp h
    have h_zero : inner ℝ (E - C) (B - C) = 0 := by rw [hBC, inner_zero_right]
    have h_zero2 : inner ℝ (E - C) (A - C) = 0 := by rw [← hE_eq] at h_zero; exact h_zero
    exact hE_ne_zero h_zero2

  let lamB := ((2 : ℝ) * inner ℝ (E - C) (B - C)) / inner ℝ (B - C) (B - C)
  have hE2_sub : E₂ - C = lamB • (B - C) - (E - C) := hE2

  have d2 : dist C O = dist E₂ O := by
    have h0 : dist C O = dist (s.points 0) O := rfl
    have h2_dist : dist E₂ O = dist (s.points 2) O := rfl
    rw [h0, h2_dist, hO, s.dist_circumcenter_eq_circumradius 0, s.dist_circumcenter_eq_circumradius 2]

  have h2_B : ‖C - O‖ = ‖E₂ - O‖ := by
    calc ‖C - O‖ = dist C O := dist_eq_norm C O |>.symm
      _ = dist E₂ O := d2
      _ = ‖E₂ - O‖ := dist_eq_norm E₂ O

  have h3_B : inner ℝ (C - O) (C - O) = inner ℝ (E₂ - O) (E₂ - O) := by
    have h4 : ‖C - O‖ ^ 2 = ‖E₂ - O‖ ^ 2 := by rw [h2_B]
    rwa [← real_inner_self_eq_norm_sq (C - O), ← real_inner_self_eq_norm_sq (E₂ - O)] at h4

  have h_E2_O : E₂ - O = (E₂ - C) - (O - C) := by abel

  have exp1_B : inner ℝ ((E₂ - C) - (O - C)) ((E₂ - C) - (O - C)) =
      inner ℝ (E₂ - C) (E₂ - C) - inner ℝ (E₂ - C) (O - C) - inner ℝ (O - C) (E₂ - C) + inner ℝ (O - C) (O - C) := by
    generalize hu : E₂ - C = u
    generalize hv : O - C = v
    simp only [inner_sub_left, inner_sub_right]
    ring

  have h_eq1_B : inner ℝ (O - C) (O - C) = inner ℝ (E₂ - C) (E₂ - C) - inner ℝ (E₂ - C) (O - C) - inner ℝ (O - C) (E₂ - C) + inner ℝ (O - C) (O - C) := by
    calc inner ℝ (O - C) (O - C) = inner ℝ (C - O) (C - O) := exp2.symm
      _ = inner ℝ (E₂ - O) (E₂ - O) := h3_B
      _ = inner ℝ ((E₂ - C) - (O - C)) ((E₂ - C) - (O - C)) := by rw [h_E2_O]
      _ = _ := exp1_B

  have h_eq2_B : (2 : ℝ) * inner ℝ (O - C) (E₂ - C) = inner ℝ (E₂ - C) (E₂ - C) := by
    have h_comm3 : inner ℝ (E₂ - C) (O - C) = inner ℝ (O - C) (E₂ - C) := real_inner_comm (O - C) (E₂ - C)
    linarith [h_eq1_B, h_comm3]

  have h_lamB : lamB * inner ℝ (B - C) (B - C) = (2 : ℝ) * inner ℝ (E - C) (B - C) := by
    exact div_mul_cancel₀ _ hB_ne_zero

  have exp3_B : inner ℝ (E₂ - C) (E₂ - C) = lamB * lamB * inner ℝ (B - C) (B - C) - lamB * inner ℝ (B - C) (E - C) - lamB * inner ℝ (E - C) (B - C) + inner ℝ (E - C) (E - C) := by
    rw [hE2_sub]
    generalize hu : B - C = u
    generalize hv : E - C = v
    simp only [inner_sub_left, inner_sub_right]
    simp only [real_inner_smul_left, real_inner_smul_right]
    ring

  have exp4_B : inner ℝ (E₂ - C) (E₂ - C) = inner ℝ (E - C) (A - C) := by
    have h_comm4 : inner ℝ (B - C) (E - C) = inner ℝ (E - C) (B - C) := real_inner_comm (E - C) (B - C)
    have hd : inner ℝ (E₂ - C) (E₂ - C) = inner ℝ (E - C) (E - C) := by
      calc inner ℝ (E₂ - C) (E₂ - C) = lamB * lamB * inner ℝ (B - C) (B - C) - lamB * inner ℝ (B - C) (E - C) - lamB * inner ℝ (E - C) (B - C) + inner ℝ (E - C) (E - C) := exp3_B
        _ = lamB * (lamB * inner ℝ (B - C) (B - C)) - lamB * inner ℝ (B - C) (E - C) - lamB * inner ℝ (E - C) (B - C) + inner ℝ (E - C) (E - C) := by ring
        _ = lamB * ((2 : ℝ) * inner ℝ (E - C) (B - C)) - lamB * inner ℝ (E - C) (B - C) - lamB * inner ℝ (E - C) (B - C) + inner ℝ (E - C) (E - C) := by rw [h_lamB, h_comm4]
        _ = inner ℝ (E - C) (E - C) := by ring
    rw [hd, hE_inner]

  have exp5_B : inner ℝ (O - C) (E₂ - C) = lamB * inner ℝ (O - C) (B - C) - inner ℝ (O - C) (E - C) := by
    rw [hE2_sub]
    generalize hu : B - C = u
    generalize hv : E - C = v
    simp only [inner_sub_right, real_inner_smul_right]

  let v := inner ℝ (O - C) (B - C) / inner ℝ (B - C) (B - C)
  have hvB : inner ℝ (O - C) (B - C) = v * inner ℝ (B - C) (B - C) := by
    exact (div_mul_cancel₀ _ hB_ne_zero).symm

  have h_goal3_B : (4 : ℝ) * v * inner ℝ (E - C) (B - C) - (2 : ℝ) * inner ℝ (O - C) (E - C) = inner ℝ (E - C) (A - C) := by
    have h_eq : (2 : ℝ) * (lamB * inner ℝ (O - C) (B - C) - inner ℝ (O - C) (E - C)) = inner ℝ (E - C) (A - C) := by
      calc (2 : ℝ) * (lamB * inner ℝ (O - C) (B - C) - inner ℝ (O - C) (E - C)) = (2 : ℝ) * inner ℝ (O - C) (E₂ - C) := by rw [← exp5_B]
        _ = inner ℝ (E₂ - C) (E₂ - C) := h_eq2_B
        _ = inner ℝ (E - C) (A - C) := exp4_B
    have h_lamB_sub : lamB * inner ℝ (O - C) (B - C) = (2 : ℝ) * v * inner ℝ (E - C) (B - C) := by
      calc lamB * inner ℝ (O - C) (B - C) = lamB * (v * inner ℝ (B - C) (B - C)) := by rw [hvB]
        _ = v * (lamB * inner ℝ (B - C) (B - C)) := by ring
        _ = v * ((2 : ℝ) * inner ℝ (E - C) (B - C)) := by rw [h_lamB]
        _ = (2 : ℝ) * v * inner ℝ (E - C) (B - C) := by ring
    linarith [h_eq, h_lamB_sub]

  have h_goal3_B' : (4 : ℝ) * v * inner ℝ (E - C) (A - C) - (2 : ℝ) * inner ℝ (O - C) (E - C) = inner ℝ (E - C) (A - C) := by
    have h_eq_inner : inner ℝ (E - C) (B - C) = inner ℝ (E - C) (A - C) := hE_eq.symm
    calc (4 : ℝ) * v * inner ℝ (E - C) (A - C) - (2 : ℝ) * inner ℝ (O - C) (E - C) = (4 : ℝ) * v * inner ℝ (E - C) (B - C) - (2 : ℝ) * inner ℝ (O - C) (E - C) := by rw [h_eq_inner]
      _ = inner ℝ (E - C) (A - C) := h_goal3_B

  have h_tv : (4 : ℝ) * (t - v) * inner ℝ (E - C) (A - C) = 0 := by
    calc (4 : ℝ) * (t - v) * inner ℝ (E - C) (A - C) = ((4 : ℝ) * t * inner ℝ (E - C) (A - C) - (2 : ℝ) * inner ℝ (O - C) (E - C)) - ((4 : ℝ) * v * inner ℝ (E - C) (A - C) - (2 : ℝ) * inner ℝ (O - C) (E - C)) := by ring
      _ = inner ℝ (E - C) (A - C) - inner ℝ (E - C) (A - C) := by rw [h_goal3, h_goal3_B']
      _ = 0 := sub_self _

  have h_tv2 : (4 : ℝ) * (t - v) = 0 := (mul_eq_zero.mp h_tv).resolve_right hE_ne_zero
  have h_four_ne_zero : (4 : ℝ) ≠ 0 := by norm_num
  have h_tv3 : t - v = 0 := (mul_eq_zero.mp h_tv2).resolve_left h_four_ne_zero
  have ht_eq_v : t = v := sub_eq_zero.mp h_tv3

  have htB : inner ℝ (O - C) (B - C) = t * inner ℝ (B - C) (B - C) := by
    rw [ht_eq_v]
    exact hvB

  exact ⟨t, htA, htB, h_goal3⟩

theorem t_prop (A B C O E : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
  (hE_eq : inner ℝ (E - C) (A - C) = inner ℝ (E - C) (B - C))
  (hE_inner : inner ℝ (E - C) (E - C) = inner ℝ (E - C) (A - C))
  (t : ℝ)
  (h_tA : inner ℝ (O - C) (A - C) = t * inner ℝ (A - C) (A - C))
  (h_tB : inner ℝ (O - C) (B - C) = t * inner ℝ (B - C) (B - C))
  (h_O_E : (4 : ℝ) * t * inner ℝ (E - C) (A - C) - (2 : ℝ) * inner ℝ (O - C) (E - C) = inner ℝ (E - C) (A - C))
  (hE_ne_zero : inner ℝ (E - C) (A - C) ≠ 0) :
  (2 : ℝ) * t * inner ℝ (A - C) (B - C) = inner ℝ (E - C) (A - C) :=
by

  let u : ℝ² := A - C
  let v : ℝ² := B - C
  let w : ℝ² := E - C
  let z : ℝ² := O - C
  let K : ℝ := inner ℝ w u
  let Δ : ℝ := u 0 * v 1 - u 1 * v 0

  have h_wu : inner ℝ w u = K := rfl
  have h_wv : inner ℝ w v = K := hE_eq.symm
  have h_ww : inner ℝ w w = K := hE_inner
  have h_zu : inner ℝ z u = t * inner ℝ u u := h_tA
  have h_zv : inner ℝ z v = t * inner ℝ v v := h_tB

  have h_uw : inner ℝ u w = inner ℝ w u := by rw [real_inner_comm]
  have h_vw : inner ℝ v w = inner ℝ w v := by rw [real_inner_comm]
  have h_vu : inner ℝ v u = inner ℝ u v := by rw [real_inner_comm]

  -- We show that the determinant Δ is non-zero, exploiting linear independence of (A - C) and (B - C)
  have h_Delta_ne_zero : Δ ≠ 0 := by
    intro hD

    have h_uv1 : v 1 • u - u 1 • v = 0 := by
      ext i
      have h01 : i = 0 ∨ i = 1 := by omega
      rcases h01 with rfl | rfl
      · change v 1 * u 0 - u 1 * v 0 = 0
        linarith [hD]
      · change v 1 * u 1 - u 1 * v 1 = 0
        ring

    have h_uv1_w : inner ℝ w (v 1 • u - u 1 • v) = (0 : ℝ) := by
      rw [h_uv1, inner_zero_right]

    have h_uv1_w2 : inner ℝ w (v 1 • u - u 1 • v) = (v 1 - u 1) * K := by
      calc inner ℝ w (v 1 • u - u 1 • v) = inner ℝ w (v 1 • u) - inner ℝ w (u 1 • v) := by rw [inner_sub_right]
        _ = v 1 * inner ℝ w u - u 1 * inner ℝ w v := by simp only [inner_smul_right, RCLike.star_def, conj_trivial]
        _ = v 1 * K - u 1 * K := by rw [h_wu, h_wv]
        _ = (v 1 - u 1) * K := by ring

    have hu1 : u 1 = v 1 := by
      have : (v 1 - u 1) * K = 0 := by linarith [h_uv1_w, h_uv1_w2]
      cases mul_eq_zero.mp this with
      | inl h => linarith
      | inr h => exact False.elim (hE_ne_zero h)

    have h_uv0 : v 0 • u - u 0 • v = 0 := by
      ext i
      have h01 : i = 0 ∨ i = 1 := by omega
      rcases h01 with rfl | rfl
      · change v 0 * u 0 - u 0 * v 0 = 0
        ring
      · change v 0 * u 1 - u 0 * v 1 = 0
        linarith [hD]

    have h_uv0_w : inner ℝ w (v 0 • u - u 0 • v) = (0 : ℝ) := by
      rw [h_uv0, inner_zero_right]

    have h_uv0_w2 : inner ℝ w (v 0 • u - u 0 • v) = (v 0 - u 0) * K := by
      calc inner ℝ w (v 0 • u - u 0 • v) = inner ℝ w (v 0 • u) - inner ℝ w (u 0 • v) := by rw [inner_sub_right]
        _ = v 0 * inner ℝ w u - u 0 * inner ℝ w v := by simp only [inner_smul_right, RCLike.star_def, conj_trivial]
        _ = v 0 * K - u 0 * K := by rw [h_wu, h_wv]
        _ = (v 0 - u 0) * K := by ring

    have hu0 : u 0 = v 0 := by
      have : (v 0 - u 0) * K = 0 := by linarith [h_uv0_w, h_uv0_w2]
      cases mul_eq_zero.mp this with
      | inl h => linarith
      | inr h => exact False.elim (hE_ne_zero h)

    have huv : u = v := by
      ext i
      have h01 : i = 0 ∨ i = 1 := by omega
      rcases h01 with rfl | rfl
      · exact hu0
      · exact hu1

    have hAB : A = B := by
      ext i
      have h1 : u i = v i := by rw [huv]
      change A i - C i = B i - C i at h1
      linarith

    have hAB_mat : ![A, B, C] 0 = ![A, B, C] 1 := hAB
    have h_inj : Function.Injective ![A, B, C] := AffineIndependent.injective tri
    have h_0_eq_1 : (0 : Fin 3) = (1 : Fin 3) := h_inj hAB_mat
    revert h_0_eq_1
    decide

  -- Universal algebraic vector identity projection (similar to Cramer's rule derivation)
  have h_vec : ∀ a b c : ℝ², (a 0 * b 1 - a 1 * b 0) • c = (c 0 * b 1 - c 1 * b 0) • a + (a 0 * c 1 - a 1 * c 0) • b := by
    intro a b c
    ext i
    have h01 : i = 0 ∨ i = 1 := by omega
    rcases h01 with rfl | rfl
    · change (a 0 * b 1 - a 1 * b 0) * c 0 = (c 0 * b 1 - c 1 * b 0) * a 0 + (a 0 * c 1 - a 1 * c 0) * b 0
      ring
    · change (a 0 * b 1 - a 1 * b 0) * c 1 = (c 0 * b 1 - c 1 * b 0) * a 1 + (a 0 * c 1 - a 1 * c 0) * b 1
      ring

  let x : ℝ := w 0 * v 1 - w 1 * v 0
  let y : ℝ := u 0 * w 1 - u 1 * w 0
  have hw2 : Δ • w = x • u + y • v := h_vec u v w

  have eq_w : inner ℝ (Δ • w) w = inner ℝ (x • u + y • v) w := by rw [hw2]
  have eq_w2 : Δ * K = (x + y) * K := by
    calc Δ * K = Δ * inner ℝ w w := by rw [h_ww]
      _ = inner ℝ (Δ • w) w := by simp only [inner_smul_left, RCLike.star_def, conj_trivial]
      _ = inner ℝ (x • u + y • v) w := eq_w
      _ = inner ℝ (x • u) w + inner ℝ (y • v) w := by simp only [inner_add_left]
      _ = x * inner ℝ u w + y * inner ℝ v w := by simp only [inner_smul_left, RCLike.star_def, conj_trivial]
      _ = x * inner ℝ w u + y * inner ℝ w v := by rw [h_uw, h_vw]
      _ = x * K + y * K := by rw [h_wu, h_wv]
      _ = (x + y) * K := by ring

  have h_Delta : Δ = x + y := by
    have : (Δ - (x + y)) * K = 0 := by linarith [eq_w2]
    cases mul_eq_zero.mp this with
    | inl h => linarith
    | inr h => exact False.elim (hE_ne_zero h)

  have eq_u : inner ℝ (Δ • w) u = inner ℝ (x • u + y • v) u := by rw [hw2]
  have eq_u2 : Δ * K = x * inner ℝ u u + y * inner ℝ u v := by
    calc Δ * K = Δ * inner ℝ w u := by rw [h_wu]
      _ = inner ℝ (Δ • w) u := by simp only [inner_smul_left, RCLike.star_def, conj_trivial]
      _ = inner ℝ (x • u + y • v) u := eq_u
      _ = x * inner ℝ u u + y * inner ℝ v u := by simp only [inner_add_left, inner_smul_left, RCLike.star_def, conj_trivial]
      _ = x * inner ℝ u u + y * inner ℝ u v := by rw [h_vu]

  have eq_v : inner ℝ (Δ • w) v = inner ℝ (x • u + y • v) v := by rw [hw2]
  have eq_v2 : Δ * K = x * inner ℝ u v + y * inner ℝ v v := by
    calc Δ * K = Δ * inner ℝ w v := by rw [h_wv]
      _ = inner ℝ (Δ • w) v := by simp only [inner_smul_left, RCLike.star_def, conj_trivial]
      _ = inner ℝ (x • u + y • v) v := eq_v
      _ = x * inner ℝ u v + y * inner ℝ v v := by simp only [inner_add_left, inner_smul_left, RCLike.star_def, conj_trivial]

  have eq_zw : inner ℝ z (Δ • w) = inner ℝ z (x • u + y • v) := by rw [hw2]
  have eq_zw2 : Δ * inner ℝ z w = t * (x * inner ℝ u u + y * inner ℝ v v) := by
    calc Δ * inner ℝ z w = inner ℝ z (Δ • w) := by simp only [inner_smul_right, RCLike.star_def, conj_trivial]
      _ = inner ℝ z (x • u + y • v) := eq_zw
      _ = x * inner ℝ z u + y * inner ℝ z v := by simp only [inner_add_right, inner_smul_right, RCLike.star_def, conj_trivial]
      _ = x * (t * inner ℝ u u) + y * (t * inner ℝ v v) := by rw [h_zu, h_zv]
      _ = t * (x * inner ℝ u u + y * inner ℝ v v) := by ring

  have h_subst : x * inner ℝ u u + y * inner ℝ v v = Δ * (2 * K - inner ℝ u v) := by
    calc x * inner ℝ u u + y * inner ℝ v v = (Δ * K - y * inner ℝ u v) + (Δ * K - x * inner ℝ u v) := by linarith [eq_u2, eq_v2]
      _ = 2 * Δ * K - (x + y) * inner ℝ u v := by ring
      _ = 2 * Δ * K - Δ * inner ℝ u v := by rw [← h_Delta]
      _ = Δ * (2 * K - inner ℝ u v) := by ring

  have eq_zw3 : Δ * inner ℝ z w = t * Δ * (2 * K - inner ℝ u v) := by
    calc Δ * inner ℝ z w = t * (x * inner ℝ u u + y * inner ℝ v v) := eq_zw2
      _ = t * (Δ * (2 * K - inner ℝ u v)) := by rw [h_subst]
      _ = t * Δ * (2 * K - inner ℝ u v) := by ring

  have h_OE_K : (4 : ℝ) * t * K - (2 : ℝ) * inner ℝ z w = K := h_O_E
  have h_final : Δ * (2 * t * inner ℝ u v) = Δ * K := by
    calc Δ * (2 * t * inner ℝ u v) = 4 * t * K * Δ - 2 * (t * Δ * (2 * K - inner ℝ u v)) := by ring
      _ = 4 * t * K * Δ - 2 * (Δ * inner ℝ z w) := by rw [← eq_zw3]
      _ = Δ * (4 * t * K - 2 * inner ℝ z w) := by ring
      _ = Δ * K := by rw [h_OE_K]

  have h_ans : (2 : ℝ) * t * inner ℝ u v = K := by
    have : Δ * ((2 : ℝ) * t * inner ℝ u v - K) = 0 := by
      calc Δ * ((2 : ℝ) * t * inner ℝ u v - K) = Δ * (2 * t * inner ℝ u v) - Δ * K := by ring
        _ = 0 := by rw [h_final, sub_self]
    cases mul_eq_zero.mp this with
    | inl h => exact False.elim (h_Delta_ne_zero h)
    | inr h => linarith

  exact h_ans

theorem A_ne_C_of_AffineIndependent_X_prop (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C]) :
  A ≠ C :=
by
  intro h
  have h_eq : ![A, B, C] 0 = ![A, B, C] 2 := h
  have h_idx : (0 : Fin 3) = 2 := AffineIndependent.injective tri h_eq
  revert h_idx
  decide

theorem exists_k_of_collinear_X_prop (X A C : ℝ²)
  (hCollinear : Collinear ℝ {X, A, C})
  (hA_ne_C : A ≠ C) :
  ∃ k : ℝ, X - C = k • (A - C) :=
by
  -- Rewrite the theorem right at the hypothesis
  rw [collinear_iff_exists_forall_eq_smul_vadd] at hCollinear
  obtain ⟨p₀, v, h⟩ := hCollinear

  -- The points are obviously in the set we defined
  have mem_X : X ∈ ({X, A, C} : Set ℝ²) := by simp
  have mem_A : A ∈ ({X, A, C} : Set ℝ²) := by simp
  have mem_C : C ∈ ({X, A, C} : Set ℝ²) := by simp

  obtain ⟨rX, hrX⟩ := h X mem_X
  obtain ⟨rA, hrA⟩ := h A mem_A
  obtain ⟨rC, hrC⟩ := h C mem_C

  have hXC : X - C = (rX - rC) • v := by
    rw [hrX, hrC]
    -- Since vectors are naturally AddTorsors over themselves, `+ᵥ` is definitionally `+`
    change rX • v + p₀ - (rC • v + p₀) = (rX - rC) • v
    rw [sub_smul]
    abel

  have hAC : A - C = (rA - rC) • v := by
    rw [hrA, hrC]
    change rA • v + p₀ - (rC • v + p₀) = (rA - rC) • v
    rw [sub_smul]
    abel

  have hr_ne : rA - rC ≠ 0 := by
    intro h_eq
    have hAC_zero : A - C = 0 := by
      rw [hAC, h_eq, zero_smul]
    have hAC_eq : A = C := sub_eq_zero.mp hAC_zero
    exact hA_ne_C hAC_eq

  -- Introduce our scaled witness k
  use (rX - rC) / (rA - rC)
  have h_div : (rX - rC) / (rA - rC) * (rA - rC) = rX - rC := div_mul_cancel₀ (rX - rC) hr_ne

  calc X - C = (rX - rC) • v := hXC
    _ = (((rX - rC) / (rA - rC)) * (rA - rC)) • v := by rw [h_div]
    _ = ((rX - rC) / (rA - rC)) • (rA - rC) • v := by rw [mul_smul]
    _ = ((rX - rC) / (rA - rC)) • (A - C) := by rw [← hAC]

theorem cospherical_extract_r2 (X C E₁ E₂ : ℝ²) (h : Cospherical {X, C, E₁, E₂}) :
  ∃ c r, dist X c = r ∧ dist C c = r ∧ dist E₁ c = r ∧ dist E₂ c = r :=
by
  rw [EuclideanGeometry.cospherical_def] at h
  obtain ⟨c, r, hr⟩ := h
  use c, r
  exact ⟨hr X (by simp), hr C (by simp), hr E₁ (by simp), hr E₂ (by simp)⟩

theorem inner_sub_sub_eq_zero_of_dist_eq_r2 (c O C E : ℝ²)
  (hc : dist C c = dist E c)
  (ho : dist C O = dist E O) :
  inner ℝ (c - O) (E - C) = (0 : ℝ) :=
by
  have hc' : dist c C = dist c E := by
    rw [dist_comm c C, hc, dist_comm E c]

  have h1 : ‖c - C‖ ^ 2 = ‖c - E‖ ^ 2 := by
    have d1 : ‖c - C‖ = dist c C := (dist_eq_norm c C).symm
    have d2 : ‖c - E‖ = dist c E := (dist_eq_norm c E).symm
    rw [d1, d2, hc']

  have eq1 : c - C = (c - O) - (C - O) := by abel
  have eq2 : c - E = (c - O) - (E - O) := by abel
  rw [eq1, eq2] at h1

  have h2 := norm_sub_pow_two_real (c - O) (C - O)
  have h3 := norm_sub_pow_two_real (c - O) (E - O)
  rw [h2, h3] at h1

  have h4 : ‖C - O‖ ^ 2 = ‖E - O‖ ^ 2 := by
    have d1 : ‖C - O‖ = dist C O := (dist_eq_norm C O).symm
    have d2 : ‖E - O‖ = dist E O := (dist_eq_norm E O).symm
    rw [d1, d2, ho]

  have h5 : inner ℝ (c - O) (C - O) = inner ℝ (c - O) (E - O) := by linarith [h1, h4]

  have eq3 : E - C = (E - O) - (C - O) := by abel
  rw [eq3, inner_sub_right, h5, sub_self]

theorem eq_zero_of_inner_eq_zero_of_affine_independent_r2 (x C E₁ E₂ : ℝ²)
  (tri : AffineIndependent ℝ ![C, E₁, E₂])
  (h1 : inner ℝ x (E₁ - C) = (0 : ℝ))
  (h2 : inner ℝ x (E₂ - C) = (0 : ℝ)) :
  x = 0 :=
by
  have h_li : LinearIndependent ℝ (fun j : {x : Fin 3 // x ≠ 0} => ![C, E₁, E₂] j -ᵥ ![C, E₁, E₂] 0) :=
    affineIndependent_iff_linearIndependent_vsub ℝ ![C, E₁, E₂] 0 |>.mp tri

  have h_span : Submodule.span ℝ (Set.range (fun j : {x : Fin 3 // x ≠ 0} => ![C, E₁, E₂] j -ᵥ ![C, E₁, E₂] 0)) = ⊤ := by
    apply Submodule.eq_top_of_finrank_eq
    have h_dim : Module.finrank ℝ (Submodule.span ℝ (Set.range (fun j : {x : Fin 3 // x ≠ 0} => ![C, E₁, E₂] j -ᵥ ![C, E₁, E₂] 0))) = 2 := by
      first
      | rw [finrank_span_eq_card h_li]; rfl
      | rw [LinearIndependent.finrank_span h_li]; rfl
    rw [h_dim, finrank_euclideanSpace]
    rfl

  let S : Submodule ℝ ℝ² :=
    { carrier := {y | inner ℝ x y = (0 : ℝ)}
      add_mem' := by
        rintro a b ha hb
        dsimp at *
        rw [inner_add_right, ha, hb, add_zero]
      zero_mem' := by
        dsimp
        rw [inner_zero_right]
      smul_mem' := by
        rintro c y hy
        dsimp at *
        try rw [inner_smul_right]
        try rw [real_inner_smul_right]
        simp [hy] }

  have h_range : Set.range (fun j : {x : Fin 3 // x ≠ 0} => ![C, E₁, E₂] j -ᵥ ![C, E₁, E₂] 0) ⊆ S := by
    rintro _ ⟨⟨j, hj⟩, rfl⟩
    obtain ⟨jv, hlt⟩ := j
    have : jv = 0 ∨ jv = 1 ∨ jv = 2 := by omega
    rcases this with rfl | rfl | rfl
    · have h0 : (⟨0, hlt⟩ : Fin 3) = 0 := rfl
      exact False.elim (hj h0)
    · try change inner ℝ x (E₁ - C) = (0 : ℝ)
      try rw [vsub_eq_sub]
      exact h1
    · try change inner ℝ x (E₂ - C) = (0 : ℝ)
      try rw [vsub_eq_sub]
      exact h2

  have h_le : Submodule.span ℝ (Set.range (fun j : {x : Fin 3 // x ≠ 0} => ![C, E₁, E₂] j -ᵥ ![C, E₁, E₂] 0)) ≤ S := Submodule.span_le.mpr h_range
  rw [h_span] at h_le
  have hx : inner ℝ x x = (0 : ℝ) := h_le Submodule.mem_top
  exact inner_self_eq_zero.mp hx

theorem dist_circumcenter_eq_r2_1 (C E₁ E₂ : ℝ²)
  (tri : AffineIndependent ℝ ![C, E₁, E₂]) :
  dist C (circumcenter ⟨![C, E₁, E₂], tri⟩) = dist E₁ (circumcenter ⟨![C, E₁, E₂], tri⟩) :=
by
  have hC : dist C (circumcenter ⟨![C, E₁, E₂], tri⟩) = (⟨![C, E₁, E₂], tri⟩ : Affine.Simplex ℝ ℝ² 2).circumradius :=
    Affine.Simplex.dist_circumcenter_eq_circumradius ⟨![C, E₁, E₂], tri⟩ 0
  have hE₁ : dist E₁ (circumcenter ⟨![C, E₁, E₂], tri⟩) = (⟨![C, E₁, E₂], tri⟩ : Affine.Simplex ℝ ℝ² 2).circumradius :=
    Affine.Simplex.dist_circumcenter_eq_circumradius ⟨![C, E₁, E₂], tri⟩ 1
  exact hC.trans hE₁.symm

theorem dist_circumcenter_eq_r2_2 (C E₁ E₂ : ℝ²)
  (tri : AffineIndependent ℝ ![C, E₁, E₂]) :
  dist C (circumcenter ⟨![C, E₁, E₂], tri⟩) = dist E₂ (circumcenter ⟨![C, E₁, E₂], tri⟩) :=
by
  have h1 : dist C (circumcenter ⟨![C, E₁, E₂], tri⟩) = _ :=
    Affine.Simplex.dist_circumcenter_eq_circumradius (⟨![C, E₁, E₂], tri⟩ : Affine.Simplex ℝ ℝ² 2) (0 : Fin 3)
  have h2 : dist E₂ (circumcenter ⟨![C, E₁, E₂], tri⟩) = _ :=
    Affine.Simplex.dist_circumcenter_eq_circumradius (⟨![C, E₁, E₂], tri⟩ : Affine.Simplex ℝ ℝ² 2) (2 : Fin 3)
  rw [h1, h2]

theorem circumcenter_eq_center_r2 (C E₁ E₂ c : ℝ²) (r : ℝ)
  (tri : AffineIndependent ℝ ![C, E₁, E₂])
  (hC : dist C c = r)
  (hE1 : dist E₁ c = r)
  (hE2 : dist E₂ c = r) :
  c = circumcenter ⟨![C, E₁, E₂], tri⟩ :=
by
  have h_dist_c_1 : dist C c = dist E₁ c := by rw [hC, hE1]
  have h_dist_c_2 : dist C c = dist E₂ c := by rw [hC, hE2]

  have h_dist_O_1 : dist C (circumcenter ⟨![C, E₁, E₂], tri⟩) = dist E₁ (circumcenter ⟨![C, E₁, E₂], tri⟩) :=
    dist_circumcenter_eq_r2_1 C E₁ E₂ tri
  have h_dist_O_2 : dist C (circumcenter ⟨![C, E₁, E₂], tri⟩) = dist E₂ (circumcenter ⟨![C, E₁, E₂], tri⟩) :=
    dist_circumcenter_eq_r2_2 C E₁ E₂ tri

  have h_inner_1 : inner ℝ (c - circumcenter ⟨![C, E₁, E₂], tri⟩) (E₁ - C) = (0 : ℝ) :=
    inner_sub_sub_eq_zero_of_dist_eq_r2 c (circumcenter ⟨![C, E₁, E₂], tri⟩) C E₁ h_dist_c_1 h_dist_O_1
  have h_inner_2 : inner ℝ (c - circumcenter ⟨![C, E₁, E₂], tri⟩) (E₂ - C) = (0 : ℝ) :=
    inner_sub_sub_eq_zero_of_dist_eq_r2 c (circumcenter ⟨![C, E₁, E₂], tri⟩) C E₂ h_dist_c_2 h_dist_O_2

  have h_zero : c - circumcenter ⟨![C, E₁, E₂], tri⟩ = 0 :=
    eq_zero_of_inner_eq_zero_of_affine_independent_r2 (c - circumcenter ⟨![C, E₁, E₂], tri⟩) C E₁ E₂ tri h_inner_1 h_inner_2

  exact sub_eq_zero.mp h_zero

theorem dist_O_X_eq_dist_O_C_X_prop (X C E₁ E₂ O : ℝ²)
  (hCospherical : Cospherical {X, C, E₁, E₂})
  (tri2 : AffineIndependent ℝ ![C, E₁, E₂])
  (hO : O = circumcenter ⟨![C, E₁, E₂], tri2⟩) :
  dist O X = dist O C :=
by
  obtain ⟨c, r, hX, hC, hE1, hE2⟩ := cospherical_extract_r2 X C E₁ E₂ hCospherical
  have h_c_eq_O : c = O := by
    rw [hO]
    exact circumcenter_eq_center_r2 C E₁ E₂ c r tri2 hC hE1 hE2
  rw [← h_c_eq_O]
  rw [dist_comm c X, dist_comm c C]
  rw [hX, hC]

theorem quadratic_eq_of_dist_eq_X_prop (X C O A : ℝ²) (k t : ℝ)
  (hX : X - C = k • (A - C))
  (h_dist : dist O X = dist O C)
  (h_t : inner ℝ (O - C) (A - C) = t * inner ℝ (A - C) (A - C)) :
  k^2 * inner ℝ (A - C) (A - C) - (2 : ℝ) * k * (t * inner ℝ (A - C) (A - C)) = (0 : ℝ) :=
by

  -- First, establish the connection between squared norm and real inner product.
  have h_norm_sq : ∀ (v : ℝ²), ‖v‖ ^ 2 = inner ℝ v v := by
    intro v
    have hz : ‖v - v‖ ^ 2 = ‖v‖ ^ 2 - 2 * inner ℝ v v + ‖v‖ ^ 2 := norm_sub_pow_two_real v v
    have hvv : v - v = 0 := sub_self v
    rw [hvv] at hz
    have h0 : ‖(0 : ℝ²)‖ = 0 := norm_zero
    rw [h0] at hz
    have h00 : (0 : ℝ) ^ 2 = 0 := by ring
    rw [h00] at hz
    linarith [hz]

  -- Convert the distance equality to a squared norm equality.
  have hd : dist O X ^ 2 = dist O C ^ 2 := by rw [h_dist]
  have dX : dist O X = ‖O - X‖ := dist_eq_norm O X
  have dC : dist O C = ‖O - C‖ := dist_eq_norm O C
  rw [dX, dC] at hd

  -- Substitute O - X with (O - C) - (X - C).
  have h2 : O - X = O - C - (X - C) := by abel
  have h3 : ‖O - C - (X - C)‖ ^ 2 = ‖O - C‖ ^ 2 := by
    rw [← h2]
    exact hd

  -- Expand the squared norm of the difference.
  have hn := norm_sub_pow_two_real (O - C) (X - C)
  have h4 : ‖O - C‖ ^ 2 - 2 * inner ℝ (O - C) (X - C) + ‖X - C‖ ^ 2 = ‖O - C‖ ^ 2 := by
    calc ‖O - C‖ ^ 2 - 2 * inner ℝ (O - C) (X - C) + ‖X - C‖ ^ 2
      _ = ‖(O - C) - (X - C)‖ ^ 2 := hn.symm
      _ = ‖O - C‖ ^ 2 := h3

  -- Simplify to isolate the terms involving X - C.
  have h5 : ‖X - C‖ ^ 2 - 2 * inner ℝ (O - C) (X - C) = 0 := by linarith [h4]

  -- Rewrite the squared norm as an inner product.
  have h6 : inner ℝ (X - C) (X - C) - 2 * inner ℝ (O - C) (X - C) = 0 := by
    calc inner ℝ (X - C) (X - C) - 2 * inner ℝ (O - C) (X - C)
      _ = ‖X - C‖ ^ 2 - 2 * inner ℝ (O - C) (X - C) := by rw [← h_norm_sq (X - C)]
      _ = 0 := h5

  -- Substitute the vector X - C with its scalar multiple representation.
  have h7 : inner ℝ (k • (A - C)) (k • (A - C)) - 2 * inner ℝ (O - C) (k • (A - C)) = 0 := by
    have h_sub : X - C = k • (A - C) := hX
    rw [h_sub] at h6
    exact h6

  -- Helper properties for scalar multiplication in real inner products.
  have hs_left : ∀ (r : ℝ) (x y : ℝ²), inner ℝ (r • x) y = r * inner ℝ x y := by
    intro r x y
    calc inner ℝ (r • x) y = (starRingEnd ℝ) r * inner ℝ x y := InnerProductSpace.smul_left x y r
      _ = r * inner ℝ x y := by simp

  have h_symm : ∀ (x y : ℝ²), inner ℝ x y = inner ℝ y x := by
    intro x y
    exact real_inner_comm y x

  have hs_right : ∀ (r : ℝ) (x y : ℝ²), inner ℝ x (r • y) = r * inner ℝ x y := by
    intro r x y
    calc inner ℝ x (r • y) = inner ℝ (r • y) x := h_symm x (r • y)
      _ = r * inner ℝ y x := hs_left r y x
      _ = r * inner ℝ x y := by rw [h_symm y x]

  -- Extract the scalars from the inner products in h7.
  have h7_1 : inner ℝ (k • (A - C)) (k • (A - C)) = k * (k * inner ℝ (A - C) (A - C)) := by
    calc inner ℝ (k • (A - C)) (k • (A - C))
      _ = k * inner ℝ (A - C) (k • (A - C)) := hs_left k (A - C) (k • (A - C))
      _ = k * (k * inner ℝ (A - C) (A - C)) := by rw [hs_right k (A - C) (A - C)]

  have h7_2 : inner ℝ (O - C) (k • (A - C)) = k * inner ℝ (O - C) (A - C) := by
    exact hs_right k (O - C) (A - C)

  have h7_3 : k * (k * inner ℝ (A - C) (A - C)) - 2 * (k * inner ℝ (O - C) (A - C)) = 0 := by
    calc k * (k * inner ℝ (A - C) (A - C)) - 2 * (k * inner ℝ (O - C) (A - C))
      _ = inner ℝ (k • (A - C)) (k • (A - C)) - 2 * inner ℝ (O - C) (k • (A - C)) := by rw [← h7_1, ← h7_2]
      _ = 0 := h7

  -- Substitute the parameter t relationship.
  have h7_4 : k * (k * inner ℝ (A - C) (A - C)) - 2 * (k * (t * inner ℝ (A - C) (A - C))) = 0 := by
    calc k * (k * inner ℝ (A - C) (A - C)) - 2 * (k * (t * inner ℝ (A - C) (A - C)))
      _ = k * (k * inner ℝ (A - C) (A - C)) - 2 * (k * inner ℝ (O - C) (A - C)) := by rw [← h_t]
      _ = 0 := h7_3

  -- Complete the proof using basic ring algebra.
  calc k ^ 2 * inner ℝ (A - C) (A - C) - (2 : ℝ) * k * (t * inner ℝ (A - C) (A - C))
    _ = k * (k * inner ℝ (A - C) (A - C)) - 2 * (k * (t * inner ℝ (A - C) (A - C))) := by ring
    _ = 0 := h7_4

theorem k_ne_zero_of_X_ne_C_X_prop (X A C : ℝ²) (k : ℝ)
  (hX : X - C = k • (A - C))
  (hX_ne_C : X ≠ C) :
  k ≠ (0 : ℝ) :=
by
  intro hk
  rw [hk] at hX
  rw [zero_smul] at hX
  have hXC : X = C := sub_eq_zero.mp hX
  exact hX_ne_C hXC

theorem inner_AC_ne_zero_X_prop (A C : ℝ²) (h : A ≠ C) :
  inner ℝ (A - C) (A - C) ≠ (0 : ℝ) :=
by
  intro h1
  rw [inner_self_eq_zero] at h1
  rw [sub_eq_zero] at h1
  exact h h1

theorem k_eq_two_t_X_prop (A C : ℝ²) (k t : ℝ)
  (h_inner_AC_ne_zero : inner ℝ (A - C) (A - C) ≠ (0 : ℝ))
  (h_eq : k^2 * inner ℝ (A - C) (A - C) - (2 : ℝ) * k * (t * inner ℝ (A - C) (A - C)) = (0 : ℝ))
  (hk_ne_zero : k ≠ (0 : ℝ)) :
  k = (2 : ℝ) * t :=
by
  have H : (k * (k - (2 : ℝ) * t)) * inner ℝ (A - C) (A - C) = k^2 * inner ℝ (A - C) (A - C) - (2 : ℝ) * k * (t * inner ℝ (A - C) (A - C)) := by ring
  have h1 : (k * (k - (2 : ℝ) * t)) * inner ℝ (A - C) (A - C) = (0 : ℝ) := by
    rw [H, h_eq]
  have h2 : k * (k - (2 : ℝ) * t) = (0 : ℝ) := by
    have h_or := mul_eq_zero.mp h1
    cases h_or with
    | inl h_left => exact h_left
    | inr h_right => contradiction
  have h3 : k - (2 : ℝ) * t = (0 : ℝ) := by
    have h_or2 := mul_eq_zero.mp h2
    cases h_or2 with
    | inl h_left => contradiction
    | inr h_right => exact h_right
  linarith

theorem X_prop (A B C E₁ E₂ X O : ℝ²)
  (tri : AffineIndependent ℝ ![A, B, C])
  (hX_ne_C : X ≠ C)
  (hCospherical : Cospherical {X, C, E₁, E₂})
  (hCollinear : Collinear ℝ {X, A, C})
  (tri2 : AffineIndependent ℝ ![C, E₁, E₂])
  (hO : O = circumcenter ⟨![C, E₁, E₂], tri2⟩)
  (t : ℝ) (h_tA : inner ℝ (O - C) (A - C) = t * inner ℝ (A - C) (A - C)) :
  X - C = ((2 : ℝ) * t) • (A - C) :=
by
  have hA_ne_C := A_ne_C_of_AffineIndependent_X_prop A B C tri
  obtain ⟨k, hk⟩ := exists_k_of_collinear_X_prop X A C hCollinear hA_ne_C
  have hO_dist := dist_O_X_eq_dist_O_C_X_prop X C E₁ E₂ O hCospherical tri2 hO
  have h_quad := quadratic_eq_of_dist_eq_X_prop X C O A k t hk hO_dist h_tA
  have hk_ne_zero := k_ne_zero_of_X_ne_C_X_prop X A C k hk hX_ne_C
  have h_inner_ne := inner_AC_ne_zero_X_prop A C hA_ne_C
  have hk_eq := k_eq_two_t_X_prop A C k t h_inner_ne h_quad hk_ne_zero
  rw [hk_eq] at hk
  exact hk

theorem main_identity (A B C D E X O : ℝ²) (t k : ℝ)
  (hD_k : D - C = k • (A - C))
  (hD_inner : inner ℝ (D - C) (A - C) = inner ℝ (B - C) (A - C))
  (hX : X - C = ((2 : ℝ) * t) • (A - C))
  (h_tA : inner ℝ (O - C) (A - C) = t * inner ℝ (A - C) (A - C))
  (hE_eq : inner ℝ (E - C) (A - C) = inner ℝ (E - C) (B - C))
  (hE_inner : inner ℝ (E - C) (E - C) = inner ℝ (E - C) (A - C))
  (hO_E : (4 : ℝ) * t * inner ℝ (E - C) (A - C) - (2 : ℝ) * inner ℝ (O - C) (E - C) = inner ℝ (E - C) (A - C))
  (h_t_ab : (2 : ℝ) * t * inner ℝ (A - C) (B - C) = inner ℝ (E - C) (A - C)) :
  inner ℝ (O - X) (E - D) = (0 : ℝ) :=
by

  have h_main : inner ℝ (O - X) (E - D) = inner ℝ (O - C) (E - C) - inner ℝ (O - C) (D - C) - inner ℝ (X - C) (E - C) + inner ℝ (X - C) (D - C) := by
    calc inner ℝ (O - X) (E - D)
      _ = inner ℝ ((O - C) - (X - C)) ((E - C) - (D - C)) := by
        have h1 : O - X = (O - C) - (X - C) := by abel
        have h2 : E - D = (E - C) - (D - C) := by abel
        rw [h1, h2]
      _ = inner ℝ (O - C) ((E - C) - (D - C)) - inner ℝ (X - C) ((E - C) - (D - C)) := by rw [inner_sub_left]
      _ = inner ℝ ((E - C) - (D - C)) (O - C) - inner ℝ ((E - C) - (D - C)) (X - C) := by
        have c1 : inner ℝ (O - C) ((E - C) - (D - C)) = inner ℝ ((E - C) - (D - C)) (O - C) := real_inner_comm _ _
        have c2 : inner ℝ (X - C) ((E - C) - (D - C)) = inner ℝ ((E - C) - (D - C)) (X - C) := real_inner_comm _ _
        rw [c1, c2]
      _ = (inner ℝ (E - C) (O - C) - inner ℝ (D - C) (O - C)) - (inner ℝ (E - C) (X - C) - inner ℝ (D - C) (X - C)) := by
        simp only [inner_sub_left]
      _ = (inner ℝ (O - C) (E - C) - inner ℝ (O - C) (D - C)) - (inner ℝ (X - C) (E - C) - inner ℝ (X - C) (D - C)) := by
        have c1 : inner ℝ (E - C) (O - C) = inner ℝ (O - C) (E - C) := real_inner_comm _ _
        have c2 : inner ℝ (D - C) (O - C) = inner ℝ (O - C) (D - C) := real_inner_comm _ _
        have c3 : inner ℝ (E - C) (X - C) = inner ℝ (X - C) (E - C) := real_inner_comm _ _
        have c4 : inner ℝ (D - C) (X - C) = inner ℝ (X - C) (D - C) := real_inner_comm _ _
        rw [c1, c2, c3, c4]
      _ = inner ℝ (O - C) (E - C) - inner ℝ (O - C) (D - C) - inner ℝ (X - C) (E - C) + inner ℝ (X - C) (D - C) := by ring

  have hd1 : inner ℝ (D - C) (A - C) = k * inner ℝ (A - C) (A - C) := by
    calc inner ℝ (D - C) (A - C)
      _ = inner ℝ (k • (A - C)) (A - C) := by rw [hD_k]
      _ = k * inner ℝ (A - C) (A - C) := real_inner_smul_left (A - C) (A - C) k

  have hk_inner : k * inner ℝ (A - C) (A - C) = inner ℝ (B - C) (A - C) := by
    calc k * inner ℝ (A - C) (A - C)
      _ = inner ℝ (D - C) (A - C) := hd1.symm
      _ = inner ℝ (B - C) (A - C) := hD_inner

  have hoD : inner ℝ (O - C) (D - C) = t * inner ℝ (A - C) (B - C) := by
    calc inner ℝ (O - C) (D - C)
      _ = inner ℝ (D - C) (O - C) := real_inner_comm _ _
      _ = inner ℝ (k • (A - C)) (O - C) := by rw [hD_k]
      _ = k * inner ℝ (A - C) (O - C) := real_inner_smul_left (A - C) (O - C) k
      _ = k * inner ℝ (O - C) (A - C) := by rw [real_inner_comm (A - C) (O - C)]
      _ = k * (t * inner ℝ (A - C) (A - C)) := by rw [h_tA]
      _ = t * (k * inner ℝ (A - C) (A - C)) := by ring
      _ = t * inner ℝ (B - C) (A - C) := by rw [hk_inner]
      _ = t * inner ℝ (A - C) (B - C) := by rw [real_inner_comm (B - C) (A - C)]

  have hXE : inner ℝ (X - C) (E - C) = (2 : ℝ) * t * inner ℝ (E - C) (A - C) := by
    calc inner ℝ (X - C) (E - C)
      _ = inner ℝ (((2 : ℝ) * t) • (A - C)) (E - C) := by rw [hX]
      _ = ((2 : ℝ) * t) * inner ℝ (A - C) (E - C) := real_inner_smul_left (A - C) (E - C) ((2 : ℝ) * t)
      _ = (2 : ℝ) * t * inner ℝ (E - C) (A - C) := by rw [real_inner_comm (A - C) (E - C)]

  have hXD : inner ℝ (X - C) (D - C) = (2 : ℝ) * t * inner ℝ (A - C) (B - C) := by
    calc inner ℝ (X - C) (D - C)
      _ = inner ℝ (((2 : ℝ) * t) • (A - C)) (D - C) := by rw [hX]
      _ = ((2 : ℝ) * t) * inner ℝ (A - C) (D - C) := real_inner_smul_left (A - C) (D - C) ((2 : ℝ) * t)
      _ = ((2 : ℝ) * t) * inner ℝ (D - C) (A - C) := by rw [real_inner_comm (A - C) (D - C)]
      _ = ((2 : ℝ) * t) * inner ℝ (B - C) (A - C) := by rw [hD_inner]
      _ = (2 : ℝ) * t * inner ℝ (A - C) (B - C) := by rw [real_inner_comm (B - C) (A - C)]

  have e1 : inner ℝ (O - X) (E - D) = inner ℝ (O - C) (E - C) - (t * inner ℝ (A - C) (B - C)) - (2 : ℝ) * (t * inner ℝ (E - C) (A - C)) + (2 : ℝ) * (t * inner ℝ (A - C) (B - C)) := by
    calc inner ℝ (O - X) (E - D)
      _ = inner ℝ (O - C) (E - C) - inner ℝ (O - C) (D - C) - inner ℝ (X - C) (E - C) + inner ℝ (X - C) (D - C) := h_main
      _ = inner ℝ (O - C) (E - C) - t * inner ℝ (A - C) (B - C) - inner ℝ (X - C) (E - C) + inner ℝ (X - C) (D - C) := by rw [hoD]
      _ = inner ℝ (O - C) (E - C) - t * inner ℝ (A - C) (B - C) - (2 : ℝ) * t * inner ℝ (E - C) (A - C) + inner ℝ (X - C) (D - C) := by rw [hXE]
      _ = inner ℝ (O - C) (E - C) - t * inner ℝ (A - C) (B - C) - (2 : ℝ) * t * inner ℝ (E - C) (A - C) + (2 : ℝ) * t * inner ℝ (A - C) (B - C) := by rw [hXD]
      _ = inner ℝ (O - C) (E - C) - (t * inner ℝ (A - C) (B - C)) - (2 : ℝ) * (t * inner ℝ (E - C) (A - C)) + (2 : ℝ) * (t * inner ℝ (A - C) (B - C)) := by ring

  have h_t_ab' : (2 : ℝ) * (t * inner ℝ (A - C) (B - C)) = inner ℝ (E - C) (A - C) := by
    calc (2 : ℝ) * (t * inner ℝ (A - C) (B - C))
      _ = (2 : ℝ) * t * inner ℝ (A - C) (B - C) := by ring
      _ = inner ℝ (E - C) (A - C) := h_t_ab

  have hO_E' : (4 : ℝ) * (t * inner ℝ (E - C) (A - C)) - (2 : ℝ) * inner ℝ (O - C) (E - C) = inner ℝ (E - C) (A - C) := by
    calc (4 : ℝ) * (t * inner ℝ (E - C) (A - C)) - (2 : ℝ) * inner ℝ (O - C) (E - C)
      _ = (4 : ℝ) * t * inner ℝ (E - C) (A - C) - (2 : ℝ) * inner ℝ (O - C) (E - C) := by ring
      _ = inner ℝ (E - C) (A - C) := hO_E

  linarith [e1, hO_E', h_t_ab']

theorem perp_of_inner_zero (X O D E : ℝ²) (h : inner ℝ (O - X) (E - D) = (0 : ℝ)) :
  (affineSpan ℝ {X, O}).direction ⟂ (affineSpan ℝ {D, E}).direction :=
by
  -- Convert orthogonality of submodules to an inner product equation
  rw [Submodule.isOrtho_iff_inner_eq]
  intro u hu v hv

  -- The direction of the affine span of 2 points is the vector span of their difference
  rw [direction_affineSpan, vectorSpan_pair] at hu hv

  -- Extract the scalar multiples representing u and v
  rcases Submodule.mem_span_singleton.mp hu with ⟨a, rfl⟩
  rcases Submodule.mem_span_singleton.mp hv with ⟨b, rfl⟩

  -- Provide all sign-variants of the target condition to robustly handle the direction of the vector span
  have h1 : inner ℝ (O - X) (E - D) = (0 : ℝ) := h
  have h2 : inner ℝ (X - O) (E - D) = (0 : ℝ) := by
    rw [← neg_sub O X, inner_neg_left, h1, neg_zero]
  have h3 : inner ℝ (O - X) (D - E) = (0 : ℝ) := by
    rw [← neg_sub E D, inner_neg_right, h1, neg_zero]
  have h4 : inner ℝ (X - O) (D - E) = (0 : ℝ) := by
    rw [← neg_sub O X, ← neg_sub E D, inner_neg_left, inner_neg_right, neg_neg, h1]

  -- State that `-ᵥ` (vsub) is literally `-` (sub) for vectors in `ℝ²`
  have v1 : O -ᵥ X = O - X := rfl
  have v2 : X -ᵥ O = X - O := rfl
  have v3 : E -ᵥ D = E - D := rfl
  have v4 : D -ᵥ E = D - E := rfl

  -- Simplify using our variants, vsub definitions, and inner product bilinearity laws
  simp [v1, v2, v3, v4, inner_smul_left, inner_smul_right, h1, h2, h3, h4]

theorem PBBasic027 (A B C : ℝ²) (tri : AffineIndependent ℝ ![A, B, C])
    (acute : AcuteAngled ⟨![A, B, C], tri⟩) : let D := altitudeFoot ⟨![A, B, C], tri⟩ 1
    let E := altitudeFoot ⟨![A, B, C], tri⟩ 2
    let E₁ := reflection (affineSpan ℝ {A, C}) E
    let E₂ := reflection (affineSpan ℝ {B, C}) E
    ∀ X : ℝ², X ≠ C → Cospherical {X, C, E₁, E₂} → Collinear ℝ {X, A, C} →
    ∀ (tri2 : AffineIndependent ℝ ![C, E₁, E₂]),
    let O := circumcenter ⟨![C, E₁, E₂], tri2⟩
    (affineSpan ℝ {X, O}).direction ⟂ (affineSpan ℝ {D, E}).direction :=
by
  intros D E E₁ E₂ X hX_ne_C hCospherical hCollinear tri2 O
  have hD := D_prop A B C D tri rfl
  have hE := E_prop A B C E tri acute rfl
  have hE12 := E1_E2_prop A B C E E₁ E₂ rfl rfl
  have hO_prop := O_prop A B C E E₁ E₂ O hE12.1 hE12.2 hE.2.1 hE.1 hE.2.2 tri2 rfl

  have hD_inner := hD.1
  obtain ⟨k, hD_k⟩ := hD.2
  obtain ⟨t, h_t⟩ := hO_prop

  have htA := h_t.1
  have htB := h_t.2.1
  have hOE := h_t.2.2

  -- Apply corrected t_prop strictly passing the non-zero hypothesis hE.2.2
  have ht_ab := t_prop A B C O E tri hE.1 hE.2.1 t htA htB hOE hE.2.2

  have hX := X_prop A B C E₁ E₂ X O tri hX_ne_C hCospherical hCollinear tri2 rfl t htA
  have h_main := main_identity A B C D E X O t k hD_k hD_inner hX htA hE.1 hE.2.1 hOE ht_ab

  exact perp_of_inner_zero X O D E h_main
