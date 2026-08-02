-- 题目ID: 【A4基础强化合并】1000题数一高数篇_0463
-- 评测时间: 20260725_233211
-- 编译结果: FAILED
-- 原始问题: 计算不定积分：∫ x(x+2) dx

import Mathlib

open Real

theorem antideriv_x_x_plus_2 (C x : ℝ) : HasDerivAt (fun (x : ℝ) => (1/3)*x^3 + x^2 + C) (x*(x+2)) x := by
  have hx3 : HasDerivAt (fun (x : ℝ) => x^3) (3*x^2) x := by
    have h := hasDerivAt_pow 3 x
    simpa [show (3:ℕ)-1=2 by decide] using h
  have hx2 : HasDerivAt (fun (x : ℝ) => x^2) (2*x) x := by
    have h := hasDerivAt_pow 2 x
    simpa [show (2:ℕ)-1=1 by decide] using h
  have hconst : HasDerivAt (fun (_ : ℝ) => C) (0) x := hasDerivAt_const x C
  have hthird : HasDerivAt (fun (x : ℝ) => (1/3)*x^3) ((1/3)*(3*x^2)) x :=
    HasDerivAt.const_mul (1/3) hx3
  have hthird_simp : ((1/3 : ℝ)*(3*x^2)) = x^2 := by ring
  have hthird' : HasDerivAt (fun (x : ℝ) => (1/3)*x^3) (x^2) x := by
    simpa [hthird_simp] using hthird
  have hsum1 : HasDerivAt (fun (x : ℝ) => (1/3)*x^3 + x^2) (x^2 + (2*x)) x :=
    HasDerivAt.add hthird' hx2
  have hsum_simp : x^2 + (2*x) = x*(x+2) := by ring
  have hsum : HasDerivAt (fun (x : ℝ) => (1/3)*x^3 + x^2) (x*(x+2)) x := by
    simpa [hsum_simp] using hsum1
  have htotal : HasDerivAt (fun (x : ℝ) => (1/3)*x^3 + x^2 + C) (x*(x+2)) x := by
    have := HasDerivAt.add hsum hconst
    simpa [add_zero] using this
  exact htotal