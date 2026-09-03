import Mathlib

theorem mem_digits_imp {b : ℕ} (hb : 2 ≤ b) (m u : ℕ) :
  u ∈ Nat.digits b m → ∃ i, u = (m / b^i) % b ∧ m / b^i > 0 :=
by
  induction' m using Nat.strong_induction_on with m ih
  intro hu
  rcases eq_or_ne m 0 with rfl | hm_ne
  · rw [Nat.digits_zero] at hu
    cases hu
  · have hm : 0 < m := by omega
    have hb_gt : 1 < b := by omega
    rw [Nat.digits_def' hb_gt hm] at hu
    simp only [List.mem_cons] at hu
    rcases hu with rfl | hu
    · use 0
      rw [pow_zero, Nat.div_one]
      exact ⟨rfl, hm⟩
    · have h_lt : m / b < m := by apply Nat.div_lt_self <;> omega
      rcases ih (m / b) h_lt hu with ⟨i, hi1, hi2⟩
      use i + 1
      have Hdiv : m / b ^ (i + 1) = m / b / b ^ i := by
        rw [pow_add, pow_one, mul_comm (b ^ i) b, ← Nat.div_div_eq_div_mul]
      rw [Hdiv]
      exact ⟨hi1, hi2⟩

theorem pow_div_gt_zero_imp_lt (n k i : ℕ) (hk : 0 < k) (hn : 0 < n) :
  n^k / (2 * n)^i > 0 → i < k :=
by
  intro h_div
  by_contra hki
  have hk_le_i : k ≤ i := by omega
  have h1 : (2 * n)^i ≤ n^k := by
    by_contra h2
    have h3 : n^k / (2 * n)^i = 0 := Nat.div_eq_of_lt (by omega)
    omega
  have hk_le : 1 ≤ k := by omega
  have h_base : 1 ≤ 2 * n := by omega
  have h5 : (2 * n)^k ≤ (2 * n)^i := pow_le_pow_right' h_base hk_le_i
  have h6 : (2 * n)^k = (2 : ℕ)^k * n^k := mul_pow (2 : ℕ) n k
  have h7 : (2 : ℕ)^1 ≤ (2 : ℕ)^k := pow_le_pow_right' (by omega : 1 ≤ (2 : ℕ)) hk_le
  have h7' : (2 : ℕ) ≤ (2 : ℕ)^k := h7
  have h8 : (2 : ℕ) * n^k ≤ (2 : ℕ)^k * n^k := Nat.mul_le_mul_right (n^k) h7'
  have h9 : 0 < n^k := by positivity
  omega

theorem div_two_n_pow (n i j : ℕ) (hn : 0 < n) :
  n^(i + j) / (2 * n)^i = n^j / 2^i :=
by
  -- Rewrite the numerator: n^(i + j) = n^(j + i) = n^j * n^i
  have h1 : n^(i + j) = n^j * n^i := by
    rw [add_comm i j, pow_add]

  -- Rewrite the denominator: (2 * n)^i = 2^i * n^i
  have h2 : (2 * n)^i = 2^i * n^i := by
    rw [mul_pow]

  -- Substitute the expanded expressions back into the goal
  rw [h1, h2]

  -- Apply the right-cancellation law for natural number division
  -- This leaves us with the side goal of proving that the canceled factor is strictly positive
  apply Nat.mul_div_mul_right

  -- Since n > 0, any natural power of n is also strictly positive
  positivity

theorem aux_div_eq (n p i : ℕ) (hn : 0 < n) :
  ((n * p) / 2^i) % (2 * n) = (n * (p % 2^(i+1))) / 2^i :=
by
  have hp : p = 2^(i+1) * (p / 2^(i+1)) + (p % 2^(i+1)) := (Nat.div_add_mod p (2^(i+1))).symm

  have hnp : n * p = (2 * n * (p / 2^(i+1))) * 2^i + n * (p % 2^(i+1)) := by
    calc n * p = n * (2^(i+1) * (p / 2^(i+1)) + (p % 2^(i+1))) := congrArg (fun x => n * x) hp
      _ = (2 * n * (p / 2^(i+1))) * 2^i + n * (p % 2^(i+1)) := by
        rw [pow_succ]
        ring

  have h_pos : 0 < 2^i := by positivity

  have h_div : (n * p) / 2^i = 2 * n * (p / 2^(i+1)) + (n * (p % 2^(i+1))) / 2^i := by
    rw [hnp]
    have h_rw : (2 * n * (p / 2^(i+1))) * 2^i + n * (p % 2^(i+1)) = n * (p % 2^(i+1)) + (2 * n * (p / 2^(i+1))) * 2^i := Nat.add_comm _ _
    rw [h_rw]
    rw [Nat.add_mul_div_right (n * (p % 2^(i+1))) (2 * n * (p / 2^(i+1))) h_pos]
    exact Nat.add_comm _ _

  have h_mod : ((n * p) / 2^i) % (2 * n) = ((n * (p % 2^(i+1))) / 2^i) % (2 * n) := by
    rw [h_div]
    have h_add : 2 * n * (p / 2^(i+1)) + (n * (p % 2^(i+1))) / 2^i = (n * (p % 2^(i+1))) / 2^i + 2 * n * (p / 2^(i+1)) := Nat.add_comm _ _
    rw [h_add]
    rw [Nat.add_mul_mod_self_left]

  have hr_lt : (p % 2^(i+1)) < 2^(i+1) := Nat.mod_lt p (by positivity)

  have hnr_lt : n * (p % 2^(i+1)) < 2 * n * 2^i := by
    have h_pow_eq : n * 2^(i+1) = 2 * n * 2^i := by
      rw [pow_succ]
      ring
    calc n * (p % 2^(i+1)) < n * 2^(i+1) := Nat.mul_lt_mul_of_pos_left hr_lt hn
      _ = 2 * n * 2^i := h_pow_eq

  have h_div_lt : (n * (p % 2^(i+1))) / 2^i < 2 * n := by
    rw [Nat.div_lt_iff_lt_mul h_pos]
    exact hnr_lt

  rw [h_mod]
  exact Nat.mod_eq_of_lt h_div_lt

theorem odd_pow_helper (n m : ℕ) (hn : Odd n) : Odd (n^m) :=
by
  induction m with
  | zero =>
    -- Base case: n^0 = 1. Since 1 = 2 * 0 + 1, our witness is 0.
    exact ⟨0, rfl⟩
  | succ m ih =>
    -- Inductive step: n^(m+1) = n^m * n
    obtain ⟨k, hk⟩ := ih
    obtain ⟨j, hj⟩ := hn

    -- The expanded form of (2k + 1)(2j + 1) reveals our next witness
    exact ⟨2 * k * j + k + j, by
      -- Lean definitionally evaluates n^(succ m) as (n^m) * n
      change n ^ m * n = _
      rw [hk, hj]
      ring⟩

theorem odd_mod_pow_pos (p i : ℕ) (hp : Odd p) :
  0 < p % 2^(i+1) :=
by
  by_contra h
  have h1 : p % 2^(i+1) = 0 := by omega
  have h2 : 2^(i+1) ∣ p := Nat.dvd_of_mod_eq_zero h1
  have h3 : 2 ∣ 2^(i+1) := ⟨2^i, by rw [pow_add, pow_one, mul_comm]⟩
  have h4 : 2 ∣ p := dvd_trans h3 h2
  exact Odd.not_two_dvd_nat hp h4

theorem n_ge_d_plus_one_mul_two_pow (n d k i : ℕ) (hik : i < k) (hn : (d + 1) * 2^k < n) :
  (d + 1) * 2^i ≤ n :=
by
  have h : (d + 1) * 2^i ≤ (d + 1) * 2^k := by gcongr <;> omega
  omega

theorem u_gt_d (n r i d : ℕ) (hr : 1 ≤ r) (hn : (d + 1) * 2^i ≤ n) :
  d < (n * r) / 2^i :=
by
  have h2 : (d + 1) * 2^i ≤ n * r :=
    calc
      (d + 1) * 2^i ≤ n := hn
      _ = n * 1 := (Nat.mul_one n).symm
      _ ≤ n * r := Nat.mul_le_mul_left n hr
  have h_pos : 0 < 2^i := by positivity
  show d + 1 ≤ (n * r) / 2^i
  exact (Nat.le_div_iff_mul_le h_pos).mpr h2

theorem PBAdvanced025 (k d : ℕ) (hk : 0 < k) (hd : 0 < d) :
    ∃ N > 0, ∀ n > N, Odd n → ∀ u ∈ Nat.digits (2*n) (n^k), d < u :=
by
  use (d + 1) * 2^k
  constructor
  · positivity
  · intro n hn hn_odd u hu
    have hn0 : 0 < n := by omega
    have hb : 2 ≤ 2 * n := by omega
    rcases mem_digits_imp hb (n^k) u hu with ⟨i, hi1, hi2⟩
    have hik : i < k := pow_div_gt_zero_imp_lt n k i hk hn0 hi2

    -- Safely isolate differences as new positive variables to prevent infinite regression during rw
    obtain ⟨m, hm⟩ : ∃ m : ℕ, k = i + m := ⟨k - i, by omega⟩
    have hm_pos : 0 < m := by omega
    obtain ⟨j, hj⟩ : ∃ j : ℕ, m = j + 1 := ⟨m - 1, by omega⟩

    have h_div : n^k / (2 * n)^i = n^m / 2^i := by
      calc n^k / (2 * n)^i = n^(i + m) / (2 * n)^i := by rw [hm]
                         _ = n^m / 2^i := div_two_n_pow n i m hn0

    have h_n_pow : n^m = n * n^j := by
      calc n^m = n^(j + 1) := by rw [hj]
             _ = n^(1 + j) := by rw [add_comm j 1]
             _ = n^1 * n^j := by rw [pow_add]
             _ = n * n^j := by rw [pow_one]

    have h_u : u = ((n * n^j) / 2^i) % (2 * n) := by
      calc u = (n^k / (2 * n)^i) % (2 * n) := hi1
           _ = (n^m / 2^i) % (2 * n) := by rw [h_div]
           _ = ((n * n^j) / 2^i) % (2 * n) := by rw [h_n_pow]

    have h_u2 : u = (n * (n^j % 2^(i + 1))) / 2^i := by
      rw [h_u, aux_div_eq n (n^j) i hn0]

    have h_odd : Odd (n^j) := odd_pow_helper n j hn_odd
    have h_mod_pos : 0 < n^j % 2^(i + 1) := odd_mod_pow_pos (n^j) i h_odd
    have h_mod_ge : 1 ≤ n^j % 2^(i + 1) := by omega

    have hn_bound : (d + 1) * 2^k < n := hn
    have h_n_ge : (d + 1) * 2^i ≤ n := n_ge_d_plus_one_mul_two_pow n d k i hik hn_bound

    have h_ans : d < (n * (n^j % 2^(i + 1))) / 2^i :=
      u_gt_d n (n^j % 2^(i + 1)) i d h_mod_ge h_n_ge

    rw [← h_u2] at h_ans
    exact h_ans
