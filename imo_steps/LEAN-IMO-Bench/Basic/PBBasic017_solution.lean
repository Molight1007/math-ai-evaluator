import Mathlib

theorem PBBasic017 (A : ℕ → ℕ)
    (hA : ∀ n, A n = 1 + 3 ^ (20 * (n ^ 2 + n + 1))
      + 9 ^ (14 * (n ^ 2 + n + 1))) : {n | (A n).Prime} = {} :=
by
  ext n
  constructor
  · intro hn
    -- Explicitly type as `Nat.Prime` to leverage Mathlib's Nat.Prime theorems seamlessly
    have h_prime : Nat.Prime (A n) := hn

    -- Introduce variables OPQAQUELY to prevent `positivity` or `nlinarith` timeouts during unfolding
    obtain ⟨k, hk⟩ : ∃ k : ℕ, k = n ^ 2 + n + 1 := ⟨n ^ 2 + n + 1, rfl⟩
    have h_k_pos : 1 ≤ k := by omega

    obtain ⟨x, hx_eq⟩ : ∃ x : ℕ, x = 3 ^ (4 * k) := ⟨3 ^ (4 * k), rfl⟩

    have hx_ge : 81 ≤ x := by
      rw [hx_eq]
      have h_pow : 3 ^ 4 ≤ 3 ^ (4 * k) := by
        -- Ensure `omega` tackles all subgoals (e.g., base bounding) instantiated by `gcongr`
        gcongr <;> omega
      exact h_pow

    -- Verify the polynomial equality via explicit power multiplications
    have hA_val : A n = x ^ 7 + x ^ 5 + 1 := by
      rw [hA n, ← hk]
      have h1 : 3 ^ (20 * k) = x ^ 5 := by
        rw [hx_eq]
        have hR : (3 ^ (4 * k)) ^ 5 = 3 ^ (4 * k * 5) := by rw [← pow_mul]
        rw [hR]
        have : 20 * k = 4 * k * 5 := by ring
        rw [this]
      have h2 : 9 ^ (14 * k) = x ^ 7 := by
        rw [hx_eq]
        have h9 : 9 = 3 ^ 2 := rfl
        rw [h9]
        have hL : (3 ^ 2) ^ (14 * k) = 3 ^ (2 * (14 * k)) := by rw [← pow_mul]
        have hR : (3 ^ (4 * k)) ^ 7 = 3 ^ (4 * k * 7) := by rw [← pow_mul]
        rw [hL, hR]
        have : 2 * (14 * k) = 4 * k * 7 := by ring
        rw [this]
      rw [h1, h2]
      ring

    -- Clear the heavy definitions to avoid ANY nested expansion timeouts later on
    clear hk hx_eq hA

    obtain ⟨B, hB_eq⟩ : ∃ B : ℕ, B = x ^ 2 + x + 1 := ⟨x ^ 2 + x + 1, rfl⟩
    obtain ⟨C, hC_eq⟩ : ∃ C : ℕ, C = x ^ 4 * (x - 1) + x * (x ^ 2 - 1) + 1 := ⟨_, rfl⟩

    -- Perform polynomial factorization strictly verified in ℤ mappings to handle subtractions
    have h_eq_Z : (A n : ℤ) = (B : ℤ) * (C : ℤ) := by
      have hA_Z : (A n : ℤ) = (x : ℤ) ^ 7 + (x : ℤ) ^ 5 + 1 := by exact_mod_cast hA_val
      have hB_Z : (B : ℤ) = (x : ℤ) ^ 2 + (x : ℤ) + 1 := by exact_mod_cast hB_eq
      have hC_Z : (C : ℤ) = (x : ℤ) ^ 4 * ((x : ℤ) - 1) + (x : ℤ) * ((x : ℤ) ^ 2 - 1) + 1 := by
        rw [hC_eq]
        push_cast
        have hx_sub : ((x - 1 : ℕ) : ℤ) = (x : ℤ) - 1 := Nat.cast_sub (by omega)
        have hx2_sub : ((x ^ 2 - 1 : ℕ) : ℤ) = (x : ℤ) ^ 2 - 1 := by
          have : 1 ≤ x ^ 2 := by
            have : 1 ≤ x := by omega
            nlinarith
          exact Nat.cast_sub this
        rw [hx_sub, hx2_sub]
      rw [hA_Z, hB_Z, hC_Z]
      ring

    have h_eq : A n = B * C := by exact_mod_cast h_eq_Z

    -- Evaluate factor magnitudes efficiently with generalized bounds
    have hB_gt : 1 < B := by
      rw [hB_eq]
      omega

    have hC_gt : 1 < C := by
      rw [hC_eq]
      have h1 : 0 < x - 1 := by omega
      have h2 : 0 < x ^ 4 := by positivity
      have h3 : 0 < x ^ 4 * (x - 1) := Nat.mul_pos h2 h1
      omega

    -- Complete Prime evaluation by confirming factorization
    have h_div : B ∣ A n := by
      rw [h_eq]
      exact dvd_mul_right B C

    have h_prime_eq := (Nat.dvd_prime h_prime).mp h_div
    rcases h_prime_eq with h_B_eq_1 | h_B_eq_A
    · omega
    · have h_zero : (B : ℤ) * ((C : ℤ) - 1) = 0 := by
        calc (B : ℤ) * ((C : ℤ) - 1) = (B : ℤ) * (C : ℤ) - (B : ℤ) := by ring
          _ = (A n : ℤ) - (B : ℤ) := by rw [← h_eq_Z]
          _ = 0 := by
            have : (A n : ℤ) = (B : ℤ) := by rw [h_B_eq_A]
            omega
      cases mul_eq_zero.mp h_zero with
      | inl h => omega
      | inr h => omega

  · intro hn
    change False at hn
    exact False.elim hn
