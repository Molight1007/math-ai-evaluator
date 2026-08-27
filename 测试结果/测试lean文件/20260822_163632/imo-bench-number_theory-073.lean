-- 题目ID: imo-bench-number_theory-073
-- 评测时间: 20260822_163632
-- 编译结果: N/A
-- 原始问题: Let $q$ be an odd prime number. For an integer $i$ from 1 to $q-1$, let $n_i$ denote the number of d

import Mathlib.NumberTheory.Divisors

theorem sum_ni_eq_q_minus_one (q : ℕ) [hq : Fact q.Prime] (hq_odd : Odd q) : 
    (Finset.sum (Finset.Ico 1 q) fun i => 
      (Finset.filter (fun d => i ≤ d ∧ d ≤ q - 1 ∧ d ∣ q * i + 1) (Finset.Ico 1 q)).card) = q - 1 := by
  -- Define the sum S as the sum of n_i
  let S := (Finset.sum (Finset.Ico 1 q) fun i => 
    (Finset.filter (fun d => i ≤ d ∧ d ≤ q - 1 ∧ d ∣ q * i + 1) (Finset.Ico 1 q)).card)
  -- By double counting, S equals the number of pairs (i, d) with 1 ≤ i ≤ d ≤ q-1 and d | qi+1
  have hS : S = (Finset.filter (fun p : ℕ × ℕ => 
    let i := p.1
    let d := p.2
    1 ≤ i ∧ i ≤ d ∧ d ≤ q - 1 ∧ d ∣ q * i + 1) 
    (Finset.product (Finset.Ico 1 q) (Finset.Ico 1 q))).card := by
    -- This follows from the definition of sum of cardinalities
    simp only [S]
    -- Use the fact that sum of cardinalities equals cardinality of disjoint union
    -- (This step would require more detailed proof in a complete formalization)
    sorry
  -- For each d in [1, q-1], there is exactly one i in [1, d] such that d | qi+1
  have h_pairs : (Finset.filter (fun p : ℕ × ℕ => 
    let i := p.1
    let d := p.2
    1 ≤ i ∧ i ≤ d ∧ d ≤ q - 1 ∧ d ∣ q * i + 1) 
    (Finset.product (Finset.Ico 1 q) (Finset.Ico 1 q))).card = q - 1 := by
    -- For each d, since gcd(q, d) = 1 (as q is prime and d < q),
    -- there exists a unique i mod d such that qi ≡ -1 mod d
    -- This i is in [1, d], so exactly one i per d
    -- (This step requires number theory about modular inverses)
    sorry
  -- Combine the results
  rw [hS, h_pairs]
