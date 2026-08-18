import os
import sys
import time
import signal
import asyncio
import threading
import subprocess

from pyppeteer import launch


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
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n"
    "-102718744012.us-east5.run.app/watch"
)

VIDEO_WAIT_SECONDS = 45

processos = []

browser_global = None
page_global = None
ffmpeg_global = None
tunnel_global = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global browser_global
    global ffmpeg_global

    log("")
    log("=" * 70)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 70)

    try:
        if ffmpeg_global:
            if ffmpeg_global.poll() is None:
                ffmpeg_global.terminate()
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
            "tcp",
            "-dpi",
            "96"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(xvfb)

    time.sleep(2)

    if xvfb.poll() is not None:
        raise RuntimeError("Xvfb não iniciou.")

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
            "--start",
            "--exit-idle-time=-1"
        ],
        check=False
    )

    time.sleep(2)

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
                "Não foi possível criar o sink:\n"
                + resultado.stderr
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

    time.sleep(1)

    sources = subprocess.run(
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
    log(sources.stdout)

    if "webtv.monitor" not in sources.stdout:
        raise RuntimeError(
            "webtv.monitor não foi encontrado."
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
            "--bind",
            "0.0.0.0",
            "--directory",
            STREAM_DIR
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
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

    global tunnel_global

    log("[5] Iniciando túnel localhost.run...")

    tunnel = subprocess.Popen(
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
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1
    )

    tunnel_global = tunnel
    processos.append(tunnel)

    def ler():

        for linha in iter(tunnel.stdout.readline, ""):

            if not linha:
                break

            linha = linha.strip()

            log("[TUNEL]", linha)

            if ".lhr.life" in linha and "https://" in linha:

                partes = linha.split()

                for parte in partes:

                    if parte.startswith("https://") and ".lhr.life" in parte:

                        url = parte.rstrip("/")

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

                        break

    threading.Thread(
        target=ler,
        daemon=True
    ).start()

    # Aguarda o SSH realmente estabelecer
    for _ in range(20):

        if tunnel.poll() is not None:
            raise RuntimeError(
                "localhost.run encerrou."
            )

        time.sleep(1)


# ============================================================
# CAPTURA X11
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

    if resultado.returncode != 0:

        raise RuntimeError(
            "Falha na captura X11:\n"
            + resultado.stderr
        )

    log(
        "[DIAGNÓSTICO] Captura OK:",
        arquivo
    )


# ============================================================
# DIAGNÓSTICO DO PLAYER
# ============================================================

async def diagnosticar(page):

    try:

        return await page.evaluate(
            """
            () => Array.from(
                document.querySelectorAll("video")
            ).map((v, i) => ({
                index: i,
                src: v.src || "",
                currentSrc: v.currentSrc || "",
                paused: v.paused,
                ended: v.ended,
                muted: v.muted,
                readyState: v.readyState,
                networkState: v.networkState,
                currentTime: v.currentTime,
                duration: v.duration,
                width: v.videoWidth,
                height: v.videoHeight,
                error: v.error ? {
                    code: v.error.code,
                    message: v.error.message
                } : null
            }))
            """
        )

    except Exception as erro:

        log("[PLAYER] Erro diagnóstico:", erro)

        return []


# ============================================================
# EVENTOS DO NAVEGADOR
# ============================================================

def configurar_eventos(page):

    def console_handler(msg):

        texto = msg.text

        # Mantém os logs importantes
        if (
            "VIEWER_" in texto
            or
            "contentVideo" in texto
            or
            "Firestore" in texto
            or
            "requestFullscreen" in texto
        ):
            log("[CONSOLE]", texto)

    page.on(
        "console",
        console_handler
    )

    def request_failed(req):

        url = req.url

        # Não polui o log com Firestore
        if "firestore.googleapis.com" in url:
            return

        log(
            "[REQUEST FAILED]",
            url,
            req.failure
        )

    page.on(
        "requestfailed",
        request_failed
    )


# ============================================================
# AGUARDAR PLAYER DO SITE
# ============================================================

async def aguardar_player(page):

    log("")
    log("=" * 70)
    log("[PLAYER] Aguardando o player original do site")
    log("=" * 70)

    inicio = time.time()

    ultimo = None

    while time.time() - inicio < VIDEO_WAIT_SECONDS:

        videos = await diagnosticar(page)

        if videos != ultimo:

            if videos:
                log("[PLAYER]", videos)

            ultimo = videos

        # Importante:
        # não chamamos play()
        # não chamamos load()
        # não alteramos src
        #
        # O próprio site controla a reprodução.

        for video in videos:

            if (
                video.get("readyState", 0) >= 2
                and
                video.get("width", 0) > 0
                and
                video.get("height", 0) > 0
            ):

                log("")
                log(
                    "[PLAYER] Vídeo reproduzível detectado."
                )

                return True

        await asyncio.sleep(2)

    log("")
    log(
        "[AVISO] O site não confirmou reprodução."
    )

    return False


# ============================================================
# FULLSCREEN DO CHROMIUM
# ============================================================

def fullscreen_chromium():

    log("")
    log("=" * 70)
    log("[TELA] Ativando tela cheia do Chromium")
    log("=" * 70)

    # Aqui está a mecânica diferente.
    #
    # NÃO usamos:
    # document.requestFullscreen()
    #
    # porque isso exige user gesture.
    #
    # Usamos F11 no próprio Chromium.

    resultado = subprocess.run(
        [
            "xdotool",
            "key",
            "--clearmodifiers",
            "F11"
        ],
        env={
            **os.environ,
            "DISPLAY": DISPLAY
        },
        capture_output=True,
        text=True
    )

    if resultado.returncode != 0:

        log(
            "[TELA] F11 falhou:",
            resultado.stderr
        )

        return False

    time.sleep(3)

    log(
        "[TELA] Chromium em tela cheia."
    )

    return True


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

        handleSIGINT=False,
        handleSIGTERM=False,
        handleSIGHUP=False,

        args=[

            "--no-sandbox",

            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",

            "--ozone-platform=x11",

            # NÃO desabilitar GPU/media agressivamente.
            #
            # O Chromium precisa conseguir decodificar
            # o vídeo normalmente.

            "--autoplay-policy=no-user-gesture-required",

            "--window-size=1280,720",

            "--window-position=0,0",

            "--force-device-scale-factor=1",

            "--no-first-run",

            "--no-default-browser-check",

            "--disable-background-networking",

            "--disable-background-timer-throttling",

            "--disable-backgrounding-occluded-windows",

            "--disable-renderer-backgrounding",

            "--disable-popup-blocking",

            "--disable-notifications",

            "--disable-infobars",

            "--disable-session-crashed-bubble",

            # Permite mídia em ambiente automatizado
            "--use-fake-ui-for-media-stream",

            "--disable-features=Translate,MediaRouter"
        ]
    )

    browser_global = browser

    log("Chromium iniciado.")

    page = await browser.newPage()

    page_global = page

    configurar_eventos(page)

    await page.setViewport(
        {
            "width": WIDTH,
            "height": HEIGHT,
            "deviceScaleFactor": 1
        }
    )

    return browser, page


# ============================================================
# FFmpeg
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_global

    log("")
    log("=" * 70)
    log("INICIANDO FFMPEG")
    log("=" * 70)

    comando = [

        "ffmpeg",

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

        # ----------------------------------------------------
        # VIDEO
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
        f"{WIDTH}x{HEIGHT}",

        "-i",
        f"{DISPLAY}.0",

        # ----------------------------------------------------
        # AUDIO
        # ----------------------------------------------------

        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ----------------------------------------------------
        # H264
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

        # Wi-Fi 2.4 GHz
        "-b:v",
        "1500k",

        "-maxrate",
        "1800k",

        "-bufsize",
        "3000k",

        # ----------------------------------------------------
        # AUDIO
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
        os.path.join(
            STREAM_DIR,
            "segment_%05d.ts"
        ),

        os.path.join(
            STREAM_DIR,
            "live.m3u8"
        )
    ]

    log("Comando FFmpeg:")
    log(" ".join(comando))

    ffmpeg = subprocess.Popen(
        comando,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    ffmpeg_global = ffmpeg

    def monitorar():

        for linha in iter(
            ffmpeg.stderr.readline,
            ""
        ):

            if linha:
                log("[FFMPEG]", linha.rstrip())

    threading.Thread(
        target=monitorar,
        daemon=True
    ).start()

    time.sleep(3)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou imediatamente."
        )

    log("FFmpeg funcionando.")


# ============================================================
# AGUARDAR HLS
# ============================================================

def aguardar_hls():

    log("[HLS] Aguardando playlist...")

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    inicio = time.time()

    while time.time() - inicio < 30:

        if os.path.exists(playlist):

            try:

                if os.path.getsize(playlist) > 50:

                    log("[HLS] Playlist pronta.")

                    return True

            except Exception:
                pass

        time.sleep(1)

    return False


# ============================================================
# MONITORAR FFMPEG
# ============================================================

def monitorar_stream():

    while True:

        time.sleep(10)

        if ffmpeg_global is None:
            continue

        if ffmpeg_global.poll() is not None:

            log("")
            log(
                "[ERRO] FFmpeg encerrou!"
            )

            encerrar()

        playlist = os.path.join(
            STREAM_DIR,
            "live.m3u8"
        )

        if not os.path.exists(playlist):

            log(
                "[AVISO] Playlist HLS desapareceu."
            )


# ============================================================
# MAIN
# ============================================================

async def main_async():

    log("=" * 70)
    log("WEBTV STREAM")
    log("=" * 70)

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_tunel()

    testar_tela()

    browser, page = await iniciar_chromium()

    log("")
    log("Abrindo página:")
    log(URL_ALVO)

    try:

        await page.goto(
            URL_ALVO,
            {
                "waitUntil": "domcontentloaded",
                "timeout": 60000
            }
        )

    except Exception as erro:

        log(
            "[AVISO] goto:",
            erro
        )

    log("Página carregada.")

    # Dá tempo para React/Firebase/player
    # inicializarem naturalmente.
    await asyncio.sleep(8)

    # ========================================================
    # NÃO ALTERAMOS O PLAYER
    # ========================================================

    reproduzindo = await aguardar_player(
        page
    )

    if reproduzindo:

        log(
            "[PLAYER] Reprodução confirmada."
        )

    else:

        log(
            "[PLAYER] Site ainda não confirmou vídeo."
        )

    # ========================================================
    # FULLSCREEN PELO SISTEMA
    # ========================================================

    fullscreen_chromium()

    await asyncio.sleep(3)

    # ========================================================
    # FFmpeg
    # ========================================================

    iniciar_ffmpeg()

    if not aguardar_hls():

        raise RuntimeError(
            "HLS não foi criado."
        )

    log("")
    log("=" * 70)
    log("TRANSMISSÃO ATIVA")
    log("=" * 70)

    threading.Thread(
        target=monitorar_stream,
        daemon=True
    ).start()

    # ========================================================
    # MANTÉM O CHROMIUM VIVO
    # ========================================================

    while True:

        if browser.process is not None:

            try:

                if browser.process.poll() is not None:

                    raise RuntimeError(
                        "Chromium encerrou."
                    )

            except Exception:
                pass

        await asyncio.sleep(10)


# ============================================================
# MAIN
# ============================================================

def main():

    try:

        asyncio.run(
            main_async()
        )

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("=" * 70)
        log("ERRO FATAL")
        log("=" * 70)
        log(repr(erro))

        encerrar()


if __name__ == "__main__":
    main()
