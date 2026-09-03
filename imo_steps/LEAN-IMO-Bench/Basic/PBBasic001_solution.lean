import Mathlib

theorem PBBasic001_lem2 (f : ℤ → ℤ) (h : ∀ x y, f (2 * x) + 2 * f y = f (f (x + y))) (x y : ℤ) :
  f (2 * x) + 2 * f y = 2 * f (x + y) + f 0 :=
by
  have h1 := h 0 (x + y)
  rw [mul_zero, zero_add] at h1
  rw [h x y]
  rw [← h1]
  omega

theorem PBBasic001_lem3 (f : ℤ → ℤ) (h : ∀ x y, f (2 * x) + 2 * f y = f (f (x + y))) (x : ℤ) :
  f (2 * x) = 2 * f x - f 0 :=
by
  have h1 := h x 0
  have h2 := h 0 x
  rw [add_zero] at h1
  rw [zero_add, mul_zero] at h2
  omega

theorem PBBasic001_lem4 (f : ℤ → ℤ) (h : ∀ x y, f (2 * x) + 2 * f y = f (f (x + y))) (x y : ℤ) :
  f (x + y) = f x + f y - f 0 :=
by
  have h2 := PBBasic001_lem2 f h x y
  have h3 := PBBasic001_lem3 f h x
  omega

theorem PBBasic001_lem5_nat (f : ℤ → ℤ) (h : ∀ x y, f (x + y) = f x + f y - f 0) (n : ℕ) :
  f (n : ℤ) = (f 1 - f 0) * (n : ℤ) + f 0 :=
by
  induction n with
  | zero =>
    push_cast
    ring
  | succ n ih =>
    push_cast
    rw [h, ih]
    ring

theorem PBBasic001_lem5_neg_prop (f : ℤ → ℤ) (h : ∀ x y, f (x + y) = f x + f y - f 0) (x : ℤ) :
  f (-x) = 2 * f 0 - f x :=
by
  specialize h x (-x)
  have h2 : x + -x = 0
  · ring
  rw [h2] at h
  linarith

theorem PBBasic001_lem5 (f : ℤ → ℤ) (h : ∀ x y, f (x + y) = f x + f y - f 0) (x : ℤ) :
  f x = (f 1 - f 0) * x + f 0 :=
by
  cases x with
  | ofNat n =>
    have h_nat : Int.ofNat n = (n : ℤ) := rfl
    rw [h_nat]
    exact PBBasic001_lem5_nat f h n
  | negSucc n =>
    have hx : Int.negSucc n = -((n + 1 : ℕ) : ℤ) := rfl
    rw [hx]
    rw [PBBasic001_lem5_neg_prop f h ((n + 1 : ℕ) : ℤ)]
    rw [PBBasic001_lem5_nat f h (n + 1)]
    ring

theorem PBBasic001_lem6_alg (c d : ℤ)
  (h1 : c * (2 * 0) + d + 2 * (c * 0 + d) = c * (c * (0 + 0) + d) + d)
  (h2 : c * (2 * 1) + d + 2 * (c * 0 + d) = c * (c * (1 + 0) + d) + d) :
  c = 0 ∨ c = 2 :=
by
  cases Int.eq_zero_or_eq_zero_of_mul_eq_zero (show c * (c - 2) = 0 by linear_combination h1 - h2) with
  | inl h =>
    left
    exact h
  | inr h =>
    right
    omega

theorem PBBasic001_lem6 (f : ℤ → ℤ) (h : ∀ x y, f (2 * x) + 2 * f y = f (f (x + y))) :
  f 1 - f 0 = 0 ∨ f 1 - f 0 = 2 :=
by
  have hf4 : ∀ x y, f (x + y) = f x + f y - f 0 := PBBasic001_lem4 f h
  have hf5 : ∀ x, f x = (f 1 - f 0) * x + f 0 := PBBasic001_lem5 f hf4
  refine PBBasic001_lem6_alg (f 1 - f 0) (f 0) ?_ ?_
  · rw [← hf5 (2 * 0), ← hf5 0, h 0 0, hf5 (0 + 0), hf5 ((f 1 - f 0) * (0 + 0) + f 0)]
  · rw [← hf5 (2 * 1), ← hf5 0, h 1 0, hf5 (1 + 0), hf5 ((f 1 - f 0) * (1 + 0) + f 0)]

theorem PBBasic001_lem7_1 (f : ℤ → ℤ) (h : ∀ x y, f (2 * x) + 2 * f y = f (f (x + y))) (h0 : f 1 - f 0 = 0) (x : ℤ) :
  f x = f 0 :=
by
  have h4 : ∀ (x y : ℤ), f (x + y) = f x + f y - f 0 := PBBasic001_lem4 f h
  have h5 : f x = (f 1 - f 0) * x + f 0 := PBBasic001_lem5 f h4 x
  rw [h5]
  rw [h0]
  ring

theorem PBBasic001_lem7_2 (f : ℤ → ℤ) (h : ∀ x y, f (2 * x) + 2 * f y = f (f (x + y))) (h0 : f 1 - f 0 = 0) :
  f 0 = 0 :=
by
  have h_eval := h 0 0
  have h1 := PBBasic001_lem7_1 f h h0 (2 * 0)
  have h2 := PBBasic001_lem7_1 f h h0 (f (0 + 0))
  linarith

theorem PBBasic001_lem7 (f : ℤ → ℤ) (h : ∀ x y, f (2 * x) + 2 * f y = f (f (x + y))) (h0 : f 1 - f 0 = 0) (x : ℤ) :
  f x = 0 :=
by
  have h1 : f x = f 0 := PBBasic001_lem7_1 f h h0 x
  have h2 : f 0 = 0 := PBBasic001_lem7_2 f h h0
  rw [h1, h2]

theorem PBBasic001 :
    {f : ℤ → ℤ | ∀ x y, f (2 * x) + 2 * f y = f (f (x + y))}
      = {0} ∪ {(fun x ↦ 2 * x + c)| (c : ℤ)} :=
by
  ext f
  simp only [Set.mem_setOf_eq, Set.mem_union, Set.mem_singleton_iff, Set.mem_range, Set.mem_image]
  constructor
  · intro hf
    have h6 := PBBasic001_lem6 f hf
    cases h6 with
    | inl h0 =>
      left
      ext x
      have h7 := PBBasic001_lem7 f hf h0 x
      first | exact h7 | exact h7.symm
    | inr h2 =>
      right
      use f 0
      ext x
      have h4 := PBBasic001_lem4 f hf
      have h5 := PBBasic001_lem5 f h4 x
      rw [h2] at h5
      first | exact h5 | exact h5.symm
  · rintro (rfl | ⟨c, rfl⟩)
    · intro x y
      simp
    · intro x y
      dsimp only
      ring
