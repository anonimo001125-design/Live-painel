import os
import re
import sys
import time
import signal
import shutil
import threading
import subprocess
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

# ============================================================
# CONFIGURAÇÃO
# ============================================================

STREAM_DIR = os.path.abspath("stream")
DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720
FPS = 30

HTTP_PORT = 8080

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

processes = []
tunnel_process = None
ffmpeg_process = None


# ============================================================
# LOG
# ============================================================

def log(text=""):
    print(text, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def stop_all(signum=None, frame=None):
    global tunnel_process
    global ffmpeg_process

    log("")
    log("ENCERRANDO...")

    for proc in [ffmpeg_process, tunnel_process] + processes:
        if proc is None:
            continue

        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

    time.sleep(2)

    for proc in [ffmpeg_process, tunnel_process] + processes:
        if proc is None:
            continue

        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass

    sys.exit(0)


signal.signal(signal.SIGTERM, stop_all)
signal.signal(signal.SIGINT, stop_all)


# ============================================================
# PREPARAR STREAM
# ============================================================

def prepare_stream():
    os.makedirs(STREAM_DIR, exist_ok=True)

    for name in os.listdir(STREAM_DIR):
        path = os.path.join(STREAM_DIR, name)

        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    log("Stream preparado.")


# ============================================================
# XVFB
# ============================================================

def start_xvfb():
    log("Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    proc = subprocess.Popen(
        [
            "Xvfb",
            DISPLAY,
            "-screen",
            "0",
            f"{WIDTH}x{HEIGHT}x24",
            "-ac",
            "-nolisten",
            "tcp",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    processes.append(proc)

    time.sleep(3)

    if proc.poll() is not None:
        raise RuntimeError("Xvfb não iniciou.")

    log("Xvfb OK.")


# ============================================================
# PULSEAUDIO
# ============================================================

def start_pulse():
    log("Iniciando PulseAudio...")

    runtime = "/tmp/pulse-runtime"

    os.makedirs(runtime, exist_ok=True)

    os.environ["PULSE_RUNTIME_PATH"] = runtime

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--daemonize=true",
            "--exit-idle-time=-1",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(3)

    info = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True,
    )

    if info.returncode != 0:
        raise RuntimeError("PulseAudio não iniciou.")

    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        capture_output=True,
        text=True,
    )

    if "webtv" not in sinks.stdout:
        result = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Não foi possível criar o áudio virtual WebTV."
           
