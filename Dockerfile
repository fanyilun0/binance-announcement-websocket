FROM python:3.9-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 

# 运行程序
CMD ["python3", "-u", "main.py"]