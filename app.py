import asyncio
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

# ============================================================
# CONFIGURAÇÕES
# ============================================================

STREAM_DIR = os.path.abspath("stream")

DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720
FPS = 30

HTTP_PORT = 8080

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

PROCESSOS = []


def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):
    log("")
    log("ENCERRANDO TRANSMISSAO...")

    for processo in reversed(PROCESSOS):
        try:
            if processo.poll() is None:
                processo.terminate()
        except Exception:
            pass

    time.sleep(2)

    for processo in reversed(PROCESSOS):
        try:
            if processo.poll() is None:
                processo.kill()
        except Exception:
            pass

    sys.exit(0)


signal.signal(signal.SIGINT, encerrar)
signal.signal(signal.SIGTERM, encerrar)


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("[1] Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    processo = subprocess.Popen(
        [
            "Xvfb",
            DISPLAY,
            "-screen",
            "0",
            f"{WIDTH}x{HEIGHT}x24",
            "-ac",
            "-nolisten",
            "tcp",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    PROCESSOS.append(processo)

    time.sleep(3)

    if processo.poll() is not None:
        raise RuntimeError("Xvfb nao iniciou.")

    log("Xvfb funcionando.")
    log(f"DISPLAY={DISPLAY}")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("[2] Iniciando PulseAudio...")

    runtime = "/tmp/pulse"

    os.makedirs(runtime, exist_ok=True)

    os.environ["PULSE_RUNTIME_PATH"] = runtime
    os.environ["DISPLAY"] = DISPLAY

    ambiente = os.environ.copy()

    subprocess.run(
        ["pulseaudio", "--kill"],
        env=ambiente,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    processo = subprocess.Popen(
        [
            "pulseaudio",
            "--daemonize=no",
            "--exit-idle-time=-1",
        ],
        env=ambiente,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    PROCESSOS.append(processo)

    time.sleep(3)

    if processo.poll() is not None:
        raise RuntimeError("PulseAudio nao iniciou.")

    # Tenta criar o sink.
    resultado = subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            "sink_name=webtv",
            "sink_properties=device.description=WebTV",
        ],
        env=ambiente,
        capture_output=True,
        text=True,
        check=False,
    )

    if resultado.returncode != 0:
        log("Sink WebTV provavelmente ja existe.")

    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        env=ambiente,
        check=False,
    )

    os.environ["PULSE_SINK"] = "webtv"

    fontes = subprocess.run(
        ["pactl", "list", "short", "sources"],
        env=ambiente,
        capture_output=True,
        text=True,
        check=False,
    )

    log("Fontes PulseAudio:")
    log(fontes.stdout)

    if "webtv.monitor" not in fontes.stdout:

        raise RuntimeError(
            "webtv.monitor nao foi encontrado."
        )

    log("Audio WebTV funcionando.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

class WebTVHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            directory=STREAM_DIR,
            **kwargs,
        )

    def end_headers(self):

        self.send_header(
            "Cache-Control",
            "no-cache, no-store, must-revalidate",
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

        super().end_headers()

    def guess_type(self, path):

        if path.endswith(".m3u8"):
            return "application/vnd.apple.mpegurl"

        if path.endswith(".ts"):
            return "video/mp2t"

        return super().guess_type(path)


def iniciar_servidor():

    log("[3] Iniciando servidor HTTP...")

    servidor = ThreadingHTTPServer(
        ("0.0.0.0", HTTP_PORT),
        WebTVHandler,
    )

    thread = threading.Thread(
        target=servidor.serve_forever,
        daemon=True,
    )

    thread.start()

    log(
        f"Servidor: http://127.0.0.1:{HTTP_PORT}/"
    )

    return servidor


# ============================================================
# FFmpeg
# ============================================================

def iniciar_ffmpeg():

    log("[4] Iniciando FFmpeg...")

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8",
    )

    segmento = os.path.join(
        STREAM_DIR,
        "segment_%06d.ts",
    )

    comando = [

        "ffmpeg",

        "-hide_banner",

        "-loglevel",
        "warning",

        "-y",

        # VIDEO
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

        # AUDIO
        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # VIDEO ENCODE
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
        str(FPS * 2),

        "-keyint_min",
        str(FPS * 2),

        "-sc_threshold",
        "0",

        # AUDIO ENCODE
        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "48000",

        "-ac",
        "2",

        # HLS
        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        segmento,

        playlist,
    ]

    log("Comando FFmpeg iniciado.")

    processo = subprocess.Popen(
        comando,
        env=os.environ.copy(),
    )

    PROCESSOS.append(processo)

    return processo


# ============================================================
# PLAYWRIGHT / CHROMIUM
# ============================================================

async def iniciar_navegador():

    log("[5] Iniciando Chromium...")

    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()

    ambiente = os.environ.copy()

    ambiente["DISPLAY"] = DISPLAY
    ambiente["PULSE_SINK"] = "webtv"

    # IMPORTANTE:
    # Não desativamos GPU/video decode.
    navegador = await playwright.chromium.launch(

        headless=False,

        executable_path="/usr/bin/chromium",

        env=ambiente,

        args=[

            "--no-sandbox",

            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",

            "--ozone-platform=x11",

            "--autoplay-policy=no-user-gesture-required",

            "--no-first-run",

            "--no-default-browser-check",

            "--disable-popup-blocking",

            "--disable-notifications",

            "--disable-background-timer-throttling",

            "--disable-backgrounding-occluded-windows",

            "--disable-renderer-backgrounding",

            "--window-size=1280,720",

            "--window-position=0,0",

            "--force-device-scale-factor=1",

        ],
    )

    pagina = await navegador.new_page(

        viewport={
            "width": WIDTH,
            "height": HEIGHT,
        },

        device_scale_factor=1,
    )

    # ========================================================
    # LOGS DO NAVEGADOR
    # ========================================================

    pagina.on(
        "console",
        lambda msg: log(
            "[CONSOLE]",
            msg.type,
            msg.text,
        ),
    )

    pagina.on(
        "pageerror",
        lambda erro: log(
            "[PAGE ERROR]",
            erro,
        ),
    )

    pagina.on(
        "requestfailed",
        lambda request: log(
            "[REQUEST FAILED]",
            request.url,
            request.failure,
        ),
    )

    log("")
    log("Abrindo pagina:")
    log(URL_ALVO)
    log("")

    try:

        await pagina.goto(
            URL_ALVO,
            wait_until="domcontentloaded",
            timeout=60000,
        )

    except Exception as erro:

        log(
            "[AVISO] goto:",
            erro,
        )

    await pagina.wait_for_timeout(10000)

    log("Pagina carregada.")

    # ========================================================
    # DIAGNÓSTICO DOS VÍDEOS
    # ========================================================

    try:

        diagnostico = await pagina.evaluate(
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

                            width:
                                video.videoWidth,

                            height:
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
                        };
                    }
                );
            }
            """
        )

        log("")
        log("==============================================")
        log("DIAGNOSTICO DOS VIDEOS")
        log("==============================================")

        if not diagnostico:

            log("NENHUM ELEMENTO VIDEO ENCONTRADO.")

        else:

            for video in diagnostico:
                log(video)

        log("==============================================")
        log("")

    except Exception as erro:

        log(
            "[DIAGNOSTICO] Erro:",
            erro,
        )

    # ========================================================
    # TENTAR PLAY SEM QUEBRAR O PLAYER
    # ========================================================

    try:

        resultado = await pagina.evaluate(
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

                        let playResult = "nao-testado";

                        try {

                            const promessa =
                                video.play();

                            if (promessa) {
                                await promessa;
                            }

                            playResult = "OK";

                        } catch (erro) {

                            playResult =
                                String(erro);
                        }

                        resultados.push({

                            index: i,

                            play:
                                playResult,

                            currentSrc:
                                video.currentSrc || "",

                            readyState:
                                video.readyState,

                            networkState:
                                video.networkState,

                            paused:
                                video.paused,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight
                        });

                    } catch (erro) {

                        resultados.push({

                            index: i,

                            erro:
                                String(erro)
                        });
                    }
                }

                return resultados;
            }
            """
        )

        log("RESULTADO PLAY:")
        log(resultado)

    except Exception as erro:

        log(
            "[PLAYER] Erro:",
            erro,
        )

    # ========================================================
    # TELA CHEIA / QUIOSQUE
    # ========================================================

    try:

        await pagina.evaluate(
            """
            () => {

                document.documentElement.style.margin = "0";
                document.documentElement.style.padding = "0";

                document.body.style.margin = "0";
                document.body.style.padding = "0";

                document.body.style.overflow = "hidden";

            }
            """
        )

    except Exception:
        pass

    return playwright, navegador, pagina


# ============================================================
# AGUARDAR HLS
# ============================================================

async def esperar_hls(ffmpeg):

    log("[6] Aguardando HLS...")

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8",
    )

    for tentativa in range(1, 31):

        await asyncio.sleep(1)

        if ffmpeg.poll() is not None:

            raise RuntimeError(
                "FFmpeg encerrou antes do HLS."
            )

        if os.path.exists(playlist):

            tamanho = os.path.getsize(
                playlist
            )

            if tamanho > 20:

                log("HLS funcionando.")

                return

        log(
            f"HLS aguardando... {tentativa}/30"
        )

    raise RuntimeError(
        "FFmpeg nao criou live.m3u8."
    )


# ============================================================
# CLOUDFLARE
# ============================================================

def iniciar_cloudflare():

    log("[7] Iniciando tunel publico...")

    processo = subprocess.Popen(

        [
            "cloudflared",
            "tunnel",
            "--no-autoupdate",
            "--url",
            f"http://127.0.0.1:{HTTP_PORT}",
        ],

        stdout=subprocess.PIPE,

        stderr=subprocess.STDOUT,

        text=True,

        bufsize=1,
    )

    PROCESSOS.append(processo)

    padrao = re.compile(
        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com"
    )

    inicio = time.time()

    while time.time() - inicio < 60:

        linha = processo.stdout.readline()

        if not linha:
            continue

        linha = linha.strip()

        if linha:
            log("[TUNEL]", linha)

        resultado = padrao.search(linha)

        if resultado:

            url = resultado.group(0)

            log("")
            log("==================================================")
            log("TRANSMISSAO ONLINE")
            log("==================================================")
            log("")
            log("LINK DA WEBTV:")
            log(url + "/")
            log("")
            log("LINK HLS:")
            log(url + "/live.m3u8")
            log("")
            log("==================================================")
            log("")

            return url

    raise RuntimeError(
        "Cloudflare nao forneceu URL publica."
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    log("")
    log("==================================================")
    log("WEBTV - INICIANDO")
    log("==================================================")

    os.makedirs(
        STREAM_DIR,
        exist_ok=True,
    )

    # Limpa segmentos antigos.
    for nome in os.listdir(STREAM_DIR):

        caminho = os.path.join(
            STREAM_DIR,
            nome,
        )

        try:

            if os.path.isfile(caminho):
                os.remove(caminho)

        except Exception:
            pass

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    ffmpeg = iniciar_ffmpeg()

    playwright, navegador, pagina = (
        await iniciar_navegador()
    )

    await esperar_hls(ffmpeg)

    url = iniciar_cloudflare()

    log("")
    log("==================================================")
    log("TRANSMISSAO PRONTA")
    log("==================================================")
    log("")
    log("ABRA ESTE LINK:")
    log(url + "/")
    log("")
    log("HLS DIRETO:")
    log(url + "/live.m3u8")
    log("")
    log("==================================================")

    while True:

        await asyncio.sleep(5)

        if ffmpeg.poll() is not None:

            raise RuntimeError(
                "FFmpeg encerrou."
            )

        if PROCESSOS[-1].poll() is not None:

            raise RuntimeError(
                "Tunel encerrou."
            )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("==================================================")
        log("ERRO FATAL")
        log("==================================================")
        log(str(erro))
        log("==================================================")

        encerrar()
