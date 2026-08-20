# Lean 工具链接入评测环境说明

## 目标

让 MathPilot 的 deep 档证明题 **Lean 硬验证**（`agent/lean_gate.py` → `agent/lean_bridge.py`）在评测环境中真正生效。

Lean 验证的编译路径为 `lake env lean verify.lean`（单文件模式，**不依赖 mathlib**），因此只需保证 `lake` / `lean` 可用且版本与 `lean-toolchain` 一致（`leanprover/lean4:v4.31.0`）。

## 三种接入方式（按可靠程度）

### 方式一：提交物自带脚本，评测启动时调用（推荐）

评测容器（Linux）在运行评测前执行：

```bash
bash deploy/setup_lean.sh
```

脚本会：

1. **幂等检测**：若 `lake --version` 已可用，直接退出 0，不做任何破坏性操作；
2. **在线安装**：用 elan（Lean 版本管理器）安装 `lean-toolchain` 指定的 `v4.31.0` toolchain（`lake` 由 Lean 4 自带）；
3. **离线回退**：若无法联网，则从 `deploy/lean-cache/` 解压预编译 `lake`/`lean` 到 PATH，并生成 `deploy/lean-env.sh` 供 shell 加载；
4. 最终校验 `lake --version`。

### 方式二：Python 侧自动自举（已内置）

`agent/lean_bridge.py` 的 `detect_lean_environment()` 在检测到 `lake` 缺失时，会自动执行一次 `bash deploy/setup_lean.sh --offline` 自举（进程级只尝试一次，纯 best-effort，失败静默降级 unknown）。

**因此无需改动评测启动命令**——只要提交物包含 `deploy/setup_lean.sh` 与离线缓存，Lean 验证即可自动接入。

### 方式三：评测环境手工预装

```bash
# 在线
curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -o /tmp/elan-init.sh
bash /tmp/elan-init.sh -y --default-toolchain leanprover/lean4:v4.31.0
export PATH="$HOME/.elan/bin:$PATH"
elan default leanprover/lean4:v4.31.0
```

## 离线缓存（可选，推荐评测容器无外网时使用）

在本地（有 Lean 的机器）用 elan 安装好 toolchain 后，将 `lake`、`lean` 及其依赖库打包到 `deploy/lean-cache/`：

```bash
# 在本地有 Lean 的机器上
mkdir -p deploy/lean-cache/bin
cp "$HOME/.elan/bin/lake" deploy/lean-cache/bin/
cp "$HOME/.elan/bin/lean" deploy/lean-cache/bin/
# 若使用符号链接（elan 的 lean 指向 toolchain 版本），用 tar 打包整个 .elan 目录
tar -czf deploy/lean-cache/elan-linux-x86_64.tar.gz -C "$HOME" .elan
```

`setup_lean.sh --offline` 会自动解压该 `tar.gz` 并使用其中的 `bin/lake`。

## 降级策略（重要）

Lean 环境缺失 / 超时 / 异常时，`lean_bridge.verify()` 返回 `verdict='unknown'`，
`lean_gate.py` 默认**降级放行**（不损失分数），仅当 `lean_gate_strict=True` 才保守拒绝。
因此 Lean 工具链未就绪 **不会** 导致评测崩溃或分数回退，只会让证明题回到纯 LLM 验证。

## 关键文件

- `lean-toolchain` — 指定 Lean 版本 `leanprover/lean4:v4.31.0`
- `deploy/setup_lean.sh` — 安装脚本（在线 + 离线）
- `deploy/lean-cache/` — 离线预编译缓存（可选）
- `agent/lean_bridge.py` — Lean 验证桥接层（含自动自举）
- `agent/lean_gate.py` — deep 档硬验证门禁
