FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    pulseaudio \
    xvfb \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir playwright && playwright install --with-deps chromium

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN curl -s https://amazonaws.com | tee /etc/apt/trusted.gpg.co.id/ngrok.asc >/dev/null && \
    echo "deb [signed-by=/etc/apt/trusted.gpg.co.id/ngrok.asc] https://amazonaws.com buster main" | tee /etc/get/sources.list.d/ngrok.list && \
    apt-get update && apt-get install ngrok

COPY . .

RUN mkdir -p /app/stream
EXPOSE 8080

CMD xvfb-run --server-args="-screen 0 1280x720x24" pulseaudio -D --exit-idle-time=-1 && python app.py
