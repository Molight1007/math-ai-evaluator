-- 题目ID: gen_3654e942
-- 评测时间: 20260725_233211
-- 编译结果: FAILED
-- 原始问题: 求函数 \(f(x) = x^3 - 3x + 1\) 的极值点。

import Mathlib

open Set
open Filter

def f (x : ℝ) : ℝ := x^3 - 3*x + 1

theorem extrema : IsLocalMax f (-1) ∧ IsLocalMin f 1 :=
by
  have hmax : IsLocalMax f (-1) := by
    have hmem : (-1 : ℝ) ∈ Ioo (-2 : ℝ) 0 := by
      constructor <;> nlinarith
    refine ⟨Ioo (-2 : ℝ) 0, isOpen_Ioo.mem_nhds hmem, ?_⟩
    intro x hx
    rcases hx with ⟨hxl, hxr⟩
    have : f x - 3 ≤ 0 := by
      calc
        f x - 3 = (x + 1)^2 * (x - 2) := by
          dsimp [f]
          ring
        _ ≤ 0 := by
          nlinarith
    linarith
  have hmin : IsLocalMin f 1 := by
    have hmem : (1 : ℝ) ∈ Ioo (0 : ℝ) 2 := by
      constructor <;> nlinarith
    refine ⟨Ioo (0 : ℝ) 2, isOpen_Ioo.mem_nhds hmem, ?_⟩
    intro x hx
    rcases hx with ⟨hxl, hxr⟩
    have : f x + 1 ≥ 0 := by
      calc
        f x + 1 = (x - 1)^2 * (x + 2) := by
          dsimp [f]
          ring
        _ ≥ 0 := by
          nlinarith
    linarith
  exact ⟨hmax, hmin⟩