# lean-lsp-mcp 对接验证·汇总报告（执行计划 Step 5 产出）

> 日期：2026-09-04 | 全流程：调研 → 冒烟 → 方案 → 对照 → 报告（`lean_lsp_mcp对接计划_0904.md` 执行完毕）

## 一、可行性结论：**可行（Go），本地评测价值明确，平台不受影响**

1. **技术全通**：lean-lsp-mcp（PyPI **0.30.0**，活跃维护）在 Windows + Lean 4.31.0 本地可用；leanclient 0.13.2 × Lean 4.31.0 LSP 兼容（原最大不确定点，冒烟解除）。
2. **verdict 100% 一致**：8 用例 × 双后端（lake env lean vs MCP diagnostic）全覆盖一致（pass/fail × 未知常量/假上界/假边界/语法/不可证/sorry）。
3. **超出 LeanBridge 的三个能力（按杠杆排序）**：
   - ⭐ **lean_verify 可靠性判定**：抓 `sorryAx`/非标准 axioms——完整解法覆盖源码 sorry 正则漏掉的 **axiom/unsafe/implemented_by 等不可信构造**（诚实修正：lean_bridge._compile_lean 原本已拦源码直接写的 sorry，真实漏洞面是源码 sorry 之外的构造，已由**档 1** 就地补齐，2026-09-04）
   - ⭐ **行级/子目标级定位**：结构化 `l行c列` 诊断 + `lean_goal` 任意行 goal state（elaboration 后秒回）→ 003/009/053 型"中段第 3-4 步悄悄错"有增量探查通道 → 直击"验证器错因质量"杠杆（IMO 2025 论文 5/6=85.7% 的支点）
   - 结构化诊断文本（含反设上下文）→ 喂给验证-精炼 loop 的 BugReport 更干净

## 二、接入收益预估（9/15 前）

| 档 | 内容 | 成本 | 收益 | 风险 |
|---|---|---|---|---|
| **档 1（✅ 已完成 09-04）** | lean_bridge pass 判定扩展不可信构造扫描：源码 sorry/axiom/unsafe/implemented_by/skipKernelTC + 输出侧 `uses \`sorry\`` 兜底 | ~1h（已改+19 单测+真实编译 5 用例冒烟；三方同步完成，未 push） | 补 axiom/unsafe 等可靠性漏洞（源码 sorry 原已拦） | ≈0 |
| **档 2（✅ 代码适配完成 09-04）** | `LEAN_BACKEND=mcp` 可选后端：lean_bridge 分发 + proxy 子进程（零主进程依赖）+ lean_goal 行级定位进 error | 新增 23 单测 + 全量 299 passed 无回归；bridge/mcp 真实 7 用例判定一致；三方同步完成，未 push | 行级/目标级错因定位（对 63% 推理错误的错因质量杠杆）；结构服务化（老师诉求） | 中（常驻进程稳定性；**A/B 待用户安排**，无增益则作可选工具） |

- 结构收益（老师诉求"避免自研耦合"）：档 2 落地即"验证后端服务化"，agent 主流程不动，仅换后端。
- 平台：无 MCP 生态 → 平台判分不变（仍 AI 判分 + Lean 证据链材料）；**本地证据链与材料分（40%）直接受益**（报告可写"双后端交叉验证 + sorry 拦截"）。

## 三、9/15 前决策建议

1. **档 1 已落地（09-04）**：不可信构造拦截进 lean_bridge，三方本地同步完成、**未 push**。
2. **档 2 代码适配已完成（09-04）**：`LEAN_BACKEND=mcp` 即用（见接入方案档 2）。**A/B 评测由用户安排**（wrong10b/45 题本地对照）；无正增益证据则降级为可选工具，材料用档 1 + 冒烟/对照证据。
3. **不触碰**：agent 主流程、prefill/答案锚定框架（验证后端与 LLM 提示层正交，兼容性已验证）。

## 四、产出文件

| 文件 | 内容 |
|---|---|
| `docs/lean_lsp_mcp_调研与能力矩阵_0904.md` | Step1：仓库/工具/先例/三方矩阵 |
| `docs/lean_lsp_mcp_冒烟报告_0904.md` | Step2：兼容性 + 4 用例 verdict 对照（含 sorry 漏判实证） |
| `docs/lean_lsp_mcp_接入方案_0904.md` | Step3：方案 A/B + 分档实施 + Go/No-Go 判据 |
| `docs/lean_lsp_mcp_对照数据_0904.md` | Step4：8 用例双后端数据 + 定位/耗时 |
| `C:/Users/35174/lean_lsp_smoke/` | 探针/批量脚本（可复跑）；venv `C:/Users/35174/leanlsp-venv` |

## 五、待确认/遗留

- [x] 档 1（lean_bridge 不可信构造拦截）✅ 已完成 09-04，三方本地同步，未 push
- [x] 档 2（lean_backend=mcp 代码适配 + proxy + 定位）✅ 已完成 09-04，三方本地同步，未 push；**A/B 评测待用户安排**
- [ ] 老师所指"lean-lsp-mcp"是否确为此仓库（fraware/lean-lsp-mcp）——推荐已确认，汇报时附链接核对
- [ ] 用户级记忆更新：lean-lsp-mcp 适配完成（bridge/mcp 双后端可用）
- [ ] ripgrep 未装 → lean_verify 源码扫描（unsafe 等）暂缺，装 rg 后自动启用
- [ ] 平台 Lean 部署方向与此正交（lean-lsp-mcp 仅本地评测用）
