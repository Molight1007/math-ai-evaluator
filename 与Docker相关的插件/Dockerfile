# ============================================================
# 优化版书生 AI · 数学智能体评测器 — 后端镜像
# 构建: docker build -t math-evaluator .
# ============================================================
FROM python:3.10-slim

WORKDIR /app

# 系统依赖（pdfplumber 需要 libstdc++）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目全部代码
COPY . .

# 测试结果目录（运行时写入）
RUN mkdir -p 测试结果/测试结果展示 \
    测试结果/原始输出和推理过程 \
    测试结果/原始问题 \
    测试结果/测试lean文件

# 入口脚本
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
