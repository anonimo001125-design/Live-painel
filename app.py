import os
import sys
import time
import signal
import subprocess
import threading
import asyncio
import re

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
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

# Bitrate mais leve para melhorar reprodução em Wi-Fi 2.4 GHz
VIDEO_BITRATE = "1800k"
VIDEO_MAXRATE = "2200k"
VIDEO_BUFSIZE = "4400k"

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

    log("[1] Limpando stream antigo...")

    os.makedirs(STREAM_DIR, exist_ok=True)

    for arquivo in os.listdir(STREAM_DIR):

        caminho = os.path.join(
            STREAM_DIR,
            arquivo
        )

        try:

            if os.path.isfile(caminho):
                os.remove(caminho)

        except Exception as erro:

            log(
                "[AVISO] Não foi possível remover:",
                caminho,
                erro
            )


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("")
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
            "+extension",
            "RANDR"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(xvfb)

    time.sleep(3)

    if xvfb.poll() is not None:
        raise RuntimeError(
            "Xvfb não conseguiu iniciar."
        )

    log("DISPLAY:", DISPLAY)
    log("RESOLUÇÃO:", f"{WIDTH}x{HEIGHT}")
    log("Xvfb pronto.")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("")
    log("[3] Iniciando PulseAudio...")

    runtime = "/tmp/pulse"

    os.makedirs(
        runtime,
        exist_ok=True
    )

    os.environ["PULSE_RUNTIME_PATH"] = runtime

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1",
            "--daemonize=yes"
        ],
        check=False
    )

    time.sleep(3)

    teste = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True
    )

    if teste.returncode != 0:

        log(teste.stderr)

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

            log(resultado.stdout)
            log(resultado.stderr)

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

    log("")
    log("Fontes de áudio:")
    log(fontes.stdout)

    if "webtv.monitor" not in fontes.stdout:

        raise RuntimeError(
            "webtv.monitor não foi encontrado."
        )

    log("Áudio pronto.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():

    log("")
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
# TÚNEL LOCALHOST.RUN
# ============================================================

def iniciar_tunel():

    global tunnel_global

    log("")
    log("[5] Iniciando túnel localhost.run...")
    log("")

    tunnel = subprocess.Popen(
        [
            "ssh",

            "-T",

            "-o",
            "StrictHostKeyChecking=no",

            "-o",
            "UserKnownHostsFile=/dev/null",

            "-o",
            "ServerAliveInterval=15",

            "-o",
            "ServerAliveCountMax=5",

            "-o",
            "TCPKeepAlive=yes",

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

    tunnel_global = tunnel

    processos.append(tunnel)

    def ler_tunel():

        ultimo_url = None

        try:

            for linha in iter(
                tunnel.stdout.readline,
                ""
            ):

                if not linha:
                    continue

                linha = linha.strip()

                log(
                    "[TUNEL]",
                    linha
                )

                # ------------------------------------------------
                # IMPORTANTE:
                #
                # NÃO pegar admin.localhost.run.
                #
                # O endereço real normalmente termina em
                # .lhr.life
                # ------------------------------------------------

                encontrados = re.findall(
                    r"https://[A-Za-z0-9.-]+\.lhr\.life",
                    linha
                )

                for url in encontrados:

                    if url == ultimo_url:
                        continue

                    ultimo_url = url

                    log("")
                    log("=" * 70)
                    log("           LINK DA TRANSMISSÃO")
                    log("=" * 70)
                    log("")
                    log("LINK PRINCIPAL:")
                    log(url)
                    log("")
                    log("LINK HLS:")
                    log(
                        url.rstrip("/") +
                        "/live.m3u8"
                    )
                    log("")
                    log("=" * 70)
                    log("")

        except Exception as erro:

            log(
                "[TUNEL] Erro:",
                erro
            )

    threading.Thread(
        target=ler_tunel,
        daemon=True
    ).start()

    # Aguarda o túnel
    time.sleep(8)

    if tunnel.poll() is not None:

        raise RuntimeError(
            "O túnel encerrou antes de ficar disponível."
        )


# ============================================================
# DIAGNÓSTICO DA TELA
# ============================================================

def testar_tela():

    log("")
    log("[DIAGNÓSTICO] Testando X11...")

    arquivo = os.path.join(
        STREAM_DIR,
        "debug_screen.png"
    )

    resultado = subprocess.run(
        [
            "ffmpeg",
            "-y",

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

        stdout=subprocess.DEVNULL,

        stderr=subprocess.PIPE,

        text=True
    )

    if resultado.returncode == 0:

        log(
            "[DIAGNÓSTICO] Captura OK:",
            arquivo
        )

    else:

        log(
            "[DIAGNÓSTICO] Erro X11:",
            resultado.stderr[-2000:]
        )


# ============================================================
# DIAGNÓSTICO DOS VÍDEOS
# ============================================================

async def diagnosticar_videos(page):

    try:

        resultado = await page.evaluate(
            """
            () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                return videos.map(
                    (v, i) => ({

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
                            v.videoHeight

                    })
                );
            }
            """
        )

        log(
            "[PLAYER] Vídeos:",
            resultado
        )

        return resultado

    except Exception as erro:

        log(
            "[PLAYER] Erro diagnóstico:",
            erro
        )

        return []


# ============================================================
# INICIAR VÍDEO
# ============================================================

async def iniciar_videos(page):

    log("")
    log("[PLAYER] Inicializando reprodução...")

    try:

        resultado = await page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                const saida = [];

                for (const video of videos) {

                    try {

                        video.autoplay = true;
                        video.playsInline = true;

                        if (
                            video.readyState === 0 &&
                            typeof video.load === "function"
                        ) {
                            video.load();
                        }

                        let estado = "ok";

                        try {

                            const p = video.play();

                            if (p) {
                                await p;
                            }

                        } catch (e) {

                            estado = String(e);
                        }

                        saida.push({

                            paused:
                                video.paused,

                            muted:
                                video.muted,

                            readyState:
                                video.readyState,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight,

                            currentTime:
                                video.currentTime,

                            estado:
                                estado
                        });

                    } catch (e) {

                        saida.push({
                            erro: String(e)
                        });
                    }
                }

                return saida;
            }
            """
        )

        log(
            "[PLAYER] Resultado:",
            resultado
        )

    except Exception as erro:

        log(
            "[PLAYER] Erro:",
            erro
        )


# ============================================================
# ESPERAR VÍDEO
# ============================================================

async def esperar_video(page):

    log("")
    log("[PLAYER] Aguardando vídeo...")

    for tentativa in range(1, 13):

        await asyncio.sleep(3)

        videos = await diagnosticar_videos(
            page
        )

        for video in videos:

            if (
                video.get("readyState", 0) >= 3
                and
                video.get("width", 0) > 0
                and
                video.get("height", 0) > 0
            ):

                log("")
                log(
                    "[PLAYER] VÍDEO PRONTO."
                )

                return True

        log(
            "[PLAYER] Aguardando...",
            tentativa,
            "/ 12"
        )

    return False


# ============================================================
# CLICAR USANDO XDOTool
# ============================================================

def clique_real_x11():

    log("")
    log("=" * 70)
    log("[FULLSCREEN] Executando clique real no X11")
    log("=" * 70)

    centro_x = WIDTH // 2
    centro_y = HEIGHT // 2

    try:

        # Move o mouse para dentro do vídeo
        subprocess.run(
            [
                "xdotool",
                "mousemove",
                str(centro_x),
                str(centro_y)
            ],
            check=False
        )

        time.sleep(0.5)

        # Primeiro clique
        log("[FULLSCREEN] Primeiro clique...")

        subprocess.run(
            [
                "xdotool",
                "click",
                "1"
            ],
            check=False
        )

        time.sleep(0.8)

        # Segundo clique
        #
        # O site que você mostrou nos logs reage melhor
        # quando recebe dois cliques.
        #
        log("[FULLSCREEN] Segundo clique...")

        subprocess.run(
            [
                "xdotool",
                "click",
                "1"
            ],
            check=False
        )

        time.sleep(3)

        return True

    except Exception as erro:

        log(
            "[FULLSCREEN] Erro xdotool:",
            erro
        )

        return False


# ============================================================
# FULLSCREEN
# ============================================================

async def ativar_fullscreen(page):

    log("")
    log("=" * 70)
    log("[FULLSCREEN] TENTANDO FULLSCREEN")
    log("=" * 70)

    # --------------------------------------------------------
    # Primeiro garante que existe vídeo
    # --------------------------------------------------------

    try:

        await page.waitForSelector(
            "video",
            {
                "visible": True,
                "timeout": 30000
            }
        )

        log(
            "[FULLSCREEN] Vídeo encontrado."
        )

    except Exception as erro:

        log(
            "[FULLSCREEN] Vídeo não encontrado:",
            erro
        )

    await asyncio.sleep(2)

    # --------------------------------------------------------
    # Descobre onde o vídeo está
    # --------------------------------------------------------

    try:

        caixa = await page.evaluate(
            """
            () => {

                const v =
                    document.querySelector("video");

                if (!v) return null;

                const r =
                    v.getBoundingClientRect();

                return {

                    x: r.x,
                    y: r.y,
                    width: r.width,
                    height: r.height

                };
            }
            """
        )

        log(
            "[FULLSCREEN] Área:",
            caixa
        )

    except Exception:

        caixa = None

    # --------------------------------------------------------
    # Clique físico através do X11
    # --------------------------------------------------------

    clique_real_x11()

    await asyncio.sleep(2)

    # --------------------------------------------------------
    # Verifica fullscreen
    # --------------------------------------------------------

    try:

        estado = await page.evaluate(
            """
            () => ({

                fullscreen:
                    !!document.fullscreenElement,

                fullscreenTag:
                    document.fullscreenElement
                        ? document.fullscreenElement.tagName
                        : null,

                innerWidth:
                    window.innerWidth,

                innerHeight:
                    window.innerHeight

            })
            """
        )

        log(
            "[FULLSCREEN] Estado:",
            estado
        )

        if estado.get("fullscreen"):

            log(
                "[FULLSCREEN] SUCESSO!"
            )

            return True

    except Exception as erro:

        log(
            "[FULLSCREEN] Erro verificando:",
            erro
        )

    # --------------------------------------------------------
    # Se o site não ativou o fullscreen,
    # mantemos o Chromium em kiosk.
    #
    # Assim o FFmpeg ainda captura a página inteira
    # em 1280x720.
    # --------------------------------------------------------

    log(
        "[FULLSCREEN] O site não informou fullscreen."
    )

    log(
        "[FULLSCREEN] Chromium continuará em modo kiosk."
    )

    return False


# ============================================================
# CHROMIUM
# ============================================================

async def iniciar_navegador():

    global browser_global
    global page_global

    log("")
    log("[6] Iniciando Chromium...")
    log("")

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

            # =================================================
            # X11
            # =================================================

            "--ozone-platform=x11",

            # =================================================
            # KIOSK
            # =================================================

            "--kiosk",

            "--start-maximized",

            # =================================================
            # RENDERIZAÇÃO
            # =================================================

            "--use-gl=swiftshader",

            "--disable-gpu",

            "--disable-gpu-compositing",

            "--disable-gpu-rasterization",

            "--disable-accelerated-video-decode",

            "--disable-accelerated-video-encode",

            # =================================================
            # PLAYER
            # =================================================

            "--autoplay-policy=no-user-gesture-required",

            "--disable-features=MediaSessionService",

            # =================================================
            # ESTABILIDADE
            # =================================================

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

            # =================================================
            # MEMÓRIA
            # =================================================

            "--disk-cache-size=104857600",

            "--media-cache-size=52428800",

            # =================================================
            # JANELA
            # =================================================

            "--window-size=1280,720",

            "--window-position=0,0",

            "--force-device-scale-factor=1"
        ]
    )

    browser_global = browser

    log(
        "Chromium iniciado."
    )

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
    # LOGS
    # ========================================================

    page.on(
        "console",
        lambda mensagem:
            log(
                "[CONSOLE]",
                mensagem.text
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

    # ========================================================
    # ABRIR SITE
    # ========================================================

    log("")
    log("Abrindo página:")
    log(URL_ALVO)

    try:

        await page.goto(
            URL_ALVO,
            {
                "waitUntil": "domcontentloaded",
                "timeout": 120000
            }
        )

    except Exception as erro:

        log(
            "[AVISO] goto:",
            erro
        )

    log(
        "Aguardando página..."
    )

    await asyncio.sleep(8)

    # ========================================================
    # INICIA VÍDEOS
    # ========================================================

    await iniciar_videos(
        page
    )

    await asyncio.sleep(2)

    await esperar_video(
        page
    )

    # ========================================================
    # TENTATIVA DE FULLSCREEN
    # ========================================================

    await ativar_fullscreen(
        page
    )

    # ========================================================
    # DIAGNÓSTICO FINAL
    # ========================================================

    await asyncio.sleep(2)

    await diagnosticar_videos(
        page
    )

    log("")
    log(
        "[CHROMIUM] Página pronta para captura."
    )


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_global

    log("")
    log("=" * 70)
    log("INICIANDO FFMPEG")
    log("=" * 70)

    saida = os.path.join(
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
        # X11
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
        # VÍDEO
        # ====================================================

        "-c:v",
        "libx264",

        "-preset",
        "ultrafast",

        "-tune",
        "zerolatency",

        "-pix_fmt",
        "yuv420p",

        "-profile:v",
        "main",

        "-level",
        "3.1",

        "-b:v",
        VIDEO_BITRATE,

        "-maxrate",
        VIDEO_MAXRATE,

        "-bufsize",
        VIDEO_BUFSIZE,

        "-r",
        str(FPS),

        "-g",
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

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
        "4",

        "-hls_list_size",
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        segmento,

        saida
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
        stderr=None
    )

    time.sleep(5)

    if ffmpeg_global.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log("")
    log(
        "FFmpeg funcionando."
    )


# ============================================================
# MONITORAR FFMPEG
# ============================================================

def monitorar_ffmpeg():

    while True:

        time.sleep(10)

        if ffmpeg_global is None:
            continue

        if ffmpeg_global.poll() is not None:

            log("")
            log(
                "[FFMPEG] PROCESSO ENCERRADO!"
            )

            return


# ============================================================
# MONITORAR TÚNEL
# ============================================================

def monitorar_tunel():

    while True:

        time.sleep(15)

        if tunnel_global is None:
            continue

        if tunnel_global.poll() is not None:

            log("")
            log(
                "[TUNEL] CONEXÃO ENCERRADA!"
            )

            return


# ============================================================
# MAIN
# ============================================================

async def main_async():

    log("")
    log("=" * 70)
    log("WEBTV STREAM")
    log("=" * 70)

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_tunel()

    # Diagnóstico X11
    testar_tela()

    # Chromium
    await iniciar_navegador()

    # Pequeno intervalo para estabilizar a página
    await asyncio.sleep(3)

    # FFmpeg
    iniciar_ffmpeg()

    threading.Thread(
        target=monitorar_ffmpeg,
        daemon=True
    ).start()

    threading.Thread(
        target=monitorar_tunel,
        daemon=True
    ).start()

    log("")
    log("=" * 70)
    log("TRANSMISSÃO ATIVA")
    log("=" * 70)
    log("")
    log(
        "A página está sendo capturada em",
        f"{WIDTH}x{HEIGHT}@{FPS}fps"
    )
    log(
        "HLS:",
        os.path.join(STREAM_DIR, "live.m3u8")
    )
    log("")
    log("=" * 70)

    # Mantém o processo vivo
    while True:

        await asyncio.sleep(10)

        if ffmpeg_global:

            if ffmpeg_global.poll() is not None:

                log(
                    "[ERRO] FFmpeg encerrou."
                )

                break

        if tunnel_global:

            if tunnel_global.poll() is not None:

                log(
                    "[ERRO] Túnel encerrou."
                )

                break


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
        log(
            repr(erro)
        )

        encerrar()


if __name__ == "__main__":

    main()
