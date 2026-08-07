# Usa uma imagem oficial estável do Node.js baseada em Debian
FROM node:20-slim

# Instala dependências do sistema: FFmpeg, Xvfb (tela virtual) e bibliotecas do Chrome
RUN apt-get update && apt-get install -y \
    ffmpeg \
    xvfb \
    wget \
    gnupg \
    ca-certificates \
    procps \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Configura o diretório de trabalho dentro do container
WORKDIR /usr/src/app

# Copia os arquivos de dependências
COPY package*.json ./

# Instala as dependências do Node.js (incluindo o Puppeteer)
RUN npm install

# Copia o restante dos arquivos do seu projeto
COPY . .

# Expõe a porta que o Express vai rodar (Render gerencia isso automaticamente)
EXPOSE 3000

# Comando para iniciar o Xvfb (tela virtual na porta :99) e rodar o script Node.js
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x720x24 & npm start"]
