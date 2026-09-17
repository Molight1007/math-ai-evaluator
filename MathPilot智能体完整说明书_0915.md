# MathPilot 智能体完整说明书

> 目的：把整个智能体讲清楚到**可逐项调整**的粒度
> 数据来源：`D:\挑战杯` 主仓**实读代码**（非记忆推断）
> 规模：agent 24 模块 / 18580 行 · prompts 11 模块 · **配置项 108 个** · **流水线 19 个阶段**

---

## 1. 怎么看这份文档

| 你想做什么 | 看哪节 |
|---|---|
| 了解整体跑什么流程 | §2 全景流水线（19 阶段） |
| 找一个功能"开没开、怎么改" | §3 开关总表（108 项，按功能分组） |
| 知道某个文件负责什么 | §4 模块表（24 个） |
| 只想调数值 | §5 参数速查 |
| 看我这次改了什么 | §6 改动定位 |

---

## 2. 全景流水线：19 个阶段

按代码 `_stage_start` 埋点的**真实执行顺序**（不是我归纳的概念图）。

### 阶段 A · 准备

| # | 阶段 | 做什么 | 关键开关（中文含义） | 默认 |
|---|---|---|---|---|
| 0 | `0_paper_pacer` | 全卷时间池：按剩余题数分配本题软预算帽 | 全卷墙钟目标 / 单题软预算保底 / 全卷题数 | 19500 / 120 / 112 |
| 1 | `1_classify` | 题型识别（零 LLM 关键词）：证明/选择/判断/填空/解答 | **题型识别** | **开** |
| 1.1 | （内联） | 判断这道题适不适合走 Lean 形式化 | **Lean 通道总开关** | **开** |
| 1.5 | （内联） | 领域判定（元数据已有则跳过 LLM） | **领域提示增强** | **开** |
| 2 | （内联） | 快车道：能用确定性方法（SymPy）直接解出 → 提前返回 | **SymPy 快车道** | **开** |

### 阶段 B · 难度与理解

| # | 阶段 | 做什么 | 关键开关（中文含义） | 默认 |
|---|---|---|---|---|
| 2.5 | `2.5_difficulty` | 难度路由：静态预判 + LLM 自评融合 → 定档 | **难度路由总开关** / **LLM 自评难度** | 开 / 开 |
| 2.6 | `2.6_pre_audit` | 题意理解确认（客观审核门） | **客观审核门总开关** | **开** |
| 2.65 | `2.65_calc_prewarm` | 生成前算式预计算：先算准算式再解题 | **生成前算式预计算** | **关** ⚠ |

### 阶段 C · 分解与求解（最重）

| # | 阶段 | 做什么 | 关键开关（中文含义） | 默认 |
|---|---|---|---|---|
| 2.7 | `2.7_subgoal_main` | ★ 子目标主路径（**全档位统一**先跑一遍） | **子目标主路径** / **AND-OR 蓝图 DAG** | 开 / **开** |
| 3 | `3_solve` | 主求解：按档位采样 N 个候选 | **主候选数** / **各档候选数** | 2 / 按档 |
| 3.2 | `3.2_complete` | 截断候选续写补齐 | **各档续写数** | 按档 |
| 3.3 | `3.3_improve` | ★ Step2 无条件自改进（再注入一段推理预算） | **自改进总开关** / **每题最多改进数** | **开** / 2 |
| 3.4 | `3.4_collab` | deep 档三 Agent 协作（解题→审查→整合→验证） | **三 Agent 协作** | **关** |
| 3.5 | `3.5_subgoal_sup` | 子目标补充候选（仅非 deep 档且开关打开时） | **子目标补充候选** | **关** |
| 3.6 | `3.6_audit_filter` | 候选客观审核（Lean + 客观审核门串行过滤） | **客观审核门** / **非证明题走 Lean** | 开 / 开 |

### 阶段 D · 验证

| # | 阶段 | 做什么 | 关键开关（中文含义） | 默认 |
|---|---|---|---|---|
| 4 | `4_verify` | 投票验证：候选聚类 + N 票裁决 | **每候选投票数** / **各档投票数** | 1 / 按档 |
| 4.5 | `4.5_oracle` | deep 档答案客观复核（区别于投票的同源自评） | **复核预估耗时** | 360 |
| 4.6 | `4.6_adv` | 对抗式验证：正向通过后主动证伪，抓漏检 | **对抗式验证** | **开** |

### 阶段 E · 修订与兜底

| # | 阶段 | 做什么 | 关键开关（中文含义） | 默认 |
|---|---|---|---|---|
| 5 | `5_revise_or_fallback` | 全部 0 票 → 自纠错修订（带验证反馈重解） | **自纠错轮数** / **重解候选数** | 1 / 2 |
| 5.5 | `5.5_low_conf` | 低置信度强制复核（杀掉虚高置信度） | **接受置信度阈值** / **deep 档修正轮数** | 0.6 / 2 |

### 阶段 F · 输出

| # | 阶段 | 做什么 | 关键开关（中文含义） | 默认 |
|---|---|---|---|---|
| 6 | `6_format` | 格式化：抽取最终答案 + 截断修复 | **答案抽取模式** | auto |
| 6.5 | `6.5_audit_gate` | 最终答案闸门（Lean / 客观审核门双后端） | **客观审核门** | **开** |

> ⚠ `2.65_calc_prewarm`（生成前算式预计算）默认关：9/14 实测 12 题仅 1 题相关、**净负**。

---

## 3. 开关总表（108 项，按功能分组）

### 3.1 采样与生成（9 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `policy_sample_times` | 2 | 主候选数 |
| `policy_temperature` | 0.3 | 采样温度 |
| `policy_max_tokens` | 65536 | 单次上限 |
| `max_answer_tokens` | 65536 | solver 单次上限 |
| `max_tokens` | 65536 | 全局单次上限 |
| `max_tokens_cap` | 0 | 内部裁剪上限（0=不裁） |
| `temperature` | 0.3 | 默认温度 |
| `revise_sample_times` | 2 | 自纠错重解候选数 |
| `max_revise_rounds` | 1 | 自纠错轮数上限 |

### 3.2 题型与领域（4 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `enable_question_type` | **开** | 题型识别 + 差异化策略 |
| `enable_domain_hint` | **开** | 领域提示增强 |
| `objective_tactic_enabled` | **开** | 客观题特化 |
| `extraction_mode` | auto | 答案抽取模式 |

### 3.3 计算工具（6 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `enable_calc_tool` | **开** | `<calc>` 标记 + 精确求值回填 |
| `calc_mandatory` | **开** | 强制走工具 |
| `calc_hard_only` | **开** | 只对难算式强制 |
| `enable_calc_prewarm` | 关 | 生成前预计算（实测净负） |
| `tool_calc_enabled` | 关 | 原生工具循环 |
| `answer_selfcheck_enabled` | **开** | 答案自检 |

### 3.4 符号化通道（6 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `symbolic_solve_enabled` | 关 | 符号化方程求解（零 LLM） |
| `symbolic_crosscheck_enabled` | 关 | 符号化交叉核对 |
| `symbolic_max_tokens` | 512 | 建模 token |
| `symbolic_solve_max_tokens` | 384 | 求解 token |
| `symbolic_solve_feedback` | **开** | 分歧时回传模型定稿 |
| `symbolic_solve_adopt` | **开** | 采纳符号结果 |

### 3.5 子目标（13 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `enable_subgoal_main_path` | **开** | ★ 2.7 主路径（全档位） |
| `use_sub_goal` | 关 | 3.5 补充候选 |
| `deep_use_sub_goal` | **开** | deep 档强制分解 |
| `max_subgoals` | 6 | ★ 上限；**0/负 = 不截断** |
| `subgoal_stage_budget_sec` | 750.0 | deep 档阶段预算 |
| `subgoal_stage_budget_sec_std` | 450.0 | 非 deep 档阶段预算 |
| `subgoal_ctx_mode` | deps | 上下文注入模式 |
| `subgoal_calc_router` | 关 | 计算分档路由 |
| `enable_subgoal_lean_check` | **开** | 子目标 Lean 检查 |
| `subgoal_conflict_gate` | 关 | 确定性冲突闸（0 LLM） |
| `subgoal_crosscheck_llm` | 关 | LLM 交叉核对（+1 调用） |
| `subgoal_reuse_done` | **开** | 复用已完成子目标 |
| `subgoal_adaptive_recover` | **开** | 自适应恢复 |

### 3.6 蓝图与 DAG（6 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `use_blueprint_dag` | **开** | ★ AND-OR 蓝图 DAG 路径 |
| `use_blueprint` | 关 | 旧蓝图路径（等价开关） |
| `enable_skeleton_review` | 关 | 求解前骨架质量门 |
| `skeleton_review_max_rounds` | 2 | 评审-重生成上限 |
| `dag_replan_gate` | 关 | DAG 重规划门（45 题实测净 0） |
| `enable_dag_replan` | 关 | DAG 重规划 |

### 3.7 难度路由（9 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `enable_difficulty_router` | **开** | 总开关（关=全卷 standard） |
| `enable_llm_difficulty` | **开** | LLM 自评难度 |
| `algebra_force_deep` | 关 | 代数题强制 deep |
| `tier_sample_times` | 按档 | 每档候选数 |
| `tier_temperatures` | 按档 | 每档温度分层 |
| `tier_voting_times` | 按档 | 每档投票数 |
| `tier_max_completions` | 按档 | 每档续写数 |
| `tier_max_calls` | 按档 | 每档调用预算 |
| `tier_budget` | 按档 | 每档预算帽（秒） |
| `deep_quota_ratio` | 0.25 | deep 档占比上限 |

### 3.8 验证（15 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `verifier_voting_times` | 1 | 每候选投票数 |
| `verifier_temperature` | 0.0 | 验证温度（贪婪） |
| `use_scoring` | 关 | 多维评分 |
| `use_rubric` | 关 | rubric 结构化判分 |
| `use_challenge` | 关 | 反例挑战 |
| `enable_deterministic` | **开** | 确定性硬否决（SymPy 回验） |
| `enable_adversarial_verify` | **开** | 对抗式验证 |
| `adversarial_tiers` | deep,standard | 适用档位 |
| `adversarial_min_confidence` | 0.5 | 触发置信度 |
| `adversarial_max_tokens` | 640 | 上限 |
| `adversarial_max_reasoning` | 2400 | 推理上限 |
| `verify_enhance_est_seconds` | 360.0 | 增强预估耗时 |
| `enable_feedback_review` | **开** | 反馈复核 |
| `use_bug_report_feedback` | **开** | bug report 反馈 |
| `accept_confidence` | 0.6 | 接受阈值 |

### 3.9 自改进与协作（7 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `enable_self_improve` | **开** | ★ Step2（实测最大杠杆 +8.9pp） |
| `self_improve_max` | 2 | 每题最多改进候选数 |
| `improve_min_remaining` | 300.0 | 停手预留（0=关） |
| `enable_collaborative_deep` | 关 | 三 Agent 协作 |
| `collab_max_rounds` | 3 | 协作循环上限 |
| `deep_revise_rounds` | 2 | deep 档修正轮数 |
| `deep_use_playoff` | **开** | deep 0 票复算 |

### 3.10 审计与 Lean（17 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `enable_audit_gate` | **开** | AuditGate 检测链总开关 |
| `enable_lean_verify` | **开** | Lean 通道总开关（无 Lean 自动回落） |
| `enable_lean_preverify` | 关 | 2.6 前置形式化 |
| `lean_preverify_tiers` | (deep,) | 适用档位 |
| `preverify_max_rounds` | 2 | 重试上限 |
| `preverify_timeout` | 60.0 | 单次超时 |
| `lean_gate_all_proofs` | **开** | 证明题全档硬验证 |
| `lean_gate_nonproof` | **开** | 非证明题候选级 Lean |
| `lean_gate_nonproof_deep_only` | 关 | 仅 deep 档 |
| `lean_gate_strict` | 关 | unknown 时严格拒绝 |
| `lean_gate_unknown_stop` | 2 | 连续 unknown 止损（0=关） |
| `lean_timeout` | 60.0 | 编译超时 |
| `lean_backend` | mcp | 后端类型 |
| `lean_executable` | 空 | lean.exe 路径（自动探测） |
| `lean_project_dir` | 空 | lake 工程目录（自动探测） |
| `theorem_memory_enable` | 关 | 跨题定理记忆 |
| `use_proof_channel` | 关 | 证明题专用通道 |

### 3.11 时间与预算（10 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `max_time_per_question` | 1100 | 单题壁钟上限（秒） |
| `max_total_time_seconds` | 20700 | 总运行上限（秒） |
| `max_total_calls` | 150 | 调用预算硬上限 |
| `paper_target_time` | 19500 | 全卷墙钟目标 |
| `paper_min_soft` | 120 | 单题软预算保底 |
| `paper_total_questions` | 112 | 全卷题数 |
| `critical_tail_seconds` | 120.0 | 剩余不足则跳可选步骤 |
| `deep_critical_tail_seconds` | 60.0 | deep 档再收紧 |
| `max_workers` | 3 | 并发验证线程 |
| `verify_only_seconds` | 0 | 仅验证模式 |

### 3.12 记忆与自查（4 项）

| 开关 | 默认 | 含义 |
|---|---|---|
| `use_lemma_accumulation` | **开** | 引理积累（按领域路由） |
| `lemma_domains` | ["Number theory", …] | 生效领域 |
| `lemma_storage_path` | 空 | 跨题持久化（空=仅内存） |
| `enable_error_lessons` | **开** | 易错点自检注入 |

> **开关总览（实测统计）**：`bool` 型 **52** 项 —— **开 30 / 关 22**；
> 参数型（int/float/str/list/dict/tuple）**56** 项。**合计 108**。

### 3.13 ★ 默认关闭的 22 项（最值得先看的部分）

这些功能**代码在、但默认不生效**。研究阶段"放开限制"后，它们是最直接的调整对象：

### 3.13 ★ 默认关闭的 22 项：逐项说明它是什么、为什么关着

**「配置名」只是代码里的开关名，「这个功能是干什么的」请看中间一列。**

#### A 组 · 有实测证据，建议别开（3 项）

| 配置名 | 这个功能是干什么的 | 为什么关着 |
|---|---|---|
| `enable_calc_prewarm` | **生成前算式预计算**：解题前先让模型把题目里的算式单独算准，再拿结果去解题 | **实测净负**。9/14 用 12 道题验证：只有 1 道与本功能相关，其余无收益还多花时间 ⇒ 明确不该开 |
| `dag_replan_gate` | **蓝图重规划门**：正式求解前强制评审一遍子目标分解，拒绝率超标就推翻重写 | **45 题实测净 0**：门"拦得住、修不好"（21/45 触发重写，但净正确率贡献 ≈ 0），总耗时 **+23%** |
| `enable_dag_replan` | 同上（蓝图重规划的另一开关） | 同上一行 |

#### B 组 · 因为"时间墙 / 平台无 Lean"才关的，前提已消失（5 项）

| 配置名 | 这个功能是干什么的 | 为什么关着 |
|---|---|---|
| `enable_collaborative_deep` | **三 Agent 协作求解**：解题 Agent → 审查 Agent → 整合 Agent → 再验证，deep 档专用 | 当时**烧掉 535 秒**，被时间墙逼着关掉 |
| `enable_lean_preverify` | **做题前的形式化校验**：先把题目翻译成 Lean 数学声明并编译一遍，用来确认"有没有读懂题" | 平台**没有 Lean 环境**，编译必然失败 |
| `lean_gate_nonproof_deep_only` | **限制 Lean 只用在高配档**：非证明题只在 deep 档跑形式化验证 | 纯**时间墙护栏**（为了省时间） |
| `theorem_memory_enable` | **跨题定理记忆**：把编译通过的定理缓存下来，供后面的题目复用 | 9/6 去掉 Lean 后**没有写入方**了（缓存永远空） |
| `enable_skeleton_review` | **求解前骨架质量门**：先审一遍子目标规划合不合理，不过关就重新生成 | 时间墙（多一轮评审-重写） |

#### C 组 · 从未验证过，需 A/B 才能判断（9 项）

| 配置名 | 这个功能是干什么的 | 为什么关着 |
|---|---|---|
| `tool_calc_enabled` | **原生工具调用循环**：让模型显式地调用计算工具（而不是只在文字里写个 `<calc>` 标记等系统代算） | 当时担心耗时，未验证 |
| `symbolic_solve_enabled` | **符号化方程求解通道**：完全不用 LLM，用 SymPy 符号库直接解方程组 | 未验证 |
| `symbolic_crosscheck_enabled` | **符号化交叉核对**：拿符号求解的结果去校验 LLM 给出的答案是否自洽 | 未验证 |
| `use_rubric` | **结构化评分表判分**：验证器按一份评分细则逐项判定，而不是只投"对/错" | 未验证 |
| `use_challenge` | **反例挑战**：让验证器主动构造反例去推翻候选答案（而不是被动检查） | 未验证 |
| `algebra_force_deep` | **代数题强制走高配档**：凡代数题一律用 deep 档（更多候选、更多投票） | 未验证 |
| `subgoal_calc_router` | **子目标的计算分档路由**：按子目标类型决定这一步要不要走工具计算 | 未验证 |
| `subgoal_conflict_gate` | **子目标结论冲突闸**：用纯规则（不调 LLM）检查各子目标结论之间是否自相矛盾 | 未验证 |
| `subgoal_crosscheck_llm` | **子目标结论 LLM 交叉核对**：额外调一次模型来裁决子目标之间有没有矛盾（多 1 次调用） | 未验证 |

#### D 组 · 已被替代或有意简化，不需要开（5 项）

| 配置名 | 这个功能是干什么的 | 为什么关着 |
|---|---|---|
| `use_blueprint` | 旧的蓝图规划路径 | 与 `use_blueprint_dag`（**已开**）功能重复 ⇒ 开它没意义 |
| `use_scoring` | 验证器**多维评分**（给候选按维度打分） | 当时为**减少误判**而有意改成只投对/错票 |
| `use_proof_channel` | **证明题专用通道**：证明题走一条单独的求解链路 | 当时为**简化链路**而关 |
| `use_sub_goal` | **子目标补充候选**：候选不够时再拆一次子目标多产一条候选 | 与已开启的 **2.7 子目标主路径重叠**（主路径已全档位先跑一遍） |
| `lean_gate_strict` | **Lean 严格模式**：编译返回 unknown 时一律拒收候选 | 有意选**保守**：unknown 不代表错，一律拒收会误杀 |

> ★ **一句话结论**：22 项里只有 **3 项有实测证据说"别开"**；
> **5 项是因为"时间墙 / 平台没 Lean"才关的，这两个前提在研究阶段都已消失**；
> 其余 14 项要么没验证过、要么本来就不需要——**要动，先动 B 组**。

---

## 4. 模块表（24 个 / 18580 行）

| 类别 | 模块 | 行数 | 职责 |
|---|---|---:|---|
| **编排** | `orchestrator.py` | 2757 | 19 阶段主流水线 |
| | `solver.py` | 2431 | 候选生成 / 自改进 / 续写 |
| | `verifier.py` | 1015 | 投票验证 / 聚类 |
| **分解** | `sub_goal_solver.py` | 3137 | ★ 子目标分解+逐步求解+合并（最大） |
| | `blueprint_planner.py` | 923 | ★ AND-OR 蓝图 DAG |
| | `dag_reviewer.py` | 450 | ★ DAG 评审（7 维度） |
| | `skeleton_reviewer.py` | 249 | 求解前骨架门 |
| | `question_type.py` | 549 | 题型识别 + 客观题特化 |
| **计算** | `calc_tool.py` | 1783 | `<calc>` 解析 + 精确求值 |
| | `symbolic_solve.py` | 489 | 符号化求解（零 LLM） |
| | `symbolic_model.py` | 153 | 符号建模 |
| | `deterministic.py` | 529 | 确定性快车道 |
| **验证** | `audit_gate.py` | 335 | 客观审核门 |
| | `adversarial_verifier.py` | 343 | 对抗式验证 |
| | `answer_oracle.py` | 241 | 答案客观复核 |
| | `value_attack.py` | 114 | 数值攻击 |
| | `collaborative_solver.py` | 292 | 三 Agent 协作 |
| **基础** | `base.py` | 1050 | 基类 + TaskContext + 时间感知 LLM |
| | `formatter.py` | 689 | 格式化 + 截断修复 |
| | `difficulty_router.py` | 278 | 档位路由 |
| | `paper_pacer.py` | 223 | 全卷时间分配 |
| | `classifier.py` | 229 | 题型分类 |
| | `lemma_memory.py` | 163 | 引理记忆 |
| | `replay_buffer.py` | 158 | 经验回放（**未接入**） |

---

## 5. 关键参数速查

| 参数 | 当前 | 想调时改哪 |
|---|---|---|
| 子目标数上限 | 6 | `user_agent.py` → `max_subgoals`（`0`=不截断） |
| 单题/总时限 | 1100 / 20700 秒 | `user_agent.py`；或 CLI `--max_time_per_question` / `--max_total_time_seconds` |
| 子目标阶段预算 | 750 / 450 秒 | CLI `--subgoal_stage_budget_sec(_std)` |
| deep 档占比 | 0.25 | CLI `--deep_quota_ratio` |
| 主候选数 | 2 | `policy_sample_times` 或 `tier_sample_times` |
| 自改进上限 | 2 | `self_improve_max` |
| 接受置信度 | 0.6 | `accept_confidence` |
| 全卷题数 | 112 | `paper_total_questions` |

> **CLI 已覆盖 7 个旋钮**（本轮新增）：`--max_total_time_seconds` / `--subgoal_stage_budget_sec` /
> `--subgoal_stage_budget_sec_std` / `--max_subgoals` / `--improve_min_remaining` /
> `--deep_quota_ratio` / `--paper_total_questions`。不传 = 保持原口径。

---

## 6. 我这次改了什么（定位）

完整逐项明细见 **`改动明细与调整指引_0915.md`**（56 处，含行号与调整方法）。
这里只给方向：

| 功能 | 涉及文件 | 影响 |
|---|---|---|
| 前瞻引理规划 | blueprint_planner / sub_goal_solver / prompts | 新增机制（默认随蓝图路径启用） |
| 截断保留收尾 | blueprint_planner / sub_goal_solver | **修改既有行为** |
| `max_subgoals` 同源 | blueprint_planner / sub_goal_solver / user_agent / run_eval | **修既有失效** |
| 蓝图粒度放开 | prompts/blueprint | 提示词 |
| 子目标衔接 | prompts/sub_goal | 提示词 |
| 评审 5→7 维 | prompts/dag_review / dag_reviewer | 提示词 + 传参 |
| 难题跳过**回退** | orchestrator / difficulty_router / base | **已回退** |

---

## 7. ⚠ 未验证声明

1. 本文档是**结构与配置清单**，不含任何正确率主张。
2. **本次全部改动未跑端到端评测**；其中"截断保留收尾""子目标衔接"与 9/14 之前的
   "少而精"设计**方向相反**，谁更优**只有 A/B 能回答**。
3. 开关的"默认值"取自 `user_agent.py` 的 `AgentConfig`；运行时可能被 CLI/环境变量覆盖。

---

*本文件为内部研究文档，不进入代码仓库。*
