import Mathlib

theorem PBBasic002 (x y z t : ℝ)
    (hx : 0 < x) (hy : 0 < y) (hz : 0 < z) (ht : 0 < t)
    (H : x * y * z * t ≤ 2 * (x + y + z + t)) : x * y * z * t ≤ x ^ 2 + y ^ 2 + z ^ 2 + t ^ 2 :=
by
  let P := x * y * z * t
  let Q := x^2 + y^2 + z^2 + t^2
  let S := x + y + z + t

  -- Prove variables are positive/non-negative using safe methods
  have hxy : 0 < x * y := mul_pos hx hy
  have hxyz : 0 < x * y * z := mul_pos hxy hz
  have hP_pos : 0 < P := mul_pos hxyz ht

  have hQ_nonneg : 0 ≤ Q := by positivity

  have hS_pos : 0 < S := by linarith [hx, hy, hz, ht]

  -- Using identity combinations to establish Q^2 >= 16 * P
  have id1 : Q^2 - 16 * P = (x^2 + y^2 - z^2 - t^2)^2 + 4 * (x * z - y * t)^2 + 4 * (x * t - y * z)^2 := by ring
  have hsq1 : 0 ≤ (x^2 + y^2 - z^2 - t^2)^2 := by positivity
  have hsq2 : 0 ≤ 4 * (x * z - y * t)^2 := by positivity
  have hsq3 : 0 ≤ 4 * (x * t - y * z)^2 := by positivity
  have h1 : 16 * P ≤ Q^2 := by linarith [id1, hsq1, hsq2, hsq3]

  -- Using identity combinations to establish S^2 <= 4 * Q
  have id2 : 4 * Q - S^2 = (x - y)^2 + (x - z)^2 + (x - t)^2 + (y - z)^2 + (y - t)^2 + (z - t)^2 := by ring
  have hsq4 : 0 ≤ (x - y)^2 := by positivity
  have hsq5 : 0 ≤ (x - z)^2 := by positivity
  have hsq6 : 0 ≤ (x - t)^2 := by positivity
  have hsq7 : 0 ≤ (y - z)^2 := by positivity
  have hsq8 : 0 ≤ (y - t)^2 := by positivity
  have hsq9 : 0 ≤ (z - t)^2 := by positivity
  have h2 : S^2 ≤ 4 * Q := by linarith [id2, hsq4, hsq5, hsq6, hsq7, hsq8, hsq9]

  -- Connect P <= 2S securely into P^2 <= 4S^2
  have hP_le_2S : P ≤ 2 * S := H
  have h_sum1 : 0 ≤ 2 * S - P := by linarith [hP_le_2S]
  have h_sum2 : 0 ≤ 2 * S + P := by linarith [hP_pos, hS_pos]
  have hS2 : 0 ≤ (2 * S - P) * (2 * S + P) := mul_nonneg h_sum1 h_sum2
  have hS2_exp : (2 * S - P) * (2 * S + P) = (2 * S)^2 - P^2 := by ring
  have h4 : P^2 ≤ (2 * S)^2 := by linarith [hS2, hS2_exp]

  -- Show (2 * S)^2 <= 16 * Q
  have h_four_nonneg : (0 : ℝ) ≤ 4 := by norm_num
  have h5 : (2 * S)^2 ≤ 16 * Q := by
    calc (2 * S)^2 = 4 * S^2 := by ring
    _ ≤ 4 * (4 * Q) := mul_le_mul_of_nonneg_left h2 h_four_nonneg
    _ = 16 * Q := by ring

  -- Chain P^2 <= (2S)^2 <= 16Q
  have h6 : P^2 ≤ 16 * Q := le_trans h4 h5

  -- Assume Q < P for contradiction
  by_contra h_contra
  push_neg at h_contra

  -- Chain dependencies to enforce P^2 < Q^2
  have h7 : 16 * Q < 16 * P := by linarith [h_contra]
  have h8 : P^2 < Q^2 := by linarith [h6, h7, h1]

  -- Factoring P^2 - Q^2 gives a contradiction based on magnitudes
  have h9 : 0 < P - Q := by linarith [h_contra]
  have h10 : 0 < P + Q := by linarith [hP_pos, hQ_nonneg]
  have h11 : 0 < (P - Q) * (P + Q) := mul_pos h9 h10
  have h12 : (P - Q) * (P + Q) = P^2 - Q^2 := by ring

  -- Triggers the direct contradiction via Linarith (0 < P^2 - Q^2 vs P^2 < Q^2)
  linarith [h8, h11, h12]
