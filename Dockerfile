FROM node:18-slim

# Instala o FFmpeg, Google Chrome e um servidor de tela virtual (Xvfb)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    xvfb \
    chromium \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

# Inicia a tela virtual e roda o seu script
CMD xvfb-run --server-args="-screen 0 1280x720x24" node index.js
