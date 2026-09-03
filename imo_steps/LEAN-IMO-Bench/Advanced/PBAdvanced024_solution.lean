import Mathlib
def D (P : ℚ → ℚ) (x y : ℚ) : ℚ := P (x + P y) - P x - y

def S_func (P : ℚ → ℚ) (x : ℚ) : ℚ := P x + P (-x)

theorem h_to_D_mul_D {P : ℚ → ℚ}
  (h : ∀ a b, (P (b - P a) + a - P b) * (P (a + P (b - P a)) - b) = 0) (x y : ℚ) :
  D P x y * D P y x = 0 :=
by
  have h1 := h x (y + P x)
  have h2 : y + P x - P x = y := by ring
  rw [h2] at h1
  calc
    D P x y * D P y x = - ((P y + x - P (y + P x)) * (P (x + P y) - (y + P x))) := by
      simp only [D]
      ring
    _ = - 0 := by rw [h1]
    _ = 0 := by ring

theorem helper_S_func {P : ℚ → ℚ} (h : ∀ x y, D P x y * D P y x = 0) (x y : ℚ)
  (hx : S_func P x ≠ 0) (hy : S_func P y ≠ 0) : S_func P x = S_func P y :=
by
  have hDxx : ∀ z, D P z z = 0 := by
    intro z
    have h1 := h z z
    cases mul_eq_zero.mp h1 with
    | inl h2 => exact h2
    | inr h2 => exact h2

  have hP_id : ∀ z, P (z + P z) = P z + z := by
    intro z
    have h1 := hDxx z
    dsimp only [D] at h1
    linarith

  have lemA : ∀ z c, P (z + c) = P z → c = 0 := by
    intro z c hc
    have h1 : D P z (z + c) = -c := by
      dsimp only [D]
      rw [hc, hP_id z]
      ring
    have h2 : D P (z + c) z = c := by
      dsimp only [D]
      have h_id := hP_id (z + c)
      rw [hc] at h_id
      rw [h_id, hc]
      ring
    have h3 := h z (z + c)
    rw [h1, h2] at h3
    cases mul_eq_zero.mp h3 with
    | inl h4 => linarith
    | inr h4 => exact h4

  have lemB : ∀ u v, D P u v = 0 → P (P u) = u + S_func P v ∨ S_func P v = 0 := by
    intro u v huv
    have h_uv : P (u + P v) = P u + v := by
      dsimp only [D] at huv
      linarith
    have h1 : D P (u + P v) (-v) = P (u + S_func P v) - P u := by
      dsimp only [D, S_func]
      rw [h_uv]
      have h_add : u + P v + P (-v) = u + (P v + P (-v)) := by ring
      rw [h_add]
      ring
    have h2 : D P (-v) (u + P v) = P (P u) - S_func P v - u := by
      dsimp only [D, S_func]
      rw [h_uv]
      have h_add2 : -v + (P u + v) = P u := by ring
      rw [h_add2]
      ring
    have h3 := h (u + P v) (-v)
    rw [h1, h2] at h3
    cases mul_eq_zero.mp h3 with
    | inl h4 =>
      right
      have h5 : P (u + S_func P v) = P u := by linarith
      exact lemA u (S_func P v) h5
    | inr h4 =>
      left
      linarith

  have h_xy := h x y
  cases mul_eq_zero.mp h_xy with
  | inl h1 =>
    have h2 := lemB x y h1
    cases h2 with
    | inl h3 =>
      have h4 := hDxx x
      have h5 := lemB x x h4
      cases h5 with
      | inl h6 => linarith
      | inr h6 =>
        exfalso
        exact hx h6
    | inr h3 =>
      exfalso
      exact hy h3
  | inr h1 =>
    have h2 := lemB y x h1
    cases h2 with
    | inl h3 =>
      have h4 := hDxx y
      have h5 := lemB y y h4
      cases h5 with
      | inl h6 => linarith
      | inr h6 =>
        exfalso
        exact hy h6
    | inr h3 =>
      exfalso
      exact hx h3

theorem S_func_takes_at_most_two_values {P : ℚ → ℚ}
  (h : ∀ x y, D P x y * D P y x = 0) (x y : ℚ) :
  S_func P x = 0 ∨ S_func P y = 0 ∨ S_func P x = S_func P y :=
by
  by_cases hx : S_func P x = 0
  · left
    exact hx
  · right
    by_cases hy : S_func P y = 0
    · left
      exact hy
    · right
      exact helper_S_func h x y hx hy

theorem S_eq_zero_or_c {P : ℚ → ℚ}
  (h : ∀ a b, (P (b - P a) + a - P b) * (P (a + P (b - P a)) - b) = 0) :
  ∃ c : ℚ, ∀ x : ℚ, S_func P x = 0 ∨ S_func P x = c :=
by
  have hD : ∀ x y, D P x y * D P y x = 0 := h_to_D_mul_D h
  have hS : ∀ x y, S_func P x = 0 ∨ S_func P y = 0 ∨ S_func P x = S_func P y :=
    S_func_takes_at_most_two_values hD
  by_cases h_all : ∃ x, S_func P x ≠ 0
  · rcases h_all with ⟨x_0, hx0⟩
    use S_func P x_0
    intro x
    have h_or := hS x x_0
    rcases h_or with h1 | h23
    · exact Or.inl h1
    · rcases h23 with h2 | h3
      · exact False.elim (hx0 h2)
      · exact Or.inr h3
  · use 0
    intro x
    have h_eq : S_func P x = 0 := by
      by_contra h_neq
      exact h_all ⟨x, h_neq⟩
    exact Or.inl h_eq

theorem subset_zero_c_encard_le_two {c : ℚ} {s : Set ℚ} (h : s ⊆ {0, c}) : s.encard ≤ 2 :=
by
  -- Monotonicity: Since s ⊆ {0, c}, its extended cardinality is bounded by {0, c}'s
  apply le_trans (Set.encard_le_encard h)

  -- Explicitly view {0, c} as an insertion
  have h_ins : ({0, c} : Set ℚ) = insert (0 : ℚ) {c} := rfl
  rw [h_ins]

  -- Evaluate the bound depending on whether c is 0
  by_cases hc : (0 : ℚ) = c
  · rw [hc]
    -- If 0 = c, then {0, c} evaluates to just {c}
    have h_insert : insert c ({c} : Set ℚ) = {c} := Set.insert_eq_of_mem (Set.mem_singleton c)
    rw [h_insert, Set.encard_singleton]
    -- Prove 1 ≤ 2 securely under WithTop bounds
    have h12 : ((1 : ℕ) : WithTop ℕ) ≤ ((2 : ℕ) : WithTop ℕ) := WithTop.coe_le_coe.mpr (by decide)
    exact h12

  · -- If 0 ≠ c, 0 is distinct and naturally doesn't belong to {c}
    have hc' : (0 : ℚ) ∉ ({c} : Set ℚ) := by
      intro h_mem
      rw [Set.mem_singleton_iff] at h_mem
      exact hc h_mem

    -- Use the extended cardinality rules for distinct elements
    rw [Set.encard_insert_of_notMem hc', Set.encard_singleton]
    -- Goal becomes `1 + 1 ≤ 2` structurally, which evaluates by reflexivity in WithTop ℕ
    exact le_rfl

theorem good_P_encard_le_two (IsGood : (ℚ → ℚ) → Prop)
    (IsGood_def : ∀ P, IsGood P ↔ ∀ a b,
      (P (b - P a) + a - P b) * (P (a + P (b - P a)) - b) = 0)
    {P : ℚ → ℚ} (h : IsGood P) : {P a + P (-a) | (a : ℚ)}.encard ≤ 2 :=
by
  -- 1. Extract the algebraic identity from the given hypothesis using IsGood_def
  have H : ∀ a b, (P (b - P a) + a - P b) * (P (a + P (b - P a)) - b) = 0 := by
    exact (IsGood_def P).mp h

  -- 2. Obtain our constant `c` such that the range of the symmetric sum is constrained
  rcases S_eq_zero_or_c H with ⟨c, hc⟩

  -- 3. Prove that the target set `{P a + P (-a) | a : ℚ}` is a subset of `{0, c}`
  have h_sub : {P a + P (-a) | (a : ℚ)} ⊆ {0, c} := by
    intro x hx
    -- Unwrap the set-builder (range) notation
    rcases hx with ⟨a, rfl⟩
    -- Retrieve the fact that P a + P (-a) is 0 or c
    have h_cases := hc a
    -- Expand S_func's definition to structurally match P a + P (-a) exactly
    dsimp [S_func] at h_cases
    -- Unfold set insertions/singleton checks to expose the disjunction logic
    simp only [Set.mem_insert_iff, Set.mem_singleton_iff]
    exact h_cases

  -- 4. Finalise the upper bound constraint using our external set lemma
  exact subset_zero_c_encard_le_two h_sub

theorem good_P_finite_encard (IsGood : (ℚ → ℚ) → Prop)
    (IsGood_def : ∀ P, IsGood P ↔ ∀ a b,
      (P (b - P a) + a - P b) * (P (a + P (b - P a)) - b) = 0)
    {P : ℚ → ℚ} (h : IsGood P) : {P a + P (-a) | (a : ℚ)}.encard < ⊤ :=
by
  apply lt_of_le_of_lt (good_P_encard_le_two IsGood IsGood_def h)
  decide

theorem exists_good_P_encard_eq_two (IsGood : (ℚ → ℚ) → Prop)
    (IsGood_def : ∀ P, IsGood P ↔ ∀ a b,
      (P (b - P a) + a - P b) * (P (a + P (b - P a)) - b) = 0) :
    ∃ P : ℚ → ℚ, IsGood P ∧ {P a + P (-a) | (a : ℚ)}.encard = 2 :=
by
  let P : ℚ → ℚ := fun x => (2 : ℚ) * (Int.floor x : ℚ) - x
  use P

  have floor_shift : ∀ X : ℚ, ∀ Z : ℤ, Int.floor (X + (2 : ℚ) * (Z : ℚ)) = Int.floor X + 2 * Z := by
    intro X Z
    have h1 := Int.floor_le X
    have h2 := Int.lt_floor_add_one X
    have h3 : ((Int.floor X + 2 * Z : ℤ) : ℚ) ≤ X + (2 : ℚ) * (Z : ℚ) := by
      push_cast
      linarith
    have h4 : X + (2 : ℚ) * (Z : ℚ) < ((Int.floor X + 2 * Z : ℤ) : ℚ) + 1 := by
      push_cast
      linarith
    exact Int.floor_eq_iff.mpr ⟨h3, h4⟩

  have H_E : ∀ A Y : ℚ, P (A + P Y) - P A - Y = (2 : ℚ) * ((Int.floor (A - Y + (2 : ℚ) * (Int.floor Y : ℚ)) : ℚ) - (Int.floor A : ℚ) - (Int.floor Y : ℚ)) := by
    intro A Y
    dsimp [P]
    have h_inner : A + ((2 : ℚ) * (Int.floor Y : ℚ) - Y) = A - Y + (2 : ℚ) * (Int.floor Y : ℚ) := by ring
    rw [h_inner]
    ring

  have H_E2 : ∀ A Y : ℚ, P (A + P Y) - P A - Y = (2 : ℚ) * ((Int.floor (A - Y) : ℚ) + (Int.floor Y : ℚ) - (Int.floor A : ℚ)) := by
    intro A Y
    rw [H_E A Y]
    have h_shift := floor_shift (A - Y) (Int.floor Y)
    rw [h_shift]
    push_cast
    ring

  have H_zero_int : ∀ (x y : ℚ), (Int.floor (y - x) + Int.floor x - Int.floor y = 0) ∨ (Int.floor (x - y) + Int.floor y - Int.floor x = 0) := by
    intro x y
    let k := Int.floor (x - y)
    let l := Int.floor (y - x)
    let m := Int.floor x
    let n := Int.floor y
    have hk1 : (k : ℚ) ≤ x - y := Int.floor_le (x - y)
    have hk2 : x - y < (k : ℚ) + 1 := Int.lt_floor_add_one (x - y)
    have hl1 : (l : ℚ) ≤ y - x := Int.floor_le (y - x)
    have hl2 : y - x < (l : ℚ) + 1 := Int.lt_floor_add_one (y - x)
    have hm1 : (m : ℚ) ≤ x := Int.floor_le x
    have hm2 : x < (m : ℚ) + 1 := Int.lt_floor_add_one x
    have hn1 : (n : ℚ) ≤ y := Int.floor_le y
    have hn2 : y < (n : ℚ) + 1 := Int.lt_floor_add_one y
    have h1_rat : ((k + n : ℤ) : ℚ) < ((m + 1 : ℤ) : ℚ) := by push_cast; linarith
    have h1 : k + n < m + 1 := Int.cast_lt.mp h1_rat
    have h2_rat : ((m : ℤ) : ℚ) < ((k + n + 2 : ℤ) : ℚ) := by push_cast; linarith
    have h2 : m < k + n + 2 := Int.cast_lt.mp h2_rat
    have h3_rat : ((l + m : ℤ) : ℚ) < ((n + 1 : ℤ) : ℚ) := by push_cast; linarith
    have h3 : l + m < n + 1 := Int.cast_lt.mp h3_rat
    have h4_rat : ((n : ℤ) : ℚ) < ((l + m + 2 : ℤ) : ℚ) := by push_cast; linarith
    have h4 : n < l + m + 2 := Int.cast_lt.mp h4_rat
    have h5_rat : ((0 : ℤ) : ℚ) < ((k + l + 2 : ℤ) : ℚ) := by push_cast; linarith
    have h5 : 0 < k + l + 2 := Int.cast_lt.mp h5_rat
    have h_or : l + m - n = 0 ∨ k + n - m = 0 := by omega
    exact h_or

  constructor
  · rw [IsGood_def]
    intro a b
    have H_factor1 : P (b - P a) + a - P b = - (P ((b - P a) + P a) - P (b - P a) - a) := by
      have h_b : (b - P a) + P a = b := by ring
      rw [h_b]
      ring
    have H_factor2 : P (a + P (b - P a)) - b = P (a + P (b - P a)) - P a - (b - P a) := by ring
    calc (P (b - P a) + a - P b) * (P (a + P (b - P a)) - b)
      _ = - (P ((b - P a) + P a) - P (b - P a) - a) * (P (a + P (b - P a)) - P a - (b - P a)) := by
        rw [H_factor1, H_factor2]
      _ = - ((2 : ℚ) * ((Int.floor (b - P a - a) : ℚ) + (Int.floor a : ℚ) - (Int.floor (b - P a) : ℚ))) * ((2 : ℚ) * ((Int.floor (a - (b - P a)) : ℚ) + (Int.floor (b - P a) : ℚ) - (Int.floor a : ℚ))) := by
        rw [H_E2 (b - P a) a, H_E2 a (b - P a)]
      _ = - (4 : ℚ) * (((Int.floor (b - P a - a) : ℚ) + (Int.floor a : ℚ) - (Int.floor (b - P a) : ℚ)) * ((Int.floor (a - (b - P a)) : ℚ) + (Int.floor (b - P a) : ℚ) - (Int.floor a : ℚ))) := by ring
      _ = 0 := by
        have H_z := H_zero_int a (b - P a)
        rcases H_z with hl | hk
        · have hl_cast : (Int.floor (b - P a - a) : ℚ) + (Int.floor a : ℚ) - (Int.floor (b - P a) : ℚ) = 0 := by
            calc (Int.floor (b - P a - a) : ℚ) + (Int.floor a : ℚ) - (Int.floor (b - P a) : ℚ) = ((Int.floor (b - P a - a) + Int.floor a - Int.floor (b - P a) : ℤ) : ℚ) := by push_cast; rfl
              _ = ((0 : ℤ) : ℚ) := by rw [hl]
              _ = 0 := by norm_num
          rw [hl_cast]
          ring
        · have hk_cast : (Int.floor (a - (b - P a)) : ℚ) + (Int.floor (b - P a) : ℚ) - (Int.floor a : ℚ) = 0 := by
            calc (Int.floor (a - (b - P a)) : ℚ) + (Int.floor (b - P a) : ℚ) - (Int.floor a : ℚ) = ((Int.floor (a - (b - P a)) + Int.floor (b - P a) - Int.floor a : ℤ) : ℚ) := by push_cast; rfl
              _ = ((0 : ℤ) : ℚ) := by rw [hk]
              _ = 0 := by norm_num
          rw [hk_cast]
          ring
  · have H_S : {P a + P (-a) | (a : ℚ)} = {(0 : ℚ), -2} := by
      ext x
      simp only [Set.mem_setOf_eq, Set.mem_insert_iff, Set.mem_singleton_iff]
      constructor
      · rintro ⟨a, rfl⟩
        dsimp [P]
        have h_val : (2 : ℚ) * (Int.floor a : ℚ) - a + ((2 : ℚ) * (Int.floor (-a) : ℚ) - (-a)) = (2 : ℚ) * ((Int.floor a : ℚ) + (Int.floor (-a) : ℚ)) := by ring
        rw [h_val]
        have H_floor : Int.floor a + Int.floor (-a) = 0 ∨ Int.floor a + Int.floor (-a) = -1 := by
          let m := Int.floor a
          let n := Int.floor (-a)
          have hm1 : (m : ℚ) ≤ a := Int.floor_le a
          have hm2 : a < (m : ℚ) + 1 := Int.lt_floor_add_one a
          have hn1 : (n : ℚ) ≤ -a := Int.floor_le (-a)
          have hn2 : -a < (n : ℚ) + 1 := Int.lt_floor_add_one (-a)
          have h1_rat : ((m + n : ℤ) : ℚ) ≤ ((0 : ℤ) : ℚ) := by push_cast; linarith
          have h1_int : m + n ≤ 0 := Int.cast_le.mp h1_rat
          have h2_rat : ((-2 : ℤ) : ℚ) < ((m + n : ℤ) : ℚ) := by push_cast; linarith
          have h2_int : -2 < m + n := Int.cast_lt.mp h2_rat
          have h_or : m + n = 0 ∨ m + n = -1 := by omega
          exact h_or
        rcases H_floor with h0 | h1
        · left
          have h0_cast : (Int.floor a : ℚ) + (Int.floor (-a) : ℚ) = 0 := by
            calc (Int.floor a : ℚ) + (Int.floor (-a) : ℚ) = ((Int.floor a + Int.floor (-a) : ℤ) : ℚ) := by push_cast; rfl
              _ = ((0 : ℤ) : ℚ) := by rw [h0]
              _ = 0 := by norm_num
          rw [h0_cast]
          ring
        · right
          have h1_cast : (Int.floor a : ℚ) + (Int.floor (-a) : ℚ) = -1 := by
            calc (Int.floor a : ℚ) + (Int.floor (-a) : ℚ) = ((Int.floor a + Int.floor (-a) : ℤ) : ℚ) := by push_cast; rfl
              _ = ((-1 : ℤ) : ℚ) := by rw [h1]
              _ = -1 := by norm_num
          rw [h1_cast]
          ring
      · rintro (rfl | rfl)
        · use 0
          dsimp [P]
          have h0 : Int.floor (0 : ℚ) = 0 := by
            apply Int.floor_eq_iff.mpr
            norm_num
          have h0_neg : Int.floor (-(0 : ℚ)) = 0 := by
            apply Int.floor_eq_iff.mpr
            norm_num
          rw [h0, h0_neg]
          norm_num
        · use 1 / 2
          dsimp [P]
          have h1 : Int.floor ((1 / 2 : ℚ)) = 0 := by
            apply Int.floor_eq_iff.mpr
            norm_num
          have h2 : Int.floor (-(1 / 2 : ℚ)) = -1 := by
            apply Int.floor_eq_iff.mpr
            norm_num
          rw [h1, h2]
          norm_num
    rw [H_S]
    rw [Set.encard_eq_two]
    use 0, -2
    refine ⟨by norm_num, rfl⟩

theorem PBAdvanced024 (IsGood : (ℚ → ℚ) → Prop)
    (IsGood_def : ∀ P, IsGood P ↔ ∀ a b,
      (P (b - P a) + a - P b) * (P (a + P (b - P a)) - b) = 0) : (∀ P, IsGood P → {P a + P (- a) | (a : ℚ)}.encard < ⊤) ∧
      IsGreatest {{P a + P (-a) | (a : ℚ)}.encard | (P : ℚ → ℚ) (_ : IsGood P)} 2 :=
by
  constructor
  · intro P hP
    exact good_P_finite_encard IsGood IsGood_def hP
  · constructor
    · rcases exists_good_P_encard_eq_two IsGood IsGood_def with ⟨P, hP, h_encard⟩
      exact ⟨P, hP, h_encard⟩
    · rintro x ⟨P, hP, hx⟩
      rw [← hx]
      exact good_P_encard_le_two IsGood IsGood_def hP
