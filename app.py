#!/usr/bin/env python3

import os
import re
import sys
import time
import signal
import shutil
import platform
import threading
import subprocess
import urllib.request
import zipfile

from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


# ============================================================
# CONFIGURAÇÃO
# ============================================================

HOST = "0.0.0.0"
PORT = 8080

DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720
FPS = 30

PAGE_URL = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n3w3n-102718744012"
    ".us-east5.run.app/watch"
)

# Corrigido:
# o código procura o NOME da variável de ambiente.
NGROK_AUTHTOKEN = os.environ.get(
    "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk",
    ""
).strip()

STREAM_DIR = Path("stream")

NGROK_DIR = Path.home() / ".local" / "bin"
NGROK_PATH = NGROK_DIR / "ngrok"

stop_event = threading.Event()

xvfb = None
pulse = None
chromium = None
ffmpeg = None
ngrok = None
http_server = None

tunnel_url = None

pulse_runtime = None


# ============================================================
# LOG
# ============================================================

def log(text=""):
    print(text, flush=True)


def sep():
    log("=" * 70)


# ============================================================
# PROCESSOS
# ============================================================

def stop_process(process, name):

    if process is None:
        return

    try:

        if process.poll() is None:

            log(f"[STOP] Parando {name}...")

            process.terminate()

            try:
                process.wait(timeout=5)

            except subprocess.TimeoutExpired:

                process.kill()

                try:
                    process.wait(timeout=3)
                except Exception:
                    pass

    except Exception:
        pass


def cleanup():

    global http_server

    if stop_event.is_set():
        return

    stop_event.set()

    sep()
    log("ENCERRANDO WEBTV")
    sep()

    try:

        if http_server is not None:

            http_server.shutdown()
            http_server.server_close()

    except Exception:
        pass

    stop_process(ngrok, "ngrok")
    stop_process(ffmpeg, "FFmpeg")
    stop_process(chromium, "Chromium")
    stop_process(pulse, "PulseAudio")
    stop_process(xvfb, "Xvfb")


def signal_handler(signum, frame):

    cleanup()
    sys.exit(0)


signal.signal(
    signal.SIGINT,
    signal_handler
)

signal.signal(
    signal.SIGTERM,
    signal_handler
)


# ============================================================
# COMANDOS
# ============================================================

def command_exists(name):

    return shutil.which(name) is not None


def run_command(
    command,
    env=None,
    timeout=None
):

    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout
    )


# ============================================================
# VERIFICAÇÃO
# ============================================================

def check_programs():

    required = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
    ]

    missing = []

    for program in required:

        if not command_exists(program):
            missing.append(program)

    chromium_found = False

    for name in [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]:

        if command_exists(name):

            chromium_found = True
            break

    if not chromium_found:

        missing.append("chromium")

    if missing:

        raise RuntimeError(
            "Programas ausentes: "
            + ", ".join(missing)
            + "."
        )


# ============================================================
# STREAM
# ============================================================

def clean_stream():

    sep()
    log("[1] Limpando stream antigo...")

    STREAM_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    for item in STREAM_DIR.iterdir():

        try:

            if item.is_file() or item.is_symlink():

                item.unlink()

            elif item.is_dir():

                shutil.rmtree(item)

        except Exception as e:

            log(
                f"[STREAM] Erro removendo "
                f"{item}: {e}"
            )


# ============================================================
# XVFB
# ============================================================

def start_xvfb():

    global xvfb

    sep()

    log("[2] Iniciando Xvfb...")
    log(f"DISPLAY: {DISPLAY}")
    log(f"RESOLUÇÃO: {WIDTH}x{HEIGHT}")

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    # Remove lock antigo do Xvfb, se existir.
    lock_file = Path(
        f"/tmp/.X{DISPLAY.replace(':', '')}-lock"
    )

    try:

        if lock_file.exists():
            lock_file.unlink()

    except Exception:
        pass

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
            "-noreset",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env
    )

    for _ in range(30):

        if xvfb.poll() is not None:

            raise RuntimeError(
                "Xvfb encerrou durante a inicialização."
            )

        time.sleep(0.2)

    log("Xvfb pronto.")


# ============================================================
# PULSEAUDIO
# ============================================================

def create_pulse_runtime():

    global pulse_runtime

    pulse_runtime = (
        Path("/tmp")
        / f"webtv-pulse-{os.getuid()}"
    )

    if pulse_runtime.exists():

        shutil.rmtree(
            pulse_runtime,
            ignore_errors=True
        )

    pulse_runtime.mkdir(
        parents=True,
        exist_ok=True
    )

    os.chmod(
        pulse_runtime,
        0o700
    )


def pulse_env():

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    if pulse_runtime is None:
        create_pulse_runtime()

    env["PULSE_RUNTIME_PATH"] = str(
        pulse_runtime
    )

    env["PULSE_SERVER"] = (
        f"unix:{pulse_runtime}/native"
    )

    return env


def pactl_command(args):

    env = pulse_env()

    return subprocess.run(
        [
            "pactl",
            "-s",
            f"unix:{pulse_runtime}/native",
        ] + args,
        capture_output=True,
        text=True,
        env=env
    )


def pulse_sink_exists():

    result = pactl_command(
        ["list", "short", "sinks"]
    )

    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():

        parts = line.split()

        if len(parts) >= 2:

            if parts[1] == "webtv":
                return True

    return False


def pulse_monitor_exists():

    result = pactl_command(
        ["list", "short", "sources"]
    )

    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():

        parts = line.split()

        if len(parts) >= 2:

            if parts[1] == "webtv.monitor":
                return True

    return False


def start_pulseaudio():

    global pulse

    sep()
    log("[3] Iniciando PulseAudio...")

    create_pulse_runtime()

    env = pulse_env()

    # Tenta parar somente a instância relacionada
    # ao runtime utilizado por este programa.
    try:

        subprocess.run(
            [
                "pulseaudio",
                "--kill"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=5
        )

    except Exception:
        pass

    time.sleep(1)

    # Inicia PulseAudio.
    pulse = subprocess.Popen(
        [
            "pulseaudio",

            "--daemonize=no",

            "--system=false",

            "--exit-idle-time=-1",

            "--disallow-exit",

            "--log-target=stderr",

            "--load=module-native-protocol-unix "
            "auth-anonymous=1",

            "--load=module-null-sink "
            "sink_name=webtv "
            "sink_properties=device.description=WebTV "
            "rate=44100 "
            "channels=2 "
            "channel_map=front-left,front-right",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )

    # Aguarda servidor.
    ready = False

    for _ in range(40):

        if pulse.poll() is not None:
            break

        result = pactl_command(
            ["info"]
        )

        if result.returncode == 0:

            ready = True
            break

        time.sleep(0.5)

    if not ready:

        output = ""

        try:

            if pulse.stdout:

                output = pulse.stdout.read(
                    2000
                )

        except Exception:
            pass

        raise RuntimeError(
            "PulseAudio não ficou disponível.\n"
            + output
        )

    log(
        "[ÁUDIO] PulseAudio conectado."
    )

    # ========================================================
    # Garante sink webtv
    # ========================================================

    if not pulse_sink_exists():

        log(
            "[ÁUDIO] Sink webtv não encontrado."
        )

        log(
            "[ÁUDIO] Criando sink virtual..."
        )

        result = pactl_command(
            [
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV",
                "rate=44100",
                "channels=2",
                "channel_map=front-left,front-right",
            ]
        )

        if result.returncode != 0:

            raise RuntimeError(
                "Não foi possível criar o sink "
                "webtv:\n"
                + result.stderr.strip()
            )

    # Aguarda sink.
    sink_ok = False

    for _ in range(20):

        if pulse_sink_exists():

            sink_ok = True
            break

        time.sleep(0.5)

    if not sink_ok:

        raise RuntimeError(
            "Não foi possível criar o dispositivo "
            "de áudio webtv."
        )

    # ========================================================
    # Define saída padrão
    # ========================================================

    result = pactl_command(
        [
            "set-default-sink",
            "webtv"
        ]
    )

    if result.returncode != 0:

        log(
            "[ÁUDIO] Aviso: não foi possível "
            "definir sink padrão."
        )

    # ========================================================
    # Aguarda monitor
    # ========================================================

    monitor_ok = False

    for _ in range(20):

        if pulse_monitor_exists():

            monitor_ok = True
            break

        time.sleep(0.5)

    if not monitor_ok:

        raise RuntimeError(
            "O monitor webtv.monitor não foi criado."
        )

    result = pactl_command(
        ["list", "short", "sinks"]
    )

    log("Sinks de áudio:")

    if result.stdout.strip():
        log(result.stdout.strip())

    result = pactl_command(
        ["list", "short", "sources"]
    )

    log("Fontes de áudio:")

    if result.stdout.strip():
        log(result.stdout.strip())

    log(
        "Sink webtv criado com sucesso."
    )

    log(
        "Monitor: webtv.monitor"
    )

    log("Áudio pronto.")


# ============================================================
# HTTP
# ============================================================

class StreamHandler(
    BaseHTTPRequestHandler
):

    protocol_version = "HTTP/1.1"

    def log_message(
        self,
        format,
        *args
    ):
        pass

    def headers(self):

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Cache-Control",
            "no-cache, no-store, must-revalidate"
        )

        self.send_header(
            "Pragma",
            "no-cache"
        )

        self.send_header(
            "Expires",
            "0"
        )

        self.send_header(
            "Connection",
            "close"
        )

    def send_data(
        self,
        data,
        content_type,
        status=200
    ):

        self.send_response(status)

        self.send_header(
            "Content-Type",
            content_type
        )

        self.send_header(
            "Content-Length",
            str(len(data))
        )

        self.headers()

        self.end_headers()

        try:

            self.wfile.write(data)

        except (
            BrokenPipeError,
            ConnectionResetError
        ):
            pass

    def do_GET(self):

        path = self.path.split(
            "?",
            1
        )[0]

        # ====================================================
        # PLAYER
        # ====================================================

        if path in [
            "/",
            "/index.html"
        ]:

            html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>WEBTV AO VIVO</title>

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

    z-index: 9999;

    color: white;

    background:
        rgba(0,0,0,.75);

    padding:
        8px 12px;

    border-radius: 5px;

    font-family:
        Arial,
        sans-serif;
}

</style>

</head>

<body>

<div id="status">
Conectando...
</div>

<video
id="video"
controls
autoplay
muted
playsinline>
</video>

<script>

const video =
    document.getElementById("video");

const status =
    document.getElementById("status");

let hls = null;
let timer = null;
let loadingHls = false;


function statusText(text) {

    status.textContent = text;
}


function reconnect() {

    if (timer)
        return;

    timer = setTimeout(
        function() {

            timer = null;

            start();

        },
        2000
    );
}


function createHls() {

    if (!window.Hls)
        return;

    if (hls) {

        try {
            hls.destroy();
        } catch (e) {}

        hls = null;
    }

    hls = new Hls({

        enableWorker: true,

        lowLatencyMode: false,

        backBufferLength: 20,

        maxBufferLength: 30,

        maxMaxBufferLength: 60,

        liveSyncDurationCount: 3,

        liveMaxLatencyDurationCount: 8,

        manifestLoadingMaxRetry: 20,

        manifestLoadingRetryDelay: 1000,

        levelLoadingMaxRetry: 20,

        levelLoadingRetryDelay: 1000,

        fragLoadingMaxRetry: 20,

        fragLoadingRetryDelay: 1000
    });


    hls.loadSource(
        "/live.m3u8"
    );

    hls.attachMedia(
        video
    );


    hls.on(
        Hls.Events.MANIFEST_PARSED,
        function() {

            statusText(
                "● AO VIVO"
            );

            video.play()
                .catch(
                    function() {}
                );
        }
    );


    hls.on(
        Hls.Events.ERROR,
        function(
            event,
            data
        ) {

            if (!data.fatal)
                return;

            statusText(
                "Reconectando..."
            );


            if (
                data.type ===
                Hls.ErrorTypes.NETWORK_ERROR
            ) {

                try {

                    hls.startLoad();

                } catch (e) {}

                reconnect();

                return;
            }


            if (
                data.type ===
                Hls.ErrorTypes.MEDIA_ERROR
            ) {

                try {

                    hls.recoverMediaError();

                } catch (e) {}

                return;
            }


            try {

                hls.destroy();

            } catch (e) {}

            hls = null;

            reconnect();
        }
    );
}


function loadHlsJs() {

    if (loadingHls)
        return;

    loadingHls = true;

    const script =
        document.createElement(
            "script"
        );

    script.src =
        "https://cdn.jsdelivr.net/npm/hls.js@1";

    script.onload =
        function() {

            loadingHls = false;

            if (
                window.Hls &&
                Hls.isSupported()
            ) {

                createHls();

            } else {

                statusText(
                    "HLS não suportado"
                );

                reconnect();
            }
        };


    script.onerror =
        function() {

            loadingHls = false;

            statusText(
                "Erro carregando HLS"
            );

            reconnect();
        };


    document.head.appendChild(
        script
    );
}


function start() {

    if (
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ) {

        video.src =
            "/live.m3u8";

        video.play()
            .catch(
                function() {}
            );

        statusText(
            "● AO VIVO"
        );

        return;
    }


    if (
        window.Hls &&
        Hls.isSupported()
    ) {

        createHls();

        return;
    }


    loadHlsJs();
}


video.addEventListener(
    "playing",
    function() {

        statusText(
            "● AO VIVO"
        );
    }
);


video.addEventListener(
    "waiting",
    function() {

        statusText(
            "Buffering..."
        );
    }
);


video.addEventListener(
    "stalled",
    function() {

        statusText(
            "Buffering..."
        );
    }
);


start();

</script>

</body>
</html>
"""

            self.send_data(
                html.encode("utf-8"),
                "text/html; charset=utf-8"
            )

            return

        # ====================================================
        # HLS
        # ====================================================

        if path == "/live.m3u8":

            file = (
                STREAM_DIR /
                "live.m3u8"
            )

            if not file.exists():

                self.send_response(503)

                self.headers()

                self.end_headers()

                return

            try:

                data = file.read_bytes()

            except Exception:

                self.send_response(503)

                self.headers()

                self.end_headers()

                return

            self.send_data(
                data,
                "application/vnd.apple.mpegurl"
            )

            return

        # ====================================================
        # SEGMENTOS
        # ====================================================

        if path.startswith(
            "/segment_"
        ):

            filename = os.path.basename(
                path
            )

            if (
                ".." in filename
                or "/"
                in filename
                or "\\"
                in filename
            ):

                self.send_response(400)

                self.headers()

                self.end_headers()

                return

            if not re.fullmatch(
                r"segment_\d+\.ts",
                filename
            ):

                self.send_response(400)

                self.headers()

                self.end_headers()

                return

            file = (
                STREAM_DIR /
                filename
            )

            if not file.exists():

                self.send_response(404)

                self.headers()

                self.end_headers()

                return

            try:

                size = file.stat().st_size

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "video/mp2t"
                )

                self.send_header(
                    "Content-Length",
                    str(size)
                )

                self.headers()

                self.end_headers()

                with open(
                    file,
                    "rb"
                ) as f:

                    while True:

                        chunk = f.read(
                            1024 * 1024
                        )

                        if not chunk:
                            break

                        try:

                            self.wfile.write(
                                chunk
                            )

                        except (
                            BrokenPipeError,
                            ConnectionResetError
                        ):

                            break

            except Exception:
                pass

            return

        # ====================================================
        # HEALTH
        # ====================================================

        if path == "/health":

            self.send_data(
                b"OK\n",
                "text/plain; charset=utf-8"
            )

            return

        self.send_response(404)

        self.headers()

        self.end_headers()


def start_http():

    global http_server

    sep()

    log(
        "[4] Iniciando servidor HTTP..."
    )

    class ReusableServer(
        ThreadingHTTPServer
    ):

        allow_reuse_address = True

        daemon_threads = True

    http_server = ReusableServer(
        (HOST, PORT),
        StreamHandler
    )

    thread = threading.Thread(
        target=http_server.serve_forever,
        daemon=True
    )

    thread.start()

    log(
        f"Servidor HTTP ativo "
        f"na porta {PORT}"
    )


# ============================================================
# CHROMIUM
# ============================================================

def get_chromium():

    for name in [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]:

        path = shutil.which(name)

        if path:
            return path

    raise RuntimeError(
        "Chromium não encontrado."
    )


def start_chromium():

    global chromium

    sep()

    log(
        "[5] Iniciando Chromium..."
    )

    browser = get_chromium()

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    if pulse_runtime:

        env["PULSE_RUNTIME_PATH"] = (
            str(pulse_runtime)
        )

        env["PULSE_SERVER"] = (
            f"unix:{pulse_runtime}/native"
        )

    profile = (
        Path("/tmp")
        / f"webtv-chromium-{os.getuid()}"
    )

    shutil.rmtree(
        profile,
        ignore_errors=True
    )

    command = [

        browser,

        "--no-sandbox",

        "--disable-setuid-sandbox",

        "--disable-dev-shm-usage",

        "--disable-gpu",

        "--disable-software-rasterizer",

        "--disable-background-networking",

        "--disable-background-timer-throttling",

        "--disable-renderer-backgrounding",

        "--disable-backgrounding-occluded-windows",

        "--disable-extensions",

        "--disable-sync",

        "--disable-translate",

        "--disable-notifications",

        "--disable-popup-blocking",

        "--autoplay-policy=no-user-gesture-required",

        "--no-first-run",

        "--no-default-browser-check",

        "--disable-features="
        "Translate,"
        "BackForwardCache",

        "--start-fullscreen",

        "--kiosk",

        f"--window-size={WIDTH},{HEIGHT}",

        f"--user-data-dir={profile}",

        PAGE_URL
    ]

    chromium = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env
    )

    time.sleep(5)

    if chromium.poll() is not None:

        raise RuntimeError(
            "Chromium encerrou durante "
            "a inicialização."
        )

    log("Chromium iniciado.")

    log("Abrindo página:")

    log(PAGE_URL)


# ============================================================
# FULLSCREEN
# ============================================================

def fullscreen():

    if not command_exists(
        "xdotool"
    ):

        log(
            "[TELA] xdotool não encontrado."
        )

        return

    try:

        env = os.environ.copy()

        env["DISPLAY"] = DISPLAY

        result = subprocess.run(
            [
                "xdotool",
                "search",
                "--onlyvisible",
                "--class",
                "chromium",
            ],
            capture_output=True,
            text=True,
            env=env
        )

        windows = (
            result.stdout
            .strip()
            .splitlines()
        )

        if not windows:
            return

        window = windows[-1]

        subprocess.run(
            [
                "xdotool",
                "windowactivate",
                "--sync",
                window
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env
        )

        subprocess.run(
            [
                "xdotool",
                "key",
                "--window",
                window,
                "F11"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env
        )

        log(
            "[TELA] Chromium em tela cheia."
        )

    except Exception:
        pass


# ============================================================
# FFMPEG
# ============================================================

def start_ffmpeg():

    global ffmpeg

    sep()

    log("INICIANDO FFMPEG")

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

    command = [

        "ffmpeg",

        "-hide_banner",

        "-loglevel",
        "warning",

        "-nostdin",

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

        "-probesize",
        "32M",

        "-analyzeduration",
        "2M",

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
        # MAP
        # ----------------------------------------------------

        "-map",
        "0:v:0",

        "-map",
        "1:a:0",

        # ----------------------------------------------------
        # VIDEO
        # ----------------------------------------------------

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

        "-fps_mode",
        "cfr",

        "-g",
        str(FPS * 2),

        "-keyint_min",
        str(FPS * 2),

        "-sc_threshold",
        "0",

        "-b:v",
        "1400k",

        "-maxrate",
        "1600k",

        "-bufsize",
        "3200k",

        # ----------------------------------------------------
        # AUDIO
        # ----------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        "96k",

        "-ar",
        "44100",

        "-ac",
        "2",

        "-af",
        "aresample=async=1000:first_pts=0",

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
        "delete_segments+append_list"
        "+independent_segments"
        "+program_date_time",

        "-hls_delete_threshold",
        "3",

        "-hls_segment_filename",

        str(
            STREAM_DIR /
            "segment_%06d.ts"
        ),

        str(playlist)
    ]

    env = pulse_env()

    log(
        "[FFMPEG] Capturando vídeo "
        "do Xvfb."
    )

    log(
        "[FFMPEG] Capturando áudio "
        "de webtv.monitor."
    )

    ffmpeg = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )

    def output_reader():

        try:

            for line in ffmpeg.stdout:

                line = line.strip()

                if line:

                    log(
                        "[FFMPEG] "
                        + line
                    )

        except Exception:
            pass

    threading.Thread(
        target=output_reader,
        daemon=True
    ).start()

    time.sleep(4)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou durante "
            "a inicialização."
        )

    log(
        "FFmpeg funcionando."
    )


# ============================================================
# HLS
# ============================================================

def wait_hls():

    sep()

    log(
        "[HLS] Aguardando playlist..."
    )

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

    started = time.time()

    while (
        time.time() - started
        < 60
    ):

        if stop_event.is_set():

            return False

        if playlist.exists():

            segments = list(
                STREAM_DIR.glob(
                    "segment_*.ts"
                )
            )

            if len(segments) >= 2:

                log(
                    "[HLS] Playlist pronta."
                )

                return True

        time.sleep(1)

    return False


# ============================================================
# NGROK - DOWNLOAD
# ============================================================

def get_architecture():

    machine = platform.machine().lower()

    if machine in [
        "x86_64",
        "amd64",
    ]:

        return "amd64"

    if machine in [
        "aarch64",
        "arm64",
    ]:

        return "arm64"

    if machine in [
        "armv7l",
        "armv7",
    ]:

        return "arm"

    return None


def download_ngrok():

    global NGROK_PATH

    if NGROK_PATH.exists():

        try:

            NGROK_PATH.chmod(
                0o755
            )

            return str(
                NGROK_PATH
            )

        except Exception:
            pass

    architecture = (
        get_architecture()
    )

    if not architecture:

        log(
            "[NGROK] Arquitetura "
            "não suportada:"
        )

        log(
            platform.machine()
        )

        return None

    NGROK_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    zip_path = (
        Path("/tmp")
        / f"ngrok-{architecture}.zip"
    )

    url = (
        "https://bin.equinox.io/"
        "c/bNyj1mQVY4c/"
        f"ngrok-v3-stable-linux-{architecture}.zip"
    )

    sep()

    log(
        "[NGROK] Executável não encontrado."
    )

    log(
        "[NGROK] Baixando ngrok automaticamente..."
    )

    log(
        f"[NGROK] Arquitetura: {architecture}"
    )

    try:

        urllib.request.urlretrieve(
            url,
            zip_path
        )

    except Exception as e:

        log(
            "[NGROK] Falha no download:"
        )

        log(str(e))

        return None

    try:

        with zipfile.ZipFile(
            zip_path,
            "r"
        ) as archive:

            members = archive.namelist()

            ngrok_member = None

            for member in members:

                if (
                    member == "ngrok"
                    or member.endswith("/ngrok")
                ):

                    ngrok_member = member
                    break

            if not ngrok_member:

                raise RuntimeError(
                    "ngrok não encontrado "
                    "dentro do arquivo."
                )

            with archive.open(
                ngrok_member
            ) as source:

                with open(
                    NGROK_PATH,
                    "wb"
                ) as destination:

                    shutil.copyfileobj(
                        source,
                        destination
                    )

    except Exception as e:

        log(
            "[NGROK] Erro extraindo ngrok:"
        )

        log(str(e))

        return None

    try:

        NGROK_PATH.chmod(
            0o755
        )

    except Exception as e:

        log(
            "[NGROK] Não foi possível "
            "dar permissão ao executável:"
        )

        log(str(e))

        return None

    try:

        zip_path.unlink()

    except Exception:
        pass

    if not NGROK_PATH.exists():

        log(
            "[NGROK] Download não produziu "
            "o executável."
        )

        return None

    log(
        "[NGROK] ngrok instalado automaticamente."
    )

    return str(
        NGROK_PATH
    )


def get_ngrok():

    # 1. PATH
    path = shutil.which(
        "ngrok"
    )

    if path:

        return path

    # 2. Local
    if NGROK_PATH.exists():

        try:

            NGROK_PATH.chmod(
                0o755
            )

        except Exception:
            pass

        return str(
            NGROK_PATH
        )

    # 3. Instala automaticamente
    return download_ngrok()


# ============================================================
# NGROK TOKEN
# ============================================================

def configure_ngrok(
    executable
):

    if not NGROK_AUTHTOKEN:

        log(
            "[NGROK] NGROK_AUTHTOKEN "
            "não configurado."
        )

        log(
            "[NGROK] No GitHub, crie um "
            "secret chamado:"
        )

        log(
            "NGROK_AUTHTOKEN"
        )

        return False

    log(
        "[NGROK] Configurando autenticação..."
    )

    result = subprocess.run(
        [
            executable,
            "config",
            "add-authtoken",
            NGROK_AUTHTOKEN,
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:

        log(
            "[NGROK] Falha configurando token."
        )

        if result.stderr:

            log(
                result.stderr.strip()
            )

        return False

    log(
        "[NGROK] Token configurado."
    )

    return True


# ============================================================
# NGROK API
# ============================================================

def extract_ngrok_url():

    # Primeiro tenta curl.
    if command_exists(
        "curl"
    ):

        try:

            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "--max-time",
                    "5",
                    "http://127.0.0.1:4040/api/tunnels",
                ],
                capture_output=True,
                text=True,
                timeout=7
            )

            if result.returncode == 0:

                match = re.search(
                    r'"public_url"\s*:\s*"(https://[^"]+)"',
                    result.stdout
                )

                if match:

                    return match.group(1)

        except Exception:
            pass

    # Depois tenta Python.
    try:

        with urllib.request.urlopen(
            "http://127.0.0.1:4040/api/tunnels",
            timeout=5
        ) as response:

            data = response.read().decode(
                "utf-8",
                errors="ignore"
            )

            match = re.search(
                r'"public_url"\s*:\s*"(https://[^"]+)"',
                data
            )

            if match:

                return match.group(1)

    except Exception:
        pass

    return None


# ============================================================
# INICIA NGROK
# ============================================================

def start_ngrok():

    global ngrok
    global tunnel_url

    executable = get_ngrok()

    if not executable:

        log(
            "[NGROK] Não foi possível "
            "instalar/encontrar o ngrok."
        )

        return None

    if not NGROK_AUTHTOKEN:

        log(
            "[NGROK] NGROK_AUTHTOKEN "
            "não configurado."
        )

        return None

    if not configure_ngrok(
        executable
    ):

        return None

    # Se já existe processo, encerra.
    if ngrok is not None:

        stop_process(
            ngrok,
            "ngrok"
        )

        ngrok = None

    sep()

    log(
        "[NGROK] Iniciando túnel..."
    )

    try:

        ngrok = subprocess.Popen(
            [
                executable,
                "http",
                str(PORT),

                "--log=stdout",

                "--log-format=logfmt",

                "--log-level=info",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )

    except Exception as e:

        log(
            "[NGROK] Erro iniciando túnel:"
        )

        log(str(e))

        ngrok = None

        return None

    # Leitor de log.
    def read_ngrok_output():

        try:

            for line in ngrok.stdout:

                line = line.strip()

                if line:

                    # Evita poluir o terminal.
                    if (
                        "started tunnel"
                        in line.lower()
                    ):
                        log(
                            "[NGROK] "
                            + line
                        )

        except Exception:
            pass

    threading.Thread(
        target=read_ngrok_output,
        daemon=True
    ).start()

    started = time.time()

    while (
        time.time() - started
        < 40
    ):

        if stop_event.is_set():
            return None

        if ngrok.poll() is not None:

            log(
                "[NGROK] Processo encerrou."
            )

            ngrok = None

            return None

        url = extract_ngrok_url()

        if url:

            tunnel_url = url

            sep()

            log(
                "LINK PÚBLICO DA TRANSMISSÃO"
            )

            sep()

            log(
                tunnel_url
            )

            log("")

            log(
                "LINK HLS:"
            )

            log(
                tunnel_url
                + "/live.m3u8"
            )

            sep()

            return tunnel_url

        time.sleep(1)

    log(
        "[NGROK] Tempo esgotado esperando "
        "o túnel."
    )

    return None


# ============================================================
# NGROK MONITOR
# ============================================================

def ngrok_alive():

    return (
        ngrok is not None
        and ngrok.poll() is None
    )


def ngrok_monitor():

    global ngrok

    while not stop_event.is_set():

        time.sleep(10)

        if ngrok_alive():
            continue

        if stop_event.is_set():
            return

        sep()

        log(
            "[NGROK] Túnel desconectado."
        )

        log(
            "[NGROK] FFmpeg continua funcionando."
        )

        log(
            "[NGROK] Tentando reconectar..."
        )

        sep()

        ngrok = None

        connected = False

        for attempt in range(
            1,
            6
        ):

            if stop_event.is_set():
                return

            log(
                f"[NGROK] Tentativa "
                f"{attempt}/5"
            )

            url = start_ngrok()

            if url:

                log(
                    "[NGROK] Túnel reconectado."
                )

                connected = True

                break

            time.sleep(
                min(
                    attempt * 3,
                    15
                )
            )

        if not connected:

            log(
                "[NGROK] Não foi possível "
                "reconectar agora."
            )

            log(
                "[NGROK] Nova tentativa "
                "será feita automaticamente."
            )


# ============================================================
# FFMPEG MONITOR
# ============================================================

def ffmpeg_monitor():

    while not stop_event.is_set():

        time.sleep(5)

        if ffmpeg is None:
            continue

        if ffmpeg.poll() is not None:

            sep()

            log(
                "[ERRO] FFmpeg parou."
            )

            log(
                "[ERRO] Transmissão encerrada."
            )

            sep()

            stop_event.set()

            return


# ============================================================
# HLS MONITOR
# ============================================================

def hls_monitor():

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

    previous = 0

    while not stop_event.is_set():

        time.sleep(10)

        if not playlist.exists():

            log(
                "[HLS] ALERTA: playlist ausente."
            )

            continue

        try:

            current = (
                playlist.stat()
                .st_mtime_ns
            )

        except Exception:
            continue

        if current == previous:

            log(
                "[HLS] ALERTA: playlist "
                "não atualizou."
            )

        previous = current


# ============================================================
# CHROMIUM MONITOR
# ============================================================

def chromium_monitor():

    global chromium

    while not stop_event.is_set():

        time.sleep(10)

        if chromium is None:
            continue

        if chromium.poll() is not None:

            sep()

            log(
                "[CHROMIUM] Navegador encerrou."
            )

            log(
                "[CHROMIUM] Reiniciando..."
            )

            try:

                start_chromium()

                time.sleep(4)

                fullscreen()

            except Exception as e:

                log(
                    "[CHROMIUM] Falha:"
                )

                log(
                    str(e)
                )


# ============================================================
# MAIN
# ============================================================

def main():

    sep()

    log(
        "WEBTV STREAM 24H"
    )

    sep()

    # ========================================================
    # Verificação
    # ========================================================

    check_programs()

    # ========================================================
    # 1
    # ========================================================

    clean_stream()

    # ========================================================
    # 2
    # ========================================================

    start_xvfb()

    # ========================================================
    # 3
    # ========================================================

    start_pulseaudio()

    # ========================================================
    # 4
    # ========================================================

    start_http()

    # ========================================================
    # 5
    # ========================================================

    start_chromium()

    time.sleep(5)

    fullscreen()

    time.sleep(2)

    # ========================================================
    # 6
    # ========================================================

    start_ffmpeg()

    # ========================================================
    # 7
    # ========================================================

    if not wait_hls():

        raise RuntimeError(
            "HLS não foi criado."
        )

    # ========================================================
    # 8 - NGROK
    # ========================================================

    start_ngrok()

    # ========================================================
    # TRANSMISSÃO ATIVA
    # ========================================================

    sep()

    log(
        "TRANSMISSÃO ATIVA"
    )

    sep()

    log(
        "HLS LOCAL:"
    )

    log(
        f"http://127.0.0.1:{PORT}/live.m3u8"
    )

    if tunnel_url:

        log("")

        log(
            "LINK PÚBLICO:"
        )

        log(
            tunnel_url
        )

        log("")

        log(
            "LINK HLS:"
        )

        log(
            tunnel_url
            + "/live.m3u8"
        )

    else:

        log("")

        log(
            "[AVISO] Túnel público não está ativo."
        )

        log(
            "[AVISO] O HLS local continua funcionando."
        )

    sep()

    # ========================================================
    # MONITORES
    # ========================================================

    threading.Thread(
        target=ngrok_monitor,
        daemon=True
    ).start()

    threading.Thread(
        target=ffmpeg_monitor,
        daemon=True
    ).start()

    threading.Thread(
        target=hls_monitor,
        daemon=True
    ).start()

    threading.Thread(
        target=chromium_monitor,
        daemon=True
    ).start()

    # ========================================================
    # 24 HORAS
    # ========================================================

    while not stop_event.is_set():

        time.sleep(10)


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        pass

    except Exception as e:

        sep()

        log(
            "[ERRO FATAL]"
        )

        log(
            str(e)
        )

        sep()

    finally:

        cleanup()
