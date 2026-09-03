import Mathlib
variable (A : Finset ℕ)
def Acond := A ⊆ Finset.Icc 1 2000 ∧ A.card = 1000 ∧ ∀ a ∈ A, ∀ b ∈ A, a ≠ b → ¬ a ∣ b

def Odd2000 : Finset ℕ := (Finset.Icc 1 2000).filter Odd

noncomputable def pow_part (n : ℕ) : ℕ := padicValNat 2 n

noncomputable def odd_part (n : ℕ) : ℕ := n / 2^(pow_part n)

def c_fun (m : ℕ) : ℕ :=
  if m < 3 then 6
  else if m < 9 then 5
  else if m < 27 then 4
  else if m < 81 then 3
  else if m < 243 then 2
  else if m < 729 then 1
  else 0

def A0_fun (m : ℕ) : ℕ := m * 2^(c_fun m)

def A0 : Finset ℕ := Odd2000.image A0_fun

def max_k (m : ℕ) : ℕ :=
  if m * 729 ≤ 2000 then 6
  else if m * 243 ≤ 2000 then 5
  else if m * 81 ≤ 2000 then 4
  else if m * 27 ≤ 2000 then 3
  else if m * 9 ≤ 2000 then 2
  else if m * 3 ≤ 2000 then 1
  else 0

-- We use a new distinct lemma name `Acond_elem_ge_64` to bypass the local compiler "Unknown identifier" error
-- while strictly avoiding the "REDEFINITION ERROR" on `Acond_min_ge_64` in the shared graph.

-- Step 1: Extract basic bounds for any element in set A based on the conditions.

-- Helper lemma asserting that the image of A under odd_part is exactly Odd2000.
-- Its proof relies on injectivity and the cardinality constraint (both sets have 1000 elements).

-- Existing subproblem lemmas

-- 1. Helper Lemma: Extracts the bounding properties of element `a` in `A`.

-- Lemma 1: Bounding limits strictly defined by the subset criteria (hA).

set_option maxRecDepth 500000

theorem elem_in_bounds {A : Finset ℕ} (hA : Acond A) {x : ℕ} (hx : x ∈ A) :
  1 ≤ x ∧ x ≤ 2000 :=
by
  unfold Acond at hA
  have h_sub : A ⊆ Finset.Icc 1 2000 := hA.1
  have hx_in : x ∈ Finset.Icc 1 2000 := h_sub hx
  exact Finset.mem_Icc.mp hx_in

theorem decomp_odd_pow (x : ℕ) (hx : 1 ≤ x ∧ x ≤ 2000) :
  ∃ m p : ℕ, Odd m ∧ x = m * 2^p ∧ (1 ≤ m ∧ m ≤ 2000) :=
by
  have hx_nz : x ≠ 0 := by omega
  obtain ⟨p, m, h_odd, h_eq⟩ := Nat.exists_eq_two_pow_mul_odd hx_nz
  use m, p
  refine ⟨h_odd, ?_, ?_⟩
  · rw [h_eq]
    exact mul_comm (2^p) m
  · have h1 : 1 ≤ m := by
      by_contra! h_not
      have hm : m = 0 := by omega
      have hx0 : x = 0 := by rw [h_eq, hm, mul_zero]
      omega
    have h_pos : 0 < 2^p := by positivity
    have hA_pos : 1 ≤ 2^p := h_pos
    have h_mul : 1 * m ≤ 2^p * m := Nat.mul_le_mul_right m hA_pos
    rw [one_mul] at h_mul
    have h3 : m ≤ x := by
      rw [h_eq]
      exact h_mul
    constructor
    · exact h1
    · omega

theorem max_k_property (m : ℕ) (hm : 1 ≤ m ∧ m ≤ 2000) :
  ∃ k : ℕ, m * 3^k ≤ 2000 ∧ 2000 < m * 3^(k+1) ∧ k ≤ 6 :=
by
  obtain ⟨hm_ge, hm_le⟩ := hm
  by_cases h6 : m * 3^6 ≤ 2000
  · use 6
    constructor
    · exact h6
    · constructor
      · have h : m * 3^(6+1) = m * 2187 := by norm_num
        rw [h]
        omega
      · omega
  · by_cases h5 : m * 3^5 ≤ 2000
    · use 5
      constructor
      · exact h5
      · constructor
        · have h : m * 3^(5+1) = m * 3^6 := by norm_num
          rw [h]
          omega
        · omega
    · by_cases h4 : m * 3^4 ≤ 2000
      · use 4
        constructor
        · exact h4
        · constructor
          · have h : m * 3^(4+1) = m * 3^5 := by norm_num
            rw [h]
            omega
          · omega
      · by_cases h3 : m * 3^3 ≤ 2000
        · use 3
          constructor
          · exact h3
          · constructor
            · have h : m * 3^(3+1) = m * 3^4 := by norm_num
              rw [h]
              omega
            · omega
        · by_cases h2 : m * 3^2 ≤ 2000
          · use 2
            constructor
            · exact h2
            · constructor
              · have h : m * 3^(2+1) = m * 3^3 := by norm_num
                rw [h]
                omega
              · omega
          · by_cases h1 : m * 3^1 ≤ 2000
            · use 1
              constructor
              · exact h1
              · constructor
                · have h : m * 3^(1+1) = m * 3^2 := by norm_num
                  rw [h]
                  omega
                · omega
            · use 0
              constructor
              · have h0 : m * 3^0 = m := by norm_num
                rw [h0]
                omega
              · constructor
                · have h1_eq : m * 3^(0+1) = m * 3^1 := by norm_num
                  rw [h1_eq]
                  omega
                · omega

theorem elem_in_bounds_custom {A : Finset ℕ} (hA : Acond A) {a : ℕ} (ha : a ∈ A) : 1 ≤ a ∧ a ≤ 2000 :=
by
  unfold Acond at hA
  have h_sub := hA.1
  have h_mem := h_sub ha
  rw [Finset.mem_Icc] at h_mem
  exact h_mem

theorem odd_part_le_custom (a : ℕ) : odd_part a ≤ a :=
by
  exact Nat.div_le_self a (2 ^ pow_part a)

theorem mem_Odd2000_iff_custom (x : ℕ) : x ∈ Odd2000 ↔ 1 ≤ x ∧ x ≤ 2000 ∧ Odd x :=
by
  unfold Odd2000
  rw [Finset.mem_filter, Finset.mem_Icc, and_assoc]

theorem odd_part_is_odd_custom {a : ℕ} (ha : 0 < a) : Odd (odd_part a) :=
by
  have ha_ne : a ≠ 0 := by omega
  obtain ⟨k, m, hm, rfl⟩ := Nat.exists_eq_two_pow_mul_odd ha_ne
  unfold odd_part pow_part
  have h_pos : 0 < 2 ^ k := by positivity
  have h1 : 2 ^ k ≠ 0 := by omega
  have h2 : m ≠ 0 := by
    intro hm_zero
    subst hm_zero
    rw [mul_zero] at ha
    omega
  have hp : Fact (Nat.Prime 2) := ⟨Nat.prime_two⟩
  have h2m : ¬ 2 ∣ m := Odd.not_two_dvd_nat hm
  have hm_padic : padicValNat 2 m = 0 := padicValNat.eq_zero_of_not_dvd h2m
  have h_padic : padicValNat 2 (2 ^ k * m) = k := by
    have h_mul : padicValNat 2 (2 ^ k * m) = padicValNat 2 (2 ^ k) + padicValNat 2 m :=
      padicValNat.mul h1 h2
    rw [h_mul, padicValNat.prime_pow k, hm_padic, add_zero]
  rw [h_padic]
  have hk_div : 2 ^ k * m / 2 ^ k = m := Nat.mul_div_cancel_left _ h_pos
  rw [hk_div]
  exact hm

theorem odd_part_pos_custom {a : ℕ} (h_odd : Odd (odd_part a)) : 1 ≤ odd_part a :=
by
  rcases h_odd with ⟨k, hk⟩
  omega

theorem odd_part_mem_Odd2000 {A : Finset ℕ} (hA : Acond A) {a : ℕ} (ha : a ∈ A) :
  odd_part a ∈ Odd2000 :=
by
  -- Extract initial bounds constraints
  have ⟨h1, h2⟩ := elem_in_bounds_custom hA ha

  -- `1 ≤ a` indicates `0 < a` which validates it for parity assertions
  have hpos : 0 < a := h1

  -- Procure oddness properties mapping and deduce positivity limits
  have h_odd := odd_part_is_odd_custom hpos
  have h_pos2 : 1 ≤ odd_part a := odd_part_pos_custom h_odd

  -- Formulate the upper bound transitively
  have h_le := odd_part_le_custom a
  have h_le2000 : odd_part a ≤ 2000 := le_trans h_le h2

  -- Reconstruct to explicitly match conditions of `Odd2000` via our strict equivalence
  rw [mem_Odd2000_iff_custom]
  exact ⟨h_pos2, h_le2000, h_odd⟩

theorem odd_part_injOn_A {A : Finset ℕ} (hA : Acond A) : ∀ a ∈ A, ∀ b ∈ A, odd_part a = odd_part b → a = b :=
by
  have hA_unfolded : A ⊆ Finset.Icc 1 2000 ∧ A.card = 1000 ∧ ∀ a ∈ A, ∀ b ∈ A, a ≠ b → ¬ a ∣ b := hA
  obtain ⟨_, _, h_div⟩ := hA_unfolded
  intros a ha b hb heq
  have h_a : 2 ^ pow_part a * odd_part a = a := Nat.ordProj_mul_ordCompl_eq_self a 2
  have h_b : 2 ^ pow_part b * odd_part b = b := Nat.ordProj_mul_ordCompl_eq_self b 2
  rcases le_total (pow_part a) (pow_part b) with hab | hba
  · have hb_dvd : a ∣ b := by
      have e : pow_part a + (pow_part b - pow_part a) = pow_part b := by omega
      use 2 ^ (pow_part b - pow_part a)
      calc
        b = 2 ^ pow_part b * odd_part b := h_b.symm
        _ = 2 ^ (pow_part a + (pow_part b - pow_part a)) * odd_part b := by rw [e]
        _ = (2 ^ pow_part a * 2 ^ (pow_part b - pow_part a)) * odd_part b := by rw [pow_add]
        _ = (2 ^ pow_part a * odd_part b) * 2 ^ (pow_part b - pow_part a) := by rw [mul_right_comm]
        _ = (2 ^ pow_part a * odd_part a) * 2 ^ (pow_part b - pow_part a) := by rw [← heq]
        _ = a * 2 ^ (pow_part b - pow_part a) := by rw [h_a]
    by_contra h_neq
    exact h_div a ha b hb h_neq hb_dvd
  · have ha_dvd : b ∣ a := by
      have e : pow_part b + (pow_part a - pow_part b) = pow_part a := by omega
      use 2 ^ (pow_part a - pow_part b)
      calc
        a = 2 ^ pow_part a * odd_part a := h_a.symm
        _ = 2 ^ (pow_part b + (pow_part a - pow_part b)) * odd_part a := by rw [e]
        _ = (2 ^ pow_part b * 2 ^ (pow_part a - pow_part b)) * odd_part a := by rw [pow_add]
        _ = (2 ^ pow_part b * odd_part a) * 2 ^ (pow_part a - pow_part b) := by rw [mul_right_comm]
        _ = (2 ^ pow_part b * odd_part b) * 2 ^ (pow_part a - pow_part b) := by rw [heq]
        _ = b * 2 ^ (pow_part a - pow_part b) := by rw [h_b]
    by_contra h_neq
    exact h_div b hb a ha (fun h => h_neq h.symm) ha_dvd

theorem Acond_card {A : Finset ℕ} (hA : Acond A) : A.card = 1000 :=
by
  obtain ⟨_, h_card, _⟩ := hA
  exact h_card

theorem Odd2000_card : Odd2000.card = 1000 :=
by
  have hinj : Function.Injective (fun n : ℕ => 2 * n + 1) := by
    intro a b hab
    -- Unfold the beta-application so `omega` understands the linear arithmetic structure
    change 2 * a + 1 = 2 * b + 1 at hab
    omega
  have H : Odd2000 = (Finset.range 1000).map ⟨fun n => 2 * n + 1, hinj⟩ := by
    ext x
    -- Including `Function.Embedding.coeFn_mk` here resolves the lingering map coercion to simple integer math
    simp only [Odd2000, Finset.mem_filter, Finset.mem_Icc, Finset.mem_map, Finset.mem_range, Function.Embedding.coeFn_mk]
    constructor
    · rintro ⟨⟨h1, h2⟩, hOdd⟩
      obtain ⟨k, hk⟩ := hOdd
      subst hk
      -- `refine` with `rfl` handles the existential generation seamlessly instead of `use`
      refine ⟨k, ?_, rfl⟩
      omega
    · rintro ⟨a, ha, rfl⟩
      refine ⟨⟨?_, ?_⟩, a, rfl⟩
      · omega
      · omega
  rw [H, Finset.card_map, Finset.card_range]

theorem image_odd_part_eq_Odd2000 {A : Finset ℕ} (hA : Acond A) : A.image odd_part = Odd2000 :=
by
  -- Two sets are equal if one is a subset of the other and the superset is not larger
  apply Finset.eq_of_subset_of_card_le
  · -- Subproblem 1: Prove A.image odd_part ⊆ Odd2000
    intro x hx
    rw [Finset.mem_image] at hx
    obtain ⟨a, ha, rfl⟩ := hx
    exact odd_part_mem_Odd2000 hA ha
  · -- Subproblem 2: Prove Odd2000.card ≤ (A.image odd_part).card
    -- First, state injectivity purely in terms of Set.InjOn
    have h_inj : Set.InjOn odd_part A := by
      intro a ha b hb hab
      exact odd_part_injOn_A hA a ha b hb hab

    -- Evaluate cardinalities to build the proof
    have h_card1 : (A.image odd_part).card = A.card := Finset.card_image_of_injOn h_inj
    have h_card2 : A.card = 1000 := Acond_card hA
    have h_card3 : Odd2000.card = 1000 := Odd2000_card

    -- `omega` automatically applies arithmetic bounds given the above properties
    omega

theorem odd_part_surj {A : Finset ℕ} (hA : Acond A) {m : ℕ} (hm : m ∈ Odd2000) : ∃ a ∈ A, odd_part a = m :=
by
  -- We know from the helper lemma that the image of A under odd_part is exactly Odd2000
  rw [← image_odd_part_eq_Odd2000 hA] at hm
  -- By the definition of Finset.image, m being in the image implies the existence of our element
  exact Finset.mem_image.mp hm

theorem mul_three_pow_le_of_succ_pow_local {m k : ℕ} (h : m * 3^(k+1) ≤ 2000) : m * 3^k ≤ 2000 :=
by
  have h1 : m * 3 ^ (k + 1) = (m * 3 ^ k) * 3 := by ring
  rw [h1] at h
  omega

theorem mul_three_pow_eq_succ_pow_local (m k : ℕ) : (3 * m) * 3^k = m * 3^(k+1) :=
by
  rw [pow_add, pow_one]
  ring

theorem odd_three_mul_local {m : ℕ} (h : Odd m) : Odd (3 * m) :=
by
  obtain ⟨k, hk⟩ := h
  use 3 * k + 1
  omega

theorem dvd_mul_two_pow_local {m k p' : ℕ} (h : k ≤ p') : (m * 2^k) ∣ ((3 * m) * 2^p') :=
by
  obtain ⟨c, hc⟩ := pow_dvd_pow (2 : ℕ) h
  use 3 * c
  rw [hc]
  ring

theorem neq_of_odd_part_neq_local {a a' m m' : ℕ} (h1 : odd_part a = m) (h2 : odd_part a' = m') (hneq : m ≠ m') : a ≠ a' :=
by
  rintro rfl
  exact hneq (h1.symm.trans h2)

theorem odd_neq_mul_three_local {m : ℕ} (h : Odd m) : m ≠ 3 * m :=
by
  obtain ⟨k, hk⟩ := h
  omega

theorem le_2000_of_mul_pow_le_local {m k : ℕ} (hLe : m * 3^k ≤ 2000) : m ≤ 2000 :=
by
  have h1 : 1 ≤ 3^k := Nat.one_le_pow' k 2
  have h2 : m * 1 ≤ m * 3^k := Nat.mul_le_mul_left m h1
  omega

theorem mem_Odd2000_local {m : ℕ} (hOdd : Odd m) (hLe : m ≤ 2000) : m ∈ Odd2000 :=
by
  rw [Odd2000, Finset.mem_filter, Finset.mem_Icc]
  constructor
  · constructor
    · obtain ⟨k, hk⟩ := hOdd
      omega
    · exact hLe
  · exact hOdd

theorem no_dvd_of_Acond_local {A : Finset ℕ} (hA : Acond A) {a b : ℕ} (ha : a ∈ A) (hb : b ∈ A) (hneq : a ≠ b) : ¬ a ∣ b :=
hA.2.2 a ha b hb hneq

theorem a_eq_odd_part_mul_pow_part_of_mem_local {A : Finset ℕ} (hA : Acond A) {a : ℕ} (ha : a ∈ A) : a = odd_part a * 2 ^ pow_part a :=
by
  have ha_Icc : a ∈ Finset.Icc 1 2000 := hA.1 ha
  have ha_ne_zero : a ≠ 0 := by
    rw [Finset.mem_Icc] at ha_Icc
    omega
  have hdvd : 2 ^ pow_part a ∣ a := by
    exact (padicValNat_dvd_iff_le ha_ne_zero).mpr (Nat.le_refl _)
  unfold odd_part
  exact (Nat.div_mul_cancel hdvd).symm

theorem elem_in_bounds_local_thm {A : Finset ℕ} (hA : Acond A) {a : ℕ} (ha : a ∈ A) : 1 ≤ a ∧ a ≤ 2000 :=
by
  rw [Acond] at hA
  have h_sub : A ⊆ Finset.Icc 1 2000 := hA.1
  have h_mem : a ∈ Finset.Icc 1 2000 := h_sub ha
  rw [Finset.mem_Icc] at h_mem
  exact h_mem

theorem mem_Odd2000_local_thm {y : ℕ} (hy1 : 1 ≤ y) (hy2 : y ≤ 2000) (hOdd : Odd y) : y ∈ Odd2000 :=
by
  rw [Odd2000, Finset.mem_filter, Finset.mem_Icc]
  exact ⟨⟨hy1, hy2⟩, hOdd⟩

theorem odd_part_le_local_thm (a : ℕ) : odd_part a ≤ a :=
by
  exact Nat.div_le_self a (2 ^ pow_part a)

theorem odd_part_pos_local_thm {a : ℕ} (ha : a ≠ 0) : 1 ≤ odd_part a :=
by
  unfold odd_part pow_part
  have h_dvd : 2 ^ padicValNat 2 a ∣ a := pow_padicValNat_dvd
  have h_cancel := Nat.div_mul_cancel h_dvd
  have h_ne : a / 2 ^ padicValNat 2 a ≠ 0 := by
    intro h0
    rw [h0, zero_mul] at h_cancel
    exact ha h_cancel.symm
  exact Nat.pos_of_ne_zero h_ne

theorem odd_part_two_pow_mul_odd_local {k m : ℕ} (hm : Odd m) : odd_part (2 ^ k * m) = m :=
by
  unfold odd_part pow_part
  have hp : Fact (Nat.Prime 2) := ⟨Nat.prime_two⟩
  have hm0 : m ≠ 0 := by
    rintro rfl
    rcases hm with ⟨c, hc⟩
    omega
  have h2k0 : 2^k ≠ 0 := by positivity
  have h_not_dvd : ¬ 2 ∣ m := by
    rintro ⟨c, rfl⟩
    rcases hm with ⟨d, hd⟩
    omega

  -- The 2-adic valuation of an odd number is 0
  have h_padic_m : padicValNat 2 m = 0 := by
    by_contra h_ne_zero
    have h_dvd := (@dvd_iff_padicValNat_ne_zero 2 m hp hm0).mpr h_ne_zero
    exact h_not_dvd h_dvd

  -- The 2-adic valuation is additive over multiplication for non-zero entries
  have h_mul : padicValNat 2 (2 ^ k * m) = padicValNat 2 (2 ^ k) + padicValNat 2 m :=
    @padicValNat.mul 2 (2 ^ k) m hp h2k0 hm0

  -- The 2-adic valuation of 2^k is exactly k
  have h_padic2 : padicValNat 2 (2 ^ k) = k := by
    first
    | simp
    | exact padicValNat_prime_pow
    | exact padicValNat.prime_pow

  -- Combining them establishes the property on the complete multiplicative term
  have h_padic : padicValNat 2 (2 ^ k * m) = k := by
    rw [h_mul, h_padic_m, h_padic2, add_zero]

  -- Perform cancellation for final evaluation
  rw [h_padic]
  have h_pos : 0 < 2^k := by positivity
  first
  | exact Nat.mul_div_cancel_left m h_pos
  | exact Nat.mul_div_cancel_left _ h_pos
  | exact Nat.mul_div_cancel_left (2^k) m h_pos
  | exact Nat.mul_div_cancel_left m (2^k) h_pos
  | rw [mul_comm]; exact Nat.mul_div_cancel_right _ h_pos
  | rw [mul_comm]; exact Nat.mul_div_cancel _ h_pos
  | simp [h_pos]

theorem odd_part_odd_local_thm {a : ℕ} (ha : a ≠ 0) : Odd (odd_part a) :=
by
  obtain ⟨k, m, hm, rfl⟩ := Nat.exists_eq_two_pow_mul_odd ha
  rw [odd_part_two_pow_mul_odd_local hm]
  exact hm

theorem image_subset_Odd2000_local {A : Finset ℕ} (hA : Acond A) : A.image odd_part ⊆ Odd2000 :=
by
  intro y hy
  -- Unfold the definition of Finset.image
  rw [Finset.mem_image] at hy
  rcases hy with ⟨a, ha, hy_eq⟩

  -- Gather structural conditions of `a` strictly from environment rules
  have h_bounds := elem_in_bounds_local_thm hA ha
  have ha1 : 1 ≤ a := h_bounds.1
  have ha2000 : a ≤ 2000 := h_bounds.2
  have h_a_ne_zero : a ≠ 0 := by omega

  -- Gather localized bounding logic regarding the structure of odd_part evaluation
  have hop_le : odd_part a ≤ a := odd_part_le_local_thm a
  have hop_pos : 1 ≤ odd_part a := odd_part_pos_local_thm h_a_ne_zero
  have hop_odd : Odd (odd_part a) := odd_part_odd_local_thm h_a_ne_zero

  -- Conclusively deduce it falls within boundary bounds
  have hop_le_2000 : odd_part a ≤ 2000 := by omega

  -- Substitute the parameter y equivalently representing our evaluated functional mapping
  rw [← hy_eq]

  -- Close target requirement strictly invoking established verified boundaries
  exact mem_Odd2000_local_thm hop_pos hop_le_2000 hop_odd

theorem card_image_odd_part_local {A : Finset ℕ} (hA : Acond A) : (A.image odd_part).card = 1000 :=
by
  have hA_card : A.card = 1000 := hA.2.1
  have hA_div : ∀ a ∈ A, ∀ b ∈ A, a ≠ b → ¬ a ∣ b := hA.2.2

  have h_inj : Set.InjOn odd_part A := by
    intro a ha b hb hab

    have hdvd_a : 2 ^ pow_part a ∣ a := by
      unfold pow_part
      exact pow_padicValNat_dvd
    have hdvd_b : 2 ^ pow_part b ∣ b := by
      unfold pow_part
      exact pow_padicValNat_dvd

    have ha_eq : a = odd_part a * 2 ^ pow_part a := by
      unfold odd_part
      exact (Nat.div_mul_cancel hdvd_a).symm
    have hb_eq : b = odd_part b * 2 ^ pow_part b := by
      unfold odd_part
      exact (Nat.div_mul_cancel hdvd_b).symm

    have h_cases : pow_part a ≤ pow_part b ∨ pow_part b ≤ pow_part a := by omega
    rcases h_cases with hle | hle
    · have h_dvd : a ∣ b := by
        use 2 ^ (pow_part b - pow_part a)
        have h_pow : 2 ^ pow_part b = 2 ^ pow_part a * 2 ^ (pow_part b - pow_part a) := by
          rw [← pow_add]
          have h_eq : pow_part a + (pow_part b - pow_part a) = pow_part b := by omega
          rw [h_eq]
        calc
          b = odd_part b * 2 ^ pow_part b := hb_eq
          _ = odd_part a * 2 ^ pow_part b := by rw [← hab]
          _ = odd_part a * (2 ^ pow_part a * 2 ^ (pow_part b - pow_part a)) := by rw [h_pow]
          _ = (odd_part a * 2 ^ pow_part a) * 2 ^ (pow_part b - pow_part a) := by rw [← mul_assoc]
          _ = a * 2 ^ (pow_part b - pow_part a) := by rw [← ha_eq]
      by_contra h_neq
      exact hA_div a ha b hb h_neq h_dvd

    · have h_dvd : b ∣ a := by
        use 2 ^ (pow_part a - pow_part b)
        have h_pow : 2 ^ pow_part a = 2 ^ pow_part b * 2 ^ (pow_part a - pow_part b) := by
          rw [← pow_add]
          have h_eq : pow_part b + (pow_part a - pow_part b) = pow_part a := by omega
          rw [h_eq]
        calc
          a = odd_part a * 2 ^ pow_part a := ha_eq
          _ = odd_part b * 2 ^ pow_part a := by rw [hab]
          _ = odd_part b * (2 ^ pow_part b * 2 ^ (pow_part a - pow_part b)) := by rw [h_pow]
          _ = (odd_part b * 2 ^ pow_part b) * 2 ^ (pow_part a - pow_part b) := by rw [← mul_assoc]
          _ = b * 2 ^ (pow_part a - pow_part b) := by rw [← hb_eq]
      by_contra h_neq
      have h_neq' : b ≠ a := fun h => h_neq h.symm
      exact hA_div b hb a ha h_neq' h_dvd

  rw [Finset.card_image_of_injOn h_inj, hA_card]

theorem Odd2000_card_local_thm : Odd2000.card = 1000 :=
by
  decide

theorem image_odd_part_eq_Odd2000_local {A : Finset ℕ} (hA : Acond A) : A.image odd_part = Odd2000 :=
by
  have h_sub := image_subset_Odd2000_local hA
  have h_card : (A.image odd_part).card = Odd2000.card := by
    rw [card_image_odd_part_local hA, Odd2000_card_local_thm]
  have h_le : Odd2000.card ≤ (A.image odd_part).card := by omega
  exact (Finset.subset_iff_eq_of_card_le h_le).mp h_sub

theorem odd_part_surj_local {A : Finset ℕ} (hA : Acond A) {m : ℕ} (hm : m ∈ Odd2000) : ∃ a ∈ A, odd_part a = m :=
by
  have h_eq := image_odd_part_eq_Odd2000_local hA
  rw [← h_eq] at hm
  exact Finset.mem_image.mp hm

theorem pow_part_ge_k_induction_step {A : Finset ℕ} (hA : Acond A) (k : ℕ)
  (ih : ∀ m : ℕ, Odd m → m * 3^k ≤ 2000 → ∀ a ∈ A, odd_part a = m → k ≤ pow_part a) :
  ∀ m : ℕ, Odd m → m * 3^(k+1) ≤ 2000 → ∀ a ∈ A, odd_part a = m → k + 1 ≤ pow_part a :=
by
  intro m hOdd hLe a ha hOddPart
  have hLe_k : m * 3^k ≤ 2000 := mul_three_pow_le_of_succ_pow_local hLe
  have hk : k ≤ pow_part a := ih m hOdd hLe_k a ha hOddPart

  -- We prove `k ≠ pow_part a` to trigger strict inequality `k < pow_part a`,
  -- which is definitionally equivalent to `k + 1 ≤ pow_part a` in Nat.
  have h_ne : k ≠ pow_part a := by
    intro heq

    have ha_val : a = m * 2^k := by
      have h1 : a = odd_part a * 2 ^ pow_part a := a_eq_odd_part_mul_pow_part_of_mem_local hA ha
      rw [hOddPart, ← heq] at h1
      exact h1

    have hOdd3 : Odd (3 * m) := odd_three_mul_local hOdd
    have hLe3 : (3 * m) * 3^k ≤ 2000 := by
      rw [mul_three_pow_eq_succ_pow_local]
      exact hLe

    have hLe3_2000 : 3 * m ≤ 2000 := le_2000_of_mul_pow_le_local hLe3

    have hm3 : 3 * m ∈ Odd2000 := mem_Odd2000_local hOdd3 hLe3_2000

    have h_surj : ∃ a' ∈ A, odd_part a' = 3 * m := odd_part_surj_local hA hm3
    rcases h_surj with ⟨a', ha', hOddPart'⟩

    have hk' : k ≤ pow_part a' := ih (3 * m) hOdd3 hLe3 a' ha' hOddPart'

    have ha'_val : a' = (3 * m) * 2^(pow_part a') := by
      have h2 : a' = odd_part a' * 2 ^ pow_part a' := a_eq_odd_part_mul_pow_part_of_mem_local hA ha'
      rw [hOddPart'] at h2
      exact h2

    have hdvd : a ∣ a' := by
      rw [ha_val, ha'_val]
      exact dvd_mul_two_pow_local hk'

    have hneq_a : a ≠ a' := neq_of_odd_part_neq_local hOddPart hOddPart' (odd_neq_mul_three_local hOdd)

    -- Derive contradiction using the cleanly abstracted divisibility ban within `Acond`
    have h_ndvd : ¬ a ∣ a' := no_dvd_of_Acond_local hA ha ha' hneq_a
    exact h_ndvd hdvd

  have h_lt : k < pow_part a := lt_of_le_of_ne hk h_ne
  exact h_lt

theorem pow_part_ge_k_induction {A : Finset ℕ} (hA : Acond A) (k : ℕ) :
  ∀ m : ℕ, Odd m → m * 3^k ≤ 2000 → ∀ a ∈ A, odd_part a = m → k ≤ pow_part a :=
by
  induction k with
  | zero =>
    intros m _ _ a _ _
    exact Nat.zero_le _
  | succ k ih =>
    exact pow_part_ge_k_induction_step hA k ih

theorem mem_Odd2000_of_odd_mul_pow {m k : ℕ} (hOdd : Odd m) (hLe : m * 3^k ≤ 2000) : m ∈ Odd2000 :=
by
  rw [Odd2000, Finset.mem_filter, Finset.mem_Icc]
  refine ⟨⟨?_, ?_⟩, hOdd⟩
  · obtain ⟨c, hc⟩ := hOdd
    omega
  · have h_pow : 1 ≤ 3 ^ k := by
      have h : 0 < 3 ^ k := by positivity
      omega
    calc
      m = m * 1 := by rw [mul_one]
      _ ≤ m * 3 ^ k := Nat.mul_le_mul_left m h_pow
      _ ≤ 2000 := hLe

theorem pow_part_ge_k_of_mul_3_pow {A : Finset ℕ} (hA : Acond A) (k : ℕ) :
  ∀ m : ℕ, Odd m → m * 3^k ≤ 2000 →
  ∃ a ∈ A, odd_part a = m ∧ k ≤ pow_part a :=
by
  intro m hOdd hLe
  have hm : m ∈ Odd2000 := mem_Odd2000_of_odd_mul_pow hOdd hLe
  rcases odd_part_surj hA hm with ⟨a, ha, heq⟩
  exact ⟨a, ha, heq, pow_part_ge_k_induction hA k m hOdd hLe a ha heq⟩

theorem a_eq_odd_part_mul_pow_part_of_mem {A : Finset ℕ} (hA : Acond A) {a : ℕ} (ha : a ∈ A) :
  a = odd_part a * 2 ^ pow_part a :=
by
  have hdvd : 2 ^ pow_part a ∣ a := by
    unfold pow_part
    exact pow_padicValNat_dvd
  unfold odd_part
  exact (Nat.div_mul_cancel hdvd).symm

theorem chain_elem_exists {A : Finset ℕ} (hA : Acond A) (m k : ℕ) (hm_odd : Odd m) (hk_bound : m * 3^k ≤ 2000) :
  ∃ a ∈ A, ∃ p' : ℕ, a = m * 2^p' ∧ k ≤ p' :=
by
  -- 1. Apply the primary bound lemma via induction
  obtain ⟨a, ha_mem, h_odd, h_pow⟩ := pow_part_ge_k_of_mul_3_pow hA k m hm_odd hk_bound

  -- 2. Construct the exact existentials using `pow_part a` as the witness for `p'`
  refine ⟨a, ha_mem, pow_part a, ?_, h_pow⟩

  -- 3. Show a = m * 2^pow_part a using the definitions
  rw [← h_odd]
  exact a_eq_odd_part_mul_pow_part_of_mem hA ha_mem

theorem unique_odd_part {A : Finset ℕ} (hA : Acond A) {a x m p1 p2 : ℕ}
  (ha : a ∈ A) (hx : x ∈ A) (hodd : Odd m) (heq1 : a = m * 2^p1) (heq2 : x = m * 2^p2) :
  p1 = p2 :=
by
  rcases hA with ⟨hsub, _, hdiv⟩

  have h_exists : ∀ n m, n < m → ∃ k, m = n + k + 1 := by
    intro n m
    induction m with
    | zero =>
      intro hp
      omega
    | succ m ih =>
      intro hp
      by_cases heq : n = m
      · use 0
        omega
      · have hlt : n < m := by omega
        obtain ⟨k, hk⟩ := ih hlt
        use k + 1
        omega

  have h_cancel : ∀ z c, z = z * c * 2 → z = 0 := by
    intro z c hC
    cases c with
    | zero =>
      calc
        z = z * 0 * 2 := hC
        _ = 0 := by ring
    | succ c =>
      have hC' : z = z * (c + 1) * 2 := hC
      have h_expand : z * c * 2 + z + z = z := by
        calc
          z * c * 2 + z + z = z * c * 2 + z * 2 := by ring
          _ = z * (c + 1) * 2 := by ring
          _ = z := hC'.symm
      omega

  rcases lt_trichotomy p1 p2 with h | h | h
  · have ha_pos : 0 < a := by
      have hsub_mem := hsub ha
      rw [Finset.mem_Icc] at hsub_mem
      omega
    obtain ⟨k, hk_eq⟩ := h_exists p1 p2 h
    have h_eq : x = a * 2 ^ k * 2 := by
      calc
        x = m * 2 ^ p2 := heq2
        _ = m * 2 ^ (p1 + k + 1) := by rw [hk_eq]
        _ = m * (2 ^ (p1 + k) * 2 ^ 1) := by rw [pow_add]
        _ = m * (2 ^ p1 * 2 ^ k * 2 ^ 1) := by rw [pow_add]
        _ = (m * 2 ^ p1) * (2 ^ k * 2 ^ 1) := by ring
        _ = a * (2 ^ k * 2 ^ 1) := by rw [← heq1]
        _ = a * (2 ^ k * 2) := by rw [pow_one]
        _ = a * 2 ^ k * 2 := by rw [← mul_assoc]
    have h_neq : a ≠ x := by
      intro hax
      rw [hax] at h_eq
      have := h_cancel x (2 ^ k) h_eq
      omega
    have hdvd : a ∣ x := by
      use 2 ^ k * 2
      calc
        x = a * 2 ^ k * 2 := h_eq
        _ = a * (2 ^ k * 2) := by rw [mul_assoc]
    have hndvd := hdiv a ha x hx h_neq
    contradiction
  · exact h
  · have hx_pos : 0 < x := by
      have hsub_mem := hsub hx
      rw [Finset.mem_Icc] at hsub_mem
      omega
    obtain ⟨k, hk_eq⟩ := h_exists p2 p1 h
    have h_eq : a = x * 2 ^ k * 2 := by
      calc
        a = m * 2 ^ p1 := heq1
        _ = m * 2 ^ (p2 + k + 1) := by rw [hk_eq]
        _ = m * (2 ^ (p2 + k) * 2 ^ 1) := by rw [pow_add]
        _ = m * (2 ^ p2 * 2 ^ k * 2 ^ 1) := by rw [pow_add]
        _ = (m * 2 ^ p2) * (2 ^ k * 2 ^ 1) := by ring
        _ = x * (2 ^ k * 2 ^ 1) := by rw [← heq2]
        _ = x * (2 ^ k * 2) := by rw [pow_one]
        _ = x * 2 ^ k * 2 := by rw [← mul_assoc]
    have h_neq : x ≠ a := by
      intro hxa
      rw [hxa] at h_eq
      have := h_cancel a (2 ^ k) h_eq
      omega
    have hdvd : x ∣ a := by
      use 2 ^ k * 2
      calc
        a = x * 2 ^ k * 2 := h_eq
        _ = x * (2 ^ k * 2) := by rw [mul_assoc]
    have hndvd := hdiv x hx a ha h_neq
    contradiction

theorem calc_lower_bound (m k : ℕ) (hm : 1 ≤ m ∧ m ≤ 2000) (hk_le : k ≤ 6) (hk_bound : 2000 < m * 3^(k+1)) :
  64 ≤ m * 2^k :=
by
  have hk_cases : k = 0 ∨ k = 1 ∨ k = 2 ∨ k = 3 ∨ k = 4 ∨ k = 5 ∨ k = 6 := by omega
  rcases hk_cases with rfl | rfl | rfl | rfl | rfl | rfl | rfl
  · revert hk_bound; norm_num; intro hk_bound; omega
  · revert hk_bound; norm_num; intro hk_bound; omega
  · revert hk_bound; norm_num; intro hk_bound; omega
  · revert hk_bound; norm_num; intro hk_bound; omega
  · revert hk_bound; norm_num; intro hk_bound; omega
  · revert hk_bound; norm_num; intro hk_bound; omega
  · revert hk_bound; norm_num; intro hk_bound; omega

theorem Acond_elem_ge_64 {A : Finset ℕ} (hA : Acond A) {x : ℕ} (hx : x ∈ A) : 64 ≤ x :=
by
  -- Obtain the required constraints for the chosen element x ∈ A
  have hx_bounds : 1 ≤ x ∧ x ≤ 2000 := elem_in_bounds hA hx

  -- Decompose x into m * 2^p
  obtain ⟨m, p, hm_odd, hx_eq, hm_bounds⟩ := decomp_odd_pow x hx_bounds

  -- Find the maximal k for our odd part m
  obtain ⟨k, hk_le_2000, hk_gt_2000, hk_le_6⟩ := max_k_property m hm_bounds

  -- Guarantee the existence of the matching element a ∈ A
  obtain ⟨a, ha_mem, p', ha_eq, hk_le_p'⟩ := chain_elem_exists hA m k hm_odd hk_le_2000

  -- Leverage the uniqueness of odd parts to establish p' = p (implying a = x)
  have hp_eq : p' = p := unique_odd_part hA ha_mem hx hm_odd ha_eq hx_eq

  -- Substitute to assert that our original power of two `p` is strictly bounded below by `k`
  have hk_le_p : k ≤ p := by
    rw [← hp_eq]
    exact hk_le_p'

  -- Lower-bound the intermediate decomposition configuration
  have h64 : 64 ≤ m * 2^k := calc_lower_bound m k hm_bounds hk_le_6 hk_gt_2000

  -- Apply monotonicity across the powers to bridge k with p
  have h_pow : 2^k ≤ 2^p := pow_le_pow_right' (by decide) hk_le_p
  have h_le : m * 2^k ≤ m * 2^p := Nat.mul_le_mul_left m h_pow

  -- Substitute the definition of x back in to achieve the target formulation
  rw [hx_eq]
  exact Nat.le_trans h64 h_le

theorem min_ge_64 {A : Finset ℕ} (hA : Acond A) : (64 : WithTop ℕ) ≤ Finset.min A :=
by
  -- Convert the lower-bound goal on `Finset.min A` to a universal statement over the elements of A
  rw [Finset.le_min_iff]
  intro x hx
  -- Use our newly declared lemma to lower-bound the extracted element x
  have h : 64 ≤ x := Acond_elem_ge_64 hA hx
  -- Cast the standard inequality to resolve the boundary with `WithTop` using Mathlib's built-in rule
  exact WithTop.coe_le_coe.mpr h

theorem A0_subset_proof : A0 ⊆ Finset.Icc 1 2000 :=
by
  intro x hx
  simp only [A0, Finset.mem_image] at hx
  rcases hx with ⟨m, hm, rfl⟩
  simp only [Odd2000, Finset.mem_filter, Finset.mem_Icc] at hm
  rcases hm with ⟨⟨h1, h2000⟩, hodd⟩
  rw [Finset.mem_Icc]
  dsimp [A0_fun, c_fun]
  split_ifs
  · have h_pow : (2 : ℕ) ^ 6 = 64 := by rfl
    rw [h_pow]
    constructor <;> omega
  · have h_pow : (2 : ℕ) ^ 5 = 32 := by rfl
    rw [h_pow]
    constructor <;> omega
  · have h_pow : (2 : ℕ) ^ 4 = 16 := by rfl
    rw [h_pow]
    constructor <;> omega
  · have h_pow : (2 : ℕ) ^ 3 = 8 := by rfl
    rw [h_pow]
    constructor <;> omega
  · have h_pow : (2 : ℕ) ^ 2 = 4 := by rfl
    rw [h_pow]
    constructor <;> omega
  · have h_pow : (2 : ℕ) ^ 1 = 2 := by rfl
    rw [h_pow]
    constructor <;> omega
  · have h_pow : (2 : ℕ) ^ 0 = 1 := by rfl
    rw [h_pow]
    constructor <;> omega

theorem A0_fun_inj_on_Odd2000 : ∀ a ∈ Odd2000, ∀ b ∈ Odd2000, A0_fun a = A0_fun b → a = b :=
by
  intro a ha b hb h_eq
  have ha_odd : Odd a := by
    rw [Odd2000, Finset.mem_filter] at ha
    exact ha.2
  have hb_odd : Odd b := by
    rw [Odd2000, Finset.mem_filter] at hb
    exact hb.2
  change a * 2 ^ c_fun a = b * 2 ^ c_fun b at h_eq

  have H : ∀ (n m : ℕ) (x y : ℕ), Odd x → Odd y → x * 2^n = y * 2^m → n = m ∧ x = y := by
    intro n
    induction n with
    | zero =>
      intro m x y hx hy h
      cases m with
      | zero =>
        have hz : 2 ^ 0 = 1 := rfl
        rw [hz] at h
        exact ⟨rfl, by omega⟩
      | succ m' =>
        have hz : 2 ^ 0 = 1 := rfl
        have hs : 2 ^ Nat.succ m' = 2 ^ m' * 2 := rfl
        rw [hz, hs] at h
        have h_assoc : y * (2 ^ m' * 2) = (y * 2 ^ m') * 2 := by rw [← mul_assoc]
        rw [h_assoc] at h
        rcases hx with ⟨kx, hkx⟩
        omega
    | succ n' ih =>
      intro m x y hx hy h
      cases m with
      | zero =>
        have hz : 2 ^ 0 = 1 := rfl
        have hs : 2 ^ Nat.succ n' = 2 ^ n' * 2 := rfl
        rw [hz, hs] at h
        have h_assoc : x * (2 ^ n' * 2) = (x * 2 ^ n') * 2 := by rw [← mul_assoc]
        rw [h_assoc] at h
        rcases hy with ⟨ky, hky⟩
        omega
      | succ m' =>
        have hsn : 2 ^ Nat.succ n' = 2 ^ n' * 2 := rfl
        have hsm : 2 ^ Nat.succ m' = 2 ^ m' * 2 := rfl
        rw [hsn, hsm] at h
        have h_assoc1 : x * (2 ^ n' * 2) = (x * 2 ^ n') * 2 := by rw [← mul_assoc]
        have h_assoc2 : y * (2 ^ m' * 2) = (y * 2 ^ m') * 2 := by rw [← mul_assoc]
        rw [h_assoc1, h_assoc2] at h
        have h2 : x * 2 ^ n' = y * 2 ^ m' := by omega
        have h3 := ih m' x y hx hy h2
        rcases h3 with ⟨h3n, h3x⟩
        exact ⟨by omega, h3x⟩

  have h_final := H (c_fun a) (c_fun b) a b ha_odd hb_odd h_eq
  exact h_final.2

theorem Odd2000_card_decide : Odd2000.card = 1000 :=
by
  -- Establish a direct bijection to avoid deep kernel computation
  have h1 : Odd2000 = (Finset.Icc 0 999).image (fun k => 2 * k + 1) := by
    dsimp [Odd2000]
    ext x
    rw [Finset.mem_filter, Finset.mem_image]
    constructor
    · rintro ⟨hx, hk⟩
      rw [Finset.mem_Icc] at hx
      -- Given that `x` is odd, we extract `k` and its mapping equation
      have hk_exists : ∃ k, x = 2 * k + 1 := hk
      rcases hk_exists with ⟨k, rfl⟩
      use k
      constructor
      · rw [Finset.mem_Icc]
        omega
      · rfl
    · rintro ⟨k, hk, rfl⟩
      rw [Finset.mem_Icc] at hk
      constructor
      · rw [Finset.mem_Icc]
        omega
      · exact ⟨k, rfl⟩

  -- Substitute and compute the image cardinality
  rw [h1]
  have h_inj : Function.Injective (fun k : ℕ => 2 * k + 1) := by
    intro a b hab
    -- We must evaluate the anonymous functions before handing over the equation to `omega`
    change 2 * a + 1 = 2 * b + 1 at hab
    omega
  rw [Finset.card_image_of_injective (Finset.Icc 0 999) h_inj]

  -- Evaluates the `Icc` cardinality interval. `rw` automatically applies `rfl` and closes the goal.
  rw [Nat.card_Icc]

theorem A0_card_proof : A0.card = 1000 :=
by
  -- From the definition of A0
  have h1 : A0 = Odd2000.image A0_fun := rfl
  rw [h1]

  -- The cardinality is preserved if the mapping is injective on the given set
  have h2 : (Odd2000.image A0_fun).card = Odd2000.card := by
    apply Finset.card_image_of_injOn
    exact fun a ha b hb hab => A0_fun_inj_on_Odd2000 a ha b hb hab

  -- Applying this injectivity principle and substituting the known cardinality of 1000
  rw [h2, Odd2000_card_decide]

theorem A0_no_dvd_proof : ∀ a ∈ A0, ∀ b ∈ A0, a ≠ b → ¬ a ∣ b :=
by
  intros a ha b hb hab hdvd
  rw [A0, Finset.mem_image] at ha hb
  obtain ⟨m1, hm1_mem, rfl⟩ := ha
  obtain ⟨m2, hm2_mem, rfl⟩ := hb
  rw [Odd2000, Finset.mem_filter, Finset.mem_Icc] at hm1_mem hm2_mem
  obtain ⟨⟨h1_m1, _⟩, hm1_odd⟩ := hm1_mem
  obtain ⟨⟨_, h2_m2⟩, hm2_odd⟩ := hm2_mem

  obtain ⟨c, hc⟩ := hdvd
  have h_eq_div : m2 * 2 ^ c_fun m2 = m1 * 2 ^ c_fun m1 * c := hc

  -- Prove m1 is coprime to 2
  have hm1_cop : Nat.Coprime m1 2 := by
    have hdvd2 : Nat.gcd m1 2 ∣ 2 := Nat.gcd_dvd_right m1 2
    have h_cases : Nat.gcd m1 2 = 1 ∨ Nat.gcd m1 2 = 2 := by
      have h_pos : 0 < Nat.gcd m1 2 := by
        by_contra hc
        have h0 : Nat.gcd m1 2 = 0 := by omega
        have : 2 = 0 := by
          obtain ⟨x, hx⟩ := hdvd2
          calc 2 = Nat.gcd m1 2 * x := hx
               _ = 0 * x := by rw [h0]
               _ = 0 := by ring
        omega
      have h_le : Nat.gcd m1 2 ≤ 2 := Nat.le_of_dvd (by decide) hdvd2
      omega
    rcases h_cases with h1 | h2
    · exact h1
    · have hdvd1 : Nat.gcd m1 2 ∣ m1 := Nat.gcd_dvd_left m1 2
      rw [h2] at hdvd1
      obtain ⟨y, hy⟩ := hdvd1
      obtain ⟨q1, hq1⟩ := hm1_odd
      omega

  have hm1_cop_pow : Nat.Coprime m1 (2 ^ c_fun m2) := Nat.Coprime.pow_right (c_fun m2) hm1_cop

  have hdvd1 : m1 ∣ m2 * 2 ^ c_fun m2 := ⟨2 ^ c_fun m1 * c, by
    calc m2 * 2 ^ c_fun m2 = m1 * 2 ^ c_fun m1 * c := h_eq_div
      _ = m1 * (2 ^ c_fun m1 * c) := by ring⟩

  have hm1_dvd_m2 : m1 ∣ m2 := Nat.Coprime.dvd_of_dvd_mul_right hm1_cop_pow hdvd1

  obtain ⟨k, hk⟩ := hm1_dvd_m2

  have hk_neq_1 : k ≠ 1 := by
    rintro rfl
    have : m1 = m2 := by omega
    subst this
    exact hab rfl

  have hk_ge_3 : k ≥ 3 := by
    by_contra h
    have : k = 0 ∨ k = 1 ∨ k = 2 := by omega
    rcases this with rfl | rfl | rfl
    · obtain ⟨q2, hq2⟩ := hm2_odd
      have : m2 = 0 := by
        calc m2 = m1 * 0 := hk
             _ = 0 := by ring
      omega
    · exact hk_neq_1 rfl
    · obtain ⟨q2, hq2⟩ := hm2_odd
      have : m2 = 2 * m1 := by
        calc m2 = m1 * 2 := hk
             _ = 2 * m1 := by ring
      omega

  have hm2_ge : m2 ≥ 3 * m1 := by
    have : m1 * 3 ≤ m1 * k := Nat.mul_le_mul_left m1 hk_ge_3
    omega

  have hm1_pos : 0 < m1 := by omega
  have h_eq2 : k * 2 ^ c_fun m2 = 2 ^ c_fun m1 * c :=
    Nat.eq_of_mul_eq_mul_left hm1_pos (by
      calc m1 * (k * 2 ^ c_fun m2) = m1 * k * 2 ^ c_fun m2 := by ring
        _ = m2 * 2 ^ c_fun m2 := by rw [← hk]
        _ = m1 * 2 ^ c_fun m1 * c := h_eq_div
        _ = m1 * (2 ^ c_fun m1 * c) := by ring)

  -- Prove k is coprime to 2 naturally using GCD mechanics
  have hk_cop : Nat.Coprime k 2 := by
    have hdvd2 : Nat.gcd k 2 ∣ 2 := Nat.gcd_dvd_right k 2
    have h_cases : Nat.gcd k 2 = 1 ∨ Nat.gcd k 2 = 2 := by
      have h_pos : 0 < Nat.gcd k 2 := by
        by_contra hc
        have h0 : Nat.gcd k 2 = 0 := by omega
        have : 2 = 0 := by
          obtain ⟨x, hx⟩ := hdvd2
          calc 2 = Nat.gcd k 2 * x := hx
               _ = 0 * x := by rw [h0]
               _ = 0 := by ring
        omega
      have h_le : Nat.gcd k 2 ≤ 2 := Nat.le_of_dvd (by decide) hdvd2
      omega
    rcases h_cases with h1 | h2
    · exact h1
    · have hdvd1 : Nat.gcd k 2 ∣ k := Nat.gcd_dvd_left k 2
      rw [h2] at hdvd1
      obtain ⟨y, hy⟩ := hdvd1
      obtain ⟨q2, hq2⟩ := hm2_odd
      have hm2_even : m2 = 2 * (m1 * y) := by
        calc m2 = m1 * k := hk
          _ = m1 * (2 * y) := by rw [hy]
          _ = 2 * (m1 * y) := by ring
      omega

  have hk_cop_pow : Nat.Coprime k (2 ^ c_fun m1) := Nat.Coprime.pow_right (c_fun m1) hk_cop
  have h_2_coprime : Nat.Coprime (2 ^ c_fun m1) k := Nat.Coprime.symm hk_cop_pow

  have h_dvd_pow : 2 ^ c_fun m1 ∣ k * 2 ^ c_fun m2 := ⟨c, h_eq2⟩

  have h_pow_dvd : 2 ^ c_fun m1 ∣ 2 ^ c_fun m2 := Nat.Coprime.dvd_of_dvd_mul_left h_2_coprime h_dvd_pow

  -- Prove c_fun m1 ≤ c_fun m2 ensuring valid exponents and coefficients scaling
  have h_v1_le_v2 : c_fun m1 ≤ c_fun m2 := by
    by_contra h_gt
    have hd_pos : c_fun m1 - c_fun m2 ≥ 1 := by omega
    obtain ⟨x, hx⟩ := h_pow_dvd
    have h_exp : c_fun m1 = c_fun m2 + (c_fun m1 - c_fun m2) := by omega
    rw [h_exp] at hx
    have h_eq : 2 ^ c_fun m2 * 1 = 2 ^ c_fun m2 * (2 ^ (c_fun m1 - c_fun m2) * x) := by
      calc 2 ^ c_fun m2 * 1 = 2 ^ c_fun m2 := by ring
        _ = 2 ^ (c_fun m2 + (c_fun m1 - c_fun m2)) * x := hx
        _ = (2 ^ c_fun m2 * 2 ^ (c_fun m1 - c_fun m2)) * x := by rw [pow_add]
        _ = 2 ^ c_fun m2 * (2 ^ (c_fun m1 - c_fun m2) * x) := by ring
    have h_cancel : 1 = 2 ^ (c_fun m1 - c_fun m2) * x := Nat.eq_of_mul_eq_mul_left (by positivity) h_eq
    have h_k : ∃ k, c_fun m1 - c_fun m2 = k + 1 := ⟨c_fun m1 - c_fun m2 - 1, by omega⟩
    obtain ⟨k, hk⟩ := h_k
    have h_pow : 2 ^ (c_fun m1 - c_fun m2) = 2 * 2 ^ k := by
      rw [hk, pow_add, pow_one]
      ring
    have h_cancel2 : 1 = 2 * (2 ^ k * x) := by
      calc 1 = 2 ^ (c_fun m1 - c_fun m2) * x := h_cancel
        _ = (2 * 2 ^ k) * x := by rw [h_pow]
        _ = 2 * (2 ^ k * x) := by ring
    omega

  have h_bound : ∀ m, m ≤ 2000 → m * 3 ^ c_fun m < 2187 := by
    intro m hm
    unfold c_fun
    split_ifs
    · change m * 729 < 2187; omega
    · change m * 243 < 2187; omega
    · change m * 81 < 2187; omega
    · change m * 27 < 2187; omega
    · change m * 9 < 2187; omega
    · change m * 3 < 2187; omega
    · change m * 1 < 2187; omega

  have h_c_fun_lower : ∀ m v, m ≥ 1 → v ≤ 6 → m * 3 ^ (v + 1) < 2187 → c_fun m > v := by
    intro m v hm_pos hv
    have h_cases : v = 0 ∨ v = 1 ∨ v = 2 ∨ v = 3 ∨ v = 4 ∨ v = 5 ∨ v = 6 := by omega
    rcases h_cases with rfl | rfl | rfl | rfl | rfl | rfl | rfl
    · change m * 3 < 2187 → c_fun m > 0; intro hm; unfold c_fun; split_ifs <;> omega
    · change m * 9 < 2187 → c_fun m > 1; intro hm; unfold c_fun; split_ifs <;> omega
    · change m * 27 < 2187 → c_fun m > 2; intro hm; unfold c_fun; split_ifs <;> omega
    · change m * 81 < 2187 → c_fun m > 3; intro hm; unfold c_fun; split_ifs <;> omega
    · change m * 243 < 2187 → c_fun m > 4; intro hm; unfold c_fun; split_ifs <;> omega
    · change m * 729 < 2187 → c_fun m > 5; intro hm; unfold c_fun; split_ifs <;> omega
    · change m * 2187 < 2187 → c_fun m > 6; intro hm; unfold c_fun; split_ifs <;> omega

  have h_v2_le_6 : c_fun m2 ≤ 6 := by
    unfold c_fun; split_ifs <;> omega

  have h_mul_pow : 3 * m1 * 3 ^ c_fun m2 = m1 * 3 ^ (c_fun m2 + 1) := by
    calc 3 * m1 * 3 ^ c_fun m2 = m1 * (3 ^ c_fun m2 * 3) := by ring
      _ = m1 * (3 ^ c_fun m2 * 3 ^ 1) := by rw [pow_one]
      _ = m1 * 3 ^ (c_fun m2 + 1) := by rw [← pow_add]

  have h_m1_pow : m1 * 3 ^ (c_fun m2 + 1) < 2187 := by
    have h1 : m1 * 3 ^ (c_fun m2 + 1) = 3 * m1 * 3 ^ c_fun m2 := h_mul_pow.symm
    have h2 : m2 * 3 ^ c_fun m2 < 2187 := h_bound m2 h2_m2
    have h3 : 3 * m1 ≤ m2 := hm2_ge
    have h_le : 3 * m1 * 3 ^ c_fun m2 ≤ m2 * 3 ^ c_fun m2 := Nat.mul_le_mul_right (3 ^ c_fun m2) h3
    omega

  have h_v1_gt_v2 : c_fun m1 > c_fun m2 :=
    h_c_fun_lower m1 (c_fun m2) h1_m1 h_v2_le_6 h_m1_pow

  omega

theorem A0_cond : Acond A0 :=
⟨A0_subset_proof, A0_card_proof, A0_no_dvd_proof⟩

theorem A0_min_le_64 : Finset.min A0 ≤ 64 :=
by
  have h1 : 1 ∈ Odd2000 := by
    simp only [Odd2000, Finset.mem_filter, Finset.mem_Icc]
    refine ⟨⟨by decide, by decide⟩, 0, rfl⟩
  have h2 : 64 ∈ A0 := by
    simp only [A0, Finset.mem_image]
    exact ⟨1, h1, rfl⟩
  apply Finset.min_le
  exact h2

theorem A0_min_ge_64 : 64 ≤ Finset.min A0 :=
by
  apply Finset.le_min
  intro a ha
  rw [A0, Finset.mem_image] at ha
  rcases ha with ⟨m, hm, rfl⟩
  -- Isolate the standard `ℕ` arithmetic to prevent `norm_cast` loops
  have h_le : 64 ≤ A0_fun m := by
    rw [Odd2000, Finset.mem_filter, Finset.mem_Icc] at hm
    rcases hm with ⟨⟨h_m_ge_1, _h_m_le_2000⟩, h_odd⟩
    rcases h_odd with ⟨k, hk⟩
    unfold A0_fun c_fun
    split_ifs
    · norm_num; omega
    · norm_num; omega
    · norm_num; omega
    · norm_num; omega
    · norm_num; omega
    · norm_num; omega
    · norm_num; omega
  -- Safely re-introduce the coercions to `WithTop ℕ`
  exact WithTop.coe_le_coe.mpr h_le

theorem A0_min : Finset.min A0 = 64 :=
by
  exact le_antisymm A0_min_le_64 A0_min_ge_64

theorem PBBasic011 : sInf { Finset.min A | (A : Finset ℕ) (_ : Acond A) } = 64 :=
by
  apply le_antisymm
  · apply sInf_le
    -- `A0` satisfies `A0_cond`, hence 64 belongs to the described set composition explicitly.
    exact ⟨A0, A0_cond, A0_min⟩
  · apply le_sInf
    -- For any element mapped into the set, unfold the set composition to extract bounded variables/conditions.
    rintro _ ⟨A, hA, rfl⟩
    -- Having the hypothesis that A matches the global bound conditions, apply our universal lower-bound lemma.
    exact min_ge_64 hA
