FROM python:3.10-slim

RUN apt-get update && apt-get install -y ffmpeg pulseaudio xvfb curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright pyngrok && playwright install --with-deps chromium

WORKDIR /app
COPY . .
RUN mkdir -p /app/stream
EXPOSE 8080

CMD xvfb-run --server-args="-screen 0 1280x720x24" pulseaudio -D --exit-idle-time=-1 && python3 app.py
