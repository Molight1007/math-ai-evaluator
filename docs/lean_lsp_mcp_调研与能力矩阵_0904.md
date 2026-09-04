# lean-lsp-mcp 调研与能力矩阵（执行计划 Step 1 产出）

> 日期：2026-09-04 | 计划：`lean_lsp_mcp对接计划_0904.md` Step 1
> 调研对象：fraware/lean-lsp-mcp（PyPI 包名 lean-lsp-mcp，作者 Oliver Dressler / oOo0oOo）

---

## 一、仓库现状（结论：活跃维护，可试）

| 项 | 事实 |
|---|---|
| 仓库 | github.com/fraware/lean-lsp-mcp（原 oOo0oOo，README 引证仍标 oOo0oOo） |
| 最新版本 | **0.23.2**（pyproject 2026-03-08 Release）；main 分支最后提交 2026-03-04/06 |
| 维护状态 | ✅ 活跃（Lean Together 2026 有官方 talk；持续加功能：local_search namespace、lean_verify 等） |
| 依赖 | `leanclient==0.9.3`、`mcp[cli]==1.26.0`、orjson、certifi；python>=3.10 |
| 安装 | `uvx lean-lsp-mcp` 或 `pip install lean-lsp-mcp`（PyPI 有包） |
| Lean 版本 | **通过项目自带 lake serve 启动 Lean LSP**（按 lean-toolchain 解析），协议层通信由 leanclient 承担 → 我们本地 v4.31.0 是否兼容 leanclient 0.9.3 **需实测（Step 2）**，这是主要不确定点 |
| 环境变量 | `LEAN_PROJECT_PATH=<lake 工程根>`（默认 cwd） |
| 可选依赖 | ripgrep（lean_local_search / lean_verify 源码扫描）、PyYAML |
| 许可 | MIT，beta 阶段（研究工具） |

## 二、MCP 工具清单（按对我们的用途分类）

### A. 验证判定类（替代/增强 LeanBridge 判分）
- **lean_diagnostic_messages**：文件全部诊断（info/warn/error），带 `l行c列` 精确定位 → 行级错误定位（比 lake 整文件 stderr 结构化）
- **lean_goal**：指定行/列的 proof goal（tactic state）→ **子目标级检查**（对应 009/003/053 中段错定位）
- **lean_verify**：**定理可靠性检查**：返回 axioms + 源码模式扫描（unsafe / debug.* / implemented_by）→ `sorryAx` 等非标准公理直接暴露（LeanBridge 的 lake 编译对 sorry 是 pass 的，lean_gate 需另查 sorry；MCP 一步到位）
- **lean_proofs_complete**：文件内 proofs 完整性检查（简单实现）
- **lean_term_goal / lean_hover_info**：类型/文档查证（翻译质量检查辅助）

### B. 证明开发辅助类
- **lean_multi_attempt**：一行试多个 tactic 返回各自 goal state + 诊断（不落盘试错；`LEAN_REPL=true` 时走 REPL ~5x 快）
- **lean_code_actions**：LSP "Try This"（simp?/exact?/apply? 的替换建议）
- **lean_profile_proof**：按行耗时 profile（simp 慢在哪）

### C. 检索类
- **lean_local_search**：本地工程+stdlib 声明检索（防 API 幻觉；需 rg）
- 外搜：lean_leansearch（leansearch.net 官方，**我们已在用**）、lean_loogle、lean_leanfinder、lean_state_search、lean_hammer_premise

### D. 工程类
- lean_file_outline / lean_build（重建工程+重启 LSP server）

## 三、数学 agent 验证先例

- **没有直接"LLM 解题→lean-lsp-mcp 自动判定对错"的公开先例**（我们的用法是全新的）；现有用法集中在**交互式证明开发辅助**（Claude Code/Codex/VSCode agent 模式：auto proof、分析证明、设计证法）。
- 相关项目：LeanTool、LeanExplore MCP、"Agentic Coding Skill: Lean 4 Theorem Proving"（官方配套 prompt 模板）。
- lean_verify 的 sorryAx/axioms 机制说明作者关注"判定可靠性"，与我们 lean_gate 语义契合。

## 四、三方能力矩阵

| 维度 | LeanBridge（自研，现状） | lean-lsp-mcp（MCP/LSP） | LeanSearch v2 API（远程，在用） |
|---|---|---|---|
| 本质 | lake env lean 全量编译文件 | LSP 增量诊断（lean server 常驻） | 远程引理检索（premise retrieval） |
| 验证粒度 | 整文件编译 pass/fail | 行/列级诊断 + 任意行 goal state | 不验证，只检索 |
| 错误定位 | stderr 文本 `file:line:col: error(...)` | 结构化诊断 `l行c列` + severity + TaggedText | — |
| 中段逻辑错定位 | ✗ 只有首错+后续堆错，难以逐子目标 | ✅ lean_goal 逐行看 goal 推进；诊断给到错步 | — |
| sorry 拦截 | ✗ lake 编译 pass（需另查） | ✅ lean_verify 直接列 axioms（sorryAx） | — |
| 单次耗时 | 5-21s（每次全量） | 常驻进程，首文件加载 olean 慢（数秒~分钟），后续增量快 | 网络往返 |
| 依赖/环境 | lean.exe（本地必有） | uv/leanclient+Python venv + lake 工程（本地） | 外网（平台无） |
| 与 agent 耦合 | 紧（bridge 内嵌） | 服务化（MCP stdio/HTTP），结构解耦 | 服务化（已接 lean_search.py） |
| 平台可用 | ✅ 平台部署版（LEAN_PATH 闭包） | ❌ 平台无 MCP 生态（仅本地评测/材料） | ❌ 平台无外网 |
| 维护/成熟 | 自研，稳定可控 | 活跃，beta | 官方 |

## 五、可行性结论（Step 1）

1. **lean-lsp-mcp 值得试**：活跃、工具集正中"中段错定位 + 可靠性判定（sorry/axioms）"两个痛点，服务化结构与老师"避免自研耦合"诉求一致。
2. **最大不确定点 = leanclient 0.9.3 与 Lean 4.31.0 LSP 兼容性**（本地 v4.31.0 是 2026 版 toolchain）→ Step 2 实测首务。
3. 即便 MCP 路径不落地，**lean_verify（sorryAx 拦截）+ lean_goal（子目标定位）两个能力值得以任何形态吸收**进验证器错因质量（杠杆点：验证器错因质量）。
4. 平台判分不受影响（无 Lean/MCP），价值在本地证据链 + 材料（40%）。
