#!/usr/bin/env bash
# =============================================================================
# bootstrap_ubuntu.sh — 把 Ubuntu 24.04 云服务器初始化成 MathPilot 评测环境
# -----------------------------------------------------------------------------
# 覆盖（幂等，可重复运行）：
#   1) 系统依赖：git / curl / unzip / build-essential / python3-venv / tmux / rsync
#   2) 8 GB swap（防 OOM：直编路径无全局锁，多线程可能同时起多个 Lean）
#   3) Lean 工具链 + Mathlib 闭包：调 deploy/setup_lean.sh --offline
#   4) 跨平台判定：调 deploy/verify_lean_linux.sh
#   5) Python venv + requirements.txt
#   6) 只读扫描：硬编码的 Windows 路径（不改代码，只列清单）
#
# 用法（在仓库根目录执行）
#   bash deploy/bootstrap_ubuntu.sh
#
# 前置：上传集已就位，至少包含
#   deploy/lean-4.31.0-linux.zip     (871 MB)  —— GitHub 在国内机房常被拦，
#                                                 所以走离线 zip 而不是在线 elan
#   deploy/mathlib-olean/            (679 MB)  —— core 闭包，实测覆盖 6 战术
#   requirements.txt / lean-toolchain / 代码
#
# 退出码：0 = 全部就绪 · 其余 = 有步骤失败（见结尾汇总）
# =============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "$PWD")"
ROOT="$(cd "$SELF_DIR/.." && pwd)"
cd "$ROOT" || { echo "无法进入仓库根 $ROOT"; exit 1; }

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

FAILED=()
step_ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
step_fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; FAILED+=("$1"); }
hdr() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# ---------------------------------------------------------------- 0 环境自检
hdr "0 环境自检"
printf '  仓库根   %s\n' "$ROOT"
printf '  内核     %s\n' "$(uname -srm)"
printf '  发行版   %s\n' "$( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || echo '?')"
printf '  CPU/内存 %s 核 / %s\n' "$(nproc)" "$(free -h 2>/dev/null | awk '/Mem:/{print $2}')"
printf '  系统盘   %s\n' "$(df -h . | awk 'NR==2{printf "%s 可用 %s (%s)", $2, $4, $5}')"

if [ "$(uname -s)" != "Linux" ]; then
    printf '\n\033[31m本脚本只能在 Linux 上运行（当前 %s）\033[0m\n' "$(uname -s)"
    exit 1
fi

# 前置资产检查
MISSING=0
for f in deploy/lean-4.31.0-linux.zip deploy/setup_lean.sh requirements.txt; do
    if [ -f "$f" ]; then printf '  ✓ %s\n' "$f"; else printf '  ✗ 缺 %s\n' "$f"; MISSING=1; fi
done
for d in deploy/mathlib-olean data/mathlib-closure mathlib/closure-full; do
    [ -d "$d" ] && { printf '  ✓ %s/（闭包）\n' "$d"; CLOSURE_SEEN=1; }
done
if [ -z "${CLOSURE_SEEN:-}" ]; then printf '  ✗ 未找到任何闭包目录\n'; MISSING=1; fi
if [ "$MISSING" -eq 1 ]; then
    printf '\n前置资产不全，请先上传。参考：deploy/lean-4.31.0-linux.zip (871MB) + deploy/mathlib-olean (679MB)\n'
fi

# ---------------------------------------------------------------- 1 系统依赖
hdr "1 系统依赖"
# ★ 不能只看二进制在不在：python3-venv 缺失时 `python3 -m venv` 会**静默降级为
#   --without-pip**，装出来的 venv 一个 pip 都没有 ⇒ 依赖全部装不上（实测踩到：
#   .venv 建了、却连 requests 都没有，而 apt 那步因为"命令都在"被跳过了）。
needs_apt=0
for c in git unzip curl tmux rsync nproc; do
    command -v "$c" >/dev/null 2>&1 || { printf '  缺 %s\n' "$c"; needs_apt=1; }
done
command -v python3 >/dev/null 2>&1 || { printf '  缺 python3\n'; needs_apt=1; }
if ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
    printf '  python3 venv/ensurepip 不可用（装出的 venv 会没有 pip）\n'
    needs_apt=1
fi

if [ "$needs_apt" -eq 0 ]; then
    step_ok "依赖已齐备，跳过 apt"
else
    printf '  执行 apt 安装…\n'
    $SUDO apt-get update -y >/tmp/boot_apt.log 2>&1
    $SUDO apt-get install -y git curl unzip build-essential python3-venv \
          python3-pip tmux rsync ca-certificates >>/tmp/boot_apt.log 2>&1 \
      && step_ok "apt 安装完成" \
      || step_fail "apt 安装失败（见 /tmp/boot_apt.log）"
fi
printf '  python3: %s\n' "$(python3 --version 2>&1 || echo '缺失')"
if python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
    step_ok "venv + ensurepip 可用（能建出带 pip 的环境）"
else
    step_fail "venv/ensurepip 仍不可用 —— 后续 pip 安装会失败"
fi

# ---------------------------------------------------------------- 2 swap
hdr "2 swap（防 OOM）"
# 注意：腾讯云 Ubuntu 镜像默认已带 ~2G swap。只判断"是否存在"会误跳过，
# 必须判断总量是否够（实测发现：默认 1.9G，远低于我们需要的 8G）。
SWAP_MB=$(free -m 2>/dev/null | awk '/Swap:/{print $2}')
SWAP_MB=${SWAP_MB:-0}
printf '  当前 swap: %s MB\n' "$SWAP_MB"

if [ "$SWAP_MB" -ge 7000 ]; then
    step_ok "swap 已足够（${SWAP_MB} MB），跳过"
else
    if [ ! -f /swapfile ]; then
        printf '  创建 8G /swapfile …\n'
        $SUDO fallocate -l 8G /swapfile 2>/dev/null \
          || $SUDO dd if=/dev/zero of=/swapfile bs=1M count=8192 status=none
        $SUDO chmod 600 /swapfile
        $SUDO mkswap /swapfile >/dev/null
    fi
    $SUDO swapon /swapfile 2>/dev/null
    grep -q '^/swapfile' /etc/fstab 2>/dev/null \
      || echo '/swapfile none swap sw 0 0' | $SUDO tee -a /etc/fstab >/dev/null
    $SUDO sysctl -w vm.swappiness=10 >/dev/null 2>&1
    grep -q 'vm.swappiness' /etc/sysctl.conf 2>/dev/null \
      || echo 'vm.swappiness=10' | $SUDO tee -a /etc/sysctl.conf >/dev/null
    NEW_MB=$(free -m 2>/dev/null | awk '/Swap:/{print $2}')
    if [ "${NEW_MB:-0}" -gt "$SWAP_MB" ]; then
        step_ok "swap 已扩到 ${NEW_MB} MB（swappiness=10）"
    else
        step_fail "swap 扩容失败（磁盘空间不足？）"
    fi
fi

# ---------------------------------------------------------------- 3 Lean + 闭包
hdr "3 Lean 工具链 + Mathlib 闭包"
if [ -f deploy/setup_lean.sh ]; then
    if bash deploy/setup_lean.sh --offline; then
        step_ok "setup_lean.sh 完成（解压 Lean + 挂 LEAN_PATH + 自检）"
    else
        step_fail "setup_lean.sh 返回非 0（可能是闭包自检未过）"
    fi
    # 落一个可直接 source 的环境文件，供后续 run_eval 用
    if [ -f deploy/lean-env.sh ]; then
        printf '  环境文件：deploy/lean-env.sh（跑评测前先 source）\n'
    fi
else
    step_fail "找不到 deploy/setup_lean.sh"
fi

# ---------------------------------------------------------------- 4 跨平台判定
hdr "4 跨平台判定"
if [ -f deploy/verify_lean_linux.sh ]; then
    bash deploy/verify_lean_linux.sh > /tmp/leanverify.log 2>&1
    VRC=$?
    case "$VRC" in
        0) step_ok "L2 通过 —— olean 跨平台成立，闭包可用" ;;
        2) step_fail "仅 L1 通过：闭包能加载但 tactic 执行失败 → 换 full 闭包或走 lake exe cache get" ;;
        3) step_fail "L1 失败：olean 不可移植 → 需 lake exe cache get 重建" ;;
        *) step_fail "前置不足（退出码 $VRC）" ;;
    esac
    printf '  详细报告：%s\n' "$ROOT/verify_lean_linux_report.txt"
    printf '  完整日志：/tmp/leanverify.log（失败时把它发我）\n'
else
    step_fail "找不到 deploy/verify_lean_linux.sh"
fi

# ---------------------------------------------------------------- 5 Python 环境
hdr "5 Python 环境"
if [ -f requirements.txt ]; then
    # ★ venv 存在但**没有 pip** 是"静默半成品"（python3-venv 缺失时 venv 会
    #   降级为 --without-pip）。必须显式检查 pip，缺就删掉重建。
    if [ -x .venv/bin/python ] && [ -x .venv/bin/pip ]; then
        step_ok ".venv 已存在且含 pip，仅更新依赖"
    else
        if [ -f .venv/pyvenv.cfg ]; then
            printf '  检测到不完整的 .venv（缺 pip）→ 删除重建\n'
            rm -rf .venv
        fi
        python3 -m venv .venv && step_ok ".venv 创建完成" \
          || step_fail "venv 创建失败（缺 python3-venv？）"
        if [ -x .venv/bin/python ] && [ ! -x .venv/bin/pip ]; then
            printf '  仍无 pip → 尝试 ensurepip 补装\n'
            .venv/bin/python -m ensurepip --upgrade >>/tmp/boot_pip.log 2>&1 || true
        fi
    fi

    if [ -x .venv/bin/pip ]; then
        .venv/bin/pip install -q -U pip >>/tmp/boot_pip.log 2>&1
        if .venv/bin/pip install -q -r requirements.txt >>/tmp/boot_pip.log 2>&1; then
            step_ok "依赖安装完成"
            .venv/bin/python -c "import requests,sympy;print('    requests',requests.__version__,'/ sympy',sympy.__version__)" 2>/dev/null \
              || step_fail "依赖装了但导入失败"
        else
            step_fail "依赖安装失败（见 /tmp/boot_pip.log）"
        fi
    else
        step_fail "venv 里没有 pip → 依赖未安装（先 apt install python3-venv）"
    fi
fi

# ---------------------------------------------------------------- 6 路径扫描（只读）
hdr "6 硬编码 Windows 路径扫描（只读，不改代码）"
HITS=$(grep -rIl --include='*.py' --include='*.sh' -e 'D:/python' -e 'C:\\Users' \
        -e 'D:\\挑战杯' -e 'python.exe' . 2>/dev/null \
        | grep -v -e '^./.venv/' -e '/__pycache__/' -e '^./vendor/' | head -20)
if [ -n "$HITS" ]; then
    printf '  以下文件含 Windows 专用路径，跑评测前需确认：\n'
    printf '%s\n' "$HITS" | sed 's/^/    /'
else
    step_ok "未发现硬编码 Windows 路径"
fi

# ---------------------------------------------------------------- 汇总
hdr "汇总"
if [ "${#FAILED[@]}" -eq 0 ]; then
    printf '  \033[32m全部就绪。\033[0m\n'
else
    printf '  \033[31m%d 项未通过：\033[0m\n' "${#FAILED[@]}"
    for f in "${FAILED[@]}"; do printf '    - %s\n' "$f"; done
fi
cat <<'NEXT'

下一步（手工）
  1) 传密钥：把本机 .env 传到仓库根，然后 chmod 600 .env
     ⚠️ 别 git add .env —— 里面有明文密码
  2) 装依赖确认：.venv/bin/pip list | grep -Ei 'requests|sympy'
  3) 试跑（务必带 --verbose，否则日志几乎静默）：
       source deploy/lean-env.sh
       tmux new -s eval
       .venv/bin/python run_eval.py --test_file <错题单>.jsonl \
           --concurrency 1 --verbose --output results/cloud_smoke.jsonl
  4) 另开一个窗口盯内存峰值：
       watch -n 5 'free -h; echo "lean 进程: $(pgrep -c lean)"'
     判据：available 常年 ≥2 GB、lean 进程数 ≤2 为健康
NEXT
exit ${#FAILED[@]}
