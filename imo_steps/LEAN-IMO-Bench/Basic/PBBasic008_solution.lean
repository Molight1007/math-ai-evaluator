import Mathlib

theorem PBBasic008 (a b c : ℝ)
    (ha : 0 < a) (hb : 0 < b) (hc : 0 < c)
    (H : a + b + c = 1) : 3 * √3 * (a * b + b * c + c * a) ≤ √a + √b + √c :=
by
  have h_ineq : ∀ x : ℝ, 0 < x → x < 1 → 3 * √3 * x * (1 - x) ≤ 2 * √x := by
    intro x hx1 hx2
    have h1 : 0 ≤ ((3 : ℝ) * x - 1)^2 * ((4 : ℝ) - 3 * x) := by
      have h_lin : 0 ≤ (4 : ℝ) - 3 * x := by linarith
      positivity
    have h2 : ((3 : ℝ) * x - 1)^2 * ((4 : ℝ) - 3 * x) = 4 - (27 : ℝ) * x * (1 - x)^2 := by ring
    have h3 : (27 : ℝ) * x * (1 - x)^2 ≤ 4 := by
      calc (27 : ℝ) * x * (1 - x)^2 = 4 - (4 - (27 : ℝ) * x * (1 - x)^2) := by ring
        _ = 4 - (((3 : ℝ) * x - 1)^2 * ((4 : ℝ) - 3 * x)) := by rw [← h2]
        _ ≤ 4 := by linarith [h1]
    have h4 : (27 : ℝ) * x^2 * (1 - x)^2 ≤ 4 * x := by
      calc (27 : ℝ) * x^2 * (1 - x)^2 = ((27 : ℝ) * x * (1 - x)^2) * x := by ring
        _ ≤ (4 : ℝ) * x := mul_le_mul_of_nonneg_right h3 (by linarith)
    have h5 : √((27 : ℝ) * x^2 * (1 - x)^2) ≤ √((4 : ℝ) * x) := Real.sqrt_le_sqrt h4
    have h_num : (3 * √3 : ℝ)^2 = 27 := by
      calc (3 * √3 : ℝ)^2 = (3 : ℝ)^2 * (√3)^2 := mul_pow (3 : ℝ) (√3) 2
        _ = 9 * (√3)^2 := by ring
        _ = 9 * 3 := by
          have h_sqrt3 : (√3)^2 = 3 := Real.sq_sqrt (by norm_num)
          rw [h_sqrt3]
        _ = 27 := by ring
    have h6 : √((27 : ℝ) * x^2 * (1 - x)^2) = 3 * √3 * x * (1 - x) := by
      have h_sq : ((3 * √3) * (x * (1 - x)))^2 = (27 : ℝ) * x^2 * (1 - x)^2 := by
        calc ((3 * √3) * (x * (1 - x)))^2 = (3 * √3)^2 * (x * (1 - x))^2 := mul_pow (3 * √3) (x * (1 - x)) 2
          _ = (27 : ℝ) * (x * (1 - x))^2 := by rw [h_num]
          _ = (27 : ℝ) * x^2 * (1 - x)^2 := by ring
      calc √((27 : ℝ) * x^2 * (1 - x)^2) = √(((3 * √3) * (x * (1 - x)))^2) := by rw [← h_sq]
        _ = (3 * √3) * (x * (1 - x)) := by
          apply Real.sqrt_sq
          have hx_nonneg : 0 ≤ x := by linarith
          have h_one_sub_x_nonneg : 0 ≤ 1 - x := by linarith
          have h_sqrt3_nonneg : 0 ≤ √3 := Real.sqrt_nonneg 3
          positivity
        _ = 3 * √3 * x * (1 - x) := by ring
    have h7 : √((4 : ℝ) * x) = 2 * √x := by
      have h_four_nonneg : (0 : ℝ) ≤ 4 := by norm_num
      calc √((4 : ℝ) * x) = √(4 : ℝ) * √x := by rw [Real.sqrt_mul h_four_nonneg]
        _ = 2 * √x := by
          have h_four : √(4 : ℝ) = 2 := by norm_num
          rw [h_four]
    rw [h6, h7] at h5
    exact h5

  have ha1 : a < 1 := by linarith
  have hb1 : b < 1 := by linarith
  have hc1 : c < 1 := by linarith

  have H_a := h_ineq a ha ha1
  have H_b := h_ineq b hb hb1
  have H_c := h_ineq c hc hc1

  have H_sum : 3 * √3 * a * (1 - a) + 3 * √3 * b * (1 - b) + 3 * √3 * c * (1 - c) ≤ 2 * √a + 2 * √b + 2 * √c := by linarith [H_a, H_b, H_c]

  have H_sum2 : 3 * √3 * (a * (1 - a) + b * (1 - b) + c * (1 - c)) ≤ 2 * (√a + √b + √c) := by
    calc 3 * √3 * (a * (1 - a) + b * (1 - b) + c * (1 - c)) = 3 * √3 * a * (1 - a) + 3 * √3 * b * (1 - b) + 3 * √3 * c * (1 - c) := by ring
      _ ≤ 2 * √a + 2 * √b + 2 * √c := H_sum
      _ = 2 * (√a + √b + √c) := by ring

  have H_id : a * (1 - a) + b * (1 - b) + c * (1 - c) = 2 * (a * b + b * c + c * a) := by
    calc a * (1 - a) + b * (1 - b) + c * (1 - c) = (a + b + c) - (a^2 + b^2 + c^2) := by ring
      _ = 1 - (a^2 + b^2 + c^2) := by rw [H]
      _ = (1 : ℝ)^2 - (a^2 + b^2 + c^2) := by ring
      _ = (a + b + c)^2 - (a^2 + b^2 + c^2) := by
        have h_H : (1 : ℝ)^2 = (a + b + c)^2 := by rw [H]
        rw [h_H]
      _ = 2 * (a * b + b * c + c * a) := by ring

  rw [H_id] at H_sum2

  calc 3 * √3 * (a * b + b * c + c * a) = (3 * √3 * (2 * (a * b + b * c + c * a))) * (1 / 2 : ℝ) := by ring
    _ ≤ (2 * (√a + √b + √c)) * (1 / 2 : ℝ) := mul_le_mul_of_nonneg_right H_sum2 (by norm_num)
    _ = √a + √b + √c := by ring
