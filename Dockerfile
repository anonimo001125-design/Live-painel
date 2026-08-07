FROM ghcr.io/puppeteer/puppeteer:21.5.0

USER root

# Instala o motor de video FFmpeg e a tela virtual na nuvem do Render
RUN apt-get update && apt-get install -y \
    ffmpeg \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json .
RUN npm install

COPY . .

EXPOSE 3000

# Inicia a tela virtual e o servidor de video
CMD Xvfb :99 -screen 0 1280x720x16 & node server.js
