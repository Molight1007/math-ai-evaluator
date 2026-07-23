#!/bin/bash
# ============================================================
# 优化版书生 AI · 数学智能体评测器 — 一键更新脚本（Docker 版）
# 用法: bash deploy/update.sh
# 做了三件事: 拉代码 → 重建镜像 → 无缝重启
# ============================================================
set -e

cd "$(dirname "$0")/.."

echo ">>> [1/3] 拉取最新代码…"
git pull

echo ""
echo ">>> [2/3] 重建并启动容器（无停机）…"
docker compose up -d --build

echo ""
echo ">>> [3/3] 清理旧镜像…"
docker image prune -f

echo ""
echo "========================================"
echo "  更新完成！"
echo "  当前运行状态:"
echo "========================================"
docker compose ps

echo ""
echo "  日志:  docker compose logs -f"
echo "  状态:  docker compose ps"
