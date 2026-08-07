# Usa uma imagem oficial que já vem com o Chrome e bibliotecas gráficas prontas
FROM ghcr.io/puppeteer/puppeteer:22.6.0

USER root

# Instala apenas o FFmpeg e o sistema de som virtual
RUN apt-get update && apt-get install -y ffmpeg xvfb pulseaudio --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 3000

# Inicia a tela virtual, o som de fundo e o script em uma única linha ligeira
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x720x24 & pulseaudio --start --exit-idle-time=-1 & sleep 2 && npm start"]
