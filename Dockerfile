# ✅ 更安全基础镜像：基于 Debian Bookworm
FROM python:3.11-slim-bookworm

# ✅ 设置工作目录
WORKDIR /app

# ✅ 安装系统依赖（Playwright + HTTP/SSL 需要的最小依赖）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl unzip wget gnupg \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libasound2 libxshmfence1 libx11-xcb1 \
    ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ✅ 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ✅ 安装 Playwright + Chromium（只装 chromium）
RUN pip install --no-cache-dir playwright
RUN playwright install --with-deps chromium

# ✅ 拷贝项目代码
COPY . .

# ✅ 设置非 root 运行（安全）
RUN useradd -m botuser
USER botuser

# ✅ 环境变量（防止输出缓冲）
ENV PYTHONUNBUFFERED=1

# ✅ 启动命令（注意你的入口文件名，如 bot.py）
CMD ["python", "bot.py"]
