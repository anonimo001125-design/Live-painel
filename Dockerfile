FROM node:18-bullseye-slim

# Instala o FFmpeg e dependências de fontes/navegador de forma limpa
RUN apt-get update && apt-get install -y \
    ffmpeg \
    chromium \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

RUN mkdir -p /app/stream
EXPOSE 8080

CMD ["node", "server.js"]
