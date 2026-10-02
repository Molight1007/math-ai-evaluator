#!/usr/bin/env bash
# =============================================================================
# setup_mcp_linux.sh — 在服务器上建立 lean-lsp-mcp 执行器（让 MCP 通道真正生效）
# -----------------------------------------------------------------------------
# 为什么需要
#   lean_bridge._detect_mcp_proxy_python() 会依次找：
#     ① $LEAN_MCP_PYTHON   ② ~/leanlsp-venv/bin/python
#     ③ <repo>/lean-lsp-mcp/venv-linux/bin/python   ← 本脚本产出这个
#     ④ <repo>/lean-lsp-mcp/venv/bin/python
#   都找不到就返回空串 ⇒ MCP 静默回落 bridge，丢掉它的三项能力：
#     错误行 goal state / multi_attempt 可用策略 / hover 查证 API。
#
# 工程门控不用管
#   _mcp_gate_ok() 在 LEAN_MCP_AUTOLAKE（**默认 1**）下会自动往闭包目录补
#   lean-toolchain + lakefile.toml（幂等），所以「闭包 + LEAN_PATH」形态也能过门控。
#
# ⚠️ 本仓 vendor/.../wheels 里的 8 个二进制 wheel 是 **win_amd64 专用**
#   （cffi/cryptography/orjson/psutil/pydantic_core/pywin32/…），Linux 用不了，
#   所以默认走 PyPI；若你另备了 manylinux wheels，用 --offline <dir> 指定。
#
# 用法
#   bash deploy/setup_mcp_linux.sh                    # 走 PyPI（清华镜像）
#   bash deploy/setup_mcp_linux.sh --offline <dir>    # 走离线 wheels 目录
#   MCP_PKG_VER=0.30.0 bash deploy/setup_mcp_linux.sh # 指定版本
# =============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"
ROOT="$(cd "$SELF_DIR/.." && pwd)"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

MCP_DIR="$ROOT/lean-lsp-mcp"
VENV="$MCP_DIR/venv-linux"
PKG_VER="${MCP_PKG_VER:-0.30.0}"
CLIENT_VER="${LEANCLIENT_VER:-0.13.2}"
MIRROR="${PIP_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
OFFLINE_DIR=""
[ "${1:-}" = "--offline" ] && OFFLINE_DIR="${2:-}"

hdr() { printf '\n== %s ==\n' "$1"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$1"; }

if [ "$(uname -s)" != "Linux" ]; then echo "只能在 Linux 上运行"; exit 1; fi
hdr "0 定位"
printf '  仓库根 %s\n  venv   %s\n' "$ROOT" "$VENV"

mkdir -p "$MCP_DIR"

hdr "1 基础依赖"
if ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
    ok "安装 python3-venv / python3-pip"
    $SUDO apt-get update -y >/dev/null 2>&1
    $SUDO apt-get install -y python3-venv python3-pip >/dev/null 2>&1 \
      || { bad "apt 安装失败"; exit 1; }
fi
ok "python3: $(python3 -V 2>&1)"

hdr "2 建 venv"
if [ -x "$VENV/bin/python" ]; then
    ok "已存在，复用"
else
    python3 -m venv "$VENV" || { bad "venv 创建失败"; exit 1; }
    ok "已创建"
fi
"$VENV/bin/python" -m pip install -q -U pip setuptools wheel >/dev/null 2>&1
ok "pip $("$VENV/bin/python" -m pip -V 2>&1 | awk '{print $2}')"

hdr "3 安装 lean-lsp-mcp"
if [ -n "$OFFLINE_DIR" ]; then
    printf '  离线目录 %s\n' "$OFFLINE_DIR"
    ls "$OFFLINE_DIR"/*manylinux*.whl >/dev/null 2>&1 \
      || printf '  \033[33m⚠️ 该目录没有 manylinux wheel，极可能失败\033[0m\n'
    "$VENV/bin/python" -m pip install -q --no-index --find-links "$OFFLINE_DIR" \
        "lean-lsp-mcp==$PKG_VER" "leanclient==$CLIENT_VER" 2>&1 | tail -5
else
    printf '  源 %s\n' "$MIRROR"
    "$VENV/bin/python" -m pip install -q -i "$MIRROR" \
        "lean-lsp-mcp==$PKG_VER" "leanclient==$CLIENT_VER" 2>&1 | tail -8
fi

hdr "4 自检"
if "$VENV/bin/python" -c "import lean_lsp_mcp, leanclient; print('lean_lsp_mcp', lean_lsp_mcp.__version__ if hasattr(lean_lsp_mcp,'__version__') else '?')" 2>&1; then
    ok "模块可导入"
else
    bad "模块导入失败 —— MCP 会静默回落 bridge"
fi

ENTRY=""
for c in "$VENV/bin/lean-lsp-mcp" "$VENV/bin/leanlsp-mcp" "$MCP_DIR/bin/rg"; do
    [ -e "$c" ] && printf '  存在 %s\n' "$c"
done
chmod +x "$MCP_DIR/bin/rg" 2>/dev/null || true

hdr "5 结论"
if [ -x "$VENV/bin/python" ]; then
    ok "执行器就位：$VENV/bin/python"
    printf '  _detect_mcp_proxy_python() 的第 ③ 条候选即可命中，无需设 LEAN_MCP_PYTHON\n'
    printf '  仍建议显式固定，避免将来路径变动：\n'
    printf '      export LEAN_MCP_PYTHON=%s/bin/python\n' "$VENV"
else
    bad "未就位"
    exit 1
fi
printf '\n注意：MCP 生效还需 PATH 里有 lean/lake（由 deploy/lean-env.sh 提供）\n'
