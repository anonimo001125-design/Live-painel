import asyncio
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

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

browser = None


def log(*args):
    print(*args, flush=True)


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

    time.sleep(2)

    if processo.poll() is not None:
        raise RuntimeError("Xvfb nao iniciou.")

    log("Xvfb OK")


def iniciar_pulseaudio():
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
            "--log-target=stderr",
        ],
        env=ambiente,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    PROCESSOS.append(processo)

    time.sleep(3)

    if processo.poll() is not None:
        raise RuntimeError("PulseAudio nao iniciou.")

    criar_sink = subprocess.run(
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

    if criar_sink.returncode != 0:
        log("Sink talvez ja exista.")

    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        env=ambiente,
        check=False,
    )

    os.environ["PULSE_SINK"] = "webtv"

    log("PulseAudio OK")
    log("Sink: webtv")
    log("Monitor: webtv.monitor")


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


def criar_player():

    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>WebTV Ao Vivo</title>

<style>

html,
body {

    margin: 0;

    padding: 0;

    width: 100%;

    height: 100%;

    background: #000;

    overflow: hidden;

}

video {

    width: 100%;

    height: 100%;

    object-fit: contain;

    background: #000;

}

#status {

    position: fixed;

    top: 12px;

    left: 12px;

    right: 12px;

    z-index: 10;

    color: white;

    background: rgba(0,0,0,0.65);

    padding: 10px;

    border-radius: 8px;

    font-family: Arial, sans-serif;

    font-size: 15px;

}

</style>

</head>

<body>

<div id="status">
Conectando a transmissao...
</div>

<video
    id="video"
    controls
    autoplay
    playsinline
></video>

<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>

<script>

const video = document.getElementById("video");

const status = document.getElementById("status");

const stream = "/live.m3u8";


function aoVivo() {

    status.textContent = "AO VIVO";

    setTimeout(function() {

        status.style.display = "none";

    }, 3000);

}


function erro() {

    status.textContent =
        "Aguardando sinal da transmissao...";

}


if (
    video.canPlayType(
        "application/vnd.apple.mpegurl"
    )
) {

    video.src = stream;

    video.addEventListener(
        "loadedmetadata",
        function() {

            video.play()
                .then(aoVivo)
                .catch(erro);

        }
    );

} else if (
    window.Hls &&
    Hls.isSupported()
) {

    const hls = new Hls({

        liveSyncDurationCount: 3,

        enableWorker: true,

        lowLatencyMode: true

    });

    hls.loadSource(stream);

    hls.attachMedia(video);

    hls.on(
        Hls.Events.MANIFEST_PARSED,
        function() {

            video.play()
                .then(aoVivo)
                .catch(erro);

        }
    );

    hls.on(
        Hls.Events.ERROR,
        function(event, data) {

            if (data.fatal) {

                erro();

                hls.startLoad();

            }

        }
    );

} else {

    status.textContent =
        "Navegador sem suporte a HLS.";

}

</script>

</body>
</html>
"""

    caminho = os.path.join(
        STREAM_DIR,
        "index.html",
    )

    with open(
        caminho,
        "w",
        encoding="utf-8",
    ) as arquivo:

        arquivo.write(html)


def iniciar_servidor():

    log("[3] Iniciando servidor HTTP...")

    criar_player()

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
        f"Servidor local: http://127.0.0.1:{HTTP_PORT}/"
    )

    return servidor


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

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

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

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "48000",

        "-ac",
        "2",

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

    processo = subprocess.Popen(
        comando,
        env=os.environ.copy(),
    )

    PROCESSOS.append(processo)

    return processo


async def iniciar_navegador():

    log("[5] Iniciando Playwright...")

    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()

    ambiente = os.environ.copy()

    ambiente["DISPLAY"] = DISPLAY
    ambiente["PULSE_SINK"] = "webtv"

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

            "--window-size=1280,720",

            "--window-position=0,0",

            "--force-device-scale-factor=1",

            "--no-first-run",

            "--no-default-browser-check",

            "--disable-notifications",

            "--disable-popup-blocking",

        ],
    )

    pagina = await navegador.new_page(

        viewport={
            "width": WIDTH,
            "height": HEIGHT,
        }
    )

    log("[6] Abrindo pagina de origem...")

    await pagina.goto(
        URL_ALVO,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    log("Pagina carregada.")

    await pagina.wait_for_timeout(5000)

    try:

        await pagina.evaluate(
            """
            () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                videos.forEach(
                    video => {

                        video.autoplay = true;

                        video.playsInline = true;

                        const promessa =
                            video.play();

                        if (promessa) {

                            promessa.catch(
                                () => {}
                            );

                        }

                    }
                );

            }
            """
        )

    except Exception as erro:

        log(
            "Aviso ao iniciar video:",
            erro,
        )

    log("Player de origem iniciado.")

    return playwright, navegador, pagina


async def esperar_hls(ffmpeg):

    log("[7] Aguardando criacao do HLS...")

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8",
    )

    for tentativa in range(1, 31):

        await asyncio.sleep(1)

        if ffmpeg.poll() is not None:

            raise RuntimeError(
                "FFmpeg encerrou antes de criar o HLS."
            )

        if os.path.exists(playlist):

            tamanho = os.path.getsize(
                playlist
            )

            if tamanho > 0:

                log("HLS criado.")

                return

        log(
            f"Aguardando HLS... {tentativa}/30"
        )

    raise RuntimeError(
        "HLS nao foi criado em 30 segundos."
    )


def iniciar_cloudflare():

    log("[8] Iniciando Cloudflare Tunnel...")

    comando = [

        "cloudflared",

        "tunnel",

        "--no-autoupdate",

        "--url",

        f"http://127.0.0.1:{HTTP_PORT}",
    ]

    processo = subprocess.Popen(

        comando,

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

    while time.time() - inicio < 45:

        linha = processo.stdout.readline()

        if not linha:
            continue

        linha = linha.strip()

        if linha:
            log("[CLOUDFLARE]", linha)

        encontrado = padrao.search(linha)

        if encontrado:

            url = encontrado.group(0)

            log("")
            log("=" * 60)
            log("TRANSMISSAO AO VIVO")
            log(url + "/")
            log("=" * 60)
            log("")
            log("LINK HLS")
            log(url + "/live.m3u8")
            log("=" * 60)
            log("")

            return url

    raise RuntimeError(
        "Cloudflare Tunnel nao forneceu um endereco publico."
    )


async def main():

    log("")
    log("=" * 60)
    log("INICIANDO WEBTV")
    log("=" * 60)

    os.makedirs(
        STREAM_DIR,
        exist_ok=True,
    )

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

    iniciar_pulseaudio()

    iniciar_servidor()

    ffmpeg = iniciar_ffmpeg()

    await iniciar_navegador()

    await esperar_hls(ffmpeg)

    url_publica = iniciar_cloudflare()

    log("")
    log("=" * 60)
    log("WEBTV FUNCIONANDO")
    log("=" * 60)
    log("LINK PARA ABRIR NO CELULAR:")
    log(url_publica + "/")
    log("")
    log("LINK DIRETO HLS:")
    log(url_publica + "/live.m3u8")
    log("=" * 60)

    while True:

        await asyncio.sleep(5)

        if ffmpeg.poll() is not None:

            raise RuntimeError(
                "FFmpeg encerrou durante a transmissao."
            )

        cloudflare = PROCESSOS[-1]

        if cloudflare.poll() is not None:

            raise RuntimeError(
                "Cloudflare Tunnel encerrou."
            )


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("=" * 60)
        log("ERRO FATAL")
        log("=" * 60)
        log(str(erro))
        log("=" * 60)

        encerrar()
