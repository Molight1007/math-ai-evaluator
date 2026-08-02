-- 题目ID: gen_ef1ebe53
-- 评测时间: 20260726_154739
-- 编译结果: FAILED
-- 原始问题: 求函数f(x)=x^3-3x+1在区间[-2,2]上的最大值和最小值。

import Mathlib
open Set
open Real

/-- 函数 f(x) = x^3 - 3x + 1 -/
def f (x : ℝ) : ℝ := x^3 - 3*x + 1

/-- 在闭区间 [-2, 2] 上 f 存在最大值和最小值，
    但模型未能给出具体结果，因此证明未完成。 -/
theorem max_min_exists : ∃ (M m : ℝ), (∀ x ∈ Icc (-2 : ℝ) 2, m ≤ f x ∧ f x ≤ M) ∧ (∃ xm ∈ Icc (-2 : ℝ) 2, f xm = m) ∧ (∃ xM ∈ Icc (-2 : ℝ) 2, f xM = M) := by
  sorry