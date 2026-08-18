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

MEDIA_URLS = []

ENCERRANDO = False


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global ENCERRANDO

    if ENCERRANDO:
        return

    ENCERRANDO = True

    log("")
    log("=" * 70)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 70)

    global ffmpeg_process

    try:

        if (
            ffmpeg_process
            and
            ffmpeg_process.poll() is None
        ):
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


signal.signal(
    signal.SIGTERM,
    encerrar
)

signal.signal(
    signal.SIGINT,
    encerrar
)


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

            log(
                "[AVISO]",
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
        "Xvfb ativo:",
        DISPLAY
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
            "Criando sink webtv..."
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

    log("PulseAudio pronto.")


# ============================================================
# SERVIDOR
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
                    and
                    not encontrado
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


# ============================================================
# DETECTAR MÍDIA
# ============================================================

def registrar_midia(request):

    try:

        url = request.url.lower()

        extensoes = (
            ".m3u8",
            ".mpd",
            ".mp4",
            ".webm",
            ".m4v"
        )

        if not any(
            ext in url
            for ext in extensoes
        ):
            return

        original = request.url

        if original not in MEDIA_URLS:

            MEDIA_URLS.append(
                original
            )

            log("")
            log(
                "[MEDIA] Detectado:"
            )
            log(
                original
            )

    except Exception:
        pass


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

                        video.autoplay = true;

                        video.playsInline = true;

                        video.setAttribute(
                            "playsinline",
                            ""
                        );

                        let estado = "ok";

                        try {

                            const p =
                                video.play();

                            if (p) {
                                await p;
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
            "[PLAYER]",
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

def ativar_tela_cheia(page):

    log("")
    log(
        "[PLAYER] Tentando ativar fullscreen..."
    )

    try:

        page.wait_for_selector(
            "video",
            state="visible",
            timeout=30000
        )

    except Exception:

        log(
            "[PLAYER] Vídeo não encontrado."
        )

        return

    try:

        info = page.evaluate(
            """
            () => {

                const v =
                    document.querySelector("video");

                if (!v)
                    return null;

                const r =
                    v.getBoundingClientRect();

                return {

                    x:
                        r.left +
                        r.width / 2,

                    y:
                        r.top +
                        r.height / 2
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

        # Dois cliques físicos no elemento.
        # NÃO chamamos requestFullscreen por JS.

        page.mouse.click(
            x,
            y
        )

        time.sleep(0.15)

        page.mouse.click(
            x,
            y
        )

        log(
            "[PLAYER] Duplo clique enviado."
        )

    except Exception as erro:

        log(
            "[PLAYER] Fullscreen:",
            erro
        )

    time.sleep(2)

    try:

        estado = page.evaluate(
            """
            () => ({

                fullscreen:
                    !!document.fullscreenElement,

                element:
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
            "[PLAYER] Fullscreen:",
            estado
        )

    except Exception:
        pass


# ============================================================
# FFMPEG DIRETO
# ============================================================

def iniciar_ffmpeg_direto(url):

    global ffmpeg_process

    saida = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    log("")
    log("=" * 70)
    log("TENTANDO FFMPEG DIRETO")
    log("=" * 70)
    log(url)
    log("")

    cmd = [

        "ffmpeg",
        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

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
        "2",

        "-hls_list_size",
        "5",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",

        os.path.join(
            STREAM_DIR,
            "segment_%05d.ts"
        ),

        saida
    ]

    try:

        ffmpeg_process = subprocess.Popen(
            cmd
        )

        time.sleep(8)

        if (
            ffmpeg_process.poll()
            is not None
        ):

            log(
                "[MEDIA] FFmpeg direto falhou."
            )

            return False

        log(
            "[MEDIA] FFmpeg direto funcionando."
        )

        return True

    except Exception as erro:

        log(
            "[MEDIA] Erro FFmpeg direto:",
            erro
        )

        return False


# ============================================================
# FFMPEG X11
# ============================================================

def iniciar_ffmpeg_x11():

    global ffmpeg_process

    saida = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    log("")
    log("=" * 70)
    log("USANDO CAPTURA X11")
    log("=" * 70)
    log("")

    cmd = [

        "ffmpeg",
        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

        "-thread_queue_size",
        "1024",

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
        "1024",

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
        "2",

        "-hls_list_size",
        "5",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",

        os.path.join(
            STREAM_DIR,
            "segment_%05d.ts"
        ),

        saida
    ]

    ffmpeg_process = subprocess.Popen(
        cmd
    )

    time.sleep(5)

    if (
        ffmpeg_process.poll()
        is not None
    ):

        raise RuntimeError(
            "FFmpeg X11 não iniciou."
        )

    log(
        "FFmpeg X11 funcionando."
    )


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    global MEDIA_URLS

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

                "--disable-gpu-compositing",

                "--disable-gpu-rasterization",

                "--disable-background-networking",

                "--disable-background-timer-throttling",

                "--disable-backgrounding-occluded-windows",

                "--disable-renderer-backgrounding",

                # Política de fullscreen
                "--autoplay-policy=no-user-gesture-required"
            ]
        )

        page = browser.new_page(
            viewport={
                "width": WIDTH,
                "height": HEIGHT
            }
        )

        # ----------------------------------------------------
        # EVENTOS
        # ----------------------------------------------------

        page.on(
            "request",
            registrar_midia
        )

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

        # ----------------------------------------------------
        # SITE
        # ----------------------------------------------------

        log(
            "Abrindo:",
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

        # ----------------------------------------------------
        # PLAYER
        # ----------------------------------------------------

        tentar_reproduzir(
            page
        )

        time.sleep(3)

        ativar_tela_cheia(
            page
        )

        # ----------------------------------------------------
        # ESPERAR URL DE MÍDIA
        # ----------------------------------------------------

        log("")
        log(
            "[MEDIA] Procurando stream direto..."
        )

        for _ in range(20):

            if MEDIA_URLS:
                break

            time.sleep(1)

        # ----------------------------------------------------
        # TENTAR STREAM DIRETO
        # ----------------------------------------------------

        sucesso = False

        if MEDIA_URLS:

            # Preferir HLS.
            urls = sorted(
                MEDIA_URLS,
                key=lambda u:
                    0
                    if ".m3u8"
                    in u.lower()
                    else 1
            )

            for url in urls:

                if iniciar_ffmpeg_direto(
                    url
                ):

                    sucesso = True

                    break

        # ----------------------------------------------------
        # FALLBACK
        # ----------------------------------------------------

        if not sucesso:

            log("")
            log(
                "[MEDIA] Stream direto não funcionou."
            )

            log(
                "[MEDIA] Ativando fallback X11..."
            )

            iniciar_ffmpeg_x11()

        # ----------------------------------------------------
        # TRANSMISSÃO
        # ----------------------------------------------------

        log("")
        log("=" * 70)
        log("TRANSMISSÃO ATIVA")
        log("=" * 70)
        log("")

        # ----------------------------------------------------
        # MONITORAMENTO
        # ----------------------------------------------------

        while True:

            if (
                ffmpeg_process
                and
                ffmpeg_process.poll()
                is not None
            ):

                log("")
                log(
                    "[FFMPEG] Processo encerrou."
                )

                # Tenta novamente usando X11.
                log(
                    "[FFMPEG] Reiniciando captura..."
                )

                iniciar_ffmpeg_x11()

            time.sleep(5)


# ============================================================
# MAIN
# ============================================================

def main():

    log("")
    log("=" * 70)
    log("WEBTV STREAM")
    log("=" * 70)
    log("")

    preparar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_tunel()

    iniciar_navegador()


if __name__ == "__main__":

    main()
