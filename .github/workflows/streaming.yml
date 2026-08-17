import os
import re
import sys
import time
import signal
import shutil
import subprocess
import threading

from playwright.sync_api import sync_playwright


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
tunnel_process = None
browser = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):
    log("")
    log("==============================================")
    log("ENCERRANDO WEBTV")
    log("==============================================")

    global ffmpeg_process
    global tunnel_process
    global browser

    try:
        if browser:
            browser.close()
    except Exception:
        pass

    try:
        if ffmpeg_process and ffmpeg_process.poll() is None:
            ffmpeg_process.terminate()
    except Exception:
        pass

    try:
        if tunnel_process and tunnel_process.poll() is None:
            tunnel_process.terminate()
    except Exception:
        pass

    for p in processos:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass

    time.sleep(2)

    for p in processos:
        try:
            if p.poll() is None:
                p.kill()
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

    log("Stream preparado.")


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():
    log("")
    log("[1] Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    p = subprocess.Popen(
        [
            "Xvfb",
            DISPLAY,
            "-screen",
            "0",
            f"{WIDTH}x{HEIGHT}x24",
            "-ac",
            "-nolisten",
            "tcp"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    processos.append(p)

    time.sleep(3)

    if p.poll() is not None:
        raise RuntimeError("Xvfb não iniciou.")

    log("Xvfb OK:", DISPLAY)


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_pulseaudio():
    log("")
    log("[2] Preparando PulseAudio...")

    os.environ["PULSE_SINK"] = "webtv"

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    time.sleep(3)

    teste = subprocess.run(
        ["pactl", "info"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if teste.returncode != 0:
        raise RuntimeError(
            "PulseAudio não está disponível."
        )

    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if "webtv" not in sinks.stdout:
        log("Criando sink de áudio webtv...")

        criar = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if criar.returncode != 0:
            raise RuntimeError(
                "Não foi possível criar o sink webtv: "
                + criar.stderr
            )

    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        check=False
    )

    time.sleep(2)

    fontes = subprocess.run(
        ["pactl", "list", "short", "sources"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    log("Fontes PulseAudio:")
    log(fontes.stdout)

    if "webtv.monitor" not in fontes.stdout:
        raise RuntimeError(
            "webtv.monitor não foi encontrado."
        )

    log("PulseAudio OK.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():
    log("")
    log("[3] Iniciando servidor HTTP...")

    servidor = subprocess.Popen(
        [
            "python3",
            "-m",
            "http.server",
            str(HTTP_PORT),
            "--directory",
            STREAM_DIR
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    processos.append(servidor)

    time.sleep(2)

    if servidor.poll() is not None:
        raise RuntimeError(
            "Servidor HTTP não iniciou."
        )

    log(
        "Servidor HTTP funcionando na porta",
        HTTP_PORT
    )


# ============================================================
# TÚNEL LOCALHOST.RUN
# ============================================================

def iniciar_tunel():
    global tunnel_process

    log("")
    log("[4] Iniciando túnel público...")
    log("Aguardando endereço público...")

    tunnel_process = subprocess.Popen(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "ExitOnForwardFailure=yes",
            "-R",
            f"80:localhost:{HTTP_PORT}",
            "nokey@localhost.run"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(tunnel_process
