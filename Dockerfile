FROM node:20-slim

# Instala dependências e o navegador Chromium nativo do Linux
RUN apt-get update && apt-get install -y \
    ffmpeg \
    xvfb \
    chromium \
    alsa-utils \
    libasound2-plugins \
    procps \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY package*.json ./

# Força o Puppeteer a ignorar o download do Chrome interno (vamos usar o do sistema)
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true

RUN npm install

COPY . .

EXPOSE 3000

# Inicializa o display virtual na porta :99 antes de rodar o Node
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x720x24 & npm start"]
