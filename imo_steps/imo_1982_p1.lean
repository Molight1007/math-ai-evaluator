import Mathlib
set_option linter.unusedVariables.analyzeTactics true


open Nat

theorem imo_1982_p1
  (f : ℕ → ℤ)
  (h₀ : ∀ m n, (0 < m ∧ 0 < n) → f (m + n) - f m - f n = 0 ∨ f (m + n) - f m - f n = 1)
  (h₁ : f 2 = 0)
  (h₂ : 0 < f 3)
  (h₃ : f 9999 = 3333) :
  f 1982 = 660 := by
  have h₀₀: ∀ m n, (0 < m ∧ 0 < n) → f m  + f n ≤ f (m + n) := by
    intros m n hmn
    have g₀: f (m + n) - f m - f n = 0 ∨ f (m + n) - f m - f n = 1 := by
      exact h₀ m n hmn
    omega
  have h₀₁: ∀ m k, (0 < m ∧ 0 < k) → k * f m ≤ f (k * m) := by
    intros m k hmk
    have g₁: 1 ≤ k := by linarith
    refine Nat.le_induction ?_ ?_ k g₁
    . simp
    . intros n hmn  g₂
      rw [cast_add]
      rw [add_mul, add_mul, one_mul]
      simp
      have g₃: f (n * m) + f (m) ≤ f (n * m + m) := by
        refine h₀₀ (n * m) m ?_
        constructor
        . refine mul_pos ?_ hmk.1
          exact hmn
        . exact hmk.1
      refine le_trans ?_ g₃
      exact (Int.add_le_add_iff_right (f m)).mpr g₂
  have h₄: f 3 = 1 := by
    have g₀ : 3333 * f 3 ≤ f (9999) := by
      refine h₀₁ 3 3333 ?_
      omega
    linarith
  have h₅: f 1980 = 660 := by
    have h₅₀: f 1980 ≤ 660 := by
      have g₀ : f (5 * 1980) + f 99 ≤ f (9999) := by
        refine h₀₀ (5 * 1980) 99 (by omega)
      have g₁: 5 * f (1980) ≤ f (5 * 1980) := by
        exact h₀₁ 1980 5 (by omega)
      have g₂: 33 * f 3 ≤ f 99 := by
        exact h₀₁ 3 33 (by omega)
      rw [h₃] at g₀
      linarith
    have h₅₁: 660 ≤ f 1980 := by
      have g₀ : 660 * f 3 ≤ f (1980) := by
        refine h₀₁ 3 660 ?_
        omega
      rw [h₄] at g₀
      exact g₀
    exact le_antisymm h₅₀ h₅₁
  have h₆: f 1982 - f 1980 - f 2 = 0 ∨ f 1982 - f 1980 - f 2 = 1 := by
    refine h₀ 1980 2 ?_
    omega
  cases' h₆ with h₆₀ h₆₁
  . linarith
  . exfalso
    rw [h₅, h₁] at h₆₁
    have h₆₂: f 1982 = 661 := by
      linarith
    have h₆₃: 5 * f 1982 + 29 ≤ 3333 := by
      have g₀ : f (5 * 1982) + f 89 ≤ f 9999 := by
        refine h₀₀ (5 * 1982) 89 (by omega)
      have g₁: f (29 * 3) + f 2 ≤ f 89 := by
        refine h₀₀ (29 * 3) 2 (by omega)
      have g₂: 5 * f (1982) ≤ f (5 * 1982) := by
        exact h₀₁ 1982 5 (by omega)
      have g₃: 29 * f 3 ≤ f (87) := by
        exact h₀₁ 3 29 (by omega)
      linarith
    rw [h₆₂] at h₆₃
    linarith
