import Mathlib

theorem PBBasic021 (x : ℕ → ℕ) (hx₁ : x 1 = 6)
    (hx_rec : ∀ n ≥ 1, x (n + 1) = 2 ^ (x n) + 2)
    (n : ℕ) (hn : 1 ≤ n) : x n ∣ x (n + 1) :=
by
  have H : ∀ k : ℕ, k ≥ 1 → x k ≥ 2 ∧ ∃ K : ℕ, x (k + 1) = x k + 2 * x k * (x k - 1) * K := by
    intro k
    induction' k with k ih
    · intro hk; omega
    · intro hk
      by_cases hk1 : k = 0
      · subst hk1
        have hx1 : x 1 = 6 := hx₁
        have hx2 : x 2 = 66 := by
          have h_rec : x 2 = 2 ^ x 1 + 2 := hx_rec 1 (by omega)
          calc x 2 = 2 ^ x 1 + 2 := h_rec
            _ = 2 ^ 6 + 2 := by rw [hx1]
            _ = 66 := rfl
        refine ⟨by rw [hx1]; omega, ⟨1, ?_⟩⟩
        have h_eq : x 1 + 2 * x 1 * (x 1 - 1) * 1 = 66 := by
          calc x 1 + 2 * x 1 * (x 1 - 1) * 1
            _ = 6 + 2 * 6 * (6 - 1) * 1 := by rw [hx1]
            _ = 66 := rfl
        rw [hx2, h_eq]
      · have hk_ge_1 : k ≥ 1 := by omega
        rcases ih hk_ge_1 with ⟨hX2, ⟨K, hK⟩⟩

        let X := x k
        let Y := x (k + 1)
        let Z := x (k + 2)
        have hY : Y = 2 ^ X + 2 := hx_rec k hk_ge_1
        have hZ : Z = 2 ^ Y + 2 := hx_rec (k + 1) (by omega)

        have hY2 : Y ≥ 2 := by
          rw [hY]
          have h_pos : 2 ^ X > 0 := by positivity
          omega

        let A := 2 ^ (X - 1) + 1
        let B := 2 ^ X + 1

        have helper : ∀ (a M : ℕ), a ≥ 1 → ∃ C : ℕ, a ^ (2 * M) = (a + 1) * C + 1 := by
          intro a M ha
          induction' M with M ihM
          · use 0; ring
          · rcases ihM with ⟨C, hC⟩
            obtain ⟨b, hb⟩ : ∃ b, a = b + 1 := ⟨a - 1, by omega⟩
            use C * (b + 1) ^ 2 + b
            have h1 : 2 * (M + 1) = 2 * M + 2 := by ring
            rw [h1, pow_add, hC, hb]
            ring

        have h_pow_A : ∃ C_A, 2 ^ (Y - X) = A * C_A + 1 := by
          have ha_ge_1 : 2 ^ (X - 1) ≥ 1 := by
            have h_pos : 2 ^ (X - 1) > 0 := by positivity
            omega
          obtain ⟨C_A, hCA⟩ := helper (2 ^ (X - 1)) (X * K) ha_ge_1
          use C_A
          calc 2 ^ (Y - X) = 2 ^ (2 * (X - 1) * (X * K)) := by
                have h_exp : Y - X = 2 * (X - 1) * (X * K) := by
                  have h_sub : Y - X = 2 * X * (X - 1) * K := by
                    have hK_X : Y = X + 2 * X * (X - 1) * K := hK
                    omega
                  rw [h_sub]
                  ring
                rw [h_exp]
            _ = (2 ^ (X - 1)) ^ (2 * (X * K)) := by
                have h_mul : 2 * (X - 1) * (X * K) = (X - 1) * (2 * (X * K)) := by ring
                rw [h_mul, pow_mul]
            _ = A * C_A + 1 := hCA

        have h_pow_B : ∃ C_B, 2 ^ (Y - X) = B * C_B + 1 := by
          have hb_ge_1 : 2 ^ X ≥ 1 := by
            have h_pos : 2 ^ X > 0 := by positivity
            omega
          obtain ⟨C_B, hCB⟩ := helper (2 ^ X) ((X - 1) * K) hb_ge_1
          use C_B
          calc 2 ^ (Y - X) = 2 ^ (2 * X * ((X - 1) * K)) := by
                have h_exp : Y - X = 2 * X * ((X - 1) * K) := by
                  have h_sub : Y - X = 2 * X * (X - 1) * K := by
                    have hK_X : Y = X + 2 * X * (X - 1) * K := hK
                    omega
                  rw [h_sub]
                  ring
                rw [h_exp]
            _ = (2 ^ X) ^ (2 * ((X - 1) * K)) := by
                have h_mul : 2 * X * ((X - 1) * K) = X * (2 * ((X - 1) * K)) := by ring
                rw [h_mul, pow_mul]
            _ = B * C_B + 1 := hCB

        let W := 2 ^ (Y - X) - 1
        have hWA : A ∣ W := by
          obtain ⟨C_A, hCA⟩ := h_pow_A
          use C_A
          have h_W_def : W = 2 ^ (Y - X) - 1 := rfl
          omega
        have hWB : B ∣ W := by
          obtain ⟨C_B, hCB⟩ := h_pow_B
          use C_B
          have h_W_def : W = 2 ^ (Y - X) - 1 := rfl
          omega

        have hRelPrime : Nat.Coprime A B := by
          let d := Nat.gcd A B
          have hdA : d ∣ A := Nat.gcd_dvd_left A B
          have hdB : d ∣ B := Nat.gcd_dvd_right A B
          have hd2A : d ∣ 2 * A := by
            obtain ⟨kA, hkA⟩ := hdA
            use 2 * kA
            calc 2 * A = 2 * (d * kA) := by rw [hkA]
              _ = d * (2 * kA) := by ring
          have h2A : 2 * A = B + 1 := by
            have h_pow : 2 * 2 ^ (X - 1) = 2 ^ X := by
              calc 2 * 2 ^ (X - 1) = 2 ^ 1 * 2 ^ (X - 1) := rfl
                _ = 2 ^ (1 + (X - 1)) := by rw [← pow_add]
                _ = 2 ^ X := by
                  have h3 : 1 + (X - 1) = X := by omega
                  rw [h3]
            calc 2 * A = 2 * (2 ^ (X - 1) + 1) := rfl
              _ = 2 * 2 ^ (X - 1) + 2 := by ring
              _ = 2 ^ X + 2 := by rw [h_pow]
              _ = (2 ^ X + 1) + 1 := rfl
              _ = B + 1 := rfl
          have hd1 : d ∣ 1 := by
            rw [h2A] at hd2A
            obtain ⟨k1, hk1⟩ := hd2A
            obtain ⟨k2, hk2⟩ := hdB
            have h_diff : 1 = d * (k1 - k2) := by
              calc 1 = (B + 1) - B := by omega
                _ = d * k1 - d * k2 := by rw [hk1, hk2]
                _ = d * (k1 - k2) := by rw [← Nat.mul_sub_left_distrib]
            exact ⟨k1 - k2, h_diff⟩
          exact Nat.eq_one_of_dvd_one hd1

        have hWAB : A * B ∣ W := hRelPrime.mul_dvd_of_dvd_of_dvd hWA hWB
        obtain ⟨C_AB, hCAB⟩ := hWAB

        have hZ_eq : Z = Y + 2 * Y * (Y - 1) * (2 ^ (X - 2) * C_AB) := by
          have h4AB : 4 * A * B = 2 * Y * (Y - 1) := by
            have h2 : 2 ^ X = 2 * 2 ^ (X - 1) := by
              calc 2 ^ X = 2 ^ (1 + (X - 1)) := by
                    have h3 : 1 + (X - 1) = X := by omega
                    rw [h3]
                _ = 2 ^ 1 * 2 ^ (X - 1) := by rw [pow_add]
                _ = 2 * 2 ^ (X - 1) := rfl
            calc 4 * A * B = 4 * (2 ^ (X - 1) + 1) * (2 ^ X + 1) := rfl
              _ = 2 * (2 * 2 ^ (X - 1) + 2) * (2 ^ X + 1) := by ring
              _ = 2 * (2 ^ X + 2) * (2 ^ X + 1) := by rw [← h2]
              _ = 2 * Y * (Y - 1) := by
                have hY_eq : 2 ^ X + 2 = Y := hY.symm
                have hY1 : 2 ^ X + 1 = Y - 1 := by
                  have hY_orig : Y = 2 ^ X + 2 := hY
                  omega
                rw [hY_eq, hY1]
          calc Z = 2 ^ Y + 2 := hZ
            _ = 2 ^ (X + (Y - X)) + 2 := by
                have h_sum : X + (Y - X) = Y := by
                  have hK_X : Y = X + 2 * X * (X - 1) * K := hK
                  omega
                rw [h_sum]
            _ = 2 ^ X * 2 ^ (Y - X) + 2 := by rw [pow_add]
            _ = 2 ^ X * (W + 1) + 2 := by
                have h_W_plus : 2 ^ (Y - X) = W + 1 := by
                  have h_W_def : W = 2 ^ (Y - X) - 1 := rfl
                  obtain ⟨C_A, hCA⟩ := h_pow_A
                  omega
                rw [h_W_plus]
            _ = 2 ^ X * W + 2 ^ X * 1 + 2 := by rw [mul_add]
            _ = 2 ^ X * W + 2 ^ X + 2 := by rw [mul_one]
            _ = 2 ^ X * W + (2 ^ X + 2) := by rw [add_assoc]
            _ = 2 ^ X * W + Y := by rw [← hY]
            _ = 2 ^ X * (A * B * C_AB) + Y := by
                have hW_eq : W = A * B * C_AB := hCAB
                rw [hW_eq]
            _ = Y + (4 * A * B) * (2 ^ (X - 2) * C_AB) := by
                have h_2X : 2 ^ X = 4 * 2 ^ (X - 2) := by
                  calc 2 ^ X = 2 ^ (2 + (X - 2)) := by
                        have h_X : 2 + (X - 2) = X := by omega
                        rw [h_X]
                    _ = 2 ^ 2 * 2 ^ (X - 2) := by rw [pow_add]
                    _ = 4 * 2 ^ (X - 2) := rfl
                rw [h_2X]
                ring
            _ = Y + (2 * Y * (Y - 1)) * (2 ^ (X - 2) * C_AB) := by rw [h4AB]
            _ = Y + 2 * Y * (Y - 1) * (2 ^ (X - 2) * C_AB) := by rw [mul_assoc]
        exact ⟨hY2, ⟨2 ^ (X - 2) * C_AB, hZ_eq⟩⟩

  have h_P : x n ≥ 2 ∧ ∃ K : ℕ, x (n + 1) = x n + 2 * x n * (x n - 1) * K := H n hn
  rcases h_P with ⟨hx2, K, hK⟩
  use 1 + 2 * (x n - 1) * K
  calc x (n + 1) = x n + 2 * x n * (x n - 1) * K := hK
    _ = x n * (1 + 2 * (x n - 1) * K) := by ring
