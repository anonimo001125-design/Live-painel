FROM python:3.9-slim

# 1. Instala todas as dependências do sistema necessárias para vídeo, áudio e compiladores básicos
# Nota: O psutil às vezes precisa de ferramentas de build (gcc, python3-dev) para ser compilado no Linux.
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
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Configura a pasta de trabalho padrão
WORKDIR /app

# 3. Copia o arquivo de requerimentos e instala as bibliotecas Python (Flask e Psutil)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copia o restante dos arquivos do GitHub para o container
COPY . .

# 5. Cria a pasta onde os arquivos .m3u8 serão salvos
RUN mkdir -p static/hls && chmod -R 777 static/hls

EXPOSE 5000

# 6. Inicia o script principal
CMD ["python", "app.py"]
