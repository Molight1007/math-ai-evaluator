# MathPilot 数学智能体评测器 — 容器镜像
# 构建: docker compose -f deploy/docker-compose.yml build
# 运行: docker compose -f deploy/docker-compose.yml up -d
FROM python:3.11-slim

# 运行期行为：日志即时输出、不写 .pyc、pip 不检查新版本/不缓存（减小镜像层）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 依赖层（利用 Docker 层缓存：仅 requirements.txt 变化时才重装）
COPY requirements.txt .
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install flask gunicorn

# 应用代码
COPY 测试工具/ ./测试工具/
COPY 转化工具/ ./转化工具/
COPY 题库/ ./题库/
COPY deploy/server.py .
COPY deploy/templates/ ./templates/

# 运行期目录（与 docker-compose 挂载卷对应；无挂载时也能启动）
RUN mkdir -p 测试结果/测试结果展示 测试结果/原始问题及答案 测试结果/原始问题

# 健康检查：容器内无 curl，用 python socket 探测端口（不依赖具体路由）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import socket,sys; s=socket.create_connection(('127.0.0.1',5000),3); s.close(); sys.exit(0)" || exit 1

EXPOSE 5000

# 单 worker：Flask 全局状态（tasks / users_db / user_api_settings）依赖单进程，
# 并发由应用内 threading 处理，勿改为多 worker（-w 2+ 会破坏共享状态）。
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "300", "--access-logfile", "-", "server:app"]
