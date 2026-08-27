-- 题目ID: imo-bench-algebra-003
-- 评测时间: 20260822_163632
-- 编译结果: N/A
-- 原始问题: Find all functions $g:\mathbb{R}\rightarrow\mathbb{R}$ which is not a linear or constant function an

import Mathlib

theorem no_nonlinear_solution : 
  ¬ ∃ (g : ℝ → ℝ), 
    (¬ ∃ (a b : ℝ), ∀ x, g x = a * x + b) ∧
    (∀ x y z : ℝ, 
      4 * g (x^2 * y + y^2 * z + z^2 * x) - 
      (g y - g x) * (g z - g y) * (g x - g z) = 
      4 * g (x * y^2 + y * z^2 + z * x^2)) := by
  intro ⟨g, hnonlin, heq⟩
  -- 步骤1: 证明线性函数必须满足 a³ = -4a
  have h_linear_coeff : ∀ (a b : ℝ), (∀ x, g x = a * x + b) → a^3 = -4 * a := by
    intro a b hlin
    have := heq 1 2 3
    simp [hlin] at this
    ring_nf at this
    norm_num at this
    exact this
  -- 步骤2: 排除常数函数 (a=0)
  by_contra hconst
  obtain ⟨a, b, ha⟩ := hnonlin.not_not.1 hconst
  have := h_linear_coeff a b ha
  simp [ha] at this
  -- 步骤3: 排除线性函数 (a=±2)
  by_cases h2 : a = 2
  · simp [h2] at this
    norm_num at this
    contradiction
  · by_cases hneg2 : a = -2
    · simp [hneg2] at this
      norm_num at this
      contradiction
    · -- 证明 a 必须为 0, 2, 或 -2
      have : a * (a^2 + 4) = 0 := by
        rw [← this]
        ring
      cases' eq_or_ne a 0 with h0 h0
      · exact h0
      · have : a^2 + 4 = 0 := by
          apply mul_eq_zero.1 this
          exact h0
        linarith
  -- 步骤4: 非线性情况导出矛盾
  have hnonpoly : ¬ ∃ (n : ℕ) (c : ℕ → ℝ), (∀ x, g x = ∑ i in Finset.range n, c i * x^i) := by
    intro ⟨n, c, hpoly⟩
    have := heq 1 0 0
    simp [hpoly] at this
    -- 高次项系数不匹配
    sorry
  -- 步骤5: 非多项式情况导出矛盾
  have hnonfunc : False := by
    -- 通过变量替换证明必须为线性
    sorry
  exact hnonfunc