# 智能体评测诊断报告 — official112_local_0910_rejudged

> 数据文件：`D:\挑战杯\results\official112_local_0910_rejudged.jsonl`　｜　已完成 **112** 题

## 〇、总览

- 正确率：**21/112 = 18.8%**（未判分 0 题）
- 单题耗时合计：**30.58 h**（各题耗时累加，非墙钟）；单题均值 **983s** / 中位 1089s / 最大 1384s
- 超 1200s 截断：**25** 题（22%）
- 子目标平均步数：5.5 步/题

## 一、错在哪一环节（环节归因）

| 环节 | 关键指标 | 数值 | 判读 |
|---|---|---|---|
| ① 分类 | 学科分布 | 见附录 A | 未见分类异常 |
| ② 理解·形式化 | Lean 前置验证 verdict=fail | **13** 题 | 题面理解或形式化存在缺口 |
| ② 理解·形式化 | 存在 formal_gaps 形式化缺口 | 13 题 | 同上 |
| ③ 规划 | 骨架评审判 overall=replan | 90 题 | 评审频繁触发重生成 |
| ③ 规划 | 骨架评审降级放行 | 0 题 | — |
| ④ 求解 | 子目标求解失败（空/占位） | 3 题 | 硬失败占比低 |
| ④ 求解 | **子目标均有输出但结论错** | **104** 题 | **核心瓶颈：中间推理结论错误** |
| ④ 求解 | 触发过 revise 自我修订 | 21 题 | 修订机制很少被调用 |
| ④ 求解 | 计算工具被实际调用 | 0 题 | 工具完全未被使用 |
| ⑤ 验证 | AuditGate 判定 unknown | **623/623** | **验证器无法判定 → 拦不住错解** |
| ⑤ 验证 | AuditGate 出现 reject 的题 | 0 题 | 拒绝率极低 |
| ⑤ 验证 | AuditGate 出现 accept 的题 | 0 题 | — |
| ⑤ 验证 | **数值攻击发现反例** | **47** 题 | **检测层有效**（但见 1.2） |
| ⑤ 验证 | Lean final_gate 判 proof_invalid 的题 | 17 题 | 判定存在，但未被有效利用 |
| ⑥ 预算 | 出现预算跳过 | 9 题 | 部分题步数未跑完 |
| ⑦ 输出判分 | 错误分类 | 见第二节 | 以「求解算错」为主 |

### 1.1 验证环节有效性：Lean 判定 × 实际正确率

| Lean final_gate 判定 | 题数 | 其中正确 | 该组正确率 |
|---|---|---|---|
| answer_valid | 53 | 12 | 23% |
| unknown | 25 | 6 | 24% |
| proof_invalid | 17 | 2 | 12% |
| none | 16 | 1 | 6% |
| 无记录 | 1 | 0 | 0% |

degraded 标记分布：`{'strict_reject': 31, 'time_critical': 16}`（`time_critical` = 因时间紧迫降级跳过 Lean 把关）

> **判读**：若验证器有效，「判定通过」组的正确率应显著高于「判定拒绝」组。上表两组正确率接近，说明 Lean 闸门的判定对最终对错的**区分能力不足**——尤其 `answer_valid`（判定通过）组仍有大量错题，即「答案形式有效」被当成了「答案正确」。

### 1.2 检测 → 处置联动（关键缺口）

| 观测 | 数值 |
|---|---|
| 数值攻击发现反例、且最终答错 | **36** 题 |
| 其中真正触发了 revise 修订 | **6** 题 |
| **检测到问题但未处置（直接输出）** | **30** 题 |

> **结论**：验证层已能定位问题（数值攻击证伪、Lean 判 `proof_invalid`、`revise_feedback` 已写出具体错误指认），但这些信号未转化为「必须重解」的强制动作，错误答案仍被放行。**瓶颈不在检测能力，而在检测结果 → 修订/拦截的联动。**

**环节归因结论**：错误主要产生于 **④ 求解环节（中间子目标结论错误）**；本应兜底的 **⑤ 验证环节未能拦截**——AuditGate 判定几乎全部为 `unknown`（既非接受也非拒绝）、Lean 闸门同样多为 `unknown`，导致错误答案直达输出。理解（②）与预算（⑥）为次要因素。

## 二、错误情况

错题 **91** 题，分类分布：

| 错误分类 | 题数 | 占比 | 含义 |
|---|---|---|---|
| value_wrong | 48 | 53% | 真算错（裸数值不等） |
| expr_wrong | 38 | 42% | 表达式/推理解答错 |
| format_unresolved | 4 | 4% | 答案未定型（含未求值符号） |
| empty_output | 1 | 1% | 空输出/只剩定界符 |

### 2.1 错题明细

| 题号 | domain | 耗时 | 分类 | 标准答案 | 模型答案 |
|---|---|---|---|---|---|
| official112-000 | 离散数学 | 1063s | expr_wrong | `20460` | `\boxed{2^{19} \cdot 19!}` |
| official112-001 | 高等代数 | 1151s | expr_wrong | `$2-2m$` | `\boxed{-4}` |
| official112-002 | 数学分析 | 1090s | expr_wrong | `$\frac{1}{2}$` | `\boxed{\sqrt{5}-2}` |
| official112-003 | 离散数学 | 1125s | value_wrong | `2026, 2030` | `\boxed{2026}` |
| official112-004 | 离散数学 | 1111s | value_wrong | `2024` | `\boxed{674}` |
| official112-007 | 离散数学/高等代数 | 1384s | value_wrong | `1` | `\boxed{0}` |
| official112-008 | 数学分析 | 1087s | expr_wrong | `603729` | `\boxed{2 \times 777^2}` |
| official112-009 | 数学分析 | 1202s | value_wrong | `16` | `\boxed{1}` |
| official112-010 | 数学分析/离散数学/高等代数 | 1039s | value_wrong | `2` | `\boxed{0}` |
| official112-011 | 高等代数 | 860s | empty_output | `$f(x,y)= g(x+y, xy(x-y)^{2})$ for some polynomial $g$` | `\boxed` |
| official112-013 | 离散数学 | 1221s | value_wrong | `48` | `\boxed{50}` |
| official112-014 | 离散数学 | 1022s | value_wrong | `997008, 995026, 995018` | `\boxed{993024}` |
| official112-015 |  | 1333s | format_unresolved | `2` | `\boxed{n \geq 2}` |
| official112-016 | 离散数学 | 1000s | value_wrong | `21` | `\boxed{20}` |
| official112-017 | 离散数学/高等代数 | 1189s | value_wrong | `8` | `\boxed{6}` |
| official112-020 | 离散数学 | 1072s | expr_wrong | `$\binom{2k}{k}^2$` | `\boxed{2^{k^2}}` |
| official112-021 |  | 909s | value_wrong | `21` | `\boxed{39}` |
| official112-022 | 离散数学 | 1106s | value_wrong | `25502500` | `\boxed{23341}` |
| official112-023 | 离散数学 | 1191s | value_wrong | `290` | `\boxed{674}` |
| official112-025 | 离散数学 | 1363s | value_wrong | `506` | `\boxed{2}` |
| official112-028 | 离散数学 | 1166s | value_wrong | `43` | `\boxed{45}` |
| official112-030 | 非基础及进阶课程 | 1085s | value_wrong | `2027091` | `\boxed{4024}` |
| official112-031 | 离散数学 | 1214s | value_wrong | `1026169` | `\boxed{683109}` |
| official112-032 | 离散数学 | 1168s | value_wrong | `512` | `\boxed{402}` |
| official112-033 | 离散数学 | 1257s | value_wrong | `1057` | `\boxed{2016}` |
| official112-034 | 离散数学 | 1187s | value_wrong | `56` | `\boxed{2850}` |
| official112-035 | 离散数学 | 1215s | value_wrong | `3986729` | `\boxed{4000000}` |
| official112-037 | 离散数学 | 1175s | expr_wrong | `taking the empty card` | `\boxed{\text{The first player must not take the empty ca …` |
| official112-038 | 离散数学 | 1172s | value_wrong | `3024` | `\boxed{2016}` |
| official112-039 | 离散数学 | 1112s | value_wrong | `6` | `\boxed{4}` |
| official112-041 | 离散数学 | 1215s | value_wrong | `31395` | `\boxed{2025}` |
| official112-042 | 离散数学 | 1199s | value_wrong | `600` | `\boxed{800}` |
| official112-043 | 运筹学 | 1075s | value_wrong | `4202432` | `\boxed{2816}` |
| official112-044 | 离散数学 | 1182s | value_wrong | `96` | `\boxed{197}` |
| official112-045 | 运筹学 | 1016s | value_wrong | `2600` | `\boxed{100}` |
| official112-046 | 离散数学 | 1203s | value_wrong | `7311` | `\boxed{86}` |
| official112-047 | 离散数学 | 1206s | value_wrong | `64` | `\boxed{11}` |
| official112-048 |  | 1208s | value_wrong | `8` | `\boxed{3}` |
| official112-049 | 离散数学 | 906s | value_wrong | `81729648000` | `\boxed{5}` |
| official112-050 |  | 1326s | value_wrong | `506` | `\boxed{674}` |
| official112-051 | 离散数学 | 1065s | expr_wrong | `2278125` | `\boxed{2023^2}` |
| official112-052 |  | 1122s | value_wrong | `2` | `\boxed{3}` |
| official112-053 | 非基础及进阶课程/高等代数 | 1122s | value_wrong | `3` | `\boxed{1998}` |
| official112-054 | 离散数学 | 1239s | value_wrong | `12013` | `\boxed{1521}` |
| official112-055 | 离散数学 | 1329s | value_wrong | `18750000` | `\boxed{250000}` |
| official112-056 | 离散数学 | 1057s | value_wrong | `2450` | `\boxed{36}` |
| official112-057 | 离散数学 | 1230s | expr_wrong | `$\lambda^{st}n^{s+t}$` | `\boxed{(\lambda^{st} - o(1)) n^{s+t}}` |
| official112-058 | 离散数学 | 1088s | value_wrong | `4181` | `\boxed{1876}` |
| official112-059 | 离散数学 | 1379s | expr_wrong | `85383238549` | `\boxed{16! - 15655}` |
| official112-060 | 离散数学 | 883s | expr_wrong | `$\lambda^8 + 36\lambda^7 + 210\lambda^6 + 462\lambda^5 + …` | `\boxed{1 + 15\lambda + 91\lambda^2 + 286\lambda^3 + 495\ …` |
| official112-061 | 离散数学 | 1352s | value_wrong | `75` | `\boxed{1}` |
| official112-062 |  | 845s | value_wrong | `4` | `\boxed{1}` |
| official112-064 |  | 1089s | format_unresolved | `4` | `\boxed{m\text{ is even}}` |
| official112-066 |  | 1060s | value_wrong | `4` | `\boxed{3}` |
| official112-067 | 非基础及进阶课程 | 1208s | value_wrong | `1/2, 1` | `\boxed{2}` |
| official112-069 | 非基础及进阶课程 | 1230s | expr_wrong | `$Y = M$` | `\boxed{\text{The circumcircle of triangle } PQR}` |
| official112-070 | 非基础及进阶课程 | 1318s | value_wrong | `$\frac{5}{8}$` | `\boxed{\dfrac{1}{2}}` |
| official112-072 | 离散数学 | 1116s | expr_wrong | `$(n-2)2^n +1$` | `\boxed{1}` |
| official112-073 | 离散数学 | 832s | expr_wrong | `$(n^2 +3n+2, n^3 + 4n^2 + 3n -1)$ for $n \ge 1$` | `\boxed{\text{No solutions}}` |
| official112-074 | 数学分析 | 853s | expr_wrong | `$g(x)=c, g(x)=\lceil x \rceil, g(x)=\lfloor x \rfloor$` | `\boxed{g(x) = c \text{ for some constant } c \in \mathbb …` |
| official112-075 | 离散数学 | 1082s | value_wrong | `69169` | `\boxed{264}` |
| official112-076 | 离散数学 | 1019s | format_unresolved | `1,3,5` | `\boxed{u \geq 3}` |
| official112-077 | 离散数学 | 1125s | expr_wrong | `$5(l-1)^2$` | `\boxed{2}` |
| official112-079 | 数学分析 | 1089s | expr_wrong | `$\{(a,b):ab \geq e^3\}$` | `\boxed{(a, b) \text{ 为正实数对，满足 } ab \ge e^2}` |
| official112-080 | 离散数学 | 1010s | value_wrong | `146250` | `\boxed{9867312}` |
| official112-081 | 高等代数 | 1019s | expr_wrong | `all multiples of 14, excluding 0` | `\boxed{d=14k\ (k\in \mathbb{Z},k\neq 0)}` |
| official112-082 | 离散数学 | 1199s | expr_wrong | `$\lfloor \frac{p}{9} \rfloor$` | `\boxed{p - 9}` |
| official112-083 | 离散数学 | 1115s | value_wrong | `939` | `\boxed{499}` |
| official112-085 | 离散数学 | 1062s | expr_wrong | `$\lfloor \frac{a+2}{2}\rfloor +\lfloor \frac{a+2}{3}\rfl …` | `\boxed{a+1}` |
| official112-086 |  | 510s | expr_wrong | `\( \mathbb{Q}(5^{1/4},\zeta_8),\ 16,\ \text{是}  \)` | `分裂域 $E = \mathbb{Q}(\sqrt[4]{5}, i)$，$[E:\mathbb{Q}] = 8 …` |
| official112-088 |  | 497s | expr_wrong | `\( AB  \)` | `\boxed{A,B}` |
| official112-089 | 概率论 | 1200s | value_wrong | `5129` | `\boxed{5117}` |
| official112-090 | 随机过程 | 576s | expr_wrong | `$(N-1)\sum_{j=1}^{N-1}\frac{1}{j}$` | `\boxed{(N-1)H_{N-1}}` |
| official112-091 |  | 557s | expr_wrong | `${\hat{f}(\xi) = \frac{2}{1 + \xi^2}}$` | `\boxed{\frac{2e^{i\omega}}{1+\omega^{2}}+\frac{\pi}{2}e^ …` |
| official112-092 |  | 725s | expr_wrong | `在点 \(\left(\frac12, \frac{\sqrt{3}}{2}\right)\) 处（对应 \(\ …` | `\boxed{4}` |
| official112-093 |  | 803s | expr_wrong | `\( CE \)` | `\boxed{C}` |
| official112-094 |  | 332s | expr_wrong | `\( BCD \)` | `\boxed{BCD}` |
| official112-095 |  | 1190s | expr_wrong | `Lempel–Ziv 短语分解为   \[ (0,a),\ (1,b),\ (2,a),\ (1,c),\ (5 …` | `Lempel-Ziv 分解为短语：a, b, ab, abc, abcde。` |
| official112-096 |  | 546s | expr_wrong | `\( D  \)` | `AD` |
| official112-097 | 偏微分方程 | 542s | expr_wrong | `$L^*v = \sum_{i,j=1}^n \partial_j(a_{ij} \partial_i v) - …` | `\boxed{L^* v = \sum_{i,j=1}^n \partial_j (a_{ij} \partia …` |
| official112-099 |  | 393s | expr_wrong | `\(\boxed{\text{有限差分法、有限元法（或有限体积法）}}\)` | `\boxed{有限差分法}` |
| official112-100 |  | 675s | value_wrong | `函数 \( f(x)=\sin(x) \) 在 \( x=\frac{\pi}{4} \) 处的一阶导数（中心差 …` | `\boxed{0.70701}` |
| official112-101 | 统计推断 | 404s | expr_wrong | `正确` | `\boxed{×}` |
| official112-102 | 数值分析/统计推断 | 145s | expr_wrong | `B` | `\boxed{A}` |
| official112-103 | 统计推断 | 326s | expr_wrong | `$A,B,C,D,E$` | `\boxed{ABCD}` |
| official112-104 | 统计推断 | 147s | format_unresolved | `移动平均法、时间序列分解法` | `\boxed{X-11方法, SEATS方法}` |
| official112-105 | 统计推断 | 209s | expr_wrong | `标准差` | `\boxed{方差}` |
| official112-106 | 线性回归/统计推断 | 144s | expr_wrong | `A` | `\boxed{C}` |
| official112-108 | 线性回归 | 137s | expr_wrong | `异方差性不会导致参数估计量的偏误，但会使传统方差估计失效，即低估或高估真实方差，导致OLS估计量不再是有效估计。` | `\boxed{增大}` |
| official112-110 |  | 648s | expr_wrong | `A` | `\boxed{D}` |
| official112-111 | 线性回归 | 509s | expr_wrong | `错误` | `\boxed{正确}` |

### 2.2 典型错题的错误定位（revise_feedback 原文摘录）

- **`official112-000`**（expr_wrong）
  - 【关键错误（必须修正，否则整条推理链作废）】 1. 位置：“子目标 #2「证明每列恰有一个顶点在路径中」”    问题：该结论错误。路径是 S 的全排列，必须访问所有 60 个顶点，每列有 3 个顶点，因此每列必须被访问 3 次，而非 1 次。原论证混淆了'列被进入/离开的次数'与'列中顶点被访问的次数'，导致后续所有基于'每列恰有一个顶点'的推理（如垂直转移次数、行遍历顺序等）全部失效。 2. 位置：“子目标 #3「证明垂直转移恰有 2 次」”    问题：该结论基于错误的子目标 2。实际上，由于每列有 3 个顶点且路径必须访问所有顶点，垂直转移次数远多于 2 次（需要在每列内上下移动多次）。原论证错误地假设每列仅访问一次，导致对垂直转移次数的错误计算。 3. 位置：“子目标 #4「证明行遍历顺序必为 2→1→0」”    问题：该结论基于错误的子目标 2 和 3。实际上，路径可以在不同列之间反复上下移动，行遍历顺序不一定是严 …
- **`official112-002`**（expr_wrong）
  - [数值攻击] 蓝图声称极值 0.6180339887498949 已被数值采样证伪（发现 0.0）。请重新推导极值，不要沿用蓝图的候选值。数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 0.618034——声称的极值不成立
- **`official112-021`**（value_wrong）
  - 所有候选均未获验证通过，请重新审题并纠正推理错误。 候选答案无法解析为有效数学表达式
- **`official112-031`**（value_wrong）
  - [数值攻击] 蓝图声称极值 1025157.0 已被数值采样证伪（发现 0.0）。请重新推导极值，不要沿用蓝图的候选值。数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 1025157.000000——声称的极值不成立
- **`official112-032`**（value_wrong）
  - [审核闸门反馈] 上一候选 (#1) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约束 → 结论 = 答案），逐字锚定题目数值。 [审核闸门反馈] 上一候选 (#2) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约束 → 结论 = 答案），逐字锚定题目数值。 [审核闸门反馈] 上一候选 (#3) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题 …
- **`official112-033`**（value_wrong）
  - [数值攻击] 蓝图声称极值 2016.0 已被数值采样证伪（发现 0.0）。请重新推导极值，不要沿用蓝图的候选值。数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 2016.000000——声称的极值不成立
- **`official112-038`**（value_wrong）
  - [数值攻击] 蓝图声称极值 2016.0 已被数值采样证伪（发现 0.0）。请重新推导极值，不要沿用蓝图的候选值。数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 2016.000000——声称的极值不成立
- **`official112-043`**（value_wrong）
  - 1. The claim that each non‑center player can stay only 2 days is false. A non‑center player must play 255 matches (1 against the centre player and 254 against other non‑center players). With only one match per day, such a player must be present on at least 255 days, so a 2‑day stay is impossible.  2. The total cost cannot be 765. There are \(\binom{256}{2}=32640\) matches, each involving two players; therefore the su …
- **`official112-044`**（value_wrong）
  - [审核闸门反馈] 上一候选 (#1) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约束 → 结论 = 答案），逐字锚定题目数值。 [审核闸门反馈] 上一候选 (#2) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约束 → 结论 = 答案），逐字锚定题目数值。 [审核闸门反馈] 上一候选 (#3) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题 …
- **`official112-045`**（value_wrong）
  - 1. 位置：“子目标 #3「子目标3: Alice initially distributes 100 pebbles …」”      问题：The solution assumes Alice can initially distribute 100 pebbles as exactly 1 pebble per box, but the problem requires Alice to take n pebbles (which is exactly the number she distributes initially). For n=100, this is possible. However, the solution does not prove that this distribution prevents Bob from winning. It fails to address whether Bob c …
- **`official112-049`**（value_wrong）
  - 【关键错误（必须修正，否则整条推理链作废）】 1. 位置：“子目标 #2: Show that if N ≥ 9, there exists a pair of rows with all columns having difference ≤1... N ≤ 8”    问题：The proof that N ≤ 8 is entirely missing. The solution only states the conclusion without any mathematical argument. The described approach (modeling permutations as Hamiltonian paths and using edge counting) is not executed, making it impossible to verify the upper bound. This i …
- **`official112-051`**（expr_wrong）
  - 【关键错误（必须修正，否则整条推理链作废）】 1. 位置：“子目标 #5: After the gardener's move, at most 13 squares increase by 1 (the chosen square and its up to 8 neighbors).”    问题：The gardener's move affects the chosen square and its up to 8 neighbors, totaling at most 9 squares, not 13. This is a factual error that invalidates the subsequent calculation of the change in Φ (the sum of the top 10 heights). The claim that Φ can be kept non-increa …

## 三、耗时情况

### 3.1 分桶 × 正确率

| 耗时桶 | 题数 | 平均耗时 | 桶内正确率 |
|---|---|---|---|
| 120-540s | 14 | 315s | 2/14 = 14% |
| 540-1200s | 73 | 1016s | 16/73 = 22% |
| >=1200s(截断) | 25 | 1259s | 3/25 = 12% |

### 3.2 阶段耗时占比

| 阶段 | 累计 | 占比 |
|---|---|---|
| 分类/难度 | 500s | 0.5% |
| 预验证 | 1172s | 1.1% |
| 子目标主链 | 57424s | 52.2% |
| 求解 | 21020s | 19.1% |
| Lean候选筛选 | 344s | 0.3% |
| 补全 | 1177s | 1.1% |
| 验证 | 2937s | 2.7% |
| 修订/兜底 | 14357s | 13.0% |
| 其他 | 11121s | 10.1% |

### 3.3 最耗时的 12 题

| 题号 | 耗时 | 对错 | 分类 |
|---|---|---|---|
| official112-007 | 1384s | ❌ | value_wrong |
| official112-059 | 1379s | ❌ | expr_wrong |
| official112-025 | 1363s | ❌ | value_wrong |
| official112-061 | 1352s | ❌ | value_wrong |
| official112-015 | 1333s | ❌ | format_unresolved |
| official112-055 | 1329s | ❌ | value_wrong |
| official112-050 | 1326s | ❌ | value_wrong |
| official112-070 | 1318s | ❌ | value_wrong |
| official112-033 | 1257s | ❌ | value_wrong |
| official112-054 | 1239s | ❌ | value_wrong |
| official112-057 | 1230s | ❌ | expr_wrong |
| official112-069 | 1230s | ❌ | expr_wrong |

## 附录 A：学科分布

| 学科 | 题数 |
|---|---|
| 离散数学 | 51 |
| 未标注 | 25 |
| 高等代数 | 5 |
| 数学分析 | 5 |
| 非基础及进阶课程 | 5 |
| 统计推断 | 4 |
| 离散数学/高等代数 | 2 |
| 运筹学 | 2 |
| 抽象代数 | 2 |
| 线性回归 | 2 |
| 数学分析/离散数学/高等代数 | 1 |
| 离散数学/非基础及进阶课程 | 1 |
| 非基础及进阶课程/高等代数 | 1 |
| 概率论 | 1 |
| 随机过程 | 1 |
| 偏微分方程 | 1 |
| 数值分析/统计推断 | 1 |
| 线性回归/统计推断 | 1 |
| 线性回归/运筹学 | 1 |

## 附录 B：预算档位分布

| tier | 题数 |
|---|---|
| standard | 89 |
| deep | 18 |
| fast | 5 |

