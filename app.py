import os
import sys
import time
import signal
import asyncio
import subprocess
import threading

from playwright.async_api import async_playwright


# ============================================================
# CONFIGURAÇÃO
# ============================================================

STREAM_DIR = os.path.abspath("stream")

DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720
FPS = 30

HTTP_PORT = 8080

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

CHROMIUM = "/usr/bin/chromium"

ffmpeg_process = None
xvfb_process = None
pulse_process = None
http_process = None
tunnel_process = None

encerrando = False


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global encerrando

    if encerrando:
        return

    encerrando = True

    log("")
    log("==========================================================")
    log("ENCERRANDO TRANSMISSAO")
    log("==========================================================")

    # O FFmpeg recebe TERM normalmente.
    processos = [
        tunnel_process,
        http_process,
        ffmpeg_process,
        pulse_process,
        xvfb_process,
    ]

    for processo in processos:

        if processo is None:
            continue

        try:

            if processo.poll() is None:
                processo.terminate()

        except Exception:
            pass

    time.sleep(2)

    for processo in processos:

        if processo is None:
            continue

        try:

            if processo.poll() is None:
                processo.kill()

        except Exception:
            pass

    log("Transmissao encerrada.")


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

    global xvfb_process

    log("[1] Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    xvfb_process = subprocess.Popen(
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

    if xvfb_process.poll() is not None:

        raise RuntimeError(
            "Xvfb nao iniciou."
        )

    log("Xvfb OK.")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    global pulse_process

    log("[2] Iniciando PulseAudio...")

    runtime = "/tmp/pulse"

    os.makedirs(runtime, exist_ok=True)

    os.environ["PULSE_RUNTIME_PATH"] = runtime
    os.environ["DISPLAY"] = DISPLAY

    subprocess.run(
        ["pulseaudio", "--kill"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    pulse_process = subprocess.Popen(
        [
            "pulseaudio",
            "--daemonize=no",
            "--exit-idle-time=-1"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    time.sleep(3)

    teste = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True,
        check=False
    )

    if teste.returncode != 0:

        raise RuntimeError(
            "PulseAudio nao iniciou."
        )

    # Cria sink virtual.
    criar = subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            "sink_name=webtv",
            "sink_properties=device.description=WebTV"
        ],
        capture_output=True,
        text=True,
        check=False
    )

    if criar.returncode != 0:

        log(
            "Sink webtv ja existe."
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

    fontes = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ],
        capture_output=True,
        text=True,
        check=False
    )

    if "webtv.monitor" not in fontes.stdout:

        raise RuntimeError(
            "webtv.monitor nao encontrado."
        )

    log("PulseAudio OK.")


# ============================================================
# HTTP
# ============================================================

def iniciar_http():

    global http_process

    log("[3] Iniciando servidor HTTP...")

    http_process = subprocess.Popen(
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

    if http_process.poll() is not None:

        raise RuntimeError(
            "Servidor HTTP encerrou."
        )

    log(
        f"HTTP ativo na porta {HTTP_PORT}."
    )


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_process

    log("[4] Iniciando FFmpeg...")

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    segmentos = os.path.join(
        STREAM_DIR,
        "segment_%05d.ts"
    )

    comando = [

        "ffmpeg",

        "-hide_banner",

        "-loglevel",
        "warning",

        "-y",

        # ----------------------------
        # VIDEO
        # ----------------------------

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

        # ----------------------------
        # AUDIO
        # ----------------------------

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ----------------------------
        # VIDEO
        # ----------------------------

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

        # ----------------------------
        # AUDIO
        # ----------------------------

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        "-ac",
        "2",

        # ----------------------------
        # HLS
        # ----------------------------

        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        segmentos,

        playlist
    ]

    ffmpeg_process = subprocess.Popen(
        comando,
        env=os.environ.copy()
    )

    time.sleep(3)

    if ffmpeg_process.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou ao iniciar."
        )

    log("FFmpeg OK.")


# ============================================================
# TUNEL
# ============================================================

def iniciar_tunel():

    global tunnel_process

    log("[5] Iniciando tunel publico...")

    tunnel_process = subprocess.Popen(
        [
            "cloudflared",
            "tunnel",
            "--no-autoupdate",
            "--url",
            f"http://127.0.0.1:{HTTP_PORT}"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    inicio = time.time()

    while time.time() - inicio < 60:

        linha = tunnel_process.stdout.readline()

        if not linha:
            continue

        linha = linha.strip()

        if linha:
            log("[TUNEL]", linha)

        if "trycloudflare.com" in linha:

            partes = linha.split()

            for parte in partes:

                if (
                    parte.startswith("https://")
                    and
                    "trycloudflare.com" in parte
                ):

                    url = parte.rstrip("/")

                    log("")
                    log("==========================================================")
                    log("TRANSMISSAO ONLINE")
                    log("==========================================================")
                    log("")
                    log("LINK:")
                    log(url)
                    log("")
                    log("HLS:")
                    log(url + "/live.m3u8")
                    log("")
                    log("==========================================================")
                    log("")

                    return url

    raise RuntimeError(
        "Nao foi possivel obter o link publico."
    )


# ============================================================
# DIAGNÓSTICO
# ============================================================

async def diagnostico(page):

    try:

        dados = await page.evaluate(
            """
            () => {

                return [...document.querySelectorAll("video")]
                    .map((v, i) => ({

                        index: i,

                        src: v.src || "",

                        currentSrc:
                            v.currentSrc || "",

                        paused:
                            v.paused,

                        muted:
                            v.muted,

                        readyState:
                            v.readyState,

                        networkState:
                            v.networkState,

                        currentTime:
                            v.currentTime,

                        duration:
                            v.duration,

                        width:
                            v.videoWidth,

                        height:
                            v.videoHeight,

                        error:
                            v.error
                            ? {
                                code: v.error.code,
                                message: v.error.message
                            }
                            : null
                    }));
            }
            """
        )

        log("")
        log("========== VIDEO DIAGNOSTICO ==========")

        if not dados:

            log("Nenhum video encontrado.")

        else:

            for video in dados:
                log(video)

        log("========================================")
        log("")

        return dados

    except Exception as erro:

        log(
            "[DIAGNOSTICO]",
            erro
        )

        return []


# ============================================================
# TENTAR REPRODUÇÃO
# ============================================================

async def tentar_reproduzir(page):

    try:

        resultado = await page.evaluate(
            """
            async () => {

                const videos =
                    [...document.querySelectorAll("video")];

                const retorno = [];

                for (
                    let i = 0;
                    i < videos.length;
                    i++
                ) {

                    const video = videos[i];

                    video.autoplay = true;
                    video.playsInline = true;

                    let resultado = "";

                    try {

                        const p = video.play();

                        if (p) {
                            await p;
                        }

                        resultado = "PLAY_OK";

                    } catch (erro) {

                        resultado =
                            String(erro);
                    }

                    retorno.push({

                        index: i,

                        resultado,

                        readyState:
                            video.readyState,

                        width:
                            video.videoWidth,

                        height:
                            video.videoHeight,

                        paused:
                            video.paused,

                        currentTime:
                            video.currentTime
                    });
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
            "[PLAYER]",
            erro
        )


# ============================================================
# ABRIR NAVEGADOR
# ============================================================

async def abrir_navegador(playwright):

    log("")
    log("[CHROMIUM] Abrindo navegador...")

    ambiente = os.environ.copy()

    ambiente["DISPLAY"] = DISPLAY
    ambiente["PULSE_SINK"] = "webtv"

    navegador = await playwright.chromium.launch(

        headless=False,

        executable_path=CHROMIUM,

        env=ambiente,

        args=[

            "--no-sandbox",

            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",

            "--ozone-platform=x11",

            "--autoplay-policy=no-user-gesture-required",

            "--no-first-run",

            "--no-default-browser-check",

            "--disable-popup-blocking",

            "--disable-notifications",

            "--window-size=1280,720",

            "--window-position=0,0",

            "--start-maximized",

            "--kiosk",

            "--start-fullscreen",

            "--force-device-scale-factor=1"
        ]
    )

    pagina = await navegador.new_page(
        viewport={
            "width": WIDTH,
            "height": HEIGHT
        }
    )

    # --------------------------------------------------------
    # LOGS
    # --------------------------------------------------------

    pagina.on(
        "console",
        lambda msg:
        log(
            "[CONSOLE]",
            msg.type,
            msg.text
        )
    )

    pagina.on(
        "pageerror",
        lambda erro:
        log(
            "[PAGE ERROR]",
            erro
        )
    )

    pagina.on(
        "requestfailed",
        lambda req:
        log(
            "[REQUEST FAILED]",
            req.url,
            req.failure
        )
    )

    # --------------------------------------------------------
    # ABRIR
    # --------------------------------------------------------

    log(
        "[CHROMIUM] Abrindo:",
        URL_ALVO
    )

    try:

        await pagina.goto(
            URL_ALVO,
            wait_until="domcontentloaded",
            timeout=60000
        )

    except Exception as erro:

        log(
            "[CHROMIUM] goto:",
            erro
        )

    await pagina.wait_for_timeout(8000)

    log(
        "[CHROMIUM] Pagina carregada."
    )

    try:

        log(
            "[CHROMIUM] Titulo:",
            await pagina.title()
        )

    except Exception:
        pass

    # --------------------------------------------------------
    # CSS DE TELA
    # --------------------------------------------------------

    try:

        await pagina.evaluate(
            """
            () => {

                document.documentElement.style.margin = "0";
                document.documentElement.style.padding = "0";

                document.body.style.margin = "0";
                document.body.style.padding = "0";

                document.body.style.width = "100vw";
                document.body.style.height = "100vh";

                document.body.style.overflow = "hidden";
            }
            """
        )

    except Exception:
        pass

    # --------------------------------------------------------
    # DIAGNÓSTICO
    # --------------------------------------------------------

    await diagnostico(pagina)

    # --------------------------------------------------------
    # PLAY
    # --------------------------------------------------------

    await tentar_reproduzir(pagina)

    # --------------------------------------------------------
    # UM ÚNICO CLIQUE
    # --------------------------------------------------------

    try:

        await pagina.mouse.click(
            WIDTH // 2,
            HEIGHT // 2
        )

        await pagina.wait_for_timeout(1000)

        await tentar_reproduzir(pagina)

    except Exception as erro:

        log(
            "[CHROMIUM] Clique:",
            erro
        )

    # --------------------------------------------------------
    # FULLSCREEN
    # --------------------------------------------------------

    try:

        await pagina.evaluate(
            """
            async () => {

                try {

                    if (
                        !document.fullscreenElement &&
                        document.documentElement.requestFullscreen
                    ) {

                        await document.documentElement
                            .requestFullscreen()
                            .catch(() => {});
                    }

                } catch (e) {}
            }
            """
        )

    except Exception:
        pass

    return navegador, pagina


# ============================================================
# MONITOR DO NAVEGADOR
# ============================================================

async def monitorar_navegador(playwright):

    tentativa = 0

    while not encerrando:

        navegador = None
        pagina = None

        try:

            tentativa += 1

            if tentativa > 1:

                log("")
                log(
                    "=========================================================="
                )
                log(
                    f"[CHROMIUM] REINICIANDO NAVEGADOR - tentativa {tentativa}"
                )
                log(
                    "=========================================================="
                )

                await asyncio.sleep(3)

            navegador, pagina = await abrir_navegador(
                playwright
            )

            # ------------------------------------------------
            # Fica monitorando enquanto o navegador estiver vivo
            # ------------------------------------------------

            while navegador.is_connected() and not encerrando:

                await asyncio.sleep(5)

                try:

                    videos = await diagnostico(
                        pagina
                    )

                    # Só tenta play se existir vídeo carregado
                    # e estiver pausado.
                    precisa_play = False

                    for video in videos:

                        if (
                            video.get("readyState", 0) >= 2
                            and
                            video.get("width", 0) > 0
                            and
                            video.get("height", 0) > 0
                            and
                            video.get("paused")
                        ):

                            precisa_play = True
                            break

                    if precisa_play:

                        await tentar_reproduzir(
                            pagina
                        )

                except Exception as erro:

                    log(
                        "[PLAYER MONITOR]",
                        erro
                    )

            log(
                "[CHROMIUM] Navegador fechou."
            )

        except Exception as erro:

            log("")
            log(
                "[CHROMIUM] ERRO:"
            )
            log(
                str(erro)
            )

        finally:

            # ------------------------------------------------
            # Importante:
            # NÃO encerramos FFmpeg aqui.
            # ------------------------------------------------

            try:

                if navegador:

                    await navegador.close()

            except Exception:
                pass

            navegador = None
            pagina = None

        if not encerrando:

            log(
                "[CHROMIUM] O FFmpeg continuara rodando."
            )

            await asyncio.sleep(2)


# ============================================================
# ESPERAR HLS
# ============================================================

async def esperar_hls():

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    log("[6] Aguardando HLS...")

    for i in range(60):

        await asyncio.sleep(1)

        if (
            ffmpeg_process
            and
            ffmpeg_process.poll() is not None
        ):

            raise RuntimeError(
                "FFmpeg encerrou."
            )

        if os.path.exists(playlist):

            if os.path.getsize(playlist) > 20:

                log(
                    "[HLS] live.m3u8 criado."
                )

                return

        if i % 5 == 0:

            log(
                f"[HLS] aguardando... {i}/60"
            )

    raise RuntimeError(
        "HLS nao foi criado."
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_http()

    iniciar_ffmpeg()

    # --------------------------------------------------------
    # O FFmpeg começa ANTES do navegador.
    # --------------------------------------------------------

    await asyncio.sleep(3)

    if ffmpeg_process.poll() is not None:

        raise RuntimeError(
            "FFmpeg morreu."
        )

    # --------------------------------------------------------
    # Garante HLS.
    # --------------------------------------------------------

    await esperar_hls()

    # --------------------------------------------------------
    # LINK PUBLICO.
    # --------------------------------------------------------

    iniciar_tunel()

    # --------------------------------------------------------
    # Chromium.
    # --------------------------------------------------------

    async with async_playwright() as playwright:

        # O monitor NÃO deixa a morte do Chromium derrubar
        # o FFmpeg.
        await monitorar_navegador(
            playwright
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
        log("==========================================================")
        log("ERRO FATAL")
        log("==========================================================")
        log(str(erro))
        log("==========================================================")

        encerrar()
