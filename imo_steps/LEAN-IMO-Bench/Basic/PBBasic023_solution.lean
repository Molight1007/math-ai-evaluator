import Mathlib

theorem lemma_c1 (a b : ℕ) (ha : 0 < a) (hb : 0 < b) (h : 2 ^ a + 1 = 7 ^ b + 2) : a = 3 ∧ b = 1 :=
by
  have h7 : ∀ n : ℕ, 7 ^ n % 16 = 1 ∨ 7 ^ n % 16 = 7 := by
    intro n
    induction n with
    | zero => left; rfl
    | succ n ih =>
      rcases ih with ih | ih
      · right
        calc 7 ^ (n + 1) % 16 = (7 ^ n * 7) % 16 := by rw [pow_add, pow_one]
        _ = (7 ^ n % 16 * (7 % 16)) % 16 := by rw [Nat.mul_mod]
        _ = (1 * (7 % 16)) % 16 := by rw [ih]
        _ = 7 := by rfl
      · left
        calc 7 ^ (n + 1) % 16 = (7 ^ n * 7) % 16 := by rw [pow_add, pow_one]
        _ = (7 ^ n % 16 * (7 % 16)) % 16 := by rw [Nat.mul_mod]
        _ = (7 * (7 % 16)) % 16 := by rw [ih]
        _ = 1 := by rfl

  have h_a_lt_4 : a < 4 := by
    by_contra! h_ge
    have h_mod16 : (2 ^ a + 1) % 16 = (7 ^ b + 2) % 16 := by rw [h]
    have h_2a : 2 ^ a % 16 = 0 := by
      obtain ⟨k, hk⟩ : ∃ k, a = 4 + k := ⟨a - 4, by omega⟩
      rw [hk, pow_add]
      have H1 : 2 ^ 4 = 16 := by rfl
      rw [H1]
      calc (16 * 2 ^ k) % 16 = (16 % 16 * (2 ^ k % 16)) % 16 := by rw [Nat.mul_mod]
      _ = (0 * (2 ^ k % 16)) % 16 := by rfl
      _ = 0 % 16 := by rw [zero_mul]
      _ = 0 := by rfl
    have h_left : (2 ^ a + 1) % 16 = 1 := by
      calc (2 ^ a + 1) % 16 = (2 ^ a % 16 + 1 % 16) % 16 := by rw [Nat.add_mod]
      _ = (0 + 1 % 16) % 16 := by rw [h_2a]
      _ = 1 := by rfl
    rcases h7 b with hb1 | hb7
    · have h_right : (7 ^ b + 2) % 16 = 3 := by
        calc (7 ^ b + 2) % 16 = (7 ^ b % 16 + 2 % 16) % 16 := by rw [Nat.add_mod]
        _ = (1 + 2 % 16) % 16 := by rw [hb1]
        _ = 3 := by rfl
      rw [h_left, h_right] at h_mod16
      omega
    · have h_right : (7 ^ b + 2) % 16 = 9 := by
        calc (7 ^ b + 2) % 16 = (7 ^ b % 16 + 2 % 16) % 16 := by rw [Nat.add_mod]
        _ = (7 + 2 % 16) % 16 := by rw [hb7]
        _ = 9 := by rfl
      rw [h_left, h_right] at h_mod16
      omega

  have h_a_cases : a = 1 ∨ a = 2 ∨ a = 3 := by omega
  rcases h_a_cases with rfl | rfl | rfl
  · -- a = 1
    obtain ⟨k, hk⟩ : ∃ k, b = k + 1 := ⟨b - 1, by omega⟩
    have h_expand : 7 ^ (k + 1) = 7 ^ k * 7 := by rw [pow_add, pow_one]
    have h2 : 2 ^ 1 + 1 = 3 := by rfl
    rw [hk, h_expand, h2] at h
    omega
  · -- a = 2
    obtain ⟨k, hk⟩ : ∃ k, b = k + 1 := ⟨b - 1, by omega⟩
    have h_expand : 7 ^ (k + 1) = 7 ^ k * 7 := by rw [pow_add, pow_one]
    have h2 : 2 ^ 2 + 1 = 5 := by rfl
    rw [hk, h_expand, h2] at h
    omega
  · -- a = 3
    obtain ⟨k, hk⟩ : ∃ k, b = k + 1 := ⟨b - 1, by omega⟩
    have h_expand : 7 ^ (k + 1) = 7 ^ k * 7 := by rw [pow_add, pow_one]
    have h2 : 2 ^ 3 + 1 = 9 := by rfl
    rw [hk, h_expand, h2] at h
    have hk_val : 7 ^ k = 1 := by omega
    have hk_cases : k = 0 ∨ k > 0 := by omega
    rcases hk_cases with rfl | hk_pos
    · constructor
      · rfl
      · omega
    · obtain ⟨m, hm⟩ : ∃ m, k = m + 1 := ⟨k - 1, by omega⟩
      rw [hm] at hk_val
      have h_expand2 : 7 ^ (m + 1) = 7 ^ m * 7 := by rw [pow_add, pow_one]
      rw [h_expand2] at hk_val
      omega

theorem b_is_even (a b c : ℕ) (ha : 0 < a) (hb : 0 < b) (hc : 1 < c) (h : 2 ^ a + 1 = 7 ^ b + 2 ^ c) : ∃ k, 0 < k ∧ b = 2 * k :=
by
  have h7_pos : ∀ n, 1 ≤ 7 ^ n := by
    intro n; induction n with
    | zero => exact Nat.le_refl 1
    | succ n ih =>
      calc 1 ≤ 7 ^ n := ih
        _ = 7 ^ n * 1 := by rw [mul_one]
        _ ≤ 7 ^ n * 7 := Nat.mul_le_mul_left (7 ^ n) (by decide)
        _ = 7 ^ (n + 1) := by rfl

  have ha2 : 2 ≤ a := by
    by_contra! h_lt
    have ha1 : a = 1 := by omega
    subst ha1
    have h_eval : 2 ^ 1 + 1 = 3 := rfl
    rw [h_eval] at h
    have h7_bound : 7 ≤ 7 ^ b := by
      obtain ⟨b', rfl⟩ : ∃ b', b = b' + 1 := ⟨b - 1, by omega⟩
      calc 7 = 1 * 7 := by rfl
        _ ≤ 7 ^ b' * 7 := Nat.mul_le_mul_right 7 (h7_pos b')
        _ = 7 ^ (b' + 1) := by rfl
    have h_contra : 7 ≤ 3 := by
      calc 7 = 7 + 0 := by rfl
        _ ≤ 7 ^ b + 2 ^ c := Nat.add_le_add h7_bound (Nat.zero_le (2 ^ c))
        _ = 3 := h.symm
    omega

  have h_zmod_eq : (2 : ZMod 4) ^ a + 1 = (7 : ZMod 4) ^ b + (2 : ZMod 4) ^ c := by
    calc (2 : ZMod 4) ^ a + 1 = ((2 ^ a + 1 : ℕ) : ZMod 4) := by push_cast; ring
      _ = ((7 ^ b + 2 ^ c : ℕ) : ZMod 4) := by rw [h]
      _ = (7 : ZMod 4) ^ b + (2 : ZMod 4) ^ c := by push_cast; ring

  have h_mod_a : (2 : ZMod 4) ^ a = 0 := by
    obtain ⟨a', rfl⟩ : ∃ a', a = a' + 2 := ⟨a - 2, by omega⟩
    have h_two_sq : (2 : ZMod 4) ^ 2 = 0 := by decide
    calc (2 : ZMod 4) ^ (a' + 2) = (2 : ZMod 4) ^ a' * (2 : ZMod 4) ^ 2 := by rw [pow_add]
      _ = (2 : ZMod 4) ^ a' * 0 := by rw [h_two_sq]
      _ = 0 := by ring

  have h_mod_c : (2 : ZMod 4) ^ c = 0 := by
    obtain ⟨c', rfl⟩ : ∃ c', c = c' + 2 := ⟨c - 2, by omega⟩
    have h_two_sq : (2 : ZMod 4) ^ 2 = 0 := by decide
    calc (2 : ZMod 4) ^ (c' + 2) = (2 : ZMod 4) ^ c' * (2 : ZMod 4) ^ 2 := by rw [pow_add]
      _ = (2 : ZMod 4) ^ c' * 0 := by rw [h_two_sq]
      _ = 0 := by ring

  have h_zmod2 : (1 : ZMod 4) = (7 : ZMod 4) ^ b := by
    calc (1 : ZMod 4) = (2 : ZMod 4) ^ a + 1 := by rw [h_mod_a, zero_add]
      _ = (7 : ZMod 4) ^ b + (2 : ZMod 4) ^ c := h_zmod_eq
      _ = (7 : ZMod 4) ^ b + 0 := by rw [h_mod_c]
      _ = (7 : ZMod 4) ^ b := by rw [add_zero]

  have h7 : (7 : ZMod 4) = -1 := by decide
  rw [h7] at h_zmod2

  have h_even : b % 2 = 0 := by
    by_contra h_odd
    have hb_mod : b % 2 = 1 := by omega
    obtain ⟨k, hk⟩ : ∃ k, b = 2 * k + 1 := ⟨b / 2, by omega⟩
    have h_pow : (-1 : ZMod 4) ^ b = -1 := by
      calc (-1 : ZMod 4) ^ b = (-1 : ZMod 4) ^ (2 * k + 1) := by rw [hk]
        _ = (-1 : ZMod 4) ^ (2 * k) * (-1 : ZMod 4) ^ 1 := by rw [pow_add]
        _ = ((-1 : ZMod 4) ^ 2) ^ k * (-1 : ZMod 4) ^ 1 := by rw [pow_mul]
        _ = (1 : ZMod 4) ^ k * (-1 : ZMod 4) ^ 1 := by
          have h_sq : (-1 : ZMod 4) ^ 2 = 1 := by decide
          rw [h_sq]
        _ = 1 * (-1) := by rw [one_pow, pow_one]
        _ = -1 := by ring
    rw [h_pow] at h_zmod2
    have h_false : (1 : ZMod 4) ≠ -1 := by decide
    exact h_false h_zmod2

  have h_b_eq : b = 2 * (b / 2) := by omega
  use b / 2
  constructor
  · omega
  · exact h_b_eq

theorem a_is_even (a b c : ℕ) (ha : 0 < a) (hb : 0 < b) (hc : 1 < c) (h : 2 ^ a + 1 = 7 ^ b + 2 ^ c) : ∃ K, 0 < K ∧ a = 2 * K :=
by
  by_cases h_even : a % 2 = 0
  · use a / 2
    constructor
    · omega
    · omega
  · have ha_odd : a % 2 = 1 := by omega

    have pow_mod2 : ∀ {m : ℕ} [NeZero m] (x : ZMod m) (hk : x^2 = 1) (n : ℕ), x^n = x^(n % 2) := by
      intro m _ x hk n
      have eq : n = 2 * (n / 2) + n % 2 := by omega
      calc
        x ^ n = x ^ (2 * (n / 2) + n % 2) := congrArg (fun y => x ^ y) eq
        _ = x ^ (2 * (n / 2)) * x ^ (n % 2) := by rw [pow_add]
        _ = (x ^ 2) ^ (n / 2) * x ^ (n % 2) := by rw [pow_mul]
        _ = 1 ^ (n / 2) * x ^ (n % 2) := by rw [hk]
        _ = 1 * x ^ (n % 2) := by rw [one_pow]
        _ = x ^ (n % 2) := by rw [one_mul]

    have pow_mod3 : ∀ {m : ℕ} [NeZero m] (x : ZMod m) (hk : x^3 = 1) (n : ℕ), x^n = x^(n % 3) := by
      intro m _ x hk n
      have eq : n = 3 * (n / 3) + n % 3 := by omega
      calc
        x ^ n = x ^ (3 * (n / 3) + n % 3) := congrArg (fun y => x ^ y) eq
        _ = x ^ (3 * (n / 3)) * x ^ (n % 3) := by rw [pow_add]
        _ = (x ^ 3) ^ (n / 3) * x ^ (n % 3) := by rw [pow_mul]
        _ = 1 ^ (n / 3) * x ^ (n % 3) := by rw [hk]
        _ = 1 * x ^ (n % 3) := by rw [one_pow]
        _ = x ^ (n % 3) := by rw [one_mul]

    have pow_mod4 : ∀ {m : ℕ} [NeZero m] (x : ZMod m) (hk : x^4 = 1) (n : ℕ), x^n = x^(n % 4) := by
      intro m _ x hk n
      have eq : n = 4 * (n / 4) + n % 4 := by omega
      calc
        x ^ n = x ^ (4 * (n / 4) + n % 4) := congrArg (fun y => x ^ y) eq
        _ = x ^ (4 * (n / 4)) * x ^ (n % 4) := by rw [pow_add]
        _ = (x ^ 4) ^ (n / 4) * x ^ (n % 4) := by rw [pow_mul]
        _ = 1 ^ (n / 4) * x ^ (n % 4) := by rw [hk]
        _ = 1 * x ^ (n % 4) := by rw [one_pow]
        _ = x ^ (n % 4) := by rw [one_mul]

    have pow_mod12 : ∀ {m : ℕ} [NeZero m] (x : ZMod m) (hk : x^12 = 1) (n : ℕ), x^n = x^(n % 12) := by
      intro m _ x hk n
      have eq : n = 12 * (n / 12) + n % 12 := by omega
      calc
        x ^ n = x ^ (12 * (n / 12) + n % 12) := congrArg (fun y => x ^ y) eq
        _ = x ^ (12 * (n / 12)) * x ^ (n % 12) := by rw [pow_add]
        _ = (x ^ 12) ^ (n / 12) * x ^ (n % 12) := by rw [pow_mul]
        _ = 1 ^ (n / 12) * x ^ (n % 12) := by rw [hk]
        _ = 1 * x ^ (n % 12) := by rw [one_pow]
        _ = x ^ (n % 12) := by rw [one_mul]

    have H_mod (m : ℕ) [NeZero m] : (2 : ZMod m)^a + 1 = (7 : ZMod m)^b + (2 : ZMod m)^c := by
      have h_cast : ((2^a + 1 : ℕ) : ZMod m) = ((7^b + 2^c : ℕ) : ZMod m) := by rw [h]
      push_cast at h_cast
      exact h_cast

    -- Modulo 3
    have h2_3 : (2 : ZMod 3)^2 = 1 := by decide
    have h7_3 : (7 : ZMod 3) = 1 := by decide
    have H7_3_b : (7 : ZMod 3)^b = 1 := by
      calc (7 : ZMod 3)^b = (1 : ZMod 3)^b := by rw [h7_3]
           _ = 1 := by rw [one_pow]

    have hc_mod2 : c % 2 = 1 := by
      have h_c_cases : c % 2 = 0 ∨ c % 2 = 1 := by omega
      rcases h_c_cases with hc_0 | hc_1
      · exfalso
        have h_eq := H_mod 3
        rw [pow_mod2 (2 : ZMod 3) h2_3 a, ha_odd, pow_mod2 (2 : ZMod 3) h2_3 c, hc_0, H7_3_b] at h_eq
        revert h_eq; decide
      · exact hc_1

    -- Modulo 4
    have ha2 : a ≥ 2 := by
      have h_a_cases : a = 1 ∨ a ≥ 2 := by omega
      rcases h_a_cases with rfl | ha_2
      · exfalso
        have h_b : 7^b ≥ 7 := by
          obtain ⟨b', rfl⟩ : ∃ b', b = b' + 1 := ⟨b - 1, by omega⟩
          have hX : 7 ^ b' > 0 := by positivity
          have h_eq : 7 ^ (b' + 1) = 7 ^ b' * 7 := by rw [pow_add, pow_one]
          omega
        have h_c : 2^c ≥ 4 := by
          obtain ⟨c', rfl⟩ : ∃ c', c = c' + 2 := ⟨c - 2, by omega⟩
          have hX : 2 ^ c' > 0 := by positivity
          have h_eq : 2 ^ (c' + 2) = 2 ^ c' * 4 := by
            calc 2 ^ (c' + 2) = 2 ^ c' * 2 ^ 2 := by rw [pow_add]
                 _ = 2 ^ c' * 4 := by rfl
          omega
        have : 2^1 + 1 = 3 := by rfl
        omega
      · exact ha_2

    have H2_4_a : (2 : ZMod 4)^a = 0 := by
      obtain ⟨a', rfl⟩ : ∃ a', a = a' + 2 := ⟨a - 2, by omega⟩
      rw [pow_add]
      have : (2 : ZMod 4)^2 = 0 := by decide
      rw [this, mul_zero]

    have H2_4_c : (2 : ZMod 4)^c = 0 := by
      obtain ⟨c', rfl⟩ : ∃ c', c = c' + 2 := ⟨c - 2, by omega⟩
      rw [pow_add]
      have : (2 : ZMod 4)^2 = 0 := by decide
      rw [this, mul_zero]

    have h_mod4 := H_mod 4
    rw [H2_4_a, H2_4_c] at h_mod4
    have h7_4 : (7 : ZMod 4) = (3 : ZMod 4) := by decide
    have h3_4 : (3 : ZMod 4)^2 = 1 := by decide
    have hb_mod4_even : b % 2 = 0 := by
      have hb_cases : b % 2 = 0 ∨ b % 2 = 1 := by omega
      rcases hb_cases with hb_0 | hb_1
      · exact hb_0
      · exfalso
        have h_eq := h_mod4
        rw [h7_4, pow_mod2 (3 : ZMod 4) h3_4 b, hb_1] at h_eq
        revert h_eq; decide

    -- Modulo 5
    have h2_5 : (2 : ZMod 5)^4 = 1 := by decide
    have h7_5 : (7 : ZMod 5) = (2 : ZMod 5) := by decide
    have hb_mod4 : b % 4 = 0 := by
      have hb4_cases : b % 4 = 0 ∨ b % 4 = 2 := by
        have : b % 2 = 0 := hb_mod4_even
        omega
      rcases hb4_cases with hb_0 | hb_2
      · exact hb_0
      · exfalso
        have ha4_cases : a % 4 = 1 ∨ a % 4 = 3 := by
          have : a % 2 = 1 := ha_odd
          omega
        have hc4_cases : c % 4 = 1 ∨ c % 4 = 3 := by
          have : c % 2 = 1 := hc_mod2
          omega
        rcases ha4_cases with ha4 | ha4 <;> rcases hc4_cases with hc4 | hc4
        all_goals
          have h_eq := H_mod 5
          rw [h7_5, pow_mod4 (2 : ZMod 5) h2_5 a, ha4, pow_mod4 (2 : ZMod 5) h2_5 c, hc4, pow_mod4 (2 : ZMod 5) h2_5 b, hb_2] at h_eq
          revert h_eq
          decide

    -- Modulo 7
    have h2_7 : (2 : ZMod 7)^3 = 1 := by decide
    have h7_7 : (7 : ZMod 7) = 0 := by decide
    have H7_7_b : (7 : ZMod 7)^b = 0 := by
      obtain ⟨b', rfl⟩ : ∃ b', b = b' + 1 := ⟨b - 1, by omega⟩
      rw [pow_add, pow_one, h7_7, mul_zero]

    have ha3_cases : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega
    have hc3_cases : c % 3 = 0 ∨ c % 3 = 1 ∨ c % 3 = 2 := by omega
    have h_a3_c3 : a % 3 = 0 ∧ c % 3 = 1 := by
      rcases ha3_cases with ha_0 | ha_1 | ha_2
      · rcases hc3_cases with hc_0 | hc_1 | hc_2
        · exfalso; have h_eq := H_mod 7; rw [pow_mod3 (2 : ZMod 7) h2_7 a, ha_0, pow_mod3 (2 : ZMod 7) h2_7 c, hc_0, H7_7_b] at h_eq; revert h_eq; decide
        · exact ⟨ha_0, hc_1⟩
        · exfalso; have h_eq := H_mod 7; rw [pow_mod3 (2 : ZMod 7) h2_7 a, ha_0, pow_mod3 (2 : ZMod 7) h2_7 c, hc_2, H7_7_b] at h_eq; revert h_eq; decide
      · rcases hc3_cases with hc_0 | hc_1 | hc_2
        · exfalso; have h_eq := H_mod 7; rw [pow_mod3 (2 : ZMod 7) h2_7 a, ha_1, pow_mod3 (2 : ZMod 7) h2_7 c, hc_0, H7_7_b] at h_eq; revert h_eq; decide
        · exfalso; have h_eq := H_mod 7; rw [pow_mod3 (2 : ZMod 7) h2_7 a, ha_1, pow_mod3 (2 : ZMod 7) h2_7 c, hc_1, H7_7_b] at h_eq; revert h_eq; decide
        · exfalso; have h_eq := H_mod 7; rw [pow_mod3 (2 : ZMod 7) h2_7 a, ha_1, pow_mod3 (2 : ZMod 7) h2_7 c, hc_2, H7_7_b] at h_eq; revert h_eq; decide
      · rcases hc3_cases with hc_0 | hc_1 | hc_2
        · exfalso; have h_eq := H_mod 7; rw [pow_mod3 (2 : ZMod 7) h2_7 a, ha_2, pow_mod3 (2 : ZMod 7) h2_7 c, hc_0, H7_7_b] at h_eq; revert h_eq; decide
        · exfalso; have h_eq := H_mod 7; rw [pow_mod3 (2 : ZMod 7) h2_7 a, ha_2, pow_mod3 (2 : ZMod 7) h2_7 c, hc_1, H7_7_b] at h_eq; revert h_eq; decide
        · exfalso; have h_eq := H_mod 7; rw [pow_mod3 (2 : ZMod 7) h2_7 a, ha_2, pow_mod3 (2 : ZMod 7) h2_7 c, hc_2, H7_7_b] at h_eq; revert h_eq; decide

    -- Modulo 13 Contradiction
    have h2_13 : (2 : ZMod 13)^12 = 1 := by decide
    have h7_13 : (7 : ZMod 13)^12 = 1 := by decide
    have ha_mod12 : a % 12 = 3 ∨ a % 12 = 9 := by
      have h1 : a % 2 = 1 := ha_odd
      have h2 : a % 3 = 0 := h_a3_c3.1
      omega
    have hb_mod12 : b % 12 = 0 ∨ b % 12 = 4 ∨ b % 12 = 8 := by
      have h1 : b % 4 = 0 := hb_mod4
      omega
    have hc_mod12 : c % 12 = 1 ∨ c % 12 = 7 := by
      have h1 : c % 2 = 1 := hc_mod2
      have h2 : c % 3 = 1 := h_a3_c3.2
      omega

    have H_contra : False := by
      rcases ha_mod12 with ha12 | ha12 <;>
      rcases hb_mod12 with hb12 | hb12 | hb12 <;>
      rcases hc_mod12 with hc12 | hc12
      all_goals
        have h_eq := H_mod 13
        rw [pow_mod12 (2 : ZMod 13) h2_13 a, ha12, pow_mod12 (7 : ZMod 13) h7_13 b, hb12, pow_mod12 (2 : ZMod 13) h2_13 c, hc12] at h_eq
        revert h_eq
        decide

    exact False.elim H_contra

theorem lem4_aux (K B c : ℕ) (hK : 0 < K) (hB : 0 < B) (hc : 0 < c)
  (h : 2 ^ (2 * K) + 1 = 7 ^ (2 * B) + 2 ^ c) :
  (2:ℤ) ^ c ∣ ((7:ℤ) ^ B - 1) * ((7:ℤ) ^ B + 1) :=
by
  have hc_le : c ≤ 2 * K := by
    by_contra! hcontra
    have h_eq : (2:ℤ) ^ c = (2:ℤ) ^ (2 * K + (c - 2 * K - 1) + 1) := congrArg (fun x => (2:ℤ) ^ x) (by omega)
    have h_z_local : (2:ℤ) ^ (2 * K) + 1 = (7:ℤ) ^ (2 * B) + (2:ℤ) ^ c := by exact_mod_cast h
    have h2 : (2:ℤ) ^ c = (2:ℤ) ^ (2 * K) * (2:ℤ) ^ (c - 2 * K - 1) * 2 := by
      calc (2:ℤ) ^ c = (2:ℤ) ^ (2 * K + (c - 2 * K - 1) + 1) := h_eq
        _ = (2:ℤ) ^ (2 * K + (c - 2 * K - 1)) * (2:ℤ) ^ 1 := by rw [pow_add]
        _ = (2:ℤ) ^ (2 * K) * (2:ℤ) ^ (c - 2 * K - 1) * (2:ℤ) ^ 1 := by rw [pow_add]
        _ = (2:ℤ) ^ (2 * K) * (2:ℤ) ^ (c - 2 * K - 1) * 2 := by rw [pow_one]
    have h3 : (2:ℤ) ^ c = (2:ℤ) ^ (2 * K) * (2:ℤ) ^ (c - 2 * K - 1) + (2:ℤ) ^ (2 * K) * (2:ℤ) ^ (c - 2 * K - 1) := by
      calc (2:ℤ) ^ c = (2:ℤ) ^ (2 * K) * (2:ℤ) ^ (c - 2 * K - 1) * 2 := h2
        _ = (2:ℤ) ^ (2 * K) * (2:ℤ) ^ (c - 2 * K - 1) + (2:ℤ) ^ (2 * K) * (2:ℤ) ^ (c - 2 * K - 1) := by ring
    have h_pos_strict : 0 < (2:ℤ) ^ (c - 2 * K - 1) := by positivity
    have h_pos : 1 ≤ (2:ℤ) ^ (c - 2 * K - 1) := by omega
    have h5_strict : 0 < (7:ℤ) ^ (2 * B) := by positivity
    have h5 : 1 ≤ (7:ℤ) ^ (2 * B) := by omega
    have h6_strict : 0 < (2:ℤ) ^ (2 * K) := by positivity
    have h6 : 1 ≤ (2:ℤ) ^ (2 * K) := by omega
    have h7 : 0 ≤ (2:ℤ) ^ (2 * K) := by omega
    nlinarith

  have h_z : (2:ℤ) ^ (2 * K) + 1 = (7:ℤ) ^ (2 * B) + (2:ℤ) ^ c := by exact_mod_cast h

  have h_diff_sq : ((7:ℤ) ^ B - 1) * ((7:ℤ) ^ B + 1) = (7:ℤ) ^ (2 * B) - 1 := by
    have h_2B : (7:ℤ) ^ (2 * B) = (7:ℤ) ^ (B + B) := congrArg (fun x => (7:ℤ) ^ x) (by omega)
    rw [h_2B, pow_add]
    ring

  have h_target_eq : ((7:ℤ) ^ B - 1) * ((7:ℤ) ^ B + 1) = (2:ℤ) ^ (2 * K) - (2:ℤ) ^ c := by
    rw [h_diff_sq]
    linarith

  have h_div1 : (2:ℤ) ^ c ∣ (2:ℤ) ^ (2 * K) := by
    have h_2k_eq : (2:ℤ) ^ (2 * K) = (2:ℤ) ^ (c + (2 * K - c)) := congrArg (fun x => (2:ℤ) ^ x) (by omega)
    rw [h_2k_eq, pow_add]
    exact ⟨(2:ℤ) ^ (2 * K - c), rfl⟩

  have h_div_self : (2:ℤ) ^ c ∣ (2:ℤ) ^ c := ⟨1, by ring⟩

  have h_div2 : (2:ℤ) ^ c ∣ (2:ℤ) ^ (2 * K) - (2:ℤ) ^ c := dvd_sub h_div1 h_div_self

  rw [h_target_eq]
  exact h_div2

theorem lem3_aux (B c : ℕ) (hB : 0 < B) (hc : 0 < c)
  (hdiv : (2:ℤ) ^ c ∣ ((7:ℤ) ^ B - 1) * ((7:ℤ) ^ B + 1)) :
  (2:ℤ) ^ c ∣ (2:ℤ) * ((7:ℤ) ^ B - 1) ∨ (2:ℤ) ^ c ∣ (2:ℤ) * ((7:ℤ) ^ B + 1) :=
by
  have h2X : (2:ℤ) ∣ (7:ℤ)^B - 1 := by
    have h1 : (7:ℤ) - (1:ℤ) ∣ (7:ℤ)^B - (1:ℤ)^B := sub_dvd_pow_sub_pow (7:ℤ) (1:ℤ) B
    rw [one_pow] at h1
    have h2 : (2:ℤ) ∣ (7:ℤ) - (1:ℤ) := by norm_num
    exact dvd_trans h2 h1

  obtain ⟨x, hx⟩ := h2X
  have hY : (7:ℤ)^B + 1 = (2:ℤ) * (x + 1) := by
    calc (7:ℤ)^B + 1 = ((7:ℤ)^B - 1) + 2 := by ring
      _ = (2:ℤ) * x + 2 := by rw [hx]
      _ = (2:ℤ) * (x + 1) := by ring

  have h_eq1 : ((7:ℤ)^B - 1) * ((7:ℤ)^B + 1) = (4:ℤ) * x * (x + 1) := by
    calc ((7:ℤ)^B - 1) * ((7:ℤ)^B + 1) = ((2:ℤ) * x) * ((2:ℤ) * (x + 1)) := by rw [hx, hY]
      _ = (4:ℤ) * x * (x + 1) := by ring

  have h_mod : x % (2:ℤ) = 0 ∨ x % (2:ℤ) = 1 := by omega

  rcases h_mod with h0 | h1
  · left
    obtain ⟨k, hk⟩ : ∃ k : ℤ, x = (2:ℤ) * k := ⟨x / (2:ℤ), by omega⟩

    have h_coprime : IsCoprime (2:ℤ) (x + 1) := by
      use -k, 1
      calc (-k) * (2:ℤ) + 1 * (x + 1) = (-k) * (2:ℤ) + 1 * ((2:ℤ) * k + 1) := by rw [hk]
        _ = 1 := by ring

    have h_coprime_c : IsCoprime ((2:ℤ)^c) (x + 1) := h_coprime.pow_left
    obtain ⟨u, v, huv⟩ := h_coprime_c

    have h_target_eq : (2:ℤ) * ((7:ℤ)^B - 1) = (4:ℤ) * x := by
      calc (2:ℤ) * ((7:ℤ)^B - 1) = (2:ℤ) * ((2:ℤ) * x) := by rw [hx]
        _ = (4:ℤ) * x := by ring
    rw [h_target_eq]

    have hdiv' : (2:ℤ)^c ∣ (4:ℤ) * x * (x + 1) := by
      rw [←h_eq1]
      exact hdiv

    obtain ⟨w, hw⟩ := hdiv'

    use u * (4:ℤ) * x + v * w
    calc (4:ℤ) * x = (4:ℤ) * x * 1 := by ring
      _ = (4:ℤ) * x * (u * (2:ℤ)^c + v * (x + 1)) := by rw [huv]
      _ = u * (4:ℤ) * x * (2:ℤ)^c + v * ((4:ℤ) * x * (x + 1)) := by ring
      _ = u * (4:ℤ) * x * (2:ℤ)^c + v * ((2:ℤ)^c * w) := by rw [hw]
      _ = (2:ℤ)^c * (u * (4:ℤ) * x + v * w) := by ring

  · right
    obtain ⟨k, hk⟩ : ∃ k : ℤ, x = (2:ℤ) * k + 1 := ⟨x / (2:ℤ), by omega⟩

    have h_coprime : IsCoprime (2:ℤ) x := by
      use -k, 1
      calc (-k) * (2:ℤ) + 1 * x = (-k) * (2:ℤ) + 1 * ((2:ℤ) * k + 1) := by rw [hk]
        _ = 1 := by ring

    have h_coprime_c : IsCoprime ((2:ℤ)^c) x := h_coprime.pow_left
    obtain ⟨u, v, huv⟩ := h_coprime_c

    have h_target_eq : (2:ℤ) * ((7:ℤ)^B + 1) = (4:ℤ) * (x + 1) := by
      calc (2:ℤ) * ((7:ℤ)^B + 1) = (2:ℤ) * ((2:ℤ) * (x + 1)) := by rw [hY]
        _ = (4:ℤ) * (x + 1) := by ring
    rw [h_target_eq]

    have hdiv' : (2:ℤ)^c ∣ x * ((4:ℤ) * (x + 1)) := by
      have h_comm : x * ((4:ℤ) * (x + 1)) = (4:ℤ) * x * (x + 1) := by ring
      rw [h_comm, ←h_eq1]
      exact hdiv

    obtain ⟨w, hw⟩ := hdiv'

    use u * (4:ℤ) * (x + 1) + v * w
    calc (4:ℤ) * (x + 1) = (4:ℤ) * (x + 1) * 1 := by ring
      _ = (4:ℤ) * (x + 1) * (u * (2:ℤ)^c + v * x) := by rw [huv]
      _ = u * (4:ℤ) * (x + 1) * (2:ℤ)^c + v * (x * ((4:ℤ) * (x + 1))) := by ring
      _ = u * (4:ℤ) * (x + 1) * (2:ℤ)^c + v * ((2:ℤ)^c * w) := by rw [hw]
      _ = (2:ℤ)^c * (u * (4:ℤ) * (x + 1) + v * w) := by ring

theorem lem2_aux (K B c : ℕ) (hK : 0 < K) (hB : 0 < B) (hc : 0 < c)
  (h : 2 ^ (2 * K) + 1 = 7 ^ (2 * B) + 2 ^ c) :
  (2:ℤ) ^ c ≥ (2:ℤ) * ((7:ℤ) ^ B + 1) :=
by
  -- Cast the main equation to the integers
  have hZ : (2:ℤ)^(2 * K) + 1 = (7:ℤ)^(2 * B) + (2:ℤ)^c := by exact_mod_cast h

  -- Use exponent laws to express terms as squares
  have H1 : (2:ℤ)^(2 * K) = ((2:ℤ)^K)^2 := by
    rw [mul_comm 2 K, pow_mul]
  have H2 : (7:ℤ)^(2 * B) = ((7:ℤ)^B)^2 := by
    rw [mul_comm 2 B, pow_mul]

  rw [H1, H2] at hZ

  -- Rearrange the integer equation to apply the difference of squares
  have h_diff : ((2:ℤ)^K)^2 - ((7:ℤ)^B)^2 = (2:ℤ)^c - 1 := by linarith [hZ]
  have h_sq : ((2:ℤ)^K)^2 - ((7:ℤ)^B)^2 = ((2:ℤ)^K - (7:ℤ)^B) * ((2:ℤ)^K + (7:ℤ)^B) := by ring
  have h_prod : ((2:ℤ)^K - (7:ℤ)^B) * ((2:ℤ)^K + (7:ℤ)^B) = (2:ℤ)^c - 1 := by linarith [h_diff, h_sq]

  -- Since c > 0, extract its minimum bound
  obtain ⟨c', hc'⟩ : ∃ c', c = c' + 1 := ⟨c - 1, by omega⟩
  have h_c_pos : (2:ℤ)^c ≥ 2 := by
    rw [hc', pow_add, pow_one]
    have h_pos : 0 < (2:ℤ)^c' := by positivity
    have h_ge_1 : (2:ℤ)^c' ≥ 1 := by omega
    nlinarith

  -- Prove the positivity of our core integer bases
  have H_sum_pos : (2:ℤ)^K + (7:ℤ)^B > 0 := by
    have : 0 < (2:ℤ)^K := by positivity
    have : 0 < (7:ℤ)^B := by positivity
    linarith

  have H_diff_pos : (2:ℤ)^K - (7:ℤ)^B > 0 := by
    by_contra! h_contra
    have : ((2:ℤ)^K - (7:ℤ)^B) * ((2:ℤ)^K + (7:ℤ)^B) ≤ 0 := by nlinarith [h_contra, H_sum_pos]
    linarith

  -- Since it's strictly positive, an integer difference is at least 1
  have H_diff_ge_1 : (2:ℤ)^K - (7:ℤ)^B ≥ 1 := by omega

  -- Establish bounds on factors
  have H_mul_1 : (2:ℤ)^K - (7:ℤ)^B - 1 ≥ 0 := by linarith
  have H_mul_2 : (2:ℤ)^K + (7:ℤ)^B ≥ 0 := by linarith
  have H_mul : ((2:ℤ)^K - (7:ℤ)^B - 1) * ((2:ℤ)^K + (7:ℤ)^B) ≥ 0 := by nlinarith [H_mul_1, H_mul_2]

  -- Form the core lower-bound relationship via expansion
  have H_bound : (2:ℤ)^c - 1 ≥ (2:ℤ)^K + (7:ℤ)^B := by
    calc (2:ℤ)^c - 1 = ((2:ℤ)^K - (7:ℤ)^B) * ((2:ℤ)^K + (7:ℤ)^B) := h_prod.symm
      _ = ((2:ℤ)^K - (7:ℤ)^B - 1) * ((2:ℤ)^K + (7:ℤ)^B) + ((2:ℤ)^K + (7:ℤ)^B) := by ring
      _ ≥ 0 + ((2:ℤ)^K + (7:ℤ)^B) := by linarith [H_mul]
      _ = (2:ℤ)^K + (7:ℤ)^B := by ring

  -- Finally, substitute our knowledge to finish the inequality
  linarith

theorem lem5_case1_false (B c : ℕ) (hB : 0 < B) (hc : 0 < c)
  (h_dvd : (2:ℤ) ^ c ∣ (2:ℤ) * ((7:ℤ) ^ B - 1))
  (h_ge : (2:ℤ) ^ c ≥ (2:ℤ) * ((7:ℤ) ^ B + 1)) : False :=
by
  -- Since B > 0, we can write B = B' + 1 for some natural number B'.
  obtain ⟨B', hB_eq⟩ : ∃ b, B = b + 1 := ⟨B - 1, by omega⟩
  subst hB_eq

  -- The term (7:ℤ) ^ B' is strictly positive.
  have hp : 0 < (7:ℤ) ^ B' := by positivity
  have h1 : 1 ≤ (7:ℤ) ^ B' := by omega

  -- Expand (7:ℤ) ^ (B' + 1) into (7:ℤ) ^ B' * 7
  have h_pow : (7:ℤ) ^ (B' + 1) = (7:ℤ) ^ B' * 7 := by rw [pow_add, pow_one]
  rw [h_pow] at h_dvd h_ge

  -- Deduce that 2 * (7^B - 1) is strictly positive, hence non-zero.
  have h_pos : 0 < (2:ℤ) * ((7:ℤ) ^ B' * 7 - 1) := by omega
  have h_ne : (2:ℤ) * ((7:ℤ) ^ B' * 7 - 1) ≠ 0 := by omega

  -- Apply the helper theorem: a ∣ b with b ≠ 0 implies a ≤ |b|.
  have h_le_abs := Int.le_abs_of_dvd h_ne h_dvd

  -- Since 2 * (7^B - 1) is strictly positive, its absolute value is itself.
  -- We utilize `omega` to handle the non-negativity proof trivially.
  have h_abs : |(2:ℤ) * ((7:ℤ) ^ B' * 7 - 1)| = (2:ℤ) * ((7:ℤ) ^ B' * 7 - 1) := abs_of_nonneg (by omega)
  rw [h_abs] at h_le_abs

  -- Now we have (2:ℤ)^c ≤ 2 * (7^B - 1) from the divisibility,
  -- and (2:ℤ)^c ≥ 2 * (7^B + 1) from our assumption.
  -- This creates an immediate contradiction.
  omega

theorem lem5_case2_eq (B c : ℕ) (hB : 0 < B) (hc : 0 < c)
  (h_dvd : (2:ℤ) ^ c ∣ (2:ℤ) * ((7:ℤ) ^ B + 1))
  (h_ge : (2:ℤ) ^ c ≥ (2:ℤ) * ((7:ℤ) ^ B + 1)) : (2:ℤ) ^ c = (2:ℤ) * ((7:ℤ) ^ B + 1) :=
by
  have hy : 0 < (2:ℤ) * ((7:ℤ) ^ B + 1) := by positivity
  have hy_ne : (2:ℤ) * ((7:ℤ) ^ B + 1) ≠ 0 := ne_of_gt hy
  have h_abs : (2:ℤ) ^ c ≤ |(2:ℤ) * ((7:ℤ) ^ B + 1)| := Int.le_abs_of_dvd hy_ne h_dvd
  rw [abs_of_pos hy] at h_abs
  omega

theorem lem5 (K B c : ℕ) (hK : 0 < K) (hB : 0 < B) (hc : 0 < c)
  (h : 2 ^ (2 * K) + 1 = 7 ^ (2 * B) + 2 ^ c) :
  (2:ℤ) ^ c = (2:ℤ) * ((7:ℤ) ^ B + 1) :=
by
  have h4 := lem4_aux K B c hK hB hc h
  have h3 := lem3_aux B c hB hc h4
  have h2 := lem2_aux K B c hK hB hc h
  rcases h3 with h3_left | h3_right
  · exact False.elim (lem5_case1_false B c hB hc h3_left h2)
  · exact lem5_case2_eq B c hB hc h3_right h2

theorem lem8 (K B c : ℕ) (hK : 0 < K) (hB : 0 < B) (hc : 0 < c)
  (h : 2 ^ (2 * K) + 1 = 7 ^ (2 * B) + 2 ^ c) :
  c = 4 :=
by
  have lem5 : ∀ n : ℕ, ∃ k : ℤ, (49:ℤ)^(2 * n + 1) - 1 = 48 * k ∧ (∃ m : ℤ, k = 2 * m + 1) := by
    intro n
    induction n with
    | zero =>
      use 1
      constructor
      · norm_num
      · use 0; norm_num
    | succ n ih =>
      rcases ih with ⟨k, hk1, m, hk2⟩
      use 2401 * k + 50
      constructor
      · have step1 : 2 * (n + 1) + 1 = 2 * n + 1 + 2 := by omega
        calc (49:ℤ)^(2 * (n + 1) + 1) - 1
          _ = (49:ℤ)^(2 * n + 1 + 2) - 1 := by rw [step1]
          _ = (49:ℤ)^(2 * n + 1) * (49:ℤ)^2 - 1 := by rw [pow_add]
          _ = (49:ℤ)^(2 * n + 1) * 2401 - 1 := by norm_num
          _ = 2401 * ((49:ℤ)^(2 * n + 1) - 1) + 2400 := by ring
          _ = 2401 * (48 * k) + 2400 := by rw [hk1]
          _ = 48 * (2401 * k + 50) := by ring
      · use 2401 * m + 1225
        calc 2401 * k + 50
          _ = 2401 * (2 * m + 1) + 50 := by rw [hk2]
          _ = 2 * (2401 * m + 1225) + 1 := by ring

  have lem6 : ∀ b : ℕ, 0 < b → ∃ v : ℕ, ∃ k : ℤ, (∃ m : ℤ, k = 2 * m + 1) ∧ (49:ℤ)^b - 1 = (2:ℤ)^(v+4) * k ∧ 2^v ≤ b := by
    intro b
    induction b using Nat.strong_induction_on with
    | h b ih =>
      intro hb
      have h_mod : b % 2 = 0 ∨ b % 2 = 1 := by omega
      have h_cases : (∃ b', b = 2 * b') ∨ (∃ n, b = 2 * n + 1) := by
        rcases h_mod with h0 | h1
        · left; use b / 2; omega
        · right; use b / 2; omega
      rcases h_cases with ⟨b', hb'⟩ | ⟨n, hn⟩
      · have hb'0 : 0 < b' := by omega
        have hb'lt : b' < b := by omega
        rcases ih b' hb'lt hb'0 with ⟨v', k', ⟨m', hk'odd⟩, hk'eq, hk'le⟩
        use v' + 1
        use k' * ((2:ℤ)^(v'+3) * k' + 1)
        constructor
        · use m' * (2 * (2:ℤ)^(v'+2)) * k' + m' + (2:ℤ)^(v'+2) * k'
          have h2 : (2:ℤ)^(v'+3) = 2 * (2:ℤ)^(v'+2) := by
            have step1 : v' + 3 = v' + 2 + 1 := by omega
            calc (2:ℤ)^(v'+3) = (2:ℤ)^(v'+2+1) := by rw [step1]
              _ = (2:ℤ)^(v'+2) * (2:ℤ)^1 := by rw [pow_add]
              _ = (2:ℤ)^(v'+2) * 2 := by rw [pow_one]
              _ = 2 * (2:ℤ)^(v'+2) := by ring
          calc k' * ((2:ℤ)^(v'+3) * k' + 1)
            _ = (2 * m' + 1) * ((2:ℤ)^(v'+3) * k' + 1) := by nth_rw 1 [hk'odd]
            _ = 2 * m' * (2:ℤ)^(v'+3) * k' + 2 * m' + (2:ℤ)^(v'+3) * k' + 1 := by ring
            _ = 2 * m' * (2:ℤ)^(v'+3) * k' + 2 * m' + (2 * (2:ℤ)^(v'+2)) * k' + 1 := by
              have : (2:ℤ)^(v'+3) * k' = (2 * (2:ℤ)^(v'+2)) * k' := by rw [h2]
              rw [this]
            _ = 2 * (m' * (2 * (2:ℤ)^(v'+2)) * k' + m' + (2:ℤ)^(v'+2) * k') + 1 := by ring
        · constructor
          · have hB_eq : (49:ℤ)^b - 1 = ((49:ℤ)^b' - 1) * (((49:ℤ)^b' - 1) + 2) := by
              calc (49:ℤ)^b - 1
                _ = (49:ℤ)^(2 * b') - 1 := by rw [hb']
                _ = (49:ℤ)^(b' * 2) - 1 := by
                  have step1 : 2 * b' = b' * 2 := by omega
                  rw [step1]
                _ = ((49:ℤ)^b')^2 - 1 := by rw [pow_mul]
                _ = ((49:ℤ)^b' - 1) * (((49:ℤ)^b' - 1) + 2) := by ring
            have h3 : (2:ℤ)^(v'+4) = 2 * (2:ℤ)^(v'+3) := by
              have step1 : v' + 4 = v' + 3 + 1 := by omega
              calc (2:ℤ)^(v'+4) = (2:ℤ)^(v'+3+1) := by rw [step1]
                _ = (2:ℤ)^(v'+3) * (2:ℤ)^1 := by rw [pow_add]
                _ = (2:ℤ)^(v'+3) * 2 := by rw [pow_one]
                _ = 2 * (2:ℤ)^(v'+3) := by ring
            calc (49:ℤ)^b - 1
              _ = ((49:ℤ)^b' - 1) * (((49:ℤ)^b' - 1) + 2) := hB_eq
              _ = ((2:ℤ)^(v'+4) * k') * (((2:ℤ)^(v'+4) * k') + 2) := by rw [hk'eq]
              _ = ((2:ℤ)^(v'+4) * k') * (2 * (2:ℤ)^(v'+3) * k' + 2) := by
                have : ((2:ℤ)^(v'+4) * k' + 2) = (2 * (2:ℤ)^(v'+3) * k' + 2) := by rw [h3]
                rw [this]
              _ = ((2:ℤ)^(v'+4) * 2) * (k' * ((2:ℤ)^(v'+3) * k' + 1)) := by ring
              _ = (2:ℤ)^(v'+4+1) * (k' * ((2:ℤ)^(v'+3) * k' + 1)) := by
                have hp : (2:ℤ)^(v'+4) * 2 = (2:ℤ)^(v'+4+1) := by
                  calc (2:ℤ)^(v'+4) * 2 = (2:ℤ)^(v'+4) * (2:ℤ)^1 := by rw [pow_one]
                    _ = (2:ℤ)^(v'+4+1) := by rw [←pow_add]
                rw [hp]
              _ = (2:ℤ)^(v'+1+4) * (k' * ((2:ℤ)^(v'+3) * k' + 1)) := by
                have step1 : v' + 4 + 1 = v' + 1 + 4 := by omega
                rw [step1]
          · calc 2^(v'+1)
              _ = 2^v' * 2^1 := by rw [pow_add]
              _ = 2^v' * 2 := by rw [pow_one]
              _ ≤ b' * 2 := Nat.mul_le_mul_right 2 hk'le
              _ = 2 * b' := by ring
              _ = b := by omega
      · use 0
        rcases lem5 n with ⟨k, hk_eq, ⟨m, hk_odd⟩⟩
        use 3 * k
        constructor
        · use 3 * m + 1
          calc 3 * k = 3 * (2 * m + 1) := by rw [hk_odd]
            _ = 2 * (3 * m + 1) + 1 := by ring
        · constructor
          · calc (49:ℤ)^b - 1
              _ = (49:ℤ)^(2 * n + 1) - 1 := by rw [hn]
              _ = 48 * k := hk_eq
              _ = 16 * (3 * k) := by ring
              _ = (2:ℤ)^4 * (3 * k) := by norm_num
              _ = (2:ℤ)^(0+4) * (3 * k) := rfl
          · have : 2^0 = 1 := rfl
            omega

  rcases lem6 B hB with ⟨v, k, hk_odd, hk_eq, hk_le⟩
  have h_orig : (2:ℤ)^(2*K) + 1 = (7:ℤ)^(2*B) + (2:ℤ)^c := by exact_mod_cast h

  have h_2K_ge_c : 2 * K ≥ c := by
    have h_pow : (49:ℤ) ≤ (7:ℤ)^(2*B) := by
      have step : (7:ℤ)^(2 + (2 * B - 2)) = (7:ℤ)^(2 * B) := by congr 1; omega
      calc (49:ℤ) = (7:ℤ)^2 * 1 := by norm_num
        _ ≤ (7:ℤ)^2 * (7:ℤ)^(2 * B - 2) := by
          have h_pos : (0 : ℤ) < (7:ℤ)^(2 * B - 2) := by positivity
          have h_pos_le : (1 : ℤ) ≤ (7:ℤ)^(2 * B - 2) := by omega
          apply mul_le_mul_of_nonneg_left h_pos_le (by norm_num)
        _ = (7:ℤ)^(2 + (2 * B - 2)) := by rw [←pow_add]
        _ = (7:ℤ)^(2 * B) := step
    by_contra h_not
    have h_le : 2 * K ≤ c := by omega
    have h_pow_le : (2:ℤ)^(2*K) ≤ (2:ℤ)^c := by
      have h_pos : (0:ℤ) < (2:ℤ)^(c - 2*K) := by positivity
      have h_pos_le : (1:ℤ) ≤ (2:ℤ)^(c - 2*K) := by omega
      have step : (2:ℤ)^(2*K + (c - 2*K)) = (2:ℤ)^c := by congr 1; omega
      calc (2:ℤ)^(2*K) = (2:ℤ)^(2*K) * 1 := by ring
        _ ≤ (2:ℤ)^(2*K) * (2:ℤ)^(c - 2*K) := mul_le_mul_of_nonneg_left h_pos_le (by positivity)
        _ = (2:ℤ)^(2*K + (c - 2*K)) := by rw [←pow_add]
        _ = (2:ℤ)^c := step
    linarith [h_orig, h_pow]

  have h_eq2 : (2:ℤ)^c * ((2:ℤ)^(2*K-c) - 1) = (2:ℤ)^(v+4) * k := by
    have step : (2:ℤ)^(c + (2*K-c)) = (2:ℤ)^(2*K) := by congr 1; omega
    calc (2:ℤ)^c * ((2:ℤ)^(2*K-c) - 1)
      _ = (2:ℤ)^c * (2:ℤ)^(2*K-c) - (2:ℤ)^c := by ring
      _ = (2:ℤ)^(c + (2*K-c)) - (2:ℤ)^c := by rw [←pow_add]
      _ = (2:ℤ)^(2*K) - (2:ℤ)^c := by rw [step]
      _ = (7:ℤ)^(2*B) - 1 := by linarith [h_orig]
      _ = ((7:ℤ)^2)^B - 1 := by rw [←pow_mul]
      _ = (49:ℤ)^B - 1 := by norm_num
      _ = (2:ℤ)^(v+4) * k := hk_eq

  have h_c_le : c ≤ v + 4 := by
    by_contra hc_gt
    let e := c - (v + 4)
    have he_pos : 0 < e := by omega
    have hc_sub : c = v + 4 + e := by omega
    have h_eq3 : (2:ℤ)^(v+4) * ((2:ℤ)^e * ((2:ℤ)^(2*K-c) - 1)) = (2:ℤ)^(v+4) * k := by
      have step : (2:ℤ)^(v+4+e) = (2:ℤ)^c := by congr 1; omega
      calc (2:ℤ)^(v+4) * ((2:ℤ)^e * ((2:ℤ)^(2*K-c) - 1))
        _ = ((2:ℤ)^(v+4) * (2:ℤ)^e) * ((2:ℤ)^(2*K-c) - 1) := by ring
        _ = (2:ℤ)^(v+4+e) * ((2:ℤ)^(2*K-c) - 1) := by rw [←pow_add]
        _ = (2:ℤ)^c * ((2:ℤ)^(2*K-c) - 1) := by rw [step]
        _ = (2:ℤ)^(v+4) * k := h_eq2
    have h_eq4 : (2:ℤ)^e * ((2:ℤ)^(2*K-c) - 1) = k := by
      have h_pos : (2:ℤ)^(v+4) ≠ 0 := by positivity
      exact mul_left_cancel₀ h_pos h_eq3
    have h_eq5 : (2:ℤ)^e = 2 * (2:ℤ)^(e-1) := by
      have step : (2:ℤ)^e = (2:ℤ)^(1 + (e - 1)) := by congr 1; omega
      calc (2:ℤ)^e = (2:ℤ)^(1 + (e-1)) := step
        _ = (2:ℤ)^1 * (2:ℤ)^(e-1) := by rw [pow_add]
        _ = 2 * (2:ℤ)^(e-1) := by rw [pow_one]
    have h_eq6 : 2 * (2:ℤ)^(e-1) * ((2:ℤ)^(2*K-c) - 1) = k := by
      calc 2 * (2:ℤ)^(e-1) * ((2:ℤ)^(2*K-c) - 1)
        _ = (2:ℤ)^e * ((2:ℤ)^(2*K-c) - 1) := by rw [←h_eq5]
        _ = k := h_eq4
    rcases hk_odd with ⟨m, hm⟩
    have h_eq7 : 2 * (2:ℤ)^(e-1) * ((2:ℤ)^(2*K-c) - 1) = 2 * m + 1 := by rw [h_eq6, hm]
    have h_contra_eq : 2 * ((2:ℤ)^(e-1) * ((2:ℤ)^(2*K-c) - 1) - m) = 1 := by
      calc 2 * ((2:ℤ)^(e-1) * ((2:ℤ)^(2*K-c) - 1) - m)
        _ = 2 * (2:ℤ)^(e-1) * ((2:ℤ)^(2*K-c) - 1) - 2 * m := by ring
        _ = 2 * m + 1 - 2 * m := by rw [h_eq7]
        _ = 1 := by ring
    omega

  have h_diff : (2:ℤ)^c - 1 = ((2:ℤ)^K - (7:ℤ)^B) * ((2:ℤ)^K + (7:ℤ)^B) := by
    have step1 : 2 * K = K * 2 := by omega
    have step2 : 2 * B = B * 2 := by omega
    calc (2:ℤ)^c - 1
      _ = (2:ℤ)^(2*K) - (7:ℤ)^(2*B) := by linarith [h_orig]
      _ = (2:ℤ)^(K*2) - (7:ℤ)^(B*2) := by rw [step1, step2]
      _ = ((2:ℤ)^K)^2 - ((7:ℤ)^B)^2 := by rw [pow_mul, pow_mul]
      _ = ((2:ℤ)^K - (7:ℤ)^B) * ((2:ℤ)^K + (7:ℤ)^B) := by ring

  have h_K_gt : (7:ℤ)^B < (2:ℤ)^K := by
    by_contra! h_le
    have h_le2 : ((2:ℤ)^K)^2 ≤ ((7:ℤ)^B)^2 := by
      have h_pos : (0:ℤ) < (2:ℤ)^K := by positivity
      nlinarith
    have h_contra : (7:ℤ)^(2*B) ≥ (2:ℤ)^(2*K) := by
      have step1 : 2 * B = B * 2 := by omega
      have step2 : 2 * K = K * 2 := by omega
      calc (7:ℤ)^(2*B) = (7:ℤ)^(B * 2) := by rw [step1]
        _ = ((7:ℤ)^B)^2 := by rw [pow_mul]
        _ ≥ ((2:ℤ)^K)^2 := h_le2
        _ = (2:ℤ)^(K * 2) := by rw [←pow_mul]
        _ = (2:ℤ)^(2*K) := by rw [←step2]
    have h_2c : (2:ℤ)^c ≥ 2 := by
      have h_pos_le : (1:ℤ) ≤ (2:ℤ)^(c-1) := by
        have h_p : (0:ℤ) < (2:ℤ)^(c-1) := by positivity
        omega
      have step : (2:ℤ)^c = (2:ℤ)^(1 + (c - 1)) := by congr 1; omega
      calc (2:ℤ)^c = (2:ℤ)^(1 + (c-1)) := step
        _ = (2:ℤ)^1 * (2:ℤ)^(c-1) := by rw [pow_add]
        _ = 2 * (2:ℤ)^(c-1) := by rw [pow_one]
        _ ≥ 2 * 1 := mul_le_mul_of_nonneg_left h_pos_le (by norm_num)
        _ = 2 := by ring
    linarith [h_orig, h_contra, h_2c]

  have h_7_lt : (7:ℤ)^B < (2:ℤ)^c := by
    have h_diff_ge : (2:ℤ)^c - 1 ≥ 1 * ((2:ℤ)^K + (7:ℤ)^B) := by
      calc (2:ℤ)^c - 1 = ((2:ℤ)^K - (7:ℤ)^B) * ((2:ℤ)^K + (7:ℤ)^B) := h_diff
        _ ≥ 1 * ((2:ℤ)^K + (7:ℤ)^B) := by
          have h_diff_pos : (1:ℤ) ≤ ((2:ℤ)^K - (7:ℤ)^B) := by linarith [h_K_gt]
          have h_sum_pos : (0:ℤ) ≤ ((2:ℤ)^K + (7:ℤ)^B) := by positivity
          exact mul_le_mul_of_nonneg_right h_diff_pos h_sum_pos
    linarith [h_diff_ge, show (0:ℤ) < (2:ℤ)^K by positivity]

  have h_7_ge : ∀ n : ℕ, n ≥ 2 → 16 * (n:ℤ) < (7:ℤ)^n := by
    intro n
    induction n with
    | zero => intro h; omega
    | succ n ih =>
      intro hn
      have h_cases : n = 1 ∨ n ≥ 2 := by omega
      rcases h_cases with rfl | hn2
      · norm_num
      · have ih_val := ih hn2
        have step : (7:ℤ)^(2 + (n - 2)) = (7:ℤ)^n := by congr 1; omega
        calc 16 * (n + 1 : ℤ) = 16 * (n:ℤ) + 16 := by ring
          _ < (7:ℤ)^n + 16 := by linarith [ih hn2]
          _ < (7:ℤ)^n + 6 * (7:ℤ)^n := by
            have h_pow : (49:ℤ) ≤ (7:ℤ)^n := by
              have h_pos_le : (1:ℤ) ≤ (7:ℤ)^(n-2) := by
                have h_p : (0:ℤ) < (7:ℤ)^(n-2) := by positivity
                omega
              calc (49:ℤ) = (7:ℤ)^2 * 1 := by norm_num
                _ ≤ (7:ℤ)^2 * (7:ℤ)^(n-2) := mul_le_mul_of_nonneg_left h_pos_le (by norm_num)
                _ = (7:ℤ)^(2 + (n - 2)) := by rw [←pow_add]
                _ = (7:ℤ)^n := step
            linarith
          _ = 7 * (7:ℤ)^n := by ring
          _ = (7:ℤ)^(n + 1) := by
            calc 7 * (7:ℤ)^n = (7:ℤ)^1 * (7:ℤ)^n := by norm_num
              _ = (7:ℤ)^(1 + n) := by rw [←pow_add]
              _ = (7:ℤ)^(n + 1) := by
                have st : 1 + n = n + 1 := by omega
                rw [st]

  have h_7_lt_16 : (7:ℤ)^B < 16 * (B:ℤ) := by
    calc (7:ℤ)^B < (2:ℤ)^c := h_7_lt
      _ ≤ (2:ℤ)^(v+4) := by
        have h_pos_le : (1:ℤ) ≤ (2:ℤ)^(v + 4 - c) := by
          have h_p : (0:ℤ) < (2:ℤ)^(v + 4 - c) := by positivity
          omega
        have step : (2:ℤ)^(c + (v + 4 - c)) = (2:ℤ)^(v + 4) := by congr 1; omega
        calc (2:ℤ)^c = (2:ℤ)^c * 1 := by ring
          _ ≤ (2:ℤ)^c * (2:ℤ)^(v + 4 - c) := mul_le_mul_of_nonneg_left h_pos_le (by positivity)
          _ = (2:ℤ)^(c + (v + 4 - c)) := by rw [←pow_add]
          _ = (2:ℤ)^(v + 4) := step
      _ = 16 * (2:ℤ)^v := by
        have step : (2:ℤ)^(v+4) = (2:ℤ)^(4+v) := by congr 1; omega
        calc (2:ℤ)^(v+4) = (2:ℤ)^(4+v) := step
          _ = (2:ℤ)^4 * (2:ℤ)^v := by rw [pow_add]
          _ = 16 * (2:ℤ)^v := by norm_num
      _ ≤ 16 * (B:ℤ) := by
        have h_v_le : (2:ℤ)^v ≤ (B:ℤ) := by exact_mod_cast hk_le
        linarith

  have h_B_eq_1 : B = 1 := by
    by_contra h_neq
    have h_B_ge_2 : B ≥ 2 := by omega
    have h_ge := h_7_ge B h_B_ge_2
    linarith [h_7_lt_16]

  have h_v_0 : v = 0 := by
    have h1 : 2^v ≤ B := hk_le
    rw [h_B_eq_1] at h1
    by_contra h_neq
    have h_v_ge_1 : v ≥ 1 := by omega
    have h_pow_ge : (2:ℤ)^v ≥ (2:ℤ)^1 := by
      have h_pos_le : (1:ℤ) ≤ (2:ℤ)^(v-1) := by
        have h_p : (0:ℤ) < (2:ℤ)^(v-1) := by positivity
        omega
      have step : (2:ℤ)^v = (2:ℤ)^(1 + (v - 1)) := by congr 1; omega
      calc (2:ℤ)^v = (2:ℤ)^(1 + (v-1)) := step
        _ = (2:ℤ)^1 * (2:ℤ)^(v-1) := by rw [pow_add]
        _ = 2 * (2:ℤ)^(v-1) := by rw [pow_one]
        _ ≥ 2 * 1 := mul_le_mul_of_nonneg_left h_pos_le (by norm_num)
        _ = 2 := by ring
        _ = (2:ℤ)^1 := by norm_num
    have h1_z : (2:ℤ)^v ≤ 1 := by exact_mod_cast h1
    linarith

  have h_c_le_4 : c ≤ 4 := by omega

  have h_eq_c : (2:ℤ)^(2*K) = 48 + (2:ℤ)^c := by
    have hB1 : (7:ℤ)^(2*B) = 49 := by
      have st : 2 * B = 2 := by omega
      rw [st]
      norm_num
    linarith [h_orig]

  have hc_cases : c = 1 ∨ c = 2 ∨ c = 3 ∨ c = 4 := by omega
  rcases hc_cases with rfl | rfl | rfl | rfl
  · have h_eq : (2:ℤ)^(2*K) = 50 := by linarith [h_eq_c]
    have h_K_ge_2 : K ≥ 2 := by
      by_contra h_lt
      have : K = 1 := by omega
      have h_eq_false : (2:ℤ)^(2*1) = 50 := by rw [←this]; exact h_eq
      revert h_eq_false
      norm_num
    have h_pow : (2:ℤ)^(2*K) = 16 * (2:ℤ)^(2*K-4) := by
      have step : (2:ℤ)^(2*K) = (2:ℤ)^(4 + (2*K - 4)) := by congr 1; omega
      calc (2:ℤ)^(2*K) = (2:ℤ)^(4 + (2*K - 4)) := step
        _ = (2:ℤ)^4 * (2:ℤ)^(2*K-4) := by rw [pow_add]
        _ = 16 * (2:ℤ)^(2*K-4) := by norm_num
    have h_contra_eq : 16 * (2:ℤ)^(2*K-4) = 50 := by linarith [h_eq, h_pow]
    omega
  · have h_eq : (2:ℤ)^(2*K) = 52 := by linarith [h_eq_c]
    have h_K_ge_2 : K ≥ 2 := by
      by_contra h_lt
      have : K = 1 := by omega
      have h_eq_false : (2:ℤ)^(2*1) = 52 := by rw [←this]; exact h_eq
      revert h_eq_false
      norm_num
    have h_pow : (2:ℤ)^(2*K) = 16 * (2:ℤ)^(2*K-4) := by
      have step : (2:ℤ)^(2*K) = (2:ℤ)^(4 + (2*K - 4)) := by congr 1; omega
      calc (2:ℤ)^(2*K) = (2:ℤ)^(4 + (2*K - 4)) := step
        _ = (2:ℤ)^4 * (2:ℤ)^(2*K-4) := by rw [pow_add]
        _ = 16 * (2:ℤ)^(2*K-4) := by norm_num
    have h_contra_eq : 16 * (2:ℤ)^(2*K-4) = 52 := by linarith [h_eq, h_pow]
    omega
  · have h_eq : (2:ℤ)^(2*K) = 56 := by linarith [h_eq_c]
    have h_K_ge_2 : K ≥ 2 := by
      by_contra h_lt
      have : K = 1 := by omega
      have h_eq_false : (2:ℤ)^(2*1) = 56 := by rw [←this]; exact h_eq
      revert h_eq_false
      norm_num
    have h_pow : (2:ℤ)^(2*K) = 16 * (2:ℤ)^(2*K-4) := by
      have step : (2:ℤ)^(2*K) = (2:ℤ)^(4 + (2*K - 4)) := by congr 1; omega
      calc (2:ℤ)^(2*K) = (2:ℤ)^(4 + (2*K - 4)) := step
        _ = (2:ℤ)^4 * (2:ℤ)^(2*K-4) := by rw [pow_add]
        _ = 16 * (2:ℤ)^(2*K-4) := by norm_num
    have h_contra_eq : 16 * (2:ℤ)^(2*K-4) = 56 := by linarith [h_eq, h_pow]
    omega
  · rfl

theorem solve_even_case_aux (K B c : ℕ) (hc : c = 4)
  (hB : (2:ℤ) ^ c = (2:ℤ) * ((7:ℤ) ^ B + 1))
  (h : 2 ^ (2 * K) + 1 = 7 ^ (2 * B) + 2 ^ c) : K = 3 ∧ B = 1 ∧ c = 4 :=
by
  subst hc

  have h2 : (7:ℤ) ^ B = 7 := by
    have h1 : (2:ℤ) ^ 4 = 16 := by norm_num
    have hB' : (16:ℤ) = (2:ℤ) * ((7:ℤ) ^ B + 1) := by
      rw [← h1]
      exact hB
    linarith

  have hB_eq : B = 1 := by
    have h3 : 7 ^ B = 7 ^ 1 := by
      have h_seven : 7 ^ 1 = 7 := by norm_num
      rw [h_seven]
      exact_mod_cast h2
    exact Nat.pow_right_injective (by decide) h3

  subst hB_eq

  have hK1 : 2 ^ (2 * K) + 1 = 65 := by
    calc 2 ^ (2 * K) + 1 = 7 ^ (2 * 1) + 2 ^ 4 := h
      _ = 65 := by norm_num

  have hK2 : 2 ^ (2 * K) = 2 ^ 6 := by
    calc 2 ^ (2 * K) = 64 := by omega
      _ = 2 ^ 6 := by norm_num

  have hK3 : 2 * K = 6 := Nat.pow_right_injective (by decide) hK2

  have hK_eq : K = 3 := by omega

  exact ⟨hK_eq, rfl, rfl⟩

theorem solve_even_case (K B c : ℕ) (hK : 0 < K) (hB : 0 < B) (hc : 0 < c)
  (h : 2 ^ (2 * K) + 1 = 7 ^ (2 * B) + 2 ^ c) : K = 3 ∧ B = 1 ∧ c = 4 :=
solve_even_case_aux K B c (lem8 K B c hK hB hc h) (lem5 K B c hK hB hc h) h

theorem PBBasic023 : {(a, b, c) : ℕ × ℕ × ℕ | 0 < a ∧ 0 < b ∧ 0 < c ∧ 2 ^ a + 1 = 7 ^ b + 2 ^ c}
      = {(3,1,1), (6,2,4)} :=
by
  ext ⟨a, b, c⟩
  simp only [Set.mem_setOf_eq, Set.mem_insert_iff, Set.mem_singleton_iff, Prod.mk.injEq]
  constructor
  · rintro ⟨ha, hb, hc, heq⟩
    have hc_cases : c = 1 ∨ 1 < c := by omega
    rcases hc_cases with rfl | hc_gt
    · left
      have heq' : 2 ^ a + 1 = 7 ^ b + 2 :=
        calc 2 ^ a + 1 = 7 ^ b + 2 ^ 1 := heq
          _ = 7 ^ b + 2 := rfl
      obtain ⟨rfl, rfl⟩ := lemma_c1 a b ha hb heq'
      exact ⟨rfl, rfl, rfl⟩
    · right
      obtain ⟨B, hB, rfl⟩ := b_is_even a b c ha hb hc_gt heq
      obtain ⟨K, hK, rfl⟩ := a_is_even a (2 * B) c ha (by omega) hc_gt heq
      obtain ⟨rfl, rfl, rfl⟩ := solve_even_case K B c hK hB hc heq
      exact ⟨rfl, rfl, rfl⟩
  · rintro (⟨rfl, rfl, rfl⟩ | ⟨rfl, rfl, rfl⟩)
    · exact ⟨by decide, by decide, by decide, by rfl⟩
    · exact ⟨by decide, by decide, by decide, by rfl⟩
