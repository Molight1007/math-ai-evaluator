import Mathlib

theorem int_dvd_of_mod_eq_minus_alt (a n k : ℤ) (h : a % n = n - k) : n ∣ a + k :=
by
  -- Retrieve the foundational division identity: a % n = a - n * (a / n)
  have h_mod := EuclideanDomain.mod_eq_sub_mul_div a n

  -- We provide the explicit divisor multiplier
  use (a / n) + 1

  -- Chain equalities to show a + k perfectly factors into n * ((a / n) + 1)
  calc
    a + k = a % n + n * (a / n) + k := by linarith [h_mod]
    _ = (n - k) + n * (a / n) + k := by rw [h]
    _ = n * ((a / n) + 1) := by ring

theorem zmod_7_eq_6_of_nat_alt (n : ℕ) (h : n % 7 = 6) : (n : ℤ) % 7 = 6 :=
by
  exact_mod_cast h

theorem int_k_pos_alt (n d k : ℕ) (hn : n = d * k) (h7 : n % 7 = 6) : (k : ℤ) > 0 :=
by
  have hk : k ≠ 0 := by
    intro h
    subst h
    rw [mul_zero] at hn
    subst hn
    omega
  omega

theorem r_eq_mod_z_alt (d k n : ℕ) (hd : d > 0) (hn : n = d * k) :
  (((d + (n / d : ℕ)) ^ 2 % n : ℕ) : ℤ) = ((d : ℤ)^2 + (k : ℤ)^2) % (n : ℤ) :=
by
  have h_div : n / d = k := by
    rw [hn]
    apply Nat.mul_div_cancel_left
    exact hd
  rw [h_div]
  push_cast
  have h_sq : ((d : ℤ) + (k : ℤ)) ^ 2 = (d : ℤ) ^ 2 + (k : ℤ) ^ 2 + 2 * (n : ℤ) := by
    have hnZ : (n : ℤ) = (d : ℤ) * (k : ℤ) := by
      rw [hn]
      push_cast
      rfl
    rw [hnZ]
    ring
  rw [h_sq]
  have H : ((d : ℤ) ^ 2 + (k : ℤ) ^ 2) % (n : ℤ) = ((d : ℤ) ^ 2 + (k : ℤ) ^ 2 + 2 * (n : ℤ)) % (n : ℤ) := by
    change Int.ModEq (n : ℤ) ((d : ℤ) ^ 2 + (k : ℤ) ^ 2) ((d : ℤ) ^ 2 + (k : ℤ) ^ 2 + 2 * (n : ℤ))
    rw [Int.modEq_add_mul_modulus_iff]
  exact H.symm

theorem int_mod_lt_alt (a n : ℤ) (hn : n > 0) : a % n < n :=
by
  have h1 : n ≠ 0 := by omega
  have h2 := Int.emod_lt_abs a h1
  have h3 : |n| = n := abs_of_pos hn
  omega

theorem zify_mul_alt (n d k : ℕ) (h : n = d * k) : (n : ℤ) = (d : ℤ) * (k : ℤ) :=
by
  rw [h]
  push_cast
  rfl

theorem n_pos_from_mod_alt (n : ℕ) (h : n % 7 = 6) : (n : ℤ) > 0 :=
by
  omega

theorem vieta_jump_1_alt (d k : ℤ) (hd : d > 0) (hk : k > 0) (h : d * k ∣ d^2 + k^2 + 1) :
  d^2 + k^2 + 1 = 3 * d * k :=
by
  obtain ⟨m, hm⟩ := h
  have hm_eq : d^2 + k^2 + 1 = m * d * k := by
    calc d^2 + k^2 + 1 = d * k * m := hm
      _ = m * d * k := by ring

  have hm_pos : m > 0 := by
    by_contra! h_le
    have hd_nonneg : d ≥ 0 := by omega
    have hk_nonneg : k ≥ 0 := by omega
    have hdk_nonneg : d * k ≥ 0 := mul_nonneg hd_nonneg hk_nonneg
    have hm_neg : -m ≥ 0 := by omega
    have h_mul : -m * (d * k) ≥ 0 := mul_nonneg hm_neg hdk_nonneg
    have h_le_zero : -(-m * (d * k)) ≤ 0 := by linarith [h_mul]
    have h_mdk_le : m * d * k ≤ 0 := by
      calc m * d * k = -(-m * (d * k)) := by ring
        _ ≤ 0 := h_le_zero
    have hd2 : d^2 ≥ 0 := sq_nonneg d
    have hk2 : k^2 ≥ 0 := sq_nonneg k
    have h_d2_pos : d^2 + k^2 + 1 > 0 := by linarith [hd2, hk2]
    linarith [hm_eq, h_mdk_le, h_d2_pos]

  by_contra h_m_ne_3
  have h_m_ne : m ≠ 3 := by
    intro h_m_eq_3
    apply h_m_ne_3
    calc d^2 + k^2 + 1 = m * d * k := hm_eq
      _ = 3 * d * k := by rw [h_m_eq_3]

  let S := fun (s : ℕ) => ∃ (x y : ℤ), x > 0 ∧ y > 0 ∧ x^2 + y^2 + 1 = m * x * y ∧ x + y = (s : ℤ)

  have hS : ∃ s, S s := by
    use (d + k).toNat
    use d, k
    refine ⟨hd, hk, hm_eq, by omega⟩

  have h_min_exists : ∃ s, S s ∧ ∀ s' < s, ¬ S s' := by
    classical
    exact ⟨Nat.find hS, Nat.find_spec hS, fun s' hs' => Nat.find_min hS hs'⟩
  obtain ⟨s_min, h_min, h_min_prop⟩ := h_min_exists

  obtain ⟨x, y, hx, hy, heq, hs⟩ := h_min

  obtain ⟨X, Y, hX, hY, heq2, hs2, hXY⟩ : ∃ X Y : ℤ, X > 0 ∧ Y > 0 ∧ X^2 + Y^2 + 1 = m * X * Y ∧ X + Y = (s_min : ℤ) ∧ X ≥ Y := by
    by_cases hxy : x ≥ y
    · exact ⟨x, y, hx, hy, heq, hs, hxy⟩
    · have hyx : y ≥ x := by omega
      refine ⟨y, x, hy, hx, ?_, ?_, hyx⟩
      · calc y^2 + x^2 + 1 = x^2 + y^2 + 1 := by ring
          _ = m * x * y := heq
          _ = m * y * x := by ring
      · calc y + x = x + y := by ring
          _ = s_min := hs

  by_cases h_eq : X = Y
  · have hY_eq : Y = X := h_eq.symm
    have h_heq2_X : X^2 + X^2 + 1 = m * X * X := by
      calc X^2 + X^2 + 1 = X^2 + Y^2 + 1 := by rw [hY_eq]
        _ = m * X * Y := heq2
        _ = m * X * X := by rw [hY_eq]
    have h1 : X^2 * (m - 2) = 1 := by
      calc X^2 * (m - 2) = m * X * X - (X^2 + X^2) := by ring
        _ = (X^2 + X^2 + 1) - (X^2 + X^2) := by rw [← h_heq2_X]
        _ = 1 := by ring
    have hm2 : m - 2 > 0 := by
      by_contra! h_le
      have h_sq : X^2 ≥ 0 := sq_nonneg X
      have h_neg : -(m - 2) ≥ 0 := by omega
      have h_mul : X^2 * -(m - 2) ≥ 0 := mul_nonneg h_sq h_neg
      have h_le_zero : -(X^2 * -(m - 2)) ≤ 0 := by linarith [h_mul]
      have h_X2_le : X^2 * (m - 2) ≤ 0 := by
        calc X^2 * (m - 2) = -(X^2 * -(m - 2)) := by ring
          _ ≤ 0 := h_le_zero
      linarith [h1, h_X2_le]
    have h_X2_le : X^2 ≤ 1 := by
      have h_sq : X^2 ≥ 0 := sq_nonneg X
      have h_m2_diff : (m - 2) - 1 ≥ 0 := by omega
      have h_mul : X^2 * ((m - 2) - 1) ≥ 0 := mul_nonneg h_sq h_m2_diff
      have h_le_sub : X^2 * (m - 2) - X^2 * ((m - 2) - 1) ≤ X^2 * (m - 2) := by linarith [h_mul]
      have h_le_mul : X^2 * 1 ≤ X^2 * (m - 2) := by
        calc X^2 * 1 = X^2 * (m - 2) - X^2 * ((m - 2) - 1) := by ring
          _ ≤ X^2 * (m - 2) := h_le_sub
      calc X^2 = X^2 * 1 := by ring
        _ ≤ X^2 * (m - 2) := h_le_mul
        _ = 1 := h1
    have h_X2_ge : X^2 ≥ 1 := by
      have hX_diff : X - 1 ≥ 0 := by omega
      have h_mul : (X - 1) * (X + 1) ≥ 0 := mul_nonneg hX_diff (by omega)
      have h_sum : (X - 1) * (X + 1) + 1 ≥ 1 := by linarith [h_mul]
      calc X^2 = (X - 1) * (X + 1) + 1 := by ring
        _ ≥ 1 := h_sum
    have hX2_eq : X^2 = 1 := le_antisymm h_X2_le h_X2_ge
    have hX1 : X = 1 := by
      have h1_eq : (X - 1) * (X + 1) = 0 := by
        calc (X - 1) * (X + 1) = X^2 - 1 := by ring
          _ = 1 - 1 := by rw [hX2_eq]
          _ = 0 := by ring
      cases mul_eq_zero.mp h1_eq with
      | inl h => omega
      | inr h => omega
    have h_m_eq_3 : m = 3 := by
      calc m = 1^2 * (m - 2) + 2 := by ring
        _ = X^2 * (m - 2) + 2 := by rw [hX1]
        _ = 1 + 2 := by rw [h1]
        _ = 3 := by ring
    exact h_m_ne h_m_eq_3

  · have h_gt : X > Y := by omega
    let X' := m * Y - X
    have hXX' : X * X' = Y^2 + 1 := by
      calc X * X' = X * (m * Y - X) := rfl
        _ = (m * X * Y) - X^2 := by ring
        _ = (X^2 + Y^2 + 1) - X^2 := by rw [← heq2]
        _ = Y^2 + 1 := by ring
    have hX' : X' > 0 := by
      by_contra! h_le
      have h_sq : X ≥ 0 := by omega
      have h_neg : -X' ≥ 0 := by omega
      have h_mul : X * -X' ≥ 0 := mul_nonneg h_sq h_neg
      have h_le_zero : -(X * -X') ≤ 0 := by linarith [h_mul]
      have h_XX'_le : X * X' ≤ 0 := by
        calc X * X' = -(X * -X') := by ring
          _ ≤ 0 := h_le_zero
      have hy2 : Y^2 ≥ 0 := sq_nonneg Y
      have h_Y2_pos : Y^2 + 1 > 0 := by linarith [hy2]
      linarith [hXX', h_XX'_le, h_Y2_pos]
    have heq3 : X'^2 + Y^2 + 1 = m * X' * Y := by
      calc X'^2 + Y^2 + 1 = (m * Y - X)^2 + Y^2 + 1 := rfl
        _ = (m * Y)^2 - 2 * m * Y * X + (X^2 + Y^2 + 1) := by ring
        _ = (m * Y)^2 - 2 * m * Y * X + m * X * Y := by rw [heq2]
        _ = m * (m * Y - X) * Y := by ring
        _ = m * X' * Y := rfl
    have hX'_lt_X : X' < X := by
      by_cases hY1 : Y = 1
      · have h1 : X * X' = 2 := by
          calc X * X' = Y^2 + 1 := hXX'
            _ = 1^2 + 1 := by rw [hY1]
            _ = 2 := by ring
        have h2 : X ≥ 2 := by omega
        have hX'1 : X' = 1 := by
          by_contra! h_ne
          have hX'_ge_2 : X' ≥ 2 := by omega
          have hX_diff : X - 2 ≥ 0 := by omega
          have hX'_diff : X' - 2 ≥ 0 := by omega
          have h_mul : (X - 2) * (X' - 2) ≥ 0 := mul_nonneg hX_diff hX'_diff
          have h_sum : (X - 2) * (X' - 2) + 2 * X + 2 * X' - 4 ≥ 4 := by linarith [h_mul, h2, hX'_ge_2]
          have : X * X' ≥ 4 := by
            calc X * X' = (X - 2) * (X' - 2) + 2 * X + 2 * X' - 4 := by ring
              _ ≥ 4 := h_sum
          omega
        omega
      · have h_bound : Y^2 + 1 < Y^2 + Y := by
          have hY2 : Y ≥ 2 := by omega
          linarith [hY2]
        have h_XY_diff : X - (Y + 1) ≥ 0 := by omega
        have h_X'_pos : X' ≥ 0 := by omega
        have h_mul_diff : (X - (Y + 1)) * X' ≥ 0 := mul_nonneg h_XY_diff h_X'_pos
        have h_le_sub : X * X' - (X - (Y + 1)) * X' ≤ X * X' := by linarith [h_mul_diff]
        have h_le : (Y + 1) * X' ≤ X * X' := by
          calc (Y + 1) * X' = X * X' - (X - (Y + 1)) * X' := by ring
            _ ≤ X * X' := h_le_sub

        have h_le_expanded : Y * X' + X' ≤ X * X' := by
          calc Y * X' + X' = (Y + 1) * X' := by ring
            _ ≤ X * X' := h_le
        have h_bound_expanded : Y^2 + 1 < Y^2 + Y := h_bound
        have h_lt_expanded : Y * X' + X' < Y^2 + Y := by linarith [h_le_expanded, hXX', h_bound_expanded]
        have h_lt' : (Y + 1) * X' < (Y + 1) * Y := by
          calc (Y + 1) * X' = Y * X' + X' := by ring
            _ < Y^2 + Y := h_lt_expanded
            _ = (Y + 1) * Y := by ring

        have h_cancel : X' < Y := by
          by_contra! h_ge
          have h_diff : X' - Y ≥ 0 := by omega
          have h_pos : Y + 1 ≥ 0 := by omega
          have h_mul : (Y + 1) * (X' - Y) ≥ 0 := mul_nonneg h_pos h_diff
          have h_ge_add : (Y + 1) * (X' - Y) + (Y + 1) * Y ≥ (Y + 1) * Y := by linarith [h_mul]
          have h_contra : (Y + 1) * X' ≥ (Y + 1) * Y := by
            calc (Y + 1) * X' = (Y + 1) * (X' - Y) + (Y + 1) * Y := by ring
              _ ≥ (Y + 1) * Y := h_ge_add
          linarith [h_lt', h_contra]
        omega
    have hS' : S (X' + Y).toNat := by
      use X', Y
      refine ⟨hX', hY, heq3, by omega⟩
    have h_lt : (X' + Y).toNat < s_min := by
      have : X' + Y < X + Y := by omega
      have : X + Y = (s_min : ℤ) := hs2
      have : X' + Y > 0 := by omega
      omega
    have h_not_S := h_min_prop (X' + Y).toNat h_lt
    exact h_not_S hS'

theorem int_not_mod_6_1_alt (d k : ℤ) (h : d^2 + k^2 + 1 = 3 * d * k) :
  (d * k) % 7 ≠ 6 :=
by
  intro h6
  have h_dk : ((d * k : ℤ) : ZMod 7) = (6 : ZMod 7) := by
    have h_cast := ZMod.intCast_mod (d * k) 7
    rw [← h_cast]
    have h_eq : (d * k) % (↑(7 : ℕ) : ℤ) = 6 := h6
    rw [h_eq]
    push_cast
    rfl

  have h_dk2 : (d : ZMod 7) * (k : ZMod 7) = (6 : ZMod 7) := by
    calc (d : ZMod 7) * (k : ZMod 7)
      _ = ((d * k : ℤ) : ZMod 7) := by push_cast; rfl
      _ = (6 : ZMod 7) := h_dk

  have h_eq : (d : ZMod 7)^2 + (k : ZMod 7)^2 + (1 : ZMod 7) = (3 : ZMod 7) * (6 : ZMod 7) := by
    calc (d : ZMod 7)^2 + (k : ZMod 7)^2 + (1 : ZMod 7)
      _ = ((d^2 + k^2 + 1 : ℤ) : ZMod 7) := by push_cast; ring
      _ = ((3 * d * k : ℤ) : ZMod 7) := by rw [h]
      _ = (3 : ZMod 7) * ((d * k : ℤ) : ZMod 7) := by push_cast; ring
      _ = (3 : ZMod 7) * (6 : ZMod 7) := by rw [h_dk]

  have h3 : ((d : ZMod 7) - (k : ZMod 7))^2 = (5 : ZMod 7) := by
    calc ((d : ZMod 7) - (k : ZMod 7))^2
      _ = (d : ZMod 7)^2 + (k : ZMod 7)^2 + (1 : ZMod 7) - (1 : ZMod 7) - (2 : ZMod 7) * ((d : ZMod 7) * (k : ZMod 7)) := by ring
      _ = (3 : ZMod 7) * (6 : ZMod 7) - (1 : ZMod 7) - (2 : ZMod 7) * ((d : ZMod 7) * (k : ZMod 7)) := by rw [h_eq]
      _ = (3 : ZMod 7) * (6 : ZMod 7) - (1 : ZMod 7) - (2 : ZMod 7) * (6 : ZMod 7) := by rw [h_dk2]
      _ = (5 : ZMod 7) := by ring

  have h4 : ∀ x : ZMod 7, x^2 ≠ (5 : ZMod 7) := by decide
  exact h4 ((d : ZMod 7) - (k : ZMod 7)) h3

theorem vieta_jump_2_alt (d k : ℤ) (hd : d > 0) (hk : k > 0) (h : d * k ∣ d^2 + k^2 + 2) :
  d^2 + k^2 + 2 = 4 * d * k :=
by
  have H_main : ∀ (n : ℕ) (d k : ℤ), d > 0 → k > 0 → k ≤ d → d + k = (n : ℤ) → d * k ∣ d^2 + k^2 + 2 → d^2 + k^2 + 2 = 4 * d * k := by
    intro n
    induction' n using Nat.strong_induction_on with n ih
    intro d k hd hk hdk hsum hdvd
    obtain ⟨m, hm⟩ := hdvd
    have h_m_pos : m > 0 := by
      have h1 : d^2 + k^2 + 2 > 0 := by positivity
      have h2 : d * k * m > 0 := by linarith [hm]
      have h3 : d * k > 0 := by positivity
      by_contra H
      have : m ≤ 0 := by omega
      have : d * k * m ≤ 0 := by nlinarith
      linarith

    let x := m * k - d
    have hx_def : x = m * k - d := rfl
    have hx_eq : d * x = k^2 + 2 := by
      calc d * x = d * (m * k - d) := by rw [hx_def]
        _ = d * m * k - d^2 := by ring
        _ = (d * k * m) - d^2 := by ring
        _ = (d^2 + k^2 + 2) - d^2 := by rw [← hm]
        _ = k^2 + 2 := by ring

    have hx_pos : x > 0 := by
      have h1 : k^2 + 2 > 0 := by positivity
      have h2 : d * x > 0 := by linarith [hx_eq]
      by_contra H
      have : x ≤ 0 := by omega
      have : d * x ≤ 0 := by nlinarith
      linarith

    have hm_eq : x^2 + k^2 + 2 = m * x * k := by
      calc x^2 + k^2 + 2 = x * (m * k - d) + k^2 + 2 := by
             have : x * (m * k - d) = x^2 := by
               calc x * (m * k - d) = x * x := by rw [← hx_def]
                 _ = x^2 := by ring
             rw [this]
        _ = m * x * k - d * x + k^2 + 2 := by ring
        _ = m * x * k - (k^2 + 2) + k^2 + 2 := by rw [hx_eq]
        _ = m * x * k := by ring

    have h_d2 : d^2 ≤ k^2 + 2 ∨ x < d := by
      by_cases hxd : x ≥ d
      · left
        have h_dx : d * x ≥ d^2 := by nlinarith
        linarith [hx_eq]
      · right; omega

    rcases h_d2 with hd2 | hxd
    · have hk2_le : k^2 ≤ d^2 := by
        have h_diff_sum : (d - k) * (d + k) ≥ 0 := by
          have h1 : d - k ≥ 0 := by omega
          have h2 : d + k ≥ 0 := by omega
          nlinarith
        have h_diff_sq : d^2 - k^2 ≥ 0 := by
          calc d^2 - k^2 = (d - k) * (d + k) := by ring
            _ ≥ 0 := h_diff_sum
        linarith
      have hd2_cases : d^2 = k^2 ∨ d^2 = k^2 + 1 ∨ d^2 = k^2 + 2 := by omega
      rcases hd2_cases with eq1 | eq2 | eq3
      · have hdk_eq : d = k := by
          have : (d - k) * (d + k) = 0 := by
            calc (d - k) * (d + k) = d^2 - k^2 := by ring
              _ = k^2 - k^2 := by rw [eq1]
              _ = 0 := by ring
          have H3 : d - k = 0 ∨ d + k = 0 := mul_eq_zero.mp this
          rcases H3 with h1 | h2
          · omega
          · omega
        have h_k2_div : k^2 * (m - 2) = 2 := by
          have H_dkm : d * k * m = k * k * m := by rw [hdk_eq]
          calc k^2 * (m - 2) = k * k * m - 2 * k^2 := by ring
            _ = d * k * m - 2 * k^2 := by rw [← H_dkm]
            _ = (d^2 + k^2 + 2) - 2 * k^2 := by rw [← hm]
            _ = k^2 + k^2 + 2 - 2 * k^2 := by rw [hdk_eq]
            _ = 2 := by ring
        have hk1 : k = 1 := by
          by_contra hk_not
          have hk2_ge : k ≥ 2 := by omega
          have hm2_pos : m - 2 > 0 := by
            have h_k2_pos : k^2 > 0 := by nlinarith
            have : k^2 * (m - 2) > 0 := by linarith [h_k2_div]
            by_contra H
            have : m - 2 ≤ 0 := by omega
            have : k^2 * (m - 2) ≤ 0 := by nlinarith
            linarith
          have hm2_ge : m - 2 ≥ 1 := by omega
          have h_bound : k^2 * (m - 2) ≥ 4 := by
            have h1 : k^2 ≥ 4 := by nlinarith
            have h2 : k^2 * (m - 2) ≥ 4 * (m - 2) := by nlinarith
            have h3 : 4 * (m - 2) ≥ 4 := by linarith
            linarith
          linarith [h_k2_div, h_bound]
        have hm4 : m = 4 := by
          have h1 : m - 2 = 2 := by
            calc m - 2 = 1^2 * (m - 2) := by ring
              _ = k^2 * (m - 2) := by rw [← hk1]
              _ = 2 := h_k2_div
          linarith
        calc d^2 + k^2 + 2 = d * k * m := hm
          _ = d * k * 4 := by rw [hm4]
          _ = 4 * d * k := by ring

      · have h_diff_sq : (d - k) * (d + k) = 1 := by
          calc (d - k) * (d + k) = d^2 - k^2 := by ring
            _ = k^2 + 1 - k^2 := by rw [eq2]
            _ = 1 := by ring
        have h_sum : d + k ≥ 2 := by omega
        have h_diff : d - k > 0 := by
          have : (d - k) * (d + k) > 0 := by linarith [h_diff_sq]
          by_contra H
          have : d - k ≤ 0 := by omega
          have : (d - k) * (d + k) ≤ 0 := by nlinarith
          linarith
        have h_bound : (d - k) * (d + k) ≥ 2 := by
          have h1 : d - k ≥ 1 := by omega
          have h2 : (d - k) * (d + k) ≥ 1 * (d + k) := by nlinarith
          have h3 : 1 * (d + k) ≥ 2 := by linarith
          linarith
        linarith [h_diff_sq, h_bound]

      · have h_diff_sq : (d - k) * (d + k) = 2 := by
          calc (d - k) * (d + k) = d^2 - k^2 := by ring
            _ = k^2 + 2 - k^2 := by rw [eq3]
            _ = 2 := by ring
        have h_sum : d + k ≥ 2 := by omega
        have h_diff : d - k > 0 := by
          have : (d - k) * (d + k) > 0 := by linarith [h_diff_sq]
          by_contra H
          have : d - k ≤ 0 := by omega
          have : (d - k) * (d + k) ≤ 0 := by nlinarith
          linarith
        have h_diff_eq : d - k = 1 := by
          by_contra H
          have h_ge2 : d - k ≥ 2 := by omega
          have h_bound : (d - k) * (d + k) ≥ 4 := by
            have h2 : (d - k) * (d + k) ≥ 2 * (d + k) := by nlinarith
            have h3 : 2 * (d + k) ≥ 4 := by linarith
            linarith
          linarith [h_diff_sq, h_bound]
        have h_sum_eq2 : d + k = 2 := by
          have : 1 * (d + k) = 2 := by
            calc 1 * (d + k) = (d - k) * (d + k) := by rw [h_diff_eq]
              _ = 2 := h_diff_sq
          linarith
        omega

    · by_cases hkx : k ≤ x
      · have h_nat_lt : (x + k).toNat < n := by
          have h_eq : ((x + k).toNat : ℤ) = x + k := Int.toNat_of_nonneg (by omega)
          omega
        have h_sum_eq : x + k = ↑(x + k).toNat := by
          exact (Int.toNat_of_nonneg (by omega)).symm
        have h_dvd : x * k ∣ x^2 + k^2 + 2 := by
          use m
          calc x^2 + k^2 + 2 = m * x * k := hm_eq
            _ = x * k * m := by ring
        have ih_res := ih (x + k).toNat h_nat_lt x k hx_pos hk hkx h_sum_eq h_dvd
        have hm4 : m = 4 := by
          have hxk_pos : x * k > 0 := by nlinarith
          have H1 : m * x * k = 4 * x * k := by
            calc m * x * k = x^2 + k^2 + 2 := hm_eq.symm
              _ = 4 * x * k := ih_res
          have H2 : (m - 4) * (x * k) = 0 := by
            calc (m - 4) * (x * k) = m * x * k - 4 * x * k := by ring
              _ = 4 * x * k - 4 * x * k := by rw [H1]
              _ = 0 := by ring
          have H3 : m - 4 = 0 ∨ x * k = 0 := mul_eq_zero.mp H2
          rcases H3 with hm4_eq | hxk_zero
          · omega
          · linarith
        calc d^2 + k^2 + 2 = d * k * m := hm
          _ = d * k * 4 := by rw [hm4]
          _ = 4 * d * k := by ring

      · have hkx' : x < k := by omega
        have h_nat_lt : (k + x).toNat < n := by
          have h_eq : ((k + x).toNat : ℤ) = k + x := Int.toNat_of_nonneg (by omega)
          omega
        have h_sum_eq : k + x = ↑(k + x).toNat := by
          exact (Int.toNat_of_nonneg (by omega)).symm
        have h_dvd : k * x ∣ k^2 + x^2 + 2 := by
          use m
          calc k^2 + x^2 + 2 = x^2 + k^2 + 2 := by ring
            _ = m * x * k := hm_eq
            _ = k * x * m := by ring
        have ih_res := ih (k + x).toNat h_nat_lt k x hk hx_pos (by omega) h_sum_eq h_dvd
        have hm4 : m = 4 := by
          have hxk_pos : k * x > 0 := by nlinarith
          have H1 : m * k * x = 4 * k * x := by
            calc m * k * x = m * x * k := by ring
              _ = x^2 + k^2 + 2 := hm_eq.symm
              _ = k^2 + x^2 + 2 := by ring
              _ = 4 * k * x := ih_res
          have H2 : (m - 4) * (k * x) = 0 := by
            calc (m - 4) * (k * x) = m * k * x - 4 * k * x := by ring
              _ = 4 * k * x - 4 * k * x := by rw [H1]
              _ = 0 := by ring
          have H3 : m - 4 = 0 ∨ k * x = 0 := mul_eq_zero.mp H2
          rcases H3 with hm4_eq | hkx_zero
          · omega
          · linarith
        calc d^2 + k^2 + 2 = d * k * m := hm
          _ = d * k * 4 := by rw [hm4]
          _ = 4 * d * k := by ring

  by_cases h_le : k ≤ d
  · exact H_main (d + k).toNat d k hd hk h_le (by exact (Int.toNat_of_nonneg (by omega)).symm) h
  · have h_eq : k^2 + d^2 + 2 = 4 * k * d := by
      have h_sum_eq : k + d = ↑(k + d).toNat := by exact (Int.toNat_of_nonneg (by omega)).symm
      have h_dvd : k * d ∣ k^2 + d^2 + 2 := by
        obtain ⟨m, hm⟩ := h
        use m
        calc k^2 + d^2 + 2 = d^2 + k^2 + 2 := by ring
          _ = d * k * m := hm
          _ = k * d * m := by ring
      exact H_main (k + d).toNat k d hk hd (by omega) h_sum_eq h_dvd
    linarith

theorem int_not_mod_6_2_alt (d k : ℤ) (h : d^2 + k^2 + 2 = 4 * d * k) :
  (d * k) % 7 ≠ 6 :=
by
  intro h1
  have H : ∀ x y : ZMod 7, x^2 + y^2 + (2 : ZMod 7) = (4 : ZMod 7) * (x * y) → x * y ≠ (6 : ZMod 7) := by decide
  have h2 : ((d * k : ℤ) : ZMod 7) = ((6 : ℤ) : ZMod 7) := by
    apply (ZMod.intCast_eq_intCast_iff' (d * k) 6 7).mpr
    omega
  have h_eq : (d : ZMod 7)^2 + (k : ZMod 7)^2 + (2 : ZMod 7) = (4 : ZMod 7) * ((d : ZMod 7) * (k : ZMod 7)) := by
    calc (d : ZMod 7)^2 + (k : ZMod 7)^2 + (2 : ZMod 7)
      _ = ((d^2 + k^2 + 2 : ℤ) : ZMod 7) := by push_cast; ring
      _ = ((4 * d * k : ℤ) : ZMod 7) := by rw [h]
      _ = (4 : ZMod 7) * ((d : ZMod 7) * (k : ZMod 7)) := by push_cast; ring
  have h_eq6 : (d : ZMod 7) * (k : ZMod 7) = (6 : ZMod 7) := by
    calc (d : ZMod 7) * (k : ZMod 7)
      _ = ((d * k : ℤ) : ZMod 7) := by push_cast; ring
      _ = ((6 : ℤ) : ZMod 7) := h2
      _ = (6 : ZMod 7) := by norm_num
  exact H (d : ZMod 7) (k : ZMod 7) h_eq h_eq6

theorem r_bounds (r : ℕ → ℕ → ℕ) (hr : ∀ n d, r n d = (d + (n / d : ℕ)) ^ 2 % n) (n d k : ℕ) (hn : n = d * k) (hd : d > 0) (h7 : n % 7 = 6) : (r n d : ℤ) ≤ (n : ℤ) - 3 :=
by
  have h_r_eval : (r n d : ℤ) = ((d : ℤ)^2 + (k : ℤ)^2) % (n : ℤ) := by
    rw [hr n d]
    exact r_eq_mod_z_alt d k n hd hn

  have h_n_pos : (n : ℤ) > 0 := n_pos_from_mod_alt n h7
  have h_k_pos : (k : ℤ) > 0 := int_k_pos_alt n d k hn h7
  have hd_z : (d : ℤ) > 0 := by omega
  have hn_z : (n : ℤ) = (d : ℤ) * (k : ℤ) := zify_mul_alt n d k hn

  have R_bound : ((d : ℤ)^2 + (k : ℤ)^2) % (n : ℤ) < (n : ℤ) := int_mod_lt_alt ((d : ℤ)^2 + (k : ℤ)^2) (n : ℤ) h_n_pos

  have h_not_1 : ((d : ℤ)^2 + (k : ℤ)^2) % (n : ℤ) ≠ (n : ℤ) - 1 := by
    intro hc
    have hdvd := int_dvd_of_mod_eq_minus_alt ((d : ℤ)^2 + (k : ℤ)^2) (n : ℤ) (1 : ℤ) hc
    have hdvd' : (d : ℤ) * (k : ℤ) ∣ (d : ℤ)^2 + (k : ℤ)^2 + 1 := by
      rw [← hn_z]
      exact hdvd
    have hv := vieta_jump_1_alt (d : ℤ) (k : ℤ) hd_z h_k_pos hdvd'
    have hnot := int_not_mod_6_1_alt (d : ℤ) (k : ℤ) hv
    have heq : ((d : ℤ) * (k : ℤ)) % 7 = 6 := by
      rw [← hn_z]
      exact zmod_7_eq_6_of_nat_alt n h7
    exact hnot heq

  have h_not_2 : ((d : ℤ)^2 + (k : ℤ)^2) % (n : ℤ) ≠ (n : ℤ) - 2 := by
    intro hc
    have hdvd := int_dvd_of_mod_eq_minus_alt ((d : ℤ)^2 + (k : ℤ)^2) (n : ℤ) (2 : ℤ) hc
    have hdvd' : (d : ℤ) * (k : ℤ) ∣ (d : ℤ)^2 + (k : ℤ)^2 + 2 := by
      rw [← hn_z]
      exact hdvd
    have hv := vieta_jump_2_alt (d : ℤ) (k : ℤ) hd_z h_k_pos hdvd'
    have hnot := int_not_mod_6_2_alt (d : ℤ) (k : ℤ) hv
    have heq : ((d : ℤ) * (k : ℤ)) % 7 = 6 := by
      rw [← hn_z]
      exact zmod_7_eq_6_of_nat_alt n h7
    exact hnot heq

  omega

theorem PBAdvanced017 (r : ℕ → ℕ → ℕ) (hr : ∀ n d, r n d = (d + (n / d : ℕ)) ^ 2 % n) : IsLeast {(n - r n d : ℕ) | (n : ℕ) (d : ℕ) (_ : n % 7 = 6) (_ : d ∣ n)} 3 :=
by
  constructor
  · -- Show 3 is in the set for explicitly chosen n = 76 and d = 4
    refine ⟨76, 4, by rfl, ⟨19, rfl⟩, ?_⟩
    rw [hr]
    rfl
  · -- Show that any valid element in the set is bounded below by 3
    rintro x ⟨n, d, h7, hd, rfl⟩
    rcases hd with ⟨k, hk⟩
    have hd0 : d > 0 := by
      by_contra h
      have h_d : d = 0 := by omega
      subst h_d
      have h_n : n = 0 := by omega
      revert h7
      rw [h_n]
      decide
    have h_bound := r_bounds r hr n d k hk hd0 h7
    -- `omega` transparently handles the connection between ℕ subtraction definitions and ℤ bounds
    omega
