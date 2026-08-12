FROM ://microsoft.com

# Instala ferramentas de áudio e transmissão de vídeo
RUN apt-get update && apt-get install -y \
    ffmpeg \
    pulseaudio \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/stream
EXPOSE 10000

# Executa criando a placa de som virtual e o display em segundo plano
CMD xvfb-run --server-args="-screen 0 1280x720x24" pulseaudio -D --exit-idle-time=-1 && python app.py
