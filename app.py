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
            ffmpeg_global.wait(timeout=5)
    except Exception:
        try:
            if ffmpeg_global:
                ffmpeg_global.kill()
        except Exception:
            pass

    try:
        if browser_global:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(browser_global.close())
            loop.close()
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
            log("[AVISO] Não foi possível remover:", caminho, erro)


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
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
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
            "--start",
            "--exit-idle-time=-1",
        ],
        check=False,
    )

    time.sleep(3)

    info = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True,
    )

    if info.returncode != 0:
        raise RuntimeError("PulseAudio não iniciou.")

    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        capture_output=True,
        text=True,
    )

    if "webtv" not in sinks.stdout:

        log("Criando sink virtual webtv...")

        resultado = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV",
            ],
            capture_output=True,
            text=True,
        )

        if resultado.returncode != 0:
            raise RuntimeError(
                "Não foi possível criar o sink webtv."
            )

    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        check=False,
    )

    os.environ["PULSE_SINK"] = "webtv"

    time.sleep(1)

    sources = subprocess.run(
        ["pactl", "list", "short", "sources"],
        capture_output=True,
        text=True,
    )

    log("Fontes de áudio:")
    log(sources.stdout)

    if "webtv.monitor" not in sources.stdout:
        raise RuntimeError(
            "webtv.monitor não encontrado."
        )

    log("Áudio pronto.")


# ============================================================
# SERVIDOR HTTP
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
            STREAM_DIR,
            "--bind",
            "0.0.0.0",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    processos.append(servidor)

    time.sleep(2)

    if servidor.poll() is not None:
        raise RuntimeError("Servidor HTTP encerrou.")

    log(
        "Servidor HTTP ativo na porta",
        HTTP_PORT,
    )


# ============================================================
# TÚNEL
# ============================================================

def iniciar_tunel():

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
            "nokey@localhost.run",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    processos.append(tunnel)

    def ler():

        url_encontrada = False

        try:

            for linha in iter(tunnel.stdout.readline, ""):

                if not linha:
                    continue

                linha = linha.strip()

                log("[TUNEL]", linha)

                if (
                    "https://" in linha
                    and
                    ".lhr.life" in linha
                    and
                    not url_encontrada
                ):

                    inicio = linha.find("https://")

                    url = linha[inicio:].split()[0]

                    url_encontrada = True

                    log("")
                    log("=" * 70)
                    log("LINK DA TRANSMISSÃO")
                    log("=" * 70)
                    log("LINK PRINCIPAL:")
                    log(url)
                    log("")
                    log("LINK HLS:")
                    log(url.rstrip("/") + "/live.m3u8")
                    log("=" * 70)
                    log("")

        except Exception as erro:

            log("[TUNEL] Erro:", erro)

    threading.Thread(
        target=ler,
        daemon=True,
    ).start()

    time.sleep(6)

    if tunnel.poll() is not None:
        raise RuntimeError(
            "Túnel encerrou antes de ficar disponível."
        )


# ============================================================
# TESTE X11
# ============================================================

def testar_tela():

    log("[DIAGNÓSTICO] Testando X11...")

    arquivo = os.path.join(
        STREAM_DIR,
        "debug_screen.png",
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
            arquivo,
        ],
        capture_output=True,
        text=True,
    )

    if resultado.returncode == 0:
        log("[DIAGNÓSTICO] Captura OK:", arquivo)
    else:
        log(
            "[DIAGNÓSTICO] Erro:",
            resultado.stderr,
        )


# ============================================================
# DIAGNÓSTICO DO PLAYER
# ============================================================

async def diagnosticar_videos(page):

    try:

        resultado = await page.evaluate(
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
                duration: Number.isFinite(v.duration)
                    ? v.duration
                    : null,
                width: v.videoWidth,
                height: v.videoHeight,
                error: v.error
                    ? {
                        code: v.error.code,
                        message: v.error.message || ""
                    }
                    : null
            }))
            """
        )

        log("[PLAYER]", resultado)

        return resultado

    except Exception as erro:

        log("[PLAYER] Erro diagnóstico:", erro)

        return []


# ============================================================
# ABRIR CHROMIUM
# ============================================================

async def abrir_navegador():

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

            "--disable-software-rasterizer",

            "--ozone-platform=x11",

            # IMPORTANTE:
            # não desabilitar completamente o pipeline
            # de vídeo.

            "--use-gl=swiftshader",

            # Autoplay
            "--autoplay-policy=no-user-gesture-required",

            # Janela
            "--window-size=1280,720",

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

            "--disable-notifications",

            "--disable-infobars",

            "--disable-session-crashed-bubble",

            # Permitir mídia
            "--enable-features=UseOzonePlatform",

        ],
    )

    browser_global = browser

    page = await browser.newPage()

    page_global = page

    await page.setViewport(
        {
            "width": WIDTH,
            "height": HEIGHT,
            "deviceScaleFactor": 1,
        }
    )

    # --------------------------------------------------------
    # CONSOLE
    # --------------------------------------------------------

    page.on(
        "console",
        lambda msg: log(
            "[CONSOLE]",
            msg.text,
        )
    )

    # --------------------------------------------------------
    # ERROS DE PÁGINA
    # --------------------------------------------------------

    page.on(
        "pageerror",
        lambda erro: log(
            "[PAGE ERROR]",
            erro,
        )
    )

    # --------------------------------------------------------
    # REQUESTS
    # --------------------------------------------------------

    def request_failed(req):

        url = req.url

        # Mostrar principalmente mídia e APIs importantes.
        if (
            ".mp4" in url
            or ".m3u8" in url
            or ".ts" in url
            or "firestore" in url
        ):
            log(
                "[REQUEST FAILED]",
                url,
            )

    page.on(
        "requestfailed",
        request_failed,
    )

    # --------------------------------------------------------
    # ABRIR SITE
    # --------------------------------------------------------

    log("")
    log("Abrindo página:")
    log(URL_ALVO)

    try:

        await page.goto(
            URL_ALVO,
            {
                "waitUntil": "domcontentloaded",
                "timeout": 90000,
            },
        )

    except Exception as erro:

        log(
            "[AVISO] goto:",
            erro,
        )

    log("Aguardando página...")

    await asyncio.sleep(8)

    return browser, page


# ============================================================
# ESPERAR SITE ESTABILIZAR
# ============================================================

async def esperar_site(page):

    log("")
    log("=" * 70)
    log("AGUARDANDO O PLAYER NATIVO DO SITE")
    log("=" * 70)

    # Não troca src.
    # Não cria outro vídeo.
    # Não força currentTime.
    # Não pausa o player.

    for tentativa in range(1, 13):

        await asyncio.sleep(5)

        videos = await diagnosticar_videos(page)

        pronto = False

        for video in videos:

            if (
                video.get("readyState", 0) >= 3
                and
                video.get("width", 0) > 0
                and
                video.get("height", 0) > 0
                and
                not video.get("error")
            ):

                pronto = True
                break

        if pronto:

            log("")
            log(
                "[PLAYER] Vídeo carregado pelo próprio site."
            )

            return True

        log(
            f"[PLAYER] Tentativa {tentativa}/12:"
            " aguardando player..."
        )

    log("")
    log(
        "[AVISO] O site não confirmou reprodução."
    )

    return False


# ============================================================
# TENTAR GESTO REAL
# ============================================================

async def gesto_reproducao(page):

    log("")
    log("=" * 70)
    log("[PLAYER] Tentando iniciar pelo fluxo normal do site")
    log("=" * 70)

    try:

        # Primeiro tenta clicar no centro da página.
        # Isso cria um verdadeiro user gesture.
        await page.mouse.click(
            WIDTH // 2,
            HEIGHT // 2,
        )

        await asyncio.sleep(2)

        log("[PLAYER] Clique real enviado.")

    except Exception as erro:

        log(
            "[PLAYER] Clique:",
            erro,
        )

    # Depois deixa o próprio navegador lidar com autoplay.
    # Não sobrescrevemos src nem currentTime.

    try:

        resultado = await page.evaluate(
            """
            () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                return videos.map((video, index) => ({
                    index,
                    paused: video.paused,
                    readyState: video.readyState,
                    width: video.videoWidth,
                    height: video.videoHeight,
                    currentTime: video.currentTime,
                    src: video.currentSrc || video.src || ""
                }));

            }
            """
        )

        log(
            "[PLAYER] Estado após gesto:",
            resultado,
        )

    except Exception as erro:

        log(
            "[PLAYER] Diagnóstico:",
            erro,
        )


# ============================================================
# TELA CHEIA DO CHROMIUM
# ============================================================

def tela_cheia_chromium():

    log("")
    log("=" * 70)
    log("[TELA] Ativando tela cheia do Chromium")
    log("=" * 70)

    # F11 é tratado pelo próprio Chromium/X11.
    # Não depende da Fullscreen API.
    resultado = subprocess.run(
        [
            "xdotool",
            "key",
            "--clearmodifiers",
            "F11",
        ],
        capture_output=True,
        text=True,
    )

    if resultado.returncode != 0:

        log(
            "[TELA] Erro F11:",
            resultado.stderr,
        )

        return False

    time.sleep(3)

    log("[TELA] F11 enviado ao Chromium.")
    log("[TELA] Tela preparada para captura.")

    return True


# ============================================================
# VERIFICAR REPRODUÇÃO
# ============================================================

async def verificar_reproducao(page):

    log("")
    log("=" * 70)
    log("[PLAYER] Verificando reprodução")
    log("=" * 70)

    anterior = None

    for _ in range(6):

        await asyncio.sleep(3)

        videos = await diagnosticar_videos(page)

        for video in videos:

            if (
                video.get("width", 0) > 0
                and
                video.get("height", 0) > 0
            ):

                atual = video.get(
                    "currentTime"
                )

                if anterior is not None:

                    diferenca = atual - anterior

                    if diferenca > 0:

                        log(
                            "[PLAYER] Reprodução avançando:",
                            round(diferenca, 2),
                            "s",
                        )

                        return True

                anterior = atual

    log(
        "[AVISO] Não foi possível confirmar avanço."
    )

    return False


# ============================================================
# FFMPEG
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
        str(FPS),

        "-g",
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        # ----------------------------------------------------
        # BITRATE
        # ----------------------------------------------------

        "-b:v",
        "1800k",

        "-maxrate",
        "2200k",

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
        os.path.join(
            STREAM_DIR,
            "segment_%05d.ts",
        ),

        os.path.join(
            STREAM_DIR,
            "live.m3u8",
        ),
    ]

    log(
        "Comando FFmpeg:"
    )

    log(
        " ".join(comando)
    )

    ffmpeg_global = subprocess.Popen(
        comando,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    processos.append(ffmpeg_global)

    def ler_ffmpeg():

        try:

            for linha in iter(
                ffmpeg_global.stderr.readline,
                "",
            ):

                if linha:
                    log(
                        "[FFMPEG]",
                        linha.rstrip(),
                    )

        except Exception:
            pass

    threading.Thread(
        target=ler_ffmpeg,
        daemon=True,
    ).start()

    time.sleep(4)

    if ffmpeg_global.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou imediatamente."
        )

    log("FFmpeg funcionando.")


# ============================================================
# ESPERAR HLS
# ============================================================

def esperar_hls():

    log("[HLS] Aguardando playlist...")

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8",
    )

    for _ in range(30):

        if (
            os.path.exists(playlist)
            and
            os.path.getsize(playlist) > 0
        ):

            log("[HLS] Playlist pronta.")

            return True

        time.sleep(1)

    raise RuntimeError(
        "FFmpeg não criou a playlist HLS."
    )


# ============================================================
# MONITORAR
# ============================================================

def monitorar():

    global ffmpeg_global

    log("")
    log("=" * 70)
    log("STREAM RODANDO")
    log("=" * 70)

    while True:

        time.sleep(10)

        if ffmpeg_global is None:
            raise RuntimeError(
                "FFmpeg não existe."
            )

        if ffmpeg_global.poll() is not None:

            raise RuntimeError(
                "FFmpeg encerrou durante a transmissão."
            )

        playlist = os.path.join(
            STREAM_DIR,
            "live.m3u8",
        )

        if not os.path.exists(playlist):

            raise RuntimeError(
                "Playlist HLS desapareceu."
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

    browser, page = await abrir_navegador()

    # --------------------------------------------------------
    # DEIXA O SITE REPRODUZIR
    # --------------------------------------------------------

    await esperar_site(page)

    await gesto_reproducao(page)

    await asyncio.sleep(5)

    # --------------------------------------------------------
    # TELA CHEIA REAL DO CHROMIUM
    # --------------------------------------------------------

    tela_cheia_chromium()

    await asyncio.sleep(5)

    # --------------------------------------------------------
    # VERIFICA NOVAMENTE
    # --------------------------------------------------------

    await verificar_reproducao(page)

    # --------------------------------------------------------
    # CAPTURA
    # --------------------------------------------------------

    iniciar_ffmpeg()

    esperar_hls()

    monitorar()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("=" * 70)
        log("ERRO FATAL")
        log("=" * 70)
        log(erro)

        encerrar()
