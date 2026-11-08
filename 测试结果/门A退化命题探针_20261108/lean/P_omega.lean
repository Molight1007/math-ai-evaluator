import Mathlib.Tactic
set_option autoImplicit false
set_option maxHeartbeats 100000 in
example (a b : ℝ) : 2 * a * b ^ 3 ≤ a ^ 2 + b ^ 4 ∧ (2 * a * b ^ 3 = a ^ 2 + b ^ 4 ↔ a = b ^ 2) := by omega
set_option maxHeartbeats 100000 in
example (x y z : ℝ) : x * y ^ 3 + y * z ^ 3 + z * x ^ 3 ≤ (x ^ 2 + y ^ 2 + z ^ 2 + x ^ 4 + y ^ 4 + z ^ 4) / 2 := by omega
set_option maxHeartbeats 100000 in
example (x y z : ℝ) (h : x ^ 2 + y ^ 2 + z ^ 2 = 3) : x ^ 4 + y ^ 4 + z ^ 4 ≥ 3 ∧ (x ^ 4 + y ^ 4 + z ^ 4 = 3 ↔ x ^ 2 = 1 ∧ y ^ 2 = 1 ∧ z ^ 2 = 1) := by omega
set_option maxHeartbeats 100000 in
example (X : Set ℤ) (hX : ∀ k l : ℕ, 0 < k → 0 < l → (2^k - 2^l) ∈ X) (hRich : ∀ (n : ℕ) (x : Fin (n+1) → ℤ), (∀ i, x i ∈ X) → ∀ r : ℤ, (∑ i : Fin (n+1), x i * r ^ (i : ℕ)) = 0 → r ∈ X) : 0 ∈ X := by omega
set_option maxHeartbeats 100000 in
example (X : Set ℤ) (h0 : 0 ∈ X) (h2 : 2 ∈ X) (hRich : ∀ (n : ℕ) (x : Fin (n+1) → ℤ), (∀ i, x i ∈ X) → ∀ r : ℤ, (∑ i : Fin (n+1), x i * r ^ (i : ℕ)) = 0 → r ∈ X) : -1 ∈ X := by omega
set_option maxHeartbeats 100000 in
example (X : Set ℤ) (hNeg1 : -1 ∈ X) (hRich : ∀ (n : ℕ) (x : Fin (n+1) → ℤ), (∀ i, x i ∈ X) → ∀ r : ℤ, (∑ i : Fin (n+1), x i * r ^ (i : ℕ)) = 0 → r ∈ X) : ∀ r : ℤ, r ∈ X := by omega
set_option maxHeartbeats 100000 in
example (X : Set ℤ) (h : ∀ r : ℤ, r ∈ X) : X = (Set.univ : Set ℤ) := by omega
set_option maxHeartbeats 100000 in
example (p q r s : ℝ) (hp : p ≠ 0) : (∃ y1 y2 y3 : ℝ, y1 ≠ y2 ∧ y2 ≠ y3 ∧ y1 ≠ y3 ∧ p*y1^3+q*y1^2+r*y1+s=0 ∧ p*y2^3+q*y2^2+r*y2+s=0 ∧ p*y3^3+q*y3^2+r*y3+s=0) ↔ (3*p*r-q^2 < 0 ∧ ∃ y1 y2 : ℝ, y1 ≠ y2 ∧ 3*p*y1^2+2*q*y1+r=0 ∧ 3*p*y2^2+2*q*y2+r=0 ∧ (p*y1^3+q*y1^2+r*y1+s)*(p*y2^3+q*y2^2+r*y2+s) < 0) := by omega
set_option maxHeartbeats 100000 in
example (p q r s : ℝ) (hp : p ≠ 0) (h : ∃ y1 y2 y3 : ℝ, y1 ≠ y2 ∧ y2 ≠ y3 ∧ y1 ≠ y3 ∧ p*y1^3+q*y1^2+r*y1+s=0 ∧ p*y2^3+q*y2^2+r*y2+s=0 ∧ p*y3^3+q*y3^2+r*y3+s=0) : 16*p^2*(3*p*r-q^2+9*p*s) > 0 := by omega
set_option maxHeartbeats 100000 in
example (p q r s : ℝ) (hp : p ≠ 0) (h : ∃ y1 y2 y3 : ℝ, y1 ≠ y2 ∧ y2 ≠ y3 ∧ y1 ≠ y3 ∧ p*y1^3+q*y1^2+r*y1+s=0 ∧ p*y2^3+q*y2^2+r*y2+s=0 ∧ p*y3^3+q*y3^2+r*y3+s=0) : ∃ z1 z2 : ℝ, z1 ≠ z2 ∧ (p*z1^3+q*z1^2+r*z1+s)*(6*p*z1+2*q)=(3*p*z1^2+2*q*z1+r)^2 ∧ (p*z2^3+q*z2^2+r*z2+s)*(6*p*z2+2*q)=(3*p*z2^2+2*q*z2+r)^2 ∧ ∀ z : ℝ, (p*z^3+q*z^2+r*z+s)*(6*p*z+2*q)=(3*p*z^2+2*q*z+r)^2 → z=z1 ∨ z=z2 := by omega
set_option maxHeartbeats 100000 in
example (q r s : ℝ) : ¬(∃ y1 y2 y3 : ℝ, y1 ≠ y2 ∧ y2 ≠ y3 ∧ y1 ≠ y3 ∧ q*y1^2+r*y1+s=0 ∧ q*y2^2+r*y2+s=0 ∧ q*y3^2+r*y3+s=0) := by omega
set_option maxHeartbeats 100000 in
example (x y z : ℝ) (hx : x ≠ 0) (hy : y ≠ 0) (hz : z ≠ 0) (hxy : x ≠ y) (hyz : y ≠ z) (hxz : x ≠ z) (h1 : x^2 + y^2 + z^2 = 3) (h2 : x*y^3 + y*z^3 + z*x^3 = 3) : False := by omega
set_option maxHeartbeats 100000 in
example (x z : ℝ) (hx : x ≠ 0) (hz : z ≠ 0) (hxz : x ≠ z) (h1 : 2*x^2 + z^2 = 3) (h2 : x^4 + x*z^3 + z*x^3 = 3) : False := by omega
set_option maxHeartbeats 100000 in
example (x : ℝ) (hx : x ≠ 0) (h1 : 3*x^2 = 3) (h2 : 3*x^4 = 3) : False := by omega
set_option maxHeartbeats 100000 in
example (X : Set ℤ) (h2 : ∀ k l : ℕ, k > 0 → l > 0 → (2^k - 2^l) ∈ X) : 2 ∈ X := by omega
set_option maxHeartbeats 100000 in
example (X : Set ℤ) (h2 : ∀ k l : ℕ, k > 0 → l > 0 → (2^k - 2^l) ∈ X) : 0 ∈ X := by omega
set_option maxHeartbeats 100000 in
example (α β γ : ℝ) (h : α < β ∧ β < γ) : ∀ C : ℝ, ∃ (s : Finset ℝ), s.card = 2 ∧ ∀ z ∈ s, (1/(z-α) + 1/(z-β) + 1/(z-γ)) = C := by omega
set_option maxHeartbeats 100000 in
example (boris_targets : Finset (ℕ × ℕ)) (natasha_reds : ℕ → Finset (ℕ × ℕ)) : boris_targets.card = 4 → ∀ k, (natasha_reds k).card ≤ 2 * k → ∃ (blue_sofar : Finset (ℕ × ℕ)), blue_sofar.card ≥ 4 := by omega
set_option maxHeartbeats 100000 in
example (D : ℝ) (y : ℕ → ℝ) (hD : D > (777:ℝ)^2 / 2) (hy : ∀ k, 0 ≤ y k ∧ y k ≤ (777:ℝ)^2) (h : ∀ m n, m < n → (m + n) * |y n - y m| ≥ D) : False := by omega
set_option maxHeartbeats 100000 in
example (y : ℕ → ℝ) (h : ∀ k, y k = (777:ℝ)^2 * k / (2 * (k + 1))) : ∀ m n, m < n → (m + n) * |y n - y m| ≥ (777:ℝ)^2 / 2 := by omega
set_option maxHeartbeats 100000 in
example : ¬ ∃ (a b : ℤ), a ≠ b ∧ b^3 = a^3 ∧ ¬ ∃ (a b c : ℤ), a ≠ b ∧ b ≠ c ∧ a ≠ c ∧ c^3 = a^3 + b^3 := by omega
set_option maxHeartbeats 100000 in
example (y : ℕ → ℝ) (h : ∀ n, 0 ≤ y n ∧ y n ≤ 777^2) : ∃ (s : Set ℕ), Infinite s ∧ (∀ i ∈ s, 0 ≤ y i ∧ y i ≤ 777^2/2) ∨ (∀ i ∈ s, 777^2/2 < y i ∧ y i ≤ 777^2) := by omega
set_option maxHeartbeats 100000 in
example (D : ℝ) (y : ℕ → ℝ) (h1 : ∀ n, 0 ≤ y n ∧ y n ≤ 777^2) (h2 : ∀ m n, m < n → (m + n) * |y n - y m| ≥ D) : D ≤ 2 * 777^2 := by omega
set_option maxHeartbeats 100000 in
example (y : ℕ → ℝ) (h : ∀ n, if Odd n then y n = 777^2 else y n = 0) : ∀ m n, m < n → (m + n) * |y n - y m| ≥ 2 * 777^2 := by omega
set_option maxHeartbeats 100000 in
example (x : ℕ → ℝ) (h : ∀ n, if Odd n then x n = 777 else x n = 0) : ∀ n, 0 ≤ x n ∧ x n ≤ 777 ∧ ∀ m n, m < n → (m + n) * |x n^2 - x m^2| ≥ 2 * 777^2 := by omega
set_option maxHeartbeats 100000 in
example (q m : ℕ) (hq : Nat.Prime q) (h3 : q > 3) (hmq : m ≥ q) : ¬ (q ∣ 6 * Nat.factorial m - 1) := by omega
set_option maxHeartbeats 100000 in
example (P : Polynomial ℤ) (hP : P.Monic) (hdeg : P.natDegree ≥ 2) : ∃ (q : ℕ) (hq : Nat.Prime q), q > 3 ∧ Int.natAbs (P.eval (q : ℤ)) > q := by omega
set_option maxHeartbeats 100000 in
example (a : ℤ) (ha : a ≠ -1 ∧ a ≠ 0) : ∃ (q : ℕ) (hq : Nat.Prime q), q > 3 ∧ ¬ (q ∣ 6 * Nat.factorial (Int.natAbs (q + a)) - 1) := by omega
set_option maxHeartbeats 100000 in
example (q : ℕ) (hq : Nat.Prime q) (h3 : q > 3) : q ∣ 6 * Nat.factorial (q - 2) - 1 := by omega
set_option maxHeartbeats 100000 in
example (q : ℕ) (hq : Nat.Prime q) (h3 : q > 3) : q ∣ 6 * Nat.factorial q - 1 := by omega
set_option maxHeartbeats 100000 in
example (n : ℕ) (x : Fin n → ℝ) (h1 : ∀ i, |x i| ≤ 1) (h2 : (∑ i, x i)^2 + ∑ i, (x i)^2 = 20) (h3 : |∑ i, x i| < 1) : n ≥ 10 := by omega
set_option maxHeartbeats 100000 in
example (x : Fin 9 → ℝ) (h1 : ∀ i, |x i| ≤ 1) (h2 : (∑ i, x i)^2 + ∑ i, (x i)^2 = 20) (h3 : |∑ i, x i| < 1) : False := by omega
set_option maxHeartbeats 100000 in
example (D : ℝ) (x : ℕ → ℝ) (hD : ∀ m n, 0 < m → m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) (hx : ∀ i, 0 ≤ x i ∧ x i ≤ 777) (m n : ℕ) (hm : 0 < m) (hmn : m < n) : (m + n) * D ≤ 777 ^ 2 := by omega
set_option maxHeartbeats 100000 in
example (D : ℝ) (h : ∀ m n, 0 < m → m < n → (m + n) * D ≤ 777 ^ 2) : D ≤ 777 ^ 2 / 2 := by omega
set_option maxHeartbeats 100000 in
example (m n : ℕ) (hmn : 1 ≤ m ∧ m < n) : (m + n) * (777 ^ 2 * (n - m) / (m * n)) ≥ 777 ^ 2 / 2 := by omega
set_option maxHeartbeats 100000 in
example (ε : ℝ) (hε : 0 < ε) : ¬(∃ x : ℕ → ℝ, (∀ i, 0 ≤ x i ∧ x i ≤ 777) ∧ ∀ m n, 0 < m → m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ 777 ^ 2 / 2 + ε) := by omega
set_option maxHeartbeats 100000 in
example (ε : ℝ) (hε : 0 < ε) (x : ℕ → ℝ) (hx : ∀ i, 0 ≤ x i ∧ x i ≤ 777) (h : ∀ m n, 0 < m → m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ 777 ^ 2 / 2 + ε) : False := by omega
set_option maxHeartbeats 100000 in
example (D : ℝ) (x : ℕ → ℝ) (hD : 0 < D) (h : ∀ m n : ℕ, 0 < m → m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) : ∀ n : ℕ, 1 < n → |x n ^ 2 - x (n - 1) ^ 2| ≥ D / (2 * n - 1) := by omega
set_option maxHeartbeats 100000 in
example : ¬ Summable (fun k : ℕ => 1 / (2 * (k + 2) - 1)) := by omega
set_option maxHeartbeats 100000 in
example (D : ℝ) (x : ℕ → ℝ) (hD : 0 < D) (h : ∀ m n : ℕ, 0 < m → m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) (hb : ∀ n : ℕ, 0 ≤ x n ∧ x n ≤ 777) : False := by omega
set_option maxHeartbeats 100000 in
example (c : ℝ) (hc : 0 ≤ c ∧ c ≤ 777) : ∃ x : ℕ → ℝ, (∀ n : ℕ, 0 ≤ x n ∧ x n ≤ 777) ∧ ∀ m n : ℕ, 0 < m → m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ 0 := by omega
set_option maxHeartbeats 100000 in
example (x : ℕ → ℝ) (h : ∀ i, 0 ≤ x i ∧ x i ≤ 777) (m n : ℕ) : |x n ^ 2 - x m ^ 2| ≤ 777 ^ 2 := by omega
set_option maxHeartbeats 100000 in
example (D : ℝ) (hD : 0 < D) : ∃ m n : ℕ, m < n ∧ (m + n : ℝ) > 777 ^ 2 / D := by omega
set_option maxHeartbeats 100000 in
example (x : ℕ → ℝ) (h : ∀ i, 0 ≤ x i ∧ x i ≤ 777) (D : ℝ) (hcond : ∀ m n, m < n → (m + n) * |x n ^ 2 - x m ^ 2| ≥ D) : D ≤ 777 ^ 2 / 2 := by omega
set_option maxHeartbeats 100000 in
example (x : ℕ → ℝ) (hx : ∀ n, x n = 777 * (n % 2)) (m n : ℕ) (h : m < n) : (m + n) * |x n ^ 2 - x m ^ 2| ≥ 777 ^ 2 / 2 ∧ (∀ i, 0 ≤ x i ∧ x i ≤ 777) := by omega
set_option maxHeartbeats 100000 in
example (a : ℕ → ℕ) (h : ∀ p, a (a (a p)) = a (p + 1) + 1) : (∀ n, a n < a (n + 1)) ∧ (∀ n, n ≤ a n) := by omega
set_option maxHeartbeats 100000 in
example (a : ℕ → ℕ) (h : ∀ p, a (a (a p)) = a (p + 1) + 1) (h_mono : ∀ n, a n < a (n + 1)) (h_ge : ∀ n, n ≤ a n) : a 0 = 0 := by omega
set_option maxHeartbeats 100000 in
example (a : ℕ → ℕ) (h : ∀ p, a (a (a p)) = a (p + 1) + 1) (h_a0 : a 0 = 0) : a 1 = 1 := by omega
set_option maxHeartbeats 100000 in
example (a : ℕ → ℕ) (h : ∀ p, a (a (a p)) = a (p + 1) + 1) (h_a1 : a 1 = 1) (h_mono : ∀ n, a n < a (n + 1)) : ∀ n, 1 ≤ n → a n = n + 1 := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (h : ∀ n m, f (f n + f m) = n + m) : Function.Injective f := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (h : ∀ n m, f (f n + f m) = n + m) : Function.Surjective f := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (h : ∀ n m, f (f n + f m) = n + m) (surj : Function.Surjective f) : ∃ a, f a = 1 ∧ ∀ n, f (f n + 1) = n + a := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (a : ℕ+) (ha : ∀ n, f (f n + 1) = n + a) : f 2 = 2 * a ∧ f (f 1 + 1) = 1 + a := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (inj : Function.Injective f) (a : ℕ+) (h2 : f 2 = 2 * a) : a = 1 := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (h : ∀ n m, f (f n + f m) = n + m) (inj : Function.Injective f) (a1 : f 1 = 1) : ∀ n, f (n + 1) = f n + 1 := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (rec : ∀ n, f (n + 1) = f n + 1) (base : f 1 = 1) : ∀ n, f n = n := by omega
set_option maxHeartbeats 100000 in
example (ζ : ℂ) (n : ℕ) (h : ζ ^ n = 1) : (∃ (a b : ℤ), ζ ^ 2 + a * ζ + b = 0) ↔ (minpoly ℚ ζ).natDegree = 2 := by omega
set_option maxHeartbeats 100000 in
example (n : ℕ) (h : n ∈ ({3, 4, 6} : Set ℕ)) (ζ : ℂ) (hprim : IsPrimitiveRoot ζ n) : ∃ (a b : ℤ), ζ ^ 2 + a * ζ + b = 0 := by omega
set_option maxHeartbeats 100000 in
example (x : Fin 10 → ℕ) (h : ∀ i, x i = Nat.gcd (x (i - 1)) (x (i + 1)) + 1) : ∀ i, x i ≥ 3 := by omega
set_option maxHeartbeats 100000 in
example (x : Fin 10 → ℕ) (h : ∀ i, x i = Nat.gcd (x (i - 1)) (x (i + 1)) + 1) (h3 : ∃ i, x i = 3) : ∀ i, x i = 3 := by omega
set_option maxHeartbeats 100000 in
example (x : Fin 10 → ℕ) (h : ∀ i, x i = Nat.gcd (x (i - 1)) (x (i + 1)) + 1) (h3 : ¬ ∃ i, x i = 3) : ∀ i, Even (x i - 1) := by omega
set_option maxHeartbeats 100000 in
example (x : Fin 10 → ℕ) (h : ∀ i, x i = Nat.gcd (x (i - 1)) (x (i + 1)) + 1) (hodd : ∀ i, Even (x i - 1)) (h5 : ¬ ∃ i, x i = 3) : ∀ i, x i = 5 := by omega
set_option maxHeartbeats 100000 in
example (n : ℕ) : n ∣ 2 ^ n + 2 → n % 2 = 0 := by omega
set_option maxHeartbeats 100000 in
example (m : ℕ) : (2 * m) ∣ 2 ^ (2 * m) + 2 ↔ m ∣ 2 ^ (2 * m - 1) + 1 := by omega
set_option maxHeartbeats 100000 in
example (m : ℕ) (h : m ∣ 2 ^ (2 * m - 1) + 1) : (5 * m) ∣ 2 ^ (10 * m - 1) + 1 := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (h : ∀ n m : ℕ+, f (f n + f m) = n + m) : Function.Injective f := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (h : ∀ n m : ℕ+, f (f n + f m) = n + m) : Function.Surjective f := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (h : ∀ n m : ℕ+, f (f n + f m) = n + m) (hf : Function.Injective f) : f 1 = 1 := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (h : ∀ n m : ℕ+, f (f n + f m) = n + m) (hf : Function.Injective f) (h1 : f 1 = 1) : ∀ n : ℕ+, f (n + 1) = f n + 1 := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (h3 : ∀ n : ℕ+, f (n + 1) = f n + 1) (h1 : f 1 = 1) : ∀ n : ℕ+, f n = n := by omega
set_option maxHeartbeats 100000 in
example (V : Type) [Fintype V] (c : V → V → Fin 3) (h : ∀ u v w, u ≠ v ∧ v ≠ w ∧ u ≠ w → ¬ (c u v = c v w ∧ c v w = c u w)) : ∀ u v w, u ≠ v ∧ v ≠ w ∧ u ≠ w → ¬ (c u v = c v w ∧ c v w = c u w) := by omega
set_option maxHeartbeats 100000 in
example (n : ℕ) (h : ∀ (c : Fin n → Fin n → Fin 3), ∃ u v w, u ≠ v ∧ v ≠ w ∧ u ≠ w ∧ c u v = c v w ∧ c v w = c u w) : n ≤ 5 := by omega
set_option maxHeartbeats 100000 in
example : ¬ (∃ (c : Fin 6 → Fin 6 → Fin 3), (∀ u v, u ≠ v → c u v = c v u) ∧ (∀ u v w, u ≠ v ∧ v ≠ w ∧ u ≠ w → ¬ (c u v = c v w ∧ c v w = c u w)) ∧ (∀ v, ¬ (∃ a b d, a ≠ b ∧ b ≠ d ∧ a ≠ d ∧ c v a = c v b ∧ c v b = c v d ∧ c v a = 0 ∧ c v a = 1 ∧ c v a = 2))) := by omega
set_option maxHeartbeats 100000 in
example (x : ℕ → ℕ) (i : ℕ) (h : x i = Nat.gcd (x (i-1)) (x (i+1)) + 1) : x i ≥ 2 := by omega
set_option maxHeartbeats 100000 in
example (x : ℕ → ℕ) (h : ∀ i, x i = Nat.gcd (x (i-1)) (x (i+1)) + 1) (h' : ∀ i, x i ≥ 3) : False := by omega
set_option maxHeartbeats 100000 in
example (a b c : ℕ) (h : a = Nat.gcd b c + 1) : (a - 1) ∣ b ∧ (a - 1) ∣ c := by omega
set_option maxHeartbeats 100000 in
example (x : ℕ → ℕ) (h : ∀ i, (x i - 1) ∣ x (i-1) ∧ (x i - 1) ∣ x (i+1)) (h' : ∃ i, x i = 2) : ∀ i, Even (x i) := by omega
set_option maxHeartbeats 100000 in
example (n : ℕ) (h : n ∣ 2 ^ n + 2) (h100 : 100 ≤ n) : Even n := by omega
set_option maxHeartbeats 100000 in
example (n m : ℕ) (hn : n = 2 * m) (hm : Odd m) : (n ∣ 2 ^ n + 2) ↔ (m ∣ 2 ^ (2 * m - 1) + 1) := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (hf : ∀ n m, f (f n + f m) = n + m) : Function.Injective f := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (hf : ∀ n m, f (f n + f m) = n + m) : Function.Surjective f := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (hf : ∀ n m, f (f n + f m) = n + m) : f 1 = 1 := by omega
set_option maxHeartbeats 100000 in
example (f : ℕ+ → ℕ+) (hf : ∀ n m, f (f n + f m) = n + m) (h1 : f 1 = 1) : ∀ k, f k = k := by omega
set_option maxHeartbeats 100000 in
example (n : ℕ) (h : (2^n + 2) % n = 0) : Even n := by omega
set_option maxHeartbeats 100000 in
example (m : ℕ) (h : (2^(2*m) + 2) % (2*m) = 0) : Odd m ∧ (2^(2*m - 1) + 1) % m = 0 := by omega
set_option maxHeartbeats 100000 in
example (m : ℕ) (ho : Odd m) (hd : (2^(2*m - 1) + 1) % m = 0) : m % 3 = 0 := by omega
set_option maxHeartbeats 100000 in
example (n : ℕ) (h_odd : Odd n) (h_gt1 : n > 1) : ¬ (n ∣ 2 ^ n + 2) := by omega
