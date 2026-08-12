FROM ://microsoft.com

RUN apt-get update && apt-get install -y ffmpeg pulseaudio curl && rm -rf /var/lib/apt/lists/*

RUN curl -s https://amazonaws.com | tee /etc/apt/trusted.gpg.co.id/ngrok.asc >/dev/null && \
    echo "deb [signed-by=/etc/apt/trusted.gpg.co.id/ngrok.asc] https://amazonaws.com buster main" | tee /etc/apt/sources.list.d/ngrok.list && \
    apt-get update && apt-get install ngrok

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/stream
EXPOSE 8080

CMD xvfb-run --server-args="-screen 0 1280x720x24" pulseaudio -D --exit-idle-time=-1 && python app.py
