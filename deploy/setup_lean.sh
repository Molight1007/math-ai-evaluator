#!/usr/bin/env bash
# =============================================================================
# deploy/setup_lean.sh — 评测环境 Lean 工具链安装脚本
# =============================================================================
# 目标：让 MathPilot 的 deep 档证明题硬验证（agent/lean_gate.py + lean_bridge.py）
#       真正生效。lean_bridge 的编译路径为 `lake env lean verify.lean`（单文件，
#       不依赖 mathlib），因此只需保证 `lake` 与 `lean` 可用且版本匹配 lean-toolchain。
#
# 策略（双保险）：
#   1) 在线：优先用 elan（Lean 版本管理器）安装 lean-toolchain 指定版本（v4.31.0）；
#   2) 离线：若无法联网，则从预打包目录 deploy/lean-cache/ 解压预编译 lake/lean，
#      并把其 bin 加入 PATH（生成 lean-env.sh 供 shell 加载）。
#
# 幂等：已检测到可用 lake（--version 成功）则直接退出 0，不做任何破坏性操作。
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
ENV_FILE="$ROOT_DIR/deploy/lean-env.sh"
MODE="${1:-online}"
LOG_PREFIX="[setup_lean]"

log()  { echo "$LOG_PREFIX $*"; }
die()  { log "ERROR: $*"; exit 1; }

# ---- 0) 已安装则直接退出 ------------------------------------------------
if command -v lake >/dev/null 2>&1 && lake --version >/dev/null 2>&1; then
    log "检测到已可用的 lake: $(lake --version 2>&1 | head -1)，无需安装。"
    exit 0
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

install_from_cache() {
    log "尝试从离线缓存目录加载 lake/lean: $CACHE_DIR"
    if [ ! -d "$CACHE_DIR" ]; then
        log "缓存目录不存在，离线安装不可用。"
        return 1
    fi

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
case "$MODE" in
    --offline)
        install_from_cache || die "离线安装失败（可检查 $CACHE_DIR 是否含预编译 lake）"
        ;;
    *)
        install_with_elan || { log "在线安装失败，回退离线..."; install_from_cache || die "Lean 安装失败，评测将降级 unknown"; }
        ;;
esac

# ---- 4) 最终校验 --------------------------------------------------------
if command -v lake >/dev/null 2>&1 && lake --version >/dev/null 2>&1; then
    log "✓ Lean 工具链就绪: $(lake --version 2>&1 | head -1)"
    exit 0
fi
die "lake 仍不可用，评测将降级 unknown（不影响主流程）"
