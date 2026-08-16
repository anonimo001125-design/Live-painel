import os
import time
import signal
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÕES
# ============================================================

WIDTH = 1280
HEIGHT = 720
DISPLAY = ":99"

# COLOQUE AQUI O ENDEREÇO DO SEU PAINEL
URL_ALVO = os.environ.get(
    "URL_ALVO",
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
)

STREAM_DIR = Path("stream")
PLAYLIST = STREAM_DIR / "live.m3u8"

HTTP_PORT = 8080


# ============================================================
# PROCESSOS
# ============================================================

processos = []


def executar_background(comando):
    processo = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(processo)
    return processo


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar_tudo(*args):
    print("\nEncerrando transmissão...")

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

    print("Transmissão encerrada.")


signal.signal(signal.SIGINT, encerrar_tudo)
signal.signal(signal.SIGTERM, encerrar_tudo)


# ============================================================
# PASTA STREAM
# ============================================================

def preparar_stream():

    STREAM_DIR.mkdir(parents=True, exist_ok=True)

    # Remove arquivos antigos para não iniciar com playlist velha
    for arquivo in STREAM_DIR.glob("segment_*.ts"):
        try:
            arquivo.unlink()
        except Exception:
            pass

    try:
        PLAYLIST.unlink()
    except FileNotFoundError:
        pass


# ============================================================
# PULSEAUDIO
#
