FROM ://microsoft.com

RUN apt-get update && apt-get install -y ffmpeg pulseaudio xvfb curl && rm -rf /var/lib/apt/lists/*

# Instala as duas dependências direto aqui, sem precisar do arquivo requirements.txt
RUN pip install --no-cache-dir playwright pyngrok

WORKDIR /app
COPY . .
RUN mkdir -p /app/stream
EXPOSE 8080

CMD xvfb-run --server-args="-screen 0 1280x720x24" pulseaudio -D --exit-idle-time=-1 && python3 app.py
