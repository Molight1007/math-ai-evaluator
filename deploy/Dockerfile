# MathPilot 数学智能体评测器 — 生产镜像（v2 重构版）
# 设计要点（相对 v1）：
#   1. 非 root 用户运行（appuser, uid 1000）：容器逃逸风险收窄
#   2. 参数化：worker 数 / 超时可通过环境变量覆盖（容器内端口固定 5000）
#   3. 分层缓存：依赖层仅在 requirements.txt 变化时重建
#   4. HEALTHCHECK：python socket 探测（容器内无 curl）
#
# 构建: docker compose -f deploy/docker-compose.yml build
# 运行: docker compose -f deploy/docker-compose.yml up -d
FROM python:3.11-slim

# 运行期行为：日志即时输出、不写 .pyc、pip 不缓存
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── 依赖层（仅 requirements.txt 变化时重建）──
COPY requirements.txt .
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install flask gunicorn

# ── 应用代码 ──
COPY 测试工具/ ./测试工具/
COPY 转化工具/ ./转化工具/
COPY 题库/ ./题库/
COPY deploy/server.py .
COPY deploy/templates/ ./templates/

# ── 运行期目录 + 非 root 用户 ──
# 挂载卷（deploy/results、题库、users.json、user_api_settings.json）在
# Docker Desktop 下权限宽松（777），appuser 可写；若遇权限问题可改回 root。
RUN mkdir -p 测试结果/测试结果展示 测试结果/原始问题及答案 测试结果/原始问题 \
    && useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

# 健康检查：TCP 探测 5000 端口（不依赖具体路由）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import socket,sys; s=socket.create_connection(('127.0.0.1',5000),3); s.close(); sys.exit(0)" || exit 1

EXPOSE 5000

# 单 worker（默认）：Flask 全局状态（tasks/users_db/user_api_settings）依赖单进程，
# 并发由应用内 threading 处理；GUNICORN_WORKERS>1 会破坏共享状态，勿改。
# worker 数 / 超时可通过环境变量覆盖（见 docker-compose.yml）。
CMD ["sh", "-c", "exec gunicorn -w ${GUNICORN_WORKERS:-1} -b 0.0.0.0:5000 --timeout ${GUNICORN_TIMEOUT:-300} --access-logfile - server:app"]
