

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

    global ffmpeg_global

    try:
        if ffmpeg_global:
            if ffmpeg_global.poll() is None:
                ffmpeg_global.terminate()
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
    os.environ["PULSE_SINK"] = "webtv"

    os.makedirs(
        pulse_runtime,
        exist_ok=True
    )

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

        log(
            "[ERRO] PulseAudio não iniciou."
        )

        log(
            teste.stderr
        )

        raise RuntimeError(
            "PulseAudio não está funcionando."
        )

    # --------------------------------------------------------
    # Verifica sink
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

    if "webtv" not in sinks.stdout:

        log(
            "Criando sink virtual WebTV..."
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

            log(
                resultado.stdout
            )

            log(
                resultado.stderr
            )

            raise RuntimeError(
                "Não foi possível criar o sink WebTV."
            )

    else:

        log(
            "Sink WebTV já existe."
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

    log(
        "Áudio virtual pronto."
    )


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

                if not linha:
                    continue

                linha = linha.strip()

                log(
                    "[TUNEL]",
                    linha
                )

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
                        "URL PÚBLICA"
                    )
                    log(url)
                    log("")
                    log(
                        "HLS"
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
# DIAGNÓSTICO X11
# ============================================================

def testar_tela():

    log("")
    log(
        "[DIAGNÓSTICO] Testando captura do Xvfb..."
    )

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

        stdout=subprocess.PIPE,

        stderr=subprocess.PIPE,

        text=True
    )

    if resultado.returncode == 0:

        log(
            "[DIAGNÓSTICO] Captura criada:",
            arquivo
        )

    else:

        log(
            "[DIAGNÓSTICO] Erro:",
            resultado.stderr[-3000:]
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
                    (video, index) => {

                        return {

                            index: index,

                            src: video.src || "",

                            currentSrc:
                                video.currentSrc || "",

                            poster:
                                video.poster || "",

                            paused:
                                video.paused,

                            ended:
                                video.ended,

                            muted:
                                video.muted,

                            autoplay:
                                video.autoplay,

                            readyState:
                                video.readyState,

                            networkState:
                                video.networkState,

                            currentTime:
                                video.currentTime,

                            duration:
                                video.duration,

                            videoWidth:
                                video.videoWidth,

                            videoHeight:
                                video.videoHeight,

                            error:
                                video.error
                                    ? {
                                        code:
                                            video.error.code,

                                        message:
                                            video.error.message
                                    }
                                    : null,

                            sources:
                                Array.from(
                                    video.querySelectorAll(
                                        "source"
                                    )
                                ).map(
                                    source => ({

                                        src:
                                            source.src,

                                        type:
                                            source.type

                                    })
                                )

                        };

                    }
                );

            }
            """
        )

        log("")
        log(
            "=========================================================="
        )
        log(
            "[DIAGNÓSTICO COMPLETO DOS VÍDEOS]"
        )
        log(
            "=========================================================="
        )

        for video in resultado:

            log(
                "Vídeo:",
                video
            )

        log(
            "=========================================================="
        )
        log("")

        return resultado

    except Exception as erro:

        log(
            "[DIAGNÓSTICO] Erro:",
            erro
        )

        return []


# ============================================================
# TENTA INICIAR OS VÍDEOS
# ============================================================

async def iniciar_videos(page):

    log("")
    log(
        "[PLAYER] Tentando inicializar vídeos..."
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

                for (
                    let i = 0;
                    i < videos.length;
                    i++
                ) {

                    const video = videos[i];

                    try {

                        video.autoplay = true;

                        video.playsInline = true;

                        /*
                         * Não alteramos muted aqui.
                         *
                         * Alguns players precisam controlar
                         * isso internamente.
                         */

                        if (
                            video.readyState === 0 &&
                            video.load
                        ) {
                            video.load();
                        }

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

                            index: i,

                            sucesso: sucesso,

                            src:
                                video.src || "",

                            currentSrc:
                                video.currentSrc || "",

                            readyState:
                                video.readyState,

                            networkState:
                                video.networkState,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight,

                            paused:
                                video.paused

                        });

                    } catch (erro) {

                        resultados.push({

                            index: i,

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

        return resultado

    except Exception as erro:

        log(
            "[PLAYER] Erro:",
            erro
        )

        return []


# ============================================================
# ESPERA VÍDEO CARREGAR
# ============================================================

async def esperar_video(page):

    log("")
    log(
        "[PLAYER] Aguardando vídeo receber dados..."
    )

    for tentativa in range(1, 7):

        await asyncio.sleep(5)

        resultado = await diagnosticar_videos(
            page
        )

        carregado = False

        for video in resultado:

            if (
                video.get("readyState", 0) >= 2
                and
                video.get("videoWidth", 0) > 0
                and
                video.get("videoHeight", 0) > 0
            ):

                carregado = True

                break

        if carregado:

            log("")
            log(
                "[PLAYER] VÍDEO CARREGADO!"
            )

            return True

        log(
            "[PLAYER] Ainda não carregou.",
            "Tentativa:",
            tentativa,
            "/ 6"
        )

    log("")
    log(
        "[PLAYER] Nenhum vídeo recebeu dados."
    )

    return False


# ============================================================
# CHROMIUM
# ============================================================

async def abrir_navegador():

    global browser_global

    log("")
    log(
        "[6] Iniciando Chromium..."
    )
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

            # X11
            "--ozone-platform=x11",

            # Renderização
            "--use-gl=swiftshader",

            "--disable-gpu",

            "--disable-gpu-compositing",

            "--disable-gpu-rasterization",

            "--disable-accelerated-video-decode",

            "--disable-accelerated-video-encode",

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

            "--disable-infobars"
        ]
    )

    browser_global = browser

    log(
        "Chromium iniciado."
    )

    page = await browser.newPage()

    await page.setViewport(
        {
            "width": WIDTH,

            "height": HEIGHT,

            "deviceScaleFactor": 1
        }
    )

    # ========================================================
    # MONITORAMENTO DE ERROS
    # ========================================================

    page.on(
        "console",
        lambda mensagem:
            log(
                "[CONSOLE]",
                mensagem.text
