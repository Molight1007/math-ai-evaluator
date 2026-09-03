import Mathlib
open scoped Topology
def a (x y : ℤ) (n : ℕ) : ℤ :=
  (x^n + y).gcd ((y - x) * (∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ) - 1))
def satisfyingPairs : Set (ℤ × ℤ) := {
  (x, y) | (x : ℤ) (_ : 0 < x) (y : ℤ) (_ : 0 < y) (l : ℝ)
  (_ : Filter.atTop.Tendsto (fun n ↦ (a x y n : ℝ)) (𝓝 l))
}

theorem lem_eventually_const_val {x y : ℤ} (h : (x, y) ∈ satisfyingPairs) :
  ∃ (c N : ℕ), ∀ n ≥ N, Int.gcd (x ^ n + y) (y ^ n + x) = c :=
by
  -- Extract variables but don't use `subst` to avoid wiping out parameters `x` and `y`.
  obtain ⟨x1, hx_pos, y1, hy_pos, l, hl_tendsto, heq⟩ := h
  have hx : x1 = x := congrArg Prod.fst heq
  have hy : y1 = y := congrArg Prod.snd heq
  -- Safe rewrite in the necessary hypothesis
  rw [hx, hy] at hl_tendsto

  have H_diff : ∀ n : ℕ, y^n - x^n = (y - x) * ∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ) := by
    intro n
    induction' n with n ih
    · rw [Finset.sum_range_zero]
      ring
    · have h_eq : (∑ i ∈ Finset.range (n + 1), y^i * x^(n + 1 - i - 1 : ℕ)) = ∑ i ∈ Finset.range (n + 1), y^i * x^(n - i : ℕ) := by
        apply Finset.sum_congr rfl
        intro i hi
        rw [Finset.mem_range] at hi
        have h_exp : (n + 1 - i - 1 : ℕ) = (n - i : ℕ) := by omega
        have h_pow_eq : x^(n + 1 - i - 1 : ℕ) = x^(n - i : ℕ) := congrArg (fun (e : ℕ) => x^e) h_exp
        rw [h_pow_eq]

      have h_eq2 : (∑ i ∈ Finset.range n, y^i * x^(n - i : ℕ)) = (∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ)) * x := by
        rw [Finset.sum_mul]
        apply Finset.sum_congr rfl
        intro i hi
        rw [Finset.mem_range] at hi
        have h_pow : x^(n - i : ℕ) = x^(n - i - 1 : ℕ) * x := by
          have h_exp : (n - i : ℕ) = (n - i - 1) + 1 := by omega
          have h_pow_eq_aux : x^(n - i : ℕ) = x^((n - i - 1) + 1 : ℕ) := congrArg (fun (e : ℕ) => x^e) h_exp
          rw [h_pow_eq_aux, pow_add, pow_one]
        rw [h_pow]
        ring

      have H_sum : (∑ i ∈ Finset.range (n + 1), y^i * x^(n + 1 - i - 1 : ℕ)) = (∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ)) * x + y^n := by
        rw [h_eq, Finset.sum_range_succ, h_eq2]
        have h_last : y^n * x^(n - n : ℕ) = y^n := by
          have hz : (n - n : ℕ) = 0 := by omega
          have h_eq_zero : x^(n - n : ℕ) = x^0 := congrArg (fun (e : ℕ) => x^e) hz
          rw [h_eq_zero, pow_zero, mul_one]
        rw [h_last]

      calc y^(n + 1) - x^(n + 1)
        _ = y^n * y - x^n * x := by
          have hy1 : y^(n + 1) = y^n * y := by rw [pow_add, pow_one]
          have hx1 : x^(n + 1) = x^n * x := by rw [pow_add, pow_one]
          rw [hy1, hx1]
        _ = (y^n - x^n) * x + (y - x) * y^n := by ring
        _ = ((y - x) * ∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ)) * x + (y - x) * y^n := by rw [ih]
        _ = (y - x) * ((∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ)) * x + y^n) := by ring
        _ = (y - x) * (∑ i ∈ Finset.range (n + 1), y^i * x^(n + 1 - i - 1 : ℕ)) := by rw [← H_sum]

  have H_eq : ∀ n : ℕ, y^n + x = x^n + y + (y - x) * (∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ) - 1) := by
    intro n
    calc y^n + x = (y^n - x^n) + x^n + x := by ring
      _ = (y - x) * (∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ)) + x^n + x := by rw [H_diff n]
      _ = x^n + y + (y - x) * (∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ) - 1) := by ring

  have H_gcd : ∀ n : ℕ, Int.gcd (x^n + y) (y^n + x) = Int.gcd (x^n + y) ((y - x) * (∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ) - 1)) := by
    intro n
    let A := x^n + y
    let B := y^n + x
    let C := (y - x) * (∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ) - 1)
    have HC : B = A + C := H_eq n
    let G1 := Int.gcd A B
    let G2 := Int.gcd A C

    have hdvd1 : (G1 : ℤ) ∣ A := Int.gcd_dvd_left A B
    have hdvd2 : (G1 : ℤ) ∣ B := Int.gcd_dvd_right A B
    have hdvd3 : (G1 : ℤ) ∣ C := by
      have hd_C : C = B - A := by omega
      rw [hd_C]
      exact dvd_sub hdvd2 hdvd1

    have hdvd4 : (G2 : ℤ) ∣ A := Int.gcd_dvd_left A C
    have hdvd5 : (G2 : ℤ) ∣ C := Int.gcd_dvd_right A C
    have hdvd6 : (G2 : ℤ) ∣ B := by
      have hd_B : B = A + C := HC
      rw [hd_B]
      exact dvd_add hdvd4 hdvd5

    have hd1 : G1 ∣ G2 := Int.dvd_gcd hdvd1 hdvd3
    have hd2 : G2 ∣ G1 := Int.dvd_gcd hdvd4 hdvd6
    exact Nat.dvd_antisymm hd1 hd2

  have H_a : ∀ n : ℕ, a x y n = (Int.gcd (x^n + y) (y^n + x) : ℤ) := by
    intro n
    have h_def : a x y n = (Int.gcd (x^n + y) ((y - x) * (∑ i ∈ Finset.range n, y^i * x^(n - i - 1 : ℕ) - 1)) : ℤ) := rfl
    have h_gcd_n := H_gcd n
    rw [← h_gcd_n] at h_def
    exact h_def

  have h_cauchy : CauchySeq (fun n ↦ (a x y n : ℝ)) := hl_tendsto.cauchySeq
  rw [Metric.cauchySeq_iff] at h_cauchy
  obtain ⟨N, hN⟩ := h_cauchy ((1 : ℝ) / 2) (by norm_num)

  have h_eq_const : ∀ n ≥ N, a x y n = a x y N := by
    intro n hn
    have h_dist := hN n hn N (le_refl N)
    have h_lt : (|(a x y n - a x y N : ℤ)| : ℝ) < 1 := by
      calc (|(a x y n - a x y N : ℤ)| : ℝ) = |(a x y n : ℝ) - (a x y N : ℝ)| := by push_cast; rfl
        _ = ‖(a x y n : ℝ) - (a x y N : ℝ)‖ := by exact (Real.norm_eq_abs _).symm
        _ = dist (a x y n : ℝ) (a x y N : ℝ) := (dist_eq_norm _ _).symm
        _ < ((1 : ℝ) / 2) := h_dist
        _ < 1 := by norm_num
    have h_diff_int : |a x y n - a x y N| < 1 := by exact_mod_cast h_lt
    rw [Int.abs_lt_one_iff] at h_diff_int
    omega

  use Int.gcd (x^N + y) (y^N + x), N
  intro n hn
  have han_eq : (Int.gcd (x^n + y) (y^n + x) : ℤ) = (Int.gcd (x^N + y) (y^N + x) : ℤ) := by
    calc (Int.gcd (x^n + y) (y^n + x) : ℤ) = a x y n := (H_a n).symm
      _ = a x y N := h_eq_const n hn
      _ = (Int.gcd (x^N + y) (y^N + x) : ℤ) := H_a N
  exact_mod_cast han_eq

theorem lem_xy_ge_two_of_satisfying {x y : ℤ} (hx : x ≠ 1) (hy : y ≠ 1) (h : (x, y) ∈ satisfyingPairs) : x ≥ 2 ∧ y ≥ 2 :=
by
  -- Extract the positivity conditions from the definition of satisfyingPairs
  have h_pos : 0 < x ∧ 0 < y := by
    unfold satisfyingPairs at h
    try simp only [Set.mem_setOf_eq] at h
    aesop

  -- Destruct the extracted conjunction
  obtain ⟨hx_pos, hy_pos⟩ := h_pos

  -- Split the goal into two subgoals for x and y
  constructor
  · -- Since x > 0 and x is an integer, x >= 1. Combined with x ≠ 1, x >= 2.
    omega
  · -- Since y > 0 and y is an integer, y >= 1. Combined with y ≠ 1, y >= 2.
    omega

theorem lem_cross_div {x y : ℤ} {c N : ℕ}
  (hx : x ≥ 2) (hy : y ≥ 2)
  (hc : ∀ n ≥ N, Int.gcd (x ^ n + y) (y ^ n + x) = c)
  {p : ℕ} (hp : Nat.Prime p) (hdiv : (p : ℤ) ∣ x * y + 1) :
  (p : ℤ) ∣ y * (x - 1) ∧ (p : ℤ) ∣ x * (y - 1) :=
by
  have hN_sub : N + 1 ≥ 1 := by omega
  have hp_sub : p - 1 ≥ 1 := by
    have : p ≥ 2 := Nat.Prime.two_le hp
    omega

  have hpx : ¬ ((p : ℤ) ∣ x) := by
    intro h
    have hdvd : (p : ℤ) ∣ x * y := dvd_mul_of_dvd_left h y
    have h1 : (p : ℤ) ∣ 1 := by
      have e : (1 : ℤ) = (x * y + 1) - x * y := by ring
      rw [e]
      exact dvd_sub hdiv hdvd
    have h1_nat : p ∣ 1 := Int.natCast_dvd.mp h1
    have hp1 : p = 1 := Nat.dvd_one.mp h1_nat
    have hp2 : p ≥ 2 := Nat.Prime.two_le hp
    omega

  have hpy : ¬ ((p : ℤ) ∣ y) := by
    intro h
    have hdvd : (p : ℤ) ∣ x * y := by
      have e : x * y = y * x := by ring
      rw [e]
      exact dvd_mul_of_dvd_left h x
    have h1 : (p : ℤ) ∣ 1 := by
      have e : (1 : ℤ) = (x * y + 1) - x * y := by ring
      rw [e]
      exact dvd_sub hdiv hdvd
    have h1_nat : p ∣ 1 := Int.natCast_dvd.mp h1
    have hp1 : p = 1 := Nat.dvd_one.mp h1_nat
    have hp2 : p ≥ 2 := Nat.Prime.two_le hp
    omega

  -- Robust fallback for Euclid's lemma over integers
  have int_prime_dvd_mul : ∀ (A B : ℤ), (p : ℤ) ∣ A * B → (p : ℤ) ∣ A ∨ (p : ℤ) ∣ B := by
    intro A B h
    have h1 : p ∣ (A * B).natAbs := Int.natCast_dvd.mp h
    have h2 : (A * B).natAbs = A.natAbs * B.natAbs := Int.natAbs_mul A B
    rw [h2] at h1
    have h3 : p ∣ A.natAbs ∨ p ∣ B.natAbs := hp.dvd_mul.mp h1
    rcases h3 with hA | hB
    · left; exact Int.natCast_dvd.mpr hA
    · right; exact Int.natCast_dvd.mpr hB

  have H_pow_sub : ∀ (k : ℕ) (A B : ℤ), (A - B) ∣ A^k - B^k := by
    intro k A B
    induction k with
    | zero =>
      have e : A^0 - B^0 = 0 := by ring
      rw [e]
      exact dvd_zero (A - B)
    | succ k ih =>
      have e : A^(k+1) - B^(k+1) = (A^k - B^k) * A + B^k * (A - B) := by
        have eA : A^(k+1) = A^k * A := by rw [pow_add, pow_one]
        have eB : B^(k+1) = B^k * B := by rw [pow_add, pow_one]
        rw [eA, eB]
        ring
      rw [e]
      apply dvd_add
      · exact dvd_mul_of_dvd_left ih A
      · have e2 : B^k * (A - B) = (A - B) * B^k := by ring
        rw [e2]
        exact dvd_mul_of_dvd_left (dvd_refl (A - B)) (B^k)

  have H_mod_x : (p : ℤ) ∣ x^(p-1) - 1 := by
    have H1 : x^p - x = x * (x^(p-1) - 1) := by
      have hp_pos : p - 1 + 1 = p := by omega
      calc x^p - x = x^(p - 1 + 1) - x := by rw [hp_pos]
        _ = x^(p-1) * x^1 - x := by rw [pow_add]
        _ = x^(p-1) * x - x := by rw [pow_one]
        _ = x * (x^(p-1) - 1) := by ring
    have H2 : (p : ℤ) ∣ x^p - x := Int.ModEq.dvd (Int.ModEq.symm (Int.ModEq.pow_prime_eq_self hp x))
    rw [H1] at H2
    rcases int_prime_dvd_mul x (x^(p-1) - 1) H2 with h_div_x | h_div_x_pow
    · exact False.elim (hpx h_div_x)
    · exact h_div_x_pow

  let K := (N + 1) * (p - 1)
  have hK : K ≥ 1 := by apply Nat.mul_pos hN_sub hp_sub

  let n := 2 * K - 1

  have h_n_add : n + 1 = 2 * K := by
    have hn : n = 2 * K - 1 := rfl
    omega

  have h_n_ge : n ≥ N := by
    have h1 : p - 1 ≥ 1 := hp_sub
    have h2 : N + 1 ≤ K := by
      have e : N + 1 = (N + 1) * 1 := by omega
      rw [e]
      exact Nat.mul_le_mul_left (N + 1) h1
    have hn : n = 2 * K - 1 := rfl
    omega

  have h_mod3 : (p : ℤ) ∣ x^(n + 1) - 1 := by
    have h_step : x^(p-1) - 1 ∣ (x^(p-1))^(2 * (N + 1)) - 1^(2 * (N + 1)) := H_pow_sub (2 * (N + 1)) (x^(p-1)) 1
    have e1 : (x^(p-1))^(2 * (N + 1)) = x^((p-1) * (2 * (N + 1))) := by rw [←pow_mul]
    have e2 : (p - 1) * (2 * (N + 1)) = 2 * K := by
      have e_K : K = (N + 1) * (p - 1) := rfl
      rw [e_K]
      ring
    have e3 : (1 : ℤ)^(2 * (N + 1)) = 1 := one_pow _
    rw [e2] at e1
    rw [e1, e3] at h_step
    have hn_eq : 2 * K = n + 1 := by
      have hn : n = 2 * K - 1 := rfl
      omega
    rw [hn_eq] at h_step
    exact dvd_trans H_mod_x h_step

  have H3 : (p : ℤ) ∣ x * (x^n + y) := by
    have eq1 : x * (x^n + y) = (x^(n+1) - 1) + (x * y + 1) := by
      have e2 : x * x^n = x^(n+1) := by
        rw [pow_add, pow_one]
        ring
      calc x * (x^n + y) = x * x^n + x * y := by ring
        _ = x^(n+1) + x * y := by rw [e2]
        _ = (x^(n+1) - 1) + (x * y + 1) := by ring
    rw [eq1]
    exact dvd_add h_mod3 hdiv

  have H4 : (p : ℤ) ∣ x^n + y := by
    rcases int_prime_dvd_mul x (x^n + y) H3 with h_div_x | h_div_xny
    · exact False.elim (hpx h_div_x)
    · exact h_div_xny

  have h_neg1_pow : (-1 : ℤ)^n = -1 := by
    obtain ⟨M, hM⟩ : ∃ M : ℕ, n = 2 * M + 1 := by
      use K - 1
      have hn : n = 2 * K - 1 := rfl
      omega
    rw [hM]
    have e1 : (-1 : ℤ) ^ (2 * M + 1) = (-1 : ℤ) ^ (2 * M) * (-1 : ℤ) := by rw [pow_add, pow_one]
    have e2 : (-1 : ℤ) ^ (2 * M) = ((-1 : ℤ) ^ 2) ^ M := by rw [pow_mul]
    have e3 : (-1 : ℤ) ^ 2 = 1 := by norm_num
    rw [e1, e2, e3]
    have e4 : (1 : ℤ) ^ M = 1 := one_pow M
    rw [e4]
    ring

  have h_xyn : (p : ℤ) ∣ (x * y)^n - (-1 : ℤ)^n := by
    have h_base : (p : ℤ) ∣ x * y - (-1 : ℤ) := by
      have e : x * y - (-1 : ℤ) = x * y + 1 := by ring
      rw [e]
      exact hdiv
    have h_step : x * y - (-1 : ℤ) ∣ (x * y)^n - (-1 : ℤ)^n := H_pow_sub n (x * y) (-1)
    exact dvd_trans h_base h_step

  have H_xyn2 : (p : ℤ) ∣ (x * y)^n + 1 := by
    have e : (x * y)^n - (-1 : ℤ)^n = (x * y)^n + 1 := by
      rw [h_neg1_pow]
      ring
    rw [←e]
    exact h_xyn

  have H5 : (p : ℤ) ∣ x^n * (y^n + x) := by
    have eq2 : x^n * (y^n + x) = ((x * y)^n + 1) + (x^(n+1) - 1) := by
      have e2 : x^n * x = x^(n+1) := by rw [pow_add, pow_one]
      have e3 : x^n * y^n = (x * y)^n := by rw [←mul_pow]
      calc x^n * (y^n + x) = x^n * y^n + x^n * x := by ring
        _ = (x * y)^n + x^(n+1) := by rw [e3, e2]
        _ = ((x * y)^n + 1) + (x^(n+1) - 1) := by ring
    rw [eq2]
    exact dvd_add H_xyn2 h_mod3

  have H6 : (p : ℤ) ∣ y^n + x := by
    rcases int_prime_dvd_mul (x^n) (y^n + x) H5 with h_div_xn | h_div_ynx
    · have h_div_y : (p : ℤ) ∣ y := by
        have e : y = (x^n + y) - x^n := by ring
        rw [e]
        exact dvd_sub H4 h_div_xn
      exact False.elim (hpy h_div_y)
    · exact h_div_ynx

  have H7 : (p : ℤ) ∣ (c : ℤ) := by
    have h_gcd_nat : p ∣ Int.gcd (x^n + y) (y^n + x) := Int.dvd_gcd H4 H6
    have h_hc : Int.gcd (x^n + y) (y^n + x) = c := hc n h_n_ge
    rw [h_hc] at h_gcd_nat
    have h_gcd_nat2 : p ∣ (c : ℤ).natAbs := h_gcd_nat
    exact Int.natCast_dvd.mpr h_gcd_nat2

  have h_c_dvd_x (m : ℕ) (hm : m ≥ N) : (c : ℤ) ∣ x^m + y := by
    have h_hc : Int.gcd (x^m + y) (y^m + x) = c := hc m hm
    have h_dvd : ((Int.gcd (x^m + y) (y^m + x) : ℕ) : ℤ) ∣ x^m + y := Int.gcd_dvd_left (x^m + y) (y^m + x)
    have h_hc_int : ((Int.gcd (x^m + y) (y^m + x) : ℕ) : ℤ) = (c : ℤ) := by rw [h_hc]
    rw [h_hc_int] at h_dvd
    exact h_dvd

  have h_p_dvd_x (m : ℕ) (hm : m ≥ N) : (p : ℤ) ∣ x^m + y :=
    dvd_trans H7 (h_c_dvd_x m hm)

  have h_c_dvd_y (m : ℕ) (hm : m ≥ N) : (c : ℤ) ∣ y^m + x := by
    have h_hc : Int.gcd (x^m + y) (y^m + x) = c := hc m hm
    have h_dvd : ((Int.gcd (x^m + y) (y^m + x) : ℕ) : ℤ) ∣ y^m + x := Int.gcd_dvd_right (x^m + y) (y^m + x)
    have h_hc_int : ((Int.gcd (x^m + y) (y^m + x) : ℕ) : ℤ) = (c : ℤ) := by rw [h_hc]
    rw [h_hc_int] at h_dvd
    exact h_dvd

  have h_p_dvd_y (m : ℕ) (hm : m ≥ N) : (p : ℤ) ∣ y^m + x :=
    dvd_trans H7 (h_c_dvd_y m hm)

  have h_pN1_x : (p : ℤ) ∣ x^(N+1) + y := h_p_dvd_x (N+1) (by omega)
  have h_pN_x : (p : ℤ) ∣ x^N + y := h_p_dvd_x N (by omega)

  have h_sub_x : (p : ℤ) ∣ x^(N+1) - x^N := by
    have e : x^(N+1) - x^N = (x^(N+1) + y) - (x^N + y) := by ring
    rw [e]
    exact dvd_sub h_pN1_x h_pN_x

  have h_sub_x2 : (p : ℤ) ∣ x^N * (x - 1) := by
    have e : x^(N+1) - x^N = x^N * (x - 1) := by
      have eA : x^(N+1) = x^N * x := by rw [pow_add, pow_one]
      rw [eA]
      ring
    rw [←e]
    exact h_sub_x

  have h_p_x_1 : (p : ℤ) ∣ x - 1 := by
    rcases int_prime_dvd_mul (x^N) (x - 1) h_sub_x2 with h_div_xN | h_div_x1
    · have h_div_y : (p : ℤ) ∣ y := by
        have e : y = (x^N + y) - x^N := by ring
        rw [e]
        exact dvd_sub h_pN_x h_div_xN
      exact False.elim (hpy h_div_y)
    · exact h_div_x1

  have h_pN1_y : (p : ℤ) ∣ y^(N+1) + x := h_p_dvd_y (N+1) (by omega)
  have h_pN_y : (p : ℤ) ∣ y^N + x := h_p_dvd_y N (by omega)

  have h_sub_y : (p : ℤ) ∣ y^(N+1) - y^N := by
    have e : y^(N+1) - y^N = (y^(N+1) + x) - (y^N + x) := by ring
    rw [e]
    exact dvd_sub h_pN1_y h_pN_y

  have h_sub_y2 : (p : ℤ) ∣ y^N * (y - 1) := by
    have e : y^(N+1) - y^N = y^N * (y - 1) := by
      have eA : y^(N+1) = y^N * y := by rw [pow_add, pow_one]
      rw [eA]
      ring
    rw [←e]
    exact h_sub_y

  have h_p_y_1 : (p : ℤ) ∣ y - 1 := by
    rcases int_prime_dvd_mul (y^N) (y - 1) h_sub_y2 with h_div_yN | h_div_y1
    · have h_div_x : (p : ℤ) ∣ x := by
        have e : x = (y^N + x) - y^N := by ring
        rw [e]
        exact dvd_sub h_pN_y h_div_yN
      exact False.elim (hpx h_div_x)
    · exact h_div_y1

  constructor
  · have e : y * (x - 1) = (x - 1) * y := by ring
    rw [e]
    exact dvd_mul_of_dvd_left h_p_x_1 y
  · have e : x * (y - 1) = (y - 1) * x := by ring
    rw [e]
    exact dvd_mul_of_dvd_left h_p_y_1 x

theorem lem_prime_dvd_two_of_dvd_xy {p : ℕ} {x y : ℤ}
  (h1 : (p : ℤ) ∣ x * y + 1)
  (h2 : (p : ℤ) ∣ y * (x - 1))
  (h3 : (p : ℤ) ∣ x * (y - 1)) :
  (p : ℤ) ∣ (2 : ℤ) :=
by
  obtain ⟨k1, hk1⟩ := h1
  obtain ⟨k2, hk2⟩ := h2
  obtain ⟨k3, hk3⟩ := h3
  use 3 * k1 - k2 - k3 - (p : ℤ) * k1^2 + (p : ℤ) * k1 * k2 + (p : ℤ) * k1 * k3 - (p : ℤ) * k2 * k3
  calc
    (2 : ℤ) = 3 * (x * y + 1) - y * (x - 1) - x * (y - 1) - (x * y + 1)^2 + (x * y + 1) * (y * (x - 1)) + (x * y + 1) * (x * (y - 1)) - (y * (x - 1)) * (x * (y - 1)) := by ring
    _ = 3 * ((p : ℤ) * k1) - ((p : ℤ) * k2) - ((p : ℤ) * k3) - ((p : ℤ) * k1)^2 + ((p : ℤ) * k1) * ((p : ℤ) * k2) + ((p : ℤ) * k1) * ((p : ℤ) * k3) - ((p : ℤ) * k2) * ((p : ℤ) * k3) := by rw [hk1, hk2, hk3]
    _ = (p : ℤ) * (3 * k1 - k2 - k3 - (p : ℤ) * k1^2 + (p : ℤ) * k1 * k2 + (p : ℤ) * k1 * k3 - (p : ℤ) * k2 * k3) := by ring

theorem lem_prime_eq_two_of_dvd_two {p : ℕ} (hp : Nat.Prime p) (h : (p : ℤ) ∣ (2 : ℤ)) : p = 2 :=
by
  have h_nat : p ∣ 2 := by exact_mod_cast h
  obtain ⟨k, hk⟩ := h_nat
  have hp2 : 2 ≤ p := hp.two_le
  have h_cases : k = 0 ∨ 1 ≤ k := by omega
  rcases h_cases with rfl | hk_one
  · omega
  · have h1 : (1 : ℤ) ≤ (k : ℤ) := by exact_mod_cast hk_one
    have h2 : (2 : ℤ) ≤ (p : ℤ) := by exact_mod_cast hp2
    have h3 : (2 : ℤ) = (p : ℤ) * (k : ℤ) := by exact_mod_cast hk
    have hp_eq : (p : ℤ) = 2 := by nlinarith
    exact_mod_cast hp_eq

theorem lem_prime_dvd_implies_two {x y : ℤ} {c N : ℕ}
  (hx : x ≥ 2) (hy : y ≥ 2)
  (hc : ∀ n ≥ N, Int.gcd (x ^ n + y) (y ^ n + x) = c)
  {p : ℕ} (hp : Nat.Prime p) (hdiv : (p : ℤ) ∣ x * y + 1) : p = 2 :=
by
  have ⟨h2, h3⟩ := lem_cross_div hx hy hc hp hdiv
  have h_two := lem_prime_dvd_two_of_dvd_xy hdiv h2 h3
  exact lem_prime_eq_two_of_dvd_two hp h_two

theorem lem_int_four_dvd_of_only_two_prime_factor {M : ℤ} (hM : M ≥ 5)
  (hp : ∀ p : ℕ, p.Prime → (p : ℤ) ∣ M → p = 2) : (4 : ℤ) ∣ M :=
by
  have h_gt : 2 < M.natAbs := by omega
  rcases Nat.four_dvd_or_exists_odd_prime_and_dvd_of_two_lt h_gt with h4 | ⟨p, hp_prime, hp_dvd, hp_odd⟩
  · obtain ⟨k, hk⟩ := h4
    use (k : ℤ)
    have h1 : M = (M.natAbs : ℤ) := by omega
    rw [h1, hk]
    push_cast
    rfl
  · have h_p_dvd_M : (p : ℤ) ∣ M := by
      obtain ⟨k, hk⟩ := hp_dvd
      use (k : ℤ)
      have h1 : M = (M.natAbs : ℤ) := by omega
      rw [h1, hk]
      push_cast
      rfl
    have hp2 : p = 2 := hp p hp_prime h_p_dvd_M
    rcases hp2 with rfl
    rcases hp_odd with ⟨k, hk⟩
    omega

theorem lem_four_dvd_xy_add_one {x y : ℤ} {c N : ℕ}
  (hx : x ≥ 2) (hy : y ≥ 2)
  (hc : ∀ n ≥ N, Int.gcd (x ^ n + y) (y ^ n + x) = c) :
  (4 : ℤ) ∣ (x * y + 1) :=
by
  have hM : x * y + 1 ≥ 5 := by nlinarith
  apply lem_int_four_dvd_of_only_two_prime_factor hM
  intro p hp hdiv
  exact lem_prime_dvd_implies_two hx hy hc hp hdiv

theorem lem_mod_four_of_four_dvd {x y : ℤ} (h : (4 : ℤ) ∣ (x * y + 1)) :
  (x % 4 = 1 ∧ y % 4 = 3) ∨ (x % 4 = 3 ∧ y % 4 = 1) :=
by
  obtain ⟨k, hk⟩ := h
  have Hx : x = 4 * (x / 4) + x % 4 := by omega
  have Hy : y = 4 * (y / 4) + y % 4 := by omega

  have H : (x % 4) * (y % 4) + 1 = 4 * (k - 4 * (x / 4) * (y / 4) - (x % 4) * (y / 4) - (y % 4) * (x / 4)) := by
    calc
      (x % 4) * (y % 4) + 1
        = (4 * (x / 4) + x % 4) * (4 * (y / 4) + y % 4) + 1 - 4 * (4 * (x / 4) * (y / 4) + (x % 4) * (y / 4) + (y % 4) * (x / 4)) := by ring
      _ = x * y + 1 - 4 * (4 * (x / 4) * (y / 4) + (x % 4) * (y / 4) + (y % 4) * (x / 4)) := by rw [← Hx, ← Hy]
      _ = 4 * k - 4 * (4 * (x / 4) * (y / 4) + (x % 4) * (y / 4) + (y % 4) * (x / 4)) := by rw [hk]
      _ = 4 * (k - 4 * (x / 4) * (y / 4) - (x % 4) * (y / 4) - (y % 4) * (x / 4)) := by ring

  have H2 : ∃ M : ℤ, (x % 4) * (y % 4) + 1 = 4 * M := ⟨_, H⟩
  obtain ⟨M, hM⟩ := H2

  have cases_x : x % 4 = 0 ∨ x % 4 = 1 ∨ x % 4 = 2 ∨ x % 4 = 3 := by omega
  have cases_y : y % 4 = 0 ∨ y % 4 = 1 ∨ y % 4 = 2 ∨ y % 4 = 3 := by omega

  rcases cases_x with hx0 | hx1 | hx2 | hx3
  · rcases cases_y with hy0 | hy1 | hy2 | hy3
    · rw [hx0, hy0] at hM; omega
    · rw [hx0, hy1] at hM; omega
    · rw [hx0, hy2] at hM; omega
    · rw [hx0, hy3] at hM; omega
  · rcases cases_y with hy0 | hy1 | hy2 | hy3
    · rw [hx1, hy0] at hM; omega
    · rw [hx1, hy1] at hM; omega
    · rw [hx1, hy2] at hM; omega
    · left; exact ⟨hx1, hy3⟩
  · rcases cases_y with hy0 | hy1 | hy2 | hy3
    · rw [hx2, hy0] at hM; omega
    · rw [hx2, hy1] at hM; omega
    · rw [hx2, hy2] at hM; omega
    · rw [hx2, hy3] at hM; omega
  · rcases cases_y with hy0 | hy1 | hy2 | hy3
    · rw [hx3, hy0] at hM; omega
    · right; exact ⟨hx3, hy1⟩
    · rw [hx3, hy2] at hM; omega
    · rw [hx3, hy3] at hM; omega

theorem lem_c_mod_four {x y : ℤ} {c N : ℕ}
  (hc : ∀ n ≥ N, Int.gcd (x ^ n + y) (y ^ n + x) = c)
  (hmod : (x % 4 = 1 ∧ y % 4 = 3) ∨ (x % 4 = 3 ∧ y % 4 = 1)) :
  False :=
by
  rcases hmod with ⟨hx, hy⟩ | ⟨hx, hy⟩
  · have hx_mod : Int.ModEq 4 x 1 := by
      change x % 4 = (1 : ℤ) % 4
      have : (1 : ℤ) % 4 = 1 := by norm_num
      rw [this]
      exact hx
    have hy_mod : Int.ModEq 4 y (-1) := by
      change y % 4 = (-1 : ℤ) % 4
      have : (-1 : ℤ) % 4 = 3 := by norm_num
      rw [this]
      exact hy
    have h_neg1_even : (-1 : ℤ) ^ (2 * N) = 1 := by
      have : (-1 : ℤ) ^ (2 * N) = ((-1 : ℤ) ^ 2) ^ N := by rw [pow_mul]
      rw [this]
      have h_sq : (-1 : ℤ) ^ 2 = 1 := by norm_num
      rw [h_sq]
      exact one_pow N
    have h_neg1_odd : (-1 : ℤ) ^ (2 * N + 1) = -1 := by
      have : (-1 : ℤ) ^ (2 * N + 1) = (-1 : ℤ) ^ (2 * N) * (-1 : ℤ) := by
        rw [pow_add, pow_one]
      rw [this, h_neg1_even]
      ring

    have H_odd_A : Int.ModEq 4 (x ^ (2 * N + 1) + y) 0 := by
      have h1 := Int.ModEq.pow (2 * N + 1) hx_mod
      have h2 : (1 : ℤ) ^ (2 * N + 1) = 1 := one_pow (2 * N + 1)
      rw [h2] at h1
      have h_add := Int.ModEq.add h1 hy_mod
      have h_simp : (1 : ℤ) + (-1) = 0 := by norm_num
      rw [h_simp] at h_add
      exact h_add
    have H_odd_B : Int.ModEq 4 (y ^ (2 * N + 1) + x) 0 := by
      have h1 := Int.ModEq.pow (2 * N + 1) hy_mod
      rw [h_neg1_odd] at h1
      have h_add := Int.ModEq.add h1 hx_mod
      have h_simp : (-1 : ℤ) + 1 = 0 := by norm_num
      rw [h_simp] at h_add
      exact h_add

    have h4A : (4 : ℤ) ∣ x ^ (2 * N + 1) + y := by
      have h := H_odd_A
      change (x ^ (2 * N + 1) + y) % 4 = (0 : ℤ) % 4 at h
      have : (0 : ℤ) % 4 = 0 := by norm_num
      rw [this] at h
      exact ⟨(x ^ (2 * N + 1) + y) / 4, by omega⟩

    have h4B : (4 : ℤ) ∣ y ^ (2 * N + 1) + x := by
      have h := H_odd_B
      change (y ^ (2 * N + 1) + x) % 4 = (0 : ℤ) % 4 at h
      have : (0 : ℤ) % 4 = 0 := by norm_num
      rw [this] at h
      exact ⟨(y ^ (2 * N + 1) + x) / 4, by omega⟩

    have h_gcd := Int.dvd_gcd h4A h4B
    have heq1 : Int.gcd (x ^ (2 * N + 1) + y) (y ^ (2 * N + 1) + x) = c := hc (2 * N + 1) (by omega)
    rw [heq1] at h_gcd
    rcases h_gcd with ⟨k, hk⟩

    -- Cast natural number divisibility relations into integers
    have hk_int : (c : ℤ) = 4 * (k : ℤ) := by exact_mod_cast hk

    have H_even_B : Int.ModEq 4 (y ^ (2 * N) + x) 2 := by
      have h1 := Int.ModEq.pow (2 * N) hy_mod
      rw [h_neg1_even] at h1
      have h_add := Int.ModEq.add h1 hx_mod
      have h_simp : (1 : ℤ) + 1 = 2 := by norm_num
      rw [h_simp] at h_add
      exact h_add

    have hc_dvd_B : (c : ℤ) ∣ y ^ (2 * N) + x := by
      have h := Int.gcd_dvd_right (x ^ (2 * N) + y) (y ^ (2 * N) + x)
      have heq2 : Int.gcd (x ^ (2 * N) + y) (y ^ (2 * N) + x) = c := hc (2 * N) (by omega)
      rw [heq2] at h
      exact h

    rcases hc_dvd_B with ⟨m, hm⟩
    have h_contradiction : (y ^ (2 * N) + x) % 4 = 0 := by
      rw [hm, hk_int]
      have h_eq : (4 : ℤ) * (k : ℤ) * m = 4 * ((k : ℤ) * m) := by ring
      rw [h_eq]
      omega

    have h_mod2 : (y ^ (2 * N) + x) % 4 = 2 := by
      have h := H_even_B
      change (y ^ (2 * N) + x) % 4 = (2 : ℤ) % 4 at h
      have : (2 : ℤ) % 4 = 2 := by norm_num
      rw [this] at h
      exact h

    omega
  · have hx_mod : Int.ModEq 4 x (-1) := by
      change x % 4 = (-1 : ℤ) % 4
      have : (-1 : ℤ) % 4 = 3 := by norm_num
      rw [this]
      exact hx
    have hy_mod : Int.ModEq 4 y 1 := by
      change y % 4 = (1 : ℤ) % 4
      have : (1 : ℤ) % 4 = 1 := by norm_num
      rw [this]
      exact hy
    have h_neg1_even : (-1 : ℤ) ^ (2 * N) = 1 := by
      have : (-1 : ℤ) ^ (2 * N) = ((-1 : ℤ) ^ 2) ^ N := by rw [pow_mul]
      rw [this]
      have h_sq : (-1 : ℤ) ^ 2 = 1 := by norm_num
      rw [h_sq]
      exact one_pow N
    have h_neg1_odd : (-1 : ℤ) ^ (2 * N + 1) = -1 := by
      have : (-1 : ℤ) ^ (2 * N + 1) = (-1 : ℤ) ^ (2 * N) * (-1 : ℤ) := by
        rw [pow_add, pow_one]
      rw [this, h_neg1_even]
      ring

    have H_odd_A : Int.ModEq 4 (x ^ (2 * N + 1) + y) 0 := by
      have h1 := Int.ModEq.pow (2 * N + 1) hx_mod
      rw [h_neg1_odd] at h1
      have h_add := Int.ModEq.add h1 hy_mod
      have h_simp : (-1 : ℤ) + 1 = 0 := by norm_num
      rw [h_simp] at h_add
      exact h_add
    have H_odd_B : Int.ModEq 4 (y ^ (2 * N + 1) + x) 0 := by
      have h1 := Int.ModEq.pow (2 * N + 1) hy_mod
      have h2 : (1 : ℤ) ^ (2 * N + 1) = 1 := one_pow (2 * N + 1)
      rw [h2] at h1
      have h_add := Int.ModEq.add h1 hx_mod
      have h_simp : (1 : ℤ) + (-1) = 0 := by norm_num
      rw [h_simp] at h_add
      exact h_add

    have h4A : (4 : ℤ) ∣ x ^ (2 * N + 1) + y := by
      have h := H_odd_A
      change (x ^ (2 * N + 1) + y) % 4 = (0 : ℤ) % 4 at h
      have : (0 : ℤ) % 4 = 0 := by norm_num
      rw [this] at h
      exact ⟨(x ^ (2 * N + 1) + y) / 4, by omega⟩

    have h4B : (4 : ℤ) ∣ y ^ (2 * N + 1) + x := by
      have h := H_odd_B
      change (y ^ (2 * N + 1) + x) % 4 = (0 : ℤ) % 4 at h
      have : (0 : ℤ) % 4 = 0 := by norm_num
      rw [this] at h
      exact ⟨(y ^ (2 * N + 1) + x) / 4, by omega⟩

    have h_gcd := Int.dvd_gcd h4A h4B
    have heq1 : Int.gcd (x ^ (2 * N + 1) + y) (y ^ (2 * N + 1) + x) = c := hc (2 * N + 1) (by omega)
    rw [heq1] at h_gcd
    rcases h_gcd with ⟨k, hk⟩

    -- Cast natural number divisibility relations into integers
    have hk_int : (c : ℤ) = 4 * (k : ℤ) := by exact_mod_cast hk

    have H_even_A : Int.ModEq 4 (x ^ (2 * N) + y) 2 := by
      have h1 := Int.ModEq.pow (2 * N) hx_mod
      rw [h_neg1_even] at h1
      have h_add := Int.ModEq.add h1 hy_mod
      have h_simp : (1 : ℤ) + 1 = 2 := by norm_num
      rw [h_simp] at h_add
      exact h_add

    have hc_dvd_A : (c : ℤ) ∣ x ^ (2 * N) + y := by
      have h := Int.gcd_dvd_left (x ^ (2 * N) + y) (y ^ (2 * N) + x)
      have heq2 : Int.gcd (x ^ (2 * N) + y) (y ^ (2 * N) + x) = c := hc (2 * N) (by omega)
      rw [heq2] at h
      exact h

    rcases hc_dvd_A with ⟨m, hm⟩
    have h_contradiction : (x ^ (2 * N) + y) % 4 = 0 := by
      rw [hm, hk_int]
      have h_eq : (4 : ℤ) * (k : ℤ) * m = 4 * ((k : ℤ) * m) := by ring
      rw [h_eq]
      omega

    have h_mod2 : (x ^ (2 * N) + y) % 4 = 2 := by
      have h := H_even_A
      change (x ^ (2 * N) + y) % 4 = (2 : ℤ) % 4 at h
      have : (2 : ℤ) % 4 = 2 := by norm_num
      rw [this] at h
      exact h

    omega

theorem lem_no_solution_gt_one {x y : ℤ} (hx : x ≠ 1) (hy : y ≠ 1) (h : (x, y) ∈ satisfyingPairs) : False :=
by
  -- Obtain x ≥ 2 and y ≥ 2 from our helper lemma
  have ⟨hx2, hy2⟩ := lem_xy_ge_two_of_satisfying hx hy h

  -- Destruct to fetch variables using the uniquely named local helper lemma
  obtain ⟨c, N, hc⟩ := lem_eventually_const_val h

  -- Feed values directly to derive constraints
  have h4 := lem_four_dvd_xy_add_one hx2 hy2 hc
  have hmod := lem_mod_four_of_four_dvd h4

  -- Derive modular contradiction
  exact lem_c_mod_four hc hmod

theorem y_pos_of_mem_satisfyingPairs {x y : ℤ} (h : (x, y) ∈ satisfyingPairs) : y > 0 :=
by
  simp only [satisfyingPairs, Set.mem_setOf_eq] at h
  -- Extract all bounds and constraints generated by the set comprehension
  obtain ⟨x1, hx1, y1, hy1, l, hl, heq⟩ := h
  -- Unpack the equality of the pairs
  rw [Prod.mk_inj] at heq
  obtain ⟨hx, hy_eq⟩ := heq
  -- `omega` acts exactly like `linarith` but is explicitly designed for robust integer relations
  omega

theorem gcd_one_pow_add (y : ℤ) (n : ℕ) : Int.gcd ((1 : ℤ) ^ n + y) (y ^ n + 1) = Int.gcd (y + 1) (y ^ n + 1) :=
by
  have h : (1 : ℤ) ^ n + y = y + 1 := by
    rw [one_pow, add_comm]
  rw [h]

theorem y_add_one_dvd_odd (y : ℤ) (N : ℕ) : (y + 1) ∣ y ^ (2 * N + 1) + 1 :=
by
  have h : Odd (2 * N + 1) := ⟨N, rfl⟩
  have h_dvd := Odd.add_dvd_pow_add_pow y (1 : ℤ) h
  rw [one_pow] at h_dvd
  exact h_dvd

theorem y_add_one_dvd_even_sub_two (y : ℤ) (N : ℕ) : (y + 1) ∣ (y ^ (2 * N) + 1) - (2 : ℤ) :=
by
  have h_one : (-1 : ℤ) ^ (2 * N) = 1 := by
    rw [pow_mul]
    have : (-1 : ℤ) ^ 2 = 1 := by norm_num
    rw [this, one_pow]

  have h2 : y ^ (2 * N) + 1 - (2 : ℤ) = y ^ (2 * N) - (-1 : ℤ) ^ (2 * N) := by
    rw [h_one]
    ring

  have h3 : y + 1 = y - (-1 : ℤ) := by ring

  rw [h2, h3]
  exact sub_dvd_pow_sub_pow y (-1 : ℤ) (2 * N)

theorem gcd_eq_left_of_dvd {a b : ℤ} (h : a ∣ b) : Int.gcd a b = a.natAbs :=
by
  rcases h with ⟨c, rfl⟩
  rw [Int.gcd_def, Int.natAbs_mul]
  apply Nat.gcd_eq_left
  exact ⟨c.natAbs, rfl⟩

theorem gcd_eq_of_dvd_sub {a b c : ℤ} (h : a ∣ b - c) : Int.gcd a b = Int.gcd a c :=
by
  have H := gcd_eq_of_dvd_sub_right h
  change (Int.gcd a b : ℤ) = (Int.gcd a c : ℤ) at H
  exact_mod_cast H

theorem gcd_two_le (a : ℤ) : Int.gcd a (2 : ℤ) ≤ 2 :=
by
  have h_neq : (2 : ℤ) ≠ 0 := by decide
  have h_dvd : (Int.gcd a (2 : ℤ) : ℤ) ∣ (2 : ℤ) := Int.gcd_dvd_right a (2 : ℤ)
  have h_le := Int.le_abs_of_dvd h_neq h_dvd
  have h_abs : |(2 : ℤ)| = 2 := by norm_num
  rw [h_abs] at h_le
  omega

theorem lem_eventually_constant_1y {y : ℤ} (h : (1, y) ∈ satisfyingPairs) :
  ∃ c N : ℕ, ∀ n : ℕ, n ≥ N → Int.gcd ((1 : ℤ) ^ n + y) (y ^ n + 1) = c :=
by
  rcases h with ⟨x, hx, y_bind, hy, L, hL, heq⟩
  rcases heq with ⟨rfl, rfl⟩

  have ha_eq : ∀ m : ℕ, a 1 y m = (Int.gcd (1 + y) (y^m - y) : ℤ) := by
    intro m
    dsimp [a]
    simp only [one_pow, mul_one]
    have H2 : (y - 1) * ((∑ i ∈ Finset.range m, y^i) - 1) = y^m - y := by
      rw [mul_sub, mul_one]
      have H3 : ∀ k : ℕ, (y - 1) * ∑ i ∈ Finset.range k, y^i = y^k - 1 := by
        intro k
        induction k with
        | zero => simp
        | succ k ih =>
          rw [Finset.sum_range_succ, mul_add, ih, pow_succ]
          ring
      rw [H3 m]
      ring
    rw [H2]

  have h_eq : ∀ m : ℕ, Int.gcd (1 + y) (y^m + 1) = Int.gcd (1 + y) (y^m - y) := by
    intro m
    apply Nat.dvd_antisymm
    · have h1 : (Int.gcd (1 + y) (y^m + 1) : ℤ) ∣ 1 + y := Int.gcd_dvd_left _ _
      have h2 : (Int.gcd (1 + y) (y^m + 1) : ℤ) ∣ y^m + 1 := Int.gcd_dvd_right _ _
      have h3 : (Int.gcd (1 + y) (y^m + 1) : ℤ) ∣ y^m - y := by
        have : y^m - y = (y^m + 1) - (1 + y) := by ring
        rw [this]
        exact dvd_sub h2 h1
      have h4 := Int.dvd_gcd h1 h3
      exact_mod_cast h4
    · have h1 : (Int.gcd (1 + y) (y^m - y) : ℤ) ∣ 1 + y := Int.gcd_dvd_left _ _
      have h2 : (Int.gcd (1 + y) (y^m - y) : ℤ) ∣ y^m - y := Int.gcd_dvd_right _ _
      have h3 : (Int.gcd (1 + y) (y^m - y) : ℤ) ∣ y^m + 1 := by
        have : y^m + 1 = (y^m - y) + (1 + y) := by ring
        rw [this]
        exact dvd_add h2 h1
      have h4 := Int.dvd_gcd h1 h3
      exact_mod_cast h4

  have h_mem : Set.Ioo (L - (1 / 2 : ℝ)) (L + (1 / 2 : ℝ)) ∈ 𝓝 L := by
    apply Ioo_mem_nhds <;> linarith
  have h_eventually := Filter.Tendsto.eventually hL h_mem
  rcases Filter.eventually_atTop.mp h_eventually with ⟨N, hN⟩

  have h_const : ∀ n ≥ N, a 1 y n = a 1 y N := by
    intro n hn
    have hn1 : (a 1 y n : ℝ) ∈ Set.Ioo (L - (1/2:ℝ)) (L + (1/2:ℝ)) := hN n hn
    have hn2 : (a 1 y N : ℝ) ∈ Set.Ioo (L - (1/2:ℝ)) (L + (1/2:ℝ)) := hN N (le_refl N)
    have h_diff : |(a 1 y n : ℝ) - (a 1 y N : ℝ)| < 1 := by
      rcases hn1 with ⟨hn1l, hn1r⟩
      rcases hn2 with ⟨hn2l, hn2r⟩
      rw [abs_lt]
      constructor <;> linarith
    have h_diff_int : |a 1 y n - a 1 y N| < 1 := by exact_mod_cast h_diff
    rw [abs_lt] at h_diff_int
    omega

  use Int.gcd (1 + y) (y^N + 1), N
  intro n hn
  simp only [one_pow]
  have H1 := h_const n hn
  rw [ha_eq n, ha_eq N] at H1
  have H2 : Int.gcd (1 + y) (y^n - y) = Int.gcd (1 + y) (y^N - y) := by exact_mod_cast H1
  rw [←h_eq n, ←h_eq N] at H2
  exact H2

theorem lem_x_eq_one {y : ℤ} (h : (1, y) ∈ satisfyingPairs) : y = 1 :=
by
  -- Extract positivity condition
  have hy_pos : y > 0 := y_pos_of_mem_satisfyingPairs h

  -- Use the property of eventually constant GCD sequence
  rcases lem_eventually_constant_1y h with ⟨c, N, hN⟩

  -- Case 1: Evaluate constant c at an odd integer index (2 * N + 1)
  have h_odd : 2 * N + 1 ≥ N := by omega
  have eq_odd := hN (2 * N + 1) h_odd
  rw [gcd_one_pow_add] at eq_odd
  have h_dvd_odd := y_add_one_dvd_odd y N
  have gcd_odd := gcd_eq_left_of_dvd h_dvd_odd
  rw [gcd_odd] at eq_odd

  -- Case 2: Evaluate constant c at an even integer index (2 * N)
  have h_even : 2 * N ≥ N := by omega
  have eq_even := hN (2 * N) h_even
  rw [gcd_one_pow_add] at eq_even
  have h_dvd_even := y_add_one_dvd_even_sub_two y N
  have gcd_even := gcd_eq_of_dvd_sub h_dvd_even
  rw [gcd_even] at eq_even

  -- Deduce constraints
  have h_le := gcd_two_le (y + 1)
  rw [eq_even] at h_le

  -- `omega` can automatically solve Presburger arithmetic using the following assembled facts:
  -- 1. y > 0
  -- 2. (y + 1).natAbs = c
  -- 3. c ≤ 2
  omega

theorem lem_y_eq_one {x : ℤ} (h : (x, 1) ∈ satisfyingPairs) : x = 1 :=
by
  have int_dvd_gcd : ∀ {a b c : ℤ}, a ∣ b → a ∣ c → a ∣ (b.gcd c : ℤ) := by
    intro a b c hab hac
    have h_bezout : (b.gcd c : ℤ) = b * Int.gcdA b c + c * Int.gcdB b c := Int.gcd_eq_gcd_ab b c
    rw [h_bezout]
    obtain ⟨kb, hkb⟩ := hab
    obtain ⟨kc, hkc⟩ := hac
    use kb * Int.gcdA b c + kc * Int.gcdB b c
    rw [hkb, hkc]
    ring

  have h_copy := h
  simp only [satisfyingPairs, Set.mem_setOf_eq] at h_copy
  rcases h_copy with ⟨x_1, hx_1, y_1, hy_1, l, hl, hp⟩
  injection hp with hx_eq hy_eq
  subst x_1
  subst y_1
  have h_pos : 0 < x := hx_1

  have hF : ∀ n : ℕ, (∑ i ∈ Finset.range n, (1 : ℤ)^i * x^(n - i - 1 : ℕ)) * (1 - x) = 1 - x^n := by
    intro n
    induction n with
    | zero => simp
    | succ n ih =>
      rw [Finset.sum_range_succ']
      have h_eq : (∑ i ∈ Finset.range n, (1 : ℤ) ^ (i + 1) * x ^ (n + 1 - (i + 1) - 1)) = ∑ i ∈ Finset.range n, (1 : ℤ) ^ i * x ^ (n - i - 1) := by
        apply Finset.sum_congr rfl
        intro i _
        have H_pow1 : (1 : ℤ) ^ (i + 1) = (1 : ℤ) ^ i := by simp
        have H_pow2 : n + 1 - (i + 1) - 1 = n - i - 1 := by omega
        rw [H_pow1, H_pow2]
      rw [h_eq]
      have h3 : (1 : ℤ) ^ 0 * x ^ (n + 1 - 0 - 1) = x ^ n := by
        have : n + 1 - 0 - 1 = n := by omega
        rw [this]
        simp
      rw [h3]
      calc ((∑ i ∈ Finset.range n, (1 : ℤ)^i * x^(n - i - 1 : ℕ)) + x^n) * (1 - x)
        _ = (∑ i ∈ Finset.range n, (1 : ℤ)^i * x^(n - i - 1 : ℕ)) * (1 - x) + x^n * (1 - x) := by ring
        _ = (1 - x^n) + x^n * (1 - x) := by rw [ih]
        _ = 1 - x^(n + 1) := by
          have H_pow : x ^ (n + 1) = x ^ n * x := by rw [pow_add, pow_one]
          rw [H_pow]
          ring

  have ha2 : ∀ n : ℕ, a x 1 n = ((x^n + 1).gcd (x + 1) : ℤ) := by
    intro n
    unfold a
    have h1 : (1 - x) * (∑ i ∈ Finset.range n, (1 : ℤ)^i * x^(n - i - 1 : ℕ) - 1) = x - x^n := by
      calc (1 - x) * (∑ i ∈ Finset.range n, (1 : ℤ)^i * x^(n - i - 1 : ℕ) - 1)
        _ = (1 - x) * (∑ i ∈ Finset.range n, (1 : ℤ)^i * x^(n - i - 1 : ℕ)) - (1 - x) := by ring
        _ = (∑ i ∈ Finset.range n, (1 : ℤ)^i * x^(n - i - 1 : ℕ)) * (1 - x) - (1 - x) := by ring
        _ = 1 - x^n - (1 - x) := by rw [hF n]
        _ = x - x^n := by ring
    rw [h1]
    have H1 : ((x^n + 1).gcd (x - x^n) : ℤ) ∣ ((x^n + 1).gcd (x + 1) : ℤ) := by
      have d1 : ((x^n + 1).gcd (x - x^n) : ℤ) ∣ (x^n + 1) := Int.gcd_dvd_left (x^n + 1) (x - x^n)
      have d2 : ((x^n + 1).gcd (x - x^n) : ℤ) ∣ (x - x^n) := Int.gcd_dvd_right (x^n + 1) (x - x^n)
      have d3 : ((x^n + 1).gcd (x - x^n) : ℤ) ∣ (x^n + 1) + (x - x^n) := dvd_add d1 d2
      have h_eq : (x^n + 1) + (x - x^n) = x + 1 := by ring
      rw [h_eq] at d3
      exact int_dvd_gcd d1 d3
    have H2 : ((x^n + 1).gcd (x + 1) : ℤ) ∣ ((x^n + 1).gcd (x - x^n) : ℤ) := by
      have d1 : ((x^n + 1).gcd (x + 1) : ℤ) ∣ (x^n + 1) := Int.gcd_dvd_left (x^n + 1) (x + 1)
      have d2 : ((x^n + 1).gcd (x + 1) : ℤ) ∣ (x + 1) := Int.gcd_dvd_right (x^n + 1) (x + 1)
      have d3 : ((x^n + 1).gcd (x + 1) : ℤ) ∣ (x + 1) - (x^n + 1) := dvd_sub d2 d1
      have h_eq : (x + 1) - (x^n + 1) = x - x^n := by ring
      rw [h_eq] at d3
      exact int_dvd_gcd d1 d3
    have hp1 : 0 < ((x^n + 1).gcd (x + 1) : ℤ) := by
      have h_neq : ((x^n + 1).gcd (x + 1) : ℤ) ≠ 0 := by
        intro contra
        have h_zero_nat : (x^n + 1).gcd (x + 1) = 0 := by exact_mod_cast contra
        have h_zero_both := Int.gcd_eq_zero_iff.mp h_zero_nat
        have : x + 1 = 0 := h_zero_both.2
        omega
      omega
    have hp2 : 0 < ((x^n + 1).gcd (x - x^n) : ℤ) := by
      have h_neq : ((x^n + 1).gcd (x - x^n) : ℤ) ≠ 0 := by
        intro contra
        have h_zero_nat : (x^n + 1).gcd (x - x^n) = 0 := by exact_mod_cast contra
        have h_zero_both := Int.gcd_eq_zero_iff.mp h_zero_nat
        have : x^n + 1 = 0 := h_zero_both.1
        have h_pos_pow : 0 < x^n := by positivity
        omega
      omega
    apply le_antisymm
    · exact Int.le_of_dvd hp1 H1
    · exact Int.le_of_dvd hp2 H2

  have h_odd : ∀ k : ℕ, (x + 1) ∣ x^(2 * k + 1) + 1 := by
    intro k
    induction k with
    | zero =>
      show (x + 1) ∣ (x^(2 * 0 + 1) + 1)
      exact ⟨1, by ring⟩
    | succ k ih =>
      have : x^(2 * (k + 1) + 1) + 1 = (x^(2 * k + 1) + 1) * x^2 - (x + 1) * (x - 1) := by
        have h_pow : x^(2 * (k + 1) + 1) = x^(2 * k + 1) * x^2 := by
          have : 2 * (k + 1) + 1 = 2 * k + 1 + 2 := by omega
          rw [this, pow_add]
        rw [h_pow]
        ring
      rw [this]
      apply dvd_sub
      · exact dvd_mul_of_dvd_left ih _
      · exact dvd_mul_right _ _

  have h_odd_gcd : ∀ k : ℕ, ((x^(2 * k + 1) + 1).gcd (x + 1) : ℤ) = x + 1 := by
    intro k
    have hdvd : (x + 1) ∣ x^(2 * k + 1) + 1 := h_odd k
    have H1 : ((x^(2 * k + 1) + 1).gcd (x + 1) : ℤ) ∣ x + 1 := Int.gcd_dvd_right _ _
    have H2 : (x + 1) ∣ ((x^(2 * k + 1) + 1).gcd (x + 1) : ℤ) := int_dvd_gcd hdvd (dvd_refl _)
    have hz : 0 < x + 1 := by omega
    have hz2 : 0 < ((x^(2 * k + 1) + 1).gcd (x + 1) : ℤ) := by
      have h_neq : ((x^(2 * k + 1) + 1).gcd (x + 1) : ℤ) ≠ 0 := by
        intro contra
        have h_zero_nat : (x^(2 * k + 1) + 1).gcd (x + 1) = 0 := by exact_mod_cast contra
        have h_zero_both := Int.gcd_eq_zero_iff.mp h_zero_nat
        have : x + 1 = 0 := h_zero_both.2
        omega
      omega
    apply le_antisymm
    · exact Int.le_of_dvd hz H1
    · exact Int.le_of_dvd hz2 H2

  have h_even : ∀ k : ℕ, (x + 1) ∣ x^(2 * k) - 1 := by
    intro k
    induction k with
    | zero =>
      show (x + 1) ∣ (x^(2 * 0) - 1)
      exact ⟨0, by ring⟩
    | succ k ih =>
      have : x^(2 * (k + 1)) - 1 = (x^(2 * k) - 1) * x^2 + (x + 1) * (x - 1) := by
        have h_pow : x^(2 * (k + 1)) = x^(2 * k) * x^2 := by
          have : 2 * (k + 1) = 2 * k + 2 := by omega
          rw [this, pow_add]
        rw [h_pow]
        ring
      rw [this]
      apply dvd_add
      · exact dvd_mul_of_dvd_left ih _
      · exact dvd_mul_right _ _

  have h_even_gcd : ∀ k : ℕ, ((x^(2 * k) + 1).gcd (x + 1) : ℤ) = ((2 : ℤ).gcd (x + 1) : ℤ) := by
    intro k
    have hdvd : (x + 1) ∣ (x^(2 * k) + 1) - 2 := by
      have : (x^(2 * k) + 1) - 2 = (x^(2 * k) - 1) := by ring
      rw [this]
      exact h_even k
    have H1 : ((x^(2 * k) + 1).gcd (x + 1) : ℤ) ∣ ((2 : ℤ).gcd (x + 1) : ℤ) := by
      have d1 : ((x^(2 * k) + 1).gcd (x + 1) : ℤ) ∣ (x^(2 * k) + 1) := Int.gcd_dvd_left (x^(2 * k) + 1) (x + 1)
      have d2 : ((x^(2 * k) + 1).gcd (x + 1) : ℤ) ∣ (x + 1) := Int.gcd_dvd_right (x^(2 * k) + 1) (x + 1)
      have d_sub : ((x^(2 * k) + 1).gcd (x + 1) : ℤ) ∣ (x^(2 * k) + 1) - ((x^(2 * k) + 1) - 2) := by
        apply dvd_sub d1 (dvd_trans d2 hdvd)
      have h_eq : (x^(2 * k) + 1) - ((x^(2 * k) + 1) - 2) = 2 := by ring
      rw [h_eq] at d_sub
      exact int_dvd_gcd d_sub d2
    have H2 : (((2 : ℤ).gcd (x + 1) : ℤ)) ∣ ((x^(2 * k) + 1).gcd (x + 1) : ℤ) := by
      have d1 : (((2 : ℤ).gcd (x + 1) : ℤ)) ∣ 2 := Int.gcd_dvd_left 2 (x + 1)
      have d2 : (((2 : ℤ).gcd (x + 1) : ℤ)) ∣ (x + 1) := Int.gcd_dvd_right 2 (x + 1)
      have d_add : (((2 : ℤ).gcd (x + 1) : ℤ)) ∣ 2 + ((x^(2 * k) + 1) - 2) := by
        apply dvd_add d1 (dvd_trans d2 hdvd)
      have h_eq : 2 + ((x^(2 * k) + 1) - 2) = x^(2 * k) + 1 := by ring
      rw [h_eq] at d_add
      exact int_dvd_gcd d_add d2
    have hz1 : 0 < (((2 : ℤ).gcd (x + 1) : ℤ)) := by
      have h_neq : (((2 : ℤ).gcd (x + 1) : ℤ)) ≠ 0 := by
        intro contra
        have h_zero_nat : (2 : ℤ).gcd (x + 1) = 0 := by exact_mod_cast contra
        have h_zero_both := Int.gcd_eq_zero_iff.mp h_zero_nat
        have : (2 : ℤ) = 0 := h_zero_both.1
        omega
      omega
    have hz2 : 0 < ((x^(2 * k) + 1).gcd (x + 1) : ℤ) := by
      have h_neq : ((x^(2 * k) + 1).gcd (x + 1) : ℤ) ≠ 0 := by
        intro contra
        have h_zero_nat : (x^(2 * k) + 1).gcd (x + 1) = 0 := by exact_mod_cast contra
        have h_zero_both := Int.gcd_eq_zero_iff.mp h_zero_nat
        have : x + 1 = 0 := h_zero_both.2
        omega
      omega
    apply le_antisymm
    · exact Int.le_of_dvd hz1 H1
    · exact Int.le_of_dvd hz2 H2

  have t_odd : Filter.Tendsto (fun k : ℕ ↦ 2 * k + 1) Filter.atTop Filter.atTop := by
    rw [Filter.tendsto_atTop_atTop]
    intro b
    use b
    intro a ha
    omega
  have t_even : Filter.Tendsto (fun k : ℕ ↦ 2 * k) Filter.atTop Filter.atTop := by
    rw [Filter.tendsto_atTop_atTop]
    intro b
    use b
    intro a ha
    omega

  have h_tendsto_odd : Filter.Tendsto ((fun n : ℕ ↦ (a x 1 n : ℝ)) ∘ (fun k : ℕ ↦ 2 * k + 1)) Filter.atTop (𝓝 l) :=
    hl.comp t_odd
  have h_tendsto_even : Filter.Tendsto ((fun n : ℕ ↦ (a x 1 n : ℝ)) ∘ (fun k : ℕ ↦ 2 * k)) Filter.atTop (𝓝 l) :=
    hl.comp t_even

  have h_odd_eq : ((fun n : ℕ ↦ (a x 1 n : ℝ)) ∘ (fun k : ℕ ↦ 2 * k + 1)) = fun k ↦ (x + 1 : ℝ) := by
    ext k
    simp only [Function.comp_apply]
    have h1 : (a x 1 (2 * k + 1) : ℤ) = ((x^(2 * k + 1) + 1).gcd (x + 1) : ℤ) := ha2 (2 * k + 1)
    have h2 : ((x^(2 * k + 1) + 1).gcd (x + 1) : ℤ) = x + 1 := h_odd_gcd k
    have h3 : (a x 1 (2 * k + 1) : ℤ) = x + 1 := by rw [h1, h2]
    exact_mod_cast h3

  have h_even_eq : ((fun n : ℕ ↦ (a x 1 n : ℝ)) ∘ (fun k : ℕ ↦ 2 * k)) = fun k ↦ (((2 : ℤ).gcd (x + 1) : ℤ) : ℝ) := by
    ext k
    simp only [Function.comp_apply]
    have h1 : (a x 1 (2 * k) : ℤ) = ((x^(2 * k) + 1).gcd (x + 1) : ℤ) := ha2 (2 * k)
    have h2 : ((x^(2 * k) + 1).gcd (x + 1) : ℤ) = ((2 : ℤ).gcd (x + 1) : ℤ) := h_even_gcd k
    have h3 : (a x 1 (2 * k) : ℤ) = ((2 : ℤ).gcd (x + 1) : ℤ) := by rw [h1, h2]
    exact_mod_cast h3

  have h_tendsto_odd_const : Filter.Tendsto (fun k : ℕ ↦ (x + 1 : ℝ)) Filter.atTop (𝓝 l) := by
    have H := h_tendsto_odd
    rw [h_odd_eq] at H
    exact H

  have h_tendsto_even_const : Filter.Tendsto (fun k : ℕ ↦ (((2 : ℤ).gcd (x + 1) : ℤ) : ℝ)) Filter.atTop (𝓝 l) := by
    have H := h_tendsto_even
    rw [h_even_eq] at H
    exact H

  have hl_odd : l = (x + 1 : ℝ) := tendsto_nhds_unique h_tendsto_odd_const tendsto_const_nhds
  have hl_even : l = (((2 : ℤ).gcd (x + 1) : ℤ) : ℝ) := tendsto_nhds_unique h_tendsto_even_const tendsto_const_nhds

  have h_eq_real : (x + 1 : ℝ) = (((2 : ℤ).gcd (x + 1) : ℤ) : ℝ) := by
    rw [← hl_odd, ← hl_even]

  have h_eq_int : x + 1 = ((2 : ℤ).gcd (x + 1) : ℤ) := by
    exact_mod_cast h_eq_real

  have h_div_2 : ((2 : ℤ).gcd (x + 1) : ℤ) ∣ 2 := Int.gcd_dvd_left 2 (x + 1)
  have h_le_2 : ((2 : ℤ).gcd (x + 1) : ℤ) ≤ 2 := by
    apply Int.le_of_dvd
    · decide
    · exact h_div_2

  rw [← h_eq_int] at h_le_2
  omega

theorem lem_one_one_mem : (1, 1) ∈ satisfyingPairs :=
by
  have ha : ∀ n : ℕ, (a 1 1 n : ℝ) = 2 := by
    intro n
    unfold a
    have h1 : (1 : ℤ) ^ n + 1 = 2 := by
      rw [one_pow]
      rfl
    rw [h1]
    rw [sub_self]
    rw [zero_mul]
    have h3 : Int.gcd 2 0 = 2 := rfl
    rw [h3]
    norm_num

  have h_tendsto : Filter.Tendsto (fun n ↦ (a 1 1 n : ℝ)) Filter.atTop (𝓝 2) := by
    have h_eq : (fun n ↦ (a 1 1 n : ℝ)) = (fun n ↦ (2 : ℝ)) := by
      ext n
      exact ha n
    rw [h_eq]
    exact tendsto_const_nhds

  unfold satisfyingPairs
  simp only [Set.mem_setOf_eq]
  have h_pos : (0 : ℤ) < 1 := by norm_num
  exact ⟨1, h_pos, 1, h_pos, 2, h_tendsto, rfl⟩

theorem PBAdvanced020 : satisfyingPairs = {(1, 1)} :=
by
  ext ⟨x, y⟩
  constructor
  · intro h
    by_cases hx : x = 1
    · subst hx
      have hy : y = 1 := lem_x_eq_one h
      subst hy
      exact Set.mem_singleton_iff.mpr rfl
    · by_cases hy : y = 1
      · subst hy
        have hx_eq : x = 1 := lem_y_eq_one h
        subst hx_eq
        exact Set.mem_singleton_iff.mpr rfl
      · exfalso
        exact lem_no_solution_gt_one hx hy h
  · intro h
    have h1 : (x, y) = (1, 1) := Set.mem_singleton_iff.mp h
    have h2 : x = 1 ∧ y = 1 := Prod.mk_inj.mp h1
    rcases h2 with ⟨rfl, rfl⟩
    exact lem_one_one_mem
