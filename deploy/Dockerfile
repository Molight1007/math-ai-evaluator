FROM python:3.11-slim

WORKDIR /app

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir flask gunicorn

COPY 测试工具/ ./测试工具/
COPY 转化工具/ ./转化工具/
COPY 题库/ ./题库/
COPY user_agent.py .
COPY agent/ ./agent/
COPY utils/ ./utils/
COPY prompts/ ./prompts/
COPY deploy/server.py .
COPY deploy/templates/ ./templates/

RUN mkdir -p 测试结果/测试结果展示 测试结果/原始问题及答案 测试结果/原始问题

EXPOSE 5000

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "300", "server:app"]
