import Mathlib
set_option linter.unusedVariables.analyzeTactics true


theorem imo_2022_p2_simple
  (g: ℝ → ℝ)
  (h₀: ∀ x, 0 < x → ∃ y:ℝ , (0 < y ∧ g (x) + g (y) ≤ 2 * x * y
        ∧ (∀ z:ℝ, (0 < z ∧ z ≠ y) →  ¬ g (x) + g (z) ≤ 2 * x * z) )) :
  (∀ x:ℝ , 0 < x → g x = x^2) := by
  have h₁: ∀ x y:ℝ , 0 < x ∧ 0 < y → g x + g y ≤ 2 * x * y → x = y := by
    intros x y hp h₁
    by_contra! hc
    have g₁: 2 * x * x < g x + g x := by
      let ⟨p,h₁₁⟩ := h₀ x hp.1
      cases' h₁₁ with h₁₁ h₁₂
      cases' h₁₂ with h₁₂ h₁₃
      by_cases hxp: x ≠ p
      . have h₁₄: ¬ g x + g x ≤ 2 * x * x := by
          refine h₁₃ x ?_
          constructor
          . exact hp.1
          . exact hxp
        exact not_le.mp h₁₄
      . push_neg at hxp
        exfalso
        have hpy: y ≠ p := by exact Ne.trans_eq (id (Ne.symm hc)) hxp
        have hcy: ¬g x + g y ≤ 2 * x * y := by
          refine h₁₃ y ?_
          constructor
          . exact hp.2
          . exact hpy
        linarith
    have g₂: 2 * y * y < g y + g y := by
      let ⟨p,h₁₁⟩ := h₀ y hp.2
      cases' h₁₁ with h₁₁ h₁₂
      cases' h₁₂ with h₁₂ h₁₃
      by_cases hyp: y ≠ p
      . have h₁₄: ¬ g y + g y ≤ 2 * y * y := by
          refine h₁₃ y ?_
          constructor
          . exact hp.2
          . exact hyp
        exact not_le.mp h₁₄
      . push_neg at hyp
        exfalso
        have hpx: x ≠ p := by exact Ne.trans_eq hc hyp
        have hcy: ¬g x + g y ≤ 2 * x * y := by
          rw [add_comm, mul_right_comm]
          refine h₁₃ x ?_
          constructor
          . exact hp.1
          . exact hpx
        linarith
    ring_nf at g₁ g₂
    simp at g₁ g₂
    have g₃: x ^ 2 + y ^ 2 < g x + g y := by exact add_lt_add g₁ g₂
    have g₄: x ^ 2 + y ^ 2 < 2 * x * y := by exact LT.lt.trans_le g₃ h₁
    have g₅: (x - y) ^ 2 < 0 := by
      rw [sub_sq, sub_add_eq_add_sub]
      exact sub_neg.mpr g₄
    have g₆: (x - y) ≠ 0 := by exact sub_ne_zero.mpr hc
    have g₇: 0 < (x - y) ^ 2 := by exact (sq_pos_iff).mpr g₆
    have g₈: (0:ℝ) ≠ 0 := by
      refine ne_of_lt ?_
      exact lt_trans g₇ g₅
    refine false_of_ne g₈
  have h₂: ∀ x:ℝ , 0 < x → g x ≤ x ^ 2 := by
    intros x hxp
    let ⟨y,h₁₁⟩ := h₀ x hxp
    cases' h₁₁ with h₁₁ h₁₂
    cases' h₁₂ with h₁₂ h₁₃
    have hxy: x = y := by
      apply h₁ x y
      . exact { left := hxp, right := h₁₁ }
      . exact h₁₂
    rw [← hxy] at h₁₂
    linarith
  have h₃: ∀ x:ℝ , 0 < x → ¬ g x < x ^ 2 := by
    simp
    by_contra! hc
    let ⟨x,hxp⟩ := hc
    cases' hxp with hxp h₃
    let d₁:ℝ := x ^ 2 - g x
    have hd₁ : g x = x ^ 2 - d₁ := by exact (sub_sub_self (x ^ 2) (g x)).symm
    let z:ℝ := x + Real.sqrt d₁
    have hz: z = x + Real.sqrt d₁ := by exact rfl
    have hzp: 0 < z := by
      refine add_pos hxp ?_
      refine Real.sqrt_pos_of_pos ?_
      exact sub_pos.mpr h₃
    have hxz: z ≠ x := by
      rw [hz]
      simp
      push_neg
      refine Real.sqrt_ne_zero'.mpr ?_
      exact sub_pos.mpr h₃
    have h₅: g x + g z ≤ 2 * x * z := by
      rw [hd₁]
      have h₅₁: - d₁ + Real.sqrt (x ^ 2 - (x ^ 2 - d₁)) ^ 2 ≤ 0 := by
        simp
        rw [Real.sq_sqrt]
        exact sub_nonneg_of_le (h₂ x hxp)
      have h₅₂: x ^ 2 - d₁ + z ^ 2 ≤ 2 * x * z := by
        rw [hz, mul_add, add_sq]
        ring_nf
        repeat rw [add_assoc]
        refine add_le_add_left ?_ (x * Real.sqrt (x ^ 2 - g x) * 2)
        rw [hd₁]
        linarith
      exact add_le_of_add_le_left h₅₂ (h₂ z hzp)
    let ⟨y,hyp⟩ := h₀ x hxp
    cases' hyp with hyp h₆
    cases' h₆ with h₆ h₇
    have hxy: x = y := by
      apply h₁
      . exact { left := hxp, right := hyp }
      . exact h₆
    have h₈: ¬g x + g z ≤ 2 * x * z := by
        refine h₇ z ?_
        constructor
        . exact hzp
        . exact Ne.trans_eq hxz hxy
    linarith[h₅,h₈]
  intros x hxp
  have g₂: g x ≤ x ^ 2 := by exact h₂ x hxp
  have g₃: ¬ g x < x ^ 2 := by exact h₃ x hxp
  linarith





theorem imo_2022_p2
  (f: ℝ → ℝ)
  (hfp: ∀ x:ℝ, 0 < x → 0 < f x)
  (h₀: ∀ x:ℝ , 0 < x → ∃! y:ℝ , 0 < y ∧ (x * f (y) + y * f (x) ≤ 2) ):
  ∀ x:ℝ , 0 < x → f (x) = 1 / x := by
  have h₁: ∀ x y:ℝ , (0 < x ∧ 0 < y) → (x * f (y) + y * f (x) ≤ 2) → x = y := by
    intros x y hp h₁
    by_contra! hc
    have h₁₀: x * f x + x * f x > 2 := by
      let ⟨z,h₁₁⟩ := h₀ x hp.1
      cases' h₁₁ with h₁₁ h₁₂
      have h₁₄: y = z := by
        apply h₁₂ y
        constructor
        . exact hp.2
        . exact h₁
      have hxz: ¬ x = z := by exact Ne.trans_eq hc h₁₄
      have h₁₆: ¬ (fun y => 0 < y ∧ x * f y + y * f x ≤ 2) x := by
        exact mt (h₁₂ x) hxz
      have h₁₇: ¬ (0 < x ∧ x * f x + x * f x ≤ 2) := by exact h₁₆
      push_neg at h₁₇
      exact h₁₇ hp.1
    have h₁₁: y * f y + y * f y > 2 := by
      let ⟨z,h₁₁⟩ := h₀ y hp.2
      cases' h₁₁ with h₁₁ h₁₂
      have h₁₄: x = z := by
        apply h₁₂ x
        constructor
        . exact hp.1
        . rw [add_comm]
          exact h₁
      have hxz: ¬ y = z := by exact Ne.trans_eq (id (Ne.symm hc)) h₁₄
      have h₁₆: ¬ (fun y_2 => 0 < y_2 ∧ y * f y_2 + y_2 * f y ≤ 2) y := by
        exact mt (h₁₂ y) hxz
      have h₁₇: ¬ (0 < y ∧ y * f y + y * f y ≤ 2) := by exact h₁₆
      push_neg at h₁₇
      exact h₁₇ hp.2
    ring_nf at h₁₀ h₁₁
    simp at h₁₀ h₁₁
    have h₁₅: 1 / x < f x := by exact (div_lt_iff₀' hp.1).mpr (h₁₀)
    have h₁₆: 1 / y < f y := by exact (div_lt_iff₀' hp.2).mpr (h₁₁)
    have h₁₂: x / y + y / x < 2 := by
      refine lt_of_le_of_lt' h₁ ?_
      refine add_lt_add ?_ ?_
      . rw [← mul_one_div]
        exact (mul_lt_mul_left hp.1).mpr h₁₆
      . rw [← mul_one_div]
        exact (mul_lt_mul_left hp.2).mpr h₁₅
    have h₁₃: 2 < x / y + y / x := by
      refine lt_of_mul_lt_mul_right ?_ (le_of_lt hp.1)
      refine lt_of_mul_lt_mul_right ?_ (le_of_lt hp.2)
      repeat rw [add_mul, mul_assoc]
      rw [mul_comm x y, ← mul_assoc (x/y)]
      rw [div_mul_comm x y y, div_mul_comm y x x, div_self, div_self]
      . ring_nf
        refine lt_of_sub_pos ?_
        rw [mul_comm _ 2, ← mul_assoc]
        rw [← sub_sq']
        refine sq_pos_of_ne_zero ?_
        exact sub_ne_zero.mpr hc.symm
      . exact ne_of_gt hp.1
      . exact ne_of_gt hp.2
    linarith
  have h₂: ∀ x:ℝ , 0 < x → x * f x ≤ 1 := by
    intros x hxp
    let ⟨y,h₂₁⟩ := h₀ x hxp
    cases' h₂₁ with h₂₁ h₂₂
    have hxy: x = y := by
      apply h₁ x y
      . constructor
        . exact hxp
        . exact h₂₁.1
      . exact h₂₁.2
    rw [← hxy] at h₂₁
    linarith
  have h₃: ∀ x:ℝ , 0 < x → ¬ x * f x < 1 := by
    by_contra! hc
    let ⟨x,hxp⟩ := hc
    cases' hxp with hxp h₃
    let d₁:ℝ := 1 - x * f x
    have hd₁ : x * f x = 1 - d₁ := by exact (sub_sub_self 1 (x * f x)).symm
    let z:ℝ := x + d₁ / f x
    have hz: z = x + d₁ / f x := by exact rfl
    have hzp: 0 < z := by
      refine add_pos hxp ?_
      refine div_pos ?_ ?_
      . exact sub_pos.mpr h₃
      . exact hfp x hxp
    have hxz: ¬ x = z := by
      by_contra! hcz₀
      rw [← hcz₀] at hz
      have hcz₁: 0 < d₁ / f x := by
        refine div_pos ?_ (hfp x hxp)
        exact sub_pos.mpr h₃
      linarith
    have h₄: ¬ (x * f z + z * f x ≤ 2) := by
      have h₄₁: x * f z + z * f x ≤ 2 → x = z := by
        exact h₁ x z { left := hxp, right := hzp }
      exact mt h₄₁ hxz
    have h₅: x * f z < 1 := by
      suffices h₅₁: z * f z ≤ 1 by
        refine lt_of_lt_of_le ?_ h₅₁
        refine (mul_lt_mul_right (hfp z hzp)).mpr ?_
        rw [hz]
        refine lt_add_of_pos_right x ?_
        refine div_pos ?_ (hfp x hxp)
        exact sub_pos.mpr h₃
      exact h₂ z hzp
    have h₆: x * f z + z * f x < 2 := by
      suffices h₇: z * f x ≤ 1 by
        linarith
      rw [hz, add_mul, hd₁]
      rw [div_mul_comm d₁ (f x) (f x)]
      rw [div_self]
      . rw [one_mul, sub_add_cancel]
      . exact Ne.symm (ne_of_lt (hfp x hxp))
    linarith
  intros x hxp
  have h₄: x * f x ≤ 1 := by exact h₂ x hxp
  have h₅: ¬ x * f x < 1 := by exact h₃ x hxp
  refine eq_div_of_mul_eq ?_ ?_
  . exact ne_of_gt hxp
  . push_neg at h₅
    linarith
