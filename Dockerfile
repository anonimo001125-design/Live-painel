FROM node:18-bullseye-slim
RUN apt-get update && apt-get install -y ffmpeg pulseaudio xvfb python3 python3-pip && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
CMD xvfb-run --server-args="-screen 0 1280x720x24" pulseaudio -D --exit-idle-time=-1 && python3 /app/app.py
