# lean-lsp-mcp 接入方案设计（执行计划 Step 3 产出）

> 日期：2026-09-04 | 依据：Step1 调研 + Step2 冒烟（`lean_lsp_mcp_调研与能力矩阵_0904.md`、`lean_lsp_mcp_冒烟报告_0904.md`）

## 一、方案选项

### 方案 A（增强，推荐）：LeanBridge 兜底 + MCP 作为可选增强后端
- LeanBridge 保持现状为默认后端（平台/无 MCP 环境可用）
- 新增 `lean_backend: bridge | mcp` 配置（默认 bridge），mcp 后端走 lean-lsp-mcp（stdio 单实例常驻）
- 引入位置：**agent/lean_bridge.py 内做后端抽象**（`_verify_with_backend`），判定语义不变（编译通过性 + 错误文本），不触碰 agent 主流程（老师红线：只换验证后端）
- MCP 后端额外能力（不进判定，只进错因）：
  1. 诊断失败 → **lean_goal 取首个错误行前/后的 goal state** → 结构化进 BugReport（错因质量杠杆）
  2. pass 前追加 **lean_verify 可靠性判定**（sorryAx/非标准 axioms → 降级 fail）

### 方案 B（替换）：agent Lean 调用全走 MCP —— **不推荐**
- 平台无 MCP 生态；首文件冷启动 40-50s；常驻进程生命周期（保活/崩溃恢复/并发）运维成本高；LeanBridge 已稳定验证（084 可对）。结构解耦诉求用 A 的后端抽象满足即可，无需物理替换。

## 二、分档实施建议（9/12 代码冻结前的时间约束）

### 档 1（零 MCP 依赖，立即可做，风险≈0）——补 lean_gate 可靠性漏洞
- 证据：lake env lean 对 `sorry` 假证 **exit=0 判 pass**（仅 warning `declaration uses 'sorry'`）→ LeanBridge/lean_gate 目前会把 sorry 证当 pass
- 改动：lean_bridge 编译 **pass 判定加一道输出扫描**：stdout 匹配 `declaration uses 'sorry'` / `sorryAx` / `unsafe` → 判 fail（伪码 ≤10 行）
- 收益：验证可靠性立即提升，是 lean_verify 逻辑的"穷人版"（覆盖 sorry 主威胁，不含 axioms 全查）

### 档 2（引 MCP，实验性可选后端）——定位/错因增强
- 落地：lean_bridge 新增 `LeanMcpBackend`（mcp stdio client 封装：懒启动单实例 + 请求超时 + 失败自动回落 bridge）
- 三处消费点改造均保持输出协议不变：
  - preverify / verify_answer / lean_gate 的 fail 诊断 → 附带 lean_goal 定位文本
  - lean_gate deep 档多候选 → 同一 session 顺序判定（省进程启动，后续文件 19-26s/个）
  - 修复重试轮（refiner/self-improve 改代码后重判）→ LSP 增量秒回
- **不进主流程默认路径**：仅在本地评测 A/B 生效，平台/提交版仍 bridge

## 三、Go/No-Go 判据（Step4 验证后定）

| 判据 | 阈值 |
|---|---|
| verdict 一致性（bridge vs mcp） | 8+ 用例 100% 一致 |
| 定位精度 | fail 用例全部给出错误行，且 error 行 = 主张/翻译错行 |
| 耗时 | 常驻 session 内连续判定 ≤ 单次 lake 冷启动（19s 基线） |

## 四、兼容性结论

- prefill / 答案锚定 / `_answer_embedded`：LLM 提示与校验层，与验证后端无关 → 完全兼容
- LeanBridge 输出协议（verdict/error）被 lean_gate/preverify/verify_answer 消费 → 后端抽象保持协议即可无缝
- 平台部署（LEAN_PATH 闭包直编）：不受影响（MCP 仅本地）
- 依赖：仅本地评测机需 venv（lean-lsp-mcp 0.30.0 + leanclient 0.13.2，已验证 Lean 4.31.0 兼容）；不进主仓库依赖声明（按可选 extras）

## 五、时间与风险

- 档 1：≤1h 改动 + 45 题 A/B 验证（2-3h，9/12 前可完成）
- 档 2：1-2 天改动 + wrong10b/45 题 A/B；**若 9/10 前无正增益证据 → 砍掉**，材料用档 1 + Step2 冒烟证据
- 主风险：MCP 常驻进程在长评测（2-3h）中的稳定性（看门狗/超时回落需做好）
