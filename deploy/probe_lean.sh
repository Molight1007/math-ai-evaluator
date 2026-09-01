#!/usr/bin/env bash
# ============================================================
# 平台 Lean 环境探测（零重量，不提交任何二进制）
# ============================================================
# 用法：bash deploy/probe_lean.sh   （由 user_agent.py 启动时自动调用，
#       仅当仓库存在 deploy/.probe 标记文件时执行）
#
# 输出约定：全部走 stdout，行首带 `PROBE|` 前缀，便于在评测日志中检索。
# 设计原则：任何一步失败都不中断（set +e），绝不阻塞主流程。
# 超时：调用方（user_agent.py）用 subprocess timeout=30 兜底。
#
# 探测分 3 关：
#   关0 平台是否已预装 lean/lake/elan（零成本）
#   关1 外网可达性（GitHub 对照 tuna 清华镜像）
#   关2 （可选，需二进制已提交时）自带 lean 能否执行
# ============================================================
set +e

echo "PROBE|start $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# ---------- 关 0：预装检查 ----------
for cmd in lean lake elan leanchecker; do
  path="$(command -v "$cmd" 2>/dev/null)"
  if [ -n "$path" ]; then
    echo "PROBE|preinstalled|$cmd|$path"
  else
    echo "PROBE|not_found|$cmd"
  fi
done

# 若预装 lean，取版本（老版本可能是 lean3，无法用 mathlib v4）
if command -v lean >/dev/null 2>&1; then
  echo "PROBE|lean_version|$(lean --version 2>&1 | head -1)"
fi
if command -v lake >/dev/null 2>&1; then
  echo "PROBE|lake_version|$(lake --version 2>&1 | head -1)"
fi

# ---------- 关 1：外网可达性 ----------
# GitHub（lean 二进制分发主源）—— 3s 超时
GH_CODE=000; GH_TIME="?"
GH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 6 \
  https://github.com/leanprover/lean4/releases 2>/dev/null)
echo "PROBE|net|github|http=${GH_CODE}"

# tuna 清华镜像（已知可达：pip install 走它）—— 对照组
TUNA_CODE=000
TUNA_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 6 \
  https://pypi.tuna.tsinghua.edu.cn/simple/ 2>/dev/null)
echo "PROBE|net|tuna|http=${TUNA_CODE}"

# leanprover 官方 CDN / elan 安装源
LEAN_CDN=000
LEAN_CDN=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 6 \
  https://raw.githubusercontent.com/leanprover/lean4/master/README.md 2>/dev/null)
echo "PROBE|net|raw_github|http=${LEAN_CDN}"

# ---------- 关 2：自带二进制（若已随仓库提交）----------
# 说明：lean 官方发布包中 bin/lean 是软链/包装，真身在 lib/lean/lean；
#       本地 deploy/lean-4.31.0-linux/ 若已解压则测，否则跳过。
LEAN_HOME="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)/deploy/lean-4.31.0-linux"
if [ -x "$LEAN_HOME/lib/lean/lean" ]; then
  echo "PROBE|bundled_lean_found|$LEAN_HOME"
  echo "PROBE|bundled_lean_version|$($LEAN_HOME/lib/lean/lean --version 2>&1 | head -1)"
  # 纯核心编译测试（不需要 mathlib；import Init 走自带 olean）
  echo '#eval 1 + 1' > /tmp/probe_core.lean
  (cd /tmp && "$LEAN_HOME/lib/lean/lean" probe_core.lean 2>&1)
  echo "PROBE|bundled_core_eval_exit=$?"
else
  echo "PROBE|bundled_lean_missing"
fi

echo "PROBE|end"
