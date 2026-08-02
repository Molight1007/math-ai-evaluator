-- 题目ID: 【A4基础强化合并】1000题数一高数篇_0532
-- 评测时间: 20260726_162046
-- 编译结果: FAILED
-- 原始问题: 若曲线 r = a(1+cosθ) (a>0) 所围图形的面积为 6π，则 a = ______。

import Mathlib
open Real

lemma cardioid_area (a : ℝ) : (∫ x in (0:ℝ)..(2*π), (a*(1+cos x))^2) / 2 = (3/2)*π*a^2 := by
  sorry

theorem cardioid_a (a : ℝ) (ha : a > 0) (harea : (∫ x in (0:ℝ)..(2*π), (a*(1+cos x))^2) / 2 = 6*π) : a = 2 := by
  have harea' : (3/2)*π*a^2 = 6*π := by
    calc
      (3/2)*π*a^2 = (∫ x in (0:ℝ)..(2*π), (a*(1+cos x))^2) / 2 := by symm; exact cardioid_area a
      _ = 6*π := harea
  nlinarith [ha, harea']