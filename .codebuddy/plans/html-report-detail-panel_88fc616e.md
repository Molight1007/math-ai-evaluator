---
name: html-report-detail-panel
overview: 在评测报告 HTML 页面中，为每道题目添加可点击的详情弹窗功能，展示书生AI的完整思考过程（reasoning/steps/verification）和 DeepSeek 的判题解释（judge_explanation/error_type/correct_answer）。
design:
  architecture:
    framework: html
  styleKeywords:
    - Glassmorphism Modal
    - Clean Minimalist
    - Card-based Layout
    - Smooth Transitions
    - Code-block Aesthetic
    - Status-colored Accents
  fontSystem:
    fontFamily: "'Segoe UI', 'Microsoft YaHei', -apple-system, sans-serif"
    heading:
      size: 18px
      weight: 700
    subheading:
      size: 14px
      weight: 600
    body:
      size: 13px
      weight: 400
  colorSystem:
    primary:
      - "#2563EB"
      - "#7C3AED"
      - "#00C5FF"
    background:
      - "#FFFFFF"
      - "#F8FAFC"
      - "#F1F5F9"
      - "#EFF6FF"
      - "#F5F3FF"
    text:
      - "#1E293B"
      - "#475569"
      - "#94A3B8"
      - "#FFFFFF"
    functional:
      - "#10B981"
      - "#EF4444"
      - "#F59E0B"
      - "#3B82F6"
todos:
  - id: modify-row-data
    content: 修改 reporter.py 表格行生成逻辑，为每行 tr 添加 data-detail JSON 属性和可点击样式类
    status: completed
  - id: add-modal-css
    content: 在 generate_html_report 的 CSS 区新增 Modal 弹窗完整样式（含遮罩、卡片、各内容区块）
    status: completed
  - id: add-modal-html
    content: 在 HTML 模板中 table 后面添加 Modal 弹窗的 DOM 结构（含头部、题目信息、AI推理区、判题分析区）
    status: completed
  - id: add-modal-js
    content: 添加 JavaScript 逻辑：showDetail/hideModal 函数、ESC 关闭、遮罩点击关闭、分步推理动态渲染
    status: completed
    dependencies:
      - modify-row-data
      - add-modal-css
      - add-modal-html
---

## Product Overview

在现有的 Math Agent Evaluation Report HTML 报告页面中，为 Detailed Results 表格中的每行题目添加**点击查看详情**功能。用户点击题目行（或专门的查看按钮）后，弹出详情模态弹窗(Modal)，展示该题目的完整 AI 推理过程和判题分析信息。

## Core Features

- **可点击的表格行/按钮**: Question 列或整行添加点击交互，鼠标悬停有视觉提示（cursor: pointer, 高亮效果）
- **模态弹窗 (Modal)**: 点击后弹出居中浮层，包含以下分区展示：
- **题目基础信息区**: 完整题干、参考答案、AI 给出的最终答案
- **书生 AI 思考过程区**: 完整推理文本 (`intern_reasoning`)、分步推理列表 (`intern_steps` 数组)、自验证过程 (`intern_verification`)
- **DeepSeek 判题分析区**: 判题解释 (`judge_explanation`)、错误类型 (`error_type`)、判题给出的正确答案 (`correct_answer_judge`)、置信度 (`confidence`)
- **性能指标区**: 推理耗时、判题耗时、Token 消耗
- **弹窗交互**: 支持 ESC 键关闭、点击遮罩层关闭、点击关闭按钮关闭；弹窗内容区域支持长文本滚动；代码块/公式类内容使用等宽字体
- **视觉区分**: 正确/错误的题目在弹窗头部用绿色/红色标识，与现有报告风格保持一致

## 数据来源

所有数据已完整存储在 `EvaluationResult` 对象中（来自 JSON 报告），无需修改后端或数据库：

- AI 输出字段: `intern_answer`, `intern_reasoning`, `intern_steps`(list), `intern_verification`
- 判题输出字段: `judge_explanation`, `error_type`, `correct_answer_judge`, `confidence`, `is_correct`

## Tech Stack

- **语言**: Python 3.x（修改 reporter.py 的 HTML 生成逻辑）
- **前端**: 纯 HTML + CSS + JavaScript（无外部依赖，静态单文件报告）
- **方案**: 在 `reporter.py` 的 `generate_html_report()` 函数中，将全量评测数据以 `data-*` 属性嵌入表格行 `<tr>`，通过内联 JS + CSS 实现 Modal 弹窗交互

## Implementation Approach

### 核心策略：纯前端 Modal 方案（零依赖）

由于 HTML 报告是**静态单文件**（无服务器、无构建工具），采用纯原生 HTML/CSS/JS 实现是最优解：

1. **数据嵌入**: 将每条 `EvaluationResult` 的全量字段序列化为 JSON 字符串，存入 `<tr>` 的自定义属性 `data-detail` 中
2. **触发交互**: Question 列文字添加 `clickable-question` 类和 `onclick` 事件，鼠标悬停时显示下划线+指针变化
3. **Modal 结构**: 在 HTML 末尾添加一个隐藏的 Modal DOM 结构（固定定位、居中显示、半透明遮罩）
4. **JS 逻辑**: 

- `showDetail(rowElement)` - 从 `data-detail` 解析 JSON，填充 Modal 各区域并显示
- `hideDetail()` - 隐藏 Modal
- ESC 键监听 + 遮罩点击关闭

5. **样式设计**: Modal 使用毛玻璃背景(glassmorphism)、圆角卡片、分区块布局，与现有浅色主题一致但更有层次感

### 关键技术决策

| 决策 | 选择 | 原因 |
| --- | --- | --- |
| 数据传递方式 | `data-detail` JSON 属性 | 单次嵌入、按需解析、无需额外请求 |
| 弹窗实现 | 内联 CSS + 原生 JS | 零依赖、兼容性最好 |
| 长文本处理 | `white-space: pre-wrap` + `max-height` 滚动 | 推理过程可能很长，需可控展示 |
| 分步推理渲染 | 有序列表 `<ol>` | `intern_steps` 是数组，列表形式更清晰 |


### 性能考量

- 数据在页面加载时即嵌入，无需异步请求，弹窗打开瞬间响应
- Modal 默认 `display:none`，不影响初始渲染性能
- 对于 5~50 题规模的报告，`data-*` 属性的总大小在 KB~几十 KB 级别，完全可接受

## Architecture Design

```
reporter.py (唯一修改文件)
├── generate_html_report() 主函数
│   ├── 行数据构建循环 (新增 data-detail 属性)
│   ├── CSS 样式区 (新增 .modal / .modal-content 等样式)
│   ├── Modal HTML 结构 (新增在 </table> 之后)
│   └── JavaScript 逻辑 (新增 showModal/hideModal/ESC监听)
│
└── 输出: 完整的单文件 HTML 报告（含内联样式和脚本）
```

## Directory Structure

```
d:/挑战杯/
└── 测试工具/
    └── reporter.py    # [MODIFY] 唯一需要修改的文件
                         # 1. 表格行生成逻辑：添加 data-detail JSON 属性 + 可点击 class
                         # 2. CSS 区：新增 Modal 弹窗完整样式（~100行）
                         # 3. HTML 区：新增 Modal DOM 结构
                         # 4. Script 区：新增弹窗控制 JS 逻辑
```

## Implementation Notes

- 保持现有报告风格不变（浅色主题、卡片布局、统计摘要），Modal 作为叠加层
- `_escape_html()` 函数必须用于所有插入 HTML 的动态内容，防止 XSS 和公式/特殊字符破坏结构
- `intern_steps` 是 list 类型，需在 Python 端用 `json.dumps()` 序列化后再 escape
- `data-detail` 中的 JSON 需要双重转义处理（先 JSON 编码，再 HTML 转义）
- 向后兼容：即使某字段为空值，弹窗对应区域也应优雅降级显示"暂无数据"
- 不引入任何外部库或 CDN 依赖，确保报告可在离线环境打开

## 设计概述

在现有浅色主题报告基础上，添加一个精致的模态弹窗(Modal)详情面板。弹窗采用现代 Glassmorphism 设计风格，与原有页面形成层次对比但整体协调统一。

### 页面规划（仅1个核心页面变更）

**HTML 报告页 - 详情弹窗**

#### Block 1: 弹窗遮罩层

半透明深色背景遮罩（rgba(0,0,0,0.5)），覆盖整个视口，点击可关闭弹窗。带有淡入淡出过渡动画。

#### Block 2: 弹窗主体卡片

居中白色卡片容器，最大宽度 800px，高度最大 85vh，带圆角(16px)阴影和微弱毛玻璃效果。顶部右侧有关闭按钮(X)。

#### Block 3: 弹窗头部

左侧显示题目 ID 和正确/错误状态标签（绿色 Correct 或红色 Wrong），右侧显示置信度百分比。底部有一条细分割线。

#### Block 4: 题目基础信息区（双列布局）

左列：完整题干文本（灰色背景代码块样式，等宽字体）。右列：参考答案 + AI 最终答案，各自独立卡片。

#### Block 5: 书生 AI 思考过程区（核心区域）

标题栏带 AI 图标标识（蓝色调）。内容分为三个子区块：

- 完整推理过程（大文本框，pre-wrap 格式保留换行缩进）
- 分步推理（有序列表 <ol>，每步一个编号项，交替行背景色便于阅读）
- 自验证结论（独立高亮框）

#### Block 6: DeepSeek 判题分析区

标题栏带判断图标标识（紫色调）。内容包括：

- 判题详细解释（主文本区）
- 错误类型标签（如 incomplete / calculation_error，黄色徽章）
- 判题给出的正确答案（绿色边框高亮框）

#### Block 7: 性能指标底栏

横向排列推理耗时、判题耗时、Token 消耗三项指标，紧凑型数字卡片。

## Agent Extensions

- **coding**
- Purpose: 负责修改 `reporter.py` 文件，实现 Modal 弹窗功能的 HTML/CSS/JS 代码编写，确保代码质量和最佳实践
- Expected outcome: 产出完整的、可直接运行的 reporter.py 修改版本