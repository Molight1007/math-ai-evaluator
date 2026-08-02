-- 题目ID: 【A4基础强化合并】1000题数一高数篇_0163
-- 评测时间: 20260726_162046
-- 编译结果: FAILED
-- 原始问题: 设f(x) = { x arctan(1/x), x>0; (π/2)(e^{sin x} - 1), x≤0 }。讨论f(x)在点x=0处的连续性和可导性；若可导，讨论其导函数f'(x)在x=0处的

{
  "lean_code": "import Mathlib\n\nopen Real\n\nnoncomputable section\n\ndef f : ℝ → ℝ := λ x =>\n  if x > 0 then x * Real.arctan (1 / x)\n  else (π / 2) * (Real.exp (Real.sin x) - 1)\n\ntheorem f_analysis : ContinuousAt f 0 ∧ HasDerivAt f (π / 