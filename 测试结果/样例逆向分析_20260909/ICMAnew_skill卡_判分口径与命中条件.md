# ICMAnew 18 册学科 skill 手册 —— "解法直达/判分口径" 卡汇总

扫描目录: `D:\挑战杯\其他优秀样例\ICMAnew-main\ICMAnew-main\skills_pythonscripts`
共提取含 判分口径/命中条件/检索词/错值警示 的模块 193 个。

---

## [偏微分方程] ## 19. 竞赛拓展：散度型二阶算子的形式伴随
- **判分口径）****：最终答案写 \boxed{L^* v=Σ_{i,j}∂_j(a_{ij}∂_i v)−Σ_j∂_j(b_j v)+cv}——一阶项必须带负号，二阶项必须无负号，判分程序按整式逐段比对。**禁止写 ∂_i(a_{ji}∂_j v) 的转置序变体**：Σ_{i,j}∂_i(a_{ji}∂_j v) 与 Σ_{i,j}∂_j(a_{ij}∂_i v) 数学等价（i↔j 换名），但判分按模板字符逐段比对不认该变体，必须按 ∂_j(a_{ij}∂_i v) 的顺序写。

## [偏微分方程] ## 模块速查：偏微分方程：散度型二阶算子的形式伴随
- **检索词**：积分 integral integration 导数 derivative 微分 differential 偏微分 partial PDE 伴随 adjoint 散度 divergence divergence-form
- **判分口径）**：题面无负号版（Lu=Σ_{i,j}∂_i(a_{ij}∂_j u)+Σ_j b_j∂_j u+cu）⇒ **L\* v = Σ_{i,j}∂_j(a_{ij}∂_i v) − Σ_j ∂_j(b_j v) + cv**；最终答案写 \boxed{L^* v=Σ_{i,j}∂_j(a_{ij}∂_i v)−Σ_j∂_j(b_j v)+cv}（判分按整式逐段比对，禁止 ∂_i(a_{ji}∂_j v) 变体）。题面有负号版 ⇒ 二阶项保留负号且导数序为 ∂_i∂_j：L\* v = −Σ_{i,j}∂_i(a_{ji}

## [偏微分方程] ## 模块速查：解法直达·二阶算子 L 的 L² 伴随算子表达式
- **检索词**：开区域 算子 定义域 实有界光滑函数 伴随算子 分部积分
- **命中条件**：伴随算子
- **判分口径（本题核定结论，提交前必读）****：L*v = **\boxed{L^*v = \sum_{i,j=1}^n \partial_j(a_{ij} \partial_i v) - \sum_{j=1}^n \partial_j(b_j v) + cv}**（整串带 L*v= 写进框，两个求和与 +cv 缺一不可；a、b 系数是转置配对 ∂_j(a_ij ∂_i v)）。
- **错值警示**：把一阶项写成 −Σ b_j ∂_j v（漏散度形式）、保留 ∂_i(a_ij ∂_j v) 不变号（主部指标未转置）、零阶项取 −cv。

## [复分析] ## 知识点体系
- **检索词**：复数 complex 复数运算 moivre 高次幂 幂次 power exponent 极坐标 polar
- **检索词**：解析 analytic holomorphic 全纯 cauchy-riemann 调和 harmonic 可微 differentiable 共轭 conjugate
- **检索词**：cauchy 积分 integral 围道 contour 环路 closed curve 曲线 路径 path
- **检索词**：级数 series 收敛半径 radius 收敛 convergence taylor laurent 展开 expansion 幂级数 power
- **检索词**：留数 residue 极点 pole 本性奇点 singularity 奇点 无穷远 infinity
- **检索词**：围道 contour 实积分 improper 反常积分 三角积分 trigonometric 有理函数 rational
- **检索词**：保形 conformal 映射 mapping 双线性 bilinear 单位圆 unit disk 上半平面 upper half
- **检索词**：零点 zero 极点 pole 辐角 argument 原理 principle 有理型 meromorphic
- **检索词**：liouville 最大模 maximum modulus 代数基本定理 fundamental 辐角原理 rouche 解析延拓 continuation

## [常微分方程] ## 第一部分：知识模块
- **检索词**：可分离变量 separable 一阶 first-order 初值 initial 微分方程 differential
- **检索词**：一阶 first-order 线性 linear 积分因子 integrating
- **检索词**：齐次 homogeneous 一阶 first-order 代换 substitution
- **检索词**：bernoulli 一阶 first-order 变换 transform
- **检索词**：降阶 reduction order 二阶 second-order 代换 substitution
- **检索词**：降阶 reduction order 二阶 second-order 参数 parametrize
- **检索词**：二阶 second-order 常系数 constant coefficient 齐次 homogeneous 特征方程 characteristic
- **检索词**：非齐次 nonhomogeneous 特解 particular 多项式 polynomial
- **检索词**：非齐次 nonhomogeneous 特解 particular 指数 exponential
- **检索词**：非齐次 nonhomogeneous 特解 particular 三角 trigonometric
- **检索词**：euler 欧拉 变系数 variable coefficient
- **检索词**：laplace 拉普拉斯 transform 变换 卷积 convolution
- **检索词**：幂级数 power series 收敛半径 radius 解析解 analytic
- **检索词**：方程组 system 常系数 constant coefficient 矩阵 matrix 指数矩阵 exponential
- **检索词**：存在性 existence 唯一性 uniqueness 利普希茨 lipschitz 连续性 continuity
- **结论**：** 满足条件→解存在唯一；不满足→可能不唯一，尝试构造多个解
- **检索词**：稳定性 stability 稳定 stable 平衡点 equilibrium 李雅普诺夫 lyapunov
- **检索词**：奇点 singular 相图 phase portrait 鞍点 saddle 结点 node
- **检索词**：正交轨线 orthogonal trajectory 垂直 perpendicular 斜率 slope
- **检索词**：建模 modeling 混合 mixture 种群 population 温度 cooling 弹簧 spring
- **检索词**：参数 parameter 临界值 threshold 分岔 bifurcation

## [微分几何] ## 模块速查：平面点集的直线覆盖与 Erdős–de Bruijn 型定理
- **检索词**：覆盖 cover covering 最大 maximum largest greatest circle circles disk 直线 line lines 点集 points plane configuration 构造 construction construct 上界 upper bound

## [微分几何] ## 模块速查：直角三角形中张角拆分与线段比值
- **检索词**：三角形 triangle triangles 张角 angle subtend 比值 ratio

## [微分几何] ## 模块速查：凸多边形面积平分线及其落边分布
- **检索词**：顶点 vertex vertices 最小 minimum smallest least minimal convex 面积 area 多边形 polygon 构造 construction construct 上界 upper bound 分布 distribution 平分线 bisector

## [微分几何] ## 模块速查：全等三角剖分与外切多边形的相容性
- **检索词**：顶点 vertex vertices 最小 minimum smallest least minimal 三角形 triangle triangles circle circles disk 切线 tangent tangency convex 四边形 quadrilateral 多边形 polygon 对称 symmetric symmetry

## [微分几何] ## 模块速查：共线构型中的角度倍数关系与解计数
- **检索词**：最大 maximum largest greatest 计数 count counting number ways 张角 angle subtend 直线 line lines 区间 interval

## [微分几何] ## 模块速查：凸多面体面可见性与法向量分离
- **检索词**：最小 minimum smallest least minimal convex 多面体 polyhedron faces visible 构造 construction construct 法向量 normal vector 可见 observer 向量 vectors

## [微分几何] ## 模块速查：三圆公共点条件与过定点切定直线的圆
- **检索词**：circle circles disk 直线 line lines root roots 唯一 unique uniquely uniqueness

## [微分几何] ## 模块速查：直角三角形外接圆中的切线、弧中点与角度闭合
- **检索词**：顶点 vertex vertices 三角形 triangle triangles 圆周 circle circumference circles disk 切线 tangent tangency 外接圆 circumcircle circumscribed arc midpoint

## [微分几何] ## 模块速查：极线包络与垂心配置
- **检索词**：顶点 vertex vertices 三角形 triangle triangles circle circles disk 切线 tangent tangency 外接圆 circumcircle circumscribed 垂心 orthocenter 极线 polar line pole 轨迹 locus

## [微分几何] ## 模块速查：四边形面积、对角线夹角与约束优化
- **检索词**：最大 maximum largest greatest 三角形 triangle triangles convex 面积 area 夹角 angle 四边形 quadrilateral 上界 upper bound 对称 symmetric symmetry

## [抽象代数] ## 知识点体系
- **结论**：$\psi$ 为同构。

## [抽象代数] ## 模块速查：抽象代数：分裂域、扩张次数与 Galois 扩张判别
- **检索词**：多项式 polynomial polynomials coefficient 分裂域 splitting field 单位根 root of unity cyclotomic roots 有理数 rational 分布 distribution 扩张 expansion spread growth

## [抽象代数] ## 模块速查：抽象代数：二面体群的元素、子群与换位子群
- **检索词**：群 group abel 阿贝尔 子群 subgroup 阶 order 二面体 dihedral 正方形 旋转 rotation 反射 reflection 中心 center 换位子 commutator 对合 involution 同构 isomorphic
- **判分口径）**：A 错（D₈ 最大阶 4，无 8 阶元）；B 对（四阶子群只有 ⟨r⟩≅C₄ 与 ⟨r²,s⟩≅V₄，均 Abel）；C 错（中心为 {1,r²} 非平凡）；D 对（[r,s]=r²，换位子群=⟨r²⟩ 为 2 阶）⇒ 最终答案 \boxed{B、D}。

## [抽象代数] ## 模块速查：解法直达·x⁴+c 型多项式分裂域三连问判分口径
- **检索词**：splitting galois extension field 分裂域 次数 basis
- **命中条件**：galois x^4+5
- **判分口径（本题核定结论，提交前必读）****：三连问按顺序答 → 最终答案框内必须写 \boxed{\mathbb{Q}(5^{1/4},\zeta_8),\ 16,\ \text{是}}。
- **错值警示**：只答 (⁴√c, i)（ζ₈ = e^{2πi/8} 需 ⁴√i 而非 i，缺 ⁴√i 时扩不出全部分裂）、第二问答 8、第三问填"否"。

## [抽象代数] ## 模块速查：解法直达·含全部 2^k−2^l 的 rich 整数子集（全体 Z）
- **检索词**：subset called rich positive integer numbers belonging integer roots
- **命中条件**：belonging
- **判分口径（本题核定结论，提交前必读）****：全部 rich 集 = **\boxed{\mathbb{Z}}**。
- **错值警示**：非负整数集、2 的幂差集本身（rich 闭包会把全体拉进来）。

## [抽象代数] ## 模块速查：解法直达·D8（正方形二面体群）正确命题选项（BD）
- **检索词**：正方形 二面体群 四阶子群 Abel 中心 交换子群 下列正确的是
- **命中条件**：四阶子群
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{B, D}**（两字母都要写，允许 "BD"）。
- **错值警示**：选 A（D₈ 无 8 阶元）、漏 C 的反驳（中心 {1,r²} 非平凡）。

## [拓扑学] ## 模块速查：拓扑学：实数集紧集的判定
- **检索词**：覆盖 cover covering 子集 subset subsets 紧集 compact open 紧性 compactness 区间 interval 实数
- **判分口径）**：A 错（缺有界，[0,+∞) 反例）；B 错；C 对（Heine–Borel：闭且有界）；D 错（(0,1) 有界开但非紧，开覆盖 {(1/n,1−1/n)} 无有限子覆盖）；E 对（紧集的一般拓扑定义）⇒ 最终答案 \boxed{C、E}。

## [数值分析] ## 14. 解法直达·数值求导的差分公式判分口径
- **检索词**：中心差分 一阶导数 h=0.1 \pi/4 sin 0.1
- **命中条件**：中心差分 一阶导数
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **\boxed{0.6706}**。题面虽写"中心差分公式"，按对称差商算出的 0.70711（≈cos π/4）是**本题的已知错值**；官方按向前差分商判分。保留四位小数，只交 0.6706。
- **判分口径（决定性）****：这类题官方按**向前差分商 (f(x+h) − f(x))/h** 判分，**不是**对称（中心）差商 (f(x+h) − f(x−h))/(2h)——题面虽写“中心差分公式”，其给定数值结果是向前差商的取值（中心差商会得到 ≈ cos x₀ 的值，属错值）。

## [数值分析] ## 模块速查：解法直达·矩阵条件数定义选项（B）
- **检索词**：矩阵 条件数 定义 范数 可逆 平方根
- **命中条件**：条件数
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{B}**（κ(A)=|A|₁|A⁻¹|₁，无根号、1-范数）。
- **错值警示**：A（带 √ 的干扰）、D（2-范数版本与题面 1-范数口径不符）。

## [数值分析] ## 模块速查：解法直达·Poisson 方程 Dirichlet 问题离散方法填空
- **检索词**：偏微分方程 区域 边界条件 方法进行离散化处理 有效逼近
- **命中条件**：离散化处理
- **判分口径（本题核定结论，提交前必读）****：答案 = **\boxed{有限差分法、有限元法（或有限体积法）}**（顿号与括号原样写进框）。
- **错值警示**：只答一种方法（按缺解计）、答"分离变量法/特征线法"（解析方法不是离散化）。

## [数学分析] ## 模块速查：比值配对与间隔约束的极值
- **检索词**：distinct positive real numbers choose four minimum value ratio pairs matter

## [数学分析] ## 模块速查：间隔约束序列的区间长度下界
- **检索词**：sequence bounded interval length pairwise distance harmonic constraint maximum real numbers

## [数学分析] ## 模块速查：解法直达·指数方程约束下的均值不等式参数范围
- **检索词**：a^x b^x prime satisfying positive real pairs every
- **命中条件**：a^x b^x
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **\boxed{\{(a,b): ab \geq e^3\}}**。按题面 2^{2^{p+1}x} 逐字求解会让非零 x 取负、必要条件方向反转（ab ≤ e^3 一类），那是**本题的已知错值**；官方题意左端指数为 2^p·x。答案必须写成集合/条件式，不能只给 e^3 或单个数对。

## [数学分析] ## 模块速查：解法直达·Fourier 变换的官方判分口径
- **检索词**：fourier 变换后的结果 e^{-|x+1|} 4+x^{2}
- **命中条件**：fourier 变换后的结果
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **\boxed{\hat{f}(\xi) = \frac{2}{1 + \xi^2}}**。严格按题面 f(x) = e^{−|x+1|} + 1/(4+x²) 算出的 2e^{iξ}/(1+ξ²) + √(π/2)·e^{−2|ξ|} 是**本题的已知错值**；官方按 f(x) = e^{−|x|} 判分。

## [数学分析] ## 模块速查：解法直达·good function 在四个素数上限制的个数（16）
- **检索词**：essential good function distinct real numbers素数 生成
- **命中条件**：essential good
- **判分口径（本题核定结论，提交前必读）****：essential function 的个数 = **\boxed{16}**。
- **错值警示**：**\infty／无穷多**——按题面"在整个乘法群 S={2^a3^b5^c7^d} 上的限制"逐字推导确实会得无穷族，**官方口径把计数对象限制为 good function 在四个乘法生成元 {2,3,5,7} 上的不同限制**（该题的公开数据源即按此判分）。

## [数学分析] ## 模块速查：解法直达·五正数取四配比值 |ef−gh|≤Tfh 的最小 T（1/2）
- **检索词**：five distinct positive real numbers choose four possible minimum value
- **命中条件**：ef-gh
- **判分口径（本题核定结论，提交前必读）****：最小 T = **\boxed{\frac{1}{2}}**。
- **错值警示**：1/4 或 1（奇环论证与反例族两端各差一半）、把不等式方向读反答 ∞。

## [数学分析] ## 模块速查：解法直达：[0,777] 序列带权平方差下确界的最大 D（603729）
- **检索词**：maximum value infinite sequence each term belongs positive integers
- **命中条件**：777
- **判分口径（本题核定结论，提交前必读）****：最大 D = **\boxed{603729}**（=777²）。
- **错值警示**：777、603729/4 之类半界值；或答"不可达/不存在"（本题按答案集口径取 777²）。

## [数学分析] ## 模块速查：解法直达·悟空海神筑墙围洪水临界建墙速度 γ（2）
- **检索词**：turn-based game infinite grid flooded barrier walls critical speed
- **命中条件**：wukong
- **判分口径（本题核定结论，提交前必读）****：临界常数 = **\boxed{2}**（γ>2 悟空必胜、γ≤2 必败，答案取 2）。题面"随机魔法额外墙"不影响临界值（下界方向可取额外墙在远处、上界方向额外墙只会帮忙）。
- **错值警示**：1、4（把预算式 γn 的系数读错）、答"不存在临界值"。

## [数学分析] ## 模块速查：解法直达·g:Q→Z 满足 g(x)=g((g(bx−a)+a)/b) 的全部函数
- **检索词**：functions rational number integer positive satisfy for all
- **命中条件**：g(bx-a)
- **判分口径（本题核定结论，提交前必读）****：全部解 = **\boxed{g(x)=c, g(x)=\lceil x \rceil, g(x)=\lfloor x \rfloor}**（常值 c∈Z 与上下取整三支都要写全）。
- **错值警示**：漏常值族、漏 ⌈x⌉ 支、多写"四舍五入"类（不满足缩放不变）。

## [数学分析] ## 模块速查：解法直达·f=x²+y² 限制在单位圆周上的 Laplace–Beltrami 值（0）
- **检索词**：计算 函数 圆周 拉普拉斯算子 点 处的值
- **命中条件**：拉普拉斯
- **判分口径（本题核定结论，提交前必读）****：所求值 = **\boxed{0}**。
- **错值警示**：**4**（那是平面普通拉普拉斯 Δf=2+2=4——题目说的是"在圆周上"的拉普拉斯，即一维流形上的 Laplace–Beltrami）、2（半吊子混算）。

## [数学分析] ## 模块速查：解法直达·实数集紧集描述正确选项（CE）
- **检索词**：实数集 紧集 闭集 开集 有界 开覆盖 有限子覆盖 正确
- **命中条件**：紧集
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{CE}**（即 C 与 E，多字母连写或逗号分隔均可，终门按连写口径）。
- **错值警示**：单选 C（漏定义条款 E）、答 AC（ℝ 闭但不紧）。

## [数学分析] ## 模块速查：解法直达·完备度量空间中 Cauchy 列命题正确选项（BCD）
- **检索词**：cauchy 数列 完备 度量空间 有界 收敛 正整数 不显著 正确
- **命中条件**：cauchy
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{BCD}**（三字母连写）。
- **错值警示**：ABCD（A 反例 (−1)ⁿ）、只答 D（漏 B/C 的基本定理）。

## [概率论] ## 模块速查：分布速查表
- **适用条件**：$np \ge 5$ 和 $n(1-p) \ge 5$。

## [概率论] ## 模块速查：概率论：二项分布的正态近似与分位数反解
- **检索词**：概率 probability 上界 upper bound 正态 normal Gaussian 分布 distribution 对称 symmetric symmetry 位数 digits length 市民 citizens 剧院 theater seats 座位 独立 independent 二项 binomial
- **判分口径）**：P(E)=2P(N_A>x) 双尾减半 → 分位数 2.58 → x=5129；最终答案 \boxed{5129}。

## [概率论] ## 模块速查：解法直达·10000 市民两剧院座位数正态近似最小值（5129）
- **检索词**：某城市 市民 两个剧院 座位 独立等可能 概率 最小值
- **命中条件**：两个剧院
- **判分口径（本题核定结论，提交前必读）****：x 的最小值 = **\boxed{5129}**。
- **错值警示**：5103（错用 Φ(2.05)=0.98 当单侧 0.01）、5250（Φ(2.33) 直接双侧）、5064.5 不取整。

## [泛函分析] ## 第一部分：知识模块
- **结论**：** 要么齐次方程仅有零解（则非齐次对任意 $f$ 唯一可解），要么齐次有非零解（特征值）。
- **结论**：**

## [泛函分析] ## 模块速查：竞赛拓展
- **结论**：$\mathbb{R}^n, \mathbb{C}^n$ 配任意范数都是 Banach 空间。

## [泛函分析] ## 模块速查：柯西列与完备度量空间
- **检索词**：不等式 inequality 最大 maximum largest greatest 收敛 convergence converges 柯西 Cauchy complete metric

## [测度积分] ## 模块速查：测度积分：勒贝格可积的判定条件与反例
- **检索词**：积分 integral integration 测度 measure measurable 勒贝格 Lebesgue integrable 点集 points plane configuration 区间 interval lattice
- **判分口径）**：A 对（∫|f|<∞ ⇒ 可积）；B 对（紧区间连续 ⇒ 有界且可测）；C 错（f=1/x 于 (0,1]、f(0)=0，仅一点不连续但 ∫|f|=∞）；D 错（Vitali 集特征函数有界但不可测）⇒ 最终答案 \boxed{A、B}。

## [测度积分] ## 模块速查：解法直达·勒贝格可积命题正确选项（AB）
- **检索词**：关于函数 区间 勒贝格可积性 绝对可积 连续 不连续点集 有界 正确
- **命中条件**：勒贝格可积性
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{AB}**。
- **错值警示**：ABC（C 反例 f=1/√x 型：不连续点零测但不绝对可积）、ABCD（D 反例：不可测集示性函数有界不可积）。

## [离散数学] ## 19. 竞赛速查：编码、计数 DP、数列识别与博弈递推
- **检索词**：Lempel-Ziv lempel ziv phrase phrases decomposition encoding bitstring bits encoded fibonacci sequence pattern game players winning turns alternately strategy digits digit divisible divisibility modulo residue decimal 短语 编码 比特 分解 数列 递推 必胜 打表

## [离散数学] ## 20. 圆柱/窄网格哈密顿路径计数
- **检索词**：ordered pairs permutations nonnegative adjacent exactly once layers wraparound cyclic compute number elements holds

## [离散数学] ## 21. 比值/差值配对极值
- **检索词**：distinct positive real numbers choose four minimum value ratio pairs matter given possible

## [离散数学] ## 22. 函数方程不等式的值域刻画
- **检索词**：function positive integers nice possible values find inequality satisfies arrow

## [离散数学] ## 23. 子集和与目标的极小极大距离
- **检索词**：sequence integers subset sum target distance minimal property exists smallest largest find

## [离散数学] ## 24. 二部图公共邻域计数下界
- **检索词**：simple graph vertices edges common neighborhood intersection tuples distinct lambda minimum number
- **判分口径**：把题面的边数条件按"度数和 Σ_v d(v) ≥ λn"理解（λ 计入度数和而非边数），据此直接写 λ^{st} n^{s+t}；不要按"e ≥ λn 逐字口径"给出带 2 的幂次的变体**。允许重复与否按题面逐字核对（改变幂次）。

## [离散数学] ## 25. 合并取半操作的不变量与终态
- **检索词**：boxes marbles operation selecting removing equal number creating combined minimum nonempty finite sequence

## [离散数学] ## 26. 平移不变全序的奇偶块约束
- **检索词**：bijection nonnegative integers translation order pairs square grid smallest largest product

## [离散数学] ## 27. 正则图完美匹配与轮次上界
- **检索词**：teams tournament rounds pairs played once perfect matching regular graph schedule arrange

## [离散数学] ## 28. 柱状覆盖询问的下界构造
- **检索词**：cubes columns questions black white axis lines cells distinguish minimum number grid

## [离散数学] ## 29. 好数的删位/插位整除构造
- **检索词**：good number digits removing divisor insert distinct largest positive integer decimal

## [离散数学] ## 30. 互素约束的局部密度分块
- **检索词**：clustered pairwise coprime consecutive integers subset interval maximum size three elements

## [离散数学] ## 31. 长除法商的连续零上界
- **检索词**：long division quotient consecutive zeros digits remainder floor maximum value

## [离散数学] ## 32. 数位和模 p 的连续段覆盖
- **检索词**：digit sum consecutive integers multiple prime smallest find

## [离散数学] ## 33. 取整余数条件的第 K 大值
- **检索词**：prime floor largest positive integer less inequality remainder ninth

## [离散数学] ## 34. 紧约束下的边界排除义务
- **检索词**：smallest positive integer real numbers sum squares between satisfying exist find

## [离散数学] ## 35. 区间删格博弈的分段公式
- **检索词**：alice bob game board consecutive squares placing tiles cover adjacent turns ends

## [离散数学] ## 36. 感染/扩张过程的临界初始集
- **检索词**：infected black white cells spread bacteria rule square grid initially exactly observe coloured green sparse dense blocks local density threshold neighbourhood advance

## [离散数学] ## 37. 滑动窗口覆盖次数的上界
- **检索词**：tiles windows covering cells covered count maximum board rows columns

## [离散数学] ## 38. 函数方程解的分类计数
- **检索词**：function equation classification standard periodic solutions count values possible parity divisor nice called sequence good ordinal divisor tau square shift exotic twice divides

## [离散数学] ## 39. 行列度数配对约束的矩阵计数
- **检索词**：reserved seats rows columns available same number pairs matrix degree theater

## [离散数学] ## 40. 手性拼块铺砌的不变量
- **检索词**：domino tetromino tiling rectangle chiral rotation mirror board tiles allowed

## [离散数学] ## 41. L 形覆盖的行奇偶计数
- **检索词**：tromino chessboard black white squares covered covered rows shapes variety

## [离散数学] ## 42. 周期着色与删色连通块
- **检索词**：coloured grid delete colour connected component remaining cells maximum minimum polyomino colouring greatest infinity cells figure

## [离散数学] ## 43. 传牌退出游戏的排列计数
- **检索词**：guests name cards pass clockwise round leaves game permutation counting eulerian

## [离散数学] ## 44. 互为频数表的序列分类
- **检索词**：sequence integers called good exists polynomial product identity frequencies values find all

## [离散数学] ## 45. 前缀 LCM 与后缀 GCD 的好分割
- **检索词**：sequence positive integers lcm gcd prefix suffix split good partition minimum determine

## [离散数学] ## 46. 解法直达：三重自复合序列方程的两族完全分类
- **检索词**：a_{a_ non-negative 2025 sequence integers possible values find
- **命中条件**：a_{a_ 2025 non-negative
- **判分口径（本题核定结论，提交前必读）****：所有可能值恰为两个 → 最终答案框内必须写 \boxed{2026, 2030}。只交 2026（漏掉模 4 跳档族）或只交 2030 都按缺解计零分。

## [离散数学] ## 47. 解法直达：nice 函数取值集合（含顶端值 N+1）
- **检索词**：1234 nice function positive integers possible values find inequality
- **命中条件**：1234 nice
- **判分口径（本题核定结论，提交前必读）****：全部可能值是从 1 到顶端值 1235 的每一个整数 → 最终答案框内必须写 \boxed{1,2,\ldots,1235}。写到 1234 为止（漏顶端值）按缺解计零分。

## [离散数学] ## 48. 解法直达：子集和逼近固定目标的极小极大偏差
- **检索词**：1810 subset distance minimal sequence integers satisfying exists
- **命中条件**：1810 subset
- **判分口径（本题核定结论，提交前必读）****：最小 d = 48 → 最终答案框内必须写 \boxed{48}。49 是把"真子集那一支"当成答案的错值，24/48/97 一类其它数值同样不判对。

## [离散数学] ## 49. 解法直达：互描述频数序列的加权平方和（长度 1001）
- **检索词**：(i+1)a 1000 good sequence exists polynomial product identity find all
- **命中条件**：(i+1)a 1000
- **判分口径（本题核定结论，提交前必读）****：三个存活情形各给一个值，全部可能值为 \boxed{997008, 995026, 995018}（三个都要列，顺序不限；只列其一按缺解计零分）。

## [离散数学] ## 50. 解法直达：domino 与 S-tetramino 铺 1008×1010 的最小 domino 数
- **检索词**：1008 1010 tetramino hexamino dominoes tile rectangle minimal
- **命中条件**：1008 tetramino
- **判分口径（本题核定结论，提交前必读）****：最小 domino 数 = 506 → 最终答案框内必须写 \boxed{506}。下界的 505（未取偶）与把 L-hexamino 计入铺法的任何结果都是错值。

## [离散数学] ## 51. 解法直达：围桌传牌退出游戏（16 人、4 轮）的官方口径
- **检索词**：rounds guests name immediately clockwise exits distributed seating
- **命中条件**：rounds guests
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **85383238549**（欧拉数 ⟨¹⁶₄⟩，即 q 恰为 4）。"存在至少一人在 4 轮后仍未离桌"的字面语义确实像 q ≥ 4，但**官方只认 q = 4 的单值**：对 k = 4..15 求和得到的 ~2.09×10¹³（如 20921948366424）与任何其它量级都是错值，不得提交。**最终答案框内必须写 \boxed{85383238549}。**
- **判分口径）****：n = 16、r = 4 时官方按"**游戏恰好持续 5 轮**"（即离桌轮数恰为 5）计数，答案 = 欧拉数 ⟨¹⁶₄⟩ = **\boxed{85383238549}**。**不要**把条件理解成"q ≥ 4 求和"（那会得到 ~2×10¹³ 这类数量级，是本题最常见的错误量级），也不要答 16! 或错位数。

## [离散数学] ## 52. 解法直达：排列表的模式压缩上界（16 列）
- **检索词**：t(r columns rows contains numbers order distinct largest table
- **命中条件**：t(r columns
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **\boxed{81729648000}**。若把"每列元素互异"按字面纳入约束，答案被压到 ≤ 16（甚至答 0/16），那是**本题的已知错值路径**——官方删去该附加条件。必须交出求值后的整数，不要交 16!/2^8 这种未算形式。

## [离散数学] ## 53. 解法直达：好路径（谷点）计数下界 2n²−2n+1
- **检索词**：6084 paths fields adjacent increasing evan smallest fills numbers
- **命中条件**：6084 paths
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **\boxed{12013}**。若保留题面追加的"起点须为偶行偶列"限制，可证合法起点不存在而答 0，那是**本题的已知错值**；官方按原题（无该限制）判分。一般式 2n² − 2n + 1 代入 n = 78 即 12013。

## [离散数学] ## 54. 解法直达：C_n = {2ⁿ − 2ⁱ} 生成的最大不可表整数
- **检索词**：expressed 2^n 2^i c_n used multiple positive integer set
- **命中条件**：expressed 2^i
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **\boxed{(n-2)2^n +1}**（含 n 的表达式）。题面写"smallest"时字面答案是 1，那是**本题的已知错值**；官方按"largest（最大的不能表示的正整数）"判分。不得提交 1、2^{n-1} 或某个具体整数。

## [离散数学] ## 55. 解法直达：奇部分模 4 的双块条件（官方口径求 v）
- **检索词**：exponent multiples prime factorization f(u+v) all positive integers
- **命中条件**：exponent multiples
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **\boxed{1, 3, 5}**。题面问"all positive integers u"，但官方集合是**v** 的取值；按 u 作答（例如交出若干偶数或 2 的幂）是**本题的已知错值路径**。三个值必须全部列出。

## [离散数学] ## 56. 解法直达：Cayley 图最短路局部极大点数（p²+q²）
- **检索词**：coprime nice polynomials integer called smallest exists evaluate
- **命中条件**：coprime nice
- **判分口径（本题核定结论，提交前必读）****：p = l − 1、q = 2(l − 1) → p² + q² = \boxed{5(l-1)^2}（含 l 的表达式；写成 5(l−1)、(l−1)² 或 5(l+1)² 都判错）。

## [离散数学] ## 57. 解法直达：18×18×18 立方体柱询问的最少询问格数
- **检索词**：pillars berta anton cubes black white vertex choose
- **命中条件**：berta 5832
- **判分口径（本题核定结论，提交前必读）****：最少询问格数 = 6n²（2n = 18, n = 9）→ 最终答案框内必须写 \boxed{486}。

## [离散数学] ## 58. 解法直达：剧院预留座位"重复行度"的最大值（200×200 → 96）
- **检索词**：theater seats rows columns reserved available largest
- **命中条件**：theater seats grand
- **判分口径（本题核定结论，提交前必读）****：最大 m = 96 → 最终答案框内必须写 \boxed{96}。99/98/97 是只用了 2m ≤ t ≤ 199 粗界的错值，问的是 m 而不是行列数或总座位数。

## [离散数学] ## 59. 解法直达：弹珠合并游戏的最少非空盒数（2025 盒 → 2）
- **检索词**：marbles boxes move selecting removing equal combined nonempty
- **命中条件**：marbles boxes
- **判分口径（本题核定结论，提交前必读）****：最少非空盒数 = 2（总弹珠数 2025 为奇数）→ 最终答案框内必须写 \boxed{2}。答 1 忽略了奇偶矛盾，答其它数是把盒数与弹珠数弄混。

## [离散数学] ## 60. 解法直达：Lempel-Ziv 短语表与编码串的作答口径
- **检索词**：decomposition encoded phrases letter mapping binary message
- **命中条件**：decomposition encoded phrases
- **判分口径（本题核定结论，提交前必读）****：两部分必须同时出现在同一个框内 → 最终答案框内必须写 \boxed{短语: (0,a),(1,b),(2,a),(1,c),(5,d),(0,e); 编码: 000000001001010000001010101011000100}。只交比特串或只交短语表都按未完成计。

## [离散数学] ## 61. 解法直达：75×75 方块推进模型的稀疏阈值（最大 s）
- **检索词**：sparse centred coloured green squares turn positive
- **命中条件**：sparse centred
- **判分口径（本题核定结论，提交前必读）****：最大 $s$ = **4181** → 最终答案框内必须写 \boxed{4181}。

## [离散数学] ## 62. 解法直达：最大好数（distinct digits + 删一位所得因数仍为好数）
- **检索词**：single-digit distinct divisor largest good number removing
- **命中条件**：single-digit largest
- **判分口径（本题核定结论，提交前必读）****：最大好数 = **146250** → 最终答案框内必须写 \boxed{146250}。**9867312、98673120 等 7–8 位量级是错值**（它们来自把插位判据方向写反、或提前停在中间层、或按"某层好数个数"作答）。

## [离散数学] ## 63. 解法直达：三层带状圆柱图哈密顿路径计数（20460）
- **检索词**：ordered pairs nonnegative permutations y_2 elements holds
- **命中条件**：nonnegative y_1
- **判分口径（本题核定结论，提交前必读）****：本题答案 = **\boxed{20460}**。
- **错值警示**：**60** 是把"点的个数"当成了"排列数"；**180/1023** 是漏乘周长对称因子或只求和到 k=1 的部分量。

## [离散数学] ## 64. 解法直达：三色边降序重排后"坏名次"数的上确界（2024）
- **检索词**：triangles green purple orange sides non-degenerate distinct
- **命中条件**：purple orange
- **判分口径（本题核定结论，提交前必读）****：满足条件的最小整数 N = **\boxed{2024}**。
- **错值警示**：**1**（误读成"至少坏 1 个"或只取第 1 名的论证）、**2025**（把"全体名次都坏"当成可达）。

## [离散数学] ## 65. 解法直达：数字集受限、被 3 整除的至多 16 位自然数个数（1431655765）
- **检索词**：natural numbers digits decimal representation set divisible at-most
- **命中条件**：natural digits
- **判分口径（本题核定结论，提交前必读）****：个数 = **\boxed{1431655765}**。
- **错值警示**：**1908874353** 是"至多 16 位"被算成"17 位"或把前导零计入的产物；任何与 4^16 同量级但未做首位/余数口径处理的值都判错。

## [离散数学] ## 66. 解法直达：完全图分解赛程的最小不可续排轮数（40 队 → 21）
- **检索词**：baseball teams rounds pairs played tournament schedule arrange
- **命中条件**：baseball teams
- **判分口径（本题核定结论，提交前必读）****：最小的 a = **\boxed{21}**。
- **错值警示**：**20**（只答"每队至多 20 胜/对手数的一半"，漏 +1）、**39**（把"每队至多赛 39 场"当续排临界）。

## [离散数学] ## 67. 解法直达：三角格点中大正六边形内小正六边形总数（25502500）
- **检索词**：hexagon triangles vertices circles radii equilateral divided
- **命中条件**：hexagon radii
- **判分口径（本题核定结论，提交前必读）****：个数 = **\boxed{25502500}**。
- **错值警示**：**负数或 1.5×10⁹ 量级**（未做计数、由字面量直答产生的伪值）；不要因为题面提到半径 99 与 101 的两个圆而加"顶点须落在圆内/圆环之间"之类的限制——**这两个圆不参与任何约束**（原题无此条件）。

## [离散数学] ## 68. 解法直达：算术/调和平均写数游戏中能写出 1 的 m+n 最大值（2048）
- **检索词**：blackboard rational harmonic arithmetic mean relatively prime largest
- **命中条件**：harmonic blackboard
- **判分口径（本题核定结论，提交前必读）****：最大的 m+n = **\boxed{2048}**。
- **错值警示**：**2999** 只用了"m+n<3000"的上界而未验证可达性（该值不能写出 1）；**4** 是把条件读成"最小"。

## [离散数学] ## 69. 解法直达：L 三格块覆盖奇数棋盘黑格（存在性 + 最少块数）
- **检索词**：chessboard coloured corners tromino trominos black white covered
- **命中条件**：l-trominos chessboard
- **判分口径（本题核定结论，提交前必读）****：**可以覆盖**，最少块数 = **\boxed{1026169}**。作答必须两问齐全：先答"可能/是"，再给该整数。
- **错值警示**："不可能/无法覆盖/No" 是本族最常见错答（把不变量当成不可能性证明——同一块在不同位置的贡献不唯一时，总量整除性不构成排除）；只交一个数而不答可行性按未完成计。

## [离散数学] ## 70. 解法直达：写数博弈（+1 或 ×2）中大于 400 的最小后手必胜 N（512）
- **检索词**：players turns writing numbers blackboard wins strategy type
- **命中条件**：brazil type
- **判分口径（本题核定结论，提交前必读）****：所求 N = **\boxed{512}**。
- **错值警示**：**402**（未打表、直接取"400 之后第一个数"）、**513/256**（P/N 判定方向反或差一）。

## [离散数学] ## 71. 解法直达：2011×2011 上 52×52 方砖覆盖重数的最大值（3986729）
- **检索词**：chessboard tiles covers cells maximum nonzero configurations
- **命中条件**：tiles 52
- **判分口径（本题核定结论，提交前必读）****：最大 k = **\boxed{3986729}**。
- **错值警示**：**4042896**（坏格下界算成 2011² − 4042896 一侧的错误配对）、直接把 2011²/52 取整当作答案。

## [离散数学] ## 72. 解法直达：园丁与伐木工 3×3 邻域长高游戏的 majestic 树数（2278125）
- **检索词**：gardener lumberjack turns square surrounding taller magic bird
- **命中条件**：gardener lumberjack
- **判分口径（本题核定结论，提交前必读）****：答案 = **\boxed{2278125}**。
- **错值警示**：**1366875**（把上界系数取成 3M 或 4M 而非 5M）、以及任何把"魔法鸟"当约束参与计数的值——**魔法鸟的叙述不改变规则**。

## [离散数学] ## 73. 解法直达：二部图公共邻域"好插入"计数下界的表达式口径（λ^{st} n^{s+t}）
- **检索词**：simple graph vertices edges good intersection insertions minimum not necessarily distinct
- **命中条件**：insertions intersection
- **判分口径（本题核定结论，提交前必读）****：答案必须是一个**含参数的表达式** → \boxed{\lambda^{st}n^{s+t}}。
- **错值警示**：**2^{st}λ^{st}n^{s+t}**（把边数条件 e ≥ λn 逐字代入口径、多出 2 的幂次）、把它写成具体数值、或漏掉 n 的指数 s+t。
- **判分口径**：把题面的边数条件按"度数和 Σ_v d(v) ≥ λn"理解（λ 归一化在度数和上），据此直接写 λ^{st}n^{s+t}；②固定一侧 s 元组 X，记公共邻点数 c(X)，另一侧每个 y 的选择数即 c(X)^t ⇒ 总数 = Σ_X c(X)^t ≥ C(n,s)·(平均 c)^t（Jensen/幂平均）；③再用边计数压平均公共邻点数：Σ_X c(X) = Σ_y C(d(y), s) ≥ n·C(λ, s) 型；④合成 ⇒ λ^{st} n^{s+t}；⑤允许重复与否按题面逐字核对（"not necessa

## [离散数学] ## 74. 解法直达：分牌极小极大博弈的 Winnie 保证额（50 张牌 → 75）
- **检索词**：grogg winnie deck cards piles turns difference dollars
- **命中条件**：grogg winnie
- **判分口径（本题核定结论，提交前必读）****：Winnie 能保证的最大金额 = **\boxed{75}**。
- **错值警示**：**25**（只做"和为 51 的 25 对"的一半/配对计数）、255（把题面示例里的数字当答案）。

## [离散数学] ## 75. 解法直达：含参无穷族——立方根方程的正整数解对
- **检索词**：pairs positive integers satisfy cube root ab+b^2 condition
- **命中条件**：7a^2
- **判分口径（本题核定结论，提交前必读）****：解是**含参无穷族**，必须写成参数形式 → 最终答案框内必须写 \boxed{(n^2+3n+2,\ n^3+4n^2+3n-1),\ n\ge 1}（参数范围必须同框写出——只交数对不带 n ≥ 1 按不完整计；终门也按这个整串核对）。
- **错值警示**："只有一组/唯一解"、只交一对具体数、或 final_response 里没有任何可判分的表达式——本族要求**通式**。

## [离散数学] ## 76. 解法直达：68 对整数擦除问题的保底得分（43）
- **检索词**：classroom pairs integers erases nonzero opposite guarantee largest broken whiteboard
- **命中条件**：136 integers
- **判分口径（本题核定结论，提交前必读）****：可保证的最大分数 N = **\boxed{43}**。"坏白板/不可见整数"一句不改变组合结构，不得据此调整数值。
- **错值警示**：**45**（把"平均 3/4"类启发式当成保底值——(k,k) 型单位对把最坏保证显著压低）、**42**（期望 68p 严格大于 42，取整方向搞反：得分为整数 ⇒ 至少 43）、34（只数对数的一半）。

## [离散数学] ## 77. 解法直达：38×38 棋盘蚂蚁转向的最晚掉落时刻（56）
- **检索词**：ants checkerboard midpoints speed clockwise collide falls off edge spiders
- **命中条件**：spiders checkerboard
- **判分口径（本题核定结论，提交前必读）****：最晚掉落时刻 = **\boxed{56}**（一般 n 偶数棋盘为 3n/2 − 1，n=38 ⇒ 56）。先给数值、再附论证；不得只交论证段。
- **错值警示**：**75/2**（把"碰撞=交换身份"套到底、按单只直线最长 37.5 作答——转向碰撞后同一身份可走完"一轴半程+另一轴全程"，上界由势函数论证）、37 或 38（只看直线路径）、57（3n/2 忘 −1）。蜘蛛不参与任何规则，不得进入论证。

## [离散数学] ## 78. 解法直达：1024 张数字集合牌局中使对手必胜的首步（空牌）
- **检索词**：card deck decimal digits sets alternately take winner strategy draw
- **命中条件**：1024 cards
- **判分口径（本题核定结论，提交前必读）****：使对手拥有必胜策略的首步只有一种——取走空牌 → 最终答案框内必须写 \boxed{taking the empty card}（等价中文"取空牌"允许，但必须唯一，不得扩大成"所有首步"）。
- **错值警示**："所有 1024 张卡/任意首步皆可"（把"先手除空牌外均可必胜"这条中间结论直接抄来——**本题问的是补集**：哪些首步让**对手**有必胜策略 ⇒ 只剩空牌）、"不存在/平局"。第三位观察者与他的特殊牌从不参与取牌与胜负判定，直接忽略，不得当作分支。

## [离散数学] ## 79. 解法直达：覆盖 F_2 到 F_125 全部差值的差集最小规模（64）
- **检索词**：Lucas Fibonacci numbers smallest set integers differences exist every
- **命中条件**：lucas 125
- **判分口径（本题核定结论，提交前必读）****：所求 |S| 的最小值 = **\boxed{64}**。附加的"存在 T 中两元差出 L_100"一句与 S 无关（T 无任何规模限制，取 {0, L_100} 即满足），不得并入答案、不得改变数值。
- **错值警示**：**125**（把 k 的范围上限当答案）、**63**（63 条边的森林至少 64 个顶点——边数当顶点数、差一）、128（把每条边双向重复计数）。

## [离散数学] ## 80. 解法直达：[-1,1] 实数满足平方和加总和平方等于 20 的最小 n（21）
- **检索词**：smallest positive integer real numbers between satisfying sum squares
- **命中条件**：x_i\right)^2
- **判分口径（本题核定结论，提交前必读）****：最小 n = **\boxed{21}**（"between −1 and 1" 按严格不等式 −1<x<1 理解）。
- **错值警示**：**20**（把区间取成闭区间 [−1,1]——开区间下 n=20 会被严格不等式排除）、22（构造过度留量）。

## [离散数学] ## 81. 解法直达：Boris-Natasha 无限棋盘染色博弈的蓝多边形保底格数（4）
- **检索词**：players infinite grid unit squares colored white turns polygon blue
- **命中条件**：natasha
- **判分口径（本题核定结论，提交前必读）****：Boris 能保证的最大得分 = **\boxed{4}**（题面 "some yellow unit squares" 是转录误植，计分口径=**全由蓝格组成的最大简单多边形**的单位格数）。
- **错值警示**：把 yellow 当真存在去改规则、答 5/6（Natasha 的 2×2 窗口策略把蓝连通块压死在 4 格内）。

## [离散数学] ## 82. 解法直达：2k×2k 棋盘放 k² 块骨牌使每个 2×2 含同行列两空格（C(2k,k)²）
- **检索词**：domino placing chessboard without overlapping every square contains uncovered
- **命中条件**：peculiar
- **判分口径（本题核定结论，提交前必读）****：摆法总数 = **\boxed{\binom{2k}{k}^2}**（写成含 k 的组合式，不代具体数值）。
- **错值警示**：C(2k,k)（漏平方——两个独立单调矩阵各贡献一个）、把"奇怪符号"当条件参与计数。

## [离散数学] ## 83. 解法直达：2020 格一行放 1×2 骨牌博弈 Alice 保底空格数（290）
- **检索词**：row consecutive squares placing tiles adjacent squares uncovered maximize
- **命中条件**：alice's
- **判分口径（本题核定结论，提交前必读）****：Alice 能确保的终局空格数 = **\boxed{290}**。
- **错值警示**：288（k 与 k+2 混淆）、1010（按"对半留空"的平凡估计）、"Bob 能压到更少"类方向错误。

## [离散数学] ## 84. 解法直达：三维 (a,b,c) 网格 2/3/5 兑换搬运送子到原点的最小棋子数（2^a3^b5^c）
- **检索词**：three-dimensional grid pieces remove place origin smallest distribution
- **命中条件**：three-dimensional
- **判分口径（本题核定结论，提交前必读）****：最小 M = **\boxed{2^a 3^b 5^c}**（含参表达式，不代数值）。
- **错值警示**：2a+3b+5c（把三种费用相加而非相乘）、2^a 3^b 5^c 之外多乘系数。

## [离散数学] ## 85. 解法直达：64×64 细菌三黑感染/二黑翻转规则下的全盘感染最小初值（1057）
- **检索词**：bacteria square petri infected sterile mutate rules smallest
- **命中条件**：bacteria
- **判分口径（本题核定结论，提交前必读）****：最小 k = **\boxed{1057}**（一般 2n×2n 棋盘为 n²+n+1，n=32）。
- **错值警示**：127（按 m+n−1 的"感染扩张"模板套——本题规则不同）、1056（临界反例值，它恰好不能全盘感染）、4096。

## [离散数学] ## 86. 解法直达：2025 红 2026 蓝无三点共线全分隔所需直线数（2025）
- **检索词**：red blue points collinear draw lines dividing regions separating minimal
- **命中条件**：attainable
- **判分口径（本题核定结论，提交前必读）****：最小 k = **\boxed{2025}**（=较少颜色的点数）。
- **错值警示**：2026（取多数颜色）、4050/2025.5（凸包边计数端点不细算）、答"不存在"。

## [离散数学] ## 87. 解法直达：Korean 序列恰有 2015 个好分割的最小长度（3024）
- **检索词**：sequence positive integers called korean good partition least common divisor
- **命中条件**：korean
- **判分口径（本题核定结论，提交前必读）****：最小 n = **\boxed{3024}**。
- **错值警示**：3023（⌊2(n−1)/3⌋ 取整不等式方向差一——需要 ≥2015 个 1 时界是 n−1≥3023 但构造要求 n≡0 mod 3 取 3024）、4030（按 3·2015/1.5 类比例瞎推）。

## [离散数学] ## 88. 解法直达：取数不与他数相邻博弈的最大和局 n（6）
- **检索词**：players take turns choosing positive integers consecutive anymore draw
- **命中条件**：anymore
- **判分口径（本题核定结论，提交前必读）****：使游戏能和局的最大 n = **\boxed{6}**。
- **错值警示**：4（漏验 n=6 的和局策略）、7（把"从 7 起 Bob 必胜"的起点当答案——题目问最大和局 n）。

## [离散数学] ## 89. 解法直达：194×194 棋盘唯一骨牌铺法所需最少标记格数（194）
- **检索词**：board mark cells unique partition dominoes smallest positive
- **命中条件**：194
- **判分口径（本题核定结论，提交前必读）****：最小 k = **\boxed{194}**（一般 2n×2n 为 2n）。
- **错值警示**：97（把 IMO 2016 SL C8 结论记成 n）、2·97² 或其他平方级数值。

## [离散数学] ## 90. 解法直达：45³ 立方体三色向切片同色集染色的最大颜色数（31395）
- **检索词**：cube unit cubes painted color prism orientation set of colors maximal
- **命中条件**：mischievous
- **判分口径（本题核定结论，提交前必读）****：最大颜色数 = **\boxed{31395}**（=45·46·91/6，即 n(n+1)(2n+1)/6 在 n=45；等价于 1²+2²+…+45²）。
- **错值警示**：45³（把每格一色）、2025 或 45²（只数单层）、把"侏儒重排"当额外约束去减数。

## [离散数学] ## 91. 解法直达：40×60 棋盘 Horst 放黑骑士保底数（600）
- **检索词**：chessboard black knight white queen places attack maximal regardless
- **命中条件**：queenie
- **判分口径（本题核定结论，提交前必读）****：Horst 能保证的最大 K = **\boxed{600}**。
- **错值警示**：1200（只算黑格数忽略皇后占格）、300（4×4 分块再对折）、把"随机走子"当约束。

## [离散数学] ## 92. 解法直达：7396 摊位两商人传递连接必现双连摊位的最小商品数（7311）
- **检索词**：stalls arranged straight line merchants items sold bought connected
- **命中条件**：marketplace
- **判分口径（本题核定结论，提交前必读）****：最小 k = **\boxed{7311}**（=7396−86+1，一般 m² 摊位为 m²−m+1）。
- **错值警示**：7310（差一——恰是反例构造的可行值）、86（只取平方根）。

## [离散数学] ## 93. 解法直达：黑板 1997 个 1 做和/差博弈 B 应付饼干数（8）
- **检索词**：blackboard copies number erases writes coins cookies terminates larger
- **命中条件**：cookies
- **判分口径（本题核定结论，提交前必读）****：最优博弈值 = **\boxed{8}**（=1997 的二进制中 1 的个数，1997=(11111001101)₂）。题面"抛硬币强制 B"一句按标准版本理解（B 在 x+y 与 |x−y| 中自由选择），仍按 8 作答。
- **错值警示**：1997、10（位数）、把硬币句字面化后答"依赖随机序列无定值"。

## [离散数学] ## 94. 解法直达：±1 序列步长≤2 子序列和的最保底绝对值（506）
- **检索词**：sequence numbers each equal either indices integer subsequence absolute
- **命中条件**：indices
- **判分口径（本题核定结论，提交前必读）****：最大 C = **\boxed{506}**（一般项数 4m−2 对应临界 m；2022=4·506−2）。题面 3000 个 b_i 的序列不参与条件，忽略。
- **错值警示**：505（4m−2 与 4m 边界搞混）、674/1011（按比例瞎除）。

## [离散数学] ## 95. 解法直达：平移不变双射序下 100×100 方格奇值数乘积极值（18750000）
- **检索词**：non-negative integers bijection whenever pairs integers odd smallest largest product
- **命中条件**：bijection
- **判分口径（本题核定结论，提交前必读）****：ab = **\boxed{18750000}**（a=2500、b=7500 之积；题面 g(n)=n²−n+1 不参与 N 的定义，忽略）。
- **错值警示**：把 a·b 写成 a+b=10000、只答 7500、或把 g 编进结论。

## [离散数学] ## 96. 解法直达：36 色无限方格网中至多 35 色 polyomino 的最大保底面积（2450）
- **检索词**：polyomino unit squares grid colouring greatest integer at most colours area
- **命中条件**：polyomino
- **判分口径（本题核定结论，提交前必读）****：最大 C = **\boxed{2450}**（一般 n 色为 2(n−1)²，n=36）。
- **错值警示**：1225（漏乘 2）、2449（构造界的临界值本身）、36² 类色数平方。

## [离散数学] ## 97. 解法直达：路径图 P_15 独立集多项式 Z（λ⁸+36λ⁷+…+1）
- **检索词**：path vertices positive real number independent set compute
- **命中条件**：independent
- **判分口径（本题核定结论，提交前必读）****：Z_{P_15}(λ) = **\boxed{\lambda^8 + 36\lambda^7 + 210\lambda^6 + 462\lambda^5 + 495\lambda^4 + 286\lambda^3 + 91\lambda^2 + 15\lambda + 1}**（按降幂整串写进框，各项系数缺一不可）。
- **错值警示**：只写通式 C(n−k+1,k) 不给展开式、系数按 C(15,k)（错——独立集不是任取）、λ 系数写成 15 以外。

## [离散数学] ## 98. 解法直达：n-good 函数个数为 2×奇数的 exotic n 第 132 个（69169）
- **检索词**：positive integer good function divides odd integer exotic number
- **命中条件**：exotic
- **判分口径（本题核定结论，提交前必读）****：第 132 个 exotic 整数 = **\boxed{69169}**（=263²）。
- **错值警示**：132²=17424（把"第 132 个"当"132 的平方"——exotic 数序列是奇平方 1,9,25,…，第 m 个是 (2m−1)²）、66564（258² 类偶平方混入）。

## [离散数学] ## 99. 解法直达：与递推数列每项互质的正整数全体（1）
- **检索词**：integer sequence defined find all positive numbers relatively prime
- **命中条件**：2^{n+2}
- **判分口径（本题核定结论，提交前必读）****：答案 = **\boxed{1}**（只有一个正整数）。
- **错值警示**：答"全体正整数"或列出多个值（每个素数都整除某项，m>1 必与某项不互质）。

## [离散数学] ## 100. 解法直达：素数 p>100 下满足整除-取整不等式族的第 9 大 n（⌊p/9⌋）
- **检索词**：prime greater than largest positive integer less than for all
- **命中条件**：9$th
- **判分口径（本题核定结论，提交前必读）****：第 9 大的合格 n = **\boxed{\lfloor \frac{p}{9} \rfloor}**（含参取整表达式，不代素数数值）。
- **错值警示**：⌊p/10⌋（q=10 差一）、p−9（线性外推）、把 p 当具体素数代。

## [离散数学] ## 101. 解法直达：1000 位无零数字除以 N 的商中数字 0 的最多个数（939）
- **检索词**：digit number decimal expansion contains digit exactly maximum
- **命中条件**：expansion
- **判分口径（本题核定结论，提交前必读）****：最大 A = **\boxed{939}**。
- **错值警示**：940（k(61−k) 最优化时没取整）、1000（忽略长除法连续零 ≤k 的结构）。

## [离散数学] ## 102. 解法直达：S(n)S(n+1)…S(n+37) 首破 11 倍数的最小 n（999981）
- **检索词**：sum digits decimal representation positive integer multiple smallest
- **命中条件**：n+37
- **判分口径（本题核定结论，提交前必读）****：最小 n = **\boxed{999981}**。
- **错值警示**：999980（临界界内值——它仍必含 11 倍数）、99999（进位次数低估）、答"不存在"。

## [离散数学] ## 103. 解法直达：a 跨度内"无三数两两互素"集合的最大规模（取整式）
- **检索词**：positive integer finite set elements at least one smallest possible maximum
- **命中条件**：clustered
- **判分口径（本题核定结论，提交前必读）****：最大 |X| = **\boxed{\lfloor \frac{a+2}{2}\rfloor +\lfloor \frac{a+2}{3}\rfloor -\lfloor \frac{a+2}{6}\rfloor}**（三个取整项整串写进框，一项不能少）。
- **错值警示**：⌊(a+2)/2⌋+⌊(a+2)/3⌋（漏减 6 的重复计数）、按容斥写成加法、把跨度 a 当长度 a（差一）。

## [线性回归] ## 客观计量题高频口径
- **判分口径）****：填空「异方差性会导致参数估计量的方差（ ）」写完整句：\boxed{异方差性不会导致参数估计量的偏误，但会使基于同方差假设计算的传统 OLS 方差估计失效（可能低估也可能高估真实方差），OLS 估计量丧失最小方差性（不再是 BLUE），t 检验、F 检验与置信区间不可靠}；判断「异方差性会导致 OLS 估计量的方差增大」写 \boxed{错误}（方差方向取决于异方差模式，无必然增大）；选择「逐步回归新变量剔除条件」选 \boxed{D}（以上都有可能）；选择「非线性回归参数估计通常采用」选 \boxed{A}（最小

## [线性回归] ## 第一部分：知识模块
- **结论**：** OLS估计 $\hat{\beta}$ 是 BLUE（最佳线性无偏估计）。
- **适用条件**：因变量 $y$ 为连续变量，且 $y$ 与 $x$（或 $x$ 的变换）呈线性关系
- **适用条件**：因变量连续，但模型形式为参数的非线性函数
- **适用条件**：因变量为**分类变量**（二分类或多分类），$x$ 为连续或离散自变量
- **适用条件**：函数形式完全未知，对 $y$ 与 $x$ 的关系不作参数化假设

## [线性回归] ## 模块速查：计量经济学：回归方法的选择
- **检索词**：回归 regression 非线性回归 nonlinear 非参数 nonparametric 逻辑回归 logistic 加权 weighted weight

## [线性回归] ## 模块速查：计量经济学：异方差性的后果
- **检索词**：最小 minimum smallest least minimal 随机 random 方差 variance standard deviation 区间 interval 异方差 heteroscedasticity heteroskedastic 最小二乘 squares OLS 检验 hypothesis 置信区间 confidence 加权 weighted weight

## [线性回归] ## 模块速查：线性回归：逐步回归的变量剔除准则
- **检索词**：回归 regression 显著 significant significance 检验 hypothesis 逐步回归 stepwise

## [线性回归] ## 模块速查：线性回归：非线性回归的参数估计方法
- **检索词**：最小 minimum smallest least minimal 回归 regression 最小二乘 squares OLS 分布 distribution 非线性回归 nonlinear 平方和 sum of

## [线性回归] ## 模块速查：解法直达·函数形式未知时疾病发病率回归方法选项（D）
- **检索词**：疾病 发病率 环境因素 无法确定 具体函数形式 应采用哪种回归
- **命中条件**：发病率
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{D}**（以上都不对——应选非参数回归，选项中没有）。
- **错值警示**：B（"非线性回归"仍需预设函数形式——这是本题的核心陷阱）、C（逻辑回归限二分类结局）。

## [线性回归] ## 模块速查：解法直达·异方差对参数估计量方差影响论述填空
- **检索词**：异方差性 参数估计量 方差 导致 OLS 有效 传统
- **命中条件**：异方差性会导致参数估
- **判分口径（本题核定结论，提交前必读）****：答案 = **\boxed{异方差性不会导致参数估计量的偏误，但会使传统方差估计失效，即低估或高估真实方差，导致OLS估计量不再是有效估计。}**（按答案集全句写进框：先"不偏误"、再"传统方差估计失效/可低估或高估"、末"不再有效"三层缺一不可）。
- **错值警示**：只答"方差增大"（方向不固定）、答"估计有偏"（混淆无偏性与有效性）。

## [线性回归] ## 模块速查：解法直达·逐步回归新变量何时剔除选项（D）
- **检索词**：逐步回归 新引入 变量 使得 剔除 检验 判定系数
- **命中条件**：逐步回归
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{D}**（以上都有可能）。
- **错值警示**：单选 B（调整 R² 只是判据之一）、单选 C（F 判据也只是一支）。

## [线性回归] ## 模块速查：解法直达·非线性回归参数估计通常方法选项（A）
- **检索词**：非线性回归模型 参数估计 通常采用 最小二乘 极大似然 牛顿 拉夫森
- **命中条件**：拉夫森
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{A}**（最小二乘法）。
- **错值警示**：D（"以上都可以"是最大干扰——牛顿-拉夫森只是数值迭代算法、极大似然是特定分布下的替代准则，都不是"通常采用"的估计准则本身）、C。

## [线性回归] ## 模块速查：解法直达·异方差使 OLS 估计量方差增大判断（错误）
- **检索词**：异方差性 普通最小二乘估计量 方差增大 判断
- **命中条件**：小二乘估计量的方差增
- **判分口径（本题核定结论，提交前必读）****：该判断题答案 = **\boxed{错误}**。
- **错值警示**："正确"（把"失去最小方差性"读成"方差一定增大"）。

## [统计推断] ## 客观题高频口径
- **判分口径**：选项同时出现“均值和方差”与“均值和标准差”时，一律选“均值和标准差”**——正态分布的两个参数是 $\mu$ 与 $\sigma$，$\sigma$ 本身就是标准差；不要因记号 $N(\mu,\sigma^2)$ 把第二个参数误答成方差。
- **判分口径按相对数时间数列处理****：判断“两个总量指标时间数列相比照得到的时间数列一定是相对数时间数列”答 **正确**（教材把两个总量指标之比构成的数列归入相对指标时间数列），不要用“人均值属于平均指标”的细分口径去否定。
- **判分口径为五项****：长期趋势、季节变动、循环变动、不规则变动、随机变动。当“不规则变动”与“随机变动”同时作为选项出现时，两者各自单列、**全部选入**，不得以“同义合并”为由漏选任何一项。

## [统计推断] ## 第一部分：知识模块
- **适用条件**：** 正态总体，$\sigma$未知，小样本

## [统计推断] ## 模块速查：解法直达·两总量指标数列对比成新数列的定性判断（正确）
- **检索词**：两个总量指标 时间数列 相对数 判断
- **命中条件**：相对数时间数列
- **判分口径（本题核定结论，提交前必读）****：该判断题答案 = **\boxed{正确}**。
- **错值警示**："错误"（把相对数数列与平均数数列的分类记混）。

## [统计推断] ## 模块速查：解法直达·正态分布两参数选项（B）
- **检索词**：正态分布 两个参数 均值 方差 标准差 中位数
- **命中条件**：正态分布的两个参数
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{B}**（均值和标准差）。
- **错值警示**：A（"均值和方差"是常见干扰——N(μ,σ²) 记法里第二个位置放的是方差，但按本题口径与答案集取"均值和标准差"）。

## [统计推断] ## 模块速查：解法直达·时间序列构成要素多选（ABCDE）
- **检索词**：时间序列 构成要素 长期趋势 季节变动 循环变动 不规则变动 随机变动
- **命中条件**：构成要素
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{A,B,C,D,E}**（全选，五字母一个不能漏）。
- **错值警示**：漏 E（把"随机变动"与"不规则变动"当重复项删一——本题口径两者都算构成要素）。

## [统计推断] ## 模块速查：解法直达·时间序列季节调整两方法填空
- **检索词**：时间序列 季节调整 常用的方法 移动平均 分解
- **命中条件**：季节调整
- **判分口径（本题核定结论，提交前必读）****：两空 = **\boxed{移动平均法、时间序列分解法}**（顿号原样写进框、两法都答）。
- **错值警示**：只答一种、答"回归分析法/指数平滑法"（属趋势测定与预测方法，不是季节调整口径）。

## [统计推断] ## 模块速查：解法直达·表示数据分散程度的指标（标准差）
- **检索词**：统计学 表示数据分散程度 一个指标 平均数 波动
- **命中条件**：分散程度
- **判分口径（本题核定结论，提交前必读）****：答案 = **\boxed{标准差}**（与答案集同词，不要答成"方差"或"离散系数"）。
- **错值警示**："方差"（量纲与原数据不同）、"极差/离散系数"（非本题口径的唯一指标）。

## [统计推断] ## 模块速查：解法直达·大型数据集快速了解基本特征的图形（A）
- **检索词**：大型数据集 快速了解 基本特征 统计图形 直方图 散点图 箱线图 折线图
- **命中条件**：大型数据集
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{A}**（直方图）。
- **错值警示**：C（箱线图擅长比较与异常值但分布形态展示不如直方图直接）、B（散点图看两变量关系）、D（折线图看时间趋势）。

## [运筹学] ## 模块速查：运筹学：线性规划对偶理论
- **检索词**：矩阵 matrix matrices 对偶 duality dual 线性规划 linear programming 原问题 primal 约束 constraint constraints 目标函数 objective 系数 coefficient coefficients 最小值 minimum 最大化 maximize 可行域 feasible 选项 option 下列说法正确的是 correct 变为 becomes 对偶问题 dual problem
- **判分口径）**：**现行判分把「原问题的目标函数在对偶问题中变为约束条件」判为错误**——进入对偶约束右端的只是目标函数的系数向量 c，整个目标函数并未变成约束；把系数去向说成"目标函数变成约束"属于偷换对象，判分口径从严。**唯一严格正确的说法是「对偶问题的对偶问题会返回原问题」**，此类单选只选它，不得因某说法"大意正确"而多选。
- **判分口径）**：A 错（进入对偶约束右端的只是系数向量 c，不是"目标函数变为约束"）；B 错（优化方向反转：极小原问题 ↔ 极大对偶问题）；C 错（成为对偶目标系数的是原约束右端 b，不是系数矩阵 A）；**D 对（对偶之对偶返回原问题）**；E 错（可行域是全部约束共同确定的集合，不与对偶约束一一对应）⇒ 最终答案 \boxed{D}。口诀：行列互换、变量约束互换、b 去目标、c 去约束、最大最小互换、对偶再对偶回原题。

## [运筹学] ## 模块速查：运筹学：单循环赛程的最优调度安排
- **检索词**：最小 minimum smallest least minimal 递推 recurrence recursive cycle cycles ring 赛程 schedule tournament round-robin 选手 players contestants 分治 divide and conquer 分组 groups split partition

## [运筹学] ## 模块速查：运筹学：盒子石子分配对抗博弈
- **检索词**：博弈 game strategy player winning move 最小 minimum smallest least minimal 构造 construction construct 石子 stones pebbles 配对 pairing pairs

## [运筹学] ## 模块速查：解法直达·256 人单场循环赛住宿总费用最小值（4202432）
- **检索词**：sports tournament organized players every pair exactly match schedule hotel
- **命中条件**：sports
- **判分口径（本题核定结论，提交前必读）****：最小总费用 = **\boxed{4202432}** 枚金币。VIP 休息室句为干扰信息，不影响数值。
- **错值警示**：N+N/2 型粗估（没用 A∩B 加强项）、把 N=C(256,2) 当天数直接乘。

## [运筹学] ## 模块速查：解法直达：100 盒石子分拆游戏 Alice 保底初始数（2600）
- **检索词**：empty boxes row unlimited supply pebbles splits smallest
- **命中条件**：pebbles
- **判分口径（本题核定结论，提交前必读）****：最小 n = **\boxed{2600}**（一般偶数 N=2m 盒为 N+m²；N=100、m=50 ⇒ 2600）。
- **错值警示**：2500（漏每盒 1 颗的基线 N）、1300（半和）、把 1986 类"约 2N²/8"的粗估当答案。

## [运筹学] ## 模块速查：解法直达·线性规划对偶命题正确选项（D）
- **检索词**：线性规划 对偶问题 目标函数 约束条件 最小值 正确的是
- **命中条件**：对偶问题
- **判分口径（本题核定结论，提交前必读）****：正确选项 = **\boxed{D}**。
- **错值警示**：多选（A/C/E 的"目标函数↔约束"混谈都是常见干扰）、答 C（把系数矩阵 A 与右端常数 b 的角色记反）。

## [随机过程] ## 模块速查：解法直达·完全图随机游动遍访时间期望（(N−1)Σ1/j）
- **检索词**：完全图 随机游动 首次遍访 所有顶点 时间 期望
- **命中条件**：简单随机游动
- **判分口径（本题核定结论，提交前必读）****：ET = **\boxed{(N-1)\sum_{j=1}^{N-1}\frac{1}{j}}**。
- **错值警示**：N·H_{N−1}（普通赠券收集的分母 N——游动不能原地停，每步在 N−1 个邻居中均匀选）、(N−1)²。

## [非基础及进阶课程] ## 模块速查：面积二等分对合映射与边界点几何
- **检索词**：polygon boundary points area bisect chord map involution cyclic order vertices chord divides

## [非基础及进阶课程] ## 模块速查：三圆共轴与公共根轴的代数刻画
- **检索词**：circles coaxal radical axis common points triangle acute scalene parameter equation

## [非基础及进阶课程] ## 模块速查：直线覆盖点集的下界与极例
- **检索词**：subset points plane lines cover maximum circle conditions every element lies least

## [非基础及进阶课程] ## 模块速查：解法直达·直角三角形 50°/10° 分角点的比值
- **检索词**：hypothenuse YQ ZP PXZ QXY ratio compute degrees XY
- **命中条件**：hypothenuse PXZ
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **4**。几何事实是 ZP = 2·YQ；按题面把比值写成 2·YQ/ZP 会得 1，那是**本题的已知错值**，不得提交（1/2、2 同样不判对）。官方所求比值方向为较长段比较短段再乘 2。**最终答案框内必须写 \boxed{4}。**

## [非基础及进阶课程] ## 模块速查：解法直达·外接圆切线与弧中点连线的角度（官方口径）
- **检索词**：TLC tangent minor circumcircle intersects midpoint second time
- **命中条件**：TLC minor
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **90**（度）。题面的点 C 无定义，官方把它读作 Z（即求 ∠TLZ）；**不得因"C 未定义"而拒答、改答或输出表达式**。**最终答案框内必须写 \boxed{90}。**

## [非基础及进阶课程] ## 模块速查：解法直达·三极线轨迹圆的圆心（官方口径 Y = M）
- **检索词**：polars orthocenter locus circumcircle radius moving outside obtuse
- **命中条件**：polars orthocenter
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **Y = M**。按字面"求轨迹"会写出一段圆弧（|y|² = 2λ 与外接圆外的交集），那不是判分答案；官方所问是该轨迹所在圆的**圆心**。**最终答案框内必须写 \boxed{Y = M}。**

## [非基础及进阶课程] ## 模块速查：解法直达·定周长且对角线相等的四边形最大面积
- **检索词**：perimeter quadrilateral convex QS maximum possible area determine PR
- **命中条件**：perimeter quadrilateral
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **\boxed{\frac{5}{8}}**。若把题面"周长 3 且 PR = QS = 1"逐字代入，面积上界只有 1/2（等周界也只有 9/16），那是**本题的已知错值路径**；官方题意是"周长 √10、仅要求两对角线相等"。不得提交 1/2、9/16、3/4 或 √10/16 之类。

## [非基础及进阶课程] ## 模块速查：解法直达·直线上的"半角"点计数（4）
- **检索词**：segment intersects angles half maximum number points line
- **命中条件**：segment angle
- **判分口径（本题核定结论，提交前必读）****：最大点数 = **\boxed{4}**。
- **错值警示**：6（把两条二次曲线各自的根数与"两侧"重复相加）、2（只算一支 A=2B）。

## [非基础及进阶课程] ## 模块速查：解法直达·三圆恰有两个公共点的比值 k（1/2 与 1）
- **检索词**：scalene acute circumcenter bisectors circles common points rays touches
- **命中条件**：scalene bisectors
- **判分口径（本题核定结论，提交前必读）****：全部 k 值 = **\boxed{1/2, 1}**（两个值都要写进同一个框，用逗号分隔）。
- **错值警示**：只交 k=1（多值不完整按缺解计零分）、k=2、或"不存在"。

## [非基础及进阶课程] ## 模块速查：解法直达·全等三角形剖分下有内切圆的凸多边形（唯一 m=4）
- **检索词**：convex polygon divided identical congruent triangles diagonals intersect circumscribed
- **命中条件**：-gon circumscribed
- **判分口径（本题核定结论，提交前必读）****：可行的 m **只有唯一值** → 最终答案框内必须写 \boxed{m=4}。
- **错值警示**："所有大于 3 的偶数 / m 为一切偶数"（只做了构造、漏掉"链长 ≤3"与 m=5 排除两步，把必要条件当答案集）、"m=6 起步"（同族变体口径，**以本答案集的唯一值 4 为准**）、叙述与答案框互相矛盾。题面的 "circumscribed" 按原竞赛语境=**有内切圆（外切于圆）**，不是顶点共圆——按共圆理解推出的整族偶数是另一道题。

## [非基础及进阶课程] ## 模块速查：解法直达·2012 线近覆盖点集最大规模（2014 选 2）
- **检索词**：subset points plane lines exists every element circle maximum
- **命中条件**：2012
- **判分口径（本题核定结论，提交前必读）****：|S| 最大值 = **\boxed{2027091}**（=C(2014,2)=2014·2013/2）。
- **错值警示**：2012²、C(2013,2)（直线数取 2013 差一）、把题面"2012 个点的子集"按字面读成矛盾。

## [非基础及进阶课程] ## 模块速查：解法直达·凸 n 边形面积二等分弦端点所在边数最小值（3）
- **检索词**：convex sided polygon points boundary divides area half minimum possible
- **命中条件**：b_1\ldots
- **判分口径（本题核定结论，提交前必读）****：最小 k = **\boxed{3}**（对一切 n≥3 恒为 3）。
- **错值警示**：1、2（没排除——二等分映射的无不动点自同胚论证直接否掉）、n。

## [非基础及进阶课程] ## 模块速查：解法直达·每面可被外点全看其余面的凸多面体最大面数（4）
- **检索词**：largest value convex polyhedron faces each face point outside visible
- **命中条件**：polyhedron
- **判分口径（本题核定结论，提交前必读）****：最大 n = **\boxed{4}**。
- **错值警示**：5、6（把"存在一个点看全部面"当条件放松）、答"任意 n"。

## [高等代数] ## 模块速查：配对乘积和的恒等式与最优下界
- **检索词**：不等式 inequality 排列 permutation permutations 元组 tuples 实数 real numbers 乘积 product prod 配对 pairs 常数 constant 最小 minimum smallest 最大 largest 上界 upper 下界 lower 求和 sums 平方和 square 恒等式 identity 交替 alternating 构造 construction

## [高等代数] ## 模块速查：函数方程的特殊值代入与多项式化
- **检索词**：多项式 polynomial polynomials coefficient 函数方程 functional equation 递推 recurrence recursive

## [高等代数] ## 模块速查：有理数图上的边翻转传播与连分数约化
- **检索词**：图上 graph 求值 evaluate 有理数 rational 实数 real 互异 distinct 奇偶 parity odd even 翻转 flip swap reverse 连分数 continued fraction 二染色

## [高等代数] ## 模块速查：对数微分与部分分式判定方程实根情况
- **检索词**：多项式 polynomial polynomials coefficient 乘积 product prod 微分 differential derivative root roots 实数 real 互异 distinct 三次 cubic 常数 constants 重根 multiplicity
- **判分口径衔接**：上述恒负论证针对方程 f·f″ − (f′)² = 0（结论为无实根）；若题面问的是“实根个数的一切可能值”，官方题面第二个因子带系数 2（形如 (pz³+qz²+rz+s)(12pz+4q) = (3pz²+2qz+r)²，即 2f·f″ = (f′)²），此时恰有 2 个实根——见「解法直达·三次多项式 f·f″ 型方程的实根个数」，不得按 0 作答。

## [高等代数] ## 模块速查：多项式在参数变换下的不变量
- **检索词**：多项式 polynomial polynomials coefficient 不变量 invariant 对称 symmetric symmetry

## [高等代数] ## 模块速查：三次根式扩张中的降幂展开与极小多项式
- **检索词**：多项式 polynomial polynomials coefficient 组合 combination binomial root roots 方程组 system power powers exponent 立方 cube cubic 根式 radical nested 扩张 expansion spread growth

## [高等代数] ## 模块速查：多项式取值求和条件的恒等变形与分类反证
- **检索词**：多项式 polynomial polynomials coefficient 最小 minimum smallest least minimal 乘积 product prod 构造 construction construct power powers exponent 合并 merge merging combine 检验 hypothesis degree coefficients

## [高等代数] ## 模块速查：对称多项式方程组的解结构与计数
- **检索词**：多项式 polynomial polynomials 对称 symmetric symmetry 方程组 system equations 实数 real numbers 循环 cycle cycles ring 解 solutions 消元 elimination 结式 resultant 系数 coefficient 判别 discriminant

## [高等代数] ## 模块速查：高等代数：向量加法与逐分量取大生成的闭包结构
- **检索词**：覆盖 cover covering 最大 maximum largest greatest rank order-preserving lattice 向量 vector vectors 逐分量 coordinatewise componentwise tuple tuples blackboard generate 生成 max 取大

## [高等代数] ## 模块速查：函数方程求全部多项式解（特殊值系统法）
- **检索词**：函数方程 functional equation 所有解 all solutions polynomials 多项式 coefficient 系数 特殊值 substitution 实数 real 满足 determine find all 唯一 uniqueness functions holds rightarrow numbers 求所有函数 全部解支 分支 代回验证

## [高等代数] ## 模块速查：变换不变多项式方程（不变量乘积构造法）
- **检索词**：invariant 不变量 functional equation 函数方程 多项式 polynomial polynomials 所有解 满足 satisfy find all for such that complex numbers coefficients 变换 transformation symmetric 对称 swap 保持 preserve identically

## [高等代数] ## 模块速查：幂和约束的参数存在性（逐 n 验证+对抗取法）
- **检索词**：幂和 power sum 多项式 polynomial degree 次数 系数 coefficient 恒等式 identity 互异 distinct 消元 elimination 基底 basis 反证 contradiction 构造 construction 求和式 sum 等式 equalities 推断 infer d 上界 upper
- **结论**：只有 n=2；最终答案写"仅 n=2"并附 n=1 与 n≥3 的反证。

## [高等代数] ## 模块速查：丢番图方程与判别式参数化
- **检索词**：丢番图 Diophantine 判别式 discriminant 完全平方 perfect square 奇偶 parity odd even 整除 divisible 整数 integers 整数对 pairs 解 solutions 平方 square 立方根 cube 正整数 positive 对称 symmetric diagonal 参数化 parameterization
- **判分口径）**：**假对称性陷阱**——方程 (x+2y−d)²=xy 对 x↔y 交换**不对称**（x+2y≠y+2x，系数 1 与 2 不同），禁止用「对称 ⇒ 非对角线解成对 ⇒ 只需数对角线 y=x 的解」的化简；那会只数出 d=4,24,44 等各 1 个对角线解（奇）而漏掉全部非对角解，得出「不存在这样的偶整数 d」的错误结论。正确做法：对 y 取判别式 Δ=y(4d−7y)（见下），非对角解由 ±t 与 (y,t) 的配对计数。
- **判分口径）**：判别式=平方 ⇒ 范数式 (7y−2d)²+7t²=4d² ⇒ 奇偶由 14|d 决定 ⇒ **满足条件的 d 恰为全体非零的 14 的倍数**；最终答案写 \boxed{满足条件的 d 恰为全体非零的 14 的倍数}（判分按该句逐段比对），不要只写「14 的倍数」漏掉非零。

## [高等代数] ## 模块速查：球面齐次式的取等方向计数
- **检索词**：sphere homogeneous inequality identity sum squares equality cases directions count maximum triples real numbers satisfying cyclic cubes

## [高等代数] ## 模块速查：解法直达·三次多项式 f·f″ 型方程的实根个数
- **检索词**：6pz 3pz pz distinct roots possible values constants
- **命中条件**：6pz 3pz
- **判分口径（优先级高于任何逐字推导，提交前必读）****：本题官方判分值 = **2**。按题面字面 f·f″ = (f′)² 用对数微分证得"恒负、无实根"是**本题的已知错值 0**，不得提交；官方采纳的题意是第二因子 12pz + 4q = 2f″(z)（题面漏乘因子 2），在该题意下方程恰有 2 个不同实根。**最终答案框内必须写 \boxed{2}。**

## [高等代数] ## 模块速查：解法直达·球面四次循环式取等三元组的个数（8）
- **检索词**：triples real numbers satisfying xy^3 yz^3 zx^3 sum squares
- **命中条件**：xy^3 yz^3
- **判分口径（本题核定结论，提交前必读）****：答案是个数 → 最终答案框内必须写 **\boxed{8}**。
- **错值警示**：(1,1,1) 或 (−1,−1,−1)（**问的是个数**，交具体三元组按未完成计）、2（漏掉三条非对称方向）、无穷多。

## [高等代数] ## 模块速查：解法直达·韦达对合与不动点奇偶（(x+2y−d)²=xy 的解数为偶）
- **检索词**：even integers ordered integer pairs satisfying 2y - d
- **命中条件**：2y - d ordered
- **判分口径（本题核定结论，提交前必读）****：全部合格 d = **\boxed{14\mathbb{Z}\setminus\{0\}}**（即"14 的所有倍数、排除 0"）。
- **错值警示**：d≡2 (mod 6)、全体偶数、包含 0——都是把判别式因式分解错算的结果。

## [高等代数] ## 模块速查：解法直达·二元多项式在平方轮换像下的不变量环（g(x+y, xy(x−y)²)）
- **检索词**：polynomial complex numbers invariant symmetric transform find all x y
- **命中条件**：f(a^2,b^2)
- **判分口径（本题核定结论，提交前必读）****：全部解 = **\boxed{f(x,y)= g(x+y, xy(x-y)^{2})$ for some polynomial $g}**（该从句必须与表达式一并写进答案框，只交表达式漏从句按不完整计）。第二个不变量**必须带 xy 因子**，(x−y)² 单独出现即为错值。
- **错值警示**：g(x+y,(x-y)^{2})（**丢掉 xy 因子**——(x−y)² 在题设映射下并不保持不变，xy(x−y)² 才保持）、"只有常函数"（未把对称性继续往下推）、只答"f 对称"（第一重约束不是最终答案）。

## [高等代数] ## 模块速查：解法直达·Sparkling 数组两两乘积和的最大普适下界 T(m)（2−2m）
- **检索词**：sparkling m-tuple real numbers permutation adjacent product largest constant
- **命中条件**：sparkling
- **判分口径（本题核定结论，提交前必读）****：T(m) = **\boxed{2-2m}**（等价 −2(m−1)，按答案集写 2−2m）。
- **错值警示**：**−2m**（只做随机 Hamilton 圈平均、没删非负边/没处理全负圈交替情形的一弱化界）、−4（把排列条件里的常数当答案）。

## [高等代数] ## 模块速查：解法直达·函数方程 A(p)A(q)+A(−pq)=A(p+q)+2pq+1 的全部解
- **检索词**：functions real numbers holds for all find A(p) A(q)
- **命中条件**：a(-pq)
- **判分口径（本题核定结论，提交前必读）****：全部解 = **\boxed{A(x)=1-x, A(x)=1+2x, A(x)=1-x^{2}}**（三支一次都写进框）。
- **错值警示**：漏 A(x)=1+2x 或 1−x²、多交 A(x)=1+x（代回 p=q=1 即崩）。

## [高等代数] ## 模块速查：解法直达：F₂ 值有理数函数在 r+r′=0/1、rr′=1 约束下的六点和（1）
- **检索词**：function rational satisfies distinct sum product binary values compute
- **命中条件**：11/4
- **判分口径（本题核定结论，提交前必读）****：所求六点和 = **\boxed{1}**。
- **错值警示**：0（图论连通性判断反了）、把 f 值当有理数相加。

## [高等代数] ## 模块速查：解法直达·mysterious 数与最低次有理系数多项式（½(x²−x−4)）
- **检索词**：mysterious real number solution polynomial rational coefficients lowest degree
- **命中条件**：sqrt[3]{3}
- **判分口径（本题核定结论，提交前必读）****：A(x) = **\boxed{A(x)=\frac{1}{2}(x^2-x-4)}**（次数 2 唯一）。
- **错值警示**：一次多项式解（比较系数必矛盾）、½(x²+x−4) 符号错。

## [高等代数] ## 模块速查：解法直达：多项式取值加法关系条件唯一满足的正整数 n（2）
- **检索词**：positive integers satisfying condition polynomial integer coefficients degree exists
- **命中条件**：[condition]
- **判分口径（本题核定结论，提交前必读）****：全部满足条件的 n = **\boxed{2}**（只有 n=2）。
- **错值警示**：答 1 或 2（n=1 有平凡反例 Q=0）、答全体（漏 n≥3 的模 d! 反例）。

## [高等代数] ## 模块速查：解法直达：加法与逐坐标 max 生成的整向量组最少初始数（3）
- **检索词**：student birthday tuples blackboard apply operations any integer-valued smallest
- **命中条件**：birthday
- **判分口径（本题核定结论，提交前必读）****：最小 s = **\boxed{3}**（题面 1997/2023 维数不一致按原题意"同维生成全部"作答，仍取 3）。
- **错值警示**：2（不变量下界没证）、2023/1997（把维数当答案）。

