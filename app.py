import os
import sys
import time
import signal
import asyncio
import threading
import subprocess

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

browser_global = None
page_global = None
ffmpeg_global = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global ffmpeg_global
    global browser_global

    log("")
    log("=" * 70)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 70)

    try:
        if ffmpeg_global:
            if ffmpeg_global.poll() is None:
                ffmpeg_global.terminate()
                ffmpeg_global.wait(timeout=5)
    except Exception:
        try:
            ffmpeg_global.kill()
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
# LIMPAR STREAM
# ============================================================

def limpar_stream():

    os.makedirs(STREAM_DIR, exist_ok=True)

    log("[1] Limpando stream antigo...")

    for nome in os.listdir(STREAM_DIR):

        caminho = os.path.join(STREAM_DIR, nome)

        try:
            if os.path.isfile(caminho):
                os.remove(caminho)
        except Exception as erro:
            log("[AVISO]", caminho, erro)


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("[2] Iniciando Xvfb...")

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
        stderr=subprocess.DEVNULL
    )

    processos.append(xvfb)

    time.sleep(3)

    if xvfb.poll() is not None:
        raise RuntimeError("Xvfb encerrou.")

    log("DISPLAY:", DISPLAY)
    log("RESOLUÇÃO:", f"{WIDTH}x{HEIGHT}")
    log("Xvfb pronto.")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("[3] Iniciando PulseAudio...")

    runtime = "/tmp/pulse"

    os.makedirs(runtime, exist_ok=True)

    os.environ["PULSE_RUNTIME_PATH"] = runtime

    subprocess.run(
        [
            "pulseaudio",
            "--kill"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

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

    info = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True
    )

    if info.returncode != 0:
        raise RuntimeError(
            "PulseAudio não iniciou."
        )

    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        capture_output=True,
        text=True
    )

    if "webtv" not in sinks.stdout:

        log("Criando sink virtual webtv...")

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
            raise RuntimeError(
                "Falha criando sink:\n" +
                resultado.stderr
            )

    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        check=False
    )

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

    log("Fontes de áudio:")
    log(fontes.stdout)

    if "webtv.monitor" not in fontes.stdout:
        raise RuntimeError(
            "webtv.monitor não encontrado."
        )

    log("Áudio pronto.")


# ============================================================
# HTTP
# ============================================================

def iniciar_servidor():

    log("[4] Iniciando servidor HTTP...")

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
        stderr=subprocess.DEVNULL
    )

    processos.append(servidor)

    time.sleep(2)

    if servidor.poll() is not None:
        raise RuntimeError(
            "Servidor HTTP encerrou."
        )

    log(
        "Servidor HTTP ativo na porta",
        HTTP_PORT
    )


# ============================================================
# TÚNEL
# ============================================================

def iniciar_tunel():

    log("[5] Iniciando túnel localhost.run...")

    tunel = subprocess.Popen(
        [
            "ssh",

            "-o",
            "StrictHostKeyChecking=no",

            "-o",
            "ServerAliveInterval=15",

            "-o",
            "ServerAliveCountMax=6",

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

    processos.append(tunel)

    def ler():

        for linha in iter(
            tunel.stdout.readline,
            ""
        ):

            if not linha:
                continue

            linha = linha.strip()

            log("[TUNEL]", linha)

            if (
                "https://" in linha
                and ".lhr.life" in linha
            ):

                inicio = linha.find("https://")

                url = (
                    linha[inicio:]
                    .split()[0]
                    .rstrip("/")
                )

                log("")
                log("=" * 70)
                log("LINK DA TRANSMISSÃO")
                log("=" * 70)
                log("LINK PRINCIPAL:")
                log(url)
                log("")
                log("LINK HLS:")
                log(url + "/live.m3u8")
                log("=" * 70)
                log("")

    threading.Thread(
        target=ler,
        daemon=True
    ).start()

    time.sleep(6)

    if tunel.poll() is not None:
        raise RuntimeError(
            "Túnel encerrou."
        )


# ============================================================
# TESTE X11
# ============================================================

def testar_tela():

    log("[DIAGNÓSTICO] Testando X11...")

    arquivo = os.path.join(
        STREAM_DIR,
        "debug_screen.png"
    )

    resultado = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",

            "-f",
            "x11grab",

            "-video_size",
            f"{WIDTH}x{HEIGHT}",

            "-framerate",
            "1",

            "-i",
            f"{DISPLAY}.0",

            "-frames:v",
            "1",

            arquivo
        ],
        capture_output=True,
        text=True
    )

    if resultado.returncode == 0:

        log(
            "[DIAGNÓSTICO] Captura OK:",
            arquivo
        )

    else:

        log(
            "[DIAGNÓSTICO] Falha:",
            resultado.stderr
        )


# ============================================================
# CHROMIUM
# ============================================================

async def iniciar_chromium():

    global browser_global
    global page_global

    log("[6] Iniciando Chromium...")

    ambiente = os.environ.copy()

    ambiente["DISPLAY"] = DISPLAY
    ambiente["PULSE_SINK"] = "webtv"

    browser = await launch(

        headless=False,

        executablePath="/usr/bin/chromium",

        env=ambiente,

        ignoreDefaultArgs=[
            "--enable-automation"
        ],

        handleSIGINT=False,
        handleSIGTERM=False,
        handleSIGHUP=False,

        args=[

            "--no-sandbox",

            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",

            "--ozone-platform=x11",

            # Renderização estável para Xvfb
            "--use-gl=swiftshader",

            "--disable-gpu",

            "--disable-gpu-compositing",

            "--disable-gpu-rasterization",

            "--disable-accelerated-video-decode",

            "--disable-accelerated-video-encode",

            # Autoplay permitido
            "--autoplay-policy=no-user-gesture-required",

            # Janela
            f"--window-size={WIDTH},{HEIGHT}",

            "--window-position=0,0",

            "--force-device-scale-factor=1",

            # Estabilidade
            "--no-first-run",

            "--no-default-browser-check",

            "--disable-background-networking",

            "--disable-background-timer-throttling",

            "--disable-backgrounding-occluded-windows",

            "--disable-renderer-backgrounding",

            "--disable-popup-blocking",

            "--disable-notifications"
        ]
    )

    browser_global = browser

    log("Chromium iniciado.")

    page = await browser.newPage()

    page_global = page

    await page.setViewport(
        {
            "width": WIDTH,
            "height": HEIGHT,
            "deviceScaleFactor": 1
        }
    )

    # --------------------------------------------------------
    # CONSOLE
    # --------------------------------------------------------

    page.on(
        "console",
        lambda mensagem:
            log(
                "[CONSOLE]",
                mensagem.text
            )
    )

    # --------------------------------------------------------
    # REQUEST FAILED
    # --------------------------------------------------------

    def request_failed(request):

        url = request.url

        # Firestore pode falhar sem impedir
        # necessariamente a renderização.
        if "firestore.googleapis.com" in url:

            log(
                "[FIRESTORE] Requisição falhou."
            )

        elif (
            ".mp4" in url
            or ".m3u8" in url
            or ".ts" in url
        ):

            log(
                "[MEDIA FAILED]",
                url
            )

    page.on(
        "requestfailed",
        request_failed
    )

    # --------------------------------------------------------
    # ABRIR SITE
    # --------------------------------------------------------

    log("Abrindo página:")
    log(URL_ALVO)

    try:

        await page.goto(
            URL_ALVO,
            {
                "waitUntil": "domcontentloaded",
                "timeout": 90000
            }
        )

    except Exception as erro:

        log(
            "[AVISO] goto:",
            erro
        )

    log("Aguardando página...")

    await asyncio.sleep(8)

    return page


# ============================================================
# ESTADO DO PLAYER
# ============================================================

async def estado_videos(page):

    try:

        resultado = await page.evaluate(
            """
            () => {

                return [...document.querySelectorAll("video")]
                    .map((video, index) => ({

                        index,

                        src:
                            video.currentSrc ||
                            video.src ||
                            "",

                        paused:
                            video.paused,

                        ended:
                            video.ended,

                        muted:
                            video.muted,

                        readyState:
                            video.readyState,

                        networkState:
                            video.networkState,

                        currentTime:
                            video.currentTime,

                        duration:
                            Number.isFinite(video.duration)
                                ? video.duration
                                : null,

                        width:
                            video.videoWidth,

                        height:
                            video.videoHeight,

                        error:
                            video.error
                                ? {
                                    code:
                                        video.error.code,

                                    message:
                                        video.error.message || ""
                                }
                                : null
                    }));
            }
            """
        )

        return resultado

    except Exception as erro:

        log(
            "[PLAYER] Erro diagnóstico:",
            erro
        )

        return []


# ============================================================
# ESPERAR PLAYER ORIGINAL
# ============================================================

async def esperar_player(page):

    log("")
    log("=" * 70)
    log("[PLAYER] Aguardando reprodução do site...")
    log("=" * 70)

    ultimo_tempo = None

    for tentativa in range(1, 31):

        await asyncio.sleep(2)

        videos = await estado_videos(page)

        log(
            f"[PLAYER] Tentativa {tentativa}/30:",
            videos
        )

        for video in videos:

            ready = video.get(
                "readyState",
                0
            )

            width = video.get(
                "width",
                0
            )

            height = video.get(
                "height",
                0
            )

            tempo = video.get(
                "currentTime",
                0
            )

            paused = video.get(
                "paused",
                True
            )

            # ------------------------------------------------
            # REPRODUÇÃO REAL
            #
            # Não chamamos play().
            # Não chamamos load().
            # Não alteramos src.
            # ------------------------------------------------

            if (
                ready >= 3
                and
                width > 0
                and
                height > 0
                and
                not paused
            ):

                if (
                    ultimo_tempo is not None
                    and
                    tempo > ultimo_tempo
                ):

                    log("")
                    log("=" * 70)
                    log("[PLAYER] REPRODUÇÃO CONFIRMADA")
                    log("=" * 70)

                    return True

                ultimo_tempo = tempo

    log("")
    log(
        "[AVISO] O player não confirmou reprodução."
    )

    return False


# ============================================================
# FULLSCREEN
# ============================================================

def entrar_tela_cheia():

    log("")
    log("=" * 70)
    log("[TELA] Ativando tela cheia do Chromium")
    log("=" * 70)

    # Ativa a janela Chromium.
    subprocess.run(
        [
            "xdotool",
            "search",
            "--onlyvisible",
            "--class",
            "chromium",
            "windowactivate",
            "--sync"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    time.sleep(1)

    # Tela cheia REAL da janela.
    # Não usa requestFullscreen().
    subprocess.run(
        [
            "xdotool",
            "key",
            "--clearmodifiers",
            "F11"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    time.sleep(4)

    log("[TELA] F11 enviado ao Chromium.")
    log("[TELA] Tela preparada para captura.")


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_global

    log("")
    log("=" * 70)
    log("INICIANDO FFMPEG")
    log("=" * 70)

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    segmento = os.path.join(
        STREAM_DIR,
        "segment_%05d.ts"
    )

    comando = [

        "ffmpeg",

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

        # ----------------------------------------------------
        # CAPTURA DA TELA
        # ----------------------------------------------------

        "-thread_queue_size",
        "4096",

        "-f",
        "x11grab",

        "-draw_mouse",
        "0",

        "-framerate",
        "30",

        "-video_size",
        "1280x720",

        "-i",
        ":99.0",

        # ----------------------------------------------------
        # ÁUDIO
        # ----------------------------------------------------

        "-thread_queue_size",
        "4096",

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

        "-pix_fmt",
        "yuv420p",

        "-r",
        "30",

        "-g",
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        # Mais leve para Wi-Fi 2.4 GHz.
        "-b:v",
        "1600k",

        "-maxrate",
        "1800k",

        "-bufsize",
        "3600k",

        # ----------------------------------------------------
        # ÁUDIO
        # ----------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        "96k",

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
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        segmento,

        playlist
    ]

    log(
        "Comando FFmpeg:"
    )

    log(
        " ".join(comando)
    )

    ffmpeg = subprocess.Popen(
        comando,

        stdout=subprocess.DEVNULL,

        stderr=subprocess.PIPE,

        text=True,

        bufsize=1
    )

    ffmpeg_global = ffmpeg

    processos.append(ffmpeg)

    def ler():

        for linha in iter(
            ffmpeg.stderr.readline,
            ""
        ):

            if linha:
                log(
                    "[FFMPEG]",
                    linha.strip()
                )

    threading.Thread(
        target=ler,
        daemon=True
    ).start()

    time.sleep(5)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log("=" * 70)
    log("TRANSMISSÃO ATIVA")
    log("=" * 70)


# ============================================================
# HLS
# ============================================================

def esperar_hls():

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    log("[HLS] Aguardando playlist...")

    for tentativa in range(30):

        if os.path.exists(playlist):

            try:

                if os.path.getsize(playlist) > 100:

                    log(
                        "[HLS] Playlist pronta."
                    )

                    return True

            except Exception:
                pass

        time.sleep(1)

    raise RuntimeError(
        "Playlist HLS não foi criada."
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    log("=" * 70)
    log("WEBTV STREAM")
    log("=" * 70)

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_tunel()

    testar_tela()

    page = await iniciar_chromium()

    # --------------------------------------------------------
    # DEIXA O SITE CONTROLAR O PLAYER
    # --------------------------------------------------------

    reproduzindo = await esperar_player(page)

    if not reproduzindo:

        log(
            "[AVISO] O player não confirmou estado."
        )

        log(
            "[AVISO] Mantendo a página aberta."
        )

        # Não forçamos play.
        # Damos tempo para o próprio site resolver
        # sua sincronização/transição.
        await asyncio.sleep(8)

    # --------------------------------------------------------
    # TELA CHEIA
    # --------------------------------------------------------

    entrar_tela_cheia()

    await asyncio.sleep(3)

    # --------------------------------------------------------
    # CAPTURA
    # --------------------------------------------------------

    iniciar_ffmpeg()

    esperar_hls()

    log("")
    log("=" * 70)
    log("STREAM RODANDO")
    log("=" * 70)

    # --------------------------------------------------------
    # MANTER VIVO
    # --------------------------------------------------------

    while True:

        await asyncio.sleep(15)

        if (
            ffmpeg_global
            and
            ffmpeg_global.poll() is not None
        ):

            raise RuntimeError(
                "FFmpeg encerrou durante a transmissão."
            )


# ============================================================
# EXECUTAR
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("=" * 70)
        log("ERRO FATAL")
        log("=" * 70)
        log(repr(erro))

        encerrar()
