FROM ghcr.io/puppeteer/puppeteer:21.5.0

USER root

# Instala o FFmpeg junto com os drivers de áudio virtuais (pulseaudio)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    xvfb \
    pulseaudio \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json .
RUN npm install

COPY . .

EXPOSE 3000

# Cria o servidor de som de fundo antes de abrir a imagem
CMD pulseaudio --start --exit-idle-time=-1 && Xvfb :99 -screen 0 1280x720x16 & node server.js
