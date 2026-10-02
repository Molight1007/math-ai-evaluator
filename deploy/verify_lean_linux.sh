#!/usr/bin/env bash
# =============================================================================
# verify_lean_linux.sh — 判定「Windows 构建的 Mathlib olean 能否在 Linux 上加载」
# -----------------------------------------------------------------------------
# 为什么要这个东西
#   本地 .lake/build 与 deploy/mathlib-olean 都是在 Windows 下构建的。
#   Lean 的 olean 是序列化格式（理论上跨平台），但从未在真实 Linux 上验证过。
#   本脚本在 Linux 上按 L0 / L1 / L2 三层判定，把「失败」定位到具体层：
#     L0  裸 Lean 可用？            （lean 二进制本身）
#     L1  闭包能被 LEAN_PATH 加载？  （只 import，不调用 tactic）
#     L2  6 个核心 tactic 能执行？   （这一步才会触达 .ir / 原生码）
#   判定：
#     L2 通过        -> 跨平台成立，Linux 服务器可直接用现有闭包
#     L1 通过 L2 失败 -> 闭包可加载但 tactic 执行失败，需换 full 闭包或走 cache get
#     L1 也失败      -> 闭包格式不兼容，走 lake exe cache get 拉官方 Linux olean
#
# 只需两样东西（放在任意目录、或放在仓库里）
#   lean-4.31.0-linux.zip      Linux 版 Lean 4.31.0（官方构建，约 871 MB）
#   mathlib-olean/ 或 data/mathlib-closure/   Mathlib olean 闭包
#
# 用法
#   bash verify_lean_linux.sh                        # 自动探测
#   bash verify_lean_linux.sh /path/to/repo          # 指定仓库根
#   LEAN_BIN=/path/to/lean bash verify_lean_linux.sh # 指定 lean 二进制
#   CLOSURE=/path/to/closure bash verify_lean_linux.sh
#   WORK_DIR=/path/to/work bash verify_lean_linux.sh # 指定探针工作目录（默认 mktemp -d）
#   bash verify_lean_linux.sh --no-mem               # 跳过内存采样
#
# 退出码  0 = L2 通过 · 2 = 仅 L1 通过 · 3 = 失败 · 1 = 前置条件不足
# =============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"
REPO_ARG="${1:-}"
SKIP_MEM=0
for a in "$@"; do [ "$a" = "--no-mem" ] && SKIP_MEM=1; done
[ "$REPO_ARG" = "--no-mem" ] && REPO_ARG=""

WORK="${WORK_DIR:-}"
if [ -z "$WORK" ]; then
    WORK="$(mktemp -d "${TMPDIR:-/tmp}/leanverify_XXXXXX")"
else
    mkdir -p "$WORK" || { echo "无法创建 WORK_DIR=$WORK"; exit 1; }
fi
REPORT="$PWD/verify_lean_linux_report.txt"
: > "$REPORT"

log()  { printf '%s\n' "$*" | tee -a "$REPORT"; }
hr()   { log "----------------------------------------------------------------------"; }
hdr()  { hr; log "$*"; hr; }

# ---------------------------------------------------------------- 环境信息
KERNEL="$(uname -s 2>/dev/null || echo '?')"
NOT_LINUX=0
[ "$KERNEL" != "Linux" ] && NOT_LINUX=1
HAS_PROC=0
[ -r /proc/self/status ] && HAS_PROC=1
[ "$SKIP_MEM" -eq 1 ] && HAS_PROC=0

hdr "[0] 系统环境"
log "时间         $(date '+%F %T %z')"
log "内核         $(uname -srm 2>/dev/null || echo '?')"
log "发行版       $( (cat /etc/os-release 2>/dev/null | sed -n 's/^PRETTY_NAME=//p') | tr -d '"' || echo '?')"
log "架构         $(uname -m 2>/dev/null || echo '?')"
log "libc         $(getconf GNU_LIBC_VERSION 2>/dev/null || ldd --version 2>/dev/null | head -1 || echo '?')"
log "工作目录     $WORK"
log "内存采样     $([ "$HAS_PROC" -eq 1 ] && echo '启用 (/proc/status VmHWM)' || echo '不可用（跳过）')"
if [ "$NOT_LINUX" -eq 1 ]; then
    log ""
    log "⚠️  当前内核不是 Linux（$KERNEL）"
    log "    本次结果【不能】用于判定「Windows 构建的 olean 能否在 Linux 加载」。"
    log "    该结论只在真实 Linux 上运行本脚本时才成立。"
fi

# ---------------------------------------------------------------- 找仓库根
REPO=""
if [ -n "$REPO_ARG" ] && [ -d "$REPO_ARG" ]; then
    REPO="$(cd "$REPO_ARG" && pwd)"
else
    for cand in "$SELF_DIR/.." "$SELF_DIR" "$PWD" "$PWD/.."; do
        [ -d "$cand" ] || continue
        if [ -f "$cand/lean-toolchain" ] || [ -d "$cand/data" ] || [ -d "$cand/deploy" ]; then
            REPO="$(cd "$cand" && pwd)"; break
        fi
    done
fi
log ""
log "仓库根       ${REPO:-（未找到，将只依赖显式资产）}"

# 资产搜索路径：先显式变量，再工作目录，再仓库，再脚本同级
search_dirs=("$PWD" "$SELF_DIR")
[ -n "$REPO" ] && search_dirs+=("$REPO" "$REPO/deploy" "$REPO/data" "$REPO/mathlib")

find_first_dir() {
    for d in "${search_dirs[@]}"; do
        for rel in "$@"; do
            if [ -d "$d/$rel" ]; then printf '%s\n' "$d/$rel"; return 0; fi
        done
    done
    return 1
}
find_first_file() {
    for d in "${search_dirs[@]}"; do
        for rel in "$@"; do
            if [ -f "$d/$rel" ]; then printf '%s\n' "$d/$rel"; return 0; fi
        done
    done
    return 1
}

# ---------------------------------------------------------------- 找 lean
hdr "[1] 定位 Linux 版 lean 4.31.0"
LEAN_BIN="${LEAN_BIN:-}"

lean_ok() {  # 判断给定二进制是否可用且是 4.31.0
    [ -n "${1:-}" ] && [ -x "$1" ] || return 1
    local v
    v="$("$1" --version 2>&1 | head -2)"
    printf '%s' "$v" | grep -q '4\.31\.0'
}

if [ -n "$LEAN_BIN" ] && lean_ok "$LEAN_BIN"; then
    log "使用 LEAN_BIN=$LEAN_BIN"
elif lean_ok "$(command -v lean 2>/dev/null)"; then
    LEAN_BIN="$(command -v lean)"
    log "使用 PATH 中的 lean: $LEAN_BIN"
else
    # 已解压的缓存目录
    for d in "${search_dirs[@]}"; do
        for p in "$d"/lean-cache/lean-*/bin/lean "$d"/lean-*/bin/lean "$d"/bin/lean; do
            if lean_ok "$p"; then LEAN_BIN="$p"; break 2; fi
        done
    done
fi

if [ -z "$LEAN_BIN" ] || ! lean_ok "$LEAN_BIN"; then
    ZIP="$(find_first_file lean-4.31.0-linux.zip deploy/lean-4.31.0-linux.zip || true)"
    if [ -n "$ZIP" ]; then
        log "从压缩包解压: $ZIP"
        if command -v unzip >/dev/null 2>&1; then
            unzip -q -o "$ZIP" -d "$WORK/lc" >>"$REPORT" 2>&1 || log "  unzip 失败"
        elif command -v python3 >/dev/null 2>&1; then
            python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
                "$ZIP" "$WORK/lc" >>"$REPORT" 2>&1 || log "  python3 解压失败"
        else
            log "  既无 unzip 也无 python3，无法解压"
        fi
        LEAN_BIN="$(find "$WORK/lc" -type f -name lean -perm -u+x 2>/dev/null | head -1)"
        [ -z "$LEAN_BIN" ] && LEAN_BIN="$(find "$WORK/lc" -type f -name lean 2>/dev/null | head -1)"
        [ -n "$LEAN_BIN" ] && chmod +x "$LEAN_BIN" 2>/dev/null
    fi
fi

if [ -z "$LEAN_BIN" ] || [ ! -x "$LEAN_BIN" ]; then
    log "❌ 未找到可用的 Linux lean 4.31.0"
    log "   请提供 lean-4.31.0-linux.zip，或用 LEAN_BIN= 指定，或先装 elan："
    log "     curl https://elan.lean-lang.org/elan-init.sh -sSf | sh"
    log "     elan toolchain install leanprover/lean4:v4.31.0"
    log ""
    log "报告已写入: $REPORT"
    exit 1
fi
log "✅ lean: $LEAN_BIN"
log "   版本: $("$LEAN_BIN" --version 2>&1 | head -2 | tr '\n' ' ')"

# ---------------------------------------------------------------- 找闭包
hdr "[2] 定位 Mathlib olean 闭包"
CLOSURE="${CLOSURE:-}"
[ -z "$CLOSURE" ] && CLOSURE="$(find_first_dir mathlib-olean mathlib/closure-full data/mathlib-closure data/mathlib-closure-core closure-full deploy/mathlib-olean || true)"

if [ -z "$CLOSURE" ] || [ ! -d "$CLOSURE" ]; then
    log "❌ 未找到闭包目录。请提供其一，或用 CLOSURE= 指定："
    log "     deploy/mathlib-olean        (core，679 MB，含 6 战术)"
    log "     data/mathlib-closure        (full，2.2 GB，含 Mathlib/Tactic.olean)"
    log "     mathlib/closure-full        (full 的另一处副本)"
    log ""
    log "报告已写入: $REPORT"
    exit 1
fi
log "✅ 闭包: $CLOSURE"

NFILES=$(find "$CLOSURE" -name '*.olean' 2>/dev/null | wc -l | tr -d ' ')
HAS_ENTRY=no
[ -f "$CLOSURE/Mathlib/Tactic.olean" ] && HAS_ENTRY=yes
MF="$(du -sm "$CLOSURE" 2>/dev/null | awk '{print $1}')"
log "   olean 文件数: $NFILES   体积: ${MF:-?} MB"
log "   Mathlib/Tactic.olean (聚合入口): $HAS_ENTRY"

if [ "$NFILES" -lt 100 ]; then
    log "   ⚠️ olean 数量异常偏少，闭包可能不完整"
fi

# ---------------------------------------------------------------- 探针
IMPORT_FULL="import Mathlib.Tactic"
IMPORT_CORE="import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Ring
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Positivity"

TACTICS='example : (1:ℕ) + 1 = 2 := by norm_num
example (x : ℚ) : x + x = 2*x := by ring
example (x y : ℚ) (h : x < y) : x + 1 < y + 1 := by linarith
example (x : ℚ) (h : x^2 ≤ 4) (h2 : x ≥ 0) : x ≤ 2 := by nlinarith
example (x : ℚ) (h : x > 0) : x^2 > 0 := by positivity
example (n : ℕ) : n + 3 ≥ 3 := by omega'

PASS_L1=0
PASS_L2=0
declare -a SUMMARY=()

peak_mb() {  # $1=pid -> 峰值 RSS（MB）
    local hwm
    hwm="$(awk '/VmHWM/{print $2}' "/proc/$1/status" 2>/dev/null)"
    [ -z "$hwm" ] && hwm=0
    awk -v k="$hwm" 'BEGIN{printf "%.0f", k/1024}'
}

run_probe() {  # $1=标签 $2=闭包(或空) $3=源码
    local label="$1" closure="$2" src="$3"
    local f="$WORK/probe.lean"
    printf '%s\n' "$src" > "$f"

    local t0 t1 rc out peak=0
    t0=$(date +%s)
    if [ -n "$closure" ]; then
        LEAN_PATH="$closure${LEAN_PATH:+:$LEAN_PATH}" "$LEAN_BIN" "$f" \
            >"$WORK/out.txt" 2>&1 &
    else
        "$LEAN_BIN" "$f" >"$WORK/out.txt" 2>&1 &
    fi
    local pid=$!
    if [ "$SKIP_MEM" -eq 0 ]; then
        while kill -0 "$pid" 2>/dev/null; do
            local m; m="$(peak_mb "$pid")"
            [ -n "$m" ] && [ "$m" -gt "$peak" ] 2>/dev/null && peak="$m"
            sleep 0.2
        done
    fi
    wait "$pid"; rc=$?
    t1=$(date +%s)
    local dur=$(( t1 - t0 ))

    out="$(cat "$WORK/out.txt" 2>/dev/null)"
    local peakstr
    if [ "$HAS_PROC" -eq 1 ] && [ "${peak:-0}" -gt 0 ] 2>/dev/null; then
        peakstr="${peak} MB"
    else
        peakstr="n/a"
    fi
    if [ "$rc" -eq 0 ]; then
        log "  ✅ PASS  ${label}  (${dur}s, 峰值 ${peakstr})"
        SUMMARY+=("PASS|${dur}s|${peakstr}|${label}")
    else
        log "  ❌ FAIL  ${label}  (${dur}s, 峰值 ${peakstr})  rc=$rc"
        printf '%s\n' "$out" | head -12 | sed 's/^/         /' | tee -a "$REPORT"
        SUMMARY+=("FAIL|${dur}s|${peakstr}|${label}")
    fi
    LAST_RC=$rc
}

hdr "[3] L0 裸 Lean（不含 Mathlib，验证二进制本身）"
run_probe "L0 bare lean" "" 'example : (1:Nat) + 1 = 2 := rfl'

hdr "[4] L1 闭包加载（只 import，不调用 tactic）"
if [ "$HAS_ENTRY" = yes ]; then
    run_probe "L1 import Mathlib.Tactic" "$CLOSURE" "$IMPORT_FULL"
else
    log "  (闭包无聚合入口，跳过 full 形态)"
fi
run_probe "L1 import 4 具体模块" "$CLOSURE" "$IMPORT_CORE"
[ "${LAST_RC:-1}" -eq 0 ] && PASS_L1=1

hdr "[5] L2 tactic 执行（6 战术，会触达 .ir / 原生码）"
if [ "$HAS_ENTRY" = yes ]; then
    run_probe "L2 full: norm_num/ring/linarith/nlinarith/positivity/omega" \
        "$CLOSURE" "$IMPORT_FULL
$TACTICS"
    [ "${LAST_RC:-1}" -eq 0 ] && PASS_L2=1
fi
run_probe "L2 core: norm_num/ring/linarith/nlinarith/positivity/omega" \
    "$CLOSURE" "$IMPORT_CORE
$TACTICS"
[ "${LAST_RC:-1}" -eq 0 ] && PASS_L2=1

# ---------------------------------------------------------------- 结论
hdr "[6] 明细"
if [ "${#SUMMARY[@]}" -gt 0 ]; then
    for row in "${SUMMARY[@]}"; do
        IFS='|' read -r st du pk lb <<< "$row"
        printf '  %-5s %7s %8s  %s\n' "$st" "$du" "$pk" "$lb" | tee -a "$REPORT"
    done
fi

hdr "[7] 结论"
if [ "$NOT_LINUX" -eq 1 ]; then
    log "⚠️⚠️  本次内核 = $KERNEL，不是 Linux。"
    log "      下面这个结论【无效】—— 只反映本平台，不能回答跨平台问题。"
    log "      请把本脚本拿到真实 Linux 上重跑一次。"
    log ""
fi
if [ "$PASS_L2" -eq 1 ]; then
    if [ "$NOT_LINUX" -eq 1 ]; then
        log "（本平台）olean 闭包加载并执行了全部 6 个 tactic —— 说明闭包本身完整可用。"
        log "跨平台结论待 Linux 上复跑。"
    else
        log "✅ 【跨平台成立】olean 闭包在 Linux 上加载并成功执行全部 6 个 tactic。"
        log "   => 现有 Windows 构建的闭包可直接用于 Linux 服务器，无需重建。"
        log "   => 服务器上传集：deploy/lean-4.31.0-linux.zip (871MB) + 该闭包目录。"
    fi
    RC=0
elif [ "$PASS_L1" -eq 1 ]; then
    log "⚠️ 【部分成立】闭包能被加载（L1 通过），但 tactic 执行失败（L2 失败）。"
    log "   若当前用的是 core 闭包，先换 full（data/mathlib-closure 或 mathlib/closure-full）重试。"
    log "   仍失败则在服务器上执行（原生 Linux olean，必然可用）："
    log "     cd <mathlib4 源树> && lake exe cache get"
    RC=2
else
    log "❌ 【不成立】闭包无法在 Linux 加载（L1 失败）=> olean 跨平台不可移植。"
    log "   退路（原生 Linux olean，必然可用）："
    log "     1) 上传 mathlib4 源码树（非 .lake 部分，约 190MB）+ .lake/packages（约 389MB）"
    log "     2) 在服务器上：lake exe cache get   # 下载官方预编译 Linux olean（入站，不计流量）"
    log "   或：在有 Mathlib 工程的环境执行 lake build 重建（耗时数小时，内存峰值高）。"
    RC=3
fi

log ""
log "报告: $REPORT"
log "把上面的文件内容回传即可判定。"
exit $RC
