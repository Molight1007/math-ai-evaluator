# MathPilot 项目状态记忆

> **用途**：记录项目当前状态，每次修改后同步更新。
> **维护规则**：每次代码变更后更新对应状态。此文件供 AI 助手快速了解项目当前情况，避免重复探索。

---

## 一、项目当前概况

| 属性 | 值 |
|---|---|
| 项目名称 | MathPilot |
| 竞赛 | 挑战杯 — 基于 Intern-S 系列大模型的数学智能体 |
| 主分支 | main（工作区已切换 origin/main 基线，两条历史无共同祖先，手动整合） |
| 最后活跃日期 | 2026-08-18 |
| 项目阶段 | **v3 整合中 — 以 origin/main（P1-B7 求解闭环+RunState+Summarizer）为基线，重新叠加 P1 确定性验证/Judger友好输出（默认开）、P2 rubric判分/反例挑战（默认关）、P3 视角采样（默认关）；use_arbitration 决策表被 origin 自带 revise 闭环取代** |

---

## 二、模块状态

### 2.1 核心智能体模块 (`agent/`)

| 文件 | 状态 | 说明 |
|---|---|---|
| `base.py` | ✅ v3 | TaskContext + 壁钟追踪 + Budget + BaseAgent；Verdict 新增 `deterministic` 旁证字段（P1） |
| `classifier.py` | ✅ 稳定 | 31 领域题型识别（关键词优先 + LLM 回退） |
| `question_type.py` | ✅ NEW | 题目格式类型分类（选择/判断/证明/解答/填空，关键词 + LLM 两级） |
| `solver.py` | ✅ v3 | 候选生成 + **P3 视角采样**（`use_view_sampling`：换元/几何/代数/倒推，默认关）+ revise 错因定向修订 |
| `verifier.py` | ✅ v3 | 每候选1票 + 聚类选优 + **P1 确定性旁证**（默认开，0 预算）+ **P2 rubric 结构化判分/反例挑战**（`use_rubric`/`use_challenge`，默认关） |
| `deterministic.py` | ✅ NEW v3 | **P1 确定性验证通道**（SymPy 代入采样/反例程序验证/数值回溯，0 LLM 预算，默认开） |
| `formatter.py` | ✅ v3 | 共识聚类加权 + **P1 `_judger_friendly` 黑盒 Judger 友好输出**（默认开） |
| `orchestrator.py` | ✅ v3 | 简化流水线 + **P3 `_arbitrate` 仲裁决策表**（`use_arbitration`：accept/revise/fallback，默认关） |
| `__init__.py` | ✅ 稳定 | 包导出 |

### 2.2 提示词模块 (`prompts/`)

| 文件 | 状态 | 说明 |
|---|---|---|
| `policy.py` | ✅ 稳定 | 通用解题 + 33 领域提示 + 蓝图策略 |
| `proof.py` | ✅ v2.0 | 证明题专用提示词（反证/归纳/构造 + 分步编号） |
| `question_type.py` | ✅ NEW | 题型分类 LLM 提示词 + 六种题型的引导提示词字典 |
| `revise.py` | ✅ 稳定 | 自纠错重解提示词 |
| `verifier.py` | ✅ 稳定 | 验证/评分/反馈提示词 |
| `__init__.py` | ✅ v2.1 | 包初始化（防止极端部署环境 ModuleNotFoundError） |

### 2.3 工具模块 (`utils/`)

| 文件 | 状态 | 说明 |
|---|---|---|
| `extract.py` | ✅ 稳定 | 答案提取 + is_valid_final_answer 终检 |
| `sympy_tools.py` | ✅ v2.0 | SymPy 安全计算引擎（safe_simplify/solve_eq/diff/integrate/det/limit/compare_expr） |
| `llm_client.py` | ✅ v2.1 新增 | OpenAI 兼容 LLM 客户端（自动重试+多格式兼容+环境变量/参数双配置） |
| `__init__.py` | ✅ 稳定 | 导出 extract + sympy + LLMClient |

### 2.4 入口文件

| 文件 | 状态 | 说明 |
|---|---|---|
| `user_agent.py` | ✅ v3 | ReasoningAgent + AgentConfig；P1 开关 `judger_friendly`/`use_deterministic`（默认开）、P2 `use_rubric`/`use_challenge`、P3 `use_view_sampling`/`use_arbitration`（默认关） |
| `run_eval.py` | ✅ v3 | 本地评测脚本 + P1/P2/P3 A/B 开关 + `~/.math_evaluator/.env` 自动加载 + **备用端点故障转移**（`OPENAI_FALLBACK_BASE_URL/MODEL`） |

### 2.5 测试工具 (`测试工具/`)

| 文件 | 状态 | 说明 |
|---|---|---|
| `main.py` | 稳定 | 完整评测器主入口，依赖独立 LLM client |
| `intern_s1.py` | ✅ 已修复 | Intern-S1 推理模块：提升 _INFERENCE_MAX_TOKENS 3072→8192，截断 continuation + 更大 token 重试，修复 70% token 反向重试 bug，修复 EvalConfig 嵌套访问，修复 LLMClient 构造（api_url=→LLMClient(cfg.intern_s1)） |
| `llm_client.py` | ✅ 已修复 | OpenAI 兼容 LLM 客户端：改进 `_detect_content_truncation`，支持未闭合 markdown 代码块与任意位置未闭合 JSON |
| `aggregator.py` | ✅ 已更新 | `merge_result` 直接透传 `raw_response`/`finish_reason`/`is_truncated` 诊断字段 |
| `problem_type_detector.py` | 稳定 | 18 种题型检测 |
| `verify_phase6.py` | 稳定 | Phase 6 验证 |
| `verify_phase6_3.py` | 稳定 | Phase 6.3 约束验证 |
| `lean_verifier.py` | ✅ 已恢复+修复 | Lean 4 形式化验证模块（从历史提交 d5f114a 恢复，修复 No module named 'lean_verifier'，修复 detect_lean_environment 多余参数，修复 'version'→'lean_version' 键名错误） |
| `models.py` | ✅ 已更新 | 扩展 `LeanVerificationResult` 字段以兼容 main.py 与 lean_verifier.py |
| `launcher.py` | ✅ 已修复 | 修复 `lambda` 闭包引用异常变量 `e` 导致的 `NameError`（Python 3.11+） |
| `multi_agent_runner.py` | ❌ 缺失 | 测试工具 --multi-agent 模式桥接层（待创建） |

### 2.6 Web 服务 (`Web服务模块/`)

| 文件 | 状态 | 说明 |
|---|---|---|
| `api/users.db` | 12KB SQLite | 用户数据库 |

### 2.7 其他目录

| 目录 | 状态 | 说明 |
|---|---|---|
| `赛事提交版/` | ✅ 保持现状 | 竞赛正式提交源。**决策（2026-08-18）：不同步 origin/main 新基线**——P1-B7 闭环/RunState/Summarizer 仅过本地测试、未经平台评测，且 P3 快筛无正面证据；保留已验证的旧版 P1（deterministic/judger_friendly）。待新基线 A/B 证实某组件有真实收益后再定向同步 |
| `submit/` | 空壳 | 仅含目录结构 |
| `测试结果/` | 历史数据 | 多批次 JSON/HTML/Lean 输出 |
| `题库/` | ✅ v2.3 恢复 | 4 个 db + 3 个 JSON 源：`question_bank.db`(主用1705题) / `示例题库.db`(deploy用970题) / `我的题库.db`(空) / `高数a.json`+`新高数.json`+`1000题高数.json` |
| `测试工具/question_bank.db` | ✅ v2.3 新增 | GUI 用库（1705 题，由 restore_banks_from_json.py 导入） |
| `题库备份/` | ✅ v2.3 备份 | 4 个 db 时间戳备份 |
| `题库维护脚本/` | ✅ v2.3 | 一次性恢复脚本 `restore_banks_from_json.py` |

## 重要平台约束（2026-08-20 确认）
- **比赛平台无 Lean 环境**：`agent/lean_bridge.py`（队友改造3）在平台自动降级 unknown，`enable_lean_verify` 平台无效——Lean 方向停止投入，合并代码保持默认关（无害）；
- 比赛平台为 **Linux 环境**（Lean 即便本地也需 Linux 适配，但平台无环境故无意义）。

### 2.8 题库数据流向（v2.3 明确）

```
JSON 源（题库/*.json）
    ↓ [restore_banks_from_json.py]
测试工具/question_bank.db   ←── GUI 题库评测主入口
    ↓ [QuestionBankDB.list_banks / get_problem_count]
题库/question_bank.db       ←── 主用库（含 770 条 answer_mapping）
    ↓ [deploy/server.py]
题库/示例题库.db            ←── deploy 用（含第10届竞赛赛题）
```

> **重要**：GUI 硬编码指向 `测试工具/question_bank.db`，主流程指向 `题库/question_bank.db`，两库结构一致但内容相互独立。任何导入操作需明确目标库。

---

## 三、已完成的工作 (v2.0 + v2.1)

### v2.0 重大优化
- [x] 致命 BUG 修复 14 项（__future__ 导入/拒绝语/投票逻辑/等价分组/置信度/续写/答案提取等）
- [x] SymPy 真实工具集成（5类确定性题目快车道，带 _HAS_SYMPY 守卫）
- [x] 跨候选共识聚类投票（AnswerCluster + 簇级多数投票 → 替代单候选重复投票）
- [x] Verifier 多维评分接线（correctness/logic/clarity/completeness/overall 五维）
- [x] 证明题专用通道（PROOF_SYSTEM 分步编号 + 反证/归纳/构造）
- [x] 引理积累机制（TaskContext.lemma_repo，最多5条防token爆炸）
- [x] 防思考链污染（ENGLISH_THINK_PATTERNS + 模板泄露检测）
- [x] 本地评测闭环（run_eval.py 适配用户自定义题库）
- [x] 全部核心 .py 文件 from __future__ import annotations

### v2.3 本地优化同步到赛事提交版（2026-08-02）
+- [x] 模板泄露检测 4→20+ 模式 + 更好诊断日志（base.py）
+- [x] 关键词优先分类 + LLM 回退（classifier.py，借鉴 math_agent-main）
+- [x] 模板泄露恢复 + 英文 think 追回 + 300 阈值（solver.py）
+- [x] _is_correct_vote None 安全防护（verifier.py）
+- [x] 300 字符长答案重提取 + 簇置信度权重（formatter.py）
+- [x] USE_BLUEPRINT_DEFAULT = False（policy.py）
+- [x] 全部 5 项官方测试通过
+
+### v2.3.2 EvalConfig 字段缺失修复（2026-08-09）
+- [x] `config.py`：`EvalConfig` 新增 `lean_compiler: str = "lean"` 和 `lean_timeout: float = 0.0`
+- [x] `lean_verifier.py` L977：`detect_lean_environment(config.lean_compiler)` → `detect_lean_environment()`
+- [x] `intern_s1.py` L770-772 + L915-917：`cfg.intern_s1_api_url` → `cfg.intern_s1.base_url`（等 6 处）
+- [x] Lint 0 错误，Lean 审核和二次复核恢复正常运行
+
+### v2.1 竞赛新规则适配（2026-08-01）
- [x] 平台规则：并发=3，单题≤20分钟，总计≤6小时，反rollout
- [x] 参数全面精简（候选6→3，投票5→2，调用150→40，workers 4→3）
- [x] TaskContext 壁钟时间追踪（start_time/deadline + time_remaining/is_time_critical/is_timed_out）
- [x] Orchestrator 三级时间守卫（调控入口/revise前/追加前/完整性检查 共6处检查点）
- [x] Verifier 修复致命 Bug（__init__ 签名 + total_votes 属性名）
- [x] 新增 utils/llm_client.py（本地测试 LLM 连接）
- [x] run_eval.py 修复（导入+API+client注入）
- [x] 文档同步（agents.md + memory.md）

---

## 四、进行中的工作

- [~] 本地实际评测验证（需要 LLM API 连接）—— v2.2 需重新测试
- [~] v2.2 简化架构验证

---

## 四.五、2026-08-05 题库恢复（v2.3）

**背景**：用户报告 3 个题库（高数a / 新高数 / 1000题高数）丢失，GUI 显示"暂无题库"。

**根因诊断**：
- `测试工具/question_bank.py` 第 28 行 `DB_PATH` 硬编码指向 `测试工具/question_bank.db`（空库）
- `题库/question_bank.db` 实际**未丢失**（1705 题与 JSON 100% 匹配）
- 用户看到 GUI "暂无题库" 后误判主库也丢失

**恢复方案**：
1. 备份 `题库/*.db` + `测试工具/question_bank.db` 到 `题库备份/`（含时间戳命名）
2. 将 3 个 JSON 从 `C:\Users\35174\Downloads\` 复制到 `题库/`（项目内持久化）
3. 编写 `题库维护脚本/restore_banks_from_json.py`，按题库名分库导入到 `测试工具/question_bank.db`
4. 抽样校验：3 个题库 × 3 个位置 = 9 条全 OK

**未改动**：
- `题库/question_bank.db`（与 JSON 100% 匹配，无需重导）
- `题库/示例题库.db`（deploy 用，含第10届竞赛题，独立于本次需求）
- `题库/我的题库.db`（用户保留，0 题）
- `测试工具/question_bank.py` 的 `DB_PATH`（避免改动入口逻辑）

---

## 四.六、2026-08-07 题库评测崩溃修复

**背景**：用户通过 `启动评测器.bat` 使用题库评测时，GUI 报 `No module named 'lean_verifier'`，且异常提示框触发 `NameError: cannot access free variable 'e'`。

**根因诊断**：
- `测试工具/lean_verifier.py` 在提交 `511d249`（"移除冗余工具和敏感数据"）中被删除，但 `测试工具/main.py` 仍保留 `from lean_verifier import ...`
- `测试工具/models.py` 的 `LeanVerificationResult` 字段不足，`main.py` 与 `lean_verifier.py` 均访问 `verified` / `compile_passed` / `error_category` 等缺失字段
- `测试工具/launcher.py` 在 `except Exception as e:` 块内使用 `lambda: ...str(e)`，Python 3.11+ 会在 except 块结束时删除 `e`，导致延迟执行的 `after` 回调抛出 `NameError`

**修复方案**：
1. 从历史提交 `d5f114a` 恢复 `测试工具/lean_verifier.py`
2. 扩展 `测试工具/models.py` 的 `LeanVerificationResult`，新增 `verified`、`compile_passed`、`error_category`、`lean_available`、`analysis_performed` 等字段并设置默认值
3. 修复 `测试工具/launcher.py` 中 4 处 `lambda` 闭包，将 `lambda: ...e` 改为 `lambda e=e: ...e`，确保异常对象在回调执行时仍可用

**验证**：
- `python -m py_compile` 通过 `models.py`、`launcher.py`、`lean_verifier.py`
- 在 `launcher.py` 设置的 `sys.path` 顺序下，`from main import ...` 与 `from lean_verifier import ...` 均可正常导入
- `LeanVerificationResult(problem_id, verified, compile_passed, error_category, lean_code)` 可正常实例化并 `to_dict()`

---

## 五、待实现

### P0 — v2.2 已完成 ✅
- [x] 移除 `_strip_thinking_process` 全局调用（根因修复）
- [x] 提升 `max_tokens_cap` 4096 → 12288
- [x] 简化 Orchestrator（去 _regulate、_ensure_completeness）
- [x] Verifier 改为每候选1票，移除 feedback 提取
- [x] 关闭 blueprint、proof_channel、lemma、scoring
- [x] LLM 调用预算 40 → 10 次

### P1 — 待验证
- [ ] 本地评测对比 v2.1 vs v2.2 效果
- [ ] 根据评测结果微调 temperature 等参数

### P2
- [~] 按需恢复部分高级功能（若简化版评测不理想）

### P2.5 — 小优化
- [x] 长答案阈值 150 → 300（避免中等长度数学答案被误截断）

### P3 — 待实现
- [ ] trace 脱敏与可解释增强
- [ ] 测试工具 multi_agent_runner 桥接
- [ ] Intern-S1 优化版独立化
- [ ] 线上评测自动化

---

## 六、关键决策记录

| 日期 | 决策 | 原因 |
|---|---|---|
| 2026-08-01 | 竞赛参数大幅精简（40调用/3候选/2投票） | 适配新规则：单题≤20分钟，防rollout |
| 2026-08-01 | 壁钟时间守卫集成到 orchestrator 决策点 | 20分钟限制下必须预留退出路径 |
| 2026-08-01 | 本地 LLM 客户端独立模块 | 与竞赛平台解耦，方便本地测试 |
| 2026-08-02 | 长答案阈值 150 → 300 | 150 太短，多步骤数学答案易被误判为过长 |
| 2026-08-02 | 6项优化同步到赛事提交版 | 本地所有 v2.2+ 优化完整同步，通过官方 5 项测试 |
| 2026-08-05 | 题库恢复：用 JSON 重建 `测试工具/question_bank.db` | GUI 入口硬编码该路径，原为空库。保留 `题库/question_bank.db` 不动（数据未丢） |
| - | 四 Agent 协作架构 | 责任分离，每 Agent 可独立优化 |
| - | Verifier 聚类投票替代重复投票 | 更准+更省调用 |
| - | SymPy 快车道为先 | 确定性问题即时求解，省预算给难题 |

---

### 四.七、2026-08-08 评测系统截断优化

**背景**：官方评测日志暴露三大致命问题 — 响应截断率 64.8%、运行错误 27.7%、准确率仅 9.82%（112 题 961 次 API 调用）。

**根因诊断**：
- `finish_reason` 被提取但全项目未使用 → 截断静默失败
- `max_tokens` 过高（推理 6144、Lean 4096×5、评判 8192）
- 自审核 `max_review_retries=2` 导致 API 调用爆炸

**优化方案（四层防御体系）**：
1. `llm_client.py`：`chat()` 新增 `is_truncated`/`content_truncated` 字段 + 括号完整性检测
2. 全模块 `max_tokens` 削峰：推理 6144→3072、审核 2048→1024、Lean 4096→2048×5、评判 8192→4096
3. 截断感知自动降级重试：推理/评判截断→70% tokens 重试；审核截断→默认 pass；Lean 截断→警告继续
4. 自审核 `max_review_retries` 从 2 降至 1（含 argparse 默认值）

**修改文件清单**：`llm_client.py`、`intern_s1.py`、`deepseek.py`、`lean_verifier.py`、`main.py`

**预期效果**：API 调用 961→约 450-550，截断大幅减少，无效题 35→10-15，正确率 9.82%→15-20%

---

### 四.八、2026-08-08 双重审核机制（Intern-S1 + Lean 并行验证）

**背景**：原有审核流程是串行的（先自审核，不通过则重试），Lean 验证仅作为评测后的独立阶段，两者不协同。

**用户设想的核心逻辑**：
1. **自检测阶段**：Intern-S1 将逻辑链转化为 Lean 代码，利用 Lean 编译器进行形式化验证
2. **并行执行**：Intern-S1 自审核 与 Lean 编译验证 同时跑（`asyncio.gather`）
3. **双通过即接受**：两者都通过 → 直接接受答案
4. **任一不通过触发二次复核**：Lean 判错不一定正确（形式化翻译可能失败），需要 Intern-S1 再审核一遍
5. **真错 → 重新生成**；**误判 → 保留答案**
6. **最终正确性仅由 DeepSeek 判定**（保持评分体系一致）

**改造实施**：

| 文件 | 改动内容 |
|---|---|
| `models.py` | 新增 `lean_verification`、`secondary_review`、`dual_review_passed`、`lean_latency_seconds` 字段（InferenceResult + EvaluationResult） |
| `intern_s1.py` | 新增 `SECONDARY_REVIEW_SYSTEM_PROMPT`（二次复核提示词）、`LEAN_FOR_REVIEW_SYSTEM_PROMPT`（Lean代码生成提示词）；新增 `_run_lean_check()`（转化+编译）、`_secondary_review()`（二审判断）、`_build_combined_feedback()`（综合反馈）；重写 `run_inference()` 审核循环为并行双审逻辑 |
| `main.py` | `enable_lean` 参数贯穿全链路（`run_evaluation`→`evaluate_batch_mode`/`_run_single_mode`→`_run_inference_stage`→`run_inference`）；Lean 阶段改为补充验证（跳过审核阶段已覆盖的题）；策略打印增加 Lean 状态显示 |
| `aggregator.py` | `merge_result` 透传 `lean_verification`、`secondary_review`、`dual_review_passed` |

**核心流程**：
```
Intern-S1 生成解答
    ↓
┌── 并行执行 ────────────────────┐
│  Intern-S1 自审核    Lean 编译验证  │
└────────────────────────────────┘
    ↓
  两者都通过？───是──→ 接受答案
    │
   否 → Intern-S1 二次复核
         ├── 确认真错 → 重新生成
         └── 判定误判 → 保留答案
              ↓
         DeepSeek 终审（唯一正确性判定来源）
```

**Lean 在审核中的角色**：
- Intern-S1 将推理链转化为 Lean 4 代码（`LEAN_FOR_REVIEW_SYSTEM_PROMPT`）
- Lean 编译器验证逻辑一致性
- 优势：机器可独立复现，不依赖 LLM 内部判断
- 局限：形式化翻译可能失败 → 因此需要二次复核兜底

---

---

### 四.九、2026-08-09 截断导致 Parse error 根因修复

**背景**：用户最新测试报告仍出现 `Parse error: Failed to parse JSON from response`，集中在部分复杂题（如 1000题数一高数篇_1007）。

**根因诊断**：
- `_INFERENCE_MAX_TOKENS = 3072` 过小，复杂题自然语言推理过长，还没输出 JSON 就触发 `finish_reason == "length"`
- 截断后的降级逻辑是 `int(_INFERENCE_MAX_TOKENS * 0.7)`，token 反而更少，导致重试必然再次截断
- 旧 `_detect_content_truncation` 只检测以 `{` 开头的内容，无法识别 markdown 代码块或未闭合的嵌套 JSON
- 截断时原始响应（`raw_response`）和 `finish_reason` 未透传到评测报告，导致之前难以定位

**修复方案**：
1. `intern_s1.py`：
   - `_INFERENCE_MAX_TOKENS` 3072 → 8192
   - 截断后不再减少 token，改为 **continuation 续写**（把已输出内容作为 assistant 消息，要求模型继续补全 JSON）
   - continuation 失败后使用 `_TRUNCATION_RETRY_MAX_TOKENS = 8192` 完整重试一次
   - `SYSTEM_PROMPT` 增加 `Start directly with the opening brace {` 与 `keep candidate reasoning concise` 约束
2. `llm_client.py`：
   - `_detect_content_truncation` 支持未闭合 markdown 代码块与任意位置未闭合 JSON 的检测
3. `aggregator.py`：
   - `merge_result` 直接透传 `inference_raw_response` / `inference_finish_reason` / `inference_is_truncated` 到报告

**修改文件清单**：`intern_s1.py`、`llm_client.py`、`aggregator.py`

**预期效果**：复杂题 Parse error 大幅下降；若仍有截断，报告会携带 `finish_reason="length"` 与 `raw_response`，便于进一步诊断。

---

### 四.十、2026-08-09 批量判题结果匹配失败（"未能在批量响应中找到"）

**现象**：评测报告中出现 `error_type=mathematical_error`，判题解释为"未能在批量响应中找到该题目的判定结果"，实际并非数学错误。

**根因**：`deepseek.py` 的 `parse_judge_batch_response` 要求 DeepSeek 在 JSON 响应中精确回写 `problem_id`（如 `【A4基础强化合并】1000题数一高数篇_0914`）。DeepSeek 偶尔会漏写、缩写或改写这个复杂中文 ID，导致 key 匹配失败，代码默认给 `is_correct=False` 且 `explanation` 标记为"未找到"。

**修复方案（4 处改动）**：
1. **短 ID 替换**：Prompt 和响应格式中不再使用中文 `problem_id`，改为 `P1`/`P2`/`P3` 短标签。模型需要回写的是 `"P1"` 而不是复杂中文，匹配成功率大幅提升。
2. **三层 fallback 匹配**：解析时先尝试 `problem_index`（P1/P2），失败 → 按数组位置匹配，失败 → 旧格式 `problem_id` 兼容。
3. **单题兜底**：解析后检测缺失题目，对缺失题自动调用 `run_judge()` 单题判题兜底，而非直接判错。
4. **截断重试修复**：单题和批量判题的截断重试从 `0.7 * max_tokens`（更少）改为 `1.5 * max_tokens`（更多，上限 4096/8192）。

**修改文件**：`deepseek.py`（`JUDGE_BATCH_SYSTEM_PROMPT` + `_run_judge_batch_chunk` + `parse_judge_batch_response` + `run_judge` 截断重试）

---

### 四.十一、2026-08-09 题目格式类型识别模块

**背景**：构建题目种类识别功能，在书生AI接到题目时先用AI自身判定题型，再生成对应的引导型提示词，然后让AI带着针对性提示词解答题目。

**实施方案**：

1. `prompts/question_type.py`（新建）：题型分类 LLM 提示词 + 六种题型的引导提示词字典
2. `agent/question_type.py`（新建）：`QuestionTypeClassifier` 继承 `BaseAgent`，两级分类（关键词预判 + LLM 精分类）
3. `agent/base.py`（修改）：`TaskContext` 新增 `question_type` / `question_type_hint` 字段
4. `agent/orchestrator.py`（修改）：流水线插入 `QuestionTypeClassifier`
5. `agent/solver.py`（修改）：注入题型引导提示词到 user_content，增强证明题检测
6. `user_agent.py`（修改）：新增 `enable_question_type_hint` 配置开关

**题型体系**：单选/多选/判断/证明/解答/填空，共六种。关键词预筛覆盖 ~70% 题目，剩余通过轻量 LLM（temperature=0.0，max_tokens=64）精分类。

---
*最后更新：2026-08-09（v2.3.1：Formatter 输出完整推理链 — 所有题型使用 reasoning 替代短答案）*

---

### 四.十二、2026-08-09 Formatter 输出完整推理链（v2.3.1）

**背景**：用户发现两个问题：1) 证明题的 final_response 只有结论，缺少分步证明过程；2) AI 输出没有完整逻辑链，只有简短的候选比较。

**根因**：`FormatterAgent.run()` 取 `best.answer`（短结论）而非 `best.reasoning`（完整推理过程），300 字符截断 + 包裹文字剥离进一步破坏文本结构。

**关键认识**：DeepSeek 判题需要看到完整逻辑推导链才能正确评估，所有题型都需要输出完整推理。

**修复方案**（`agent/formatter.py` 两处改动）：
1. `run()`：所有题型统一使用 `best.reasoning`；移除 300 字符截断；传入 `skip_wrapper_strip=True`
2. `_diagnose_and_repair()`：新增 `skip_wrapper_strip` 参数，跳过包裹文字剥离（步骤 4），保留步骤 1-3

**设计原则**：`candidate.answer` 不变（供 Verifier 比较）；修复在 Formatter 层面（不影响上游）；`question_type` 的前三个用途不受影响。

---

### 四.十三、2026-08-09 EvalConfig 字段缺失修复（v2.3.2）

**背景**：用户测试报告显示 Lean 审核报错 `'EvalConfig' object has no attribute 'lean_compiler'`，二次复核报错 `'EvalConfig' object has no attribute 'intern_s1_api_url'`。Lean 高报错比例并非 Lean 本身无法工作，而是配置类缺少字段导致代码崩溃。

**根因**：
- `EvalConfig`（config.py L63-66）仅定义 `intern_s1` 和 `deepseek` 两个字段，缺少 `lean_compiler` 和 `lean_timeout`
- `lean_verifier.py` L977 调用 `detect_lean_environment(config.lean_compiler)` 传入不存在的属性
- `detect_lean_environment()` 函数签名不接受参数，传入参数无意义
- `intern_s1.py` 两处使用 `cfg.intern_s1_api_url` 等扁平访问，但 `intern_s1` 是 `LLMConfig` 对象，正确路径是 `cfg.intern_s1.base_url`

**修复方案（3 个文件）**：
1. `config.py`：`EvalConfig` 新增 `lean_compiler: str = "lean"` 和 `lean_timeout: float = 0.0`
2. `lean_verifier.py` L977：`detect_lean_environment(config.lean_compiler)` → `detect_lean_environment()`
3. `intern_s1.py` L770-772 和 L915-917：`cfg.intern_s1_api_url` → `cfg.intern_s1.base_url` 等 6 处嵌套访问修复

**预期效果**：Lean 审核和二次复核恢复正常运行，不再因配置字段缺失崩溃。

---

### 四.十四、2026-08-09 LLMClient 构造参数不匹配 + lean_version 键名错误（v2.3.3）

**背景**：v2.3.2 修复后用户反馈问题依旧。深入排查发现 `.pyc` 缓存导致旧代码继续执行，以及两个更底层的 bug。

**根因**：
1. `LLMClient.__init__()` 签名为 `(self, config: LLMConfig)`，只接受一个 `LLMConfig` 参数
2. 但 `intern_s1.py` L769/L914 用 `LLMClient(api_url=..., api_key=..., model=...)` 传 3 个独立参数 → `TypeError: unexpected keyword argument 'api_url'`
3. L676/L1114/L1267 用 `LLMClient(cfg.intern_s1)` 是正确的（直接传 LLMConfig）
4. `detect_lean_environment()` 返回 `{"lean_version": ...}`，但 `_get_lean_env` L979 访问 `['version']` → `KeyError`

**修复方案（2 个文件 + 缓存清理）**：
1. `intern_s1.py` L769 + L914：`LLMClient(api_url=..., api_key=..., model=...)` → `LLMClient(cfg.intern_s1)`
2. `lean_verifier.py` L979：`_lean_env_cache['version']` → `_lean_env_cache.get('lean_version', 'unknown')`
3. 删除 `测试工具/__pycache__/` 中 3 个过期 `.pyc` 文件，强制重新编译

**诊断验证（全部通过）**：
- Config 字段：lean_compiler/lean_timeout/intern_s1 正常
- Lean 环境检测：Lean 4.31.0 可用
- LLMClient 构造：`LLMClient(cfg.intern_s1)` 正确
- 旧接口残留：0 处
- version 直接访问：0 处

---

*最后更新：2026-08-09（v2.3.3：LLMClient 构造修复 + lean_version 键名修复 — Lean 审核和二次复核完全恢复）*
