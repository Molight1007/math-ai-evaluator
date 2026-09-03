import Mathlib
set_option linter.unusedVariables.analyzeTactics true

open NNReal Nat BigOperators Finset

-- imo-official.org/problems/IMO2007SL.pdf


lemma aux1
  (a : ℕ → NNReal)
  (m : ℕ)
  (hm₀ : Nat.succ 4 ≤ m) :
  a (m - 1) ^ 2 + a m ^ 2 + a 1 ^ 2 + a 2 ^ 2 ≤ ∑ x ∈ Finset.range m, a (x + 1) ^ 2 := by
  let fs: Finset ℕ := {0, 1, m-2, m-1}
  have h₀: fs = {0, 1, m-2, m-1} := by rfl
  have h₁: fs ⊆ Finset.range m := by
    refine insert_subset ?_ ?_
    . refine mem_range.mpr ?_
      exact zero_lt_of_lt hm₀
    . refine insert_subset ?_ ?_
      . refine mem_range.mpr ?_
        linarith
      . refine insert_subset ?_ ?_
        . refine mem_range.mpr ?_
          refine sub_lt ?_ (by norm_num)
          exact zero_lt_of_lt hm₀
        . refine singleton_subset_iff.mpr ?_
          refine mem_range.mpr ?_
          exact sub_one_lt_of_lt hm₀
  rw [← Finset.sum_sdiff h₁]
  have h₂: ∑ x ∈ fs, a (x + 1) ^ 2 = a (m - 1) ^ 2 + a m ^ 2 + a 1 ^ 2 + a 2 ^ 2 := by
    rw [h₀]
    have g₀: 0 ∈ fs := by exact mem_insert_self 0 {1, m - 2, m - 1}
    rw [← Finset.add_sum_erase fs _ g₀]
    simp
    have g₁: 4 ≤ m - 1 := by exact Nat.le_sub_one_of_lt hm₀
    have g₂: 3 ≤ m - 2 := by exact le_sub_of_add_le hm₀
    have g₃: fs.erase 0 = ({1, m - 2, m - 1}:(Finset ℕ)) := by
      rw [h₀]
      refine erase_insert ?h
      refine forall_mem_not_eq'.mp ?_
      intros b hb₀ hb₁
      rw [hb₁] at hb₀
      norm_num at hb₀
      cases' hb₀ with hb₀ hb₀
      . rw [← hb₀] at g₂
        linarith
      . rw [← hb₀] at g₁
        linarith
    rw [g₃]
    have g₄: (1:ℕ) ∈ ({1, m - 2, m - 1}:(Finset ℕ)) := by
      exact mem_insert_self 1 {m - 2, m - 1}
    rw [← Finset.add_sum_erase _ _ g₄]
    simp
    rw [Finset.erase_eq_self.mpr ?_]
    . have g₅: (m - 2) ∈ ({m - 2, m - 1}:(Finset ℕ)) := by
        exact mem_insert_self (m - 2) {m - 1}
      rw [← Finset.add_sum_erase _ _ g₅]
      simp
      rw [Finset.erase_eq_self.mpr ?_]
      . rw [Finset.sum_singleton, Nat.sub_add_cancel (by linarith)]
        rw [← Nat.sub_add_comm (by linarith)]
        simp
        ring_nf
      . refine Finset.not_mem_singleton.mpr ?_
        omega
    . refine forall_mem_not_eq'.mp ?_
      intros b hb₀ hb₁
      rw [hb₁] at hb₀
      simp at hb₀
      cases' hb₀ with hb₀ hb₀
      . rw [← hb₀] at g₂
        linarith
      . rw [← hb₀] at g₁
        linarith
  rw [add_comm _ (∑ x ∈ fs, a (x + 1) ^ 2), h₂]
  exact le_self_add



lemma aux2
  (a : ℕ → NNReal) :
  ∀ (n : ℕ),
    4 < n ∧ n < 101 →
      (∀ (x y : ℕ), x % n = y % n → a (x + 1) = a (y + 1)) →
        ∑ x ∈ range n, (a (x + 1) ^ 4 + 2 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2 * a (x + 1) ^ 2 * a (x + 3) ^ 2) ≤
          (∑ x ∈ range n, a (x + 1) ^ 2) ^ 2 := by
  intro n hn₀ hn₂
  cases' hn₀ with hn₀ hn₁
  have hn₃: n = (n - 2) + 1 + 1 := by omega
  nth_rw 1 [hn₃,]
  rw [Finset.sum_range_succ, sum_range_succ]
  have hn₄: a (n - 2 + 1) = a (n - 1) := by
    refine congrArg a (by omega)
  have hn₅: a (n - 2 + 3) = a 1 := by
    refine hn₂ (n - 2 + 2) 0 ?_
    rw [Nat.zero_mod, Nat.sub_add_cancel ?_]
    . rw [Nat.mod_self n]
    . linarith
  have hn₆: a (n - 2 + 1 + 3) = a 2 := by
    refine hn₂ (n - 2 + 3) 1 ?_
    symm
    rw [Nat.mod_eq_of_lt (by linarith)]
    have g₀: n - 2 + 3 = n + 1 := by linarith
    rw [g₀]
    refine Eq.symm (mod_eq_of_modEq ?_ (by linarith))
    exact Nat.add_modEq_left
  rw [← hn₃, hn₄, hn₅, hn₆]
  refine le_induction ?_ ?_ n hn₀
  . repeat rw [Finset.sum_range_succ]
    simp
    ring_nf
    repeat refine add_le_add_right ?_ _
    refine le_of_eq ?_
    rfl
  . intros m hm₀ hm₁
    have hm₂: m + 1 - 2 = m - 2 + 1 := by
      rw [add_comm, add_comm _ 1, Nat.add_sub_assoc ?_ 1]
      omega
    rw [hm₂, Finset.sum_range_succ, sum_range_succ]
    have hm₃: m - 2 + 1 = m - 1 := by exact id (Eq.symm hm₂)
    have hm₄: m - 2 + 2 = m := by exact Eq.symm ((fun {m n} => pred_eq_succ_iff.mp) hm₂)
    have hm₅: m - 2 + 3 = m + 1 := by omega
    have hm₆: m + 1 - 1 = m := by exact rfl
    rw [hm₃, hm₄, hm₅, hm₆]
    clear hm₃ hm₄ hm₅ hm₆
    rw [add_sq, add_assoc ((∑ x ∈ Finset.range m, a (x + 1) ^ 2) ^ 2)]
    have h₅₀: 2 * a (m - 1) ^ 2 * a (m + 1) ^ 2 + 2 * a m ^ 2 * a (m + 1) ^ 2
      + 2 * a (m + 1) ^ 2 * a 1 ^ 2 + 2 * a (m + 1) ^ 2 * a 2 ^ 2 + a (m + 1) ^ 4 ≤
      (2 * ∑ x ∈ Finset.range m, a (x + 1) ^ 2) * a (m + 1) ^ 2 + (a (m + 1) ^ 2) ^ 2 := by
      rw [← pow_mul]
      simp
      have h₅₁: 2 * a (m - 1) ^ 2 * a (m + 1) ^ 2 + 2 * a m ^ 2 * a (m + 1) ^ 2 + 2 * a (m + 1) ^ 2 * a 1 ^ 2 +
        2 * a (m + 1) ^ 2 * a 2 ^ 2 =
        2 * a (m + 1) ^ 2 * (a (m - 1) ^ 2 + a m ^ 2 + a 1 ^ 2 + a 2 ^ 2) := by
        ring_nf
      rw [h₅₁, mul_assoc 2 _ (a (m + 1) ^ 2), mul_comm (∑ x ∈ Finset.range m, a (x + 1) ^ 2), ← mul_assoc 2]
      have h₅₂: a (m - 1) ^ 2 + a m ^ 2 + a 1 ^ 2 + a 2 ^ 2 ≤ ∑ x ∈ Finset.range m, a (x + 1) ^ 2 := by
        exact aux1 a m hm₀
      refine mul_le_mul ?_ ?_ ?_ ?_
      . exact le_of_eq (by rfl)
      . exact h₅₂
      . exact _root_.zero_le (a (m - 1) ^ 2 + a m ^ 2 + a 1 ^ 2 + a 2 ^ 2)
      . exact _root_.zero_le (2 * a (m + 1) ^ 2)
    have h₅₃: ∑ x ∈ Finset.range (m - 2), (a (x + 1) ^ 4 + 2 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2 * a (x + 1) ^ 2 * a (x + 3) ^ 2) +
        a (m - 1) ^ 4 + 2 * a (m - 1) ^ 2 * a m ^ 2 + a m ^ 4 + 2 * a m ^ 2 * a 1 ^ 2
      ≤ (∑ x ∈ Finset.range m, a (x + 1) ^ 2) ^ 2 := by
      have h₅₄: ∑ x ∈ Finset.range (m - 2), (a (x + 1) ^ 4 + 2 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2 * a (x + 1) ^ 2 * a (x + 3) ^ 2) +
          a (m - 1) ^ 4 + 2 * a (m - 1) ^ 2 * a m ^ 2 + a m ^ 4 + 2 * a m ^ 2 * a 1 ^ 2
        ≤ ∑ x ∈ Finset.range (m - 2), (a (x + 1) ^ 4 + 2 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2 * a (x + 1) ^ 2 * a (x + 3) ^ 2) +
          (a (m - 1) ^ 4 + 2 * a (m - 1) ^ 2 * a m ^ 2 + 2 * a (m - 1) ^ 2 * a 1 ^ 2) +
          (a m ^ 4 + 2 * a m ^ 2 * a 1 ^ 2 + 2 * a m ^ 2 * a 2 ^ 2) := by
        repeat rw [add_assoc]
        repeat refine add_le_add_left ?_ _
        have h₅₅: 2 * a (m - 1) ^ 2 * a 1 ^ 2 + (a m ^ 4 + (2 * a m ^ 2 * a 1 ^ 2 + 2 * a m ^ 2 * a 2 ^ 2)) =
          (a m ^ 4 + 2 * a m ^ 2 * a 1 ^ 2) + (2 * a (m - 1) ^ 2 * a 1 ^ 2 + 2 * a m ^ 2 * a 2 ^ 2) := by
          ring_nf
        rw [h₅₅]
        exact le_self_add
      exact le_trans h₅₄ hm₁
    apply add_le_add h₅₃ at h₅₀
    have h₅₆: ∑ x ∈ Finset.range (m - 2), (a (x + 1) ^ 4 + 2 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2 * a (x + 1) ^ 2 * a (x + 3) ^ 2)
        + a (m - 1) ^ 4 + 2 * a (m - 1) ^ 2 * a m ^ 2 + a m ^ 4 + 2 * a m ^ 2 * a 1 ^ 2
        + (2 * a (m - 1) ^ 2 * a (m + 1) ^ 2 + 2 * a m ^ 2 * a (m + 1) ^ 2 + 2 * a (m + 1) ^ 2 * a 1 ^ 2
        + 2 * a (m + 1) ^ 2 * a 2 ^ 2 + a (m + 1) ^ 4)
      = ∑ x ∈ Finset.range (m - 2), (a (x + 1) ^ 4 + 2 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2 * a (x + 1) ^ 2 * a (x + 3) ^ 2) +
        (a (m - 1) ^ 4 + 2 * a (m - 1) ^ 2 * a m ^ 2 + 2 * a (m - 1) ^ 2 * a (m + 1) ^ 2) +
      (a m ^ 4 + 2 * a m ^ 2 * a (m + 1) ^ 2 + 2 * a m ^ 2 * a 1 ^ 2) +
    (a (m + 1) ^ 4 + 2 * a (m + 1) ^ 2 * a 1 ^ 2 + 2 * a (m + 1) ^ 2 * a 2 ^ 2) := by
      repeat rw [add_assoc]
      simp
      ring_nf
    rw [← h₅₆]
    exact h₅₀


theorem imo_2007_p6
  (a : ℕ → NNReal)
  (h₀ : ∑ x ∈ Finset.range 100, ((a (x + 1)) ^ 2) = 1)
  (h₁ : ∀ x y, x % 100 = y % 100 → a (x + 1) = a (y + 1)) :
  ∑ x ∈ Finset.range (99), ((a (x + 1)) ^ 2 * a (x + 2)) + (a 100) ^ 2 * a 1 < (12:NNReal) / (25:NNReal) := by
  have h₂: ∀ x, 2 * a x ^ 2 * a (x + 1) * a (x + 2) ≤
    (a x * a (x + 1)) ^ 2 + (a x * a (x + 2)) ^ 2 := by
    intro x
    have h₂₀: 2 * (a x * a (x + 1)) * (a x * a (x + 2)) ≤
      (a x * a (x + 1)) ^ 2 + (a x * a (x + 2)) ^ 2 := by
      exact two_mul_le_add_sq (a x * a (x + 1)) (a x * a (x + 2))
    have h₂₁: 2 * (a x * a (x + 1)) * (a x * a (x + 2)) = 2 * a x ^ 2 * a (x + 1) * a (x + 2) := by
      rw [pow_two]
      ring_nf
    exact le_of_eq_of_le (id (Eq.symm h₂₁)) h₂₀
  have h₃: ∀ x ∈ Finset.range 100, a (x + 1) ≤ 1 := by
    intros x hx₀
    by_contra hx₁
    push_neg at hx₁
    let fsx : Finset ℕ := {x}
    have hx₂: 1 < ∑ x ∈ range 100, a (x + 1) ^ 2 := by
      have hx₃: 0 ≤ ∑ x ∈ (range 100 \ fsx), a (x + 1) ^ 2 := by
        exact _root_.zero_le (∑ x ∈ range 100 \ fsx, a (x + 1) ^ 2)
      have hx₄: 1 < ∑ x ∈ (fsx), a (x + 1) ^ 2 := by
        rw [Finset.sum_singleton]
        refine one_lt_pow₀ hx₁ ?_
        norm_num
      have hx₅: ∑ x ∈ (range 100 \ fsx), a (x + 1) ^ 2 + ∑ x ∈ (fsx), a (x + 1) ^ 2 =
        ∑ x ∈ range 100, a (x + 1) ^ 2 := by
        rw [← Finset.sum_union ?_]
        . rw [Finset.sdiff_union_self_eq_union]
          have hx₆: range 100 ∪ fsx = range 100 := by
            refine Finset.union_eq_left.mpr ?_
            exact singleton_subset_iff.mpr hx₀
          rw [hx₆]
        . exact sdiff_disjoint
      rw [← hx₅]
      exact lt_add_of_nonneg_of_lt hx₃ hx₄
    simp_all only [mem_range, lt_self_iff_false]
  have h₄: (∑ x ∈ Finset.range 100, (a (x + 2) * (a (x + 1) ^ 2  + 2 * a (x + 2) * a (x + 3)))) ^ 2 ≤
    ∑ x ∈ Finset.range 100, (a (x + 1) ^ 4 + 6 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2 * a (x + 1) ^ 2 * a (x + 3) ^ 2) := by
    have h₄₀: (∑ x ∈ Finset.range 100, (a (x + 2) * (a (x + 1) ^ 2 + 2 * a (x + 2) * a (x + 3)))) ^ 2 ≤
      (∑ x ∈ Finset.range 100, (a (x + 2) ^ 2)) *
      (∑ x ∈ Finset.range 100, ((a (x + 1) ^ 2 + 2 * a (x + 2) * a (x + 3))) ^ 2) := by
      refine sum_mul_sq_le_sq_mul_sq (range 100) (fun i => a (i + 2)) _
    have h₄₁: ∑ x ∈ Finset.range 100, (a (x + 2) ^ 2) = 1 := by
      rw [Finset.sum_range_succ'] at h₀
      simp at h₀
      rw [Finset.sum_range_succ]
      have h₄₁₁: a 1 = a 101 := by exact h₁ 0 100 rfl
      rw [← h₄₁₁]
      exact h₀
    have h₄₂: ∑ x ∈ Finset.range 100, ((a (x + 1) ^ 2  + 2 * a (x + 2) * a (x + 3))) ^ 2 =
      ∑ x ∈ Finset.range 100, ((a (x + 1) ^ 4 + 4 * a (x + 1) ^ 2 * a (x + 2) * a (x + 3)
        + 4 * a (x + 2) ^ 2 * a (x + 3) ^ 2)) := by
      refine Finset.sum_congr (rfl) ?_
      intros x _
      rw [add_sq]
      ring_nf
    rw [h₄₁, one_mul, h₄₂] at h₄₀
    have h₄₃: ∑ x ∈ Finset.range 100, ((a (x + 1) ^ 4 + 4 * a (x + 1) ^ 2 * a (x + 2) * a (x + 3)
        + 4 * a (x + 2) ^ 2 * a (x + 3) ^ 2)) ≤
      ∑ x ∈ Finset.range 100, ((a (x + 1) ^ 4 + 2 * a (x + 1) ^ 2 * (a (x + 2) ^ 2 + a (x + 3) ^ 2)
        + 4 * a (x + 2) ^ 2 * a (x + 3) ^ 2)) := by
      refine Finset.sum_le_sum ?_
      intros x _
      rw [add_comm (a (x + 1) ^ 4) _, add_comm (a (x + 1) ^ 4) _]
      rw [add_assoc, add_assoc]
      refine add_le_add ?_ ?_
      . have hx₁: 2 * a (x + 1) ^ 2 * a (x + 1 + 1) * a (x + 1 + 2) ≤
          (a (x + 1) * a (x + 1 + 1)) ^ 2 + (a (x + 1) * a (x + 1 + 2)) ^ 2 := by
          exact h₂ (x + 1)
        have hx₂: 2 * a (x + 1) ^ 2 * a (x + 2) * a (x + 3) ≤
          a (x + 1) ^ 2 * (a (x + 2) ^ 2 + a (x + 3) ^ 2) := by
          rw [mul_add]
          refine le_of_le_of_eq hx₁ ?_
          ring_nf
        have hx₃: (4:NNReal) = 2 * 2 := by norm_num
        rw [hx₃]
        repeat rw [mul_assoc]
        have hx₄: 0 < (2:NNReal) := by norm_num
        refine (mul_le_mul_left hx₄).mpr ?_
        ring_nf
        ring_nf at hx₂
        exact hx₂
      . exact Preorder.le_refl (a (x + 1) ^ 4 + 4 * a (x + 2) ^ 2 * a (x + 3) ^ 2)
    have h₄₄: ∑ x ∈ Finset.range 100, ((a (x + 1) ^ 4 + 2 * a (x + 1) ^ 2 * (a (x + 2) ^ 2 + a (x + 3) ^ 2)
        + 4 * a (x + 2) ^ 2 * a (x + 3) ^ 2)) =
      ∑ x ∈ Finset.range 100, (a (x + 1) ^ 4 + 6 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2
        * a (x + 1) ^ 2 * a (x + 3) ^ 2) := by
      rw [Finset.sum_add_distrib]
      have h₄₄₁: ∑ x ∈ range 100, 4 * a (x + 2) ^ 2 * a (x + 3) ^ 2 =
        ∑ x ∈ range 100, 4 * a (x + 1) ^ 2 * a (x + 2) ^ 2 := by
        rw [Finset.sum_range_succ _ 99, sum_range_succ' _ 99]
        have g₀: a 101 = a 1 := by exact h₁ 100 0 rfl
        have g₁: a 102 = a 2 := by exact h₁ 101 1 rfl
        rw [g₀, g₁]
      rw [h₄₄₁, ← Finset.sum_add_distrib]
      refine Finset.sum_congr (rfl) ?_
      intros x _
      rw [mul_add]
      ring_nf
    rw [h₄₄] at h₄₃
    exact le_trans h₄₀ h₄₃
  have h₆: ∑ x ∈ range 100, 4 * a (x + 1) ^ 2 * a (x + 2) ^ 2 ≤ 1 := by
    have h₆₀: ∑ x ∈ range 100, 4 * a (x + 1) ^ 2 * a (x + 2) ^ 2 =
      ∑ x ∈ range 100, 4 * (a (x + 1) ^ 2 * a (x + 2) ^ 2) := by
      refine Finset.sum_congr rfl ?_
      intros x _
      ring_nf
    rw [h₆₀, ← Finset.mul_sum]
    let fs₂ := Finset.range (100)
    let fs₀ : Finset ℕ := fs₂.filter (fun x => Odd x)
    let fs₁ : Finset ℕ := fs₂.filter (fun x => Even x)
    have h₆₁ : Disjoint fs₀ fs₁ := by
      refine Finset.sdiff_eq_self_iff_disjoint.mp (by rfl)
    have h₆₂ : fs₀ ∪ fs₁ = fs₂ := by
      symm
      refine Finset.ext_iff.mpr ?_
      intro a
      constructor
      . intro ha₀
        refine mem_union.mpr ?mp.a
        have ha₁: Odd a ∨ Even a := by exact Or.symm (even_or_odd a)
        cases' ha₁ with ha₂ ha₃
        . left
          refine mem_filter.mpr ?mp.a.inl.h.a
          exact And.symm ⟨ha₂, ha₀⟩
        . right
          refine mem_filter.mpr ?mp.a.inl.h.b
          exact And.symm ⟨ha₃, ha₀⟩
      . intro ha₀
        apply mem_union.mp at ha₀
        cases' ha₀ with ha₁ ha₂
        . exact mem_of_mem_filter a ha₁
        . exact mem_of_mem_filter a ha₂
    have h₆₃: 4 * ∑ i ∈ fs₂, a (i + 1) ^ 2 * a (i + 2) ^ 2 ≤
      4 * ((∑ i ∈ fs₀, (a (i + 1) ^ 2)) * (∑ i ∈ fs₁, (a (i + 1) ^ 2))) := by
      refine mul_le_mul (by norm_num) ?_ ?_ (by norm_num)
      . rw [← h₆₂, Finset.sum_union h₆₁]
        have g₀: ∑ i ∈ fs₁, a (i + 1) ^ 2 = ∑ i ∈ fs₀, (a i) ^ 2 := by
          refine sum_bij ?_ ?h.b2 ?h.b3 ?h.b4 ?h.b5
          . intros b _
            exact (b + 1)
          . intros b hb₀
            apply mem_filter.mp at hb₀
            cases' hb₀ with hb₀ hb₁
            have hb₂: Odd (b + 1) := by exact Even.add_one hb₁
            have hb₃: b ≤ 98 := by
              by_contra hc₀
              apply mem_range.mp at hb₀
              interval_cases b
              have hc₁: ¬ Even 99 := by decide
              exact hc₁ hb₁
            have hb₄: b + 1 < 100 := by linarith
            have hb₅: (b + 1) ∈ fs₂ := by exact mem_range.mpr hb₄
            refine mem_filter.mpr ?_
            exact And.symm ⟨hb₂, hb₅⟩
          . intros b _ c _ hb₂
            linarith
          . intros b hb₀
            use (b - 1)
            refine exists_prop.mpr ?h.a
            have hb₁: b ∈ fs₂ ∧ Odd b := by exact mem_filter.mp hb₀
            have hb₂: 1 ≤ b := by
              by_contra hc
              interval_cases b
              have hb₃: ¬ Odd 0 := by decide
              exact hb₃ hb₁.2
            constructor
            . cases' hb₁ with hb₁ hb₃
              have hb₄: Even (b - 1) := by exact Nat.Odd.sub_odd hb₃ (by decide)
              have hb₅: (b - 1) ∈ fs₂ := by
                refine mem_range.mpr ?_
                have hb₆: b < 100 := by exact List.mem_range.mp hb₁
                omega
              refine mem_filter.mpr ?_
              exact And.symm ⟨hb₄, hb₅⟩
            . exact Nat.sub_add_cancel hb₂
          . exact fun a_1 _ => rfl
        have g₁: ∑ x ∈ fs₁, a (x + 1) ^ 2 * a (x + 2) ^ 2 =
          ∑ x ∈ fs₀, a (x) ^ 2 * a (x + 1) ^ 2 := by
          refine sum_bij ?_ ?_ ?_ ?_ ?_
          . intros b _
            exact (b + 1)
          . intros b hb₀
            apply mem_filter.mp at hb₀
            cases' hb₀ with hb₀ hb₁
            have hb₂: Odd (b + 1) := by exact Even.add_one hb₁
            have hb₃: b ≤ 98 := by
              by_contra hc₀
              apply mem_range.mp at hb₀
              interval_cases b
              have hc₁: ¬ Even 99 := by decide
              exact hc₁ hb₁
            have hb₄: b + 1 < 100 := by linarith
            have hb₅: (b + 1) ∈ fs₂ := by exact mem_range.mpr hb₄
            refine mem_filter.mpr ?_
            exact And.symm ⟨hb₂, hb₅⟩
          . intros b _ c _ hb₂
            linarith
          . intros b hb₀
            use (b - 1)
            refine exists_prop.mpr ?h.b
            have hb₁: b ∈ fs₂ ∧ Odd b := by exact mem_filter.mp hb₀
            have hb₂: 1 ≤ b := by
              by_contra hc
              interval_cases b
              have hb₃: ¬ Odd 0 := by decide
              exact hb₃ hb₁.2
            constructor
            . cases' hb₁ with hb₁ hb₃
              have hb₄: Even (b - 1) := by exact Nat.Odd.sub_odd hb₃ (by decide)
              have hb₅: (b - 1) ∈ fs₂ := by
                refine mem_range.mpr ?_
                have hb₆: b < 100 := by exact List.mem_range.mp hb₁
                omega
              refine mem_filter.mpr ?_
              exact And.symm ⟨hb₄, hb₅⟩
            . exact Nat.sub_add_cancel hb₂
          . exact fun a_1 _ => rfl
        rw [g₀, g₁, Finset.sum_mul_sum, add_comm, ← sum_add_distrib]
        refine sum_le_sum ?_
        intros x hx₀
        apply mem_filter.mp at hx₀
        cases' hx₀ with hx₀ hx₁
        apply mem_range.mp at hx₀
        by_cases hx₃: x < 99
        . clear h₀ h₁ h₂ h₃ h₄ h₆₀ g₀ g₁
          let fs₃ : Finset ℕ := {x, (x + 2)}
          have hx₄: fs₃ ⊆ fs₀ := by
            intros b hb₀
            have hb₁: b = x ∨ b = x + 2 := by
              have g₀: fs₃ = {x, x + 2} := by rfl
              simp_all only [mem_insert, mem_singleton]
            cases' hb₁ with hb₁ hb₁
            . rw [hb₁]
              refine mem_filter.mpr ?_
              apply mem_range.mpr at hx₀
              exact And.symm ⟨hx₁, hx₀⟩
            . rw [hb₁]
              refine mem_filter.mpr ?_
              constructor
              . have hx₄: x < 98 := by
                  by_contra hc
                  interval_cases x
                  have hx₅: ¬ Odd 98 := by decide
                  apply hx₅ hx₁
                refine mem_range.mpr ?_
                linarith
              . refine Odd.add_even hx₁ ?_
                decide
          have hx₅: ∑ j ∈ fs₃, a (x + 1) ^ 2 * a j ^ 2 = a (x + 1) ^ 2 * a x ^ 2 + a (x + 1) ^ 2 * a (x + 2) ^ 2 := by
            have hx₆: fs₃ = {x, x + 2} := by rfl
            refine Finset.sum_eq_add_of_mem (x) (x + 2) ?_ ?_ (by norm_num) ?_
            . rw [hx₆]
              exact mem_insert_self x {x + 2}
            . rw [hx₆]
              simp
            . intros c hc₀ hc₁
              exfalso
              rw [hx₆] at hc₀
              simp only [mem_insert, mem_singleton] at hc₀
              have hc₃: ¬ (c ≠ x ∧ c ≠ x + 2) := by
                omega
              exact hc₃ hc₁
          rw [← Finset.sum_sdiff hx₄, hx₅]
          refine le_add_left ?_
          refine le_of_eq ?_
          rw [mul_comm (a x ^ 2) (a (x + 1) ^ 2)]
        . interval_cases x
          norm_num
          have hx₄: a 101 = a 1 := by exact h₁ 100 0 rfl
          let fs₃: Finset ℕ := {1, 99}
          have hx₅: fs₃ ⊆ fs₀ := by
            refine Finset.subset_iff.mpr ?_
            intros b hb₀
            have hb₁: b = 1 ∨ b = 99 := by exact List.mem_pair.mp hb₀
            cases' hb₁ with hb₂ hb₂
            . refine mem_filter.mpr ?_
              rw [hb₂]
              constructor
              . refine mem_range.mpr (by decide)
              . decide
            . rw [hb₂]
              refine mem_filter.mpr ?_
              constructor
              . exact self_mem_range_succ 99
              . decide
          have hx₆: ∑ x ∈ fs₃, a 100 ^ 2 * a x ^ 2 = a 100 ^ 2 * a 99 ^ 2 + a 100 ^ 2 * a 1 ^ 2 := by
            clear h₀ h₁ h₂ h₃ h₄ h₆₀
            have hx₇: fs₃ = {1, 99} := by rfl
            refine Finset.sum_eq_add_of_mem (99:ℕ) (1:ℕ) ?_ ?_ (by norm_num) ?_
            . rw [hx₇]
              decide
            . rw [hx₇]
              decide
            . intros c hc₀ hc₁
              exfalso
              have hc₂: c = 99 ∨ c = 1 := by
                refine Or.symm ?_
                exact List.mem_pair.mp hc₀
              have hc₃: ¬ (c ≠ 99 ∧ c ≠ 1) := by omega
              exact hc₃ hc₁
          rw [← Finset.sum_sdiff hx₅, hx₄, hx₆]
          refine le_add_left ?_
          refine le_of_eq ?_
          rw [mul_comm (a 99 ^ 2) (a 100 ^ 2)]
      . exact _root_.zero_le (∑ i ∈ range 100, a (i + 1) ^ 2 * a (i + 2) ^ 2)
    have h₆₄: 4 * ((∑ i ∈ fs₀, (a (i + 1) ^ 2)) * (∑ i ∈ fs₁, (a (i + 1) ^ 2))) ≤
      (∑ i ∈ fs₀, (a (i + 1) ^ 2) + ∑ i ∈ fs₁, (a (i + 1) ^ 2)) ^ 2 := by
      have g₀: ∀ x y : ℝ, 4 * x * y ≤ (x + y) ^ 2 := by
        intros x y
        rw [add_sq]
        have g₁: 2 * x * y ≤ x ^ 2 + y ^ 2 := by exact two_mul_le_add_sq x y
        linarith
      rw [← mul_assoc]
      let x := (∑ i ∈ fs₀, a (i + 1) ^ 2)
      let y := (∑ i ∈ fs₁, a (i + 1) ^ 2)
      refine g₀ x y
    have h₆₅: (∑ i ∈ fs₀, (a (i + 1) ^ 2) + ∑ i ∈ fs₁, (a (i + 1) ^ 2)) ^ 2 = 1 := by
      rw [← Finset.sum_union h₆₁, h₆₂, h₀]
      exact one_pow 2
    refine le_trans h₆₃ ?_
    refine le_trans h₆₄ ?_
    rw [h₆₅]
  let S : NNReal := ∑ x ∈ Finset.range 99, ((a (x + 1)) ^ 2 * a (x + 2)) + (a 100) ^ 2 * a 1
  have hS : S = ∑ x ∈ Finset.range 99, ((a (x + 1)) ^ 2 * a (x + 2)) + (a 100) ^ 2 * a 1 := by rfl
  rw [← hS]
  have hS₁ : S = ∑ x ∈ Finset.range 100, ((a (x + 1)) ^ 2 * a (x + 2)) := by
    rw [Finset.sum_range_succ]
    norm_num
    have g₀: a 101 = a 1 := by exact h₁ 100 0 rfl
    rw [g₀]
  have h₇: (3 * S) ^ 2 ≤ 2 := by
    have h₇₀: 3 * S = ∑ x ∈ Finset.range 100, (a (x + 2) * (a (x + 1) ^ 2  + 2 * a (x + 2) * a (x + 3))) := by
      have g₀: ∑ x ∈ Finset.range 100, (a (x + 2) * (a (x + 1) ^ 2  + 2 * a (x + 2) * a (x + 3))) =
        ∑ x ∈ Finset.range 100, (a (x + 1) ^ 2 * a (x + 2) + 2 * a (x + 2) ^ 2 * a (x + 3)) := by
        refine Finset.sum_congr rfl ?_
        intros x _
        ring_nf
      have g₁: (3:NNReal) = 1 + 2 := by norm_num
      rw [g₀, Finset.sum_add_distrib]
      rw [g₁, hS₁, add_mul, one_mul, Finset.mul_sum]
      simp
      rw [Finset.sum_range_succ' _ 99, sum_range_succ _ 99]
      norm_num
      have g₂: a 101 = a 1 := by exact h₁ 100 0 rfl
      have g₃: a 102 = a 2 := by exact h₁ 101 1 rfl
      rw [g₂, g₃, ← mul_assoc 2]
      simp
      refine Finset.sum_congr rfl ?_
      intros x _
      ring_nf
    rw [← h₇₀] at h₄
    refine le_trans h₄ ?_
    have h₇₁: ∑ x ∈ range 100, (a (x + 1) ^ 4 + 6 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2 * a (x + 1) ^ 2 * a (x + 3) ^ 2) =
      ∑ x ∈ range 100, (a (x + 1) ^ 4 + 2 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2 * a (x + 1) ^ 2 * a (x + 3) ^ 2) +
      ∑ x ∈ range 100, 4 * a (x + 1) ^ 2 * a (x + 2) ^ 2 := by
      rw [← Finset.sum_add_distrib]
      refine Finset.sum_congr rfl ?_
      intros x _
      ring_nf
    have h₇₂: ∑ x ∈ range 100, (a (x + 1) ^ 4 + 2 * a (x + 1) ^ 2 * a (x + 2) ^ 2 + 2 * a (x + 1) ^ 2 * a (x + 3) ^ 2) ≤ 1 := by
      refine le_trans (aux2 a 100 ?_ h₁) ?_
      . omega
      . refine (sq_le_one_iff₀ ?_).mpr ?_
        . exact _root_.zero_le (∑ x ∈ range 100, a (x + 1) ^ 2)
        . rw [← h₀]
    rw [h₇₁, ← one_add_one_eq_two]
    refine add_le_add ?_ h₆
    norm_num
    exact h₇₂
  have h₈ : S ≤ (NNReal.sqrt 2) / (3:NNReal) := by
    have h₆₀: NNReal.sqrt (((3:NNReal) * S) ^ 2) ≤ NNReal.sqrt 2 := by
      exact NNReal.sqrt_le_sqrt.mpr h₇
    rw [sqrt_sq, mul_comm] at h₆₀
    refine (le_div_iff₀ (by norm_num)).mpr h₆₀
  have h₉: (NNReal.sqrt 2) / (3:NNReal) < (12:NNReal) / (25:NNReal)  := by
    have h₇₁: 2 < 144 / (625:NNReal) * 9 := by
      refine (one_lt_div (by norm_num)).mp ?_
      rw [mul_comm_div, ← mul_div_assoc, div_div]
      norm_num
      refine (one_lt_div (by norm_num)).mpr ?_
      norm_num
    have h₇₂: (NNReal.sqrt 2 / 3:NNReal) ^ 2 < (12 / 25:NNReal) ^ 2 := by
      rw [div_pow, div_pow]
      norm_num
      refine (div_lt_iff₀ ?_).mpr h₇₁
      exact ofNat_pos'
    have h₇₃: NNReal.sqrt ((NNReal.sqrt 2 / 3) ^ 2) < NNReal.sqrt ((12 / 25) ^ 2) := by
      exact sqrt_lt_sqrt.mpr h₇₂
    rw [sqrt_sq, sqrt_sq] at h₇₃
    exact h₇₃
  exact lt_of_le_of_lt h₈ h₉
