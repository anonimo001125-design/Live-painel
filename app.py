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
page_global = None
ffmpeg_global = None


# ============================================================
# LOG
# ============================================================

def log(msg):
    print(msg, flush=True)


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

    try:
        if ffmpeg_global:
            ffmpeg_global.terminate()
    except Exception:
        pass

    try:
        if browser_global:
            # Não conseguimos fazer await aqui com segurança.
            pass
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

        caminho = os.path.join(STREAM_DIR, arquivo)

        try:

            if os.path.isfile(caminho):
                os.remove(caminho)

        except Exception as erro:

            log(f"[AVISO] Não foi possível remover {caminho}: {erro}")


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
        raise RuntimeError("Xvfb encerrou imediatamente.")

    log("Tela virtual pronta.")
    log(f"DISPLAY = {DISPLAY}")
    log(f"RESOLUÇÃO = {WIDTH}x{HEIGHT}")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("")
    log("[3] Iniciando PulseAudio...")

    pulse_runtime = "/tmp/pulse"

    os.environ["PULSE_RUNTIME_PATH"] = pulse_runtime

    os.makedirs(pulse_runtime, exist_ok=True)

    # O Chromium vai enviar o áudio para este sink.
    os.environ["PULSE_SINK"] = "webtv"

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1",
            "--daemonize=true"
        ],
        check=False
    )

    time.sleep(3)

    # Remove um possível sink antigo.
    subprocess.run(
        [
            "pactl",
            "unload-module",
            "module-null-sink"
        ],
        capture_output=True,
        text=True
    )

    # Cria o sink virtual.
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

        log("[AVISO] Não foi possível criar o sink WebTV.")
        log(resultado.stdout)
        log(resultado.stderr)

    else:

        log("Sink de áudio WebTV criado.")

    # Define como saída padrão.
    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        check=False
    )

    log("Áudio virtual pronto.")


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
        raise RuntimeError("Servidor HTTP encerrou.")

    log(f"Servidor HTTP funcionando na porta {HTTP_PORT}.")


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

                    log("[TUNEL] " + linha)

                    # Detecta URL automaticamente.
                    if "https://" in linha:

                        inicio = linha.find("https://")

                        if inicio >= 0:

                            url = linha[inicio:].split()[0]

                            log("")
                            log("==========================================================")
                            log("URL PÚBLICA DO STREAM")
                            log(url)
                            log("")
                            log("PLAYLIST HLS")
                            log(url.rstrip("/") + "/live.m3u8")
                            log("==========================================================")
                            log("")

        except Exception as erro:

            log(f"[TUNEL] Erro: {erro}")

    threading.Thread(
        target=ler_tunel,
        daemon=True
    ).start()

    time.sleep(5)


# ============================================================
# TESTE DA TELA
# ============================================================

def testar_tela():

    log("")
    log("[6] Testando captura do Xvfb...")

    arquivo_teste = os.path.join(
        STREAM_DIR,
        "debug_screen.png"
    )

    comando = [
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

        arquivo_teste
    ]

    resultado = subprocess.run(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if resultado.returncode == 0:

        log("Captura de tela criada:")
        log(arquivo_teste)

    else:

        log("[AVISO] Não foi possível criar captura de diagnóstico.")
        log(resultado.stderr[-2000:])


# ============================================================
# CHROMIUM
# ============================================================

async def abrir_navegador():

    global browser_global
    global page_global

    log("")
    log("[7] Iniciando Chromium...")
    log("")

    # Garantir áudio no sink WebTV.
    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY
    env["PULSE_SINK"] = "webtv"

    browser = await launch(

        headless=False,

        executablePath="/usr/bin/chromium",

        env=env,

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

            # ------------------------------------------------
            # RENDERIZAÇÃO
            # ------------------------------------------------

            "--disable-software-rasterizer",

            "--disable-features=UseSkiaRenderer",

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
            # INICIALIZAÇÃO
            # ------------------------------------------------

            "--no-first-run",

            "--no-default-browser-check",

            "--disable-background-networking",

            "--disable-background-timer-throttling",

            "--disable-backgrounding-occluded-windows",

            "--disable-renderer-backgrounding",

            # ------------------------------------------------
            # ESTABILIDADE
            # ------------------------------------------------

            "--disable-features=Translate",

            "--disable-popup-blocking",

            "--disable-notifications",

            "--disable-infobars"
        ]
    )

    browser_global = browser

    page = await browser.newPage()

    page_global = page

    await page.setViewport(
        {
            "width": WIDTH,
            "height": HEIGHT
        }
    )

    log("Chromium iniciado.")
    log("Abrindo painel da Web TV...")
    log(URL_ALVO)

    try:

        await page.goto(
            URL_ALVO,
            {
                "waitUntil": "domcontentloaded",
                "timeout": 120000
            }
        )

        log("Painel carregado.")

    except Exception as erro:

        log("")
        log("ERRO AO ABRIR O PAINEL:")
        log(str(erro))
        log("")

    # --------------------------------------------------------
    # Aguarda renderização
    # --------------------------------------------------------

    log("")
    log("Aguardando painel renderizar...")

    await asyncio.sleep(15)

    # --------------------------------------------------------
    # Tenta garantir reprodução dos vídeos HTML5
    # --------------------------------------------------------

    try:

        resultado = await page.evaluate(
            """
            () => {

                const videos = Array.from(
                    document.querySelectorAll("video")
                );

                videos.forEach(video => {

                    try {

                        video.muted = false;
                        video.autoplay = true;
                        video.playsInline = true;

                        const promessa = video.play();

                        if (promessa) {
                            promessa.catch(() => {});
                        }

                    } catch (e) {}
                });

                return {
                    videos: videos.length
                };
            }
            """
        )

        log(
            "[CHROMIUM] Vídeos encontrados:",
            resultado
        )

    except Exception as erro:

        log(
            "[CHROMIUM] Não foi possível verificar vídeos:",
            erro
        )

    # --------------------------------------------------------
    # Screenshot do navegador
    # --------------------------------------------------------

    try:

        await page.screenshot(
            {
                "path": os.path.join(
                    STREAM_DIR,
                    "browser_debug.png"
                ),
                "fullPage": False
            }
        )

        log(
            "[CHROMIUM] Screenshot salvo em "
            "stream/browser_debug.png"
        )

    except Exception as erro:

        log(
            "[CHROMIUM] Erro ao salvar screenshot:",
            erro
        )

    # --------------------------------------------------------
    # TESTE REAL DA TELA X11
    # --------------------------------------------------------

    testar_tela()

    log("")
    log("==========================================================")
    log("PAINEL CARREGADO")
    log("Chromium está rodando dentro do Xvfb.")
    log("A captura X11 foi testada.")
    log("==========================================================")
    log("")

    # --------------------------------------------------------
    # MANTER NAVEGADOR VIVO
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
                "[CHROMIUM] Página apresentou erro:",
                erro
            )

            # Tenta recuperar a página.
            try:

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
    log("[8] Iniciando FFmpeg...")
    log("")

    ffmpeg_cmd = [

        "ffmpeg",

        "-y",

        # ====================================================
        # VÍDEO - X11
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
        # ÁUDIO - PULSEAUDIO
        # ====================================================

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
        # ÁUDIO
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

    log("Comando FFmpeg:")
    log(" ".join(ffmpeg_cmd))
    log("")

    ffmpeg_global = subprocess.Popen(
        ffmpeg_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(ffmpeg_global)

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

    time.sleep(5)

    if ffmpeg_global.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou logo após iniciar."
        )

    log("")
    log("==========================================================")
    log("TRANSMISSÃO INICIADA")
    log("==========================================================")
    log("")

    log(
        "Playlist HLS:",
        f"http://localhost:{HTTP_PORT}/live.m3u8"
    )


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

            tamanho = os.path.getsize(
                playlist
            )

            if tamanho == ultimo_tamanho:

                log(
                    "[HLS] AVISO: playlist não está "
                    "mudando."
                )

            else:

                log(
                    "[HLS] Playlist funcionando. "
                    f"Tamanho: {tamanho} bytes"
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
                f"[HLS] Segmentos disponíveis: "
                f"{len(segmentos)}"
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
    log("==========================================================")
    log("                 INICIANDO WEB TV")
    log("==========================================================")
    log("")

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_tunel()

    # --------------------------------------------------------
    # Inicia o loop asyncio
    # --------------------------------------------------------

    loop = asyncio.new_event_loop()

    asyncio.set_event_loop(loop)

    navegador_task = loop.create_task(
        abrir_navegador()
    )

    # --------------------------------------------------------
    # Dá tempo para Chromium iniciar
    # --------------------------------------------------------

    log("")
    log("Aguardando Chromium renderizar...")
    log("")

    loop.run_until_complete(
        asyncio.sleep(20)
    )

    # --------------------------------------------------------
    # Inicia FFmpeg depois do Chromium
    # --------------------------------------------------------

    iniciar_ffmpeg()

    monitorar_hls()

    log("")
    log("==========================================================")
    log("SISTEMA COMPLETO")
    log("==========================================================")
    log("")
    log("Web TV: ONLINE")
    log("Chromium: ONLINE")
    log("Xvfb: ONLINE")
    log("PulseAudio: ONLINE")
    log("FFmpeg: ONLINE")
    log("HLS: ONLINE")
    log("")
    log("A transmissão está rodando.")
    log("")

    try:

        loop.run_until_complete(
            navegador_task
        )

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("ERRO PRINCIPAL:")
        log(str(erro))
        log("")

        encerrar()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    iniciar()
