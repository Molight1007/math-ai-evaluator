import Mathlib
open Relation
def operation (x x' : ℕ) : Prop :=
  x' = x + 2 ∨ x' = 3 * x
def single_step (p q : ℕ × ℕ) : Prop :=
  operation p.fst q.fst ∧ operation p.snd q.snd
def reachable (p q : ℕ × ℕ) : Prop :=
  ReflTransGen single_step p q
def eventually_equal (a b : ℕ) : Prop :=
  ∃ x : ℕ, reachable (a, b) (x, x)
def good_pair (a b : ℕ) : Prop :=
  (a % 2 = 0 ∧ b % 2 = 0) ∨ (a % 2 = 1 ∧ b % 2 = 1 ∧ a % 4 = b % 4)

theorem eventually_equal_implies_good_pair (a b : ℕ) : eventually_equal a b → good_pair a b :=
by
  rintro ⟨x, h_reach⟩

  have h_step_lem : ∀ {p q : ℕ × ℕ}, single_step p q → good_pair q.1 q.2 → good_pair p.1 p.2 := by
    rintro ⟨p1, p2⟩ ⟨q1, q2⟩ h_step h_good
    have h1_1 : p1 % 2 = q1 % 2 := by
      have h_op := h_step.1
      dsimp [operation] at h_op
      rcases h_op with rfl | rfl
      · omega
      · omega
    have h1_2 : p1 % 2 = 1 → (p1 % 4 + 2) % 4 = q1 % 4 := by
      have h_op := h_step.1
      dsimp [operation] at h_op
      rcases h_op with rfl | rfl
      · intro _
        omega
      · intro _
        omega
    have h2_1 : p2 % 2 = q2 % 2 := by
      have h_op := h_step.2
      dsimp [operation] at h_op
      rcases h_op with rfl | rfl
      · omega
      · omega
    have h2_2 : p2 % 2 = 1 → (p2 % 4 + 2) % 4 = q2 % 4 := by
      have h_op := h_step.2
      dsimp [operation] at h_op
      rcases h_op with rfl | rfl
      · intro _
        omega
      · intro _
        omega

    dsimp [good_pair] at h_good ⊢
    rcases h_good with ⟨g1, g2⟩ | ⟨g1, g2, g3⟩
    · left
      omega
    · right
      have hp1 : p1 % 2 = 1 := by omega
      have hp2 : p2 % 2 = 1 := by omega
      have hq1 : (p1 % 4 + 2) % 4 = q1 % 4 := h1_2 hp1
      have hq2 : (p2 % 4 + 2) % 4 = q2 % 4 := h2_2 hp2
      refine ⟨hp1, hp2, ?_⟩
      omega

  have h_good_x : ∀ x : ℕ, good_pair x x := by
    intro x
    dsimp [good_pair]
    have h : x % 2 = 0 ∨ x % 2 = 1 := by omega
    rcases h with h0 | h1
    · left
      exact ⟨h0, h0⟩
    · right
      exact ⟨h1, h1, rfl⟩

  change (fun p : ℕ × ℕ => good_pair p.1 p.2) (a, b)
  have h_reach' : ReflTransGen single_step (a, b) (x, x) := h_reach
  refine ReflTransGen.head_induction_on h_reach' (h_good_x x) ?_
  intros
  apply h_step_lem
  · assumption
  · assumption

theorem good_pair_implies_eventually_equal (a b : ℕ) : good_pair a b → eventually_equal a b :=
by
  intro hgp
  have claim1 : ∀ c A B : ℕ, B + 2 = 3 * A + 4 * c → eventually_equal A B := by
    intro c
    induction c with
    | zero =>
      intros A B h
      use 3 * A
      have step1 : single_step (A, B) (3 * A, 3 * A) := by
        dsimp [single_step, operation]
        omega
      exact Relation.ReflTransGen.head step1 Relation.ReflTransGen.refl
    | succ c ih =>
      intros A B h
      have h1 : eventually_equal (A + 2) (B + 2) := by
        apply ih
        omega
      rcases h1 with ⟨Z, hZ⟩
      use Z
      have step1 : single_step (A, B) (A + 2, B + 2) := by
        dsimp [single_step, operation]
        omega
      exact Relation.ReflTransGen.head step1 hZ

  have swap_step : ∀ p q : ℕ × ℕ, single_step p q → single_step (p.snd, p.fst) (q.snd, q.fst) := by
    intros p q h
    dsimp [single_step] at h ⊢
    tauto

  have swap_reach : ∀ p q : ℕ × ℕ, reachable p q → reachable (p.snd, p.fst) (q.snd, q.fst) := by
    intros p q h
    induction h with
    | refl => exact Relation.ReflTransGen.refl
    | tail hr hs ih => exact Relation.ReflTransGen.tail ih (swap_step _ _ hs)

  have symm_ee : ∀ x y : ℕ, eventually_equal x y → eventually_equal y x := by
    intros x y h
    rcases h with ⟨Z, hZ⟩
    use Z
    exact swap_reach (x, y) (Z, Z) hZ

  have wlog : ∀ a b : ℕ, a ≤ b → good_pair a b → eventually_equal a b := by
    intros a b hle hgp
    rcases eq_or_lt_of_le hle with rfl | hlt
    · use a; apply Relation.ReflTransGen.refl
    · rcases hgp with ⟨ha, hb⟩ | ⟨ha, hb, hab⟩
      · have h_cases : (a + b) % 4 = 0 ∨ (a + b) % 4 = 2 := by omega
        rcases h_cases with h_ab0 | h_ab2
        · have step1 : single_step (a, b) (a + 2, 3 * b) := by
            dsimp [single_step, operation]
            omega
          have h_eq_ex : ∃ c : ℕ, 3 * b + 2 = 3 * (a + 2) + 4 * c := by
            have h_Z : ∃ c_int : ℤ, (3 * (b : ℤ) + 2) = 3 * ((a : ℤ) + 2) + 4 * c_int := by
              use (3 * (b : ℤ) + 2 - 3 * ((a : ℤ) + 2)) / 4
              omega
            rcases h_Z with ⟨c_int, hc_int⟩
            use c_int.toNat
            omega
          rcases h_eq_ex with ⟨c, h_eq⟩
          have h_ee : eventually_equal (a + 2) (3 * b) := claim1 c _ _ h_eq
          rcases h_ee with ⟨Z, hZ⟩
          use Z
          exact Relation.ReflTransGen.head step1 hZ
        · have h_cases2 : b + 2 ≥ 3 * a ∨ b + 2 < 3 * a := by omega
          rcases h_cases2 with hb1 | hb2
          · have h_eq_ex : ∃ c : ℕ, b + 2 = 3 * a + 4 * c := by
              have h_Z : ∃ c_int : ℤ, ((b : ℤ) + 2) = 3 * (a : ℤ) + 4 * c_int := by
                use ((b : ℤ) + 2 - 3 * (a : ℤ)) / 4
                omega
              rcases h_Z with ⟨c_int, hc_int⟩
              use c_int.toNat
              omega
            rcases h_eq_ex with ⟨c, h_eq⟩
            exact claim1 c _ _ h_eq
          · have step1 : single_step (a, b) (a + 2, 3 * b) := by
              dsimp [single_step, operation]
              omega
            have step2 : single_step (a + 2, 3 * b) (a + 4, 9 * b) := by
              dsimp [single_step, operation]
              omega
            have h_eq_ex : ∃ c : ℕ, 9 * b + 2 = 3 * (a + 4) + 4 * c := by
              have h_Z : ∃ c_int : ℤ, (9 * (b : ℤ) + 2) = 3 * ((a : ℤ) + 4) + 4 * c_int := by
                use (9 * (b : ℤ) + 2 - 3 * ((a : ℤ) + 4)) / 4
                omega
              rcases h_Z with ⟨c_int, hc_int⟩
              use c_int.toNat
              omega
            rcases h_eq_ex with ⟨c, h_eq⟩
            have h_ee : eventually_equal (a + 4) (9 * b) := claim1 c _ _ h_eq
            rcases h_ee with ⟨Z, hZ⟩
            use Z
            exact Relation.ReflTransGen.head step1 (Relation.ReflTransGen.head step2 hZ)
      · have h_cases2 : b + 2 ≥ 3 * a ∨ b + 2 < 3 * a := by omega
        rcases h_cases2 with hb1 | hb2
        · have h_eq_ex : ∃ c : ℕ, b + 2 = 3 * a + 4 * c := by
            have h_Z : ∃ c_int : ℤ, ((b : ℤ) + 2) = 3 * (a : ℤ) + 4 * c_int := by
              use ((b : ℤ) + 2 - 3 * (a : ℤ)) / 4
              omega
            rcases h_Z with ⟨c_int, hc_int⟩
            use c_int.toNat
            omega
          rcases h_eq_ex with ⟨c, h_eq⟩
          exact claim1 c _ _ h_eq
        · have step1 : single_step (a, b) (a + 2, 3 * b) := by
            dsimp [single_step, operation]
            omega
          have h_eq_ex : ∃ c : ℕ, 3 * b + 2 = 3 * (a + 2) + 4 * c := by
            have h_Z : ∃ c_int : ℤ, (3 * (b : ℤ) + 2) = 3 * ((a : ℤ) + 2) + 4 * c_int := by
              use (3 * (b : ℤ) + 2 - 3 * ((a : ℤ) + 2)) / 4
              omega
            rcases h_Z with ⟨c_int, hc_int⟩
            use c_int.toNat
            omega
          rcases h_eq_ex with ⟨c, h_eq⟩
          have h_ee : eventually_equal (a + 2) (3 * b) := claim1 c _ _ h_eq
          rcases h_ee with ⟨Z, hZ⟩
          use Z
          exact Relation.ReflTransGen.head step1 hZ

  have h_le : a ≤ b ∨ b ≤ a := by omega
  rcases h_le with h1 | h2
  · apply wlog a b h1 hgp
  · apply symm_ee
    apply wlog b a h2
    rcases hgp with ⟨ha, hb⟩ | ⟨ha, hb, hab⟩
    · exact Or.inl ⟨hb, ha⟩
    · exact Or.inr ⟨hb, ha, hab.symm⟩

theorem PBAdvanced014 (a b : ℕ) (h_pos : a > 0 ∧ b > 0) (h_ne : a ≠ b) : eventually_equal a b ↔ good_pair a b :=
by
  constructor
  · exact eventually_equal_implies_good_pair a b
  · exact good_pair_implies_eventually_equal a b
