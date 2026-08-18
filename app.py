import os
import time
import subprocess
import signal
import sys

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


# ============================================================
# PROCESSOS
# ============================================================

xvfb_process = None
http_process = None
ffmpeg_process = None
tunnel_process = None

browser = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global browser

    log("")
    log("==========================================================")
    log("ENCERRANDO TRANSMISSÃO")
    log("==========================================================")

    try:
        if browser:
            browser.close()
    except Exception:
        pass

    processos = [
        ffmpeg_process,
        tunnel_process,
        http_process,
        xvfb_process
    ]

    for processo in processos:

        try:
            if processo and processo.poll() is None:
                processo.terminate()
        except Exception:
            pass

    time.sleep(2)

    for processo in processos:

        try:
            if processo and processo.poll() is None:
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

    log("[1] Limpando stream anterior...")

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
                "[AVISO] Não foi possível remover:",
                caminho,
                erro
            )


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    global xvfb_process

    log("")
    log("[2] Iniciando Xvfb...")

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
            "Xvfb encerrou imediatamente."
        )

    log("Xvfb iniciado.")
    log("DISPLAY:", DISPLAY)
    log("RESOLUÇÃO:", f"{WIDTH}x{HEIGHT}")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("")
    log("[3] Iniciando PulseAudio...")

    os.environ["DISPLAY"] = DISPLAY

    resultado = subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    time.sleep(3)

    teste = subprocess.run(
        [
            "pactl",
            "info"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if teste.returncode != 0:

        log(teste.stderr)

        raise RuntimeError(
            "PulseAudio não iniciou."
        )

    # --------------------------------------------------------
    # Criar sink virtual
    # --------------------------------------------------------

    sinks = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sinks"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if "webtv" not in sinks.stdout:

        log("Criando sink virtual WebTV...")

        criar = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if criar.returncode != 0:

            log(
                "[AUDIO]",
                criar.stderr
            )

            raise RuntimeError(
                "Não foi possível criar o sink WebTV."
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

    time.sleep(1)

    fontes = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    log("")
    log("Fontes de áudio:")
    log(fontes.stdout)

    if "webtv.monitor" not in fontes.stdout:

        raise RuntimeError(
            "webtv.monitor não foi encontrado."
        )

    log("Áudio WebTV pronto.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_http():

    global http_process

    log("")
    log("[4] Iniciando servidor HTTP...")

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
        "Servidor HTTP ativo na porta",
        HTTP_PORT
    )


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_process

    log("")
    log("[5] Iniciando FFmpeg...")

    arquivo_m3u8 = os.path.join(
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
        "info",

        "-y",

        # ====================================================
        # CAPTURA DE TELA
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
        # AUDIO
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
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        segmentos,

        arquivo_m3u8
    ]

    log("")
    log("==========================================================")
    log("COMANDO FFMPEG")
    log("==========================================================")
    log(" ".join(comando))
    log("==========================================================")
    log("")

    ffmpeg_process = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    # ========================================================
    # IMPORTANTE:
    # Ler continuamente a saída do FFmpeg.
    # ========================================================

    def monitorar_ffmpeg():

        while True:

            try:

                linha = ffmpeg_process.stdout.readline()

            except Exception:

                break

            if linha:

                print(
                    "[FFMPEG]",
                    linha.rstrip(),
                    flush=True
                )

            if ffmpeg_process.poll() is not None:

                break

    import threading

    threading.Thread(
        target=monitorar_ffmpeg,
        daemon=True
    ).start()

    # ========================================================
    # Esperar a playlist aparecer
    # ========================================================

    log(
        "Aguardando geração do HLS..."
    )

    inicio = time.time()

    while time.time() - inicio < 20:

        if os.path.exists(arquivo_m3u8):

            tamanho = os.path.getsize(
                arquivo_m3u8
            )

            if tamanho > 20:

                log("")
                log(
                    "HLS criado com sucesso."
                )

                log(
                    "Arquivo:",
                    arquivo_m3u8
                )

                return

        if ffmpeg_process.poll() is not None:

            raise RuntimeError(
                "FFmpeg encerrou durante a inicialização."
            )

        time.sleep(1)

    raise RuntimeError(
        "FFmpeg não criou live.m3u8."
    )


# ============================================================
# TÚNEL
# ============================================================

def iniciar_tunel():

    global tunnel_process

    log("")
    log("[6] Iniciando túnel público...")

    tunnel_process = subprocess.Popen(
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

    def ler_tunel():

        while True:

            linha = tunnel_process.stdout.readline()

            if not linha:
                break

            linha = linha.strip()

            log(
                "[TUNEL]",
                linha
            )

            if "https://" in linha:

                posicao = linha.find(
                    "https://"
                )

                url = linha[posicao:].split()[0]

                log("")
                log(
                    "=========================================================="
                )
                log(
                    "TRANSMISSÃO AO VIVO"
                )
                log(
                    "=========================================================="
                )
                log("")
                log(
                    "LINK PÚBLICO:"
                )
                log(
                    url
                )
                log("")
                log(
                    "LINK HLS:"
                )
                log(
                    url.rstrip("/") +
                    "/live.m3u8"
                )
                log("")
                log(
                    "=========================================================="
                )
                log("")

    import threading

    threading.Thread(
        target=ler_tunel,
        daemon=True
    ).start()


# ============================================================
# DIAGNÓSTICO DOS VÍDEOS
# ============================================================

def diagnosticar_videos(page):

    try:

        resultado = page.evaluate(
            """
            () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                return videos.map(
                    (video, index) => ({

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
                            : null

                    })
                );
            }
            """
        )

        log("")
        log(
            "=========================================================="
        )
        log(
            "DIAGNÓSTICO DOS VÍDEOS"
        )
        log(
            "=========================================================="
        )

        for video in resultado:

            log(video)

        log(
            "=========================================================="
        )

        return resultado

    except Exception as erro:

        log(
            "[DIAGNÓSTICO]",
            erro
        )

        return []


# ============================================================
# REPRODUZIR
# ============================================================

def reproduzir_videos(page):

    try:

        resultado = page.evaluate(
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

                            paused:
                                video.paused,

                            readyState:
                                video.readyState,

                            networkState:
                                video.networkState,

                            currentTime:
                                video.currentTime,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight

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
            "[PLAYER]",
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

    global browser

    log("")
    log("[7] Iniciando Chromium...")
    log("")

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=False,

            args=[

                "--no-sandbox",

                "--disable-dev-shm-usage",

                "--autoplay-policy=no-user-gesture-required",

                "--kiosk",

                "--no-first-run",

                "--no-default-browser-check",

                "--start-fullscreen",

                "--start-maximized",

                "--window-size=1280,720",

                "--window-position=0,0",

                "--force-device-scale-factor=1"
            ]
        )

        page = browser.new_page(
            viewport={
                "width": WIDTH,
                "height": HEIGHT
            }
        )

        # ====================================================
        # MONITORAR ERROS DO SITE
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

        page.on(
            "requestfailed",
            lambda request:
            log(
                "[REQUEST FAILED]",
                request.url,
                request.failure
            )
        )

        # ====================================================
        # ABRIR PÁGINA
        # ====================================================

        log(
            "Acessando página:"
        )

        log(
            URL_ALVO
        )

        try:

            page.goto(
                URL_ALVO,
                wait_until="commit",
                timeout=0
            )

        except Exception as erro:

            log(
                "[GOTO]",
                erro
            )

        log(
            "Aguardando página carregar..."
        )

        time.sleep(10)

        try:

            log(
                "Título:",
                page.title()
            )

        except Exception:
            pass

        # ====================================================
        # PRIMEIRO DIAGNÓSTICO
        # ====================================================

        diagnosticar_videos(page)

        # ====================================================
        # TENTAR PLAY
        # ====================================================

        reproduzir_videos(page)

        # ====================================================
        # CLIQUE NO PLAYER
        # ====================================================

        try:

            page.mouse.click(
                WIDTH // 2,
                HEIGHT // 2
            )

            log(
                "[PLAYER] Clique de ativação executado."
            )

            time.sleep(3)

            reproduzir_videos(page)

        except Exception as erro:

            log(
                "[PLAYER] Clique:",
                erro
            )

        # ====================================================
        # TELA CHEIA
        # ====================================================

        try:

            page.keyboard.press("F11")

            log(
                "[TELA] F11 enviado."
            )

        except Exception as erro:

            log(
                "[TELA]",
                erro
            )

        # ====================================================
        # TENTAR FULLSCREEN DO DOCUMENTO
        # ====================================================

        try:

            page.evaluate(
                """
                () => {

                    if (
                        document.documentElement.requestFullscreen
                        &&
                        !document.fullscreenElement
                    ) {

                        document.documentElement
                            .requestFullscreen()
                            .catch(() => {});
                    }
                }
                """
            )

        except Exception:
            pass

        log("")
        log(
            "=========================================================="
        )
        log(
            "TRANSMISSÃO ATIVA"
        )
        log(
            "NAVEGADOR ATIVO"
        )
        log(
            "=========================================================="
        )

        # ====================================================
        # MONITORAMENTO
        # ====================================================

        contador = 0

        while True:

            time.sleep(5)

            contador += 1

            try:

                if contador % 3 == 0:

                    videos = diagnosticar_videos(
                        page
                    )

                    # Se algum vídeo estiver pausado,
                    # tenta reproduzir novamente.

                    for video in videos:

                        if (
                            video.get("paused")
                            and
                            not video.get("ended")
                        ):

                            reproduzir_videos(
                                page
                            )

            except Exception as erro:

                log(
                    "[MONITOR]",
                    erro
                )


# ============================================================
# MAIN
# ============================================================

def iniciar():

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_http()

    iniciar_ffmpeg()

    # Espera o HLS começar antes do túnel.
    time.sleep(3)

    iniciar_tunel()

    # Agora abre o navegador.
    iniciar_navegador()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    iniciar()
