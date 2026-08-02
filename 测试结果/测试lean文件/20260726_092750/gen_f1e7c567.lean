-- 题目ID: gen_f1e7c567
-- 评测时间: 20260726_092750
-- 编译结果: FAILED
-- 原始问题: 求极限 $\lim_{x \to 0} \frac{\sin x - x}{x^3}$。

import Mathlib

open Real
open Filter

theorem limit_sin_sub_x_div_x_cube : Tendsto (λ x : ℝ => (sin x - x) / (x ^ 3)) (𝓝 0) (𝓝 (-1/6 : ℝ)) := by
  sorry