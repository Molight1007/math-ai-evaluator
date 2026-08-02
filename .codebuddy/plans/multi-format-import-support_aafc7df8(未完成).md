---
name: multi-format-import-support
overview: 为「导入答案」和「导入题目」两个功能扩展文件格式支持，新增 .ppt / .pdf / .md / .csv / .xlsx / .json 六种格式。
todos:
  - id: add-dependencies
    content: 更新 requirements.txt 添加 openpyxl 依赖
    status: pending
  - id: extend-answer-extractor
    content: 在 answer_extractor.py 中新增 extract_from_ppt/pdf/md/csv/xlsx/json 六个提取函数，扩展 extract_answers() 分发逻辑
    status: pending
    dependencies:
      - add-dependencies
  - id: extend-question-import
    content: 在 question_bank.py 的 import_from_file() 中新增 .ppt/.pptx/.md/.xlsx 分支，调用转化工具或 loader
    status: pending
    dependencies:
      - add-dependencies
  - id: add-convert-tools
    content: 在转化工具目录新增 ppt_to_json.py、md_to_json.py、xlsx_to_json.py 三个转化脚本
    status: pending
    dependencies:
      - add-dependencies
  - id: update-gui-filetypes
    content: 更新 launcher.py 中 3 处 filetypes（导入答案、导入题目、选题评测）以包含全部新格式
    status: pending
  - id: update-cli-help
    content: 更新 main.py 中 --import-answers 帮助文本以反映新的格式支持
    status: pending
---

## 用户需求

扩展「导入答案」和「导入题目」两个功能的文件格式支持范围，使其能够处理更多常见格式。

## 产品概述

当前项目的评测工具包含两个文件导入功能：「导入答案」用于将外部答案文档中的题目-答案对提取后智能匹配到题库；「导入题目」用于将外部题目文件批量导入题库。两者目前支持的格式有限，需要统一扩展到全部常见格式。

## 核心功能

- **导入答案**：从 .pptx / .docx / .txt 扩展支持 .ppt / .pdf / .md / .csv / .xlsx / .json
- **导入题目**：从 .pdf / .docx / .json / .csv 扩展支持 .ppt / .pptx / .md / .xlsx
- GUI 文件选择对话框同步更新所有格式过滤选项
- CLI 帮助文本更新以反映新的格式支持范围
- 新增依赖 openpyxl（处理 .xlsx），新增转化工具脚本（ppt_to_json / md_to_json / xlsx_to_json）

## 技术栈

- 语言：Python 3
- 现有依赖：python-pptx、python-docx、pdfplumber、pandas
- 新增依赖：openpyxl（.xlsx 读写）、markdown（可选，.md 解析）
- 旧版 .ppt 处理：优先使用 python-pptx（部分兼容），不兼容时提示用户用 PowerPoint 另存为 .pptx

## 实现方案

### 整体策略

采用「统一入口 + 格式分发」模式，在现有 `extract_answers()` 和 `import_from_file()` 中扩展 `elif` 分支，新增格式的提取逻辑尽量复用已有的 `_parse_answer_pairs()` 纯文本解析核心。

### 各格式实现方案

#### 1. .ppt（旧版 PowerPoint 97-2003）

- **导入答案**：尝试用 python-pptx 打开（部分 .ppt 可兼容），若失败则提示用户先用 PowerPoint 另存为 .pptx
- **导入题目**：同上策略，先尝试读取，失败给出明确指引
- 实现位置：`answer_extractor.py` 新增 `extract_from_ppt()`，`question_bank.py` 新增 .ppt 分支

#### 2. .pdf

- **导入答案**（新增）：用 pdfplumber 逐页提取文本，拼接后调用 `_parse_answer_pairs()` 解析
- **导入题目**（已有）：复用 `转化工具/pdf_to_json.py` 的 `convert_pdf()`
- 实现位置：`answer_extractor.py` 新增 `extract_from_pdf()`

#### 3. .md（Markdown）

- **导入答案**：直接读取文件文本，按 `##` / `###` 标题分段后调用 `_parse_answer_pairs()`
- **导入题目**：解析 Markdown 中的题目结构（按 `## 题目` 或数字序号分段），转为 Problem 列表
- 实现位置：`answer_extractor.py` 新增 `extract_from_md()`，`转化工具/md_to_json.py` 新增 `convert_md()`

#### 4. .csv

- **导入答案**（新增）：用 pandas 读取 CSV，自动识别题目列（question/problem/content）和答案列（answer/solution），按行生成答案对
- **导入题目**（已有）：复用 `loader.py` 的 `load_problems_from_csv()`
- 实现位置：`answer_extractor.py` 新增 `extract_from_csv()`

#### 5. .xlsx（Excel）

- **导入答案**：用 openpyxl 读取第一个工作表，按行列解析，自动识别题目列和答案列
- **导入题目**：用 openpyxl 读取，按行映射到 Problem 对象
- 实现位置：`answer_extractor.py` 新增 `extract_from_xlsx()`，`转化工具/xlsx_to_json.py` 新增 `convert_xlsx()`

#### 6. .json

- **导入答案**（新增）：读取 JSON，识别数组中的 question/answer 字段对，或 {"questions": [...]} 结构
- **导入题目**（已有）：复用 `loader.py` 的 `load_problems_from_json()`
- 实现位置：`answer_extractor.py` 新增 `extract_from_json()`

### 关键设计决策

- **复用核心解析器**：所有新增的答案提取函数最终都复用 `_parse_answer_pairs()` 和 `_split_question_answer()`，保证解析逻辑一致
- **列名自动识别**：CSV/XLSX/JSON 的答案提取使用别名映射（question/problem/content → 题目，answer/solution/reference_answer → 答案），与现有 `import_from_file` 中的 `_g()` 模式一致
- **旧版 .ppt 降级策略**：不引入重量级依赖（如 LibreOffice），优先尝试 python-pptx 读取，失败时给出明确提示引导用户转换格式，避免安装复杂性
- **新增转化工具保持风格一致**：新增的 `md_to_json.py` 和 `xlsx_to_json.py` 遵循现有 `docx_to_json.py` / `pdf_to_json.py` 的 CLI 接口和输出格式

## 实现细节

### 需要修改的文件（共 6 个）

| 文件 | 修改内容 |
| --- | --- |
| `测试工具/answer_extractor.py` | 新增 6 个提取函数（extract_from_ppt/pdf/md/csv/xlsx/json），扩展 extract_answers() 分发逻辑，更新模块文档字符串 |
| `测试工具/question_bank.py` | import_from_file() 新增 .ppt/.pptx/.md/.xlsx 分支，复用转化工具或 loader |
| `测试工具/launcher.py` | 3 处 filetypes 更新：导入答案（第558行）、导入题目（第288行）、选题评测（第1194行） |
| `测试工具/main.py` | 更新 --import-answers 帮助文本 |
| `requirements.txt` | 添加 openpyxl>=3.1.0 |
| `转化工具/` | 新增 ppt_to_json.py、md_to_json.py、xlsx_to_json.py |


### 性能注意事项

- CSV/XLSX 大文件（万行级）：逐行处理，不一次性加载全部到内存（pandas 已做优化）
- PDF 大文件：pdfplumber 逐页提取，不缓存全量页面对象
- 答案提取的列名识别使用简单的字符串包含匹配，O(n) 复杂度，无性能瓶颈

### 日志规范

- 复用现有 `logger = logging.getLogger(__name__)` 模式
- 每个提取函数记录格式+提取数量（如 "从 PDF 提取了 50 个答案对 (共 30 页)"）
- 格式不支持时抛出 ValueError 并给出支持的格式列表

### 向后兼容

- 所有现有格式的处理逻辑不变
- 仅新增 elif 分支，不影响已有 .pptx / .docx / .txt / .pdf / .json / .csv 的处理

## Agent Extensions

### Skill

- **xlsx**
- 用途：验证 .xlsx 文件的读取逻辑和列名识别方案是否正确，参考最佳实践
- 预期结果：确保 openpyxl 的使用方式正确，列名映射逻辑可靠

- **pdf**
- 用途：验证 .pdf 格式答案提取中 pdfplumber 的使用方式
- 预期结果：确保 PDF 文本提取逻辑与现有 pdf_to_json.py 保持一致

- **docx**
- 用途：参考现有 docx_to_json.py 的模式来设计 md_to_json.py 和 xlsx_to_json.py
- 预期结果：新增转化工具与现有工具风格统一

### SubAgent

- **code-explorer**
- 用途：在实现过程中验证 loader.py 的 load_problems 函数签名和 Problem 模型定义
- 预期结果：确保新增格式的导入逻辑与现有类型系统兼容