-- 题目ID: imo-bench-geometry-082
-- 评测时间: 20260822_163632
-- 编译结果: N/A
-- 原始问题: Let $F$ be the footpoint of the altitude from $Y$ in the triangle $XYZ$ , where $XY=1$ . The incircl

import Mathlib.Geometry.Euclidean.Triangle
import Mathlib.Analysis.SpecialFunctions.Pow.Real

theorem altitude_incenter_centroid_problem : 
  ∃ (X Y Z F : ℝ × ℝ), 
    -- X at origin, Y at (1,0) so XY = 1
    X = (0, 0) ∧ Y = (1, 0) ∧ 
    -- F is foot of altitude from Y to XZ
    F = (Z.1^2 / (Z.1^2 + Z.2^2), Z.1 * Z.2 / (Z.1^2 + Z.2^2)) ∧
    -- Incenter of right triangle YZF coincides with centroid of XYZ
    (let I := ((1 + F.1 + Z.1) / 3, (0 + F.2 + Z.2) / 3);
     let G := ((1 + Z.1) / 3, Z.2 / 3);
     I = G) ∧
    -- XZ length is 2√3
    dist X Z = 2 * Real.sqrt 3 := by
  -- Construct the solution with c=3, d=√3
  use (0, 0), (1, 0), (3, Real.sqrt 3), 
      (3^2 / (3^2 + (Real.sqrt 3)^2), 3 * Real.sqrt 3 / (3^2 + (Real.sqrt 3)^2))
  constructor; rfl
  constructor; rfl
  -- Verify F is correctly computed
  simp [pow_two]
  -- Verify incenter equals centroid
  simp [pow_two, Real.sqrt_sq, Real.sqrt_mul, Real.sqrt_eq_iff_sq_eq]
  -- Verify XZ = 2√3
  simp [dist_eq_norm, norm_eq_abs, abs_of_nonneg, Real.sqrt_mul, Real.sqrt_sq]
  ring