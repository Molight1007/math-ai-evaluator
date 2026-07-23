#!/bin/bash
# ============================================================
# Docker 入口脚本：初始化持久化数据 & 启动 uvicorn
# ============================================================
set -e

DATA="/app/data"

# 确保持久化数据目录存在
mkdir -p "$DATA"

# ---- 1. users.db ----
if [ -f "$DATA/users.db" ]; then
    # 持久卷已有数据 → 用软链覆盖镜像中的
    rm -f /app/api/users.db
    ln -s "$DATA/users.db" /app/api/users.db
elif [ -f /app/api/users.db ]; then
    # 镜像自带初始 users.db → 迁移到持久卷
    mv /app/api/users.db "$DATA/users.db"
    ln -s "$DATA/users.db" /app/api/users.db
else
    # 都没有 → 建软链，FastAPI 启动时自动建表
    ln -s "$DATA/users.db" /app/api/users.db
fi

# ---- 2. 题库 databases ----
BANKS_DIR="$DATA/banks"
if [ -d "$BANKS_DIR" ]; then
    # 持久卷已有题库 → 替换镜像中的目录为软链
    rm -rf /app/题库
    ln -s "$BANKS_DIR" /app/题库
else
    # 首次：把镜像里的题库移入持久卷再建软链
    mv /app/题库 "$BANKS_DIR"
    ln -s "$BANKS_DIR" /app/题库
fi

echo "[entrypoint] 持久化初始化完成，启动服务…"

exec "$@"
