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
    log("=" * 70)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 70)

    try:
        if browser_global:
            browser_global.close()
    except Exception:
        pass

    try:
        if ffmpeg_process and ffmpeg_process.poll() is None:
            ffmpeg_process.terminate()
            ffmpeg_process.wait(timeout=5)
    except Exception:
        try:
            if ffmpeg_process:
                ffmpeg_process.kill()
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
# STREAM
# ============================================================

def preparar_stream():

    os.makedirs(STREAM_DIR, exist_ok=True)

    log("[1] Limpando stream antigo...")

    for nome in os.listdir(STREAM_DIR):

        caminho = os.path.join(STREAM_DIR, nome)

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
            "tcp",
            "-dpi",
            "96"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(xvfb)

    time.sleep(3)

    if xvfb.poll() is not None:
        raise RuntimeError("Xvfb não conseguiu iniciar.")

    log("Tela virtual:", DISPLAY)
    log("Resolução:", f"{WIDTH}x{HEIGHT}")


# ============================================================
# ÁUDIO
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
        raise RuntimeError("PulseAudio não iniciou.")

    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        capture_output=True,
        text=True
    )

    if "webtv" not in sinks.stdout:

        log("Criando áudio virtual webtv...")

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
            raise RuntimeError("Não foi possível criar webtv.")

    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        check=False
    )

    os.environ["PULSE_SINK"] = "webtv"

    time.sleep(2)

    fontes = subprocess.run(
        ["pactl", "list", "short", "sources"],
        capture_output=True,
        text=True
    )

    log("")
    log("Fontes de áudio:")
    log(fontes.stdout)

    if "webtv.monitor" not in fontes.stdout:
        raise RuntimeError("webtv.monitor não foi encontrado.")

    log("Áudio pronto.")


# ============================================================
# SERVIDOR
# ============================================================

def iniciar_servidor():

    log("")
    log("[4] Iniciando servidor HTTP...")

    servidor = subprocess.Popen(
        [
            sys.executable,
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

            "-T",

            "-o",
            "StrictHostKeyChecking=no",

            "-o",
            "ServerAliveInterval=20",

            "-o",
            "ServerAliveCountMax=6",

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

                log("[TUNEL]", linha)

                # ==================================================
                # IMPORTANTE:
                # NÃO pegar admin.localhost.run.
                #
                # Procuramos especificamente o domínio .lhr.life
                # que o localhost.run fornece para o túnel.
                # ==================================================

                if not encontrado:

                    encontrados = re.findall(
                        r"https://[A-Za-z0-9.-]+\.lhr\.life",
                        linha
                    )

                    if encontrados:

                        url = encontrados[0].rstrip("/")

                        encontrado = True

                        log("")
                        log("=" * 70)
                        log("             LINK DA TRANSMISSÃO")
                        log("=" * 70)
                        log("")
                        log("LINK PRINCIPAL:")
                        log(url)
                        log("")
                        log("LINK HLS:")
                        log(url + "/live.m3u8")
                        log("")
                        log("=" * 70)
                        log("")

        except Exception as erro:

            log("[TUNEL] Erro:", erro)

    threading.Thread(
        target=ler_tunel,
        daemon=True
    ).start()

    time.sleep(5)


# ============================================================
# DIAGNÓSTICO
# ============================================================

def diagnosticar(page):

    try:

        resultado = page.evaluate(
            """
            () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                return videos.map(
                    (v, i) => ({

                        index: i,

                        paused:
                            v.paused,

                        ended:
                            v.ended,

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

                        currentSrc:
                            v.currentSrc || "",

                        src:
                            v.src || ""
                    })
                );
            }
            """
        )

        log("")
        log("[PLAYER] Vídeos:")
        log(resultado)

        return resultado

    except Exception as erro:

        log("[PLAYER] Diagnóstico:", erro)
        return []


# ============================================================
# NÃO FORÇAR A REPRODUÇÃO
# ============================================================

def verificar_reproducao(page):

    log("")
    log("[PLAYER] Verificando reprodução do site...")

    for tentativa in range(1, 9):

        time.sleep(3)

        videos = diagnosticar(page)

        reproduzindo = False

        for video in videos:

            if (
                video.get("paused") is False
                and
                video.get("readyState", 0) >= 3
                and
                video.get("width", 0) > 0
            ):
                reproduzindo = True
                break

        if reproduzindo:

            log("")
            log("=" * 70)
            log("[PLAYER] VÍDEO DO SITE ESTÁ REPRODUZINDO")
            log("=" * 70)
            log("")

            return True

        log(
            "[PLAYER] Aguardando player do site...",
            tentativa,
            "/ 8"
        )

    return False


# ============================================================
# FULLSCREEN VIA GESTO REAL
# ============================================================

def fullscreen_x11():

    log("")
    log("=" * 70)
    log("[FULLSCREEN] Iniciando gesto real do mouse")
    log("=" * 70)

    # --------------------------------------------------------
    # NÃO usamos:
    #
    # document.fullscreenElement
    # video.requestFullscreen()
    #
    # porque o navegador rejeita isso sem user gesture.
    # --------------------------------------------------------

    try:

        subprocess.run(
            [
                "xdotool",
                "mousemove",
                str(WIDTH // 2),
                str(HEIGHT // 2)
            ],
            check=False
        )

        time.sleep(1)

        # Primeiro clique.
        subprocess.run(
            [
                "xdotool",
                "click",
                "1"
            ],
            check=False
        )

        log("[FULLSCREEN] Primeiro clique realizado.")

        time.sleep(1)

        # Segundo clique.
        #
        # O seu player demonstrou que a sequência de dois
        # cliques é a que consegue ativar o fullscreen.
        #
        subprocess.run(
            [
                "xdotool",
                "click",
                "1"
            ],
            check=False
        )

        log("[FULLSCREEN] Segundo clique realizado.")

        time.sleep(3)

    except Exception as erro:

        log(
            "[FULLSCREEN] Erro:",
            erro
        )


# ============================================================
# FULLSCREEN COM PLAYWRIGHT + MOUSE X11
# ============================================================

def preparar_fullscreen(page):

    log("")
    log("[FULLSCREEN] Procurando área do player...")

    try:

        page.wait_for_selector(
            "video",
            state="visible",
            timeout=30000
        )

        log("[FULLSCREEN] Vídeo encontrado.")

    except Exception as erro:

        log(
            "[FULLSCREEN] Vídeo não encontrado:",
            erro
        )

    time.sleep(2)

    # --------------------------------------------------------
    # Descobre a posição do vídeo.
    # --------------------------------------------------------

    try:

        caixa = page.locator(
            "video"
        ).first.bounding_box()

        if caixa:

            log(
                "[FULLSCREEN] Área do vídeo:",
                caixa
            )

            x = int(
                caixa["x"] +
                caixa["width"] / 2
            )

            y = int(
                caixa["y"] +
                caixa["height"] / 2
            )

        else:

            x = WIDTH // 2
            y = HEIGHT // 2

    except Exception as erro:

        log(
            "[FULLSCREEN] Não conseguiu obter área:",
            erro
        )

        x = WIDTH // 2
        y = HEIGHT // 2

    # --------------------------------------------------------
    # GESTO REAL X11
    # --------------------------------------------------------

    try:

        subprocess.run(
            [
                "xdotool",
                "mousemove",
                str(x),
                str(y)
            ],
            check=False
        )

        time.sleep(0.5)

        subprocess.run(
            [
                "xdotool",
                "click",
                "1"
            ],
            check=False
        )

        log(
            "[FULLSCREEN] Clique real realizado em:",
            x,
            y
        )

        time.sleep(1)

        # O player que você mostrou anteriormente precisa
        # dessa segunda interação para chegar ao fullscreen.

        subprocess.run(
            [
                "xdotool",
                "click",
                "1"
            ],
            check=False
        )

        log("[FULLSCREEN] Segundo clique realizado.")

    except Exception as erro:

        log(
            "[FULLSCREEN] Erro X11:",
            erro
        )

    time.sleep(4)

    # --------------------------------------------------------
    # Apenas diagnóstico.
    # NÃO chamamos requestFullscreen.
    # --------------------------------------------------------

    try:

        estado = page.evaluate(
            """
            () => ({
                fullscreen:
                    !!document.fullscreenElement,

                width:
                    window.innerWidth,

                height:
                    window.innerHeight
            })
            """
        )

        log(
            "[FULLSCREEN] Estado:",
            estado
        )

    except Exception as erro:

        log(
            "[FULLSCREEN] Diagnóstico:",
            erro
        )


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_process

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

        # ====================================================
        # AUDIO
        # ====================================================

        "-thread_queue_size",
        "1024",

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

        "-profile:v",
        "main",

        "-level",
        "3.1",

        "-r",
        str(FPS),

        # bitrate moderado para Wi-Fi 2.4 GHz
        "-b:v",
        "1800k",

        "-maxrate",
        "2200k",

        "-bufsize",
        "4400k",

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
        "2",

        "-hls_list_size",
        "4",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        segmento,

        saida
    ]

    log("Comando FFmpeg:")
    log(" ".join(comando))
    log("")

    ffmpeg_process = subprocess.Popen(
        comando,
        stdout=subprocess.DEVNULL,
        stderr=None
    )

    time.sleep(6)

    if ffmpeg_process.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou inesperadamente."
        )

    log("FFmpeg funcionando.")


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    global browser_global

    log("")
    log("=" * 70)
    log("[6] INICIANDO CHROMIUM")
    log("=" * 70)

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=False,

            args=[

                "--no-sandbox",

                "--disable-setuid-sandbox",

                "--disable-dev-shm-usage",

                "--disable-gpu",

                "--disable-gpu-compositing",

                "--disable-gpu-rasterization",

                "--use-gl=swiftshader",

                "--ozone-platform=x11",

                "--autoplay-policy=no-user-gesture-required",

                "--no-first-run",

                "--no-default-browser-check",

                "--disable-popup-blocking",

                "--disable-notifications",

                "--disable-infobars",

                "--window-size=1280,720",

                "--window-position=0,0",

                "--force-device-scale-factor=1",

                "--disable-background-networking",

                "--disable-background-timer-throttling",

                "--disable-backgrounding-occluded-windows",

                "--disable-renderer-backgrounding"
            ]
        )

        browser_global = browser

        page = browser.new_page(
            viewport={
                "width": WIDTH,
                "height": HEIGHT
            }
        )

        # ====================================================
        # LOGS DO SITE
        # ====================================================

        page.on(
            "console",
            lambda msg:
                log(
                    "[CONSOLE]",
                    msg.text
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
        # ABRIR SITE
        # ====================================================

        log("")
        log("Abrindo página:")
        log(URL_ALVO)

        try:

            page.goto(
                URL_ALVO,
                wait_until="domcontentloaded",
                timeout=120000
            )

        except Exception as erro:

            log(
                "[AVISO] page.goto:",
                erro
            )

        log("")
        log("Aguardando página...")

        # ====================================================
        # MUITO IMPORTANTE:
        #
        # Não mexemos no currentTime.
        # Não trocamos src.
        # Não fazemos pause/play repetidamente.
        #
        # O próprio site faz:
        #
        # WebSocket
        # sincronização
        # seek
        # anúncios
        # conteúdo
        # onPlaying
        # ====================================================

        time.sleep(8)

        # ====================================================
        # ESPERA O SITE COMEÇAR A REPRODUZIR
        # ====================================================

        reproduzindo = verificar_reproducao(
            page
        )

        if not reproduzindo:

            log(
                "[PLAYER] O site ainda não está reproduzindo."
            )

            time.sleep(5)

        # ====================================================
        # FULLSCREEN
        # ====================================================

        preparar_fullscreen(
            page
        )

        # ====================================================
        # DIAGNÓSTICO FINAL
        # ====================================================

        diagnosticar(page)

        log("")
        log("=" * 70)
        log("CHROMIUM CONTINUARÁ RODANDO")
        log("=" * 70)

        # ====================================================
        # NÃO fechar o navegador.
        # Ele precisa permanecer capturando a página.
        # ====================================================

        while True:

            time.sleep(10)

            # Diagnóstico periódico leve.

            try:

                videos = page.locator(
                    "video"
                )

                quantidade = videos.count()

                if quantidade > 0:

                    estado = page.evaluate(
                        """
                        () => {

                            const v =
                                Array.from(
                                    document.querySelectorAll("video")
                                ).find(
                                    x =>
                                        x.videoWidth > 0 &&
                                        !x.paused
                                );

                            if (!v) return null;

                            return {

                                paused:
                                    v.paused,

                                currentTime:
                                    v.currentTime,

                                readyState:
                                    v.readyState,

                                width:
                                    v.videoWidth,

                                height:
                                    v.videoHeight
                            };
                        }
                        """
                    )

                    if estado:
                        log(
                            "[PLAYER]",
                            estado
                        )

            except Exception as erro:

                log(
                    "[PLAYER] Monitor:",
                    erro
                )


# ============================================================
# MAIN
# ============================================================

def main():

    log("=" * 70)
    log("INICIANDO TRANSMISSÃO")
    log("=" * 70)

    preparar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_tunel()

    iniciar_navegador()

    # Caso o navegador encerre, não deixa o processo morrer
    # silenciosamente.

    while True:
        time.sleep(60)


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("=" * 70)
        log("ERRO FATAL")
        log("=" * 70)
        log(repr(erro))
        log("")

        encerrar()
