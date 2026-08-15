import os
import time
import subprocess
import asyncio
import threading
import signal
import sys

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


# ============================================================
# PROCESSOS
# ============================================================

processos = []

browser_global = None
ffmpeg_global = None


# ============================================================
# LOG
# ============================================================

# IMPORTANTE:
# Aceita 1 ou vários argumentos.
# Corrige o erro:
# TypeError: log() takes 1 positional argument but 2 were given
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    log("")
    log("==========================================================")
    log("ENCERRANDO TRANSMISSÃO")
    log("==========================================================")

    global browser_global
    global ffmpeg_global

    # --------------------------------------------------------
    # FFmpeg
    # --------------------------------------------------------

    try:

        if ffmpeg_global:
            if ffmpeg_global.poll() is None:
                ffmpeg_global.terminate()

    except Exception:
        pass

    # --------------------------------------------------------
    # Chromium
    # --------------------------------------------------------

    try:

        if browser_global:
            # O Chromium será encerrado pelo processo pai
            # caso ainda esteja ativo.
            pass

    except Exception:
        pass

    # --------------------------------------------------------
    # Outros processos
    # --------------------------------------------------------

    for processo in processos:

        try:

            if processo.poll() is None:
                processo.terminate()

        except Exception:
            pass

    time.sleep(2)

    # --------------------------------------------------------
    # Força encerramento
    # --------------------------------------------------------

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

        except Exception as erro:

            log(
                "[AVISO] Não foi possível remover:",
                caminho,
                erro
            )


# ============================================================
# Xvfb
# ============================================================

def iniciar_xvfb():

    log("")
    log("[2] Iniciando tela virtual Xvfb...")

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
            "Xvfb encerrou imediatamente."
        )

    log("Tela virtual pronta.")
    log("DISPLAY:", DISPLAY)
    log("RESOLUÇÃO:", f"{WIDTH}x{HEIGHT}")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("")
    log("[3] Iniciando PulseAudio...")

    pulse_runtime = "/tmp/pulse"

    os.environ["PULSE_RUNTIME_PATH"] = pulse_runtime

    os.makedirs(
        pulse_runtime,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Sink padrão do Chromium
    # --------------------------------------------------------

    os.environ["PULSE_SINK"] = "webtv"

    # --------------------------------------------------------
    # Inicia PulseAudio
    # --------------------------------------------------------

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
    # Verifica se PulseAudio está funcionando
    # --------------------------------------------------------

    pulse_check = subprocess.run(
        [
            "pactl",
            "info"
        ],
        capture_output=True,
        text=True
    )

    if pulse_check.returncode != 0:

        log(
            "[ERRO] PulseAudio não está disponível."
        )

        log(
            pulse_check.stderr
        )

        raise RuntimeError(
            "PulseAudio não iniciou corretamente."
        )

    # --------------------------------------------------------
    # Verifica se o sink já existe
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

    sink_existe = (
        "webtv" in sinks.stdout
    )

    # --------------------------------------------------------
    # Cria sink virtual
    # --------------------------------------------------------

    if not sink_existe:

        log("Criando sink virtual WebTV...")

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

            log(
                "[ERRO] Não foi possível criar "
                "o sink WebTV."
            )

            log(resultado.stdout)
            log(resultado.stderr)

            raise RuntimeError(
                "Falha ao criar sink PulseAudio."
            )

    else:

        log("Sink WebTV já existe.")

    # --------------------------------------------------------
    # Define sink padrão
    # --------------------------------------------------------

    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        check=False
    )

    # --------------------------------------------------------
    # Verifica monitor
    # --------------------------------------------------------

    monitors = subprocess.run(
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
    log("Fontes PulseAudio:")
    log(monitors.stdout)

    if "webtv.monitor" not in monitors.stdout:

        raise RuntimeError(
            "webtv.monitor não foi criado."
        )

    log("Áudio virtual pronto.")
    log("Sink: webtv")
    log("Monitor: webtv.monitor")


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
        "Servidor HTTP funcionando na porta",
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
            "ServerAliveInterval=30",

            "-o",
            "ServerAliveCountMax=3",

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

        try:

            for linha in iter(
                tunnel.stdout.readline,
                ""
            ):

                if linha:

                    linha = linha.strip()

                    log(
                        "[TUNEL]",
                        linha
                    )

                    # ------------------------------------------------
                    # Procura URL pública
                    # ------------------------------------------------

                    if "https://" in linha:

                        inicio = linha.find(
                            "https://"
                        )

                        url = linha[inicio:].split()[0]

                        log("")
                        log(
                            "=========================================================="
                        )
                        log(
                            "URL PÚBLICA DO STREAM"
                        )
                        log(url)
                        log("")
                        log(
                            "PLAYLIST HLS"
                        )
                        log(
                            url.rstrip("/") +
                            "/live.m3u8"
                        )
                        log(
                            "=========================================================="
                        )
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

    time.sleep(5)


# ============================================================
# TESTE X11
# ============================================================

def testar_tela():

    log("")
    log("[DIAGNÓSTICO] Testando captura do Xvfb...")

    arquivo_teste = os.path.join(
        STREAM_DIR,
        "debug_screen.png"
    )

    comando = [

        "ffmpeg",

        "-y",

        "-f",
        "x11grab",

        "-draw_mouse",
        "0",

        "-video_size",
        f"{WIDTH}x{HEIGHT}",

        "-framerate",
        "1",

        "-i",
        f"{DISPLAY}.0",

        "-frames:v",
        "1",

        arquivo_teste
    ]

    resultado = subprocess.run(
        comando,

        stdout=subprocess.PIPE,

        stderr=subprocess.PIPE,

        text=True
    )

    if resultado.returncode == 0:

        log(
            "[DIAGNÓSTICO] Captura criada:"
        )

        log(
            arquivo_teste
        )

    else:

        log(
            "[DIAGNÓSTICO] Erro na captura:"
        )

        log(
            resultado.stderr[-3000:]
        )


# ============================================================
# CHROMIUM
# ============================================================

async def abrir_navegador():

    global browser_global

    log("")
    log("[6] Iniciando Chromium...")
    log("")

    # --------------------------------------------------------
    # Ambiente
    # --------------------------------------------------------

    ambiente = os.environ.copy()

    ambiente["DISPLAY"] = DISPLAY

    ambiente["PULSE_SINK"] = "webtv"

    # --------------------------------------------------------
    # Chromium
    # --------------------------------------------------------

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

            # ------------------------------------------------
            # SANDBOX
            # ------------------------------------------------

            "--no-sandbox",

            "--disable-setuid-sandbox",

            # ------------------------------------------------
            # MEMÓRIA
            # ------------------------------------------------

            "--disable-dev-shm-usage",

            # ------------------------------------------------
            # GPU
            # ------------------------------------------------

            "--disable-gpu",

            "--disable-gpu-compositing",

            # NÃO desabilitamos o software rasterizer.
            # Isso ajuda a evitar tela preta no Xvfb.

            # ------------------------------------------------
            # AUTOPLAY
            # ------------------------------------------------

            "--autoplay-policy=no-user-gesture-required",

            # ------------------------------------------------
            # TELA
            # ------------------------------------------------

            "--window-size=1280,720",

            "--start-fullscreen",

            "--force-device-scale-factor=1",

            "--kiosk",

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
            # VÍDEO
            # ------------------------------------------------

            "--enable-features=NetworkService,NetworkServiceInProcess",

            "--disable-features=Translate"
        ]
    )

    browser_global = browser

    log(
        "Chromium iniciado."
    )

    # --------------------------------------------------------
    # Nova página
    # --------------------------------------------------------

    page = await browser.newPage()

    await page.setViewport(
        {
            "width": WIDTH,
            "height": HEIGHT
        }
    )

    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    log("")
    log(
        "Abrindo painel da Web TV..."
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

        log(
            "Painel carregado."
        )

    except Exception as erro:

        log("")
        log(
            "ERRO AO ABRIR O PAINEL:"
        )

        log(
            erro
        )

        log("")

    # --------------------------------------------------------
    # Aguarda renderização
    # --------------------------------------------------------

    log("")
    log(
        "Aguardando painel renderizar..."
    )

    await asyncio.sleep(15)

    # --------------------------------------------------------
    # Verifica página
    # --------------------------------------------------------

    try:

        titulo = await page.title()

        log(
            "[CHROMIUM] Título:",
            titulo
        )

    except Exception as erro:

        log(
            "[CHROMIUM] Não foi possível "
            "obter título:",
            erro
        )

    # --------------------------------------------------------
    # Verifica vídeos
    # --------------------------------------------------------

    try:

        resultado = await page.evaluate(
            """
            () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                const informacoes =
                    videos.map((video, index) => {

                        return {
                            index: index,
                            paused: video.paused,
                            ended: video.ended,
                            muted: video.muted,
                            readyState: video.readyState,
                            currentTime: video.currentTime,
                            width: video.videoWidth,
                            height: video.videoHeight
                        };

                    });

                return {
                    quantidade: videos.length,
                    videos: informacoes
                };
            }
            """
        )

        log("")
        log(
            "[CHROMIUM] Vídeos encontrados:",
            resultado
        )

    except Exception as erro:

        log(
            "[CHROMIUM] Erro ao verificar vídeos:",
            erro
        )

    # --------------------------------------------------------
    # Tenta iniciar vídeos HTML5
    # --------------------------------------------------------

    try:

        resultado_play = await page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                let tentativas = 0;

                for (const video of videos) {

                    try {

                        video.autoplay = true;

                        video.playsInline = true;

                        video.muted = false;

                        const promessa =
                            video.play();

                        if (promessa) {
                            await promessa.catch(() => {});
                        }

                        tentativas++;

                    } catch (e) {}

                }

                return {
                    videos: videos.length,
                    tentativas: tentativas
                };
            }
            """
        )

        log(
            "[CHROMIUM] Tentativa de reprodução:",
            resultado_play
        )

    except Exception as erro:

        log(
            "[CHROMIUM] Erro ao iniciar vídeos:",
            erro
        )

    # --------------------------------------------------------
    # Screenshot do navegador
    # --------------------------------------------------------

    try:

        caminho_browser = os.path.join(
            STREAM_DIR,
            "browser_debug.png"
        )

        await page.screenshot(
            {
                "path": caminho_browser,

                "fullPage": False
            }
        )

        log(
            "[CHROMIUM] Screenshot salvo:",
            caminho_browser
        )

    except Exception as erro:

        log(
            "[CHROMIUM] Erro no screenshot:",
            erro
        )

    # --------------------------------------------------------
    # Testa Xvfb
    # --------------------------------------------------------

    testar_tela()

    log("")
    log(
        "=========================================================="
    )
    log(
        "PAINEL CARREGADO"
    )
    log(
        "Chromium está rodando dentro do Xvfb."
    )
    log(
        "Captura X11 foi testada."
    )
    log(
        "=========================================================="
    )
    log("")

    # --------------------------------------------------------
    # Mantém Chromium vivo
    # --------------------------------------------------------

    while True:

        await asyncio.sleep(30)

        try:

            titulo = await page.title()

            log(
                "[CHROMIUM] Página ativa:",
                titulo
            )

        except Exception as erro:

            log(
                "[CHROMIUM] Erro na página:",
                erro
            )

            # ------------------------------------------------
            # Tenta recarregar
            # ------------------------------------------------

            try:

                log(
                    "[CHROMIUM] Tentando recarregar..."
                )

                await page.goto(
                    URL_ALVO,

                    {
                        "waitUntil": "domcontentloaded",

                        "timeout": 120000
                    }
                )

                await asyncio.sleep(10)

            except Exception as erro2:

                log(
                    "[CHROMIUM] Falha ao recarregar:",
                    erro2
                )


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_global

    log("")
    log(
        "[7] Iniciando FFmpeg..."
    )
    log("")

    ffmpeg_cmd = [

        "ffmpeg",

        "-y",

        # ====================================================
        # VÍDEO
        # ====================================================

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

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ====================================================
        # VÍDEO H264
        # ====================================================

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-tune",
        "zerolatency",

        "-pix_fmt",
        "yuv420p",

        "-profile:v",
        "main",

        "-level",
        "3.1",

        "-r",
        str(FPS),

        "-g",
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        # ====================================================
        # ÁUDIO AAC
        # ====================================================

        "-c:a",
        "aac",

        "-b:a",
        "128k",

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
        "5",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        f"{STREAM_DIR}/segment_%05d.ts",

        f"{STREAM_DIR}/live.m3u8"
    ]

    log(
        "Comando FFmpeg:"
    )

    log(
        " ".join(ffmpeg_cmd)
    )

    log("")

    # --------------------------------------------------------
    # Inicia FFmpeg
    # --------------------------------------------------------

    ffmpeg_global = subprocess.Popen(

        ffmpeg_cmd,

        stdout=subprocess.PIPE,

        stderr=subprocess.STDOUT,

        text=True,

        bufsize=1
    )

    processos.append(
        ffmpeg_global
    )

    # --------------------------------------------------------
    # Lê log
    # --------------------------------------------------------

    def ler_ffmpeg():

        try:

            for linha in iter(
                ffmpeg_global.stdout.readline,
                ""
            ):

                if linha:

                    log(
                        "[FFMPEG]",
                        linha.strip()
                    )

        except Exception:
            pass

    threading.Thread(
        target=ler_ffmpeg,
        daemon=True
    ).start()

    # --------------------------------------------------------
    # Aguarda FFmpeg
    # --------------------------------------------------------

    time.sleep(5)

    if ffmpeg_global.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou logo após iniciar."
        )

    log("")
    log(
        "=========================================================="
    )
    log(
        "TRANSMISSÃO INICIADA"
    )
    log(
        "=========================================================="
    )
    log("")


# ============================================================
# MONITOR HLS
# ============================================================

def monitorar_hls():

    def monitor():

        ultimo_tamanho = 0

        while True:

            time.sleep(10)

            playlist = os.path.join(
                STREAM_DIR,
                "live.m3u8"
            )

            if not os.path.exists(playlist):

                log(
                    "[HLS] Aguardando live.m3u8..."
                )

                continue

            try:

                tamanho = os.path.getsize(
                    playlist
                )

            except Exception:

                continue

            if tamanho == ultimo_tamanho:

                log(
                    "[HLS] AVISO: playlist "
                    "não está mudando."
                )

            else:

                log(
                    "[HLS] Playlist funcionando.",
                    "Tamanho:",
                    tamanho,
                    "bytes"
                )

            ultimo_tamanho = tamanho

            segmentos = [

                arquivo

                for arquivo in os.listdir(
                    STREAM_DIR
                )

                if arquivo.endswith(".ts")
            ]

            log(
                "[HLS] Segmentos disponíveis:",
                len(segmentos)
            )

    threading.Thread(
        target=monitor,
        daemon=True
    ).start()


# ============================================================
# MAIN
# ============================================================

def iniciar():

    log("")
    log(
        "=========================================================="
    )
    log(
        "                 INICIANDO WEB TV"
    )
    log(
        "=========================================================="
    )
    log("")

    try:

        # ----------------------------------------------------
        # 1. Stream
        # ----------------------------------------------------

        limpar_stream()

        # ----------------------------------------------------
        # 2. Xvfb
        # ----------------------------------------------------

        iniciar_xvfb()

        # ----------------------------------------------------
        # 3. Áudio
        # ----------------------------------------------------

        iniciar_audio()

        # ----------------------------------------------------
        # 4. HTTP
        # ----------------------------------------------------

        iniciar_servidor()

        # ----------------------------------------------------
        # 5. Túnel
        # ----------------------------------------------------

        iniciar_tunel()

        # ----------------------------------------------------
        # 6. Asyncio
        # ----------------------------------------------------

        loop = asyncio.new_event_loop()

        asyncio.set_event_loop(loop)

        navegador_task = loop.create_task(
            abrir_navegador()
        )

        # ----------------------------------------------------
        # Aguarda Chromium
        # ----------------------------------------------------

        log("")
        log(
            "Aguardando Chromium renderizar..."
        )
        log("")

        loop.run_until_complete(
            asyncio.sleep(20)
        )

        # ----------------------------------------------------
        # 7. FFmpeg
        # ----------------------------------------------------

        iniciar_ffmpeg()

        # ----------------------------------------------------
        # 8. Monitor HLS
        # ----------------------------------------------------

        monitorar_hls()

        # ----------------------------------------------------
        # Sistema online
        # ----------------------------------------------------

        log("")
        log(
            "=========================================================="
        )
        log(
            "SISTEMA COMPLETO"
        )
        log(
            "=========================================================="
        )
        log("")
        log(
            "Web TV: ONLINE"
        )
        log(
            "Chromium: ONLINE"
        )
        log(
            "Xvfb: ONLINE"
        )
        log(
            "PulseAudio: ONLINE"
        )
        log(
            "FFmpeg: ONLINE"
        )
        log(
            "HLS: ONLINE"
        )
        log("")
        log(
            "A transmissão está rodando."
        )
        log("")

        # ----------------------------------------------------
        # Mantém tudo vivo
        # ----------------------------------------------------

        loop.run_until_complete(
            navegador_task
        )

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log(
            "=========================================================="
        )
        log(
            "ERRO PRINCIPAL"
        )
        log(
            "=========================================================="
        )

        log(
            erro
        )

        log("")

        encerrar()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    iniciar()
