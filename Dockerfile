FROM python:3.9-slim

# 1. Instala todas as dependências do sistema como root
RUN apt-get update && apt-get install -y \
    ffmpeg \
    xvfb \
    pulseaudio \
    chromium \
    libnss3 \
    libgbm1 \
    libasound2 \
    dbus-x11 \
    xdotool \
    && rm -rf /var/lib/apt/lists/*

# 2. Configura a pasta de trabalho padrão
WORKDIR /app

# 3. Instala o Flask
RUN pip install --no-cache-dir flask

# 4. Copia os arquivos do GitHub para o container
COPY . .

# 5. Cria a pasta HLS com permissão total de escrita
RUN mkdir -p static/hls && chmod -R 777 static/hls

# Porta padrão de escuta informativa (o Render gerencia isso internamente)
EXPOSE 5000

# 6. Inicia a tela virtual antes do script Python
CMD ["xvfb-run", "--server-args=-screen 0 1280x720x24", "python", "app.py"]
