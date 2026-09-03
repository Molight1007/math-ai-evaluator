import Mathlib
structure ProblemPath (n : ℕ) where
  points : List (ℕ × ℕ)
  nonempty : points ≠ []
  start : points.head nonempty = (0,0)
  finish : points.getLast nonempty = (n,n)
  up_right : points.Chain' (fun (x₁,y₁) (x₂,y₂) ↦ (x₂,y₂) = (x₁+1,y₁) ∨ (x₂,y₂) = (x₁,y₁+1))
structure ProblemPath.pair n where
  (path1 path2 : ProblemPath n)
  (cond : ∀ (i : ℕ) (_ : i < path1.points.length) (_ : i < path2.points.length),
    path1.points[i].2 ≤ path2.points[i].2)
noncomputable
def f (n : ℕ) : ℕ := Nat.card (ProblemPath.pair n)

def U (N m : ℕ) := { l : List Bool // l.length = N ∧ l.count true = m }
def path_cond (l1 l2 : List Bool) : Prop :=
  ∀ i ≤ l1.length, (l1.take i).count true ≤ (l2.take i).count true
def P_pairs_10 := U 20 10 × U 20 10
def ValidPair_10 := { p : P_pairs_10 // path_cond p.1.val p.2.val }
def InvalidPair_10 := { p : P_pairs_10 // ¬ path_cond p.1.val p.2.val }

noncomputable section
local instance (p : Prop) : Decidable p := Classical.propDecidable p
local instance (α : Type) (p : α → Prop) : DecidablePred p := fun x => Classical.propDecidable (p x)
def is_viol (l1 l2 : List Bool) (i : ℕ) : Prop :=
  (l1.take i).count true > (l2.take i).count true
def first_viol (l1 l2 : List Bool) : ℕ :=
  if h : ∃ i, is_viol l1 l2 i then Nat.find h else 0
def swap_tail (l1 l2 : List Bool) (i : ℕ) : List Bool × List Bool :=
  (l1.take i ++ l2.drop i, l2.take i ++ l1.drop i)
def swap_pair (p : List Bool × List Bool) : List Bool × List Bool :=
  swap_tail p.1 p.2 (first_viol p.1 p.2)

def list_to_finset {N : ℕ} (l : List Bool) (h : l.length = N) : Finset (Fin N) :=
  Finset.filter (fun i => l.get ⟨i.val, by rw [h]; exact i.isLt⟩ = true) Finset.univ
def finset_to_list {N : ℕ} (s : Finset (Fin N)) : List Bool :=
  List.ofFn (fun i => if i ∈ s then true else false)

def U_inj (N m : ℕ) : U N m → (Fin N → Bool) :=
  fun x i => x.val.get ⟨i.val, by
    have h : x.val.length = N := x.property.1
    rw [h]
    exact i.isLt⟩

def points_to_steps (points : List (ℕ × ℕ)) : List Bool :=
  List.zipWith (fun p1 p2 => p2.2 == p1.2 + 1) points.dropLast points.tail
def steps_to_points (l : List Bool) : List (ℕ × ℕ) :=
  List.ofFn (fun i : Fin (l.length + 1) =>
    ((l.take i.val).count false, (l.take i.val).count true))

theorem InvalidPair_10_ext (p q : InvalidPair_10) (h1 : p.val.1.val = q.val.1.val) (h2 : p.val.2.val = q.val.2.val) :
  p = q :=
by
  have h_fst : p.val.1 = q.val.1 := Subtype.ext h1
  have h_snd : p.val.2 = q.val.2 := Subtype.ext h2
  have h_val : p.val = q.val := Prod.ext h_fst h_snd
  exact Subtype.ext h_val

theorem U_pair_ext (p q : U 20 11 × U 20 9) (h1 : p.1.val = q.1.val) (h2 : p.2.val = q.2.val) :
  p = q :=
by
  have h_fst : p.1 = q.1 := Subtype.ext h1
  have h_snd : p.2 = q.2 := Subtype.ext h2
  exact Prod.ext h_fst h_snd

theorem swap_tail_part_length (l1 l2 : List Bool) (i : ℕ) (h1 : l1.length = 20) (h2 : l2.length = 20) :
  (l1.take i ++ l2.drop i).length = 20 :=
by
  simp_all
  omega

theorem swap_tail_def_1 (l1 l2 : List Bool) (i : ℕ) :
  (swap_tail l1 l2 i).1 = l1.take i ++ l2.drop i :=
rfl

theorem swap_tail_def_2 (l1 l2 : List Bool) (i : ℕ) :
  (swap_tail l1 l2 i).2 = l2.take i ++ l1.drop i :=
by
  rfl

theorem swap_tail_length (l1 l2 : List Bool) (i : ℕ) (h1 : l1.length = 20) (h2 : l2.length = 20) :
  (swap_tail l1 l2 i).1.length = 20 ∧ (swap_tail l1 l2 i).2.length = 20 :=
by
  constructor
  · rw [swap_tail_def_1]
    exact swap_tail_part_length l1 l2 i h1 h2
  · rw [swap_tail_def_2]
    exact swap_tail_part_length l2 l1 i h2 h1

theorem invalid_pair_length_1 (p : InvalidPair_10) : p.val.1.val.length = 20 :=
p.val.1.property.1

theorem invalid_pair_length_2 (p : InvalidPair_10) : p.val.2.val.length = 20 :=
p.val.2.property.1

theorem swap_pair_def_eq (l1 l2 : List Bool) : swap_pair (l1, l2) = swap_tail l1 l2 (first_viol l1 l2) :=
rfl

theorem invalid_equiv_10_fun_length1 (p : InvalidPair_10) :
  (swap_pair (p.val.1.val, p.val.2.val)).1.length = 20 :=
by
  rw [swap_pair_def_eq]
  have h1 : p.val.1.val.length = 20 := invalid_pair_length_1 p
  have h2 : p.val.2.val.length = 20 := invalid_pair_length_2 p
  exact (swap_tail_length p.val.1.val p.val.2.val (first_viol p.val.1.val p.val.2.val) h1 h2).1

theorem invalid_p_len1 (p : InvalidPair_10) : p.val.1.val.length = 20 :=
by
  exact p.val.1.property.1

theorem invalid_p_len2 (p : InvalidPair_10) : p.val.2.val.length = 20 :=
p.val.2.property.1

theorem invalid_p_count1 (p : InvalidPair_10) : p.val.1.val.count true = 10 :=
p.val.1.property.2

theorem invalid_p_count2 (p : InvalidPair_10) : p.val.2.val.count true = 10 :=
p.val.2.property.right

theorem swap_pair_eq_swap_tail (l1 l2 : List Bool) :
  swap_pair (l1, l2) = swap_tail l1 l2 (first_viol l1 l2) :=
rfl

theorem invalid_p_not_path_cond (p : InvalidPair_10) : ¬ path_cond p.val.1.val p.val.2.val :=
p.property

theorem not_path_cond_iff_exists_viol (l1 l2 : List Bool) :
  ¬ path_cond l1 l2 ↔ ∃ i ≤ l1.length, is_viol l1 l2 i :=
by
  -- Expose the inner inequalities and structure by unfolding the definitions
  unfold path_cond is_viol

  constructor
  · -- Forward implication (→)
    intro h
    -- Push the negation inward, which flips `∀` to `∃` and `≤` to `>`
    push_neg at h
    exact h
  · -- Backward implication (←)
    intro h
    -- Push the negation on the target goal (¬ ∀ ...) inward
    push_neg
    exact h

theorem invalid_pair_exists_viol_le_20 (p : InvalidPair_10) :
  ∃ i ≤ 20, is_viol p.val.1.val p.val.2.val i :=
by
  have h1 := invalid_p_not_path_cond p
  have h2 := (not_path_cond_iff_exists_viol p.val.1.val p.val.2.val).mp h1
  have h3 := invalid_p_len1 p
  rw [h3] at h2
  exact h2

theorem first_viol_eq_find (l1 l2 : List Bool) (h : ∃ i, is_viol l1 l2 i) :
  first_viol l1 l2 = Nat.find h :=
by
  unfold first_viol
  split
  · rfl
  · contradiction

theorem first_viol_le_of_is_viol (l1 l2 : List Bool) (i : ℕ) (hviol : is_viol l1 l2 i) :
  first_viol l1 l2 ≤ i :=
by
  have h_ex : ∃ j, is_viol l1 l2 j := ⟨i, hviol⟩
  rw [first_viol_eq_find l1 l2 h_ex]
  exact Nat.find_le hviol

theorem first_viol_le (l1 l2 : List Bool) (N : ℕ) (h : ∃ i ≤ N, is_viol l1 l2 i) :
  (∃ i, is_viol l1 l2 i) ∧ first_viol l1 l2 ≤ N :=
by
  rcases h with ⟨i, hi, hviol⟩
  exact ⟨⟨i, hviol⟩, le_trans (first_viol_le_of_is_viol l1 l2 i hviol) hi⟩

theorem invalid_has_viol_and_le_20 (p : InvalidPair_10) :
  (∃ i, is_viol p.val.1.val p.val.2.val i) ∧ first_viol p.val.1.val p.val.2.val ≤ 20 :=
first_viol_le p.val.1.val p.val.2.val 20 (invalid_pair_exists_viol_le_20 p)

theorem first_viol_spec (l1 l2 : List Bool) (h : ∃ i, is_viol l1 l2 i) :
  is_viol l1 l2 (first_viol l1 l2) ∧ ∀ j < first_viol l1 l2, ¬ is_viol l1 l2 j :=
by
  rw [first_viol_eq_find l1 l2 h]
  exact ⟨Nat.find_spec h, fun j hj => Nat.find_min h hj⟩

theorem count_take_succ_le (l : List Bool) (k : ℕ) :
  (l.take (k + 1)).count true ≤ (l.take k).count true + 1 :=
by
  induction l generalizing k with
  | nil =>
    simp
  | cons hd tl ih =>
    cases k with
    | zero =>
      cases hd <;> simp
    | succ k' =>
      have h := ih k'
      cases hd
      · simp
        omega
      · simp
        omega

theorem count_take_le_succ (l : List Bool) (k : ℕ) :
  (l.take k).count true ≤ (l.take (k + 1)).count true :=
by
  induction l generalizing k
  case nil =>
    simp
  case cons hd tl ih =>
    cases k
    case zero =>
      simp
    case succ k' =>
      have h := ih k'
      cases hd
      case false =>
        simp [h]
        try omega
      case true =>
        simp [h]
        try omega

theorem not_is_viol_zero (l1 l2 : List Bool) : ¬ is_viol l1 l2 0 :=
by
  simp [is_viol]

theorem first_viol_pos (l1 l2 : List Bool) (h : ∃ i, is_viol l1 l2 i) :
  first_viol l1 l2 > 0 :=
by
  -- Obtain the first component of the conjunction from `first_viol_spec`.
  have h_spec := (first_viol_spec l1 l2 h).1

  -- Check if the first violation index is 0.
  by_cases h_z : first_viol l1 l2 = 0
  · -- If it is 0, substitute 0 into our specification property.
    rw [h_z] at h_spec
    -- This means `is_viol l1 l2 0` holds, which contradicts our helper lemma.
    exact False.elim (not_is_viol_zero l1 l2 h_spec)
  · -- If it is not 0, then by properties of natural numbers, it must be strictly positive.
    exact Nat.pos_of_ne_zero h_z

theorem is_viol_iff_count (l1 l2 : List Bool) (i : ℕ) :
  is_viol l1 l2 i ↔ (l1.take i).count true > (l2.take i).count true :=
Iff.rfl

theorem first_viol_val (l1 l2 : List Bool) (h : ∃ i, is_viol l1 l2 i) :
  (l1.take (first_viol l1 l2)).count true = (l2.take (first_viol l1 l2)).count true + 1 :=
by
  have fv_pos := first_viol_pos l1 l2 h
  have spec := first_viol_spec l1 l2 h
  have viol_at := spec.left
  generalize H : first_viol l1 l2 = v
  cases v with
  | zero =>
    rw [H] at fv_pos
    omega
  | succ k =>
    -- Store the strict syntactic match for `k + 1` replacing `Nat.succ k`
    have H2 : first_viol l1 l2 = k + 1 := H

    -- Prove that index `k` happens before the first violation
    have h_lt : k < first_viol l1 l2 := by
      rw [H2]
      omega
    have not_viol_before : ¬ is_viol l1 l2 k := spec.right k h_lt

    -- Expose the definitions into basic True-count comparison inequalities
    rw [is_viol_iff_count] at viol_at not_viol_before

    -- Instantiating our helper bounding counts
    have c1 := count_take_succ_le l1 k
    have c2 := count_take_le_succ l2 k

    -- Rewrite the bounds explicitly to `k + 1` terms so omega has syntactically matching constraints
    rw [H2] at viol_at
    change (l1.take (k + 1)).count true = (l2.take (k + 1)).count true + 1

    -- Discharge the final basic integer linear equality
    omega

theorem list_count_take_add_drop (l : List Bool) (v : ℕ) :
  (l.take v).count true + (l.drop v).count true = l.count true :=
by
  rw [← List.count_append, List.take_append_drop]

theorem swap_tail_count_11_9 (l1 l2 : List Bool) (v : ℕ) (h1 : l1.length = 20) (h2 : l2.length = 20) (h3 : v ≤ 20)
  (c1 : l1.count true = 10) (c2 : l2.count true = 10)
  (hv : (l1.take v).count true = (l2.take v).count true + 1) :
  (swap_tail l1 l2 v).1.count true = 11 ∧ (swap_tail l1 l2 v).2.count true = 9 :=
by
  constructor
  · rw [swap_tail_def_1, List.count_append]
    have h1_split := list_count_take_add_drop l1 v
    have h2_split := list_count_take_add_drop l2 v
    omega
  · rw [swap_tail_def_2, List.count_append]
    have h1_split := list_count_take_add_drop l1 v
    have h2_split := list_count_take_add_drop l2 v
    omega

theorem invalid_equiv_10_fun_count1 (p : InvalidPair_10) :
  (swap_pair (p.val.1.val, p.val.2.val)).1.count true = 11 :=
by
  -- 1. Extract Lengths
  have h1 : p.val.1.val.length = 20 := invalid_p_len1 p
  have h2 : p.val.2.val.length = 20 := invalid_p_len2 p

  -- 2. Extract specific counts of `true`
  have c1 : p.val.1.val.count true = 10 := invalid_p_count1 p
  have c2 : p.val.2.val.count true = 10 := invalid_p_count2 p

  -- 3. Gain the bounds and violation conditions
  have hv_and_le := invalid_has_viol_and_le_20 p
  have hv := hv_and_le.1
  have h3 := hv_and_le.2

  -- 4. Formulate the relationship constraint at the violation step
  have h_take := first_viol_val p.val.1.val p.val.2.val hv

  -- 5. Calculate the swapped counts cleanly
  have h_swap := swap_tail_count_11_9 p.val.1.val p.val.2.val (first_viol p.val.1.val p.val.2.val) h1 h2 h3 c1 c2 h_take

  -- 6. Apply definition and goal matching
  rw [swap_pair_eq_swap_tail]
  exact h_swap.1

theorem invalid_equiv_10_fun_length2 (p : InvalidPair_10) :
  (swap_pair (p.val.1.val, p.val.2.val)).2.length = 20 :=
by
  have h1 : p.val.1.val.length = 20 := p.val.1.property.1
  have h2 : p.val.2.val.length = 20 := p.val.2.property.1
  have h_len := swap_tail_length p.val.1.val p.val.2.val (first_viol p.val.1.val p.val.2.val) h1 h2
  exact h_len.2

theorem invalid_equiv_10_fun_count2 (p : InvalidPair_10) :
  (swap_pair (p.val.1.val, p.val.2.val)).2.count true = 9 :=
by
  have h_viol_le20 := invalid_has_viol_and_le_20 p
  have h_viol : ∃ i, is_viol p.val.1.val p.val.2.val i := h_viol_le20.1
  have h3 : first_viol p.val.1.val p.val.2.val ≤ 20 := h_viol_le20.2
  have h1 : p.val.1.val.length = 20 := invalid_p_len1 p
  have h2 : p.val.2.val.length = 20 := invalid_p_len2 p
  have c1 : p.val.1.val.count true = 10 := invalid_p_count1 p
  have c2 : p.val.2.val.count true = 10 := invalid_p_count2 p
  have hv : (p.val.1.val.take (first_viol p.val.1.val p.val.2.val)).count true =
    (p.val.2.val.take (first_viol p.val.1.val p.val.2.val)).count true + 1 := first_viol_val p.val.1.val p.val.2.val h_viol
  have h_swap := swap_tail_count_11_9 p.val.1.val p.val.2.val (first_viol p.val.1.val p.val.2.val) h1 h2 h3 c1 c2 hv
  rw [swap_pair_def_eq p.val.1.val p.val.2.val]
  exact h_swap.2

theorem invalid_equiv_10_inv_length1 (p : U 20 11 × U 20 9) :
  (swap_pair (p.1.val, p.2.val)).1.length = 20 :=
by
  -- Rewrite the swap_pair function into its swap_tail definition
  rw [swap_pair_def_eq]

  -- Extract the length assertions from the subtype definitions of U 20 11 and U 20 9
  have h1 : p.1.val.length = 20 := p.1.property.1
  have h2 : p.2.val.length = 20 := p.2.property.1

  -- Apply the swap_tail_length lemma to close the goal on the first part (.1) of the pair
  exact (swap_tail_length p.1.val p.2.val (first_viol p.1.val p.2.val) h1 h2).1

theorem u_pair_count_11 (p : U 20 11 × U 20 9) : p.1.val.count true = 11 :=
by
  exact p.1.property.2

theorem u_pair_count_9 (p : U 20 11 × U 20 9) : p.2.val.count true = 9 :=
by
  exact p.2.property.2

theorem take_of_length_le_my (l : List Bool) (n : ℕ) (h : l.length ≤ n) : l.take n = l :=
(List.take_eq_self_iff l).mpr h

theorem viol_of_count_gt (l1 l2 : List Bool) (h : l1.count true > l2.count true) : ∃ i, is_viol l1 l2 i :=
by
  use l1.length + l2.length
  rw [is_viol_iff_count]
  have h1 : l1.length ≤ l1.length + l2.length := by omega
  have h2 : l2.length ≤ l1.length + l2.length := by omega
  rw [take_of_length_le_my l1 (l1.length + l2.length) h1]
  rw [take_of_length_le_my l2 (l1.length + l2.length) h2]
  exact h

theorem u_pair_has_viol (p : U 20 11 × U 20 9) : ∃ i, is_viol p.1.val p.2.val i :=
by
  apply viol_of_count_gt
  rw [u_pair_count_11 p, u_pair_count_9 p]
  decide

theorem list_count_take_add_drop_bool (l : List Bool) (n : ℕ) (a : Bool) :
  (l.take n).count a + (l.drop n).count a = l.count a :=
by
  rw [← List.count_append, List.take_append_drop]

theorem swap_tail_count_1_10 (l1 l2 : List Bool) (v : ℕ)
  (h_v : (l1.take v).count true = (l2.take v).count true + 1)
  (c2 : l2.count true = 9) :
  (swap_tail l1 l2 v).1.count true = 10 :=
by
  -- Evaluate the definition of swap_tail and take its first projection
  change (l1.take v ++ l2.drop v).count true = 10
  -- Distribute the count across the concatenation
  rw [List.count_append]
  -- Substitute the premise that (l1.take v) has one more true than (l2.take v)
  rw [h_v]
  -- Recombine l2 counts
  have h := list_count_take_add_drop_bool l2 v true
  -- Conclude the proof directly via linear natural number arithmetic
  omega

theorem invalid_equiv_10_inv_count1 (p : U 20 11 × U 20 9) :
  (swap_pair (p.1.val, p.2.val)).1.count true = 10 :=
by
  -- Unfold the definition of swap_pair to its swap_tail equivalent definitionally
  change (swap_tail p.1.val p.2.val (first_viol p.1.val p.2.val)).1.count true = 10

  -- Apply the isolated arithmetic and list manipulation logic for this scenario
  apply swap_tail_count_1_10

  · -- Supply the constraint h_v utilizing the graph lemma
    exact first_viol_val p.1.val p.2.val (u_pair_has_viol p)

  · -- Extract the condition c2 (l2.count true = 9) inherently wrapped inside the subtype property
    exact p.2.property.2

theorem invalid_equiv_10_inv_length2 (p : U 20 11 × U 20 9) :
  (swap_pair (p.1.val, p.2.val)).2.length = 20 :=
by
  rw [swap_pair_def_eq]
  have h1 : p.1.val.length = 20 := p.1.property.1
  have h2 : p.2.val.length = 20 := p.2.property.1
  exact (swap_tail_length p.1.val p.2.val (first_viol p.1.val p.2.val) h1 h2).2

theorem count_take_add_count_drop (l : List Bool) (v : ℕ) :
  (l.take v).count true + (l.drop v).count true = l.count true :=
by
  rw [← List.count_append]
  rw [List.take_append_drop]

theorem swap_tail_2 (l1 l2 : List Bool) (v : ℕ) :
  (swap_tail l1 l2 v).2 = l2.take v ++ l1.drop v :=
rfl

theorem swap_tail_def_2_count (l1 l2 : List Bool) (v : ℕ) :
  (swap_tail l1 l2 v).2.count true = (l2.take v).count true + (l1.drop v).count true :=
by
  rw [swap_tail_2, List.count_append]

theorem swap_tail_count_2_10 (l1 l2 : List Bool) (v : ℕ)
  (h_v : (l1.take v).count true = (l2.take v).count true + 1)
  (c1 : l1.count true = 11) :
  (swap_tail l1 l2 v).2.count true = 10 :=
by
  rw [swap_tail_def_2_count]
  have h := count_take_add_count_drop l1 v
  omega

theorem invalid_equiv_10_inv_count2 (p : U 20 11 × U 20 9) :
  (swap_pair (p.1.val, p.2.val)).2.count true = 10 :=
by
  rw [swap_pair_eq_swap_tail]
  have h_viol : ∃ i, is_viol p.1.val p.2.val i := u_pair_has_viol p
  have h_v : (p.1.val.take (first_viol p.1.val p.2.val)).count true =
             (p.2.val.take (first_viol p.1.val p.2.val)).count true + 1 :=
    first_viol_val p.1.val p.2.val h_viol
  have c1 : p.1.val.count true = 11 := u_pair_count_11 p
  exact swap_tail_count_2_10 p.1.val p.2.val (first_viol p.1.val p.2.val) h_v c1

theorem is_viol_20_u (p : U 20 11 × U 20 9) : is_viol p.1.val p.2.val 20 :=
by
  unfold is_viol
  have h1 : p.1.val.length = 20 := p.1.property.1
  have h2 : p.2.val.length = 20 := p.2.property.1

  -- We use the equivalence List.take n x = x ↔ x.length ≤ n to bypass motive type errors.
  have t1 : p.1.val.take 20 = p.1.val := by
    apply (List.take_eq_self_iff p.1.val).mpr
    omega
  have t2 : p.2.val.take 20 = p.2.val := by
    apply (List.take_eq_self_iff p.2.val).mpr
    omega

  rw [t1, t2]
  have c1 : p.1.val.count true = 11 := p.1.property.2
  have c2 : p.2.val.count true = 9 := p.2.property.2
  rw [c1, c2]
  omega

theorem first_viol_le_20_u (p : U 20 11 × U 20 9) : first_viol p.1.val p.2.val ≤ 20 :=
by
  unfold first_viol
  split
  · apply Nat.find_min'
    exact is_viol_20_u p
  · omega

theorem helper_take_append (L1 L2 : List Bool) : (L1 ++ L2).take L1.length = L1 :=
by
  induction L1 with
  | nil => rfl
  | cons hd tl ih => simp [ih]

theorem helper_length_take (l : List Bool) (v : ℕ) (h : v ≤ l.length) : (l.take v).length = v :=
by
  exact List.length_take_of_le h

theorem swap_tail_take_1 (l1 l2 : List Bool) (v : ℕ) (h : v ≤ l1.length) : (swap_tail l1 l2 v).1.take v = l1.take v :=
by
  rw [swap_tail_def_1]
  have h1 := helper_take_append (l1.take v) (l2.drop v)
  have h2 := helper_length_take l1 v h
  rw [h2] at h1
  exact h1

theorem my_list_take_append_left {α : Type*} (l1 l2 : List α) (n : ℕ) (h : l1.length = n) :
  (l1 ++ l2).take n = l1 :=
by
  rw [← h]
  exact List.take_left

theorem my_length_take_eq_of_le {α : Type*} {l : List α} {n : ℕ} (h : n ≤ l.length) :
  (l.take n).length = n :=
by
  rw [List.length_take]
  exact Nat.min_eq_left h

theorem swap_tail_take_2 (l1 l2 : List Bool) (v : ℕ) (h : v ≤ l2.length) :
  (swap_tail l1 l2 v).2.take v = l2.take v :=
by
  rw [swap_tail_def_2]
  apply my_list_take_append_left
  exact my_length_take_eq_of_le h

theorem u_pair_is_viol_first_viol (p : U 20 11 × U 20 9) : is_viol p.1.val p.2.val (first_viol p.1.val p.2.val) :=
by
  exact (first_viol_spec p.1.val p.2.val (u_pair_has_viol p)).1

theorem invalid_equiv_10_inv_cond (p : U 20 11 × U 20 9) :
  ¬ path_cond (swap_pair (p.1.val, p.2.val)).1 (swap_pair (p.1.val, p.2.val)).2 :=
by
  intro hcond

  -- The violation at the first_viol index directly from our lemmas:
  have hviol : is_viol p.1.val p.2.val (first_viol p.1.val p.2.val) := u_pair_is_viol_first_viol p

  have h_len_swapped : (swap_pair (p.1.val, p.2.val)).1.length = 20 := invalid_equiv_10_inv_length1 p
  have h_v_le_20 : first_viol p.1.val p.2.val ≤ 20 := first_viol_le_20_u p

  -- The first violation index is a valid threshold for evaluating the (false) path_cond
  have h_v_le_swapped : first_viol p.1.val p.2.val ≤ (swap_pair (p.1.val, p.2.val)).1.length := by
    rw [h_len_swapped]
    exact h_v_le_20

  -- Evaluate the assumed false condition at the violation index
  have hcond_v := hcond (first_viol p.1.val p.2.val) h_v_le_swapped

  have h_swap_eq : swap_pair (p.1.val, p.2.val) = swap_tail p.1.val p.2.val (first_viol p.1.val p.2.val) :=
    swap_pair_eq_swap_tail p.1.val p.2.val

  have h1 : (swap_pair (p.1.val, p.2.val)).1 = (swap_tail p.1.val p.2.val (first_viol p.1.val p.2.val)).1 :=
    congrArg Prod.fst h_swap_eq
  have h2 : (swap_pair (p.1.val, p.2.val)).2 = (swap_tail p.1.val p.2.val (first_viol p.1.val p.2.val)).2 :=
    congrArg Prod.snd h_swap_eq

  have h_len1 : p.1.val.length = 20 := p.1.property.1
  have h_len2 : p.2.val.length = 20 := p.2.property.1
  have h_v_le1 : first_viol p.1.val p.2.val ≤ p.1.val.length := by
    rw [h_len1]
    exact h_v_le_20
  have h_v_le2 : first_viol p.1.val p.2.val ≤ p.2.val.length := by
    rw [h_len2]
    exact h_v_le_20

  -- Substituting our structural structural knowledge of what swap_tail actually does to the prefixes
  have h_take1 : (swap_tail p.1.val p.2.val (first_viol p.1.val p.2.val)).1.take (first_viol p.1.val p.2.val) = p.1.val.take (first_viol p.1.val p.2.val) :=
    swap_tail_take_1 p.1.val p.2.val (first_viol p.1.val p.2.val) h_v_le1
  have h_take2 : (swap_tail p.1.val p.2.val (first_viol p.1.val p.2.val)).2.take (first_viol p.1.val p.2.val) = p.2.val.take (first_viol p.1.val p.2.val) :=
    swap_tail_take_2 p.1.val p.2.val (first_viol p.1.val p.2.val) h_v_le2

  rw [h1, h2] at hcond_v
  rw [h_take1, h_take2] at hcond_v

  -- Obtain the contradiction: Path evaluated implies ≤, while actual violation establishes strictly >.
  exact Nat.not_le_of_gt hviol hcond_v

theorem swap_tail_eq (l1 l2 : List Bool) (v : ℕ) :
  swap_tail l1 l2 v = (l1.take v ++ l2.drop v, l2.take v ++ l1.drop v) :=
rfl

theorem my_list_drop_append_left {α : Type*} (l1 l2 : List α) (n : ℕ) (h : l1.length = n) :
  (l1 ++ l2).drop n = l2 :=
by
  subst h
  induction l1 with
  | nil => rfl
  | cons a tail ih => exact ih

theorem swap_tail_drop_1 (l1 l2 : List Bool) (v : ℕ) (h : v ≤ l1.length) :
  (swap_tail l1 l2 v).1.drop v = l2.drop v :=
by
  have h1 := swap_tail_def_1 l1 l2 v
  have h2 := helper_length_take l1 v h
  have h3 := my_list_drop_append_left (l1.take v) (l2.drop v) v h2
  rw [h1]
  exact h3

theorem swap_tail_drop_2 (l1 l2 : List Bool) (v : ℕ) (h : v ≤ l2.length) :
  (swap_tail l1 l2 v).2.drop v = l1.drop v :=
by
  rw [swap_tail_def_2]
  apply my_list_drop_append_left
  exact my_length_take_eq_of_le h

theorem swap_tail_involutive_gen (l1 l2 : List Bool) (v : ℕ) (h1 : v ≤ l1.length) (h2 : v ≤ l2.length) :
  swap_tail (swap_tail l1 l2 v).1 (swap_tail l1 l2 v).2 v = (l1, l2) :=
by
  -- 1. Expand the outer application of swap_tail
  rw [swap_tail_eq (swap_tail l1 l2 v).1 (swap_tail l1 l2 v).2 v]

  -- 2. Rewrite prefix `take` operations retrieving exact elements since length criteria are met
  rw [swap_tail_take_1 l1 l2 v h1]
  rw [swap_tail_take_2 l1 l2 v h2]

  -- 3. Rewrite suffix `drop` operations reverting exactly the swapped tail counterparts
  rw [swap_tail_drop_2 l1 l2 v h2]
  rw [swap_tail_drop_1 l1 l2 v h1]

  -- 4. Complete the reconstruction identity (l.take v ++ l.drop v = l) using Mathlib's native List simp lemma
  simp only [List.take_append_drop]

theorem swap_tail_involutive (l1 l2 : List Bool) (v : ℕ) (h1 : l1.length = 20) (h2 : l2.length = 20) (h3 : v ≤ 20) :
  swap_tail (swap_tail l1 l2 v).1 (swap_tail l1 l2 v).2 v = (l1, l2) :=
by
  apply swap_tail_involutive_gen l1 l2 v
  · rw [h1]
    exact h3
  · rw [h2]
    exact h3

theorem list_take_length_eq_my (l : List Bool) (v : ℕ) (h : v ≤ l.length) :
  (l.take v).length = v :=
by
  simp
  omega

theorem list_take_append_my (l1 l2 : List Bool) (i : ℕ) (h : i ≤ l1.length) :
  (l1 ++ l2).take i = l1.take i :=
List.take_append_of_le_length h

theorem list_take_take_my (l : List Bool) (i v : ℕ) (h : i ≤ v) :
  (l.take v).take i = l.take i :=
by
  rw [List.take_take, Nat.min_eq_left h]

theorem swap_tail_take_i_1 (l1 l2 : List Bool) (v i : ℕ) (h1 : v ≤ l1.length) (hiv : i ≤ v) :
  (swap_tail l1 l2 v).1.take i = l1.take i :=
by
  rw [swap_tail_def_1 l1 l2 v]
  have hlen : (l1.take v).length = v := list_take_length_eq_my l1 v h1
  have hi : i ≤ (l1.take v).length := by
    rw [hlen]
    exact hiv
  rw [list_take_append_my (l1.take v) (l2.drop v) i hi]
  rw [list_take_take_my l1 i v hiv]

theorem swap_tail_take_i_2 (l1 l2 : List Bool) (v i : ℕ) (h2 : v ≤ l2.length) (hiv : i ≤ v) :
  (swap_tail l1 l2 v).2.take i = l2.take i :=
by
  -- Unfold the definition to expose the exact list append structure for the second component.
  change (l2.take v ++ l1.drop v).take i = l2.take i

  -- Calculate the exact length of the left side of the append
  have h_len : (l2.take v).length = v := by
    rw [List.length_take]
    omega

  -- Show that we are only taking elements from the first part of the append
  have h_le : i ≤ (l2.take v).length := by
    rw [h_len]
    exact hiv

  -- Reduce the append operation since the subset bound `i` does not exceed the first list's length
  rw [List.take_append_of_le_length h_le]

  -- Resolve the nested takes
  rw [List.take_take]

  -- `List.take_take` leaves `min v i` (or `min i v`); `congr` peels off `List.take` leaving the arithmetic goal.
  congr
  omega

theorem is_viol_swap_tail_le (l1 l2 : List Bool) (v i : ℕ) (h1 : v ≤ l1.length) (h2 : v ≤ l2.length) (hiv : i ≤ v) :
  is_viol (swap_tail l1 l2 v).1 (swap_tail l1 l2 v).2 i ↔ is_viol l1 l2 i :=
by
  simp only [is_viol_iff_count, swap_tail_take_i_1 l1 l2 v i h1 hiv, swap_tail_take_i_2 l1 l2 v i h2 hiv]

theorem first_viol_le_of_iff (l1 l2 l1' l2' : List Bool)
  (h : ∃ i, is_viol l1 l2 i)
  (H : ∀ i ≤ first_viol l1 l2, is_viol l1' l2' i ↔ is_viol l1 l2 i) :
  first_viol l1' l2' ≤ first_viol l1 l2 :=
by
  have h1 : is_viol l1 l2 (first_viol l1 l2) := (first_viol_spec l1 l2 h).1
  have h2 : is_viol l1' l2' (first_viol l1 l2) := (H (first_viol l1 l2) (Nat.le_refl _)).mpr h1
  exact (first_viol_le l1' l2' (first_viol l1 l2) ⟨first_viol l1 l2, Nat.le_refl _, h2⟩).2

theorem exists_viol_of_iff (l1 l2 l1' l2' : List Bool)
  (h : ∃ i, is_viol l1 l2 i)
  (H : ∀ i ≤ first_viol l1 l2, is_viol l1' l2' i ↔ is_viol l1 l2 i) :
  ∃ i, is_viol l1' l2' i :=
by
  use first_viol l1 l2
  have h1 := (first_viol_spec l1 l2 h).1
  have h2 := H (first_viol l1 l2) le_rfl
  exact h2.mpr h1

theorem first_viol_ge_of_iff (l1 l2 l1' l2' : List Bool)
  (h : ∃ i, is_viol l1 l2 i)
  (H : ∀ i ≤ first_viol l1 l2, is_viol l1' l2' i ↔ is_viol l1 l2 i) :
  first_viol l1 l2 ≤ first_viol l1' l2' :=
by
  by_contra h_contra
  have h_lt : first_viol l1' l2' < first_viol l1 l2 := by omega

  -- Obtain the existence of a violation for the second pair
  have h' : ∃ i, is_viol l1' l2' i := exists_viol_of_iff l1 l2 l1' l2' h H

  -- The first violation of (l1', l2') is indeed a violation for it
  have h_spec_1' := (first_viol_spec l1' l2' h').1

  -- Since first_viol l1' l2' < first_viol l1 l2, it cannot be a violation for (l1, l2)
  have h_spec_1 := (first_viol_spec l1 l2 h).2 (first_viol l1' l2') h_lt

  -- Use the equivalence hypothesis H at the index first_viol l1' l2'
  have h_le : first_viol l1' l2' ≤ first_viol l1 l2 := by omega
  have h_iff := H (first_viol l1' l2') h_le

  -- The equivalence shows it MUST be a violation for (l1, l2), yielding a contradiction
  have h_viol_1_2 := h_iff.mp h_spec_1'
  exact h_spec_1 h_viol_1_2

theorem first_viol_eq_of_is_viol_iff (l1 l2 l1' l2' : List Bool)
  (h : ∃ i, is_viol l1 l2 i)
  (H : ∀ i ≤ first_viol l1 l2, is_viol l1' l2' i ↔ is_viol l1 l2 i) :
  first_viol l1' l2' = first_viol l1 l2 :=
Nat.le_antisymm (first_viol_le_of_iff l1 l2 l1' l2' h H) (first_viol_ge_of_iff l1 l2 l1' l2' h H)

theorem first_viol_swap_pair_20 (l1 l2 : List Bool) (h : ∃ i, is_viol l1 l2 i) (h1 : l1.length = 20) (h2 : l2.length = 20) (h3 : first_viol l1 l2 ≤ 20) :
  first_viol (swap_pair (l1, l2)).1 (swap_pair (l1, l2)).2 = first_viol l1 l2 :=
by
  rw [swap_pair_def_eq]
  apply first_viol_eq_of_is_viol_iff
  · exact h
  · intro i hi
    apply is_viol_swap_tail_le
    · omega
    · omega
    · exact hi

theorem swap_pair_involutive_invalid (p : InvalidPair_10) :
  swap_pair ((swap_pair (p.val.1.val, p.val.2.val)).1, (swap_pair (p.val.1.val, p.val.2.val)).2) = (p.val.1.val, p.val.2.val) :=
by
  have hl1 : p.val.1.val.length = 20 := invalid_p_len1 p
  have hl2 : p.val.2.val.length = 20 := invalid_p_len2 p
  have hviol : (∃ i, is_viol p.val.1.val p.val.2.val i) ∧ first_viol p.val.1.val p.val.2.val ≤ 20 := invalid_has_viol_and_le_20 p
  have hviol_ex := hviol.1
  have hviol_le := hviol.2

  have h_fv : first_viol (swap_pair (p.val.1.val, p.val.2.val)).1 (swap_pair (p.val.1.val, p.val.2.val)).2 = first_viol p.val.1.val p.val.2.val :=
    first_viol_swap_pair_20 p.val.1.val p.val.2.val hviol_ex hl1 hl2 hviol_le

  rw [swap_pair_eq_swap_tail ((swap_pair (p.val.1.val, p.val.2.val)).1) ((swap_pair (p.val.1.val, p.val.2.val)).2)]
  rw [h_fv]
  rw [swap_pair_eq_swap_tail p.val.1.val p.val.2.val]
  exact swap_tail_involutive p.val.1.val p.val.2.val (first_viol p.val.1.val p.val.2.val) hl1 hl2 hviol_le

theorem swap_pair_involutive_lists (l1 l2 : List Bool) (h1 : l1.length = 20) (h2 : l2.length = 20)
  (hviol : ∃ i, is_viol l1 l2 i) (h_v_le : first_viol l1 l2 ≤ 20) :
  swap_pair ((swap_pair (l1, l2)).1, (swap_pair (l1, l2)).2) = (l1, l2) :=
by
  rw [swap_pair_def_eq ((swap_pair (l1, l2)).1) ((swap_pair (l1, l2)).2)]
  rw [first_viol_swap_pair_20 l1 l2 hviol h1 h2 h_v_le]
  rw [swap_pair_def_eq l1 l2]
  exact swap_tail_involutive l1 l2 (first_viol l1 l2) h1 h2 h_v_le

theorem swap_pair_involutive_u (p : U 20 11 × U 20 9) :
  swap_pair ((swap_pair (p.1.val, p.2.val)).1, (swap_pair (p.1.val, p.2.val)).2) = (p.1.val, p.2.val) :=
by
  have h1 : p.1.val.length = 20 := p.1.property.1
  have h2 : p.2.val.length = 20 := p.2.property.1
  have hviol : ∃ i, is_viol p.1.val p.2.val i := u_pair_has_viol p
  have h_v_le : first_viol p.1.val p.2.val ≤ 20 := first_viol_le_20_u p
  exact swap_pair_involutive_lists p.1.val p.2.val h1 h2 hviol h_v_le

theorem invalid_equiv_10 : Nonempty (InvalidPair_10 ≃ (U 20 11 × U 20 9)) :=
⟨{
  toFun := fun p =>
    (⟨(swap_pair (p.val.1.val, p.val.2.val)).1, And.intro (invalid_equiv_10_fun_length1 p) (invalid_equiv_10_fun_count1 p)⟩,
     ⟨(swap_pair (p.val.1.val, p.val.2.val)).2, And.intro (invalid_equiv_10_fun_length2 p) (invalid_equiv_10_fun_count2 p)⟩),
  invFun := fun p =>
    ⟨(⟨(swap_pair (p.1.val, p.2.val)).1, And.intro (invalid_equiv_10_inv_length1 p) (invalid_equiv_10_inv_count1 p)⟩,
      ⟨(swap_pair (p.1.val, p.2.val)).2, And.intro (invalid_equiv_10_inv_length2 p) (invalid_equiv_10_inv_count2 p)⟩),
     invalid_equiv_10_inv_cond p⟩,
  left_inv := fun p => InvalidPair_10_ext _ _
    (congrArg Prod.fst (swap_pair_involutive_invalid p))
    (congrArg Prod.snd (swap_pair_involutive_invalid p)),
  right_inv := fun p => U_pair_ext _ _
    (congrArg Prod.fst (swap_pair_involutive_u p))
    (congrArg Prod.snd (swap_pair_involutive_u p))
}⟩

theorem my_card_prod_of_finite (A B : Type*) (hA : Finite A) (hB : Finite B) : Nat.card (A × B) = Nat.card A * Nat.card B :=
by
  exact Nat.card_prod A B

theorem my_card_eq_zero_of_not_finite {A : Type*} (h : ¬ Finite A) : Nat.card A = 0 :=
by
  haveI : Infinite A := ⟨h⟩
  exact Nat.card_eq_zero_of_infinite

theorem not_finite_prod_left_of_nonempty {A B : Type*} (hA : ¬ Finite A) (hB : Nonempty B) : ¬ Finite (A × B) :=
by
  intro hAB
  have ⟨b⟩ := hB
  have h_inj : Function.Injective (fun a : A => (a, b)) := fun x y hxy => congrArg Prod.fst hxy
  have hA_fin : Finite A := by
    haveI := hAB
    exact Finite.of_injective (fun a : A => (a, b)) h_inj
  exact hA hA_fin

theorem my_card_eq_zero_of_isEmpty {A : Type*} (h : IsEmpty A) : Nat.card A = 0 :=
Nat.card_eq_zero.mpr (Or.inl h)

theorem prod_isEmpty (A : Type*) {B : Type*} (h : IsEmpty B) : IsEmpty (A × B) :=
⟨fun p => h.false p.2⟩

theorem isEmpty_of_not_nonempty {B : Type*} (h : ¬ Nonempty B) : IsEmpty B :=
⟨fun x => h ⟨x⟩⟩

theorem my_card_prod_of_not_finite_left (A B : Type*) (h : ¬ Finite A) : Nat.card (A × B) = Nat.card A * Nat.card B :=
by
  by_cases hB : Nonempty B
  · -- Case 1: B is Nonempty
    -- Under this branch, the product is infinite
    have hAB_not_finite : ¬ Finite (A × B) := not_finite_prod_left_of_nonempty h hB
    have hA_card : Nat.card A = 0 := my_card_eq_zero_of_not_finite h
    have hAB_card : Nat.card (A × B) = 0 := my_card_eq_zero_of_not_finite hAB_not_finite

    -- Substituting card A = 0 and card (A × B) = 0, simplifying to 0 = 0 * card B
    rw [hA_card, hAB_card, Nat.zero_mul]

  · -- Case 2: B is Empty
    have hEmpty : IsEmpty B := isEmpty_of_not_nonempty hB
    have h1 : Nat.card B = 0 := my_card_eq_zero_of_isEmpty hEmpty
    have h2 : Nat.card (A × B) = 0 := my_card_eq_zero_of_isEmpty (prod_isEmpty A hEmpty)

    -- Substituting card B = 0 and card (A × B) = 0, simplifying to 0 = card A * 0
    rw [h1, h2, Nat.mul_zero]

theorem my_card_prod_of_not_finite_right (A B : Type*) (h : ¬ Finite B) : Nat.card (A × B) = Nat.card A * Nat.card B :=
by
  exact Nat.card_prod A B

theorem my_card_prod (A B : Type*) : Nat.card (A × B) = Nat.card A * Nat.card B :=
by
  by_cases hA : Finite A
  · by_cases hB : Finite B
    · exact my_card_prod_of_finite A B hA hB
    · exact my_card_prod_of_not_finite_right A B hB
  · exact my_card_prod_of_not_finite_left A B hA

theorem length_finset_to_list {N : ℕ} (s : Finset (Fin N)) :
  (finset_to_list s).length = N :=
by
  simp [finset_to_list]

theorem finset_to_list_get {N : ℕ} (s : Finset (Fin N)) (x : Fin N) (h : x.val < (finset_to_list s).length) :
  (finset_to_list s).get ⟨x.val, h⟩ = if x ∈ s then true else false :=
by
  unfold finset_to_list at h ⊢
  rw [List.get_ofFn]
  have H_eq : ∀ p, (Fin.cast p ⟨x.val, h⟩ : Fin N) = x := by
    intro p
    apply Fin.ext
    rfl
  rw [H_eq]

theorem finset_to_list_empty {N : ℕ} :
  (finset_to_list (∅ : Finset (Fin N))).count true = 0 :=
by
  -- 1. The count of `true` is 0 if and only if `true` is not in the list.
  rw [List.count_eq_zero]

  -- 2. Assume for contradiction that `true` is in the list.
  intro h

  -- 3. Connect list membership to the list element at some valid index `i`.
  rw [List.mem_iff_get] at h
  rcases h with ⟨i, hi⟩

  -- 4. Establish the length of the list is exactly `N`.
  have h_len := length_finset_to_list (∅ : Finset (Fin N))

  -- 5. Show that the index `i` is strictly less than `N` utilizing purely arithmetic reasoning (`omega`).
  have h_isLt := i.isLt
  have h_lt : i.val < N := by omega

  -- 6. Construct `x : Fin N` with the exact same value as `i`.
  let x : Fin N := ⟨i.val, h_lt⟩

  -- 7. Using definitional equality, cast our `i.isLt` property to `x.val`'s bound constraint.
  have h_x_lt : x.val < (finset_to_list (∅ : Finset (Fin N))).length := h_isLt

  -- 8. Apply the retrieval API for `finset_to_list` at this specific index `x`.
  have h_get := finset_to_list_get (∅ : Finset (Fin N)) x h_x_lt

  -- 9. The membership condition `x ∈ ∅` simplifies to `False`, so the `if-then-else` yields `false`.
  have h_not_mem : x ∉ (∅ : Finset (Fin N)) := by simp
  rw [if_neg h_not_mem] at h_get

  -- 10. `⟨x.val, h_x_lt⟩` is definitionally equal to `i` (by Structure Eta-Reduction on `Fin`),
  --     so we enforce this typed equality explicitly.
  have h_eq : (finset_to_list (∅ : Finset (Fin N))).get i = false := h_get

  -- 11. Finally, rewrite `hi` substituting `h_eq`, creating the disjoint `false = true` which forms a contradiction.
  rw [h_eq] at hi
  contradiction

theorem list_count_set_true (l : List Bool) (i : ℕ) (h : i < l.length) (hi : l.get ⟨i, h⟩ = false) :
  (l.set i true).count true = l.count true + 1 :=
by
  induction l generalizing i with
  | nil =>
    -- Base case: l = [] has length 0, so h : i < 0 is a contradiction.
    exact False.elim (Nat.not_lt_zero i h)
  | cons x xs ih =>
    cases i with
    | zero =>
      -- Subcase: i = 0. The element being modified is the head of the list.
      -- List.get on index 0 evaluates definitionally to the head element.
      have hx : x = false := hi
      subst hx
      -- After substituting x = false, simp trivially reduces count evaluations.
      simp
      try omega
    | succ i' =>
      -- Subcase: i = i' + 1. The element being modified is in the tail `xs`.
      have h' : i' < xs.length := Nat.lt_of_succ_lt_succ h
      -- List.get on index i' + 1 evaluates definitionally to evaluating the tail at i'.
      have hi' : xs.get ⟨i', h'⟩ = false := hi
      specialize ih i' h' hi'

      cases x with
      | false =>
        -- If the head x is false, it does not contribute to the true count.
        simp [ih]
        try omega
      | true =>
        -- If the head x is true, it identically contributes +1 to both counts.
        simp [ih]
        try omega

theorem finset_to_list_insert_length {N : ℕ} (s : Finset (Fin N)) (a : Fin N) :
  (finset_to_list (insert a s)).length = ((finset_to_list s).set a.val true).length :=
by
  -- Reduce the left-hand side length calculation to `N`.
  rw [length_finset_to_list]
  -- Evaluate the right-hand side list update operation. The length is preserved.
  rw [List.length_set]
  -- Reduce the updated right-hand side length calculation to `N`.
  rw [length_finset_to_list]

theorem list_get_set_eq_lem {α : Type*} (l : List α) (a : ℕ) (i : ℕ) (v : α)
  (h2 : i < (l.set a v).length) (h_eq : i = a) :
  (l.set a v).get ⟨i, h2⟩ = v :=
by
  -- Revert constraints and indices to manually generalize them safely over the induction
  revert a i h2 h_eq
  induction l with
  | nil =>
    intro a i h2 h_eq
    -- For an empty list, `[].set a v` is `[]`. Its length is 0, so `h2 : i < 0`.
    -- `cases` automatically eliminates this impossible condition.
    cases h2
  | cons x xs ih =>
    intro a i h2 h_eq
    -- We perform case analysis on `a` *before* rewriting the equality.
    -- This strictly preserves variable structures.
    cases a with
    | zero =>
      -- When a = 0, h_eq becomes i = 0.
      cases h_eq
      -- Updating the head and grabbing the 0-th index definitionally evaluates to `v`.
      rfl
    | succ a' =>
      -- When a = a' + 1, h_eq becomes i = a' + 1.
      cases h_eq
      -- The goal drops a successor wrapper, mapping directly to the tail induction hypothesis.
      -- `Nat.le_of_succ_le_succ` precisely handles stripping the `succ` from the strict inequality proof bound.
      exact ih a' a' (Nat.le_of_succ_le_succ h2) rfl

theorem list_get_set_ne_lem {α : Type*} (l : List α) (a : ℕ) (i : ℕ) (v : α)
  (h2 : i < (l.set a v).length) (h3 : i < l.length) (h_ne : i ≠ a) :
  (l.set a v).get ⟨i, h2⟩ = l.get ⟨i, h3⟩ :=
by
  exact List.getElem_set_of_ne h_ne.symm v h2

theorem finset_to_list_insert_get_eq {N : ℕ} (s : Finset (Fin N)) (a : Fin N) (i : ℕ)
  (h1 : i < (finset_to_list (insert a s)).length)
  (h2 : i < ((finset_to_list s).set a.val true).length) :
  (finset_to_list (insert a s)).get ⟨i, h1⟩ = ((finset_to_list s).set a.val true).get ⟨i, h2⟩ :=
by
  have h_len_ins : (finset_to_list (insert a s)).length = N := length_finset_to_list (insert a s)
  have h_i : i < N := by
    have h1_copy := h1
    rw [h_len_ins] at h1_copy
    exact h1_copy
  by_cases h_eq : i = a.val
  · have h_a : (⟨i, h_i⟩ : Fin N) = a := Fin.ext h_eq
    have h_in : (⟨i, h_i⟩ : Fin N) ∈ insert a s := by
      rw [h_a]
      rw [Finset.mem_insert]
      exact Or.inl rfl
    have LHS_eq : (finset_to_list (insert a s)).get ⟨i, h1⟩ = if (⟨i, h_i⟩ : Fin N) ∈ insert a s then true else false :=
      finset_to_list_get (insert a s) ⟨i, h_i⟩ h1
    rw [LHS_eq, if_pos h_in]
    exact (list_get_set_eq_lem (finset_to_list s) a.val i true h2 h_eq).symm
  · have h_ne : i ≠ a.val := h_eq
    have h_a_ne : (⟨i, h_i⟩ : Fin N) ≠ a := by
      intro h_contra
      have h_val : (⟨i, h_i⟩ : Fin N).val = a.val := congrArg Fin.val h_contra
      exact h_ne h_val
    have h_iff : (⟨i, h_i⟩ : Fin N) ∈ insert a s ↔ (⟨i, h_i⟩ : Fin N) ∈ s := by
      rw [Finset.mem_insert]
      apply Iff.intro
      · intro h_mem
        cases h_mem with
        | inl h_eq2 => exact False.elim (h_a_ne h_eq2)
        | inr h_s => exact h_s
      · intro h_mem
        exact Or.inr h_mem
    have LHS_eq : (finset_to_list (insert a s)).get ⟨i, h1⟩ = if (⟨i, h_i⟩ : Fin N) ∈ insert a s then true else false :=
      finset_to_list_get (insert a s) ⟨i, h_i⟩ h1
    rw [LHS_eq]
    have h_len2 : (finset_to_list s).length = N := length_finset_to_list s
    have h3 : i < (finset_to_list s).length := by
      have h_i_copy := h_i
      rw [← h_len2] at h_i_copy
      exact h_i_copy
    have RHS_eq_val := list_get_set_ne_lem (finset_to_list s) a.val i true h2 h3 h_ne
    rw [RHS_eq_val]
    have RHS_eq2 : (finset_to_list s).get ⟨i, h3⟩ = if (⟨i, h_i⟩ : Fin N) ∈ s then true else false :=
      finset_to_list_get s ⟨i, h_i⟩ h3
    rw [RHS_eq2]
    by_cases h_in_s : (⟨i, h_i⟩ : Fin N) ∈ s
    · have h_in_ins : (⟨i, h_i⟩ : Fin N) ∈ insert a s := h_iff.mpr h_in_s
      rw [if_pos h_in_ins, if_pos h_in_s]
    · have h_not_in_ins : (⟨i, h_i⟩ : Fin N) ∉ insert a s := by
        intro h_contra
        exact h_in_s (h_iff.mp h_contra)
      rw [if_neg h_not_in_ins, if_neg h_in_s]

theorem finset_to_list_insert_eq_set {N : ℕ} (s : Finset (Fin N)) (a : Fin N) :
  finset_to_list (insert a s) = (finset_to_list s).set a.val true :=
by
  apply List.ext_get
  · exact finset_to_list_insert_length s a
  · exact finset_to_list_insert_get_eq s a

theorem finset_to_list_insert {N : ℕ} (s : Finset (Fin N)) (a : Fin N) (ha : a ∉ s) :
  (finset_to_list (insert a s)).count true = (finset_to_list s).count true + 1 :=
by
  rw [finset_to_list_insert_eq_set s a]

  have h_len : a.val < (finset_to_list s).length := by
    rw [length_finset_to_list]
    exact a.isLt

  have h_get : (finset_to_list s).get ⟨a.val, h_len⟩ = false := by
    rw [finset_to_list_get s a h_len, if_neg ha]

  exact list_count_set_true (finset_to_list s) a.val h_len h_get

theorem count_finset_to_list {N : ℕ} (s : Finset (Fin N)) :
  (finset_to_list s).count true = s.card :=
by
  refine @Finset.induction_on (Fin N) (fun x => (finset_to_list x).count true = x.card) _ s ?_ ?_
  · show (finset_to_list ∅).count true = (∅ : Finset (Fin N)).card
    calc
      (finset_to_list ∅).count true = 0 := finset_to_list_empty
      _ = (∅ : Finset (Fin N)).card := Finset.card_empty.symm
  · intro a s' ha ih
    show (finset_to_list (insert a s')).count true = (insert a s').card
    calc
      (finset_to_list (insert a s')).count true = (finset_to_list s').count true + 1 := finset_to_list_insert s' a ha
      _ = s'.card + 1 := by rw [ih]
      _ = (insert a s').card := (Finset.card_insert_of_notMem ha).symm

theorem finset_to_list_left_inv_len {N : ℕ} (l : List Bool) (h : l.length = N) :
  (finset_to_list (list_to_finset l h)).length = l.length :=
by
  rw [length_finset_to_list]
  exact h.symm

theorem mem_list_to_finset {N : ℕ} (l : List Bool) (h : l.length = N) (x : Fin N) :
  x ∈ list_to_finset l h ↔ l.get ⟨x.val, h.symm ▸ x.isLt⟩ = true :=
by
  subst h
  simp [list_to_finset]

theorem finset_to_list_left_inv_get {N : ℕ} (l : List Bool) (h : l.length = N) (i : ℕ)
  (h1 : i < (finset_to_list (list_to_finset l h)).length) (h2 : i < l.length) :
  (finset_to_list (list_to_finset l h)).get ⟨i, h1⟩ = l.get ⟨i, h2⟩ :=
by
  have i_lt_N : i < N := h ▸ h2
  have H1 : (finset_to_list (list_to_finset l h)).get ⟨i, h1⟩ = if (⟨i, i_lt_N⟩ : Fin N) ∈ list_to_finset l h then true else false :=
    finset_to_list_get (list_to_finset l h) ⟨i, i_lt_N⟩ h1
  have H2 : (⟨i, i_lt_N⟩ : Fin N) ∈ list_to_finset l h ↔ l.get ⟨i, h2⟩ = true :=
    mem_list_to_finset l h ⟨i, i_lt_N⟩
  rw [H1]
  by_cases hx : (⟨i, i_lt_N⟩ : Fin N) ∈ list_to_finset l h
  · rw [if_pos hx]
    exact (H2.mp hx).symm
  · rw [if_neg hx]
    have H3 : l.get ⟨i, h2⟩ ≠ true := mt H2.mpr hx
    generalize h_val : l.get ⟨i, h2⟩ = b
    cases b
    · rfl
    · exact False.elim (H3 h_val)

theorem finset_to_list_left_inv {N : ℕ} (l : List Bool) (h : l.length = N) :
  finset_to_list (list_to_finset l h) = l :=
by
  apply List.ext_get
  · exact finset_to_list_left_inv_len l h
  · intros i h1 h2
    exact finset_to_list_left_inv_get l h i h1 h2

theorem card_list_to_finset {N : ℕ} (l : List Bool) (h : l.length = N) :
  (list_to_finset l h).card = l.count true :=
by
  have h1 := count_finset_to_list (list_to_finset l h)
  rw [finset_to_list_left_inv l h] at h1
  exact h1.symm

theorem finset_to_list_right_inv {N : ℕ} (s : Finset (Fin N)) (h : (finset_to_list s).length = N) :
  list_to_finset (finset_to_list s) h = s :=
by
  ext x
  rw [mem_list_to_finset (finset_to_list s) h x]
  have H : x.val < (finset_to_list s).length := h.symm ▸ x.isLt
  rw [finset_to_list_get s x H]
  by_cases hx : x ∈ s
  · rw [if_pos hx]
    exact iff_of_true rfl hx
  · rw [if_neg hx]
    exact iff_of_false (fun contra => Bool.noConfusion contra) hx

theorem U_equiv_finset_nonempty (N m : ℕ) : Nonempty (U N m ≃ { s : Finset (Fin N) // s.card = m }) :=
Nonempty.intro {
    toFun := fun x => ⟨list_to_finset x.val x.property.1, by
      rw [card_list_to_finset x.val x.property.1, x.property.2]⟩
    invFun := fun s => ⟨finset_to_list s.val, ⟨length_finset_to_list s.val, by
      rw [count_finset_to_list s.val, s.property]⟩⟩
    left_inv := fun x => Subtype.ext (finset_to_list_left_inv x.val x.property.1)
    right_inv := fun s => Subtype.ext (finset_to_list_right_inv s.val (length_finset_to_list s.val))
  }

theorem card_finset_len_eq_choose (N m : ℕ) :
  Nat.card { s : Finset (Fin N) // s.card = m } = Nat.choose N m :=
by
  have h : Nat.card { s : Finset (Fin N) // s.card = m } =
    (Finset.powersetCard m (Finset.univ : Finset (Fin N))).card := by
    apply Nat.subtype_card (Finset.powersetCard m (Finset.univ : Finset (Fin N)))
    intro x
    simp [Finset.mem_powersetCard]
  rw [h, Finset.card_powersetCard]
  have h2 : (Finset.univ : Finset (Fin N)).card = N := by simp
  rw [h2]

theorem U_card (N m : ℕ) : Nat.card (U N m) = Nat.choose N m :=
by
  have e := Classical.choice (U_equiv_finset_nonempty N m)
  rw [Nat.card_congr e]
  exact card_finset_len_eq_choose N m

theorem my_card_congr {α β : Type*} (e : α ≃ β) : Nat.card α = Nat.card β :=
Nat.card_congr e

theorem InvalidPair_card_10 : Nat.card (InvalidPair_10) = Nat.choose 20 11 * Nat.choose 20 9 :=
by
  -- Extract the equivalence from the Nonempty proof
  have ⟨e⟩ := invalid_equiv_10

  -- Rewrite the cardinality of InvalidPair_10 to the cardinality of the product type
  rw [my_card_congr e]

  -- Break the cardinality of the product type into the product of cardinalities
  rw [my_card_prod]

  -- Resolve the cardinalities of the individual step dimensions
  rw [U_card 20 11]
  rw [U_card 20 9]

theorem P_pairs_card_10 : Nat.card (P_pairs_10) = (Nat.choose 20 10) ^ 2 :=
by
  dsimp [P_pairs_10]
  rw [my_card_prod, U_card]
  ring

theorem valid_invalid_equiv_10 : Nonempty (ValidPair_10 ⊕ InvalidPair_10 ≃ P_pairs_10) :=
by
  classical
  exact ⟨Equiv.sumCompl _⟩

theorem U_length {N m : ℕ} (x : U N m) : x.val.length = N :=
x.property.1

theorem U_get_eq_U_inj {N m : ℕ} (x : U N m) (n : ℕ) (hx : n < x.val.length) (hn : n < N) :
  x.val.get ⟨n, hx⟩ = U_inj N m x ⟨n, hn⟩ :=
rfl

theorem U_inj_injective (N m : ℕ) : Function.Injective (U_inj N m) :=
by
  intro x y h
  apply Subtype.ext
  rw [List.ext_get_iff]
  constructor
  · rw [U_length x, U_length y]
  · intro n hx hy
    have hn : n < N := by
      rw [← U_length x]
      exact hx
    have eq_x := U_get_eq_U_inj x n hx hn
    have eq_y := U_get_eq_U_inj y n hy hn
    rw [eq_x, eq_y]
    exact congr_fun h ⟨n, hn⟩

theorem U_finite (N m : ℕ) : Finite (U N m) :=
Finite.of_injective (U_inj N m) (U_inj_injective N m)

theorem valid_finite : Finite ValidPair_10 :=
by
  -- Explicitly introduce local instances step-by-step
  haveI h1 : Finite (U 20 10) := U_finite 20 10
  haveI h2 : Finite (U 20 10 × U 20 10) := inferInstance
  haveI h3 : Finite P_pairs_10 := h2

  -- Since ValidPair_10 is a Subtype of P_pairs_10, we inject it directly into the finite space
  apply Finite.of_injective (fun x => x.val)
  intro a b h
  exact Subtype.ext h

theorem invalid_finite : Finite InvalidPair_10 :=
by
  have : Finite (U 20 10) := U_finite 20 10
  delta InvalidPair_10 P_pairs_10
  infer_instance

theorem my_card_sum_valid_invalid : Nat.card (ValidPair_10 ⊕ InvalidPair_10) = Nat.card (ValidPair_10) + Nat.card (InvalidPair_10) :=
by
  haveI : Finite ValidPair_10 := valid_finite
  haveI : Finite InvalidPair_10 := invalid_finite
  exact Nat.card_sum

theorem Valid_add_Invalid_10 : Nat.card (ValidPair_10) + Nat.card (InvalidPair_10) = Nat.card (P_pairs_10) :=
by
  rw [← my_card_sum_valid_invalid]
  exact my_card_congr (Classical.choice valid_invalid_equiv_10)

theorem my_ProblemPath_points_length_pos {n : ℕ} (p : ProblemPath n) :
  0 < p.points.length :=
by
  have hn := p.nonempty
  cases h : p.points with
  | nil =>
    -- If the points list is empty, it contradicts the `p.nonempty` property.
    rw [h] at hn
    contradiction
  | cons hd tl =>
    -- If the points list has at least one element, its length is definitionally > 0.
    exact Nat.zero_lt_succ _

theorem points_to_steps_length (l : List (ℕ × ℕ)) :
  (points_to_steps l).length = l.length - 1 :=
by
  simp [points_to_steps]

theorem path_chain_get_or_aux (p1 p2 : ℕ × ℕ)
  (h : (fun (x₁, y₁) (x₂, y₂) ↦ (x₂, y₂) = (x₁ + 1, y₁) ∨ (x₂, y₂) = (x₁, y₁ + 1)) p1 p2) :
  p2 = (p1.1 + 1, p1.2) ∨ p2 = (p1.1, p1.2 + 1) :=
by
  rcases p1 with ⟨x1, y1⟩
  rcases p2 with ⟨x2, y2⟩
  exact h

theorem path_chain_get_or (L : List (ℕ × ℕ))
  (h_chain : L.Chain' (fun (x₁,y₁) (x₂,y₂) ↦ (x₂,y₂) = (x₁+1,y₁) ∨ (x₂,y₂) = (x₁,y₁+1)))
  (i : ℕ) (hi_L : i + 1 < L.length) :
  (L[i + 1]'hi_L) = ((L[i]'(Nat.lt_of_succ_lt hi_L)).1 + 1, (L[i]'(Nat.lt_of_succ_lt hi_L)).2) ∨
  (L[i + 1]'hi_L) = ((L[i]'(Nat.lt_of_succ_lt hi_L)).1, (L[i]'(Nat.lt_of_succ_lt hi_L)).2 + 1) :=
by
  apply path_chain_get_or_aux
  exact List.Chain'.getElem h_chain i hi_L

theorem points_to_steps_get_eq (L : List (ℕ × ℕ)) (i : ℕ)
  (hi : i < (points_to_steps L).length)
  (hi1 : i < L.length)
  (hi2 : i + 1 < L.length) :
  (points_to_steps L)[i]'hi = ((L[i + 1]'hi2).2 == (L[i]'hi1).2 + 1) :=
by
  induction L generalizing i with
  | nil =>
    have hl : ([] : List (ℕ × ℕ)).length = 0 := rfl
    omega
  | cons a L' ih =>
    cases L' with
    | nil =>
      have hl : ([a] : List (ℕ × ℕ)).length = 1 := rfl
      omega
    | cons b L'' =>
      cases i with
      | zero =>
        -- Base case: index 0 evaluates definitionally to the same boolean check.
        rfl
      | succ i' =>
        -- Inductive step: shift the problem over to the tail.
        have h_len3 : (points_to_steps (a :: b :: L'')).length = (points_to_steps (b :: L'')).length + 1 := rfl
        have h_len4 : (a :: b :: L'').length = (b :: L'').length + 1 := rfl

        -- Omega easily validates the strictly shrinking bounds
        have hi'_len : i' < (points_to_steps (b :: L'')).length := by omega
        have hi1' : i' < (b :: L'').length := by omega
        have hi2' : i' + 1 < (b :: L'').length := by omega

        -- Defeq reduction ensures that the evaluated expressions match the induction hypothesis precisely
        exact ih i' hi'_len hi1' hi2'

theorem nat_beq_self_add_one (a : ℕ) : (a == a + 1) = false :=
by
  cases h : a == a + 1
  · rfl
  · have h_ne : a ≠ a + 1 := by omega
    have h_not := not_beq_of_ne h_ne
    contradiction

theorem nat_beq_add_one_self (a : ℕ) : (a + 1 == a + 1) = true :=
by
  simp

theorem path_step_analysis (L : List (ℕ × ℕ))
  (h_chain : L.Chain' (fun (x₁,y₁) (x₂,y₂) ↦ (x₂,y₂) = (x₁+1,y₁) ∨ (x₂,y₂) = (x₁,y₁+1)))
  (i : ℕ) (hi_L : i + 1 < L.length)
  (hi_step : i < (points_to_steps L).length) :
  ((points_to_steps L)[i]'hi_step = false → L[i + 1]'hi_L = ((L[i]'(Nat.lt_of_succ_lt hi_L)).1 + 1, (L[i]'(Nat.lt_of_succ_lt hi_L)).2)) ∧
  ((points_to_steps L)[i]'hi_step = true → L[i + 1]'hi_L = ((L[i]'(Nat.lt_of_succ_lt hi_L)).1, (L[i]'(Nat.lt_of_succ_lt hi_L)).2 + 1)) :=
by
  have h_or := path_chain_get_or L h_chain i hi_L
  have h_pts := points_to_steps_get_eq L i hi_step (Nat.lt_of_succ_lt hi_L) hi_L
  cases h_or with
  | inl h_x =>
    constructor
    · intro _
      exact h_x
    · intro h
      rw [h_x] at h_pts
      change (points_to_steps L)[i]'hi_step = ((L[i]'(Nat.lt_of_succ_lt hi_L)).2 == (L[i]'(Nat.lt_of_succ_lt hi_L)).2 + 1) at h_pts
      rw [nat_beq_self_add_one] at h_pts
      rw [h_pts] at h
      contradiction
  | inr h_y =>
    constructor
    · intro h
      rw [h_y] at h_pts
      change (points_to_steps L)[i]'hi_step = ((L[i]'(Nat.lt_of_succ_lt hi_L)).2 + 1 == (L[i]'(Nat.lt_of_succ_lt hi_L)).2 + 1) at h_pts
      rw [nat_beq_add_one_self] at h_pts
      rw [h_pts] at h
      contradiction
    · intro _
      exact h_y

theorem list_take_succ_eq_append_get_custom {α : Type} (l : List α) (i : ℕ) (hi : i < l.length) :
  l.take (i + 1) = l.take i ++ [l[i]'hi] :=
by
  revert i
  induction l with
  | nil =>
    intro i hi
    contradiction
  | cons hd tl ih =>
    intro i hi
    cases i with
    | zero =>
      rfl
    | succ i' =>
      have hi' : i' < tl.length := Nat.lt_of_succ_lt_succ hi
      exact congrArg (fun xs => hd :: xs) (ih i' hi')

theorem list_count_append_false_false (l : List Bool) :
  (l ++ [false]).count false = l.count false + 1 :=
by
  rw [List.count_append]
  rfl

theorem list_count_append_false_true (l : List Bool) :
  (l ++ [true]).count false = l.count false :=
by
  simp

theorem list_count_append_true_true (l : List Bool) :
  (l ++ [true]).count true = l.count true + 1 :=
by
  induction l with
  | nil => rfl
  | cons h t ih =>
    cases h <;> simp [ih]

theorem list_count_append_true_false (l : List Bool) :
  (l ++ [false]).count true = l.count true :=
by
  simp [List.count_append]

theorem path_point_eq_count (L : List (ℕ × ℕ))
  (h_chain : L.Chain' (fun (x₁,y₁) (x₂,y₂) ↦ (x₂,y₂) = (x₁+1,y₁) ∨ (x₂,y₂) = (x₁,y₁+1)))
  (i : ℕ) (hi : i < L.length) (h0 : 0 < L.length) :
  L[i]'hi = ((L[0]'h0).1 + ((points_to_steps L).take i).count false,
             (L[0]'h0).2 + ((points_to_steps L).take i).count true) :=
by
  revert hi
  induction i with
  | zero =>
    intro hi
    have H : L[0]'hi = L[0]'h0 := rfl
    rw [H]
    have h_count_f : ((points_to_steps L).take 0).count false = 0 := rfl
    have h_count_t : ((points_to_steps L).take 0).count true = 0 := rfl
    rw [h_count_f, h_count_t]
    apply Prod.ext <;> omega
  | succ i ih =>
    intro hi
    have hi_step : i < (points_to_steps L).length := by
      rw [points_to_steps_length]
      omega
    have h_take_succ : (points_to_steps L).take (i + 1) = (points_to_steps L).take i ++ [(points_to_steps L)[i]'hi_step] :=
      list_take_succ_eq_append_get_custom _ i hi_step
    rw [h_take_succ]

    have h_step_cases := path_step_analysis L h_chain i hi hi_step

    by_cases hb : (points_to_steps L)[i]'hi_step = false
    · -- Subcase: The step evaluated to false (Step Right)
      have h_next := h_step_cases.1 hb
      rw [h_next, hb]
      rw [list_count_append_false_false, list_count_append_true_false]
      rw [ih (Nat.lt_of_succ_lt hi)]
      apply Prod.ext <;> omega
    · -- Subcase: The step evaluated to true (Step Up)
      have hb_true : (points_to_steps L)[i]'hi_step = true := by
        cases h : (points_to_steps L)[i]'hi_step
        · exact False.elim (hb h)
        · rfl
      have h_next := h_step_cases.2 hb_true
      rw [h_next, hb_true]
      rw [list_count_append_false_true, list_count_append_true_true]
      rw [ih (Nat.lt_of_succ_lt hi)]
      apply Prod.ext <;> omega

theorem ProblemPath_last_eq_get_length_sub_one {n : ℕ} (p : ProblemPath n) (h_len : p.points.length - 1 < p.points.length) :
  p.points[p.points.length - 1]'h_len = (n, n) :=
by
  have h2 : p.points[p.points.length - 1]'h_len = p.points.get ⟨p.points.length - 1, h_len⟩ := rfl
  have h1 : p.points.get ⟨p.points.length - 1, h_len⟩ = p.points.getLast p.nonempty := List.get_length_sub_one h_len
  rw [h2, h1]
  exact p.finish

theorem head_eq_get_zero {α : Type*} (L : List α) (h_nonempty : L ≠ []) (h_len : 0 < L.length) :
  L.head h_nonempty = L[0]'h_len :=
by
  cases L
  · contradiction
  · rfl

theorem ProblemPath_zero_eq {n : ℕ} (p : ProblemPath n) (h0 : 0 < p.points.length) :
  p.points[0]'h0 = (0, 0) :=
by
  rw [← head_eq_get_zero p.points p.nonempty h0]
  exact p.start

theorem bool_list_count_add_count (l : List Bool) :
  l.count false + l.count true = l.length :=
by
  induction l with
  | nil => rfl
  | cons b bs ih =>
    cases b
    · simp [ih]
      omega
    · simp [ih]
      omega

theorem list_take_all_length_sub_one {n : ℕ} (p : ProblemPath n) :
  (points_to_steps p.points).take (p.points.length - 1) = points_to_steps p.points :=
by
  rw [List.take_eq_self_iff, points_to_steps_length]

theorem ProblemPath_points_length {n : ℕ} (p : ProblemPath n) :
  p.points.length = 2 * n + 1 :=
by
  have h0 : 0 < p.points.length := my_ProblemPath_points_length_pos p
  have h_len : p.points.length - 1 < p.points.length := by omega
  have h_last : p.points[p.points.length - 1]'h_len = (n, n) := ProblemPath_last_eq_get_length_sub_one p h_len
  have h_zero : p.points[0]'h0 = (0, 0) := ProblemPath_zero_eq p h0
  have h_eq := path_point_eq_count p.points p.up_right (p.points.length - 1) h_len h0
  rw [h_last, h_zero] at h_eq
  have h_take : (points_to_steps p.points).take (p.points.length - 1) = points_to_steps p.points :=
    list_take_all_length_sub_one p
  rw [h_take] at h_eq
  have h_false : (points_to_steps p.points).count false = n := by
    have h1 := congrArg Prod.fst h_eq
    change n = 0 + (points_to_steps p.points).count false at h1
    omega
  have h_true : (points_to_steps p.points).count true = n := by
    have h2 := congrArg Prod.snd h_eq
    change n = 0 + (points_to_steps p.points).count true at h2
    omega
  have h_sum2 := bool_list_count_add_count (points_to_steps p.points)
  have h_len_eq := points_to_steps_length p.points
  omega

theorem ProblemPath_to_U_length {n : ℕ} (p : ProblemPath n) :
  (points_to_steps p.points).length = 2 * n :=
by
  have h1 := points_to_steps_length p.points
  have h2 := ProblemPath_points_length p
  omega

theorem steps_to_points_length (l : List Bool) : (steps_to_points l).length = l.length + 1 :=
by
  simp [steps_to_points]

theorem my_points_to_steps_length_plus_one {n : ℕ} (p : ProblemPath n) :
  (points_to_steps p.points).length + 1 = p.points.length :=
by
  rw [points_to_steps_length]
  have h := my_ProblemPath_points_length_pos p
  omega

theorem steps_to_points_get (l : List Bool) (i : ℕ) (hi : i < (steps_to_points l).length) :
  (steps_to_points l)[i]'hi = ((l.take i).count false, (l.take i).count true) :=
by
  have h_eq : (steps_to_points l)[i]'hi = (List.ofFn (fun j : Fin (l.length + 1) => ((l.take j.val).count false, (l.take j.val).count true))).get ⟨i, hi⟩ := rfl
  rw [h_eq]
  rw [List.get_ofFn]
  rfl

theorem list_ext_custom {α : Type*} (l1 l2 : List α)
  (hl : l1.length = l2.length)
  (h : ∀ (i : ℕ) (h1 : i < l1.length) (h2 : i < l2.length), l1[i]'h1 = l2[i]'h2) : l1 = l2 :=
by
  exact List.ext_getElem hl h

theorem simplify_start_pair (a b : ℕ) : (((0, 0) : ℕ × ℕ).1 + a, ((0, 0) : ℕ × ℕ).2 + b) = (a, b) :=
by
  simp

theorem points_to_steps_inv {n : ℕ} (p : ProblemPath n) :
  steps_to_points (points_to_steps p.points) = p.points :=
by
  apply list_ext_custom
  · rw [steps_to_points_length]
    exact my_points_to_steps_length_plus_one p
  · intro i h1 h2
    rw [steps_to_points_get (points_to_steps p.points) i h1]
    have h0 : 0 < p.points.length := my_ProblemPath_points_length_pos p
    rw [path_point_eq_count p.points p.up_right i h2 h0]
    have h_head : p.points.head p.nonempty = p.points[0]'h0 := head_eq_get_zero p.points p.nonempty h0
    have h_start := p.start
    rw [h_head] at h_start
    rw [h_start]
    exact (simplify_start_pair _ _).symm

theorem steps_to_points_get_snd (l : List Bool) (i : ℕ) (hi : i < (steps_to_points l).length) :
  (steps_to_points l)[i].2 = (l.take i).count true :=
by
  have h : (steps_to_points l)[i] = (List.ofFn (fun j : Fin (l.length + 1) => ((l.take j.val).count false, (l.take j.val).count true))).get ⟨i, hi⟩ := rfl
  rw [h, List.get_ofFn]
  rfl

theorem list_get_congr {α : Type*} {l1 l2 : List α} (h : l1 = l2) (i : ℕ) (h1 : i < l1.length) (h2 : i < l2.length) :
  l1[i]'(h1) = l2[i]'(h2) :=
by
  subst h
  rfl

theorem point_y_eq_steps_count {n : ℕ} (p : ProblemPath n) (i : ℕ) (h : i < p.points.length) :
  p.points[i].2 = ((points_to_steps p.points).take i).count true :=
by
  have h_inv : steps_to_points (points_to_steps p.points) = p.points := points_to_steps_inv p
  have h_len : i < (steps_to_points (points_to_steps p.points)).length := by
    rw [h_inv]
    exact h
  have h_get := steps_to_points_get_snd (points_to_steps p.points) i h_len
  have h_eq : p.points[i]'(h) = (steps_to_points (points_to_steps p.points))[i]'(h_len) :=
    list_get_congr h_inv.symm i h h_len
  rw [h_eq]
  exact h_get

theorem list_get_idx_congr_custom {α : Type*} (l : List α) (i j : ℕ) (hi : i < l.length) (hj : j < l.length) (h : i = j) : l[i]'hi = l[j]'hj :=
by
  cases h
  rfl

theorem ProblemPath_last_y {n : ℕ} (p : ProblemPath n) (h : 2 * n < p.points.length) :
  p.points[2 * n].2 = n :=
by
  have hl : p.points.length = 2 * n + 1 := ProblemPath_points_length p
  have h_eq : 2 * n = p.points.length - 1 := by omega
  have h_len : p.points.length - 1 < p.points.length := by omega
  have h_idx := list_get_idx_congr_custom p.points (2 * n) (p.points.length - 1) h h_len h_eq
  have h_val := ProblemPath_last_eq_get_length_sub_one p h_len
  rw [h_idx, h_val]

theorem ProblemPath_to_U_count {n : ℕ} (p : ProblemPath n) :
  (points_to_steps p.points).count true = n :=
by
  -- Establish that `2 * n` is a valid index into the points array
  have h_lt : 2 * n < p.points.length := by
    rw [ProblemPath_points_length p]
    exact Nat.lt_succ_self (2 * n)

  -- Apply the core sequence count relation at the last valid step index (2 * n)
  have h_count := point_y_eq_steps_count p (2 * n) h_lt

  -- The length of the mapped steps list is exactly `2 * n`
  have h_len : (points_to_steps p.points).length = 2 * n := ProblemPath_to_U_length p

  -- Taking `2 * n` elements from a list of length `2 * n` returns the exact same list
  have h_take : (points_to_steps p.points).take (2 * n) = points_to_steps p.points := by
    rw [← h_len, List.take_length]

  -- Substitute the simplified taken sequence back into our count relation
  rw [h_take] at h_count

  -- Substitute the known finishing property of the ProblemPath's y-coordinate
  rw [ProblemPath_last_y p h_lt] at h_count

  -- Flip the equality to exactly match the expected theorem target signature
  exact h_count.symm

theorem steps_to_points_nonempty {n : ℕ} (u : U (2 * n) n) : steps_to_points u.val ≠ [] :=
by
  intro h
  have h_len : (steps_to_points u.val).length = u.val.length + 1 := steps_to_points_length u.val
  have h_zero : (steps_to_points u.val).length = 0 := by
    rw [h]
    rfl
  rw [h_zero] at h_len
  omega

theorem steps_to_points_start {n : ℕ} (u : U (2 * n) n) :
  (steps_to_points u.val).head (steps_to_points_nonempty u) = (0, 0) :=
by
  -- 1. Establish that the generated points list has a strictly positive length
  have h_len : 0 < (steps_to_points u.val).length := by
    rw [steps_to_points_length u.val]
    exact Nat.zero_lt_succ _

  -- 2. Connect the `List.head` extraction to the `0`-th index element using the helper lemma
  rw [head_eq_get_zero (steps_to_points u.val) (steps_to_points_nonempty u) h_len]

  -- 3. Substitute the `0`-th index extraction to evaluate counts over a `0`-length taken sublist, and finish.
  rw [steps_to_points_get u.val 0 h_len]
  rfl

theorem getLast_eq_getElem_of_length {α : Type} (xs : List α) (h_not_empty : xs ≠ []) (n : ℕ) (h_len : xs.length = n + 1) (hn : n < xs.length) :
  xs.getLast h_not_empty = xs[n]'hn :=
by
  induction xs generalizing n with
  | nil =>
    -- Base case: the list is empty, which contradicts our non-empty hypothesis.
    exfalso
    exact h_not_empty rfl
  | cons x xs' ih =>
    -- Inductive step: decompose the tail to see if we are at the last element.
    cases xs' with
    | nil =>
      -- Subcase 1: the list is exactly `[x]`.
      cases n with
      | zero =>
        -- `getLast [x]` and `[x][0]` structurally evaluate to `x`.
        rfl
      | succ m =>
        -- If `n = m + 1`, evaluate lengths clearly so `omega` finds the arithmetical contradiction.
        exfalso
        simp only [List.length_cons, List.length_nil] at h_len
        omega
    | cons y ys =>
      -- Subcase 2: the list has at least two elements, `x :: y :: ys`.
      cases n with
      | zero =>
        -- If `n = 0`, length bounds are arithmetically violated.
        exfalso
        simp only [List.length_cons, List.length_nil] at h_len
        omega
      | succ m =>
        -- If `n = m + 1`, we step down the induction logically.
        -- We make `List.length` evaluations structurally explicit for `omega` to see the linearity.
        have h_len' : (y :: ys).length = m + 1 := by
          simp only [List.length_cons, List.length_nil] at h_len ⊢
          omega
        have hn' : m < (y :: ys).length := by
          simp only [List.length_cons, List.length_nil] at hn ⊢
          omega
        have h_not_empty' : y :: ys ≠ [] := by
          intro h
          contradiction

        -- Because Lean's proof irrelevance renders any two proofs of `y :: ys ≠ []` and
        -- indexing boundary comparisons definitionally equal, the inductive hypothesis applies exactly.
        exact ih h_not_empty' m h_len' hn'

theorem steps_to_points_getLast_eq (l : List Bool) (h : steps_to_points l ≠ []) :
  (steps_to_points l).getLast h = (l.count false, l.count true) :=
by
  -- Extrapolate lengths and verify strict boundary properties avoiding Nat subtraction
  have h_len : (steps_to_points l).length = l.length + 1 := steps_to_points_length l
  have h_lt : l.length < (steps_to_points l).length := by omega

  -- Relate `getLast` explicitly to list access at index `l.length` using the helper lemma
  have h_last := getLast_eq_getElem_of_length (steps_to_points l) h l.length h_len h_lt
  rw [h_last]

  -- Map the explicit coordinate evaluation property
  have h_get := steps_to_points_get l l.length h_lt
  rw [h_get]

  -- Evaluate bounding slice trivially with Mathlib's length constraints
  rw [List.take_length]

theorem steps_to_points_finish {n : ℕ} (u : U (2 * n) n) :
  (steps_to_points u.val).getLast (steps_to_points_nonempty u) = (n, n) :=
by
  -- Evaluate the end point of the stepped path using our generalized lemma
  rw [steps_to_points_getLast_eq u.val (steps_to_points_nonempty u)]

  -- Extract properties directly from the U Subtype to avoid graph collision overheads
  have h_len : u.val.length = 2 * n := u.property.1
  have h_true : u.val.count true = n := u.property.2
  have h_add := bool_list_count_add_count u.val

  -- Utilize the math arithmetic solver omega to isolate and solve the count of falses
  have h_false : u.val.count false = n := by omega

  -- Substitute both resolved variable counts back into the tuple pair mapping
  rw [h_false, h_true]

theorem list_chain'_implies_get_custom {α : Type} {R : α → α → Prop} {l : List α}
  (h : l.Chain' R) :
  ∀ (i : ℕ) (hi : i + 1 < l.length), R (l[i]'(Nat.lt_of_succ_lt hi)) (l[i + 1]'hi) :=
by
  intro i hi
  exact List.Chain'.getElem h i hi

theorem list_chain_hyp_shift {α : Type} {R : α → α → Prop} {a : α} {l : List α}
  (h : ∀ (i : ℕ) (hi : i + 1 < (a :: l).length), R ((a :: l)[i]'(Nat.lt_of_succ_lt hi)) ((a :: l)[i + 1]'hi)) :
  ∀ (i : ℕ) (hi : i + 1 < l.length), R (l[i]'(Nat.lt_of_succ_lt hi)) (l[i + 1]'hi) :=
by
  intro i hi
  exact h (i + 1) (Nat.succ_lt_succ hi)

theorem list_chain_hyp_zero {α : Type} {R : α → α → Prop} {a b : α} {l : List α}
  (h : ∀ (i : ℕ) (hi : i + 1 < (a :: b :: l).length), R ((a :: b :: l)[i]'(Nat.lt_of_succ_lt hi)) ((a :: b :: l)[i + 1]'hi)) :
  R a b :=
by
  have hi : 0 + 1 < (a :: b :: l).length := by
    change 1 < l.length + 2
    omega
  exact h 0 hi

theorem get_custom_implies_list_chain' {α : Type} {R : α → α → Prop} {l : List α}
  (h : ∀ (i : ℕ) (hi : i + 1 < l.length), R (l[i]'(Nat.lt_of_succ_lt hi)) (l[i + 1]'hi)) :
  l.Chain' R :=
by
  induction l with
  | nil => exact List.chain'_nil
  | cons a l ih =>
    cases l with
    | nil => exact List.Chain.nil
    | cons b l' =>
      exact List.Chain.cons (list_chain_hyp_zero h) (ih (list_chain_hyp_shift h))

theorem list_chain'_iff_get_custom {α : Type} {R : α → α → Prop} {l : List α} :
  l.Chain' R ↔ ∀ (i : ℕ) (hi : i + 1 < l.length), R (l[i]'(Nat.lt_of_succ_lt hi)) (l[i + 1]'hi) :=
⟨list_chain'_implies_get_custom, get_custom_implies_list_chain'⟩

theorem steps_to_points_chain_core (l : List Bool) :
  (steps_to_points l).Chain' (fun (x₁, y₁) (x₂, y₂) ↦ (x₂, y₂) = (x₁ + 1, y₁) ∨ (x₂, y₂) = (x₁, y₁ + 1)) :=
by
  apply list_chain'_iff_get_custom.mpr
  intro i hi
  have h_len : (steps_to_points l).length = l.length + 1 := steps_to_points_length l
  have hi_l : i < l.length := by omega
  have h1 : (steps_to_points l)[i]'(Nat.lt_of_succ_lt hi) = ((l.take i).count false, (l.take i).count true) :=
    steps_to_points_get l i (Nat.lt_of_succ_lt hi)
  have h2 : (steps_to_points l)[i + 1]'hi = ((l.take (i + 1)).count false, (l.take (i + 1)).count true) :=
    steps_to_points_get l (i + 1) hi
  rw [h1, h2]
  change ((l.take (i + 1)).count false, (l.take (i + 1)).count true) =
         ((l.take i).count false + 1, (l.take i).count true) ∨
         ((l.take (i + 1)).count false, (l.take (i + 1)).count true) =
         ((l.take i).count false, (l.take i).count true + 1)
  have h_take : l.take (i + 1) = l.take i ++ [l[i]'hi_l] := list_take_succ_eq_append_get_custom l i hi_l
  rw [h_take]
  have h_bool : l[i]'hi_l = false ∨ l[i]'hi_l = true := by
    generalize h_val : l[i]'hi_l = b
    cases b
    · exact Or.inl rfl
    · exact Or.inr rfl
  rcases h_bool with h_f | h_t
  · rw [h_f]
    rw [list_count_append_false_false]
    rw [list_count_append_true_false]
    left
    rfl
  · rw [h_t]
    rw [list_count_append_false_true]
    rw [list_count_append_true_true]
    right
    rfl

theorem steps_to_points_chain {n : ℕ} (u : U (2 * n) n) :
  (steps_to_points u.val).Chain' (fun (x₁, y₁) (x₂, y₂) ↦ (x₂, y₂) = (x₁ + 1, y₁) ∨ (x₂, y₂) = (x₁, y₁ + 1)) :=
by
  exact steps_to_points_chain_core u.val

theorem path_cond_to_counts (l1 l2 : List Bool) (h : path_cond l1 l2) :
  ∀ i ≤ l1.length, (l1.take i).count true ≤ (l2.take i).count true :=
h

theorem counts_to_path_cond (l1 l2 : List Bool) (h : ∀ i ≤ l1.length, (l1.take i).count true ≤ (l2.take i).count true) :
  path_cond l1 l2 :=
by
  exact h

theorem path_cond_iff (l1 l2 : List Bool) :
  path_cond l1 l2 ↔ ∀ i ≤ l1.length, (l1.take i).count true ≤ (l2.take i).count true :=
⟨path_cond_to_counts l1 l2, counts_to_path_cond l1 l2⟩

theorem pair_cond_equiv {n : ℕ} (p1 p2 : ProblemPath n) :
  (∀ (i : ℕ) (h1 : i < p1.points.length) (h2 : i < p2.points.length),
    p1.points[i].2 ≤ p2.points[i].2) ↔
  path_cond (points_to_steps p1.points) (points_to_steps p2.points) :=
by
  rw [path_cond_iff]
  constructor
  · intro h i hi
    have len1 : (points_to_steps p1.points).length = 2 * n := ProblemPath_to_U_length p1
    have pt_len1 : p1.points.length = 2 * n + 1 := ProblemPath_points_length p1
    have pt_len2 : p2.points.length = 2 * n + 1 := ProblemPath_points_length p2
    have h1 : i < p1.points.length := by omega
    have h2 : i < p2.points.length := by omega
    have h_ineq := h i h1 h2
    rw [point_y_eq_steps_count p1 i h1] at h_ineq
    rw [point_y_eq_steps_count p2 i h2] at h_ineq
    exact h_ineq
  · intro h i h1 h2
    have len1 : (points_to_steps p1.points).length = 2 * n := ProblemPath_to_U_length p1
    have pt_len1 : p1.points.length = 2 * n + 1 := ProblemPath_points_length p1
    have hi : i ≤ (points_to_steps p1.points).length := by omega
    have h_ineq := h i hi
    rw [point_y_eq_steps_count p1 i h1]
    rw [point_y_eq_steps_count p2 i h2]
    exact h_ineq

theorem ValidPair_to_pair_cond {n : ℕ} (v1 v2 : U (2 * n) n) (h : path_cond v1.val v2.val) :
  ∀ (i : ℕ) (h1 : i < (steps_to_points v1.val).length) (h2 : i < (steps_to_points v2.val).length),
    (steps_to_points v1.val)[i].2 ≤ (steps_to_points v2.val)[i].2 :=
by
  intro i h1 h2
  -- Rewrite the y-coordinates of both sides using our lemma.
  -- This effectively translates the points back to counts of 'true' boolean steps.
  rw [steps_to_points_get_snd v1.val i h1, steps_to_points_get_snd v2.val i h2]

  -- Obtain the length bounds for v1 and use `omega` to verify that `i ≤ v1.val.length`
  have hl := steps_to_points_length v1.val
  have h_bound : i ≤ v1.val.length := by omega

  -- Supply the specific index and the bound directly to the path_cond hypothesis to close the goal.
  exact h i h_bound

theorem points_to_steps_steps_to_points_length (l : List Bool) :
  (points_to_steps (steps_to_points l)).length = l.length :=
by
  rw [points_to_steps_length, steps_to_points_length]
  omega

theorem steps_to_points_succ_snd_eq_of_true (l : List Bool) (i : ℕ) (hil : i < l.length)
  (hi_L : i + 1 < (steps_to_points l).length) (h : l[i]'hil = true) :
  ((steps_to_points l)[i + 1]'hi_L).2 = ((steps_to_points l)[i]'(Nat.lt_of_succ_lt hi_L)).2 + 1 :=
by
  simp only [steps_to_points_get]
  rw [list_take_succ_eq_append_get_custom l i hil]
  rw [h]
  rw [list_count_append_true_true]

theorem steps_to_points_succ_snd_eq_of_false (l : List Bool) (i : ℕ) (hil : i < l.length)
  (hi_L : i + 1 < (steps_to_points l).length) (h : l[i]'hil = false) :
  ((steps_to_points l)[i + 1]'hi_L).2 = ((steps_to_points l)[i]'(Nat.lt_of_succ_lt hi_L)).2 :=
by
  -- Relate the point's y-coordinates to the counting of `true`s in the prefixes
  have h1 : ((steps_to_points l)[i + 1]'hi_L).2 = (l.take (i + 1)).count true := steps_to_points_get_snd l (i + 1) hi_L
  have h2 : ((steps_to_points l)[i]'(Nat.lt_of_succ_lt hi_L)).2 = (l.take i).count true := steps_to_points_get_snd l i (Nat.lt_of_succ_lt hi_L)

  -- Rewrite LHS and RHS to be in terms of `list.count`
  rw [h1, h2]

  -- Decompose the list prefix
  have h3 : l.take (i + 1) = l.take i ++ [l[i]'hil] := list_take_succ_eq_append_get_custom l i hil

  -- Apply the sequence of rewrites: decomposing the prefix, evaluating the element (since it is `false`), and shrinking the list count
  rw [h3, h, list_count_append_true_false]

theorem get_points_to_steps_steps_to_points (l : List Bool) (i : ℕ)
  (hi : i < (points_to_steps (steps_to_points l)).length)
  (hil : i < l.length) :
  (points_to_steps (steps_to_points l))[i]'hi = l[i]'hil :=
by
  have h_len_L : (steps_to_points l).length = l.length + 1 := steps_to_points_length l
  have hi_L : i + 1 < (steps_to_points l).length := by omega
  have h_chain := steps_to_points_chain_core l
  have step_analysis := path_step_analysis (steps_to_points l) h_chain i hi_L hi
  have h_step_false := step_analysis.1
  have h_step_true := step_analysis.2

  have hp : (points_to_steps (steps_to_points l))[i]'hi = true ∨ (points_to_steps (steps_to_points l))[i]'hi = false := by
    cases h : (points_to_steps (steps_to_points l))[i]'hi
    · exact Or.inr rfl
    · exact Or.inl rfl

  have hl_cases : l[i]'hil = true ∨ l[i]'hil = false := by
    cases h : l[i]'hil
    · exact Or.inr rfl
    · exact Or.inl rfl

  rcases hp with hp_true | hp_false
  · rcases hl_cases with hl_true | hl_false
    · rw [hp_true, hl_true]
    · have h1 := h_step_true hp_true
      have h1_snd : ((steps_to_points l)[i + 1]'hi_L).2 = ((steps_to_points l)[i]'(Nat.lt_of_succ_lt hi_L)).2 + 1 := by rw [h1]
      have h2_snd := steps_to_points_succ_snd_eq_of_false l i hil hi_L hl_false
      omega
  · rcases hl_cases with hl_true | hl_false
    · have h1 := h_step_false hp_false
      have h1_snd : ((steps_to_points l)[i + 1]'hi_L).2 = ((steps_to_points l)[i]'(Nat.lt_of_succ_lt hi_L)).2 := by rw [h1]
      have h2_snd := steps_to_points_succ_snd_eq_of_true l i hil hi_L hl_true
      omega
    · rw [hp_false, hl_false]

theorem points_to_steps_steps_to_points (l : List Bool) :
  points_to_steps (steps_to_points l) = l :=
by
  apply list_ext_custom
  · exact points_to_steps_steps_to_points_length l
  · intro i h1 h2
    exact get_points_to_steps_steps_to_points l i h1 h2

theorem steps_to_points_inv {n : ℕ} (u : U (2 * n) n) :
  points_to_steps (steps_to_points u.val) = u.val :=
by
  exact points_to_steps_steps_to_points u.val

theorem ProblemPath_ext {n : ℕ} (p1 p2 : ProblemPath n) (h : p1.points = p2.points) : p1 = p2 :=
by
  -- Destruct both structures into their underlying points and property proofs
  cases p1
  cases p2
  -- Simplify the hypothesis by evaluating the `points` projections on the constructors
  dsimp only at h
  -- Substitute the points list of p1 with the points list of p2 everywhere in the context
  subst h
  -- Close the goal by reflexivity; proof irrelevance automatically equates the `Prop` fields
  rfl

theorem ProblemPath_pair_ext {n : ℕ} (p1 p2 : ProblemPath.pair n)
  (h1 : p1.path1 = p2.path1) (h2 : p1.path2 = p2.path2) : p1 = p2 :=
by
  cases p1
  cases p2
  simp_all

theorem f_10_eq_card_ValidPair : f 10 = Nat.card ValidPair_10 :=
by
  change Nat.card (ProblemPath.pair 10) = Nat.card ValidPair_10

  let to_U (p : ProblemPath 10) : U 20 10 :=
    ⟨points_to_steps p.points, @ProblemPath_to_U_length 10 p, @ProblemPath_to_U_count 10 p⟩

  let to_P (u : U 20 10) : ProblemPath 10 :=
    { points := steps_to_points u.val,
      nonempty := @steps_to_points_nonempty 10 u,
      start := @steps_to_points_start 10 u,
      finish := @steps_to_points_finish 10 u,
      up_right := @steps_to_points_chain 10 u }

  let toFun (p : ProblemPath.pair 10) : ValidPair_10 :=
    ⟨(to_U p.path1, to_U p.path2), (@pair_cond_equiv 10 p.path1 p.path2).mp p.cond⟩

  let invFun (v : ValidPair_10) : ProblemPath.pair 10 :=
    { path1 := to_P v.val.1,
      path2 := to_P v.val.2,
      cond := @ValidPair_to_pair_cond 10 v.val.1 v.val.2 v.property }

  have left_inv : ∀ p, invFun (toFun p) = p := by
    intro p
    apply ProblemPath_pair_ext
    · apply ProblemPath_ext
      exact @points_to_steps_inv 10 p.path1
    · apply ProblemPath_ext
      exact @points_to_steps_inv 10 p.path2

  have right_inv : ∀ v, toFun (invFun v) = v := by
    intro v
    apply Subtype.ext
    apply Prod.ext
    · apply Subtype.ext
      exact @steps_to_points_inv 10 v.val.1
    · apply Subtype.ext
      exact @steps_to_points_inv 10 v.val.2

  let eqv : ProblemPath.pair 10 ≃ ValidPair_10 := {
    toFun := toFun,
    invFun := invFun,
    left_inv := left_inv,
    right_inv := right_inv
  }

  exact my_card_congr eqv

theorem f_10_val : f 10 + Nat.choose 20 11 * Nat.choose 20 9 = (Nat.choose 20 10) ^ 2 :=
by
  -- Substitute f 10 with the cardinality of ValidPair_10
  rw [f_10_eq_card_ValidPair]
  -- Replace the numeric product with the cardinality of InvalidPair_10
  rw [← InvalidPair_card_10]
  -- Combine valid and invalid path pairs into the total unconstrained paths
  rw [Valid_add_Invalid_10]
  -- Replace the total path pairs with its evaluated cardinality
  rw [P_pairs_card_10]

theorem f_10_eq_valid_pair : f 10 = Nat.card (ValidPair_10) :=
by
  have h_f := f_10_val
  have h := Valid_add_Invalid_10
  rw [P_pairs_card_10, InvalidPair_card_10] at h
  omega

theorem f_10_value : f 10 + (Nat.choose 20 11 * Nat.choose 20 9) = (Nat.choose 20 10) ^ 2 :=
by
  rw [f_10_eq_valid_pair]
  rw [← InvalidPair_card_10]
  rw [Valid_add_Invalid_10]
  rw [P_pairs_card_10]

theorem f_eq_card_ValidPair_10 : f 10 = Nat.card (ValidPair_10) :=
by
  have h1 := f_10_value
  have h2 := InvalidPair_card_10
  have h3 := P_pairs_card_10
  have h4 := Valid_add_Invalid_10
  omega

theorem PBBasic012 : f 10 = (Nat.choose 20 10)^2 - (Nat.choose 20 9)^2 :=
by
  rw [f_eq_card_ValidPair_10]
  have h := Valid_add_Invalid_10
  rw [InvalidPair_card_10] at h
  rw [P_pairs_card_10] at h

  -- Symmetrically evaluate the offset binomial coefficient boundary robustly
  -- ensuring no unsolved metavariables confuse the tactic by presenting an explicit target structural change
  have h_symm : Nat.choose 20 11 = Nat.choose 20 9 := by
    change Nat.choose 20 (20 - 9) = Nat.choose 20 9
    exact Nat.choose_symm (by decide)
  rw [h_symm] at h

  -- Algebraically map the multiplied counts into identical powers
  have h_sq : Nat.choose 20 9 * Nat.choose 20 9 = (Nat.choose 20 9)^2 := by ring
  rw [h_sq] at h

  -- Extract integer subtraction bounding Nat truncation via Omega handling the explicit form directly
  omega
