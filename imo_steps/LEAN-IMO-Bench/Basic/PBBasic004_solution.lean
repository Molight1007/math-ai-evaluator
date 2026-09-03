import Mathlib

theorem PBBasic004 : {g : ℝ → ℝ | StrictMono g ∧ g.Surjective ∧ ∀ x, g (g x) = g x + 20 * x} = {(fun x ↦ 5 * x)} :=
by
  ext g
  simp only [Set.mem_setOf_eq, Set.mem_singleton_iff]
  constructor
  · rintro ⟨h_mono, h_surj, h_eq⟩
    have hg0 : g 0 = 0 := by
      have h1 := h_eq 0
      have h2 : g (g 0) = g 0 + 20 * 0 := h1
      rw [mul_zero, add_zero] at h2
      exact h_mono.injective h2

    let g_iso := StrictMono.orderIsoOfSurjective g h_mono h_surj
    let h := g_iso.symm
    have hg_eq : ⇑g_iso = g := StrictMono.coe_orderIsoOfSurjective g h_mono h_surj

    have h_gh : ∀ x, g (h x) = x := by
      intro x
      have h1 := g_iso.apply_symm_apply x
      calc g (h x) = ⇑g_iso (h x) := by rw [hg_eq]
        _ = x := h1

    have h_hg : ∀ x, h (g x) = x := by
      intro x
      have h1 := g_iso.symm_apply_apply x
      calc h (g x) = h (⇑g_iso x) := by rw [hg_eq]
        _ = x := h1

    have hh0 : h 0 = 0 := by
      apply h_mono.injective
      rw [h_gh, hg0]

    have h_mono_h : StrictMono h := g_iso.symm.strictMono

    let k : ℝ → ℝ := fun x ↦ g x - 5 * x
    let m : ℝ → ℝ := fun x ↦ g x + 4 * x

    have hm : ∀ x, m (g x) = 5 * m x := by
      intro x
      change g (g x) + 4 * g x = 5 * (g x + 4 * x)
      rw [h_eq x]
      ring

    have hk : ∀ x, k (g x) = -4 * k x := by
      intro x
      change g (g x) - 5 * g x = -4 * (g x - 5 * x)
      rw [h_eq x]
      ring

    have hmh : ∀ x, m (h x) = (1 / 5 : ℝ) * m x := by
      intro x
      have h1 := hm (h x)
      rw [h_gh] at h1
      linarith

    have hkh : ∀ x, k (h x) = (-1 / 4 : ℝ) * k x := by
      intro x
      have h1 := hk (h x)
      rw [h_gh] at h1
      linarith

    have h_hm_iter : ∀ n : ℕ, ∀ x, m (h^[n] x) = (1 / 5 : ℝ)^n * m x := by
      intro n
      induction n with
      | zero =>
        intro x
        simp
      | succ n ih =>
        intro x
        rw [Function.iterate_succ_apply]
        rw [ih (h x)]
        rw [hmh x]
        ring

    have h_hk_iter : ∀ n : ℕ, ∀ x, k (h^[n] x) = (-1 / 4 : ℝ)^n * k x := by
      intro n
      induction n with
      | zero =>
        intro x
        simp
      | succ n ih =>
        intro x
        rw [Function.iterate_succ_apply]
        rw [ih (h x)]
        rw [hkh x]
        ring

    have h_h_expr : ∀ n : ℕ, ∀ x, h^[n] x = ((1 / 5 : ℝ)^n * m x - (-1 / 4 : ℝ)^n * k x) / (9 : ℝ) := by
      intro n x
      have eq_m := h_hm_iter n x
      have eq_k := h_hk_iter n x
      have h_diff : m (h^[n] x) - k (h^[n] x) = 9 * h^[n] x := by
        change (g (h^[n] x) + 4 * h^[n] x) - (g (h^[n] x) - 5 * h^[n] x) = 9 * h^[n] x
        ring
      rw [eq_m, eq_k] at h_diff
      linarith

    have h_sign_pos : ∀ n : ℕ, ∀ x > (0 : ℝ), h^[n] x > 0 := by
      intro n
      induction n with
      | zero =>
        intro x hx
        exact hx
      | succ n ih =>
        intro x hx
        rw [Function.iterate_succ_apply]
        apply ih
        have h_mono_h_pos : h 0 < h x := h_mono_h hx
        rw [hh0] at h_mono_h_pos
        exact h_mono_h_pos

    have h_sign_neg : ∀ n : ℕ, ∀ x < (0 : ℝ), h^[n] x < 0 := by
      intro n
      induction n with
      | zero =>
        intro x hx
        exact hx
      | succ n ih =>
        intro x hx
        rw [Function.iterate_succ_apply]
        apply ih
        have h_mono_h_neg : h x < h 0 := h_mono_h hx
        rw [hh0] at h_mono_h_neg
        exact h_mono_h_neg

    have h_bound : ∀ n : ℕ, ∀ x, (5 : ℝ)^n * 9 * h^[n] x = m x - (-5 / 4 : ℝ)^n * k x := by
      intro n x
      have eq := h_h_expr n x
      have h1 : (5 : ℝ)^n * (1 / 5 : ℝ)^n = (5 * (1 / 5 : ℝ))^n := (mul_pow (5 : ℝ) (1 / 5 : ℝ) n).symm
      have h2 : (5 : ℝ)^n * (-1 / 4 : ℝ)^n = (5 * (-1 / 4 : ℝ))^n := (mul_pow (5 : ℝ) (-1 / 4 : ℝ) n).symm
      have h3 : 5 * (1 / 5 : ℝ) = 1 := by norm_num
      have h4 : 5 * (-1 / 4 : ℝ) = -5 / 4 := by norm_num
      rw [h3] at h1
      rw [h4] at h2
      have h1' : (5 : ℝ)^n * (1 / 5 : ℝ)^n = 1 := by rw [h1, one_pow]
      calc (5 : ℝ)^n * 9 * h^[n] x
        _ = (5 : ℝ)^n * 9 * (((1 / 5 : ℝ)^n * m x - (-1 / 4 : ℝ)^n * k x) / (9 : ℝ)) := by rw [eq]
        _ = (5 : ℝ)^n * (1 / 5 : ℝ)^n * m x - (5 : ℝ)^n * (-1 / 4 : ℝ)^n * k x := by ring
        _ = 1 * m x - (-5 / 4 : ℝ)^n * k x := by rw [h1', h2]
        _ = m x - (-5 / 4 : ℝ)^n * k x := by ring

    have h_bern : ∀ n : ℕ, 1 + (n : ℝ) * (1 / 4 : ℝ) ≤ (5 / 4 : ℝ) ^ n := by
      intro n
      induction n with
      | zero => norm_num
      | succ n ih =>
        have h_mul : (1 + (n : ℝ) * (1 / 4 : ℝ)) * (5 / 4 : ℝ) ≤ (5 / 4 : ℝ) ^ n * (5 / 4 : ℝ) :=
          mul_le_mul_of_nonneg_right ih (by norm_num)
        calc 1 + (↑(n + 1) : ℝ) * (1 / 4 : ℝ)
          _ = 1 + ((n : ℝ) + 1) * (1 / 4 : ℝ) := by push_cast; rfl
          _ = 1 + (n : ℝ) * (1 / 4 : ℝ) + (1 / 4 : ℝ) := by ring
          _ ≤ 1 + (n : ℝ) * (1 / 4 : ℝ) + (1 / 4 : ℝ) + (n : ℝ) * (1 / 16 : ℝ) := by
            have : 0 ≤ (n : ℝ) * (1 / 16 : ℝ) := by positivity
            linarith
          _ = (1 + (n : ℝ) * (1 / 4 : ℝ)) * (5 / 4 : ℝ) := by ring
          _ ≤ (5 / 4 : ℝ) ^ n * (5 / 4 : ℝ) := h_mul
          _ = (5 / 4 : ℝ) ^ (n + 1) := by rw [pow_add, pow_one]

    have h_exists_even : ∀ C : ℝ, ∃ k : ℕ, C < (5 / 4 : ℝ) ^ (2 * k) := by
      intro C
      obtain ⟨k, hk⟩ := exists_nat_gt (4 * (C - 1))
      use k
      have hk_cast : 4 * (C - 1) < (k : ℝ) := hk
      have hk_ineq : C < 1 + ↑(2 * k) * (1 / 4 : ℝ) := by
        have h_k_le : (k : ℝ) ≤ ↑(2 * k) := by
          push_cast
          linarith [show 0 ≤ (k : ℝ) from Nat.cast_nonneg k]
        linarith
      have h_b := h_bern (2 * k)
      linarith

    have h_exists_odd : ∀ C : ℝ, ∃ k : ℕ, C < (5 / 4 : ℝ) ^ (2 * k + 1) := by
      intro C
      obtain ⟨k, hk⟩ := exists_nat_gt (4 * (C - 1))
      use k
      have hk_cast : 4 * (C - 1) < (k : ℝ) := hk
      have hk_ineq : C < 1 + ↑(2 * k + 1) * (1 / 4 : ℝ) := by
        have h_k_le : (k : ℝ) ≤ ↑(2 * k + 1) := by
          push_cast
          linarith [show 0 ≤ (k : ℝ) from Nat.cast_nonneg k]
        linarith
      have h_b := h_bern (2 * k + 1)
      linarith

    have h_k_zero_pos : ∀ y > 0, k y = 0 := by
      intro y hy
      by_contra hk_ne
      rcases lt_trichotomy 0 (k y) with hk_pos | hk_zero | hk_neg
      · obtain ⟨n, hn⟩ := h_exists_even (m y / k y)
        have h_pos2 := h_sign_pos (2 * n) y hy
        have h_b := h_bound (2 * n) y
        have h_pow : (-5 / 4 : ℝ) ^ (2 * n) = (5 / 4 : ℝ) ^ (2 * n) := by
          have h_sq : (-5 / 4 : ℝ) ^ 2 = (5 / 4 : ℝ) ^ 2 := by norm_num
          calc (-5 / 4 : ℝ) ^ (2 * n) = ((-5 / 4 : ℝ) ^ 2) ^ n := by rw [pow_mul]
            _ = ((5 / 4 : ℝ) ^ 2) ^ n := by rw [h_sq]
            _ = (5 / 4 : ℝ) ^ (2 * n) := by rw [←pow_mul]
        rw [h_pow] at h_b
        have h_pos3 : 0 < (5 : ℝ) ^ (2 * n) * 9 * h^[2 * n] y := by positivity
        have h_lt : (5 / 4 : ℝ) ^ (2 * n) * k y < m y := by
          have h_eq : (5 / 4 : ℝ) ^ (2 * n) * k y = m y - (m y - (5 / 4 : ℝ) ^ (2 * n) * k y) := by ring
          rw [h_eq, ←h_b]
          exact sub_lt_self (m y) h_pos3
        have h_lt2 : (5 / 4 : ℝ) ^ (2 * n) < m y / k y := (lt_div_iff₀ hk_pos).mpr h_lt
        linarith
      · exact hk_ne hk_zero.symm
      · obtain ⟨n, hn⟩ := h_exists_odd (m y / (- k y))
        have h_pos2 := h_sign_pos (2 * n + 1) y hy
        have h_b := h_bound (2 * n + 1) y
        have h_pow : (-5 / 4 : ℝ) ^ (2 * n + 1) = - (5 / 4 : ℝ) ^ (2 * n + 1) := by
          calc (-5 / 4 : ℝ) ^ (2 * n + 1) = (-5 / 4 : ℝ) ^ (2 * n) * (-5 / 4 : ℝ) := by rw [pow_add, pow_one]
            _ = (5 / 4 : ℝ) ^ (2 * n) * (-5 / 4 : ℝ) := by
              have h_even : (-5 / 4 : ℝ) ^ (2 * n) = (5 / 4 : ℝ) ^ (2 * n) := by
                have h_sq : (-5 / 4 : ℝ) ^ 2 = (5 / 4 : ℝ) ^ 2 := by norm_num
                calc (-5 / 4 : ℝ) ^ (2 * n) = ((-5 / 4 : ℝ) ^ 2) ^ n := by rw [pow_mul]
                  _ = ((5 / 4 : ℝ) ^ 2) ^ n := by rw [h_sq]
                  _ = (5 / 4 : ℝ) ^ (2 * n) := by rw [←pow_mul]
              rw [h_even]
            _ = - ((5 / 4 : ℝ) ^ (2 * n) * (5 / 4 : ℝ)) := by ring
            _ = - (5 / 4 : ℝ) ^ (2 * n + 1) := by rw [pow_add, pow_one]
        rw [h_pow] at h_b
        have h_pos3 : 0 < (5 : ℝ) ^ (2 * n + 1) * 9 * h^[2 * n + 1] y := by positivity
        have h_lt : (5 / 4 : ℝ) ^ (2 * n + 1) * (- k y) < m y := by
          have h_eq : (5 / 4 : ℝ) ^ (2 * n + 1) * (- k y) = m y - (m y - - (5 / 4 : ℝ) ^ (2 * n + 1) * k y) := by ring
          rw [h_eq, ←h_b]
          exact sub_lt_self (m y) h_pos3
        have hk_neg_pos : 0 < - k y := by linarith
        have h_lt2 : (5 / 4 : ℝ) ^ (2 * n + 1) < m y / (- k y) := (lt_div_iff₀ hk_neg_pos).mpr h_lt
        linarith

    have h_k_zero_neg : ∀ y < 0, k y = 0 := by
      intro y hy
      by_contra hk_ne
      rcases lt_trichotomy 0 (k y) with hk_pos | hk_zero | hk_neg
      · obtain ⟨n, hn⟩ := h_exists_odd ((- m y) / k y)
        have h_neg1 := h_sign_neg (2 * n + 1) y hy
        have h_b := h_bound (2 * n + 1) y
        have h_pow : (-5 / 4 : ℝ) ^ (2 * n + 1) = - (5 / 4 : ℝ) ^ (2 * n + 1) := by
          calc (-5 / 4 : ℝ) ^ (2 * n + 1) = (-5 / 4 : ℝ) ^ (2 * n) * (-5 / 4 : ℝ) := by rw [pow_add, pow_one]
            _ = (5 / 4 : ℝ) ^ (2 * n) * (-5 / 4 : ℝ) := by
              have h_even : (-5 / 4 : ℝ) ^ (2 * n) = (5 / 4 : ℝ) ^ (2 * n) := by
                have h_sq : (-5 / 4 : ℝ) ^ 2 = (5 / 4 : ℝ) ^ 2 := by norm_num
                calc (-5 / 4 : ℝ) ^ (2 * n) = ((-5 / 4 : ℝ) ^ 2) ^ n := by rw [pow_mul]
                  _ = ((5 / 4 : ℝ) ^ 2) ^ n := by rw [h_sq]
                  _ = (5 / 4 : ℝ) ^ (2 * n) := by rw [←pow_mul]
              rw [h_even]
            _ = - ((5 / 4 : ℝ) ^ (2 * n) * (5 / 4 : ℝ)) := by ring
            _ = - (5 / 4 : ℝ) ^ (2 * n + 1) := by rw [pow_add, pow_one]
        rw [h_pow] at h_b
        have h_neg2 : (5 : ℝ) ^ (2 * n + 1) * 9 * h^[2 * n + 1] y < 0 := by
          have hp : 0 < (5 : ℝ) ^ (2 * n + 1) * 9 := by positivity
          exact mul_neg_of_pos_of_neg hp h_neg1
        have h_lt : (5 / 4 : ℝ) ^ (2 * n + 1) * k y < - m y := by
          have h_eq : (5 / 4 : ℝ) ^ (2 * n + 1) * k y = (m y - - (5 / 4 : ℝ) ^ (2 * n + 1) * k y) - m y := by ring
          rw [←h_b] at h_eq
          rw [h_eq]
          linarith
        have h_lt2 : (5 / 4 : ℝ) ^ (2 * n + 1) < (- m y) / k y := (lt_div_iff₀ hk_pos).mpr h_lt
        linarith
      · exact hk_ne hk_zero.symm
      · obtain ⟨n, hn⟩ := h_exists_even ((- m y) / (- k y))
        have h_neg1 := h_sign_neg (2 * n) y hy
        have h_b := h_bound (2 * n) y
        have h_pow : (-5 / 4 : ℝ) ^ (2 * n) = (5 / 4 : ℝ) ^ (2 * n) := by
          have h_sq : (-5 / 4 : ℝ) ^ 2 = (5 / 4 : ℝ) ^ 2 := by norm_num
          calc (-5 / 4 : ℝ) ^ (2 * n) = ((-5 / 4 : ℝ) ^ 2) ^ n := by rw [pow_mul]
            _ = ((5 / 4 : ℝ) ^ 2) ^ n := by rw [h_sq]
            _ = (5 / 4 : ℝ) ^ (2 * n) := by rw [←pow_mul]
        rw [h_pow] at h_b
        have h_neg2 : (5 : ℝ) ^ (2 * n) * 9 * h^[2 * n] y < 0 := by
          have hp : 0 < (5 : ℝ) ^ (2 * n) * 9 := by positivity
          exact mul_neg_of_pos_of_neg hp h_neg1
        have h_lt : (5 / 4 : ℝ) ^ (2 * n) * (- k y) < - m y := by
          have h_eq : (5 / 4 : ℝ) ^ (2 * n) * (- k y) = (m y - (5 / 4 : ℝ) ^ (2 * n) * k y) - m y := by ring
          rw [←h_b] at h_eq
          rw [h_eq]
          linarith
        have hk_neg_pos : 0 < - k y := by linarith
        have h_lt2 : (5 / 4 : ℝ) ^ (2 * n) < (- m y) / (- k y) := (lt_div_iff₀ hk_neg_pos).mpr h_lt
        linarith

    have h_k_zero_all : ∀ y, k y = 0 := by
      intro y
      rcases lt_trichotomy y 0 with hy_neg | hy_zero | hy_pos
      · exact h_k_zero_neg y hy_neg
      · rw [hy_zero]
        change g 0 - 5 * 0 = 0
        rw [hg0]
        ring
      · exact h_k_zero_pos y hy_pos

    ext x
    have hkx := h_k_zero_all x
    change g x - 5 * x = 0 at hkx
    linarith

  · rintro rfl
    simp only [Set.mem_setOf_eq, Set.mem_singleton_iff]
    refine ⟨?_, ?_, ?_⟩
    · intro a b hab
      change 5 * a < 5 * b
      linarith
    · intro y
      use y / (5 : ℝ)
      change 5 * (y / (5 : ℝ)) = y
      ring
    · intro x
      change 5 * (5 * x) = 5 * x + 20 * x
      ring
