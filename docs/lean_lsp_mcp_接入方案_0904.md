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

### 档 1（✅ 已完成 09-04，零 MCP 依赖）——补验证可靠性漏洞
- 证据：裸 `lake env lean` 对 `sorry` 假证 exit=0 仅 warning；lean_bridge._compile_lean 原有源码 `\bsorry\b` 检查（直接写 sorry 会拦），但 **axiom/unsafe/implemented_by/skipKernelTC 等不可信构造不在检查面**
- 改动（已落地 agent/lean_bridge.py，三方本地同步）：pass 判定扩展为不可信构造集合扫描 + 输出侧 `uses \`sorry\`` 兜底；allow_sorry=True 声明模式不变；19 单测全绿 + 真实 lake 编译 5 用例冒烟通过（clean pass / sorry 拦 / **axiom 拦** / **unsafe 拦**）
- 收益：验证可靠性漏洞就地补齐（lean_verify 完整 axioms 检查仍是档 2/后续增强选项）

### 档 2（✅ 已完成 09-04，实验可选后端）——定位/错因增强
- 落地（agent/lean_bridge.py 改动 + 新增 agent/lean_mcp_proxy.py）：
  - 后端开关：环境变量 `LEAN_BACKEND=mcp` 或 config.lean_backend="mcp"（默认 bridge 不动）；
    mcp 仅在 **lake 工程目录**分发（平台/临时目录直编自动回落 bridge）
  - **零主进程依赖**：mcp 判定经子进程代理（venv python 跑 lean_mcp_proxy.py，JSONL 一问一答），
    主进程（3.14）不装 mcp SDK；venv 探测 `~/leanlsp-venv` / 环境变量 LEAN_MCP_PYTHON
  - 判定语义与 bridge 完全对齐（error items → fail；allow_sorry 声明模式；
    档1 不可信构造扫描共用 `_scan_untrusted`）；**附加 lean_goal 定位**：fail 时把首个错误行
    的目标状态拼进 error（`--- [lean-lsp-mcp] 首个错误行目标状态 ---`），喂 _analyze_error
  - 可靠性：proxy 进程崩溃/超时/无 venv → 自动回落 bridge；模块级单例 + 线程锁（多 worker 串行化）
- 验证：**23 个新单测全绿 + 全量 299 passed 无回归**；真实冒烟 bridge vs mcp **7/7 判定一致**
  （clean/sorry/axiom/unsafe/009 翻译错/假上界/语法错），goal 定位段实测输出
- 使用：本地评测设 `LEAN_BACKEND=mcp` 即走 LSP 后端；平台不设（无 venv）自动 bridge

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

- 档 1：✅ 已完成（09-04）：改动 + 19 回归 + 真实编译 5 用例冒烟；三方本地同步，未 push
- 档 2：✅ 代码适配完成（09-04）：23 新单测 + 全量 299 passed + bridge/mcp 真实 7 用例判定一致；
  三方本地同步，未 push。**A/B 评测待用户安排**（wrong10b/45 题，本地 `LEAN_BACKEND=mcp` 对照）；
  若 A/B 无正增益证据 → 材料仍可用"档 1 + 冒烟/对照证据"，档 2 降级为可选工具
- 主风险：MCP 常驻进程在长评测（2-3h）中的稳定性（看门狗/超时回落已内建：崩溃自动回落 bridge）
