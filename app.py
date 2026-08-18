import os
import sys
import time
import signal
import subprocess
import threading

from playwright.sync_api import sync_playwright


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
ffmpeg_process = None
browser_global = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global ffmpeg_process
    global browser_global

    log("")
    log("=" * 58)
    log("ENCERRANDO TRANSMISSAO")
    log("=" * 58)

    try:
        if ffmpeg_process and ffmpeg_process.poll() is None:
            ffmpeg_process.terminate()
    except Exception:
        pass

    try:
        if browser_global:
            browser_global.close()
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

    log("Transmissao encerrada.")

    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


# ============================================================
# PREPARAR STREAM
# ============================================================

def preparar_stream():

    os.makedirs(STREAM_DIR, exist_ok=True)

    log("[1] Limpando arquivos antigos...")

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
        raise RuntimeError("Xvfb encerrou.")

    log("Xvfb funcionando.")
    log("DISPLAY:", DISPLAY)
    log("RESOLUÇÃO:", f"{WIDTH}x{HEIGHT}")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("")
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

    # Verifica se o sink existe
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
                "Não foi possível criar o sink webtv."
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

    log("Áudio virtual pronto.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_http():

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
        f"Servidor HTTP ativo na porta {HTTP_PORT}."
    )


# ============================================================
# TÚNEL
# ============================================================

def iniciar_tunel():

    log("")
    log("[5] Iniciando túnel público...")
    log("")

    tunnel = subprocess.Popen(
        [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
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

    inicio = time.time()

    while time.time() - inicio < 60:

        if tunnel.poll() is not None:

            log(
                "[ERRO] Túnel encerrou.",
                tunnel.returncode
            )

            break

        linha = tunnel.stdout.readline()

        if not linha:
            time.sleep(0.2)
            continue

        linha = linha.strip()

        if linha:
            log("[TUNEL]", linha)

        if "https://" in linha:

            partes = linha.split()

            for parte in partes:

                if parte.startswith("https://"):

                    url = parte.strip(
                        ".,;()[]{}<>\"'"
                    )

                    url = url.rstrip("/")

                    log("")
                    log("=" * 58)
                    log("          TRANSMISSÃO AO VIVO")
                    log("=" * 58)
                    log("")
                    log("LINK PÚBLICO:")
                    log(url)
                    log("")
                    log("LINK HLS:")
                    log(url + "/live.m3u8")
                    log("")
                    log("=" * 58)
                    log("")

                    return url

    log("")
    log("=" * 58)
    log("ERRO: NÃO FOI POSSÍVEL OBTER O LINK PÚBLICO")
    log("=" * 58)
    log("")

    return None


# ============================================================
# FFmpeg
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_process

    log("")
    log("[6] Iniciando FFmpeg...")
    log("")

    saida = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    ffmpeg_cmd = [

        "ffmpeg",
        "-y",

        # ----------------------------------------------------
        # VÍDEO
        # ----------------------------------------------------

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

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ----------------------------------------------------
        # VÍDEO ENCODE
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # ÁUDIO ENCODE
        # ----------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        "128k",

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

        saida
    ]

    log("Comando FFmpeg:")
    log(" ".join(ffmpeg_cmd))
    log("")

    ffmpeg_process = subprocess.Popen(
        ffmpeg_cmd
    )

    time.sleep(5)

    if ffmpeg_process.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou antes de iniciar."
        )

    log("FFmpeg funcionando.")


# ============================================================
# DIAGNÓSTICO DOS VÍDEOS
# ============================================================

def diagnosticar_videos(page):

    try:

        videos = page.locator("video")

        quantidade = videos.count()

        resultado = []

        for i in range(quantidade):

            video = videos.nth(i)

            try:

                dados = video.evaluate(
                    """
                    video => ({
                        paused: video.paused,
                        ended: video.ended,
                        muted: video.muted,
                        autoplay: video.autoplay,
                        readyState: video.readyState,
                        networkState: video.networkState,
                        currentTime: video.currentTime,
                        duration: video.duration,
                        width: video.videoWidth,
                        height: video.videoHeight,
                        src: video.currentSrc || video.src || "",
                        error: video.error
                            ? {
                                code: video.error.code,
                                message: video.error.message
                              }
                            : null
                    })
                    """
                )

                dados["index"] = i

                resultado.append(dados)

            except Exception as erro:

                resultado.append({
                    "index": i,
                    "erro": str(erro)
                })

        log(
            "[CHROMIUM] Vídeos encontrados:",
            {
                "quantidade": quantidade,
                "videos": resultado
            }
        )

        return resultado

    except Exception as erro:

        log(
            "[CHROMIUM] Erro diagnóstico:",
            erro
        )

        return []


# ============================================================
# TENTAR REPRODUZIR
# ============================================================

def tentar_reproduzir(page):

    log("")
    log("[PLAYER] Tentando reproduzir vídeos...")

    try:

        resultado = page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                const resultados = [];

                for (const video of videos) {

                    try {

                        video.setAttribute(
                            "playsinline",
                            ""
                        );

                        video.playsInline = true;

                        video.autoplay = true;

                        /*
                         * Não forçamos muted.
                         * O player original controla isso.
                         */

                        let playResult = "ok";

                        try {

                            const promise = video.play();

                            if (promise) {
                                await promise;
                            }

                        } catch (erro) {

                            playResult =
                                String(erro);
                        }

                        resultados.push({

                            paused: video.paused,

                            readyState:
                                video.readyState,

                            networkState:
                                video.networkState,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight,

                            currentTime:
                                video.currentTime,

                            playResult:
                                playResult

                        });

                    } catch (erro) {

                        resultados.push({
                            erro: String(erro)
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
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    global browser_global

    log("")
    log("[7] Iniciando Chromium...")
    log("")

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=False,

            args=[

                "--no-sandbox",

                "--disable-setuid-sandbox",

                "--disable-dev-shm-usage",

                "--disable-background-networking",

                "--disable-background-timer-throttling",

                "--disable-backgrounding-occluded-windows",

                "--disable-renderer-backgrounding",

                "--disable-popup-blocking",

                "--disable-notifications",

                "--no-first-run",

                "--no-default-browser-check",

                "--autoplay-policy=no-user-gesture-required",

                "--start-fullscreen",

                "--kiosk",

                "--window-size=1280,720",

                "--window-position=0,0",

                "--force-device-scale-factor=1",

                "--ozone-platform=x11",

                # Mantemos software rendering
                # para evitar problemas de GPU no runner.
                "--use-gl=swiftshader",

                "--disable-gpu",

                "--disable-gpu-compositing",

                "--disable-gpu-rasterization",

                "--disable-accelerated-video-decode",

                "--disable-accelerated-video-encode"
            ]
        )

        browser_global = browser

        page = browser.new_page(
            viewport={
                "width": WIDTH,
                "height": HEIGHT
            }
        )

        # ----------------------------------------------------
        # LOGS DO NAVEGADOR
        # ----------------------------------------------------

        page.on(
            "console",
            lambda mensagem:
                log(
                    "[CONSOLE]",
                    mensagem.type,
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

        log(
            "Acessando:",
            URL_ALVO
        )

        try:

            page.goto(
                URL_ALVO,
                wait_until="domcontentloaded",
                timeout=120000
            )

        except Exception as erro:

            log(
                "[AVISO] Erro no carregamento:",
                erro
            )

        log("Aguardando página...")

        time.sleep(10)

        # ----------------------------------------------------
        # TELA CHEIA
        # ----------------------------------------------------

        try:

            page.keyboard.press(
                "F11"
            )

        except Exception:
            pass

        # Clique inicial no player
        try:

            page.mouse.click(
                WIDTH // 2,
                HEIGHT // 2
            )

        except Exception:
            pass

        time.sleep(3)

        # ----------------------------------------------------
        # PRIMEIRA TENTATIVA
        # ----------------------------------------------------

        diagnosticar_videos(page)

        tentar_reproduzir(page)

        time.sleep(5)

        diagnosticar_videos(page)

        # ----------------------------------------------------
        # MONITOR
        # ----------------------------------------------------

        log("")
        log("=" * 58)
        log("PAINEL CARREGADO")
        log("Chromium ativo.")
        log("FFmpeg ativo.")
        log("Transmissão HLS ativa.")
        log("=" * 58)
        log("")

        ultimo_tempo = 0

        while True:

            time.sleep(5)

            try:

                if page.is_closed():

                    raise RuntimeError(
                        "A página foi fechada."
                    )

                dados = diagnosticar_videos(
                    page
                )

                # Detecta vídeo travado
                atual = 0

                for video in dados:

                    if video.get(
                        "currentTime",
                        0
                    ):

                        atual = max(
                            atual,
                            float(
                                video.get(
                                    "currentTime",
                                    0
                                )
                            )
                        )

                # Se não avançou, tenta novamente
                if atual <= ultimo_tempo:

                    log(
                        "[PLAYER] Vídeo aparentemente parado. "
                        "Tentando reprodução novamente..."
                    )

                    tentar_reproduzir(
                        page
                    )

                    try:

                        page.mouse.click(
                            WIDTH // 2,
                            HEIGHT // 2
                        )

                    except Exception:
                        pass

                ultimo_tempo = atual

            except Exception as erro:

                log(
                    "[MONITOR] Erro:",
                    erro
                )

                break


# ============================================================
# MAIN
# ============================================================

def iniciar():

    log("")
    log("=" * 58)
    log("INICIANDO TRANSMISSÃO")
    log("=" * 58)
    log("")

    preparar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_http()

    iniciar_ffmpeg()

    # Dá tempo para o HLS começar
    time.sleep(5)

    iniciar_tunel()

    iniciar_navegador()


if __name__ == "__main__":

    try:

        iniciar()

    except Exception as erro:

        log("")
        log("=" * 58)
        log("ERRO FATAL")
        log("=" * 58)
        log(str(erro))
        log("=" * 58)

        encerrar()
