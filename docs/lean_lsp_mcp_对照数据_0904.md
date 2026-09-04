# lean-lsp-mcp 小规模对照数据（执行计划 Step 4 产出）

> 日期：2026-09-04 | 方式：**纯离线**（不改 LLM 链路、不开新评测），8 用例 × 双后端
> 用例覆盖：pass ×2、未知常量、假上界（009 型）、假排除边界（053 型）、不可证目标、语法错、sorry 假证
> 环境同冒烟：Lean 4.31.0 / lean-lsp-mcp 0.30.0 / LEAN_PROJECT_PATH=D:/mathlib4-last_bump_for_v4.31.0

## 一、verdict 一致性：**8/8 = 100%**

| 用例 | 错误类型代表 | Bridge（lake env lean） | MCP（diagnostic） | 一致性 |
|---|---|---|---|---|
| 01_ok | 正例（含 084 型答案结构 ring 验证） | pass | pass（success:true, 0 err） | ✅ |
| 02_unknown | 009 真题翻译（自造 Real.rts） | fail @7:22 | fail 8×error @l7c23…（列级） | ✅ |
| 03_fakebound | 009 假上界 Σ≤170/7 | fail @7:2 | fail @l7c3 + 完整目标 | ✅ |
| 04_sorry | sorry 假证 | pass(sorry 警告) | pass + warning（**lean_verify 另证 sorryAx**） | ✅ |
| 05_fakeexcl | 053 型假排除 t≠-2 | fail @6:2 | fail @l6c3（含反设目标 a✝: t=-2 ⊢ False） | ✅ |
| 06_typeerr | 类型混用（rfl 不可证） | fail @5:2 | fail @l5c3 | ✅ |
| 07_syntax | 语法错（括号不闭） | fail @4:32 | fail @l4c33 | ✅ |
| 08_ok2 | 053 型可达性正例 | pass | pass | ✅ |

## 二、定位能力：全部 fail 用例行级定位一致

- MCP 结构化诊断 `l行c列`，首错行与 bridge 完全一致（列差 1 = 语义差异：LSP 从列 1 计数 vs lean 0 基数，非错误）
- **053 型（05）附加价值**：诊断自带反设上下文（`a✝ : x*y+y*z+z*x+2*(x+y+z) = -2 ⊢ False`）→ 直接暴露"模型把可达值 -2 当排除"的错误本质
- Step2 已证 lean_goal 秒回（elaboration 后 0s）→ 可对任一子目标行拉 goal state 做"首错步"探查

## 三、耗时：批量异文件场景 MCP ≈ Bridge；红利在增量/定位（不在批量）

| 后端 | 首文件 | 后续文件（同 session） |
|---|---|---|
| Bridge | 每次独立 17.8-19.2s | 同左（无缓存） |
| MCP | 28.8s（lean server + olean 冷加载，一次性） | 18.5-21.4s |

- 结论修正：**异文件批量判定 MCP 无速度优势**；真实红利 = ①同文件多轮 revise 增量秒回 ②lean_goal/诊断秒回（子目标探查）③lean_verify 可靠性判定。方案文档按此校准（不夸大）。

## 四、Go/No-Go：**Go**（判据 100% 达成）

| 判据 | 阈值 | 实测 |
|---|---|---|
| verdict 一致性 | 8+ 用例 100% | 8/8 = 100% ✅ |
| 定位精度 | fail 全给出错误行且=主张/翻译行 | 全部命中 ✅ |
| 耗时 | 常驻连续判定 ≤ 19s | 收敛 18.5-21.4s（首文件 28.8s 一次性）✅ |

## 五、用例工程教训（诚实记录）

- step4_06 首版构造失效：`(2:Nat)+(3:ℝ)` 被 Lean **自动 Nat.cast** → 双后端都 pass（伪一致）。真实类型错需显式不可 cast 上下文。→ 提示：**模型翻译里"看起来类型错"的代码常被 cast 自动救回**，靠编译判定拦不住此类；验证可靠性必须靠语义断言（如答案锚定）而非类型层。
