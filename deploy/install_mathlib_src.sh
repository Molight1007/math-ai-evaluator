#!/usr/bin/env bash
# =============================================================================
# deploy/install_mathlib_src.sh — 为 lean_local_search 安装 Mathlib 源码（文本检索用）
# =============================================================================
# 背景（2026-11-07）：
#   `deploy/mathlib-olean/` 只是 **olean 依赖闭包**，让 tactic 能跑，**从不含源码**。
#   于是 lean-lsp-mcp 的 `lean_local_search`（ripgrep 搜 .lean 源码）返回空：
#       {"items": [], "index": "unavailable"}
#   本脚本把与工具链**精确同 tag** 的 Mathlib 源码装进去，供 rg 检索。
#
# 为什么必须同 tag：
#   源码用于「告诉模型有哪些引理」，若版本对不上，给出的引理名/签名会在本机 olean 里
#   不存在或已改名 —— 模型照抄会报 `unknown identifier`，比不检索更糟。
#   因此先读 `deploy/mathlib-olean/lean-toolchain` 得 `leanprover/lean4:v4.31.0`，
#   再用 git ls-remote 反查 mathlib4 同名 tag 的 commit，只下那一个 commit。
#
# 只拷 Mathlib/ 子目录：不覆盖壳项目自己的 lakefile.toml / lake-manifest.json
#   （那两个是「自建壳项目」的标识，被 lean-lsp-mcp 认作工程根）。
#
# ★ 已知覆盖洞（装完也必须知道）：源码 8169 模块 vs olean 7589 模块 ⇒
#   633 个模块有源码无 olean（集中在 Algebra/Category 范畴论/层论）。
#   检索命中这些模块会给出编不过的名字，调用侧必须按 .olean 是否存在过滤
#   （见 测试结果/L2逐步探针_20261107/l2_step_probe.py::_has_olean）。
#
# 幂等：目标已有 >=7000 个 .lean 则跳过下载；--force 强制重装。
#
# 用法：
#   bash deploy/install_mathlib_src.sh              # 默认 ghfast.top 镜像
#   MATHLIB_MIRROR=direct bash deploy/install_mathlib_src.sh   # 直连 github（国内常被限速）
#   bash deploy/install_mathlib_src.sh --force      # 强制重装
#   成功：exit 0；失败：exit 1
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MATHLIB_DIR="${MATHLIB_DIR:-$ROOT_DIR/deploy/mathlib-olean}"
MIRROR="${MATHLIB_MIRROR:-ghfast.top}"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1
LOG_PREFIX="[mathlib_src]"
log() { echo "$LOG_PREFIX $*"; }
die() { log "ERROR: $*"; exit 1; }

# ---- 0) 前置检查 --------------------------------------------------------
[ -d "$MATHLIB_DIR" ] || die "找不到 $MATHLIB_DIR（先跑 deploy/setup_lean.sh）"
[ -f "$MATHLIB_DIR/lean-toolchain" ] || die "$MATHLIB_DIR/lean-toolchain 缺失，无法确定版本"
command -v rg >/dev/null 2>&1 || die "缺 ripgrep：sudo apt-get install -y ripgrep"
command -v curl >/dev/null 2>&1 || die "缺 curl"

EXISTING="$(find "$MATHLIB_DIR/Mathlib" -name '*.lean' 2>/dev/null | wc -l)"
if [ "$EXISTING" -ge 7000 ] && [ "$FORCE" -eq 0 ]; then
    log "已存在 $EXISTING 个 .lean，跳过（--force 可强制重装）"
    exit 0
fi

# ---- 1) 由 lean-toolchain 反查 mathlib4 tag 的 commit --------------------
TOOLCHAIN="$(head -1 "$MATHLIB_DIR/lean-toolchain" | tr -d '[:space:]')"
VER="$(echo "$TOOLCHAIN" | sed -n 's#.*lean4:\(v\?[0-9][0-9.]*\).*#\1#p')"
[ -n "$VER" ] || die "无法从 lean-toolchain 解析版本：$TOOLCHAIN"
case "$VER" in v*) TAG="$VER" ;; *) TAG="v$VER" ;; esac
log "toolchain=$TOOLCHAIN tag=$TAG"

SHA="$(git ls-remote --tags https://github.com/leanprover-community/mathlib4 "refs/tags/$TAG" 2>/dev/null \
       | awk '{print $1}' | head -1)"
[ -n "$SHA" ] || die "mathlib4 没有 tag $TAG（网络不通或该 Lean 版本无对应 tag）"
log "commit=$SHA"

# ---- 2) 下载 ------------------------------------------------------------
TMP_TGZ="$(mktemp /tmp/ml4_XXXXXX.tar.gz)"
trap 'rm -f "$TMP_TGZ"' EXIT
GH="https://github.com/leanprover-community/mathlib4/archive/$SHA.tar.gz"
case "$MIRROR" in
    direct) URL="$GH" ;;
    *)      URL="https://$MIRROR/$GH" ;;
esac
log "下载 $URL"
curl -sL --max-time 900 -o "$TMP_TGZ" "$URL" || die "下载失败"
log "下载完成 $(du -h "$TMP_TGZ" | cut -f1)"

# ---- 3) 校验「版本真的对得上」再落盘 ------------------------------------
GOT_TC="$(tar -xzOf "$TMP_TGZ" --wildcards '*/lean-toolchain' 2>/dev/null | head -1 | tr -d '[:space:]')"
[ "$GOT_TC" = "$TOOLCHAIN" ] || die "版本不符：包内 lean-toolchain=$GOT_TC，本机=$TOOLCHAIN"
log "✓ toolchain 校验通过：$GOT_TC"

# ---- 4) 只取 Mathlib/ 子目录 -------------------------------------------
TMP_SRC="$(mktemp -d /tmp/ml4src_XXXXXX)"
trap 'rm -f "$TMP_TGZ"; rm -rf "$TMP_SRC"' EXIT
tar -xzf "$TMP_TGZ" -C "$TMP_SRC" --strip-components=1 --wildcards '*/Mathlib/*'
N_SRC="$(find "$TMP_SRC/Mathlib" -name '*.lean' | wc -l)"
[ "$N_SRC" -ge 7000 ] || die "解压出的 .lean 只有 $N_SRC 个，疑似包损坏"

cp -a "$TMP_SRC/Mathlib/." "$MATHLIB_DIR/Mathlib/"
N_NOW="$(find "$MATHLIB_DIR/Mathlib" -name '*.lean' | wc -l)"
log "✓ 已安装 $N_NOW 个 .lean → $MATHLIB_DIR/Mathlib"

cat > "$MATHLIB_DIR/MATHLIB_SRC_VERSION.txt" <<EOF
Mathlib 源码（供 lean_local_search / ripgrep 检索）
来源: https://github.com/leanprover-community/mathlib4
tag:  $TAG
commit: $SHA
lean-toolchain: $TOOLCHAIN
安装时间: $(date '+%Y-%m-%d %H:%M %Z')
方式: $MIRROR 镜像 tar.gz，仅取 Mathlib/ 子目录
文件数: $N_NOW 个 .lean
注意: 本目录的 olean 由既有闭包提供，源码仅用于文本检索，不参与编译。
      源码模块数($N_NOW) > olean 模块数 ⇒ 存在「有源码无 olean」的模块，
      调用侧必须按 .olean 是否存在过滤命中项。
EOF

# ---- 5) 自检：检索真的能命中 -------------------------------------------
Q="dvd_factorial"
N_HIT="$(rg -c "theorem .*$Q" "$MATHLIB_DIR/Mathlib" 2>/dev/null | wc -l)"
[ "$N_HIT" -gt 0 ] || die "rg 在源码里搜不到 $Q，检索仍不可用"
log "✓ rg 自检通过：$Q 命中 $N_HIT 个文件"
log "完成。用时注意过滤无 olean 的模块。"
exit 0
