# LEAP 复现优化计划（老师 8/26 要求 #26–#33 的落地路线）

> 生成日期：2026-08-26 ｜ 依据：IMA 知识库 LEAP 思维导图 + 资料库「老师要求跟踪」#26–#33 + 现有代码核查
> 核心判断：**LEAP 论文就是老师 8/26 方法论的出处**。复现 LEAP 三阶段框架 = 落实 #26–#33 的全部要求。
> 更新（8/26 20:40 执行 Phase 0 后）：**LEAP 智能体框架代码未开源**——superhuman 仓库 leap/ 目录仅含论文 PDF 与 Lean 证明结果（solutions/），无 agent 框架代码；复现需按论文自研三阶段实现（与方案 B 嫁接一致）。

---

## 〇、Phase 0 执行记录（2026-08-26）

| 项 | 结果 |
|---|---|
| mathlib 本地构建 | 上次构建 18:23 中断（依赖已 clone、本体 0 olean）；发现 `.lake/config` 残留导致 `compiled configuration is invalid`；已隔离旧配置并重启 `lake build`（lean_build5.log，后台） |
| 测试套件 | ✅ 89 tests 全绿。修复：①测试桩 `_compile` 未适配 `lean_filename` 新签名（3 处 lambda 加 `**kw`）；②**真实源码 bug**：`verify()` project_dir 分支编译失败后无 return 返回 None，已统一走 `_analyze_error`（上层此前拿不到 BugReport、无错误分析） |
| superhuman 克隆 | ✅ 已克隆至 `D:\挑战杯\superhuman`。**关键发现：leap/ 无框架代码，只有论文+证明** |
| 资料库 | ✅ #34「LEAP 论文复现」已登记（高/进行中） |

### superhuman 仓库结构（验收基准就绪）
- `leap/solutions/Putnam-2025/`：12 题全部 Lean 4 证明（论文 100% 达成率）
- `leap/solutions/LEAN-IMO-Bench/`：Basic 25 题 + Advanced 17 题
- `leap/solutions/Open-Problems/`：Knuth 哈密顿分解子问题 + Erdős 457
- `imobench/lean_proof_bench.csv`：含 **Lean Statement 列**（题目+形式化陈述+参考答案+评分指引），可直接作输入与验收
- `aletheia/`：另一组 Lean 证明（备选参考）
- 样例证明风格：`import Mathlib` + 按 lemmata 拆解 + `omega/norm_num` tactic → 与 LEAP 子目标分解一致

### 复现策略修正（重要）
- 原计划假设"fork leap/ 目录替换 LLM 后端"（方式 A）——**不可行**：框架未开源
- 确认走**方式 B（自研嫁接）**：按论文三阶段自研 BlueprintPlanner / LeanTranslator / 迭代精炼循环，复用 math-ai-evaluator 的 Lean↔Mathlib 通道与子智能体资产
- 验收基准直接用 superhuman 官方证明：PBBasic 题号 ↔ lean_proof_bench.csv ↔ 官方 .lean 一一对应

---

## 一、老师要求 ↔ 现状 ↔ LEAP 阶段 对照表

| 条目 | 老师要求（摘要） | LEAP 对应阶段 | 当前现状 | 差距 |
|---|---|---|---|---|
| #26 | 书生先出骨架 sketch / Informal Blueprint | Stage 2 自然语言 Blueprint | ✅ `_generate_sketch()` 已实现（lean_pre_verifier.py） | 小：接入主流程、整树生成 |
| #27 | Blueprint 工具提取依赖 → 拆多子目标（AND-OR） | Stage 1 AND-OR DAG 分解 | ❌ 未实现；SubGoalSolver 为有序切块非依赖图 | **核心新写** |
| #28 | 骨架经 Lean 语法/类型审核 | Stage 2 sorry 占位编译 | ✅ `audit_sketch()` 已实现 + 单测过；端到端编译待 mathlib 构建完成 | 小：扩展到整棵 DAG 树 |
| #29 | 子目标 → 动态子智能体（创建+回溯） | Stage 3 失败重规划 | ❌ 未实现；SubGoalSolver 静态序列 | **核心新写** |
| #30 | lemma 记忆机制（累积/复用） | 论文未强调（补强点） | ❌ `use_lemma_accumulation=False` | 新写 LemmaMemory 模块 |
| #31 | Mathlib 定理检索（leansearch） | 与 LEAP 互补 | ✅ `MathlibTheoremSearcher` 已实现（索引 86412 声明，单测过）；`use_leansearch=False` | 小：打开开关并注入规划 |
| #32 | 推理闭环：搜定理→informal→翻译 Lean→审核 | 三阶段完整闭环 | ⚠️ 两端已有（前置形式化 + 答案验证），中间未打通 | **主线工作** |
| #33 | 让 AI 主动用 Mathlib 解题（调 tactic） | Stage 3 迭代精炼 | ⚠️ lean↔mathlib 通道就绪，verify() 误判已修 | 在 Stage 3 中实现 |

**关键结论**：#26/#28/#31 已有代码基础（差距小）；#27/#29/#30/#32 是真正的主线工程量。

---

## 二、优化目标（两档，先 B 后 A）

- **目标 B（推荐，5 周）**：复现 LEAP 三阶段骨架并跑通流程 —— Lean-IMO-Bench Basic 5–10 题能输出 Lean 证明，其中 **≥1 题 sorry 全部填满**；输出一份可执行的复现报告（挑战杯/专利素材）。
- **目标 A（后续）**：Putnam-2025（12 题）达到论文 baseline（容差 -10pp）。

---

## 三、分阶段执行计划

### Phase 0 — 环境与基线（本周）
| 任务 | 说明 | 检查点 |
|---|---|---|
| 完成 mathlib 本地构建 | 后台任务 qUnSxY（lean_standalone3.log）；构建完跑 `tests/validate_mathlib.py` | `import Mathlib` + `norm_num` 编译通过 |
| 跑通现有测试套件 | `python -m unittest discover -s tests`（88 个用例） | 全绿 |
| 克隆 superhuman 仓库 | `git clone https://github.com/google-deepmind/superhuman`，扫 `leap/` 目录与依赖树 | 确认 leap/ 结构、无隐藏内部依赖 |
| 资料库登记 | 新增 #34「LEAP 论文复现」（动作 1） | 资料库新增成功 |

### Phase 1 — Stage 1：Blueprint DAG 分解（第 2 周，#27）
- 新写 `agent/blueprint_planner.py`：题目 → AND-OR DAG（JSON）
  - 数据结构：`nodes[{id, type: and|or, statement, children[]}]`；OR=可选证明策略，AND=所有子目标必须证
  - 校验：无环、子目标数 ≤ 50、叶子节点为"可直接证明"粒度
- SubGoalSolver 改造为"执行者"（不再自拆目标，消费 DAG 叶子节点）
- **输入**：题目自然语言 + Lean Statement（来自 lean_proof_bench.csv）｜**输出**：合法 DAG JSON｜**检查点**：5 道 Basic 题全部生成合法 DAG
- 参考：官方证明的 lemmata 拆解模式（PBBasic001_solution.lean 等）可作 DAG 质量参照

### Phase 2 — Stage 2：非形式 → 形式化搭桥（第 3 周，#26 #28）
- 复用 `_generate_sketch()` 为每个 AND 节点生成自然语言证明草图（整树）
- 新写 `agent/lean_translator.py`：草图 → Lean 4 代码 + `sorry` 占位（参考 LEAN_FORMALIZE_SKETCH prompt）
- `audit_sketch()` 扩展为整树审核：每节点 sorry 占位编译，"除 sorry 外无错"
- **输入**：DAG + 各节点草图｜**输出**：含 sorry 的 Lean 4 源码树｜**检查点**：5 题"除 sorry 外编译通过、sorry 与节点一一对应"

### Phase 3 — Stage 3：迭代精炼 + 回溯 + 记忆（第 4 周，#29 #30 #32 #33）
- **sorry 补全循环**：LLM 补全 → `lake env lean` 编译 → 失败信息回填 → 重试 / 换策略
- **动态子智能体**：每个未完成 AND 节点动态派子任务（复用四角色 + SubGoalSolver 执行器）；失败→回退到 OR 兄弟分支
- **LemmaMemory 模块**：新写，题目内/跨题累积已证引理；`use_lemma_accumulation=True`
- **leansearch 接入**：`use_leansearch=True`，检索定理注入补全提示（复用 MathlibTheoremSearcher）
- **AI 主动用 Mathlib**：提示词引导直接调用 `norm_num/ring/linarith/omega` 等 tactic（#33）
- **输入**：含 sorry 的源码树｜**输出**：完整 Lean 证明（或失败子目标清单）｜**检查点**：≥1 题 sorry 100% 填满；单题 LLM 调用 ≤ 1500

### Phase 4 — 评测与报告（第 5 周）
- Lean-IMO-Bench Basic 子集评测 + Putnam 探针（3 题）
- 失败模式统计（编译错 / 超时 / 策略错 / 搜索枯竭）
- 复现报告：《LEAP vs math-ai-evaluator 对照表》（可复用 / 需新写 / 论文独有）+ 成本时间复盘
- 资料库回填：#26–#33 状态与进展按实际结果更新（动作 2）

---

## 四、技术选型要点

| 项 | 选型 | 理由 |
|---|---|---|
| 主推理 LLM | 书生 Intern-S1（与现有一致）+ DeepSeek-R1（成本低） | 已有 DeepSeek 判分链路；夜降成本 |
| 审查 LLM | Claude（可选） | "DeepSeek 不可全信"原则 |
| 编译 | `lake env lean`，工程目录自动探测（mathlib 构建完的目录） | 已接线，验证路径真实加载 Mathlib |
| 配置开关 | `enable_sketch_audit=True`（已开）；`use_leansearch→True`；`use_lemma_accumulation→True` | 三个开关对应 #28/#31/#30 |

---

## 五、成本与资源

- **LLM 调用**：1000–3000 次/题 × 题数 × API 单价（DeepSeek-R1 为主控成本）
- **编译**：mathlib .olean 增量缓存，避免每题全量编译
- **人力**：1 人 5 周全职（挑战杯冲刺期并行）

---

## 六、风险与规避

| 风险 | 规避 |
|---|---|
| mathlib 构建未完成阻塞 Phase 0 | 先确认后台任务状态；必要时分块构建或先跑 core-Lean 子集 |
| Gemini 3.1 Pro 闭源不可复现，替代模型能力差距（预计 -20~30pp） | 目标 B 只要求流程跑通 + 1 题完整；不强追论文数字 |
| sorry 错位触发编译雪崩 | Stage 2 严格校验"sorry 与节点一一对应"后再进 Stage 3 |
| 单题成本失控 | 硬上限 1500 次调用，超限记录失败原因并切 OR 分支 |
| superhuman 仓库隐藏内部依赖 | Phase 0 先扫依赖树，提前发现 |
| 本地 mathlib 工程 .git 残缺 | 已用独立编译方案绕过；提交时排除大文件（.gitignore 已配） |

---

## 七、资料库同步（本轮执行）

1. **动作 1（新建）**：新增 #34「LEAP 论文复现（#26–#33 落地载体）」优先级=高、状态=进行中。
2. **动作 2（回填）**：#26/#28/#31 进展更新为"已有代码基础，纳入 LEAP Phase 1–3"；#27/#29/#30 标注"LEAP 主线，Phase 1–3 新写"；#32/#33 标注"Phase 3 主线"。
