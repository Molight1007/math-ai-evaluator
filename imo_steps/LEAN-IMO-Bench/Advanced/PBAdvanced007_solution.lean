import Mathlib
open Polynomial

theorem PBAdvanced007 : ∃ P Q : ℝ[X],
    2024 ≤ P.natDegree ∧ 2 ≤ Q.natDegree ∧ P.comp (Q - X - 1) = Q.comp P :=
by
  use ((X : ℝ[X]) + C (5/4 : ℝ))^2024 - C (7/4 : ℝ)
  use ((X : ℝ[X]) + C (7/4 : ℝ))^2 - C (7/4 : ℝ)
  refine ⟨?_, ?_, ?_⟩
  · apply le_natDegree_of_ne_zero (n := 2024)
    have hMonic : ((X : ℝ[X]) + C (5/4 : ℝ)).Monic := monic_X_add_C (5/4 : ℝ)
    have hMonic_pow : (((X : ℝ[X]) + C (5/4 : ℝ))^2024).Monic := Monic.pow hMonic 2024
    have h_deg : natDegree (((X : ℝ[X]) + C (5/4 : ℝ))^2024) = 2024 := by
      rw [natDegree_pow, natDegree_X_add_C, mul_one]
    have hLC : (((X : ℝ[X]) + C (5/4 : ℝ))^2024).coeff 2024 = 1 := by
      have h1 : (((X : ℝ[X]) + C (5/4 : ℝ))^2024).leadingCoeff = 1 := hMonic_pow
      change (((X : ℝ[X]) + C (5/4 : ℝ))^2024).coeff (((X : ℝ[X]) + C (5/4 : ℝ))^2024).natDegree = 1 at h1
      rw [h_deg] at h1
      exact h1
    have h_coeff : (((X : ℝ[X]) + C (5/4 : ℝ))^2024 - C (7/4 : ℝ)).coeff 2024 = 1 := by
      rw [coeff_sub, hLC]
      have hC : (C (7/4 : ℝ)).coeff 2024 = 0 := by
        rw [coeff_C, if_neg (by decide)]
      rw [hC, sub_zero]
    rw [h_coeff]
    exact one_ne_zero
  · apply le_natDegree_of_ne_zero (n := 2)
    have hMonic : ((X : ℝ[X]) + C (7/4 : ℝ)).Monic := monic_X_add_C (7/4 : ℝ)
    have hMonic_pow : (((X : ℝ[X]) + C (7/4 : ℝ))^2).Monic := Monic.pow hMonic 2
    have h_deg : natDegree (((X : ℝ[X]) + C (7/4 : ℝ))^2) = 2 := by
      rw [natDegree_pow, natDegree_X_add_C, mul_one]
    have hLC : (((X : ℝ[X]) + C (7/4 : ℝ))^2).coeff 2 = 1 := by
      have h1 : (((X : ℝ[X]) + C (7/4 : ℝ))^2).leadingCoeff = 1 := hMonic_pow
      change (((X : ℝ[X]) + C (7/4 : ℝ))^2).coeff (((X : ℝ[X]) + C (7/4 : ℝ))^2).natDegree = 1 at h1
      rw [h_deg] at h1
      exact h1
    have h_coeff : (((X : ℝ[X]) + C (7/4 : ℝ))^2 - C (7/4 : ℝ)).coeff 2 = 1 := by
      rw [coeff_sub, hLC]
      have hC : (C (7/4 : ℝ)).coeff 2 = 0 := by
        rw [coeff_C, if_neg (by decide)]
      rw [hC, sub_zero]
    rw [h_coeff]
    exact one_ne_zero
  · rw [← C_1]
    have hL : (((X : ℝ[X]) + C (5/4 : ℝ))^2024 - C (7/4 : ℝ)).comp ((((X : ℝ[X]) + C (7/4 : ℝ))^2 - C (7/4 : ℝ)) - X - C 1) =
      ((((X : ℝ[X]) + C (7/4 : ℝ))^2 - C (7/4 : ℝ)) - X - C 1 + C (5/4 : ℝ))^2024 - C (7/4 : ℝ) := by
      simp only [add_comp, sub_comp, pow_comp, mul_comp, C_comp, X_comp]
    rw [hL]

    have hBase : ((((X : ℝ[X]) + C (7/4 : ℝ))^2 - C (7/4 : ℝ)) - X - C 1 + C (5/4 : ℝ)) = ((X : ℝ[X]) + C (5/4 : ℝ))^2 := by
      calc ((((X : ℝ[X]) + C (7/4 : ℝ))^2 - C (7/4 : ℝ)) - X - C 1 + C (5/4 : ℝ))
        _ = X^2 + X * (C (7/4 : ℝ) + C (7/4 : ℝ) - 1) + (C (7/4 : ℝ)^2 - C (7/4 : ℝ) - C 1 + C (5/4 : ℝ)) := by ring
        _ = X^2 + X * C (7/4 + 7/4 - 1 : ℝ) + C ((7/4)^2 - 7/4 - 1 + 5/4 : ℝ) := by
          have h_lin : C (7/4 : ℝ) + C (7/4 : ℝ) - 1 = C (7/4 + 7/4 - 1 : ℝ) := by
            rw [← C_1, ← map_add C, ← map_sub C]
          have h_const : C (7/4 : ℝ)^2 - C (7/4 : ℝ) - C 1 + C (5/4 : ℝ) = C ((7/4)^2 - 7/4 - 1 + 5/4 : ℝ) := by
            rw [← map_pow C, ← map_sub C, ← map_sub C, ← map_add C]
          rw [h_lin, h_const]
        _ = X^2 + X * C (5/4 + 5/4 : ℝ) + C ((5/4)^2 : ℝ) := by
          have h1 : (7/4 + 7/4 - 1 : ℝ) = (5/4 + 5/4 : ℝ) := by norm_num
          have h2 : ((7/4)^2 - 7/4 - 1 + 5/4 : ℝ) = (5/4)^2 := by norm_num
          rw [h1, h2]
        _ = X^2 + X * (C (5/4 : ℝ) + C (5/4 : ℝ)) + C (5/4 : ℝ)^2 := by
          rw [map_add C, map_pow C]
        _ = ((X : ℝ[X]) + C (5/4 : ℝ))^2 := by ring
    rw [hBase]

    have hPow1 : (((X : ℝ[X]) + C (5/4 : ℝ))^2)^2024 = ((X : ℝ[X]) + C (5/4 : ℝ))^4048 := by
      calc (((X : ℝ[X]) + C (5/4 : ℝ))^2)^2024 = ((X : ℝ[X]) + C (5/4 : ℝ))^(2 * 2024) := by rw [← pow_mul]
        _ = ((X : ℝ[X]) + C (5/4 : ℝ))^4048 := rfl
    rw [hPow1]

    have hR : ((((X : ℝ[X]) + C (7/4 : ℝ))^2 - C (7/4 : ℝ))).comp ((((X : ℝ[X]) + C (5/4 : ℝ))^2024 - C (7/4 : ℝ))) =
      (((((X : ℝ[X]) + C (5/4 : ℝ))^2024 - C (7/4 : ℝ))) + C (7/4 : ℝ))^2 - C (7/4 : ℝ) := by
      simp only [add_comp, sub_comp, pow_comp, mul_comp, C_comp, X_comp]
    rw [hR]

    have hBaseR : ((((X : ℝ[X]) + C (5/4 : ℝ))^2024 - C (7/4 : ℝ))) + C (7/4 : ℝ) = (((X : ℝ[X]) + C (5/4 : ℝ))^2024) := by
      -- Isolate large polynomial components behind generic variables so ring doesn't choke expanding them
      generalize (((X : ℝ[X]) + C (5/4 : ℝ))^2024) = P_expr
      generalize (C (7/4 : ℝ)) = C_expr
      ring
    rw [hBaseR]

    have hPow2 : (((X : ℝ[X]) + C (5/4 : ℝ))^2024)^2 = ((X : ℝ[X]) + C (5/4 : ℝ))^4048 := by
      calc (((X : ℝ[X]) + C (5/4 : ℝ))^2024)^2 = ((X : ℝ[X]) + C (5/4 : ℝ))^(2024 * 2) := by rw [← pow_mul]
        _ = ((X : ℝ[X]) + C (5/4 : ℝ))^4048 := rfl
    rw [hPow2]
