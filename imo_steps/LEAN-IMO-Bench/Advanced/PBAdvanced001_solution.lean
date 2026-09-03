import Mathlib
open scoped Classical

def is_P (m : ℕ) : Prop := ∃ b a, 0 < a ∧ 2 ≤ b ∧ m = a ^ b

noncomputable def P_set (N : ℕ) : Finset ℕ := (Finset.Icc 1 N).filter (fun m => is_P m)

noncomputable def HP_set (N : ℕ) : Finset ℕ :=
  (Finset.Icc 1 N).filter (fun m => ∃ a b, 2 ≤ a ∧ 3 ≤ b ∧ m = a ^ b)

theorem helper_bound (k : ℕ) (hk : 22 ≤ k) : (2 * k + 2) ^ 3 * 32 < 2 ^ k :=
by
  have H : ∀ n, (2 * (n + 22) + 2) ^ 3 * 32 < 2 ^ (n + 22) := by
    intro n
    induction n with
    | zero => norm_num
    | succ n ih =>
      have e1 : (2 * (n + 1 + 22) + 2) ^ 3 = 8 * n ^ 3 + 576 * n ^ 2 + 13824 * n + 110592 := by ring
      have e2 : 2 * (2 * (n + 22) + 2) ^ 3 = 16 * n ^ 3 + 1104 * n ^ 2 + 25392 * n + 194672 := by ring

      have step1 : (2 * (n + 1 + 22) + 2) ^ 3 ≤ 2 * (2 * (n + 22) + 2) ^ 3 := by
        rw [e1, e2]
        omega

      have step2 : (2 * (n + 1 + 22) + 2) ^ 3 * 32 ≤ 2 * ((2 * (n + 22) + 2) ^ 3 * 32) := by
        have hA : (2 * (n + 1 + 22) + 2) ^ 3 ≤ 2 * (2 * (n + 22) + 2) ^ 3 := step1
        revert hA
        generalize (2 * (n + 1 + 22) + 2) ^ 3 = A
        generalize (2 * (n + 22) + 2) ^ 3 = B
        intro hA
        omega

      have step3 : 2 * ((2 * (n + 22) + 2) ^ 3 * 32) < 2 * 2 ^ (n + 22) := by
        have ih_b : (2 * (n + 22) + 2) ^ 3 * 32 < 2 ^ (n + 22) := ih
        revert ih_b
        generalize (2 * (n + 22) + 2) ^ 3 * 32 = A
        generalize 2 ^ (n + 22) = B
        intro ih_b
        omega

      have step4 : 2 * 2 ^ (n + 22) = 2 ^ (n + 1 + 22) := by
        have e : n + 22 + 1 = n + 1 + 22 := by omega
        have h : 2 ^ (n + 22 + 1) = 2 ^ (n + 1 + 22) := congrArg (fun x : ℕ => 2 ^ x) e
        exact Eq.trans (pow_succ' (2 : ℕ) (n + 22)).symm h

      rw [← step4]
      exact lt_of_le_of_lt step2 step3

  have H_spec : (2 * ((k - 22) + 22) + 2) ^ 3 * 32 < 2 ^ ((k - 22) + 22) := H (k - 22)
  have h_eq : (k - 22) + 22 = k := by omega
  rw [h_eq] at H_spec
  exact H_spec

theorem lt_of_cube_lt_cube {a b : ℕ} (h : a ^ 3 < b ^ 3) : a < b :=
by
  by_contra h'
  have hle : b ≤ a := by omega
  have h2 : b ^ 3 ≤ a ^ 3 := by gcongr
  omega

theorem filter_cubed_le_N (N : ℕ) : ((Finset.Icc 1 N).filter (fun a => a ^ 3 ≤ N)).card ^ 3 ≤ N :=
by
  by_contra h
  push_neg at h
  let S := (Finset.Icc 1 N).filter (fun a => a ^ 3 ≤ N)
  have h_h : N < S.card ^ 3 := h
  have h_sub : S ⊆ (Finset.range S.card).erase 0 := by
    intro x hx
    have hx_def : x ∈ (Finset.Icc 1 N).filter (fun a => a ^ 3 ≤ N) := hx
    rw [Finset.mem_filter, Finset.mem_Icc] at hx_def
    rw [Finset.mem_erase, Finset.mem_range]
    refine ⟨?_, ?_⟩
    · intro h_eq
      rw [h_eq] at hx_def
      have : 1 ≤ 0 := hx_def.1.1
      omega
    · apply lt_of_pow_lt_pow_left₀ 3 (Nat.zero_le _)
      exact lt_of_le_of_lt hx_def.2 h_h
  have h_card := Finset.card_le_card h_sub
  by_cases hc : S.card = 0
  · rw [hc] at h_h
    have h_zero : 0 ^ 3 = 0 := rfl
    rw [h_zero] at h_h
    omega
  · have hc_pos : 0 < S.card := by omega
    have h_mem : 0 ∈ Finset.range S.card := Finset.mem_range.mpr hc_pos
    rw [Finset.card_erase_of_mem h_mem, Finset.card_range] at h_card
    omega

theorem HP_set_card_le (k : ℕ) :
  (HP_set (2 ^ (2 * k + 2))).card ≤
    (2 * k + 2) * ((Finset.Icc 1 (2 ^ (2 * k + 2))).filter (fun a => a ^ 3 ≤ 2 ^ (2 * k + 2))).card :=
by
  let N := 2 ^ (2 * k + 2)
  let A := (Finset.Icc 1 N).filter (fun a => a ^ 3 ≤ N)
  let I := Finset.Icc 1 (2 * k + 2)
  have h1 : HP_set N ⊆ I.biUnion (fun b => A.image (fun a => a ^ b)) := by
    intro m hm
    simp only [HP_set, Finset.mem_filter, Finset.mem_Icc] at hm
    rcases hm with ⟨⟨h1m, hmN⟩, a, b, ha, hb, rfl⟩
    simp only [A, I, Finset.mem_biUnion, Finset.mem_image, Finset.mem_filter, Finset.mem_Icc]
    use b
    refine ⟨⟨by omega, ?_⟩, ?_⟩
    · have h2b : 2 ^ b ≤ a ^ b := by gcongr <;> try omega
      have hb_le : 2 ^ b ≤ 2 ^ (2 * k + 2) := le_trans h2b hmN
      by_contra hbc
      push_neg at hbc
      have h2 : 2 ^ (2 * k + 2) < 2 ^ b := by gcongr <;> try omega
      omega
    · use a
      refine ⟨⟨⟨by omega, ?_⟩, ?_⟩, rfl⟩
      · have ha1 : a ^ 1 ≤ a ^ b := by gcongr <;> try omega
        calc a = a ^ 1 := (pow_one a).symm
          _ ≤ a ^ b := ha1
          _ ≤ N := hmN
      · have h3b : a ^ 3 ≤ a ^ b := by gcongr <;> try omega
        exact le_trans h3b hmN
  have h4 : I.sum (fun b => (A.image (fun a => a ^ b)).card) ≤ I.sum (fun _ => A.card) := by
    apply Finset.sum_le_sum
    intro i _
    exact Finset.card_image_le
  have h5 : I.sum (fun _ => A.card) = (2 * k + 2) * A.card := by
    have hc : I.card = 2 * k + 2 := by
      simp only [I, Nat.card_Icc]
      omega
    rw [Finset.sum_const, hc]
    simp [smul_eq_mul, nsmul_eq_mul]
  calc (HP_set (2 ^ (2 * k + 2))).card = (HP_set N).card := rfl
    _ ≤ (I.biUnion (fun b => A.image (fun a => a ^ b))).card := Finset.card_le_card h1
    _ ≤ I.sum (fun b => (A.image (fun a => a ^ b)).card) := Finset.card_biUnion_le
    _ ≤ I.sum (fun _ => A.card) := h4
    _ = (2 * k + 2) * A.card := h5
    _ = (2 * k + 2) * ((Finset.Icc 1 (2 ^ (2 * k + 2))).filter (fun a => a ^ 3 ≤ 2 ^ (2 * k + 2))).card := rfl

theorem arithmetic_bound (k : ℕ) (hk : (2 * k + 2) ^ 3 * 32 < 2 ^ k) :
  (2 * k + 2) ^ 3 * 2 ^ (2 * k + 2) < (2 ^ k) ^ 3 :=
by
  have h_pos : 0 < 2 ^ (2 * k) := by positivity
  have h4 : (2 : ℕ) ^ 2 = 4 := by rfl
  have h_exp : k + 2 * k = k * 3 := by omega
  calc
    (2 * k + 2) ^ 3 * 2 ^ (2 * k + 2)
      = (2 * k + 2) ^ 3 * (2 ^ (2 * k) * 2 ^ 2) := by rw [pow_add 2 (2 * k) 2]
    _ = (2 * k + 2) ^ 3 * (2 ^ (2 * k) * 4) := by rw [h4]
    _ = ((2 * k + 2) ^ 3 * 2 ^ (2 * k)) * 4 := by ring
    _ ≤ ((2 * k + 2) ^ 3 * 2 ^ (2 * k)) * 32 := by omega
    _ = (2 * k + 2) ^ 3 * 32 * 2 ^ (2 * k) := by ring
    _ < 2 ^ k * 2 ^ (2 * k) := mul_lt_mul_of_pos_right hk h_pos
    _ = 2 ^ (k + 2 * k) := by rw [← pow_add 2 k (2 * k)]
    _ = 2 ^ (k * 3) := by rw [h_exp]
    _ = (2 ^ k) ^ 3 := by rw [pow_mul 2 k 3]

theorem HP_card_bound (k : ℕ) (hk : 22 ≤ k) :
  (HP_set (2 ^ (2 * k + 2))).card < 2 ^ k :=
by
  have H_lt : (HP_set (2 ^ (2 * k + 2))).card ^ 3 < (2 ^ k) ^ 3 := by
    calc
      (HP_set (2 ^ (2 * k + 2))).card ^ 3 ≤ ((2 * k + 2) * ((Finset.Icc 1 (2 ^ (2 * k + 2))).filter (fun a => a ^ 3 ≤ 2 ^ (2 * k + 2))).card) ^ 3 := by
        gcongr
        exact HP_set_card_le k
      _ = (2 * k + 2) ^ 3 * ((Finset.Icc 1 (2 ^ (2 * k + 2))).filter (fun a => a ^ 3 ≤ 2 ^ (2 * k + 2))).card ^ 3 := by
        rw [mul_pow]
      _ ≤ (2 * k + 2) ^ 3 * 2 ^ (2 * k + 2) := by
        exact Nat.mul_le_mul_left ((2 * k + 2) ^ 3) (filter_cubed_le_N (2 ^ (2 * k + 2)))
      _ < (2 ^ k) ^ 3 := by
        exact arithmetic_bound k (helper_bound k hk)
  exact lt_of_cube_lt_cube H_lt

theorem image_card (k : ℕ) (f : ℕ → ℕ) (hf : ∀ x ∈ Finset.Ico (2^k) (2^(k+1)), f x ∈ Finset.Icc (x^2+1) (x^2+2*x)) : (Finset.image f (Finset.Ico (2^k) (2^(k+1)))).card = 2^k :=
by
  have h_inj : Set.InjOn f (Finset.Ico (2^k) (2^(k+1))) := by
    intro x hx y hy heq
    have hfx := Finset.mem_Icc.mp (hf x hx)
    have hfy := Finset.mem_Icc.mp (hf y hy)
    obtain hlt | rfl | hgt := lt_trichotomy x y
    · have h1 : (f x : ℤ) ≤ (x:ℤ)^2 + 2*(x:ℤ) := by exact_mod_cast hfx.2
      have h2 : (y:ℤ)^2 + 1 ≤ (f y : ℤ) := by exact_mod_cast hfy.1
      have heq_z : (f x : ℤ) = (f y : ℤ) := by exact_mod_cast heq
      have hx0 : 0 ≤ (x:ℤ) := by omega
      have hxy : (x:ℤ) + 1 ≤ (y:ℤ) := by omega
      have h_sq : ((x:ℤ) + 1)^2 ≤ (y:ℤ)^2 := by nlinarith
      nlinarith
    · rfl
    · have h1 : (f y : ℤ) ≤ (y:ℤ)^2 + 2*(y:ℤ) := by exact_mod_cast hfy.2
      have h2 : (x:ℤ)^2 + 1 ≤ (f x : ℤ) := by exact_mod_cast hfx.1
      have heq_z : (f x : ℤ) = (f y : ℤ) := by exact_mod_cast heq
      have hy0 : 0 ≤ (y:ℤ) := by omega
      have hyx : (y:ℤ) + 1 ≤ (x:ℤ) := by omega
      have h_sq : ((y:ℤ) + 1)^2 ≤ (x:ℤ)^2 := by nlinarith
      nlinarith
  rw [Finset.card_image_of_injOn h_inj]
  rw [Nat.card_Ico, pow_add, pow_one]
  omega

theorem image_subset_HP (k : ℕ) (hk : 22 ≤ k) (f : ℕ → ℕ) (hf1 : ∀ x ∈ Finset.Ico (2^k) (2^(k+1)), f x ∈ Finset.Icc (x^2+1) (x^2+2*x)) (hf2 : ∀ x ∈ Finset.Ico (2^k) (2^(k+1)), is_P (f x)) : Finset.image f (Finset.Ico (2^k) (2^(k+1))) ⊆ HP_set (2^(2*k+2)) :=
by
  rw [Finset.image_subset_iff]
  intro x hx
  rw [HP_set, Finset.mem_filter]

  have h_n_mem := hf1 x hx
  have h_n_P := hf2 x hx

  have hx_bounds := Finset.mem_Ico.mp hx
  have hx_lower := hx_bounds.1
  have hx_upper := hx_bounds.2

  have hn_bounds := Finset.mem_Icc.mp h_n_mem
  have hn_lower := hn_bounds.1
  have hn_upper := hn_bounds.2

  have hn_ge_2 : 2 ≤ f x := by
    have hx_pos' : 1 ≤ x := by
      have : 0 < 2^k := by positivity
      omega
    have h_sq_le : 1^2 ≤ x^2 := by gcongr
    have h_one_le : 1 ≤ x^2 := by
      calc 1 = 1^2 := by ring
           _ ≤ x^2 := h_sq_le
    omega

  have hn_ge_1 : 1 ≤ f x := by omega

  have hn_le : f x ≤ 2 ^ (2 * k + 2) := by
    have h1 : f x < (x + 1)^2 := by
      calc f x ≤ x^2 + 2*x := hn_upper
           _ < x^2 + 2*x + 1 := by omega
           _ = (x + 1)^2 := by ring
    have h2 : x + 1 ≤ 2^(k+1) := by omega
    have h3 : (x + 1)^2 ≤ (2^(k+1))^2 := by gcongr
    have h4 : (2^(k+1))^2 = 2^(2*k+2) := by
      calc (2^(k+1))^2 = 2^(k+1) * 2^(k+1) := by ring
           _ = 2^(k+1 + (k+1)) := by rw [← pow_add]
           _ = 2^(2*k+2) := by congr 1; omega
    omega

  have h_Icc : f x ∈ Finset.Icc 1 (2 ^ (2 * k + 2)) :=
    Finset.mem_Icc.mpr ⟨hn_ge_1, hn_le⟩

  have h_no_sq : ¬ ∃ y, f x = y ^ 2 := by
    intro ⟨y, hy⟩
    rw [hy] at hn_lower hn_upper
    have hy1 : x < y := by
      by_contra hnot
      have hle : y ≤ x := by omega
      have hsq : y ^ 2 ≤ x ^ 2 := by gcongr
      omega
    have hy2 : y < x + 1 := by
      by_contra hnot
      have hle : x + 1 ≤ y := by omega
      have hsq : (x + 1)^2 ≤ y^2 := by gcongr
      have : x^2 + 2*x + 1 ≤ y^2 := by
        calc x^2 + 2*x + 1 = (x + 1)^2 := by ring
             _ ≤ y^2 := hsq
      omega
    omega

  have h_HP_exists : ∃ a b, 2 ≤ a ∧ 3 ≤ b ∧ f x = a ^ b := by
    rcases h_n_P with ⟨b, a, ha_pos, hb_ge2, h_eq⟩
    have hb_ne2 : b ≠ 2 := by
      intro hb2
      subst hb2
      apply h_no_sq
      exact ⟨a, h_eq⟩
    have hb_ge3 : 3 ≤ b := by omega
    have ha_ge2 : 2 ≤ a := by
      by_contra hnot
      have ha_lt2 : a < 2 := by omega
      have ha_eq : a = 1 := by omega
      subst ha_eq
      have h_f_eq_1 : f x = 1 := by
        calc f x = 1 ^ b := h_eq
             _ = 1 := by simp
      omega
    exact ⟨a, b, ha_ge2, hb_ge3, h_eq⟩

  exact ⟨h_Icc, h_HP_exists⟩

theorem exists_empty_interval (k : ℕ) (hk : 22 ≤ k) :
  ∃ x ∈ Finset.Ico (2 ^ k) (2 ^ (k + 1)),
    ∀ n ∈ Finset.Icc (x ^ 2 + 1) (x ^ 2 + 2 * x), ¬ is_P n :=
by
  by_contra h
  push_neg at h
  let f : ℕ → ℕ := fun x => if hx : x ∈ Finset.Ico (2^k) (2^(k+1)) then Classical.choose (h x hx) else 0
  have hf1 : ∀ x ∈ Finset.Ico (2^k) (2^(k+1)), f x ∈ Finset.Icc (x^2+1) (x^2+2*x) := by
    intro x hx
    have h_eq : f x = Classical.choose (h x hx) := dif_pos hx
    rw [h_eq]
    exact (Classical.choose_spec (h x hx)).1
  have hf2 : ∀ x ∈ Finset.Ico (2^k) (2^(k+1)), is_P (f x) := by
    intro x hx
    have h_eq : f x = Classical.choose (h x hx) := dif_pos hx
    rw [h_eq]
    exact (Classical.choose_spec (h x hx)).2
  have h_card := image_card k f hf1
  have h_sub := image_subset_HP k hk f hf1 hf2
  have h_le := Finset.card_le_card h_sub
  rw [h_card] at h_le
  have h_lt := HP_card_bound k hk
  omega

theorem A_constant (A : ℕ → ℕ) (hA : ∀ n, A n = (P_set n).card)
  (x n : ℕ) (hn : n ∈ Finset.Icc (x ^ 2 + 1) (x ^ 2 + 2 * x))
  (h_empty : ∀ m ∈ Finset.Icc (x ^ 2 + 1) (x ^ 2 + 2 * x), ¬ is_P m) :
  A n = A (x ^ 2) :=
by
  rw [hA n, hA (x ^ 2)]
  congr 1
  ext m
  unfold P_set
  simp only [Finset.mem_filter, Finset.mem_Icc]
  constructor
  · rintro ⟨⟨h1, h2⟩, hP⟩
    by_cases h3 : m ≤ x ^ 2
    · exact ⟨⟨h1, h3⟩, hP⟩
    · have h4 : m ∈ Finset.Icc (x ^ 2 + 1) (x ^ 2 + 2 * x) := by
        rw [Finset.mem_Icc] at hn ⊢
        omega
      have h5 := h_empty m h4
      contradiction
  · rintro ⟨⟨h1, h2⟩, hP⟩
    have h3 : m ≤ n := by
      rw [Finset.mem_Icc] at hn
      omega
    exact ⟨⟨h1, h3⟩, hP⟩

theorem sq_set_card_le (z : ℕ) :
  ((Finset.Icc 1 (z^2)).filter (fun m => ∃ x, m = x^2)).card ≤ z :=
by
  have h1 : ((Finset.Icc 1 (z^2)).filter (fun m => ∃ x, m = x^2)) ⊆ (Finset.Icc 1 z).image (fun x => x^2) := by
    intro m hm
    rw [Finset.mem_filter] at hm
    rcases hm with ⟨h_mem, h_ex⟩
    rcases h_ex with ⟨x, rfl⟩
    rw [Finset.mem_Icc] at h_mem
    rcases h_mem with ⟨h1_m, h2_m⟩
    rw [Finset.mem_image]
    use x
    constructor
    · rw [Finset.mem_Icc]
      constructor
      · by_contra hx
        have h_eq : x = 0 := by omega
        rcases h_eq with rfl
        have hz : (0 : ℕ) ^ 2 = 0 := by norm_num
        rw [hz] at h1_m
        omega
      · by_contra hx
        have h_gt : x ≥ z + 1 := by omega
        have h_sq : x * x ≤ z * z := by
          have h_tmp : x ^ 2 ≤ z ^ 2 := h2_m
          have hx2 : x ^ 2 = x * x := by ring
          have hz2 : z ^ 2 = z * z := by ring
          rw [hx2, hz2] at h_tmp
          exact h_tmp
        nlinarith
    · rfl
  have h2 : ((Finset.Icc 1 (z^2)).filter (fun m => ∃ x, m = x^2)).card ≤ ((Finset.Icc 1 z).image (fun x => x^2)).card :=
    Finset.card_le_card h1
  have h3 : ((Finset.Icc 1 z).image (fun x => x^2)).card ≤ (Finset.Icc 1 z).card :=
    Finset.card_image_le
  have h_subset : Finset.Icc 1 z ⊆ (Finset.range (z + 1)).erase 0 := by
    intro x hx
    rw [Finset.mem_Icc] at hx
    rw [Finset.mem_erase, Finset.mem_range]
    constructor <;> omega
  have h4 : (Finset.Icc 1 z).card ≤ ((Finset.range (z + 1)).erase 0).card :=
    Finset.card_le_card h_subset
  have h_zero_mem : 0 ∈ Finset.range (z + 1) := by
    rw [Finset.mem_range]
    omega
  have h5 : ((Finset.range (z + 1)).erase 0).card = z := by
    rw [Finset.card_erase_of_mem h_zero_mem, Finset.card_range]
    omega
  omega

theorem x_sq_le_pow (k x : ℕ) (hx : x < 2 ^ (k + 1)) :
  x ^ 2 ≤ 2 ^ (2 * k + 2) :=
by
  have h_eq : 2 * k + 2 = (k + 1) * 2 := by omega
  rw [h_eq, pow_mul]
  gcongr <;> omega

theorem HP_set_mono {N M : ℕ} (h : N ≤ M) :
  HP_set N ⊆ HP_set M :=
by
  intro x hx
  rw [HP_set, Finset.mem_filter] at hx ⊢
  rcases hx with ⟨hx1, hx2⟩
  rw [Finset.mem_Icc] at hx1 ⊢
  exact ⟨⟨hx1.1, le_trans hx1.2 h⟩, hx2⟩

theorem P_set_subset (N : ℕ) :
  P_set N ⊆ (Finset.Icc 1 N).filter (fun m => ∃ x, m = x ^ 2) ∪ HP_set N :=
by
  intro m hm
  rw [P_set, Finset.mem_filter] at hm
  rcases hm with ⟨hIcc, hP⟩
  rw [Finset.mem_union]
  by_cases hsq : ∃ x, m = x ^ 2
  · left
    rw [Finset.mem_filter]
    exact ⟨hIcc, hsq⟩
  · right
    rw [HP_set, Finset.mem_filter]
    refine ⟨hIcc, ?_⟩
    rcases hP with ⟨b, a, ha, hb, hab⟩
    have ha2 : 2 ≤ a := by
      by_contra hc
      have ha1 : a = 1 := by omega
      apply hsq
      use 1
      rw [ha1] at hab
      simp at hab
      rw [hab]
      rfl
    have hb3 : 3 ≤ b := by
      by_contra hc
      have hb2 : b = 2 := by omega
      apply hsq
      use a
      rw [hab, hb2]
    exact ⟨a, b, ha2, hb3, hab⟩

theorem A_x2_bound (A : ℕ → ℕ) (hA : ∀ n, A n = (P_set n).card)
  (k x : ℕ) (hk : 22 ≤ k) (hx_lower : 2 ^ k ≤ x) (hx_upper : x < 2 ^ (k + 1)) :
  A (x ^ 2) ≤ 2 * x :=
by
  have h_A_val : A (x ^ 2) = (P_set (x ^ 2)).card := hA (x ^ 2)
  rw [h_A_val]
  have h_sub := P_set_subset (x ^ 2)
  have h_card := Finset.card_le_card h_sub
  have h_union := Finset.card_union_le ((Finset.Icc 1 (x ^ 2)).filter (fun m => ∃ x, m = x ^ 2)) (HP_set (x ^ 2))
  have h_S2 := sq_set_card_le x
  have h_sq_le := x_sq_le_pow k x hx_upper
  have h_HP_sub := HP_set_mono h_sq_le
  have h_HP_card1 := Finset.card_le_card h_HP_sub
  have h_HP_card2 := HP_card_bound k hk
  omega

theorem A_pos (A : ℕ → ℕ) (hA : ∀ n, A n = (P_set n).card) (x : ℕ) (hx : 1 ≤ x) :
  1 ≤ A (x ^ 2) :=
by
  -- Rewrite the goal using the provided hypothesis for A.
  rw [hA]

  -- Establish that x^2 is equivalent to x * x.
  have h_sq : x ^ 2 = x * x := by ring

  -- Prove that 1 ≤ x^2 using the property that 1 ≤ x.
  have h1 : 1 ≤ x ^ 2 := by
    rw [h_sq]
    have h2 : x * 1 ≤ x * x := Nat.mul_le_mul_left x hx
    rw [mul_one] at h2
    calc
      1 ≤ x := hx
      _ ≤ x * x := h2

  -- Prove that the set P_set (x^2) is nonempty by showing x^2 is an element.
  have h_nonempty : (P_set (x ^ 2)).Nonempty := by
    refine ⟨x ^ 2, ?_⟩
    rw [P_set, Finset.mem_filter, Finset.mem_Icc]

    -- Split the membership condition into range check and predicate check.
    refine ⟨⟨h1, le_rfl⟩, ?_⟩

    -- Show that x^2 satisfies the is_P predicate.
    have h_is_P : is_P (x ^ 2) := by
      unfold is_P
      use 2, x
      have hx_pos : 0 < x := by omega
      refine ⟨hx_pos, by decide, rfl⟩
    exact h_is_P

  -- Use the non-emptiness of the finite set to conclude its cardinality is strictly positive.
  have h_card : 0 < (P_set (x ^ 2)).card := Finset.card_pos.mpr h_nonempty

  -- 0 < card is equivalent to 1 ≤ card for natural numbers.
  omega

theorem find_multiple (m start last : ℕ) (hm : 0 < m) (hlen : m + start ≤ last + 1) :
  ∃ n ∈ Finset.Icc start last, m ∣ n + 2024 :=
by
  let r := (start + 2024) % m
  have hr : r < m := Nat.mod_lt (start + 2024) hm
  by_cases h : r = 0
  · refine ⟨start, ?_, ?_⟩
    · rw [Finset.mem_Icc]
      exact ⟨by omega, by omega⟩
    · have h_mod : (start + 2024) % m = 0 := h
      exact Nat.dvd_of_mod_eq_zero h_mod
  · let k := m - r
    refine ⟨start + k, ?_, ?_⟩
    · rw [Finset.mem_Icc]
      exact ⟨by omega, by omega⟩
    · have hk_lt : k < m := by omega
      have h_eq : start + k + 2024 = (start + 2024) + k := by omega
      rw [h_eq]
      apply Nat.dvd_of_mod_eq_zero
      rw [Nat.add_mod]
      change (r + k % m) % m = 0
      have hk_mod : k % m = k := Nat.mod_eq_of_lt hk_lt
      rw [hk_mod]
      have hrk : r + k = m := by omega
      rw [hrk]
      exact Nat.mod_self m

theorem helper_x_pos (k x : ℕ) (hk : 22 ≤ k) (hx_lower : 2 ^ k ≤ x) : 1 ≤ x :=
by
  have h : 0 < 2 ^ k := by positivity
  omega

theorem helper_n_bounds (N k x n : ℕ) (hk : 22 ≤ k) (hkN : N ≤ k)
    (hx_lower : 2 ^ k ≤ x) (hn_ge : x ^ 2 + 1 ≤ n) :
    N < n ∧ 0 < n :=
by
  have hk2 : k < 2 ^ k := by
    clear hk hkN hx_lower hn_ge
    induction k with
    | zero => exact Nat.zero_lt_one
    | succ k' ih =>
      have h1 : 0 < 2 ^ k' := by positivity
      calc k' + 1 < 2 ^ k' + 1 := by omega
        _ ≤ 2 ^ k' + 2 ^ k' := by omega
        _ = 2 ^ k' * 2 := by ring
        _ = 2 ^ (k' + 1) := rfl

  have hx : x ≤ x ^ 2 := by
    cases x with
    | zero => exact Nat.zero_le _
    | succ x' =>
      have h2 : 1 ≤ x' + 1 := by omega
      calc x' + 1 = (x' + 1) * 1 := by ring
        _ ≤ (x' + 1) * (x' + 1) := Nat.mul_le_mul_left (x' + 1) h2
        _ = (x' + 1) ^ 2 := by ring

  constructor
  · omega
  · omega

theorem PBAdvanced001 (A : ℕ → ℕ)
    (hA : ∀ n, A n = (Finset.Icc 1 n |>.filter fun m => ∃ b a, 0 < a ∧ 2 ≤ b ∧ m = a ^ b).card) : {n : ℕ | 0 < n ∧ A n ∣ n + 2024}.Infinite :=
by
  rw [Set.infinite_iff_exists_gt]
  intro N
  let k := max 22 N
  have hk : 22 ≤ k := le_max_left 22 N
  have hkN : N ≤ k := le_max_right 22 N
  obtain ⟨x, hx_mem, h_empty⟩ := exists_empty_interval k hk
  have hA' : ∀ n, A n = (P_set n).card := hA
  have hx_lower : 2 ^ k ≤ x := (Finset.mem_Ico.mp hx_mem).1
  have hx_upper_lt : x < 2 ^ (k + 1) := (Finset.mem_Ico.mp hx_mem).2
  have hx_pos : 1 ≤ x := helper_x_pos k x hk hx_lower
  let m := A (x ^ 2)
  have hm_pos : 0 < m := A_pos A hA' x hx_pos
  have hm_le : m ≤ 2 * x := A_x2_bound A hA' k x hk hx_lower hx_upper_lt
  have hlen : m + (x ^ 2 + 1) ≤ (x ^ 2 + 2 * x) + 1 := by omega
  obtain ⟨n, hn_mem, hn_div⟩ := find_multiple m (x ^ 2 + 1) (x ^ 2 + 2 * x) hm_pos hlen
  have hn_ge : x ^ 2 + 1 ≤ n := (Finset.mem_Icc.mp hn_mem).1
  obtain ⟨hN, h0⟩ := helper_n_bounds N k x n hk hkN hx_lower hn_ge
  have hAn : A n = m := A_constant A hA' x n hn_mem h_empty
  have h_mem : n ∈ {n : ℕ | 0 < n ∧ A n ∣ n + 2024} := by
    refine ⟨h0, ?_⟩
    rw [hAn]
    exact hn_div
  exact ⟨n, h_mem, hN⟩
