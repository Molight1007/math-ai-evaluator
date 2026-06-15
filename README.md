# 🧮 数学智能体评测器 — Math Agent Evaluator

> 🏆 **挑战杯** · AI 数学教育 · LLM 评测基准 · 大模型推理评估
>
> 基于 **Intern-S1（书生浦语）** + **DeepSeek** 的数学题自动评测流水线。
> 支持将 **PDF / Word / PPT / JSON / CSV** 格式的数学题集自动转化 → Intern-S1 推理 → DeepSeek 评判 → 生成可视化报告。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/Molight1007/math-ai-evaluator?style=social)](https://github.com/Molight1007/math-ai-evaluator)

**关键词：** `数学推理` `大模型评测` `AI教育` `LLM Evaluation` `Intern-S1` `DeepSeek` `Math Benchmark` `自动判题` `题库管理`

---

## 📑 目录

- [功能概览](#功能概览)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [使用指南](#使用指南)
- [工作流程](#工作流程)
- [核心模块](#核心模块)
- [报告输出](#报告输出)
- [题目格式](#题目格式)
- [代码规范](#代码规范)
- [环境要求](#环境要求)

---

## 🚀 功能概览

| 功能 | 说明 |
|------|------|
| 🖥️ **GUI 图形界面** | 可视化操作，支持文件拖放，一键评测 |
| 📝 **命令行评测** | 支持 PDF/Word/PPT/JSON/CSV 自动识别格式 |
| 📚 **题库管理** | 创建/删除题库，手动添加或批量导入题目 |
| 🔍 **AI 质量审核** | DeepSeek 自动审核题目质量，删除无效题并补全高质量新题 |
| 🏷️ **答案匹配** | 从 PPT/Word 答案文档自动提取并匹配到题库题目 |
| 📊 **可视化报告** | HTML 看板：准确率、分领域统计、逐题详情、耗时、Token 消耗 |
| ⚡ **并发推理** | 可配置并发数，批量高效处理 |
| 🔄 **格式转化** | PDF/Word/PPT → JSON 独立转化工具 |
| 🎨 **PPT 生成** | `make_ppt.js` 一键生成项目汇报 PPT |

---

## 📁 项目结构

```
挑战杯/
├── 测试工具/                   # 评测核心模块
│   ├── main.py                 # 命令行入口（自动识别输入格式）
│   ├── launcher.py             # GUI 图形界面入口（tkinter）
│   ├── config.py               # 配置管理（API Key、模型参数）
│   ├── models.py               # 数据模型（Problem、InferenceResult、JudgeResult 等）
│   ├── llm_client.py           # LLM 通用客户端（HTTP 请求、重试、JSON 提取）
│   ├── intern_s1.py            # Intern-S1 推理模块（分步推理、自验证）
│   ├── deepseek.py             # DeepSeek 评判模块（正确性判定、置信度）
│   ├── loader.py               # 题目加载器（JSON/CSV 解析、格式验证）
│   ├── aggregator.py           # 结果聚合器（推理+评判结果合并）
│   ├── reporter.py             # 报告生成器（HTML/JSON 输出）
│   ├── question_bank.py        # 题库管理（SQLite CRUD、导入导出、质量审核）
│   ├── answer_extractor.py     # 答案提取器（PPT/Word/TXT → 题目-答案对）
│   ├── answer_matcher.py       # 答案匹配引擎（DeepSeek 语义匹配）
│   ├── question_bank.db        # 题库数据库
│   └── templates/              # HTML 报告模板
│       └── report.html
├── 转化工具/                   # 格式转化工具
│   ├── convert.py              # 统一入口（PDF/Word → JSON）
│   ├── pdf_to_json.py          # PDF 解析转化
│   └── docx_to_json.py         # Word 解析转化
├── 测试结果/                   # 评测输出目录
│   ├── 测试结果展示/            # HTML 可视化报告
│   ├── 原始输出和推理过程/       # JSON 完整数据（含推理过程）
│   └── 原始问题/                # 使用的题目副本
├── 数学模型/                   # 数学建模相关文件
├── 题库/                       # 备用题库文件
├── 计划文件夹/                  # 项目计划文档
├── 下载版/                     # 完整发布版（含所有依赖和示例数据）
├── 代码要求.txt                # 代码规范文档（9大类50+条）
├── 启动评测器.bat              # Windows 一键启动脚本
├── make_ppt.js                 # PPT 自动生成脚本
├── requirements.txt            # Python 依赖清单
└── README.md                   # 本文件
```

---

## 🔧 快速开始

### 1. 环境准备

```bash
# 克隆仓库
git clone https://github.com/Molight1007/-csust.git
cd -csust

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 API Key（必须）

首次启动 GUI 时会自动弹出配置窗口，或点击「⚙️ 设置」按钮手动配置。

需要两个 API Key：

| 模型 | 用途 | 获取地址 |
|------|------|---------|
| **Intern-S1**（书生浦语） | 数学题推理 | [intern-ai.org.cn](https://intern-ai.org.cn) |
| **DeepSeek** | 答案正确性评判 | [platform.deepseek.com](https://platform.deepseek.com) |

配置保存在 `~/.math_evaluator/.env`，一次配置永久生效。

### 3. 启动运行

#### 方式一：GUI 图形界面（推荐）

```bash
# 双击启动
启动评测器.bat

# 或命令行启动
python 测试工具/launcher.py
```

操作流程：拖入文件 → 设置并发数 → 点击「开始评测」→ 浏览器自动打开报告。

#### 方式二：命令行

```bash
# 评测 PDF（自动转化）
python 测试工具/main.py -i 题目.pdf --max 10

# 评测 Word
python 测试工具/main.py -i 题目.docx

# 评测 JSON
python 测试工具/main.py -i 题目.json -c 5

# 参数说明
#   -i, --input    输入文件路径（.pdf/.docx/.pptx/.json/.csv）
#   -c, --concurrency  并发数（默认 3）
#   --max          最多评测题数（0=全部，仅 PDF/Word 有效）
#   -o, --output   自定义输出目录
```

---

## 📖 使用指南

### GUI 三大标签页

| 标签页 | 功能 |
|--------|------|
| 🚀 **快速评测** | 拖入文件 → 一键评测 → 浏览器查看报告 |
| 📚 **题库管理** | 创建题库、手动添加题目、批量导入、AI 质量审核、随机选题评测 |
| 🔍 **题库浏览** | 搜索、筛选、编辑、删除题目；浏览所有题库分类 |

### 题库管理功能

| 功能 | 说明 |
|------|------|
| **创建/删除题库** | 自由创建多个题库分类，如「高等数学」「线性代数」等 |
| **手动添加题目** | 逐题输入题目内容、所属领域、参考答案 |
| **从文件导入** | 支持 JSON 格式批量导入题目 |
| **随机选题评测** | 按数量随机抽取题目评测，支持领域筛选 |
| **AI 质量审核** | DeepSeek 自动审核题目质量，删除无效题并补全高质量新题 |
| **答案文档匹配** | 导入 PPT/Word 答案文档，自动匹配到题库对应题目 |

### 转化工具（独立使用）

```bash
# PDF → JSON
python 转化工具/convert.py 题目.pdf --max 50

# Word → JSON
python 转化工具/convert.py 题目.docx

# 指定输出路径
python 转化工具/convert.py 题目.pdf -o 输出.json
```

---

## 🔄 工作流程

```
输入: PDF / Word / PPT / JSON / CSV
              │
              ▼
      ① 自动识别格式
      （非 JSON 则调用转化工具）
              │
              ▼
      ② Intern-S1 推理
      （分步推理 + 自验证）
              │
              ▼
      ③ DeepSeek 评判
      （正确/错误 + 置信度 + 错误分类）
              │
              ▼
      ④ 结果聚合
      （推理 + 评判 合并为完整报告）
              │
              ▼
      ⑤ 生成三份报告
      ├── HTML 可视化看板（浏览器打开）
      ├── JSON 完整数据（含推理过程）
      └── 题目副本
```

### 推理流程详解

```
Intern-S1 推理:
  ① 分析问题（理解题意）
  ② 制定计划（解题思路）
  ③ 分步执行（逐步推导）
  ④ 自验证（检查结果）

DeepSeek 评判:
  ① 对比参考答案（如有）
  ② 验证推理过程
  ③ 判定正确/错误
  ④ 给出置信度（0~1）
  ⑤ 错误分类（计算错误/概念错误/逻辑错误等）
```

---

## 🧩 核心模块

| 模块 | 职责 | 关键类/函数 |
|------|------|------------|
| `models.py` | 数据模型 | `Problem`, `InferenceResult`, `JudgeResult`, `EvaluationResult` |
| `config.py` | 配置管理 | `EvalConfig`, `LLMConfig`, `save_config()`, `load_config()` |
| `llm_client.py` | LLM 客户端 | `LLMClient`（HTTP 请求、重试、JSON 提取） |
| `intern_s1.py` | 推理引擎 | `intern_s1_infer()`（分步推理 + 自验证） |
| `deepseek.py` | 评判引擎 | `deepseek_judge()`（正确性判定 + 置信度） |
| `loader.py` | 题目加载 | `load_problems()`（JSON/CSV 解析 + 格式验证） |
| `aggregator.py` | 结果聚合 | `aggregate()`（推理+评判合并为最终结果） |
| `reporter.py` | 报告生成 | `generate_report()`（HTML + JSON 输出） |
| `question_bank.py` | 题库管理 | `QuestionBankDB`（SQLite CRUD + AI 审核） |
| `answer_extractor.py` | 答案提取 | `extract_answers()`（PPT/Word/TXT → 题目-答案对） |
| `answer_matcher.py` | 答案匹配 | `match_answers_to_bank()`（DeepSeek 语义匹配） |
| `launcher.py` | GUI 界面 | `EvalLauncher`, `QuestionBankPanel`, `BankBrowserPanel` |
| `main.py` | 命令行入口 | `main()`（参数解析 + 流水线编排） |

---

## 📊 报告输出

每次评测生成带时间戳的报告，存放在 `测试结果/` 目录下：

| 目录 | 格式 | 内容 |
|------|------|------|
| `测试结果展示/` | HTML | 准确率、分领域统计、逐题详情、耗时、Token 消耗 |
| `原始输出和推理过程/` | JSON | 每题推理过程、评判结果、置信度、错误类型等完整数据 |
| `原始问题/` | JSON | 使用的题目文件副本 |

HTML 报告包含：
- 📈 总体统计卡片（准确率、平均置信度、总耗时、Token 消耗）
- 📊 分领域准确率图表
- 📋 逐题详情表格（可展开查看推理过程）
- ⏱️ 性能统计（平均推理时间、平均评判时间）

> GUI 中提供「🧹 清理结果」按钮，可一键清除所有历史评测文件。

---

## 📋 题目格式

### JSON 输入格式

```json
[
  {
    "id": "calc_001",
    "question": "求函数 f(x) = x³ - 3x² + 2 在区间 [-1, 3] 上的最大值和最小值。",
    "domain": "微积分",
    "reference_answer": "最大值为 2，最小值为 -2"
  }
]
```

| 字段 | 必填 | 说明 |
|------|:--:|------|
| `id` | ✅ | 题目唯一标识 |
| `question` | ✅ | 题目内容（支持 LaTeX 数学公式） |
| `domain` | ❌ | 所属知识域（如 微积分、线性代数、概率论） |
| `reference_answer` | ❌ | 标准答案（有则对照评判，无则仅推理） |

### PDF / Word 自动解析

转化工具会自动识别：
- 章节标题 → `domain`
- 数字序号 → 新题目
- 选择题 A/B/C/D 选项 → 合并入题目
- 参考答案/解析区域 → 自动跳过

---

## 📐 代码规范

本项目遵循统一的代码规范，详见 [`代码要求.txt`](代码要求.txt)，包含以下 9 大类：

| 类别 | 核心要求 |
|------|---------|
| 1. 冗余代码清理 | DRY 原则，删除无用 import/函数/变量 |
| 2. 中文注释规范 | 所有函数/类/模块含中文 docstring |
| 3. 命名规范 | PascalCase/snake_case，见名知义 |
| 4. 代码结构 | 单一职责，导入顺序：标准库→第三方→本地 |
| 5. 逻辑优化 | 合理数据结构，early return，避免深嵌套 |
| 6. 可维护性 | 常量提取，类型注解，参数校验 |
| 7. Bug 检测 | `py_compile` 语法检查，资源泄露检查 |
| 8. 运行效率 | I/O 优化，事件循环复用，缓存 |
| 9. 风格统一 | PEP 8，4空格缩进，行宽≤120字符 |

---

## ⚙️ 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | ≥ 3.10 | 运行环境 |
| httpx | ≥ 0.27.0 | HTTP 异步请求 |
| python-dotenv | ≥ 1.0.0 | 环境变量管理 |
| jinja2 | ≥ 3.1.0 | HTML 模板渲染 |
| tqdm | ≥ 4.66.0 | 进度条显示 |
| pdfplumber | ≥ 0.11.0 | PDF 解析转化 |
| python-docx | ≥ 1.1.0 | Word 解析转化 |
| python-pptx | ≥ 0.6.21 | PPT 答案提取 |
| pandas | ≥ 2.0.0 | CSV 数据处理（可选） |
| tkinterdnd2 | ≥ 0.3.0 | GUI 拖放支持（可选） |

```bash
# 一键安装全部依赖
pip install -r requirements.txt
```

---

## 📄 License

MIT License

---

<p align="center">
  <sub>Made with ❤️ for 挑战杯 · 数学智能体评测</sub>
</p>
