import Mathlib

theorem f_zero_or_one_or_id_like (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) :
  f = (fun _ => 0) ∨ f = (fun _ => 1) ∨ (f 0 = 0 ∧ f 1 = 1) :=
by
  by_cases h0 : f 0 = 0
  · -- Case f 0 = 0
    have h_fx_f1 (x : ℤ) : f x = f x * f 1 := by
      have h := H x 0
      have e1 : x * (0:ℤ) = 0 := by ring
      have e2 : (1:ℤ) - 0 = 1 := by ring
      have e3 : x - 0 = x := by ring
      rw [e1, h0, e3, e2] at h
      exact h
    by_cases h1 : f 1 = 1
    · -- Case f 1 = 1
      right
      right
      exact ⟨h0, h1⟩
    · -- Case f 1 ≠ 1
      have h_f1_ne_0 : (1:ℤ) - f 1 ≠ 0 := by
        intro contra
        apply h1
        linarith
      have H_fx_0 (x : ℤ) : f x = 0 := by
        have h := h_fx_f1 x
        have h_mul : f x * ((1:ℤ) - f 1) = 0 := by
          calc
            f x * ((1:ℤ) - f 1) = f x - f x * f 1 := by ring
            _ = f x - f x := by rw [← h]
            _ = 0 := by ring
        cases mul_eq_zero.mp h_mul with
        | inl h_fx => exact h_fx
        | inr h_f1 =>
          exfalso
          exact h_f1_ne_0 h_f1
      left
      ext x
      exact H_fx_0 x
  · -- Case f 0 ≠ 0
    have H_0_x (x : ℤ) : f 0 * f x = f (- f 0) := by
      have h := H 0 ((1:ℤ) - x)
      have e1 : (0:ℤ) * ((1:ℤ) - x) = 0 := by ring
      have e2 : (1:ℤ) - ((1:ℤ) - x) = x := by ring
      have e3 : (0:ℤ) - f 0 = - f 0 := by ring
      rw [e1, e3, e2] at h
      exact h.symm
    have H_fx (x : ℤ) : f 0 * f x = f 0 * f 0 := by
      calc
        f 0 * f x = f (- f 0) := H_0_x x
        _ = f 0 * f 0 := (H_0_x 0).symm
    have H_f (x : ℤ) : f x = f 0 := by
      have h_mul := H_fx x
      have h_mul_sub : f 0 * (f x - f 0) = 0 := by
        calc
          f 0 * (f x - f 0) = f 0 * f x - f 0 * f 0 := by ring
          _ = f 0 * f 0 - f 0 * f 0 := by rw [h_mul]
          _ = 0 := by ring
      cases mul_eq_zero.mp h_mul_sub with
      | inl h_f0_eq_0 =>
        exfalso
        exact h0 h_f0_eq_0
      | inr h_fx_sub_f0_eq_0 =>
        linarith
    have h_f0 : f 0 = 1 := by
      have h_H00 := H 0 0
      have e1 : (0:ℤ) * 0 = 0 := by ring
      have e2 : (1:ℤ) - 0 = 1 := by ring
      have e3 : (0:ℤ) - f 0 = - f 0 := by ring
      rw [e1, e3, e2] at h_H00
      have h1 : f (- f 0) = f 0 := H_f (- f 0)
      have h2 : f 1 = f 0 := H_f 1
      rw [h1, h2] at h_H00
      have h_mul_sub : f 0 * ((1:ℤ) - f 0) = 0 := by
        calc
          f 0 * ((1:ℤ) - f 0) = f 0 - f 0 * f 0 := by ring
          _ = f 0 - f 0 := by rw [← h_H00]
          _ = 0 := by ring
      cases mul_eq_zero.mp h_mul_sub with
      | inl h_f0_eq_0 =>
        exfalso
        exact h0 h_f0_eq_0
      | inr h_1_sub_f0_eq_0 =>
        linarith
    have H_f1 (x : ℤ) : f x = 1 := by
      calc
        f x = f 0 := H_f x
        _ = 1 := h_f0
    right
    left
    ext x
    exact H_f1 x

theorem f_neg1_ne_zero (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  f (-1) ≠ 0 :=
by
  intro h
  have h2 : f (2 : ℤ) = 1 := by
    have h_eval := H (1 : ℤ) (-1 : ℤ)
    have e1 : (1 : ℤ) * (-1 : ℤ) = -1 := by norm_num
    have e2 : (1 : ℤ) - (-1 : ℤ) = 2 := by norm_num
    have e3 : (1 : ℤ) - (0 : ℤ) = 1 := by norm_num
    rw [e1, e2, h, e3, H1] at h_eval
    have e4 : (1 : ℤ) * f (2 : ℤ) = f (2 : ℤ) := by ring
    rw [e4] at h_eval
    exact h_eval.symm

  have h3 : (1 : ℤ) = 0 := by
    have h_eval := H (2 : ℤ) (1 : ℤ)
    have e5 : (2 : ℤ) * (1 : ℤ) = 2 := by norm_num
    have e6 : (1 : ℤ) - (1 : ℤ) = 0 := by norm_num
    rw [e5, e6, h2, H0] at h_eval
    have e7 : (2 : ℤ) - (1 : ℤ) = 1 := by norm_num
    have e8 : (1 : ℤ) * (0 : ℤ) = 0 := by norm_num
    rw [e7, e8, H1] at h_eval
    exact h_eval

  omega

theorem f_eq_implies_shift (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  ∀ u v c, f u = f v → f (u + c) = f (v + c) :=
by
  have H_xfx : ∀ x, f (x - f x) = 0 := by
    intro x
    have h := H x 1
    have e : (1 : ℤ) - 1 = 0 := by omega
    have e2 : x * 1 = x := by omega
    rw [e, e2, H0, mul_zero] at h
    exact h

  have H_1_fy : ∀ y, f (1 - f y) = f (1 - y) := by
    intro y
    have h := H 1 y
    have e : 1 * y = y := by omega
    rw [e, H1, one_mul] at h
    exact h

  have h_f_neg1 : f (-1) ≠ 0 := by
    intro h_neg1
    have h_f2 : f 2 = 1 := by
      have h := H_1_fy (-1)
      rw [h_neg1] at h
      have e1 : (1 : ℤ) - 0 = 1 := by omega
      have e2 : (1 : ℤ) - -1 = 2 := by omega
      rw [e1, e2, H1] at h
      exact h.symm
    have h_f_neg2 : f (-2) = 0 := by
      have h := H (-1) (-1)
      have e1 : (-1 : ℤ) * -1 = 1 := by omega
      rw [e1, H1, h_neg1] at h
      have e2 : (-1 : ℤ) - 1 = -2 := by omega
      rw [e2, zero_mul] at h
      exact h
    have h_f3 : f 3 = 1 := by
      have h := H_1_fy (-2)
      rw [h_f_neg2] at h
      have e1 : (1 : ℤ) - 0 = 1 := by omega
      have e2 : (1 : ℤ) - -2 = 3 := by omega
      rw [e1, e2, H1] at h
      exact h.symm
    have h_f2_zero : f 2 = 0 := by
      have h := H_xfx 3
      rw [h_f3] at h
      have e : (3 : ℤ) - 1 = 2 := by omega
      rw [e] at h
      exact h
    rw [h_f2] at h_f2_zero
    omega

  have shift_fwd : ∀ u v, f u = f v → f (u + 1) = f (v + 1) := by
    intro u v huv
    have hu := H (-1) (-u)
    have hv := H (-1) (-v)
    have e1 : (-1 : ℤ) * -u = u := by omega
    have e2 : (-1 : ℤ) * -v = v := by omega
    rw [e1] at hu
    rw [e2] at hv
    have hu2 : f (-1 - f u) = f (-1) * f (1 + u) := by
      have e3 : (1 : ℤ) - -u = 1 + u := by omega
      rw [e3] at hu; exact hu
    have hv2 : f (-1 - f v) = f (-1) * f (1 + v) := by
      have e4 : (1 : ℤ) - -v = 1 + v := by omega
      rw [e4] at hv; exact hv
    rw [huv] at hu2
    have eq : f (-1) * f (1 + u) = f (-1) * f (1 + v) := by
      calc f (-1) * f (1 + u) = f (-1 - f v) := hu2.symm
        _ = f (-1) * f (1 + v) := hv2
    have eq2 : f (1 + u) = f (1 + v) := mul_left_cancel₀ h_f_neg1 eq
    have e5 : 1 + u = u + 1 := by omega
    have e6 : 1 + v = v + 1 := by omega
    rw [e5, e6] at eq2
    exact eq2

  have shift_neg : ∀ u v, f u = f v → f (-u) = f (-v) := by
    intro u v huv
    have h1 := shift_fwd u v huv
    have hu := H_1_fy (u + 1)
    have hv := H_1_fy (v + 1)
    rw [h1] at hu
    have eq : f (1 - (u + 1)) = f (1 - (v + 1)) := by
      calc f (1 - (u + 1)) = f (1 - f (v + 1)) := hu.symm
        _ = f (1 - (v + 1)) := hv
    have e1 : (1 : ℤ) - (u + 1) = -u := by omega
    have e2 : (1 : ℤ) - (v + 1) = -v := by omega
    rw [e1, e2] at eq
    exact eq

  have shift_bwd : ∀ u v, f u = f v → f (u - 1) = f (v - 1) := by
    intro u v huv
    have h1 := shift_neg u v huv
    have h2 := shift_fwd (-u) (-v) h1
    have h3 := shift_neg (-u + 1) (-v + 1) h2
    have e1 : -(-u + 1) = u - 1 := by omega
    have e2 : -(-v + 1) = v - 1 := by omega
    rw [e1, e2] at h3
    exact h3

  have H_shift_nat : ∀ (n : ℕ) u v, f u = f v → f (u + (n : ℤ)) = f (v + (n : ℤ)) := by
    intro n
    induction n with
    | zero =>
      intro u v huv
      have e1 : u + ((0 : ℕ) : ℤ) = u := by omega
      have e2 : v + ((0 : ℕ) : ℤ) = v := by omega
      rw [e1, e2]
      exact huv
    | succ n ih =>
      intro u v huv
      have h1 := ih u v huv
      have h2 := shift_fwd _ _ h1
      have e1 : u + ((n + 1 : ℕ) : ℤ) = u + (n : ℤ) + 1 := by omega
      have e2 : v + ((n + 1 : ℕ) : ℤ) = v + (n : ℤ) + 1 := by omega
      rw [e1, e2]
      exact h2

  have H_shift_neg_nat : ∀ (n : ℕ) u v, f u = f v → f (u - (n : ℤ)) = f (v - (n : ℤ)) := by
    intro n
    induction n with
    | zero =>
      intro u v huv
      have e1 : u - ((0 : ℕ) : ℤ) = u := by omega
      have e2 : v - ((0 : ℕ) : ℤ) = v := by omega
      rw [e1, e2]
      exact huv
    | succ n ih =>
      intro u v huv
      have h1 := ih u v huv
      have h2 := shift_bwd _ _ h1
      have e1 : u - ((n + 1 : ℕ) : ℤ) = u - (n : ℤ) - 1 := by omega
      have e2 : v - ((n + 1 : ℕ) : ℤ) = v - (n : ℤ) - 1 := by omega
      rw [e1, e2]
      exact h2

  intro u v c huv
  cases c with
  | ofNat n =>
    have e1 : u + Int.ofNat n = u + (n : ℤ) := rfl
    have e2 : v + Int.ofNat n = v + (n : ℤ) := rfl
    rw [e1, e2]
    exact H_shift_nat n u v huv
  | negSucc n =>
    have e1 : u + Int.negSucc n = u - ((n + 1 : ℕ) : ℤ) := by omega
    have e2 : v + Int.negSucc n = v - ((n + 1 : ℕ) : ℤ) := by omega
    rw [e1, e2]
    exact H_shift_neg_nat (n + 1) u v huv

theorem f_sub_f (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  ∀ x, f (x - f x) = 0 :=
by
  intro x
  have h := H x 1
  rw [mul_one, sub_self, H0, mul_zero] at h
  exact h

theorem f_c_eq_zero_implies_f_1_sub_c_eq_1 (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  ∀ c, f c = 0 → f (1 - c) = 1 :=
by
  intro c hc
  have h := H 1 c
  simp only [one_mul, hc, sub_zero, H1] at h
  exact h.symm

theorem f_1_sub_c_eq_1_implies_invariant (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  ∀ c, f (1 - c) = 1 → ∀ y, f (y - f (y * c)) = f y :=
by
  intro c hc y
  rw [H, hc, mul_one]

theorem invariant_implies_period (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  ∀ c, f c = 0 → (∀ z, f (z - f (z * c)) = f z) → ∀ y, f (y + c) = f y :=
by
  intro c hc hz y
  have h_eq : f c = f 0 := by rw [hc, H0]
  have h_shift := f_eq_implies_shift f H H0 H1 c 0 y h_eq
  rw [zero_add] at h_shift
  rw [add_comm c y] at h_shift
  exact h_shift

theorem zero_implies_period (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  ∀ c y, f c = 0 → f (y + c) = f y :=
by
  intro c y hc
  have h1 : f (1 - c) = 1 := f_c_eq_zero_implies_f_1_sub_c_eq_1 f H H0 H1 c hc
  have h2 : ∀ z, f (z - f (z * c)) = f z := f_1_sub_c_eq_1_implies_invariant f H H0 H1 c h1
  exact invariant_implies_period f H H0 H1 c hc h2 y

theorem f_period (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  ∀ x y, f (y + (x - f x)) = f y :=
by
  intro x y
  apply zero_implies_period f H H0 H1 (x - f x) y
  exact f_sub_f f H H0 H1 x

theorem f_pow_fixed (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  ∀ x (n : ℕ), f (f x ^ n) = f x ^ n :=
by
  have h1 : ∀ y, f (1 - f y) = f (1 - y) := by
    intro y
    have h := H (1 : ℤ) y
    rw [one_mul, H1, one_mul] at h
    exact h

  have h2 : ∀ z, f (1 - f (1 - z)) = f z := by
    intro z
    have h := h1 (1 - z)
    have h_simp : (1 : ℤ) - (1 - z) = z := by ring
    rw [h_simp] at h
    exact h

  have h3 : ∀ x, f (f x) = f x := by
    intro x
    have hz := h2 (f x)
    have hy := h1 x
    rw [hy] at hz
    have hx := h2 x
    rw [hx] at hz
    exact hz.symm

  have h4 : ∀ a b, f a = a → f b = b → f (a * b) = a * b := by
    intro a b ha hb
    have h := H a (1 - b)
    have h_simp : (1 : ℤ) - (1 - b) = b := by ring
    rw [h_simp] at h
    rw [ha, hb] at h
    have hw : f (f (a - f (a * (1 - b)))) = f (a * b) := congrArg f h
    rw [h3] at hw
    rw [h] at hw
    exact hw.symm

  intro x n
  induction n with
  | zero =>
    change f (f x ^ 0) = f x ^ 0
    rw [pow_zero, H1]
  | succ n ih =>
    change f (f x ^ (n + 1)) = f x ^ (n + 1)
    have h_pow : f x ^ (n + 1) = f x * f x ^ n := by
      rw [pow_add, pow_one]
      exact mul_comm (f x ^ n) (f x)
    rw [h_pow]
    exact h4 (f x) (f x ^ n) (h3 x) ih

theorem f_add_mul (f : ℤ → ℤ) (c : ℤ) (Hper : ∀ x, f (x + c) = f x) (x k : ℤ) : f (x + c * k) = f x :=
by
  have Hpos : ∀ (n : ℕ) (y : ℤ), f (y + c * (n : ℤ)) = f y := by
    intro n
    induction n with
    | zero =>
      intro y
      push_cast
      have eq : y + c * (0 : ℤ) = y := by ring
      rw [eq]
    | succ n ih =>
      intro y
      push_cast
      have eq : y + c * (n + 1 : ℤ) = y + c * (n : ℤ) + c := by ring
      rw [eq, Hper, ih]

  have Hsub : ∀ (y : ℤ), f (y - c) = f y := by
    intro y
    have h := Hper (y - c)
    have eq : y - c + c = y := by ring
    rw [eq] at h
    exact h.symm

  have Hneg : ∀ (n : ℕ) (y : ℤ), f (y - c * (n : ℤ)) = f y := by
    intro n
    induction n with
    | zero =>
      intro y
      push_cast
      have eq : y - c * (0 : ℤ) = y := by ring
      rw [eq]
    | succ n ih =>
      intro y
      push_cast
      have eq : y - c * (n + 1 : ℤ) = y - c * (n : ℤ) - c := by ring
      rw [eq, Hsub, ih]

  by_cases hk : 0 ≤ k
  · have eq : k = (k.toNat : ℤ) := by omega
    rw [eq]
    exact Hpos k.toNat x
  · have eq : k = -((-k).toNat : ℤ) := by omega
    rw [eq]
    have eq2 : x + c * -((-k).toNat : ℤ) = x - c * ((-k).toNat : ℤ) := by ring
    rw [eq2]
    exact Hneg (-k).toNat x

theorem exists_pow_eq_add_mul (v : ℤ) {k : ℤ} (hk : k ≠ 0) :
  ∃ (i j : ℕ) (m : ℤ), i < j ∧ v ^ j = v ^ i + k * m :=
by
  let n := k.natAbs
  have hn : n ≠ 0 := by omega
  haveI : NeZero n := ⟨hn⟩
  let f : ℕ → ZMod n := fun i => (v ^ i : ℤ)

  have h_univ : (Set.univ : Set (ZMod n)).Finite := Set.finite_univ
  have h_fin : (Set.range f).Finite := h_univ.subset (Set.subset_univ _)

  have h_not_inj : ¬ Function.Injective f := by
    intro hinj
    have h_inf_iff := Set.infinite_range_iff hinj
    have h_inf_nat : Infinite ℕ := by infer_instance
    have h_inf_range : (Set.range f).Infinite := h_inf_iff.mpr h_inf_nat
    exact h_inf_range h_fin

  have h_exists_lt : ∃ i j, i < j ∧ f i = f j := by
    have h_not_all_inj : ∃ i j, f i = f j ∧ i ≠ j := by
      by_contra! h
      exact h_not_inj (fun a b hab => h a b hab)
    obtain ⟨a, b, hab_eq, hab_ne⟩ := h_not_all_inj
    have h_lt_or_gt : a < b ∨ b < a := by omega
    rcases h_lt_or_gt with h_lt | h_lt
    · exact ⟨a, b, h_lt, hab_eq⟩
    · exact ⟨b, a, h_lt, hab_eq.symm⟩

  obtain ⟨i, j, h_lt, h_eq⟩ := h_exists_lt

  have h_k_dvd_n : k ∣ (n : ℤ) := by
    have h_or : (n : ℤ) = k ∨ (n : ℤ) = -k := by omega
    rcases h_or with hn_eq | hn_eq
    · use 1; omega
    · use -1; omega

  have n_dvd : (n : ℤ) ∣ v ^ j - v ^ i := by
    apply (ZMod.intCast_zmod_eq_zero_iff_dvd (v ^ j - v ^ i) n).mp
    calc
      ((v ^ j - v ^ i : ℤ) : ZMod n) = ((v ^ j : ℤ) : ZMod n) - ((v ^ i : ℤ) : ZMod n) := by push_cast; rfl
      _ = f j - f i := rfl
      _ = f j - f j := by rw [h_eq]
      _ = 0 := by ring

  obtain ⟨m1, hm1⟩ := h_k_dvd_n
  obtain ⟨m2, hm2⟩ := n_dvd
  have k_dvd : k ∣ v ^ j - v ^ i := by
    use m1 * m2
    calc
      v ^ j - v ^ i = (n : ℤ) * m2 := hm2
      _ = (k * m1) * m2 := by rw [hm1]
      _ = k * (m1 * m2) := by ring

  obtain ⟨m, hm⟩ := k_dvd
  use i, j, m
  refine ⟨h_lt, ?_⟩
  calc
    v ^ j = (v ^ j - v ^ i) + v ^ i := by ring
    _ = k * m + v ^ i := by rw [hm]
    _ = v ^ i + k * m := by ring

theorem int_pow_eq_pow_implies_mem (v : ℤ) {i j : ℕ} (h_lt : i < j) (h_eq : v ^ j = v ^ i) :
  v ∈ ({-1, 0, 1} : Set ℤ) :=
by
  have H_abs : ∀ (n : ℕ), |v| ^ n = |v ^ n| := by
    intro n
    induction n with
    | zero => simp
    | succ n ih =>
      change |v| ^ (n + 1) = |v ^ (n + 1)|
      have h1 : |v| ^ (n + 1) = |v| ^ n * |v| := pow_succ |v| n
      have h2 : v ^ (n + 1) = v ^ n * v := pow_succ v n
      have h3 : |v ^ n * v| = |v ^ n| * |v| := abs_mul (v ^ n) v
      rw [h1, h2, h3, ih]

  have ha_eq : |v| ^ j = |v| ^ i := by
    have h1 : |v| ^ j = |v ^ j| := H_abs j
    have h2 : |v| ^ i = |v ^ i| := H_abs i
    rw [h1, h2, h_eq]

  have h_cases : |v| = 0 ∨ |v| = 1 ∨ 1 < |v| := by
    have h_nonneg : 0 ≤ |v| := abs_nonneg v
    omega

  rcases h_cases with h0 | h1 | h2
  · have h_le : 0 ≤ v ∨ v < 0 := by omega
    rcases h_le with hv | hv
    · rw [abs_of_nonneg hv] at h0
      subst h0
      simp
    · rw [abs_of_neg hv] at h0
      have h_v : v = 0 := by linarith
      subst h_v
      simp
  · have h_le : 0 ≤ v ∨ v < 0 := by omega
    rcases h_le with hv | hv
    · rw [abs_of_nonneg hv] at h1
      have h_v : v = 1 := h1
      subst h_v
      simp
    · rw [abs_of_neg hv] at h1
      have h_v : v = -1 := by linarith
      subst h_v
      simp
  · obtain ⟨c, hc⟩ : ∃ c : ℕ, j = i + c + 1 := by
      let c_int := (j : ℤ) - (i : ℤ) - 1
      use c_int.toNat
      omega

    have H2 : ∀ k : ℕ, 1 < |v| ^ (k + 1) := by
      intro k
      induction k with
      | zero =>
        have h_pow : |v| ^ 1 = |v| := pow_one |v|
        rw [h_pow]
        omega
      | succ k ih =>
        change 1 < |v| ^ (k + 1 + 1)
        have h_step : |v| ^ (k + 1 + 1) = |v| ^ (k + 1) * |v| := pow_succ |v| (k + 1)
        rw [h_step]
        have h3 : 2 ≤ |v| ^ (k + 1) := by omega
        have h4 : 2 ≤ |v| := by omega
        have h_bound : 2 * 2 ≤ |v| ^ (k + 1) * |v| := by nlinarith
        omega

    have hp2 : ∀ k : ℕ, 1 ≤ |v| ^ k := by
      intro k
      induction k with
      | zero =>
        have h_pow : |v| ^ 0 = 1 := pow_zero |v|
        rw [h_pow]
      | succ k ih =>
        change 1 ≤ |v| ^ (k + 1)
        have h_step : |v| ^ (k + 1) = |v| ^ k * |v| := pow_succ |v| k
        rw [h_step]
        have h4 : 2 ≤ |v| := by omega
        have h_bound : 1 * 2 ≤ |v| ^ k * |v| := by nlinarith
        omega

    have hp3 : 1 ≤ |v| ^ i := hp2 i

    have H3 : |v| ^ i < |v| ^ i * |v| ^ (c + 1) := by
      have hX : 1 ≤ |v| ^ i := hp3
      have hY : 2 ≤ |v| ^ (c + 1) := by
        have h_H2 := H2 c
        omega
      have h_step1 : |v| ^ i < |v| ^ i * 2 := by linarith
      have h_step2 : |v| ^ i * 2 ≤ |v| ^ i * |v| ^ (c + 1) := by nlinarith
      linarith

    have h_add : |v| ^ (i + (c + 1)) = |v| ^ i * |v| ^ (c + 1) := pow_add |v| i (c + 1)

    have H4 : |v| ^ i < |v| ^ (i + (c + 1)) := by
      rw [h_add]
      exact H3

    have h_eq2 : i + (c + 1) = j := by omega
    have H5 : |v| ^ (i + (c + 1)) = |v| ^ j := by rw [h_eq2]

    rw [H5, ha_eq] at H4
    linarith

theorem f_bounded_of_not_id (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  (∃ c, f c ≠ c) → ∀ x, f x ∈ ({-1, 0, 1} : Set ℤ) :=
by
  rintro ⟨c, hc⟩ x
  have hk : c - f c ≠ 0 := by omega
  have hper : ∀ y, f (y + (c - f c)) = f y := f_period f H H0 H1 c
  obtain ⟨i, j, m, h_lt, h_eq⟩ := exists_pow_eq_add_mul (f x) hk

  have h_pow_i : f (f x ^ i) = f x ^ i := f_pow_fixed f H H0 H1 x i
  have h_pow_j : f (f x ^ j) = f x ^ j := f_pow_fixed f H H0 H1 x j

  have h1 : f (f x ^ j) = f (f x ^ i + (c - f c) * m) := by rw [h_eq]
  have h2 : f (f x ^ i + (c - f c) * m) = f (f x ^ i) := f_add_mul f (c - f c) hper (f x ^ i) m

  rw [h2, h_pow_i] at h1
  rw [h_pow_j] at h1

  exact int_pow_eq_pow_implies_mem (f x) h_lt h1

theorem f_eq_mod_two (f : ℤ → ℤ) (H0 : f 0 = 0) (H1 : f 1 = 1) (Hper : ∀ x, f (x + 2) = f x) :
  f = (fun x => x % 2) :=
by
  have H_pos : ∀ (n : ℕ) (r : ℤ), f (r + (n : ℤ) * 2) = f r := by
    intro n
    induction n with
    | zero =>
      intro r
      have eq0 : r + ((0 : ℕ) : ℤ) * 2 = r := by omega
      exact congrArg f eq0
    | succ n ih =>
      intro r
      calc f (r + ((n + 1 : ℕ) : ℤ) * 2)
        _ = f (r + (n : ℤ) * 2 + 2) := congrArg f (by push_cast; omega)
        _ = f (r + (n : ℤ) * 2)     := Hper (r + (n : ℤ) * 2)
        _ = f r                     := ih r

  have H_neg : ∀ (n : ℕ) (r : ℤ), f (r - (n : ℤ) * 2) = f r := by
    intro n
    induction n with
    | zero =>
      intro r
      have eq0 : r - ((0 : ℕ) : ℤ) * 2 = r := by omega
      exact congrArg f eq0
    | succ n ih =>
      intro r
      calc f (r - ((n + 1 : ℕ) : ℤ) * 2)
        _ = f (r - ((n + 1 : ℕ) : ℤ) * 2 + 2) := (Hper (r - ((n + 1 : ℕ) : ℤ) * 2)).symm
        _ = f (r - (n : ℤ) * 2)               := congrArg f (by push_cast; omega)
        _ = f r                               := ih r

  have H_all : ∀ (q : ℤ) (r : ℤ), f (r + q * 2) = f r := by
    intro q r
    cases q with
    | ofNat n =>
      exact H_pos n r
    | negSucc n =>
      have eq1 : r + (Int.negSucc n) * 2 = r - ((n + 1 : ℕ) : ℤ) * 2 := by omega
      calc f (r + (Int.negSucc n) * 2)
        _ = f (r - ((n + 1 : ℕ) : ℤ) * 2) := congrArg f eq1
        _ = f r                           := H_neg (n + 1) r

  funext x
  have h_div : x = x % 2 + (x / 2) * 2 := by omega
  have h_f : f x = f (x % 2) := by
    calc
      f x = f (x % 2 + (x / 2) * 2) := congrArg f h_div
      _   = f (x % 2)               := H_all (x / 2) (x % 2)

  have h_mod : x % 2 = 0 ∨ x % 2 = 1 := by omega
  cases h_mod with
  | inl h0 =>
    calc
      f x = f (x % 2) := h_f
      _   = f 0       := congrArg f h0
      _   = 0         := H0
      _   = x % 2     := h0.symm
  | inr h1 =>
    calc
      f x = f (x % 2) := h_f
      _   = f 1       := congrArg f h1
      _   = 1         := H1
      _   = x % 2     := h1.symm

theorem f_period_3 (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y))
  (H0 : f 0 = 0) (H1 : f 1 = 1) (Hbound : ∀ x, f x ∈ ({-1, 0, 1} : Set ℤ)) (Hneg1 : f (-1) = -1) :
  ∀ x, f (x + 3) = f x :=
by
  have hb : ∀ x, f x = -1 ∨ f x = 0 ∨ f x = 1 := by
    intro x
    have h := Hbound x
    simp only [Set.mem_insert_iff, Set.mem_singleton_iff] at h
    exact h

  have h_f_neg2 : f (-2) = 1 := by
    have h1 := H (-1 : ℤ) (2 : ℤ)
    have eq1 : (-1 : ℤ) * 2 = -2 := by norm_num
    have eq2 : (1 : ℤ) - 2 = -1 := by norm_num
    rw [eq1, eq2, Hneg1] at h1
    have h1' : f (-1 - f (-2)) = 1 := by
      calc f (-1 - f (-2)) = -1 * -1 := h1
        _ = 1 := by norm_num
    rcases hb (-2) with h2 | h2 | h2
    · rw [h2] at h1'
      have eq3 : (-1 : ℤ) - -1 = 0 := by norm_num
      rw [eq3, H0] at h1'
      omega
    · rw [h2] at h1'
      have eq3 : (-1 : ℤ) - 0 = -1 := by norm_num
      rw [eq3, Hneg1] at h1'
      omega
    · exact h2

  have h_f_2 : f 2 = -1 := by
    have h1 := H (2 : ℤ) (-1 : ℤ)
    have eq1 : (2 : ℤ) * -1 = -2 := by norm_num
    have eq2 : (1 : ℤ) - -1 = 2 := by norm_num
    rw [eq1, eq2, h_f_neg2] at h1
    have eq3 : (2 : ℤ) - 1 = 1 := by norm_num
    rw [eq3, H1] at h1
    have h2 := H (2 : ℤ) (1 : ℤ)
    have eq4 : (2 : ℤ) * 1 = 2 := by norm_num
    have eq5 : (1 : ℤ) - 1 = 0 := by norm_num
    rw [eq4, eq5, H0] at h2
    have eq6 : f 2 * 0 = 0 := by ring
    rw [eq6] at h2
    rcases hb 2 with hf2 | hf2 | hf2
    · exact hf2
    · rw [hf2] at h1
      have eq8 : (0 : ℤ) * 0 = 0 := by norm_num
      rw [eq8] at h1
      omega
    · rw [hf2] at h2
      have eq7 : (2 : ℤ) - 1 = 1 := by norm_num
      rw [eq7, H1] at h2
      omega

  have h_1_minus_x : ∀ x, f (1 - x) = f (1 - f x) := by
    intro x
    have h1 := H (1 : ℤ) x
    have eq1 : (1 : ℤ) * x = x := by ring
    rw [eq1, H1] at h1
    have eq2 : 1 * f (1 - x) = f (1 - x) := by ring
    rw [eq2] at h1
    exact h1.symm

  have h_neg_x : ∀ x, f (-x) = -f x := by
    intro x
    have h1 := H (-1 : ℤ) x
    have eq1 : (-1 : ℤ) * x = -x := by ring
    rw [eq1, Hneg1] at h1
    have eq2 : -1 * f (1 - x) = -f (1 - x) := by ring
    rw [eq2, h_1_minus_x x] at h1
    rcases hb x with hx | hx | hx
    · rw [hx] at h1
      have eq3 : (1 : ℤ) - -1 = 2 := by norm_num
      rw [eq3, h_f_2] at h1
      have eq4 : -(-1 : ℤ) = 1 := by norm_num
      rw [eq4] at h1
      rcases hb (-x) with hnx | hnx | hnx
      · rw [hnx] at h1
        have eq5 : (-1 : ℤ) - -1 = 0 := by norm_num
        rw [eq5, H0] at h1
        omega
      · rw [hnx] at h1
        have eq5 : (-1 : ℤ) - 0 = -1 := by norm_num
        rw [eq5, Hneg1] at h1
        omega
      · omega
    · rw [hx] at h1
      have eq3 : (1 : ℤ) - 0 = 1 := by norm_num
      rw [eq3, H1] at h1
      have eq4 : -(1 : ℤ) = -1 := by norm_num
      rw [eq4] at h1
      rcases hb (-x) with hnx | hnx | hnx
      · rw [hnx] at h1
        have eq5 : (-1 : ℤ) - -1 = 0 := by norm_num
        rw [eq5, H0] at h1
        omega
      · omega
      · rw [hnx] at h1
        have eq5 : (-1 : ℤ) - 1 = -2 := by norm_num
        rw [eq5, h_f_neg2] at h1
        omega
    · rw [hx] at h1
      have eq3 : (1 : ℤ) - 1 = 0 := by norm_num
      rw [eq3, H0] at h1
      have eq4 : -(0 : ℤ) = 0 := by norm_num
      rw [eq4] at h1
      rcases hb (-x) with hnx | hnx | hnx
      · omega
      · rw [hnx] at h1
        have eq5 : (-1 : ℤ) - 0 = -1 := by norm_num
        rw [eq5, Hneg1] at h1
        omega
      · rw [hnx] at h1
        have eq5 : (-1 : ℤ) - 1 = -2 := by norm_num
        rw [eq5, h_f_neg2] at h1
        omega

  have h_x_plus_1 : ∀ x, f (x + 1) = f (1 + f x) := by
    intro x
    have eq1 : x + 1 = 1 - (-x) := by ring
    rw [eq1]
    rw [h_1_minus_x (-x)]
    rw [h_neg_x x]
    have eq2 : 1 - -f x = 1 + f x := by ring
    rw [eq2]

  have h_step : ∀ x, (f x = -1 → f (x + 1) = 0) ∧
                     (f x = 0 → f (x + 1) = 1) ∧
                     (f x = 1 → f (x + 1) = -1) := by
    intro x
    refine ⟨?_, ?_, ?_⟩
    · intro h
      rw [h_x_plus_1 x, h]
      have eq1 : (1 : ℤ) + -1 = 0 := by norm_num
      rw [eq1, H0]
    · intro h
      rw [h_x_plus_1 x, h]
      have eq1 : (1 : ℤ) + 0 = 1 := by norm_num
      rw [eq1, H1]
    · intro h
      rw [h_x_plus_1 x, h]
      have eq1 : (1 : ℤ) + 1 = 2 := by norm_num
      rw [eq1, h_f_2]

  intro x
  rcases hb x with hx | hx | hx
  · obtain ⟨hx_m1, _, _⟩ := h_step x
    have h1 : f (x + 1) = 0 := hx_m1 hx
    obtain ⟨_, h1_0, _⟩ := h_step (x + 1)
    have h2 : f (x + 1 + 1) = 1 := h1_0 h1
    obtain ⟨_, _, h2_1⟩ := h_step (x + 1 + 1)
    have h3 : f (x + 1 + 1 + 1) = -1 := h2_1 h2
    calc f (x + 3) = f (x + 1 + 1 + 1) := by congr 1; ring
      _ = -1 := h3
      _ = f x := hx.symm
  · obtain ⟨_, hx_0, _⟩ := h_step x
    have h1 : f (x + 1) = 1 := hx_0 hx
    obtain ⟨_, _, h1_1⟩ := h_step (x + 1)
    have h2 : f (x + 1 + 1) = -1 := h1_1 h1
    obtain ⟨h2_m1, _, _⟩ := h_step (x + 1 + 1)
    have h3 : f (x + 1 + 1 + 1) = 0 := h2_m1 h2
    calc f (x + 3) = f (x + 1 + 1 + 1) := by congr 1; ring
      _ = 0 := h3
      _ = f x := hx.symm
  · obtain ⟨_, _, hx_1⟩ := h_step x
    have h1 : f (x + 1) = -1 := hx_1 hx
    obtain ⟨h1_m1, _, _⟩ := h_step (x + 1)
    have h2 : f (x + 1 + 1) = 0 := h1_m1 h1
    obtain ⟨_, h2_0, _⟩ := h_step (x + 1 + 1)
    have h3 : f (x + 1 + 1 + 1) = 1 := h2_0 h2
    calc f (x + 3) = f (x + 1 + 1 + 1) := by congr 1; ring
      _ = 1 := h3
      _ = f x := hx.symm

theorem f_eq_mod_three (f : ℤ → ℤ) (H0 : f 0 = 0) (H1 : f 1 = 1) (Hneg1 : f (-1) = -1)
  (Hper : ∀ x, f (x + 3) = f x) :
  f = (fun x => if 3 ∣ x then 0 else if 3 ∣ x - 1 then 1 else -1) :=
by
  ext x
  dsimp only
  have H3 : ∀ (k r : ℤ), f (r + (3 : ℤ) * k) = f r := by
    intro k
    refine Int.inductionOn' (motive := fun k => ∀ r, f (r + (3 : ℤ) * k) = f r) k 0 ?_ ?_ ?_
    · intro r
      have h0 : r + (3 : ℤ) * 0 = r := by omega
      rw [h0]
    · intro k' hk' ih r
      have h1 : r + (3 : ℤ) * (k' + (1 : ℤ)) = (r + (3 : ℤ) * k') + (3 : ℤ) := by omega
      rw [h1, Hper, ih r]
    · intro k' hk' ih r
      have h1 : r + (3 : ℤ) * k' = (r + (3 : ℤ) * (k' - (1 : ℤ))) + (3 : ℤ) := by omega
      have h2 := ih r
      rw [h1, Hper] at h2
      exact h2

  have fx_eq : f x = f (x % (3 : ℤ)) := by
    have h_rw : x = x % (3 : ℤ) + (3 : ℤ) * (x / (3 : ℤ)) := by omega
    nth_rw 1 [h_rw]
    exact H3 (x / (3 : ℤ)) (x % (3 : ℤ))

  have h_mod : x % (3 : ℤ) = 0 ∨ x % (3 : ℤ) = 1 ∨ x % (3 : ℤ) = 2 := by omega
  rcases h_mod with h0 | h1 | h2
  · rw [fx_eq, h0, H0]
    have h_dvd : (3 : ℤ) ∣ x := ⟨x / (3 : ℤ), by omega⟩
    rw [if_pos h_dvd]
  · rw [fx_eq, h1, H1]
    have h_ndvd : ¬ (3 : ℤ) ∣ x := by
      intro ⟨k, hk⟩
      omega
    have h_dvd_minus : (3 : ℤ) ∣ x - (1 : ℤ) := ⟨x / (3 : ℤ), by omega⟩
    rw [if_neg h_ndvd, if_pos h_dvd_minus]
  · have fx2 : f (x % (3 : ℤ)) = -1 := by
      rw [h2]
      have h_two : (2 : ℤ) = -1 + (3 : ℤ) * 1 := by omega
      rw [h_two, H3 1 (-1), Hneg1]
    rw [fx_eq, fx2]
    have h_ndvd : ¬ (3 : ℤ) ∣ x := by
      intro ⟨k, hk⟩
      omega
    have h_ndvd_minus : ¬ (3 : ℤ) ∣ x - (1 : ℤ) := by
      intro ⟨k, hk⟩
      omega
    rw [if_neg h_ndvd, if_neg h_ndvd_minus]

theorem f_cases (f : ℤ → ℤ) (H : ∀ x y, f (x - f (x * y)) = f x * f (1 - y)) (H0 : f 0 = 0) (H1 : f 1 = 1) :
  f = id ∨ f = (fun x => x % 2) ∨ f = (fun x => if 3 ∣ x then 0 else if 3 ∣ x - 1 then 1 else -1) :=
by
  by_cases H_id : f = id
  · left
    exact H_id
  · right
    have H_not_id : ∃ c, f c ≠ c := by
      by_contra! h
      apply H_id
      ext x
      exact h x
    have H_bound := f_bounded_of_not_id f H H0 H1 H_not_id
    have H_neg1 := H_bound (-1)
    have H_neg1_ne_zero := f_neg1_ne_zero f H H0 H1

    -- Lean 4 inherently resolves values in concise right-associated insert sets `{a, b, c}` as equality combinations.
    have H_neg1_cases : f (-1) = -1 ∨ f (-1) = 0 ∨ f (-1) = 1 := H_neg1
    rcases H_neg1_cases with h | h | h
    · -- case f (-1) = -1 implies 3-periodicity
      right
      have H_per3 := f_period_3 f H H0 H1 H_bound h
      exact f_eq_mod_three f H0 H1 h H_per3
    · -- case f (-1) = 0 is impossible
      contradiction
    · -- case f (-1) = 1 implies 2-periodicity
      left
      have H_per2 : ∀ x, f (x + 2) = f x := by
        intro x
        have H_1_eq_neg1 : f 1 = f (-1) := by rw [H1, h]
        have H_shift := f_eq_implies_shift f H H0 H1 1 (-1) (x + 1) H_1_eq_neg1
        have H_left : 1 + (x + 1) = x + 2 := by omega
        have H_right : -1 + (x + 1) = x := by omega
        rw [H_left, H_right] at H_shift
        exact H_shift
      exact f_eq_mod_two f H0 H1 H_per2

theorem verify_solutions (f : ℤ → ℤ) :
  f ∈ ({(fun _ => 0), (fun _ => 1), id, (fun x => x % 2), (fun x => if 3 ∣ x then 0 else if 3 ∣ x - 1 then 1 else -1)} : Set (ℤ → ℤ)) →
  ∀ x y, f (x - f (x * y)) = f x * f (1 - y) :=
by
  intro h
  simp only [Set.mem_insert_iff, Set.mem_singleton_iff] at h
  rcases h with rfl | rfl | rfl | rfl | rfl
  · intro x y
    simp
  · intro x y
    simp
  · intro x y
    simp only [id]
    ring
  · intro x y
    dsimp
    obtain ⟨kx, ax, rfl, hx_cases⟩ : ∃ k a : ℤ, x = 2 * k + a ∧ (a = 0 ∨ a = 1) := ⟨x / 2, x % 2, by omega, by omega⟩
    obtain ⟨ky, ay, rfl, hy_cases⟩ : ∃ k a : ℤ, y = 2 * k + a ∧ (a = 0 ∨ a = 1) := ⟨y / 2, y % 2, by omega, by omega⟩
    rcases hx_cases with rfl | rfl
    · rcases hy_cases with rfl | rfl
      · have hxy : (2 * kx + 0) * (2 * ky + 0) = 2 * (2 * kx * ky) + 0 := by ring
        rw [hxy]
        have eq_x : (2 * kx + 0) % 2 = 0 := by omega
        have eq_y : (1 - (2 * ky + 0)) % 2 = 1 := by omega
        rw [eq_x, eq_y]
        omega
      · have hxy : (2 * kx + 0) * (2 * ky + 1) = 2 * (2 * kx * ky + kx) + 0 := by ring
        rw [hxy]
        have eq_x : (2 * kx + 0) % 2 = 0 := by omega
        have eq_y : (1 - (2 * ky + 1)) % 2 = 0 := by omega
        rw [eq_x, eq_y]
        omega
    · rcases hy_cases with rfl | rfl
      · have hxy : (2 * kx + 1) * (2 * ky + 0) = 2 * (2 * kx * ky + ky) + 0 := by ring
        rw [hxy]
        have eq_x : (2 * kx + 1) % 2 = 1 := by omega
        have eq_y : (1 - (2 * ky + 0)) % 2 = 1 := by omega
        rw [eq_x, eq_y]
        omega
      · have hxy : (2 * kx + 1) * (2 * ky + 1) = 2 * (2 * kx * ky + kx + ky) + 1 := by ring
        rw [hxy]
        have eq_x : (2 * kx + 1) % 2 = 1 := by omega
        have eq_y : (1 - (2 * ky + 1)) % 2 = 0 := by omega
        rw [eq_x, eq_y]
        omega
  · intro x y
    dsimp
    have hdvd : ∀ z : ℤ, (3 ∣ z) ↔ z % 3 = 0 := by intro z; omega
    simp only [hdvd]
    obtain ⟨kx, ax, rfl, hx_cases⟩ : ∃ k a : ℤ, x = 3 * k + a ∧ (a = 0 ∨ a = 1 ∨ a = 2) := ⟨x / 3, x % 3, by omega, by omega⟩
    obtain ⟨ky, ay, rfl, hy_cases⟩ : ∃ k a : ℤ, y = 3 * k + a ∧ (a = 0 ∨ a = 1 ∨ a = 2) := ⟨y / 3, y % 3, by omega, by omega⟩
    rcases hx_cases with rfl | rfl | rfl
    · rcases hy_cases with rfl | rfl | rfl
      · have hxy : (3 * kx + 0) * (3 * ky + 0) = 3 * (3 * kx * ky) + 0 := by ring
        rw [hxy]
        have eq_x : (if (3 * kx + 0) % 3 = 0 then (0 : ℤ) else if (3 * kx + 0 - 1) % 3 = 0 then 1 else -1) = 0 := by omega
        have eq_y : (if (1 - (3 * ky + 0)) % 3 = 0 then (0 : ℤ) else if (1 - (3 * ky + 0) - 1) % 3 = 0 then 1 else -1) = 1 := by omega
        rw [eq_x, eq_y]
        omega
      · have hxy : (3 * kx + 0) * (3 * ky + 1) = 3 * (3 * kx * ky + kx) + 0 := by ring
        rw [hxy]
        have eq_x : (if (3 * kx + 0) % 3 = 0 then (0 : ℤ) else if (3 * kx + 0 - 1) % 3 = 0 then 1 else -1) = 0 := by omega
        have eq_y : (if (1 - (3 * ky + 1)) % 3 = 0 then (0 : ℤ) else if (1 - (3 * ky + 1) - 1) % 3 = 0 then 1 else -1) = 0 := by omega
        rw [eq_x, eq_y]
        omega
      · have hxy : (3 * kx + 0) * (3 * ky + 2) = 3 * (3 * kx * ky + 2 * kx) + 0 := by ring
        rw [hxy]
        have eq_x : (if (3 * kx + 0) % 3 = 0 then (0 : ℤ) else if (3 * kx + 0 - 1) % 3 = 0 then 1 else -1) = 0 := by omega
        have eq_y : (if (1 - (3 * ky + 2)) % 3 = 0 then (0 : ℤ) else if (1 - (3 * ky + 2) - 1) % 3 = 0 then 1 else -1) = -1 := by omega
        rw [eq_x, eq_y]
        omega
    · rcases hy_cases with rfl | rfl | rfl
      · have hxy : (3 * kx + 1) * (3 * ky + 0) = 3 * (3 * kx * ky + ky) + 0 := by ring
        rw [hxy]
        have eq_x : (if (3 * kx + 1) % 3 = 0 then (0 : ℤ) else if (3 * kx + 1 - 1) % 3 = 0 then 1 else -1) = 1 := by omega
        have eq_y : (if (1 - (3 * ky + 0)) % 3 = 0 then (0 : ℤ) else if (1 - (3 * ky + 0) - 1) % 3 = 0 then 1 else -1) = 1 := by omega
        rw [eq_x, eq_y]
        omega
      · have hxy : (3 * kx + 1) * (3 * ky + 1) = 3 * (3 * kx * ky + kx + ky) + 1 := by ring
        rw [hxy]
        have eq_x : (if (3 * kx + 1) % 3 = 0 then (0 : ℤ) else if (3 * kx + 1 - 1) % 3 = 0 then 1 else -1) = 1 := by omega
        have eq_y : (if (1 - (3 * ky + 1)) % 3 = 0 then (0 : ℤ) else if (1 - (3 * ky + 1) - 1) % 3 = 0 then 1 else -1) = 0 := by omega
        rw [eq_x, eq_y]
        omega
      · have hxy : (3 * kx + 1) * (3 * ky + 2) = 3 * (3 * kx * ky + 2 * kx + ky) + 2 := by ring
        rw [hxy]
        have eq_x : (if (3 * kx + 1) % 3 = 0 then (0 : ℤ) else if (3 * kx + 1 - 1) % 3 = 0 then 1 else -1) = 1 := by omega
        have eq_y : (if (1 - (3 * ky + 2)) % 3 = 0 then (0 : ℤ) else if (1 - (3 * ky + 2) - 1) % 3 = 0 then 1 else -1) = -1 := by omega
        rw [eq_x, eq_y]
        omega
    · rcases hy_cases with rfl | rfl | rfl
      · have hxy : (3 * kx + 2) * (3 * ky + 0) = 3 * (3 * kx * ky + 2 * ky) + 0 := by ring
        rw [hxy]
        have eq_x : (if (3 * kx + 2) % 3 = 0 then (0 : ℤ) else if (3 * kx + 2 - 1) % 3 = 0 then 1 else -1) = -1 := by omega
        have eq_y : (if (1 - (3 * ky + 0)) % 3 = 0 then (0 : ℤ) else if (1 - (3 * ky + 0) - 1) % 3 = 0 then 1 else -1) = 1 := by omega
        rw [eq_x, eq_y]
        omega
      · have hxy : (3 * kx + 2) * (3 * ky + 1) = 3 * (3 * kx * ky + kx + 2 * ky) + 2 := by ring
        rw [hxy]
        have eq_x : (if (3 * kx + 2) % 3 = 0 then (0 : ℤ) else if (3 * kx + 2 - 1) % 3 = 0 then 1 else -1) = -1 := by omega
        have eq_y : (if (1 - (3 * ky + 1)) % 3 = 0 then (0 : ℤ) else if (1 - (3 * ky + 1) - 1) % 3 = 0 then 1 else -1) = 0 := by omega
        rw [eq_x, eq_y]
        omega
      · have hxy : (3 * kx + 2) * (3 * ky + 2) = 3 * (3 * kx * ky + 2 * kx + 2 * ky + 1) + 1 := by ring
        rw [hxy]
        have eq_x : (if (3 * kx + 2) % 3 = 0 then (0 : ℤ) else if (3 * kx + 2 - 1) % 3 = 0 then 1 else -1) = -1 := by omega
        have eq_y : (if (1 - (3 * ky + 2)) % 3 = 0 then (0 : ℤ) else if (1 - (3 * ky + 2) - 1) % 3 = 0 then 1 else -1) = -1 := by omega
        rw [eq_x, eq_y]
        omega

theorem PBAdvanced006 : {f : ℤ → ℤ | ∀ x y, f (x - f (x * y)) = f x * f (1 - y)}
      = {(fun _ => 0), (fun _ => 1), id, (fun x => x % 2),
          (fun x => if 3 ∣ x then 0 else if 3 ∣ x - 1 then 1
            else -1)} :=
by
  ext f
  constructor
  · intro H
    rcases f_zero_or_one_or_id_like f H with h | h | ⟨h0, h1⟩
    · exact Or.inl h
    · exact Or.inr (Or.inl h)
    · rcases f_cases f H h0 h1 with h | h | h
      · exact Or.inr (Or.inr (Or.inl h))
      · exact Or.inr (Or.inr (Or.inr (Or.inl h)))
      · exact Or.inr (Or.inr (Or.inr (Or.inr h)))
  · intro H
    exact verify_solutions f H
