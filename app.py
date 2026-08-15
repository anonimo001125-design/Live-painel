import os
import time
import subprocess
import threading
import signal
import sys

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÃO
# ============================================================

TOKEN_NGROK = "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk"

URL_ALVO = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"

WIDTH = 1280
HEIGHT = 720
FPS = 30

DISPLAY = ":99"

STREAM_DIR = "stream"
HTTP_PORT = 8080


# ============================================================
# PROCESSOS
# ============================================================

processos = []


def encerrar(*args):

    print("\nEncerrando...")

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

    sys.exit(0)


signal.signal(signal.SIGINT, encerrar)
signal.signal(signal.SIGTERM, encerrar)


# ============================================================
# LIMPAR STREAM
# ============================================================

def limpar_stream():

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    for arquivo in os.listdir(STREAM_DIR):

        caminho = os.path.join(
            STREAM_DIR,
            arquivo
        )

        try:

            if os.path.isfile(caminho):
                os.remove(caminho)

        except Exception:
            pass


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    print("[1] Iniciando Xvfb...")

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
            "tcp"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(xvfb)

    time.sleep(3)

    if xvfb.poll() is not None:

        raise RuntimeError(
            "Xvfb não iniciou."
        )

    print(
        f"[X11] DISPLAY={DISPLAY}"
    )

    print(
        f"[X11] Tela={WIDTH}x{HEIGHT}"
    )


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    print("[2] Iniciando PulseAudio...")

    os.makedirs(
        "/tmp/pulse",
        exist_ok=True
    )

    os.environ["PULSE_RUNTIME_PATH"] = "/tmp/pulse"

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        check=False
    )

    time.sleep(3)

    # --------------------------------------------------------
    # Cria sink virtual
    # --------------------------------------------------------

    sinks = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sinks"
        ],
        capture_output=True,
        text=True
    )

    if "webtv" not in sinks.stdout:

        print(
            "[AUDIO] Criando sink webtv..."
        )

        subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV"
            ],
            check=False
        )

    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        check=False
    )

    os.environ["PULSE_SINK"] = "webtv"

    time.sleep(2)

    fontes = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ],
        capture_output=True,
        text=True
    )

    print(
        fontes.stdout
    )

    if "webtv.monitor" not in fontes.stdout:

        raise RuntimeError(
            "webtv.monitor não foi criado."
        )

    print(
        "[AUDIO] PulseAudio pronto."
    )


# ============================================================
# SERVIDOR
# ============================================================

def iniciar_servidor():

    print("[3] Iniciando servidor HTTP...")

    servidor = subprocess.Popen(
        [
            "python3",
            "-m",
            "http.server",
            str(HTTP_PORT),
            "--directory",
            STREAM_DIR
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(servidor)

    time.sleep(2)

    print(
        f"[HTTP] Porta {HTTP_PORT}"
    )


# ============================================================
# NGROK
# ============================================================

def iniciar_ngrok():

    print("[4] Iniciando túnel NGROK...")

    from pyngrok import ngrok

    ngrok.set_auth_token(
        TOKEN_NGROK
    )

    url_publica = ngrok.connect(
        HTTP_PORT
    ).public_url

    print("")
    print(
        "=========================================================="
    )
    print(
        "              WEB TV ONLINE"
    )
    print(
        "=========================================================="
    )
    print(
        "URL pública:"
    )
    print(
        url_publica
    )
    print("")
    print(
        "HLS:"
    )
    print(
        url_publica.rstrip("/") +
        "/live.m3u8"
    )
    print(
        "=========================================================="
    )
    print("")


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    print("[5] Iniciando FFmpeg...")

    comando = [

        "ffmpeg",

        "-y",

        # ----------------------------------------------------
        # VÍDEO
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # ÁUDIO
        # ----------------------------------------------------

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ----------------------------------------------------
        # VÍDEO
        # ----------------------------------------------------

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
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        # ----------------------------------------------------
        # ÁUDIO
        # ----------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        "-ac",
        "2",

        # ----------------------------------------------------
        # HLS
        # ----------------------------------------------------

        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "5",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        f"{STREAM_DIR}/segment_%05d.ts",

        f"{STREAM_DIR}/live.m3u8"
    ]

    print(
        " ".join(comando)
    )

    ffmpeg = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(ffmpeg)

    def acompanhar():

        for linha in iter(
            ffmpeg.stdout.readline,
            ""
        ):

            if linha:
                print(
                    "[FFMPEG]",
                    linha.strip(),
                    flush=True
                )

    threading.Thread(
        target=acompanhar,
        daemon=True
    ).start()

    time.sleep(5)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    print(
        "[FFMPEG] Transmissão iniciada."
    )


# ============================================================
# PLAYWRIGHT
# ============================================================

def iniciar_navegador():

    print("[6] Iniciando Chromium...")

    with sync_playwright() as p:

        # ----------------------------------------------------
        # IMPORTANTE:
        #
        # NÃO usamos headless.
        #
        # O navegador será desenhado no Xvfb.
        #
        # E NÃO desativamos GPU/video decode.
        # ----------------------------------------------------

        browser = p.chromium.launch(

            headless=False,

            executable_path="/usr/bin/chromium",

            args=[

                "--no-sandbox",

                "--disable-dev-shm-usage",

                "--disable-setuid-sandbox",

                "--autoplay-policy=no-user-gesture-required",

                "--window-size=1280,720",

                "--window-position=0,0",

                "--force-device-scale-factor=1",

                "--start-maximized",

                "--no-first-run",

                "--no-default-browser-check",

                "--disable-notifications",

                "--disable-popup-blocking"
            ]
        )

        page = browser.new_page(
            viewport={
                "width": WIDTH,
                "height": HEIGHT
            }
        )

        # ----------------------------------------------------
        # MONITORAMENTO
        # ----------------------------------------------------

        page.on(
            "console",
            lambda msg:
                print(
                    "[BROWSER]",
                    msg.text
                )
        )

        page.on(
            "pageerror",
            lambda error:
                print(
                    "[BROWSER ERROR]",
                    error
                )
        )

        page.on(
            "requestfailed",
            lambda request:
                print(
                    "[REQUEST FAILED]",
                    request.url,
                    request.failure
                )
        )

        # ----------------------------------------------------
        # ABRIR SITE
        # ----------------------------------------------------

        print(
            "[CHROMIUM] Abrindo:",
            URL_ALVO
        )

        try:

            page.goto(
                URL_ALVO,
                wait_until="domcontentloaded",
                timeout=120000
            )

        except Exception as erro:

            print(
                "[CHROMIUM] Erro no carregamento:",
                erro
            )

        print(
            "[CHROMIUM] Página carregada."
        )

        time.sleep(10)

        # ----------------------------------------------------
        # FULLSCREEN DA JANELA
        # ----------------------------------------------------

        try:

            page.evaluate(
                """
                () => {
                    document.documentElement.style.width = '100vw';
                    document.documentElement.style.height = '100vh';
                    document.body.style.margin = '0';
                    document.body.style.width = '100vw';
                    document.body.style.height = '100vh';
                    document.body.style.overflow = 'hidden';
                }
                """
            )

        except Exception:
            pass

        # ----------------------------------------------------
        # NÃO FORÇAMOS video.play()
        #
        # O player da própria página controla o vídeo.
        # ----------------------------------------------------

        print(
            "[CHROMIUM] Aguardando o player..."
        )

        time.sleep(10)

        # ----------------------------------------------------
        # DIAGNÓSTICO
        # ----------------------------------------------------

        try:

            videos = page.evaluate(
                """
                () => Array.from(
                    document.querySelectorAll('video')
                ).map((v, i) => ({

                    index: i,

                    src: v.src || '',

                    currentSrc:
                        v.currentSrc || '',

                    paused:
                        v.paused,

                    readyState:
                        v.readyState,

                    networkState:
                        v.networkState,

                    currentTime:
                        v.currentTime,

                    duration:
                        v.duration,

                    videoWidth:
                        v.videoWidth,

                    videoHeight:
                        v.videoHeight,

                    muted:
                        v.muted,

                    error:
                        v.error
                            ? {
                                code: v.error.code,
                                message: v.error.message
                            }
                            : null

                }))
                """
            )

            print("")
            print(
                "=========================================================="
            )
            print(
                "DIAGNÓSTICO DO PLAYER"
            )
            print(
                "=========================================================="
            )

            for video in videos:

                print(
                    video
                )

            print(
                "=========================================================="
            )
            print("")

        except Exception as erro:

            print(
                "[DIAGNÓSTICO] Erro:",
                erro
            )

        # ----------------------------------------------------
        # SCREENSHOT
        # ----------------------------------------------------

        try:

            page.screenshot(
                path=os.path.join(
                    STREAM_DIR,
                    "browser_debug.png"
                ),
                full_page=False
            )

            print(
                "[CHROMIUM] Screenshot salvo."
            )

        except Exception as erro:

            print(
                "[CHROMIUM] Erro screenshot:",
                erro
            )

        # ----------------------------------------------------
        # MANTÉM NAVEGADOR ABERTO
        # ----------------------------------------------------

        while True:

            time.sleep(30)

            try:

                print(
                    "[CHROMIUM] Página ativa:",
                    page.title()
                )

            except Exception:
                pass


# ============================================================
# MAIN
# ============================================================

def iniciar():

    print("")
    print(
        "=========================================================="
    )
    print(
        "                  WEB TV STREAM"
    )
    print(
        "=========================================================="
    )
    print("")

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_ngrok()

    # --------------------------------------------------------
    # Chromium primeiro
    # --------------------------------------------------------

    navegador = threading.Thread(
        target=iniciar_navegador,
        daemon=True
    )

    navegador.start()

    # --------------------------------------------------------
    # Aguarda navegador
    # --------------------------------------------------------

    print(
        "[MAIN] Aguardando navegador..."
    )

    time.sleep(25)

    # --------------------------------------------------------
    # FFmpeg
    # --------------------------------------------------------

    iniciar_ffmpeg()

    print("")
    print(
        "=========================================================="
    )
    print(
        "              TRANSMISSÃO ATIVA"
    )
    print(
        "=========================================================="
    )
    print("")

    # --------------------------------------------------------
    # Mantém processo
    # --------------------------------------------------------

    while True:

        time.sleep(30)


if __name__ == "__main__":

    iniciar()
