import Mathlib

theorem PBBasic003 : {f : ℝ → ℝ | ∀ a b, (b - a) * f (f a) = a * f (a + f b)}
      = {0} ∪ {(fun x ↦ - x + k) | (k : ℝ)} :=
by
  ext f
  simp only [Set.mem_setOf_eq, Set.mem_union, Set.mem_singleton_iff, Set.mem_range]
  constructor
  · intro h
    have h1 : ∀ b, b * f (f 0) = 0 := by
      intro b
      have hb := h 0 b
      calc b * f (f 0) = (b - 0) * f (f 0) := by ring
      _ = 0 * f (0 + f b) := hb
      _ = 0 := by ring
    have h2 : f (f 0) = 0 := by
      have h1_1 := h1 1
      calc f (f 0) = 1 * f (f 0) := by ring
      _ = 0 := h1_1
    let c := f 0
    have hf0_def : f 0 = c := rfl
    have hc_val : f c = 0 := h2
    by_cases hc : c = 0
    · have hf0 : f 0 = 0 := by rw [hf0_def, hc]
      have h3 : ∀ a, f (f a) = - f a := by
        intro a
        rcases eq_or_ne a 0 with rfl | ha
        · calc f (f 0) = 0 := h2
          _ = - 0 := by ring
          _ = - f 0 := by rw [hf0]
        · have h_a0 := h a 0
          have eq_h : (0 - a) * f (f a) = a * f a := by
            calc (0 - a) * f (f a) = a * f (a + f 0) := h_a0
            _ = a * f (a + 0) := by rw [hf0]
            _ = a * f a := by rw [add_zero]
          have eq_h2 : a * f (f a) = a * (- f a) := by
            calc a * f (f a) = - ((0 - a) * f (f a)) := by ring
            _ = - (a * f a) := by rw [eq_h]
            _ = a * (- f a) := by ring
          exact mul_left_cancel₀ ha eq_h2
      have h4 : ∀ a b, (a - b) * f a = a * f (a + f b) := by
        intro a b
        have hab := h a b
        calc (a - b) * f a = (b - a) * (- f a) := by ring
        _ = (b - a) * f (f a) := by rw [← h3 a]
        _ = a * f (a + f b) := hab
      by_cases hf : f = 0
      · left; exact hf
      · right
        use 0
        ext x
        have hf_ne : ∃ a₀, f a₀ ≠ 0 := by
          by_contra! h_contra
          apply hf
          ext a
          exact h_contra a
        rcases hf_ne with ⟨a₀, ha₀⟩
        have h_surj : Function.Surjective f := by
          intro y
          let b := a₀ - y * a₀ / f a₀
          use a₀ + f b
          have hab := h4 a₀ b
          have ha₀_ne_0 : a₀ ≠ 0 := by
            rintro rfl
            exact ha₀ hf0
          have hfa₀_ne_0 : f a₀ ≠ 0 := ha₀
          have eq1 : (a₀ - b) * f a₀ = y * a₀ := by
            calc (a₀ - b) * f a₀ = (a₀ - (a₀ - y * a₀ / f a₀)) * f a₀ := rfl
            _ = (y * a₀ / f a₀) * f a₀ := by
              have : a₀ - (a₀ - y * a₀ / f a₀) = y * a₀ / f a₀ := by ring
              rw [this]
            _ = y * a₀ := div_mul_cancel₀ (y * a₀) hfa₀_ne_0
          have eq2 : a₀ * y = a₀ * f (a₀ + f b) := by
            calc a₀ * y = y * a₀ := mul_comm a₀ y
            _ = (a₀ - b) * f a₀ := eq1.symm
            _ = a₀ * f (a₀ + f b) := hab
          exact (mul_left_cancel₀ ha₀_ne_0 eq2).symm
        rcases h_surj x with ⟨y, hy⟩
        have h_fx : f x = - x + 0 := by
          calc f x = f (f y) := by rw [← hy]
          _ = - f y := h3 y
          _ = - x := by rw [hy]
          _ = - x + 0 := by ring
        rw [h_fx]
    · right
      use c
      ext x
      have hc_ne : c ≠ 0 := hc
      have hf0 : f 0 = c := rfl
      have h_surj : Function.Surjective f := by
        intro y
        use c + f (y + c)
        have hcb := h c (y + c)
        have hf0_sub : f (f c) = c := by
          calc f (f c) = f 0 := by rw [hc_val]
          _ = c := rfl
        have eq0 : (y + c - c) * c = c * f (c + f (y + c)) := by
          calc (y + c - c) * c = (y + c - c) * f (f c) := by rw [hf0_sub]
          _ = c * f (c + f (y + c)) := hcb
        have eq1 : c * y = c * f (c + f (y + c)) := by
          calc c * y = (y + c - c) * c := by ring
          _ = c * f (c + f (y + c)) := eq0
        exact (mul_left_cancel₀ hc_ne eq1).symm
      have h_inj : Function.Injective f := by
        intro u v huv
        rcases h_surj (u - c) with ⟨bu, hbu⟩
        rcases h_surj (v - c) with ⟨bv, hbv⟩
        have hu : u = c + f bu := by linarith [hbu]
        have hv : v = c + f bv := by linarith [hbv]
        have hcu := h c bu
        have hcv := h c bv
        have hf0_sub : f (f c) = c := by
          calc f (f c) = f 0 := by rw [hc_val]
          _ = c := rfl
        have eq_u : (bu - c) * c = c * f u := by
          calc (bu - c) * c = (bu - c) * f (f c) := by rw [hf0_sub]
          _ = c * f (c + f bu) := hcu
          _ = c * f u := by rw [← hu]
        have eq_v : (bv - c) * c = c * f v := by
          calc (bv - c) * c = (bv - c) * f (f c) := by rw [hf0_sub]
          _ = c * f (c + f bv) := hcv
          _ = c * f v := by rw [← hv]
        have eq_uv : (bu - c) * c = (bv - c) * c := by
          calc (bu - c) * c = c * f u := eq_u
          _ = c * f v := by rw [huv]
          _ = (bv - c) * c := eq_v.symm
        have eq_uv2 : bu - c = bv - c := mul_right_cancel₀ hc_ne eq_uv
        have eq_uv3 : bu = bv := by linarith [eq_uv2]
        calc u = c + f bu := hu
        _ = c + f bv := by rw [eq_uv3]
        _ = v := hv.symm
      have h_root : ∀ a, f a = 0 ↔ a = c := by
        intro a
        constructor
        · intro ha
          have : f a = f c := by rw [ha, hc_val]
          exact h_inj this
        · intro ha
          rw [ha, hc_val]
      have h_fa : ∀ a, a ≠ 0 → a ≠ c → f a = c - a := by
        intro a ha0 hac_ne
        rcases h_surj (c - a) with ⟨b, hb⟩
        have hab := h a b
        have eq1 : (b - a) * f (f a) = 0 := by
          calc (b - a) * f (f a) = a * f (a + f b) := hab
          _ = a * f (a + (c - a)) := by rw [hb]
          _ = a * f c := by
            have : a + (c - a) = c := by ring
            rw [this]
          _ = a * 0 := by rw [hc_val]
          _ = 0 := by ring
        have hfa_ne_c : f a ≠ c := by
          intro contra
          have : f a = f 0 := by rw [contra, ← hf0]
          have eq_a : a = 0 := h_inj this
          exact ha0 eq_a
        have hffa_ne_0 : f (f a) ≠ 0 := by
          intro contra
          have := (h_root (f a)).mp contra
          exact hfa_ne_c this
        have eq2 : b - a = 0 := by
          cases mul_eq_zero.mp eq1 with
          | inl h1 => exact h1
          | inr h2 => exact False.elim (hffa_ne_0 h2)
        have eq3 : b = a := by linarith [eq2]
        rw [eq3] at hb
        exact hb
      rcases eq_or_ne x 0 with rfl | ha0
      · have h_fx : f 0 = - 0 + c := by
          calc f 0 = c := rfl
          _ = - 0 + c := by ring
        rw [h_fx]
      · rcases eq_or_ne x c with rfl | hac_ne
        · have h_fx : f c = - c + c := by
            calc f c = 0 := hc_val
            _ = - c + c := by ring
          rw [h_fx]
        · have h_fx : f x = - x + c := by
            calc f x = c - x := h_fa x ha0 hac_ne
            _ = - x + c := by ring
          rw [h_fx]
  · intro h
    rcases h with rfl | ⟨k, rfl⟩
    · intro a b
      simp only [Pi.zero_apply]
      ring
    · intro a b
      dsimp only
      ring
