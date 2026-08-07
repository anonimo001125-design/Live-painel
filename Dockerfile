FROM node:20-slim

# Instala apenas o FFmpeg, Python3 e wget (necessários para extração direta)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    python3 \
    wget \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Instala a versão mais recente do yt-dlp diretamente do repositório oficial
RUN wget https://github.com -O /usr/local/bin/yt-dlp \
    && chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /usr/src/app

COPY package*.json ./
RUN npm install
COPY . .

EXPOSE 3000

CMD ["npm", "start"]
