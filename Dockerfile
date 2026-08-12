FROM python:3.10-slim

# Instala FFmpeg, Chrome e dependências de tela virtual
RUN apt-get update && apt-get install -y \
    xvfb \
    ffmpeg \
    wget \
    gnupg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instala o Google Chrome
RUN wget -q -O - https://google.com | apt-key add - \
    && echo "deb [arch=amd64] http://google.com stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update && apt-get install -y google-chrome-stable

# Configura o diretório de trabalho
WORKDIR /app

# Copia os arquivos do projeto
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cria a pasta onde o m3u8 vai ficar disponível na web
RUN mkdir -p /app/stream

# Porta padrão que o Render vai ler e gerar o link público
EXPOSE 10000

# Script inicializador que liga a tela de fundo, o navegador e o streaming
CMD Xvfb :99 -screen 0 1280x720x24 & export DISPLAY=:99 && python app.py
