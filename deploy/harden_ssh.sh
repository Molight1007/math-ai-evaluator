#!/usr/bin/env bash
# =============================================================================
# harden_ssh.sh — 服务器安全加固（只做 SSH 与暴露面，不动业务）
# -----------------------------------------------------------------------------
# 原则
#   1) 先测试后生效：任何 sshd 配置改动都先 `sshd -t` 校验，通过才 reload
#   2) 不启用 ufw：腾讯云安全组已是第一层；服务器内再启 ufw 若漏放行 22 会锁死自己，
#      收益低风险高。改为**核查监听端口**并提示去控制台收紧安全组
#   3) 保留退路：reload 不会断开已有会话；控制台还有 VNC 登录可兜底
#
# 做四件事：
#   A. 报告当前 sshd 关键开关（密码登录是否开、root 是否可登）
#   B. 收紧 sshd（密码登录关、root 仅密钥、限尝试次数），drop-in 方式，可回滚
#   C. 核查监听端口与防火墙状态
#   D. 报告近期登录失败情况
#
# 用法：bash deploy/harden_ssh.sh            # 只报告，不改
#       bash deploy/harden_ssh.sh --apply    # 应用加固
# =============================================================================
set -uo pipefail

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
DROPIN=/etc/ssh/sshd_config.d/99-mathpilot.conf

hr() { printf '%s\n' "----------------------------------------------------------------------"; }
hdr() { hr; printf '%s\n' "$*"; hr; }

if [ "$(uname -s)" != "Linux" ]; then
    echo "只能在 Linux 上运行"; exit 1
fi

# ---------------------------------------------------------------- A 现状
hdr "A 当前 sshd 关键开关"
EFF=$($SUDO sshd -T 2>/dev/null || true)
if [ -z "$EFF" ]; then
    echo "  ⚠️ 无法读取 sshd 有效配置（sshd -T 失败）"
else
    for k in passwordauthentication kbdinteractiveauthentication permitrootlogin \
             pubkeyauthentication permitemptypasswords maxauthtries x11forwarding; do
        v=$(printf '%s\n' "$EFF" | awk -v k="$k" 'tolower($1)==k{print $2; exit}')
        printf '  %-34s %s\n' "$k" "${v:-?}"
    done
fi

hdr "B 监听端口（对外只应有 22）"
$SUDO ss -tulnp 2>/dev/null | awk 'NR==1 || /LISTEN/' | sed 's/^/  /' || echo "  (ss 不可用)"

hdr "C 防火墙"
if command -v ufw >/dev/null 2>&1; then
    printf '  ufw: %s\n' "$($SUDO ufw status 2>/dev/null | head -1)"
else
    echo "  ufw: 未安装"
fi
printf '  iptables 规则数: %s\n' "$($SUDO iptables -S 2>/dev/null | wc -l)"
echo "  ⚠️ 真正的第一层是【腾讯云控制台 → 防火墙/安全组】：确认只放行 22(SSH)"

hdr "D 近期登录失败（前 10）"
$SUDO grep -i 'failed password\|invalid user' /var/log/auth.log 2>/dev/null \
  | tail -10 | sed 's/^/  /' || echo "  (无 auth.log 或没有失败记录)"
printf '  失败总数: %s\n' "$($SUDO grep -ci 'failed password\|invalid user' /var/log/auth.log 2>/dev/null || echo 0)"

# ---------------------------------------------------------------- E 加固
hdr "E 加固动作"
if [ "$APPLY" -eq 0 ]; then
    echo "  当前为【只报告】模式。要应用加固请加 --apply"
    echo "  将写入 $DROPIN ："
    echo "      PasswordAuthentication no"
    echo "      KbdInteractiveAuthentication no"
    echo "      PubkeyAuthentication yes"
    echo "      PermitRootLogin prohibit-password"
    echo "      MaxAuthTries 3"
    echo "      X11Forwarding no"
    exit 0
fi

# 前置：必须确认密钥登录可用，否则禁用密码会锁死
if ! grep -qE '^(ssh-|ecdsa-)' "$HOME/.ssh/authorized_keys" 2>/dev/null; then
    echo "  ❌ ~/.ssh/authorized_keys 里没有公钥 —— 拒绝禁用密码登录（会锁死）"
    exit 1
fi
echo "  ✓ authorized_keys 有 $(grep -cE '^(ssh-|ecdsa-)' "$HOME/.ssh/authorized_keys") 个公钥"

$SUDO mkdir -p /etc/ssh/sshd_config.d
if [ -f "$DROPIN" ]; then
    $SUDO cp -n "$DROPIN" "$DROPIN.bak" 2>/dev/null || true
fi
$SUDO tee "$DROPIN" >/dev/null <<'EOF'
# 由 deploy/harden_ssh.sh 生成（2026-09-20）
# 只允许密钥登录；保留控制台 VNC 作为退路
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin prohibit-password
MaxAuthTries 3
X11Forwarding no
EOF
echo "  ✓ 已写入 $DROPIN"

# 关键：先测试，通过才 reload（错误文本必须完整显示，否则排查无从下手）
TEST_OUT="$($SUDO sshd -t 2>&1)"
if [ -z "$TEST_OUT" ]; then
    echo "  ✓ sshd -t 校验通过"
else
    echo "  ❌ sshd -t 报错："
    printf '%s\n' "$TEST_OUT" | sed 's/^/      /'
    echo "  → 已回滚 $DROPIN，sshd 未改动"
    $SUDO rm -f "$DROPIN"
    exit 1
fi

$SUDO systemctl reload ssh 2>/dev/null || $SUDO systemctl reload sshd 2>/dev/null \
  || { echo "  ⚠️ reload 失败，尝试 restart"; $SUDO systemctl restart ssh 2>/dev/null || $SUDO systemctl restart sshd; }

sleep 2
EFF2=$($SUDO sshd -T 2>/dev/null || true)
echo "  生效后："
printf '    passwordauthentication  %s\n' "$(printf '%s\n' "$EFF2" | awk 'tolower($1)=="passwordauthentication"{print $2}')"
printf '    permitrootlogin         %s\n' "$(printf '%s\n' "$EFF2" | awk 'tolower($1)=="permitrootlogin"{print $2}')"

echo
echo "  ⚠️ 请立刻在【另一个】终端验证密钥仍能登录："
echo "       ssh -i <你的pem> ubuntu@<IP> echo OK"
echo "     若失败：控制台 → 轻量实例 → VNC 登录（用重置后的密码），"
echo "     然后 rm $DROPIN && sudo systemctl reload ssh"
echo "  ⚠️ 注意：reload 不会断开你当前已连接的会话，所以现在这个窗口是安全的。"
