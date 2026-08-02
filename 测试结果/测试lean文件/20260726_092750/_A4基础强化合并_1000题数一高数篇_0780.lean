-- 题目ID: 【A4基础强化合并】1000题数一高数篇_0780
-- 评测时间: 20260726_092750
-- 编译结果: FAILED
-- 原始问题: 计算累次积分：∫_{0}^{1} x^2 dx ∫_{0}^{1} e^{-y^2} dy。

{
  "lean_code": "import Mathlib\nopen Real\nopen intervalIntegral\n\ntheorem iterated_integral_equals : (∫ x in (0:ℝ)..(1:ℝ), x^2) * (∫ y in (0:ℝ)..(1:ℝ), Real.exp (-y^2)) = (1/3 : ℝ) * (Real.sqrt π / 2) * Real.erf 1 := by\n  have hx : (∫ x in (0:ℝ)..(1:ℝ), x^2) = (1/3 : ℝ) := by\n    calc\n      (∫ x in (0:ℝ)..(1:ℝ), x^2) = ((1:ℝ)^(2+1) - (0:ℝ)^(2+1)) / ((2:ℝ)+1) := by\n        rw [intervalIntegral.integral_pow]\n      _ = (1 - 0) / 3 := by norm_num\n      _ = 1/3 := by ring\n  have hy : (∫ y in (0:ℝ)..(1:ℝ), Real.exp (-y^2)) = (Real.sqrt π / 2) * Real.erf 1 := by\n    have h_erf_def : Real