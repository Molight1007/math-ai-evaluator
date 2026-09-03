import Mathlib
import Mathlib.Analysis.SpecialFunctions.Pow.Real


set_option linter.unusedVariables.analyzeTactics true

open Real Set

lemma mylemma_1
  (x a: ℕ → ℝ)
  (hxp: ∀ (i : ℕ), 0 < x i)
  (h₀: ∀ (n : ℕ),
    1 ≤ n ∧ n ≤ 2023 →
      a n = sqrt ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k)
      * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k)) :
  ∀ (n : ℕ), (1 ≤ n ∧ n ≤ 2022) → a (n) < a (n + 1) := by
  intros n hn
  have h₂: a n = sqrt ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k)
              * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) := by
    refine h₀ n ?_
    constructor
    . exact hn.1
    linarith
  have h₃: a (n + 1) = sqrt ((Finset.sum (Finset.Ico 1 (n + 2)) fun k => x k)
              * Finset.sum (Finset.Ico 1 (n + 2)) fun k => 1 / x k) := by
    refine h₀ (n + 1) ?_
    constructor
    . linarith
    linarith
  rw [h₂,h₃]
  refine sqrt_lt_sqrt ?_ ?_
  . refine le_of_lt ?_
    refine mul_pos ?_ ?_
    . refine Finset.sum_pos ?_ ?_
      . exact fun i _ => hxp i
      . simp
        linarith
    . refine Finset.sum_pos ?_ ?_
      intros i _
      exact one_div_pos.mpr (hxp i)
      . simp
        linarith
  have g₀: 1 ≤ n + 1 := by linarith
  rw [Finset.sum_Ico_succ_top g₀ _, Finset.sum_Ico_succ_top g₀ _]
  repeat rw [add_mul, mul_add]
  have h₄: 0 < (Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 1)) +
    x (n + 1) * ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) + 1 / x (n + 1)) := by
      refine add_pos ?_ ?_
      . refine mul_pos ?_ ?_
        . refine Finset.sum_pos ?_ ?_
          . exact fun i _ => hxp i
          . simp
            linarith
        . exact one_div_pos.mpr (hxp (n + 1))
      . refine mul_pos ?_ ?_
        . exact hxp (n + 1)
        . refine add_pos ?_ ?_
          . refine Finset.sum_pos ?_ ?_
            . intros i _
              exact one_div_pos.mpr (hxp i)
            . simp
              linarith
          exact one_div_pos.mpr (hxp (n + 1))
  linarith


lemma mylemma_amgm
  (b1 b2 b3 b4 :ℝ)
  (hb1: 0 ≤ b1)
  (hb2: 0 ≤ b2)
  (hb3: 0 ≤ b3)
  (hb4: 0 ≤ b4) :
  (4 * (b1 * b2 * b3 * b4) ^ (4:ℝ)⁻¹ ≤ b1 + b2 + b3 + b4) := by
  let w1 : ℝ := (4:ℝ)⁻¹
  let w2 : ℝ := w1
  let w3 : ℝ := w2
  let w4 : ℝ := w3
  rw [mul_comm]
  refine mul_le_of_le_div₀ ?_ (by norm_num) ?_
  . refine add_nonneg ?_ hb4
    refine add_nonneg ?_ hb3
    exact add_nonneg hb1 hb2
  have h₀: (b1^w1 * b2^w2 * b3^w3 * b4^w4) ≤ w1 * b1 + w2 * b2 + w3 * b3 + w4 * b4 := by
    refine geom_mean_le_arith_mean4_weighted (by norm_num) ?_ ?_ ?_ hb1 hb2 hb3 hb4 ?_
    . norm_num
    . norm_num
    . norm_num
    . norm_num
  repeat rw [mul_rpow _]
  ring_nf at *
  linarith
  repeat { assumption }
  . exact mul_nonneg hb1 hb2
  . exact hb4
  . refine mul_nonneg ?_ hb3
    exact mul_nonneg hb1 hb2



lemma mylemma_2
  (x a: ℕ → ℝ)
  (hxp: ∀ (i : ℕ), 0 < x i)
  (h₀: ∀ (n : ℕ),
    1 ≤ n ∧ n ≤ 2023 →
      a n = sqrt ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k)
            * (Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k)))
  (n: ℕ)
  (hn: 1 ≤ n ∧ n ≤ 2021) :
  (4 * a n ≤
    (Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 1) + 1 / x (n + 2)) +
      (x (n + 1) + x (n + 2)) * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) := by
      repeat rw [mul_add, add_mul]
      have g₁₁: 0 ≤ Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => x x_1 := by
        refine le_of_lt ?_
        refine Finset.sum_pos ?_ ?_
        . exact fun i _ => hxp i
        . simp
          linarith
      have g₁₂: 0 ≤ Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => (x x_1)⁻¹ := by
        refine le_of_lt ?_
        refine Finset.sum_pos ?_ ?_
        . intros i _
          exact inv_pos.mpr (hxp i)
        . simp
          linarith
      have h₃₂: 4 * ( ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 1))) *
          ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 2))) *
          ((x (n + 1) * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k)) *
          (x (n + 2) * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) ) ^ (4:ℝ)⁻¹
        ≤ (Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 1)) +
          (Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 2)) +
          ((x (n + 1) * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) +
          x (n + 2) * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) := by
            let b1:ℝ := (Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 1))
            let b2:ℝ := (Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 2))
            let b3:ℝ := (x (n + 1) * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k)
            let b4:ℝ := x (n + 2) * (Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k)
            have hb1: b1 = (Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 1)) := by
              exact rfl
            have hb2: b2 = (Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 2)) := by
              exact rfl
            have hb3: b3 = (x (n + 1) * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) := by
              exact rfl
            have hb4: b4 = x (n + 2) * (Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) := by
              exact rfl
            rw [← hb1, ← hb2, ← hb3, ← hb4]
            have g₀: 4 * (b1 * b2 * b3 * b4) ^ (4:ℝ)⁻¹ ≤ b1 + b2 + b3 + b4 := by
              have b1p: 0 ≤ b1 := by
                rw [hb1]
                refine mul_nonneg ?_ ?_
                . ring_nf
                  exact g₁₁
                . refine le_of_lt ?_
                  exact one_div_pos.mpr (hxp (n + 1))
              have b2p: 0 ≤ b2 := by
                rw [hb2]
                refine mul_nonneg ?_ ?_
                . ring_nf
                  exact g₁₁
                . refine le_of_lt ?_
                  exact one_div_pos.mpr (hxp (n + 2))
              have b3p: 0 ≤ b3 := by
                rw [hb3]
                refine mul_nonneg ?_ ?_
                . exact LT.lt.le (hxp (n + 1))
                . ring_nf
                  exact g₁₂
              have b4p: 0 ≤ b4 := by
                rw [hb4]
                refine mul_nonneg ?_ ?_
                . exact LT.lt.le (hxp (n + 2))
                . ring_nf
                  exact g₁₂
              exact mylemma_amgm b1 b2 b3 b4 b1p b2p b3p b4p
            linarith
      have h₃₃: 4 * a (n) = 4 * (((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 1))) *
          ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) * (1 / x (n + 2))) *
          ((x (n + 1) * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k)) *
          (x (n + 2) * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) ) ^ (4:ℝ)⁻¹ := by
        simp
        ring_nf
        have g₀: (Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => x x_1) ^ 2
            * x (1 + n) * (x (1 + n))⁻¹ * x (2 + n) * (x (2 + n))⁻¹ *
            (Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => (x x_1)⁻¹) ^ 2
          = x (1 + n) * (x (1 + n))⁻¹ * x (2 + n) * (x (2 + n))⁻¹ *
            (Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => x x_1) ^ 2 *
            (Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => (x x_1)⁻¹) ^ 2 := by
            linarith
        have g₁: x (1 + n) * (x (1 + n))⁻¹ * x (2 + n) * (x (2 + n))⁻¹ = 1 := by
          rw [mul_assoc]
          have gg₁: x (1 + n) * (x (1 + n))⁻¹ = 1 := by
            refine div_self ?_
            exact ne_of_gt (hxp (1 + n))
          have gg₂: x (2 + n) * (x (2 + n))⁻¹ = 1 := by
            refine div_self ?_
            exact ne_of_gt (hxp (2 + n))
          rw [gg₁, gg₂]
          norm_num
        rw [g₁] at g₀
        rw [g₀]
        simp
        repeat rw [mul_rpow]
        have g₂: ((Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => x x_1) ^ (2:ℝ)) ^ (4:ℝ)⁻¹
            = (Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => x x_1) ^ (1/(2:ℝ)) := by
              rw [← rpow_mul g₁₁ (2:ℝ) (4:ℝ)⁻¹]
              norm_num
        have g₃: ((Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => (x x_1)⁻¹) ^ (2:ℝ)) ^ (4:ℝ)⁻¹
            = (Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => (x x_1)⁻¹) ^ (1/(2:ℝ)) := by
              rw [← rpow_mul g₁₂ (2:ℝ) (4:ℝ)⁻¹]
              norm_num
        -- rw [g₂, ← sqrt_eq_rpow (Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => x x_1)]
        -- rw [g₃, ← sqrt_eq_rpow (Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => (x x_1)⁻¹)]
        have g₄: a (n) = sqrt ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k)
                  * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) := by
          refine h₀ n ?_
          constructor
          . exact hn.1
          . linarith
        norm_cast at *
        rw [g₂, g₃, ← mul_rpow]
        rw [← sqrt_eq_rpow]
        ring_nf at g₄
        exact g₄
        . exact g₁₁
        . exact g₁₂
        . exact sq_nonneg (Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => x x_1)
        . exact sq_nonneg (Finset.sum (Finset.Ico 1 (1 + n)) fun x_1 => (x x_1)⁻¹)
      exact Eq.trans_le h₃₃ h₃₂


lemma mylemma_3
  (x a: ℕ → ℝ)
  (hxp: ∀ (i : ℕ), 0 < x i)
  (hx: ∀ (i j : ℕ), i ≠ j → x i ≠ x j)
  (h₀: ∀ (n : ℕ),
    1 ≤ n ∧ n ≤ 2023 →
      a n = sqrt ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k)
            * (Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k)))
  (h₀₁: ∀ (n : ℕ), 1 ≤ n ∧ n ≤ 2023 → 0 < a n) :
  (∀ (n : ℕ), 1 ≤ n ∧ n ≤ 2021 → a n + 2 < a (n + 2)) := by
    intros n hn
    have g₀: 0 ≤ a n + 2 := by
      refine le_of_lt ?_
      refine add_pos ?_ (by norm_num)
      refine h₀₁ n ?_
      constructor
      . exact hn.1
      . linarith
    have g₁: 0 ≤ a (n + 2) := by
      refine le_of_lt ?_
      refine h₀₁ (n + 2) ?_
      constructor
      . linarith
      . linarith
    rw [← sqrt_sq g₀, ← sqrt_sq g₁]
    have g₂: 0 ≤ (a n + 2) ^ 2 := by exact sq_nonneg (a n + 2)
    -- simp
    refine Real.sqrt_lt_sqrt g₂ ?_
    have g₃: 0 ≤ ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k)
        * (Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k)) := by
      refine le_of_lt ?_
      refine mul_pos ?_ ?_
      . refine Finset.sum_pos ?_ ?_
        . exact fun i _ => hxp i
        . simp
          linarith
      . refine Finset.sum_pos ?_ ?_
        . intros i _
          exact one_div_pos.mpr (hxp i)
        . simp
          linarith
    have gn₀: a (n) ^ 2 = ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k)
        * (Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k)) := by
      rw [← sq_sqrt g₃]
      have g₄: 0 ≤ a n := by
        refine le_of_lt ?_
        refine h₀₁ n ?_
        constructor
        . exact hn.1
        . linarith
      refine (sq_eq_sq₀ g₄ ?_).mpr ?_
      . exact
        sqrt_nonneg
          ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k) *
            Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k)
      . refine h₀ (n) ?_
        constructor
        . exact hn.1
        . linarith
    have gn₁: a (n + 2) = sqrt ((Finset.sum (Finset.Ico 1 (n + 2 + 1)) fun k => x k)
        * Finset.sum (Finset.Ico 1 (n + 2 + 1)) fun k => 1 / x k) := by
      refine h₀ (n + 2) ?_
      constructor
      . linarith
      . linarith
    rw [add_sq, gn₁, sq_sqrt]
    . have ga₀: 1 ≤ n + 2 := by linarith
      rw [Finset.sum_Ico_succ_top ga₀ _, Finset.sum_Ico_succ_top ga₀ _]
      have ga₁: 1 ≤ n + 1 := by linarith
      rw [Finset.sum_Ico_succ_top ga₁ _, Finset.sum_Ico_succ_top ga₁ _]
      rw [add_assoc, add_assoc, add_assoc]
      rw [add_mul, mul_add]
      rw [← gn₀]
      repeat rw [add_assoc]
      refine add_lt_add_left ?_ (a (n) ^ 2)
      rw [mul_add (x (n + 1) + x (n + 2))]
      have h₂: 4 < (x (n + 1) + x (n + 2)) * (1 / x (n + 1) + 1 / x (n + 2)) := by
        repeat rw [add_mul, mul_add, mul_add]
        repeat rw [mul_div_left_comm _ 1 _, one_mul]
        repeat rw [div_self ?_]
        . have hc₂: x (n + 1) * x (n + 2) * (x (n + 1) / x (n + 2))
            = x (n + 1) * x (n + 1) := by
            rw [mul_assoc, ← mul_div_assoc, mul_div_right_comm, div_self ?_]
            simp
            exact ne_of_gt (hxp (n + 2))
          have hc₃: x (n + 1) * x (n + 2) * (x (n + 2) / x (n + 1))
            = x (n + 2) * x (n + 2) := by
            rw [mul_comm (x (n + 1)) (x (n + 2)), mul_assoc, ← mul_div_assoc, mul_div_right_comm, div_self ?_]
            simp
            exact ne_of_gt (hxp (n + 1))
          have h₂₀: 0 < x (n + 1) * x (n + 2) := by
            refine mul_pos ?_ ?_
            . exact hxp (n + 1)
            . exact hxp (n + 2)
          have h₂₁: 2 < x (n + 1) / x (n + 2) + x (n + 2) / x (n + 1) := by
            refine lt_of_mul_lt_mul_left ?_ (le_of_lt h₂₀)
            rw [mul_add, hc₂, hc₃, ← sq, ← sq]
            refine lt_of_sub_pos ?_
            have gh₂₁: x (n + 1) ^ 2 + x (n + 2) ^ 2 - x (n + 1) * x (n + 2) * 2
                      = (x (n + 1) - x (n + 2)) ^ 2 := by
              rw [sub_sq]
              linarith
            rw [gh₂₁]
            refine (sq_pos_iff).mpr ?_
            refine sub_ne_zero.mpr ?_
            exact hx (n+1) (n+2) (by linarith)
          linarith
        . exact ne_of_gt (hxp (n + 2))
        . exact ne_of_gt (hxp (n + 1))
      clear gn₀ gn₁ g₀ g₁ g₂ g₃ ga₀ ga₁
      have h₃: 4 * a (n) ≤ (Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k)
          * (1 / x (n + 1) + 1 / x (n + 2)) +
          ((x (n + 1) + x (n + 2))
          * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) := by
          exact mylemma_2 (fun k => x k) a hxp h₀ n hn
      linarith
    . refine mul_nonneg ?_ ?_
      . refine Finset.sum_nonneg ?_
        intros i _
        exact LT.lt.le (hxp i)
      . refine Finset.sum_nonneg ?_
        intros i _
        simp
        exact LT.lt.le (hxp i)


theorem imo_2023_p4
  (x : ℕ → ℝ)
  (a : ℕ → ℝ)
  (hxp: ∀ (i: ℕ), (0 < x i) )
  (hx: ∀ (i j: ℕ), (i ≠ j) → (x i ≠ x j) )
  (h₀: ∀ (n:ℕ), (1 ≤ n ∧ n ≤ 2023) →
        a n = Real.sqrt ( (Finset.sum (Finset.Ico 1 (n + 1)) fun (k : ℕ) => (x k))
            * (Finset.sum (Finset.Ico 1 (n + 1)) fun (k : ℕ) => 1 / (x k)) ) )
  (h₁: ∀ (n:ℕ), (1 ≤ n ∧ n ≤ 2023) → ∃ (kz:ℤ), (a n = ↑kz )) :
  (3034 ≤ a 2023) := by
  have ha1: a 1 = 1 := by
    have g₀: sqrt ((Finset.sum (Finset.Ico 1 (1 + 1)) fun k => x k)
            * Finset.sum (Finset.Ico 1 (1 + 1)) fun k => 1 / x k) = 1 := by
      norm_num
      refine div_self ?_
      exact ne_of_gt (hxp 1)
    rw [← g₀]
    exact h₀ (1) (by norm_num)
  have h₀₁: ∀ (n : ℕ), (1 ≤ n ∧ n ≤ 2023) → 0 < a n := by
    intros n hn
    have ha: a n = sqrt ((Finset.sum (Finset.Ico 1 (n + 1)) fun k => x k)
       * Finset.sum (Finset.Ico 1 (n + 1)) fun k => 1 / x k) := by
        exact h₀ (n) (hn)
    rw [ha]
    refine Real.sqrt_pos.mpr ?_
    refine mul_pos ?_ ?_
    . refine Finset.sum_pos ?_ ?_
      . intros i _
        exact hxp i
      simp
      linarith
    . refine Finset.sum_pos ?_ ?_
      . intros i _
        exact one_div_pos.mpr (hxp i)
      simp
      linarith
  have h₁₁: ∀ (n : ℕ), (1 ≤ n ∧ n ≤ 2023) → ∃ (kn:ℕ), a n = ↑kn := by
    intros n hn
    have g₁₁: 0 < a n := by
      exact h₀₁ n hn
    let ⟨p, gp⟩ := h₁ n hn
    let q:ℕ := Int.toNat p
    have g₁₂: ↑q = p := by
      refine Int.toNat_of_nonneg ?_
      rw [gp] at g₁₁
      norm_cast at g₁₁
      exact Int.le_of_lt g₁₁
    use q
    rw [gp]
    norm_cast
    exact id g₁₂.symm
  have h₂₁: ∀ (n:ℕ), (1 ≤ n ∧ n ≤ 2021) → a n + 2 < a (n+2) := by
    exact fun n a_1 => mylemma_3 (fun i => x i) a hxp hx h₀ h₀₁ n a_1
  have h₂: ∀ (n:ℕ), (1 ≤ n ∧ n ≤ 2021) → a n + 3 ≤ a (n+2) := by
    intros n hn
    have g₀: a n + 2 < a (n + 2) := by exact h₂₁ n hn
    have g₀₁: ∃ (p:ℕ), a n = ↑p := by
      apply h₁₁
      constructor
      . linarith
      . linarith
    have g₀₂: ∃ (q:ℕ), a (n + 2) = ↑q := by
      apply h₁₁
      constructor
      . linarith
      . linarith
    let ⟨p, _⟩ := g₀₁
    let ⟨q, _⟩ := g₀₂
    have g₁: p + 2 < q := by
      suffices g₁₁: ↑p + (2:ℝ) < ↑q
      . norm_cast at g₁₁
      . linarith
    have g₂: ↑p + (3:ℝ) ≤ ↑q := by norm_cast
    linarith
  have h₃: ∀ (n:ℕ), (0 ≤ n ∧ n ≤ 1010) → a 1 + 3 * (↑(n)  + 1) ≤ a (3 + 2 * n) := by
    intros n hn
    induction' n with d hd
    · simp
      exact h₂ (1) (by norm_num)
    · rw [mul_add]
      simp
      have g₀: a (3 + 2 * d) + 3 ≤ a (3 + 2 * (d + 1)) := by
        refine h₂ (3 + 2 * d) ?_
        constructor
        . linarith
        . linarith
      have g₁: a 1 + 3 * (↑d + 1) + 3 ≤ a (3 + 2 * d) + 3 := by
        refine add_le_add_right ?_ (3)
        apply hd
        constructor
        . linarith
        . linarith
      refine le_trans (by linarith[g₁]) g₀
  rw [ha1] at h₃
  have h₄: (3034:ℝ)  = 1 + 3 * (↑1010 + 1) := by norm_num
  rw [h₄]
  exact h₃ (1010) (by norm_num)
