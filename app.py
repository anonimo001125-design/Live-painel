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

TUNNEL_HOST = "localhost.run"

processos = []

browser = None
ffmpeg = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global ffmpeg, browser

    log("")
    log("=" * 70)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 70)

    if ffmpeg:
        try:
            if ffmpeg.poll() is None:
                ffmpeg.terminate()
                ffmpeg.wait(timeout=5)
        except Exception:
            try:
                ffmpeg.kill()
            except Exception:
                pass

    for processo in processos:
        try:
            if processo.poll() is None:
                processo.terminate()
        except Exception:
            pass

    if browser:
        try:
            asyncio.run(browser.close())
        except Exception:
            pass

    time.sleep(1)

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
        except Exception as e:
            log("[AVISO] Não foi possível remover", caminho, e)


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("[2] Iniciando Xvfb...")

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
            "tcp"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    processos.append(proc)

    time.sleep(3)

    if proc.poll() is not None:
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
            "PulseAudio não iniciou:\n" + info.stderr
        )

    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        capture_output=True,
        text=True
    )

    if "webtv" not in sinks.stdout:

        log("Criando sink virtual webtv...")

        result = subprocess.run(
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

        if result.returncode != 0:
            raise RuntimeError(
                "Não foi possível criar o sink:\n" +
                result.stderr
            )

    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        check=False
    )

    time.sleep(2)

    sources = subprocess.run(
        ["pactl", "list", "short", "sources"],
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

    proc = subprocess.Popen(
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

    processos.append(proc)

    time.sleep(2)

    if proc.poll() is not None:
        raise RuntimeError("Servidor HTTP encerrou.")

    log(
        "Servidor HTTP ativo na porta",
        HTTP_PORT
    )


# ============================================================
# TÚNEL
# ============================================================

def iniciar_tunel():

    log("[5] Iniciando túnel localhost.run...")

    proc = subprocess.Popen(
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

            f"nokey@{TUNNEL_HOST}"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(proc)

    def ler():

        url_publica = None

        try:

            for linha in iter(proc.stdout.readline, ""):

                if not linha:
                    continue

                linha = linha.strip()

                log("[TUNEL]", linha)

                if (
                    "https://" in linha
                    and ".lhr.life" in linha
                ):

                    inicio = linha.find("https://")

                    url_publica = (
                        linha[inicio:]
                        .split()[0]
                        .rstrip("/")
                    )

                    log("")
                    log("=" * 70)
                    log("LINK DA TRANSMISSÃO")
                    log("=" * 70)
                    log("LINK PRINCIPAL:")
                    log(url_publica)
                    log("")
                    log("LINK HLS:")
                    log(url_publica + "/live.m3u8")
                    log("=" * 70)
                    log("")

        except Exception as e:
            log("[TUNEL] Erro:", e)

    threading.Thread(
        target=ler,
        daemon=True
    ).start()

    time.sleep(6)

    if proc.poll() is not None:
        raise RuntimeError(
            "O túnel encerrou antes de ficar disponível."
        )


# ============================================================
# TESTAR X11
# ============================================================

def testar_tela():

    log("[DIAGNÓSTICO] Testando X11...")

    arquivo = os.path.join(
        STREAM_DIR,
        "debug_screen.png"
    )

    result = subprocess.run(
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

    if result.returncode == 0:
        log("[DIAGNÓSTICO] Captura OK:", arquivo)
    else:
        log(
            "[DIAGNÓSTICO] Falha:",
            result.stderr
        )


# ============================================================
# CHROMIUM
# ============================================================

async def iniciar_chromium():

    global browser

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

        ignoreDefaultArgs=[
            "--enable-automation"
        ],

        args=[

            "--no-sandbox",
            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",

            "--ozone-platform=x11",

            # Mantém o navegador leve.
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",

            "--disable-popup-blocking",
            "--disable-notifications",

            # Autoplay.
            "--autoplay-policy=no-user-gesture-required",

            # Janela.
            f"--window-size={WIDTH},{HEIGHT}",
            "--window-position=0,0",
            "--force-device-scale-factor=1",

            "--no-first-run",
            "--no-default-browser-check"
        ]
    )

    log("Chromium iniciado.")

    page = await browser.newPage()

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

    def console_handler(msg):

        texto = msg.text

        # Evita poluir o log com o mesmo erro milhares de vezes.
        if "requestFullscreen" in texto:
            return

        log("[CONSOLE]", texto)

    page.on("console", console_handler)

    # --------------------------------------------------------
    # REQUESTS
    # --------------------------------------------------------

    falhas = {}

    def request_failed(request):

        url = request.url

        if (
            "firestore.googleapis.com" in url
            or "media.w3.org" in url
        ):
            falhas[url] = falhas.get(url, 0) + 1

            if falhas[url] <= 3:
                log(
                    "[REQUEST FAILED]",
                    url
                )

    page.on(
        "requestfailed",
        request_failed
    )

    # --------------------------------------------------------
    # NAVEGAR
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

    except Exception as e:

        log(
            "[AVISO] Navegação:",
            e
        )

    log("Aguardando página...")

    await asyncio.sleep(8)

    return page


# ============================================================
# DIAGNÓSTICO DO PLAYER
# ============================================================

async def diagnosticar_player(page):

    try:

        return await page.evaluate(
            """
            () => {

                const videos =
                    [...document.querySelectorAll("video")];

                return videos.map((v, i) => ({

                    index: i,

                    src: v.currentSrc || v.src || "",

                    paused: v.paused,

                    ended: v.ended,

                    readyState: v.readyState,

                    networkState: v.networkState,

                    currentTime: v.currentTime,

                    duration:
                        Number.isFinite(v.duration)
                            ? v.duration
                            : null,

                    width: v.videoWidth,

                    height: v.videoHeight,

                    muted: v.muted,

                    error: v.error
                        ? {
                            code: v.error.code,
                            message: v.error.message || ""
                        }
                        : null
                }));
            }
            """
        )

    except Exception as e:

        log(
            "[PLAYER] Diagnóstico:",
            e
        )

        return []


# ============================================================
# ESPERAR O SITE REPRODUZIR
# ============================================================

async def esperar_reproducao(page):

    log("")
    log("=" * 70)
    log("[PLAYER] Aguardando o player ORIGINAL do site...")
    log("=" * 70)

    ultimo_tempo = None
    estavel = 0

    for tentativa in range(1, 31):

        await asyncio.sleep(2)

        videos = await diagnosticar_player(page)

        log(
            f"[PLAYER] Verificação {tentativa}/30:",
            videos
        )

        for video in videos:

            tempo = video.get("currentTime", 0)
            width = video.get("width", 0)
            height = video.get("height", 0)

            if (
                video.get("readyState", 0) >= 2
                and width > 0
                and height > 0
                and not video.get("paused", True)
            ):

                if (
                    ultimo_tempo is not None
                    and tempo > ultimo_tempo
                ):
                    estavel += 1
                else:
                    estavel = 0

                ultimo_tempo = tempo

                if estavel >= 2:

                    log("")
                    log("=" * 70)
                    log("[PLAYER] REPRODUÇÃO CONFIRMADA")
                    log("=" * 70)

                    return True

    log("")
    log(
        "[AVISO] O site não confirmou reprodução."
    )

    log(
        "[AVISO] Não vamos forçar play nem trocar o src."
    )

    return False


# ============================================================
# TELA CHEIA POR F11
# ============================================================

def tela_cheia_f11():

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

    # F11 não depende de gesto JavaScript.
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

    time.sleep(3)

    log("[TELA] F11 enviado ao Chromium.")
    log("[TELA] Tela preparada para captura.")


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg

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
        # VÍDEO
        # ----------------------------------------------------

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
        # ENCODE
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

        # Bitrate mais amigável para 2.4 GHz.
        "-b:v",
        "1600k",

        "-maxrate",
        "1800k",

        "-bufsize",
        "3600k",

        # Áudio.
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

    log("Comando FFmpeg:")
    log(" ".join(comando))

    ffmpeg = subprocess.Popen(
        comando,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    processos.append(ffmpeg)

    def ler_ffmpeg():

        try:

            for linha in iter(
                ffmpeg.stderr.readline,
                ""
            ):

                if linha:
                    log("[FFMPEG]", linha.strip())

        except Exception:
            pass

    threading.Thread(
        target=ler_ffmpeg,
        daemon=True
    ).start()

    time.sleep(5)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou imediatamente."
        )

    log("=" * 70)
    log("TRANSMISSÃO ATIVA")
    log("=" * 70)


# ============================================================
# ESPERAR HLS
# ============================================================

def esperar_hls():

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    log("[HLS] Aguardando playlist...")

    for _ in range(30):

        if os.path.exists(playlist):

            try:

                if os.path.getsize(playlist) > 100:

                    log("[HLS] Playlist pronta.")
                    return True

            except Exception:
                pass

        time.sleep(1)

    raise RuntimeError(
        "FFmpeg não criou a playlist HLS."
    )


# ============================================================
# MONITORAR
# ============================================================

def monitorar():

    global ffmpeg

    while True:

        time.sleep(10)

        if ffmpeg is None:
            continue

        if ffmpeg.poll() is not None:

            log("")
            log("=" * 70)
            log("[ERRO] FFmpeg encerrou!")
            log("=" * 70)

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
    # IMPORTANTE:
    #
    # NÃO alteramos:
    #   video.src
    #   video.load()
    #   video.pause()
    #   video.play()
    #
    # O site continua controlando o próprio player.
    # --------------------------------------------------------

    reproduzindo = await esperar_reproducao(page)

    # Mesmo que o player não confirme via JS,
    # esperamos a página estabilizar antes da captura.
    if not reproduzindo:

        log(
            "[AVISO] Player não confirmou estado via JS."
        )

        log(
            "[AVISO] Continuando com captura da página."
        )

        await asyncio.sleep(5)

    # --------------------------------------------------------
    # FULLSCREEN REAL DA JANELA
    # --------------------------------------------------------

    tela_cheia_f11()

    await asyncio.sleep(3)

    # --------------------------------------------------------
    # FFmpeg
    # --------------------------------------------------------

    iniciar_ffmpeg()

    esperar_hls()

    log("")
    log("=" * 70)
    log("STREAM RODANDO")
    log("=" * 70)

    threading.Thread(
        target=monitorar,
        daemon=True
    ).start()

    while True:

        await asyncio.sleep(30)

        # Mantém o processo principal vivo.
        if ffmpeg and ffmpeg.poll() is not None:
            raise RuntimeError(
                "FFmpeg encerrou durante a transmissão."
            )


# ============================================================
# EXECUÇÃO
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
