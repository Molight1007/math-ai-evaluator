import Mathlib
open Relation
inductive Color
| red
| white
| blue
deriving DecidableEq
def Coloring := Fin 101 → Color
def Coloring.Valid (coloring : Coloring) :=
  ∀ i : Fin 101, coloring i ≠ coloring (i+1)
def Coloring.initial : Coloring := fun i ↦
  if i = 100 then .blue else if i % 2 = 1 then .red else .white
def Coloring.final : Coloring := fun i ↦
  if i = 100 then .blue else if i % 2 = 1 then .white else .red
def Coloring.Step (c1 c2 : Coloring) : Prop :=
  ∃ i : Fin 101, c2.Valid ∧ ∀ j, j ≠ i ↔ c1 j = c2 j

def diff : Color → Color → ℤ
| .red, .white => 1
| .white, .red => -1
| .white, .blue => 1
| .blue, .white => -1
| .blue, .red => 1
| .red, .blue => -1
| _, _ => 0

def weight (c : Coloring) : ℤ :=
  ∑ i : Fin 101, diff (c i) (c (i + 1))

set_option maxRecDepth 1000000
set_option maxHeartbeats 1000000

set_option maxRecDepth 1048576
set_option maxHeartbeats 10000000

theorem weight_of_reflTransGen {c : Coloring} (h : ReflTransGen Coloring.Step .initial c) :
  weight c = weight .initial :=
by
  have weight_step : ∀ {c1 c2 : Coloring}, Coloring.Step c1 c2 → c1.Valid → c2.Valid ∧ weight c2 = weight c1 := by
    intro c1 c2 h_step ih_valid

    -- Define missing modulo logic instances for the steps using `decide` for automated bounded evaluation.
    have fin_101_sub_add_cancel : ∀ i : Fin 101, i - 1 + 1 = i := by decide
    have fin_101_add_sub_cancel : ∀ i : Fin 101, i + 1 - 1 = i := by decide
    have fin_101_sub_ne : ∀ i : Fin 101, i - 1 ≠ i := by decide
    have fin_101_add_ne : ∀ i : Fin 101, i + 1 ≠ i := by decide
    have fin_101_j_plus_one_ne_i : ∀ i j : Fin 101, j ≠ i - 1 → j + 1 ≠ i := by
      intro i j hneq heq
      apply hneq
      rw [← fin_101_add_sub_cancel j, heq]

    obtain ⟨i, h_c2_valid, h_eq⟩ := h_step

    have hc2_prev : c2 (i - 1) = c1 (i - 1) := ((h_eq (i - 1)).mp (fin_101_sub_ne i)).symm
    have hc2_next : c2 (i + 1) = c1 (i + 1) := ((h_eq (i + 1)).mp (fin_101_add_ne i)).symm

    have h_x_neq_y : c1 i ≠ c2 i := fun hxy =>
      have hi : i ≠ i := (h_eq i).mpr hxy
      hi rfl

    have h_x_neq_L : c1 i ≠ c1 (i - 1) := fun h_L =>
      have h1 : c1 (i - 1) = c1 i := h_L.symm
      have h2 : c1 (i - 1) = c1 (i - 1 + 1) := by
        have h_idx : i - 1 + 1 = i := fin_101_sub_add_cancel i
        rw [h_idx]
        exact h1
      ih_valid (i - 1) h2

    have h_x_neq_R : c1 i ≠ c1 (i + 1) := ih_valid i

    have h_y_neq_L : c2 i ≠ c1 (i - 1) := fun h_yL =>
      have h1 : c2 (i - 1) = c2 i := by
        calc c2 (i - 1) = c1 (i - 1) := hc2_prev
          _ = c2 i := h_yL.symm
      have h2 : c2 (i - 1) = c2 (i - 1 + 1) := by
        have h_idx : i - 1 + 1 = i := fin_101_sub_add_cancel i
        rw [h_idx]
        exact h1
      h_c2_valid (i - 1) h2

    have h_y_neq_R : c2 i ≠ c1 (i + 1) := fun h_yR =>
      have h1 : c2 i = c2 (i + 1) := by
        calc c2 i = c1 (i + 1) := h_yR
          _ = c2 (i + 1) := hc2_next.symm
      h_c2_valid i h1

    have helper : ∀ (L R x y : Color), x ≠ y → x ≠ L → x ≠ R → y ≠ L → y ≠ R → L = R := by
      intro L R x y
      cases L <;> cases R <;> cases x <;> cases y <;> decide

    have h_L_eq_R : c1 (i - 1) = c1 (i + 1) :=
      helper (c1 (i - 1)) (c1 (i + 1)) (c1 i) (c2 i)
        h_x_neq_y h_x_neq_L h_x_neq_R h_y_neq_L h_y_neq_R

    have diff_anti : ∀ a b : Color, diff a b + diff b a = 0 := by
      intro a b
      cases a <;> cases b <;> decide

    let F1 : Fin 101 → ℤ := fun j => diff (c1 j) (c1 (j+1))
    let F2 : Fin 101 → ℤ := fun j => diff (c2 j) (c2 (j+1))

    have h_F1_sum : F1 (i - 1) + F1 i = 0 := by
      change diff (c1 (i - 1)) (c1 (i - 1 + 1)) + diff (c1 i) (c1 (i + 1)) = 0
      have h_idx : i - 1 + 1 = i := fin_101_sub_add_cancel i
      rw [h_idx]
      have : c1 (i + 1) = c1 (i - 1) := h_L_eq_R.symm
      rw [this]
      exact diff_anti (c1 (i - 1)) (c1 i)

    have h_F2_sum : F2 (i - 1) + F2 i = 0 := by
      change diff (c2 (i - 1)) (c2 (i - 1 + 1)) + diff (c2 i) (c2 (i + 1)) = 0
      have h_idx : i - 1 + 1 = i := fin_101_sub_add_cancel i
      rw [h_idx]
      have : c2 (i + 1) = c2 (i - 1) := by
        rw [hc2_next, hc2_prev]
        exact h_L_eq_R.symm
      rw [this]
      exact diff_anti (c2 (i - 1)) (c2 i)

    let G : Fin 101 → ℤ := fun j => if j = i then F2 (i - 1) - F1 (i - 1) else (0 : ℤ)

    -- Safely swapping logic by utilizing 'rw' on equality hypotheses prevents 'i' from disappearing.
    have hF : ∀ j, F1 j = F2 j + G j - G (j + 1) := by
      intro j
      by_cases hj1 : j = i
      · rw [hj1]
        have H1 : G i = F2 (i - 1) - F1 (i - 1) := if_pos rfl
        have H2 : G (i + 1) = 0 := if_neg (fin_101_add_ne i)
        rw [H1, H2]
        have eq1 : F2 i + F2 (i - 1) = 0 := by
          calc F2 i + F2 (i - 1) = F2 (i - 1) + F2 i := add_comm _ _
            _ = 0 := h_F2_sum
        have eq2 : F1 i + F1 (i - 1) = 0 := by
          calc F1 i + F1 (i - 1) = F1 (i - 1) + F1 i := add_comm _ _
            _ = 0 := h_F1_sum
        -- Over ℤ bounds, ring functions perfectly without fail.
        calc F1 i
          _ = F1 i + F1 (i - 1) - F1 (i - 1) := by ring
          _ = 0 - F1 (i - 1) := by rw [eq2]
          _ = F2 i + F2 (i - 1) - F1 (i - 1) := by rw [← eq1]
          _ = F2 i + (F2 (i - 1) - F1 (i - 1)) - 0 := by ring
      · by_cases hj2 : j = i - 1
        · rw [hj2]
          have hi1 : i - 1 ≠ i := fin_101_sub_ne i
          have H1 : G (i - 1) = 0 := if_neg hi1
          have H2 : G (i - 1 + 1) = F2 (i - 1) - F1 (i - 1) := if_pos (fin_101_sub_add_cancel i)
          rw [H1, H2]
          ring
        · have hj3 : j + 1 ≠ i := fin_101_j_plus_one_ne_i i j hj2
          have H1 : G j = 0 := if_neg hj1
          have H2 : G (j + 1) = 0 := if_neg hj3
          rw [H1, H2]
          have hA : c1 j = c2 j := (h_eq j).mp hj1
          have hB : c1 (j + 1) = c2 (j + 1) := (h_eq (j + 1)).mp hj3
          have hC : F1 j = F2 j := by
            change diff (c1 j) (c1 (j + 1)) = diff (c2 j) (c2 (j + 1))
            rw [hA, hB]
          rw [hC]
          ring

    let e : Fin 101 ≃ Fin 101 :=
      { toFun := fun j => j + 1
        invFun := fun j => j - 1
        left_inv := fin_101_add_sub_cancel
        right_inv := fin_101_sub_add_cancel }

    have h_sum1 : ∑ j, F1 j = ∑ j, (F2 j + G j - G (j + 1)) :=
      Finset.sum_congr rfl (fun j _ => hF j)

    have h_sum2 : ∑ j, (F2 j + G j - G (j + 1)) = ∑ j, F2 j + ∑ j, G j - ∑ j, G (j + 1) := by
      rw [Finset.sum_sub_distrib, Finset.sum_add_distrib]

    have h_sum3 : ∑ j : Fin 101, G (j + 1) = ∑ j : Fin 101, G j := by
      calc ∑ j : Fin 101, G (j + 1) = ∑ j : Fin 101, G (e j) := rfl
        _ = ∑ j : Fin 101, G j := Equiv.sum_comp e G

    have h_sum4 : weight c1 = weight c2 := by
      calc weight c1 = ∑ j, F1 j := rfl
        _ = ∑ j, (F2 j + G j - G (j + 1)) := h_sum1
        _ = ∑ j, F2 j + ∑ j, G j - ∑ j, G (j + 1) := h_sum2
        _ = ∑ j, F2 j + ∑ j, G j - ∑ j, G j := by rw [h_sum3]
        _ = ∑ j, F2 j := by ring
        _ = weight c2 := rfl

    exact ⟨h_c2_valid, h_sum4.symm⟩

  have H : c.Valid ∧ weight c = weight .initial := by
    induction h with
    | refl =>
      have h_valid : Coloring.initial.Valid := by
        dsimp [Coloring.Valid, Coloring.initial]
        decide
      exact ⟨h_valid, rfl⟩
    | tail h_trans h_step ih =>
      obtain ⟨ih_valid, ih_weight⟩ := ih
      obtain ⟨step_valid, step_weight⟩ := weight_step h_step ih_valid
      exact ⟨step_valid, by rw [step_weight, ih_weight]⟩

  exact H.2

theorem weight_initial : weight .initial = -3 :=
by
  rfl

theorem weight_final : weight .final = 3 :=
by
  rfl

theorem PBBasic016 : ¬ ReflTransGen Coloring.Step .initial .final :=
by
  intro h
  have h1 := weight_of_reflTransGen h
  rw [weight_final, weight_initial] at h1
  omega
