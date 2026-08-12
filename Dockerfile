FROM ://microsoft.com

# Instala o FFmpeg e pacotes de áudio essenciais de forma direta
RUN apt-get update && apt-get install -y \
    ffmpeg \
    pulseaudio \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baixa o Ngrok oficial para dentro do container de forma limpa
RUN curl -s https://amazonaws.com | tee /etc/apt/trusted.gpg.co.id/ngrok.asc >/dev/null && \
    echo "deb [signed-by=/etc/apt/trusted.gpg.co.id/ngrok.asc] https://amazonaws.com buster main" | tee /etc/get/sources.list.d/ngrok.list && \
    apt-get update && apt-get install ngrok

COPY . .

RUN mkdir -p /app/stream
EXPOSE 8080

# Comando que liga o display virtual, a placa de som virtual e o script principal
CMD xvfb-run --server-args="-screen 0 1280x720x24" pulseaudio -D --exit-idle-time=-1 && python app.py
