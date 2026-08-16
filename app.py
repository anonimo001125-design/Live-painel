import os
import re
import sys
import time
import signal
import shutil
import threading
import subprocess

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
tunnel_process = None

URL_PUBLICA = None


def log(*args):
    print(*args, flush=True)


def encerrar(*args):
    log("")
    log("Encerrando transmissão...")

    for processo in [ffmpeg_process, tunnel_process] + processos:
        if processo:
            try:
                if processo.poll() is None:
                    processo.terminate()
            except Exception:
                pass

    time.sleep(2)

    for processo in [ffmpeg_process, tunnel_process] + processos:
        if processo:
            try:
                if processo.poll() is None:
                    processo.kill()
            except Exception:
                pass

    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


# ============================================================
# PREPARAR STREAM
# ============================================================

def preparar_stream():
    os.makedirs(STREAM_DIR, exist_ok=True)

    for nome in os.listdir(STREAM_DIR):
        caminho = os.path.join(STREAM_DIR, nome)

        try:
            if os.path.isfile(caminho):
                os.remove(caminho)
        except Exception:
            pass

    # Página principal do player.
    # Ela toca o HLS no navegador usando hls.js.
    html = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>WebTV</title>

<style>
html, body {
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
</style>
</head>

<body>

<video
    id="video"
    controls
    autoplay
    playsinline
    webkit-playsinline>
</video>

<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>

<script>
const video = document.getElementById("video");
const stream = "/live.m3u8";

function iniciar() {

    if (video.canPlayType("application/vnd.apple.mpegurl")) {

        video.src = stream;

        video.addEventListener("loadedmetadata", () => {
            video.play().catch(() => {});
        });

        return;
    }

    if (window.Hls && Hls.isSupported()) {

        const hls = new Hls({
            enableWorker: true,
            lowLatencyMode: false,
            backBufferLength: 30
        });

        hls.loadSource(stream);
        hls.attachMedia(video);

        hls.on(Hls.Events.MANIFEST_PARSED, () => {
            video.play().catch(() => {});
        });

        hls.on(Hls.Events.ERROR, function(event, data) {

            if (data.fatal) {

                if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
                    hls.startLoad();
                }

                if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
                    hls.recoverMediaError();
                }
            }
        });

        return;
    }

    document.body.innerHTML =
        '<div style="color:white;font-family:Arial;text-align:center">' +
        'Seu navegador não suporta reprodução HLS.' +
        '</div>';
}

iniciar();
</script>

</body>
</html>
"""

    with open(
        os.path.join(STREAM_DIR, "index.html"),
        "w",
        encoding="utf-8"
    ) as f:
        f.write(html)

    # Arquivo inicial para o HLS
    with open(
        os.path.join(STREAM_DIR, "live.m3u8"),
        "w",
        encoding="utf-8"
    ) as f:
        f.write("#EXTM3U\n")


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("[1] Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    processo = subprocess.Popen([
        "Xvfb",
        DISPLAY,
        "-screen",
        "0",
        f"{WIDTH}x{HEIGHT}x24",
        "-ac",
        "-nolisten",
        "tcp"
    ])

    processos.append(processo)

    time.sleep(3)

    if processo.poll() is not None:
        raise RuntimeError("Xvfb não iniciou.")

    log("Xvfb OK.")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("[2] Iniciando PulseAudio...")

    runtime = "/tmp/pulse"

    os.makedirs(runtime, exist_ok=True)

    os.environ["PULSE_RUNTIME_PATH"] = runtime
    os.environ["PULSE_SINK"] = "webtv"

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        check=False
    )

    time.sleep(3)

    resultado = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True
    )

    if resultado.returncode != 0:
        raise RuntimeError("PulseAudio não iniciou.")

    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        capture_output=True,
        text=True
    )

    if "webtv" not in sinks.stdout:

        criar = subprocess.run(
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

        if criar.returncode != 0:
            log(criar.stderr)

    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        check=False
    )

    time.sleep(2)

    fontes = subprocess.run(
        ["pactl", "list", "short", "sources"],
        capture_output=True,
        text=True
    )

    log("Fontes de áudio:")
    log(fontes.stdout)

    if "webtv.monitor" not in fontes.stdout:
        raise RuntimeError("webtv.monitor não encontrado.")

    log("PulseAudio OK.")


# ============================================================
# FFmpeg
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_process

    log("[3] Iniciando FFmpeg...")

    m3u8 = os.path.join(STREAM_DIR, "live.m3u8")

    comando = [
        "ffmpeg",
        "-y",

        # ÁUDIO
        "-f",
        "pulse",
        "-i",
        "webtv.monitor",

        # VÍDEO
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

        # VÍDEO
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

        "-r",
        str(FPS),

        "-g",
        "60",

        "-keyint_min",
        "60",

        # ÁUDIO
        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        # HLS
        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "6",

        "-hls_flags",
        "delete_segments+append_list",

        "-hls_segment_filename",
        os.path.join(STREAM_DIR, "segment_%05d.ts"),

        m3u8
    ]

    ffmpeg_process = subprocess.Popen(
        comando,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    time.sleep(5)

    if ffmpeg_process.poll() is not None:
        raise RuntimeError("FFmpeg encerrou.")

    log("FFmpeg OK.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_http():

    log("[4] Iniciando servidor HTTP...")

    servidor = subprocess.Popen([
        "python3",
        "-m",
        "http.server",
        str(HTTP_PORT),
        "--directory",
        STREAM_DIR,
        "--bind",
        "0.0.0.0"
    ])

    processos.append(servidor)

    time.sleep(2)

    if servidor.poll() is not None:
        raise RuntimeError("Servidor HTTP não iniciou.")

    log("Servidor HTTP OK na porta", HTTP_PORT)


# ============================================================
# TÚNEL LOCALHOST.RUN
# ============================================================

def iniciar_tunel():

    global tunnel_process
    global URL_PUBLICA

    log("")
    log("[5] Iniciando túnel público...")
    log("Aguardando URL do localhost.run...")
    log("")

    comando = [
        "ssh",
        "-T",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "ExitOnForwardFailure=yes",
        "-R",
        f"80:127.0.0.1:{HTTP_PORT}",
        "nokey@localhost.run"
    ]

    tunnel_process = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(tunnel_process)

    def monitorar():

        global URL_PUBLICA

        try:

            for linha in iter(
                tunnel_process.stdout.readline,
                ""
            ):

                if not linha:
                    continue

                linha = linha.strip()

                log("[TUNEL]", linha)

                # Procura qualquer URL HTTPS gerada pelo túnel
                encontrados = re.findall(
                    r"https://[A-Za-z0-9._-]+\.localhost\.run",
                    linha
                )

                if encontrados and URL_PUBLICA is None:

                    URL_PUBLICA = encontrados[0]

                    log("")
                    log("=" * 70)
                    log("          TRANSMISSÃO ONLINE")
                    log("=" * 70)
                    log("")
                    log("PLAYER:")
                    log(URL_PUBLICA)
                    log("")
                    log("HLS DIRETO:")
                    log(URL_PUBLICA.rstrip("/") + "/live.m3u8")
                    log("")
                    log("=" * 70)
                    log("")

        except Exception as erro:
            log("[TUNEL] Erro:", erro)

    threading.Thread(
        target=monitorar,
        daemon=True
    ).start()

    # Espera a URL aparecer
    inicio = time.time()

    while URL_PUBLICA is None and time.time() - inicio < 30:

        if tunnel_process.poll() is not None:
            raise RuntimeError(
                "localhost.run encerrou antes de fornecer a URL."
            )

        time.sleep(1)

    if URL_PUBLICA is None:

        log("")
        log("ATENÇÃO: o túnel iniciou, mas a URL não foi identificada.")
        log("Verifique as linhas [TUNEL] acima.")
        log("")


# ============================================================
# CHROMIUM
# ============================================================

def iniciar_chromium():

    log("[6] Iniciando Chromium...")

    from pyppeteer import launch

    ambiente = os.environ.copy()

    ambiente["DISPLAY"] = DISPLAY
    ambiente["PULSE_SINK"] = "webtv"

    navegador = launch(
        headless=False,

        executablePath="/usr/bin/chromium",

        env=ambiente,

        autoClose=False,

        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",

            "--ozone-platform=x11",

            # Tela cheia / quiosque
            "--kiosk",
            "--start-fullscreen",
            "--start-maximized",

            f"--window-size={WIDTH},{HEIGHT}",
            "--window-position=0,0",

            "--force-device-scale-factor=1",

            # Autoplay
            "--autoplay-policy=no-user-gesture-required",

            # Estabilidade
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            "--disable-notifications",

            # Não desativar a aceleração de vídeo
            # porque alguns sites dependem dela.
            "--use-gl=swiftshader"
        ]
    )

    return navegador


# ============================================================
# NAVEGADOR ASYNC
# ============================================================

async def navegador_async():

    navegador = await iniciar_chromium()

    page = await navegador.newPage()

    await page.setViewport({
        "width": WIDTH,
        "height": HEIGHT,
        "deviceScaleFactor": 1
    })

    page.on(
        "console",
        lambda mensagem:
            log("[BROWSER]", mensagem.text)
    )

    page.on(
        "pageerror",
        lambda erro:
            log("[PAGE ERROR]", erro)
    )

    log("")
    log("Abrindo:")
    log(URL_ALVO)
    log("")

    try:
