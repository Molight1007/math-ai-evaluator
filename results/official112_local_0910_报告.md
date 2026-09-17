# 评测结果记录 — official112_local_0910_rejudged

- 结果文件：`D:\挑战杯\results\official112_local_0910_rejudged.jsonl`
- 题量：**112** 题（参与判分 112 题，未判分 0 题）
- 正确率：**21/112 = 18.8%**
- 单题耗时合计：**30.58 h**（各题耗时累加，非墙钟）；单题均值 983s / 中位 1089s / 最大 1384s

## 一、耗时情况

### 1.1 分桶（耗时 × 正确率）

| 耗时桶 | 题数 | 占比 | 平均耗时 | 正确数 | 桶内正确率 |
|---|---|---|---|---|---|
| 120-540s | 14 | 12% | 315s | 2 | 14% |
| 540-1200s | 73 | 65% | 1016s | 16 | 22% |
| >=1200s(截断) | 25 | 22% | 1259s | 3 | 12% |

### 1.2 阶段耗时占比

| 阶段 | 累计耗时 | 占比 |
|---|---|---|
| classify_diff | 500s | 0.5% |
| preverify | 1172s | 1.1% |
| subgoal_main | 57424s | 52.2% |
| solve | 21020s | 19.1% |
| lean_candidate_filter | 344s | 0.3% |
| complete | 1177s | 1.1% |
| verify | 2937s | 2.7% |
| revise_format_gate | 14357s | 13.0% |
| other | 11121s | 10.1% |

### 1.3 单题耗时 Top 15

| 题号 | domain | 对错 | 耗时 | 判分 | 错误分类 |
|---|---|---|---|---|---|
| official112-007 | 离散数学/高等代数 | ❌ | 1384s | 截断 | value_wrong |
| official112-059 | 离散数学 | ❌ | 1379s | 截断 | expr_wrong |
| official112-025 | 离散数学 | ❌ | 1363s | 截断 | value_wrong |
| official112-061 | 离散数学 | ❌ | 1352s | 截断 | value_wrong |
| official112-015 |  | ❌ | 1333s | 截断 | format_unresolved |
| official112-055 | 离散数学 | ❌ | 1329s | 截断 | value_wrong |
| official112-050 |  | ❌ | 1326s | 截断 | value_wrong |
| official112-070 | 非基础及进阶课程 | ❌ | 1318s | 截断 | value_wrong |
| official112-033 | 离散数学 | ❌ | 1257s | 截断 | value_wrong |
| official112-054 | 离散数学 | ❌ | 1239s | 截断 | value_wrong |
| official112-057 | 离散数学 | ❌ | 1230s | 截断 | expr_wrong |
| official112-069 | 非基础及进阶课程 | ❌ | 1230s | 截断 | expr_wrong |
| official112-005 | 离散数学 | ✅ | 1225s | 截断 |  |
| official112-013 | 离散数学 | ❌ | 1221s | 截断 | value_wrong |
| official112-084 | 离散数学 | ✅ | 1217s | 截断 |  |

### 1.4 全题耗时明细

| 题号 | domain | 对错 | 耗时(s) |
|---|---|---|---|
| official112-000 | 离散数学 | ❌ | 1063 |
| official112-001 | 高等代数 | ❌ | 1151 |
| official112-002 | 数学分析 | ❌ | 1090 |
| official112-003 | 离散数学 | ❌ | 1125 |
| official112-004 | 离散数学 | ❌ | 1111 |
| official112-005 | 离散数学 | ✅ | 1225 |
| official112-006 | 高等代数 | ✅ | 1175 |
| official112-007 | 离散数学/高等代数 | ❌ | 1384 |
| official112-008 | 数学分析 | ❌ | 1087 |
| official112-009 | 数学分析 | ❌ | 1202 |
| official112-010 | 数学分析/离散数学/高等代数 | ❌ | 1039 |
| official112-011 | 高等代数 | ❌ | 860 |
| official112-012 | 高等代数 | ✅ | 877 |
| official112-013 | 离散数学 | ❌ | 1221 |
| official112-014 | 离散数学 | ❌ | 1022 |
| official112-015 |  | ❌ | 1333 |
| official112-016 | 离散数学 | ❌ | 1000 |
| official112-017 | 离散数学/高等代数 | ❌ | 1189 |
| official112-018 | 离散数学 | ✅ | 980 |
| official112-019 | 离散数学/非基础及进阶课程 | ✅ | 1021 |
| official112-020 | 离散数学 | ❌ | 1072 |
| official112-021 |  | ❌ | 909 |
| official112-022 | 离散数学 | ❌ | 1106 |
| official112-023 | 离散数学 | ❌ | 1191 |
| official112-024 | 离散数学 | ✅ | 1177 |
| official112-025 | 离散数学 | ❌ | 1363 |
| official112-026 | 离散数学 | ✅ | 1097 |
| official112-027 |  | ✅ | 1202 |
| official112-028 | 离散数学 | ❌ | 1166 |
| official112-029 | 离散数学 | ✅ | 1185 |
| official112-030 | 非基础及进阶课程 | ❌ | 1085 |
| official112-031 | 离散数学 | ❌ | 1214 |
| official112-032 | 离散数学 | ❌ | 1168 |
| official112-033 | 离散数学 | ❌ | 1257 |
| official112-034 | 离散数学 | ❌ | 1187 |
| official112-035 | 离散数学 | ❌ | 1215 |
| official112-036 | 离散数学 | ✅ | 1069 |
| official112-037 | 离散数学 | ❌ | 1175 |
| official112-038 | 离散数学 | ❌ | 1172 |
| official112-039 | 离散数学 | ❌ | 1112 |
| official112-040 | 离散数学 | ✅ | 1054 |
| official112-041 | 离散数学 | ❌ | 1215 |
| official112-042 | 离散数学 | ❌ | 1199 |
| official112-043 | 运筹学 | ❌ | 1075 |
| official112-044 | 离散数学 | ❌ | 1182 |
| official112-045 | 运筹学 | ❌ | 1016 |
| official112-046 | 离散数学 | ❌ | 1203 |
| official112-047 | 离散数学 | ❌ | 1206 |
| official112-048 |  | ❌ | 1208 |
| official112-049 | 离散数学 | ❌ | 906 |
| official112-050 |  | ❌ | 1326 |
| official112-051 | 离散数学 | ❌ | 1065 |
| official112-052 |  | ❌ | 1122 |
| official112-053 | 非基础及进阶课程/高等代数 | ❌ | 1122 |
| official112-054 | 离散数学 | ❌ | 1239 |
| official112-055 | 离散数学 | ❌ | 1329 |
| official112-056 | 离散数学 | ❌ | 1057 |
| official112-057 | 离散数学 | ❌ | 1230 |
| official112-058 | 离散数学 | ❌ | 1088 |
| official112-059 | 离散数学 | ❌ | 1379 |
| official112-060 | 离散数学 | ❌ | 883 |
| official112-061 | 离散数学 | ❌ | 1352 |
| official112-062 |  | ❌ | 845 |
| official112-063 |  | ✅ | 992 |
| official112-064 |  | ❌ | 1089 |
| official112-065 |  | ✅ | 1100 |
| official112-066 |  | ❌ | 1060 |
| official112-067 | 非基础及进阶课程 | ❌ | 1208 |
| official112-068 | 非基础及进阶课程 | ✅ | 1148 |
| official112-069 | 非基础及进阶课程 | ❌ | 1230 |
| official112-070 | 非基础及进阶课程 | ❌ | 1318 |
| official112-071 | 抽象代数 | ✅ | 1081 |
| official112-072 | 离散数学 | ❌ | 1116 |
| official112-073 | 离散数学 | ❌ | 832 |
| official112-074 | 数学分析 | ❌ | 853 |
| official112-075 | 离散数学 | ❌ | 1082 |
| official112-076 | 离散数学 | ❌ | 1019 |
| official112-077 | 离散数学 | ❌ | 1125 |
| official112-078 |  | ✅ | 1182 |
| official112-079 | 数学分析 | ❌ | 1089 |
| official112-080 | 离散数学 | ❌ | 1010 |
| official112-081 | 高等代数 | ❌ | 1019 |
| official112-082 | 离散数学 | ❌ | 1199 |
| official112-083 | 离散数学 | ❌ | 1115 |
| official112-084 | 离散数学 | ✅ | 1217 |
| official112-085 | 离散数学 | ❌ | 1062 |
| official112-086 |  | ❌ | 510 |
| official112-087 | 抽象代数 | ✅ | 911 |
| official112-088 |  | ❌ | 497 |
| official112-089 | 概率论 | ❌ | 1200 |
| official112-090 | 随机过程 | ❌ | 576 |
| official112-091 |  | ❌ | 557 |
| official112-092 |  | ❌ | 725 |
| official112-093 |  | ❌ | 803 |
| official112-094 |  | ❌ | 332 |
| official112-095 |  | ❌ | 1190 |
| official112-096 |  | ❌ | 546 |
| official112-097 | 偏微分方程 | ❌ | 542 |
| official112-098 |  | ✅ | 371 |
| official112-099 |  | ❌ | 393 |
| official112-100 |  | ❌ | 675 |
| official112-101 | 统计推断 | ❌ | 404 |
| official112-102 | 数值分析/统计推断 | ❌ | 145 |
| official112-103 | 统计推断 | ❌ | 326 |
| official112-104 | 统计推断 | ❌ | 147 |
| official112-105 | 统计推断 | ❌ | 209 |
| official112-106 | 线性回归/统计推断 | ❌ | 144 |
| official112-107 | 线性回归/运筹学 | ✅ | 283 |
| official112-108 | 线性回归 | ❌ | 137 |
| official112-109 |  | ✅ | 573 |
| official112-110 |  | ❌ | 648 |
| official112-111 | 线性回归 | ❌ | 509 |

## 二、错题记录（错在哪）

错题共 **91** 题。错误分类分布：

| 错误分类 | 题数 | 占比 | 含义 |
|---|---|---|---|
| value_wrong | 48 | 53% | 真算错（两边都是裸数却不等） |
| expr_wrong | 38 | 42% | 表达式错（推理解答错） |
| format_unresolved | 4 | 4% | 答案未定型（含未求值符号或条件式） |
| empty_output | 1 | 1% | 空输出/只剩定界符（解析或截断 bug） |

### 二.1 `official112-000` ｜ 离散数学 ｜ 1063s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`20460`
- **模型输出**：`\boxed{2^{19} \cdot 19!}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 9 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：【关键错误（必须修正，否则整条推理链作废）】 1. 位置：“子目标 #2「证明每列恰有一个顶点在路径中」”    问题：该结论错误。路径是 S 的全排列，必须访问所有 60 个顶点，每列有 3 个顶点，因此每列必须被访问 3 次，而非 1 次。原论证混淆了'列被进入/离开的次数'与'列中顶点被访问的次数'，导致后续所有基于'每列恰有一个顶点'的推理（如垂直转移次数、行遍历顺序等）全部失效。 2. 位置：“子目标 #3「证明垂直转移恰有 2 次」”    问题：该结论基于错误的子目标 2。实际上，由于每列有 3 个顶 …
  - 触发修订轮数 = 2

### 二.2 `official112-001` ｜ 高等代数 ｜ 1151s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$2-2m$`
- **模型输出**：`\boxed{-4}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = fail
  - 形式化缺口[type_mismatch]：type mismatch: The argument   i.isLt has type   ↑i < m - 1 but is expected to have type   ↑i < m in the application   ⟨↑i, ⋯⟩ prev …
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 1 条：unknown=1
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.3 `official112-002` ｜ 数学分析 ｜ 1090s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$\frac{1}{2}$`
- **模型输出**：`\boxed{\sqrt{5}-2}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = fail
  - 形式化缺口[other]：preverify_9828_416629634.lean:3:103: error(lean.invalidField): Invalid field `Nodup`: The environment does not contain `Finset.Nod …
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 7 条：unknown=7
  - 数值攻击：蓝图极值证伪（min=0.6180339887498949）：数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 0.618034——声称的极值不成立
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：[数值攻击] 蓝图声称极值 0.6180339887498949 已被数值采样证伪（发现 0.0）。请重新推导极值，不要沿用蓝图的候选值。数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 0.618034——声称的极值不成立
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 1

### 二.4 `official112-003` ｜ 离散数学 ｜ 1125s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`2026, 2030`
- **模型输出**：`\boxed{2026}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = ok
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 1 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用

### 二.5 `official112-004` ｜ 离散数学 ｜ 1111s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`2024`
- **模型输出**：`\boxed{674}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- lean_verify [Critical](严重度5): The code is a logic error: it does not address the problem's mathematical cont …
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 1.0，声称 1.0）
  - 子目标 1 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）

### 二.6 `official112-007` ｜ 离散数学/高等代数 ｜ 1384s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`1`
- **模型输出**：`\boxed{0}`
- **归因线索**：
  - 预算跳过 5 次（单题时限内未跑完所有步骤）
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 4 条：unknown=4
  - 计算工具未被调用

### 二.7 `official112-008` ｜ 数学分析 ｜ 1087s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`603729`
- **模型输出**：`\boxed{2 \times 777^2}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = ok
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 1 条：unknown=1
  - 数值攻击：蓝图极值未被证伪（采样上界 1207458.0，声称 1207458.0）
  - 子目标 3 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.8 `official112-009` ｜ 数学分析 ｜ 1202s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`16`
- **模型输出**：`\boxed{1}`
- **归因线索**：
  - 预算跳过 1 次（单题时限内未跑完所有步骤）
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 计算工具未被调用

### 二.9 `official112-010` ｜ 数学分析/离散数学/高等代数 ｜ 1039s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`2`
- **模型输出**：`\boxed{0}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 0.0，声称 0.0）
  - 子目标 7 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 1

### 二.10 `official112-011` ｜ 高等代数 ｜ 860s ｜ empty_output

- **错误分类**：empty_output —— 空输出/只剩定界符（解析或截断 bug）
- **标准答案**：`$f(x,y)= g(x+y, xy(x-y)^{2})$ for some polynomial $g$`
- **模型输出**：`\boxed`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用

### 二.11 `official112-013` ｜ 离散数学 ｜ 1221s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`48`
- **模型输出**：`\boxed{50}`
- **归因线索**：
  - 预算跳过 4 次（单题时限内未跑完所有步骤）
  - 预算档位 = deep
  - Lean 前置验证判定 = fail
  - 形式化缺口[other]：preverify_9828_4931893601.lean:2:161: error: unexpected token 'in'; expected ','
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 1 条：unknown=1
  - 子目标 7 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 2

### 二.12 `official112-014` ｜ 离散数学 ｜ 1022s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`997008, 995026, 995018`
- **模型输出**：`\boxed{993024}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 6 条：unknown=6
  - 子目标 7 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用

### 二.13 `official112-015` ｜  ｜ 1333s ｜ format_unresolved

- **错误分类**：format_unresolved —— 答案未定型（含未求值符号或条件式）
- **标准答案**：`2`
- **模型输出**：`\boxed{n \geq 2}`
- **归因线索**：
  - 预算跳过 2 次（单题时限内未跑完所有步骤）
  - 预算档位 = deep
  - Lean 前置验证判定 = fail
  - 形式化缺口[type_mismatch]：type mismatch: The argument   i has type   Fin k but is expected to have type   Fin (k + 1) in the application   a i
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 5 条：unknown=5
  - 计算工具未被调用

### 二.14 `official112-016` ｜ 离散数学 ｜ 1000s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`21`
- **模型输出**：`\boxed{20}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 186.66666666666663，声称 20.0）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）

### 二.15 `official112-017` ｜ 离散数学/高等代数 ｜ 1189s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`8`
- **模型输出**：`\boxed{6}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 1 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用

### 二.16 `official112-020` ｜ 离散数学 ｜ 1072s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$\binom{2k}{k}^2$`
- **模型输出**：`\boxed{2^{k^2}}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = ok
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 7 条：unknown=7
  - 数值攻击：蓝图极值未被证伪（采样上界 2.0，声称 2.0）
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.17 `official112-021` ｜  ｜ 909s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`21`
- **模型输出**：`\boxed{39}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = fail
  - 形式化缺口[other]：preverify_22740_6610892853.lean:5:4: error(lean.invalidField): Invalid field notation: Field projection operates on types of the f …
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 7 条：unknown=7
  - 数值攻击：蓝图极值未被证伪（采样上界 40.0，声称 40.0）
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：所有候选均未获验证通过，请重新审题并纠正推理错误。 候选答案无法解析为有效数学表达式
  - 触发修订轮数 = 1
  - 降级标记 = 1

### 二.18 `official112-022` ｜ 离散数学 ｜ 1106s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`25502500`
- **模型输出**：`\boxed{23341}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 1 条：unknown=1
  - 子目标 8 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.19 `official112-023` ｜ 离散数学 ｜ 1191s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`290`
- **模型输出**：`\boxed{674}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.20 `official112-025` ｜ 离散数学 ｜ 1363s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`506`
- **模型输出**：`\boxed{2}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 2，声称 2.0）
  - 子目标 8 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）

### 二.21 `official112-028` ｜ 离散数学 ｜ 1166s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`43`
- **模型输出**：`\boxed{45}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = fail
  - 形式化缺口[other]：preverify_22740_9255364901.lean:10:32: error: expected ';' or line break
  - AuditGate 审核 1 条：unknown=1
  - 子目标 11 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.22 `official112-030` ｜ 非基础及进阶课程 ｜ 1085s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`2027091`
- **模型输出**：`\boxed{4024}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 4050156.0，声称 4050156.0）
  - 子目标 4 步，其中 **1 步求解失败**（空/占位）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）

### 二.23 `official112-031` ｜ 离散数学 ｜ 1214s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`1026169`
- **模型输出**：`\boxed{683109}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- lean_verify [Critical](严重度5): The logical error is in the assumption that (n² + 3)/4 gives the minimal numbe …
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值证伪（min=1025157.0）：数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 1025157.000000——声称的极值不成立
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：[数值攻击] 蓝图声称极值 1025157.0 已被数值采样证伪（发现 0.0）。请重新推导极值，不要沿用蓝图的候选值。数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 1025157.000000——声称的极值不成立
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.24 `official112-032` ｜ 离散数学 ｜ 1168s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`512`
- **模型输出**：`\boxed{402}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = ok
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 402.0，声称 402.0）
  - 子目标 3 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：[审核闸门反馈] 上一候选 (#1) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约束 → 结论 = 答案），逐字锚定题目数值。 [审核闸门反馈] 上一候选 (#2) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题 …
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 1

### 二.25 `official112-033` ｜ 离散数学 ｜ 1257s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`1057`
- **模型输出**：`\boxed{2016}`
- **归因线索**：
  - 预算跳过 1 次（单题时限内未跑完所有步骤）
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值证伪（min=2016.0）：数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 2016.000000——声称的极值不成立
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：[数值攻击] 蓝图声称极值 2016.0 已被数值采样证伪（发现 0.0）。请重新推导极值，不要沿用蓝图的候选值。数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 2016.000000——声称的极值不成立
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.26 `official112-034` ｜ 离散数学 ｜ 1187s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`56`
- **模型输出**：`\boxed{2850}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 1444，声称 1444.0）
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.27 `official112-035` ｜ 离散数学 ｜ 1215s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`3986729`
- **模型输出**：`\boxed{4000000}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 0.0，声称 4041529.0）
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.28 `official112-037` ｜ 离散数学 ｜ 1175s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`taking the empty card`
- **模型输出**：`\boxed{\text{The first player must not take the empty card (the card with no digits); any other first move allows the second player to force a win.}}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.29 `official112-038` ｜ 离散数学 ｜ 1172s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`3024`
- **模型输出**：`\boxed{2016}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值证伪（min=2016.0）：数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 2016.000000——声称的极值不成立
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：[数值攻击] 蓝图声称极值 2016.0 已被数值采样证伪（发现 0.0）。请重新推导极值，不要沿用蓝图的候选值。数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 2016.000000——声称的极值不成立
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.30 `official112-039` ｜ 离散数学 ｜ 1112s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`6`
- **模型输出**：`\boxed{4}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 4.0，声称 4.0）
  - 子目标 7 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）

### 二.31 `official112-041` ｜ 离散数学 ｜ 1215s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`31395`
- **模型输出**：`\boxed{2025}`
- **归因线索**：
  - 预算跳过 10 次（单题时限内未跑完所有步骤）
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.32 `official112-042` ｜ 离散数学 ｜ 1199s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`600`
- **模型输出**：`\boxed{800}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 1200.0，声称 1200.0）
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.33 `official112-043` ｜ 运筹学 ｜ 1075s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`4202432`
- **模型输出**：`\boxed{2816}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- lean_verify [Critical](严重度5): The cost formula is mathematically incorrect (256*255/2 - 256*120/2 ≠ 2816), a …
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 65280.0，声称 65280.0）
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：1. The claim that each non‑center player can stay only 2 days is false. A non‑center player must play 255 matches (1 against the centre player and 254 against other non‑center players). With only one match per day, such a player must be present on at least 255 …
  - 触发修订轮数 = 1
  - 降级标记 = 3

### 二.34 `official112-044` ｜ 离散数学 ｜ 1182s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`96`
- **模型输出**：`\boxed{197}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = ok
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 7 条：unknown=7
  - 数值攻击：蓝图极值未被证伪（采样上界 100.0，声称 100.0）
  - 子目标 7 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：[审核闸门反馈] 上一候选 (#1) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约束 → 结论 = 答案），逐字锚定题目数值。 [审核闸门反馈] 上一候选 (#2) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题 …
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.35 `official112-045` ｜ 运筹学 ｜ 1016s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`2600`
- **模型输出**：`\boxed{100}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：1. 位置：“子目标 #3「子目标3: Alice initially distributes 100 pebbles …」”      问题：The solution assumes Alice can initially distribute 100 pebbles as exactly 1 pebble per box, but the problem requires Alice to take n pebbles (which is exactly the number she distributes i …
  - 触发修订轮数 = 2
  - 降级标记 = 3

### 二.36 `official112-046` ｜ 离散数学 ｜ 1203s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`7311`
- **模型输出**：`\boxed{86}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 86.0，声称 86.0）
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.37 `official112-047` ｜ 离散数学 ｜ 1206s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`64`
- **模型输出**：`\boxed{11}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 6 条：unknown=6
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.38 `official112-048` ｜  ｜ 1208s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`8`
- **模型输出**：`\boxed{3}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = fail
  - 形式化缺口[other]：preverify_22740_16892395993.lean:2:0: error: type of theorem `optimal_cookie_count` is not a proposition   ℕ
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 -1997，声称 3.0）
  - 子目标 7 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.39 `official112-049` ｜ 离散数学 ｜ 906s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`81729648000`
- **模型输出**：`\boxed{5}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：【关键错误（必须修正，否则整条推理链作废）】 1. 位置：“子目标 #2: Show that if N ≥ 9, there exists a pair of rows with all columns having difference ≤1... N ≤ 8”    问题：The proof that N ≤ 8 is entirely missing. The solution only states the conclusion without any mathematical argument. The …
  - 触发修订轮数 = 2
  - 降级标记 = 3

### 二.40 `official112-050` ｜  ｜ 1326s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`506`
- **模型输出**：`\boxed{674}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 0.0，声称 448.0）
  - 子目标 7 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.41 `official112-051` ｜ 离散数学 ｜ 1065s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`2278125`
- **模型输出**：`\boxed{2023^2}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 6 条：unknown=6
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：【关键错误（必须修正，否则整条推理链作废）】 1. 位置：“子目标 #5: After the gardener's move, at most 13 squares increase by 1 (the chosen square and its up to 8 neighbors).”    问题：The gardener's move affects the chosen square and its up to 8 neighbors, totaling at most 9 squares, not 13. …
  - 触发修订轮数 = 2
  - 降级标记 = 3

### 二.42 `official112-052` ｜  ｜ 1122s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`2`
- **模型输出**：`\boxed{3}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = fail
  - 形式化缺口[other]：preverify_22740_18211556299.lean:3:4: warning: declaration uses `sorry` preverify_22740_18211556299.lean:8:0: error: type of theor …
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 1 条：unknown=1
  - 数值攻击：蓝图极值证伪（min=3.0）：数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 3.000000——声称的极值不成立
  - 子目标 10 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：[数值攻击] 蓝图声称极值 3.0 已被数值采样证伪（发现 0.0）。请重新推导极值，不要沿用蓝图的候选值。数值攻击证伪：采样发现目标值 0.000000 < 声称最小值 3.000000——声称的极值不成立 [审核闸门反馈] 上一候选 (#1) 未通过客观审核：- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约束 → 结论 = 答案），逐字锚定题 …
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.43 `official112-053` ｜ 非基础及进阶课程/高等代数 ｜ 1122s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`3`
- **模型输出**：`\boxed{1998}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 1997.0，声称 1997.0）
  - 子目标 2 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：【关键错误（必须修正，否则整条推理链作废）】 1. 位置：“子目标 #1「子目标1: Prove that s must be at least 1997 by sh…」”    问题：The solution claims s ≥ 1997 but provides no actual proof. The placeholder text (e.g., 'sh…') suggests the argument is missing. A valid lower-bound proof requires demo …
  - 触发修订轮数 = 2
  - 降级标记 = 3

### 二.44 `official112-054` ｜ 离散数学 ｜ 1239s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`12013`
- **模型输出**：`\boxed{1521}`
- **归因线索**：
  - 预算跳过 3 次（单题时限内未跑完所有步骤）
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 1521.0，声称 1521.0）
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.45 `official112-055` ｜ 离散数学 ｜ 1329s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`18750000`
- **模型输出**：`\boxed{250000}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 ?，声称 25000000）
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.46 `official112-056` ｜ 离散数学 ｜ 1057s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`2450`
- **模型输出**：`\boxed{36}`
- **归因线索**：
  - 预算档位 = deep
  - Lean 前置验证判定 = fail
  - 形式化缺口[other]：preverify_22740_20324983006.lean:5:33: error(lean.invalidField): Invalid field `card`: The environment does not contain `Function. …
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 2

### 二.47 `official112-057` ｜ 离散数学 ｜ 1230s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$\lambda^{st}n^{s+t}$`
- **模型输出**：`\boxed{(\lambda^{st} - o(1)) n^{s+t}}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值证伪（min=0.2373046875）：数值攻击证伪：采样发现目标值 0.177979 < 声称最小值 0.237305——声称的极值不成立
  - 子目标 3 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：[数值攻击] 蓝图声称极值 0.2373046875 已被数值采样证伪（发现 0.177978515625）。请重新推导极值，不要沿用蓝图的候选值。数值攻击证伪：采样发现目标值 0.177979 < 声称最小值 0.237305——声称的极值不成立
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 2

### 二.48 `official112-058` ｜ 离散数学 ｜ 1088s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`4181`
- **模型输出**：`\boxed{1876}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 6 条：unknown=6
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.49 `official112-059` ｜ 离散数学 ｜ 1379s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`85383238549`
- **模型输出**：`\boxed{16! - 15655}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.50 `official112-060` ｜ 离散数学 ｜ 883s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$\lambda^8 + 36\lambda^7 + 210\lambda^6 + 462\lambda^5 + 495\lambda^4 + 286\lambda^3 + 91\lambda^2 + 15\lambda + 1$`
- **模型输出**：`\boxed{1 + 15\lambda + 91\lambda^2 + 286\lambda^3 + 495\lambda^4 + 462\lambda^5 + 210\lambda^6 + 36\lambda^7 + \lambda^8}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 17 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用

### 二.51 `official112-061` ｜ 离散数学 ｜ 1352s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`75`
- **模型输出**：`\boxed{1}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.52 `official112-062` ｜  ｜ 845s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`4`
- **模型输出**：`\boxed{1}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 9 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.53 `official112-064` ｜  ｜ 1089s ｜ format_unresolved

- **错误分类**：format_unresolved —— 答案未定型（含未求值符号或条件式）
- **标准答案**：`4`
- **模型输出**：`\boxed{m\text{ is even}}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 1 条：unknown=1
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.54 `official112-066` ｜  ｜ 1060s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`4`
- **模型输出**：`\boxed{3}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 4.0，声称 4.0）
  - 子目标 9 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.55 `official112-067` ｜ 非基础及进阶课程 ｜ 1208s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`1/2, 1`
- **模型输出**：`\boxed{2}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 子目标 8 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 2

### 二.56 `official112-069` ｜ 非基础及进阶课程 ｜ 1230s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$Y = M$`
- **模型输出**：`\boxed{\text{The circumcircle of triangle } PQR}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 10 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 2

### 二.57 `official112-070` ｜ 非基础及进阶课程 ｜ 1318s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`$\frac{5}{8}$`
- **模型输出**：`\boxed{\dfrac{1}{2}}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 ?，声称 0.9921567416492215）
  - 子目标 8 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.58 `official112-072` ｜ 离散数学 ｜ 1116s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$(n-2)2^n +1$`
- **模型输出**：`\boxed{1}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 计算工具未被调用

### 二.59 `official112-073` ｜ 离散数学 ｜ 832s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$(n^2 +3n+2, n^3 + 4n^2 + 3n -1)$ for $n \ge 1$`
- **模型输出**：`\boxed{\text{No solutions}}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 0.08008382305190409，声称 0.0）
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：解答已较完整，请重新审题核对计算细节后给出最终答案。 [对抗式审查] 检出「计算错误：算术或代数运算出错」 出错步骤：计算过程：a = (12 ± sqrt(144 + 240))/30 = (6 ± 2√15)/15 反例/反证：Correct root calculation: a = [12 ± sqrt(384)]/30 = [12 ± 8√6]/30 = [6 ± 4√6]/15 ≈ 1.053 and -0.253, not [6 ± 2√15]/15 ≈ 0.916 依据：The solution i …
  - 触发修订轮数 = 2
  - 降级标记 = 1

### 二.60 `official112-074` ｜ 数学分析 ｜ 853s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$g(x)=c, g(x)=\lceil x \rceil, g(x)=\lfloor x \rfloor$`
- **模型输出**：`\boxed{g(x) = c \text{ for some constant } c \in \mathbb{Z}}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 2

### 二.61 `official112-075` ｜ 离散数学 ｜ 1082s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`69169`
- **模型输出**：`\boxed{264}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 7 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.62 `official112-076` ｜ 离散数学 ｜ 1019s ｜ format_unresolved

- **错误分类**：format_unresolved —— 答案未定型（含未求值符号或条件式）
- **标准答案**：`1,3,5`
- **模型输出**：`\boxed{u \geq 3}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 2 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：【关键错误（必须修正，否则整条推理链作废）】 1. 位置：“子目标 #3: 考虑函数 $f(n) = n^2$”    问题：The problem defines f(n) = n / 2^m where m is the exponent of 2 in n. The solution incorrectly redefines f(n) as n^2, n^u, or other polynomial functions. This is a fundamental misunderstanding of t …
  - 触发修订轮数 = 2
  - 降级标记 = 1

### 二.63 `official112-077` ｜ 离散数学 ｜ 1125s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$5(l-1)^2$`
- **模型输出**：`\boxed{2}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 9 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.64 `official112-079` ｜ 数学分析 ｜ 1089s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$\{(a,b):ab \geq e^3\}$`
- **模型输出**：`\boxed{(a, b) \text{ 为正实数对，满足 } ab \ge e^2}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- lean_verify [Critical](严重度5): The claim that the condition is equivalent to ab≥e^2 is false if x can be nega …
  - AuditGate 审核 5 条：unknown=5
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.65 `official112-080` ｜ 离散数学 ｜ 1010s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`146250`
- **模型输出**：`\boxed{9867312}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 -1e+18，声称 9867312）
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.66 `official112-081` ｜ 高等代数 ｜ 1019s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`all multiples of 14, excluding 0`
- **模型输出**：`\boxed{d=14k\ (k\in \mathbb{Z},k\neq 0)}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 8 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.67 `official112-082` ｜ 离散数学 ｜ 1199s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$\lfloor \frac{p}{9} \rfloor$`
- **模型输出**：`\boxed{p - 9}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 -92，声称 91.0）
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 3

### 二.68 `official112-083` ｜ 离散数学 ｜ 1115s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`939`
- **模型输出**：`\boxed{499}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=proof_invalid；反馈=- answer_verify [Critical](严重度5): 疑似自证：验证代码未引用题目关键数字/条件（只验自身恒等式），无法证明答案与题目相关。请重写：把题目条件与答案一起形式化（如 example : 题目约 …
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 -1.0，声称 997.0）
  - 子目标 2 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）

### 二.69 `official112-085` ｜ 离散数学 ｜ 1062s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$\lfloor \frac{a+2}{2}\rfloor +\lfloor \frac{a+2}{3}\rfloor -\lfloor \frac{a+2}{6}\rfloor $`
- **模型输出**：`\boxed{a+1}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 1.0，声称 6.0）
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：【论证漏洞（需补充论证，结论可能仍成立）】 1. 位置：“子目标 #3 结果: \|X\| ≤ floor((a+6)/2)”    问题：该步骤声称使用区间约束来界定图 G 的边数并推导出 \|X\| ≤ floor((a+6)/2)，但完全缺失核心论证。具体地，未解释如何将元素位于长度区间内（max-min ≤ a）这一条件与图 G 的边数关联起来（例如，未证明‘两数相差 ≤ a 则它们共享某素因子的概率/数量受限’），也未展示推导不等式的关键计算。这属于跳过必要证明的论证漏洞。 2. 位置：“子目标 #4 结 …
  - 触发修订轮数 = 2
  - 降级标记 = 3

### 二.70 `official112-086` ｜  ｜ 510s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`\( \mathbb{Q}(5^{1/4},\zeta_8),\ 16,\ \text{是}  \)`
- **模型输出**：`分裂域 $E = \mathbb{Q}(\sqrt[4]{5}, i)$，$[E:\mathbb{Q}] = 8$，是Galois扩张。`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.71 `official112-088` ｜  ｜ 497s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`\( AB  \)`
- **模型输出**：`\boxed{A,B}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：[审核闸门反馈] 上一候选 (#1) 未通过客观审核：Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - 降级标记 = 1

### 二.72 `official112-089` ｜ 概率论 ｜ 1200s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`5129`
- **模型输出**：`\boxed{5117}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=None；降级=time_critical
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 5200.0，声称 5117.0）
  - 子目标 7 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：错因：第一步事件定义错误。将“某市民无座”概率等同于 P(X≥x)（X 为选 A 的人数），忽略了该市民已选定剧院这一条件。正确应为条件概率：给定该市民选 A，其余 9999 人中选 A 的人数 Y~B(9999,0.5)，无座当且仅当 Y≥x−1，故 P(无座)=P(Y≥x−1)。修正：用 Y~N(4999.5,49.995²) 近似并作连续性修正 P(Y≥x−1)≈P(Z≥(x−1+0.5−4999.5)/49.995)≤0.01，解得 x≥5117。 候选答案无法解析为有效数学表达式，可能为幻觉或格式错误。
  - 触发修订轮数 = 2
  - 降级标记 = 1

### 二.73 `official112-090` ｜ 随机过程 ｜ 576s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$(N-1)\sum_{j=1}^{N-1}\frac{1}{j}$`
- **模型输出**：`\boxed{(N-1)H_{N-1}}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 3 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 2

### 二.74 `official112-091` ｜  ｜ 557s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`${\hat{f}(\xi) = \frac{2}{1 + \xi^2}}$`
- **模型输出**：`\boxed{\frac{2e^{i\omega}}{1+\omega^{2}}+\frac{\pi}{2}e^{-2\|\omega\|}}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 3 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.75 `official112-092` ｜  ｜ 725s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`在点 \(\left(\frac12, \frac{\sqrt{3}}{2}\right)\) 处（对应 \(\theta = \frac{\pi}{3}\)），圆周上的拉普拉斯值为    \( 0  \)`
- **模型输出**：`\boxed{4}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：- 诊断1：题目要求计算函数在圆周上的拉普拉斯算子，严格来说应指拉普拉斯‑贝尔特拉米算子在曲线上的限制，而非欧氏空间中的标准拉普拉斯算子。原解答直接计算了欧氏拉普拉斯算子 Δf=4，未考虑约束流形上的算子定义，存在概念性偏差。   - 诊断2：原解答中“由于 Δf=2 为常数”的表述有误，实际 Δf=∂²f/∂x²+∂²f/∂y²=2+2=4，计算过程正确但文字描述错误。   - 诊断3：未明确区分“函数在约束曲线上的限制”与“原函数的拉普拉斯算子”这两个不同概念。若按曲线上的拉普拉斯‑贝尔特拉米算子计算，结果应为 …
  - 触发修订轮数 = 1
  - 降级标记 = 1

### 二.76 `official112-093` ｜  ｜ 803s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`\( CE \)`
- **模型输出**：`\boxed{C}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：【关键错误（必须修正，否则整条推理链作废）】 1. 位置：“原解答给出\boxed{C,E}”    问题：题目为单选题（选项A-E并列），原解答同时选择C和E两个选项，违反了单选题的答题规则。虽然C和E在数学上均正确（C是Heine-Borel定理在R中的刻画，E是紧集的定义），但在单选题语境下只能选择一个答案，因此\boxed{C,E}这一作答形式是错误的。 【论证漏洞（需补充论证，结论可能仍成立）】 1. 位置：“步骤6：选项优先级辨析”    问题：步骤6试图论证在单选题中应选择C而非E，理由是'E属于同义 …
  - 触发修订轮数 = 2
  - 降级标记 = 1

### 二.77 `official112-094` ｜  ｜ 332s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`\( BCD \)`
- **模型输出**：`\boxed{BCD}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.78 `official112-095` ｜  ｜ 1190s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`Lempel–Ziv 短语分解为   \[ (0,a),\ (1,b),\ (2,a),\ (1,c),\ (5,d),\ (0,e). \] 编码得到的最终比特串为   \[ 000000\,001001\,010000\,001010\,101011\,000100. \]`
- **模型输出**：`Lempel-Ziv 分解为短语：a, b, ab, abc, abcde。`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 15 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 3

### 二.79 `official112-096` ｜  ｜ 546s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`\( D  \)`
- **模型输出**：`AD`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 数值攻击：蓝图极值未被证伪（采样上界 0.0，声称 2.0）
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - ⚠ 已检测到问题，但**未触发修订**（revise_round=0）
  - 降级标记 = 1

### 二.80 `official112-097` ｜ 偏微分方程 ｜ 542s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$L^*v = \sum_{i,j=1}^n \partial_j(a_{ij} \partial_i v) - \sum_{j=1}^n \partial_j(b_j v) + cv$`
- **模型输出**：`\boxed{L^* v = \sum_{i,j=1}^n \partial_j (a_{ij} \partial_i v) - \sum_{j=1}^n b_j \partial_j v + \left(c - \sum_{j=1}^n \partial_j b_j\right) v}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.81 `official112-099` ｜  ｜ 393s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`\(\boxed{\text{有限差分法、有限元法（或有限体积法）}}\)`
- **模型输出**：`\boxed{有限差分法}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 2 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：解答已较完整，请重新审题核对计算细节后给出最终答案。 [对抗式审查] 检出「题意偏差：答非所问，或答案形式不符合题目要求」 出错步骤：最终答案 \boxed{有限元法} 反例/反证：在基础数值分析教材中，对于Poisson方程Δu=f的离散化，通常首先介绍有限差分法。若题目出自此类课程，预期答案应为有限差分法，而非有限元法。 依据：填空题的答案取决于课程背景，默认认为有限元法更合适是主观推断，题目表述存在歧义，无法唯一确定答案，故原答案可能不符合出题意图。
  - 触发修订轮数 = 1
  - 降级标记 = 1

### 二.82 `official112-100` ｜  ｜ 675s ｜ value_wrong

- **错误分类**：value_wrong —— 真算错（两边都是裸数却不等）
- **标准答案**：`函数 \( f(x)=\sin(x) \) 在 \( x=\frac{\pi}{4} \) 处的一阶导数（中心差分，\( h=0.1 \)）约为 \(\boxed{0.6706}\)（保留四位小数）`
- **模型输出**：`\boxed{0.70701}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：所有候选均未获验证通过，请重新审题并纠正推理错误。 [对抗式审查] 检出「计算错误：算术或代数运算出错」 出错步骤：sin(0.885398) ≈ 0.774678 反例/反证：精确计算 sin(0.8853981634) ≈ 0.7746773，四舍五入到6位小数应为0.774677而非0.774678 依据：解法中 sin(0.885398) 的近似值0.774678存在舍入错误，正确值应为0.774677（6位小数），导致后续计算结果有微小偏差
  - 触发修订轮数 = 1
  - 降级标记 = 1

### 二.83 `official112-101` ｜ 统计推断 ｜ 404s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`正确`
- **模型输出**：`\boxed{×}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：[审核闸门反馈] 上一候选 (#1) 未通过客观审核：Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - 降级标记 = 1

### 二.84 `official112-102` ｜ 数值分析/统计推断 ｜ 145s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`B`
- **模型输出**：`\boxed{A}`
- **归因线索**：
  - 预算档位 = fast
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - AuditGate 审核 6 条：unknown=6
  - 子目标 2 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.85 `official112-103` ｜ 统计推断 ｜ 326s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`$A,B,C,D,E$`
- **模型输出**：`\boxed{ABCD}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 9 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.86 `official112-104` ｜ 统计推断 ｜ 147s ｜ format_unresolved

- **错误分类**：format_unresolved —— 答案未定型（含未求值符号或条件式）
- **标准答案**：`移动平均法、时间序列分解法`
- **模型输出**：`\boxed{X-11方法, SEATS方法}`
- **归因线索**：
  - 预算档位 = fast
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 2 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.87 `official112-105` ｜ 统计推断 ｜ 209s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`标准差`
- **模型输出**：`\boxed{方差}`
- **归因线索**：
  - 预算档位 = fast
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 4 条：unknown=4
  - 子目标 5 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.88 `official112-106` ｜ 线性回归/统计推断 ｜ 144s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`A`
- **模型输出**：`\boxed{C}`
- **归因线索**：
  - 预算档位 = fast
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 5 条：unknown=5
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.89 `official112-108` ｜ 线性回归 ｜ 137s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`异方差性不会导致参数估计量的偏误，但会使传统方差估计失效，即低估或高估真实方差，导致OLS估计量不再是有效估计。`
- **模型输出**：`\boxed{增大}`
- **归因线索**：
  - 预算档位 = fast
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 2 步，其中 **1 步求解失败**（空/占位）
  - 计算工具未被调用
  - 降级标记 = 1

### 二.90 `official112-110` ｜  ｜ 648s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`A`
- **模型输出**：`\boxed{D}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 4 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：所有候选均未获验证通过，请重新审题并纠正推理错误。 [对抗式审查] 检出「题意偏差：答非所问，或答案形式不符合题目要求」 出错步骤：三者均可用于非线性回归参数估计的不同层面，因此'以上都可以'（D）正确。 反例/反证：标准计量经济学教材（如李子奈《计量经济学》）明确指出：'非线性回归模型的参数估计通常采用非线性最小二乘法（NLS）'，而牛顿-拉夫森法属于数值优化算法，用于求解NLS的正规方程，并非参数估计方法本身。若题目考查的是'估计准则'而非'数值实现技术'，则正确答案应为A而非D。将数值算法与统计估计方法并列且 …
  - 触发修订轮数 = 1
  - 降级标记 = 2

### 二.91 `official112-111` ｜ 线性回归 ｜ 509s ｜ expr_wrong

- **错误分类**：expr_wrong —— 表达式错（推理解答错）
- **标准答案**：`错误`
- **模型输出**：`\boxed{正确}`
- **归因线索**：
  - 预算档位 = standard
  - Lean 最终闸门：判定=unknown；降级=strict_reject；反馈=Lean 验证无法判定（unknown）：翻译失败或代码未交叉引用题目条件。禁止放行裸答案——请重写验证代码，锚定题目数值与条件。
  - Lean 最终闸门：判定=answer_valid
  - AuditGate 审核 6 条：unknown=6
  - 子目标 6 步均有输出，但最终结论错（错误在中间推理步骤）
  - 计算工具未被调用
  - 修订反馈：- 子目标#5的论证存在逻辑漏洞：原文直接声称“利用 $\Omega-\sigma^{2}I$ 半正定性证明 $(X'X)^{-1}X'(\Omega-\sigma^{2}I)X(X'X)^{-1}$ 半正定”，但未给出对任意向量 $c$ 的二次型推导，且错误地假设 $\sigma_i^{2}-\sigma^{2}\ge0$（在异方差情形下并非所有 $\sigma_i^{2}$ 都大于等于共同方差 $\sigma^{2}$），导致证明缺口。 - 子目标#6的结论表述不够严谨：原文称“方差增大或至少不小于”，但在异方 …
  - 触发修订轮数 = 2
  - 降级标记 = 1

