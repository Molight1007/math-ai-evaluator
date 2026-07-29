# ========== 数学智能体评测器 - Docker 镜像 ==========
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Web 服务依赖
RUN pip install --no-cache-dir flask gunicorn

# 复制项目代码（构建上下文为项目根目录）
COPY 测试工具/ ./测试工具/
COPY 转化工具/ ./转化工具/
COPY 题库/ ./题库/

# 复制 Web 服务入口
COPY deploy/server.py .

# 创建结果输出目录
RUN mkdir -p 测试结果/测试结果展示 测试结果/原始输出和推理过程 测试结果/原始问题

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--timeout", "300", "server:app"]
