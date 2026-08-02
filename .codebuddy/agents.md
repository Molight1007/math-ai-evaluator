# MathPilot 项目 Agents 配置与开发规范

> **用途**：此文件是 AI 助手的操作手册。每次处理本项目任务时必须遵循本文档的规则。
> **维护规则**：每次项目有重大变更时，同步更新此文件。

---

## 一、项目概述

**MathPilot** — 基于 Intern-S 系列大模型的多智能体数学解题系统，参加"挑战杯"竞赛。

- **核心架构**：`Classifier → Solver → Verifier → Formatter` 简洁流水线（v2.2 借鉴 ss-main）
- **关键模块**：`agent/`（核心智能体）、`prompts/`（提示词模板）、`utils/`（工具函数）、`测试工具/`（本地评测系统）
- **竞赛提交版**：`赛事提交版/` 目录是正式提交的独立副本（v2.3：已同步全部本地优化，通过官方测试）

---

## 二、项目启动方式

### 2.1 环境要求

```bash
pip install -r requirements.txt
# 依赖：httpx>=0.24.0, sympy>=1.12
```

### 2.2 核心入口

| 入口文件 | 用途 |
|---|---|
| `user_agent.py` | **竞赛平台唯一入口** — `ReasoningAgent` 类，被平台调用 |
| `run_eval.py` | **本地评测脚本** — 批量运行测试集并统计结果 |

### 2.3 启动方式

**竞赛模式**（由平台调用，无需手动启动）：
```python
from user_agent import ReasoningAgent, AgentConfig
agent = ReasoningAgent(platform_client)      # client 由平台注入
result = agent.solve("题目文本", {})         # solve(problem, metadata) → dict
```

**本地评测模式**（手动运行，需先配置 LLM 连接）：
```bash
# 方式 A: 环境变量
export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 或其他兼容服务
export LLM_MODEL="gpt-4"
python run_eval.py --test_file tests.jsonl --output results.jsonl --concurrency 2 --resume

# 方式 B: 命令行参数
python run_eval.py --test_file tests.jsonl --api_key sk-xxx --base_url https://api.openai.com/v1 --model gpt-4
```

**测试工具**（独立的完整评测系统）：
```bash
cd 测试工具
python main.py
```

---

## 三、测试流程

### 3.1 本地评测（`run_eval.py`）

```bash
# 基础用法
python run_eval.py --test_file <题目文件.jsonl> --output <结果文件.jsonl>

# 并发评测（推荐 4 并发）
python run_eval.py --test_file tests.jsonl --output results.jsonl --concurrency 4

# 断点续跑
python run_eval.py --test_file tests.jsonl --output results.jsonl --resume
```

### 3.2 测试工具完整评测流水线

`测试工具/main.py` 是完整的评测器，支持 PDF/Word/PPT/Markdown/Excel/JSON/CSV 自动导入：

```
题目导入 → Intern-S1 推理 → DeepSeek 评判 → Lean 验证 → HTML 报告生成
```

### 3.3 测试结果目录

- `测试结果/原始输出和推理过程/` — JSON 推理报告
- `测试结果/原始问题/` — JSON 题目文件
- `测试结果/测试lean文件/` — Lean 形式化验证
- `测试结果/测试结果展示/` — HTML 可视化报告

---

## 四、代码风格规范

### 4.1 注释规范（来自 `代码规范化与注释整理` 计划）

- **模块级**：每个 `.py` 文件顶部必须有中文 docstring 说明模块用途
- **类/函数级**：每个公开类和方法必须有中文 docstring，可保留原有英文 docstring 作为补充
- **复杂逻辑**：关键算法（JSON 提取回退、字符映射、异步线程嵌套）必须添加行内中文注释
- **禁止**：完全重复的注释、与代码自解释内容重复的注释、无意义的装饰性分隔符

### 4.2 代码组织规范

- **最小改动原则**：修改代码时只改必要的部分，不重构不相关的代码结构
- **不改变函数签名**：除非绝对必要，不修改已有函数的接口
- **不修改业务逻辑**：仅修复 bug 或添加新功能，不改动已验证的逻辑
- **import 规范**：所有 import 必须在文件顶部，不允许在函数/循环内部 import

### 4.3 Python 代码风格

- 使用 4 空格缩进
- 类名使用 PascalCase（如 `ReasoningAgent`、`TaskContext`）
- 函数/变量使用 snake_case（如 `extract_final_answer`、`conf_high`）
- 私有方法前缀 `_`（如 `_regulate`、`_vote`、`_equiv_group`）
- 常量使用 UPPER_SNAKE_CASE（如 `_META_PATTERNS`、`DOMAIN_HINTS`）
- docstring 使用中文，关键术语保留英文

### 4.4 命名约定

| 类型 | 约定 | 示例 |
|---|---|---|
| 类名 | PascalCase | `ClassifierAgent`, `Budget` |
| 函数/方法 | snake_case | `extract_final_answer`, `_are_answers_equivalent` |
| 私有方法 | `_` 前缀 | `_regulate`, `_vote` |
| 常量 | UPPER_SNAKE_CASE | `_KNOWN_DOMAINS`, `VERIFIER_SYSTEM` |
| 布尔变量 | `is_` / `has_` / `use_` 前缀 | `use_scoring`, `by_enable_fast_path` |
| 配置项 | snake_case | `policy_sample_times`, `conf_high` |
| 模块文件 | snake_case | `sympy_tools.py`, `user_agent.py` |

---

## 五、不能修改的文件和目录

### 5.1 竞赛平台硬性约束（绝对不能动）

| 文件/目录 | 原因 |
|---|---|
| `user_agent.py` 中的 `ReasoningAgent` 类和 `AgentConfig` 类 | 平台固定入口，改名/改签名会导致无法运行 |
| `赛事提交版/` 目录 | 竞赛正式提交版，与根目录同步但需独立维护（已同步 v2.3 全部优化） |
| `LICENSE` | MIT 许可证 |

### 5.2 核心架构文件（谨慎修改）

这些文件定义了系统架构，修改需要充分理解影响：

| 文件 | 敏感原因 |
|---|---|
| `agent/base.py` — `TaskContext`、`Budget`、`BaseAgent` | 所有 Agent 的基类，修改会影响全局 |
| `agent/orchestrator.py` — `Orchestrator.run()` | 编排器主入口，流程核心 |
| `prompts/policy.py` — `DOMAIN_HINTS` | 33 个领域提示词，LLM 输出的关键 |

### 5.3 参考资源（只读，不要修改）

| 目录 | 原因 |
|---|---|
| `其他案例/` | 高分参考样例，用于学习而非修改 |
| `数学建模参考资料/` | 参考论文和赛题说明 |
| `计划文件夹/` | 竞赛申报材料 |
| `项目资料/` | 已提交的项目文档 |

### 5.4 外部工具链（不要修改）

| 目录/文件 | 原因 |
|---|---|
| `lean4-toolchain/` | Lean 4 工具链安装，环境依赖 |
| `与lean相关的插件/` | Lean 4 测试环境和 mathlib |
| `node_modules/` | 前端依赖 |

---

## 六、AI 助手协作规则（极其重要）

### 6.1 必须使用多 Agent 并行处理

**当任务可以被拆分时，必须使用 Subagent（`Task` 工具）并行处理。不要串行执行可以并行的任务。**

适用于以下场景：
- 同时读取/分析多个文件 → 每个文件一个 Subagent
- 同时搜索不同内容 → 每个搜索一个 Subagent  
- 需要同时处理前后端 → 前端一个 Subagent + 后端一个 Subagent
- 代码审查 → 用一个 Subagent 专门做 review
- 大规模代码探索 → 用 `code-explorer` Subagent

**不适用**：简单的单文件修改、单步操作。

### 6.2 Subagent 类型

| Subagent | 用途 |
|---|---|
| `code-explorer` | 大规模代码库探索、多文件搜索、项目结构分析 |
| 自定义 Agent（Team mode） | 复杂多步骤任务，需要异步协作时创建 |

### 6.3 A2A（Agent-to-Agent）协作

当任务复杂到需要多个 Agent 协作时：
- 使用 `team_create` 创建团队
- 用 `Task` 工具 + `name` 参数启动团队成员
- 成员间通过 `send_message` 通信
- 完成后用 `team_delete` 清理

**团队模式适用场景**：
- 前后端同时开发
- 多个独立功能模块并行实现
- 需要不同专业领域 Agent 协作（如：一个写代码 + 一个写测试 + 一个做审查）

### 6.4 处理优先原则

1. **先分析，再动手**：修改代码前必须先充分阅读相关文件
2. **能并行就并行**：批量读取、批量搜索
3. **最小改动**：只改必要的部分，不过度重构
4. **文件越大越谨慎**：大文件用 `replace_in_file` 做精准修改，不重写

### 6.5 文件更新后必须做的事

每次修改项目代码后，必须同步更新：
1. **`.codebuddy/agents.md`**（本文档）— 如果启动方式/代码风格/不可动文件有变化
2. **`.codebuddy/memory.md`** — 记录项目当前状态的变化

---

## 七、项目架构速查

```
user_agent.py (平台入口)
  └── ReasoningAgent
       └── Orchestrator.run()  [v2.2 简化版：无回环]
            ├── ClassifierAgent (题型识别, 31领域)
            ├── SolverAgent (3候选并行，无蓝图分解)
            │    └── prompts/policy.py (领域提示)
            ├── VerifierAgent (每候选1票 + 聚类选优)
            │    └── AnswerCluster (等价答案簇)
            ├── FormatterAgent (答案规范化)
            └── 快车道 (_fast_path: SymPy 确定性求解)
```

### 核心数据流

```
问题输入
  → Classifier: 题型 → domain
  → 快车道检查: 可 SymPy 求解 → 直接输出（1次LLM）
  → Solver: 生成候选解答 (policy_sample_times 次并行)
  → Verifier: 每个候选投 1 票 → 聚类选最大簇
  → Formatter: 选最优答案+规范化输出
```

### 关键配置参数（AgentConfig v2.2）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `policy_sample_times` | 3 | 候选解答数量 |
| `verifier_voting_times` | 1 | 每候选投票次数（不再重复投票） |
| `max_tokens_cap` | 12288 | 内部 token 裁剪上限（修复：原4096） |
| `max_total_calls` | 10 | LLM 调用总上限（从40降至10） |
| `max_time_per_question` | 300s | 单题时间上限（从1100s降至300s） |
| `use_blueprint` | False | 关闭蓝图分解（对Intern-S不友好） |
| `use_scoring` | False | 关闭多维评分（简化） |
| `by_enable_fast_path` | True | 启用快车道(SymPy) |

---

## 八、已知待优化问题

参考 `MathPilot优化分析.md`：

| 优先级 | 问题 | 状态 |
|---|---|---|
| P0 | SymPy 真实工具集成 | ✅ v2.0 — utils/sympy_tools.py + orchestrator._fast_path |
| P0 | 符号等价聚类投票 | ✅ v2.0 — verifier.AnswerCluster + SymPy compare_expr |
| P0 | Verifier 多维评分接线 | ✅ v2.0 — _vote_one_scoring (correctness/logic/clarity/completeness/overall) |
| P1 | 证明题专用通道 | ✅ v2.0 — prompts/proof.py + solver._generate_proof + verifier._verify_proof_step |
| P1 | 自纠错反馈结构化 | ✅ v2.0 — VERIFIER_FEEDBACK 输出半结构化文本（错误步骤+类型+方向） |
| P1 | 引理/记忆机制 | ✅ v2.0 — base.TaskContext.lemma_repo（最多5条，防token爆炸） |
| P2 | 防思考链污染 | ✅ v2.0 — base.detect_thinking_contamination + detect_template_leak |
| P2 | 本地评测闭环 | ✅ v2.0 — run_eval.py（JSONL批量/并发/断点续/领域统计） + utils/llm_client.py |
| P2 | 壁钟时间守卫（竞赛新规则适配） | ✅ v2.1 — base.TaskContext + orchestrator 三级时间检查点 |
| P3 | trace 脱敏与可解释增强 | 待实现 |
| P0 | v2.2 简化架构（借鉴 ss-main） | ✅ 完成 — 去除回环/蓝图/重复投票，修复 token 截断 |

---

*最后更新：2026-08-02（v2.3：6项优化同步到赛事提交版，官方测试全部通过）*
