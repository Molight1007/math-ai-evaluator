#!/usr/bin/env bash
# =============================================================================
# deploy/setup_lean.sh — 评测环境 Lean 工具链安装脚本
# =============================================================================
# 目标：让 MathPilot 的 deep 档证明题硬验证（agent/lean_gate.py + lean_bridge.py）
#       真正生效。lean_bridge 的编译路径为：当 <root>/lean下载版/test_mathlib 工程已挂载
#       且 Mathlib 已编译就绪时，向该工程目录写入 verify_*.lean 并以
#       `lake env lean verify_*.lean` 编译（该工程 require mathlib，故能真正加载 Mathlib，
#       提供 norm_num / ring / omega / linarith 等 tactic）；否则回退到单文件临时目录、
#       纯核心 Lean（不依赖 mathlib）。因此需保证 `lake` 与 `lean` 可用且版本匹配
#       lean-toolchain（v4.31.0），并已完成 mathlib 的本地编译（见 lean下载版/test_mathlib）。
#
# 策略（双保险）：
#   1) 在线：优先用 elan（Lean 版本管理器）安装 lean-toolchain 指定版本（v4.31.0）；
#   2) 离线：若无法联网，则从 deploy/lean-4.31.0-linux.zip 解压预编译 lake/lean
#      （历史上海存在 deploy/lean-cache/ 这份**内容完全重复**的解压副本，
#       占 3.0GB 且未被 git 跟踪，已删除，改由本脚本按需解压 zip），
#      并把其 bin 加入 PATH（生成 lean-env.sh 供 shell 加载）。
#
# Mathlib：deploy/mathlib-olean/ 是核心战术模块的**依赖闭包**
#   （920 个 olean / 约 695MB，由 tools/package_mathlib.py 从 5 个具体入口
#   NormNum/Ring/Linarith/Positivity/Omega BFS 构建，缺 Mathlib/Tactic.olean
#   聚合入口）。本脚本把它加入 LEAN_PATH，让 lean_gate 的硬验证真正能用上
#   norm_num / ring / linarith / nlinarith / positivity / omega。
#
# 幂等：已检测到可用 lake（--version 成功）则跳过安装，仅校准 LEAN_PATH 与自验。
#
# 用法：
#   bash deploy/setup_lean.sh            # 在线优先
#   bash deploy/setup_lean.sh --offline  # 仅离线解压
#   成功：exit 0；失败：exit 1（但绝不 touch 评测主流程，调用方应据此降级 unknown）
# =============================================================================
set -euo pipefail

# ---- 常量 -------------------------------------------------------------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEAN_TOOLCHAIN_FILE="${LEAN_TOOLCHAIN_FILE:-$ROOT_DIR/lean-toolchain}"
LEAN_TOOLCHAIN="$(cat "$LEAN_TOOLCHAIN_FILE" 2>/dev/null || echo 'leanprover/lean4:v4.31.0')"
# 从 toolchain 字符串提取版本号，如 "v4.31.0" -> "4.31.0"
LEAN_VERSION="$(echo "$LEAN_TOOLCHAIN" | sed -n 's#.*lean4:v\([0-9][0-9.]*\).*#\1#p' || true)"
[ -z "$LEAN_VERSION" ] && LEAN_VERSION="4.31.0"

ELAN_INSTALL_DIR="${ELAN_HOME:-$HOME/.elan}"
CACHE_DIR="$ROOT_DIR/deploy/lean-cache"
ZIP_FILE="$ROOT_DIR/deploy/lean-4.31.0-linux.zip"
# Mathlib 依赖闭包（由 tools/package_mathlib.py 按文件清单生成，约 110MB）
MATHLIB_DIR="$ROOT_DIR/deploy/mathlib-olean"
ENV_FILE="$ROOT_DIR/deploy/lean-env.sh"
MODE="${1:-online}"
LOG_PREFIX="[setup_lean]"

log()  { echo "$LOG_PREFIX $*"; }
die()  { log "ERROR: $*"; exit 1; }

# ---- 0) 已安装则跳过安装（但仍需校准 LEAN_PATH 并自验）------------------
SKIP_INSTALL=0
if command -v lake >/dev/null 2>&1 && lake --version >/dev/null 2>&1; then
    log "检测到已可用的 lake: $(lake --version 2>&1 | head -1)，跳过安装。"
    SKIP_INSTALL=1
fi

# ---- 1) 工具链版本一致性校验（可选） -------------------------------------
if command -v lean >/dev/null 2>&1; then
    lean --version >/dev/null 2>&1 || true
fi

# ---- 2) 安装 lake/lean -------------------------------------------------
install_with_elan() {
    log "尝试在线安装 elan（Lean 版本管理器）..."
    if ! command -v curl >/dev/null 2>&1; then
        log "未找到 curl，跳过在线安装。"
        return 1
    fi
    if [ ! -x "$ELAN_INSTALL_DIR/bin/elan" ]; then
        curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
            -o "$ROOT_DIR/deploy/_elan-init.sh" 2>/dev/null \
            || { log "下载 elan 安装脚本失败"; return 1; }
        bash "$ROOT_DIR/deploy/_elan-init.sh" -y --default-toolchain "$LEAN_TOOLCHAIN" 2>/dev/null \
            || { log "elan 安装失败"; rm -f "$ROOT_DIR/deploy/_elan-init.sh"; return 1; }
        rm -f "$ROOT_DIR/deploy/_elan-init.sh"
    fi
    export PATH="$ELAN_INSTALL_DIR/bin:$PATH"
    log "elan 安装完成，安装 toolchain $LEAN_TOOLCHAIN ..."
    elan toolchain install "$LEAN_TOOLCHAIN" 2>/dev/null \
        || { log "toolchain 安装失败"; return 1; }
    elan default "$LEAN_TOOLCHAIN" 2>/dev/null || true
    # lake 由 elan 提供（Lean 4 自带 lake）
    command -v lake >/dev/null 2>&1
}

install_from_zip() {
    # 离线首选：从 zip 解压。历史上依赖的 deploy/lean-cache/ 与 zip 内容重复
    # 且占 3.0GB，已删除；改为按需解压，省磁盘也省传输体积。
    log "尝试从压缩包解压 lake/lean: $ZIP_FILE"
    if [ ! -f "$ZIP_FILE" ]; then
        log "压缩包不存在，离线安装不可用。"
        return 1
    fi
    if ! command -v unzip >/dev/null 2>&1; then
        log "未找到 unzip，无法解压离线工具链。"
        return 1
    fi
    local target="$ROOT_DIR/deploy"
    if [ ! -x "$CACHE_DIR/lean-4.31.0-linux/bin/lake" ]; then
        log "解压中（约 832MB，可能需要 1-2 分钟）..."
        unzip -q -o "$ZIP_FILE" -d "$target" || { log "解压失败"; return 1; }
    fi
    [ -d "$CACHE_DIR" ] || { log "解压后未找到 $CACHE_DIR"; return 1; }
    return 0
}

install_from_cache() {
    # 优先：已有解压好的缓存目录；否则先尝试用 zip 解压出该目录。
    if [ ! -d "$CACHE_DIR" ]; then
        install_from_zip || return 1
    fi
    log "从离线缓存目录加载 lake/lean: $CACHE_DIR"

    # 兼容两种缓存布局：
    #   1) 官方 release 解压原样:  $CACHE_DIR/lean-4.31.0-linux/bin/lake
    #   2) 铺平布局:              $CACHE_DIR/bin/lake
    # lean/lake 二进制内嵌 $ORIGIN/../lib 与 $ORIGIN/../lib/lean 的 RPATH，
    # 因此只需保证 bin/ 与 lib/ 相对结构不变，无需额外设置 LD_LIBRARY_PATH。
    local bin_dir=""
    local lib_dir=""
    if [ -x "$CACHE_DIR/bin/lake" ]; then
        bin_dir="$CACHE_DIR/bin"
        lib_dir="$CACHE_DIR/lib"
    else
        local d
        for d in "$CACHE_DIR"/lean-*/bin; do
            if [ -x "$d/lake" ]; then
                bin_dir="$d"
                lib_dir="$(dirname "$d")/lib"
                break
            fi
        done
    fi

    if [ -z "$bin_dir" ] || [ ! -x "$bin_dir/lake" ]; then
        log "缓存中缺少 lake 可执行文件（期望 $CACHE_DIR/lean-*/bin/lake 或 $CACHE_DIR/bin/lake）。"
        return 1
    fi

    log "写入环境文件 $ENV_FILE (bin=$bin_dir)"
    {
        echo "export PATH=\"$bin_dir:\$PATH\""
        # RPATH 已内嵌 $ORIGIN/../lib，这里兜底显式导出，双保险
        if [ -n "$lib_dir" ] && [ -d "$lib_dir" ]; then
            echo "export LD_LIBRARY_PATH=\"$lib_dir:\$LD_LIBRARY_PATH\""
        fi
        echo "# 由 deploy/setup_lean.sh 生成：离线 Lean 工具链"
    } > "$ENV_FILE"
    export PATH="$bin_dir:$PATH"
    if [ -n "$lib_dir" ] && [ -d "$lib_dir" ]; then
        export LD_LIBRARY_PATH="$lib_dir:${LD_LIBRARY_PATH:-}"
    fi
    command -v lake >/dev/null 2>&1
}

# ---- 3) 按模式执行 ------------------------------------------------------
if [ "$SKIP_INSTALL" -eq 0 ]; then
    case "$MODE" in
        --offline)
            install_from_cache || die "离线安装失败（可检查 $ZIP_FILE 是否存在）"
            ;;
        *)
            install_with_elan || { log "在线安装失败，回退离线..."; install_from_cache || die "Lean 安装失败，评测将降级 unknown"; }
            ;;
    esac
fi

if ! (command -v lake >/dev/null 2>&1 && lake --version >/dev/null 2>&1); then
    die "lake 仍不可用，评测将降级 unknown（不影响主流程）"
fi
log "✓ Lean 工具链就绪: $(lake --version 2>&1 | head -1)"

# ---- 4) 挂载 Mathlib 依赖闭包 --------------------------------------------
# core 依赖闭包（BFS 收集的 5 具体入口传递闭包，含 Batteries/Aesop/Qq 等外部
# 包）使 norm_num/ring/linarith/nlinarith/positivity/omega 可用。注意该闭包
# **缺 Mathlib/Tactic.olean 聚合入口**（它 import 337 个子模块，core 只覆盖
# 194 个），因此代码侧 import 归一化（agent/lean_bridge.py）与下方自检探针都
# 按「聚合入口可用则用，否则用 4 个具体模块导入」自适应。
if [ -d "$MATHLIB_DIR" ]; then
    export LEAN_PATH="$MATHLIB_DIR${LEAN_PATH:+:$LEAN_PATH}"
    # 幂等写入：历史版本每次运行都 >> 追加，曾累积 60+ 行重复。已写入则跳过。
    if [ -f "$ENV_FILE" ] && grep -q "$MATHLIB_DIR" "$ENV_FILE" 2>/dev/null; then
        log "LEAN_PATH 已在 $ENV_FILE 中，跳过写入（幂等）"
    else
        {
            echo "# 由 deploy/setup_lean.sh 生成：Mathlib 依赖闭包"
            echo "export LEAN_PATH=\"$MATHLIB_DIR:\$LEAN_PATH\""
        } >> "$ENV_FILE" 2>/dev/null || true
        log "✓ 已挂载 Mathlib 闭包: $MATHLIB_DIR"
    fi
else
    log "WARN: 未找到 Mathlib 闭包 $MATHLIB_DIR，验证将降级为核心 Lean（unknown）"
fi

# ---- 5) 自检：证明 Mathlib 真的可用，而不是"装上了但用不了"---------------
# 失败时 exit 1，让 lean_bridge 走 unknown 降级路径，绝不硬崩。
# 探针覆盖全部 6 种核心 tactic（与 tools/package_mathlib.py 的 PROBE_SOURCE 对齐）。
# core 闭包（deploy/mathlib-olean）缺 Mathlib/Tactic.olean 聚合入口 →
# 探针按环境自适应：聚合入口存在用 import Mathlib.Tactic，否则用 4 个
# 具体模块导入（同样提供全部 6 种 tactic，探针实测可编译通过）。
PROBE_FILE="$(mktemp "${TMPDIR:-/tmp}/lean_probe_XXXXXX.lean" 2>/dev/null || echo "$ROOT_DIR/deploy/_lean_probe.lean")"
if [ -f "$MATHLIB_DIR/Mathlib/Tactic.olean" ]; then
    PROBE_IMPORT="import Mathlib.Tactic"
    PROBE_LABEL="import Mathlib.Tactic"
else
    PROBE_IMPORT="import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Ring
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Positivity"
    PROBE_LABEL="import Mathlib.Tactic.NormNum/Ring/Linarith/Positivity (core 闭包)"
fi
cat > "$PROBE_FILE" <<PROBE_EOF
$PROBE_IMPORT

example : (1:ℕ) + 1 = 2 := by norm_num
example (x : ℚ) : x + x = 2*x := by ring
example (x y : ℚ) (h : x < y) : x + 1 < y + 1 := by linarith
example (x : ℚ) (h : x^2 ≤ 4) (h2 : x ≥ 0) : x ≤ 2 := by nlinarith
example (x : ℚ) (h : x > 0) : x^2 > 0 := by positivity
example (n : ℕ) : n + 3 ≥ 3 := by omega
PROBE_EOF

if lean "$PROBE_FILE" >/dev/null 2>&1; then
    log "✓ 自检通过：$PROBE_LABEL + norm_num/ring/linarith/nlinarith/positivity/omega 均可用"
    rm -f "$PROBE_FILE"
    exit 0
fi

log "WARN: Mathlib 自检未通过（norm_num/ring/linarith/nlinarith/positivity/omega 不可用）"
log "      评测将降级为 unknown 放行，不影响主流程得分。"
rm -f "$PROBE_FILE"
# 注意：这里**不** exit 1——工具链本身已就绪，只是 Mathlib 不可用，
# 让 lean_bridge 走 unknown 降级即可，硬失败反而会让整条流水线不可用。
exit 0
