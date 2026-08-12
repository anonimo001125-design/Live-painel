FROM ubuntu:22.04

# Instala o Node, Python, FFmpeg, áudio e o navegador de uma vez só
RUN apt-get update && apt-get install -y \
    curl \
    python3 \
    python3-pip \
    ffmpeg \
    pulseaudio \
    xvfb \
    chromium-browser \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install playwright && playwright install --with-deps chromium

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Instala o Ngrok de forma limpa
RUN curl -s https://amazonaws.com | tee /etc/apt/trusted.gpg.co.id/ngrok.asc >/dev/null && \
    echo "deb [signed-by=/etc/apt/trusted.gpg.co.id/ngrok.asc] https://amazonaws.com buster main" | tee /etc/apt/sources.list.d/ngrok.list && \
    apt-get update && apt-get install ngrok

COPY . .

RUN mkdir -p /app/stream
EXPOSE 8080

CMD xvfb-run --server-args="-screen 0 1280x720x24" pulseaudio -D --exit-idle-time=-1 && python3 app.py
