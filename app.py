#!/usr/bin/env python3

import os
import re
import sys
import time
import signal
import shutil
import threading
import subprocess
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
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n3-102718744012"
    ".us-east5.run.app/watch"
)

STREAM_DIR = Path("stream")

stop_event = threading.Event()

xvfb = None
pulse = None
chromium = None
ffmpeg = None
cloudflared = None
http_server = None

public_url = None

lock = threading.RLock()


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

    stop_process(cloudflared, "Cloudflare Tunnel")
    stop_process(ffmpeg, "FFmpeg")
    stop_process(chromium, "Chromium")
    stop_process(pulse, "PulseAudio")
    stop_process(xvfb, "Xvfb")


def signal_handler(signum, frame):

    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============================================================
# UTILIDADES
# ============================================================

def command_exists(name):
    return shutil.which(name) is not None


def wait_process(process, seconds=1):

    if process is None:
        return False

    start = time.time()

    while time.time() - start < seconds:

        if process.poll() is not None:
            return False

        time.sleep(0.1)

    return True


# ============================================================
# VERIFICAÇÃO
# ============================================================

def check_programs():

    required = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
        "cloudflared",
        "curl",
    ]

    missing = []

    for program in required:

        if not command_exists(program):
            missing.append(program)

    chromium_found = False

    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):

        if command_exists(name):
            chromium_found = True
            break

    if not chromium_found:
        missing.append("chromium")

    if missing:

        raise RuntimeError(
            "Programas ausentes: "
            + ", ".join(missing)
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

        except Exception as exc:

            log(
                f"[STREAM] Erro removendo "
                f"{item}: {exc}"
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

    old_display = os.environ.get("DISPLAY")

    if old_display and old_display != DISPLAY:
        log(
            f"[XVFB] DISPLAY anterior: {old_display}"
        )

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    # Remove lock antigo.
    lock_file = Path(
        "/tmp",
        f".X{DISPLAY.lstrip(':')}-lock"
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
        env=env,
    )

    for _ in range(40):

        if xvfb.poll() is not None:

            raise RuntimeError(
                "Xvfb encerrou durante a inicialização."
            )

        result = subprocess.run(
            [
                "xdpyinfo",
                "-display",
                DISPLAY,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if result.returncode == 0:
            break

        time.sleep(0.25)

    else:

        raise RuntimeError(
            "Xvfb não ficou disponível."
        )

    os.environ["DISPLAY"] = DISPLAY

    log("Xvfb pronto.")


# ============================================================
# PULSEAUDIO
# ============================================================

def pulse_env():

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    runtime = Path(
        "/tmp",
        f"pulse-webtv-{os.getuid()}"
    )

    runtime.mkdir(
        parents=True,
        exist_ok=True
    )

    env["PULSE_RUNTIME_PATH"] = str(runtime)

    return env


def pactl_command(args):

    return subprocess.run(
        ["pactl"] + args,
        capture_output=True,
        text=True,
        env=pulse_env(),
    )


def pulse_running():

    result = pactl_command(["info"])

    return result.returncode == 0


def start_pulseaudio():

    global pulse

    sep()
    log("[3] Iniciando PulseAudio...")

    env = pulse_env()

    # Tenta desligar instância anterior.
    subprocess.run(
        [
            "pulseaudio",
            "--kill",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    time.sleep(1)

    pulse = subprocess.Popen(
        [
            "pulseaudio",
            "--daemonize=no",
            "--exit-idle-time=-1",
            "--disallow-exit",
            "--log-target=stderr",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    for _ in range(40):

        if pulse.poll() is not None:
            break

        if pulse_running():
            break

        time.sleep(0.5)

    if not pulse_running():

        raise RuntimeError(
            "PulseAudio não ficou disponível."
        )

    # --------------------------------------------------------
    # Procura sink
    # --------------------------------------------------------

    sink_exists = False

    result = pactl_command(
        [
            "list",
            "short",
            "sinks",
        ]
    )

    for line in result.stdout.splitlines():

        parts = line.split()

        if len(parts) >= 2:

            name = parts[1]

            if name == "webtv":
                sink_exists = True
                break

    # --------------------------------------------------------
    # Cria sink virtual
    # --------------------------------------------------------

    if not sink_exists:

        log(
            "[ÁUDIO] Criando sink virtual webtv..."
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
                "Falha ao criar o sink webtv: "
                + result.stderr.strip()
            )

    # --------------------------------------------------------
    # Aguarda sink
    # --------------------------------------------------------

    sink_ok = False

    for _ in range(30):

        result = pactl_command(
            [
                "list",
                "short",
                "sinks",
            ]
        )

        for line in result.stdout.splitlines():

            parts = line.split()

            if len(parts) >= 2:

                if parts[1] == "webtv":

                    sink_ok = True
                    break

        if sink_ok:
            break

        time.sleep(0.5)

    if not sink_ok:

        raise RuntimeError(
            "Não foi possível criar o dispositivo "
            "de áudio webtv."
        )

    # --------------------------------------------------------
    # Define sink padrão
    # --------------------------------------------------------

    pactl_command(
        [
            "set-default-sink",
            "webtv",
        ]
    )

    # --------------------------------------------------------
    # Confirma monitor
    # --------------------------------------------------------

    monitor_ok = False

    for _ in range(30):

        result = pactl_command(
            [
                "list",
                "short",
                "sources",
            ]
        )

        for line in result.stdout.splitlines():

            parts = line.split()

            if len(parts) >= 2:

                if parts[1] == "webtv.monitor":

                    monitor_ok = True
                    break

        if monitor_ok:
            break

        time.sleep(0.5)

    if not monitor_ok:

        raise RuntimeError(
            "O monitor webtv.monitor não foi criado."
        )

    # --------------------------------------------------------
    # Exibe fontes
    # --------------------------------------------------------

    result = pactl_command(
        [
            "list",
            "short",
            "sources",
        ]
    )

    log("Fontes de áudio:")
    log(result.stdout.strip())

    log("Sink webtv criado.")
    log("Monitor: webtv.monitor")
    log("Áudio pronto.")


# ============================================================
# HTTP
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def common_headers(self):

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

        self.send_header(
            "Cache-Control",
            "no-cache, no-store, must-revalidate",
        )

        self.send_header(
            "Pragma",
            "no-cache",
        )

        self.send_header(
            "Expires",
            "0",
        )

        self.send_header(
            "Connection",
            "close",
        )

    def send_data(
        self,
        data,
        content_type,
        status=200,
    ):

        self.send_response(status)

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Content-Length",
            str(len(data)),
        )

        self.common_headers()

        self.end_headers()

        try:
            self.wfile.write(data)
        except (
            BrokenPipeError,
            ConnectionResetError,
        ):
            pass

    def do_GET(self):

        path = self.path.split("?", 1)[0]

        # ====================================================
        # PLAYER
        # ====================================================

        if path in ("/", "/index.html"):

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
    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
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
    z-index: 9999;
    top: 12px;
    left: 12px;
    color: #fff;
    background: rgba(0,0,0,.75);
    padding: 8px 12px;
    border-radius: 5px;
    font-family: Arial,sans-serif;
    font-size: 14px;
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
let retryTimer = null;
let hlsScriptLoading = false;


function setStatus(text) {
    status.textContent = text;
}


function retry() {

    if (retryTimer)
        return;

    retryTimer = setTimeout(
        function() {

            retryTimer = null;
            start();

        },
        2000
    );
}


function destroyHls() {

    if (!hls)
        return;

    try {
        hls.destroy();
    } catch (e) {}

    hls = null;
}


function createHls() {

    if (!window.Hls)
        return;

    destroyHls();

    hls = new Hls({

        enableWorker: true,

        lowLatencyMode: false,

        backBufferLength: 30,

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

    hls.attachMedia(video);

    hls.on(
        Hls.Events.MANIFEST_PARSED,
        function() {

            setStatus("● AO VIVO");

            video.play().catch(
                function() {}
            );
        }
    );

    hls.on(
        Hls.Events.ERROR,
        function(event, data) {

            if (!data.fatal)
                return;

            setStatus(
                "Reconectando..."
            );

            if (
                data.type ===
                Hls.ErrorTypes.NETWORK_ERROR
            ) {

                try {
                    hls.startLoad();
                } catch (e) {}

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

            destroyHls();

            retry();
        }
    );
}


function loadHls() {

    if (window.Hls) {

        createHls();
        return;
    }

    if (hlsScriptLoading)
        return;

    hlsScriptLoading = true;

    const script =
    document.createElement("script");

    script.src =
    "https://cdn.jsdelivr.net/npm/hls.js@latest";

    script.onload =
    function() {

        hlsScriptLoading = false;

        if (
            window.Hls &&
            Hls.isSupported()
        ) {

            createHls();

        } else {

            setStatus(
                "HLS não suportado"
            );
        }
    };

    script.onerror =
    function() {

        hlsScriptLoading = false;

        setStatus(
            "Erro carregando HLS"
        );

        retry();
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

        video.play().catch(
            function() {}
        );

        setStatus(
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

    loadHls();
}


video.addEventListener(
    "playing",
    function() {

        setStatus(
            "● AO VIVO"
        );
    }
);


video.addEventListener(
    "waiting",
    function() {

        setStatus(
            "Buffering..."
        );
    }
);


video.addEventListener(
    "stalled",
    function() {

        setStatus(
            "Buffering..."
        );
    }
);


video.addEventListener(
    "error",
    function() {

        setStatus(
            "Reconectando..."
        );

        retry();
    }
);


start();

</script>

</body>
</html>
"""

            self.send_data(
                html.encode("utf-8"),
                "text/html; charset=utf-8",
            )

            return

        # ====================================================
        # HLS
        # ====================================================

        if path == "/live.m3u8":

            playlist = (
                STREAM_DIR / "live.m3u8"
            )

            if not playlist.exists():

                self.send_response(503)
                self.common_headers()
                self.end_headers()

                return

            try:

                data = playlist.read_bytes()

            except Exception:

                self.send_response(503)
                self.common_headers()
                self.end_headers()

                return

            self.send_data(
                data,
                "application/vnd.apple.mpegurl",
            )

            return

        # ====================================================
        # SEGMENTOS
        # ====================================================

        if path.startswith("/segment_"):

            filename = os.path.basename(path)

            if not re.fullmatch(
                r"segment_\d+\.ts",
                filename,
            ):

                self.send_response(400)
                self.common_headers()
                self.end_headers()

                return

            playlist_file = (
                STREAM_DIR / filename
            )

            if not playlist_file.exists():

                self.send_response(404)
                self.common_headers()
                self.end_headers()

                return

            try:

                size = playlist_file.stat().st_size

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "video/mp2t",
                )

                self.send_header(
                    "Content-Length",
                    str(size),
                )

                self.common_headers()

                self.end_headers()

                with open(
                    playlist_file,
                    "rb"
                ) as stream:

                    while True:

                        chunk = stream.read(
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
                            ConnectionResetError,
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
                "text/plain; charset=utf-8",
            )

            return

        # ====================================================
        # 404
        # ====================================================

        self.send_response(404)
        self.common_headers()
        self.end_headers()


def start_http():

    global http_server

    sep()
    log("[4] Iniciando servidor HTTP...")

    class ReusableHTTPServer(
        ThreadingHTTPServer
    ):

        allow_reuse_address = True
        daemon_threads = True

    http_server = ReusableHTTPServer(
        (HOST, PORT),
        StreamHandler,
    )

    thread = threading.Thread(
        target=http_server.serve_forever,
        daemon=True,
    )

    thread.start()

    log(
        f"Servidor HTTP ativo na porta {PORT}"
    )


# ============================================================
# CHROMIUM
# ============================================================

def get_chromium():

    names = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]

    for name in names:

        path = shutil.which(name)

        if path:
            return path

    raise RuntimeError(
        "Chromium não encontrado."
    )


def start_chromium():

    global chromium

    sep()
    log("[5] Iniciando Chromium...")

    browser = get_chromium()

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    env["PULSE_SINK"] = "webtv"

    env["PULSE_SOURCE"] = "webtv.monitor"

    profile = Path(
        "/tmp",
        f"webtv-chromium-{os.getuid()}"
    )

    shutil.rmtree(
        profile,
        ignore_errors=True,
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

        PAGE_URL,
    ]

    chromium = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        env=env,
    )

    for _ in range(30):

        if chromium.poll() is not None:

            raise RuntimeError(
                "Chromium encerrou durante "
                "a inicialização."
            )

        time.sleep(0.2)

    log("Chromium iniciado.")
    log("Abrindo página:")
    log(PAGE_URL)


def fullscreen():

    if not command_exists("xdotool"):
        return

    try:

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
                window,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        subprocess.run(
            [
                "xdotool",
                "key",
                "--window",
                window,
                "F11",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        log(
            "[TELA] Chromium em tela cheia."
        )

    except Exception:
        pass


# ============================================================
# FFMPEG
# ============================================================

def build_ffmpeg_command():

    playlist = (
        STREAM_DIR / "live.m3u8"
    )

    segment_pattern = (
        STREAM_DIR / "segment_%06d.ts"
    )

    return [

        "ffmpeg",

        "-hide_banner",

        "-loglevel",
        "warning",

        "-nostdin",

        # ----------------------------------------------------
        # VÍDEO
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
        # ÁUDIO
        # ----------------------------------------------------

        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-sample_rate",
        "44100",

        "-channels",
        "2",

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
        # VÍDEO
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
        # ÁUDIO
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
        "8",

        "-hls_flags",
        (
            "delete_segments+"
            "append_list+"
            "independent_segments+"
            "program_date_time"
        ),

        "-hls_delete_threshold",
        "4",

        "-hls_segment_filename",
        str(segment_pattern),

        str(playlist),
    ]


def start_ffmpeg():

    global ffmpeg

    sep()
    log("INICIANDO FFMPEG")

    command = build_ffmpeg_command()

    env = pulse_env()

    ffmpeg = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=env,
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
        daemon=True,
    ).start()

    time.sleep(4)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou durante "
            "a inicialização."
        )

    log("FFmpeg funcionando.")


def restart_ffmpeg():

    global ffmpeg

    log("[FFMPEG] Reiniciando...")

    stop_process(
        ffmpeg,
        "FFmpeg"
    )

    ffmpeg = None

    time.sleep(2)

    try:

        start_ffmpeg()

        if wait_hls():

            log(
                "[FFMPEG] Transmissão recuperada."
            )

    except Exception as exc:

        log(
            "[FFMPEG] Falha ao reiniciar: "
            + str(exc)
        )


# ============================================================
# HLS
# ============================================================

def wait_hls():

    sep()
    log("[HLS] Aguardando playlist...")

    playlist = (
        STREAM_DIR / "live.m3u8"
    )

    start = time.time()

    while (
        time.time() - start < 90
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

    log(
        "[HLS] Tempo limite aguardando playlist."
    )

    return False


# ============================================================
# CLOUDFLARE
# ============================================================

def find_cloudflared():

    path = shutil.which(
        "cloudflared"
    )

    if path:
        return path

    candidates = [

        Path("/usr/local/bin/cloudflared"),

        Path("/usr/bin/cloudflared"),

        Path.home()
        / ".local"
        / "bin"
        / "cloudflared",

    ]

    for candidate in candidates:

        if candidate.exists():
            return str(candidate)

    return None


def start_cloudflare():

    global cloudflared
    global public_url

    executable = find_cloudflared()

    if not executable:

        raise RuntimeError(
            "cloudflared não encontrado. "
            "O streaming.yml precisa instalá-lo."
        )

    sep()

    log(
        "[CLOUDFLARE] Iniciando Quick Tunnel..."
    )

    command = [

        executable,

        "tunnel",

        "--no-autoupdate",

        "--url",

        f"http://127.0.0.1:{PORT}",

    ]

    try:

        cloudflared = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    except Exception as exc:

        raise RuntimeError(
            "Não foi possível iniciar "
            "cloudflared: "
            + str(exc)
        )

    url_pattern = re.compile(
        r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com"
    )

    start = time.time()

    while (
        time.time() - start < 60
    ):

        if cloudflared.poll() is not None:

            raise RuntimeError(
                "cloudflared encerrou "
                "durante a inicialização."
            )

        line = cloudflared.stdout.readline()

        if line:

            line = line.strip()

            if line:
                log(
                    "[CLOUDFLARE] "
                    + line
                )

            match = url_pattern.search(
                line
            )

            if match:

                public_url = match.group(0)

                sep()

                log(
                    "LINK PÚBLICO"
                )

                sep()

                log(public_url)

                log("")

                log(
                    "LINK DA WEBTV:"
                )

                log(public_url)

                log("")

                log(
                    "LINK HLS:"
                )

                log(
                    public_url
                    + "/live.m3u8"
                )

                sep()

                return public_url

        else:

            time.sleep(0.5)

    raise RuntimeError(
        "Cloudflare Tunnel iniciou, "
        "mas não foi possível obter "
        "o endereço público."
    )


def cloudflare_alive():

    return (
        cloudflared is not None
        and cloudflared.poll() is None
    )


def restart_cloudflare():

    global cloudflared
    global public_url

    stop_process(
        cloudflared,
        "Cloudflare Tunnel"
    )

    cloudflared = None
    public_url = None

    time.sleep(2)

    try:

        return start_cloudflare()

    except Exception as exc:

        log(
            "[CLOUDFLARE] Falha: "
            + str(exc)
        )

        return None


# ============================================================
# MONITOR CLOUDFLARE
# ============================================================

def cloudflare_monitor():

    global cloudflared

    while not stop_event.is_set():

        time.sleep(10)

        if cloudflare_alive():
            continue

        if stop_event.is_set():
            return

        sep()

        log(
            "[CLOUDFLARE] Tunnel desconectado."
        )

        log(
            "[CLOUDFLARE] FFmpeg continua."
        )

        log(
            "[CLOUDFLARE] Tentando recuperar..."
        )

        sep()

        for attempt in range(1, 6):

            if stop_event.is_set():
                return

            log(
                f"[CLOUDFLARE] "
                f"Tentativa {attempt}/5"
            )

            url = restart_cloudflare()

            if url:

                log(
                    "[CLOUDFLARE] "
                    "Tunnel recuperado."
                )

                break

            time.sleep(
                min(attempt * 3, 15)
            )


# ============================================================
# MONITOR FFMPEG
# ============================================================

def ffmpeg_monitor():

    while not stop_event.is_set():

        time.sleep(5)

        if ffmpeg is None:
            continue

        if ffmpeg.poll() is not None:

            sep()

            log(
                "[FFMPEG] Processo parou."
            )

            log(
                "[FFMPEG] Tentando reiniciar."
            )

            sep()

            restart_ffmpeg()


# ============================================================
# MONITOR HLS
# ============================================================

def hls_monitor():

    playlist = (
        STREAM_DIR / "live.m3u8"
    )

    previous = 0
    unchanged = 0

    while not stop_event.is_set():

        time.sleep(10)

        if not playlist.exists():

            log(
                "[HLS] Playlist ausente."
            )

            unchanged += 1

            if unchanged >= 3:

                log(
                    "[HLS] HLS travado. "
                    "Reiniciando FFmpeg."
                )

                restart_ffmpeg()

                unchanged = 0

            continue

        try:

            current = (
                playlist.stat().st_mtime_ns
            )

        except Exception:
            continue

        if current == previous:

            unchanged += 1

            log(
                "[HLS] Playlist não atualizou."
            )

        else:

            unchanged = 0

        previous = current

        if unchanged >= 3:

            log(
                "[HLS] Playlist travada. "
                "Reiniciando FFmpeg."
            )

            restart_ffmpeg()

            unchanged = 0


# ============================================================
# MONITOR CHROMIUM
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
                "[CHROMIUM] Navegador caiu."
            )

            log(
                "[CHROMIUM] Reiniciando..."
            )

            try:

                start_chromium()

                time.sleep(3)

                fullscreen()

            except Exception as exc:

                log(
                    "[CHROMIUM] Falha: "
                    + str(exc)
                )


# ============================================================
# MONITOR PULSE
# ============================================================

def pulse_monitor():

    global pulse

    while not stop_event.is_set():

        time.sleep(10)

        if pulse_running():
            continue

        if stop_event.is_set():
            return

        sep()

        log(
            "[PULSE] PulseAudio caiu."
        )

        log(
            "[PULSE] A transmissão será "
            "encerrada para recuperação."
        )

        stop_event.set()

        return


# ============================================================
# MAIN
# ============================================================

def main():

    sep()
    log("WEBTV STREAM")
    log("CLOUDFLARE TUNNEL")
    sep()

    # --------------------------------------------------------
    # Verificação
    # --------------------------------------------------------

    check_programs()

    # --------------------------------------------------------
    # Stream
    # --------------------------------------------------------

    clean_stream()

    # --------------------------------------------------------
    # Xvfb
    # --------------------------------------------------------

    start_xvfb()

    # --------------------------------------------------------
    # Áudio
    # --------------------------------------------------------

    start_pulseaudio()

    # --------------------------------------------------------
    # HTTP
    # --------------------------------------------------------

    start_http()

    # --------------------------------------------------------
    # Chromium
    # --------------------------------------------------------

    start_chromium()

    time.sleep(5)

    fullscreen()

    time.sleep(2)

    # --------------------------------------------------------
    # FFmpeg
    # --------------------------------------------------------

    start_ffmpeg()

    # --------------------------------------------------------
    # HLS
    # --------------------------------------------------------

    if not wait_hls():

        raise RuntimeError(
            "HLS não foi criado."
        )

    # --------------------------------------------------------
    # Cloudflare
    # --------------------------------------------------------

    try:

        start_cloudflare()

    except Exception as exc:

        log(
            "[CLOUDFLARE] ERRO: "
            + str(exc)
        )

        log(
            "[CLOUDFLARE] "
            "A transmissão local continuará."
        )

    # --------------------------------------------------------
    # ATIVO
    # --------------------------------------------------------

    sep()

    log(
        "TRANSMISSÃO ATIVA"
    )

    sep()

    log(
        f"HTTP LOCAL: "
        f"http://127.0.0.1:{PORT}/"
    )

    log(
        f"HLS LOCAL: "
        f"http://127.0.0.1:{PORT}/live.m3u8"
    )

    if public_url:

        log("")

        log(
            "LINK PÚBLICO:"
        )

        log(public_url)

        log("")

        log(
            "LINK HLS:"
        )

        log(
            public_url
            + "/live.m3u8"
        )

    else:

        log(
            "[AVISO] Cloudflare "
            "Tunnel não está ativo."
        )

    sep()

    # --------------------------------------------------------
    # Monitores
    # --------------------------------------------------------

    threading.Thread(
        target=cloudflare_monitor,
        daemon=True,
    ).start()

    threading.Thread(
        target=ffmpeg_monitor,
        daemon=True,
    ).start()

    threading.Thread(
        target=hls_monitor,
        daemon=True,
    ).start()

    threading.Thread(
        target=chromium_monitor,
        daemon=True,
    ).start()

    threading.Thread(
        target=pulse_monitor,
        daemon=True,
    ).start()

    # --------------------------------------------------------
    # Executa continuamente
    # --------------------------------------------------------

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

    except Exception as exc:

        sep()

        log(
            "[ERRO FATAL]"
        )

        log(
            str(exc)
        )

        sep()

    finally:

        cleanup()
