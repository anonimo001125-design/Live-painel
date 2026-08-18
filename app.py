import os
import sys
import time
import signal
import subprocess
import threading
import re

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÃO
# ============================================================

STREAM_DIR = "stream"

DISPLAY = ":99"

# Tela virtual
WIDTH = 1280
HEIGHT = 720

# Stream mais leve para Wi-Fi 2.4 GHz
STREAM_WIDTH = 960
STREAM_HEIGHT = 540

FPS = 24

VIDEO_BITRATE = "1200k"
VIDEO_MAXRATE = "1400k"
VIDEO_BUFSIZE = "2400k"

AUDIO_BITRATE = "96k"

HTTP_PORT = 8080

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)


processos = []

ffmpeg_process = None
tunnel_process = None

encerrando = False


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global encerrando

    if encerrando:
        return

    encerrando = True

    log("")
    log("=" * 70)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 70)

    lista = list(processos)

    if ffmpeg_process:
        lista.append(ffmpeg_process)

    if tunnel_process:
        lista.append(tunnel_process)

    for processo in lista:

        try:
            if processo and processo.poll() is None:
                processo.terminate()
        except Exception:
            pass

    time.sleep(2)

    for processo in lista:

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
# STREAM
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
# PLAYER HTML
# ============================================================

def criar_player():

    log("")
    log("[1.5] Criando player HLS...")

    html = r'''<!DOCTYPE html>
<html lang="pt-BR">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"
>

<title>WebTV</title>

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

#player {

    position: fixed;

    inset: 0;

    width: 100vw;
    height: 100vh;

    background: #000;

}

#video {

    width: 100%;
    height: 100%;

    object-fit: contain;

    background: #000;
}

#controls {

    position: fixed;

    left: 0;
    right: 0;
    bottom: 0;

    padding: 15px;

    display: flex;

    justify-content: flex-end;

    background: linear-gradient(
        transparent,
        rgba(0,0,0,.75)
    );

    opacity: 1;

    transition: opacity .3s;

}

button {

    border: 0;

    border-radius: 8px;

    padding: 12px 18px;

    background: rgba(0,0,0,.75);

    color: white;

    font-size: 15px;

    cursor: pointer;

}

button:active {

    transform: scale(.97);

}

#status {

    position: fixed;

    top: 12px;
    left: 12px;

    padding: 6px 10px;

    border-radius: 6px;

    background: rgba(0,0,0,.65);

    color: #fff;

    font: 13px Arial;

    z-index: 10;

}

</style>

</head>

<body>

<div id="player">

    <video
        id="video"
        autoplay
        muted
        playsinline
        controls
    ></video>

    <div id="status">
        Conectando...
    </div>

    <div id="controls">

        <button id="fullscreen">
            ⛶ Tela cheia
        </button>

    </div>

</div>


<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>

<script>

const video =
    document.getElementById("video");

const status =
    document.getElementById("status");

const fullscreen =
    document.getElementById("fullscreen");

const stream =
    "live.m3u8";


function atualizarStatus(texto) {

    status.textContent = texto;

}


function entrarFullscreen() {

    const elemento =
        document.getElementById("player");

    if (
        document.fullscreenElement
    ) {

        document.exitFullscreen()
            .catch(() => {});

        return;
    }

    if (
        elemento.requestFullscreen
    ) {

        elemento.requestFullscreen()
            .catch(() => {});

        return;
    }

    if (
        video.webkitEnterFullscreen
    ) {

        video.webkitEnterFullscreen();

    }

}


fullscreen.addEventListener(
    "click",
    entrarFullscreen
);


video.addEventListener(
    "dblclick",
    entrarFullscreen
);


if (
    video.canPlayType("application/vnd.apple.mpegurl")
) {

    video.src = stream;

    video.play()
        .catch(() => {});

    atualizarStatus(
        "Ao vivo"
    );

} else if (
    Hls.isSupported()
) {

    const hls =
        new Hls({

            enableWorker: true,

            lowLatencyMode: false,

            maxBufferLength: 12,

            maxMaxBufferLength: 20,

            backBufferLength: 10,

            liveSyncDurationCount: 2,

            liveMaxLatencyDurationCount: 4

        });

    hls.loadSource(stream);

    hls.attachMedia(video);


    hls.on(
        Hls.Events.MANIFEST_PARSED,
        function() {

            atualizarStatus(
                "Ao vivo"
            );

            video.play()
                .catch(() => {});

        }
    );


    hls.on(
        Hls.Events.ERROR,
        function(
            event,
            data
        ) {

            console.log(
                "HLS:",
                data
            );

            if (
                data.fatal
            ) {

                atualizarStatus(
                    "Reconectando..."
                );

                if (
                    data.type ===
                    Hls.ErrorTypes.NETWORK_ERROR
                ) {

                    setTimeout(
                        function() {

                            hls.startLoad();

                        },
                        2000
                    );

                }

                else if (
                    data.type ===
                    Hls.ErrorTypes.MEDIA_ERROR
                ) {

                    hls.recoverMediaError();

                }

            }

        }
    );

} else {

    atualizarStatus(
        "Navegador não suporta HLS."
    );

}


document.addEventListener(
    "fullscreenchange",
    function() {

        if (
            document.fullscreenElement
        ) {

            fullscreen.textContent =
                "⛶ Sair da tela cheia";

        } else {

            fullscreen.textContent =
                "⛶ Tela cheia";

        }

    }
);

</script>

</body>

</html>
'''

    caminho = os.path.join(
        STREAM_DIR,
        "index.html"
    )

    with open(
        caminho,
        "w",
        encoding="utf-8"
    ) as arquivo:

        arquivo.write(html)

    log(
        "Player criado:",
        caminho
    )


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("")
    log("[2] Iniciando Xvfb...")

    os.environ[
        "DISPLAY"
    ] = DISPLAY

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
            "Xvfb não iniciou."
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
        ["pactl", "info"],
        capture_output=True,
        text=True
    )

    if teste.returncode != 0:

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
            "Criando áudio virtual..."
        )

        resultado = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",

                "sink_name=webtv",

                "sink_properties="
                "device.description=WebTV"
            ],

            capture_output=True,
            text=True
        )

        if resultado.returncode != 0:

            raise RuntimeError(
                resultado.stderr
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

    log(
        "Fontes de áudio:"
    )

    log(
        fontes.stdout
    )

    if "webtv.monitor" not in fontes.stdout:

        raise RuntimeError(
            "webtv.monitor não encontrado."
        )

    log(
        "Áudio pronto."
    )


# ============================================================
# HTTP
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

    processos.append(
        servidor
    )

    time.sleep(2)

    if servidor.poll() is not None:

        raise RuntimeError(
            "Servidor HTTP encerrou."
        )

    log(
        "HTTP ativo na porta",
        HTTP_PORT
    )


# ============================================================
# TÚNEL
# ============================================================

def iniciar_tunel():

    global tunnel_process

    log("")
    log("[5] Iniciando túnel público...")
    log("")

    comando = [

        "ssh",

        "-T",

        "-o",
        "StrictHostKeyChecking=no",

        "-o",
        "ServerAliveInterval=15",

        "-o",
        "ServerAliveCountMax=3",

        "-o",
        "TCPKeepAlive=yes",

        "-o",
        "ExitOnForwardFailure=yes",

        "-o",
        "ConnectTimeout=15",

        "-R",
        f"80:localhost:{HTTP_PORT}",

        "nokey@localhost.run"
    ]

    tunnel_process = subprocess.Popen(

        comando,

        stdin=subprocess.DEVNULL,

        stdout=subprocess.PIPE,

        stderr=subprocess.STDOUT,

        text=True,

        bufsize=1
    )

    processos.append(
        tunnel_process
    )

    def ler():

        encontrou = False

        for linha in iter(
            tunnel_process.stdout.readline,
            ""
        ):

            if not linha:
                continue

            linha = linha.strip()

            log(
                "[TUNEL]",
                linha
            )

            dominios = re.findall(
                r"https://([a-zA-Z0-9-]+\.lhr\.life)",
                linha
            )

            if dominios and not encontrou:

                encontrou = True

                dominio = dominios[0]

                url = (
                    "https://"
                    + dominio
                )

                log("")
                log("=" * 70)
                log("LINK DA TRANSMISSÃO")
                log("=" * 70)
                log("")
                log(
                    "LINK PRINCIPAL:"
                )
                log(
                    url
                    + "/"
                )
                log("")
                log(
                    "LINK HLS:"
                )
                log(
                    url
                    + "/live.m3u8"
                )
                log("")
                log("=" * 70)
                log("")

    threading.Thread(
        target=ler,
        daemon=True
    ).start()

    time.sleep(5)


# ============================================================
# FULLSCREEN VISUAL DO SITE
# ============================================================

def preparar_pagina(page):

    log("")
    log(
        "[PLAYER] Preparando vídeo para ocupar a tela..."
    )

    try:

        page.add_style_tag(
            content="""

            html,
            body {

                margin: 0 !important;
                padding: 0 !important;

                width: 100vw !important;
                height: 100vh !important;

                overflow: hidden !important;

                background: #000 !important;
            }

            video {

                position: fixed !important;

                left: 0 !important;
                top: 0 !important;

                width: 100vw !important;
                height: 100vh !important;

                max-width: none !important;
                max-height: none !important;

                object-fit: contain !important;

                z-index: 999999 !important;
            }

            """
        )

        log(
            "[PLAYER] CSS de tela cheia aplicado."
        )

    except Exception as erro:

        log(
            "[PLAYER] CSS:",
            erro
        )


# ============================================================
# REPRODUÇÃO
# ============================================================

def reproduzir(page):

    log(
        "[PLAYER] Reproduzindo vídeos..."
    )

    try:

        resultado = page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                const saida = [];

                for (
                    const video of videos
                ) {

                    try {

                        video.autoplay = true;

                        video.playsInline = true;

                        video.muted = false;

                        const p =
                            video.play();

                        if (p) {
                            await p;
                        }

                        saida.push({

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
                                video.currentTime

                        });

                    } catch (e) {

                        saida.push({
                            erro: String(e)
                        });

                    }

                }

                return saida;
            }
            """
        )

        log(
            "[PLAYER]",
            resultado
        )

    except Exception as erro:

        log(
            "[PLAYER]",
            erro
        )


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_process

    saida = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    log("")
    log("=" * 70)
    log("INICIANDO FFMPEG")
    log("=" * 70)

    comando = [

        "ffmpeg",

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

        # ----------------------------------------------------
        # VIDEO
        # ----------------------------------------------------

        "-thread_queue_size",
        "4096",

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
        # AUDIO
        # ----------------------------------------------------

        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ----------------------------------------------------
        # REDUZIR PARA 960x540
        # ----------------------------------------------------

        "-vf",
        f"scale={STREAM_WIDTH}:{STREAM_HEIGHT}:flags=fast_bilinear",

        # ----------------------------------------------------
        # H264
        # ----------------------------------------------------

        "-c:v",
        "libx264",

        "-preset",
        "ultrafast",

        "-tune",
        "zerolatency",

        "-pix_fmt",
        "yuv420p",

        "-profile:v",
        "main",

        "-level",
        "3.1",

        "-b:v",
        VIDEO_BITRATE,

        "-maxrate",
        VIDEO_MAXRATE,

        "-bufsize",
        VIDEO_BUFSIZE,

        "-r",
        str(FPS),

        "-g",
        "48",

        "-keyint_min",
        "48",

        "-sc_threshold",
        "0",

        # ----------------------------------------------------
        # AUDIO
        # ----------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        AUDIO_BITRATE,

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
        "4",

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
        "FFmpeg:"
    )

    log(
        " ".join(comando)
    )

    ffmpeg_process = subprocess.Popen(
        comando
    )

    time.sleep(5)

    if ffmpeg_process.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log(
        "FFmpeg funcionando."
    )


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

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

                "--disable-features=CalculateNativeWinOcclusion"

            ]
        )

        page = browser.new_page(
            viewport={
                "width": WIDTH,
                "height": HEIGHT
            }
        )

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

        log(
            "Abrindo página:"
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

        try:

            page.wait_for_selector(
                "video",
                state="attached",
                timeout=30000
            )

            log(
                "[PLAYER] Vídeo encontrado."
            )

        except Exception as erro:

            log(
                "[PLAYER] Vídeo não encontrado:",
                erro
            )

        time.sleep(3)

        reproduzir(
            page
        )

        time.sleep(2)

        # ----------------------------------------------------
        # EM VEZ DE REQUESTFULLSCREEN:
        #
        # FAZER O VÍDEO OCUPAR A TELA.
        # ----------------------------------------------------

        preparar_pagina(
            page
        )

        time.sleep(3)

        # ----------------------------------------------------
        # FFmpeg
        # ----------------------------------------------------

        iniciar_ffmpeg()

        log("")
        log("=" * 70)
        log("TRANSMISSÃO ATIVA")
        log("=" * 70)
        log("")

        while True:

            # ------------------------------------------------
            # FFmpeg
            # ------------------------------------------------

            if (
                ffmpeg_process
                and
                ffmpeg_process.poll()
                is not None
            ):

                log(
                    "[FFMPEG] Processo encerrou."
                )

                time.sleep(2)

                iniciar_ffmpeg()

            # ------------------------------------------------
            # TÚNEL
            # ------------------------------------------------

            if (
                tunnel_process
                and
                tunnel_process.poll()
                is not None
            ):

                log(
                    "[TUNEL] Conexão caiu."
                )

                # Não derruba a transmissão local.
                # O FFmpeg continua produzindo HLS.

            time.sleep(5)


# ============================================================
# MAIN
# ============================================================

def main():

    log("")
    log("=" * 70)
    log("WEBTV STREAM")
    log("=" * 70)

    preparar_stream()

    criar_player()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_tunel()

    iniciar_navegador()


if __name__ == "__main__":

    main()
