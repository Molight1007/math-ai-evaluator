import Mathlib
def x_val (a b : ℕ) : GaussianInt := ⟨(a : ℤ) ^ 2, (b : ℤ) ^ 2⟩
def y_val (a b : ℕ) : GaussianInt := ⟨(a : ℤ) ^ 2, -(b : ℤ) ^ 2⟩

theorem not_p_sq (p a b : ℕ) (ha : a ≠ 0) (hb : b ≠ 0) : p ^ 2 ≠ a ^ 4 + b ^ 4 :=
by
  intro h
  have ha' : (a : ℤ) ≠ 0 := by exact_mod_cast ha
  have hb' : (b : ℤ) ≠ 0 := by exact_mod_cast hb
  have h' : (a : ℤ) ^ 4 + (b : ℤ) ^ 4 = (p : ℤ) ^ 2 := by
    calc
      (a : ℤ) ^ 4 + (b : ℤ) ^ 4 = ((a ^ 4 + b ^ 4 : ℕ) : ℤ) := by push_cast; rfl
      _ = ((p ^ 2 : ℕ) : ℤ) := by rw [h]
      _ = (p : ℤ) ^ 2 := by push_cast; rfl
  exact not_fermat_42 ha' hb' h'

theorem not_p_pow_four (p a b : ℕ) (ha : a ≠ 0) (hb : b ≠ 0) : p ^ 4 ≠ a ^ 4 + b ^ 4 :=
by
  intro h
  have hp : (p : ℤ) ^ 4 = (a : ℤ) ^ 4 + (b : ℤ) ^ 4 := by exact_mod_cast h
  have h1 : (a : ℤ) ^ 4 + (b : ℤ) ^ 4 = ((p : ℤ) ^ 2) ^ 2 := by
    calc (a : ℤ) ^ 4 + (b : ℤ) ^ 4 = (p : ℤ) ^ 4 := hp.symm
      _ = ((p : ℤ) ^ 2) ^ 2 := by ring
  have ha' : (a : ℤ) ≠ 0 := by exact_mod_cast ha
  have hb' : (b : ℤ) ≠ 0 := by exact_mod_cast hb
  exact not_fermat_42 ha' hb' h1

theorem pow_four_ge_16 {a : ℕ} (h : a ≥ 2) : a ^ 4 ≥ 16 :=
by
  -- `a ≥ 2` is definitionally equivalent to `2 ≤ a`
  have h1 : 2 ≤ a := h

  -- Apply monotonicity of exponentiation over the natural numbers
  have h2 : 2 ^ 4 ≤ a ^ 4 := by gcongr

  -- Since `2 ^ 4` is definitionally `16`, `h2` corresponds directly to our goal `a ^ 4 ≥ 16`
  exact h2

theorem not_add_pow_four_eq_eight (a b : ℕ) (ha : a ≠ 0) (hb : b ≠ 0) : a ^ 4 + b ^ 4 ≠ 8 :=
by
  intro h
  -- Analyze the possible values for 'a'
  by_cases ha_ge : a ≥ 2
  · -- Case: a ≥ 2
    have h16 := pow_four_ge_16 ha_ge
    -- omega treats `a^4` and `b^4` as unknown variables `X, Y ≥ 0`.
    -- Finding `X + Y = 8` and `X ≥ 16` contradicts `X, Y ≥ 0`, omega easily closes the goal.
    omega
  · -- Case: a < 2. Since a ≠ 0, it forces a = 1.
    have eq_a : a = 1 := by omega
    rcases eq_a with rfl

    -- Now analyze the possible values for 'b'
    by_cases hb_ge : b ≥ 2
    · -- Subcase: b ≥ 2
      have h16 := pow_four_ge_16 hb_ge
      -- The context reduces to `1^4 + b^4 = 8` and `b^4 ≥ 16`, handled seamlessly.
      omega
    · -- Subcase: b < 2. Since b ≠ 0, it forces b = 1.
      have eq_b : b = 1 := by omega
      rcases eq_b with rfl
      -- Substituting both leads to `1^4 + 1^4 = 8` meaning `2 = 8`, which yields a logical falsehood.
      revert h
      norm_num

theorem p_neq_two_of_p_cube_eq_add_pow_four (p a b : ℕ) (ha : a ≠ 0) (hb : b ≠ 0) (h : p ^ 3 = a ^ 4 + b ^ 4) :
  p ≠ 2 :=
by
  intro hp
  subst hp
  have h_eval : (2 : ℕ) ^ 3 = 8 := rfl
  rw [h_eval] at h
  exact not_add_pow_four_eq_eight a b ha hb h.symm

theorem dvd_add_pow_four {x a b : ℕ} (ha : x ∣ a) (hb : x ∣ b) : x ^ 4 ∣ a ^ 4 + b ^ 4 :=
by
  -- Unfold the definition of divisibility: a = x * c and b = x * d for some integers c, d
  rcases ha with ⟨c, rfl⟩
  rcases hb with ⟨d, rfl⟩

  -- Provide the witness for divisibility: c^4 + d^4
  use c ^ 4 + d ^ 4

  -- Use the `ring` tactic to automatically verify the polynomial identity
  -- (x * c) ^ 4 + (x * d) ^ 4 = x ^ 4 * (c ^ 4 + d ^ 4)
  ring

theorem dvd_of_pow_four_dvd {d n : ℕ} (h : d ^ 4 ∣ n) : d ∣ n :=
by
  rcases h with ⟨k, rfl⟩
  use d ^ 3 * k
  ring

theorem exists_eq_pow_of_dvd_prime_pow {d p k : ℕ} (hp : p.Prime) (h : d ∣ p ^ k) :
  ∃ j : ℕ, d = p ^ j :=
by
  obtain ⟨j, _, heq⟩ := (Nat.dvd_prime_pow hp).mp h
  exact ⟨j, heq⟩

theorem prime_pow_pos {p k : ℕ} (hp : p.Prime) : 0 < p ^ k :=
by
  have : 0 < p := hp.pos
  positivity

theorem pow_le_pow_of_dvd_pow {p j k : ℕ} (hp : p.Prime) (h : p ^ j ∣ p ^ k) : p ^ j ≤ p ^ k :=
by
  -- For natural numbers, if 0 < y and x ∣ y, then x ≤ y.
  apply Nat.le_of_dvd
  · exact prime_pow_pos hp
  · exact h

theorem prime_gt_one {p : ℕ} (hp : p.Prime) : 1 < p :=
Nat.Prime.one_lt hp

theorem pow_lt_pow_of_lt_right_of_gt_one {a j k : ℕ} (ha : 1 < a) (h : k < j) : a ^ k < a ^ j :=
pow_lt_pow_right₀ ha h

theorem le_of_pow_le_pow_of_gt_one {a j k : ℕ} (ha : 1 < a) (h : a ^ j ≤ a ^ k) : j ≤ k :=
by
  by_contra hnot
  have h_lt : k < j := by omega
  have h_pow_lt : a ^ k < a ^ j := pow_lt_pow_of_lt_right_of_gt_one ha h_lt
  omega

theorem exponent_le_of_pow_le_pow {p j k : ℕ} (hp : p.Prime) (h : p ^ j ≤ p ^ k) : j ≤ k :=
le_of_pow_le_pow_of_gt_one (prime_gt_one hp) h

theorem exponent_le_of_pow_dvd_pow {p j k : ℕ} (hp : p.Prime) (h : p ^ j ∣ p ^ k) :
  j ≤ k :=
exponent_le_of_pow_le_pow hp (pow_le_pow_of_dvd_pow hp h)

theorem eq_zero_of_four_mul_le_three {j : ℕ} (h : 4 * j ≤ 3) : j = 0 :=
by
  omega

theorem pow_four_of_eq_pow {d p j : ℕ} (h : d = p ^ j) : d ^ 4 = p ^ (4 * j) :=
by
  rw [h, ← pow_mul, mul_comm j 4]

theorem gcd_eq_one_of_pow_dvd_prime_pow {d p : ℕ} (hp : p.Prime) (h : d ^ 4 ∣ p ^ 3) :
  d = 1 :=
by
  have hd : d ∣ p ^ 3 := dvd_of_pow_four_dvd h
  obtain ⟨j, hj⟩ := exists_eq_pow_of_dvd_prime_pow hp hd
  have hpow4 : d ^ 4 = p ^ (4 * j) := pow_four_of_eq_pow hj
  have hpow : p ^ (4 * j) ∣ p ^ 3 := by
    rw [← hpow4]
    exact h
  have hle : 4 * j ≤ 3 := exponent_le_of_pow_dvd_pow hp hpow
  have hj0 : j = 0 := eq_zero_of_four_mul_le_three hle
  rw [hj0] at hj
  rw [Nat.pow_zero] at hj
  exact hj

theorem gcd_eq_one_of_p_cube_eq_add_pow_four (p a b : ℕ) (hp : p.Prime) (ha : a ≠ 0) (hb : b ≠ 0)
  (h : p ^ 3 = a ^ 4 + b ^ 4) : Nat.gcd a b = 1 :=
by
  have h_dvd_a : Nat.gcd a b ∣ a := Nat.gcd_dvd_left a b
  have h_dvd_b : Nat.gcd a b ∣ b := Nat.gcd_dvd_right a b
  have h_dvd_sum : (Nat.gcd a b) ^ 4 ∣ a ^ 4 + b ^ 4 := dvd_add_pow_four h_dvd_a h_dvd_b
  rw [← h] at h_dvd_sum
  exact gcd_eq_one_of_pow_dvd_prime_pow hp h_dvd_sum

theorem x_mul_y_re (a b : ℕ) : (x_val a b * y_val a b).re = (a : ℤ) ^ 4 + (b : ℤ) ^ 4 :=
by
  simp [x_val, y_val, Zsqrtd.mul_re]
  ring

theorem x_mul_y_im (a b : ℕ) : (x_val a b * y_val a b).im = 0 :=
by
  dsimp [x_val, y_val]
  simp
  ring

theorem gaussian_sq_re (z : GaussianInt) : (z ^ 2).re = z.re ^ 2 - z.im ^ 2 :=
by
  -- Expand the square to a product `z * z`
  rw [sq]
  -- Apply the multiplication rule for the real part of Zsqrtd (where d = -1 for GaussianInt)
  rw [Zsqrtd.mul_re]
  -- Solve the resulting integer arithmetic equality
  ring

theorem gaussian_sq_im (z : GaussianInt) : (z ^ 2).im = 2 * z.re * z.im :=
by
  rw [sq, Zsqrtd.mul_im]
  ring

theorem cube_re (z : GaussianInt) :
  (z ^ 3).re = z.re * (z.re ^ 2 - 3 * z.im ^ 2) :=
by
  have h : z ^ 3 = z ^ 2 * z := by ring
  rw [h]
  rw [Zsqrtd.mul_re]
  rw [gaussian_sq_re]
  rw [gaussian_sq_im]
  ring

theorem gaussian_natCast_re (n : ℕ) : (n : GaussianInt).re = (n : ℤ) :=
rfl

theorem gaussian_natCast_im (n : ℕ) : (n : GaussianInt).im = 0 :=
rfl

theorem p_cube_re (p : ℕ) : ((p : GaussianInt) ^ 3).re = (p : ℤ) ^ 3 :=
by
  -- Expand the real part of the cube of our Gaussian integer
  rw [cube_re]
  -- Substitute the real and imaginary parts of the natural number cast
  rw [gaussian_natCast_re, gaussian_natCast_im]
  -- Resolve the resulting integer arithmetic identity: p * (p^2 - 3 * 0^2) = p^3
  ring

theorem p_cube_im (p : ℕ) : ((p : GaussianInt) ^ 3).im = 0 :=
by
  have h : (p : GaussianInt) ^ 3 = ↑(p ^ 3) := by push_cast; rfl
  rw [h]
  rfl

theorem x_mul_y_eq (a b p : ℕ) (h : p ^ 3 = a ^ 4 + b ^ 4) :
  x_val a b * y_val a b = (p : GaussianInt) ^ 3 :=
by
  ext
  · -- Real part equality
    rw [x_mul_y_re, p_cube_re]
    -- We transition types manually to ensure a reliable substitution
    have h1 : (p : ℤ) ^ 3 = ((p ^ 3 : ℕ) : ℤ) := by push_cast; rfl
    have h2 : ((p ^ 3 : ℕ) : ℤ) = ((a ^ 4 + b ^ 4 : ℕ) : ℤ) := by rw [h]
    have h3 : ((a ^ 4 + b ^ 4 : ℕ) : ℤ) = (a : ℤ) ^ 4 + (b : ℤ) ^ 4 := by push_cast; rfl
    rw [← h3, ← h2, ← h1]
  · -- Imaginary part equality
    rw [x_mul_y_im, p_cube_im]

theorem isCoprime_of_gcd_eq_one (a b : ℕ) (h : Nat.gcd a b = 1) : IsCoprime (a : ℤ) (b : ℤ) :=
Nat.Coprime.isCoprime h

theorem isCoprime_sq_of_gcd_eq_one (a b : ℕ) (h : Nat.gcd a b = 1) :
  IsCoprime ((a : ℤ) ^ 2) ((b : ℤ) ^ 2) :=
by
  -- Convert the gcd hypothesis into integer coprimality
  have h1 : IsCoprime (a : ℤ) (b : ℤ) := isCoprime_of_gcd_eq_one a b h

  -- Apply right power property: a and b coprime → a and b^2 coprime
  have h2 : IsCoprime (a : ℤ) ((b : ℤ) ^ 2) := IsCoprime.pow_right h1

  -- Use symmetry of coprimality: a and b^2 coprime → b^2 and a coprime
  have h3 : IsCoprime ((b : ℤ) ^ 2) (a : ℤ) := IsCoprime.symm h2

  -- Apply right power property again: b^2 and a coprime → b^2 and a^2 coprime
  have h4 : IsCoprime ((b : ℤ) ^ 2) ((a : ℤ) ^ 2) := IsCoprime.pow_right h3

  -- Use symmetry one final time: b^2 and a^2 coprime → a^2 and b^2 coprime
  exact IsCoprime.symm h4

theorem gaussian_mul_re_helper (u v x y : ℤ) :
  ((⟨u, v⟩ : GaussianInt) * ⟨x, y⟩).re = u * x - v * y :=
by
  have h : (((⟨u, v⟩ : GaussianInt) * ⟨x, y⟩).re : ℝ) = ((u * x - v * y : ℤ) : ℝ) := by
    calc (((⟨u, v⟩ : GaussianInt) * ⟨x, y⟩).re : ℝ)
      _ = (GaussianInt.toComplex ((⟨u, v⟩ : GaussianInt) * ⟨x, y⟩)).re := by
        rw [GaussianInt.toComplex_def₂]
      _ = (GaussianInt.toComplex ⟨u, v⟩ * GaussianInt.toComplex ⟨x, y⟩).re := by
        rw [GaussianInt.toComplex_mul]
      _ = (GaussianInt.toComplex ⟨u, v⟩).re * (GaussianInt.toComplex ⟨x, y⟩).re - (GaussianInt.toComplex ⟨u, v⟩).im * (GaussianInt.toComplex ⟨x, y⟩).im := by
        rfl
      _ = (u : ℝ) * (x : ℝ) - (v : ℝ) * (y : ℝ) := by
        simp [GaussianInt.toComplex_re, GaussianInt.toComplex_im]
      _ = ((u * x - v * y : ℤ) : ℝ) := by
        push_cast
        ring
  exact_mod_cast h

theorem mul_x_val_re (a b : ℕ) (u v : ℤ) :
  ((⟨u, -v⟩ : GaussianInt) * x_val a b).re = u * ((a : ℤ) ^ 2) + v * ((b : ℤ) ^ 2) :=
by
  -- Expand the x_val structure
  unfold x_val

  -- Apply our algebraic helper abstraction
  rw [gaussian_mul_re_helper]

  -- Push natural number casts (if any were present inherently in x_val's definition) and solve
  push_cast
  ring

theorem mul_y_val_re (a b : ℕ) (u v : ℤ) :
  ((⟨u, v⟩ : GaussianInt) * y_val a b).re = u * ((a : ℤ) ^ 2) + v * ((b : ℤ) ^ 2) :=
by
  -- Unfold the definition of y_val explicitly
  have h1 : y_val a b = ⟨(a : ℤ) ^ 2, -((b : ℤ) ^ 2)⟩ := rfl
  rw [h1]

  -- Definitonally substitute the real projection of the multiplication product
  -- ((⟨u, v⟩ * ⟨A, B⟩).re evaluates precisely to u * A + d * v * B, where d = -1 for GaussianInt)
  change u * ((a : ℤ) ^ 2) + (-1 : ℤ) * v * -((b : ℤ) ^ 2) = u * ((a : ℤ) ^ 2) + v * ((b : ℤ) ^ 2)

  -- Solve the resulting integer arithmetic identity
  ring

theorem gaussian_add_re (z w : GaussianInt) : (z + w).re = z.re + w.re :=
rfl

theorem gaussian_linear_combination_re (a b : ℕ) (u v : ℤ) :
  ((⟨u, -v⟩ : GaussianInt) * x_val a b + (⟨u, v⟩ : GaussianInt) * y_val a b).re =
  2 * (u * ((a : ℤ) ^ 2) + v * ((b : ℤ) ^ 2)) :=
by
  -- Distribute `.re` over the addition
  rw [gaussian_add_re]

  -- Substitute the real part for each term using our lemmas
  rw [mul_x_val_re a b u v]
  rw [mul_y_val_re a b u v]

  -- The resulting algebraic equivalence `X + X = 2 * X` is solved automatically by `ring`
  ring

theorem gaussian_linear_combination_im (a b : ℕ) (u v : ℤ) :
  ((⟨u, -v⟩ : GaussianInt) * x_val a b + (⟨u, v⟩ : GaussianInt) * y_val a b).im = 0 :=
by
  simp [x_val, y_val]
  ring

theorem gaussianInt_ext {z w : GaussianInt} (hre : z.re = w.re) (him : z.im = w.im) : z = w :=
by
  have hz : z = ⟨z.re, z.im⟩ := by cases z; rfl
  have hw : w = ⟨w.re, w.im⟩ := by cases w; rfl
  rw [hz, hw, hre, him]

theorem gaussian_linear_combination (a b : ℕ) (u v : ℤ) (huv : u * ((a : ℤ) ^ 2) + v * ((b : ℤ) ^ 2) = 1) :
  (⟨u, -v⟩ : GaussianInt) * x_val a b + (⟨u, v⟩ : GaussianInt) * y_val a b = 2 :=
by
  apply gaussianInt_ext
  · rw [gaussian_linear_combination_re]
    rw [huv]
    rfl
  · rw [gaussian_linear_combination_im]
    rfl

theorem two_in_ideal_of_coprime_sq (a b : ℕ)
  (h_coprime : IsCoprime ((a : ℤ) ^ 2) ((b : ℤ) ^ 2)) :
  ∃ c d : GaussianInt, c * x_val a b + d * y_val a b = 2 :=
by
  obtain ⟨u, v, huv⟩ := h_coprime
  exact ⟨⟨u, -v⟩, ⟨u, v⟩, gaussian_linear_combination a b u v huv⟩

theorem odd_p_of_prime_neq_two (p : ℕ) (hp : p.Prime) (hp_odd : p ≠ 2) : Odd p :=
Nat.Prime.odd_of_ne_two hp hp_odd

theorem nat_coprime_two_p (p : ℕ) (hp : p.Prime) (hp_odd : p ≠ 2) : Nat.Coprime 2 p :=
by
  have h_odd : Odd p := odd_p_of_prime_neq_two p hp hp_odd
  exact Odd.coprime_two_left h_odd

theorem nat_coprime_two_p_pow_three (p : ℕ) (hp : p.Prime) (hp_odd : p ≠ 2) : Nat.Coprime 2 (p ^ 3) :=
by
  rw [Nat.coprime_pow_right_iff (by decide)]
  exact nat_coprime_two_p p hp hp_odd

theorem int_natAbs_p_pow_three (p : ℕ) : ((p : ℤ) ^ 3).natAbs = p ^ 3 :=
by
  have h : (p : ℤ) ^ 3 = (p ^ 3 : ℤ) := by norm_cast
  rw [h]
  rfl

theorem int_natAbs_two : (2 : ℤ).natAbs = 2 :=
rfl

theorem isCoprime_two_pow_three (p : ℕ) (hp : p.Prime) (hp_odd : p ≠ 2) :
  IsCoprime (2 : ℤ) ((p : ℤ) ^ 3) :=
by
  -- Convert IsCoprime in ℤ to Nat.Coprime in ℕ using natAbs
  rw [Int.isCoprime_iff_nat_coprime]

  -- Simplify the absolute values cleanly
  rw [int_natAbs_two]
  rw [int_natAbs_p_pow_three]

  -- The resulting goal is exactly the statement of our helper lemma
  exact nat_coprime_two_p_pow_three p hp hp_odd

theorem isCoprime_two_pow_three_gaussian (p : ℕ) (hp : p.Prime) (hp_odd : p ≠ 2) :
  IsCoprime (2 : GaussianInt) ((p : GaussianInt) ^ 3) :=
by
  -- Obtain the integer coefficients that satisfy the Bézout identity for coprimality
  obtain ⟨a, b, hab⟩ := isCoprime_two_pow_three p hp hp_odd

  -- Lift the Bézout identity strictly to GaussianInt
  have hab_cast : ((a * 2 + b * (p : ℤ) ^ 3 : ℤ) : GaussianInt) = ((1 : ℤ) : GaussianInt) := by
    rw [hab]

  -- Push the integer casts through the arithmetic operations downwards
  push_cast at hab_cast

  -- Provide the specific coefficients constructed and the transformed cast equality
  exact ⟨(a : GaussianInt), (b : GaussianInt), hab_cast⟩

theorem isCoprime_of_two_and_mul_in_ideal {x y : GaussianInt} {p : ℕ}
  (h2 : ∃ c d : GaussianInt, c * x + d * y = 2)
  (hp : IsCoprime (2 : GaussianInt) ((p : GaussianInt) ^ 3))
  (h_mul : x * y = (p : GaussianInt) ^ 3) :
  IsCoprime x y :=
by
  -- Destructure the existentials from our hypotheses
  rcases h2 with ⟨c, d, h2_eq⟩
  rcases hp with ⟨u, v, hp_eq⟩

  -- Provide the witnesses for the coprimality of x and y
  use u * c + v * y, u * d

  -- Prove that the linear combination equals 1
  calc
    (u * c + v * y) * x + (u * d) * y
      = u * (c * x + d * y) + v * (x * y) := by ring
    _ = u * 2 + v * ((p : GaussianInt) ^ 3) := by rw [h2_eq, h_mul]
    _ = 1 := hp_eq

theorem isCoprime_x_y (a b p : ℕ) (hp : p.Prime) (hp_odd : p ≠ 2)
  (h_gcd : Nat.gcd a b = 1) (h_eq : p ^ 3 = a ^ 4 + b ^ 4) :
  IsCoprime (x_val a b) (y_val a b) :=
by
  have h1 : IsCoprime ((a : ℤ) ^ 2) ((b : ℤ) ^ 2) := isCoprime_sq_of_gcd_eq_one a b h_gcd
  have h2 : ∃ c d : GaussianInt, c * x_val a b + d * y_val a b = 2 := two_in_ideal_of_coprime_sq a b h1
  have h3 : IsCoprime (2 : GaussianInt) ((p : GaussianInt) ^ 3) := isCoprime_two_pow_three_gaussian p hp hp_odd
  have h4 : x_val a b * y_val a b = (p : GaussianInt) ^ 3 := x_mul_y_eq a b p h_eq
  exact isCoprime_of_two_and_mul_in_ideal h2 h3 h4

theorem gaussian_is_unit_implies_norm_eq_one (u : GaussianInt) (hu : IsUnit u) : Zsqrtd.norm u = 1 :=
by
  have h : (-1 : ℤ) ≤ 0 := by decide
  exact (Zsqrtd.norm_eq_one_iff' h u).mpr hu

theorem gaussian_norm_eq (u : GaussianInt) : Zsqrtd.norm u = u.re ^ 2 + u.im ^ 2 :=
by
  rw [Zsqrtd.norm_def]
  ring

theorem int_add_eq_one_cases (x y : ℤ) (hx : 0 ≤ x) (hy : 0 ≤ y) (h : x + y = 1) :
  (x = 1 ∧ y = 0) ∨ (x = 0 ∧ y = 1) :=
by
  omega

theorem sq_add_sq_eq_one_cases (a b : ℤ) (h : a ^ 2 + b ^ 2 = 1) :
  (a ^ 2 = 1 ∧ b ^ 2 = 0) ∨ (a ^ 2 = 0 ∧ b ^ 2 = 1) :=
by
  have ha : 0 ≤ a ^ 2 := by positivity
  have hb : 0 ≤ b ^ 2 := by positivity
  exact int_add_eq_one_cases (a ^ 2) (b ^ 2) ha hb h

theorem int_sq_eq_zero (a : ℤ) (h : a ^ 2 = 0) : a = 0 :=
by
  exact sq_eq_zero_iff.mp h

theorem int_sq_eq_one (a : ℤ) (h : a ^ 2 = 1) : a = 1 ∨ a = -1 :=
sq_eq_one_iff.mp h

theorem int_sq_add_sq_eq_one (a b : ℤ) (h : a ^ 2 + b ^ 2 = 1) :
  (a = 1 ∧ b = 0) ∨ (a = -1 ∧ b = 0) ∨ (a = 0 ∧ b = 1) ∨ (a = 0 ∧ b = -1) :=
by
  rcases sq_add_sq_eq_one_cases a b h with ⟨h1, h2⟩ | ⟨h1, h2⟩
  · have hb : b = 0 := int_sq_eq_zero b h2
    have ha : a = 1 ∨ a = -1 := int_sq_eq_one a h1
    rcases ha with rfl | rfl
    · exact Or.inl ⟨rfl, hb⟩
    · exact Or.inr (Or.inl ⟨rfl, hb⟩)
  · have ha : a = 0 := int_sq_eq_zero a h1
    have hb : b = 1 ∨ b = -1 := int_sq_eq_one b h2
    rcases hb with rfl | rfl
    · exact Or.inr (Or.inr (Or.inl ⟨ha, rfl⟩))
    · exact Or.inr (Or.inr (Or.inr ⟨ha, rfl⟩))

theorem gaussian_unit_cases (u : GaussianInt) (hu : IsUnit u) :
  (u.re = 1 ∧ u.im = 0) ∨ (u.re = -1 ∧ u.im = 0) ∨ (u.re = 0 ∧ u.im = 1) ∨ (u.re = 0 ∧ u.im = -1) :=
by
  have h1 : Zsqrtd.norm u = 1 := gaussian_is_unit_implies_norm_eq_one u hu
  have h2 : Zsqrtd.norm u = u.re ^ 2 + u.im ^ 2 := gaussian_norm_eq u
  have h3 : u.re ^ 2 + u.im ^ 2 = 1 := by
    rw [h1] at h2
    exact h2.symm
  exact int_sq_add_sq_eq_one u.re u.im h3

theorem cube_im (z : GaussianInt) :
  (z ^ 3).im = z.im * (3 * z.re ^ 2 - z.im ^ 2) :=
by
  -- Expand the cube into repeated multiplications in the GaussianInt ring
  have h : z ^ 3 = z * z * z := by ring
  rw [h]

  -- Destruct the Gaussian integer into its real and imaginary parts (x and y)
  rcases z with ⟨x, y⟩

  -- The multiplication evaluates directly to the polynomial expression below by definitional equality:
  -- LHS: ((⟨x,y⟩ * ⟨x,y⟩) * ⟨x,y⟩).im
  -- RHS: y * (3 * x^2 - y^2)
  change (x * x + (-1 : ℤ) * y * y) * y + (x * y + y * x) * x = y * (3 * x ^ 2 - y ^ 2)

  -- The resulting polynomial equality strictly over ℤ is then automatically verified by ring
  ring

theorem exists_cube_of_isUnit (u : GaussianInt) (hu : IsUnit u) : ∃ v : GaussianInt, u = v ^ 3 :=
by
  rcases gaussian_unit_cases u hu with ⟨h1, h2⟩ | ⟨h1, h2⟩ | ⟨h1, h2⟩ | ⟨h1, h2⟩
  · use ⟨1, 0⟩
    ext
    · rw [h1, cube_re]
      norm_num
    · rw [h2, cube_im]
      norm_num
  · use ⟨-1, 0⟩
    ext
    · rw [h1, cube_re]
      norm_num
    · rw [h2, cube_im]
      norm_num
  · use ⟨0, -1⟩
    ext
    · rw [h1, cube_re]
      norm_num
    · rw [h2, cube_im]
      norm_num
  · use ⟨0, 1⟩
    ext
    · rw [h1, cube_re]
      norm_num
    · rw [h2, cube_im]
      norm_num

theorem exists_cube_of_associated_cube (x d : GaussianInt) (h : Associated (d ^ 3) x) :
  ∃ z : GaussianInt, x = z ^ 3 :=
by
  -- Unpack the `Associated` hypothesis, which provides a unit `u : GaussianIntˣ`
  -- and a definitional equality `d ^ 3 * ↑u = x`
  obtain ⟨u, rfl⟩ := h

  -- The coercion of a unit back into `GaussianInt` satisfies `IsUnit`
  have hu : IsUnit (u : GaussianInt) := ⟨u, rfl⟩

  -- Apply our lemma to extract the cube root of the unit
  obtain ⟨v, hv⟩ := exists_cube_of_isUnit (u : GaussianInt) hu

  -- Construct our existential witness `z` as `d * v`
  use d * v

  -- Substitute the unit for its perfect cube counterpart and verify with polynomial arithmetic
  rw [hv]
  ring

theorem exists_cube_of_coprime_mul_eq_cube_gaussian (x y c : GaussianInt)
  (h_coprime : IsCoprime x y) (h_eq : x * y = c ^ 3) :
  ∃ z : GaussianInt, x = z ^ 3 :=
by
  obtain ⟨d, hd⟩ := exists_associated_pow_of_mul_eq_pow' h_coprime h_eq
  exact exists_cube_of_associated_cube x d hd

theorem cube_sub_eq_mul (x y : ℤ) : x ^ 3 - y ^ 3 = (x - y) * (x ^ 2 + x * y + y ^ 2) :=
by
  ring

theorem twice_quad_form_eq_sum_sq (x y : ℤ) : (2 : ℤ) * (x ^ 2 + x * y + y ^ 2) = x ^ 2 + y ^ 2 + (x + y) ^ 2 :=
by
  ring

theorem sq_add_sq_add_sq_eq_zero_left {a b c : ℤ} (h : a ^ 2 + b ^ 2 + c ^ 2 = 0) : a = 0 :=
by
  have ha : 0 ≤ a ^ 2 := sq_nonneg a
  have hb : 0 ≤ b ^ 2 := sq_nonneg b
  have hc : 0 ≤ c ^ 2 := sq_nonneg c
  have ha2 : a ^ 2 = 0 := by omega
  exact sq_eq_zero_iff.mp ha2

theorem sq_add_sq_add_sq_eq_zero_mid_sq {a b c : ℤ} (h : a ^ 2 + b ^ 2 + c ^ 2 = 0) : b ^ 2 = 0 :=
by
  have ha : 0 ≤ a ^ 2 := by positivity
  have hb : 0 ≤ b ^ 2 := by positivity
  have hc : 0 ≤ c ^ 2 := by positivity
  linarith

theorem eq_zero_of_sq_eq_zero_int {x : ℤ} (h : x ^ 2 = 0) : x = 0 :=
sq_eq_zero_iff.mp h

theorem sq_add_sq_add_sq_eq_zero_mid {a b c : ℤ} (h : a ^ 2 + b ^ 2 + c ^ 2 = 0) : b = 0 :=
eq_zero_of_sq_eq_zero_int (sq_add_sq_add_sq_eq_zero_mid_sq h)

theorem sum_of_squares_eq_zero_imp_left_two {a b c : ℤ} (h : a ^ 2 + b ^ 2 + c ^ 2 = 0) : a = 0 ∧ b = 0 :=
by
  have h_a : a = 0 := sq_add_sq_add_sq_eq_zero_left h
  have h_b : b = 0 := sq_add_sq_add_sq_eq_zero_mid h
  exact ⟨h_a, h_b⟩

theorem quad_form_eq_zero_imp_zero {x y : ℤ} (h : x ^ 2 + x * y + y ^ 2 = 0) : x = 0 ∧ y = 0 :=
by
  have h1 : (2 : ℤ) * (x ^ 2 + x * y + y ^ 2) = 0 := by rw [h, mul_zero]
  have h2 : x ^ 2 + y ^ 2 + (x + y) ^ 2 = 0 := by
    rw [← twice_quad_form_eq_sum_sq x y]
    exact h1
  exact sum_of_squares_eq_zero_imp_left_two h2

theorem quad_form_eq_zero {x y : ℤ} (h : x ^ 2 + x * y + y ^ 2 = 0) : x = y :=
by
  have ⟨hx, hy⟩ := quad_form_eq_zero_imp_zero h
  rw [hx, hy]

theorem int_cube_inj {x y : ℤ} (h : x ^ 3 = y ^ 3) : x = y :=
by
  -- Convert the equality to a zero difference
  have h_sub : x ^ 3 - y ^ 3 = 0 := by
    rw [h, sub_self]

  -- Rewrite the difference of cubes into the factored form using our helper lemma
  have h_fact : x ^ 3 - y ^ 3 = (x - y) * (x ^ 2 + x * y + y ^ 2) := cube_sub_eq_mul x y
  rw [h_fact] at h_sub

  -- The product of two integers is zero iff at least one of them is zero
  have h_cases : x - y = 0 ∨ x ^ 2 + x * y + y ^ 2 = 0 := mul_eq_zero.mp h_sub

  -- Resolve the two cases
  cases h_cases with
  | inl h1 =>
    -- Case 1: x - y = 0
    omega
  | inr h2 =>
    -- Case 2: x^2 + xy + y^2 = 0
    exact quad_form_eq_zero h2

theorem z_cube_re_sq_add_im_sq (z : GaussianInt) :
  ((z ^ 3).re) ^ 2 + ((z ^ 3).im) ^ 2 = (z.re ^ 2 + z.im ^ 2) ^ 3 :=
by
  rw [cube_re, cube_im]
  ring

theorem x_val_re_sq_add_im_sq (a b : ℕ) :
  ((x_val a b).re) ^ 2 + ((x_val a b).im) ^ 2 = (a : ℤ) ^ 4 + (b : ℤ) ^ 4 :=
by
  simp [x_val]
  ring

theorem p_eq_norm_z (p a b : ℕ) (z : GaussianInt) (h : p ^ 3 = a ^ 4 + b ^ 4) (hz : x_val a b = z ^ 3) :
  (p : ℤ) = z.re ^ 2 + z.im ^ 2 :=
by

  -- Promote the main equality onto the integers securely
  have hp : (p : ℤ) ^ 3 = (a : ℤ) ^ 4 + (b : ℤ) ^ 4 := by
    have h' := congrArg (fun (x : ℕ) => (x : ℤ)) h
    push_cast at h'
    exact h'

  -- Equate the squared norms of both sides of the relation hz
  have hz_norm : ((x_val a b).re) ^ 2 + ((x_val a b).im) ^ 2 = ((z ^ 3).re) ^ 2 + ((z ^ 3).im) ^ 2 := by
    rw [hz]

  -- Chain the equivalences explicitly via calc
  have h_calc : (p : ℤ) ^ 3 = (z.re ^ 2 + z.im ^ 2) ^ 3 := by
    calc (p : ℤ) ^ 3 = (a : ℤ) ^ 4 + (b : ℤ) ^ 4 := hp
      _ = ((x_val a b).re) ^ 2 + ((x_val a b).im) ^ 2 := (x_val_re_sq_add_im_sq a b).symm
      _ = ((z ^ 3).re) ^ 2 + ((z ^ 3).im) ^ 2 := hz_norm
      _ = (z.re ^ 2 + z.im ^ 2) ^ 3 := z_cube_re_sq_add_im_sq z

  -- Finally, invoke the injectivity of odd integer powers
  exact int_cube_inj h_calc

theorem natAbs_int_cast_sq (a : ℕ) : ((a : ℤ) ^ 2).natAbs = a ^ 2 :=
by
  rw [← Nat.cast_pow]
  rfl

theorem nat_sq_eq_natAbs_of_int_sq_eq {a : ℕ} {x : ℤ} (h : (a : ℤ) ^ 2 = x) :
  a ^ 2 = x.natAbs :=
by
  rw [← h]
  exact (natAbs_int_cast_sq a).symm

theorem p_cube_eq_add_pow_four_implies_param (p a b : ℕ) (hp : p.Prime) (ha : a ≠ 0) (hb : b ≠ 0) (h : p ^ 3 = a ^ 4 + b ^ 4) :
  ∃ u v : ℤ,
  (p : ℤ) = u ^ 2 + v ^ 2 ∧
  ((a ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs ∧ b ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs) ∨
  (b ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs ∧ a ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs)) :=
by
  have hp2 : p ≠ 2 := p_neq_two_of_p_cube_eq_add_pow_four p a b ha hb h
  have hgcd : Nat.gcd a b = 1 := gcd_eq_one_of_p_cube_eq_add_pow_four p a b hp ha hb h
  have hcoprime : IsCoprime (x_val a b) (y_val a b) := isCoprime_x_y a b p hp hp2 hgcd h
  have hmul : x_val a b * y_val a b = (p : GaussianInt) ^ 3 := x_mul_y_eq a b p h

  -- Obtain the gaussian integer cube root
  obtain ⟨z, hz⟩ := exists_cube_of_coprime_mul_eq_cube_gaussian (x_val a b) (y_val a b) (p : GaussianInt) hcoprime hmul

  -- Instantiate existentials with the real and imaginary parts
  use z.re, z.im
  apply And.intro
  · exact p_eq_norm_z p a b z h hz
  · apply Or.inl
    apply And.intro
    · -- Prove first equivalence component by simple term rewriting without tactics
      have h1 : (a : ℤ) ^ 2 = (x_val a b).re := rfl
      have h2 : (x_val a b).re = (z ^ 3).re := congrArg Zsqrtd.re hz
      have h3 : (z ^ 3).re = z.re * (z.re ^ 2 - 3 * z.im ^ 2) := cube_re z
      have h4 : (a : ℤ) ^ 2 = z.re * (z.re ^ 2 - 3 * z.im ^ 2) := Eq.trans (Eq.trans h1 h2) h3
      exact nat_sq_eq_natAbs_of_int_sq_eq h4
    · -- Prove second equivalence component by simple term rewriting without tactics
      have h1 : (b : ℤ) ^ 2 = (x_val a b).im := rfl
      have h2 : (x_val a b).im = (z ^ 3).im := congrArg Zsqrtd.im hz
      have h3 : (z ^ 3).im = z.im * (3 * z.re ^ 2 - z.im ^ 2) := cube_im z
      have h4 : (b : ℤ) ^ 2 = z.im * (3 * z.re ^ 2 - z.im ^ 2) := Eq.trans (Eq.trans h1 h2) h3
      exact nat_sq_eq_natAbs_of_int_sq_eq h4

theorem my_gcd_dvd_left (u v : ℤ) : (Int.gcd u v : ℤ) ∣ u :=
Int.gcd_dvd_left u v

theorem my_gcd_dvd_right (u v : ℤ) : (Int.gcd u v : ℤ) ∣ v :=
by
  exact Int.gcd_dvd_right u v

theorem int_sq_dvd_add_sq {g u v : ℤ} (hu : g ∣ u) (hv : g ∣ v) : g ^ 2 ∣ u ^ 2 + v ^ 2 :=
by
  rcases hu with ⟨c, rfl⟩
  rcases hv with ⟨d, rfl⟩
  use c ^ 2 + d ^ 2
  ring

theorem nat_sq_dvd_of_int_sq_dvd {g p : ℕ} (h : (g : ℤ) ^ 2 ∣ (p : ℤ)) : g ^ 2 ∣ p :=
by
  exact_mod_cast h

theorem dvd_of_sq_dvd {g p : ℕ} (h : g ^ 2 ∣ p) : g ∣ p :=
by
  rcases h with ⟨c, rfl⟩
  use g * c
  ring

theorem dvd_one_of_sq_dvd_self {p : ℕ} (hp_nz : p ≠ 0) (h : p ^ 2 ∣ p) : p ∣ 1 :=
by
  rw [pow_two] at h
  have h1 : p * p ∣ p * 1 := by
    rw [mul_one p]
    exact h
  exact (mul_dvd_mul_iff_left hp_nz).mp h1

theorem not_prime_sq_dvd_prime {p : ℕ} (hp : p.Prime) : ¬ (p ^ 2 ∣ p) :=
by
  intro h
  have hp_nz : p ≠ 0 := hp.ne_zero
  have h_dvd_one : p ∣ 1 := dvd_one_of_sq_dvd_self hp_nz h
  exact Nat.Prime.not_dvd_one hp h_dvd_one

theorem eq_one_of_sq_dvd_prime {p g : ℕ} (hp : p.Prime) (h : g ^ 2 ∣ p) : g = 1 :=
by
  have h_dvd : g ∣ p := dvd_of_sq_dvd h
  have h_not_sq_dvd : ¬ (p ^ 2 ∣ p) := not_prime_sq_dvd_prime hp
  have h_or : g = 1 ∨ g = p := (Nat.dvd_prime hp).mp h_dvd
  cases h_or with
  | inl h1 => exact h1
  | inr h2 =>
    rw [h2] at h
    exact False.elim (h_not_sq_dvd h)

theorem isCoprime_of_gcd_eq_one_int {u v : ℤ} (h : Int.gcd u v = 1) : IsCoprime u v :=
Int.isCoprime_iff_gcd_eq_one.mpr h

theorem coprime_of_prime_eq_sum_sq (p : ℕ) (u v : ℤ) (hp : p.Prime) (h : (p : ℤ) = u ^ 2 + v ^ 2) : IsCoprime u v :=
by
  have hg_u : ((Int.gcd u v) : ℤ) ∣ u := my_gcd_dvd_left u v
  have hg_v : ((Int.gcd u v) : ℤ) ∣ v := my_gcd_dvd_right u v
  have h_sq : ((Int.gcd u v) : ℤ) ^ 2 ∣ u ^ 2 + v ^ 2 := int_sq_dvd_add_sq hg_u hg_v
  have h_p_dvd : ((Int.gcd u v) : ℤ) ^ 2 ∣ (p : ℤ) := by
    rw [← h] at h_sq
    exact h_sq
  have h_nat_dvd : (Int.gcd u v) ^ 2 ∣ p := nat_sq_dvd_of_int_sq_dvd h_p_dvd
  have h_g_eq_1 : Int.gcd u v = 1 := eq_one_of_sq_dvd_prime hp h_nat_dvd
  exact isCoprime_of_gcd_eq_one_int h_g_eq_1

theorem odd_mul_odd_sq_minus_three_sq_poly_id (k m : ℤ) :
  (2 * k + 1) * ((2 * k + 1) ^ 2 - 3 * (2 * m + 1) ^ 2) =
  4 * (2 * k ^ 3 + 3 * k ^ 2 - 6 * k * m ^ 2 - 6 * k * m - 3 * m ^ 2 - 3 * m - 1) + 2 :=
by
  ring

theorem mod_four_eq_two_of_eq_four_mul_add_two (x w : ℤ) (h : x = 4 * w + 2) :
  x % 4 = 2 :=
by
  omega

theorem odd_mul_odd_sq_minus_three_sq_mod_four (u v : ℤ) (hu : Odd u) (hv : Odd v) :
  (u * (u ^ 2 - 3 * v ^ 2)) % 4 = 2 :=
by
  obtain ⟨k, hk⟩ := hu
  obtain ⟨m, hm⟩ := hv
  rw [hk, hm]
  exact mod_four_eq_two_of_eq_four_mul_add_two _ _ (odd_mul_odd_sq_minus_three_sq_poly_id k m)

theorem neg_mod_four_eq_two {x : ℤ} (hx : x % 4 = 2) : (-x) % 4 = 2 :=
by
  omega

theorem natAbs_mod_four_eq_two_of_mod_four_eq_two (x : ℤ) (hx : x % 4 = 2) :
  (x.natAbs : ℤ) % 4 = 2 :=
by
  -- Explicitly determine that the absolute value evaluates to x or -x
  have h1 : (x.natAbs : ℤ) = x ∨ (x.natAbs : ℤ) = -x := by omega
  cases h1 with
  | inl h_pos =>
    -- If x is non-negative, (x.natAbs : ℤ) = x, so we substitute and use the original hypothesis directly.
    rw [h_pos]
    exact hx
  | inr h_neg =>
    -- If x is negative, (x.natAbs : ℤ) = -x, so we substitute and invoke the sub-lemma.
    rw [h_neg]
    exact neg_mod_four_eq_two hx

theorem sq_mod_four_ne_two (a : ℤ) : a ^ 2 % 4 ≠ 2 :=
by
  rw [sq]
  exact Int.sq_ne_two_mod_four a

theorem both_odd_impossible (u v : ℤ) (a : ℕ) (hu : Odd u) (hv : Odd v)
  (ha : a ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs) : False :=
by
  have h1 : (u * (u ^ 2 - 3 * v ^ 2)) % 4 = 2 := odd_mul_odd_sq_minus_three_sq_mod_four u v hu hv
  have h2 : ((u * (u ^ 2 - 3 * v ^ 2)).natAbs : ℤ) % 4 = 2 := natAbs_mod_four_eq_two_of_mod_four_eq_two _ h1
  have h3 : (a : ℤ) ^ 2 = ((u * (u ^ 2 - 3 * v ^ 2)).natAbs : ℤ) := by
    rw [← ha]
    push_cast
    rfl
  have h4 : (a : ℤ) ^ 2 % 4 = 2 := by
    rw [h3]
    exact h2
  exact sq_mod_four_ne_two (a : ℤ) h4

theorem both_even_impossible (u v : ℤ) (hcoprime : IsCoprime u v) (hu : Even u) (hv : Even v) : False :=
by
  -- Destruct the coprime assumption to extract Bezout's coefficients
  rcases hcoprime with ⟨a, b, hab⟩

  -- Destruct the parity assumptions and substitute u and v with 2 * ku and 2 * kv
  rcases hu with ⟨ku, rfl⟩
  rcases hv with ⟨kv, rfl⟩

  -- Isolate the factor of 2 dynamically from the Bezout identity
  have h : 2 * (a * ku + b * kv) = 1 := by
    rw [← hab]
    ring

  -- omega finds the integer contradiction of 2 * Z = 1
  omega

theorem v_sq_eq_V_pow_four (v : ℤ) (V : ℕ) (hV : v.natAbs = V ^ 2) : v ^ 2 = (V : ℤ) ^ 4 :=
by
  rw [← Int.natAbs_sq v]
  rw [hV]
  push_cast
  ring

theorem even_V_of_even_v (v : ℤ) (V : ℕ) (hV : v.natAbs = V ^ 2) (hv : Even v) : Even (V : ℤ) :=
by
  have h1 : v ^ 2 = (V : ℤ) ^ 4 := v_sq_eq_V_pow_four v V hV
  have h2 : Even (v ^ 2) := Int.even_pow.mpr ⟨hv, by decide⟩
  have h3 : Even ((V : ℤ) ^ 4) := h1 ▸ h2
  exact (Int.even_pow.mp h3).1

theorem odd_nat_of_sq_odd (W : ℕ) (h : Odd (W ^ 2)) : Odd W :=
by
  have h_ne : 2 ≠ 0 := by decide
  exact (Nat.odd_pow_iff h_ne).mp h

theorem odd_W_of_odd_w (w : ℤ) (W : ℕ) (hW : w.natAbs = W ^ 2) (hw : Odd w) : Odd (W : ℤ) :=
by
  rw [Int.odd_coe_nat W]
  have h1 : Odd w.natAbs := by
    rw [Int.natAbs_odd]
    exact hw
  rw [hW] at h1
  exact odd_nat_of_sq_odd W h1

theorem w_sq_eq_W_pow_four (w : ℤ) (W : ℕ) (hW : w.natAbs = W ^ 2) : w ^ 2 = (W : ℤ) ^ 4 :=
by
  -- The natural absolute value of w matches the natural absolute value of its integer cast.
  have h_eq : w.natAbs = (w.natAbs : ℤ).natAbs := rfl

  -- From `a.natAbs = b.natAbs ↔ a * a = b * b`, we establish that squaring w
  -- is equivalent to squaring its integer casted absolute value.
  have h1 : w * w = (w.natAbs : ℤ) * (w.natAbs : ℤ) := Int.natAbs_eq_iff_mul_self_eq.mp h_eq

  -- Substitute the hypothesis `hW` and push the integer casts appropriately.
  have h2 : (w.natAbs : ℤ) = (W : ℤ) ^ 2 := by simp [hW]

  -- A unified calculation block leading directly to the target.
  calc
    w ^ 2 = w * w := by ring
    _ = (w.natAbs : ℤ) * (w.natAbs : ℤ) := h1
    _ = (w.natAbs : ℤ) ^ 2 := by ring
    _ = ((W : ℤ) ^ 2) ^ 2 := by rw [h2]
    _ = (W : ℤ) ^ 4 := by ring

theorem eq_sq_of_natAbs_eq_sq_ofNat (n S : ℕ) (hS : S ^ 2 = (Int.ofNat n).natAbs) :
  Int.ofNat n = (S : ℤ) ^ 2 :=
by
  -- Convert the raw `Int.ofNat n` constructor into standard standard coercion `(n : ℤ)`
  -- so that the `push_cast` tactic easily recognizes it.
  change (n : ℤ) = (S : ℤ) ^ 2

  -- `(Int.ofNat n).natAbs` is definitionally `n`, hence `hS.symm` has exactly the type `n = S ^ 2`.
  have hn : n = S ^ 2 := hS.symm

  -- Substitute `n`
  rw [hn]

  -- Push the integer cast inward over the exponentiation
  -- to equate `↑(S ^ 2)` with `(↑S) ^ 2`
  push_cast
  rfl

theorem neg_eq_sq_of_natAbs_eq_sq_negSucc (n S : ℕ) (hS : S ^ 2 = (Int.negSucc n).natAbs) :
  -(Int.negSucc n) = (S : ℤ) ^ 2 :=
by
  -- `-(Int.negSucc n)` and `((Int.negSucc n).natAbs : ℤ)` both evaluate to `(n + 1 : ℤ)` definitionally.
  have h1 : -(Int.negSucc n) = ((Int.negSucc n).natAbs : ℤ) := rfl

  -- Rewrite using the definitional equality and the reversed hypothesis
  rw [h1, ← hS]

  -- Push the integer cast inward over the exponentiation
  push_cast
  rfl

theorem eq_sq_or_neg_eq_sq_of_natAbs_eq_sq (z : ℤ) (S : ℕ) (hS : S ^ 2 = z.natAbs) :
  z = (S : ℤ) ^ 2 ∨ -z = (S : ℤ) ^ 2 :=
by
  cases z with
  | ofNat n =>
    left
    exact eq_sq_of_natAbs_eq_sq_ofNat n S hS
  | negSucc n =>
    right
    exact neg_eq_sq_of_natAbs_eq_sq_negSucc n S hS

theorem mul_eq_sq_or_mul_neg_eq_sq (x y : ℤ) (S : ℕ) (hS : S ^ 2 = (x * y).natAbs) :
  x * y = (S : ℤ) ^ 2 ∨ x * (-y) = (S : ℤ) ^ 2 :=
by
  cases eq_sq_or_neg_eq_sq_of_natAbs_eq_sq (x * y) S hS with
  | inl h1 =>
    exact Or.inl h1
  | inr h2 =>
    apply Or.inr
    have h_eq : x * (-y) = -(x * y) := by ring
    rw [h_eq]
    exact h2

theorem natAbs_eq_of_associated {a b : ℤ} (h : Associated a b) : a.natAbs = b.natAbs :=
Int.associated_iff_natAbs.mp h

theorem natAbs_pow_two (d : ℤ) : (d ^ 2).natAbs = d.natAbs ^ 2 :=
by
  -- Expand both squares into multiplications:
  -- d ^ 2 becomes d * d, and d.natAbs ^ 2 becomes d.natAbs * d.natAbs
  simp only [sq]
  -- Apply the multiplicativity property of the integer natural absolute value
  exact Int.natAbs_mul d d

theorem natAbs_eq_sq_of_isCoprime_mul_eq_sq (x y c : ℤ) (hcop : IsCoprime x y) (hmul : x * y = c ^ 2) :
  ∃ X : ℕ, x.natAbs = X ^ 2 :=
by
  -- Since ℤ is a PID, coprime factors of a perfect square are themselves associated with perfect squares
  obtain ⟨d, hd⟩ := exists_associated_pow_of_mul_eq_pow' hcop hmul

  -- We provide the absolute value of `d` as our witness `X`
  use d.natAbs

  -- Since `d^2` is associated with `x`, their absolute values are identical
  rw [← natAbs_eq_of_associated hd]

  -- Lastly, we push the absolute value inside the square
  exact natAbs_pow_two d

theorem isCoprime_neg_right_aux (x y : ℤ) (h : IsCoprime x y) : IsCoprime x (-y) :=
h.neg_right

theorem exists_sq_eq_natAbs_of_coprime_mul_eq_sq_left (x y : ℤ) (S : ℕ)
  (hcop : IsCoprime x y) (hS : S ^ 2 = (x * y).natAbs) :
  ∃ X : ℕ, x.natAbs = X ^ 2 :=
by
  have h_or := mul_eq_sq_or_mul_neg_eq_sq x y S hS
  cases h_or with
  | inl h1 =>
    exact natAbs_eq_sq_of_isCoprime_mul_eq_sq x y (S : ℤ) hcop h1
  | inr h2 =>
    have hcop_neg : IsCoprime x (-y) := isCoprime_neg_right_aux x y hcop
    exact natAbs_eq_sq_of_isCoprime_mul_eq_sq x (-y) (S : ℤ) hcop_neg h2

theorem exists_sq_eq_natAbs_of_coprime_mul_eq_sq_right (x y : ℤ) (S : ℕ)
  (hcop : IsCoprime x y) (hS : S ^ 2 = (x * y).natAbs) :
  ∃ Y : ℕ, y.natAbs = Y ^ 2 :=
by
  have h_or := Int.natAbs_eq_iff.mp hS.symm
  have hc : ((S ^ 2 : ℕ) : ℤ) = (S : ℤ) ^ 2 := by push_cast; rfl
  rw [hc] at h_or
  rcases h_or with h_pos | h_neg
  · have hyx : y * x = (S : ℤ) ^ 2 := by
      calc y * x
        _ = x * y := mul_comm y x
        _ = (S : ℤ) ^ 2 := h_pos
    have hyx_cop : IsCoprime y x := by
      obtain ⟨a, b, hab⟩ := hcop
      use b, a
      calc b * y + a * x
        _ = a * x + b * y := by ring
        _ = 1 := hab
    rcases Int.sq_of_isCoprime hyx_cop hyx with ⟨y0, hy0⟩
    use y0.natAbs
    rcases hy0 with hy0_pos | hy0_neg
    · rw [hy0_pos]
      calc (y0 ^ 2).natAbs
        _ = (y0 * y0).natAbs := by rw [sq]
        _ = y0.natAbs * y0.natAbs := by rw [Int.natAbs_mul]
        _ = y0.natAbs ^ 2 := by rw [←sq]
    · rw [hy0_neg]
      calc (- (y0 ^ 2)).natAbs
        _ = (y0 ^ 2).natAbs := by rw [Int.natAbs_neg]
        _ = (y0 * y0).natAbs := by rw [sq]
        _ = y0.natAbs * y0.natAbs := by rw [Int.natAbs_mul]
        _ = y0.natAbs ^ 2 := by rw [←sq]
  · have hyx : y * (-x) = (S : ℤ) ^ 2 := by
      calc y * (-x)
        _ = -(x * y) := by ring
        _ = - -(S : ℤ) ^ 2 := by rw [h_neg]
        _ = (S : ℤ) ^ 2 := by ring
    have hyx_cop : IsCoprime y (-x) := by
      obtain ⟨a, b, hab⟩ := hcop
      use b, -a
      calc b * y + (-a) * (-x)
        _ = a * x + b * y := by ring
        _ = 1 := hab
    rcases Int.sq_of_isCoprime hyx_cop hyx with ⟨y0, hy0⟩
    use y0.natAbs
    rcases hy0 with hy0_pos | hy0_neg
    · rw [hy0_pos]
      calc (y0 ^ 2).natAbs
        _ = (y0 * y0).natAbs := by rw [sq]
        _ = y0.natAbs * y0.natAbs := by rw [Int.natAbs_mul]
        _ = y0.natAbs ^ 2 := by rw [←sq]
    · rw [hy0_neg]
      calc (- (y0 ^ 2)).natAbs
        _ = (y0 ^ 2).natAbs := by rw [Int.natAbs_neg]
        _ = (y0 * y0).natAbs := by rw [sq]
        _ = y0.natAbs * y0.natAbs := by rw [Int.natAbs_mul]
        _ = y0.natAbs ^ 2 := by rw [←sq]

theorem absurd_of_ineqs (u v : ℤ) (h1 : v ^ 2 > 3 * u ^ 2) (h2 : u ^ 2 > 3 * v ^ 2) : False :=
by
  have h3 : 0 ≤ u ^ 2 := by positivity
  have h4 : 0 ≤ v ^ 2 := by positivity
  linarith

theorem even_pow_four_eq_eight_mul (x : ℤ) (hx : Even x) : ∃ m : ℤ, x ^ 4 = 8 * m :=
by
  -- Since x is even, it can be written as 2 * k for some integer k.
  obtain ⟨k, hk⟩ := even_iff_exists_two_mul.mp hx

  -- We provide the witness m = 2 * k ^ 4
  use 2 * k ^ 4

  -- Substitute x with 2 * k in the goal
  rw [hk]

  -- Prove the resulting algebraic equivalence (2 * k) ^ 4 = 8 * (2 * k ^ 4)
  ring

theorem odd_pow_four_expansion (k : ℤ) :
  (2 * k + 1) ^ 4 = 8 * (2 * k ^ 4 + 4 * k ^ 3 + 3 * k ^ 2 + k) + 1 :=
by
  ring

theorem odd_pow_four_eq_eight_mul_add_one (x : ℤ) (hx : Odd x) : ∃ m : ℤ, x ^ 4 = 8 * m + 1 :=
by
  -- Destruct `Odd x` into the integer `k` and the equation `x = 2 * k + 1`
  obtain ⟨k, hk⟩ := hx

  -- Provide the explicit algebraic witness `m`
  use 2 * k ^ 4 + 4 * k ^ 3 + 3 * k ^ 2 + k

  -- Rewrite `x` to its odd representation
  rw [hk]

  -- Apply the pure algebraic identity lemma
  exact odd_pow_four_expansion k

theorem sq_mod_four_eq_zero (q m : ℤ) (h : (4 * q) ^ 2 = 8 * m + 5) : False :=
by
  have h_expand : (4 * q) ^ 2 = 16 * q ^ 2 := by ring
  rw [h_expand] at h
  omega

theorem sq_mod_four_eq_one (q m : ℤ) (h : (4 * q + 1) ^ 2 = 8 * m + 5) : False :=
by
  have h_expand : (4 * q + 1) ^ 2 = 16 * q ^ 2 + 8 * q + 1 := by ring
  rw [h_expand] at h
  omega

theorem sq_mod_four_eq_two (q m : ℤ) (h : (4 * q + 2) ^ 2 = 8 * m + 5) : False :=
by
  have h_expand : (4 * q + 2) ^ 2 = 8 * (2 * q ^ 2 + 2 * q) + 4 := by ring
  rw [h_expand] at h
  omega

theorem sq_mod_four_eq_three (q m : ℤ) (h : (4 * q + 3) ^ 2 = 8 * m + 5) : False :=
by
  have h_expand : (4 * q + 3) ^ 2 = 8 * (2 * q ^ 2 + 3 * q + 1) + 1 := by ring
  rw [h_expand] at h
  omega

theorem sq_ne_eight_mul_add_five (x m : ℤ) : x ^ 2 ≠ 8 * m + 5 :=
by
  intro h
  have hr : x % 4 = 0 ∨ x % 4 = 1 ∨ x % 4 = 2 ∨ x % 4 = 3 := by omega
  rcases hr with h0 | h1 | h2 | h3
  · have hx : x = 4 * (x / 4) := by omega
    rw [hx] at h
    exact sq_mod_four_eq_zero (x / 4) m h
  · have hx : x = 4 * (x / 4) + 1 := by omega
    rw [hx] at h
    exact sq_mod_four_eq_one (x / 4) m h
  · have hx : x = 4 * (x / 4) + 2 := by omega
    rw [hx] at h
    exact sq_mod_four_eq_two (x / 4) m h
  · have hx : x = 4 * (x / 4) + 3 := by omega
    rw [hx] at h
    exact sq_mod_four_eq_three (x / 4) m h

theorem V_pow_four_sub_three_W_pow_four_ne_sq (V W F : ℕ)
  (hV : Even (V : ℤ)) (hW : Odd (W : ℤ)) (h : (V : ℤ) ^ 4 - 3 * (W : ℤ) ^ 4 = (F : ℤ) ^ 2) : False :=
by
  rcases even_pow_four_eq_eight_mul (V : ℤ) hV with ⟨a, ha⟩
  rcases odd_pow_four_eq_eight_mul_add_one (W : ℤ) hW with ⟨b, hb⟩
  have h_eq : (F : ℤ) ^ 2 = 8 * (a - 3 * b - 1) + 5 := by
    rw [← h, ha, hb]
    ring
  exact sq_ne_eight_mul_add_five (F : ℤ) (a - 3 * b - 1) h_eq

theorem coprime_symm_int {a b : ℤ} (h : IsCoprime a b) : IsCoprime b a :=
h.symm

theorem mod_3_eq_one_or_two_int (v : ℤ) (h3 : ¬ 3 ∣ v) : v % (3 : ℤ) = 1 ∨ v % (3 : ℤ) = 2 :=
by
  omega

theorem coprime_v_3_of_mod_1_int (v : ℤ) (h : v % (3 : ℤ) = 1) : IsCoprime v 3 :=
by
  -- Provide the witnesses for Bézout's identity: 1 and -(v / 3)
  use 1, -(v / (3 : ℤ))
  -- `omega` can effortlessly verify the linear integer arithmetic with division and modulo
  omega

theorem coprime_v_3_of_mod_2_int (v : ℤ) (h : v % (3 : ℤ) = 2) : IsCoprime v 3 :=
by
  use 2, -(2 * (v / (3 : ℤ)) + 1)
  omega

theorem coprime_v_3_int (v : ℤ) (h3 : ¬ 3 ∣ v) : IsCoprime v 3 :=
by
  have h_cases := mod_3_eq_one_or_two_int v h3
  cases h_cases with
  | inl h1 =>
    exact coprime_v_3_of_mod_1_int v h1
  | inr h2 =>
    exact coprime_v_3_of_mod_2_int v h2

theorem coprime_sq_right_int {a b : ℤ} (h : IsCoprime a b) : IsCoprime a (b ^ 2) :=
by
  -- Since 'a' is coprime to 'b', and 'a' is coprime to 'b',
  -- it implies 'a' is coprime to 'b * b'
  have H := IsCoprime.mul_right h h
  -- Equate b ^ 2 to b * b
  have eq : b ^ 2 = b * b := by ring
  -- Substitute this equivalence into the goal
  rw [eq]
  exact H

theorem coprime_mul_right_int {a b c : ℤ} (h1 : IsCoprime a b) (h2 : IsCoprime a c) : IsCoprime a (b * c) :=
IsCoprime.mul_right h1 h2

theorem coprime_sub_sq_int {a b : ℤ} (h : IsCoprime a b) : IsCoprime a (b - a ^ 2) :=
by
  rcases h with ⟨u, v, huv⟩
  use u + v * a, v
  have h_eq : (u + v * a) * a + v * (b - a ^ 2) = u * a + v * b := by ring
  rw [h_eq]
  exact huv

theorem coprime_v_3u2_sub_v2 (u v : ℤ) (hcop : IsCoprime u v) (h3 : ¬ 3 ∣ v) :
  IsCoprime v (3 * u ^ 2 - v ^ 2) :=
by
  have h1 : IsCoprime v u := coprime_symm_int hcop
  have h2 : IsCoprime v (u ^ 2) := coprime_sq_right_int h1
  have h3_cop : IsCoprime v 3 := coprime_v_3_int v h3
  have h4 : IsCoprime v (3 * u ^ 2) := coprime_mul_right_int h3_cop h2
  exact coprime_sub_sq_int h4

theorem int_even_or_odd_cases (C : ℤ) : Even C ∨ Odd C :=
Int.even_or_odd C

theorem sq_of_add_self (k : ℤ) : (k + k) ^ 2 = 4 * k ^ 2 :=
by
  ring

theorem four_mul_mod_four_eq_zero (m : ℤ) : (4 * m) % (4 : ℤ) = 0 :=
by
  omega

theorem sq_mod_four_eq_zero_of_even_cases (C : ℤ) (h : Even C) : C ^ 2 % (4 : ℤ) = 0 :=
by
  -- Destruct the evenness hypothesis, which by Lean 4's definition gives C = k + k for some integer k
  obtain ⟨k, hk⟩ := h

  -- Substitute C with k + k in the goal
  rw [hk]

  -- Expand the square (k + k)^2 to 4 * k^2
  rw [sq_of_add_self k]

  -- We are left with (4 * k^2) % 4 = 0, which perfectly matches Lemma 2
  exact four_mul_mod_four_eq_zero (k ^ 2)

theorem odd_sq_eq_four_mul_add_one (k : ℤ) : (2 * k + 1) ^ 2 = 4 * (k ^ 2 + k) + 1 :=
by
  ring

theorem four_mul_add_one_mod_four (m : ℤ) : (4 * m + 1) % (4 : ℤ) = 1 :=
by
  omega

theorem sq_mod_four_eq_one_of_odd_cases (C : ℤ) (h : Odd C) : C ^ 2 % (4 : ℤ) = 1 :=
by
  rcases h with ⟨k, hk⟩
  rw [hk]
  rw [odd_sq_eq_four_mul_add_one k]
  exact four_mul_add_one_mod_four (k ^ 2 + k)

theorem sq_mod_four_cases (C : ℤ) : C ^ 2 % (4 : ℤ) = 0 ∨ C ^ 2 % (4 : ℤ) = 1 :=
Or.elim (int_even_or_odd_cases C)
    (fun h_even => Or.inl (sq_mod_four_eq_zero_of_even_cases C h_even))
    (fun h_odd => Or.inr (sq_mod_four_eq_one_of_odd_cases C h_odd))

theorem sq_mod_four_ne_three (C : ℤ) : C ^ 2 % (4 : ℤ) ≠ 3 :=
by
  have h := sq_mod_four_cases C
  omega

theorem three_u2_sub_v2_mod_four_eq_three (u v : ℤ) (hu_odd : Odd u) (hv_even : Even v) :
  (3 * u ^ 2 - v ^ 2) % (4 : ℤ) = 3 :=
by
  -- Extract integer witnesses for the odd and even hypotheses
  rcases hu_odd with ⟨k, hk⟩
  rcases hv_even with ⟨m, hm⟩

  -- Create an algebraic identity for the substitution
  have h_eq : 3 * u ^ 2 - v ^ 2 = 4 * (3 * k ^ 2 + 3 * k - m ^ 2) + 3 := by
    rw [hk, hm]
    ring

  -- Substitute the simplified multiple of 4 expression back into the goal
  rw [h_eq]

  -- omega natively resolves linear operations over integer remainders cleanly
  omega

theorem sq_eq_three_u2_sub_v2_absurd (u v C : ℤ) (hu_odd : Odd u) (hv_even : Even v) (h : 3 * u ^ 2 - v ^ 2 = C ^ 2) : False :=
by
  have h1 := three_u2_sub_v2_mod_four_eq_three u v hu_odd hv_even
  rw [h] at h1
  have h2 := sq_mod_four_ne_three C
  exact h2 h1

theorem three_u2_sub_v2_neg (u v : ℤ) (C : ℕ)
  (hu_odd : Odd u) (hv_even : Even v)
  (hC : (3 * u ^ 2 - v ^ 2).natAbs = C ^ 2) :
  3 * u ^ 2 - v ^ 2 < 0 :=
by
  by_contra h
  push_neg at h

  -- Show that stripping the `natAbs` and coercing to ℤ keeps equality
  have h_eq : 3 * u ^ 2 - v ^ 2 = (C : ℤ) ^ 2 := by
    calc
      3 * u ^ 2 - v ^ 2 = ((3 * u ^ 2 - v ^ 2).natAbs : ℤ) := by omega
      _ = ((C ^ 2 : ℕ) : ℤ) := by rw [hC]
      _ = (C : ℤ) ^ 2 := by push_cast; rfl

  -- Now apply the helper lemma resolving the contradictory properties modulo 4
  exact sq_eq_three_u2_sub_v2_absurd u v (C : ℤ) hu_odd hv_even h_eq

theorem v2_gt_3u2_of_neg (u v : ℤ) (h_neg : 3 * u ^ 2 - v ^ 2 < 0) :
  v ^ 2 > 3 * u ^ 2 :=
by
  linarith

theorem not_dvd_implies_mod_ne_zero (u : ℤ) (h : ¬ 3 ∣ u) : u % (3 : ℤ) ≠ (0 : ℤ) :=
by
  omega

theorem mod_three_eq_one_or_two (u : ℤ) (h : ¬ 3 ∣ u) : u % (3 : ℤ) = (1 : ℤ) ∨ u % (3 : ℤ) = (2 : ℤ) :=
by
  have h_mod := not_dvd_implies_mod_ne_zero u h
  omega

theorem mod_three_eq_one_bezout (u : ℤ) (h : u % (3 : ℤ) = (1 : ℤ)) :
  (1 : ℤ) * u + (- (u / (3 : ℤ))) * (3 : ℤ) = (1 : ℤ) :=
by
  omega

theorem coprime_u_three_of_mod_one (u : ℤ) (h : u % (3 : ℤ) = (1 : ℤ)) : IsCoprime u 3 :=
by
  use (1 : ℤ), (- (u / (3 : ℤ)))
  exact mod_three_eq_one_bezout u h

theorem mod_three_eq_two_bezout (u : ℤ) (h : u % (3 : ℤ) = (2 : ℤ)) :
  (-1 : ℤ) * u + (u / (3 : ℤ) + (1 : ℤ)) * (3 : ℤ) = (1 : ℤ) :=
by
  omega

theorem coprime_u_three_of_mod_two (u : ℤ) (h : u % (3 : ℤ) = (2 : ℤ)) : IsCoprime u 3 :=
by
  use (-1 : ℤ), (u / (3 : ℤ) + (1 : ℤ))
  exact mod_three_eq_two_bezout u h

theorem coprime_u_three (u : ℤ) (h : ¬ 3 ∣ u) : IsCoprime u 3 :=
by
  have h_cases := mod_three_eq_one_or_two u h
  cases h_cases with
  | inl h1 => exact coprime_u_three_of_mod_one u h1
  | inr h2 => exact coprime_u_three_of_mod_two u h2

theorem coprime_u_three_v_sq (u v : ℤ) (hcop : IsCoprime u v) (h3 : ¬ 3 ∣ u) :
  IsCoprime u (3 * v ^ 2) :=
by
  have h1 : IsCoprime u 3 := coprime_u_three u h3
  have h2 : IsCoprime u (v ^ 2) := IsCoprime.pow_right hcop
  exact IsCoprime.mul_right h1 h2

theorem coprime_u_u2_sub_3v2 (u v : ℤ) (hcop : IsCoprime u v) (h3 : ¬ 3 ∣ u) :
  IsCoprime u (u ^ 2 - 3 * v ^ 2) :=
by
  -- Retrieve coprimality of u and 3 * v^2 which provides our starting Bezout identity
  have h1 : IsCoprime u (3 * v ^ 2) := coprime_u_three_v_sq u v hcop h3

  -- Obtain the Bezout coefficients a and b such that a * u + b * (3 * v^2) = 1
  obtain ⟨a, b, hab⟩ := h1

  -- We want to show ∃ X Y, X * u + Y * (u^2 - 3 * v^2) = 1
  -- We can use X = a + b * u and Y = -b
  use a + b * u, -b

  -- Verify the algebraic identity equals 1 utilizing our previous statement
  calc
    (a + b * u) * u + (-b) * (u ^ 2 - 3 * v ^ 2)
      = a * u + b * (3 * v ^ 2) := by ring
    _ = 1 := hab

theorem int_sq_mod_four_eq_zero_of_even (x : ℤ) (hx : Even x) : x ^ 2 % 4 = 0 :=
by
  obtain ⟨k, hk⟩ := hx
  have h_eq : x ^ 2 = 4 * k ^ 2 := by
    rw [hk]
    ring
  rw [h_eq]
  omega

theorem odd_of_not_even (x : ℤ) (h : ¬ Even x) : Odd x :=
Int.not_even_iff_odd.mp h

theorem int_sq_mod_four_ne_three (x : ℤ) : x ^ 2 % 4 ≠ 3 :=
by
  by_cases h : Even x
  · have h1 := int_sq_mod_four_eq_zero_of_even x h
    rw [h1]
    omega
  · have h_odd := odd_of_not_even x h
    have h2 := Int.sq_mod_four_eq_one_of_odd h_odd
    rw [h2]
    omega

theorem u2_sub_3v2_pos (u v : ℤ) (F : ℕ)
  (hu_odd : Odd u) (hv_even : Even v)
  (hF : (u ^ 2 - 3 * v ^ 2).natAbs = F ^ 2) :
  u ^ 2 - 3 * v ^ 2 > 0 :=
by
  by_contra h
  push_neg at h
  have h_abs : ((u ^ 2 - 3 * v ^ 2).natAbs : ℤ) = -(u ^ 2 - 3 * v ^ 2) := by omega

  have h2 : (F : ℤ) ^ 2 = 3 * v ^ 2 - u ^ 2 := by
    calc
      (F : ℤ) ^ 2 = ((F ^ 2 : ℕ) : ℤ) := by push_cast; rfl
      _ = ((u ^ 2 - 3 * v ^ 2).natAbs : ℤ) := by rw [← hF]
      _ = -(u ^ 2 - 3 * v ^ 2) := h_abs
      _ = 3 * v ^ 2 - u ^ 2 := by ring

  obtain ⟨a, ha⟩ := hu_odd
  obtain ⟨b, hb⟩ := hv_even

  have h3 : (F : ℤ) ^ 2 = 4 * (3 * b ^ 2 - a ^ 2 - a - 1) + 3 := by
    rw [h2, ha, hb]
    ring

  have h4 : (F : ℤ) ^ 2 % 4 = 3 := by
    rw [h3]
    omega

  have h5 := int_sq_mod_four_ne_three (F : ℤ)
  exact h5 h4

theorem u2_gt_3v2_of_pos (u v : ℤ) (h_pos : u ^ 2 - 3 * v ^ 2 > 0) :
  u ^ 2 > 3 * v ^ 2 :=
by
  linarith

theorem u_eq_three_w (u : ℤ) (h3 : 3 ∣ u) : ∃ w : ℤ, u = 3 * w :=
by
  exact h3

theorem w_odd_of_three_w_odd (w : ℤ) (hu : Odd (3 * w)) : Odd w :=
(Int.odd_mul.mp hu).right

theorem inner_expr_eq (w v : ℤ) :
  3 * w * ((3 * w) ^ 2 - 3 * v ^ 2) = 9 * (w * (3 * w ^ 2 - v ^ 2)) :=
by
  ring

theorem natAbs_expr_eq (w v : ℤ) :
  (3 * w * ((3 * w) ^ 2 - 3 * v ^ 2)).natAbs = 9 * (w * (3 * w ^ 2 - v ^ 2)).natAbs :=
by
  rw [inner_expr_eq w v]
  rw [Int.natAbs_mul]
  rfl

theorem three_dvd_nine_mul (M : ℕ) : 3 ∣ 9 * M :=
⟨3 * M, by ring⟩

theorem three_dvd_sq_of_sq_eq_nine_mul (a M : ℕ) (h : a ^ 2 = 9 * M) : 3 ∣ a ^ 2 :=
by
  rw [h]
  exact three_dvd_nine_mul M

theorem prime_three : Nat.Prime 3 :=
by
  norm_num

theorem three_dvd_of_three_dvd_sq (a : ℕ) (h : 3 ∣ a ^ 2) : 3 ∣ a :=
Nat.Prime.dvd_of_dvd_pow prime_three h

theorem exists_k_of_sq_eq_nine_mul (a M : ℕ) (h : a ^ 2 = 9 * M) : ∃ k : ℕ, a = 3 * k :=
by
  have h1 : 3 ∣ a ^ 2 := three_dvd_sq_of_sq_eq_nine_mul a M h
  have h2 : 3 ∣ a := three_dvd_of_three_dvd_sq a h1
  -- By the definition of divisibility in Lean (a ∣ b ↔ ∃ c, b = a * c),
  -- the hypothesis `h2 : 3 ∣ a` is definitionally equivalent to `∃ k : ℕ, a = 3 * k`.
  exact h2

theorem sq_eq_of_three_mul_sq_eq_nine_mul (k M : ℕ) (h : (3 * k) ^ 2 = 9 * M) : k ^ 2 = M :=
by
  have h1 : (3 * k) ^ 2 = 9 * k ^ 2 := by ring
  rw [h1] at h
  omega

theorem exists_sq_of_sq_eq_nine_mul (a M : ℕ) (h : a ^ 2 = 9 * M) :
  ∃ k : ℕ, k ^ 2 = M :=
by
  -- Obtain the existential witness directly from our new helper lemma
  have h_exists : ∃ k : ℕ, a = 3 * k := exists_k_of_sq_eq_nine_mul a M h
  rcases h_exists with ⟨k, hk⟩

  -- Use the equality `hk : a = 3 * k` to substitute backwards into the original `h`
  have h_subst : (3 * k) ^ 2 = 9 * M := by
    rw [← hk]
    exact h

  -- Finally, supply `k` as the witness and use the second helper lemma to prove `k ^ 2 = M`
  exact ⟨k, sq_eq_of_three_mul_sq_eq_nine_mul k M h_subst⟩

theorem w_mul_eq_sq_of_a_sq_eq (a : ℕ) (w v : ℤ)
  (ha : a ^ 2 = (3 * w * ((3 * w) ^ 2 - 3 * v ^ 2)).natAbs) :
  ∃ k : ℕ, k ^ 2 = (w * (3 * w ^ 2 - v ^ 2)).natAbs :=
by
  -- Rewrite the hypothesis using the algebraic extraction of 9 from the absolute value
  rw [natAbs_expr_eq w v] at ha
  -- Apply the number-theoretic lemma showing if a² = 9M, then M is a perfect square
  exact exists_sq_of_sq_eq_nine_mul a ((w * (3 * w ^ 2 - v ^ 2)).natAbs) ha

theorem coprime_w_3w2_sub_v2_identity (w v x y : ℤ) :
  (9 * x ^ 2 * w + 6 * x * y * v + 3 * y ^ 2 * w) * w + (-y ^ 2) * (3 * w ^ 2 - v ^ 2) = (x * (3 * w) + y * v) ^ 2 :=
by
  ring

theorem coprime_w_3w2_sub_v2 (w v : ℤ) (hcop : IsCoprime (3 * w) v) :
  IsCoprime w (3 * w ^ 2 - v ^ 2) :=
by
  -- Extract the Bézout coefficients from the assumption
  obtain ⟨x, y, h⟩ := hcop

  -- Provide the new Bézout coefficients as witnesses for the target
  use 9 * x ^ 2 * w + 6 * x * y * v + 3 * y ^ 2 * w, -y ^ 2

  -- Rewrite the expression using our algebraic identity
  rw [coprime_w_3w2_sub_v2_identity w v x y]

  -- Substitute the fact that x * (3 * w) + y * v = 1
  rw [h]

  -- Conclude that 1^2 = 1
  ring

theorem three_w2_sub_v2_mod_four (w v : ℤ) (hw : Odd w) (hv : Even v) (h_pos : 0 ≤ 3 * w ^ 2 - v ^ 2) :
  (3 * w ^ 2 - v ^ 2) % (4 : ℤ) = 3 :=
by
  -- Unpack the definitions of odd and even to get their existential witnesses
  rcases hw with ⟨k, hk⟩
  rcases hv with ⟨m, hm⟩

  -- Substitute w and v and establish the algebraic equivalence via `ring`
  have h_eq : 3 * w ^ 2 - v ^ 2 = 4 * (3 * k ^ 2 + 3 * k - m ^ 2) + 3 := by
    rw [hk, hm]
    ring

  -- Replace the expression in the goal and solve the modulo arithmetic automatically
  rw [h_eq]
  omega

theorem int_eq_of_natAbs_eq_sq (x : ℤ) (F : ℕ) (h_pos : 0 ≤ x) (h : x.natAbs = F ^ 2) : x = (F : ℤ) ^ 2 :=
by
  have h1 : x = (x.natAbs : ℤ) := by omega
  rw [h1, h]
  push_cast
  rfl

theorem three_w2_sub_v2_neg (w v : ℤ) (F : ℕ)
  (hw_odd : Odd w) (hv_even : Even v)
  (hF : (3 * w ^ 2 - v ^ 2).natAbs = F ^ 2) :
  3 * w ^ 2 - v ^ 2 < 0 :=
by
  by_contra h
  -- h : ¬ (3 * w ^ 2 - v ^ 2 < 0) implies it is ≥ 0
  have h_pos : 0 ≤ 3 * w ^ 2 - v ^ 2 := by omega

  -- Since it is ≥ 0, we can drop the natAbs and equate it to F^2 in ℤ
  have h_eq : 3 * w ^ 2 - v ^ 2 = (F : ℤ) ^ 2 := int_eq_of_natAbs_eq_sq _ _ h_pos hF

  -- Apply modulo 4 to both sides of the equation
  have h_mod : (3 * w ^ 2 - v ^ 2) % (4 : ℤ) = ((F : ℤ) ^ 2) % (4 : ℤ) := by rw [h_eq]

  -- We know the LHS is 3 modulo 4 due to the parities of w and v and its non-negativity
  have h_mod2 := three_w2_sub_v2_mod_four w v hw_odd hv_even h_pos
  rw [h_mod2] at h_mod

  -- However, a perfect square can never be 3 modulo 4 (the RHS)
  have h_sq := sq_mod_four_ne_three (F : ℤ)

  -- Substituting the equality leads to the contradiction 3 ≠ 3
  rw [←h_mod] at h_sq
  exact h_sq rfl

theorem neg_eq_sq_of_natAbs_eq_sq (x : ℤ) (F : ℕ)
  (h_neg : x < 0) (hF : x.natAbs = F ^ 2) :
  -x = (F : ℤ) ^ 2 :=
by
  have h : -x = (x.natAbs : ℤ) := by omega
  rw [h, hF]
  push_cast
  rfl

theorem v2_sub_3w2_eq_F2_of_neg (w v : ℤ) (F : ℕ)
  (h_neg : 3 * w ^ 2 - v ^ 2 < 0)
  (hF : (3 * w ^ 2 - v ^ 2).natAbs = F ^ 2) :
  v ^ 2 - 3 * w ^ 2 = (F : ℤ) ^ 2 :=
by
  have h := neg_eq_sq_of_natAbs_eq_sq (3 * w ^ 2 - v ^ 2) F h_neg hF
  calc
    v ^ 2 - 3 * w ^ 2 = -(3 * w ^ 2 - v ^ 2) := by ring
    _ = (F : ℤ) ^ 2 := h

theorem V_pow_four_sub_three_W_pow_four_eq_sq (V W F : ℕ) (v w : ℤ)
  (hV : v ^ 2 = (V : ℤ) ^ 4) (hW : w ^ 2 = (W : ℤ) ^ 4)
  (hF : v ^ 2 - 3 * w ^ 2 = (F : ℤ) ^ 2) :
  (V : ℤ) ^ 4 - 3 * (W : ℤ) ^ 4 = (F : ℤ) ^ 2 :=
by
  rw [← hV, ← hW]
  exact hF

theorem three_dvd_v_of_hypotheses (u v : ℤ) (a b : ℕ) (ha_nz : a ≠ 0) (hb_nz : b ≠ 0)
  (hcoprime : IsCoprime u v) (hu_odd : Odd u) (hv_even : Even v)
  (ha : a ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs)
  (hb : b ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs) : 3 ∣ v :=
by
  by_contra h3_ndvd
  have hcop_v : IsCoprime v (3 * u ^ 2 - v ^ 2) := coprime_v_3u2_sub_v2 u v hcoprime h3_ndvd
  obtain ⟨V, hV⟩ := exists_sq_eq_natAbs_of_coprime_mul_eq_sq_left v (3 * u ^ 2 - v ^ 2) b hcop_v hb
  obtain ⟨C, hC⟩ := exists_sq_eq_natAbs_of_coprime_mul_eq_sq_right v (3 * u ^ 2 - v ^ 2) b hcop_v hb
  have h_neg : 3 * u ^ 2 - v ^ 2 < 0 := three_u2_sub_v2_neg u v C hu_odd hv_even hC
  have hv2_gt : v ^ 2 > 3 * u ^ 2 := v2_gt_3u2_of_neg u v h_neg
  by_cases h3u : 3 ∣ u
  · obtain ⟨w, rfl⟩ := u_eq_three_w u h3u
    have hw_odd : Odd w := w_odd_of_three_w_odd w hu_odd
    obtain ⟨k, hk⟩ := w_mul_eq_sq_of_a_sq_eq a w v ha
    have hcop_w : IsCoprime w (3 * w ^ 2 - v ^ 2) := coprime_w_3w2_sub_v2 w v hcoprime
    obtain ⟨W, hW⟩ := exists_sq_eq_natAbs_of_coprime_mul_eq_sq_left w (3 * w ^ 2 - v ^ 2) k hcop_w hk
    obtain ⟨F, hF⟩ := exists_sq_eq_natAbs_of_coprime_mul_eq_sq_right w (3 * w ^ 2 - v ^ 2) k hcop_w hk
    have h_neg_w : 3 * w ^ 2 - v ^ 2 < 0 := three_w2_sub_v2_neg w v F hw_odd hv_even hF
    have h_eqF : v ^ 2 - 3 * w ^ 2 = (F : ℤ) ^ 2 := v2_sub_3w2_eq_F2_of_neg w v F h_neg_w hF
    have hvV : v ^ 2 = (V : ℤ) ^ 4 := v_sq_eq_V_pow_four v V hV
    have hwW : w ^ 2 = (W : ℤ) ^ 4 := w_sq_eq_W_pow_four w W hW
    have h_eq_four : (V : ℤ) ^ 4 - 3 * (W : ℤ) ^ 4 = (F : ℤ) ^ 2 := V_pow_four_sub_three_W_pow_four_eq_sq V W F v w hvV hwW h_eqF
    have hV_even : Even (V : ℤ) := even_V_of_even_v v V hV hv_even
    have hW_odd : Odd (W : ℤ) := odd_W_of_odd_w w W hW hw_odd
    exact V_pow_four_sub_three_W_pow_four_ne_sq V W F hV_even hW_odd h_eq_four
  · have hcop_u : IsCoprime u (u ^ 2 - 3 * v ^ 2) := coprime_u_u2_sub_3v2 u v hcoprime h3u
    obtain ⟨F, hF⟩ := exists_sq_eq_natAbs_of_coprime_mul_eq_sq_right u (u ^ 2 - 3 * v ^ 2) a hcop_u ha
    have h_pos : u ^ 2 - 3 * v ^ 2 > 0 := u2_sub_3v2_pos u v F hu_odd hv_even hF
    have hu2_gt : u ^ 2 > 3 * v ^ 2 := u2_gt_3v2_of_pos u v h_pos
    exact absurd_of_ineqs u v hv2_gt hu2_gt

theorem isCoprime_u_3_of_3w (u v w : ℤ) (hcoprime : IsCoprime u v) (h3 : v = 3 * w) :
  IsCoprime u 3 :=
by
  rw [h3] at hcoprime
  exact IsCoprime.of_mul_right_left hcoprime

theorem isCoprime_u_w_of_3w (u v w : ℤ) (hcoprime : IsCoprime u v) (h3 : v = 3 * w) :
  IsCoprime u w :=
by
  rw [h3] at hcoprime
  exact (IsCoprime.mul_right_iff.mp hcoprime).right

theorem bezout_identity_for_isCoprime (u w a b : ℤ) :
  (3 * a ^ 2 * w + 2 * a * b * u + b ^ 2 * w) * w + a ^ 2 * (u ^ 2 - 3 * w ^ 2) = (a * u + b * w) ^ 2 :=
by
  ring

theorem isCoprime_w_u2_minus_3w2 (u w : ℤ) (hcoprime : IsCoprime u w) :
  IsCoprime w (u ^ 2 - 3 * w ^ 2) :=
by
  -- Destructure the coprimality assumption to get the Bézout coefficients a and b
  obtain ⟨a, b, h⟩ := hcoprime
  -- Provide the new Bézout coefficients for w and (u ^ 2 - 3 * w ^ 2)
  exact ⟨3 * a ^ 2 * w + 2 * a * b * u + b ^ 2 * w, a ^ 2, by
    -- Rewrite our goal using the algebraic identity
    rw [bezout_identity_for_isCoprime]
    -- Substitute the original Bézout identity (a * u + b * w = 1)
    rw [h]
    -- Conclude that 1^2 = 1
    ring⟩

theorem isCoprime_u_u2_minus_3v2 (u v : ℤ) (hcoprime : IsCoprime u v) (hu3 : IsCoprime u 3) :
  IsCoprime u (u ^ 2 - 3 * v ^ 2) :=
by
  -- Extract Bézout coefficients from our hypotheses
  obtain ⟨x, y, hxy⟩ := hcoprime
  obtain ⟨a, b, hab⟩ := hu3

  -- Use our constructively found Bézout coefficients for u and u^2 - 3v^2
  use a * (x * u + y * v) ^ 2 + 3 * b * x ^ 2 * u + 6 * b * x * y * v + b * y ^ 2 * u, -b * y ^ 2

  -- State the algebraic factorization identity that relates the new coefficients back to the old ones
  have h_eq : (a * (x * u + y * v) ^ 2 + 3 * b * x ^ 2 * u + 6 * b * x * y * v + b * y ^ 2 * u) * u +
              (-b * y ^ 2) * (u ^ 2 - 3 * v ^ 2) = (a * u + b * 3) * (x * u + y * v) ^ 2 := by ring

  -- Rewrite the goal using the algebraic identity, then apply the extracted Bézout identities
  rw [h_eq, hxy, hab]

  -- Finally, show that 1 * 1 ^ 2 = 1
  ring

theorem nat_coprime_of_isCoprime (x y : ℤ) (h : IsCoprime x y) :
  Nat.Coprime x.natAbs y.natAbs :=
Int.isCoprime_iff_nat_coprime.mp h

theorem inner_poly_eq (u v w : ℤ) (h3 : v = 3 * w) :
  v * (3 * u ^ 2 - v ^ 2) = (9 : ℤ) * (w * (u ^ 2 - 3 * w ^ 2)) :=
by
  rw [h3]
  ring

theorem natAbs_nine_mul (x : ℤ) :
  ((9 : ℤ) * x).natAbs = (9 : ℕ) * x.natAbs :=
by
  exact Int.natAbs_mul 9 x

theorem v_eq_3w_impl_b_sq_eq (u v w : ℤ) (b : ℕ) (h3 : v = 3 * w)
  (hb : b ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs) :
  b ^ 2 = (9 : ℕ) * (w * (u ^ 2 - 3 * w ^ 2)).natAbs :=
by
  rw [hb]
  rw [inner_poly_eq u v w h3]
  rw [natAbs_nine_mul]

theorem three_dvd_b_of_b_sq_eq_nine_mul (M b : ℕ) (h : b ^ 2 = (9 : ℕ) * M) : 3 ∣ b :=
Nat.Prime.dvd_of_dvd_pow Nat.prime_three (three_dvd_sq_of_sq_eq_nine_mul b M h)

theorem M_eq_d_sq_of_b_eq_3d (M b d : ℕ) (h : b ^ 2 = (9 : ℕ) * M) (hd : b = 3 * d) : M = d ^ 2 :=
by
  rw [hd] at h
  have h1 : (3 * d) ^ 2 = (9 : ℕ) * d ^ 2 := by ring
  rw [h1] at h
  omega

theorem nat_sq_of_nine_mul (M b : ℕ) (h : b ^ 2 = (9 : ℕ) * M) :
  ∃ d : ℕ, M = d ^ 2 :=
by
  have ⟨d, hd⟩ := three_dvd_b_of_b_sq_eq_nine_mul M b h
  exact ⟨d, M_eq_d_sq_of_b_eq_3d M b d h hd⟩

theorem int_gcd_eq_one_of_nat_coprime (x y : ℕ) (h : x.Coprime y) : (x : ℤ).gcd (y : ℤ) = 1 :=
h

theorem int_mul_eq_sq_of_nat_mul_eq_sq (x y z : ℕ) (h : x * y = z ^ 2) : (x : ℤ) * (y : ℤ) = (z : ℤ) ^ 2 :=
by
  exact_mod_cast h

theorem int_mul_eq_sq_of_nat_mul_eq_sq_symm (x y z : ℕ) (h : x * y = z ^ 2) : (y : ℤ) * (x : ℤ) = (z : ℤ) ^ 2 :=
by
  have h_comm : y * x = z ^ 2 := by
    rw [mul_comm y x]
    exact h
  exact_mod_cast h_comm

theorem nat_eq_sq_of_int_eq_sq (x : ℕ) (a : ℤ) (h : (x : ℤ) = a ^ 2) : x = a.natAbs ^ 2 :=
by
  have h1 : (x : ℤ) = (a.natAbs : ℤ) ^ 2 := by
    rw [h, ← Int.natAbs_sq a]
  exact_mod_cast h1

theorem nat_zero_of_int_eq_neg_sq (x : ℕ) (a : ℤ) (h : (x : ℤ) = - a ^ 2) : x = 0 :=
by
  have h1 : 0 ≤ a ^ 2 := sq_nonneg a
  omega

theorem nat_eq_sq_of_int_eq_sq_or_neg_sq (x : ℕ) (a : ℤ) (h : (x : ℤ) = a ^ 2 ∨ (x : ℤ) = - a ^ 2) : ∃ a0 : ℕ, x = a0 ^ 2 :=
by
  cases h with
  | inl h1 =>
    exact ⟨a.natAbs, nat_eq_sq_of_int_eq_sq x a h1⟩
  | inr h2 =>
    have hx : x = 0 := nat_zero_of_int_eq_neg_sq x a h2
    exact ⟨0, by rw [hx]; rfl⟩

theorem nat_coprime_symm (x y : ℕ) (h : x.Coprime y) : y.Coprime x :=
h.symm

theorem nat_coprime_mul_eq_sq (x y z : ℕ) (h : x.Coprime y) (hsq : x * y = z ^ 2) :
  ∃ a b : ℕ, x = a ^ 2 ∧ y = b ^ 2 :=
by
  have hx : (x : ℤ).gcd (y : ℤ) = 1 := int_gcd_eq_one_of_nat_coprime x y h
  have hsq_int : (x : ℤ) * (y : ℤ) = (z : ℤ) ^ 2 := int_mul_eq_sq_of_nat_mul_eq_sq x y z hsq
  have ha_or := Int.sq_of_gcd_eq_one hx hsq_int
  obtain ⟨a_int, ha_or_eq⟩ := ha_or
  have ⟨a, ha⟩ := nat_eq_sq_of_int_eq_sq_or_neg_sq x a_int ha_or_eq

  have hy : (y : ℤ).gcd (x : ℤ) = 1 := int_gcd_eq_one_of_nat_coprime y x (nat_coprime_symm x y h)
  have hsq_symm_int : (y : ℤ) * (x : ℤ) = (z : ℤ) ^ 2 := int_mul_eq_sq_of_nat_mul_eq_sq_symm x y z hsq
  have hb_or := Int.sq_of_gcd_eq_one hy hsq_symm_int
  obtain ⟨b_int, hb_or_eq⟩ := hb_or
  have ⟨b, hb⟩ := nat_eq_sq_of_int_eq_sq_or_neg_sq y b_int hb_or_eq

  exact ⟨a, b, ha, hb⟩

theorem abs_eq_sq_imp_sq_eq_pow_four (u : ℤ) (x : ℕ) (h : u.natAbs = x ^ 2) :
  u ^ 2 = (x : ℤ) ^ 4 :=
by
  -- Substitute u ^ 2 with its casted absolute value squared.
  rw [← Int.natAbs_sq u]

  -- Rewrite using our hypothesis h
  rw [h]

  -- Push the integer casting operations inwards: ((x ^ 2 : ℕ) : ℤ) becomes (x : ℤ) ^ 2
  push_cast

  -- Resolve the final standard polynomial equivalence ((x : ℤ) ^ 2) ^ 2 = (x : ℤ) ^ 4
  ring

theorem int_eq_or_eq_neg_of_natAbs_eq_nat (x : ℤ) (n : ℕ) (h : x.natAbs = n) :
  x = (n : ℤ) ∨ x = -(n : ℤ) :=
by
  omega

theorem eq_or_eq_neg_of_natAbs_eq (x : ℤ) (s : ℕ) (h : x.natAbs = s ^ 2) :
  x = (s : ℤ) ^ 2 ∨ x = - (s : ℤ) ^ 2 :=
by
  -- Apply our helper lemma treating s^2 purely as a natural number n
  have h1 : x = ((s ^ 2 : ℕ) : ℤ) ∨ x = -((s ^ 2 : ℕ) : ℤ) :=
    int_eq_or_eq_neg_of_natAbs_eq_nat x (s ^ 2) h

  -- Branch on whether x was positive or negative
  rcases h1 with h_eq | h_eq
  · left
    rw [h_eq]
    -- Push the integer cast inward through the exponentiation
    push_cast
    rfl
  · right
    rw [h_eq]
    push_cast
    rfl

theorem u_sq_minus_3_w_sq_eq (X C S u w : ℤ)
  (hu : u ^ 2 = X ^ 4) (hw : w ^ 2 = C ^ 4)
  (h_or : u ^ 2 - 3 * w ^ 2 = S ^ 2 ∨ u ^ 2 - 3 * w ^ 2 = - S ^ 2) :
  X ^ 4 - 3 * C ^ 4 = S ^ 2 ∨ X ^ 4 - 3 * C ^ 4 = - S ^ 2 :=
by
  rw [← hu, ← hw]
  exact h_or

theorem w_even_of_v_even (v w : ℤ) (h3 : v = 3 * w) (hv : Even v) :
  Even w :=
by
  rcases hv with ⟨k, hk⟩
  exact ⟨k - w, by linarith⟩

theorem odd_of_sq_eq_pow_four (u X : ℤ) (hu : u ^ 2 = X ^ 4) (h_odd : Odd u) :
  Odd X :=
by
  have h2 : (2 : ℕ) ≠ 0 := by decide
  have h4 : (4 : ℕ) ≠ 0 := by decide
  have H1 : Odd (u ^ 2) := (Int.odd_pow' h2).mpr h_odd
  have H2 : Odd (X ^ 4) := by
    rw [← hu]
    exact H1
  exact (Int.odd_pow' h4).mp H2

theorem even_of_sq_eq_pow_four (w C : ℤ) (hw : w ^ 2 = C ^ 4) (h_even : Even w) :
  Even C :=
by
  -- 1. Deduce that w^2 is even since w is even
  have hw2 : Even (w ^ 2) := Even.pow_of_ne_zero h_even (by decide)

  -- 2. Substitute w^2 with C^4 using the given hypothesis
  have hC4 : Even (C ^ 4) := by
    rw [← hw]
    exact hw2

  -- 3. Since C^4 is even, deduce that C is even
  exact (Int.even_pow.mp hC4).left

theorem odd_pow_four_eq_four_mul_add_one (X : ℤ) (hX : Odd X) :
  ∃ Q : ℤ, X ^ 4 = (4 : ℤ) * Q + 1 :=
by
  rcases hX with ⟨k, hk⟩
  exact ⟨4 * k^4 + 8 * k^3 + 6 * k^2 + 2 * k, by rw [hk]; ring⟩

theorem even_pow_four_eq_sixteen_mul (C : ℤ) (hC : Even C) :
  ∃ Q : ℤ, C ^ 4 = (16 : ℤ) * Q :=
by
  rcases hC with ⟨k, hk⟩
  use k ^ 4
  rw [hk]
  ring

theorem sq_even_form (k : ℤ) :
  ∃ Q : ℤ, ((2 : ℤ) * k) ^ 2 = (4 : ℤ) * Q ∨ ((2 : ℤ) * k) ^ 2 = (4 : ℤ) * Q + 1 :=
by
  use k ^ 2
  left
  ring

theorem sq_odd_form (k : ℤ) :
  ∃ Q : ℤ, ((2 : ℤ) * k + 1) ^ 2 = (4 : ℤ) * Q ∨ ((2 : ℤ) * k + 1) ^ 2 = (4 : ℤ) * Q + 1 :=
by
  use k ^ 2 + k
  right
  ring

theorem sq_eq_four_mul_add_rem (S : ℤ) :
  ∃ Q : ℤ, S ^ 2 = (4 : ℤ) * Q ∨ S ^ 2 = (4 : ℤ) * Q + 1 :=
by
  have h : S % (2 : ℤ) = 0 ∨ S % (2 : ℤ) = 1 := by omega
  rcases h with h0 | h1
  · have hS : S = (2 : ℤ) * (S / (2 : ℤ)) := by omega
    rw [hS]
    exact sq_even_form (S / (2 : ℤ))
  · have hS : S = (2 : ℤ) * (S / (2 : ℤ)) + 1 := by omega
    rw [hS]
    exact sq_odd_form (S / (2 : ℤ))

theorem no_sol_minus_S_sq (X C S : ℤ) (hX : Odd X) (hC : Even C)
  (h : X ^ 4 - 3 * C ^ 4 = - S ^ 2) : False :=
by
  obtain ⟨QX, hQX⟩ := odd_pow_four_eq_four_mul_add_one X hX
  obtain ⟨QC, hQC⟩ := even_pow_four_eq_sixteen_mul C hC
  obtain ⟨QS, hQS⟩ := sq_eq_four_mul_add_rem S
  rcases hQS with hQS | hQS
  · rw [hQX, hQC, hQS] at h
    omega
  · rw [hQX, hQC, hQS] at h
    omega

theorem w_zero_of_C_zero (w C : ℤ) (hw : w ^ 2 = C ^ 4) (hC : C = 0) : w = 0 :=
by
  subst hC
  have h1 : w ^ 2 = 0 := by
    rw [hw]
    norm_num
  exact pow_eq_zero h1

theorem b_zero_of_w_zero (u w : ℤ) (b : ℕ) (hb : b ^ 2 = (9 : ℕ) * (w * (u ^ 2 - 3 * w ^ 2)).natAbs) (hw_zero : w = 0) : b = 0 :=
by
  -- Substitute w = 0 everywhere in the hypotheses and goal
  subst hw_zero

  -- Show that b ^ 2 evaluates to 0
  have h1 : b ^ 2 = 0 := by
    rw [hb]
    simp

  -- Conclude b = 0 from b ^ 2 = 0.
  -- We include both a direct standard Mathlib lemma application and nlinarith as fallback.
  try exact sq_eq_zero_iff.mp h1
  try nlinarith

theorem C_ne_zero_of_b_ne_zero (u w C : ℤ) (b : ℕ) (hb_nz : b ≠ 0)
  (hb : b ^ 2 = (9 : ℕ) * (w * (u ^ 2 - 3 * w ^ 2)).natAbs) (hw : w ^ 2 = C ^ 4) : C ≠ 0 :=
by
  intro hC
  have hw0 : w = 0 := w_zero_of_C_zero w C hw hC
  have hb0 : b = 0 := b_zero_of_w_zero u w b hb hw0
  exact hb_nz hb0

theorem ha_eq_mul (a : ℕ) (u v : ℤ) (ha : a ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs) :
  u.natAbs * (u ^ 2 - 3 * v ^ 2).natAbs = a ^ 2 :=
by
  rw [ha, Int.natAbs_mul]

theorem hd_eq_mul (d : ℕ) (u w : ℤ) (hd : (w * (u ^ 2 - 3 * w ^ 2)).natAbs = d ^ 2) :
  w.natAbs * (u ^ 2 - 3 * w ^ 2).natAbs = d ^ 2 :=
by
  rw [← Int.natAbs_mul]
  exact hd

theorem structure_of_3_dvd_v (u v : ℤ) (a b : ℕ) (hb_nz : b ≠ 0)
  (hcoprime : IsCoprime u v) (hu_odd : Odd u) (hv_even : Even v) (w : ℤ)
  (h3 : v = 3 * w)
  (ha : a ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs)
  (hb : b ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs) :
  ∃ X C S : ℤ, u ^ 2 = X ^ 4 ∧ Odd X ∧ w ^ 2 = C ^ 4 ∧ Even C ∧ X ^ 4 - 3 * C ^ 4 = S ^ 2 ∧ C ≠ 0 :=
by
  -- Relational coprimality implications based on v = 3w and gcd(u, v) = 1
  have hcop_u_3 : IsCoprime u 3 := isCoprime_u_3_of_3w u v w hcoprime h3
  have hcop_u_w : IsCoprime u w := isCoprime_u_w_of_3w u v w hcoprime h3

  have hcop_w_expr : IsCoprime w (u ^ 2 - 3 * w ^ 2) := isCoprime_w_u2_minus_3w2 u w hcop_u_w
  have hcop_w_expr_nat : Nat.Coprime w.natAbs (u ^ 2 - 3 * w ^ 2).natAbs := nat_coprime_of_isCoprime _ _ hcop_w_expr

  have hcop_u_expr : IsCoprime u (u ^ 2 - 3 * v ^ 2) := isCoprime_u_u2_minus_3v2 u v hcoprime hcop_u_3
  have hcop_u_expr_nat : Nat.Coprime u.natAbs (u ^ 2 - 3 * v ^ 2).natAbs := nat_coprime_of_isCoprime _ _ hcop_u_expr

  -- Structural breakdown for target equation from 'a'
  have ha' : u.natAbs * (u ^ 2 - 3 * v ^ 2).natAbs = a ^ 2 := ha_eq_mul a u v ha

  -- Structural breakdown for target equation from 'b'
  have hb' : b ^ 2 = (9 : ℕ) * (w * (u ^ 2 - 3 * w ^ 2)).natAbs := v_eq_3w_impl_b_sq_eq u v w b h3 hb
  have h_d : ∃ d : ℕ, (w * (u ^ 2 - 3 * w ^ 2)).natAbs = d ^ 2 := nat_sq_of_nine_mul _ _ hb'
  rcases h_d with ⟨d, hd⟩

  have hd' : w.natAbs * (u ^ 2 - 3 * w ^ 2).natAbs = d ^ 2 := hd_eq_mul d u w hd

  -- Existence deductions
  have h_u_sq : ∃ x y : ℕ, u.natAbs = x ^ 2 ∧ (u ^ 2 - 3 * v ^ 2).natAbs = y ^ 2 :=
    nat_coprime_mul_eq_sq _ _ _ hcop_u_expr_nat ha'
  rcases h_u_sq with ⟨x, y, hux, huy⟩

  have h_w_sq : ∃ c s : ℕ, w.natAbs = c ^ 2 ∧ (u ^ 2 - 3 * w ^ 2).natAbs = s ^ 2 :=
    nat_coprime_mul_eq_sq _ _ _ hcop_w_expr_nat hd'
  rcases h_w_sq with ⟨c, s, hwc, hws⟩

  -- Binding parameters X, C, S based on extracted natural multipliers
  let X : ℤ := (x : ℤ)
  let C : ℤ := (c : ℤ)
  let S : ℤ := (s : ℤ)

  have hu_pow : u ^ 2 = X ^ 4 := abs_eq_sq_imp_sq_eq_pow_four u x hux
  have hw_pow : w ^ 2 = C ^ 4 := abs_eq_sq_imp_sq_eq_pow_four w c hwc

  have h_or_s : u ^ 2 - 3 * w ^ 2 = S ^ 2 ∨ u ^ 2 - 3 * w ^ 2 = - S ^ 2 :=
    eq_or_eq_neg_of_natAbs_eq (u ^ 2 - 3 * w ^ 2) s hws

  have h_XCS : X ^ 4 - 3 * C ^ 4 = S ^ 2 ∨ X ^ 4 - 3 * C ^ 4 = - S ^ 2 :=
    u_sq_minus_3_w_sq_eq X C S u w hu_pow hw_pow h_or_s

  -- Parity analysis bounds
  have h_odd_X : Odd X := odd_of_sq_eq_pow_four u X hu_pow hu_odd
  have hw_even : Even w := w_even_of_v_even v w h3 hv_even
  have h_even_C : Even C := even_of_sq_eq_pow_four w C hw_pow hw_even

  -- Resolving Disjunction & proving non-zero characteristic
  have h_eq : X ^ 4 - 3 * C ^ 4 = S ^ 2 := by
    rcases h_XCS with h1 | h2
    · exact h1
    · exfalso
      exact no_sol_minus_S_sq X C S h_odd_X h_even_C h2

  have h_C_ne_zero : C ≠ 0 := C_ne_zero_of_b_ne_zero u w C b hb_nz hb' hw_pow

  -- Providing exact matching conjunction parameters
  exact ⟨X, C, S, hu_pow, h_odd_X, hw_pow, h_even_C, h_eq, h_C_ne_zero⟩

theorem extract_even_k (C : ℤ) (h : Even C) : ∃ k : ℤ, C = 2 * k :=
by
  obtain ⟨k, hk⟩ := h
  use k
  omega

theorem k_ne_zero_of_two_mul_ne_zero {C k : ℤ} (hk : C = 2 * k) (hC : C ≠ 0) : k ≠ 0 :=
by
  omega

theorem natAbs_pos_of_ne_zero {k : ℤ} (hk : k ≠ 0) : 0 < k.natAbs :=
by
  omega

theorem natAbs_pow_four_eq (k : ℤ) : (k.natAbs : ℤ) ^ 4 = k ^ 4 :=
by
  cases k with
  | ofNat n =>
    -- Case 1: k ≥ 0. The natural absolute value of n is n.
    -- (n : ℤ) ^ 4 = (n : ℤ) ^ 4 trivially holds.
    rfl
  | negSucc n =>
    -- Case 2: k < 0, meaning k = -(n + 1) for some natural number n.
    -- The absolute value is strictly (n + 1 : ℕ).
    have h2 : (Int.natAbs (Int.negSucc n) : ℤ) = ((n + 1 : ℕ) : ℤ) := rfl
    rw [h2]

    -- Int.negSucc n is definitionally strictly equal to -((n + 1 : ℕ) : ℤ).
    have h1 : Int.negSucc n = -((n + 1 : ℕ) : ℤ) := rfl
    rw [h1]

    -- Now the equation purely reduces to X^4 = (-X)^4, which is a simple ring identity.
    ring

theorem substitute_eq_lem (X C S k : ℤ) (Y : ℕ) (heq : X ^ 4 - 3 * C ^ 4 = S ^ 2)
  (hk : C = 2 * k) (hY : (Y : ℤ) ^ 4 = k ^ 4) : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2 :=
by
  calc
    X ^ 4 - 48 * (Y : ℤ) ^ 4 = X ^ 4 - 48 * k ^ 4 := by rw [hY]
    _ = X ^ 4 - 3 * (2 * k) ^ 4 := by ring
    _ = X ^ 4 - 3 * C ^ 4 := by rw [← hk]
    _ = S ^ 2 := heq

theorem reduction_to_descent (u v : ℤ) (a b : ℕ) (ha_nz : a ≠ 0) (hb_nz : b ≠ 0)
  (hcoprime : IsCoprime u v) (hu_odd : Odd u) (hv_even : Even v)
  (ha : a ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs)
  (hb : b ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs) :
  ∃ (X S : ℤ) (Y : ℕ), 0 < Y ∧ Odd X ∧ X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2 :=
by
  -- 1. Deduce that 3 divides v
  have h3 : 3 ∣ v := three_dvd_v_of_hypotheses u v a b ha_nz hb_nz hcoprime hu_odd hv_even ha hb
  obtain ⟨w, hw⟩ := h3

  -- 2. Obtain structural identities of descent
  have h_struct := structure_of_3_dvd_v u v a b hb_nz hcoprime hu_odd hv_even w hw ha hb
  obtain ⟨X, C, S, _, hX_odd, _, hC_even, heq, hC_nz⟩ := h_struct

  -- 3. C is even, extract k out of it
  obtain ⟨k, hk⟩ := extract_even_k C hC_even
  have hk_nz : k ≠ 0 := k_ne_zero_of_two_mul_ne_zero hk hC_nz

  -- 4. Construct Y
  let Y := k.natAbs
  have hY_pos : 0 < Y := natAbs_pos_of_ne_zero hk_nz
  have hkY : (Y : ℤ) ^ 4 = k ^ 4 := natAbs_pow_four_eq k

  -- 5. Final substitution proving equivalence to descent representation
  have heq2 : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2 := substitute_eq_lem X C S k Y heq hk hkY

  exact ⟨X, S, Y, hY_pos, hX_odd, heq2⟩

theorem extract_prime_factors (X : ℤ) (Y : ℕ) (hg : 1 < X.natAbs.gcd Y) :
  ∃ p : ℕ, ∃ X' : ℤ, ∃ Y' : ℕ, p.Prime ∧ 2 ≤ p ∧ X = (p : ℤ) * X' ∧ Y = p * Y' :=
by
  -- Since the GCD is strictly greater than 1, it is notably not equal to 1.
  have hne : X.natAbs.gcd Y ≠ 1 := ne_of_gt hg

  -- Extract a prime factor `p` that divides the GCD.
  obtain ⟨p, hp_prime, hp_dvd_gcd⟩ := Nat.exists_prime_and_dvd hne

  -- By GCD properties, `p` must divide both `X.natAbs` and `Y`.
  have hp_dvd_X : p ∣ X.natAbs := hp_dvd_gcd.trans (Nat.gcd_dvd_left X.natAbs Y)
  have hp_dvd_Y : p ∣ Y := hp_dvd_gcd.trans (Nat.gcd_dvd_right X.natAbs Y)

  -- Lift the divisibility relation for X to the integers.
  have hp_dvd_X_int : (p : ℤ) ∣ X := Int.natCast_dvd.mpr hp_dvd_X

  -- Divisibility yields the integer multipliers cleanly.
  obtain ⟨X', hX'⟩ := hp_dvd_X_int
  obtain ⟨Y', hY'⟩ := hp_dvd_Y

  -- Assemble the proofs and existentials exactly as structurally required.
  exact ⟨p, X', Y', hp_prime, Nat.Prime.two_le hp_prime, hX', hY'⟩

theorem y_prime_pos (Y Y' p : ℕ) (hY : Y = p * Y') (hpos : 0 < Y) : 0 < Y' :=
by
  cases Y' with
  | zero =>
    -- If Y' = 0, then Y = p * 0 = 0
    rw [Nat.mul_zero] at hY
    -- This contradicts 0 < Y, which omega can easily see
    omega
  | succ y =>
    -- If Y' = y + 1, then 0 < y + 1 is trivially true
    omega

theorem y_prime_lt_y (Y Y' p : ℕ) (hY : Y = p * Y') (hp : 2 ≤ p) (hposY' : 0 < Y') : Y' < Y :=
by
  rw [hY]
  have h1 : 2 * Y' ≤ p * Y' := Nat.mul_le_mul_right Y' hp
  omega

theorem y_lt_y_of_mul (Y Y' p : ℕ) (hY : Y = p * Y') (hp : 2 ≤ p) (hpos : 0 < Y) :
  Y' < Y ∧ 0 < Y' :=
by
  have hposY' : 0 < Y' := y_prime_pos Y Y' p hY hpos
  have hlt : Y' < Y := y_prime_lt_y Y Y' p hY hp hposY'
  exact ⟨hlt, hposY'⟩

theorem odd_X_prime (X : ℤ) (p : ℕ) (X' : ℤ) (hX : Odd X) (hX_eq : X = (p : ℤ) * X') : Odd X' :=
by
  rw [hX_eq] at hX
  exact Int.Odd.of_mul_right hX

theorem substitute_eq_nat (X S : ℤ) (Y : ℕ) (p : ℕ) (X' : ℤ) (Y' : ℕ)
  (hX : X = (p : ℤ) * X') (hY : Y = p * Y') (h : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2) :
  ((p : ℤ) * X') ^ 4 - 48 * ((p : ℤ) * (Y' : ℤ)) ^ 4 = S ^ 2 :=
by
  -- Substitute back `(p : ℤ) * X'` with `X` using the reversed hX
  rw [← hX]
  -- State a helper equality relating the integer casts of Y, p, and Y'
  have hY_cast : (p : ℤ) * (Y' : ℤ) = (Y : ℤ) := by
    rw [hY]
    push_cast
    rfl
  -- Substitute back `(p : ℤ) * (Y' : ℤ)` with `(Y : ℤ)` using our helper
  rw [hY_cast]
  -- The target now exactly matches hypothesis `h`
  exact h

theorem factor_p_pow_four (p : ℕ) (X' Y' : ℤ) :
  ((p : ℤ) * X') ^ 4 - 48 * ((p : ℤ) * Y') ^ 4 = (p : ℤ) ^ 4 * (X' ^ 4 - 48 * Y' ^ 4) :=
by
  ring

theorem natAbs_mul_pow_four (p : ℕ) (Z : ℤ) :
  ((p : ℤ) ^ 4 * Z).natAbs = p ^ 4 * Z.natAbs :=
by
  rw [Int.natAbs_mul, Int.natAbs_pow]
  rfl

theorem natAbs_sq (S : ℤ) :
  (S ^ 2).natAbs = S.natAbs ^ 2 :=
by
  exact Int.natAbs_pow S 2

theorem to_nat_eq (p : ℕ) (X' Y' S : ℤ)
  (h : ((p : ℤ) * X') ^ 4 - 48 * ((p : ℤ) * Y') ^ 4 = S ^ 2) :
  p ^ 4 * (X' ^ 4 - 48 * Y' ^ 4).natAbs = S.natAbs ^ 2 :=
by
  have h1 := factor_p_pow_four p X' Y'
  rw [h1] at h
  have h2 := congrArg Int.natAbs h
  rw [natAbs_mul_pow_four, natAbs_sq] at h2
  exact h2

theorem nat_prime_dvd_sq (p s : ℕ) (hp : p.Prime) (h : p ∣ s ^ 2) : p ∣ s :=
by
  have h_mul : p ∣ s * s := by
    rw [← sq]
    exact h
  cases hp.dvd_mul.mp h_mul with
  | inl h_left => exact h_left
  | inr h_right => exact h_right

theorem prime_sq_pos (p : ℕ) (hp : p.Prime) : 0 < p ^ 2 :=
by
  have h2 : 2 ≤ p := (Nat.prime_iff_not_exists_mul_eq.mp hp).1
  have hpos : 0 < p := by omega
  exact pow_pos hpos 2

theorem pow_four_eq_sq_mul_sq (p k : ℕ) : p ^ 4 * k = p ^ 2 * (p ^ 2 * k) :=
by
  ring

theorem mul_pow_two (p s1 : ℕ) : (p * s1) ^ 2 = p ^ 2 * s1 ^ 2 :=
mul_pow p s1 2

theorem cancel_left (c n m : ℕ) (hc : 0 < c) (h : c * n = c * m) : n = m :=
Nat.eq_of_mul_eq_mul_left hc h

theorem sq_eq_of_pow_four (p s1 k : ℕ) (hp : p.Prime) (h : p ^ 4 * k = (p * s1) ^ 2) : p ^ 2 * k = s1 ^ 2 :=
by
  have h1 : 0 < p ^ 2 := prime_sq_pos p hp
  have h2 : p ^ 4 * k = p ^ 2 * (p ^ 2 * k) := pow_four_eq_sq_mul_sq p k
  have h3 : (p * s1) ^ 2 = p ^ 2 * s1 ^ 2 := mul_pow_two p s1
  have h4 : p ^ 2 * (p ^ 2 * k) = p ^ 2 * s1 ^ 2 := by
    rw [← h2]
    rw [h]
    rw [h3]
  exact cancel_left (p ^ 2) (p ^ 2 * k) (s1 ^ 2) h1 h4

theorem nat_sq_dvd_of_pow_four_dvd (p s k : ℕ) (hp : p.Prime) (h : p ^ 4 * k = s ^ 2) :
  p ^ 2 ∣ s :=
by
  -- Step 1: Deduce that p ∣ s^2
  have h1 : p ∣ s ^ 2 := by
    use p ^ 3 * k
    calc s ^ 2 = p ^ 4 * k := h.symm
      _ = p * (p ^ 3 * k) := by ring

  -- Step 2: Since p is prime, p ∣ s^2 implies p ∣ s
  have h2 : p ∣ s := nat_prime_dvd_sq p s hp h1
  obtain ⟨s1, hs1⟩ := h2

  -- Step 3: Substitute s = p * s1 into the original equation
  have h3 : p ^ 4 * k = (p * s1) ^ 2 := by
    calc p ^ 4 * k = s ^ 2 := h
      _ = (p * s1) ^ 2 := by rw [hs1]

  -- Step 4: Cancel out p^2 from both sides
  have h4 : p ^ 2 * k = s1 ^ 2 := sq_eq_of_pow_four p s1 k hp h3

  -- Step 5: Deduce that p ∣ s1^2
  have h5 : p ∣ s1 ^ 2 := by
    use p * k
    calc s1 ^ 2 = p ^ 2 * k := h4.symm
      _ = p * (p * k) := by ring

  -- Step 6: Since p is prime, p ∣ s1^2 implies p ∣ s1
  have h6 : p ∣ s1 := nat_prime_dvd_sq p s1 hp h5
  obtain ⟨s2, hs2⟩ := h6

  -- Step 7: Substitute back to show p^2 ∣ s
  use s2
  calc s = p * s1 := hs1
    _ = p * (p * s2) := by rw [hs2]
    _ = p ^ 2 * s2 := by ring

theorem int_dvd_of_nat_dvd (p : ℕ) (S : ℤ) (h : p ^ 2 ∣ S.natAbs) :
  (p : ℤ) ^ 2 ∣ S :=
by
  have h2 : (p ^ 2 : ℤ) ∣ S := Int.natCast_dvd.mpr h
  push_cast at h2
  exact h2

theorem sq_dvd_of_eq_pow_four (p : ℕ) (hp : p.Prime) (X' Y' S : ℤ)
  (h : ((p : ℤ) * X') ^ 4 - 48 * ((p : ℤ) * Y') ^ 4 = S ^ 2) :
  (p : ℤ) ^ 2 ∣ S :=
by
  have h_nat := to_nat_eq p X' Y' S h
  have h_dvd := nat_sq_dvd_of_pow_four_dvd p S.natAbs (X' ^ 4 - 48 * Y' ^ 4).natAbs hp h_nat
  exact int_dvd_of_nat_dvd p S h_dvd

theorem p_neq_zero (p : ℕ) (hp : 2 ≤ p) :
  (p : ℤ) ≠ 0 :=
by
  omega

theorem reduce_equation_step (p X' Y' S' : ℤ) (hp : p ≠ 0)
  (h : (p * X') ^ 4 - 48 * (p * Y') ^ 4 = (p ^ 2 * S') ^ 2) :
  X' ^ 4 - 48 * Y' ^ 4 = S' ^ 2 :=
by
  -- 1. Factor out p^4 on the left-hand side
  have h1 : (p * X') ^ 4 - 48 * (p * Y') ^ 4 = p ^ 4 * (X' ^ 4 - 48 * Y' ^ 4) := by ring

  -- 2. Factor out p^4 on the right-hand side
  have h2 : (p ^ 2 * S') ^ 2 = p ^ 4 * S' ^ 2 := by ring

  -- 3. Rewrite the hypothesis `h` using the factorizations
  rw [h1, h2] at h

  -- 4. Prove that p^4 ≠ 0 because p ≠ 0
  have hp4 : p ^ 4 ≠ 0 := pow_ne_zero 4 hp

  -- 5. Cancel out the non-zero common factor p^4 from both sides
  exact mul_left_cancel₀ hp4 h

theorem reduce_to_coprime (Y : ℕ)
  (ih : ∀ (y : ℕ), y < Y → ∀ (X S : ℤ), 0 < y → Odd X → X ^ 4 - 48 * (y : ℤ) ^ 4 = S ^ 2 → False)
  (X S : ℤ) (hY : 0 < Y) (hX : Odd X) (h : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2)
  (hg : 1 < X.natAbs.gcd Y) : False :=
by
  -- Extract prime factor `p` strictly greater than 1 dividing both `X` and `Y`
  obtain ⟨p, X', Y', hp_prime, hp_le, hX_eq, hY_eq⟩ := extract_prime_factors X Y hg

  -- Show that `Y'` satisfies infinite descent bounds and strict positivity
  have hY'_bounds : Y' < Y ∧ 0 < Y' := y_lt_y_of_mul Y Y' p hY_eq hp_le hY
  have hY'_lt : Y' < Y := hY'_bounds.1
  have hY'_pos : 0 < Y' := hY'_bounds.2

  -- Verify that extracted inner witness `X'` preserves Odd parity
  have hX'_odd : Odd X' := odd_X_prime X p X' hX hX_eq

  -- Substitute initial parameters into original polynomial constraint
  have h_subst1 : ((p : ℤ) * X') ^ 4 - 48 * ((p : ℤ) * (Y' : ℤ)) ^ 4 = S ^ 2 :=
    substitute_eq_nat X S Y p X' Y' hX_eq hY_eq h

  -- Algebraically force that p^2 perfectly divides S
  have hdvd : (p : ℤ) ^ 2 ∣ S := sq_dvd_of_eq_pow_four p hp_prime X' (Y' : ℤ) S h_subst1

  -- Reallocate bounded variable extraction representing S'
  rcases hdvd with ⟨S', hS_eq⟩

  -- Substitute extracted factor parameters representation of `S'` back into the primary equation
  have h_subst2 : ((p : ℤ) * X') ^ 4 - 48 * ((p : ℤ) * (Y' : ℤ)) ^ 4 = ((p : ℤ) ^ 2 * S') ^ 2 := by
    rw [hS_eq] at h_subst1
    exact h_subst1

  -- Cancel strictly non-zero integer sequence scale out of terms yielding identical bounds
  have hp_neq : (p : ℤ) ≠ 0 := p_neq_zero p hp_le

  have h_reduced : X' ^ 4 - 48 * (Y' : ℤ) ^ 4 = S' ^ 2 :=
    reduce_equation_step (p : ℤ) X' (Y' : ℤ) S' hp_neq h_subst2

  -- Invoking structural induction hypotheses with appropriately bounded internal parameters cleanly resolves contradiction limits yielding definitive False
  exact ih Y' hY'_lt X' S' hY'_pos hX'_odd h_reduced

theorem gcd_pos_helper (X : ℤ) (Y : ℕ) (hY : 0 < Y) : 0 < X.natAbs.gcd Y :=
by
  have h_ne : X.natAbs.gcd Y ≠ 0 := by
    intro h
    rw [Nat.gcd_eq_zero_iff] at h
    omega
  omega

theorem gcd_cases (X : ℤ) (Y : ℕ) (hY : 0 < Y) :
  X.natAbs.gcd Y = 1 ∨ 1 < X.natAbs.gcd Y :=
by
  have h_pos := gcd_pos_helper X Y hY
  omega

theorem odd_X4_minus_48Y4 (X : ℤ) (Y : ℕ) (hX : Odd X) : Odd (X ^ 4 - 48 * (Y : ℤ) ^ 4) :=
by
  obtain ⟨k, hk⟩ := hX
  use 8 * k ^ 4 + 16 * k ^ 3 + 12 * k ^ 2 + 4 * k - 24 * (Y : ℤ) ^ 4
  rw [hk]
  ring

theorem custom_even_sq_of_even (S : ℤ) (h : Even S) : Even (S ^ 2) :=
by
  obtain ⟨k, hk⟩ := h
  exact ⟨2 * k ^ 2, by rw [hk]; ring⟩

theorem custom_not_even_and_odd (n : ℤ) (h_even : Even n) (h_odd : Odd n) : False :=
by
  obtain ⟨k, hk⟩ := h_even
  obtain ⟨m, hm⟩ := h_odd
  omega

theorem custom_int_emod_cases (S : ℤ) : S % 2 = 0 ∨ S % 2 = 1 :=
by
  exact Int.emod_two_eq_zero_or_one S

theorem custom_even_of_emod_zero (S : ℤ) (h : S % 2 = 0) : Even S :=
by
  exact Int.even_iff.mpr h

theorem custom_odd_of_emod_one (S : ℤ) (h : S % 2 = 1) : Odd S :=
by
  exact Int.odd_iff.mpr h

theorem custom_int_even_or_odd (S : ℤ) : Even S ∨ Odd S :=
by
  match custom_int_emod_cases S with
  | Or.inl h0 => exact Or.inl (custom_even_of_emod_zero S h0)
  | Or.inr h1 => exact Or.inr (custom_odd_of_emod_one S h1)

theorem odd_of_sq_odd (S : ℤ) (h : Odd (S ^ 2)) : Odd S :=
by
  cases custom_int_even_or_odd S with
  | inl h_even =>
    have h_even_sq : Even (S ^ 2) := custom_even_sq_of_even S h_even
    exfalso
    exact custom_not_even_and_odd (S ^ 2) h_even_sq h
  | inr h_odd =>
    exact h_odd

theorem S_is_odd (X S : ℤ) (Y : ℕ) (h : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2) (hX : Odd X) : Odd S :=
by
  have h1 : Odd (X ^ 4 - 48 * (Y : ℤ) ^ 4) := odd_X4_minus_48Y4 X Y hX
  have h2 : Odd (S ^ 2) := by
    rw [← h]
    exact h1
  exact odd_of_sq_odd S h2

theorem get_M_N (X S : ℤ) (hX : Odd X) (hS : Odd S) :
  ∃ M N : ℤ, 2 * M = X ^ 2 - S ∧ 2 * N = X ^ 2 + S :=
by
  obtain ⟨k, hk⟩ := hX
  obtain ⟨m, hm⟩ := hS
  use 2 * k ^ 2 + 2 * k - m, 2 * k ^ 2 + 2 * k + m + 1
  constructor
  · rw [hk, hm]
    ring
  · rw [hk, hm]
    ring

theorem MN_sum (X S M N : ℤ) (hM : 2 * M = X ^ 2 - S) (hN : 2 * N = X ^ 2 + S) :
  M + N = X ^ 2 :=
by
  linarith

theorem MN_mul (X S : ℤ) (Y : ℕ) (M N : ℤ)
  (hM : 2 * M = X ^ 2 - S) (hN : 2 * N = X ^ 2 + S)
  (h : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2) :
  M * N = 12 * (Y : ℤ) ^ 4 :=
by
  have h1 : 4 * (M * N) = 48 * (Y : ℤ) ^ 4 := by
    calc
      4 * (M * N) = (2 * M) * (2 * N) := by ring
      _ = (X ^ 2 - S) * (X ^ 2 + S) := by rw [hM, hN]
      _ = X ^ 4 - S ^ 2 := by ring
      _ = 48 * (Y : ℤ) ^ 4 := by linarith
  linarith

theorem MN_equations (X S : ℤ) (Y : ℕ) (M N : ℤ)
  (hM : 2 * M = X ^ 2 - S) (hN : 2 * N = X ^ 2 + S) (h : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2) :
  M * N = 12 * (Y : ℤ) ^ 4 ∧ M + N = X ^ 2 :=
by
  exact ⟨MN_mul X S Y M N hM hN h, MN_sum X S M N hM hN⟩

theorem odd_ne_zero (X : ℤ) (hX : Odd X) : X ≠ 0 :=
by
  rintro rfl
  exact Int.not_odd_zero hX

theorem odd_sq_pos (X : ℤ) (hX : Odd X) : 0 < X ^ 2 :=
by
  have hne : X ≠ 0 := odd_ne_zero X hX
  positivity

theorem twelve_Y4_pos (Y : ℕ) (hY : 0 < Y) : 0 < 12 * (Y : ℤ) ^ 4 :=
by
  have hY_int : 0 < (Y : ℤ) := Nat.cast_pos.mpr hY
  positivity

theorem pos_and_pos_of_mul_pos_and_add_pos (M N : ℤ) (hMul : 0 < M * N) (hAdd : 0 < M + N) : 0 < M ∧ 0 < N :=
by
  rcases mul_pos_iff.mp hMul with ⟨hM, hN⟩ | ⟨hM, hN⟩
  · exact ⟨hM, hN⟩
  · omega

theorem MN_pos (X M N : ℤ) (Y : ℕ) (hY : 0 < Y) (hX : Odd X)
  (hMN : M * N = 12 * (Y : ℤ) ^ 4) (hSum : M + N = X ^ 2) : 0 < M ∧ 0 < N :=
by
  have h1 : 0 < M * N := by
    rw [hMN]
    exact twelve_Y4_pos Y hY
  have h2 : 0 < M + N := by
    rw [hSum]
    exact odd_sq_pos X hX
  exact pos_and_pos_of_mul_pos_and_add_pos M N h1 h2

theorem extract_M_N (X S : ℤ) (Y : ℕ) (h : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2) (hX : Odd X) (hY : 0 < Y) :
  ∃ M N : ℤ, 2 * M = X ^ 2 - S ∧ 2 * N = X ^ 2 + S ∧ M * N = 12 * (Y : ℤ) ^ 4 ∧ M + N = X ^ 2 ∧ 0 < M ∧ 0 < N :=
by
  have hS : Odd S := S_is_odd X S Y h hX
  have ⟨M, N, hM, hN⟩ := get_M_N X S hX hS
  have ⟨hMN_mul, hMN_add⟩ := MN_equations X S Y M N hM hN h
  have ⟨hM_pos, hN_pos⟩ := MN_pos X M N Y hY hX hMN_mul hMN_add
  exact ⟨M, N, hM, hN, hMN_mul, hMN_add, hM_pos, hN_pos⟩

theorem prime_dvd_of_both_zero (M N : ℤ) (hM : M = 0) (hN : N = 0) :
  ∃ p : ℕ, p.Prime ∧ (p : ℤ) ∣ M ∧ (p : ℤ) ∣ N :=
by
  use 2
  rw [hM, hN]
  exact ⟨by norm_num, dvd_zero (2 : ℤ), dvd_zero (2 : ℤ)⟩

theorem natAbs_prime_of_int_prime (z : ℤ) (hz : Prime z) : z.natAbs.Prime :=
Int.prime_iff_natAbs_prime.mp hz

theorem natAbs_dvd_of_dvd (z x : ℤ) (h : z ∣ x) : (z.natAbs : ℤ) ∣ x :=
by
  rcases h with ⟨c, hc⟩
  by_cases h0 : 0 ≤ z
  · use c
    have hz : z = (z.natAbs : ℤ) := by omega
    rw [hz] at hc
    exact hc
  · use -c
    have hz : z = - (z.natAbs : ℤ) := by omega
    rw [hz] at hc
    rw [hc]
    ring

theorem exists_prime_dvd_of_not_coprime (M N : ℤ) (h : ¬ IsCoprime M N) :
  ∃ p : ℕ, p.Prime ∧ (p : ℤ) ∣ M ∧ (p : ℤ) ∣ N :=
by
  by_contra h_contra
  apply h
  apply isCoprime_of_prime_dvd
  · intro hZero
    have hM : M = 0 := hZero.1
    have hN : N = 0 := hZero.2
    exact h_contra (prime_dvd_of_both_zero M N hM hN)
  · intro z hz hzM hzN
    exact h_contra ⟨z.natAbs, natAbs_prime_of_int_prime z hz, natAbs_dvd_of_dvd z M hzM, natAbs_dvd_of_dvd z N hzN⟩

theorem prime_dvd_X_of_dvd_M_N (X M N : ℤ) (p : ℕ) (hp : p.Prime)
  (hSum : M + N = X ^ 2) (hM : (p : ℤ) ∣ M) (hN : (p : ℤ) ∣ N) : (p : ℤ) ∣ X :=
by
  -- Since p divides M and p divides N, it must divide their sum.
  have h_add : (p : ℤ) ∣ M + N := dvd_add hM hN

  -- We substitute the sum M + N with X^2 to deduce that p divides X^2.
  rw [hSum] at h_add

  -- We push the primality of `p` in Nat to primality in Int.
  have hp_prime : Prime (p : ℤ) := Nat.prime_iff_prime_int.mp hp

  -- Finally, since p is prime and divides a square (power), it must divide the base.
  exact hp_prime.dvd_of_dvd_pow h_add

theorem prime_not_two_of_dvd_odd (X : ℤ) (p : ℕ) (hp : p.Prime)
  (hX : Odd X) (hpX : (p : ℤ) ∣ X) : p ≠ 2 :=
by
  rintro rfl
  rcases hpX with ⟨k, hk⟩
  rcases hX with ⟨m, hm⟩
  omega

theorem nat_dvd_natAbs_of_int_dvd {p : ℕ} {X : ℤ} (h : (p : ℤ) ∣ X) : p ∣ X.natAbs :=
Int.natCast_dvd.mp h

theorem not_dvd_one_of_prime {p : ℕ} (hp : p.Prime) : ¬(p ∣ 1) :=
by
  intro h
  have h1 : p = 1 := Nat.eq_one_of_dvd_one h
  subst h1
  exact Nat.not_prime_one hp

theorem not_dvd_Y_of_dvd_X_coprime (X : ℤ) (Y p : ℕ) (hp : p.Prime)
  (hcoprime : X.natAbs.gcd Y = 1) (hpX : (p : ℤ) ∣ X) : ¬(p ∣ Y) :=
by
  intro hY
  -- 1. Deduce that p divides the absolute value of X as a natural number
  have h1 : p ∣ X.natAbs := nat_dvd_natAbs_of_int_dvd hpX

  -- 2. Since p divides both X.natAbs and Y, it must divide their greatest common divisor
  have h2 : p ∣ X.natAbs.gcd Y := Nat.dvd_gcd h1 hY

  -- 3. We are given that X.natAbs and Y are coprime, meaning their gcd is 1
  rw [hcoprime] at h2

  -- 4. A prime cannot divide 1, which provides the final contradiction
  exact not_dvd_one_of_prime hp h2

theorem p_sq_dvd_12_Y_4 (M N : ℤ) (Y p : ℕ)
  (hMul : M * N = 12 * (Y : ℤ) ^ 4) (hM : (p : ℤ) ∣ M) (hN : (p : ℤ) ∣ N) :
  (p : ℤ) ^ 2 ∣ 12 * (Y : ℤ) ^ 4 :=
by
  rw [← hMul]
  rw [sq]
  exact mul_dvd_mul hM hN

theorem p_sq_dvd_12_Y_4_nat (Y p : ℕ) (h : (p : ℤ) ^ 2 ∣ 12 * (Y : ℤ) ^ 4) : p ^ 2 ∣ 12 * Y ^ 4 :=
by
  exact_mod_cast h

theorem p_sq_coprime_Y_pow_4 (Y p : ℕ) (hp : p.Prime) (hndvd : ¬(p ∣ Y)) : (p ^ 2).Coprime (Y ^ 4) :=
by
  -- Since p is prime and does not divide Y, p is coprime to Y
  have h1 : p.Coprime Y := Iff.mpr (Nat.Prime.coprime_iff_not_dvd hp) hndvd

  -- Coprimality is preserved when the left number is raised to a power
  have h2 : (p ^ 2).Coprime Y := Nat.Coprime.pow_left 2 h1

  -- Coprimality is preserved when the right number is raised to a power
  have h3 : (p ^ 2).Coprime (Y ^ 4) := Nat.Coprime.pow_right 4 h2

  exact h3

theorem aux_dvd_mul_right (k m : ℕ) : k ∣ k * m :=
⟨m, rfl⟩

theorem aux_mul_comm_dvd (k m n : ℕ) (h : k ∣ m * n) : k ∣ n * m :=
by
  rw [mul_comm n m]
  exact h

theorem aux_dvd_gcd (k a b : ℕ) (ha : k ∣ a) (hb : k ∣ b) : k ∣ Nat.gcd a b :=
Nat.dvd_gcd ha hb

theorem aux_gcd_eq (k m n : ℕ) (h_coprime : k.Coprime n) : Nat.gcd (k * m) (n * m) = m :=
by
  have h : Nat.gcd k n = 1 := h_coprime
  rw [Nat.gcd_mul_right, h, Nat.one_mul]

theorem nat_dvd_of_coprime_mul (k m n : ℕ) (h_coprime : k.Coprime n) (h_dvd : k ∣ m * n) : k ∣ m :=
by
  -- $k$ trivially divides $k \cdot m$
  have h1 : k ∣ k * m := aux_dvd_mul_right k m

  -- From $k \mid m \cdot n$, we also have $k \mid n \cdot m$
  have h2 : k ∣ n * m := aux_mul_comm_dvd k m n h_dvd

  -- If $k$ divides both, it must divide their greatest common divisor
  have h3 : k ∣ Nat.gcd (k * m) (n * m) := aux_dvd_gcd k (k * m) (n * m) h1 h2

  -- The GCD of $k \cdot m$ and $n \cdot m$ is $m$ since $k$ and $n$ are coprime
  have h4 : Nat.gcd (k * m) (n * m) = m := aux_gcd_eq k m n h_coprime

  -- Substituting the simplified GCD back gives exactly $k \mid m$
  rw [h4] at h3
  exact h3

theorem p_sq_dvd_12_nat (Y p : ℕ) (hp : p.Prime)
  (hndvd : ¬(p ∣ Y)) (h : (p : ℤ) ^ 2 ∣ 12 * (Y : ℤ) ^ 4) :
  p ^ 2 ∣ 12 :=
nat_dvd_of_coprime_mul (p ^ 2) 12 (Y ^ 4) (p_sq_coprime_Y_pow_4 Y p hp hndvd) (p_sq_dvd_12_Y_4_nat Y p h)

theorem prime_ge_3 (p : ℕ) (hp : p.Prime) (hp2 : p ≠ 2) : p ≥ 3 :=
by
  have h : 2 ≤ p := Nat.Prime.two_le hp
  omega

theorem sq_le_12_of_sq_dvd_12 (p : ℕ) (h : p ^ 2 ∣ 12) : p ^ 2 ≤ 12 :=
by
  exact Nat.le_of_dvd (by decide) h

theorem sq_ge_16_of_ge_4 (p : ℕ) (h : 4 ≤ p) : 16 ≤ p ^ 2 :=
by
  have h1 : 16 ≤ p * p := by
    calc
      16 = 4 * 4 := rfl
      _ ≤ p * p := Nat.mul_le_mul h h
  have h2 : p ^ 2 = p * p := by ring
  rw [h2]
  exact h1

theorem p_le_3_of_sq_le_12 (p : ℕ) (h : p ^ 2 ≤ 12) : p ≤ 3 :=
by
  by_contra h'
  have h4 : 4 ≤ p := by omega
  have h16 : 16 ≤ p ^ 2 := sq_ge_16_of_ge_4 p h4
  omega

theorem p_eq_3_of_sq_dvd_12 (p : ℕ) (hp : p ≥ 3) (h : p ^ 2 ∣ 12) : p = 3 :=
by
  have h1 : p ^ 2 ≤ 12 := sq_le_12_of_sq_dvd_12 p h
  have h2 : p ≤ 3 := p_le_3_of_sq_le_12 p h1
  omega

theorem p_sq_not_dvd_12 (p : ℕ) (hp : p.Prime) (hp2 : p ≠ 2) : ¬(p ^ 2 ∣ 12) :=
by
  intro h
  have h1 : p ≥ 3 := prime_ge_3 p hp hp2
  have h2 : p = 3 := p_eq_3_of_sq_dvd_12 p h1 h
  subst h2
  revert h
  norm_num

theorem coprime_M_N (X S : ℤ) (Y : ℕ) (hX : Odd X) (hcoprime : X.natAbs.gcd Y = 1)
  (M N : ℤ) (hM : 2 * M = X ^ 2 - S) (hN : 2 * N = X ^ 2 + S) (h : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2) : IsCoprime M N :=
by
  by_contra h_not_coprime
  rcases exists_prime_dvd_of_not_coprime M N h_not_coprime with ⟨p, hp, hpM, hpN⟩
  have h_eqs := MN_equations X S Y M N hM hN h
  have hMul := h_eqs.1
  have hSum := h_eqs.2
  have hpX : (p : ℤ) ∣ X := prime_dvd_X_of_dvd_M_N X M N p hp hSum hpM hpN
  have hp2 : p ≠ 2 := prime_not_two_of_dvd_odd X p hp hX hpX
  have hndvd : ¬(p ∣ Y) := not_dvd_Y_of_dvd_X_coprime X Y p hp hcoprime hpX
  have hp2_dvd_mul : (p : ℤ) ^ 2 ∣ 12 * (Y : ℤ) ^ 4 := p_sq_dvd_12_Y_4 M N Y p hMul hpM hpN
  have hp2_dvd_12 : p ^ 2 ∣ 12 := p_sq_dvd_12_nat Y p hp hndvd hp2_dvd_mul
  exact p_sq_not_dvd_12 p hp hp2 hp2_dvd_12

theorem odd_sum_of_odd_sq (M N X : ℤ) (h : M + N = X ^ 2) (hX : Odd X) : Odd (M + N) :=
by
  rw [h]
  obtain ⟨k, hk⟩ := hX
  exact ⟨2 * k ^ 2 + 2 * k, by rw [hk]; ring⟩

theorem parity_cases_of_coprime_and_odd_sum (M N : ℤ) (hcoprime : IsCoprime M N) (hsum : Odd (M + N)) :
  (Odd M ∧ Even N) ∨ (Even M ∧ Odd N) :=
by
  -- Unfold the definition of Odd to extract the linear equation
  obtain ⟨k, hk⟩ := hsum

  -- Integer remainders modulo 2 must be 0 or 1
  have hM : M % 2 = 0 ∨ M % 2 = 1 := by omega
  have hN : N % 2 = 0 ∨ N % 2 = 1 := by omega

  -- Case split on the actual parities
  rcases hM with hM0 | hM1
  · rcases hN with hN0 | hN1
    · -- Both Even: Sum would be Even, contradicting the hypothesis
      exfalso
      omega
    · -- M Even, N Odd
      right
      constructor
      · exact ⟨M / 2, by omega⟩
      · exact ⟨N / 2, by omega⟩
  · rcases hN with hN0 | hN1
    · -- M Odd, N Even
      left
      constructor
      · exact ⟨M / 2, by omega⟩
      · exact ⟨N / 2, by omega⟩
    · -- Both Odd: Sum would be Even, contradicting the hypothesis
      exfalso
      omega

theorem odd_of_odd_three_mul_pow_four (a : ℤ) (h : Odd (3 * a ^ 4)) : Odd a :=
by
  have h1 : Odd (a ^ 4) := Int.Odd.of_mul_right h
  have h2 : (4 : ℕ) ≠ 0 := by decide
  exact (Int.odd_pow' h2).mp h1

theorem zmod_8_odd_sq (x : ZMod 8) : (2 * x + 1) ^ 2 = 1 :=
by
  revert x
  decide

theorem odd_sq_mod_eight_k (k : ℤ) : ((2 * k + 1 : ℤ) : ZMod 8) ^ 2 = 1 :=
by
  push_cast
  rw [zmod_8_odd_sq]

theorem odd_sq_mod_eight (X : ℤ) (hX : Odd X) : (X : ZMod 8) ^ 2 = 1 :=
by
  -- By definition of an odd integer, there exists some integer k such that X = 2 * k + 1
  obtain ⟨k, hk⟩ := hX
  -- Substitute this equality into our goal expression
  subst hk
  -- We are left exactly with the generic case over arbitrary integer k
  exact odd_sq_mod_eight_k k

theorem odd_pow_four_mod_eight (a : ℤ) (ha : Odd a) : (a : ZMod 8) ^ 4 = 1 :=
by
  -- Extract the integer witness `k` such that `a = 2 * k + 1` and substitute it everywhere for `a`.
  rcases ha with ⟨k, rfl⟩

  -- Use a calc block to explicitly orchestrate the expansion and modulo reduction
  calc (((2 * k + 1) : ℤ) : ZMod 8) ^ 4
    -- 1. Push the integer to `ZMod 8` coercion inside the operations.
    _ = (2 * (k : ZMod 8) + 1) ^ 4 := by push_cast; rfl

    -- 2. Expand the polynomial algebraically. The `ring` tactic verifies the standard binomial expansion.
    _ = 16 * (k : ZMod 8) ^ 4 + 32 * (k : ZMod 8) ^ 3 + 24 * (k : ZMod 8) ^ 2 + 8 * (k : ZMod 8) + 1 := by ring

    -- 3. Substitute the coefficients that evaluate to 0 modulo 8 and cleanly reduce the polynomial.
    _ = 1 := by
      have h16 : (16 : ZMod 8) = 0 := rfl
      have h32 : (32 : ZMod 8) = 0 := rfl
      have h24 : (24 : ZMod 8) = 0 := rfl
      have h8  : (8 : ZMod 8) = 0 := rfl
      rw [h16, h32, h24, h8]
      ring

theorem zmod_8_eq_impossible (b : ZMod 8) (h : (3 : ZMod 8) + 4 * b ^ 4 = 1) : False :=
by
  revert b
  decide

theorem case_B_impossible (a b X : ℤ) (h : 3 * a ^ 4 + 4 * b ^ 4 = X ^ 2) (hX : Odd X) (ha : Odd a) : False :=
by
  -- Project the equality modulo 8
  have h1 := congrArg (fun (x : ℤ) ↦ (x : ZMod 8)) h

  -- Push the integer casts into the operations
  push_cast at h1

  -- Apply the lemmas that simplify odd powers in ZMod 8
  rw [odd_sq_mod_eight X hX, odd_pow_four_mod_eight a ha] at h1

  -- At this point, h1 is exactly `3 * 1 + 4 * (b : ZMod 8) ^ 4 = 1`
  -- We now rearrange this to cleanly match the zmod_8_eq_impossible lemma's hypothesis
  have h2 : (3 : ZMod 8) + 4 * (b : ZMod 8) ^ 4 = 1 := by
    calc
      (3 : ZMod 8) + 4 * (b : ZMod 8) ^ 4 = 3 * 1 + 4 * (b : ZMod 8) ^ 4 := by ring
      _ = 1 := h1

  -- Derive the final contradiction
  exact zmod_8_eq_impossible (b : ZMod 8) h2

theorem four_dvd_mul_of_eq (M N : ℤ) (Y : ℕ) (h : M * N = 12 * (Y : ℤ) ^ 4) : 4 ∣ M * N :=
by
  rw [h]
  exact ⟨3 * (Y : ℤ) ^ 4, by ring⟩

theorem three_dvd_mul_of_eq (M N : ℤ) (Y : ℕ) (h : M * N = 12 * (Y : ℤ) ^ 4) : 3 ∣ M * N :=
by
  rw [h]
  exact ⟨4 * (Y : ℤ) ^ 4, by ring⟩

theorem four_dvd_of_odd_mul (M N : ℤ) (hM : Odd M) (h : 4 ∣ M * N) : 4 ∣ N :=
by
  -- Destructure the hypotheses into explicit integer witnesses and equations.
  obtain ⟨k, hk⟩ := hM
  obtain ⟨c, hc⟩ := h

  -- Provide the explicit algebraic witness w such that N = 4 * w.
  exact ⟨c - 2 * k * c + k ^ 2 * N, by
    calc
      N = (1 - 2 * k) * (2 * k + 1) * N + 4 * k ^ 2 * N := by ring
      _ = (1 - 2 * k) * (M * N) + 4 * k ^ 2 * N := by
        -- Substitute (2 * k + 1) with M
        rw [← hk]
        ring
      _ = 4 * (c - 2 * k * c + k ^ 2 * N) := by
        -- Substitute (M * N) with (4 * c)
        rw [hc]
        ring⟩

theorem four_dvd_of_mul_odd_identity (M N c k : ℤ) (hN : N = 2 * k + 1) (hMN : M * N = 4 * c) :
  M = 4 * (c - 2 * k * c + k ^ 2 * M) :=
by
  -- We provide the exact coefficients for the linear combination of our hypotheses:
  -- (1 - 2k) * (MN - 4c) + M(2k - 1) * (N - (2k + 1)) = M - 4c + 8kc - 4k^2M
  linear_combination (1 - 2 * k) * hMN + M * (2 * k - 1) * hN

theorem four_dvd_of_mul_odd (M N : ℤ) (hN : Odd N) (h : 4 ∣ M * N) : 4 ∣ M :=
by
  obtain ⟨k, hk⟩ := hN
  obtain ⟨c, hc⟩ := h
  use c - 2 * k * c + k ^ 2 * M
  exact four_dvd_of_mul_odd_identity M N c k hk hc

theorem three_dvd_or_dvd_of_mul (M N : ℤ) (h : 3 ∣ M * N) : 3 ∣ M ∨ 3 ∣ N :=
by
  exact Int.Prime.dvd_mul' (by norm_num : Nat.Prime 3) h

theorem twelve_dvd_of_three_and_four (N : ℤ) (h3 : 3 ∣ N) (h4 : 4 ∣ N) : 12 ∣ N :=
by
  -- Destructure the divisibility hypotheses to obtain our integer multipliers
  rcases h3 with ⟨k, hk⟩
  rcases h4 with ⟨m, hm⟩

  -- Provide the explicit integer witness for N being a multiple of 12
  use k - m

  -- Use Lean's linear arithmetic and ring solvers to verify the equality
  calc N = 4 * N - 3 * N   := by ring
       _ = 4 * (3 * k) - 3 * N := by rw [hk]
       _ = 4 * (3 * k) - 3 * (4 * m) := by rw [hm]
       _ = 12 * (k - m)    := by ring

theorem cancel_twelve (M N Y : ℤ) (h : M * (12 * N) = 12 * Y ^ 4) : M * N = Y ^ 4 :=
by
  have h1 : 12 * (M * N) = 12 * Y ^ 4 := by
    calc
      12 * (M * N) = M * (12 * N) := by ring
      _ = 12 * Y ^ 4 := h
  linarith

theorem cancel_twelve_right (M N Y : ℤ) (h : (12 * M) * N = 12 * Y ^ 4) : M * N = Y ^ 4 :=
by
  have h1 : 12 * (M * N) = 12 * Y ^ 4 := by
    calc
      12 * (M * N) = (12 * M) * N := by ring
      _ = 12 * Y ^ 4 := h
  linarith

theorem cancel_twelve_mixed (M N Y : ℤ) (h : (3 * M) * (4 * N) = 12 * Y ^ 4) : M * N = Y ^ 4 :=
by
  have h1 : 12 * (M * N) = 12 * Y ^ 4 := by
    calc
      12 * (M * N) = (3 * M) * (4 * N) := by ring
      _ = 12 * Y ^ 4 := h
  linarith

theorem cancel_twelve_mixed_right (M N Y : ℤ) (h : (4 * M) * (3 * N) = 12 * Y ^ 4) : M * N = Y ^ 4 :=
by
  have h1 : 12 * (M * N) = 12 * Y ^ 4 := by
    calc
      12 * (M * N) = (4 * M) * (3 * N) := by ring
      _ = 12 * Y ^ 4 := h
  linarith

theorem coprime_of_mul_coprime_left (M N k : ℤ) (h : IsCoprime M (k * N)) : IsCoprime M N :=
IsCoprime.of_mul_right_right h

theorem coprime_of_mul_coprime_right (M N k : ℤ) (h : IsCoprime (k * M) N) : IsCoprime M N :=
match h with
  | ⟨x, y, hxy⟩ => ⟨x * k, y, by rw [mul_assoc, hxy]⟩

theorem coprime_of_coprime_mul_mul_algebra (M1 N1 k1 k2 a b : ℤ) (h : a * (k1 * M1) + b * (k2 * N1) = 1) : (a * k1) * M1 + (b * k2) * N1 = 1 :=
by
  rw [mul_assoc, mul_assoc]
  exact h

theorem coprime_of_coprime_mul_mul (M1 N1 k1 k2 : ℤ) (h : IsCoprime (k1 * M1) (k2 * N1)) : IsCoprime M1 N1 :=
by
  obtain ⟨a, b, hab⟩ := h
  use a * k1, b * k2
  exact coprime_of_coprime_mul_mul_algebra M1 N1 k1 k2 a b hab

theorem my_pos_of_mul_pos_left (A k : ℤ) (hk : 0 < k) (h : 0 < k * A) : 0 < A :=
by
  nlinarith

theorem isUnit_gcd_of_coprime_int (m n : ℤ) (h : IsCoprime m n) : IsUnit (GCDMonoid.gcd m n) :=
(gcd_isUnit_iff m n).mpr h

theorem eq_of_associated_of_nonneg {a b : ℤ} (ha : 0 ≤ a) (hb : 0 ≤ b) (h : Associated a b) : a = b :=
by
  have h_or : a = b ∨ a = -b := Int.associated_iff.mp h
  rcases h_or with h1 | h2
  · exact h1
  · omega

theorem int_eq_pow_four_of_associated (m d : ℤ) (hm : 0 < m) (h : Associated (d ^ 4) m) : m = d ^ 4 :=
by
  have hd : 0 ≤ d ^ 4 := by positivity
  have hm_nonneg : 0 ≤ m := by omega
  exact (eq_of_associated_of_nonneg hd hm_nonneg h).symm

theorem nonneg_eq_of_pow_four_eq (x z : ℤ) (hx : 0 ≤ x) (hz : 0 ≤ z) (h : x ^ 4 = z ^ 4) : x = z :=
by
  have h4 : (4 : ℕ) ≠ 0 := by decide
  exact (pow_left_inj₀ hx hz h4).mp h

theorem adjust_signs_for_product (m n y a b : ℤ) (hy : 0 ≤ y) (hm : m = a ^ 4) (hn : n = b ^ 4) (hy_pow : y ^ 4 = (a * b) ^ 4) :
  ∃ a' b' : ℤ, m = a' ^ 4 ∧ n = b' ^ 4 ∧ y = a' * b' :=
by
  by_cases hab : 0 ≤ a * b
  · exact ⟨a, b, hm, hn, nonneg_eq_of_pow_four_eq y (a * b) hy hab hy_pow⟩
  · have hm' : m = (-a) ^ 4 := by
      rw [hm]
      ring
    have h_pos : 0 ≤ -a * b := by
      have h1 : 0 ≤ -(a * b) := by linarith
      have h2 : -(a * b) = -a * b := by ring
      rw [← h2]
      exact h1
    have h_pow : y ^ 4 = (-a * b) ^ 4 := by
      calc y ^ 4 = (a * b) ^ 4 := hy_pow
           _ = (-a * b) ^ 4 := by ring
    exact ⟨-a, b, hm', hn, nonneg_eq_of_pow_four_eq y (-a * b) hy h_pos h_pow⟩

theorem int_coprime_mul_eq_pow_four (m n y : ℤ) (hm : 0 < m) (hn : 0 < n) (hy : 0 ≤ y)
  (h_coprime : IsCoprime m n) (h_mul : m * n = y ^ 4) :
  ∃ a b : ℤ, m = a ^ 4 ∧ n = b ^ 4 ∧ y = a * b :=
by
  have h_unit : IsUnit (GCDMonoid.gcd m n) := isUnit_gcd_of_coprime_int m n h_coprime
  obtain ⟨a, ha_assoc⟩ := exists_associated_pow_of_mul_eq_pow h_unit h_mul
  have ha_eq : m = a ^ 4 := int_eq_pow_four_of_associated m a hm ha_assoc

  have h_coprime_rev : IsCoprime n m := h_coprime.symm
  have h_unit_rev : IsUnit (GCDMonoid.gcd n m) := isUnit_gcd_of_coprime_int n m h_coprime_rev
  have h_mul_rev : n * m = y ^ 4 := by
    rw [mul_comm]
    exact h_mul
  obtain ⟨b, hb_assoc⟩ := exists_associated_pow_of_mul_eq_pow h_unit_rev h_mul_rev
  have hb_eq : n = b ^ 4 := int_eq_pow_four_of_associated n b hn hb_assoc

  have hy_pow : y ^ 4 = (a * b) ^ 4 := by
    calc y ^ 4 = m * n := h_mul.symm
         _ = a ^ 4 * b ^ 4 := by rw [ha_eq, hb_eq]
         _ = (a * b) ^ 4 := by ring

  exact adjust_signs_for_product m n y a b hy ha_eq hb_eq hy_pow

theorem factor_M_N (M N : ℤ) (Y : ℕ) (hMN : M * N = 12 * (Y : ℤ) ^ 4)
  (hposM : 0 < M) (hposN : 0 < N) (hcoprime : IsCoprime M N)
  (hX2 : ∃ X : ℤ, Odd X ∧ M + N = X ^ 2) :
  ∃ a b : ℤ, (Y : ℤ) = a * b ∧ ((M = a ^ 4 ∧ N = 12 * b ^ 4) ∨ (M = 12 * a ^ 4 ∧ N = b ^ 4)) :=
by
  obtain ⟨X, hX_odd, hX_sum⟩ := hX2
  have h_sum_odd : Odd (M + N) := odd_sum_of_odd_sq M N X hX_sum hX_odd
  have h_cases : (Odd M ∧ Even N) ∨ (Even M ∧ Odd N) :=
    parity_cases_of_coprime_and_odd_sum M N hcoprime h_sum_odd
  rcases h_cases with ⟨hM_odd, hN_even⟩ | ⟨hM_even, hN_odd⟩
  · have h4 : 4 ∣ M * N := four_dvd_mul_of_eq M N Y hMN
    have h3_dvd : 3 ∣ M * N := three_dvd_mul_of_eq M N Y hMN
    have h4N : 4 ∣ N := four_dvd_of_odd_mul M N hM_odd h4
    have h3_cases : 3 ∣ M ∨ 3 ∣ N := three_dvd_or_dvd_of_mul M N h3_dvd
    rcases h3_cases with h3M | h3N
    · obtain ⟨M1, hM1⟩ := h3M
      obtain ⟨N1, hN1⟩ := h4N
      have hMN_sub : (3 * M1) * (4 * N1) = 12 * (Y : ℤ) ^ 4 := by
        calc
          (3 * M1) * (4 * N1) = M * (4 * N1) := by rw [← hM1]
          _ = M * N := by rw [← hN1]
          _ = 12 * (Y : ℤ) ^ 4 := hMN
      have hM1N1 : M1 * N1 = (Y : ℤ) ^ 4 := cancel_twelve_mixed M1 N1 (Y : ℤ) hMN_sub
      have h_coprime_sub : IsCoprime M1 N1 := coprime_of_coprime_mul_mul M1 N1 3 4 (by
        have h_eq : 3 * M1 = M := hM1.symm
        have h_eq2 : 4 * N1 = N := hN1.symm
        rw [h_eq, h_eq2]
        exact hcoprime)
      have hM1_pos : 0 < M1 := my_pos_of_mul_pos_left M1 3 (by decide) (by
        have h_eq : 3 * M1 = M := hM1.symm
        rw [h_eq]
        exact hposM)
      have hN1_pos : 0 < N1 := my_pos_of_mul_pos_left N1 4 (by decide) (by
        have h_eq : 4 * N1 = N := hN1.symm
        rw [h_eq]
        exact hposN)
      have hY_nonneg : 0 ≤ (Y : ℤ) := by exact Nat.cast_nonneg Y
      obtain ⟨a, b, hM1_eq, hN1_eq, hY_eq⟩ := int_coprime_mul_eq_pow_four M1 N1 (Y : ℤ) hM1_pos hN1_pos hY_nonneg h_coprime_sub hM1N1
      have ha_odd : Odd a := odd_of_odd_three_mul_pow_four a (by
        have h_eq : 3 * a ^ 4 = M := by
          calc
            3 * a ^ 4 = 3 * M1 := by rw [← hM1_eq]
            _ = M := by rw [← hM1]
        rw [h_eq]
        exact hM_odd)
      have hB_imp : 3 * a ^ 4 + 4 * b ^ 4 = X ^ 2 := by
        calc
          3 * a ^ 4 + 4 * b ^ 4 = 3 * M1 + 4 * N1 := by rw [← hM1_eq, ← hN1_eq]
          _ = M + 4 * N1 := by rw [← hM1]
          _ = M + N := by rw [← hN1]
          _ = X ^ 2 := hX_sum
      have h_false := case_B_impossible a b X hB_imp hX_odd ha_odd
      exact False.elim h_false
    · have h12N : 12 ∣ N := twelve_dvd_of_three_and_four N h3N h4N
      obtain ⟨N1, hN1⟩ := h12N
      have hMN_sub : M * (12 * N1) = 12 * (Y : ℤ) ^ 4 := by
        calc
          M * (12 * N1) = M * N := by rw [← hN1]
          _ = 12 * (Y : ℤ) ^ 4 := hMN
      have hMN1 : M * N1 = (Y : ℤ) ^ 4 := cancel_twelve M N1 (Y : ℤ) hMN_sub
      have h_coprime_sub : IsCoprime M N1 := coprime_of_mul_coprime_left M N1 12 (by
        have h_eq : 12 * N1 = N := hN1.symm
        rw [h_eq]
        exact hcoprime)
      have hN1_pos : 0 < N1 := my_pos_of_mul_pos_left N1 12 (by decide) (by
        have h_eq : 12 * N1 = N := hN1.symm
        rw [h_eq]
        exact hposN)
      have hY_nonneg : 0 ≤ (Y : ℤ) := by exact Nat.cast_nonneg Y
      obtain ⟨a, b, hM_eq, hN1_eq, hY_eq⟩ := int_coprime_mul_eq_pow_four M N1 (Y : ℤ) hposM hN1_pos hY_nonneg h_coprime_sub hMN1
      use a, b
      refine ⟨hY_eq, Or.inl ⟨hM_eq, ?_⟩⟩
      calc
        N = 12 * N1 := hN1
        _ = 12 * b ^ 4 := by rw [hN1_eq]
  · have h4 : 4 ∣ M * N := four_dvd_mul_of_eq M N Y hMN
    have h3_dvd : 3 ∣ M * N := three_dvd_mul_of_eq M N Y hMN
    have h4M : 4 ∣ M := four_dvd_of_mul_odd M N hN_odd h4
    have h3_cases : 3 ∣ M ∨ 3 ∣ N := three_dvd_or_dvd_of_mul M N h3_dvd
    rcases h3_cases with h3M | h3N
    · have h12M : 12 ∣ M := twelve_dvd_of_three_and_four M h3M h4M
      obtain ⟨M1, hM1⟩ := h12M
      have hMN_sub : (12 * M1) * N = 12 * (Y : ℤ) ^ 4 := by
        calc
          (12 * M1) * N = M * N := by rw [← hM1]
          _ = 12 * (Y : ℤ) ^ 4 := hMN
      have hM1N : M1 * N = (Y : ℤ) ^ 4 := cancel_twelve_right M1 N (Y : ℤ) hMN_sub
      have h_coprime_sub : IsCoprime M1 N := coprime_of_mul_coprime_right M1 N 12 (by
        have h_eq : 12 * M1 = M := hM1.symm
        rw [h_eq]
        exact hcoprime)
      have hM1_pos : 0 < M1 := my_pos_of_mul_pos_left M1 12 (by decide) (by
        have h_eq : 12 * M1 = M := hM1.symm
        rw [h_eq]
        exact hposM)
      have hY_nonneg : 0 ≤ (Y : ℤ) := by exact Nat.cast_nonneg Y
      obtain ⟨a, b, hM1_eq, hN_eq, hY_eq⟩ := int_coprime_mul_eq_pow_four M1 N (Y : ℤ) hM1_pos hposN hY_nonneg h_coprime_sub hM1N
      use a, b
      refine ⟨hY_eq, Or.inr ⟨?_, hN_eq⟩⟩
      calc
        M = 12 * M1 := hM1
        _ = 12 * a ^ 4 := by rw [hM1_eq]
    · obtain ⟨M1, hM1⟩ := h4M
      obtain ⟨N1, hN1⟩ := h3N
      have hMN_sub : (4 * M1) * (3 * N1) = 12 * (Y : ℤ) ^ 4 := by
        calc
          (4 * M1) * (3 * N1) = M * (3 * N1) := by rw [← hM1]
          _ = M * N := by rw [← hN1]
          _ = 12 * (Y : ℤ) ^ 4 := hMN
      have hM1N1 : M1 * N1 = (Y : ℤ) ^ 4 := cancel_twelve_mixed_right M1 N1 (Y : ℤ) hMN_sub
      have h_coprime_sub : IsCoprime M1 N1 := coprime_of_coprime_mul_mul M1 N1 4 3 (by
        have h_eq : 4 * M1 = M := hM1.symm
        have h_eq2 : 3 * N1 = N := hN1.symm
        rw [h_eq, h_eq2]
        exact hcoprime)
      have hM1_pos : 0 < M1 := my_pos_of_mul_pos_left M1 4 (by decide) (by
        have h_eq : 4 * M1 = M := hM1.symm
        rw [h_eq]
        exact hposM)
      have hN1_pos : 0 < N1 := my_pos_of_mul_pos_left N1 3 (by decide) (by
        have h_eq : 3 * N1 = N := hN1.symm
        rw [h_eq]
        exact hposN)
      have hY_nonneg : 0 ≤ (Y : ℤ) := by exact Nat.cast_nonneg Y
      obtain ⟨a, b, hM1_eq, hN1_eq, hY_eq⟩ := int_coprime_mul_eq_pow_four M1 N1 (Y : ℤ) hM1_pos hN1_pos hY_nonneg h_coprime_sub hM1N1
      have hb_odd : Odd b := odd_of_odd_three_mul_pow_four b (by
        have h_eq : 3 * b ^ 4 = N := by
          calc
            3 * b ^ 4 = 3 * N1 := by rw [← hN1_eq]
            _ = N := by rw [← hN1]
        rw [h_eq]
        exact hN_odd)
      have hB_imp : 3 * b ^ 4 + 4 * a ^ 4 = X ^ 2 := by
        calc
          3 * b ^ 4 + 4 * a ^ 4 = 3 * N1 + 4 * M1 := by rw [← hN1_eq, ← hM1_eq]
          _ = N + 4 * M1 := by rw [← hN1]
          _ = N + M := by rw [← hM1]
          _ = M + N := by rw [add_comm]
          _ = X ^ 2 := hX_sum
      have h_false := case_B_impossible b a X hB_imp hX_odd hb_odd
      exact False.elim h_false

theorem odd_sq (x : ℤ) (hx : Odd x) : Odd (x ^ 2) :=
by
  -- By definition, since x is odd, there exists some integer k such that x = 2k + 1
  obtain ⟨k, hk⟩ := hx

  -- We provide the witness for x^2 being odd, which is 2k^2 + 2k
  use 2 * k ^ 2 + 2 * k

  -- Substitute x with 2k + 1
  rw [hk]

  -- The remaining algebraic identity (2k + 1)^2 = 2(2k^2 + 2k) + 1 can be solved automatically by the `ring` tactic
  ring

theorem odd_of_odd_add_12_mul (x y : ℤ) (h : Odd (x + 12 * y)) : Odd x :=
by
  obtain ⟨k, hk⟩ := h
  exact ⟨k - 6 * y, by linarith⟩

theorem even_pow4_of_even (x : ℤ) (hx : Even x) : Even (x ^ 4) :=
by
  rw [Int.even_pow]
  exact ⟨hx, by decide⟩

theorem odd_of_odd_pow4 (x : ℤ) (h : Odd (x ^ 4)) : Odd x :=
by
  by_cases hx : Even x
  · -- Case 1: If x is even, we use the helper lemma to reach a contradiction.
    have h4 : Even (x ^ 4) := even_pow4_of_even x hx
    obtain ⟨k, hk⟩ := h
    obtain ⟨m, hm⟩ := h4
    -- 'h' asserts x^4 is odd (x^4 = 2k + 1) and 'h4' asserts x^4 is even (x^4 = 2m).
    -- The omega tactic proves that 2m = 2k + 1 has no integer solution.
    omega
  · -- Case 2: If x is not even (thus odd), we can swiftly close using the exact library result.
    exact (Int.odd_pow' (by decide)).mp h

theorem odd_A_of_X2_eq_A4_add_12B4 (X A B : ℤ) (h : X ^ 2 = A ^ 4 + 12 * B ^ 4) (hX : Odd X) : Odd A :=
by
  have h1 : Odd (X ^ 2) := odd_sq X hX
  have h2 : Odd (A ^ 4 + 12 * B ^ 4) := by
    rw [←h]
    exact h1
  have h3 : Odd (A ^ 4) := odd_of_odd_add_12_mul (A ^ 4) (B ^ 4) h2
  exact odd_of_odd_pow4 A h3

theorem symmetric_M_N (M N X a b : ℤ) (hX : M + N = X ^ 2) (hOddX : Odd X)
  (h : (M = a ^ 4 ∧ N = 12 * b ^ 4) ∨ (M = 12 * a ^ 4 ∧ N = b ^ 4)) :
  ∃ A B : ℤ, X ^ 2 = A ^ 4 + 12 * B ^ 4 ∧ (a * b).natAbs = (A * B).natAbs ∧ Odd A :=
by
  rcases h with ⟨rfl, rfl⟩ | ⟨rfl, rfl⟩
  · -- Case 1: M = a^4 and N = 12 * b^4
    use a, b
    have h1 : X ^ 2 = a ^ 4 + 12 * b ^ 4 := hX.symm
    exact ⟨h1, rfl, odd_A_of_X2_eq_A4_add_12B4 X a b h1 hOddX⟩
  · -- Case 2: M = 12 * a^4 and N = b^4
    use b, a
    have h1 : X ^ 2 = b ^ 4 + 12 * a ^ 4 := by
      calc X ^ 2 = 12 * a ^ 4 + b ^ 4 := hX.symm
      _ = b ^ 4 + 12 * a ^ 4 := add_comm (12 * a ^ 4) (b ^ 4)
    refine ⟨h1, ?_, odd_A_of_X2_eq_A4_add_12B4 X b a h1 hOddX⟩
    -- The target for the remaining absolute value condition is (a * b).natAbs = (b * a).natAbs
    rw [mul_comm a b]

theorem coprime_X_Y (X : ℤ) (Y : ℕ) (h : X.natAbs.gcd Y = 1) : IsCoprime X (Y : ℤ) :=
Int.isCoprime_iff_nat_coprime.mpr h

theorem eq_or_eq_neg_of_natAbs_eq_alt (U V : ℤ) (h : U.natAbs = V.natAbs) : U = V ∨ U = -V :=
by
  omega

theorem coprime_of_natAbs_eq (X U V : ℤ) (h : U.natAbs = V.natAbs) (hU : IsCoprime X U) : IsCoprime X V :=
by
  -- Obtain the two possible relations between U and V
  have h_or : U = V ∨ U = -V := eq_or_eq_neg_of_natAbs_eq_alt U V h
  rcases h_or with h1 | h2
  · -- Case 1: U = V
    rw [h1] at hU
    exact hU
  · -- Case 2: U = -V
    rw [h2] at hU
    -- Unfold the definition of IsCoprime X (-V)
    rcases hU with ⟨a, b, hab⟩
    -- Provide the updated coefficients a and -b to prove IsCoprime X V
    exact ⟨a, -b, by
      -- Align the expression algebraically
      have h_eq : a * X + (-b) * V = a * X + b * (-V) := by ring
      rw [h_eq]
      exact hab⟩

theorem get_coprime_X_A (X A B : ℤ) (Y : ℕ) (hcoprime : X.natAbs.gcd Y = 1)
  (hY : (Y : ℤ).natAbs = (A * B).natAbs) (hX2 : X ^ 2 = A ^ 4 + 12 * B ^ 4) : IsCoprime X A :=
by
  have h1 : IsCoprime X (Y : ℤ) := coprime_X_Y X Y hcoprime
  have h2 : IsCoprime X (A * B) := coprime_of_natAbs_eq X (Y : ℤ) (A * B) hY h1
  exact IsCoprime.of_mul_right_left h2

theorem B_ne_zero (Y : ℕ) (hY : 0 < Y) (A B : ℤ) (h : (Y : ℤ).natAbs = (A * B).natAbs) : B ≠ 0 :=
by
  intro hB
  rw [hB] at h
  rw [mul_zero] at h
  omega

theorem natAbs_eq_self_lem (X : ℤ) (h : 0 ≤ X) : (X.natAbs : ℤ) = X :=
by
  omega

theorem sq_natAbs_helper (X : ℤ) (h : 0 ≤ X) : (X.natAbs : ℤ) ^ 2 = X ^ 2 :=
by
  rw [natAbs_eq_self_lem X h]

theorem sq_natAbs (X : ℤ) : (X.natAbs : ℤ) ^ 2 = X ^ 2 :=
by
  by_cases h : 0 ≤ X
  · exact sq_natAbs_helper X h
  · have h1 : 0 ≤ -X := by omega
    have h2 := sq_natAbs_helper (-X) h1
    have h3 : (-X).natAbs = X.natAbs := Int.natAbs_neg X
    rw [h3] at h2
    rw [h2]
    ring

theorem odd_of_odd_sq (X : ℤ) (h : Odd (X ^ 2)) : Odd X :=
by
  have h1 := Int.odd_pow.mp h
  cases h1 with
  | inl h_odd => exact h_odd
  | inr h_zero => contradiction

theorem odd_of_sq_eq (X A B : ℤ) (h : X ^ 2 = A ^ 4 + 12 * B ^ 4) (hA : Odd A) : Odd X :=
by
  apply odd_of_odd_sq
  obtain ⟨k, hk⟩ := hA
  use 8 * k ^ 4 + 16 * k ^ 3 + 12 * k ^ 2 + 4 * k + 6 * B ^ 4
  rw [h, hk]
  ring

theorem natAbs_eq_self_or_neg (X : ℤ) : (X.natAbs : ℤ) = X ∨ (X.natAbs : ℤ) = -X :=
by
  omega

theorem odd_neg_of_odd (X : ℤ) (h : Odd X) : Odd (-X) :=
by
  exact Odd.neg h

theorem odd_natAbs (X : ℤ) (h : Odd X) : Odd (X.natAbs : ℤ) :=
by
  match natAbs_eq_self_or_neg X with
  | Or.inl hEq =>
    rw [hEq]
    exact h
  | Or.inr hEq =>
    rw [hEq]
    exact odd_neg_of_odd X h

theorem get_P_Q_from_k_m (k m : ℤ) :
  ∃ P Q : ℤ, 2 * P = (2 * k + 1) - (2 * m + 1) ^ 2 ∧ 2 * Q = (2 * k + 1) + (2 * m + 1) ^ 2 :=
by
  use k - 2 * m ^ 2 - 2 * m, k + 2 * m ^ 2 + 2 * m + 1
  constructor
  · ring
  · ring

theorem get_P_Q (x A : ℤ) (hx : Odd x) (hA : Odd A) : ∃ P Q : ℤ, 2 * P = x - A ^ 2 ∧ 2 * Q = x + A ^ 2 :=
by
  obtain ⟨k, hk⟩ := hx
  obtain ⟨m, hm⟩ := hA
  rw [hk, hm]
  exact get_P_Q_from_k_m k m

theorem P_Q_mul (x A B P Q : ℤ) (hP : 2 * P = x - A ^ 2) (hQ : 2 * Q = x + A ^ 2) (hx : x ^ 2 = A ^ 4 + 12 * B ^ 4) :
  P * Q = 3 * B ^ 4 :=
by
  have h1 : 4 * (P * Q) = 12 * B ^ 4 := by
    -- Expand 4PQ to (2P)(2Q)
    have h2 : 4 * (P * Q) = (2 * P) * (2 * Q) := by ring
    rw [h2, hP, hQ]

    -- Evaluate the product (x - A^2)(x + A^2)
    have h3 : (x - A ^ 2) * (x + A ^ 2) = x ^ 2 - A ^ 4 := by ring
    rw [h3, hx]

    -- Final algebraic simplification of (A^4 + 12B^4) - A^4 = 12B^4
    ring

  -- Cancel the scalar factor 4 using linear integer arithmetic
  linarith

theorem P_Q_add (x A P Q : ℤ) (hP : 2 * P = x - A ^ 2) (hQ : 2 * Q = x + A ^ 2) :
  P + Q = x :=
by
  linarith

theorem P_Q_sub (x A P Q : ℤ) (hP : 2 * P = x - A ^ 2) (hQ : 2 * Q = x + A ^ 2) :
  Q - P = A ^ 2 :=
by
  linarith

theorem P_Q_equations (x A B P Q : ℤ) (hP : 2 * P = x - A ^ 2) (hQ : 2 * Q = x + A ^ 2) (hx : x ^ 2 = A ^ 4 + 12 * B ^ 4) :
  P * Q = 3 * B ^ 4 ∧ P + Q = x ∧ Q - P = A ^ 2 :=
by
  have h1 := P_Q_mul x A B P Q hP hQ hx
  have h2 := P_Q_add x A P Q hP hQ
  have h3 := P_Q_sub x A P Q hP hQ
  exact ⟨h1, h2, h3⟩

theorem isCoprime_natAbs_left (X A : ℤ) (h : IsCoprime X A) : IsCoprime (X.natAbs : ℤ) A :=
by
  -- 1. Unpack the original coprime witnesses
  obtain ⟨u, v, h_eq⟩ := h

  -- 2. Case split on the constructors of the integer X
  cases X with
  | ofNat n =>
    -- Case 1: X is non-negative.
    -- (X.natAbs : ℤ) simplifies to Int.ofNat n, which is definitionally exactly X.
    -- We can use the same witnesses u and v.
    use u, v
    exact h_eq
  | negSucc n =>
    -- Case 2: X is strictly negative.
    -- X = Int.negSucc n, and its absolute value corresponds algebraically to -X.
    -- We negate the first witness.
    use -u, v

    -- The absolute value of (Int.negSucc n) cast to integers is exactly the negation of Int.negSucc n.
    have h_abs : (Int.natAbs (Int.negSucc n) : ℤ) = - (Int.negSucc n) := rfl

    -- We verify the resulting algebraic equality for our new witnesses.
    calc
      -u * (Int.natAbs (Int.negSucc n) : ℤ) + v * A = -u * -(Int.negSucc n) + v * A := by rw [h_abs]
      _ = u * (Int.negSucc n) + v * A := by ring
      _ = 1 := h_eq

theorem P_Q_coprime_lem (P Q x A : ℤ) (hsum : P + Q = x) (hdiff : Q - P = A ^ 2) (hcoprime : IsCoprime x A) : IsCoprime P Q :=
by
  have h1 : IsCoprime (x ^ 1) (A ^ 2) := IsCoprime.pow hcoprime
  have h2 : x ^ 1 = x := pow_one x
  rw [h2] at h1
  rcases h1 with ⟨c, d, hcd⟩
  exact ⟨c - d, c + d, by
    calc
      (c - d) * P + (c + d) * Q = c * (P + Q) + d * (Q - P) := by ring
      _ = c * x + d * A ^ 2 := by rw [hsum, hdiff]
      _ = 1 := hcd⟩

theorem b_pow_four_pos (B : ℤ) (hB : B ≠ 0) : 0 < B ^ 4 :=
by
  positivity

theorem three_mul_b_pow_four_pos (B : ℤ) (hB : B ≠ 0) : 0 < 3 * B ^ 4 :=
by
  -- Obtain the positivity of B^4 using our lemma
  have hB4 : 0 < B ^ 4 := b_pow_four_pos B hB
  -- The constant 3 is strictly positive
  have h3 : (0 : ℤ) < 3 := by norm_num
  -- The product of two positive integers is positive
  exact mul_pos h3 hB4

theorem Q_pos_of_P_pos (P Q : ℤ) (hP : 0 < P) (hmul : 0 < P * Q) : 0 < Q :=
by
  nlinarith

theorem absurd_of_nonpos_P (P Q : ℤ) (hP : P ≤ 0) (hmul : 0 < P * Q) (hadd : 0 ≤ P + Q) : False :=
by
  have hQ : 0 ≤ Q := by linarith
  nlinarith

theorem pos_of_mul_pos_add_nonneg (P Q : ℤ) (hmul : 0 < P * Q) (hadd : 0 ≤ P + Q) : 0 < P ∧ 0 < Q :=
by
  by_cases hP : 0 < P
  · -- Case 1: P is strictly positive
    exact ⟨hP, Q_pos_of_P_pos P Q hP hmul⟩
  · -- Case 2: P is non-positive (leads to a contradiction)
    exfalso
    have hP_le : P ≤ 0 := by omega
    exact absurd_of_nonpos_P P Q hP_le hmul hadd

theorem P_Q_pos_lem (P Q x B : ℤ) (hPQ : P * Q = 3 * B ^ 4) (hSum : P + Q = x) (hx_pos : 0 ≤ x) (hB : B ≠ 0) : 0 < P ∧ 0 < Q :=
by
  have h1 : 0 < 3 * B ^ 4 := three_mul_b_pow_four_pos B hB
  have h2 : 0 < P * Q := by
    rw [hPQ]
    exact h1
  have h3 : 0 ≤ P + Q := by
    rw [hSum]
    exact hx_pos
  exact pos_of_mul_pos_add_nonneg P Q h2 h3

theorem natAbs_nonneg_lem (X : ℤ) : 0 ≤ (X.natAbs : ℤ) :=
by
  omega

theorem coprime_P_Q (X A B : ℤ) (h : X ^ 2 = A ^ 4 + 12 * B ^ 4)
  (hA : Odd A) (hcoprime : IsCoprime X A) (hB : B ≠ 0) :
  ∃ P Q : ℤ, P * Q = 3 * B ^ 4 ∧ P + Q = (X.natAbs : ℤ) ∧ Q - P = A ^ 2 ∧ IsCoprime P Q ∧ 0 < P ∧ 0 < Q :=
by
  have hX_odd : Odd X := odd_of_sq_eq X A B h hA
  have hXabs_odd : Odd (X.natAbs : ℤ) := odd_natAbs X hX_odd
  have h_sq : (X.natAbs : ℤ) ^ 2 = A ^ 4 + 12 * B ^ 4 := by
    rw [sq_natAbs]
    exact h
  obtain ⟨P, Q, hP, hQ⟩ := get_P_Q (X.natAbs : ℤ) A hXabs_odd hA
  use P, Q
  have heq : P * Q = 3 * B ^ 4 ∧ P + Q = (X.natAbs : ℤ) ∧ Q - P = A ^ 2 :=
    P_Q_equations (X.natAbs : ℤ) A B P Q hP hQ h_sq
  obtain ⟨hPQ, hSum, hDiff⟩ := heq
  have hcop : IsCoprime P Q := by
    have hcoprime_abs : IsCoprime (X.natAbs : ℤ) A := isCoprime_natAbs_left X A hcoprime
    exact P_Q_coprime_lem P Q (X.natAbs : ℤ) A hSum hDiff hcoprime_abs
  have hpos : 0 < P ∧ 0 < Q := P_Q_pos_lem P Q (X.natAbs : ℤ) B hPQ hSum (natAbs_nonneg_lem X) hB
  exact ⟨hPQ, hSum, hDiff, hcop, hpos.1, hpos.2⟩

theorem three_dvd_PQ (P Q B : ℤ) (h : P * Q = 3 * B ^ 4) : 3 ∣ P * Q :=
⟨B ^ 4, h⟩

theorem three_dvd_P_or_Q (P Q B : ℤ) (h : P * Q = 3 * B ^ 4) : 3 ∣ P ∨ 3 ∣ Q :=
by
  -- Obtain the fact that 3 divides P * Q
  have h_div : (3 : ℤ) ∣ P * Q := three_dvd_PQ P Q B h
  -- Apply Euclid's lemma for integers using the primality of 3
  exact Int.Prime.dvd_mul' Nat.prime_three h_div

theorem three_dvd_natAbs (P : ℤ) (h : (3 : ℤ) ∣ P) : (3 : ℕ) ∣ P.natAbs :=
Int.natCast_dvd.mp h

theorem coprime_nat_of_isCoprime_int (P Q : ℤ) (h : IsCoprime P Q) : P.natAbs.Coprime Q.natAbs :=
Int.isCoprime_iff_nat_coprime.mp h

theorem natAbs_mul_eq_three_mul_pow_four (P Q B : ℤ) (h : P * Q = (3 : ℤ) * B ^ 4) : P.natAbs * Q.natAbs = (3 : ℕ) * B.natAbs ^ 4 :=
by
  have h1 : (P * Q).natAbs = ((3 : ℤ) * B ^ 4).natAbs := congrArg Int.natAbs h
  rw [Int.natAbs_mul, Int.natAbs_mul, Int.natAbs_pow] at h1
  exact h1

theorem obtain_a_from_h3 (p : ℕ) (h3 : (3 : ℕ) ∣ p) : ∃ a : ℕ, p = (3 : ℕ) * a :=
by
  exact h3

theorem p_eq_three_a_mul (p q b a : ℕ) (hp : p = (3 : ℕ) * a) (h : p * q = (3 : ℕ) * b ^ 4) : (3 : ℕ) * (a * q) = (3 : ℕ) * b ^ 4 :=
by
  rw [← mul_assoc]
  rw [← hp]
  exact h

theorem coprime_subst (p q a : ℕ) (hp : p = (3 : ℕ) * a) (hc : p.Coprime q) : Nat.Coprime ((3 : ℕ) * a) q :=
by
  rw [← hp]
  exact hc

theorem mul_cancel_three (a q b : ℕ) (h : (3 : ℕ) * (a * q) = (3 : ℕ) * b ^ 4) : a * q = b ^ 4 :=
by
  omega

theorem coprime_of_mul_coprime (a q : ℕ) (hc : Nat.Coprime ((3 : ℕ) * a) q) : a.Coprime q :=
Nat.Coprime.of_dvd_left ⟨3, Nat.mul_comm 3 a⟩ hc

theorem pow_four_eq_sq_sq (x : ℕ) : x ^ 4 = (x ^ 2) ^ 2 :=
by
  ring

theorem int_sq_natAbs (x : ℤ) : ((x.natAbs : ℕ) : ℤ) ^ 2 = x ^ 2 :=
Int.natAbs_sq x

theorem nat_exists_eq_sq_of_mul_eq_sq (a b c : ℕ) (h : a * b = c ^ 2) (hc : a.Coprime b) : ∃ d : ℕ, a = d ^ 2 :=
by
  -- Cast the target equation into ℤ to leverage integer arithmetic factorization
  have h_int : (a : ℤ) * (b : ℤ) = (c : ℤ) ^ 2 := by exact_mod_cast h

  -- Coprimality transfers naturally to integer GCD directly by definitional equality
  have h_gcd : Int.gcd (a : ℤ) (b : ℤ) = 1 := by exact hc

  -- Use Mathlib's result to split into positive and negative square mappings in ℤ
  obtain ⟨a0, h_eq | h_eq⟩ := Int.sq_of_gcd_eq_one h_gcd h_int

  · -- Case 1: (a : ℤ) = a0 ^ 2
    have h1 : (a : ℤ) = (a0.natAbs : ℤ) ^ 2 := by
      rw [int_sq_natAbs a0]
      exact h_eq
    -- Project the mapped integer natAbs safely back to ℕ
    exact ⟨a0.natAbs, by exact_mod_cast h1⟩

  · -- Case 2: (a : ℤ) = - a0 ^ 2
    -- Since 'a' was cast from ℕ, it evaluates to 0
    have ha : a = 0 := nat_zero_of_int_eq_neg_sq a a0 h_eq
    exact ⟨0, by rw [ha]; rfl⟩

theorem nat_sq_inj (x y : ℕ) (h : x * x = y * y) : x = y :=
(mul_self_inj (Nat.zero_le x) (Nat.zero_le y)).mp h

theorem nat_sq_mul_sq_eq_mul_mul (d e : ℕ) : d ^ 2 * e ^ 2 = (d * e) * (d * e) :=
by
  ring

theorem nat_sq_eq_mul_mul (b : ℕ) : b ^ 2 = b * b :=
sq b

theorem nat_mul_eq_of_sq_mul_sq_eq_sq (d e b : ℕ) (h : d ^ 2 * e ^ 2 = b ^ 2) : d * e = b :=
by
  have h1 : d ^ 2 * e ^ 2 = (d * e) * (d * e) := nat_sq_mul_sq_eq_mul_mul d e
  have h2 : b ^ 2 = b * b := nat_sq_eq_mul_mul b
  rw [h1, h2] at h
  exact nat_sq_inj (d * e) b h

theorem sq_coprime_left (d e : ℕ) (h : (d ^ 2).Coprime e) : d.Coprime e :=
(Nat.coprime_pow_left_iff (n := 2) (by decide) d e).mp h

theorem sq_coprime_right (d e : ℕ) (h : d.Coprime (e ^ 2)) : d.Coprime e :=
(Nat.coprime_pow_right_iff (by decide) d e).mp h

theorem coprime_of_sq_coprime (d e : ℕ) (h : (d ^ 2).Coprime (e ^ 2)) : d.Coprime e :=
sq_coprime_right d e (sq_coprime_left d (e ^ 2) h)

theorem nat_exists_eq_pow_four_of_mul_eq_pow_four (a q b : ℕ) (h : a * q = b ^ 4) (hc : a.Coprime q) : ∃ d : ℕ, a = d ^ 4 :=
by
  have h' : a * q = (b ^ 2) ^ 2 := by
    rw [h, pow_four_eq_sq_sq]
  obtain ⟨d_1, hd1⟩ := nat_exists_eq_sq_of_mul_eq_sq a q (b ^ 2) h' hc

  have h'' : q * a = (b ^ 2) ^ 2 := by
    rw [Nat.mul_comm, h']
  have hc_symm : q.Coprime a := hc.symm
  obtain ⟨e_1, he1⟩ := nat_exists_eq_sq_of_mul_eq_sq q a (b ^ 2) h'' hc_symm

  have h_mul_sq : d_1 ^ 2 * e_1 ^ 2 = (b ^ 2) ^ 2 := by
    rw [← hd1, ← he1, h']
  have h_mul : d_1 * e_1 = b ^ 2 := nat_mul_eq_of_sq_mul_sq_eq_sq d_1 e_1 (b ^ 2) h_mul_sq

  have hc_sq : (d_1 ^ 2).Coprime (e_1 ^ 2) := by
    rw [← hd1, ← he1]
    exact hc
  have hc_d1_e1 : d_1.Coprime e_1 := coprime_of_sq_coprime d_1 e_1 hc_sq

  obtain ⟨d_2, hd2⟩ := nat_exists_eq_sq_of_mul_eq_sq d_1 e_1 b h_mul hc_d1_e1

  use d_2
  rw [hd1, hd2, ← pow_four_eq_sq_sq]

theorem nat_pow_four_inj (x y : ℕ) (h : x ^ 4 = y ^ 4) : x = y :=
by
  -- Expand the 4th powers into nested squares mathematically matching `nat_sq_inj`.
  have h1 : x ^ 4 = (x * x) * (x * x) := by ring
  have h2 : y ^ 4 = (y * y) * (y * y) := by ring

  -- Translate the goal through our explicit ring expansions
  have h3 : (x * x) * (x * x) = (y * y) * (y * y) := by
    rw [← h1, ← h2]
    exact h

  -- Apply the square injectivity once to eliminate the outer square.
  have h4 := nat_sq_inj (x * x) (y * y) h3

  -- Apply it a second time to eliminate the inner square.
  exact nat_sq_inj x y h4

theorem nat_coprime_mul_eq_pow_four (a q b : ℕ) (h : a * q = b ^ 4) (hc : a.Coprime q) :
  ∃ d e : ℕ, a = d ^ 4 ∧ q = e ^ 4 ∧ b = d * e :=
by
  -- 1. Extract `d` from the fact that `a * q` is a 4th power and `a` is coprime to `q`
  obtain ⟨d, hd⟩ := nat_exists_eq_pow_four_of_mul_eq_pow_four a q b h hc

  -- 2. Use commutativity and symmetry to apply the same logic for `q`
  have h_comm : q * a = b ^ 4 := by
    rw [Nat.mul_comm q a]
    exact h
  have hc_comm : q.Coprime a := hc.symm
  obtain ⟨e, he⟩ := nat_exists_eq_pow_four_of_mul_eq_pow_four q a b h_comm hc_comm

  -- 3. Supply the witnesses `d` and `e`
  use d, e
  refine ⟨hd, he, ?_⟩

  -- 4. Re-associate the variables algebraically to deduce `b = d * e`
  have h1 : (d * e) ^ 4 = b ^ 4 := by
    calc
      (d * e) ^ 4 = d ^ 4 * e ^ 4 := by rw [mul_pow]
      _ = a * e ^ 4 := by rw [← hd]
      _ = a * q := by rw [← he]
      _ = b ^ 4 := h

  -- 5. Conclude injectivity to strip off the 4th powers
  exact (nat_pow_four_inj (d * e) b h1).symm

theorem p_eq_subst (p a d : ℕ) (hp : p = (3 : ℕ) * a) (ha : a = d ^ 4) : p = (3 : ℕ) * d ^ 4 :=
by
  rw [hp, ha]

theorem factor_case1_nat (p q b : ℕ) (h : p * q = (3 : ℕ) * b ^ 4) (hcoprime : p.Coprime q) (h3 : (3 : ℕ) ∣ p) :
  ∃ d e : ℕ, p = (3 : ℕ) * d ^ 4 ∧ q = e ^ 4 ∧ b = d * e :=
by
  -- 1. Extract `a` such that `p = 3 * a`
  obtain ⟨a, ha⟩ := obtain_a_from_h3 p h3

  -- 2. Substitute `p` for `3 * a` in our equations
  have h1 : (3 : ℕ) * (a * q) = (3 : ℕ) * b ^ 4 := p_eq_three_a_mul p q b a ha h
  have hc1 : Nat.Coprime ((3 : ℕ) * a) q := coprime_subst p q a ha hcoprime

  -- 3. Resolve the base properties of `a` and `q`
  have haq : a * q = b ^ 4 := mul_cancel_three a q b h1
  have hcaq : a.Coprime q := coprime_of_mul_coprime a q hc1

  -- 4. Unpack the structural results given by the multiplication of coprime 4th powers
  have H := nat_coprime_mul_eq_pow_four a q b haq hcaq
  rcases H with ⟨d, e, hd, he, hde⟩

  -- 5. Construct the final exact requested term
  exact ⟨d, e, p_eq_subst p a d ha hd, he, hde⟩

theorem factor_case1 (P Q B : ℤ) (h : P * Q = 3 * B ^ 4) (hcoprime : IsCoprime P Q) (hp : 0 < P) (hq : 0 < Q) (h3 : 3 ∣ P) :
  ∃ d e : ℤ, P = 3 * d ^ 4 ∧ Q = e ^ 4 ∧ B.natAbs = (d * e).natAbs :=
by
  have h1 := natAbs_mul_eq_three_mul_pow_four P Q B h
  have h2 := coprime_nat_of_isCoprime_int P Q hcoprime
  have h3' := three_dvd_natAbs P h3

  -- Use the natural number roots directly
  rcases factor_case1_nat P.natAbs Q.natAbs B.natAbs h1 h2 h3' with ⟨d, e, hp_eq, hq_eq, hb_eq⟩

  -- We provide their integer casts to the existential goal
  use (d : ℤ), (e : ℤ)
  refine ⟨?_, ?_, ?_⟩

  · -- Prove P = 3 * d ^ 4
    have eqP : P = (P.natAbs : ℤ) := by omega
    rw [eqP, hp_eq]
    push_cast
    rfl

  · -- Prove Q = e ^ 4
    have eqQ : Q = (Q.natAbs : ℤ) := by omega
    rw [eqQ, hq_eq]
    push_cast
    rfl

  · -- Prove B.natAbs = |d * e|
    rw [hb_eq]
    -- Mathlib's fundamental equivalence for Int.natAbs of products over cast naturals resolves this natively
    exact (Int.natAbs_mul (d : ℤ) (e : ℤ)).symm

theorem factor_case2 (P Q B : ℤ) (h : P * Q = 3 * B ^ 4) (hcoprime : IsCoprime P Q) (hp : 0 < P) (hq : 0 < Q) (h3 : 3 ∣ Q) :
  ∃ d e : ℤ, P = d ^ 4 ∧ Q = 3 * e ^ 4 ∧ B.natAbs = (d * e).natAbs :=
by
  -- Swap P and Q in the product to apply factor_case1
  have h_comm : Q * P = 3 * B ^ 4 := by rw [mul_comm, h]

  -- Apply the previously established factor_case1 for the reversed roles
  obtain ⟨d', e', hQ, hP, hB⟩ := factor_case1 Q P B h_comm hcoprime.symm hq hp h3

  -- Supply the returned witnesses backwards to fit case2
  exact ⟨e', d', hP, hQ, by rw [hB, mul_comm d' e']⟩

theorem zmod8_odd_sq_helper (k : ZMod 8) : (2 * k + 1) ^ 2 = 1 :=
by
  revert k
  decide

theorem odd_sq_zmod8 (x : ℤ) (h : Odd x) : (x : ZMod 8) ^ 2 = 1 :=
by
  obtain ⟨k, hk⟩ := h
  rw [hk]
  push_cast
  exact zmod8_odd_sq_helper (k : ZMod 8)

theorem no_solution_zmod8 (d e : ZMod 8) : (3 : ZMod 8) * e ^ 4 - d ^ 4 ≠ 1 :=
by
  revert d e
  decide

theorem reject_case2 (A d e : ℤ) (hdiff : 3 * e ^ 4 - d ^ 4 = A ^ 2) (hA : Odd A) : False :=
by
  have h1 : ((3 * e ^ 4 - d ^ 4 : ℤ) : ZMod 8) = ((A ^ 2 : ℤ) : ZMod 8) :=
    congrArg (fun x : ℤ ↦ (x : ZMod 8)) hdiff
  have h2 : ((3 * e ^ 4 - d ^ 4 : ℤ) : ZMod 8) = (3 : ZMod 8) * (e : ZMod 8) ^ 4 - (d : ZMod 8) ^ 4 := by
    push_cast
    rfl
  have h3 : ((A ^ 2 : ℤ) : ZMod 8) = (A : ZMod 8) ^ 2 := by
    push_cast
    rfl
  have h4 : (A : ZMod 8) ^ 2 = 1 := odd_sq_zmod8 A hA
  have h5 : (3 : ZMod 8) * (e : ZMod 8) ^ 4 - (d : ZMod 8) ^ 4 = 1 := by
    rw [← h2, h1, h3, h4]
  exact no_solution_zmod8 (d : ZMod 8) (e : ZMod 8) h5

theorem factor_P_Q (P Q B A : ℤ) (hPQ : P * Q = 3 * B ^ 4)
  (hcoprime : IsCoprime P Q) (hdiff : Q - P = A ^ 2) (hA : Odd A) (hposP : 0 < P) (hposQ : 0 < Q) :
  ∃ d e : ℤ, P = 3 * d ^ 4 ∧ Q = e ^ 4 ∧ B.natAbs = (d * e).natAbs :=
by
  rcases three_dvd_P_or_Q P Q B hPQ with h3P | h3Q
  · exact factor_case1 P Q B hPQ hcoprime hposP hposQ h3P
  · obtain ⟨d, e, hp, hq, _⟩ := factor_case2 P Q B hPQ hcoprime hposP hposQ h3Q
    rw [hp, hq] at hdiff
    exact False.elim (reject_case2 A d e hdiff hA)

theorem Y_eq_A_B (Y : ℕ) (a b A B d e : ℤ) (hY : (Y : ℤ) = a * b)
  (h : (a * b).natAbs = (A * B).natAbs) (hB : B.natAbs = (d * e).natAbs) :
  Y = A.natAbs * (d * e).natAbs :=
by
  calc
    Y = (Y : ℤ).natAbs := rfl
    _ = (a * b).natAbs := by rw [hY]
    _ = (A * B).natAbs := h
    _ = A.natAbs * B.natAbs := Int.natAbs_mul A B
    _ = A.natAbs * (d * e).natAbs := by rw [hB]

theorem k_even_sq_add_k_even (k q : ℤ) (hk : k = 2 * q) : ∃ m : ℤ, k ^ 2 + k = 2 * m :=
by
  exact ⟨2 * q ^ 2 + q, by rw [hk]; ring⟩

theorem k_odd_sq_add_k_even (k q : ℤ) (hk : k = 2 * q + 1) : ∃ m : ℤ, k ^ 2 + k = 2 * m :=
by
  use 2 * q ^ 2 + 3 * q + 1
  rw [hk]
  ring

theorem k_sq_add_k_even (k : ℤ) : ∃ m : ℤ, k ^ 2 + k = 2 * m :=
by
  have h : k % 2 = 0 ∨ k % 2 = 1 := by omega
  cases h with
  | inl h0 =>
    have hk : k = 2 * (k / 2) := by omega
    exact k_even_sq_add_k_even k (k / 2) hk
  | inr h1 =>
    have hk : k = 2 * (k / 2) + 1 := by omega
    exact k_odd_sq_add_k_even k (k / 2) hk

theorem odd_sq_eq_eight_mul_add_one (x : ℤ) (hx : Odd x) : ∃ c : ℤ, x ^ 2 = 8 * c + 1 :=
by
  obtain ⟨k, hk⟩ := hx
  obtain ⟨m, hm⟩ := k_sq_add_k_even k
  use m
  have h_eq : x ^ 2 = 4 * (k ^ 2 + k) + 1 := by
    rw [hk]
    ring
  rw [h_eq, hm]
  ring

theorem d_is_even_exists_k (A e d : ℤ) (h : e ^ 4 - 3 * d ^ 4 = A ^ 2) (hA : Odd A) : ∃ k : ℤ, d = 2 * k :=
by
  by_cases hd : Even d
  · rcases hd with ⟨k, hk⟩
    use k
    omega
  · have hd_odd : Odd d := Int.not_even_iff_odd.mp hd
    rcases odd_sq_eq_eight_mul_add_one A hA with ⟨a', ha⟩
    rcases odd_pow_four_eq_eight_mul_add_one d hd_odd with ⟨d', hd'⟩
    by_cases he : Even e
    · rcases even_pow_four_eq_eight_mul e he with ⟨e', he'⟩
      omega
    · have he_odd : Odd e := Int.not_even_iff_odd.mp he
      rcases odd_pow_four_eq_eight_mul_add_one e he_odd with ⟨e', he'⟩
      omega

theorem even_of_not_odd (e : ℤ) (h : ¬ Odd e) : Even e :=
by
  exact Int.not_odd_iff_even.mp h

theorem e_is_odd_algebra (e d A m c k : ℤ)
  (h_eq : e ^ 4 - 3 * d ^ 4 = A ^ 2)
  (h_e : e ^ 4 = 8 * m)
  (h_A : A ^ 2 = 8 * c + 1)
  (h_d : d = 2 * k) :
  8 * m - 48 * k ^ 4 = 8 * c + 1 :=
by
  -- Show that the LHS matches the partially substituted target equation
  have h1 : 8 * m - 48 * k ^ 4 = e ^ 4 - 3 * (2 * k) ^ 4 := by
    rw [h_e]
    ring

  -- Show that this partially substituted term is equivalent to our un-substituted original formula side
  have h2 : e ^ 4 - 3 * (2 * k) ^ 4 = e ^ 4 - 3 * d ^ 4 := by
    rw [h_d]

  -- String everything together via substitution
  rw [h1, h2, h_eq, h_A]

theorem mul_eight_neq_mul_eight_add_one (a b : ℤ) (h : 8 * a = 8 * b + 1) : False :=
by
  omega

theorem e_is_odd_contradiction (m k c : ℤ) (h : 8 * m - 48 * k ^ 4 = 8 * c + 1) : False :=
by
  have h1 : 8 * (m - 6 * k ^ 4) = 8 * c + 1 := by omega
  exact mul_eight_neq_mul_eight_add_one (m - 6 * k ^ 4) c h1

theorem e_is_odd (A e d k : ℤ) (h : e ^ 4 - 3 * d ^ 4 = A ^ 2) (hA : Odd A) (hd : d = 2 * k) : Odd e :=
by
  by_contra h_not_odd
  have h_even : Even e := even_of_not_odd e h_not_odd
  have h_m : ∃ m : ℤ, e ^ 4 = 8 * m := even_pow_four_eq_eight_mul e h_even
  have h_c : ∃ c : ℤ, A ^ 2 = 8 * c + 1 := odd_sq_eq_eight_mul_add_one A hA
  cases h_m with
  | intro m hm =>
    cases h_c with
    | intro c hc =>
      have h_alg : 8 * m - 48 * k ^ 4 = 8 * c + 1 := e_is_odd_algebra e d A m c k h hm hc hd
      exact e_is_odd_contradiction m k c h_alg

theorem descent_step_algebra (A e d k : ℤ) (h : e ^ 4 - 3 * d ^ 4 = A ^ 2) (hd : d = 2 * k) :
  e ^ 4 - 48 * k ^ 4 = A ^ 2 :=
by
  calc
    e ^ 4 - 48 * k ^ 4 = e ^ 4 - 3 * (2 * k) ^ 4 := by ring
    _ = e ^ 4 - 3 * d ^ 4 := by rw [← hd]
    _ = A ^ 2 := h

theorem descent_step_y_eq (Y : ℕ) (A e d k : ℤ)
  (hY : Y = A.natAbs * (d * e).natAbs) (hd : d = 2 * k) :
  Y = 2 * A.natAbs * e.natAbs * k.natAbs :=
by
  rw [hY, hd]
  simp_rw [Int.natAbs_mul]
  ring

theorem pos_factors_helper (a b c : ℕ) (h : 0 < 2 * a * b * c) : 0 < c ∧ 0 < a ∧ 0 < b :=
by
  have hc : c ≠ 0 := by
    rintro rfl
    revert h
    simp
  have ha : a ≠ 0 := by
    rintro rfl
    revert h
    simp
  have hb : b ≠ 0 := by
    rintro rfl
    revert h
    simp
  exact ⟨by omega, by omega, by omega⟩

theorem pos_factors_of_y_pos (Y : ℕ) (A e k : ℤ)
  (hY : Y = 2 * A.natAbs * e.natAbs * k.natAbs) (hYpos : 0 < Y) :
  0 < k.natAbs ∧ 0 < A.natAbs ∧ 0 < e.natAbs :=
by
  rw [hY] at hYpos
  exact pos_factors_helper A.natAbs e.natAbs k.natAbs hYpos

theorem one_le_mul_of_pos_nat (a b : ℕ) (ha : 0 < a) (hb : 0 < b) : 1 ≤ a * b :=
Nat.mul_pos ha hb

theorem ge_two_of_one_le_mul (a b : ℕ) (h : 1 ≤ a * b) : 2 ≤ 2 * a * b :=
by
  rw [Nat.mul_assoc]
  omega

theorem ge_two_of_pos (a b : ℕ) (ha : 0 < a) (hb : 0 < b) :
  2 ≤ 2 * a * b :=
by
  apply ge_two_of_one_le_mul
  apply one_le_mul_of_pos_nat a b ha hb

theorem nat_lt_two_mul (y : ℕ) (hy : 0 < y) : y < 2 * y :=
by
  omega

theorem nat_two_mul_le_mul (x y : ℕ) (hx : 2 ≤ x) : 2 * y ≤ x * y :=
Nat.mul_le_mul_right y hx

theorem nat_mul_gt_of_ge_two (x y : ℕ) (hx : 2 ≤ x) (hy : 0 < y) :
  y < x * y :=
lt_of_lt_of_le (nat_lt_two_mul y hy) (nat_two_mul_le_mul x y hx)

theorem descent_step_y_prop (Y : ℕ) (A e d k : ℤ)
  (hY : Y = A.natAbs * (d * e).natAbs) (hYpos : 0 < Y) (hd : d = 2 * k) :
  k.natAbs < Y ∧ 0 < k.natAbs :=
by
  have h_eq : Y = 2 * A.natAbs * e.natAbs * k.natAbs := descent_step_y_eq Y A e d k hY hd
  have h_pos : 0 < k.natAbs ∧ 0 < A.natAbs ∧ 0 < e.natAbs := pos_factors_of_y_pos Y A e k h_eq hYpos
  have hk_pos : 0 < k.natAbs := h_pos.1
  have hA_pos : 0 < A.natAbs := h_pos.2.1
  have he_pos : 0 < e.natAbs := h_pos.2.2
  have hx : 2 ≤ 2 * A.natAbs * e.natAbs := ge_two_of_pos A.natAbs e.natAbs hA_pos he_pos
  have hy : k.natAbs < (2 * A.natAbs * e.natAbs) * k.natAbs := nat_mul_gt_of_ge_two (2 * A.natAbs * e.natAbs) k.natAbs hx hk_pos
  have h_lt : k.natAbs < Y := by
    rw [h_eq]
    exact hy
  exact ⟨h_lt, hk_pos⟩

theorem negSucc_eq (n : ℕ) : (Int.negSucc n) = -((n + 1 : ℕ) : ℤ) :=
rfl

theorem neg_pow_four (x : ℤ) : (-x) ^ 4 = x ^ 4 :=
by
  ring

theorem negSucc_pow_four (n : ℕ) : (Int.negSucc n) ^ 4 = ((n + 1 : ℕ) : ℤ) ^ 4 :=
by
  rw [negSucc_eq n, neg_pow_four]

theorem natAbs_pow_four (k : ℤ) : (k.natAbs : ℤ) ^ 4 = k ^ 4 :=
by
  cases k with
  | ofNat n => rfl
  | negSucc n => exact (negSucc_pow_four n).symm

theorem final_descent_step (A e d : ℤ) (Y : ℕ)
  (hQ : e ^ 4 - 3 * d ^ 4 = A ^ 2) (hA : Odd A)
  (hY : Y = A.natAbs * (d * e).natAbs) (hYpos : 0 < Y) :
  ∃ y : ℕ, y < Y ∧ 0 < y ∧ ∃ X S : ℤ, Odd X ∧ X ^ 4 - 48 * (y : ℤ) ^ 4 = S ^ 2 :=
by
  have ⟨k, hk⟩ := d_is_even_exists_k A e d hQ hA
  have he : Odd e := e_is_odd A e d k hQ hA hk
  have h_alg : e ^ 4 - 48 * k ^ 4 = A ^ 2 := descent_step_algebra A e d k hQ hk
  have h_y_prop : k.natAbs < Y ∧ 0 < k.natAbs := descent_step_y_prop Y A e d k hY hYpos hk

  -- Rewrite the absolute value equation purely with integers
  have h_alg2 : e ^ 4 - 48 * (k.natAbs : ℤ) ^ 4 = A ^ 2 := by
    rw [natAbs_pow_four k]
    exact h_alg

  -- Exact matches all clauses in the existential target recursively
  exact ⟨k.natAbs, h_y_prop.1, h_y_prop.2, e, A, he, h_alg2⟩

theorem descent_step (Y : ℕ)
  (ih : ∀ (y : ℕ), y < Y → ∀ (X S : ℤ), 0 < y → Odd X → X ^ 4 - 48 * (y : ℤ) ^ 4 = S ^ 2 → False)
  (X S : ℤ) (hY : 0 < Y) (hX : Odd X) (h : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2) : False :=
by
  have h_gcd := gcd_cases X Y hY
  cases h_gcd with
  | inl hcoprime =>
    rcases extract_M_N X S Y h hX hY with ⟨M, N, hM, hN, hMN_mul, hMN_add, hposM, hposN⟩
    have hcoprime_MN := coprime_M_N X S Y hX hcoprime M N hM hN h
    rcases factor_M_N M N Y hMN_mul hposM hposN hcoprime_MN ⟨X, hX, hMN_add⟩ with ⟨a, b, hYab, hab_cases⟩
    rcases symmetric_M_N M N X a b hMN_add hX hab_cases with ⟨A, B, hX2, hAB_natAbs, hA⟩

    have h_Y_natAbs : (Y : ℤ).natAbs = (A * B).natAbs := by
      rw [hYab]
      exact hAB_natAbs

    have hcoprime_XA := get_coprime_X_A X A B Y hcoprime h_Y_natAbs hX2
    have hB_ne_zero := B_ne_zero Y hY A B h_Y_natAbs

    rcases coprime_P_Q X A B hX2 hA hcoprime_XA hB_ne_zero with ⟨P, Q, hPQ_mul, hPQ_add, hPQ_sub, hcoprime_PQ, hposP, hposQ⟩
    rcases factor_P_Q P Q B A hPQ_mul hcoprime_PQ hPQ_sub hA hposP hposQ with ⟨d, e, hP, hQ, hB_natAbs⟩

    have hY_final := Y_eq_A_B Y a b A B d e hYab hAB_natAbs hB_natAbs
    have h_eqA : e ^ 4 - 3 * d ^ 4 = A ^ 2 := by
      rw [← hQ, ← hP]
      exact hPQ_sub

    rcases final_descent_step A e d Y h_eqA hA hY_final hY with ⟨y, hy_lt, hy_pos, X', S'', hX'_odd, h_eq⟩

    exact ih y hy_lt X' S'' hy_pos hX'_odd h_eq
  | inr hg =>
    exact reduce_to_coprime Y ih X S hY hX h hg

theorem no_sol_descent (X S : ℤ) (Y : ℕ) (hY : 0 < Y) (hX : Odd X)
  (h : X ^ 4 - 48 * (Y : ℤ) ^ 4 = S ^ 2) : False :=
by
  revert X S hY hX h
  refine Nat.strong_induction_on Y ?_
  intro y ih X S hy hx h_eq
  exact descent_step y ih X S hy hx h_eq

theorem no_sol_odd_even (u v : ℤ) (a b : ℕ) (ha_nz : a ≠ 0) (hb_nz : b ≠ 0)
  (hcoprime : IsCoprime u v)
  (hu_odd : Odd u) (hv_even : Even v)
  (ha : a ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs)
  (hb : b ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs) : False :=
by
  obtain ⟨X, S, Y, hY, hX, h⟩ := reduction_to_descent u v a b ha_nz hb_nz hcoprime hu_odd hv_even ha hb
  exact no_sol_descent X S Y hY hX h

theorem natAbs_symm_1 (u v : ℤ) :
  (v * (v ^ 2 - 3 * u ^ 2)).natAbs = (v * (3 * u ^ 2 - v ^ 2)).natAbs :=
by
  have h : v * (3 * u ^ 2 - v ^ 2) = - (v * (v ^ 2 - 3 * u ^ 2)) := by ring
  rw [h, Int.natAbs_neg]

theorem natAbs_symm_2 (u v : ℤ) :
  (u * (3 * v ^ 2 - u ^ 2)).natAbs = (u * (u ^ 2 - 3 * v ^ 2)).natAbs :=
by
  have h : u * (3 * v ^ 2 - u ^ 2) = - (u * (u ^ 2 - 3 * v ^ 2)) := by ring
  rw [h, Int.natAbs_neg]

theorem no_sol_even_odd (u v : ℤ) (a b : ℕ) (ha_nz : a ≠ 0) (hb_nz : b ≠ 0)
  (hcoprime : IsCoprime u v)
  (hu_even : Even u) (hv_odd : Odd v)
  (ha : a ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs)
  (hb : b ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs) : False :=
by
  have hb' : b ^ 2 = (v * (v ^ 2 - 3 * u ^ 2)).natAbs := by
    rw [natAbs_symm_1 u v]
    exact hb
  have ha' : a ^ 2 = (u * (3 * v ^ 2 - u ^ 2)).natAbs := by
    rw [natAbs_symm_2 u v]
    exact ha
  exact no_sol_odd_even v u b a hb_nz ha_nz hcoprime.symm hv_odd hu_even hb' ha'

theorem int_even_or_odd_lem (u : ℤ) : Even u ∨ Odd u :=
Int.even_or_odd u

theorem no_sol_diophantine (u v : ℤ) (a b : ℕ) (ha_nz : a ≠ 0) (hb_nz : b ≠ 0)
  (hcoprime : IsCoprime u v)
  (ha : a ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs)
  (hb : b ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs) : False :=
by
  have hu := int_even_or_odd_lem u
  have hv := int_even_or_odd_lem v
  cases hu with
  | inl hu_even =>
    cases hv with
    | inl hv_even => exact both_even_impossible u v hcoprime hu_even hv_even
    | inr hv_odd => exact no_sol_even_odd u v a b ha_nz hb_nz hcoprime hu_even hv_odd ha hb
  | inr hu_odd =>
    cases hv with
    | inl hv_even => exact no_sol_odd_even u v a b ha_nz hb_nz hcoprime hu_odd hv_even ha hb
    | inr hv_odd => exact both_odd_impossible u v a hu_odd hv_odd ha

theorem no_sol_for_param (p a b : ℕ) (ha : a ≠ 0) (hb : b ≠ 0) (u v : ℤ) (hp : p.Prime) (h_p : (p : ℤ) = u ^ 2 + v ^ 2) :
  ¬ ((a ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs ∧ b ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs) ∨
     (b ^ 2 = (u * (u ^ 2 - 3 * v ^ 2)).natAbs ∧ a ^ 2 = (v * (3 * u ^ 2 - v ^ 2)).natAbs)) :=
by
  intro h_or
  have hcoprime : IsCoprime u v := coprime_of_prime_eq_sum_sq p u v hp h_p
  rcases h_or with ⟨h1, h2⟩ | ⟨h3, h4⟩
  · exact no_sol_diophantine u v a b ha hb hcoprime h1 h2
  · exact no_sol_diophantine u v b a hb ha hcoprime h3 h4

theorem not_p_cube (p a b : ℕ) (hp : p.Prime) (ha : a ≠ 0) (hb : b ≠ 0) : p ^ 3 ≠ a ^ 4 + b ^ 4 :=
by
  intro h
  obtain ⟨u, v, h_p, huv⟩ := p_cube_eq_add_pow_four_implies_param p a b hp ha hb h
  exact no_sol_for_param p a b ha hb u v hp h_p huv

theorem PBAdvanced012 (p a b n : ℕ) (hp : p.Prime) (ha : a ≠ 0) (hb : b ≠ 0)
    (hp' : p ^ n = a ^ 4 + b ^ 4) (hn : 2 ≤ n) : 5 ≤ n :=
by
  by_contra h
  -- h : ¬(5 ≤ n). Combined with hn : 2 ≤ n, n must be 2, 3, or 4.
  have h_cases : n = 2 ∨ n = 3 ∨ n = 4 := by omega

  -- We destruct the possibilities and evaluate each one against its corresponding lemma
  rcases h_cases with rfl | rfl | rfl
  · exact not_p_sq p a b ha hb hp'
  · exact not_p_cube p a b hp ha hb hp'
  · exact not_p_pow_four p a b ha hb hp'
