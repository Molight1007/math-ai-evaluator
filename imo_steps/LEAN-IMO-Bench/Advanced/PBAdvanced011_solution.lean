import Mathlib
open Classical
def PosFun (f : ℝ → ℝ) : Prop :=
  ∀ x > 0, 0 < f x
def satisfies_eq (f : ℝ → ℝ) : Prop :=
  ∀ x y, 0 < x → 0 < y → y * f (y * f x + 1) = f (1 / x + f y)

theorem lemma2_eq_f_aux (f : ℝ → ℝ) (heq : satisfies_eq f) (x y z : ℝ)
    (hx : 0 < x) (hy : 0 < y) (hyz : f y = z) :
    f ((1 : ℝ) / x + z) = y * f (y * f x + 1) :=
by
  rw [← hyz]
  have H := heq x y hx hy
  first | exact H | exact Eq.symm H

theorem lemma5_f_pos (f : ℝ → ℝ) (hf : PosFun f) (x : ℝ) (hx : 0 < x) : 0 < f x :=
hf x hx

theorem lemma1_surjective_eval (f : ℝ → ℝ) (x y z : ℝ)
  (hx : x = z + 1) (hy : y * f x = z) :
  y * f (y * f x + 1) = z :=
by
  -- 1. Substitute the inner sub-expression y * f x with z using hypothesis hy
  rw [hy]
  -- 2. Use the symmetric form of hypothesis hx to replace z + 1 with x
  rw [← hx]
  -- 3. Apply hypothesis hy again to conclude that y * f x evaluates exactly to z
  rw [hy]

theorem lemma1_surjective_w_pos (x fy : ℝ) (hx : 0 < x) (hfy : 0 < fy) :
  0 < (1 : ℝ) / x + fy :=
by
  positivity

theorem lemma1_surjective (f : ℝ → ℝ) (hf : PosFun f) (heq : satisfies_eq f) :
    ∀ z > 0, ∃ w > 0, f w = z :=
by
  intro z hz
  -- Construct x and establish x > 0
  let x := z + 1
  have hx : x = z + 1 := rfl
  have hx_pos : 0 < x := by linarith

  -- Since x > 0, its evaluated function value is positive
  have hfx_pos : 0 < f x := lemma5_f_pos f hf x hx_pos

  -- Construct y and establish y > 0
  let y := z / f x
  have hy_pos : 0 < y := div_pos hz hfx_pos

  -- Confirm our crucial algebraic selection equality y * f(x) = z
  have hfx_ne : f x ≠ 0 := ne_of_gt hfx_pos
  have hy_mul : y * f x = z := div_mul_cancel₀ z hfx_ne

  -- Simplify nested function application
  have heval : y * f (y * f x + 1) = z := lemma1_surjective_eval f x y z hx hy_mul

  -- Invoke functional equation structure linking LHS evaluations back to single application expressions
  have h_eq_aux : f ((1 : ℝ) / x + f y) = y * f (y * f x + 1) :=
    lemma2_eq_f_aux f heq x y (f y) hx_pos hy_pos rfl

  -- Consequently bridge the functional side back to z
  have h_eq : f ((1 : ℝ) / x + f y) = z := by
    rw [h_eq_aux]
    exact heval

  -- Define the witness explicitly
  let w := (1 : ℝ) / x + f y
  have hfy_pos : 0 < f y := lemma5_f_pos f hf y hy_pos

  -- Verify the target witness is strictly positive
  have hw_pos : 0 < w := lemma1_surjective_w_pos x (f y) hx_pos hfy_pos

  -- Bypass `use` closing the goal early; provide the full witness explicitly
  exact ⟨w, hw_pos, h_eq⟩

theorem lemma2_eq_f (f : ℝ → ℝ) (hf : PosFun f) (heq : satisfies_eq f) :
    ∀ a b, 0 < a → 0 < b → f a = f b → ∀ z > 0, f ((1 : ℝ) / a + z) = f ((1 : ℝ) / b + z) :=
by
  intro a b ha hb hab z hz
  obtain ⟨y, hy_pos, hyz⟩ := lemma1_surjective f hf heq z hz
  rw [lemma2_eq_f_aux f heq a y z ha hy_pos hyz]
  rw [lemma2_eq_f_aux f heq b y z hb hy_pos hyz]
  rw [hab]

theorem lemma3_eq_f2 (f : ℝ → ℝ) (hf : PosFun f) (heq : satisfies_eq f) :
    ∀ a b, 0 < a → 0 < b → f a = f b → ∀ v > 0, a * f (a * v + 1) = b * f (b * v + 1) :=
by
  intro a b ha hb hab v hv
  -- By surjectivity, there is some w > 0 such that f(w) = v
  obtain ⟨w, hw1, hw2⟩ := lemma1_surjective f hf heq v hv

  -- Apply the functional equation for (x = w, y = a) and (x = w, y = b)
  have h1 : a * f (a * f w + 1) = f (1 / w + f a) := heq w a hw1 ha
  have h2 : b * f (b * f w + 1) = f (1 / w + f b) := heq w b hw1 hb

  -- Chain equalities directly solving the problem
  calc
    a * f (a * v + 1) = a * f (a * f w + 1) := by rw [← hw2]
    _                 = f (1 / w + f a)     := h1
    _                 = f (1 / w + f b)     := by rw [hab]
    _                 = b * f (b * f w + 1) := h2.symm
    _                 = b * f (b * v + 1)   := by rw [hw2]

theorem lemma5_algebraic_id1 (a b : ℝ) (ha : 0 < a) (hb : 0 < b) :
    a * ((1 : ℝ) / (a * b)) + 1 = (1 : ℝ) / b + 1 :=
by
  have h1 : a ≠ 0 := ne_of_gt ha
  have h2 : b ≠ 0 := ne_of_gt hb
  have h3 : a * b ≠ 0 := mul_ne_zero h1 h2
  field_simp [h1, h2, h3]

theorem lemma5_algebraic_id2 (a b : ℝ) (ha : 0 < a) (hb : 0 < b) :
    b * ((1 : ℝ) / (a * b)) + 1 = (1 : ℝ) / a + 1 :=
by
  have h1 : a ≠ 0 := by positivity
  have h2 : b ≠ 0 := by positivity
  have h3 : a * b ≠ 0 := by positivity
  field_simp

theorem lemma5_cancel (a b y : ℝ) (h : a * y = b * y) (hy : 0 < y) : a = b :=
by
  exact mul_right_cancel₀ (ne_of_gt hy) h

theorem lemma5_v_pos (a b : ℝ) (ha : 0 < a) (hb : 0 < b) : 0 < (1 : ℝ) / (a * b) :=
by
  positivity

theorem lemma5_pos_arg (b : ℝ) (hb : 0 < b) : 0 < (1 : ℝ) / b + 1 :=
by
  positivity

theorem zero_lt_one_real : (0 : ℝ) < (1 : ℝ) :=
zero_lt_one

theorem lemma5_injective (f : ℝ → ℝ) (hf : PosFun f) (heq : satisfies_eq f) :
    ∀ a b, 0 < a → 0 < b → f a = f b → a = b :=
by
  intros a b ha hb hab
  have hv : 0 < (1 : ℝ) / (a * b) := lemma5_v_pos a b ha hb
  have h2 : f ((1 : ℝ) / a + 1) = f ((1 : ℝ) / b + 1) :=
    lemma2_eq_f f hf heq a b ha hb hab (1 : ℝ) zero_lt_one_real
  have h3 : a * f (a * ((1 : ℝ) / (a * b)) + 1) = b * f (b * ((1 : ℝ) / (a * b)) + 1) :=
    lemma3_eq_f2 f hf heq a b ha hb hab ((1 : ℝ) / (a * b)) hv

  -- Swap the inner algebraic compositions out
  rw [lemma5_algebraic_id1 a b ha hb, lemma5_algebraic_id2 a b ha hb] at h3

  -- Use h2 to align the function's evaluation on the right-hand side
  rw [h2] at h3

  -- Prove that the evaluated function operates on and emits strict positive reals
  have harg_pos : 0 < (1 : ℝ) / b + 1 := lemma5_pos_arg b hb
  have h_pos : 0 < f ((1 : ℝ) / b + 1) := lemma5_f_pos f hf ((1 : ℝ) / b + 1) harg_pos

  -- Complete proof by safe multiplicative cancellation on the right
  exact lemma5_cancel a b (f ((1 : ℝ) / b + 1)) h3 h_pos

theorem lemma6_f_f_add_one (f : ℝ → ℝ) (hf : PosFun f) (heq : satisfies_eq f) :
    ∀ x > 0, f (f x + 1) = f ((1 : ℝ) / x + f 1) :=
by
  intro x hx
  have h1 : 0 < (1 : ℝ) := by positivity
  have h2 := heq x (1 : ℝ) hx h1
  calc
    f (f x + 1) = (1 : ℝ) * f ((1 : ℝ) * f x + 1) := by simp only [one_mul]
    _ = f ((1 : ℝ) / x + f 1) := h2

theorem lemma7_f_eq_inv_add_C (f : ℝ → ℝ) (hf : PosFun f) (heq : satisfies_eq f) :
    ∀ x > 0, f x = (1 : ℝ) / x + f 1 - 1 :=
by
  intro x hx
  have hfx : 0 < f x := hf x hx
  have h1 : 0 < f x + 1 := by linarith
  have hf1 : 0 < f 1 := hf 1 zero_lt_one
  have hx_inv : 0 < (1 : ℝ) / x := div_pos zero_lt_one hx
  have h2 : 0 < (1 : ℝ) / x + f 1 := by linarith
  have h3 : f (f x + 1) = f ((1 : ℝ) / x + f 1) := lemma6_f_f_add_one f hf heq x hx
  have h4 : f x + 1 = (1 : ℝ) / x + f 1 := lemma5_injective f hf heq (f x + 1) ((1 : ℝ) / x + f 1) h1 h2 h3
  linarith

theorem lemma8_aux_denom1_ne_zero (F : ℝ) (hF : 0 < F) : 2 * F + 1 ≠ 0 :=
by
  linarith

theorem lemma8_aux_denom2_ne_zero (F : ℝ) (hF : 0 < F) : F + (1 : ℝ) / 2 ≠ 0 :=
by
  linarith

theorem lemma8_aux_frac_eq (F : ℝ) (hF : 0 < F) :
    2 * ((1 : ℝ) / (2 * F + 1)) = (1 : ℝ) / (F + (1 : ℝ) / 2) :=
by
  have h1 : 2 * F + 1 ≠ 0 := lemma8_aux_denom1_ne_zero F hF
  have h2 : F + (1 : ℝ) / 2 ≠ 0 := lemma8_aux_denom2_ne_zero F hF
  field_simp [h1, h2]

theorem lemma8_f1_eq_1 (f : ℝ → ℝ) (hf : PosFun f) (heq : satisfies_eq f) :
    f 1 = 1 :=
by
  have h1 : 0 < (1 : ℝ) := by norm_num
  have h2 : 0 < (2 : ℝ) := by norm_num
  have hf1_pos : 0 < f 1 := hf 1 h1
  have hf2_pos : 0 < f 2 := hf 2 h2

  -- Evaluate the functional equation at x = 1 and y = 2
  have heq12 := heq 1 2 h1 h2
  have h_one_div_one : (1 : ℝ) / 1 = 1 := by norm_num
  rw [h_one_div_one] at heq12

  -- Deduce specific relations from lemma7
  have hf2_eq : f 2 = (1 : ℝ) / 2 + f 1 - 1 := lemma7_f_eq_inv_add_C f hf heq 2 h2
  have h_arg2 : 1 + f 2 = f 1 + (1 : ℝ) / 2 := by linarith [hf2_eq]

  -- Expand the LHS arguments of evaluated functional equation
  have h_arg1_pos : 0 < 2 * f 1 + 1 := by linarith [hf1_pos]
  have hf_arg1 : f (2 * f 1 + 1) = (1 : ℝ) / (2 * f 1 + 1) + f 1 - 1 :=
    lemma7_f_eq_inv_add_C f hf heq (2 * f 1 + 1) h_arg1_pos

  -- Expand the RHS arguments of evaluated functional equation
  have h_arg2_pos : 0 < 1 + f 2 := by linarith [hf2_pos]
  have hf_arg2 : f (1 + f 2) = (1 : ℝ) / (1 + f 2) + f 1 - 1 :=
    lemma7_f_eq_inv_add_C f hf heq (1 + f 2) h_arg2_pos

  -- Substitute the expanded arguments back into the evaluated functional equation
  rw [hf_arg1, hf_arg2] at heq12
  rw [h_arg2] at heq12

  -- Simplify using our purely algebraic fractional auxiliary lemma
  have h_frac_eq : 2 * ((1 : ℝ) / (2 * f 1 + 1)) = (1 : ℝ) / (f 1 + (1 : ℝ) / 2) :=
    lemma8_aux_frac_eq (f 1) hf1_pos

  have h_heq12_exp : 2 * ((1 : ℝ) / (2 * f 1 + 1)) + 2 * (f 1) - 2 = (1 : ℝ) / (f 1 + (1 : ℝ) / 2) + f 1 - 1 := by
    calc 2 * ((1 : ℝ) / (2 * f 1 + 1)) + 2 * (f 1) - 2
      _ = 2 * ((1 : ℝ) / (2 * f 1 + 1) + f 1 - 1) := by ring
      _ = (1 : ℝ) / (f 1 + (1 : ℝ) / 2) + f 1 - 1 := heq12

  rw [h_frac_eq] at h_heq12_exp

  -- The simplified purely linear system trivially resolves f 1 = 1
  linarith [h_heq12_exp]

theorem lemma9_f_eq_inv (f : ℝ → ℝ) (hf : PosFun f) (heq : satisfies_eq f) :
    ∀ x > 0, f x = (1 : ℝ) / x :=
by
  intro x hx
  rw [lemma7_f_eq_inv_add_C f hf heq x hx]
  rw [lemma8_f1_eq_1 f hf heq]
  ring

theorem PBAdvanced011_aux1 (f : {x : ℝ // 0 < x} → {x : ℝ // 0 < x})
  (h : ∀ x y, y * f (y * f x + 1) = f (1 / x + f y)) : f = fun x ↦ 1 / x :=
by
  -- `ext` automatically goes through the subtype equality mapping the goal to real numbers directly
  ext x
  let real_f : ℝ → ℝ := fun a => if ha : 0 < a then (f ⟨a, ha⟩).val else 1

  have hpos : PosFun real_f := by
    intro a ha
    have heq_a : real_f a = if ha' : 0 < a then (f ⟨a, ha'⟩).val else 1 := rfl
    rw [heq_a, dif_pos ha]
    exact (f ⟨a, ha⟩).property

  have heq : satisfies_eq real_f := by
    intro a b ha hb
    have heq_a : real_f a = if ha' : 0 < a then (f ⟨a, ha'⟩).val else 1 := rfl
    rw [heq_a, dif_pos ha]

    have heq_b : real_f b = if hb' : 0 < b then (f ⟨b, hb'⟩).val else 1 := rfl
    rw [heq_b, dif_pos hb]

    have h1 : 0 < b * (f ⟨a, ha⟩).val + 1 := by
      have hf := (f ⟨a, ha⟩).property
      positivity

    have heq_inner : real_f (b * (f ⟨a, ha⟩).val + 1) = if h1' : 0 < b * (f ⟨a, ha⟩).val + 1 then (f ⟨b * (f ⟨a, ha⟩).val + 1, h1'⟩).val else 1 := rfl
    rw [heq_inner, dif_pos h1]

    have h2 : 0 < (1 : ℝ) / a + (f ⟨b, hb⟩).val := by
      have hf := (f ⟨b, hb⟩).property
      positivity

    have heq_outer : real_f ((1 : ℝ) / a + (f ⟨b, hb⟩).val) = if h2' : 0 < (1 : ℝ) / a + (f ⟨b, hb⟩).val then (f ⟨(1 : ℝ) / a + (f ⟨b, hb⟩).val, h2'⟩).val else 1 := rfl
    rw [heq_outer, dif_pos h2]

    exact congr_arg Subtype.val (h ⟨a, ha⟩ ⟨b, hb⟩)

  have h_val : (f x).val = (1 : ℝ) / x.val := by
    have h1 := lemma9_f_eq_inv real_f hpos heq x.val x.property
    have h2 : real_f x.val = (f x).val := by
      have heq_x : real_f x.val = if hx' : 0 < x.val then (f ⟨x.val, hx'⟩).val else 1 := rfl
      rw [heq_x, dif_pos x.property]
    rwa [h2] at h1

  -- Close the goal with the proven property mapped exactly to underlying reals definitionally.
  exact h_val

theorem PBAdvanced011_aux2_lemma (x y : {x : ℝ // 0 < x}) :
  y * (1 / (y * (1 / x) + 1)) = 1 / (1 / x + 1 / y) :=
by
  -- Destruct the subtypes to extract the underlying real numbers and their positivity proofs
  obtain ⟨x_val, hx⟩ := x
  obtain ⟨y_val, hy⟩ := y

  -- Push the equality from `{x : ℝ // 0 < x}` down to `ℝ`
  apply Subtype.ext

  -- The definitional equality allows us to rewrite the goal explicitly in terms of real numbers
  change y_val * ((1 : ℝ) / (y_val * ((1 : ℝ) / x_val) + 1)) = (1 : ℝ) / ((1 : ℝ) / x_val + (1 : ℝ) / y_val)

  -- Prove that all denominators involved are non-zero (since `x_val` and `y_val` are strictly positive)
  have hx_ne : x_val ≠ 0 := ne_of_gt hx
  have hy_ne : y_val ≠ 0 := ne_of_gt hy
  have hd1 : y_val * ((1 : ℝ) / x_val) + 1 ≠ 0 := by positivity
  have hd2 : (1 : ℝ) / x_val + (1 : ℝ) / y_val ≠ 0 := by positivity

  -- Now that we are in a proper field (`ℝ`) and have handled zeroes, `field_simp` behaves perfectly
  -- and completely closes the algebraic goal.
  field_simp

theorem PBAdvanced011_aux2 (f : {x : ℝ // 0 < x} → {x : ℝ // 0 < x})
  (h : f = fun x ↦ 1 / x) : ∀ x y, y * f (y * f x + 1) = f (1 / x + f y) :=
by
  subst h
  intros x y
  exact PBAdvanced011_aux2_lemma x y

theorem PBAdvanced011 : {f : {x : ℝ // 0 < x} → {x : ℝ // 0 < x} | ∀ x y, y * f (y * f x + 1) = f (1 / x + f y)}
      = {fun x ↦ 1 / x} :=
by
  ext f
  constructor
  · intro h
    exact PBAdvanced011_aux1 f h
  · intro h
    exact PBAdvanced011_aux2 f h
