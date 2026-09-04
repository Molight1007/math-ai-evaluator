# lean-lsp-mcp 最小冒烟报告（执行计划 Step 2 产出）

> 日期：2026-09-04 | 环境：Windows 11 + Git Bash；Lean 4.31.0（elan）；lean-lsp-mcp **0.30.0**（PyPI，2026-09-04 实测最新）
> venv：`C:/Users/35174/leanlsp-venv`；探针：`C:/Users/35174/lean_lsp_smoke/`；工程：`D:/mathlib4-last_bump_for_v4.31.0`（LEAN_PROJECT_PATH）

## 一、环境兼容性（原最大不确定点 → 已解除）

| 项 | 结果 |
|---|---|
| leanclient 0.13.2 × Lean 4.31.0 LSP | ✅ 兼容（init 2.4s；诊断/goal/verify 全通） |
| Windows stdio 启动 | ✅ venv + console script `lean-lsp-mcp.exe` 正常 |
| import Mathlib.Tactic | ✅（与 LeanBridge 相同，用 Tactic 入口；聚合入口 Mathlib.olean 两边都缺，非阻塞） |
| 工具可用性 | 23 个工具全部注册（诊断/目标/verify/搜索/构建…） |

## 二、verdict 一致性对照（核心结论：与 LeanBridge 完全一致，且定位/可靠性更强）

| 用例 | 性质 | LeanBridge（lake env lean） | lean-lsp-mcp | 一致性 |
|---|---|---|---|---|
| 01_ok | 正确证明 ×2 | **pass**（exit 0，仅 unused var 警告，19s） | diagnostic `success:true`，1 warning @9:14（首文件冷启动 49s） | ✅ |
| 02_unknown | **009 真题翻译**（自造常量 `Real.rts`） | **fail**：8×`Unknown constant Real.rts` 行 8/9/11/12（20s） | fail：8×error，**列级精确**（8:23/8:49/9:9/…）（38s） | ✅ |
| 03_logic | **假上界**（009 型中段错：claim ≤170/7 为假） | **fail**：`linarith failed` @13:2 + 目标状态（20s） | fail：error @13:3 完整目标；**lean_goal@13 秒回完整 goal state**（⊢ x/(y+13)+…≤170/7） | ✅ |
| 04_sorry | **sorry 假证明** | ⚠️ **pass（漏判！）** exit 0，仅 warning "declaration uses sorry"（19s） | diagnostic warning @6:9；**lean_verify → axioms 含 `sorryAx` → 判不可信**（27.7s） | ❌ **LeanBridge 漏，MCP 拦截** |

## 三、耗时画像（vs LeanBridge 每题 5-21s 全量编译）

- 首文件冷启动（lean server + Mathlib olean 加载）：**38-49s**；同一 session 后续文件：**19-26s**（缓存复用，接近 lake 冷启动单次）
- **增量红利**：文件 elaboration 完成后，`lean_goal`/再次诊断**秒回（0-2s）**——子目标级逐行探查几乎免费；多轮"改一行→再诊断"无需重编译全文件
- 结论：单文件单次判定 MCP 无优势（甚至更慢）；**多文件/多轮/子目标级迭代场景 MCP 显著占优**

## 四、冒烟结论

1. **Go**：lean-lsp-mcp 本地可用、判定与 LeanBridge 一致、能行级定位中段错、`lean_verify` 拦截 LeanBridge 抓不到的 sorry。
2. 对本项目最有价值的 3 个能力（按杠杆排序）：
   - **lean_verify**（sorryAx/axioms 可靠性判定）→ 直接补 lean_gate 漏洞（lake 编译对 sorry 判 pass！）
   - **lean_goal**（任意行 goal state）→ "中段第 3-4 步悄悄错"（003/009/053 型）的子目标级定位通道
   - **结构化诊断**（行/列 + severity）→ 比 lake stderr 更干净的错因喂给验证-精炼 loop
3. 局限：首文件冷启动 40-50s；平台无 MCP 生态 → 仅本地评测/材料证据链。

## 五、遗留注意

- ripgrep 未装 → lean_verify 源码模式扫描（unsafe/implemented_by）暂缺（仅 axioms 可用）；本地 rg 装后自动启用
- lean_verify 参数名实测为 `theorem_name`（README 示例为 declaration_name，文档滞后）
- 会话退出时 asyncio 资源清理在 Windows 打 ResourceWarning 噪音（无害）
