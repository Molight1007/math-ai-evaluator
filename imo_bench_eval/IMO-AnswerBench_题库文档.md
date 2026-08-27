# IMO-AnswerBench 题库文档

> 数据集名称：**IMO-AnswerBench**
> 题目数量：**35 道**
> 内容：IMO 解答题（题目 + 参考答案），用于 AI 数学能力评测。
> 格式：题目正文使用 LaTeX 公式（`$...$` 内联 / `$$...$$` 或 `\[...\]` 块级），常见 Markdown 渲染器与 AI 均可直接读取渲染。
> 版权说明：题目源自公开 IMO 竞赛题，仅供评测与研究使用。

---

## 一、数据集说明

| 字段 | 含义 |
|------|------|
| `id` | 题目唯一标识，形如 `imo-bench-{domain}-{index}` |
| `domain` | 领域分类：`Algebra` / `Combinatorics` / `Geometry` / `Number theory` |
| `question` | 题目正文（LaTeX 公式） |
| `reference_answer` | 参考答案 |

**领域分布统计：**

| 领域 | 题数 |
|------|------|
| Algebra（代数） | 8 |
| Combinatorics（组合） | 7 |
| Geometry（几何） | 9 |
| Number theory（数论） | 11 |
| **合计** | **35** |

---

## 二、Algebra 代数（8 题）

### 1. imo-bench-algebra-003
**题目：**

Find all functions $g:\mathbb{R}\rightarrow\mathbb{R}$ which is not a linear or constant function and satisfies

$$
4g\left(x^{2}y+y^{2}z+z^{2}x\right)-(g(y)-g(x))(g(z)-g(y))(g(x)-g(z))=4g\left(xy^{2}+yz^{2}+zx^{2}\right)
$$

for all real numbers $x,y,z$.

**参考答案：** $g(x)=2x^{3}+c, g(x)=-2x^{3}+c$

---

### 2. imo-bench-algebra-053
**题目：**

Let $x, y, z$ be real numbers such that

$$
|x^2 + 2yz + 2(x + y + z) + 3|, |y^2 + 2zx + 2(x + y + z) + 3|, |z^2 + 2xy + 2(x + y + z) + 3|
$$

are three heights of a (non-degenerate) triangle. Find all possible values of $xy + yz + zx + 2(x + y + z)$.

**参考答案：** $(-\infty, -3) \cup (-3, \infty)$

---

### 3. imo-bench-algebra-060
**题目：**

Let $n, p, q$ be positive integers such that

$$
S = \frac{12 + n}{p} + \frac{13 - n}{q} < 1, \quad 1 \le n \le 12.
$$

Find the maximum possible value of $S$.

**参考答案：** $\frac{2617}{2618}$

---

### 4. imo-bench-algebra-064
**题目：**

Let $a, b, c, k$ be nonzero real numbers such that

$$
a - b = kbc, \quad b - c = kca, \quad c- a = kab.
$$

Find all possible values of $\frac{a}{c} + \frac{b}{a} + \frac{c}{b}$.

**参考答案：** $-3$

---

### 5. imo-bench-algebra-068
**题目：**

Find all positive integers $n$ satisfying the following condition.

**[Condition]** For any positive integer $d \le n$ and a polynomial $Q(x)$ with integer coefficients and of degree less than $d$, there exists a positive integer $k \le n$, and $k + 1$ distinct integers $a_1, \ldots, a_{k+1}$ such that

$$
Q(a_{k+1}) - \sum_{i=1}^k Q(a_i) = a_{k+1}^d - \sum_{i=1}^k a_i^d.
$$

**参考答案：** $2$

---

### 6. imo-bench-algebra-075
**题目：**

Find the largest possible positive integer $n$ such that there exist $n$ distinct positive real numbers $a_1, a_2, \dots, a_n$ satisfying

$$
3(a_i^2 + a_j^2) + 15a_i^2 a_j^2 \ge (4a_ia_j + 1)^2
$$

for any $1 \le i, j \le n$.

**参考答案：** $3$

---

### 7. imo-bench-algebra-084
**题目：**

Find all complex-coefficient polynomials $Q(x)$ that satisfy

$$
(x^2 + x - 2)Q(x - 3) = (x^2 - 11x + 28)Q(x)
$$

for all real numbers $x \in \mathbb{R}$.

**参考答案：** $Q(x)=c(x-1)^2(x-4)(x+2)$

---

### 8. imo-bench-algebra-094
**题目：**

A polynomial $P$ with integer coefficients is called a *geometric polynomial* if its degree is at least 2 and the set $\{P(k): k \in \mathbb{Z}\}$ contains an infinite geometric progression. Suppose that the leading coefficient and constant term of a geometric polynomial $Q$ are $64$ and $-486$, respectively. Find $Q(5)$.

**参考答案：** $33614$

---

## 三、Combinatorics 组合（7 题）

### 1. imo-bench-combinatorics-004
**题目：**

A player removes at least $95$ numbers from the set $\{1, 2, \ldots, 191\}$ according to the following rules:
(i) If $x$ is removed, so is $2x$;
(ii) If $x$ and $y$ are removed, then $x + y$ is also removed.

What is the maximum value of the sum of the remaining numbers?

**参考答案：** $9216$

---

### 2. imo-bench-combinatorics-022
**题目：**

Consider a regular hexagon with side length $100$ that is divided into equilateral triangles with side length $1$ by lines parallel to its sides. Find the number of regular hexagons all of whose vertices are among the vertices of those equilateral triangles.

**参考答案：** $25502500$

---

### 3. imo-bench-combinatorics-024
**题目：**

Let $S$ denote the set of all permutations of the numbers $1,2,\dots,2024$. For $\pi\in S$, let $\sigma(\pi)=1$ if $\pi$ is an even permutation and $\sigma(\pi)=-1$ if $\pi$ is an odd permutation. Also, let $v(\pi)$ denote the number of fixed points of $\pi$. Let $f(x)$ be an arbitrary polynomial such that $f(0)=1$. Compute the sum

$$
\sum_{\pi\in S}\frac{\sigma(\pi)}{v(\pi)+1}.
$$

**参考答案：** $-\frac{2024}{2025}$

---

### 4. imo-bench-combinatorics-027
**题目：**

Two rational numbers $\tfrac{m}{n}$ and $\tfrac{n}{m}$ are written on a blackboard, where $m$ and $n$ are relatively prime positive integers. At any point, Lin may pick two of the numbers $x$ and $y$ written on the board and write either their arithmetic mean $\tfrac{x+y}{2}$ or their harmonic mean $\tfrac{2xy}{x+y}$ on the board as well. For a pair $(m,n)$ such that Lin can write 1 on the board in finitely many steps, find the largest value of $m+n$ knowing that $m+n < 3000$.

**参考答案：** $2048$

---

### 5. imo-bench-combinatorics-032
**题目：**

A classroom contains 68 pairs of nonzero integers. Suppose that for each positive integer $k$ at most one of the pairs $(k, k)$ and $(-k, -k)$ is written on the classroom board. A student erases some of the 136 integers, subject to the condition that no two erased integers may add to 0. The student then scores one point for each of the 68 pairs in which at least one integer is erased. Additionally, the classroom has another broken whiteboard, and some integers might be invisible. Determine, with proof, the largest number $N$ of points that the student can guarantee to score regardless of which 68 pairs have been written on the board.

**参考答案：** $43$

---

### 6. imo-bench-combinatorics-040
**题目：**

A sequence of $15$ positive integers (not necessarily distinct) is called *kawaii* if it satisfies the following condition: for each positive integer $k\geq2$, if the number $k$ appears in the sequence then so does the number $k-1$, and moreover the first occurrence of $k-1$ comes before the last occurrence of $k$. Suppose there is a set $S$ of distinct integers, with $|S| = 16$. How many kawaii sequences are there?

**参考答案：** $1307674368000$

---

### 7. imo-bench-combinatorics-058
**题目：**

Consider an $n \times n$ chessboard consisting of $n^2$ unit squares, where $n \geqslant 2$ is an integer. A configuration of $n$ rooks on this board is called *balanced* if each row and each column contains exactly one rook. Find the largest positive integer $k$ such that for any balanced configuration of rooks, there exists a $k \times k$ square with no rook in any of its $k^2$ unit squares. Additionally, consider a $2n \times 2n$ go board, where we put go pieces on that board.

**参考答案：** $\lfloor\sqrt{n-1}\rfloor$

---

## 四、Geometry 几何（9 题）

### 1. imo-bench-geometry-008
**题目：**

Let $C, I$ be the circumcenter and the incenter of a right-angled triangle; $R, r$ be the radii of respective circles; $K$ be the reflection of the vertex of the right angle in $I$. Find $CK$ in terms of $R$ and $r$.

**参考答案：** $R-2r$

---

### 2. imo-bench-geometry-033
**题目：**

Let $XYZ$ be a triangle with $\angle X = 90^\circ, \angle Y = 60^\circ$ and $YZ = 1$. Draw outside of $\triangle XYZ$ three equilateral triangles $XYU, XZV$ and $YZW$. Determine the area of $\triangle UVW$.

**参考答案：** $\frac{9\sqrt{3}}{16}$

---

### 3. imo-bench-geometry-051
**题目：**

Let $\overline{CD}$ be a chord of a circle $\Omega$, and let $R$ be a point on the chord $\overline{CD}$. Circle $\Omega_1$ passes through $C$ and $R$ and is internally tangent to $\Omega$. Circle $\Omega_2$ passes through $D$ and $R$ and is internally tangent to $\Omega$. Circles $\Omega_1$ and $\Omega_2$ intersect at points $R$ and $S$. Line $RS$ intersects $\Omega$ at $U$ and $V$. Assume that $CR=4$, $RD=6$, $UV=11$, and $RS^2 = \frac{m}{n}$, where $m$ and $n$ are relatively prime positive integers. Find $m+n$.

**参考答案：** $29$

---

### 4. imo-bench-geometry-053
**题目：**

In $\triangle XYZ$ with $XY=XZ$, point $P$ lies strictly between $X$ and $Z$ on side $\overline{XZ}$, and point $Q$ lies strictly between $X$ and $Y$ on side $\overline{XY}$ such that $XQ=QP=PY=YZ$. The degree measure of $\angle XYZ$ is $\frac{m}{n}$, where $m$ and $n$ are relatively prime positive integers. Find $m+n$.

**参考答案：** $547$

---

### 5. imo-bench-geometry-067
**题目：**

Let $\triangle XYZ$ be an isosceles triangle with $\angle X=90^{\circ}$. There exists a point $Q$ inside $\triangle XYZ$ such that $\angle QXY=\angle QYZ=\angle QZX$ and $XQ=14$. Find the area of $\triangle XYZ$.

**参考答案：** $490$

---

### 6. imo-bench-geometry-068
**题目：**

In $\triangle XYZ$ with side lengths $XY=13$, $YZ=14$, and $ZX=15$, let $N$ be the midpoint of $\overline{YZ}$. Let $R$ be the point on the circumcircle of $\triangle XYZ$ such that $N$ is on $\overline{XR}$. There exists a unique point $S$ on segment $\overline{XN}$ such that $\angle RYS = \angle RZS$. Then $XS$ can be written as $\frac{a}{\sqrt{b}}$, where $a$ and $b$ are relatively prime positive integers. Find $a+b$.

**参考答案：** $247$

---

### 7. imo-bench-geometry-080
**题目：**

Let $Q$ be a point inside the square $WXYZ$ and $QW = 1$, $QX = \sqrt2$ and $QY = \sqrt3$. Determine the angle $\angle WQX$ in terms of degree.

**参考答案：** $105$

---

### 8. imo-bench-geometry-082
**题目：**

Let $F$ be the footpoint of the altitude from $Y$ in the triangle $XYZ$, where $XY=1$. The incircle of triangle $YZF$ coincides with the centroid of triangle $XYZ$. Find the lengths of $XZ$.

**参考答案：** $\frac{\sqrt{10}}{2}$

---

### 9. imo-bench-geometry-095
**题目：**

In quadrilateral $PQRS$, $\angle QPS=\angle PQR=110^{\circ}$, $\angle QRS=35^{\circ}$, $\angle RSP=105^{\circ}$, and $PR$ bisects $\angle QPS$. Find $\angle PQS$ in terms of degree.

**参考答案：** $40$

---

## 五、Number theory 数论（11 题）

### 1. imo-bench-number_theory-008
**题目：**

Does there exist a positive integer $n$ satisfying the following condition? If so, find the smallest such $n$.

**(Condition)** There exist infinitely many ordered $n$-tuples of positive rational numbers $(x_1, \dots, x_n)$ such that both $\sum_{i=1}^n i \cdot x_i$ and $\frac{1}{x_1 + \dots + x_n} + \frac{1}{x_2 + \dots + x_n} + \dots + \frac{1}{x_n}$ are positive integers.

**参考答案：** $3$

---

### 2. imo-bench-number_theory-022
**题目：**

For a given positive integer $n$, let $m$ be the exponent of 2 in the prime factorization of $n$. Define $f(n) = \frac{n}{2^m}$. Find all positive integers $v$ for which there exists a positive integer $u$ such that

**(Condition)** $f(u+v) - f(u), f(u+v+1) - f(u+1), \cdots, f(u+2v-1) - f(u+v-1)$ are all multiples of 4.

**参考答案：** $1,3,5$

---

### 3. imo-bench-number_theory-031
**题目：**

Let $k>l$ be given coprime positive integers greater than 1. Define a function $f: \mathbb{Z}\rightarrow \mathbb{Z}$ as follows: for $x$, $f(x)$ is the smallest value of $|a|+|b|$ among all integers $a,b$ satisfying $ka+lb = x$. An integer $x$ is called *nice* if $f(x)\geq \max (f(x-k),f(x+k),f(x-l),f(x+l))$. Denote by $F(k,l)$ the number of nice integers when both $k$ and $l$ are odd, and denote by $G(k,l)$ the number of nice integers when either $k$ or $l$ is even. Suppose that there exists polynomials $p(k,l)$ and $q(k,l)$ such that $F(k,l)=p(k,l)$ for all odd integers $k,l$ and $G(k,l)=q(k,l)$ whenever at least one of $k$ or $l$ is even. Evaluate $p(k,l)^2 + q(k,l)^2$.

**参考答案：** $5(l-1)^2$

---

### 4. imo-bench-number_theory-037
**题目：**

Let $A$ be the set of odd integers $a$ such that $|a|$ is not a perfect square.

Find all numbers that can be expressed as $x+y+z$ for $x, y, z \in A$ such that $xyz$ is a perfect square.

**参考答案：** All numbers of the form $4k+3$

---

### 5. imo-bench-number_theory-057
**题目：**

Let $b_m b_{m-1}\cdots b_0$ be the base-7 representation of a positive integer $n$ for some positive integer $m$. Let $a_i$ be the number obtained by removing the digit $b_i$ from the base-7 representation of $m$ (read in base 7). Find the number of $n$ that satisfy $n=\sum_{i=0}^{m-1}a_i$.

**参考答案：** $42$

---

### 6. imo-bench-number_theory-062
**题目：**

Let $g: \mathbb{Z}_{>0} \to \mathbb{Z}$ be a function satisfying the following conditions:

(i) $g(p) = p + 1$ for all prime numbers $p$,

(ii) $g(nm) + nm = ng(m) + mg(n)$ for all positive integers $n, m$.

Find all integers $1 \le n \le 4000$ satisfying $g(n) = 2n$.

**参考答案：** $4, 27, 3125$

---

### 7. imo-bench-number_theory-073
**题目：**

Let $q$ be an odd prime number. For an integer $i$ from 1 to $q-1$, let $n_i$ denote the number of divisors of $qi+1$ that are greater than or equal to $i$ and less than or equal to $q-1$. Find the sum of $n_1, n_2, \ldots, n_{q-1}$.

**参考答案：** $q-1$

---

### 8. imo-bench-number_theory-075
**题目：**

Find all monic polynomials $P(x)$ with integer coefficients for which

$$
\frac{6(|P(q)|!) - 1}{q}
$$

is an integer for every prime $q$ greater than 3.

**参考答案：** $P(x) = x - 4$

---

### 9. imo-bench-number_theory-077
**题目：**

Given a positive integer n, perform the following operation:

(i) Remove the last digit of n.

(ii) Add 3 times the removed digit to the remaining number.

For example, if $n = 1013$, the operation yields $101 + 9 = 110$. If $n = 2$, the operation yields $0 + 6 = 6$.

Starting with $260^{135}$, repeatedly apply this operation $2025$ times. What is the final resulting number?

**参考答案：** $8$

---

### 10. imo-bench-number_theory-093
**题目：**

Non-negative integers $a<b<c$ satisfy $c\le a+b$, and $3^a, 3^b, 3^c$ all have the same remainder when divided by $10000$. Find the minimum possible value of $a+b+c$.

**参考答案：** $3000$

---

### 11. imo-bench-number_theory-096
**题目：**

Let $a$ be a positive integer greater than or equal to $3$. A finite set $X$ of positive integers is said to be *clustered* if for any three elements $x, y, z$ chosen from $X$, at least one of $\gcd(x,y)$, $\gcd(y,z)$, or $\gcd(z,x)$ is not equal to $1$. Find the maximum possible value of $|X|$ for a clustered set $X \subset \mathbb{N}$ where the difference between the maximum and minimum elements of $X$ are less than or equal to $a$.

**参考答案：** $\lfloor \frac{a+2}{2}\rfloor +\lfloor \frac{a+2}{3}\rfloor -\lfloor \frac{a+2}{6}\rfloor$

---

## 附注

- 本文档由 `d:\挑战杯\测试结果\原始问题\` 下 6 个 `bank_IMO-AnswerBench_*.json` 汇总去重生成，共 **35** 题。
- 仓库中暂未发现 **IMO-ProofBench（证明题）** 的原始题库文件，故本文档仅含 AnswerBench 题目。若后续补充 ProofBench 原文，可在此文档追加相应章节。
- 配套机器可读版本：`IMO-AnswerBench_汇总.json`（纯 JSON，含 `id`/`domain`/`question`/`reference_answer` 结构化字段）。
