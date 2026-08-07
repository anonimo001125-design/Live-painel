FROM node:20-slim

# Instala FFmpeg, Xvfb (tela), Chromium e PulseAudio (gerenciador de som virtual)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    xvfb \
    chromium \
    pulseaudio \
    dbus-x11 \
    procps \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY package*.json ./

ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true

RUN npm install

COPY . .

EXPOSE 3000

# Script de inicialização unificado: cria o D-Bus, inicia a Tela Virtual, inicia o Som Virtual e abre o Node
CMD ["sh", "-c", "mkdir -p /var/run/dbus && dbus-uuidgen --ensure && Xvfb :99 -screen 0 1280x720x24 & pulseaudio --start --exit-idle-time=-1 & sleep 2 && npm start"]
