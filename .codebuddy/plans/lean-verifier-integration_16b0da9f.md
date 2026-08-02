---
name: lean-verifier-integration
overview: 在现有数学智能体评测器中新增 Lean 4 语言逻辑验证功能模块，通过将书生 AI 的错误推理转化为 Lean 代码，利用 Lean 编译器严格检查逻辑一致性，发现 DeepSeek 评判可能遗漏的逻辑错误，并生成针对性的修正提示词。
todos:
  - id: extend-models
    content: 在 models.py 中新增 LeanVerificationResult 数据模型，在 EvaluationResult 中添加 lean_verification 可选字段
    status: completed
  - id: extend-config
    content: 在 config.py 中新增 Lean 环境配置项（lean_executable_path），支持 .env 配置和自动检测
    status: completed
  - id: create-lean-verifier
    content: 新建 lean_verifier.py 模块，实现 Lean 编译器调用、转化 prompt 构建、错误分析 prompt 构建三个核心功能
    status: completed
    dependencies:
      - extend-models
      - extend-config
  - id: integrate-main-pipeline
    content: 在 main.py 中集成 Lean 验证流程，在批量模式和逐题模式的评判阶段后增加筛选和验证调用
    status: completed
    dependencies:
      - create-lean-verifier
  - id: extend-reporter
    content: 在 reporter.py 中扩展 JSON 报告和 HTML 报告，展示 Lean 验证结果和分析详情
    status: completed
    dependencies:
      - extend-models
---

## 用户需求

在现有的数学智能体评测器中新增 Lean 4 语言逻辑验证功能模块。将书生 AI 的推理过程和答案转化为 Lean 4 代码，发送给 Lean 编译器进行严格的形式化验证。Lean 编译失败后，通过 DeepSeek 分析区分是转化错误还是原始推理的逻辑错误。对于逻辑错误，定位具体断点并生成修正提示词，可反馈给书生 AI 重新推理。整个过程集成到现有评测流水线中，只对 DeepSeek 判定为错误或低置信度的题目触发验证。

## 产品概述

一个独立的 Lean 逻辑验证模块（lean_verifier.py），作为现有评测流水线的可选增强环节。它接收书生 AI 的推理结果，通过 DeepSeek 转化为 Lean 4 代码，调用本地 Lean 编译器验证，再由 DeepSeek 分析错误根因并输出人类可读的分析报告。

## 核心功能

- **筛选触发**：自动筛选 DeepSeek 判定为错误（is_correct=false）或低置信度（confidence &lt; 0.8）的题目进行 Lean 验证
- **推理转化**：通过 DeepSeek 将书生 AI 的自然语言推理过程转化为 Lean 4 代码（含 theorem + proof）
- **编译验证**：将 Lean 代码写入临时文件，调用 Lean 编译器验证，返回 pass/fail 和错误信息
- **根因分析**：编译失败时，再次调用 DeepSeek 分析错误根因，区分"转化错误"和"逻辑错误"
- **逻辑错误定位**：对于逻辑错误，指出推理中哪一步有问题、为什么错、正确的做法是什么
- **修正提示词生成**：自动生成一段可直接发给书生 AI 的修正提示词，帮助改进推理
- **结果记录**：将 Lean 验证结果（含分析报告）记录到 EvaluationResult 中，反映在 JSON 和 HTML 报告中

## 技术栈选择

- **编程语言**：Python 3.10+（与现有项目一致）
- **异步框架**：asyncio + httpx（复用现有 LLMClient）
- **Lean 编译器**：Lean 4 + mathlib4（通过 elan 安装，命令行调用）
- **转化引擎**：DeepSeek API（复用现有 LLMConfig 和 LLMClient）
- **数据模型**：dataclass（与现有 models.py 风格一致）
- **配置管理**：复用现有 config.py 的 .env 加载机制

## 实现方案

### 核心策略

采用三阶段异步流水线设计，与现有评测流程解耦：

1. **阶段一（转化）**：调用 DeepSeek 将自然语言推理转化为 Lean 4 代码，通过精心设计的 prompt 要求输出完整的 Lean 代码、形式化命题描述、以及预期编译结果的自我评估
2. **阶段二（编译）**：使用 subprocess 异步调用 `lake env lean` 命令验证代码，设置超时保护（60秒），捕获 stdout/stderr
3. **阶段三（分析）**：编译失败时，将原始推理、Lean 代码、编译错误信息一起发给 DeepSeek，由它分析根因并生成结构化分析报告

### 关键设计决策

**转化与分析的分离**：转化阶段只要求输出 Lean 代码，不要求分析；分析阶段才做根因判断。这样每个阶段的 prompt 职责清晰，输出更可靠。

**Lean 环境检测**：模块初始化时检测 Lean 是否可用（`elan --version`），不可用时降级为纯 DeepSeek 逻辑分析模式（不编译，直接让 DeepSeek 审查推理逻辑），保证模块的鲁棒性。

**错误分类策略**：让 DeepSeek 分析时同时输出 `error_category`（translation_error / logic_error / both / uncertain）和 `confidence`，并用 `expected_result` 字段做交叉验证：如果 DeepSeek 转化时认为代码应该通过编译（expected_result: "pass"）但实际编译失败，则更可能是转化错误。

**结果持久化**：Lean 验证结果作为 `EvaluationResult` 的新字段存储，在 JSON 报告中完整记录，在 HTML 报告中以折叠面板展示，不影响现有报告结构。

### 性能优化

- 转化和编译阶段设置超时（转化 API 120s，编译 60s），防止阻塞流水线
- 使用临时文件 + subprocess 而非进程池，避免资源泄露
- 编译错误信息截断（最多保留 5000 字符），减少分析阶段的 token 消耗
- 批量模式下，Lean 验证在评判完成后独立进行，不阻塞主流水线

### 可靠性保障

- Lean 不可用时自动降级，不影响核心评测流程
- 所有异常都被捕获并记录，不会导致整个评测中断
- 转化失败时最多重试 1 次（使用修正后的 prompt）
- 分析结果始终包含 `fix_prompt_for_ai` 字段，即使无法确定错误类型也提供通用修正建议

## 代理扩展

### SubAgent

- **code-explorer**
- 用途：在实现过程中探索现有项目结构、确认文件路径和 API 签名
- 预期结果：确保新增代码与现有项目架构完全兼容，复用现有模块接口