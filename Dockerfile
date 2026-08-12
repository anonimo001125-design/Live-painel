FROM ghcr.io/puppeteer/puppeteer:22.10.0

USER root

# Instala o FFmpeg para processar o streaming m3u8
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

RUN mkdir -p /app/stream
EXPOSE 8080

CMD ["node", "server.js"]
