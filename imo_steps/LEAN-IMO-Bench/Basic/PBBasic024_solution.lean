import Mathlib

theorem PBBasic024 : {(a, b, c) : ℕ × ℕ × ℕ | 20 ^ a + b ^ 4 = 2024 ^ c}
      = {(0, 0, 0)} :=
by
  ext ⟨a, b, c⟩
  simp only [Set.mem_setOf_eq, Set.mem_singleton_iff, Prod.mk.injEq]
  constructor
  · intro h
    cases c with
    | zero =>
      rw [pow_zero] at h
      cases a with
      | zero =>
        rw [pow_zero] at h
        have hb : b = 0 := by
          by_contra h_b
          have h_pos : b > 0 := by omega
          have h_pow : b ^ 4 > 0 := by positivity
          omega
        rw [hb]
        exact ⟨rfl, rfl, rfl⟩
      | succ a' =>
        rw [pow_succ] at h
        have h4 : 20 ^ a' > 0 := by positivity
        omega
    | succ c' =>
      have h_zero : ((2024 ^ (c' + 1) : ℕ) : ZMod 11) = 0 := by
        calc ((2024 ^ (c' + 1) : ℕ) : ZMod 11) = (2024 : ZMod 11) ^ (c' + 1) := by push_cast; rfl
        _ = 0 ^ (c' + 1) := by
          have h2024 : (2024 : ZMod 11) = 0 := rfl
          rw [h2024]
        _ = 0 := by
          rw [pow_succ]
          ring
      have h_mod2 : (20 : ZMod 11) ^ a + (b : ZMod 11) ^ 4 = 0 := by
        calc (20 : ZMod 11) ^ a + (b : ZMod 11) ^ 4 = ((20 ^ a + b ^ 4 : ℕ) : ZMod 11) := by push_cast; rfl
        _ = ((2024 ^ (c' + 1) : ℕ) : ZMod 11) := by rw [h]
        _ = 0 := h_zero

      -- Isolate the modulo 11 cycle of 20^a into a standalone hypothesis
      have H1 : ∀ k : ℕ, (20 : ZMod 11) ^ k = (1 : ZMod 11) ∨ (20 : ZMod 11) ^ k = (3 : ZMod 11) ∨ (20 : ZMod 11) ^ k = (4 : ZMod 11) ∨ (20 : ZMod 11) ^ k = (5 : ZMod 11) ∨ (20 : ZMod 11) ^ k = (9 : ZMod 11) := by
        intro k
        induction k with
        | zero =>
          left
          rfl
        | succ k' ih =>
          rcases ih with hA | hA | hA | hA | hA
          · right; right; right; right; rw [pow_succ, hA]; rfl
          · right; right; right; left; rw [pow_succ, hA]; rfl
          · right; left; rw [pow_succ, hA]; rfl
          · left; rw [pow_succ, hA]; rfl
          · right; right; left; rw [pow_succ, hA]; rfl

      rcases H1 a with hA | hA | hA | hA | hA
      · rw [hA] at h_mod2
        have H_dec : ∀ y : ZMod 11, (1 : ZMod 11) + y ^ 4 ≠ 0 := by decide
        exfalso
        exact H_dec (b : ZMod 11) h_mod2
      · rw [hA] at h_mod2
        have H_dec : ∀ y : ZMod 11, (3 : ZMod 11) + y ^ 4 ≠ 0 := by decide
        exfalso
        exact H_dec (b : ZMod 11) h_mod2
      · rw [hA] at h_mod2
        have H_dec : ∀ y : ZMod 11, (4 : ZMod 11) + y ^ 4 ≠ 0 := by decide
        exfalso
        exact H_dec (b : ZMod 11) h_mod2
      · rw [hA] at h_mod2
        have H_dec : ∀ y : ZMod 11, (5 : ZMod 11) + y ^ 4 ≠ 0 := by decide
        exfalso
        exact H_dec (b : ZMod 11) h_mod2
      · rw [hA] at h_mod2
        have H_dec : ∀ y : ZMod 11, (9 : ZMod 11) + y ^ 4 ≠ 0 := by decide
        exfalso
        exact H_dec (b : ZMod 11) h_mod2
  · rintro ⟨ha, hb, hc⟩
    rw [ha, hb, hc]
    rfl
