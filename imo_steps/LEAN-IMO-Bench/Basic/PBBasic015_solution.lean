import Mathlib
structure Car where (width length : Nat)
def Cars (n : ℕ) := Fin n → Car
variable {n : ℕ}
structure Cars.IniCond (cars : Cars n) : Prop where
  distinct_width : (Car.width ∘ cars).Injective
  distinct_length : (Car.length ∘ cars).Injective
  increasing_length : Monotone (Car.length ∘ cars)
structure Cars.Swap (cars : Cars n) where
  (i1 i2 : Fin n)
  adjacent : i1.val + 1 = i2.val
  shorter_length : (cars i1).length < (cars i2).length
  greater_width : (cars i1).width > (cars i2).width
def Cars.Swap.apply {cars : Cars n} (step : Swap cars) : Cars n :=
  cars ∘ Equiv.swap step.i1 step.i2
def Cars.swapRel (prev next : Cars n) : Prop :=
  ∃ step : prev.Swap, step.apply = next

def measureZ {n : ℕ} (c : Cars n) : ℤ := ∑ i : Fin n, ((c i).width : ℤ) * ((n : ℤ) - (i.val : ℤ))

def measureNat {n : ℕ} (c : Cars n) : ℕ := (measureZ c).toNat

def Invariant {n : ℕ} (c : Cars n) : Prop := ∀ i j : Fin n, i < j → (c i).width < (c j).width ∨ (c i).length < (c j).length

theorem acc_swapRel {n : ℕ} (start : Cars n) : Acc (fun next prev => Cars.swapRel prev next) start :=
by
  have H : ∀ (prev next : Cars n), Cars.swapRel prev next → measureNat next < measureNat prev := by
    intro prev next h_swap
    rcases h_swap with ⟨step, h_next_eq⟩

    have hi12 : step.i1 ≠ step.i2 := by
      intro h
      have hval : step.i1.val = step.i2.val := congrArg Fin.val h
      have h_adj := step.adjacent
      omega

    have hi2_mem : step.i2 ∈ Finset.univ.erase step.i1 := by
      simp only [Finset.mem_erase, Finset.mem_univ, and_true]
      exact hi12.symm

    have eq1 : measureZ prev = ((prev step.i1).width : ℤ) * ((n : ℤ) - (step.i1.val : ℤ)) + ∑ i ∈ Finset.univ.erase step.i1, ((prev i).width : ℤ) * ((n : ℤ) - (i.val : ℤ)) := by
      unfold measureZ
      exact Eq.symm (Finset.add_sum_erase Finset.univ (fun i => ((prev i).width : ℤ) * ((n : ℤ) - (i.val : ℤ))) (Finset.mem_univ step.i1))

    have eq1_b : ∑ i ∈ Finset.univ.erase step.i1, ((prev i).width : ℤ) * ((n : ℤ) - (i.val : ℤ)) = ((prev step.i2).width : ℤ) * ((n : ℤ) - (step.i2.val : ℤ)) + ∑ i ∈ (Finset.univ.erase step.i1).erase step.i2, ((prev i).width : ℤ) * ((n : ℤ) - (i.val : ℤ)) := by
      exact Eq.symm (Finset.add_sum_erase (Finset.univ.erase step.i1) (fun i => ((prev i).width : ℤ) * ((n : ℤ) - (i.val : ℤ))) hi2_mem)

    have eq2 : measureZ next = ((next step.i1).width : ℤ) * ((n : ℤ) - (step.i1.val : ℤ)) + ∑ i ∈ Finset.univ.erase step.i1, ((next i).width : ℤ) * ((n : ℤ) - (i.val : ℤ)) := by
      unfold measureZ
      exact Eq.symm (Finset.add_sum_erase Finset.univ (fun i => ((next i).width : ℤ) * ((n : ℤ) - (i.val : ℤ))) (Finset.mem_univ step.i1))

    have eq2_b : ∑ i ∈ Finset.univ.erase step.i1, ((next i).width : ℤ) * ((n : ℤ) - (i.val : ℤ)) = ((next step.i2).width : ℤ) * ((n : ℤ) - (step.i2.val : ℤ)) + ∑ i ∈ (Finset.univ.erase step.i1).erase step.i2, ((next i).width : ℤ) * ((n : ℤ) - (i.val : ℤ)) := by
      exact Eq.symm (Finset.add_sum_erase (Finset.univ.erase step.i1) (fun i => ((next i).width : ℤ) * ((n : ℤ) - (i.val : ℤ))) hi2_mem)

    have eq3 : ∑ i ∈ (Finset.univ.erase step.i1).erase step.i2, ((prev i).width : ℤ) * ((n : ℤ) - (i.val : ℤ)) = ∑ i ∈ (Finset.univ.erase step.i1).erase step.i2, ((next i).width : ℤ) * ((n : ℤ) - (i.val : ℤ)) := by
      apply Finset.sum_congr rfl
      intro i hi
      simp only [Finset.mem_erase, Finset.mem_univ, and_true] at hi
      have h1 : i ≠ step.i2 := hi.1
      have h2 : i ≠ step.i1 := hi.2
      have H_eq : next i = prev i := by
        rw [← h_next_eq]
        change prev (Equiv.swap step.i1 step.i2 i) = prev i
        have h : Equiv.swap step.i1 step.i2 i = i := Equiv.swap_apply_of_ne_of_ne h2 h1
        rw [h]
      rw [H_eq]

    have hn1 : next step.i1 = prev step.i2 := by
      rw [← h_next_eq]
      change prev (Equiv.swap step.i1 step.i2 step.i1) = prev step.i2
      have h : Equiv.swap step.i1 step.i2 step.i1 = step.i2 := Equiv.swap_apply_left step.i1 step.i2
      rw [h]

    have hn2 : next step.i2 = prev step.i1 := by
      rw [← h_next_eq]
      change prev (Equiv.swap step.i1 step.i2 step.i2) = prev step.i1
      have h : Equiv.swap step.i1 step.i2 step.i2 = step.i1 := Equiv.swap_apply_right step.i1 step.i2
      rw [h]

    rw [eq1_b] at eq1
    rw [eq2_b] at eq2
    rw [hn1, hn2, ← eq3] at eq2

    have h_diff : measureZ prev - measureZ next = ((prev step.i1).width : ℤ) - ((prev step.i2).width : ℤ) := by
      rw [eq1, eq2]
      have h_v : ((step.i2.val : ℤ) - (step.i1.val : ℤ)) = 1 := by
        have := step.adjacent
        omega

      let S := ∑ i ∈ (Finset.univ.erase step.i1).erase step.i2, ((prev i).width : ℤ) * ((n : ℤ) - (i.val : ℤ))
      have H_calc : ((prev step.i1).width : ℤ) * ((n : ℤ) - (step.i1.val : ℤ)) + (((prev step.i2).width : ℤ) * ((n : ℤ) - (step.i2.val : ℤ)) + S) - (((prev step.i2).width : ℤ) * ((n : ℤ) - (step.i1.val : ℤ)) + (((prev step.i1).width : ℤ) * ((n : ℤ) - (step.i2.val : ℤ)) + S)) = ((prev step.i1).width : ℤ) - ((prev step.i2).width : ℤ) := by
        calc
          ((prev step.i1).width : ℤ) * ((n : ℤ) - (step.i1.val : ℤ)) + (((prev step.i2).width : ℤ) * ((n : ℤ) - (step.i2.val : ℤ)) + S) - (((prev step.i2).width : ℤ) * ((n : ℤ) - (step.i1.val : ℤ)) + (((prev step.i1).width : ℤ) * ((n : ℤ) - (step.i2.val : ℤ)) + S))
            = (((prev step.i1).width : ℤ) - ((prev step.i2).width : ℤ)) * ((step.i2.val : ℤ) - (step.i1.val : ℤ)) := by ring
          _ = (((prev step.i1).width : ℤ) - ((prev step.i2).width : ℤ)) * 1 := by rw [h_v]
          _ = ((prev step.i1).width : ℤ) - ((prev step.i2).width : ℤ) := by ring
      exact H_calc

    have hwidth : ((prev step.i2).width : ℤ) < ((prev step.i1).width : ℤ) := by
      have := step.greater_width
      omega

    have hz : measureZ next < measureZ prev := by
      linarith [h_diff, hwidth]

    have hpos_next : 0 ≤ measureZ next := by
      unfold measureZ
      apply Finset.sum_nonneg
      intro i _
      apply mul_nonneg
      · omega
      · have := i.isLt; omega

    unfold measureNat
    have hz2 : 0 ≤ measureZ next := hpos_next
    have hz3 : measureZ next < measureZ prev := hz
    omega

  have h_wf : ∀ k (s : Cars n), measureNat s < k → Acc (fun next prev => Cars.swapRel prev next) s := by
    intro k
    induction k with
    | zero =>
      intros s h
      omega
    | succ k ih =>
      intros s h
      constructor
      intro next h_swap
      apply ih
      have := H s next h_swap
      omega

  exact h_wf (measureNat start + 1) start (by omega)

theorem reach_inv {n : ℕ} {start final : Cars n} (hReach : Relation.ReflTransGen Cars.swapRel start final) (hIni : start.IniCond) : Invariant final ∧ (Car.width ∘ final).Injective :=
by
  induction hReach with
  | refl =>
    constructor
    · intro i j hij
      right
      have hle : (start i).length ≤ (start j).length := hIni.increasing_length (le_of_lt hij)
      have hneq : (start i).length ≠ (start j).length := by
        intro h
        have h1 : (Car.length ∘ start) i = (Car.length ∘ start) j := h
        have h2 : i = j := hIni.distinct_length h1
        exact ne_of_lt hij h2
      exact lt_of_le_of_ne hle hneq
    · exact hIni.distinct_width
  | tail h_prev hSwap ih =>
    rcases ih with ⟨hInv, hInj⟩
    rcases hSwap with ⟨step, rfl⟩
    let u := step.i1
    let v := step.i2
    have huv_val : u.val < v.val := by
      have h1 : u.val < u.val + 1 := Nat.lt_succ_self u.val
      exact step.adjacent ▸ h1
    have huv : u < v := huv_val

    constructor
    · intro i j hij
      have h_cases : (i = u ∧ j = v) ∨ Equiv.swap u v i < Equiv.swap u v j := by
        by_cases hiu : i = u
        · by_cases hjv : j = v
          · left; exact ⟨hiu, hjv⟩
          · right
            have hj_gt_v : v < j := by
              have h1 : u.val < j.val := hiu ▸ hij
              have h3 : u.val + 1 ≤ j.val := h1
              have h4 : v.val ≤ j.val := step.adjacent ▸ h3
              have h2 : j.val ≠ v.val := fun h => hjv (Fin.ext h)
              have h_val : v.val < j.val := lt_of_le_of_ne h4 h2.symm
              exact h_val
            have hi' : Equiv.swap u v i = v := by rw [hiu, Equiv.swap_apply_left]
            have hju : j ≠ u := by
              intro h
              rw [h] at hj_gt_v
              exact lt_irrefl u (lt_trans huv hj_gt_v)
            have hj' : Equiv.swap u v j = j := Equiv.swap_apply_of_ne_of_ne hju hjv
            rw [hi', hj']
            exact hj_gt_v
        · by_cases hjv : j = v
          · right
            have hi_lt_u : i < u := by
              have h1 : i.val < v.val := hjv ▸ hij
              have h3 : v.val = u.val + 1 := step.adjacent.symm
              have h4 : i.val + 1 ≤ u.val + 1 := h3 ▸ h1
              have h5 : i.val ≤ u.val := Nat.le_of_succ_le_succ h4
              have h2 : i.val ≠ u.val := fun h => hiu (Fin.ext h)
              have h_val : i.val < u.val := lt_of_le_of_ne h5 h2
              exact h_val
            have hi_ne_v : i ≠ v := by
              intro h
              rw [h] at hi_lt_u
              exact lt_irrefl v (lt_trans hi_lt_u huv)
            have hi' : Equiv.swap u v i = i := Equiv.swap_apply_of_ne_of_ne hiu hi_ne_v
            have hj' : Equiv.swap u v j = u := by rw [hjv, Equiv.swap_apply_right]
            rw [hi', hj']
            exact hi_lt_u
          · right
            by_cases hiv : i = v
            · have hj_gt_v : v < j := hiv ▸ hij
              have hju : j ≠ u := by
                intro h
                rw [h] at hj_gt_v
                exact lt_irrefl u (lt_trans huv hj_gt_v)
              have hi' : Equiv.swap u v i = u := by rw [hiv, Equiv.swap_apply_right]
              have hj' : Equiv.swap u v j = j := Equiv.swap_apply_of_ne_of_ne hju hjv
              rw [hi', hj']
              exact lt_trans huv hj_gt_v
            · by_cases hju : j = u
              · have hi_lt_u : i < u := hju ▸ hij
                have hi' : Equiv.swap u v i = i := Equiv.swap_apply_of_ne_of_ne hiu hiv
                have hj' : Equiv.swap u v j = v := by rw [hju, Equiv.swap_apply_left]
                rw [hi', hj']
                exact lt_trans hi_lt_u huv
              · have hi' : Equiv.swap u v i = i := Equiv.swap_apply_of_ne_of_ne hiu hiv
                have hj' : Equiv.swap u v j = j := Equiv.swap_apply_of_ne_of_ne hju hjv
                rw [hi', hj']
                exact hij

      cases h_cases with
      | inl heq =>
        rcases heq with ⟨hiu, hjv⟩
        left
        simp only [Cars.Swap.apply, Function.comp_apply]
        have hi' : Equiv.swap u v i = v := by rw [hiu, Equiv.swap_apply_left]
        have hj' : Equiv.swap u v j = u := by rw [hjv, Equiv.swap_apply_right]
        rw [hi', hj']
        exact step.greater_width
      | inr hlt =>
        simp only [Cars.Swap.apply, Function.comp_apply]
        exact hInv (Equiv.swap u v i) (Equiv.swap u v j) hlt

    · intro x y hxy
      have h1 : Equiv.swap u v x = Equiv.swap u v y := by
        apply hInj
        exact hxy
      exact (Equiv.swap u v).injective h1

theorem monotone_of_no_swap {n : ℕ} {c : Cars n} (hInv : Invariant c) (hInj : (Car.width ∘ c).Injective) (hEmpty : IsEmpty c.Swap) : Monotone (Car.width ∘ c) :=
by
  cases n with
  | zero =>
    intro i j _
    exact Fin.elim0 i
  | succ m =>
    apply Fin.monotone_iff_le_succ.mpr
    intro i
    by_contra h
    let i1 := i.castSucc
    let i2 := i.succ
    change ¬ (c i1).width ≤ (c i2).width at h
    have h_adj : i1.val + 1 = i2.val := rfl
    have h_lt : i1 < i2 := by omega
    have h_gt : (c i1).width > (c i2).width := by omega
    have h_inv := hInv i1 i2 h_lt
    cases h_inv with
    | inl h_w =>
      omega
    | inr h_l =>
      have step : c.Swap := {
        i1 := i1
        i2 := i2
        adjacent := h_adj
        shorter_length := h_l
        greater_width := h_gt
      }
      exact hEmpty.false step

theorem PBBasic015 (start : Cars n)
  (ini : start.IniCond) : (Acc (fun next prev => Cars.swapRel prev next) start) ∧


  (∀ final, Relation.ReflTransGen Cars.swapRel start final →
    IsEmpty final.Swap → Monotone (Car.width ∘ final)) :=
by
  constructor
  · exact acc_swapRel start
  · intro final hReach hEmpty
    have ⟨hInv, hInj⟩ := reach_inv hReach ini
    exact monotone_of_no_swap hInv hInj hEmpty
