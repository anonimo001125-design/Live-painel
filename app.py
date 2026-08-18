import os
import time
import subprocess
import signal
import sys

from playwright.sync_api import sync_playwright


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


ffmpeg = None
xvfb = None
http = None
pulse = None
browser = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAR
# ============================================================

def encerrar(*args):

    global ffmpeg, xvfb, http, pulse, browser

    log("")
    log("==========================================================")
    log("ENCERRANDO")
    log("==========================================================")

    try:
        if browser:
            browser.close()
    except Exception:
        pass

    for processo in [ffmpeg, http, pulse, xvfb]:

        try:

            if processo and processo.poll() is None:
                processo.terminate()

        except Exception:
            pass

    time.sleep(2)

    for processo in [ffmpeg, http, pulse, xvfb]:

        try:

            if processo and processo.poll() is None:
                processo.kill()

        except Exception:
            pass

    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


# ============================================================
# LIMPAR STREAM
# ============================================================

def limpar_stream():

    os.makedirs(STREAM_DIR, exist_ok=True)

    for nome in os.listdir(STREAM_DIR):

        caminho = os.path.join(
            STREAM_DIR,
            nome
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

    global xvfb

    log("[1] Iniciando Xvfb...")

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

    time.sleep(3)

    if xvfb.poll() is not None:
        raise RuntimeError("Xvfb nao iniciou.")

    log("Xvfb iniciado.")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    global pulse

    log("[2] Iniciando PulseAudio...")

    os.environ["DISPLAY"] = DISPLAY

    pulse = subprocess.Popen(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    time.sleep(3)

    teste = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True
    )

    if teste.returncode != 0:
        raise RuntimeError("PulseAudio nao iniciou.")

    # Tenta criar o sink.
    resultado = subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            "sink_name=webtv",
            "sink_properties=device.description=WebTV"
        ],
        capture_output=True,
        text=True
    )

    if resultado.returncode != 0:
        log("Sink webtv provavelmente ja existe.")

    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        check=False
    )

    os.environ["PULSE_SINK"] = "webtv"

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

    if "webtv.monitor" not in fontes.stdout:
        raise RuntimeError(
            "webtv.monitor nao foi encontrado."
        )

    log("Audio WebTV pronto.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_http():

    global http

    log("[3] Iniciando servidor HTTP...")

    http = subprocess.Popen(
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

    time.sleep(2)

    log(
        f"Servidor HTTP: porta {HTTP_PORT}"
    )


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg

    log("[4] Iniciando FFmpeg...")

    comando = [

        "ffmpeg",

        "-y",

        # VIDEO
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

        # AUDIO
        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # VIDEO
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

        # AUDIO
        "-c:a",
        "aac",

        "-b:a",
        "128k",

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
        "delete_segments+append_list",

        "-hls_segment_filename",
        os.path.join(
            STREAM_DIR,
            "segment_%05d.ts"
        ),

        os.path.join(
            STREAM_DIR,
            "live.m3u8"
        )
    ]

    ffmpeg = subprocess.Popen(
        comando
    )

    time.sleep(3)

    if ffmpeg.poll() is not None:
        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log("FFmpeg transmitindo.")


# ============================================================
# TUNEL SERVEO
# ============================================================

def iniciar_tunel():

    log("[5] Iniciando link publico...")

    processo = subprocess.Popen(
        [
            "ssh",

            "-o",
            "StrictHostKeyChecking=no",

            "-o",
            "ServerAliveInterval=30",

            "-o",
            "ServerAliveCountMax=3",

            "-R",
            f"80:localhost:{HTTP_PORT}",

            "serveo.net"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    inicio = time.time()

    while time.time() - inicio < 30:

        linha = processo.stdout.readline()

        if not linha:
            continue

        linha = linha.strip()

        log(
            "[TUNEL]",
            linha
        )

        if "https://" in linha:

            posicao = linha.find("https://")

            url = linha[posicao:].split()[0]

            log("")
            log("==========================================================")
            log("TRANSMISSAO AO VIVO")
            log("==========================================================")
            log("")
            log("LINK:")
            log(url)
            log("")
            log("LINK HLS:")
            log(url.rstrip("/") + "/live.m3u8")
            log("")
            log("==========================================================")
            log("")

            return processo

    log(
        "AVISO: o tunel nao retornou o endereco automaticamente."
    )

    return processo


# ============================================================
# DIAGNOSTICO DO VIDEO
# ============================================================

def diagnosticar(page):

    try:

        dados = page.evaluate(
            """
            () => [...document.querySelectorAll("video")]
                .map((video, index) => ({

                    index: index,

                    src: video.src || "",

                    currentSrc:
                        video.currentSrc || "",

                    paused:
                        video.paused,

                    muted:
                        video.muted,

                    readyState:
                        video.readyState,

                    networkState:
                        video.networkState,

                    currentTime:
                        video.currentTime,

                    width:
                        video.videoWidth,

                    height:
                        video.videoHeight,

                    error:
                        video.error
                        ? {
                            code: video.error.code,
                            message: video.error.message
                        }
                        : null
                }))
            """
        )

        log("")
        log("========== VIDEO ==========")
        log(dados)
        log("============================")
        log("")

        return dados

    except Exception as erro:

        log(
            "[VIDEO] Erro:",
            erro
        )

        return []


# ============================================================
# REPRODUÇÃO
# ============================================================

def reproduzir(page):

    try:

        resultado = page.evaluate(
            """
            async () => {

                const videos =
                    [...document.querySelectorAll("video")];

                const retorno = [];

                for (const video of videos) {

                    video.autoplay = true;
                    video.playsInline = true;

                    try {

                        const promessa = video.play();

                        if (promessa) {
                            await promessa;
                        }

                        retorno.push({
                            sucesso: true,
                            paused: video.paused,
                            readyState: video.readyState,
                            width: video.videoWidth,
                            height: video.videoHeight,
                            currentTime: video.currentTime
                        });

                    } catch (erro) {

                        retorno.push({
                            sucesso: false,
                            erro: String(erro),
                            paused: video.paused,
                            readyState: video.readyState,
                            width: video.videoWidth,
                            height: video.videoHeight
                        });
                    }
                }

                return retorno;
            }
            """
        )

        log(
            "[PLAYER]",
            resultado
        )

    except Exception as erro:

        log(
            "[PLAYER] Erro:",
            erro
        )


# ============================================================
# CHROMIUM
# ============================================================

def iniciar_navegador():

    global browser

    log("[6] Iniciando Chromium...")

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=False,

            args=[

                "--no-sandbox",

                "--disable-dev-shm-usage",

                "--autoplay-policy=no-user-gesture-required",

                "--kiosk",

                "--no-first-run",

                "--no-default-browser-check",

                "--start-fullscreen",

                "--start-maximized",

                "--window-size=1280,720",

                "--window-position=0,0",

                "--force-device-scale-factor=1"
            ]
        )

        page = browser.new_page(
            viewport={
                "width": WIDTH,
                "height": HEIGHT
            }
        )

        # ----------------------------------------------------
        # ERROS DA PAGINA
        # ----------------------------------------------------

        page.on(
            "console",
            lambda msg:
            log(
                "[CONSOLE]",
                msg.text
            )
        )

        page.on(
            "pageerror",
            lambda erro:
            log(
                "[PAGE ERROR]",
                erro
            )
        )

        page.on(
            "requestfailed",
            lambda request:
            log(
                "[REQUEST FAILED]",
                request.url,
                request.failure
            )
        )

        # ----------------------------------------------------
        # CARREGAR PAGINA
        # ----------------------------------------------------

        log(
            "Abrindo:",
            URL_ALVO
        )

        try:

            page.goto(
                URL_ALVO,
                wait_until="commit",
                timeout=0
            )

        except Exception as erro:

            log(
                "[GOTO]",
                erro
            )

        log(
            "Aguardando pagina..."
        )

        time.sleep(10)

        try:

            log(
                "Titulo:",
                page.title()
            )

        except Exception:
            pass

        # ----------------------------------------------------
        # TENTAR VIDEO
        # ----------------------------------------------------

        diagnosticar(page)

        reproduzir(page)

        # ----------------------------------------------------
        # CLIQUE REAL NO PLAYER
        # ----------------------------------------------------

        try:

            page.mouse.click(
                WIDTH // 2,
                HEIGHT // 2
            )

            time.sleep(2)

            reproduzir(page)

        except Exception as erro:

            log(
                "[CLICK]",
                erro
            )

        # ----------------------------------------------------
        # FULLSCREEN
        # ----------------------------------------------------

        try:

            page.evaluate(
                """
                () => {

                    const elemento =
                        document.documentElement;

                    if (
                        elemento.requestFullscreen &&
                        !document.fullscreenElement
                    ) {

                        elemento.requestFullscreen()
                            .catch(() => {});
                    }
                }
                """
            )

        except Exception:
            pass

        # ----------------------------------------------------
        # MONITOR
        # ----------------------------------------------------

        log("")
        log(
            "=========================================================="
        )
        log(
            "NAVEGADOR ATIVO"
        )
        log(
            "=========================================================="
        )

        ultimo_diagnostico = 0

        while True:

            time.sleep(5)

            try:

                agora = time.time()

                if agora - ultimo_diagnostico >= 15:

                    dados = diagnosticar(page)

                    ultimo_diagnostico = agora

                    # Se existe vídeo, mas está pausado,
                    # tenta novamente.
                    for video in dados:

                        if (
                            video.get("paused")
                            and
                            video.get("width", 0) > 0
                        ):

                            reproduzir(page)

            except Exception as erro:

                log(
                    "[MONITOR]",
                    erro
                )

                # Não encerramos imediatamente.
                # Dá tempo para o player se recuperar.
                time.sleep(2)


# ============================================================
# MAIN
# ============================================================

def iniciar():

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_http()

    iniciar_ffmpeg()

    # Dá tempo para o HLS começar.
    time.sleep(4)

    iniciar_tunel()

    iniciar_navegador()


if __name__ == "__main__":

    iniciar()
