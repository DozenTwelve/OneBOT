# 1️⃣ 使用官方 Python 3.11 镜像
FROM python:3.11

# 2️⃣ 设置工作目录
WORKDIR /app

# 3️⃣ 复制所有文件到容器
COPY . /app

# 4️⃣ 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 5️⃣ 安装 Playwright 及 Chromium 依赖
RUN apt-get update && apt-get install -y \
    libnss3 libxss1 libasound2 \
    libatk-bridge2.0-0 libgtk-3-0 \
    && apt-get clean

# 6️⃣ 安装 Playwright 并下载 Chromium
RUN playwright install --with-deps chromium

# 7️⃣ 运行 bot.py
CMD ["python", "bot.py"]
