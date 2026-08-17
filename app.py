import os
import sys
import time
import asyncio
import signal
import subprocess
import threading
import re

from pyppeteer import launch


# ============================================================
# CONFIGURAÇÃO
# ============================================================

STREAM_DIR = "stream"

DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720

FPS = 30

HTTP_PORT = 8080

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

processos = []

ffmpeg_process = None
browser_global = None


# ============================================================
# LOG
# ============================================================

def log(*mensagens):
    print(*mensagens, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):
    log("")
    log("Encerrando transmissão...")

    global ffmpeg_process

    try:
        if ffmpeg_process and ffmpeg_process.poll() is None:
            ffmpeg_process.terminate()
    except Exception:
        pass

    for processo in processos:
        try:
            if processo.poll() is None:
                processo.terminate()
        except Exception:
            pass

    time.sleep(2)

    for processo in processos:
        try:
            if processo.poll() is None:
                processo.kill()
        except Exception:
            pass

    log("Transmissão encerrada.")
    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


# ============================================================
# PREPARAR STREAM
# ============================================================

def preparar_stream():
    os.makedirs(STREAM_DIR, exist_ok=True)

    for nome in os.listdir(STREAM_DIR):
        caminho = os.path.join(STREAM_DIR, nome)

        try:
            if os.path.isfile(caminho):
                os.remove(caminho)
        except Exception:
            pass

    log("Pasta stream preparada.")


# ============================================================
# PÁGINA DO PLAYER
# ============================================================

def criar_player():

    html = "\n".join([
        "<!DOCTYPE html>",
        "<html lang='pt-BR'>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>WebTV</title>",
        "<style>",
        "html,body{margin:0;width:100%;height:100%;background:#000;overflow:hidden}",
        "video{width:100%;height:100%;object-fit:contain;background:#000}",
        "#msg{position:fixed;top:10px;left:10px;color:white;font:14px Arial;z-index:10}",
        "</style>",
        "</head>",
        "<body>",
        "<div id='msg'>Carregando transmissão...</div>",
        "<video id='video' controls autoplay playsinline></video>",
        "<script src='https://cdn.jsdelivr.net/npm/hls.js@latest'></script>",
        "<script>",
        "const video=document.getElementById('video');",
        "const msg=document.getElementById('msg');",
        "const src='live.m3u8';",
        "",
        "function iniciar(){",
        "  if(video.canPlayType('application/vnd.apple.mpegurl')){",
        "    video.src=src;",
        "    video.play().catch(()=>{});",
        "    msg.style.display='none';",
        "    return;",
        "  }",
        "",
        "  if(window.Hls && Hls.isSupported()){",
        "    const hls=new Hls({",
        "      liveSyncDurationCount:3,",
        "      maxLiveSyncPlaybackRate:1.5,",
        "      enableWorker:true",
        "    });",
        "",
        "    hls.loadSource(src);",
        "    hls.attachMedia(video);",
        "",
        "    hls.on(Hls.Events.MANIFEST_PARSED,function(){",
        "      video.play().then(()=>{",
        "        msg.style.display='none';",
        "      }).catch(()=>{});",
        "    });",
        "",
        "    hls.on(Hls.Events.ERROR,function(event,data){",
        "      if(data.fatal){",
        "        setTimeout(()=>{",
        "          try{hls.destroy();}catch(e){}",
        "          location.reload();",
        "        },3000);",
        "      }",
        "    });",
        "",
        "    return;",
        "  }",
        "",
        "  msg.textContent='Este navegador não suporta HLS.';",
        "}",
        "",
        "iniciar();",
        "</script>",
        "</body>",
        "</html>"
    ])

    caminho = os.path.join(STREAM_DIR, "index.html")

    with open(caminho, "w", encoding="utf-8") as arquivo:
        arquivo.write(html)

    log("Player criado:", caminho)


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    xvfb = subprocess.Popen([
        "Xvfb",
        DISPLAY,
        "-screen",
        "0",
        f"{WIDTH}x{HEIGHT}x24",
        "-ac",
        "-nolisten",
        "tcp"
    ])

    processos.append(xvfb)

    time.sleep(3)

    if xvfb.poll() is not None:
        raise RuntimeError("Xvfb não iniciou.")

    log("Xvfb OK.")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("Iniciando PulseAudio...")

    os.environ["PULSE_SINK"] = "webtv"

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        check=False
    )

    time.sleep(3)

    info = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True
    )

    if info.returncode != 0:
        raise RuntimeError(
            "PulseAudio não iniciou:\n" + info.stderr
        )

    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        capture_output=True,
        text=True
    )

    if "webtv" not in sinks.stdout:

        log("Criando áudio virtual...")

        resultado = subprocess.run(
