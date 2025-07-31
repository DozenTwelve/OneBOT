#!/bin/bash

# 设置工作目录
cd ~/Trump/Bot_trump/ || exit

# 停止并删除旧容器
echo "🛑 Stopping and removing old container..."
sudo docker stop trumpbot 2>/dev/null
sudo docker rm trumpbot 2>/dev/null

# 删除旧镜像
echo "🧹 Removing old image..."
sudo docker rmi trumpbot 2>/dev/null

# 构建新镜像
echo "🔨 Building new Docker image..."
sudo docker build -t trumpbot .

# 运行新容器
echo "🚀 Running new container..."
sudo docker run -d --name trumpbot --env-file .env trumpbot

echo "✅ Deployment complete!"