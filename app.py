import os
import sys
import time
import signal
import threading
import subprocess

# ============================================================
# CONFIGURAÇÕES
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
browser = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(signum=None, frame=None):
    global ffmpeg_process, browser

    log("")
    log("============================================================")
    log("ENCERRANDO TRANSMISSÃO")
    log("============================================================")

    try:
        if ffmpeg_process and ffmpeg_process.poll() is None:
            ffmpeg_process.terminate()
    except Exception:
        pass

    try:
        if browser:
            browser.close()
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
# LIMPAR STREAM
# ============================================================

def limpar_stream():
    os.makedirs(STREAM_DIR, exist_ok=True)

    for nome in os.listdir(STREAM_DIR):
        caminho = os.path.join(STREAM_DIR, nome)

        try:
            if os.path.isfile(caminho):
                os.remove(caminho)
        except Exception:
            pass

    log("[OK] Pasta stream preparada.")


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("[1/7] Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    xvfb = subprocess.Popen(
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

    processos.append(xvfb)

    time.sleep(3)

    if xvfb.poll() is not None:
        raise RuntimeError("Xvfb não conseguiu iniciar.")

    log("[OK] Tela virtual:", DISPLAY)
    log("[OK] Resolução:", f"{WIDTH}x{HEIGHT}")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("[2/7] Iniciando PulseAudio...")

    pulse_dir = "/tmp/pulse"

    os.makedirs(pulse_dir, exist_ok=True)

    os.environ["PULSE_RUNTIME_PATH"] = pulse_dir
    os.environ["PULSE_SINK"] = "webtv"

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    time.sleep(3)

    info = subprocess.run(
        ["pactl", "info"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if info.returncode != 0:
        raise RuntimeError(
            "PulseAudio não iniciou:\n" + info.stderr
        )

    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if "webtv" not in sinks.stdout:

        log("[AUDIO] Criando saída virtual...")

        criar = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if criar.returncode != 0:
            raise RuntimeError(
                "Não foi possível criar o áudio virtual:\n"
                + criar.stderr
            )

    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        check=False,
    )

    time.sleep(2)

    sources = subprocess.run(
        ["pactl", "list", "short", "sources"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    log("[AUDIO] Fontes disponíveis:")
    log(sources.stdout)

    if "webtv.monitor" not in sources.stdout:
        raise RuntimeError(
            "webtv.monitor não foi encontrado."
        )

    log("[OK] Áudio virtual funcionando.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():

    log("[3/7] Iniciando servidor HLS...")

    servidor = subprocess.Popen(
        [
            "python3",
            "-m",
            "http.server",
            str(HTTP_PORT),
            "--directory",
            STREAM_DIR,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    processos.append(servidor)

    time.sleep(2)

    if servidor.poll() is not None:
        raise RuntimeError(
            "Servidor HTTP não conseguiu iniciar."
        )

    log(
        "[OK] Servidor HTTP:",
        f"http://127.0.0.1:{HTTP_PORT}"
    )


# ============================================================
# TÚNEL PÚBLICO
# ============================================================

def iniciar_tunel():

    log("[4/7] Iniciando túnel público...")

    tunnel = subprocess.Popen(
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
            "nokey@localhost.run",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    processos.append(tunnel)

    def monitorar():

        try:
            for linha in iter(tunnel.stdout.readline, ""):

                linha = linha.strip()

                if not linha:
                    continue

                log("[TUNEL]", linha)

                if "https://" in linha:

                    inicio = linha.find("https://")
                    url = linha[inicio:].split()[0]

                    log("")
                    log("============================================================")
                    log("                 TRANSMISSÃO ONLINE")
                    log("============================================================")
                    log("URL:")
                    log(url)
                    log("")
                    log("PLAYER HLS:")
                    log(url.rstrip("/") + "/live.m3u8")
                    log("============================================================")
                    log("")

        except Exception as erro:
            log("[TUNEL] Monitor:", erro)

    threading.Thread(
        target=monitorar,
        daemon=True,
    ).start()

    time.sleep(5)

    if tunnel.poll() is not None:
        raise RuntimeError(
            "O túnel encerrou antes de fornecer a URL."
        )


# ============================================================
# FFmpeg
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_process

    log("[5/7] Iniciando FFmpeg...")

    audio_input = "webtv.monitor"

    comando = [
        "ffmpeg",
        "-y",

        # ---------------- AUDIO ----------------

        "-f",
        "pulse",

        "-i",
        audio_input,

        # ---------------- VIDEO ----------------

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

        # ---------------- VIDEO CODEC ----------------

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-tune",
        "zerolatency",

        "-profile:v",
        "main",

        "-pix_fmt",
        "yuv420p",

        "-r",
        str(FPS),

        "-g",
        str(FPS * 2),

        "-keyint_min",
        str(FPS * 2),

        # ---------------- AUDIO CODEC ----------------

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        # ---------------- HLS ----------------

        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "6",

        "-hls_flags",
        "delete_segments+independent_segments",

        "-hls_segment_filename",
        os.path.join(
            STREAM_DIR,
            "segment_%05d.ts"
        ),

        os.path.join(
            STREAM_DIR,
            "live.m3u8"
        ),
    ]

    ffmpeg_process = subprocess.Popen(
        comando,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    time.sleep(5)

    if ffmpeg_process.poll() is not None:

        erro = ""

        try:
            erro = ffmpeg_process.stderr.read()
        except Exception:
            pass

        raise RuntimeError(
            "FFmpeg encerrou.\n" + erro[-5000:]
        )

    log("[OK] FFmpeg transmitindo.")
    log(
        "[OK] HLS:",
        os.path.join(STREAM_DIR, "live.m3u8")
    )


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    global browser

    log("[6/7] Iniciando Chromium...")

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()

    browser = pw.chromium.launch(
        headless=False,

        executable_path="/usr/bin/chromium",

        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",

            # X11
            "--ozone-platform=x11",

            # Autoplay
            "--autoplay-policy=no-user-gesture-required",

            # Tela cheia
            "--kiosk",
            "--start-fullscreen",
            "--start-maximized",

            # Janela
            "--window-position=0,0",
            f"--window-size={WIDTH},{HEIGHT}",
            "--force-device-scale-factor=1",

            # Estabilidade
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            "--disable-notifications",

            # Evita economia de recursos
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",

            # NÃO desativamos a decodificação de vídeo.
            # Isso é importante para evitar quebrar reprodução.
        ],
    )

    page = browser.new_page(
        viewport={
            "width": WIDTH,
            "height": HEIGHT,
        },
    )

    # ========================================================
    # LOG DO NAVEGADOR
    # ========================================================

    page.on(
        "console",
        lambda msg: log(
            "[BROWSER]",
            msg.text
        ),
    )

    page.on(
        "pageerror",
        lambda erro: log(
            "[PAGE ERROR]",
            erro
        ),
    )

    # ========================================================
    # ABRIR SITE
    # ========================================================

    log("")
    log("[BROWSER] Abrindo:")
    log(URL_ALVO)

    try:

        page.goto(
            URL_ALVO,
            wait_until="domcontentloaded",
            timeout=60000,
        )

    except Exception as erro:

        log(
            "[BROWSER] Aviso ao abrir:",
            erro
        )

    time.sleep(8)

    # ========================================================
    # GARANTIR TELA CHEIA
    # ========================================================

    try:

        page.keyboard.press("F11")

        log("[BROWSER] F11 enviado.")

    except Exception as erro:

        log(
            "[BROWSER] Não foi possível enviar F11:",
            erro
        )

    time.sleep(3)

    # ========================================================
    #
