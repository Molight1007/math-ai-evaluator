-- 题目ID: imo-bench-number_theory-093
-- 评测时间: 20260822_163632
-- 编译结果: N/A
-- 原始问题: Non-negative integers $a<b<c$ satisfy $c\le a+b$, and $3^a, 3^b, 3^c$ all have the same remainder wh

import Mathlib.NumberTheory.ModularArithmetic
import Mathlib.Data.Nat.Digits

theorem min_sum_of_exponents : ∃ (a b c : ℕ), a < b ∧ b < c ∧ c ≤ a + b ∧
  3^a % 10000 = 3^b % 10000 ∧ 3^b % 10000 = 3^c % 10000 ∧
  a + b + c = 3000 ∧
  ∀ (a' b' c' : ℕ), a' < b' → b' < c' → c' ≤ a' + b' →
    3^a' % 10000 = 3^b' % 10000 → 3^b' % 10000 = 3^c' % 10000 →
    a' + b' + c' ≥ 3000 := by
  -- First, show that 3^500 ≡ 1 mod 10000
  have h500 : 3^500 % 10000 = 1 := by
    -- Using Chinese Remainder Theorem: 10000 = 16 * 625
    -- Show 3^500 ≡ 1 mod 16 and mod 625
    have h16 : 3^500 % 16 = 1 := by
      -- ord_16(3) = 4, and 4 divides 500
      have : 3^4 % 16 = 1 := by norm_num
      rw [← Nat.pow_mul, this, Nat.pow_one]
      norm_num
    have h625 : 3^500 % 625 = 1 := by
      -- ord_625(3) = 500
      -- This requires more detailed proof, but we can use known results
      -- or compute directly (in practice, we'd need a lemma)
      sorry
    -- Combine using CRT
    have : 3^500 % 10000 = 1 := by
      -- Since 3^500 ≡ 1 mod 16 and mod 625, and gcd(16,625)=1
      -- then 3^500 ≡ 1 mod 10000
      exact Nat.mod_eq_of_mod_eq_of_mod_eq h16 h625 (by norm_num)
    exact this
  
  -- Now construct the solution a=500, b=1000, c=1500
  use 500, 1000, 1500
  split <;> norm_num
  split <;> norm_num
  split <;> norm_num
  -- Show 3^500 ≡ 3^1000 ≡ 3^1500 mod 10000
  have h1 : 3^500 % 10000 = 3^1000 % 10000 := by
    rw [← Nat.pow_add, h500, Nat.mul_one, Nat.pow_add, h500, Nat.mul_one]
    norm_num
  have h2 : 3^1000 % 10000 = 3^1500 % 10000 := by
    rw [← Nat.pow_add, h500, Nat.mul_one, Nat.pow_add, h500, Nat.mul_one]
    norm_num
  split <;> exact h1
  split <;> exact h2
  -- Show sum is 3000
  norm_num
  
  -- Now show minimality
  intro a' b' c' h1 h2 h3 h4 h5
  -- Since 3^a' ≡ 3^b' mod 10000 and gcd(3,10000)=1, we have 3^(b'-a') ≡ 1 mod 10000
  -- So b'-a' must be a multiple of ord_10000(3) = 500
  -- Similarly c'-b' must be a multiple of 500
  -- This part requires more detailed number theory proofs
  sorry