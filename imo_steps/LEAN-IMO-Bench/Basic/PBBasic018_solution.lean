import Mathlib

theorem PBBasic018 (x y : ℕ) (hx : x ≠ 0) (hy : y ≠ 0)
    (H : 2 * x ^ 2 + x = 3 * y ^ 2 + y) : IsSquare (2 * x + 2 * y + 1) :=
by
  have h_xy : y ≤ x := by
    by_contra h
    have h1 : x + 1 ≤ y := by omega
    have h1z : (x : ℤ) + 1 ≤ (y : ℤ) := by exact_mod_cast h1
    have h2z : 0 ≤ (x : ℤ) := by omega
    have h3z : 0 ≤ (y : ℤ) - ((x : ℤ) + 1) := by omega
    have h4z : 0 ≤ (y : ℤ) + ((x : ℤ) + 1) := by omega
    have h5z : 0 ≤ ((y : ℤ) - ((x : ℤ) + 1)) * ((y : ℤ) + ((x : ℤ) + 1)) := mul_nonneg h3z h4z
    have h6z : ((x : ℤ) + 1) ^ 2 ≤ (y : ℤ) ^ 2 := by
      calc ((x : ℤ) + 1) ^ 2 ≤ ((x : ℤ) + 1) ^ 2 + ((y : ℤ) - ((x : ℤ) + 1)) * ((y : ℤ) + ((x : ℤ) + 1)) := by linarith
        _ = (y : ℤ) ^ 2 := by ring
    have HZ : 2 * (x : ℤ) ^ 2 + (x : ℤ) = 3 * (y : ℤ) ^ 2 + (y : ℤ) := by exact_mod_cast H
    have h7z : 2 * (x : ℤ) ^ 2 + (x : ℤ) < 3 * ((x : ℤ) + 1) ^ 2 + ((x : ℤ) + 1) := by
      have : 0 ≤ (x : ℤ) ^ 2 := by positivity
      linarith
    have h8z : 3 * ((x : ℤ) + 1) ^ 2 + ((x : ℤ) + 1) ≤ 3 * (y : ℤ) ^ 2 + (y : ℤ) := by linarith
    linarith

  let A : ℕ := x - y
  let B : ℕ := 2 * x + 2 * y + 1

  have h_AB_Z : (A : ℤ) * (B : ℤ) = (y : ℤ) ^ 2 := by
    have hA : (A : ℤ) = (x : ℤ) - (y : ℤ) := by omega
    have hB : (B : ℤ) = 2 * (x : ℤ) + 2 * (y : ℤ) + 1 := by omega
    have HZ : 2 * (x : ℤ) ^ 2 + (x : ℤ) = 3 * (y : ℤ) ^ 2 + (y : ℤ) := by exact_mod_cast H
    calc (A : ℤ) * (B : ℤ) = ((x : ℤ) - (y : ℤ)) * (2 * (x : ℤ) + 2 * (y : ℤ) + 1) := by rw [hA, hB]
      _ = 2 * (x : ℤ) ^ 2 + (x : ℤ) - 2 * (y : ℤ) ^ 2 - (y : ℤ) := by ring
      _ = 3 * (y : ℤ) ^ 2 + (y : ℤ) - 2 * (y : ℤ) ^ 2 - (y : ℤ) := by rw [HZ]
      _ = (y : ℤ) ^ 2 := by ring

  have h_AB : A * B = y ^ 2 := by exact_mod_cast h_AB_Z

  have h_B_eq : B = 2 * A + 4 * y + 1 := by omega

  let g := Nat.gcd B y
  have h_gB : g ∣ B := Nat.gcd_dvd_left B y
  have h_gy : g ∣ y := Nat.gcd_dvd_right B y
  rcases h_gB with ⟨B1, hB1⟩
  rcases h_gy with ⟨Y1, hY1⟩

  have hB_pos : 0 < B := by omega
  have hg_pos : 0 < g := Nat.gcd_pos_of_pos_left y hB_pos

  have h_mul1 : g * (A * B1) = g * (g * Y1 ^ 2) := by
    calc g * (A * B1) = A * (g * B1) := by ring
      _ = A * B := by rw [← hB1]
      _ = y ^ 2 := h_AB
      _ = (g * Y1) ^ 2 := by rw [← hY1]
      _ = g * (g * Y1 ^ 2) := by ring

  have h_AB1 : A * B1 = g * Y1 ^ 2 := Nat.eq_of_mul_eq_mul_left hg_pos h_mul1

  have h_gcd_eq : g = g * Nat.gcd B1 Y1 := by
    calc g = Nat.gcd B y := rfl
      _ = Nat.gcd (g * B1) (g * Y1) := by rw [hB1, hY1]
      _ = g * Nat.gcd B1 Y1 := Nat.gcd_mul_left g B1 Y1

  have h_cop : Nat.Coprime B1 Y1 := by
    have h_g1 : g * Nat.gcd B1 Y1 = g * 1 := by
      calc g * Nat.gcd B1 Y1 = g := h_gcd_eq.symm
        _ = g * 1 := by ring
    exact Nat.eq_of_mul_eq_mul_left hg_pos h_g1

  have h_B1_dvd_g : B1 ∣ g := by
    have hdvd : B1 ∣ g * Y1 ^ 2 := ⟨A, by
      calc g * Y1 ^ 2 = A * B1 := h_AB1.symm
        _ = B1 * A := by ring⟩
    have hdvd2 : B1 ∣ g * (Y1 * Y1) := by
      have : g * (Y1 * Y1) = g * Y1 ^ 2 := by ring
      rw [this]
      exact hdvd
    have h_cop_sq : Nat.Coprime B1 (Y1 * Y1) := Nat.Coprime.mul_right h_cop h_cop
    exact h_cop_sq.dvd_of_dvd_mul_right hdvd2

  have h_B_B1 : g * B1 ^ 2 = g * (2 * Y1 ^ 2 + 4 * Y1 * B1) + B1 := by
    calc g * B1 ^ 2 = (g * B1) * B1 := by ring
      _ = B * B1 := by rw [← hB1]
      _ = (2 * A + 4 * y + 1) * B1 := by rw [h_B_eq]
      _ = 2 * (A * B1) + 4 * y * B1 + B1 := by ring
      _ = 2 * (g * Y1 ^ 2) + 4 * (g * Y1) * B1 + B1 := by rw [h_AB1, hY1]
      _ = g * (2 * Y1 ^ 2 + 4 * Y1 * B1) + B1 := by ring

  have h_g_dvd_B1 : g ∣ B1 := by
    set X := B1 ^ 2
    set Y := 2 * Y1 ^ 2 + 4 * Y1 * B1
    have h_add : g * X = g * Y + B1 := h_B_B1
    have h_Y_le_X : Y ≤ X := by
      have : g * Y ≤ g * X := by omega
      exact Nat.le_of_mul_le_mul_left this hg_pos
    have h_eq : B1 = g * (X - Y) := by
      have h1 : Y + (X - Y) = X := by omega
      have h2 : g * X = g * Y + g * (X - Y) := by
        have h3 : g * (Y + (X - Y)) = g * Y + g * (X - Y) := by rw [mul_add]
        rw [h1] at h3
        exact h3
      omega
    exact ⟨X - Y, h_eq⟩

  have h_B1_eq_g : B1 = g := Nat.dvd_antisymm h_B1_dvd_g h_g_dvd_B1

  rw [isSquare_iff_exists_sq]
  exact ⟨g, by
    calc 2 * x + 2 * y + 1 = B := rfl
      _ = g * B1 := hB1
      _ = g * g := by rw [h_B1_eq_g]
      _ = g ^ 2 := by ring⟩
