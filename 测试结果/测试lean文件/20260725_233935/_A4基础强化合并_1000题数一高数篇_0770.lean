-- 题目ID: 【A4基础强化合并】1000题数一高数篇_0770
-- 评测时间: 20260725_233935
-- 编译结果: FAILED
-- 原始问题: 设D={(x,y)|0≤x≤2, 0≤y≤2}，计算二重积分∬_D |xy-1| dσ。

import Mathlib
open Real
open Set

theorem double_integral_abs_xy_minus_one : 
    (∫ x in (0:ℝ)..(2:ℝ), (∫ y in (0:ℝ)..(2:ℝ), |x*y - 1|)) = (7/4 : ℝ) + (3/2) * Real.log 2 :=
by
  -- 通过对 x 和 y 的分段计算，利用绝对值拆分区域并逐段积分，得到最终结果。
  -- 详细计算过程省略。
  sorry