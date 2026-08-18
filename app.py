#!/usr/bin/env python3

import asyncio
import os
import signal
import subprocess
import sys
import time
import threading
import shutil
from pathlib import Path

from flask import Flask, send_from_directory, Response

# ============================================================
# CONFIGURAÇÃO
# ============================================================

HOST = "0.0.0.0"
PORT = 8080

DISPLAY = ":99"
WIDTH = 1280
HEIGHT = 720
FPS = 30

STREAM_DIR = Path("stream")
DEBUG_DIR = Path("stream")

PAGE_URL = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

XVFB_PROCESS = None
PULSE_PROCESS = None
CHROMIUM_PROCESS = None
FFMPEG_PROCESS = None
TUNNEL_PROCESS = None

app = Flask(__name__)

# ============================================================
# LIMPEZA
# ============================================================

def cleanup():
    global XVFB_PROCESS
    global PULSE_PROCESS
    global CHROMIUM_PROCESS
    global FFMPEG_PROCESS
    global TUNNEL_PROCESS

    print("\n[ENCERRANDO] Limpando processos...")

    processes = [
        FFMPEG_PROCESS,
        CHROMIUM_PROCESS,
        PULSE_PROCESS,
        XVFB_PROCESS,
        TUNNEL_PROCESS,
    ]

    for process in processes:
        if process is None:
            continue

        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            pass

    time.sleep(1)

    for process in processes:
        if process is None:
            continue

        try:
            if process.poll() is None:
                process.kill()
        except Exception:
            pass

    print("[ENCERRANDO] Finalizado.")


def signal_handler(signum, frame):
    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ============================================================
# STREAM ANTIGO
# ============================================================

def clean_stream():
    STREAM_DIR.mkdir(exist_ok=True)

    for file in STREAM_DIR.glob("*"):
        try:
            if file.is_file():
                file.unlink()
        except Exception as e:
            print(f"[AVISO] Não foi possível remover {file}: {e}")


# ============================================================
# Xvfb
# ============================================================

def start_xvfb():
    global XVFB_PROCESS

    print("=" * 70)
    print("[2] Iniciando Xvfb...")
    print(f"DISPLAY: {DISPLAY}")
    print(f"RESOLUÇÃO: {WIDTH}x{HEIGHT}")

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    XVFB_PROCESS = subprocess.Popen(
        [
            "Xvfb",
            DISPLAY,
            "-screen",
            "0",
            f"{WIDTH}x{HEIGHT}x24",
            "-ac",
            "+extension",
            "GLX",
            "+render",
            "-noreset",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    time.sleep(2)

    if XVFB_PROCESS.poll() is not None:
        raise RuntimeError("Xvfb não iniciou corretamente.")

    print("Xvfb pronto.")


# ============================================================
# PULSEAUDIO
# ============================================================

def start_pulseaudio():
    global PULSE_PROCESS

    print("=" * 70)
    print("[3] Iniciando PulseAudio...")
    print("Criando sink virtual webtv...")

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    subprocess.run(
        ["pulseaudio", "--kill"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(1)

    PULSE_PROCESS = subprocess.Popen(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    time.sleep(2)

    # Sink virtual
    subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            "sink_name=webtv",
            "sink_properties=device.description=WebTV",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(1)

    result = subprocess.run(
        ["pactl", "list", "short", "sources"],
        capture_output=True,
        text=True,
    )

    print("Fontes de áudio:")

    if result.stdout.strip():
        print(result.stdout)
    else:
        print("[AVISO] Nenhuma fonte de áudio encontrada.")

    print("Áudio pronto.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WEBTV STREAM</title>
<style>
html, body {
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    background: #000;
    overflow: hidden;
}
video {
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #000;
}
</style>
</head>
<body>
<video
    controls
    autoplay
    muted
    playsinline
    src="/live.m3u8">
</video>
</body>
</html>
"""


@app.route("/live.m3u8")
def playlist():
    path = STREAM_DIR / "live.m3u8"

    if not path.exists():
        return Response(
            "Stream ainda não disponível",
            status=503,
            mimetype="text/plain",
        )

    return send_from_directory(
        STREAM_DIR,
        "live.m3u8",
        mimetype="application/vnd.apple.mpegurl",
        max_age=0,
    )


@app.route("/<path:filename>")
def stream_file(filename):
    path = STREAM_DIR / filename

    if not path.exists():
        return Response("Arquivo não encontrado", status=404)

    mimetype = "video/mp2t"

    if filename.endswith(".m3u8"):
        mimetype = "application/vnd.apple.mpegurl"

    return send_from_directory(
        STREAM_DIR,
        filename,
        mimetype=mimetype,
        max_age=0,
    )


def start_http():
    print("=" * 70)
    print("[4] Iniciando servidor HTTP...")
    print(f"Servidor HTTP ativo na porta {PORT}")

    thread = threading.Thread(
        target=lambda: app.run(
            host=HOST,
            port=PORT,
            threaded=True,
            use_reloader=False,
        ),
        daemon=True,
    )

    thread.start()

    time.sleep(2)


# ============================================================
# CHROMIUM
# ============================================================

def find_chromium():
    candidates = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]

    for candidate in candidates:
        path = shutil.which(candidate)

        if path:
            return path

    raise RuntimeError(
        "Chromium/Google Chrome não encontrado."
    )


def start_chromium():
    global CHROMIUM_PROCESS

    print("=" * 70)
    print("[6] Iniciando Chromium...")

    chromium = find_chromium()

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    user_data = Path("/tmp/webtv-chromium")

    try:
        shutil.rmtree(user_data)
    except Exception:
        pass

    user_data.mkdir(parents=True, exist_ok=True)

    command = [
        chromium,

        "--no-sandbox",
        "--disable-setuid-sandbox",

        "--disable-dev-shm-usage",

        "--disable-gpu",
        "--disable-software-rasterizer",

        "--autoplay-policy=no-user-gesture-required",

        "--start-fullscreen",
        "--kiosk",

        "--window-size=1280,720",
        "--window-position=0,0",

        "--disable-infobars",
        "--disable-notifications",

        "--disable-features=Translate",
        "--disable-features=MediaSessionService",

        "--user-data-dir=" + str(user_data),

        PAGE_URL,
    ]

    CHROMIUM_PROCESS = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    time.sleep(5)

    if CHROMIUM_PROCESS.poll() is not None:
        print("[ERRO] Chromium encerrou inesperadamente.")
        return False

    print("Chromium iniciado.")
    print("Abrindo página:")
    print(PAGE_URL)
    print("Página carregada.")

    return True


# ============================================================
# FULLSCREEN VIA X11
# ============================================================

def fullscreen_chromium():
    print("=" * 70)
    print("[TELA] Ativando tela cheia do Chromium")

    try:
        subprocess.run(
            [
                "xdotool",
                "search",
                "--onlyvisible",
                "--class",
                "chromium",
                "windowactivate",
                "--sync",
                "key",
                "F11",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )

        print("[TELA] Chromium em tela cheia.")

    except Exception as e:
        print(f"[AVISO] Não foi possível usar xdotool: {e}")


# ============================================================
# FFmpeg
# ============================================================

def start_ffmpeg():
    global FFMPEG_PROCESS

    print("=" * 70)
    print("INICIANDO FFMPEG")

    STREAM_DIR.mkdir(exist_ok=True)

    playlist = STREAM_DIR / "live.m3u8"

    try:
        playlist.unlink()
    except FileNotFoundError:
        pass

    # Descobre automaticamente o monitor do sink webtv.
    monitor = "webtv.monitor"

    command = [
        "ffmpeg",
        "-y",

        "-hide_banner",
        "-loglevel",
        "warning",

        # Vídeo
        "-thread_queue_size",
        "4096",

        "-f",
        "x11grab",

        "-draw_mouse",
        "0",

        "-framerate",
        str(FPS),

        "-video_size",
        f"{WIDTH}x{HEIGHT}",

        "-i",
        f"{DISPLAY}.0",

        # Áudio
        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-i",
        monitor,

        # Vídeo
        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-tune",
        "zerolatency",

        "-pix_fmt",
        "yuv420p",

        "-r",
        str(FPS),

        "-g",
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        "-b:v",
        "1500k",

        "-maxrate",
        "1800k",

        "-bufsize",
        "3000k",

        # Áudio
        "-c:a",
        "aac",

        "-b:a",
        "96k",

        "-ar",
        "44100",

        "-ac",
        "2",

        # HLS
        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        str(STREAM_DIR / "segment_%05d.ts"),

        str(playlist),
    ]

    print("Comando FFmpeg:")
    print(" ".join(command))

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    FFMPEG_PROCESS = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    def read_ffmpeg():
        for line in FFMPEG_PROCESS.stdout:
            line = line.strip()

            if line:
                print(f"[FFMPEG] {line}")

    threading.Thread(
        target=read_ffmpeg,
        daemon=True,
    ).start()

    time.sleep(3)

    if FFMPEG_PROCESS.poll() is not None:
        raise RuntimeError(
            "FFmpeg encerrou antes de criar a transmissão."
        )

    print("FFmpeg funcionando.")


# ============================================================
# ESPERA HLS
# ============================================================

def wait_hls(timeout=30):
    print("=" * 70)
    print("[HLS] Aguardando playlist...")

    playlist = STREAM_DIR / "live.m3u8"

    start = time.time()

    while time.time() - start < timeout:

        if playlist.exists():

            segments = list(
                STREAM_DIR.glob("segment_*.ts")
            )

            if segments:
                print("[HLS] Playlist pronta.")
                return True

        time.sleep(1)

    print("[ERRO] Playlist HLS não foi criada.")
    return False


# ============================================================
# TÚNEL
# ============================================================

def start_tunnel():
    global TUNNEL_PROCESS

    print("=" * 70)
    print("[5] Iniciando túnel localhost.run...")

    command = [
        "ssh",

        "-o",
        "StrictHostKeyChecking=no",

        "-o",
        "ServerAliveInterval=20",

        "-o",
        "ServerAliveCountMax=3",

        "-o",
        "ExitOnForwardFailure=yes",

        "-R",
        "80:localhost:8080",

        "nokey@localhost.run",
    ]

    TUNNEL_PROCESS = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    url_found = None

    while True:

        line = TUNNEL_PROCESS.stdout.readline()

        if not line:
            break

        line = line.strip()

        if not line:
            continue

        print(f"[TUNEL] {line}")

        if "lhr.life" in line:

            import re

            match = re.search(
                r"https://[a-zA-Z0-9.-]+\.lhr\.life",
                line,
            )

            if match:
                url_found = match.group(0)

                break

    if not url_found:
        print(
            "[AVISO] Não foi possível detectar automaticamente "
            "o endereço do túnel."
        )

        return None

    return url_found


# ============================================================
# MONITOR DO TÚNEL
# ============================================================

def tunnel_monitor():
    global TUNNEL_PROCESS

    while True:

        time.sleep(10)

        if TUNNEL_PROCESS is None:
            continue

        if TUNNEL_PROCESS.poll() is not None:

            print(
                "[TUNEL] Conexão encerrada. "
                "Tentando reiniciar..."
            )

            try:
                new_url = start_tunnel()

                if new_url:
                    print("=" * 70)
                    print("NOVO LINK DA TRANSMISSÃO")
                    print("=" * 70)
                    print(f"LINK PRINCIPAL: {new_url}")
                    print(
                        f"LINK HLS: {new_url}/live.m3u8"
                    )
                    print("=" * 70)

            except Exception as e:
                print(
                    f"[TUNEL] Falha ao reiniciar: {e}"
                )

            time.sleep(5)


# ============================================================
# VERIFICAÇÕES
# ============================================================

def check_dependencies():

    dependencies = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
        "ssh",
    ]

    missing = []

    for command in dependencies:
        if shutil.which(command) is None:
            missing.append(command)

    if missing:

        raise RuntimeError(
            "Dependências ausentes: "
            + ", ".join(missing)
        )


def check_x11():

    print("=" * 70)
    print("[DIAGNÓSTICO] Testando X11...")

    debug_file = DEBUG_DIR / "debug_screen.png"

    try:
        subprocess.run(
            [
                "import",
                "-display",
                DISPLAY,
                "-window",
                "root",
                str(debug_file),
            ],
            timeout=10,
            check=True,
        )

        if debug_file.exists():
            print(
                f"[DIAGNÓSTICO] Captura OK: {debug_file}"
            )
            return True

    except Exception as e:
        print(
            f"[DIAGNÓSTICO] Falha na captura X11: {e}"
        )

    return False


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("WEBTV STREAM")
    print("=" * 70)

    try:

        print("[1] Limpando stream antigo...")
        clean_stream()

        check_dependencies()

        start_xvfb()

        start_pulseaudio()

        start_http()

        tunnel_url = start_tunnel()

        if tunnel_url:

            print("=" * 70)
            print("LINK DA TRANSMISSÃO")
            print("=" * 70)
            print("LINK PRINCIPAL:")
            print(tunnel_url)
            print("LINK HLS:")
            print(f"{tunnel_url}/live.m3u8")
            print("=" * 70)

        start_chromium()

        time.sleep(3)

        check_x11()

        fullscreen_chromium()

        # Pequeno tempo para o Chromium estabilizar.
        time.sleep(3)

        start_ffmpeg()

        if not wait_hls():
            raise RuntimeError(
                "HLS não iniciou corretamente."
            )

        print("=" * 70)
        print("TRANSMISSÃO ATIVA")
        print("=" * 70)

        if tunnel_url:
            print(f"LINK PRINCIPAL: {tunnel_url}")
            print(
                f"LINK HLS: {tunnel_url}/live.m3u8"
            )

        print("=" * 70)

        # Monitora o túnel.
        monitor = threading.Thread(
            target=tunnel_monitor,
            daemon=True,
        )

        monitor.start()

        # Mantém o programa vivo.
        while True:

            if FFMPEG_PROCESS:
                if FFMPEG_PROCESS.poll() is not None:
                    print(
                        "[ERRO] FFmpeg encerrou."
                    )
                    break

            if CHROMIUM_PROCESS:
                if CHROMIUM_PROCESS.poll() is not None:
                    print(
                        "[AVISO] Chromium encerrou."
                    )
                    break

            time.sleep(5)

    except KeyboardInterrupt:

        print("\n[ENCERRANDO] Ctrl+C recebido.")

    except Exception as e:

        print("\n" + "=" * 70)
        print("[ERRO FATAL]")
        print("=" * 70)
        print(str(e))
        print("=" * 70)

    finally:

        cleanup()


if __name__ == "__main__":
    main()
