import Mathlib
set_option linter.unusedVariables.analyzeTactics true

open Real

lemma mylemma_1
  (a b c : ℝ)
  (x y z : ℝ)
  (h₀ : 0 < a ∧ 0 < b ∧ 0 < c)
  (h₂: c ≤ b ∧ b ≤ a)
  (h₃: z ≤ y ∧ y ≤ x) :
  a * z + c * y + b * x ≤ c * z + b * y + a * x := by
  suffices h₄: c * (y - z) + b * (x - y) ≤ a * (x - z)
  . linarith
  . have h₅: c * (y - z) + b * (x - y) ≤ b * (y - z) + b * (x - y) := by
      simp
      refine mul_le_mul h₂.1 ?_ ?_ ?_
      . exact le_rfl
      . exact sub_nonneg_of_le h₃.1
      . exact le_of_lt h₀.2.1
    refine le_trans h₅ ?_
    rw [mul_sub, mul_sub, add_comm]
    rw [← add_sub_assoc, sub_add_cancel]
    rw [← mul_sub]
    refine mul_le_mul h₂.2 ?_ ?_ ?_
    . exact le_rfl
    . refine sub_nonneg_of_le ?_
      exact le_trans h₃.1 h₃.2
    . exact le_of_lt h₀.1


lemma mylemma_2
  (a b c : ℝ)
  (x y z : ℝ)
  (h₀ : 0 < a ∧ 0 < b ∧ 0 < c)
  (h₂: c ≤ b ∧ b ≤ a)
  (h₃: z ≤ y ∧ y ≤ x) :
  b * z + a * y + c * x ≤ c * z + b * y + a * x := by
  suffices h₄: c * (x - z) + b * (z - y) ≤ a * (x - y)
  . linarith
  . have h₅: c * (x - z) + b * (z - y) ≤ b * (x - z) + b * (z - y) := by
      simp
      refine mul_le_mul h₂.1 ?_ ?_ ?_
      . exact le_rfl
      . refine sub_nonneg_of_le ?_
        exact le_trans h₃.1 h₃.2
      . exact le_of_lt h₀.2.1
    refine le_trans h₅ ?_
    rw [mul_sub, mul_sub]
    rw [← add_sub_assoc, sub_add_cancel]
    rw [← mul_sub]
    refine mul_le_mul h₂.2 ?_ ?_ ?_
    . exact le_rfl
    . exact sub_nonneg_of_le h₃.2
    . exact le_of_lt h₀.1


-- case #1
lemma mylemma_cba
  (a b c : ℝ)
  (hap : 0 < a )
  (hbp : 0 < b )
  (hcp : 0 < c )
  (h₁ : c < a + b)
  -- (h₂ : b < a + c)
  (h₃ : a < b + c)
  (hba: b ≤ a)
  (hcb: c ≤ b) :
  0 ≤ a^2 * b * (a - b) + b^2 * c * (b - c) + c^2 * a * (c - a) := by
  have g₀: b * c ≤ a * c := by exact (mul_le_mul_iff_of_pos_right hcp).mpr hba
  have g₁: a * c ≤ a * b := by exact (mul_le_mul_iff_of_pos_left hap).mpr hcb
  have g₂: a * (b + c - a) ≤ b * (a + c - b) := by
    have g₂₁: 0 ≤ (a-b) * (a+b-c) := by
      refine mul_nonneg ?_ ?_
      . exact sub_nonneg_of_le hba
      . refine le_of_lt ?_
        exact sub_pos.mpr h₁
    linarith
  have g₃: b * (a + c - b) ≤ c * (a + b - c) := by
    have g₃₁: 0 ≤ (b - c) * (b + c - a) := by
      refine mul_nonneg ?_ ?_
      . exact sub_nonneg_of_le hcb
      . refine le_of_lt ?_
        exact sub_pos.mpr h₃
    linarith
  have g₄: (a * b) * (a * (b + c - a)) + (b * c) * (b * (a + c - b)) + (a * c) * (c * (a + b - c))
      ≤ (b * c) * (a * (b + c - a)) + (a * c) * (b * (a + c - b)) + (a * b) * (c * (a + b - c)) := by
    refine mylemma_1 (a * b) (a * c) (b * c) (c * (a + b - c)) (b * (a + c - b)) (a * (b + c - a)) ?_ ?_ ?_
    . constructor
      . exact mul_pos hap hbp
      . constructor
        . exact mul_pos hap hcp
        . exact mul_pos hbp hcp
    . exact { left := g₀, right := g₁ }
    . exact { left := g₂, right := g₃ }
  linarith


-- tight version
lemma mylemma_cba_tight
  (a b c : ℝ)
  (hap : 0 < a )
  (hbp : 0 < b )
  (hcp : 0 < c )
  (h₁ : c < a + b)
  -- (h₂ : b < a + c)
  (h₃ : a < b + c)
  (hba: b ≤ a)
  (hcb: c ≤ b) :
  0 ≤ a^2 * c * (a - c) + c^2 * b * (c - b) + b^2 * a * (b - a) := by
  have g₀: b * c ≤ a * c := by exact (mul_le_mul_iff_of_pos_right hcp).mpr hba
  have g₁: a * c ≤ a * b := by exact (mul_le_mul_iff_of_pos_left hap).mpr hcb
  have g₂: a * (b + c - a) ≤ b * (a + c - b) := by
    have g₂₁: 0 ≤ (a-b) * (a+b-c) := by
      refine mul_nonneg ?_ ?_
      . exact sub_nonneg_of_le hba
      . refine le_of_lt ?_
        exact sub_pos.mpr h₁
    linarith
  have g₃: b * (a + c - b) ≤ c * (a + b - c) := by
    have g₃₁: 0 ≤ (b - c) * (b + c - a) := by
      refine mul_nonneg ?_ ?_
      . exact sub_nonneg_of_le hcb
      . refine le_of_lt ?_
        exact sub_pos.mpr h₃
    linarith
  have g₄: (a * c) * (a * (b + c - a)) + (a * b) * (b * (a + c - b)) + (b * c) * (c * (a + b - c))
      ≤ (b * c) * (a * (b + c - a)) + (a * c) * (b * (a + c - b)) + (a * b) * (c * (a + b - c)) := by
    refine mylemma_2 (a * b) (a * c) (b * c) (c * (a + b - c)) (b * (a + c - b)) (a * (b + c - a)) ?_ ?_ ?_
    . constructor
      . exact mul_pos hap hbp
      . constructor
        . exact mul_pos hap hcp
        . exact mul_pos hbp hcp
    . exact { left := g₀, right := g₁ }
    . exact { left := g₂, right := g₃ }
  linarith


theorem imo_1983_p6
  (a b c : ℝ)
  (h₀ : 0 < a ∧ 0 < b ∧ 0 < c)
  (h₁ : c < a + b)
  (h₂ : b < a + c)
  (h₃ : a < b + c) :
  0 ≤ a^2 * b * (a - b) + b^2 * c * (b - c) + c^2 * a * (c - a) := by
  wlog ho₀: b ≤ a generalizing a b c
  . clear this
    push_neg at ho₀
    wlog ho₁: c ≤ b generalizing a b c
    . clear this
      push_neg at ho₁ -- a < b < c
      rw [add_comm] at h₁ h₂ h₃
      have g₀: 0 ≤ c ^ 2 * a * (c - a) + a ^ 2 * b * (a - b) + b ^ 2 * c * (b - c) := by
        exact mylemma_cba_tight c b a h₀.2.2 h₀.2.1 h₀.1 h₃ h₁ (le_of_lt ho₁) (le_of_lt ho₀)
      linarith
    . wlog ho₂: c ≤ a generalizing a b c
      . clear this -- a < c ≤ b
        push_neg at ho₂
        rw [add_comm] at h₁ h₂
        have g₀: 0 ≤ b ^ 2 * c * (b - c) + c ^ 2 * a * (c - a) + a ^ 2 * b * (a - b) := by
          exact mylemma_cba b c a h₀.2.1 h₀.2.2 h₀.1 h₃ h₂ ho₁ (le_of_lt ho₂)
        linarith
      . -- c ≤ a < b
        rw [add_comm] at h₁
        have g₀: 0 ≤ b ^ 2 * c * (b - c) + c ^ 2 * a * (c - a) + a ^ 2 * b * (a - b) := by
          exact mylemma_cba_tight b a c h₀.2.1 h₀.1 h₀.2.2 h₁ h₂ (le_of_lt ho₀) ho₂
        linarith
  . wlog ho₁: c ≤ b generalizing a b c
    . clear this
      push_neg at ho₁
      wlog ho₂: c ≤ a generalizing a b c
      . clear this
        push_neg at ho₂ -- b < a < c
        rw [add_comm] at h₂ h₃
        have g₀: 0 ≤ c ^ 2 * a * (c - a) + a ^ 2 * b * (a - b) + b ^ 2 * c * (b - c) := by
          exact mylemma_cba c a b h₀.2.2 h₀.1 h₀.2.1 h₂ h₁ (le_of_lt ho₂) ho₀
        linarith
      . rw [add_comm] at h₃
        exact mylemma_cba_tight a c b h₀.1 h₀.2.2 h₀.2.1 h₂ h₃ ho₂ (le_of_lt ho₁)
    . exact mylemma_cba a b c h₀.1 h₀.2.1 h₀.2.2 h₁ h₃ ho₀ ho₁
