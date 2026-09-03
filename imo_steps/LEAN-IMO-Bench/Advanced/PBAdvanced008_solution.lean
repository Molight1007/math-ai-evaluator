import Mathlib
noncomputable def period_M (c : ℕ) : ℕ :=
  if h : 1 < c then
    have : c.totient < c := Nat.totient_lt c h
    Nat.lcm c.totient (period_M c.totient)
  else 1
termination_by c

theorem PB_generalized_c_eq_1 (F : ℕ → ℕ) (a : ℤ) (K : ℕ) (b : ℤ) :
    ∃ n : ℕ, n ≥ K ∧ (1 : ℤ) ∣ a ^ F n + (n : ℤ) - b :=
by
  use K
  constructor
  · exact le_rfl
  · exact one_dvd _

theorem period_M_pos (c : ℕ) : 0 < period_M c :=
by
  refine Nat.strong_induction_on c (fun n ih => ?_)
  rw [period_M]
  split_ifs with h
  · have ht : n.totient < n := Nat.totient_lt n h
    have h_ind : 0 < period_M n.totient := ih n.totient ht
    have h_tot_pos : 0 < n.totient := Nat.totient_pos.mpr (by omega)

    -- Prove that the LCM of two positive numbers is strictly positive
    have h_gcd_lcm : Nat.gcd n.totient (period_M n.totient) * Nat.lcm n.totient (period_M n.totient) = n.totient * period_M n.totient := Nat.gcd_mul_lcm n.totient (period_M n.totient)
    apply Nat.pos_of_ne_zero
    intro hlcm
    rw [hlcm, mul_zero] at h_gcd_lcm
    have h_mul : 0 < n.totient * period_M n.totient := Nat.mul_pos h_tot_pos h_ind
    rw [← h_gcd_lcm] at h_mul
    omega
  · exact zero_lt_one

theorem period_M_pos_local (c : ℕ) : 0 < period_M c :=
if h : 1 < c then
    have hc : c.totient < c := Nat.totient_lt c h
    have ih : 0 < period_M c.totient := period_M_pos_local c.totient
    by
      unfold period_M
      rw [dif_pos h]
      have ht : 0 < c.totient := Nat.totient_pos.mpr (by omega)
      exact Nat.pos_of_ne_zero fun h_lcm => by
        have h_gcd := Nat.gcd_mul_lcm c.totient (period_M c.totient)
        rw [h_lcm, mul_zero] at h_gcd
        rcases mul_eq_zero.mp h_gcd.symm with h1 | h2
        · omega
        · omega
  else
    by
      unfold period_M
      rw [dif_neg h]
      omega
termination_by c

theorem max_prime_factor_exists_local (c : ℕ) (hc : 1 < c) :
  ∃ p, p.Prime ∧ p ∣ c ∧ ∀ q, q.Prime → q ∣ c → q ≤ p :=
by
  classical
  have hc1 : c ≠ 1 := by omega
  obtain ⟨p0, hp0_prime, hp0_dvd⟩ := Nat.exists_prime_and_dvd hc1

  -- The set of prime factors of c is bounded by c + 1
  have hS_nonempty : ((Finset.range (c + 1)).filter (fun x => x.Prime ∧ x ∣ c)).Nonempty := by
    refine ⟨p0, ?_⟩
    simp only [Finset.mem_filter, Finset.mem_range]
    refine ⟨?_, hp0_prime, hp0_dvd⟩
    have : p0 ≤ c := Nat.le_of_dvd (by omega) hp0_dvd
    omega

  -- Extract the maximum element from this non-empty finite set
  have hp_mem : ((Finset.range (c + 1)).filter (fun x => x.Prime ∧ x ∣ c)).max' hS_nonempty ∈ (Finset.range (c + 1)).filter (fun x => x.Prime ∧ x ∣ c) :=
    Finset.max'_mem ((Finset.range (c + 1)).filter (fun x => x.Prime ∧ x ∣ c)) hS_nonempty

  -- Break down the membership property to get primality and divisibility
  simp only [Finset.mem_filter, Finset.mem_range] at hp_mem
  obtain ⟨_, hp_prime, hp_dvd⟩ := hp_mem

  -- Use the maximum element as our existential witness
  use ((Finset.range (c + 1)).filter (fun x => x.Prime ∧ x ∣ c)).max' hS_nonempty
  refine ⟨hp_prime, hp_dvd, fun q hq_prime hq_dvd => ?_⟩

  -- Show that any other prime factor belongs to the same set and is thus bounded by the max element
  have hq_mem : q ∈ (Finset.range (c + 1)).filter (fun x => x.Prime ∧ x ∣ c) := by
    simp only [Finset.mem_filter, Finset.mem_range]
    refine ⟨?_, hq_prime, hq_dvd⟩
    have : q ≤ c := Nat.le_of_dvd (by omega) hq_dvd
    omega

  apply Finset.le_max'
  exact hq_mem

theorem primeFactorsList_le_of_prime_dvd_le_local {c p : ℕ} (hc_pos : 0 < c)
  (h_max : ∀ q, q.Prime → q ∣ c → q ≤ p) :
  ∀ q ∈ c.primeFactorsList, q ≤ p :=
by
  intro q hq
  have h_ne : c ≠ 0 := by omega
  rw [Nat.mem_primeFactorsList h_ne] at hq
  exact h_max q hq.1 hq.2

theorem padicValNat_pos_of_dvd_lem {c p : ℕ} (hp : p.Prime) (hc_pos : 0 < c) (h_dvd : p ∣ c) :
  0 < padicValNat p c :=
by
  haveI : Fact (Nat.Prime p) := ⟨hp⟩
  have hc_ne : c ≠ 0 := by omega
  have h_ne : padicValNat p c ≠ 0 := (dvd_iff_padicValNat_ne_zero (p := p) (n := c) hc_ne).mp h_dvd
  omega

theorem exists_mul_of_pow_padicValNat_dvd_lem {c : ℕ} (p : ℕ) (hc_pos : 0 < c) :
  ∃ m : ℕ, c = p ^ (padicValNat p c) * m :=
by
  have h := @pow_padicValNat_dvd p c
  exact h

theorem coprime_part_properties_lem {c p k m : ℕ} (hp : p.Prime) (hc_pos : 0 < c)
  (hk : k = padicValNat p c) (hm : c = p ^ k * m)
  (h_max : ∀ q ∈ c.primeFactorsList, q ≤ p) :
  0 < p ^ k ∧ 0 < m ∧ ¬ p ∣ m ∧ Nat.Coprime (p ^ k) m ∧ ∀ q ∈ m.primeFactorsList, q ≤ p :=
by
  have hm_pos : 0 < m := by
    by_contra h
    have : m = 0 := by omega
    rw [this, mul_zero] at hm
    omega
  have hc_ne : c ≠ 0 := Nat.ne_of_gt hc_pos
  have hm_ne : m ≠ 0 := Nat.ne_of_gt hm_pos

  have hp_not_dvd_m : ¬ p ∣ m := by
    intro h_dvd
    rcases h_dvd with ⟨x, hx⟩
    have h_c_dvd : p ^ (k + 1) ∣ c := by
      rw [hm, hx]
      have h_eq : p ^ k * (p * x) = p ^ (k + 1) * x := by ring
      rw [h_eq]
      exact dvd_mul_right (p ^ (k + 1)) x
    have h_le : k + 1 ≤ c.factorization p := by
      first
      | exact (Nat.pow_dvd_iff_le_factorization hp hc_ne).mp h_c_dvd
      | exact (Nat.Prime.pow_dvd_iff_le_factorization hp hc_ne).mp h_c_dvd
      | exact (pow_dvd_iff_le_factorization hp hc_ne).mp h_c_dvd
    have hk_eq : c.factorization p = k := by
      rw [Nat.factorization_def c hp, ← hk]
    omega

  refine ⟨?_, hm_pos, hp_not_dvd_m, ?_, ?_⟩
  · have hp_pos : 0 < p := hp.pos
    positivity
  · have h_coprime : m.Coprime (p ^ k) := Nat.Prime.coprime_pow_of_not_dvd hp hp_not_dvd_m
    exact h_coprime.symm
  · intro q hq
    have hq_prime : q.Prime := by
      first
      | exact ((Nat.mem_primeFactorsList hm_ne).mp hq).1
      | exact ((Nat.mem_primeFactorsList hm_ne q).mp hq).1
      | exact ((Nat.mem_primeFactorsList (p := q) hm_ne).mp hq).1
      | exact (Nat.mem_primeFactorsList.mp hq).1
      | exact (Nat.mem_primeFactorsList.mp hq).1.1
    have hq_dvd : q ∣ m := by
      first
      | exact ((Nat.mem_primeFactorsList hm_ne).mp hq).2
      | exact ((Nat.mem_primeFactorsList hm_ne q).mp hq).2
      | exact ((Nat.mem_primeFactorsList (p := q) hm_ne).mp hq).2
      | exact (Nat.mem_primeFactorsList.mp hq).2
      | exact (Nat.mem_primeFactorsList.mp hq).2.1
      | exact (Nat.mem_primeFactorsList.mp hq).1.2
    have hq_dvd_c : q ∣ c := by
      rw [hm]
      exact dvd_mul_of_dvd_right hq_dvd (p ^ k)
    have hq_c : q ∈ c.primeFactorsList := by
      first
      | exact (Nat.mem_primeFactorsList hc_ne).mpr ⟨hq_prime, hq_dvd_c⟩
      | exact (Nat.mem_primeFactorsList hc_ne q).mpr ⟨hq_prime, hq_dvd_c⟩
      | exact (Nat.mem_primeFactorsList (p := q) hc_ne).mpr ⟨hq_prime, hq_dvd_c⟩
      | exact Nat.mem_primeFactorsList.mpr ⟨hq_prime, hq_dvd_c⟩
      | exact Nat.mem_primeFactorsList.mpr ⟨hq_prime, ⟨hq_dvd_c, hc_ne⟩⟩
      | exact Nat.mem_primeFactorsList.mpr ⟨⟨hq_prime, hq_dvd_c⟩, hc_ne⟩
    exact h_max q hq_c

theorem padicValNat_prime_pow_totient_lem {p k : ℕ} (hp : p.Prime) (hk_pos : 0 < k) :
  padicValNat p (p ^ k).totient + 1 = k :=
by
  haveI : Fact p.Prime := ⟨hp⟩
  have hp2 : 2 ≤ p := hp.two_le
  have h_tot : (p ^ k).totient = p ^ (k - 1) * (p - 1) := Nat.totient_prime_pow hp hk_pos
  rw [h_tot]
  have hpk1 : p ^ (k - 1) ≠ 0 := by positivity
  have hp1 : p - 1 ≠ 0 := by omega
  rw [padicValNat.mul hpk1 hp1]
  rw [padicValNat.prime_pow (k - 1)]
  have h_not_dvd : ¬ p ∣ p - 1 := by
    intro h
    have : p ≤ p - 1 := Nat.le_of_dvd (by omega) h
    omega
  rw [padicValNat.eq_zero_of_not_dvd h_not_dvd]
  omega

theorem padicValNat_totient_mul_lem {a b p : ℕ} (hp : p.Prime) (h_coprime : Nat.Coprime a b)
  (ha : 0 < a) (hb : 0 < b) :
  padicValNat p (a * b).totient = padicValNat p a.totient + padicValNat p b.totient :=
by
  -- Provide the `Fact` instance required by `padicValNat.mul`
  haveI : Fact (Nat.Prime p) := ⟨hp⟩

  -- Rewrite the totient of a product of coprime integers
  rw [Nat.totient_mul h_coprime]

  -- Use the multiplicativity of the p-adic valuation (with correct lemma name)
  rw [padicValNat.mul]

  -- Discharge the non-zero subgoals automatically using the positivity tactic
  · positivity
  · positivity

theorem padicValNat_totient_of_not_dvd_lem {c p : ℕ} (hp : p.Prime) (hc_pos : 0 < c)
  (h_max : ∀ q ∈ c.primeFactorsList, q ≤ p) (h_ndvd : ¬ p ∣ c) :
  padicValNat p c.totient = 0 :=
by
  apply padicValNat.eq_zero_of_not_dvd
  intro h_dvd
  have h_totient_dvd : c.totient * ∏ q ∈ c.primeFactors, q = c * ∏ q ∈ c.primeFactors, (q - 1) := Nat.totient_mul_prod_primeFactors c
  have h_dvd_mul : p ∣ c.totient * ∏ q ∈ c.primeFactors, q := by
    obtain ⟨k, hk⟩ := h_dvd
    exact ⟨k * ∏ q ∈ c.primeFactors, q, by rw [hk]; ring⟩
  rw [h_totient_dvd] at h_dvd_mul
  have h_dvd_c_or : p ∣ c ∨ p ∣ ∏ q ∈ c.primeFactors, (q - 1) := hp.dvd_mul.mp h_dvd_mul
  cases h_dvd_c_or with
  | inl h_dvd_c => exact h_ndvd h_dvd_c
  | inr h_dvd_prod =>
    have dvd_prod : ∀ (s : Finset ℕ) (f : ℕ → ℕ), p ∣ ∏ x ∈ s, f x → ∃ x ∈ s, p ∣ f x := by
      intro s
      refine Finset.induction_on s ?_ ?_
      · intro f h
        rw [Finset.prod_empty] at h
        have hp1 : ¬ p ∣ 1 := by
          intro h1
          obtain ⟨k, hk⟩ := h1
          have hp2 := hp.two_le
          cases k with
          | zero =>
            rw [mul_zero] at hk
            omega
          | succ k' =>
            have h_k_pos : 1 ≤ k' + 1 := by omega
            have h_mul : p * 1 ≤ p * (k' + 1) := Nat.mul_le_mul_left p h_k_pos
            omega
        exact False.elim (hp1 h)
      · intro a s ha ih f h
        rw [Finset.prod_insert ha] at h
        cases hp.dvd_mul.mp h with
        | inl h1 => exact ⟨a, Finset.mem_insert_self a s, h1⟩
        | inr h2 =>
          obtain ⟨x, hx, hpx⟩ := ih f h2
          exact ⟨x, Finset.mem_insert_of_mem hx, hpx⟩
    obtain ⟨q, hq_mem, hq_dvd⟩ := dvd_prod _ _ h_dvd_prod
    have hq_list : q ∈ c.primeFactorsList := by
      have h1 : q ∈ c.primeFactorsList.toFinset := hq_mem
      exact List.mem_toFinset.mp h1
    have hq_prime : q.Prime := Nat.prime_of_mem_primeFactorsList hq_list
    have hq_le : q ≤ p := h_max q hq_list
    have hq_pos : 0 < q - 1 := by
      have := hq_prime.two_le
      omega
    have h_p_le : p ≤ q - 1 := by
      obtain ⟨k, hk⟩ := hq_dvd
      have hk0 : 1 ≤ k := by
        by_contra h_k
        have : k = 0 := by omega
        rw [this, mul_zero] at hk
        omega
      calc
        p = p * 1 := by ring
        _ ≤ p * k := Nat.mul_le_mul_left p hk0
        _ = q - 1 := hk.symm
    omega

theorem padicValNat_totient_of_dvd_lem {c p : ℕ} (hp : p.Prime) (hc_pos : 0 < c)
  (h_max : ∀ q ∈ c.primeFactorsList, q ≤ p) (h_dvd : p ∣ c) :
  padicValNat p c.totient + 1 = padicValNat p c :=
by
  -- 1. Establish the strictly positive valuation of p in c
  have hk_pos : 0 < padicValNat p c := padicValNat_pos_of_dvd_lem hp hc_pos h_dvd

  -- 2. Establish the factorization of c into its p-adic part and the coprime part m
  obtain ⟨m, hm_eq⟩ := exists_mul_of_pow_padicValNat_dvd_lem p hc_pos

  -- 3. Obtain necessary properties of the multiplier m without unrolling subtractions
  obtain ⟨hpk_pos, hm_pos, h_ndvd, h_coprime, hm_max⟩ :=
    coprime_part_properties_lem hp hc_pos rfl hm_eq h_max

  -- 4. Calculate the valuation's multiplicativity across Euler's totient (phi) function
  -- We use `congrArg` instead of `rw` to prevent rewriting any `c` terms that are generated inside the expansion.
  have h_tot_mul : padicValNat p c.totient = padicValNat p (p ^ padicValNat p c).totient + padicValNat p m.totient := by
    calc
      padicValNat p c.totient = padicValNat p (p ^ padicValNat p c * m).totient := congrArg (fun x => padicValNat p x.totient) hm_eq
      _ = padicValNat p (p ^ padicValNat p c).totient + padicValNat p m.totient :=
        padicValNat_totient_mul_lem hp h_coprime hpk_pos hm_pos

  -- 5. By bounds constraint, phi(m) provides exactly 0 p-adic valuations (relies on the locally existing lemma)
  have h_tot_m : padicValNat p m.totient = 0 :=
    padicValNat_totient_of_not_dvd_lem hp hm_pos hm_max h_ndvd

  -- 6. The standard formula mapping: v_p(phi(p^k)) + 1 = k
  have h_tot_pk : padicValNat p (p ^ padicValNat p c).totient + 1 = padicValNat p c :=
    padicValNat_prime_pow_totient_lem hp hk_pos

  -- 7. Rewrite evaluations natively and solve strictly linear logic with `omega`
  rw [h_tot_mul, h_tot_m]
  omega

theorem padicValNat_totient_le_lem (c p : ℕ) (hp : p.Prime) (hc_pos : 0 < c)
  (h_max : ∀ q ∈ c.primeFactorsList, q ≤ p) :
  padicValNat p c.totient + (if p ∣ c then 1 else 0) ≤ padicValNat p c :=
by
  split_ifs with h
  · have h1 := padicValNat_totient_of_dvd_lem hp hc_pos h_max h
    omega
  · have h1 := padicValNat_totient_of_not_dvd_lem hp hc_pos h_max h
    omega

theorem padicValNat_lcm_eq_max_lem (a b p : ℕ) (hp : p.Prime) (ha : 0 < a) (hb : 0 < b) :
  padicValNat p (a.lcm b) = max (padicValNat p a) (padicValNat p b) :=
by
  -- Convert `padicValNat` expressions into `factorization` forms using the theorem directly
  rw [← Nat.factorization_def a hp]
  rw [← Nat.factorization_def b hp]
  rw [← Nat.factorization_def (a.lcm b) hp]

  -- Use the explicit `lcm` factorization theorem over non-zero parameters
  rw [Nat.factorization_lcm (ne_of_gt ha) (ne_of_gt hb)]

  -- `Finsupp.sup` (⊔) is constructed pointwise via `zipWith` where `sup` for `ℕ` is `max`.
  -- Thus, applying `p` evaluates cleanly down to `max (a.factorization p) (b.factorization p)` definitionally.
  rfl

theorem padicValNat_one_lem (p : ℕ) : padicValNat p 1 = 0 :=
padicValNat.one

theorem period_M_eq_of_gt_one_lem (c : ℕ) (hc : 1 < c) : period_M c = c.totient.lcm (period_M c.totient) :=
by
  rw [period_M, dif_pos hc]

theorem period_M_eq_one_of_le_one_lem (c : ℕ) (hc : c ≤ 1) : period_M c = 1 :=
by
  unfold period_M
  split
  · omega
  · rfl

theorem totient_lt_self_of_gt_one_lem (c : ℕ) (hc : 1 < c) : c.totient < c :=
Nat.totient_lt c hc

theorem totient_pos_of_pos_lem (c : ℕ) (hc : 0 < c) : 0 < c.totient :=
Nat.totient_pos.mpr hc

theorem primeFactorsList_totient_le_lem (c p : ℕ) (hp : p.Prime) (hc_pos : 0 < c)
  (h_max : ∀ q ∈ c.primeFactorsList, q ≤ p) :
  ∀ q ∈ c.totient.primeFactorsList, q ≤ p :=
by
  intro q hq

  -- Extract q.Prime and q | c.totient robustly using Mathlib's unconditional theorems
  have hq_prime : q.Prime := by
    have h_copy := hq
    rw [← Nat.mem_primeFactors_iff_mem_primeFactorsList, Nat.mem_primeFactors] at h_copy
    tauto

  have hq_dvd : q ∣ c.totient := by
    have h_copy := hq
    rw [← Nat.mem_primeFactors_iff_mem_primeFactorsList, Nat.mem_primeFactors] at h_copy
    tauto

  -- Use Euler's totient multiplicative formula directly in ℕ
  have hq_dvd_mul : q ∣ c * ∏ r ∈ c.primeFactors, (r - 1) := by
    have H_nat_eq := Nat.totient_mul_prod_primeFactors c
    rw [← H_nat_eq]
    exact dvd_mul_of_dvd_left hq_dvd _

  -- Euclid's lemma on the product
  have h_or : q ∣ c ∨ q ∣ ∏ r ∈ c.primeFactors, (r - 1) := (Nat.Prime.dvd_mul hq_prime).mp hq_dvd_mul

  rcases h_or with h_q_c | h_q_prod
  · -- Case 1: q | c
    have hq_in_c : q ∈ c.primeFactorsList := by
      rw [← Nat.mem_primeFactors_iff_mem_primeFactorsList, Nat.mem_primeFactors]
      have hc_ne : c ≠ 0 := by omega
      tauto
    exact h_max q hq_in_c

  · -- Case 2: q | ∏ (r - 1)
    have H_gen : ∀ s : Finset ℕ, q ∣ ∏ r ∈ s, (r - 1) → ∃ r ∈ s, q ∣ r - 1 := by
      intro s
      induction s using Finset.induction_on with
      | empty =>
        intro h
        rw [Finset.prod_empty] at h
        have h_pos : 0 < 1 := by omega
        have h_q_le_one : q ≤ 1 := Nat.le_of_dvd h_pos h
        have h_q_two : 2 ≤ q := hq_prime.two_le
        omega
      | insert a s ha ih =>
        intro h
        rw [Finset.prod_insert ha] at h
        have h_or_s : q ∣ a - 1 ∨ q ∣ ∏ r ∈ s, (r - 1) := (Nat.Prime.dvd_mul hq_prime).mp h
        rcases h_or_s with h_a | h_s
        · exact ⟨a, by simp, h_a⟩
        · rcases ih h_s with ⟨r, hr_mem_s, hr_dvd⟩
          exact ⟨r, by simp [hr_mem_s], hr_dvd⟩

    rcases H_gen c.primeFactors h_q_prod with ⟨r, hr, hr_dvd⟩

    have hr_prime : r.Prime := by
      have hr_copy := hr
      rw [Nat.mem_primeFactors] at hr_copy
      tauto

    have hr_in_list : r ∈ c.primeFactorsList := by
      rw [← Nat.mem_primeFactors_iff_mem_primeFactorsList]
      exact hr

    have hr_le_p : r ≤ p := h_max r hr_in_list

    -- Prove bounds without Z-casts directly applying pure linear integer arithmetic
    have hr_sub_pos : 0 < r - 1 := by
      have : 2 ≤ r := hr_prime.two_le
      omega

    have hq_le_r_sub_one : q ≤ r - 1 := Nat.le_of_dvd hr_sub_pos hr_dvd

    omega

theorem period_M_pos_lem (c : ℕ) : 0 < period_M c :=
by
  refine Nat.strongRecOn' c (fun n ih => ?_)
  rw [period_M]
  split_ifs with h
  · have h1 : n.totient < n := Nat.totient_lt n h
    have h2 : 0 < n.totient := Nat.totient_pos.mpr (by omega)
    have h3 : 0 < period_M n.totient := ih n.totient h1
    positivity
  · omega

theorem padicValNat_period_M_le_of_primeFactors_le (c p : ℕ) (hp : p.Prime) (hc_pos : 0 < c)
  (h_max : ∀ q ∈ c.primeFactorsList, q ≤ p) :
  padicValNat p (period_M c) + (if p ∣ c then 1 else 0) ≤ padicValNat p c :=
by
  revert hc_pos h_max
  refine Nat.strong_induction_on c ?_
  intro n ih hc_pos h_max
  by_cases hc : n ≤ 1
  · have h1 : n = 1 := by omega
    subst h1
    have hp1 : ¬ p ∣ 1 := by
      intro h
      have h_pos : 0 < 1 := by decide
      have h_le : p ≤ 1 := Nat.le_of_dvd h_pos h
      have h2 : 2 ≤ p := hp.two_le
      omega
    have h_pm : period_M 1 = 1 := period_M_eq_one_of_le_one_lem 1 (Nat.le_refl 1)
    rw [h_pm, padicValNat_one_lem p, if_neg hp1]
  · have hc_gt : 1 < n := by omega
    have h_pm : period_M n = n.totient.lcm (period_M n.totient) := period_M_eq_of_gt_one_lem n hc_gt
    rw [h_pm]

    have htot_pos : 0 < n.totient := totient_pos_of_pos_lem n hc_pos
    have hpm_pos : 0 < period_M n.totient := period_M_pos_lem n.totient
    rw [padicValNat_lcm_eq_max_lem n.totient (period_M n.totient) p hp htot_pos hpm_pos]

    have htot_lt : n.totient < n := totient_lt_self_of_gt_one_lem n hc_gt
    have htot_max : ∀ q ∈ n.totient.primeFactorsList, q ≤ p := primeFactorsList_totient_le_lem n p hp hc_pos h_max
    have ih_apply := ih n.totient htot_lt htot_pos htot_max

    have h_le := padicValNat_totient_le_lem n p hp hc_pos h_max

    have h_le_add : padicValNat p (period_M n.totient) ≤ padicValNat p (period_M n.totient) + (if p ∣ n.totient then 1 else 0) :=
      Nat.le_add_right _ _
    have h_le_tot : padicValNat p (period_M n.totient) ≤ padicValNat p n.totient :=
      Nat.le_trans h_le_add ih_apply

    have h_max_eq : max (padicValNat p n.totient) (padicValNat p (period_M n.totient)) = padicValNat p n.totient := max_eq_left h_le_tot
    rw [h_max_eq]
    exact h_le

theorem padicValNat_period_M_le_of_le_local {c p : ℕ} (hc_pos : 0 < c) (hp : p.Prime) (hpc : p ∣ c)
  (h_max : ∀ q, q.Prime → q ∣ c → q ≤ p) : padicValNat p (period_M c) + 1 ≤ padicValNat p c :=
by
  have h_max_list := primeFactorsList_le_of_prime_dvd_le_local hc_pos h_max
  have h_bound := padicValNat_period_M_le_of_primeFactors_le c p hp hc_pos h_max_list
  rw [if_pos hpc] at h_bound
  exact h_bound

theorem padicValNat_le_of_dvd_of_prime_local {a b p : ℕ} (hb : 0 < b) (hp : p.Prime) (h_dvd : a ∣ b) :
  padicValNat p a ≤ padicValNat p b :=
by
  have hb_ne : b ≠ 0 := by omega
  have ha_ne : a ≠ 0 := by
    rintro rfl
    rcases h_dvd with ⟨c, hc⟩
    omega
  have _ : Fact (Nat.Prime p) := ⟨hp⟩
  have h1 : p ^ padicValNat p a ∣ a := (padicValNat_dvd_iff_le ha_ne).mpr le_rfl
  have h2 : p ^ padicValNat p a ∣ b := dvd_trans h1 h_dvd
  exact (padicValNat_dvd_iff_le hb_ne).mp h2

theorem gcd_period_M_lt {c : ℕ} (hc : 1 < c) : Nat.gcd (period_M c) c < c :=
by
  -- 1. Initial Setup & Bounds
  have hc_pos : 0 < c := by omega

  -- 2. Contradiction Assumption
  by_contra h_not_lt

  -- Establish h_eq : Nat.gcd (period_M c) c = c
  have h_eq : Nat.gcd (period_M c) c = c := by
    have h_le : Nat.gcd (period_M c) c ≤ c := Nat.le_of_dvd hc_pos (Nat.gcd_dvd_right (period_M c) c)
    omega

  -- 3. Deduce Divisibility
  have h_dvd : c ∣ period_M c := by
    have h_gcd_dvd_left := Nat.gcd_dvd_left (period_M c) c
    rw [h_eq] at h_gcd_dvd_left
    exact h_gcd_dvd_left

  have h_per_pos : 0 < period_M c := period_M_pos_local c

  -- 4. Extract Maximal Prime Factor
  obtain ⟨p, hp, hpc, h_max⟩ := max_prime_factor_exists_local c hc

  -- 5. Evaluate Valuations
  -- Strict upper bound established from the properties of the Markov period
  have h_val_lt : padicValNat p (period_M c) + 1 ≤ padicValNat p c :=
    padicValNat_period_M_le_of_le_local hc_pos hp hpc h_max

  -- Lower bound deduced from our local divisibility helper lemma
  have h_val_ge : padicValNat p c ≤ padicValNat p (period_M c) :=
    padicValNat_le_of_dvd_of_prime_local h_per_pos hp h_dvd

  -- 6. Conclude Contradiction
  -- The valuations are bounded by physically contradictory constraints.
  -- `omega` effortlessly discharges this mathematical impossibility.
  omega

theorem mod_eq_consequences (c : ℕ) (k₁ k₂ : ℕ) (hc : 1 < c)
  (hk₁ : k₁ + 1 ≥ c) (hk₂ : k₂ + 1 ≥ c)
  (h_mod : ((k₁ + 1 : ℕ) : ℤ) % (period_M c : ℤ) = ((k₂ + 1 : ℕ) : ℤ) % (period_M c : ℤ)) :
  ((k₁ + 1 : ℕ) : ℤ) % (c.totient : ℤ) = ((k₂ + 1 : ℕ) : ℤ) % (c.totient : ℤ) ∧
  (k₁ : ℤ) % (period_M c.totient : ℤ) = (k₂ : ℤ) % (period_M c.totient : ℤ) :=
by

  -- 1. Unfold the definition of period_M localized to the LHS
  have h_period : period_M c = Nat.lcm c.totient (period_M c.totient) := by
    conv =>
      lhs
      unfold period_M
    rw [dif_pos hc]

  -- 2. Obtain divisibility properties in natural numbers
  have h_lcm1 : c.totient ∣ period_M c := by
    rw [h_period]
    exact Nat.dvd_lcm_left _ _

  have h_lcm2 : period_M c.totient ∣ period_M c := by
    rw [h_period]
    exact Nat.dvd_lcm_right _ _

  -- 3. Transfer divisibility to integers
  have h_lcm1_z : (c.totient : ℤ) ∣ (period_M c : ℤ) := by exact_mod_cast h_lcm1
  have h_lcm2_z : (period_M c.totient : ℤ) ∣ (period_M c : ℤ) := by exact_mod_cast h_lcm2

  -- 4. Reinterpret modular equation as congruence and then divisibility
  have h_mod_eq : ((k₁ + 1 : ℕ) : ℤ) ≡ ((k₂ + 1 : ℕ) : ℤ) [ZMOD (period_M c : ℤ)] := h_mod

  have h_diff_dvd : (period_M c : ℤ) ∣ ((k₂ + 1 : ℕ) : ℤ) - ((k₁ + 1 : ℕ) : ℤ) :=
    Int.modEq_iff_dvd.mp h_mod_eq

  -- 5. By transitivity, the difference is divisible by both components
  have hdvd1 : (c.totient : ℤ) ∣ ((k₂ + 1 : ℕ) : ℤ) - ((k₁ + 1 : ℕ) : ℤ) :=
    dvd_trans h_lcm1_z h_diff_dvd

  have hdvd2 : (period_M c.totient : ℤ) ∣ ((k₂ + 1 : ℕ) : ℤ) - ((k₁ + 1 : ℕ) : ℤ) :=
    dvd_trans h_lcm2_z h_diff_dvd

  -- 6. Prove the first part of the conjunction
  have h_goal1 : ((k₁ + 1 : ℕ) : ℤ) % (c.totient : ℤ) = ((k₂ + 1 : ℕ) : ℤ) % (c.totient : ℤ) :=
    Int.modEq_iff_dvd.mpr hdvd1

  -- 7. Prepare the setup for the second part of the conjunction
  have h_eq : ((k₂ + 1 : ℕ) : ℤ) - ((k₁ + 1 : ℕ) : ℤ) = (k₂ : ℤ) - (k₁ : ℤ) := by
    push_cast
    ring

  rw [h_eq] at hdvd2

  -- 8. Translate back into modulo resolution
  have h_goal2 : (k₁ : ℤ) % (period_M c.totient : ℤ) = (k₂ : ℤ) % (period_M c.totient : ℤ) :=
    Int.modEq_iff_dvd.mpr hdvd2

  exact ⟨h_goal1, h_goal2⟩

theorem F_ge_n_trans (F : ℕ → ℕ) (hF1 : F 1 = 1) (hF_rec : ∀ n ≥ 1, F (n+1) = (n+1) ^ F n)
  (n c : ℕ) (hn : n ≥ c) (hc : 0 < c) :
  F n ≥ c :=
by
  have H : ∀ m, F m ≥ m := by
    intro m
    induction m with
    | zero => exact Nat.zero_le (F 0)
    | succ k ih =>
      change F (k + 1) ≥ k + 1
      by_cases hk : k = 0
      · subst hk
        change F 1 ≥ 1
        -- `omega` can directly utilize the local hypothesis `hF1 : F 1 = 1`
        -- and solve the system without risking `rw` closing the goal silently.
        omega
      · have hk1 : k ≥ 1 := by omega
        rw [hF_rec k hk1]
        have base_le : 1 ≤ k + 1 := by omega
        have exp_le : 1 ≤ F k := by omega

        -- Apply Mathlib's generic Monoid power monotonicity theorem
        have h_pow := pow_le_pow_right' base_le exp_le
        rw [pow_one] at h_pow
        exact h_pow

  have Hn := H n
  omega

theorem F_mod_eq_of_k_mod_eq (F : ℕ → ℕ) (hF1 : F 1 = 1) (hF_rec : ∀ n ≥ 1, F (n+1) = (n+1) ^ F n)
  (c : ℕ) (hc : 1 < c)
  (k₁ k₂ : ℕ) (hk₁ : k₁ + 1 ≥ c) (hk₂ : k₂ + 1 ≥ c)
  (h_n_mod : ((k₁ + 1 : ℕ) : ℤ) % (c.totient : ℤ) = ((k₂ + 1 : ℕ) : ℤ) % (c.totient : ℤ))
  (h_k_pow_mod : (((k₁ + 1 : ℕ) : ℤ) ^ F k₁) % (c.totient : ℤ) = (((k₁ + 1 : ℕ) : ℤ) ^ F k₂) % (c.totient : ℤ)) :
  (F (k₁ + 1) : ℤ) % (c.totient : ℤ) = (F (k₂ + 1) : ℤ) % (c.totient : ℤ) :=
by
  have hk1_ge : k₁ ≥ 1 := by omega
  have hk2_ge : k₂ ≥ 1 := by omega
  rw [hF_rec k₁ hk1_ge, hF_rec k₂ hk2_ge]
  push_cast at h_k_pow_mod h_n_mod ⊢
  rw [h_k_pow_mod]
  exact Int.ModEq.pow (F k₂) h_n_mod

theorem totient_pos_of_gt_one (c : ℕ) (hc : 1 < c) : 0 < c.totient :=
by
  rw [Nat.totient_pos]
  omega

theorem totient_lt_of_gt_one (c : ℕ) (hc : 1 < c) : c.totient < c :=
Nat.totient_lt c hc

theorem int_mod_one_eq_zero (x : ℤ) : x % ((1 : ℕ) : ℤ) = 0 :=
by
  push_cast
  omega

theorem eq_of_mod_totient_zero (n m : ℕ) (h : (n : ℤ) % ((0 : ℕ).totient : ℤ) = (m : ℤ) % ((0 : ℕ).totient : ℤ)) : n = m :=
by
  change (n : ℤ) % (0 : ℤ) = (m : ℤ) % (0 : ℤ) at h
  simp at h
  omega

theorem nat_mod_eq_of_int_mod_eq (n m d : ℕ) (h : (n : ℤ) % (d : ℤ) = (m : ℤ) % (d : ℤ)) : n % d = m % d :=
by
  exact_mod_cast h

theorem int_mod_eq_of_nat_mod_eq (x y c : ℕ) (h : x % c = y % c) : (x : ℤ) % (c : ℤ) = (y : ℤ) % (c : ℤ) :=
by
  rw [← Int.natCast_mod x c, h, Int.natCast_mod y c]

theorem pow_mod_prime_pow_eq {a c n m p : ℕ} (hp : p.Prime) (hc : 0 < c) (hn : n ≥ c) (hm : m ≥ c)
  (h_mod : n % c.totient = m % c.totient) :
  (a ^ n) % (p ^ padicValNat p c) = (a ^ m) % (p ^ padicValNat p c) :=
by
  by_cases hv : padicValNat p c = 0
  · rw [hv, pow_zero, Nat.mod_one, Nat.mod_one]
  · have hv_pos : 0 < padicValNat p c := Nat.pos_of_ne_zero hv

    have h_fact : c.factorization p = padicValNat p c := Nat.factorization_def c hp
    have hdvd : p ^ padicValNat p c ∣ c := by
      rw [← h_fact]
      exact Nat.ordProj_dvd c p

    have hp_pos : 0 < p := hp.pos
    have hp2 : 2 ≤ p := hp.two_le

    have hp_pow_pos : ∀ k, 0 < p ^ k := by
      intro k
      induction k with
      | zero => exact Nat.zero_lt_one
      | succ k' ih =>
        have h_pow : p ^ (k' + 1) = p ^ k' * p := rfl
        rw [h_pow]
        exact Nat.mul_pos ih hp_pos

    have hv_le_pow : padicValNat p c ≤ p ^ padicValNat p c := by
      have h_le : ∀ v, v ≤ p ^ v := by
        intro v
        induction v with
        | zero => exact Nat.zero_le _
        | succ d ih =>
          have h2 : 1 ≤ p ^ d := hp_pow_pos d
          have h3 : p ^ d * 2 ≤ p ^ d * p := Nat.mul_le_mul_left _ hp2
          have h4 : p ^ (d + 1) = p ^ d * p := rfl
          omega
      exact h_le (padicValNat p c)

    have hpv_le_c : p ^ padicValNat p c ≤ c := Nat.le_of_dvd hc hdvd
    have hv_le_n : padicValNat p c ≤ n := by omega
    have hv_le_m : padicValNat p c ≤ m := by omega

    by_cases hpa : p ∣ a
    · have hpn : p ^ padicValNat p c ∣ p ^ n := by
        use p ^ (n - padicValNat p c)
        rw [← pow_add]
        have h_eq : padicValNat p c + (n - padicValNat p c) = n := by omega
        rw [h_eq]
      have han : p ^ n ∣ a ^ n := by
        rcases hpa with ⟨k, hk⟩
        use k ^ n
        rw [hk, mul_pow]
      have hvan : p ^ padicValNat p c ∣ a ^ n := Nat.dvd_trans hpn han
      have h_mod_n : a ^ n % p ^ padicValNat p c = 0 := Nat.mod_eq_zero_of_dvd hvan

      have hpm : p ^ padicValNat p c ∣ p ^ m := by
        use p ^ (m - padicValNat p c)
        rw [← pow_add]
        have h_eq : padicValNat p c + (m - padicValNat p c) = m := by omega
        rw [h_eq]
      have ham : p ^ m ∣ a ^ m := by
        rcases hpa with ⟨k, hk⟩
        use k ^ m
        rw [hk, mul_pow]
      have hvam : p ^ padicValNat p c ∣ a ^ m := Nat.dvd_trans hpm ham
      have h_mod_m : a ^ m % p ^ padicValNat p c = 0 := Nat.mod_eq_zero_of_dvd hvam

      rw [h_mod_n, h_mod_m]

    · have hcop : Nat.Coprime p a := (Nat.Prime.coprime_iff_not_dvd hp).mpr hpa
      have hcop_symm : Nat.Coprime a p := hcop.symm
      have hcop_v : Nat.Coprime a (p ^ padicValNat p c) := Nat.Coprime.pow_right _ hcop_symm

      have htot_dvd : (p ^ padicValNat p c).totient ∣ c.totient := Nat.totient_dvd_of_dvd hdvd
      have h_modeq : n ≡ m [MOD c.totient] := h_mod
      have h_mod_pv : n % (p ^ padicValNat p c).totient = m % (p ^ padicValNat p c).totient :=
        Nat.ModEq.of_dvd htot_dvd h_modeq

      let M := p ^ padicValNat p c
      let T := M.totient

      have h_euler : a ^ T ≡ 1 [MOD M] := Nat.ModEq.pow_totient hcop_v

      have h_pow_n : a ^ n = (a ^ T) ^ (n / T) * a ^ (n % T) := by
        symm
        rw [← pow_mul, ← pow_add]
        have h_eq : T * (n / T) + n % T = n := Nat.div_add_mod n T
        rw [h_eq]

      have h_pow_m : a ^ m = (a ^ T) ^ (m / T) * a ^ (m % T) := by
        symm
        rw [← pow_mul, ← pow_add]
        have h_eq : T * (m / T) + m % T = m := Nat.div_add_mod m T
        rw [h_eq]

      have h_pow_euler_n : (a ^ T) ^ (n / T) ≡ 1 ^ (n / T) [MOD M] := Nat.ModEq.pow (n / T) h_euler
      have h_pow_euler_n2 : (a ^ T) ^ (n / T) ≡ 1 [MOD M] := by
        have h_one : 1 ^ (n / T) = 1 := one_pow _
        rw [h_one] at h_pow_euler_n
        exact h_pow_euler_n

      have h_pow_euler_m : (a ^ T) ^ (m / T) ≡ 1 ^ (m / T) [MOD M] := Nat.ModEq.pow (m / T) h_euler
      have h_pow_euler_m2 : (a ^ T) ^ (m / T) ≡ 1 [MOD M] := by
        have h_one : 1 ^ (m / T) = 1 := one_pow _
        rw [h_one] at h_pow_euler_m
        exact h_pow_euler_m

      have h_n_mod : a ^ n ≡ a ^ (n % T) [MOD M] := by
        have h1 := Nat.ModEq.mul h_pow_euler_n2 (Nat.ModEq.refl (a ^ (n % T)))
        rw [one_mul] at h1
        rw [h_pow_n]
        exact h1

      have h_m_mod : a ^ m ≡ a ^ (m % T) [MOD M] := by
        have h1 := Nat.ModEq.mul h_pow_euler_m2 (Nat.ModEq.refl (a ^ (m % T)))
        rw [one_mul] at h1
        rw [h_pow_m]
        exact h1

      have h_mod_pv2 : n % T = m % T := h_mod_pv
      have h_n_mod_eq : a ^ (n % T) = a ^ (m % T) := by rw [h_mod_pv2]

      have h_final : a ^ n ≡ a ^ m [MOD M] := by
        have step1 : a ^ n ≡ a ^ (m % T) [MOD M] := by
          rw [← h_n_mod_eq]
          exact h_n_mod
        have step2 : a ^ (m % T) ≡ a ^ m [MOD M] := Nat.ModEq.symm h_m_mod
        exact Nat.ModEq.trans step1 step2

      exact h_final

theorem nat_mod_eq_iff_int_dvd (A B c : ℕ) : A % c = B % c ↔ (c : ℤ) ∣ ((A : ℤ) - (B : ℤ)) :=
by
  constructor
  · intro h
    have h' : A ≡ B [MOD c] := h
    have h1 : (c : ℤ) ∣ (B : ℤ) - (A : ℤ) := Nat.modEq_iff_dvd.mp h'
    rcases h1 with ⟨k, hk⟩
    use -k
    calc (A : ℤ) - (B : ℤ) = -((B : ℤ) - (A : ℤ)) := by ring
      _ = -((c : ℤ) * k) := by rw [hk]
      _ = (c : ℤ) * -k := by ring
  · intro h
    have h1 : (c : ℤ) ∣ (B : ℤ) - (A : ℤ) := by
      rcases h with ⟨k, hk⟩
      use -k
      calc (B : ℤ) - (A : ℤ) = -((A : ℤ) - (B : ℤ)) := by ring
        _ = -((c : ℤ) * k) := by rw [hk]
        _ = (c : ℤ) * -k := by ring
    have h' : A ≡ B [MOD c] := Nat.modEq_iff_dvd.mpr h1
    exact h'

theorem int_dvd_iff_natAbs_dvd (c : ℕ) (z : ℤ) : (c : ℤ) ∣ z ↔ c ∣ z.natAbs :=
Int.natCast_dvd

theorem nat_dvd_of_forall_prime_pow_dvd {c X : ℕ} (hc : 0 < c) (h : ∀ p : ℕ, p.Prime → p ^ padicValNat p c ∣ X) : c ∣ X :=
by
  by_cases hX : X = 0
  · rw [hX]
    exact dvd_zero c
  · have hc0 : c ≠ 0 := ne_of_gt hc
    apply (@Nat.ordProj_dvd_ordProj_iff_dvd c X hc0 hX).mp
    intro p
    by_cases hp : p.Prime
    · have h1 : p ^ c.factorization p ∣ c := Nat.ordProj_dvd c p
      have h2 : c.factorization p ≤ padicValNat p c :=
        (@padicValNat_dvd_iff_le p ⟨hp⟩ c (c.factorization p) hc0).mp h1
      have h3 : p ^ c.factorization p ∣ p ^ padicValNat p c := pow_dvd_pow p h2
      have h4 : p ^ padicValNat p c ∣ X := h p hp
      have h5 : p ^ c.factorization p ∣ X := dvd_trans h3 h4
      exact (@Nat.Prime.pow_dvd_iff_dvd_ordProj p (c.factorization p) X hp hX).mp h5
    · have hcp : c.factorization p = 0 := by simp [hp]
      rw [hcp, pow_zero]
      exact ⟨p ^ X.factorization p, (one_mul (p ^ X.factorization p)).symm⟩

theorem nat_mod_eq_of_forall_prime_pow {A B c : ℕ} (hc : 0 < c)
  (h : ∀ p : ℕ, p.Prime → A % (p ^ padicValNat p c) = B % (p ^ padicValNat p c)) :
  A % c = B % c :=
by
  apply (nat_mod_eq_iff_int_dvd A B c).mpr
  apply (int_dvd_iff_natAbs_dvd c ((A : ℤ) - (B : ℤ))).mpr
  apply nat_dvd_of_forall_prime_pow_dvd hc
  intro p hp
  apply (int_dvd_iff_natAbs_dvd (p ^ padicValNat p c) ((A : ℤ) - (B : ℤ))).mp
  apply (nat_mod_eq_iff_int_dvd A B (p ^ padicValNat p c)).mp
  exact h p hp

theorem pow_mod_eq_of_mod_totient_nat (a c n m : ℕ) (h_mod : n % c.totient = m % c.totient)
  (hn : n ≥ c) (hm : m ≥ c) (hc : 0 < c) :
  (a ^ n) % c = (a ^ m) % c :=
by
  apply nat_mod_eq_of_forall_prime_pow hc
  intro p hp
  apply pow_mod_prime_pow_eq hp hc hn hm h_mod

theorem int_pow_mod_eq_toNat_pow_mod (a : ℤ) (c n : ℕ) (hc : 0 < c) :
  (a ^ n : ℤ) % (c : ℤ) = (((a % (c : ℤ)).toNat ^ n : ℕ) : ℤ) % (c : ℤ) :=
by
  have h_mod_nonneg : 0 ≤ a % (c : ℤ) := by
    apply Int.emod_nonneg
    omega
  have h_toNat : ((a % (c : ℤ)).toNat : ℤ) = a % (c : ℤ) := Int.toNat_of_nonneg h_mod_nonneg
  rw [Nat.cast_pow]
  rw [h_toNat]
  have h_modeq : Int.ModEq (c : ℤ) a (a % (c : ℤ)) := by
    change a % (c : ℤ) = (a % (c : ℤ)) % (c : ℤ)
    exact Eq.symm (Int.emod_emod a (c : ℤ))
  exact Int.ModEq.pow n h_modeq

theorem pow_mod_eq_of_mod_totient (a : ℤ) (c n m : ℕ)
  (h_mod : (n : ℤ) % (c.totient : ℤ) = (m : ℤ) % (c.totient : ℤ))
  (hn : n ≥ c) (hm : m ≥ c) :
  (a ^ n : ℤ) % (c : ℤ) = (a ^ m : ℤ) % (c : ℤ) :=
by
  -- Evaluate standard cases over the boundary condition c = 0 vs c > 0
  have hc_cases : c = 0 ∨ 0 < c := by
    cases c with
    | zero => exact Or.inl rfl
    | succ c' => exact Or.inr (Nat.zero_lt_succ c')

  cases hc_cases with
  | inl h_eq =>
    -- Case 1: c = 0
    subst h_eq
    have h1 : n = m := eq_of_mod_totient_zero n m h_mod
    rw [h1]
  | inr hc_pos =>
    -- Case 2: c > 0
    -- Step A: Cast equivalence natively to ℕ
    have hn_mod : n % c.totient = m % c.totient := nat_mod_eq_of_int_mod_eq n m c.totient h_mod

    -- Step B: Use `toNat` representations to resolve modulus parity issues cleanly
    have h2 : (a ^ n : ℤ) % (c : ℤ) = (((a % (c : ℤ)).toNat ^ n : ℕ) : ℤ) % (c : ℤ) := int_pow_mod_eq_toNat_pow_mod a c n hc_pos
    have h3 : (a ^ m : ℤ) % (c : ℤ) = (((a % (c : ℤ)).toNat ^ m : ℕ) : ℤ) % (c : ℤ) := int_pow_mod_eq_toNat_pow_mod a c m hc_pos
    rw [h2, h3]

    -- Step C: Push the logical proof off to our purely Natural-number helper lemma
    have h4 : ((a % (c : ℤ)).toNat ^ n) % c = ((a % (c : ℤ)).toNat ^ m) % c :=
      pow_mod_eq_of_mod_totient_nat ((a % (c : ℤ)).toNat) c n m hn_mod hn hm hc_pos

    -- Close goal symmetrically mapping our proof in ℕ back natively to ℤ
    exact int_mod_eq_of_nat_mod_eq _ _ _ h4

theorem period_M_works (F : ℕ → ℕ) (hF1 : F 1 = 1) (hF_rec : ∀ n ≥ 1, F (n+1) = (n+1) ^ F n)
  (c : ℕ) (hc : 0 < c) (a : ℤ) :
  ∀ n₁ n₂ : ℕ, n₁ ≥ c → n₂ ≥ c → (n₁ : ℤ) % (period_M c : ℤ) = (n₂ : ℤ) % (period_M c : ℤ) →
  (a ^ F n₁ : ℤ) % (c : ℤ) = (a ^ F n₂ : ℤ) % (c : ℤ) :=
by
  revert a hc
  induction' c using Nat.strong_induction_on with c ih
  intro hc a n₁ n₂ hn₁ hn₂ hmod
  obtain rfl | hc_gt : c = 1 ∨ 1 < c := by omega
  · rw [int_mod_one_eq_zero, int_mod_one_eq_zero]
  · obtain ⟨k₁, rfl⟩ : ∃ k, n₁ = k + 1 := by
      cases n₁ with
      | zero => exfalso; omega
      | succ k => exact ⟨k, rfl⟩
    obtain ⟨k₂, rfl⟩ : ∃ k, n₂ = k + 1 := by
      cases n₂ with
      | zero => exfalso; omega
      | succ k => exact ⟨k, rfl⟩

    have h_mod_cons := mod_eq_consequences c k₁ k₂ hc_gt hn₁ hn₂ hmod
    have h_n_mod := h_mod_cons.1
    have h_k_mod := h_mod_cons.2

    have htpos : 0 < c.totient := totient_pos_of_gt_one c hc_gt
    have htlt : c.totient < c := totient_lt_of_gt_one c hc_gt

    have h_k_pow_mod := ih c.totient htlt htpos ((k₁ + 1 : ℕ) : ℤ) k₁ k₂ (by omega) (by omega) h_k_mod

    have h_F_mod := F_mod_eq_of_k_mod_eq F hF1 hF_rec c hc_gt k₁ k₂ hn₁ hn₂ h_n_mod h_k_pow_mod

    have hF1_ge := F_ge_n_trans F hF1 hF_rec (k₁ + 1) c hn₁ (by omega)
    have hF2_ge := F_ge_n_trans F hF1 hF_rec (k₂ + 1) c hn₂ (by omega)

    exact pow_mod_eq_of_mod_totient a c (F (k₁ + 1)) (F (k₂ + 1)) h_F_mod hF1_ge hF2_ge

theorem exists_period_and_reduction (F : ℕ → ℕ) (hF1 : F 1 = 1) (hF_rec : ∀ n ≥ 1, F (n+1) = (n+1) ^ F n)
    (a : ℤ) (c : ℕ) (hc : 1 < c) :
  ∃ M : ℕ, 0 < M ∧ Nat.gcd M c < c ∧
  ∀ n₁ n₂ : ℕ, n₁ ≥ c → n₂ ≥ c → (n₁ : ℤ) % (M : ℤ) = (n₂ : ℤ) % (M : ℤ) →
    (a ^ F n₁ : ℤ) % (c : ℤ) = (a ^ F n₂ : ℤ) % (c : ℤ) :=
by
  use period_M c
  have hpos : 0 < period_M c := period_M_pos c
  have hgcd : Nat.gcd (period_M c) c < c := gcd_period_M_lt hc
  have hc_pos : 0 < c := by omega
  exact ⟨hpos, hgcd, period_M_works F hF1 hF_rec c hc_pos a⟩

theorem crt_condition (d : ℕ) (m : ℕ) (b a_Fm : ℤ) (h_div : (d : ℤ) ∣ a_Fm + m - b) :
    (m : ℤ) % (d : ℤ) = (b - a_Fm) % (d : ℤ) :=
by
  apply Int.modEq_of_dvd
  rcases h_div with ⟨k, hk⟩
  use -k
  calc
    (b - a_Fm) - (m : ℤ) = - (a_Fm + m - b) := by ring
    _ = - ((d : ℤ) * k) := by rw [hk]
    _ = (d : ℤ) * -k := by ring

theorem crt_like_int (M c : ℕ) (hM : 0 < M) (hc : 0 < c)
    (x : ℤ) (y : ℤ) (hx : x % (Nat.gcd M c : ℤ) = y % (Nat.gcd M c : ℤ)) (B : ℕ) :
    ∃ n : ℕ, n ≥ B ∧ (n : ℤ) % (M : ℤ) = x % (M : ℤ) ∧ (n : ℤ) % (c : ℤ) = y % (c : ℤ) :=
by
  have hx_modEq : Int.ModEq (Nat.gcd M c : ℤ) x y := hx
  have hdvd : (Nat.gcd M c : ℤ) ∣ x - y := Int.modEq_iff_dvd.mp hx_modEq.symm
  obtain ⟨k, hk⟩ := hdvd

  have h4 : (Nat.gcd M c : ℤ) = (M : ℤ) * Int.gcdA (M : ℤ) (c : ℤ) + (c : ℤ) * Int.gcdB (M : ℤ) (c : ℤ) :=
    Int.gcd_eq_gcd_ab (M : ℤ) (c : ℤ)

  let n_0 := x - (M : ℤ) * (Int.gcdA (M : ℤ) (c : ℤ) * k)
  let t : ℤ := (Int.natAbs ((B : ℤ) - n_0) : ℤ)

  let N := n_0 + t * ((M : ℤ) * (c : ℤ))
  have h_N_ge : N ≥ (B : ℤ) := by
    have hM_pos : (M : ℤ) ≥ 1 := by omega
    have hc_pos : (c : ℤ) ≥ 1 := by omega
    have ht_bound : t ≥ (B : ℤ) - n_0 := by
      have : t = (Int.natAbs ((B : ℤ) - n_0) : ℤ) := rfl
      omega
    have hL : (M : ℤ) * (c : ℤ) ≥ 1 := by nlinarith
    have htL : t * ((M : ℤ) * (c : ℤ)) ≥ t := by
      have ht_pos : t ≥ 0 := by
        have : t = (Int.natAbs ((B : ℤ) - n_0) : ℤ) := rfl
        omega
      nlinarith
    dsimp [N]
    nlinarith

  have hN_pos : N ≥ 0 := by omega

  let n := N.toNat
  have hn_eq : (n : ℤ) = N := by
    change (N.toNat : ℤ) = N
    omega

  have hn_B : n ≥ B := by omega

  use n
  refine ⟨hn_B, ?_, ?_⟩

  · have H : N = x + (M : ℤ) * (- (Int.gcdA (M : ℤ) (c : ℤ) * k) + t * (c : ℤ)) := by
      dsimp [N, n_0]
      ring
    rw [hn_eq, H, Int.add_mul_emod_self_left]

  · have H : N = y + (c : ℤ) * (Int.gcdB (M : ℤ) (c : ℤ) * k + (M : ℤ) * t) := by
      dsimp [N, n_0]
      have h_gcd_sub : (M : ℤ) * Int.gcdA (M : ℤ) (c : ℤ) = (Nat.gcd M c : ℤ) - (c : ℤ) * Int.gcdB (M : ℤ) (c : ℤ) := by
        calc (M : ℤ) * Int.gcdA (M : ℤ) (c : ℤ) = (M : ℤ) * Int.gcdA (M : ℤ) (c : ℤ) + (c : ℤ) * Int.gcdB (M : ℤ) (c : ℤ) - (c : ℤ) * Int.gcdB (M : ℤ) (c : ℤ) := by ring
          _ = (Nat.gcd M c : ℤ) - (c : ℤ) * Int.gcdB (M : ℤ) (c : ℤ) := by rw [← h4]
      have h_sub : (Nat.gcd M c : ℤ) * k = x - y := hk.symm
      calc x - (M : ℤ) * (Int.gcdA (M : ℤ) (c : ℤ) * k) + t * ((M : ℤ) * (c : ℤ))
        _ = x - ((M : ℤ) * Int.gcdA (M : ℤ) (c : ℤ)) * k + (c : ℤ) * ((M : ℤ) * t) := by ring
        _ = x - ((Nat.gcd M c : ℤ) - (c : ℤ) * Int.gcdB (M : ℤ) (c : ℤ)) * k + (c : ℤ) * ((M : ℤ) * t) := by rw [h_gcd_sub]
        _ = x - (Nat.gcd M c : ℤ) * k + (c : ℤ) * Int.gcdB (M : ℤ) (c : ℤ) * k + (c : ℤ) * ((M : ℤ) * t) := by ring
        _ = x - (x - y) + (c : ℤ) * Int.gcdB (M : ℤ) (c : ℤ) * k + (c : ℤ) * ((M : ℤ) * t) := by rw [h_sub]
        _ = y + (c : ℤ) * (Int.gcdB (M : ℤ) (c : ℤ) * k + (M : ℤ) * t) := by ring
    rw [hn_eq, H, Int.add_mul_emod_self_left]

theorem final_divisibility (c M : ℕ) (m n : ℕ) (a_Fn a_Fm b : ℤ)
    (hn_mod_c : (n : ℤ) % (c : ℤ) = (b - a_Fm) % (c : ℤ))
    (h_per : a_Fn % (c : ℤ) = a_Fm % (c : ℤ)) :
    (c : ℤ) ∣ a_Fn + n - b :=
by
  have h_per_mod : Int.ModEq (c : ℤ) a_Fm a_Fn := Eq.symm h_per
  have h1 : (c : ℤ) ∣ a_Fn - a_Fm := Int.modEq_iff_dvd.mp h_per_mod

  have hn_mod_c_mod : Int.ModEq (c : ℤ) (b - a_Fm) (n : ℤ) := Eq.symm hn_mod_c
  have h2 : (c : ℤ) ∣ (n : ℤ) - (b - a_Fm) := Int.modEq_iff_dvd.mp hn_mod_c_mod

  have h3 : (c : ℤ) ∣ (a_Fn - a_Fm) + ((n : ℤ) - (b - a_Fm)) := dvd_add h1 h2

  have h4 : (a_Fn - a_Fm) + ((n : ℤ) - (b - a_Fm)) = a_Fn + n - b := by ring

  rw [h4] at h3
  exact h3

theorem PB_generalized_step (F : ℕ → ℕ) (hF1 : F 1 = 1) (hF_rec : ∀ n ≥ 1, F (n+1) = (n+1) ^ F n)
    (a : ℤ) (c : ℕ) (hc : 1 < c)
    (IH : ∀ c' < c, 0 < c' → ∀ (K : ℕ) (b : ℤ), ∃ n : ℕ, n ≥ K ∧ (c' : ℤ) ∣ a ^ F n + (n : ℤ) - b)
    (K : ℕ) (b : ℤ) :
    ∃ n : ℕ, n ≥ K ∧ (c : ℤ) ∣ a ^ F n + (n : ℤ) - b :=
by
  -- Guarantee that c > 0 from 1 < c
  have hc_pos : 0 < c := by omega

  -- Extract the period modulus M and associated period properties
  have h_per_red := exists_period_and_reduction F hF1 hF_rec a c hc
  obtain ⟨M, hM_pos, hgcd_lt, h_per⟩ := h_per_red

  -- The gcd(M, c) is strictly positive because c > 0
  have hd_pos : 0 < Nat.gcd M c := by
    apply Nat.pos_of_ne_zero
    intro h
    have : c = 0 := (Nat.gcd_eq_zero_iff.mp h).2
    omega

  -- Apply the strong induction hypothesis on the strictly smaller modulus gcd(M, c)
  have h_IH := IH (Nat.gcd M c) hgcd_lt hd_pos (max K c) b
  obtain ⟨m, hm_ge, h_div⟩ := h_IH

  -- Convert the divisibility constraint to a modulo equivalence equation
  have h_mod : (m : ℤ) % (Nat.gcd M c : ℤ) = (b - a ^ F m) % (Nat.gcd M c : ℤ) :=
    crt_condition (Nat.gcd M c) m b (a ^ F m) h_div

  -- Use the Generalized Chinese Remainder Theorem logic to extract a greater bound 'n'
  have h_crt := crt_like_int M c hM_pos hc_pos (m : ℤ) (b - a ^ F m) h_mod (max K c)
  obtain ⟨n, hn_ge, hn_M, hn_c⟩ := h_crt

  -- Deduce bounds compatibility for the periodicity threshold
  have hn_c_ge : n ≥ c := by omega
  have hm_c_ge : m ≥ c := by omega

  -- Because n ≡ m (mod M), mapping over the period guarantees congruency for powers
  have h_per_app : (a ^ F n : ℤ) % (c : ℤ) = (a ^ F m : ℤ) % (c : ℤ) :=
    h_per n m hn_c_ge hm_c_ge hn_M

  -- Finally, consolidate the congruencies into a clean divisibility argument modulo c
  have h_final : (c : ℤ) ∣ a ^ F n + (n : ℤ) - b :=
    final_divisibility c M m n (a ^ F n) (a ^ F m) b hn_c h_per_app

  -- Output the witness fulfilling both the magnitude constraint and modulo property
  use n
  exact ⟨by omega, h_final⟩

theorem PB_generalized (F : ℕ → ℕ) (hF1 : F 1 = 1) (hF_rec : ∀ n ≥ 1, F (n+1) = (n+1) ^ F n)
    (a : ℤ) (c : ℕ) :
  0 < c → ∀ (K : ℕ) (b : ℤ), ∃ n : ℕ, n ≥ K ∧ (c : ℤ) ∣ a ^ F n + (n : ℤ) - b :=
by
  refine Nat.strong_induction_on c (fun c1 IH hc K b => ?_)
  have hc_cases : c1 = 1 ∨ 1 < c1 := by omega
  rcases hc_cases with rfl | hc_gt
  · exact PB_generalized_c_eq_1 F a K b
  · exact PB_generalized_step F hF1 hF_rec a c1 hc_gt IH K b

theorem PBAdvanced008_divides (F : ℕ → ℕ) (hF1 : F 1 = 1) (hF_rec : ∀ n ≥ 1, F (n+1) = (n+1) ^ F n)
    (a b c : ℤ) (ha : 0 < a) (hc : 0 < c) : ∃ (n : ℕ), n ≥ 1 ∧ c ∣ a ^ F n + (n : ℤ) - b :=
by
  have hc_nat : 0 < c.toNat := by omega
  have h_eq : (c.toNat : ℤ) = c := by omega
  obtain ⟨n, hn_ge, hn_div⟩ := PB_generalized F hF1 hF_rec a c.toNat hc_nat 1 b
  use n
  refine ⟨hn_ge, ?_⟩
  rwa [← h_eq]

theorem PBAdvanced008 (F : ℕ → ℕ) (hF1 : F 1 = 1) (hF_rec : ∀ n ≥ 1, F (n+1) = (n+1) ^ F n)
    (a b c : ℤ) (ha : 0 < a) (hc : 0 < c) : ∃ᵉ (n ≥ 1) (m : ℤ), (a ^ F n + n - b : ℚ) / c = m :=
by
  obtain ⟨n, hn, h_d⟩ := PBAdvanced008_divides F hF1 hF_rec a b c ha hc
  obtain ⟨m, hm⟩ := h_d
  have h_c_ne_zero : c ≠ 0 := ne_of_gt hc
  have hc_neq : (c : ℚ) ≠ 0 := by exact_mod_cast h_c_ne_zero
  have hm_cast : (a ^ F n + n - b : ℚ) = (c : ℚ) * (m : ℚ) := by exact_mod_cast hm
  have h_eq : (a ^ F n + n - b : ℚ) / c = m := by
    rw [hm_cast]
    exact mul_div_cancel_left₀ (m : ℚ) hc_neq
  refine ⟨n, hn, m, h_eq⟩
