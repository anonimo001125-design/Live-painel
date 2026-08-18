import os
import sys
import time
import signal
import subprocess
import threading
import asyncio

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
            loop = asyncio.get_event_loop()

            if not loop.is_closed():
                loop.run_until_complete(
                    browser_global.close()
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

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    log("[1] Limpando stream antigo...")

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
                "[AVISO]",
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
            "tcp"
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

    log(
        "Tela virtual:",
        DISPLAY
    )

    log(
        "Resolução:",
        f"{WIDTH}x{HEIGHT}"
    )


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
    os.environ["PULSE_SINK"] = "webtv"

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        check=False
    )

    time.sleep(3)

    teste = subprocess.run(
        [
            "pactl",
            "info"
        ],
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

        log(
            "Criando sink virtual webtv..."
        )

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
                "Não foi possível criar webtv."
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
        "Servidor HTTP ativo:",
        HTTP_PORT
    )


# ============================================================
# TÚNEL
# ============================================================

def iniciar_tunel():

    log("")
    log("[5] Iniciando túnel público...")

    tunnel = subprocess.Popen(
        [
            "ssh",

            "-o",
            "StrictHostKeyChecking=no",

            "-o",
            "ServerAliveInterval=15",

            "-o",
            "ServerAliveCountMax=3",

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

                if (
                    "https://" in linha
                    and
                    "localhost.run" not in linha
                ):

                    partes = linha.split()

                    for parte in partes:

                        if (
                            parte.startswith("https://")
                            and
                            ".lhr.life" in parte
                        ):

                            url = parte.strip(
                                ".,;()[]{}<>\"'"
                            )

                            url = url.rstrip("/")

                            if url != ultimo_url:

                                ultimo_url = url

                                log("")
                                log("=" * 70)
                                log("LINK DA TRANSMISSÃO")
                                log("=" * 70)
                                log("")
                                log("LINK PRINCIPAL:")
                                log(url)
                                log("")
                                log("LINK HLS:")
                                log(
                                    url +
                                    "/live.m3u8"
                                )
                                log("")
                                log("=" * 70)
                                log("")

                            break

        except Exception as erro:

            log(
                "[TUNEL] Erro:",
                erro
            )

    threading.Thread(
        target=ler_tunel,
        daemon=True
    ).start()

    time.sleep(5)


# ============================================================
# DIAGNÓSTICO DOS VÍDEOS
# ============================================================

async def diagnosticar_videos(page):

    try:

        resultado = await page.evaluate(
            """
            () => {

                return Array.from(
                    document.querySelectorAll("video")
                ).map((video, index) => ({

                    index: index,

                    src:
                        video.src || "",

                    currentSrc:
                        video.currentSrc || "",

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
                        video.duration,

                    width:
                        video.videoWidth,

                    height:
                        video.videoHeight

                }));

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
            "[PLAYER] Diagnóstico:",
            erro
        )

        return []


# ============================================================
# INICIAR VÍDEO
# ============================================================

async def iniciar_videos(page):

    log("")
    log(
        "[PLAYER] Inicializando reprodução..."
    )

    try:

        resultado = await page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                const resultados = [];

                for (const video of videos) {

                    try {

                        video.playsInline = true;

                        video.setAttribute(
                            "playsinline",
                            ""
                        );

                        video.autoplay = true;

                        /*
                         * NÃO usamos requestFullscreen aqui.
                         *
                         * Isso não funciona sem gesto real.
                         */

                        let sucesso = false;

                        try {

                            const promessa =
                                video.play();

                            if (promessa) {
                                await promessa;
                            }

                            sucesso = true;

                        } catch (erro) {

                            sucesso = false;
                        }

                        resultados.push({

                            sucesso:
                                sucesso,

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
                                video.currentTime

                        });

                    } catch (erro) {

                        resultados.push({

                            sucesso: false,

                            erro:
                                String(erro)

                        });

                    }

                }

                return resultados;
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
# FULLSCREEN
# ============================================================

async def ativar_fullscreen(page):

    log("")
    log("=" * 70)
    log("[PLAYER] TENTANDO FULLSCREEN")
    log("=" * 70)

    await asyncio.sleep(3)

    try:

        video = await page.querySelector(
            "video"
        )

        if not video:

            log(
                "[PLAYER] Nenhum vídeo encontrado."
            )

            return False

        log(
            "[PLAYER] Vídeo encontrado."
        )

    except Exception as erro:

        log(
            "[PLAYER] Erro procurando vídeo:",
            erro
        )

        return False

    # --------------------------------------------------------
    # DESCOBRIR ELEMENTOS QUE ESTÃO POR CIMA DO VIDEO
    # --------------------------------------------------------

    try:

        elementos = await page.evaluate(
            """
            () => {

                const video =
                    document.querySelector("video");

                if (!video)
                    return [];

                const rect =
                    video.getBoundingClientRect();

                const x =
                    rect.left +
                    rect.width / 2;

                const y =
                    rect.top +
                    rect.height / 2;

                return document.elementsFromPoint(
                    x,
                    y
                ).slice(0, 10).map(
                    element => ({

                        tag:
                            element.tagName,

                        id:
                            element.id || "",

                        className:
                            typeof element.className === "string"
                                ? element.className
                                : "",

                        zIndex:
                            getComputedStyle(element).zIndex,

                        pointerEvents:
                            getComputedStyle(
                                element
                            ).pointerEvents

                    })
                );

            }
            """
        )

        log(
            "[PLAYER] Elementos no centro:",
            elementos
        )

    except Exception as erro:

        log(
            "[PLAYER] Não conseguiu identificar overlay:",
            erro
        )

    # --------------------------------------------------------
    # CLICAR NO CENTRO DA TELA
    #
    # IMPORTANTE:
    #
    # Não usamos video.click().
    #
    # Usamos mouse.click().
    #
    # Isso produz um gesto real do navegador.
    # --------------------------------------------------------

    try:

        log(
            "[PLAYER] Primeiro clique real..."
        )

        await page.mouse.click(
            WIDTH // 2,
            HEIGHT // 2
        )

        await asyncio.sleep(1)

        log(
            "[PLAYER] Segundo clique real..."
        )

        await page.mouse.click(
            WIDTH // 2,
            HEIGHT // 2
        )

        await asyncio.sleep(3)

    except Exception as erro:

        log(
            "[PLAYER] Erro nos cliques:",
            erro
        )

    # --------------------------------------------------------
    # VERIFICAR FULLSCREEN
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

                width:
                    window.innerWidth,

                height:
                    window.innerHeight

            })
            """
        )

        log(
            "[PLAYER] Estado fullscreen:",
            estado
        )

        if estado.get("fullscreen"):

            log(
                "[PLAYER] FULLSCREEN ATIVADO!"
            )

            return True

    except Exception as erro:

        log(
            "[PLAYER] Erro verificando fullscreen:",
            erro
        )

    # --------------------------------------------------------
    # SEGUNDA TENTATIVA:
    #
    # O site pode ter seu próprio botão fullscreen.
    #
    # Procuramos botões comuns.
    # --------------------------------------------------------

    seletores = [

        "button[aria-label*='fullscreen' i]",

        "button[title*='fullscreen' i]",

        "[aria-label*='fullscreen' i]",

        "[title*='fullscreen' i]",

        "button[data-testid*='fullscreen' i]",

        "[data-testid*='fullscreen' i]"

    ]

    for seletor in seletores:

        try:

            botoes = await page.querySelectorAll(
                seletor
            )

            if not botoes:
                continue

            log(
                "[PLAYER] Encontrado controle:",
                seletor
            )

            for botao in botoes:

                try:

                    await botao.click()

                    await asyncio.sleep(3)

                    estado = await page.evaluate(
                        """
                        () => ({
                            fullscreen:
                                !!document.fullscreenElement
                        })
                        """
                    )

                    if estado["fullscreen"]:

                        log(
                            "[PLAYER] FULLSCREEN ATIVADO PELO CONTROLE!"
                        )

                        return True

                except Exception:
                    pass

        except Exception:
            pass

    log(
        "[PLAYER] Não foi possível ativar fullscreen."
    )

    return False


# ============================================================
# MANTER REPRODUÇÃO
# ============================================================

async def monitorar_player(page):

    ultimo_tempo = None
    paradas = 0

    while True:

        try:

            await asyncio.sleep(10)

            videos = await page.evaluate(
                """
                () => Array.from(
                    document.querySelectorAll("video")
                ).map(v => ({

                    paused:
                        v.paused,

                    ended:
                        v.ended,

                    currentTime:
                        v.currentTime,

                    readyState:
                        v.readyState,

                    width:
                        v.videoWidth,

                    height:
                        v.videoHeight

                }))
                """
            )

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

            if ultimo_tempo is not None:

                diferenca = tempo - ultimo_tempo

                if diferenca < 0.5:

                    paradas += 1

                else:

                    paradas = 0

            ultimo_tempo = tempo

            if paradas >= 3:

                log(
                    "[PLAYER] Vídeo parece travado. Tentando play novamente..."
                )

                try:

                    await page.evaluate(
                        """
                        () => {

                            const videos =
                                document.querySelectorAll(
                                    "video"
                                );

                            for (const video of videos) {

                                if (
                                    video.videoWidth > 0
                                    &&
                                    video.videoHeight > 0
                                ) {

                                    video.play()
                                        .catch(() => {});

                                }

                            }

                        }
                        """
                    )

                except Exception:
                    pass

                paradas = 0

        except Exception as erro:

            log(
                "[PLAYER] Monitor:",
                erro
            )


# ============================================================
# CHROMIUM
# ============================================================

async def abrir_navegador():

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

        handleSIGINT=False,

        handleSIGTERM=False,

        handleSIGHUP=False,

        args=[

            "--no-sandbox",

            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",

            # X11
            "--ozone-platform=x11",

            # Janela
            "--start-maximized",

            "--window-size=1280,720",

            "--window-position=0,0",

            "--force-device-scale-factor=1",

            # Autoplay
            "--autoplay-policy=no-user-gesture-required",

            # Evitar economia de recursos
            "--disable-background-timer-throttling",

            "--disable-backgrounding-occluded-windows",

            "--disable-renderer-backgrounding",

            "--disable-background-networking",

            # Estabilidade
            "--no-first-run",

            "--no-default-browser-check",

            "--disable-popup-blocking",

            "--disable-notifications",

            "--disable-infobars",

            # Renderização
            "--use-gl=swiftshader",

            "--disable-gpu-compositing",

            "--disable-gpu-rasterization"

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

    page.on(
        "pageerror",
        lambda erro:
            log(
                "[PAGE ERROR]",
                erro
            )
    )

    # --------------------------------------------------------
    # ABRIR SITE
    # --------------------------------------------------------

    log("")
    log(
        "Abrindo página:"
    )

    log(
        URL_ALVO
    )

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
            "[AVISO] Navegação:",
            erro
        )

    log(
        "Aguardando página..."
    )

    await asyncio.sleep(8)

    # --------------------------------------------------------
    # VÍDEOS
    # --------------------------------------------------------

    await iniciar_videos(
        page
    )

    await asyncio.sleep(3)

    await diagnosticar_videos(
        page
    )

    # --------------------------------------------------------
    # AGUARDAR VÍDEO
    # --------------------------------------------------------

    carregado = False

    for tentativa in range(12):

        await asyncio.sleep(2)

        videos = await diagnosticar_videos(
            page
        )

        for video in videos:

            if (
                video.get("readyState", 0) >= 2
                and
                video.get("width", 0) > 0
                and
                video.get("height", 0) > 0
            ):

                carregado = True
                break

        if carregado:
            break

    if carregado:

        log(
            "[PLAYER] Vídeo pronto."
        )

    else:

        log(
            "[PLAYER] AVISO: vídeo ainda não confirmou dimensões."
        )

    # --------------------------------------------------------
    # FULLSCREEN
    # --------------------------------------------------------

    await ativar_fullscreen(
        page
    )

    # --------------------------------------------------------
    # MONITORAR PLAYER
    # --------------------------------------------------------

    asyncio.create_task(
        monitorar_player(page)
    )

    # --------------------------------------------------------
    # NÃO FECHAR O NAVEGADOR
    # --------------------------------------------------------

    while True:

        try:

            if browser.process is None:
                break

        except Exception:
            pass

        await asyncio.sleep(10)


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
        # AUDIO
        # ====================================================

        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ====================================================
        # VIDEO
        # ====================================================

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

        # ====================================================
        # QUALIDADE
        # ====================================================

        "-b:v",
        "2200k",

        "-maxrate",
        "2500k",

        "-bufsize",
        "5000k",

        # ====================================================
        # AUDIO
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
        comando
    )

    time.sleep(6)

    if ffmpeg_global.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log(
        "FFmpeg funcionando."
    )


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

    # --------------------------------------------------------
    # IMPORTANTE:
    #
    # O Chromium precisa estar rodando ANTES do FFmpeg.
    # --------------------------------------------------------

    tarefa_browser = asyncio.create_task(
        abrir_navegador()
    )

    # Dá tempo para o player aparecer.
    await asyncio.sleep(18)

    # --------------------------------------------------------
    # FFmpeg captura a tela inteira.
    # --------------------------------------------------------

    iniciar_ffmpeg()

    log("")
    log("=" * 70)
    log("TRANSMISSÃO ATIVA")
    log("=" * 70)
    log("")
    log(
        "O FFmpeg está capturando:",
        f"{WIDTH}x{HEIGHT}",
        f"{FPS} FPS"
    )
    log("")
    log(
        "O navegador continuará reproduzindo a página."
    )
    log("")

    try:

        await tarefa_browser

    except asyncio.CancelledError:

        pass


# ============================================================
# EXECUÇÃO
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
