# 数学智能体评测器

> 基于 **Intern-S1（书生浦语）** + **DeepSeek** 的数学题自动评测流水线。

支持将 **PDF / Word / JSON / CSV** 格式的数学题集，自动转化为 JSON → 交 Intern-S1 推理 → 交 DeepSeek 评判 → 生成可视化报告。

---

## 📁 项目结构

```
├── 测试工具/               # 评测核心代码
│   ├── main.py             # 命令行入口（自动识别格式）
│   ├── launcher.py         # GUI 图形界面入口
│   ├── question_bank.py    # 题库管理（创建/导入/审核）
│   ├── question_bank.db    # SQLite 题库数据库
│   └── ...
├── 转化工具/               # 格式转化工具
│   ├── convert.py          # 统一入口（PDF/Word → JSON）
│   ├── pdf_to_json.py      # PDF 转化
│   └── docx_to_json.py     # Word 转化
├── 测试结果/               # 评测输出
│   ├── 测试结果展示/         # HTML 可视化报告
│   ├── 原始输出和推理过程/    # JSON 完整数据
│   └── 原始问题/             # 题目副本
├── requirements.txt        # Python 依赖
├── 启动评测器.bat           # 一键启动 GUI
└── README.md
```

---

## 🔧 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. ⚠️ 配置 API Key（必须！）

首次启动 GUI 时会自动弹出设置窗口，或点击「设置」按钮手动配置。

需要两个 API Key：

| 模型 | 用途 | 获取地址 |
|------|------|---------|
| **Intern-S1**（书生浦语） | 数学推理 | [intern-ai.org.cn](https://intern-ai.org.cn) |
| **DeepSeek** | 答案评判 | [platform.deepseek.com](https://platform.deepseek.com) |

> **不配置 API Key 将无法运行！**

### 3. 运行

#### 方式一：GUI 图形界面（推荐）

```bash
双击 启动评测器.bat
```

拖入 PDF/Word/JSON 文件 → 点「开始评测」→ 浏览器自动打开报告。

#### 方式二：命令行

```bash
# 直接丢 PDF（自动转化）
python 测试工具/main.py -i 题目.pdf --max 10

# 丢 Word
python 测试工具/main.py -i 题目.docx

# 丢 JSON
python 测试工具/main.py -i 题目.json -c 5

# 参数说明
#   -i    输入文件（.pdf / .docx / .json / .csv）
#   -c    并发数（默认 3）
#   --max 最多评测题数（0=全部，仅 PDF/Word 有效）
```

---

## 📚 题库评测（新功能）

GUI 切换到「📚 题库评测」选项卡，支持：

| 功能 | 说明 |
|------|------|
| **创建/删除题库** | 自由创建多个题库分类 |
| **手动添加题目** | 逐题输入题目、领域、参考答案 |
| **从文件导入** | 支持 JSON 批量导入 |
| **随机选题评测** | 按数量随机抽取题目评测 |
| **领域筛选** | 评测时可指定数学领域范围 |
| **🔍 AI 质量审核** | 调用 DeepSeek 自动审核题目质量，删除无效题目并补全高质量新题 |
| **题目搜索/删除** | 支持关键词搜索，逐题管理 |

---

## 🔄 工作流程

```
PDF / Word / JSON / CSV
        │
        ▼
  自动识别格式（非 JSON 则自动调用转化工具）
        │
        ▼
  Intern-S1 逐题推理
        │
        ▼
  DeepSeek 对照答案评判（正确/错误 + 置信度）
        │
        ▼
  生成三份报告：
  ├── HTML 可视化看板（浏览器打开）
  ├── JSON 完整数据（含推理过程）
  └── 题目副本
```

---

## 📊 报告内容

每次评测生成带时间戳的报告，存放在 `测试结果/` 目录下：

| 目录 | 格式 | 内容 |
|------|------|------|
| `测试结果展示/` | HTML | 准确率、分领域统计、逐题详情、耗时、Token 消耗 |
| `原始输出和推理过程/` | JSON | 每题推理过程、评判结果、置信度等完整数据 |
| `原始问题/` | JSON | 使用的题目文件副本 |

> GUI 中提供「清理结果」按钮，可一键清除所有历史评测文件。

---

## 🛠 转化工具

独立使用转化工具（不评测，只转化格式）：

```bash
# PDF → JSON
python 转化工具/convert.py 题目.pdf --max 50

# Word → JSON
python 转化工具/convert.py 题目.docx

# 指定输出路径
python 转化工具/convert.py 题目.pdf -o 输出.json
```

---

## 📋 题目格式

### JSON 输入格式

```json
[
  {
    "id": "calc_001",
    "question": "求函数 f(x) = x^3 - 3x^2 + 2 在区间 [-1, 3] 上的最大值和最小值。",
    "domain": "微积分",
    "reference_answer": "最大值为 2，最小值为 -2"
  }
]
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✅ | 唯一标识 |
| `question` | ✅ | 题目内容 |
| `domain` | ❌ | 所属领域（如 微积分、线性代数） |
| `reference_answer` | ❌ | 标准答案（有则对照评判，无则仅推理） |

### PDF / Word 自动解析

转化工具会自动识别：
- 章节标题 → `domain`
- 数字序号 → 新题目
- 选择题 A/B/C/D 选项 → 合并入题目
- 参考答案/解析区域 → 自动跳过

---

## ⚙️ 环境要求

- Python 3.10+
- 依赖：`httpx`, `python-dotenv`, `jinja2`, `tqdm`, `pdfplumber`, `python-docx`

```bash
pip install -r requirements.txt
```
