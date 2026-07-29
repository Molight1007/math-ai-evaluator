FROM python:3.11-slim

WORKDIR /app

# 先升级 pip
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir flask gunicorn

COPY 测试工具/ ./测试工具/
COPY 转化工具/ ./转化工具/
COPY 题库/ ./题库/
COPY deploy/server.py .
COPY deploy/templates/ ./templates/

RUN mkdir -p 测试结果/测试结果展示 测试结果/原始输出和推理过程 测试结果/原始问题

EXPOSE 5000

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--timeout", "300", "server:app"]
