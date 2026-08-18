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

FFMPEG_PRESET = "veryfast"


# ============================================================
# PROCESSOS
# ============================================================

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
        if ffmpeg_global and ffmpeg_global.poll() is None:
            ffmpeg_global.terminate()
    except Exception:
        pass

    try:
        if browser_global:
            asyncio.run_coroutine_threadsafe(
                browser_global.close(),
                asyncio.get_event_loop()
            )
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

    time.sleep(2)

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
    os.environ["PULSE_SINK"] = "webtv"

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

    time.sleep(2)

    teste = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True
    )

    if teste.returncode != 0:
        raise RuntimeError(
            "PulseAudio não iniciou."
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
                "Não foi possível criar o áudio virtual."
            )

    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        check=False
    )

    time.sleep(1)

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
        f"Servidor HTTP ativo na porta {HTTP_PORT}"
    )


# ============================================================
# TÚNEL LOCALHOST.RUN
# ============================================================

def iniciar_tunel():

    log("[5] Iniciando túnel localhost.run...")

    tunnel = subprocess.Popen(
        [
            "ssh",

            "-o",
            "StrictHostKeyChecking=no",

            "-o",
            "ServerAliveInterval=20",

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

    processos.append(tunnel)

    url_encontrada = None

    inicio = time.time()

    while time.time() - inicio < 30:

        linha = tunnel.stdout.readline()

        if not linha:
            if tunnel.poll() is not None:
                break
            continue

        linha = linha.strip()

        log("[TUNEL]", linha)

        if "https://" in linha and ".lhr.life" in linha:

            partes = linha.split()

            for parte in partes:

                if (
                    parte.startswith("https://")
                    and
                    ".lhr.life" in parte
                ):
                    url_encontrada = parte.rstrip("/")
                    break

            if url_encontrada:
                break

    if not url_encontrada:

        raise RuntimeError(
            "Não foi possível obter a URL do túnel."
        )

    log("")
    log("=" * 70)
    log("LINK DA TRANSMISSÃO")
    log("=" * 70)
    log("LINK PRINCIPAL:")
    log(url_encontrada)
    log("")
    log("LINK HLS:")
    log(url_encontrada + "/live.m3u8")
    log("=" * 70)

    # Continua lendo o túnel em segundo plano
    def monitorar():

        try:

            for linha in iter(
                tunnel.stdout.readline,
                ""
            ):

                if linha:
                    log("[TUNEL]", linha.strip())

        except Exception:
            pass

    threading.Thread(
        target=monitorar,
        daemon=True
    ).start()

    return url_encontrada


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
            "[DIAGNÓSTICO] Erro:",
            resultado.stderr
        )


# ============================================================
# DIAGNÓSTICO DOS VÍDEOS
# ============================================================

async def diagnosticar_videos(page):

    try:

        return await page.evaluate(
            """
            () => Array.from(
                document.querySelectorAll("video")
            ).map((v, i) => ({
                index: i,
                src: v.currentSrc || v.src || "",
                paused: v.paused,
                ended: v.ended,
                muted: v.muted,
                readyState: v.readyState,
                networkState: v.networkState,
                currentTime: v.currentTime,
                duration: v.duration,
                width: v.videoWidth,
                height: v.videoHeight,
                error: v.error
                    ? {
                        code: v.error.code,
                        message: v.error.message
                    }
                    : null
            }))
            """
        )

    except Exception as erro:

        log(
            "[PLAYER] Erro diagnóstico:",
            erro
        )

        return []


# ============================================================
# INICIALIZAR PLAYER
# ============================================================

async def preparar_player(page):

    log("")
    log("=" * 70)
    log("[PLAYER] Preparando reprodução original da página")
    log("=" * 70)

    # Não substitui o player.
    # Apenas permite autoplay quando o próprio site chamar play().
    await page.evaluate(
        """
        () => {

            const videos =
                document.querySelectorAll("video");

            videos.forEach(video => {

                video.setAttribute(
                    "playsinline",
                    ""
                );

                video.setAttribute(
                    "webkit-playsinline",
                    ""
                );

                video.preload = "auto";

            });

        }
        """
    )

    for tentativa in range(1, 13):

        await asyncio.sleep(3)

        videos = await diagnosticar_videos(page)

        log(
            f"[PLAYER] Tentativa {tentativa}/12:",
            videos
        )

        for video in videos:

            if (
                video["readyState"] >= 3
                and
                video["width"] > 0
                and
                video["height"] > 0
                and
                not video["ended"]
            ):

                log(
                    "[PLAYER] Vídeo recebeu dados."
                )

                return True

    return False


# ============================================================
# RECUPERAÇÃO DO PLAYER
# ============================================================

async def monitorar_player(page):

    ultimo_tempo = None
    ultima_mudanca = time.time()

    while True:

        try:

            await asyncio.sleep(5)

            videos = await diagnosticar_videos(page)

            if not videos:
                continue

            principal = None

            for video in videos:

                if (
                    video["width"] > 0
                    and
                    video["height"] > 0
                ):
                    principal = video
                    break

            if not principal:
                continue

            tempo = principal["currentTime"]

            if (
                ultimo_tempo is None
                or
                tempo != ultimo_tempo
            ):

                ultimo_tempo = tempo
                ultima_mudanca = time.time()

                log(
                    "[PLAYER] Reprodução:",
                    round(tempo, 2),
                    "s"
                )

            # Se o player ficou parado por 12 segundos
            if (
                time.time() - ultima_mudanca > 12
                and
                not principal["ended"]
            ):

                log(
                    "[PLAYER] Vídeo parece travado."
                )

                await page.evaluate(
                    """
                    async () => {

                        const videos =
                            Array.from(
                                document.querySelectorAll("video")
                            );

                        for (const video of videos) {

                            if (
                                video.videoWidth > 0
                                &&
                                video.readyState >= 2
                            ) {

                                try {

                                    if (video.paused) {
                                        await video.play();
                                    }

                                } catch (e) {}

                            }

                        }

                    }
                    """
                )

                ultima_mudanca = time.time()

        except Exception as erro:

            log(
                "[PLAYER] Monitor:",
                erro
            )


# ============================================================
# TELA CHEIA DO CHROMIUM
# ============================================================

def colocar_chromium_em_tela_cheia():

    log("")
    log("=" * 70)
    log("[TELA] Ativando tela cheia do Chromium")
    log("=" * 70)

    # Aqui está a mudança importante:
    #
    # NÃO usamos:
    #
    #     element.requestFullscreen()
    #
    # pois isso exige user gesture.
    #
    # Usamos o próprio F11 do Chromium através do X11.

    time.sleep(2)

    resultado = subprocess.run(
        [
            "xdotool",
            "key",
            "--clearmodifiers",
            "F11"
        ],
        capture_output=True,
        text=True
    )

    if resultado.returncode == 0:
        log("[TELA] F11 enviado ao Chromium.")
    else:
        log(
            "[TELA] Erro F11:",
            resultado.stderr
        )

    time.sleep(3)

    # Garante que a janela ocupe a tela.
    subprocess.run(
        [
            "xdotool",
            "mousemove",
            "640",
            "360"
        ],
        check=False
    )

    log("[TELA] Tela preparada para captura.")


# ============================================================
# CHROMIUM
# ============================================================

async def abrir_navegador():

    global browser_global
    global page_global

    log("")
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

            # ------------------------------------------------
            # IMPORTANTE:
            # não desabilitamos completamente a aceleração.
            # ------------------------------------------------

            "--use-gl=swiftshader",

            "--enable-accelerated-video-decode",

            "--enable-accelerated-video-encode",

            # ------------------------------------------------
            # AUTOPLAY
            # ------------------------------------------------

            "--autoplay-policy=no-user-gesture-required",

            # ------------------------------------------------
            # JANELA
            # ------------------------------------------------

            "--window-size=1280,720",
            "--window-position=0,0",

            "--force-device-scale-factor=1",

            # ------------------------------------------------
            # ESTABILIDADE
            # ------------------------------------------------

            "--no-first-run",
            "--no-default-browser-check",

            "--disable-background-networking",

            "--disable-background-timer-throttling",

            "--disable-backgrounding-occluded-windows",

            "--disable-renderer-backgrounding",

            "--disable-popup-blocking",

            "--disable-notifications",

            "--disable-infobars",

            # ------------------------------------------------
            # EVITA ECONOMIA DE RECURSOS
            # ------------------------------------------------

            "--disable-features=CalculateNativeWinOcclusion",

            # ------------------------------------------------
            # ÁUDIO
            # ------------------------------------------------

            "--alsa-output-device=default"
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

    # ========================================================
    # CONSOLE
    # ========================================================

    page.on(
        "console",
        lambda mensagem:
            log(
                "[CONSOLE]",
                mensagem.text
            )
    )

    # ========================================================
    # ERROS DE PÁGINA
    # ========================================================

    page.on(
        "pageerror",
        lambda erro:
            log(
                "[PAGE ERROR]",
                erro
            )
    )

    # ========================================================
    # REQUESTS COM ERRO
    # ========================================================

    def request_failed(request):

        url = request.url

        # Não poluir o log com Firestore.
        if "firestore.googleapis.com" in url:
            return

        log(
            "[REQUEST FAILED]",
            url,
            request.failure
        )

    page.on(
        "requestfailed",
        request_failed
    )

    # ========================================================
    # RESPONSE
    # ========================================================

    async def verificar_resposta(response):

        try:

            if (
                "media.w3.org" in response.url
                or
                ".mp4" in response.url
            ):

                log(
                    "[MEDIA]",
                    response.status,
                    response.url
                )

        except Exception:
            pass

    page.on(
        "response",
        lambda response:
            asyncio.ensure_future(
                verificar_resposta(response)
            )
    )

    # ========================================================
    # ABRIR PÁGINA
    # ========================================================

    log("")
    log("Abrindo página:")
    log(URL_ALVO)

    await page.goto(
        URL_ALVO,
        {
            "waitUntil": "domcontentloaded",
            "timeout": 120000
        }
    )

    log("Página carregada.")

    await asyncio.sleep(8)

    # ========================================================
    # PREPARA PLAYER
    # ========================================================

    carregou = await preparar_player(page)

    if not carregou:

        log(
            "[AVISO] Player ainda não confirmou vídeo."
        )

        # Não encerra imediatamente.
        # O site pode estar fazendo sincronização.

    else:

        log(
            "[PLAYER] Reprodução detectada."
        )

    # ========================================================
    # TELA CHEIA
    # ========================================================

    colocar_chromium_em_tela_cheia()

    # ========================================================
    # MONITOR DO PLAYER
    # ========================================================

    asyncio.ensure_future(
        monitorar_player(page)
    )

    return browser, page


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

        # ====================================================
        # VÍDEO
        # ====================================================

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

        # ====================================================
        # ÁUDIO
        # ====================================================

        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ====================================================
        # ENCODER
        # ====================================================

        "-c:v",
        "libx264",

        "-preset",
        FFMPEG_PRESET,

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
        "1800k",

        "-maxrate",
        "2200k",

        "-bufsize",
        "3600k",

        # ====================================================
        # ÁUDIO
        # ====================================================

        "-c:a",
        "aac",

        "-b:a",
        "96k",

        "-ar",
        "44100",

        "-ac",
        "2",

        # ====================================================
        # HLS
        # ====================================================

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

    ffmpeg_global = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(ffmpeg_global)

    def monitorar_ffmpeg():

        try:

            for linha in iter(
                ffmpeg_global.stdout.readline,
                ""
            ):

                if linha:
                    log(
                        "[FFMPEG]",
                        linha.rstrip()
                    )

        except Exception:
            pass

    threading.Thread(
        target=monitorar_ffmpeg,
        daemon=True
    ).start()

    time.sleep(5)

    if ffmpeg_global.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log("")
    log("=" * 70)
    log("TRANSMISSÃO ATIVA")
    log("=" * 70)


# ============================================================
# VERIFICAR HLS
# ============================================================

def esperar_hls():

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    log("")
    log("[HLS] Aguardando playlist...")

    for tentativa in range(30):

        if os.path.exists(playlist):

            try:

                tamanho = os.path.getsize(
                    playlist
                )

                if tamanho > 50:

                    log(
                        "[HLS] Playlist pronta."
                    )

                    return True

            except Exception:
                pass

        time.sleep(1)

    log(
        "[HLS] Playlist não apareceu."
    )

    return False


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

    browser, page = await abrir_navegador()

    # --------------------------------------------------------
    # Dá tempo para a página efetivamente começar a reproduzir.
    # --------------------------------------------------------

    log("")
    log("[PLAYER] Aguardando reprodução estabilizar...")

    await asyncio.sleep(5)

    # --------------------------------------------------------
    # Só agora começa a captura.
    # --------------------------------------------------------

    iniciar_ffmpeg()

    esperar_hls()

    log("")
    log("=" * 70)
    log("STREAM RODANDO")
    log("=" * 70)

    # Mantém o processo vivo.
    while True:

        if ffmpeg_global:

            if ffmpeg_global.poll() is not None:

                log(
                    "[ERRO] FFmpeg encerrou."
                )

                break

        if browser:

            try:

                pages = await browser.pages()

                if not pages:

                    log(
                        "[ERRO] Chromium encerrou."
                    )

                    break

            except Exception:
                pass

        await asyncio.sleep(10)


# ============================================================
# ENTRADA
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

        log(
            repr(erro)
        )

        encerrar()


if __name__ == "__main__":
    main()
