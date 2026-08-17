import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

STREAM_DIR = Path("stream")

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
ffmpeg = None
public_url = ""


def log(*args):
    print(*args, flush=True)


def parar_processo(processo):
    if processo is None:
        return

    try:
        if processo.poll() is None:
            processo.terminate()
            processo.wait(timeout=5)
    except Exception:
        try:
            processo.kill()
        except Exception:
            pass


def encerrar(*args):
    log("")
    log("=" * 60)
    log("ENCERRANDO TRANSMISSAO")
    log("=" * 60)

    parar_processo(ffmpeg)

    for processo in reversed(processos):
        parar_processo(processo)

    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


def preparar_stream():
    STREAM_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    for arquivo in STREAM_DIR.iterdir():

        if arquivo.is_file():

            try:
                arquivo.unlink()
            except Exception:
                pass

    log("Ambiente preparado.")


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
            "tcp"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(processo)

    time.sleep(3)

    if processo.poll() is not None:
        raise RuntimeError(
            "Xvfb nao iniciou."
        )

    log("Xvfb OK.")


def iniciar_audio():

    log("[2] Iniciando PulseAudio...")

    runtime = "/tmp/pulse"

    os.makedirs(
        runtime,
        exist_ok=True
    )

    os.environ["PULSE_RUNTIME_PATH"] = runtime

    subprocess.run(
        [
            "pulseaudio",
            "--kill"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    time.sleep(3)

    info = subprocess.run(
        [
            "pactl",
            "info"
        ],
        capture_output=True,
        text=True,
        check=False
    )

    if info.returncode != 0:

        raise RuntimeError(
            "PulseAudio nao iniciou: "
            + info.stderr
        )

    sinks = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sinks"
        ],
        capture_output=True,
        text=True,
        check=False
    ).stdout

    if "webtv" not in sinks:

        resultado = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV"
            ],
            capture_output=True,
            text=True,
            check=False
        )

        if resultado.returncode != 0:

            raise RuntimeError(
                "Nao foi possivel criar o audio WebTV: "
                + resultado.stderr
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

    sources = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ],
        capture_output=True,
        text=True,
        check=False
    ).stdout

    if "webtv.monitor" not in sources:

        raise RuntimeError(
            "webtv.monitor nao foi encontrado."
        )

    log("PulseAudio OK.")


def criar_player():

    html = """<!DOCTYPE html>
<html lang="pt-BR">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>WebTV AO VIVO</title>

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

body {

    display: flex;

    align-items: center;

    justify-content: center;
}

video {

    width: 100vw;

    height: 100vh;

    object-fit: contain;

    background: #000;
}

#status {

    position: fixed;

    left: 12px;

    bottom: 12px;

    z-index: 100;

    padding: 8px 12px;

    background: rgba(0,0,0,.75);

    color: white;

    border-radius: 6px;

    font-family: Arial, sans-serif;

    font-size: 14px;
}

</style>

<script src="/hls.min.js"></script>

</head>

<body>

<video
    id="video"
    controls
    autoplay
    playsinline
></video>

<div id="status">
    Conectando ao vivo...
</div>

<script>

const video =
    document.getElementById("video");

const status =
    document.getElementById("status");

const stream =
    "/live.m3u8";


function mostrar(texto) {

    status.textContent = texto;
}


function iniciarPlayer() {

    if (
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ) {

        video.src = stream;

        video.addEventListener(
            "loadedmetadata",
            function () {

                video.play().catch(
                    function () {}
                );

                mostrar("AO VIVO");

            }
        );

        return;
    }


    if (
        !window.Hls ||
        !Hls.isSupported()
    ) {

        mostrar(
            "Este navegador nao suporta HLS."
        );

        return;
    }


    const hls =
        new Hls({

            liveSyncDurationCount: 2,

            liveMaxLatencyDurationCount: 6,

            maxBufferLength: 8,

            maxMaxBufferLength: 12,

            enableWorker: true
        });


    hls.loadSource(stream);


    hls.attachMedia(video);


    hls.on(
        Hls.Events.MANIFEST_PARSED,
        function () {

            video.play().catch(
                function () {}
            );

            mostrar("AO VIVO");

        }
    );


    hls.on(
        Hls.Events.ERROR,
        function (
            evento,
            dados
        ) {

            if (!dados.fatal) {
                return;
            }


            if (
                dados.type ===
                Hls.ErrorTypes.NETWORK_ERROR
            ) {

                mostrar(
                    "Reconectando..."
                );

                hls.startLoad();

                return;
            }


            if (
                dados.type ===
                Hls.ErrorTypes.MEDIA_ERROR
            ) {

                mostrar(
                    "Recuperando video..."
                );

                hls.recoverMediaError();

                return;
            }


            mostrar(
                "Erro no video. Recarregando..."
            );

            setTimeout(
                function () {

                    location.reload();

                },
                2000
            );

        }
    );
}


iniciarPlayer();

</script>

</body>

</html>
"""

    arquivo = (
        STREAM_DIR /
        "index.html"
    )

    arquivo.write_text(
        html,
        encoding="utf-8"
    )

    log(
        "Player criado."
    )


def iniciar_servidor():

    log("[3] Criando player...")

    criar_player()

    hls = (
        STREAM_DIR /
        "hls.min.js"
    )

    if not hls.exists():

        raise RuntimeError(
            "hls.min.js nao encontrado."
        )

    log("[3] Iniciando servidor HTTP...")

    processo = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(HTTP_PORT),
            "--bind",
            "0.0.0.0",
            "--directory",
            str(STREAM_DIR)
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(processo)

    time.sleep(2)

    if processo.poll() is not None:

        raise RuntimeError(
            "Servidor HTTP nao iniciou."
        )

    log(
        "Servidor HTTP OK na porta",
        HTTP_PORT
    )


def iniciar_cloudflare():

    global public_url

    log(
        "[4] Iniciando Cloudflare Tunnel..."
    )

    processo = subprocess.Popen(
        [
            "cloudflared",
            "tunnel",
            "--url",
            f"http://127.0.0.1:{HTTP_PORT}",
            "--no-autoupdate"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(processo)

    padrao = re.compile(
        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com"
    )

    limite = time.time() + 60

    while time.time() < limite:

        if processo.poll() is not None:
            break

        linha = processo.stdout.readline()

        if not linha:
            time.sleep(.2)
            continue

        linha = linha.strip()

        log(
            "[CLOUDFLARE]",
            linha
        )

        resultado = padrao.search(
            linha
        )

        if resultado:

            public_url = (
                resultado.group(0)
            )

            break


    if not public_url:

        raise RuntimeError(
            "Cloudflare nao forneceu o link."
        )


    link_player = (
        public_url +
        "/"
    )

    link_hls = (
        public_url +
        "/live.m3u8"
    )


    (STREAM_DIR / "PUBLIC_URL.txt").write_text(
        "PLAYER AO VIVO:\n"
        + link_player
        + "\n\n"
        + "HLS:\n"
        + link_hls
        + "\n",
        encoding="utf-8"
    )


    log("")

    log("=" * 60)

    log(
        "LINK DA TRANSMISSAO AO VIVO"
    )

    log(link_player)

    log("")

    log(
        "LINK HLS"
    )

    log(link_hls)

    log("=" * 60)

    log("")


def iniciar_ffmpeg():

    global ffmpeg

    log("[5] Iniciando FFmpeg...")

    ffmpeg = subprocess.Popen(
        [

            "ffmpeg",

            "-hide_banner",

            "-loglevel",
            "warning",

            "-y",


            "-f",
            "x11grab",

            "-video_size",
            f"{WIDTH}x{HEIGHT}",

            "-framerate",
            str(FPS),

            "-draw_mouse",
            "0",

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
            "44100",


            "-f",
            "hls",

            "-hls_time",
            "2",

            "-hls_list_size",
            "6",

            "-hls_allow_cache",
            "0",

            "-hls_flags",
            "delete_segments+append_list+independent_segments",

            "-hls_segment_filename",

            str(
                STREAM_DIR /
                "segment_%05d.ts"
            ),

            str(
                STREAM_DIR /
                "live.m3u8"
            )
        ],

        stdout=subprocess.DEVNULL,

        stderr=None
    )


    time.sleep(2)


    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou imediatamente."
        )


    log(
        "FFmpeg OK."
    )


def esperar_hls():

    log(
        "[6] Aguardando transmissao HLS..."
    )

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

    limite = (
        time.time() +
        40
    )


    while time.time() < limite:

        if (
            ffmpeg
            and
            ffmpeg.poll() is not None
        ):

            return False


        if playlist.exists():

            segmentos = list(
                STREAM_DIR.glob(
                    "segment_*.ts"
                )
            )

            if (
                playlist.stat().st_size > 0
                and
                segmentos
            ):

                log(
                    "HLS ONLINE."
                )

                return True


        time.sleep(1)


    return False


def iniciar_chromium():

    log(
        "[7] Iniciando Chromium..."
    )

    from playwright.sync_api import (
        sync_playwright
    )


    with sync_playwright() as playwright:

        navegador = (
            playwright.chromium.launch(
                headless=False,

                executable_path=(
                    "/usr/bin/chromium"
                ),

                args=[

                    "--no-sandbox",

                    "--disable-setuid-sandbox",

                    "--disable-dev-shm-usage",

                    "--ozone-platform=x11",

                    "--use-gl=swiftshader",

                    "--autoplay-policy=no-user-gesture-required",

                    "--window-size=1280,720",

                    "--window-position=0,0",

                    "--force-device-scale-factor=1",

                    "--start-fullscreen",

                    "--kiosk",

                    "--no-first-run",

                    "--no-default-browser-check",

                    "--disable-background-networking",

                    "--disable-background-timer-throttling",

                    "--disable-backgrounding-occluded-windows",

                    "--disable-renderer-backgrounding",

                    "--disable-popup-blocking",

                    "--disable-notifications"
                ]
            )
        )


        pagina = navegador.new_page(
            viewport={
                "width": WIDTH,
                "height": HEIGHT
            }
        )


        pagina.on(
            "console",
            lambda mensagem:
            log(
                "[BROWSER]",
                mensagem.text
            )
        )


        pagina.on(
            "pageerror",
            lambda erro:
            log(
                "[BROWSER ERROR]",
                erro
            )
        )


        log(
            "Abrindo WebTV..."
        )


        pagina.goto(
            URL_ALVO,
            wait_until="domcontentloaded",
            timeout=120000
        )


        time.sleep(8)


        try:

            pagina.mouse.click(
                WIDTH // 2,
                HEIGHT // 2
            )

        except Exception:
            pass


        try:

            pagina.evaluate(
                '''
                () => {

                    const videos =
                        Array.from(
                            document.querySelectorAll(
                                "video"
                            )
                        );

                    for (
                        const video of videos
                    ) {

                        video.autoplay = true;

                        video.playsInline = true;

                        try {
                            video.play();
                        } catch (e) {
                        }

                    }

                }
                '''
            )

        except Exception as erro:

            log(
                "[PLAYER] Aviso:",
                erro
            )


        try:

            pagina.evaluate(
                '''
                async () => {

                    try {

                        await document
                            .documentElement
                            .requestFullscreen();

                    } catch (e) {
                    }

                }
                '''
            )

        except Exception:
            pass


        log("")

        log("=" * 60)

        log(
            "TRANSMISSAO AO VIVO ONLINE"
        )

        log("")

        log(
            "PLAYER:"
        )

        log(
            public_url + "/"
        )

        log("")

        log(
            "HLS:"
        )

        log(
            public_url +
            "/live.m3u8"
        )

        log("=" * 60)

        log("")


        while True:

            time.sleep(5)


            if pagina.is_closed():

                raise RuntimeError(
                    "Chromium foi fechado."
                )


            try:

                pagina.evaluate(
                    '''
                    () => {

                        const videos =
                            Array.from(
                                document.querySelectorAll(
                                    "video"
                                )
                            );

                        for (
                            const video of videos
                        ) {

                            if (
                                video.paused
                                &&
                                !video.ended
                            ) {

                                try {
                                    video.play();
                                } catch (e) {
                                }

                            }

                        }

                    }
                    '''
                )

            except Exception:
                pass


def main():

    log("=" * 60)

    log(
        "INICIANDO WEBTV"
    )

    log("=" * 60)

    log("")


    preparar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_cloudflare()

    iniciar_ffmpeg()


    if not esperar_hls():

        raise RuntimeError(
            "O HLS nao ficou online."
        )


    iniciar_chromium()


if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")

        log("=" * 60)

        log(
            "ERRO FATAL"
        )

        log("=" * 60)

        log(
            repr(erro)
        )

        log("=" * 60)

        encerrar()
