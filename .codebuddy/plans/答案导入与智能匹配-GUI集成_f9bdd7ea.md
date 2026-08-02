---
name: 答案导入与智能匹配-GUI集成
overview: 在 launcher.py 的题库管理面板中添加「导入答案文档」按钮和交互流程，让用户可以通过 GUI 将 PPT/Word 格式的答案导入并智能匹配到题库。
todos:
  - id: add-import-btn
    content: 在 launcher.py 的 QuestionBankPanel.__init__ 中 row3 添加「📥 导入答案」按钮和 self._import_running 标志
    status: completed
  - id: add-import-methods
    content: 添加 _import_answers（文件选择+启动线程）、_run_import_answers_async（调用 db.import_answers_from_file）、_on_import_done（结果展示）三个方法
    status: completed
    dependencies:
      - add-import-btn
  - id: show-coverage-in-stats
    content: 修改 _update_stats_and_list 方法，调用 db.get_answer_mapping_stats 并在 stats_var 中追加显示答案映射覆盖率
    status: completed
    dependencies:
      - add-import-btn
---

## 用户需求

在现有 GUI 题库管理面板中添加「导入答案」功能，让用户选择 PPT/Word 答案文档后，由 DeepSeek 自动匹配答案到题库题目，匹配结果入库用于辅助后续评测（提升准确率）。

## 功能概述

- 在「题库评测」选项卡的按钮行（row3）添加「📥 导入答案」按钮
- 点击后弹出文件选择对话框，支持 .pptx / .docx / .txt 格式
- 选择文件后自动执行：提取答案 → DeepSeek 语义匹配 → 写入 answer_mapping 表
- 显示进度条和实时状态，完成后弹出结果摘要
- 刷新题库统计时自动显示答案映射覆盖率

## 技术方案

### 实现策略

在 `launcher.py` 的 `QuestionBankPanel` 类中新增：

1. 一个「📥 导入答案」按钮（加入 row3）
2. 一个 `_import_answers` 方法（处理文件选择 + 后台线程 + 进度更新 + 结果展示）
3. 一个 `_run_import_answers_async` 方法（在线程中调用 `db.import_answers_from_file()`）
4. 修改 `_update_stats_and_list` 方法，在统计信息中追加答案映射覆盖率

### 关键设计决策

- **复用已有 API**：直接调用 `db.import_answers_from_file()`，无需修改后端代码
- **后台线程执行**：参考现有 `_start_audit_quality` / `_run_audit_async` 模式（第420-502行），使用 `threading.Thread` + `daemon=True`，避免阻塞 GUI
- **进度回调**：通过 `self.launcher.root.after(0, lambda: ...)` 安全更新 GUI
- **统计信息增强**：在 `_update_stats_and_list` 中调用 `db.get_answer_mapping_stats()`，将覆盖率追加到 `stats_var` 显示

### 实现细节

- 文件选择：`filedialog.askopenfilename`，过滤 `.pptx/.docx/.txt`
- 按钮禁用：导入期间禁用 `import_answer_btn`，防止重复点击
- 错误处理：捕获所有异常，通过 `messagebox.showerror` 展示
- 完成提示：`messagebox.showinfo` 展示导入摘要（提取数/匹配数/入库数/覆盖率/耗时）