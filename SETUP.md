# SETUP —— 未上传内容与运行前置说明

> ⚠ **本仓库刻意未包含若干「体积大」或「含密钥」的资源。直接 `git clone` 后无法开箱即用，请按本文补齐。**
>
> 这份说明的目的：让任何人下载后都能明白**缺了什么、要不要补、怎么补**。

---

## 零、运行档位：**默认是「赛期受限档」，不是「研究版」**（重要）

代码默认值与「研究版（无时间限制 + 联网可用）」**不是一回事**。仓库里的默认值刻意与**平台约束对齐**：

| 配置项 | **代码默认（赛期受限档）** | **研究版（`run_research.py`）** |
|---|---|---|
| `max_time_per_question` | **1100s** | **86400s**（语义=不限） |
| `tier_budget` | **{fast:120, standard:540, deep:1150}** | **86400 × 3** |
| `paper_target_time` | **8438s**（45 题卷折算） | **86400000** |
| `max_total_time_seconds` | **20700s**（6h 硬限 − 4%） | **86400000** |
| **`enable_web_search`** | **False（联网关闭）** | **true** |
| **`use_leansearch`** | **False（联网检索关闭）** | **true** |
| `verifier_deep_final_enabled` | **False** | **true** |
| `verifier_diversify_enabled` | True | true |
| `enable_calc_tool` | False | False（研究档亦未开，原因见下） |
| `phase_budget_enabled` | False | False |

⇒ **直接 `python run_eval.py ...` 或 `python main.py ...` 跑出来的是「单题 1100s、无网络」的受限档。**
研究阶段（比赛已结束，目标是**正确率**而非平台得分）应该用：

```bash
python run_research.py --test_file <题单.jsonl> --output <结果.jsonl>
```

该脚本把"无时间限制 + 联网可用"这组配置**固化**下来（`--max_time_per_question 86400`、
`--tier_budget 86400,86400,86400`、`--paper_target_time/--max_total_time_seconds 86400000`、
`--enable_web_search true`、`--use_leansearch true`、`--verifier_deep_final_enabled true`、`--verbose`），
并自动：① 从仓库根 `.env` / 环境变量准备密钥；② 设置 `LEAN_MCP_ALLOW_NET=1`、
`LEAN_MCP_TIMEOUT_FLOOR=300`、`LLM_TIMEOUT=300`；③ 打印实际生效配置的横幅。

**为什么不在代码里直接把默认值改成"不限"**：`user_agent.py` 是**平台固定入口**，
其默认值必须与平台 1200s 硬限对齐；把研究档写进默认值会污染提交语义。
故研究档只作为**显式选择**存在（这也是为什么需要这个脚本）。

**`enable_calc_tool` 为何研究档也默认关**：该工具链关闭时 `<calc>` 引导与标记解析
**一并停用**（见 `agent/solver.py` 的 `answer_selfcheck` 注释），历史上导致"要求结构性
无法满足 ⇒ 徒劳重问且把好答案改坏"。要开启需连带评估该链路，不宜在研究档里静默打开。

---

## 一、未上传清单（一眼看懂）

| # | 未上传项 | 体积 | 是否必需 | 补齐方式 |
|---|---|---|---|---|
| 1 | `.env`（API 密钥） | 小 | ⛔ **必需** | 见第二节 |
| 2 | `lean下载版/`（Lean 4.31.0 工具链） | **≈3.0 GB** | ⛔ **必需**（Lean 验证链） | 见第三节 |
| 3 | `data/mathlib-closure/`（Mathlib olean 依赖闭包） | **≈2.2 GB** | ⛔ **必需**（Lean 验证链） | 见第三节 |
| 4 | `vendor/lean-toolchain`（submodule 内容） | — | ⛔ **需初始化** | `git submodule update --init --recursive` |
| 5 | `deploy/mathlib-olean/` | ≈680 MB | 可选（部署产物） | 见第三节 |
| 6 | `deploy/lean-4.31.0-linux.zip` | ≈830 MB | 可选（Linux 部署） | 自行准备 |
| 7 | `deploy/lean-env.sh` | 小 | 可选 | 自行编写 |
| 8 | `deploy/users.json`、`deploy/user_api_settings.json` | 小 | 🚫 **有意不上传**（含**密钥与用户名单**） | 自行创建 |
| 9 | `与lean相关的插件/test_mathlib/.lake/` | ≈240 MB | 可选（本地构建缓存） | `lake build` 重建 |
| 10 | `node_modules/` | ≈105 MB | 可选（前端） | `npm install` |
| 11 | `formal-imo/`、`superhuman/` | 小 | 可选（外部参考仓） | 自行 clone |
| 12 | `LEANSEARCH_CORPUS_PATH` 指向的语料 | 仓库外 | 可选（无它则离线检索不可用） | 见第四节 |
| 13 | `gitcode_sync/` | — | ❌ **已废弃，不需要** | — |

**已上传、无需自备**：全部源码（`agent/` `prompts/` `tools/` `utils/`）、**题库（含 official112 全量 112 题）**、`run_eval.py`、`user_agent.py`、`main.py`、`requirements.txt`、`tests/`、`.gitmodules`。

---

## 二、API 密钥（必需）

代码从**环境变量**读取，不读配置文件。共三组，分属不同客户端：

| 客户端（文件） | 变量 | 说明 |
|---|---|---|
| **主链路** `utils/llm_client.py` | `OPENAI_API_KEY` | 密钥 |
| | `OPENAI_BASE_URL` | **基址**（末尾带 `/v1`，客户端自行拼接 `/chat/completions`） |
| | `LLM_MODEL` | 模型名 |
| 根目录 `llm_client.py` | `INTERN_API_KEY` | 密钥 |
| | `INTERN_API_BASE` | ⚠ 这里是**完整端点**（**含** `/chat/completions`），与上面的基址语义不同 |
| | `INTERN_MODEL` | 模型名 |
| `tools/lean_local/leap_eval.py` | `DEEPSEEK_API_KEY` / `DEEPSEEK_API_BASE` / `DEEPSEEK_MODEL` | 仅 LEAP 对照评测用，平时可不设 |

### ⚠ 最容易踩的坑

**只设 `INTERN_*` 而不设 `OPENAI_*`** 时，主链路的 `OPENAI_BASE_URL` 缺失会**静默回落到 `http://localhost:8000/v1`**，表现为连接被拒（`os error 10061` / 502），**整批题全部失败**。

创建 `.env`（示例）：

```
OPENAI_API_KEY=your-key-here
OPENAI_BASE_URL=https://your-endpoint/v1
LLM_MODEL=your-model-name
```

### 其他可调环境变量（均有默认值，可不设）

`LLM_TIMEOUT`(300) · `LLM_RETRY_ON_TIMEOUT`(1) · `LEAN_EXE` · `LEAN_PROJECT_PATH` · `LEAN_MCP_TIMEOUT_FLOOR`(300) · `LEAN_MCP_ALLOW_NET` · `LEAN_MCP_WORKERS` · `LEAN_GATE_PARALLEL` · `LEAN_GATE_STRICT_UNKNOWN` · `LEANSEARCH_CORPUS_PATH` · `LOCAL_MAX_CONCURRENCY`

---

## 三、Lean 工具链与 Mathlib（Lean 验证链必需）

### 3.1 Lean 可执行文件在哪里找

`tools/lean_local/lean_bridge.py` 按以下**优先级**探测：

1. 环境变量 `LEAN_EXE`（显式指定）
2. `~/.elan/toolchains/leanprover--lean4---v4.31.0/bin/lean.exe`（用 elan 安装的默认位置）
3. `<仓库根>/lean下载版/lean-toolchain/bin/lean.exe`（**本地约定路径，本仓库不含**）

⇒ 任选其一即可。**用 elan 安装最省事**：

```bash
elan toolchain install leanprover/lean4:v4.31.0
```

### 3.2 Mathlib 依赖闭包

`data/mathlib-closure/` 存放 Mathlib 的 `.olean` 依赖闭包（≈2.2 GB），**本仓库不含**。没有它时 Lean 只能编译核心库，**无法验证依赖 Mathlib 的命题**。

### 3.3 submodule

`vendor/lean-toolchain` 是一个 **git submodule**（在 `.gitmodules` 中登记）：

```bash
git submodule update --init --recursive
```

### 3.4 ⚠ 没有 Lean 环境时会怎样（重要）

**流水线不会崩。** Lean 相关闸门会**整体降级放行**（`lean_gate` 记 `degraded="lean_missing"`），
即：**放弃"硬验证"这一层**，但仍能跑完并给出答案。
→ 这意味着**正确率会下降**，但流程可跑通、可调试。

---

## 四、LeanSearch 语料（可选）

`LEANSEARCH_CORPUS_PATH` 指向 `mathlib_informal_*.jsonl`（非形式化 Mathlib 语料，**不在仓库内**）。

- **不设它**：在线检索（`leansearch.net`）仍然可用；仅"离线语料兜底"不可用。
- **设它**：离线优先，适合无外网环境。

---

## 五、最简可跑路径（不含 Lean）

```bash
git clone <repo> && cd <repo>
pip install -r requirements.txt
# 创建 .env（见第二节）
python main.py            # 或：python run_eval.py --test_file <题库> --output <结果>
```

此时**所有 Lean 相关环节自动降级放行**，流水线可完整跑通。
适合：调试流水线、跑非 Lean 路径、看答案抽取与选答逻辑。

---

## 六、完整复现路径（含 Lean 硬验证）

```bash
# 1) 依赖
pip install -r requirements.txt

# 2) Lean 4.31.0（三选一）
elan toolchain install leanprover/lean4:v4.31.0
# 或  设置 LEAN_EXE=/path/to/lean
# 或  放置到 <仓库根>/lean下载版/lean-toolchain/bin/lean.exe

# 3) Mathlib 闭包 → data/mathlib-closure/

# 4) submodule
git submodule update --init --recursive

# 5) 环境变量
export OPENAI_API_KEY=...  OPENAI_BASE_URL=.../v1  LLM_MODEL=...
export LEAN_MCP_ALLOW_NET=1          # 放行 Lean MCP 的远程检索工具
export LEAN_MCP_TIMEOUT_FLOOR=300    # Mathlib 冷启动需 60–90s，超时地板须抬高

# 6) 运行本地评测
python run_eval.py --test_file 题库/official112_本地测试题库/official112_full.jsonl \
                   --output results/run.jsonl --concurrency 1 --verbose
```

---

## 七、自查：我是否补全了？

- [ ] `.env` 已建，且**同时**含 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LLM_MODEL`
- [ ] `pip install -r requirements.txt` 成功（仅 `requests`、`sympy` 两个包）
- [ ] 若要 Lean 验证：`LEAN_EXE` 可执行 **或** `~/.elan/...` 存在
- [ ] 若要 Lean 验证：`data/mathlib-closure/` 已就位
- [ ] `git submodule update --init --recursive` 已执行（`vendor/lean-toolchain` 非空）
- [ ] 若无 Lean：确认接受"Lean 闸门降级放行"

---

## 八、为什么这些不放进仓库

| 原因 | 涉及项 |
|---|---|
| **体积过大**（GitHub 单文件 100 MB 硬限；仓库总体积限制） | Lean 工具链（3 GB）、Mathlib 闭包（2.2 GB）、`deploy/*.zip`（830 MB） |
| **含密钥 / 隐私**（不得公开） | `.env`、`deploy/users.json`、`deploy/user_api_settings.json` |
| **可由工具重建**（放进仓库是冗余） | `node_modules/`、`data/mathlib-closure/`、`.lake/` 构建缓存 |
| **已废弃** | `gitcode_sync/`（旧镜像目录，不再使用） |

---

*本文件由项目维护者在 2026-09-17 补充，用于说明仓库未包含的运行前置资源。*
