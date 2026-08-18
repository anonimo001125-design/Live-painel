import os
import sys
import time
import signal
import subprocess
import threading
import re

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

MEDIA_URL = None


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

    log("")
    log("=" * 70)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 70)

    try:
        if ffmpeg_process and ffmpeg_process.poll() is None:
            ffmpeg_process.terminate()
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
# PREPARAR STREAM
# ============================================================

def preparar_stream():

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    log("[1] Limpando stream antigo...")

    for nome in os.listdir(STREAM_DIR):

        caminho = os.path.join(
            STREAM_DIR,
            nome
        )

        try:

            if os.path.isfile(caminho):
                os.remove(caminho)

        except Exception as erro:

            log("[AVISO]", erro)


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

    os.environ[
        "PULSE_RUNTIME_PATH"
    ] = runtime

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
            "Criando áudio virtual webtv..."
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

    os.environ[
        "PULSE_SINK"
    ] = "webtv"

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

        encontrado = False

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
                    and not encontrado
                ):

                    for parte in linha.split():

                        if parte.startswith(
                            "https://"
                        ):

                            url = parte.strip(
                                ".,;()[]{}<>\"'"
                            )

                            url = url.rstrip("/")

                            encontrado = True

                            log("")
                            log("=" * 70)
                            log("LINK DA TRANSMISSÃO")
                            log("=" * 70)
                            log("")
                            log(
                                "LINK PRINCIPAL:"
                            )
                            log(url)
                            log("")
                            log(
                                "LINK HLS:"
                            )
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
# IDENTIFICAR URL DE MÍDIA
# ============================================================

def parece_midia(url):

    url_lower = url.lower()

    extensoes = [
        ".m3u8",
        ".mpd",
        ".mp4",
        ".webm",
        ".m4v",
        ".mov"
    ]

    return any(
        extensao in url_lower
        for extensao in extensoes
    )


# ============================================================
# CAPTURAR URL DE MÍDIA
# ============================================================

def registrar_midia(request):

    global MEDIA_URL

    try:

        url = request.url

        if not parece_midia(url):
            return

        log("")
        log(
            "[MEDIA] URL DETECTADA:"
        )
        log(url)

        # HLS é a melhor opção.
        if ".m3u8" in url.lower():

            MEDIA_URL = url

            log(
                "[MEDIA] >>> HLS SELECIONADO <<<"
            )

        elif MEDIA_URL is None:

            MEDIA_URL = url

    except Exception:
        pass


# ============================================================
# FFMPEG DIRETO
# ============================================================

def iniciar_ffmpeg_direto(url):

    global ffmpeg_process

    log("")
    log("=" * 70)
    log("FFMPEG DIRETO")
    log("=" * 70)
    log("")
    log("Fonte:")
    log(url)
    log("")

    saida = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    cmd = [

        "ffmpeg",
        "-y",

        "-reconnect",
        "1",

        "-reconnect_streamed",
        "1",

        "-reconnect_delay_max",
        "5",

        "-i",
        url,

        "-map",
        "0:v:0",

        "-map",
        "0:a:0?",

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

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        "-ac",
        "2",

        "-f",
        "hls",

        "-hls_time",
        "1",

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

    log(
        "Iniciando FFmpeg direto..."
    )

    ffmpeg_process = subprocess.Popen(
        cmd
    )

    time.sleep(5)

    if ffmpeg_process.poll() is not None:

        raise RuntimeError(
            "FFmpeg direto encerrou."
        )

    log(
        "FFmpeg direto funcionando."
    )


# ============================================================
# FFMPEG CAPTURA DE TELA
# ============================================================

def iniciar_ffmpeg_tela():

    global ffmpeg_process

    log("")
    log("=" * 70)
    log("FFMPEG X11 FALLBACK")
    log("=" * 70)

    saida = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    cmd = [

        "ffmpeg",
        "-y",

        "-thread_queue_size",
        "512",

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

        "-thread_queue_size",
        "512",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        "-c:v",
        "libx264",

        "-preset",
        "ultrafast",

        "-tune",
        "zerolatency",

        "-threads",
        "2",

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

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        "-ac",
        "2",

        "-f",
        "hls",

        "-hls_time",
        "1",

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

    log(
        "Iniciando captura X11..."
    )

    ffmpeg_process = subprocess.Popen(
        cmd
    )

    time.sleep(5)

    if ffmpeg_process.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log(
        "FFmpeg X11 funcionando."
    )


# ============================================================
# REPRODUÇÃO
# ============================================================

def tentar_reproduzir(page):

    log("")
    log(
        "[PLAYER] Tentando reproduzir..."
    )

    try:

        resultado = page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                const resultado = [];

                for (
                    const video of videos
                ) {

                    try {

                        video.playsInline = true;

                        video.setAttribute(
                            "playsinline",
                            ""
                        );

                        video.autoplay = true;

                        let estado = "ok";

                        try {

                            const promessa =
                                video.play();

                            if (promessa) {
                                await promessa;
                            }

                        } catch (erro) {

                            estado =
                                String(erro);
                        }

                        resultado.push({

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

                            src:
                                video.currentSrc || "",

                            estado
                        });

                    } catch (erro) {

                        resultado.push({
                            erro:
                                String(erro)
                        });
                    }
                }

                return resultado;
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
# DIAGNÓSTICO
# ============================================================

def diagnosticar_videos(page):

    try:

        resultado = page.evaluate(
            """
            () => {

                return Array.from(
                    document.querySelectorAll("video")
                ).map(
                    (video, index) => ({

                        index,

                        paused:
                            video.paused,

                        muted:
                            video.muted,

                        readyState:
                            video.readyState,

                        currentTime:
                            video.currentTime,

                        duration:
                            video.duration,

                        width:
                            video.videoWidth,

                        height:
                            video.videoHeight,

                        currentSrc:
                            video.currentSrc || "",

                        error:
                            video.error
                                ? {
                                    code:
                                        video.error.code,

                                    message:
                                        video.error.message
                                }
                                : null
                    })
                );
            }
            """
        )

        log(
            "[CHROMIUM] Vídeos:"
        )

        log(resultado)

    except Exception as erro:

        log(
            "[CHROMIUM] Diagnóstico:",
            erro
        )


# ============================================================
# FULLSCREEN
# ============================================================

def ativar_tela_cheia(page):

    log("")
    log(
        "[PLAYER] Preparando fullscreen..."
    )

    time.sleep(3)

    try:

        page.wait_for_selector(
            "video",
            state="visible",
            timeout=30000
        )

    except Exception as erro:

        log(
            "[PLAYER] Vídeo não encontrado:",
            erro
        )

        return

    # --------------------------------------------------------
    # DESCOBRIR PLAYER
    # --------------------------------------------------------

    try:

        info = page.evaluate(
            """
            () => {

                const video =
                    document.querySelector("video");

                if (!video) {
                    return null;
                }

                const rect =
                    video.getBoundingClientRect();

                return {

                    x:
                        rect.left +
                        rect.width / 2,

                    y:
                        rect.top +
                        rect.height / 2,

                    width:
                        rect.width,

                    height:
                        rect.height
                };
            }
            """
        )

        if not info:
            return

        x = info["x"]
        y = info["y"]

        log(
            "[PLAYER] Centro:",
            x,
            y
        )

    except Exception as erro:

        log(
            "[PLAYER] Erro:",
            erro
        )

        return

    # --------------------------------------------------------
    # DUPLO CLIQUE REAL
    # --------------------------------------------------------

    try:

        log(
            "[PLAYER] Enviando duplo clique..."
        )

        page.mouse.move(
            x,
            y
        )

        page.mouse.down()

        time.sleep(0.08)

        page.mouse.up()

        time.sleep(0.12)

        page.mouse.down()

        time.sleep(0.08)

        page.mouse.up()

        log(
            "[PLAYER] Duplo clique enviado."
        )

    except Exception as erro:

        log(
            "[PLAYER] Erro no clique:",
            erro
        )

    time.sleep(2)

    # --------------------------------------------------------
    # NÃO chamar requestFullscreen aqui
    # --------------------------------------------------------

    try:

        estado = page.evaluate(
            """
            () => ({

                fullscreen:
                    !!document.fullscreenElement,

                fullscreenElement:
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

    except Exception as erro:

        log(
            "[PLAYER] Erro:",
            erro
        )


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    global MEDIA_URL

    log("")
    log("[7] Iniciando Chromium...")
    log("")

    with sync_playwright() as p:

        # ====================================================
        # CONTEXTO
        # ====================================================

        contexto = p.chromium.launch_persistent_context(

            "./browser-data",

            headless=False,

            viewport={
                "width": WIDTH,
                "height": HEIGHT
            },

            args=[

                "--no-sandbox",

                "--disable-setuid-sandbox",

                "--disable-dev-shm-usage",

                "--autoplay-policy=no-user-gesture-required",

                "--no-first-run",

                "--no-default-browser-check",

                "--disable-popup-blocking",

                "--disable-notifications",

                "--window-size=1280,720",

                "--window-position=0,0",

                "--force-device-scale-factor=1",

                "--ozone-platform=x11",

                "--use-gl=swiftshader",

                # Permite fullscreen automático
                # para o domínio da página.

                "--disable-background-networking",

                "--disable-background-timer-throttling",

                "--disable-backgrounding-occluded-windows",

                "--disable-renderer-backgrounding"
            ]
        )

        # ====================================================
        # PÁGINA
        # ====================================================

        pages = contexto.pages

        if pages:

            page = pages[0]

        else:

            page = contexto.new_page()

        # ====================================================
        # CAPTURA DE MÍDIA
        # ====================================================

        page.on(
            "request",
            registrar_midia
        )

        # ====================================================
        # LOGS
        # ====================================================

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

        # ====================================================
        # ABRIR
        # ====================================================

        log(
            "Abrindo painel:"
        )

        log(
            URL_ALVO
        )

        try:

            page.goto(
                URL_ALVO,
                wait_until="commit",
                timeout=120000
            )

        except Exception as erro:

            log(
                "[AVISO]",
                erro
            )

        log(
            "Aguardando página..."
        )

        time.sleep(10)

        # ====================================================
        # REPRODUÇÃO
        # ====================================================

        tentar_reproduzir(
            page
        )

        time.sleep(3)

        diagnosticar_videos(
            page
        )

        # ====================================================
        # FULLSCREEN
        # ====================================================

        ativar_tela_cheia(
            page
        )

        # ====================================================
        # ESPERAR MÍDIA
        # ====================================================

        log("")
        log(
            "[MEDIA] Aguardando identificação do stream..."
        )

        for _ in range(20):

            if MEDIA_URL:
                break

            time.sleep(1)

        # ====================================================
        # ESCOLHER MÉTODO
        # ====================================================

        if MEDIA_URL:

            log("")
            log("=" * 70)
            log(
                "[MEDIA] STREAM DIRETO ENCONTRADO"
            )
            log("=" * 70)
            log(
                MEDIA_URL
            )

            # O FFmpeg direto será iniciado
            # fora do loop do navegador.

            iniciar_ffmpeg_direto(
                MEDIA_URL
            )

        else:

            log("")
            log("=" * 70)
            log(
                "[MEDIA] STREAM DIRETO NÃO ENCONTRADO"
            )
            log(
                "[MEDIA] Usando fallback X11."
            )
            log("=" * 70)

            iniciar_ffmpeg_tela()

        # ====================================================
        # MANTER CHROMIUM
        # ====================================================

        log("")
        log("=" * 70)
        log(
            "TRANSMISSÃO ATIVA"
        )
        log("=" * 70)
        log("")

        while True:

            if page.is_closed():

                raise RuntimeError(
                    "Página foi fechada."
                )

            if (
                ffmpeg_process
                and
                ffmpeg_process.poll() is not None
            ):

                raise RuntimeError(
                    "FFmpeg encerrou."
                )

            time.sleep(10)


# ============================================================
# MAIN
# ============================================================

def main():

    log("")
    log("=" * 70)
    log(
        "WEBTV STREAM"
    )
    log("=" * 70)
    log("")

    try:

        preparar_stream()

        iniciar_xvfb()

        iniciar_audio()

        iniciar_servidor()

        iniciar_tunel()

        iniciar_navegador()

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("=" * 70)
        log(
            "ERRO FATAL"
        )
        log("=" * 70)

        log(
            repr(erro)
        )

        encerrar()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    main()
