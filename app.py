import os
import re
import sys
import time
import signal
import threading
import subprocess

# ============================================================
# CONFIGURAÇÃO
# ============================================================

URL_ALVO = os.environ.get(
    "URL_ALVO",
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
)

DISPLAY = ":99"
WIDTH = 1280
HEIGHT = 720
FPS = 30

STREAM_DIR = os.path.abspath("stream")
PLAYLIST = os.path.join(STREAM_DIR, "live.m3u8")

HTTP_PORT = 8080

processos = []
browser = None
playwright_instance = None


# ============================================================
# UTILIDADES
# ============================================================

def executar(cmd, espera=0, env=None):
    print("\n[EXEC]", " ".join(cmd))

    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )

    processos.append(p)

    if espera:
        time.sleep(espera)

    return p


def matar_processos():
    print("\n[ENCERRANDO] Finalizando processos...")

    for p in reversed(processos):
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass

    time.sleep(2)

    for p in reversed(processos):
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass


def finalizar(sig=None, frame=None):
    matar_processos()

    try:
        if browser:
            browser.close()
    except Exception:
        pass

    try:
        if playwright_instance:
            playwright_instance.stop()
    except Exception:
        pass

    sys.exit(0)


signal.signal(signal.SIGTERM, finalizar)
signal.signal(signal.SIGINT, finalizar)


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():
    print("\n==========================================================")
    print("INICIANDO PULSEAUDIO")
    print("==========================================================")

    # Mata instâncias antigas
    subprocess.run(
        ["pulseaudio", "-k"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(1)

    subprocess.Popen([
        "pulseaudio",
        "--daemonize=yes",
        "--exit-idle-time=-1",
        "--disallow-exit=yes"
    ])

    time.sleep(3)

    # Cria um sink virtual próprio para o navegador.
    resultado = subprocess.run(
        [
            "pactl",
            "load-module",
            "
