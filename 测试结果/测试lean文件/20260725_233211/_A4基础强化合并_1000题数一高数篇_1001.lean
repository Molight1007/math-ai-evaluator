-- 题目ID: 【A4基础强化合并】1000题数一高数篇_1001
-- 评测时间: 20260725_233211
-- 编译结果: FAILED
-- 原始问题: 设Ω={(x,y,z)|x^2+y^2+z^2≤1, x≥0, y≥0, z≥0}，则三重积分∭_Ω (x^2+2y^2+3z^2) dxdydz = ______。

import Mathlib

open Set
open Real

noncomputable def Ω : Set (ℝ × ℝ × ℝ) := 
  {p | p.1^2 + p.2.1^2 + p.2.2^2 ≤ 1 ∧ p.1 ≥ 0 ∧ p.2.1 ≥ 0 ∧ p.2.2 ≥ 0}

noncomputable def f (p : ℝ × ℝ × ℝ) : ℝ := p.1^2 + 2 * p.2.1^2 + 3 * p.2.2^2

theorem answer : (∫ p in Ω, f p) = (π : ℝ)/5 :=
  by
    sorry