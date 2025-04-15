FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl unzip wget gnupg \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libasound2 libxshmfence1 libx11-xcb1 \
    ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ✅ 安装 playwright + Chromium，并修复权限
RUN pip install --no-cache-dir playwright && \
    playwright install --with-deps chromium && \
    chown -R botuser:botuser /root/.cache/ms-playwright

COPY . .

RUN useradd -m botuser
USER botuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]