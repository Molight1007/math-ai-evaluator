#!/bin/bash
# ============================================================
# Docker 入口脚本：初始化持久化数据 & 启动 uvicorn
# （路径已适配当前目录结构：Web服务模块/api/）
# ============================================================
set -e

DATA="/app/data"
API_DIR="/app/Web服务模块/api"

# 确保持久化数据目录存在
mkdir -p "$DATA"

# ---- 1. users.db ----
# users.db 在 Web服务模块/api/ 目录下
if [ -f "$DATA/users.db" ]; then
    # 持久卷已有数据 → 用软链覆盖镜像中的
    rm -f "$API_DIR/users.db"
    ln -s "$DATA/users.db" "$API_DIR/users.db"
elif [ -f "$API_DIR/users.db" ]; then
    # 镜像自带初始 users.db → 迁移到持久卷
    mv "$API_DIR/users.db" "$DATA/users.db"
    ln -s "$DATA/users.db" "$API_DIR/users.db"
else
    # 都没有 → 建软链，FastAPI 启动时自动建表
    ln -s "$DATA/users.db" "$API_DIR/users.db"
fi

# ---- 2. 题库 databases ----
# 题库目录保持在 /app/题库（项目根目录下）
BANKS_DIR="$DATA/banks"
if [ -d "$BANKS_DIR" ]; then
    rm -rf /app/题库
    ln -s "$BANKS_DIR" /app/题库
else
    mv /app/题库 "$BANKS_DIR"
    ln -s "$BANKS_DIR" /app/题库
fi

echo "[entrypoint] 持久化初始化完成，启动服务…"

# ---- 3. 切换到 API 目录以支持相对导入 ----
cd /app/Web服务模块

exec "$@"
