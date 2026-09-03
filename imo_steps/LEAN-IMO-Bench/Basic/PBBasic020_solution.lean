import Mathlib

theorem PBBasic020 : {(a, b) : ℕ × ℕ | a.Prime ∧ b.Prime ∧ (a ^ 2 - a * b - b ^ 3 : ℕ) = 1} = {(7, 3)} :=
by
  ext ⟨a, b⟩
  simp only [Set.mem_setOf_eq, Set.mem_singleton_iff, Prod.mk.injEq]
  constructor
  · rintro ⟨ha, hb, h_eq⟩
    have hb2 : 2 ≤ b := Nat.Prime.two_le hb
    have ha2 : 2 ≤ a := Nat.Prime.two_le ha

    -- Using `omega` directly abstracts nonlinear terms like a^2 and b^3 to resolve the subtraction.
    have h2 : a^2 = a * b + b^3 + 1 := by omega

    have hb_sq : b ≤ b^2 := by
      calc b = b * 1 := by ring
      _ ≤ b * b := Nat.mul_le_mul_left b (by omega)
      _ = b^2 := by ring

    have h_a_gt_b : b < a := by
      by_contra h_not
      have h_b_le : a ≤ b := by omega
      have h_le : a^2 ≤ a * b := by
        calc a^2 = a * a := by ring
        _ ≤ a * b := Nat.mul_le_mul_left a h_b_le
      omega

    have h_b_le_a : b ≤ a := by omega

    -- Factor algebraically over ℤ
    have h_factor_nat : a * (a - b) = (b + 1) * (b^2 - b + 1) := by
      have h2_z : (a:ℤ)^2 = (a:ℤ)*(b:ℤ) + (b:ℤ)^3 + 1 := by exact_mod_cast h2
      zify [h_b_le_a, hb_sq]
      push_cast
      calc (a:ℤ) * ((a:ℤ) - (b:ℤ)) = (a:ℤ)^2 - (a:ℤ) * (b:ℤ) := by ring
      _ = ((a:ℤ)*(b:ℤ) + (b:ℤ)^3 + 1) - (a:ℤ) * (b:ℤ) := by rw [h2_z]
      _ = (b:ℤ)^3 + 1 := by ring
      _ = ((b:ℤ) + 1) * ((b:ℤ)^2 - (b:ℤ) + 1) := by ring

    have h_dvd : a ∣ (b + 1) * (b^2 - b + 1) := ⟨a - b, h_factor_nat.symm⟩

    rcases (Nat.Prime.dvd_mul ha).mp h_dvd with h_dvd1 | h_dvd2
    · -- Case 1: a ∣ b + 1
      have h_b_plus_one_pos : 0 < b + 1 := by omega
      have : a ≤ b + 1 := Nat.le_of_dvd h_b_plus_one_pos h_dvd1
      have ha_eq : a = b + 1 := by omega
      rw [ha_eq] at h_factor_nat
      have h_sub : (b + 1) * 1 = (b + 1) * (b^2 - b + 1) := by
        have h_one : 1 = b + 1 - b := by omega
        calc (b + 1) * 1 = (b + 1) * (b + 1 - b) := congrArg (fun x => (b + 1) * x) h_one
        _ = (b + 1) * (b^2 - b + 1) := h_factor_nat
      have h_eq3 : 1 = b^2 - b + 1 := Nat.eq_of_mul_eq_mul_left (by omega) h_sub
      have : b^2 - b = 0 := by omega
      have hb_eq : b^2 = b := by omega
      have : 2 * b ≤ b^2 := by
        calc 2 * b ≤ b * b := Nat.mul_le_mul_right b hb2
        _ = b^2 := by ring
      omega

    · -- Case 2: a ∣ b^2 - b + 1
      obtain ⟨k, hk⟩ := h_dvd2
      have hk_eq : a * k = b^2 - b + 1 := hk.symm

      have h_sub2 : a * (a - b) = a * (k * (b + 1)) := by
        calc a * (a - b) = (b + 1) * (b^2 - b + 1) := h_factor_nat
        _ = (b + 1) * (a * k) := by rw [← hk_eq]
        _ = a * (k * (b + 1)) := by ring

      have ha_pos : 0 < a := by omega
      have h_sub3 : a - b = k * (b + 1) := Nat.eq_of_mul_eq_mul_left ha_pos h_sub2

      have ha_eq2 : a = k * b + k + b := by
        calc a = a - b + b := by omega
        _ = k * (b + 1) + b := by rw [h_sub3]
        _ = k * b + k + b := by ring

      have hk_eq2 : (k * b + k + b) * k = b^2 - b + 1 := by
        calc (k * b + k + b) * k = a * k := by rw [← ha_eq2]
        _ = b^2 - b + 1 := hk_eq

      have h_quad : (b:ℤ)^2 + 1 = ((k:ℤ)^2 + (k:ℤ) + 1) * (b:ℤ) + (k:ℤ)^2 := by
        have hk_eq2_Z : ((k:ℤ) * (b:ℤ) + (k:ℤ) + (b:ℤ)) * (k:ℤ) = (b:ℤ)^2 - (b:ℤ) + 1 := by
          have h_tmp := hk_eq2
          zify [hb_sq] at h_tmp
          push_cast at h_tmp
          exact h_tmp
        calc (b:ℤ)^2 + 1 = (b:ℤ)^2 - (b:ℤ) + 1 + (b:ℤ) := by ring
        _ = ((k:ℤ) * (b:ℤ) + (k:ℤ) + (b:ℤ)) * (k:ℤ) + (b:ℤ) := by rw [← hk_eq2_Z]
        _ = ((k:ℤ)^2 + (k:ℤ) + 1) * (b:ℤ) + (k:ℤ)^2 := by ring

      have hk0 : k ≠ 0 := by
        intro h_zero
        have : b^2 - b + 1 = 0 := by
          calc b^2 - b + 1 = a * k := hk_eq.symm
          _ = 0 := by rw [h_zero, mul_zero]
        have : 2 * b ≤ b^2 := by
          calc 2 * b ≤ b * b := Nat.mul_le_mul_right b hb2
          _ = b^2 := by ring
        omega

      have hk_cases : k = 1 ∨ 2 ≤ k := by omega
      rcases hk_cases with rfl | hk_gt
      · -- Subcase k = 1
        have h_quad_1 : (b:ℤ)^2 + 1 = 3 * (b:ℤ) + 1 := by
          calc (b:ℤ)^2 + 1 = ((1:ℤ)^2 + (1:ℤ) + 1) * (b:ℤ) + (1:ℤ)^2 := h_quad
          _ = 3 * (b:ℤ) + 1 := by ring
        have h_b_eq : (b:ℤ) * ((b:ℤ) - 3) = 0 := by
          calc (b:ℤ) * ((b:ℤ) - 3) = (b:ℤ)^2 + 1 - (3 * (b:ℤ) + 1) := by ring
          _ = 3 * (b:ℤ) + 1 - (3 * (b:ℤ) + 1) := by rw [h_quad_1]
          _ = 0 := by ring
        rcases mul_eq_zero.mp h_b_eq with hb0 | hb3
        · have : 2 ≤ (b:ℤ) := by exact_mod_cast hb2
          omega
        · have hb3_eq : (b:ℤ) = 3 := by omega
          have hb3_nat : b = 3 := by exact_mod_cast hb3_eq
          have ha7_nat : a = 7 := by
            calc a = 1 * b + 1 + b := ha_eq2
            _ = 1 * 3 + 1 + 3 := by rw [hb3_nat]
            _ = 7 := by rfl
          exact ⟨ha7_nat, hb3_nat⟩

      · -- Subcase k ≥ 2
        have hK : 2 ≤ (k:ℤ) := by exact_mod_cast hk_gt
        have h_factor_B : (b:ℤ) * ((b:ℤ) - ((k:ℤ)^2 + (k:ℤ) + 1)) = (k:ℤ)^2 - 1 := by
          calc (b:ℤ) * ((b:ℤ) - ((k:ℤ)^2 + (k:ℤ) + 1)) = ((b:ℤ)^2 + 1) - 1 - ((k:ℤ)^2 + (k:ℤ) + 1) * (b:ℤ) := by ring
          _ = (((k:ℤ)^2 + (k:ℤ) + 1) * (b:ℤ) + (k:ℤ)^2) - 1 - ((k:ℤ)^2 + (k:ℤ) + 1) * (b:ℤ) := by rw [h_quad]
          _ = (k:ℤ)^2 - 1 := by ring

        have h_pos : 0 < (k:ℤ)^2 - 1 := by nlinarith [hK]

        have h_diff_pos : 0 < (b:ℤ) - ((k:ℤ)^2 + (k:ℤ) + 1) := by
          by_contra h_not
          have h1 : (b:ℤ) - ((k:ℤ)^2 + (k:ℤ) + 1) ≤ 0 := by omega
          have h2 : 0 ≤ (b:ℤ) := by omega
          have h3 : (b:ℤ) * ((b:ℤ) - ((k:ℤ)^2 + (k:ℤ) + 1)) ≤ 0 := by nlinarith [h1, h2]
          have h4 : (k:ℤ)^2 - 1 ≤ 0 := by
            calc (k:ℤ)^2 - 1 = (b:ℤ) * ((b:ℤ) - ((k:ℤ)^2 + (k:ℤ) + 1)) := h_factor_B.symm
            _ ≤ 0 := h3
          omega

        have h_diff_ge : 1 ≤ (b:ℤ) - ((k:ℤ)^2 + (k:ℤ) + 1) := by omega

        -- Form bound contradictions safely abstracted
        have h_bound1 : (b:ℤ) ≤ (k:ℤ)^2 - 1 := by
          have h2 : 1 ≤ (b:ℤ) - ((k:ℤ)^2 + (k:ℤ) + 1) := h_diff_ge
          have h3 : 0 ≤ (b:ℤ) := by omega
          have h4 : (b:ℤ) * 1 ≤ (b:ℤ) * ((b:ℤ) - ((k:ℤ)^2 + (k:ℤ) + 1)) := by nlinarith [h2, h3]
          calc (b:ℤ) = (b:ℤ) * 1 := by ring
          _ ≤ (b:ℤ) * ((b:ℤ) - ((k:ℤ)^2 + (k:ℤ) + 1)) := h4
          _ = (k:ℤ)^2 - 1 := h_factor_B

        have h_bound2 : (k:ℤ)^2 + (k:ℤ) + 2 ≤ (b:ℤ) := by omega

        -- omega robustly abstracts uninterpreted (k:ℤ)^2 allowing for a much faster resolution
        omega

  · -- Prove the known elements satisfy all definition criteria backward
    rintro ⟨rfl, rfl⟩
    exact ⟨by decide, by decide, by rfl⟩
