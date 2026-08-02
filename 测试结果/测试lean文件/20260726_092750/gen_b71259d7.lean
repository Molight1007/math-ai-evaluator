-- 题目ID: gen_b71259d7
-- 评测时间: 20260726_092750
-- 编译结果: FAILED
-- 原始问题: 求函数f(x,y) = x^2 + y^2 - 2x + 4y + 1的极值。

import Mathlib

open Real

theorem f_extreme_value : (∃ (x y : ℝ), x^2 + y^2 - 2*x + 4*y + 1 = -4) ∧ (∀ (x y : ℝ), x^2 + y^2 - 2*x + 4*y + 1 ≥ -4) :=
by
  constructor
  · use 1, -2
    norm_num
  · intro x y
    have h_eq : x^2 + y^2 - 2*x + 4*y + 1 = (x - 1)^2 + (y + 2)^2 - 4 := by ring
    rw [h_eq]
    have hx : (x - 1)^2 ≥ 0 := sq_nonneg _
    have hy : (y + 2)^2 ≥ 0 := sq_nonneg _
    linarith