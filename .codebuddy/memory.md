# MathPilot 项目状态记忆

> **用途**：记录项目当前状态，每次修改后同步更新。
> **维护规则**：每次代码变更后更新对应状态。此文件供 AI 助手快速了解项目当前情况，避免重复探索。

---

## 一、项目当前概况

| 属性 | 值 |
|---|---|
| 项目名称 | MathPilot |
| 竞赛 | 挑战杯 — 基于 Intern-S 系列大模型的数学智能体 |
| 主分支 | main |
| 最后活跃日期 | 2026-08-01 |
| 项目阶段 | **v2.2 简化版 — 借鉴 ss-main 架构，大幅削减 LLM 调用** |

---

## 二、模块状态

### 2.1 核心智能体模块 (`agent/`)

| 文件 | 状态 | 说明 |
|---|---|---|
| `base.py` | ✅ v2.1 | TaskContext + 壁钟追踪 + Budget + BaseAgent |
| `classifier.py` | ✅ 稳定 | 31 领域题型识别 |
| `solver.py` | ✅ v2.2 | 候选生成（蓝图关闭、证明通道关闭） |
| `verifier.py` | ✅ v2.2 | 每候选1票 + 聚类选优（移除 feedback 提取） |
| `formatter.py` | ✅ 稳定 | 共识聚类加权 + 答案规范化 |
| `orchestrator.py` | ✅ v2.2 | **简化版**：无 _regulate 回环、无 _ensure_completeness |
| `__init__.py` | ✅ 稳定 | 包导出 |

### 2.2 提示词模块 (`prompts/`)

| 文件 | 状态 | 说明 |
|---|---|---|
| `policy.py` | ✅ 稳定 | 通用解题 + 33 领域提示 + 蓝图策略 |
| `proof.py` | ✅ v2.0 | 证明题专用提示词（反证/归纳/构造 + 分步编号） |
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
| `user_agent.py` | ✅ v2.1 | ReasoningAgent + AgentConfig（竞赛参数精简：40调用/3候选/2投票） |
| `run_eval.py` | ✅ v2.1 | 本地评测脚本（修复导入/API/LLMClient，新增 --api_key/--base_url/--model） |

### 2.5 测试工具 (`测试工具/`)

| 文件 | 状态 | 说明 |
|---|---|---|
| `main.py` | 稳定 | 完整评测器主入口，依赖独立 LLM client |
| `intern_s1.py` | 稳定 | Intern-S1 推理模块 |
| `problem_type_detector.py` | 稳定 | 18 种题型检测 |
| `verify_phase6.py` | 稳定 | Phase 6 验证 |
| `verify_phase6_3.py` | 稳定 | Phase 6.3 约束验证 |
| `multi_agent_runner.py` | ❌ 缺失 | 测试工具 --multi-agent 模式桥接层（待创建） |

### 2.6 Web 服务 (`Web服务模块/`)

| 文件 | 状态 | 说明 |
|---|---|---|
| `api/users.db` | 12KB SQLite | 用户数据库 |

### 2.7 其他目录

| 目录 | 状态 | 说明 |
|---|---|---|
| `赛事提交版/` | ✅ v2.3 | 竞赛正式提交版（已同步6项本地优化，通过官方测试） |
| `submit/` | 空壳 | 仅含目录结构 |
| `测试结果/` | 历史数据 | 多批次 JSON/HTML/Lean 输出 |
| `题库/` | SQLite | question_bank.db |

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
| - | 四 Agent 协作架构 | 责任分离，每 Agent 可独立优化 |
| - | Verifier 聚类投票替代重复投票 | 更准+更省调用 |
| - | SymPy 快车道为先 | 确定性问题即时求解，省预算给难题 |

---

*最后更新：2026-08-02（v2.3：6项优化同步到赛事提交版）*
