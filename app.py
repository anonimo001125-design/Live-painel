app.py

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

tunnel_url = None

process_lock = threading.Lock()


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

                log(
                    f"[STOP] Forçando encerramento de {name}..."
                )

                process.kill()

                try:
                    process.wait(timeout=3)
                except Exception:
                    pass

    except Exception as e:

        log(
            f"[STOP] Erro ao parar {name}: {e}"
        )


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

    log("WEBTV FINALIZADA")


def signal_handler(signum, frame):

    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============================================================
# UTILITÁRIOS
# ============================================================

def command_exists(name):

    return shutil.which(name) is not None


def run_command(command, env=None, timeout=15):

    try:

        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    except Exception as e:

        log(
            "[CMD] Erro: "
            + str(e)
        )

        return None


# ============================================================
# DEPENDÊNCIAS
# ============================================================

def check_programs():

    sep()
    log("VERIFICANDO DEPENDÊNCIAS")

    required = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
        "curl",
    ]

    missing = []

    for program in required:

        if not command_exists(program):

            missing.append(program)

    chromium_found = False

    for browser in [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]:

        if command_exists(browser):

            chromium_found = True
            break

    if not chromium_found:

        missing.append("chromium")

    if not command_exists("cloudflared"):

        missing.append("cloudflared")

    if missing:

        raise RuntimeError(
            "Programas ausentes: "
            + ", ".join(missing)
        )

    log("Todas as dependências estão disponíveis.")


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
                f"[STREAM] Não consegui remover "
                f"{item}: {e}"
            )


# ============================================================
# XVFB
# ============================================================

def start_xvfb():

    global xvfb

    sep()
    log("[2] Iniciando Xvfb...")

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

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

    for _ in range(20):

        if xvfb.poll() is not None:

            raise RuntimeError(
                "Xvfb encerrou durante a inicialização."
            )

        time.sleep(0.25)

    log("Xvfb pronto.")


# ============================================================
# PULSEAUDIO
# ============================================================

def pulse_env():

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    runtime = (
        Path("/tmp")
        / f"pulse-webtv-{os.getuid()}"
    )

    runtime.mkdir(
        parents=True,
        exist_ok=True
    )

    env["PULSE_RUNTIME_PATH"] = str(runtime)

    return env


def pactl(args):

    return subprocess.run(
        ["pactl"] + args,
        capture_output=True,
        text=True,
        env=pulse_env(),
    )


def start_pulseaudio():

    global pulse

    sep()
    log("[3] Iniciando PulseAudio...")

    env = pulse_env()

    subprocess.run(
        ["pulseaudio", "--kill"],
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
            "--log-target=stderr",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    ready = False

    for _ in range(30):

        result = pactl(["info"])

        if result.returncode == 0:

            ready = True
            break

        if pulse.poll() is not None:
            break

        time.sleep(0.5)

    if not ready:

        raise RuntimeError(
            "PulseAudio não ficou disponível."
        )

    sinks = pactl(
        ["list", "short", "sinks"]
    )

    sink_exists = False

    for item in sinks.stdout.splitlines():

        parts = item.split()

        if len(parts) >= 2:

            if parts[1] == "webtv":

                sink_exists = True
                break

    if not sink_exists:

        log(
            "[ÁUDIO] Criando sink webtv..."
        )

        result = pactl(
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
                "Não foi possível criar o sink webtv: "
                + result.stderr.strip()
            )

    pactl(
        ["set-default-sink", "webtv"]
    )

    monitor_ok = False

    for _ in range(20):

        sources = pactl(
            ["list", "short", "sources"]
        )

        for item in sources.stdout.splitlines():

            parts = item.split()

            if len(parts) >= 2:

                if parts[1] == "webtv.monitor":

                    monitor_ok = True
                    break

        if monitor_ok:
            break

        time.sleep(0.5)

    if not monitor_ok:

        raise RuntimeError(
            "webtv.monitor não foi criado."
        )

    log("Fontes de áudio:")

    log(
        sources.stdout.strip()
    )

    log("Sink webtv criado.")
    log("Monitor: webtv.monitor")
    log("Áudio pronto.")


# ============================================================
# HTTP
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def common_headers(self):

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

    def send_bytes(
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

        self.common_headers()

        self.end_headers()

        try:

            self.wfile.write(data)

        except (
            BrokenPipeError,
            ConnectionResetError
        ):
            pass

    def do_GET(self):

        path = self.path.split("?", 1)[0]

        # ----------------------------------------------------
        # PLAYER
        # ----------------------------------------------------

        if path in ["/", "/index.html"]:

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

    top: 10px;
    left: 10px;

    z-index: 100;

    padding: 8px 12px;

    color: white;

    background: rgba(0,0,0,.75);

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
playsinline
preload="auto">
</video>

<script>

const video =
document.getElementById("video");

const status =
document.getElementById("status");

let hls = null;

let retryTimer = null;


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

    if (hls) {

        try {
            hls.destroy();
        } catch(e) {}

        hls = null;

    }

}


function startHls() {

    destroyHls();

    if (!window.Hls) {

        loadHlsLibrary();

        return;

    }

    if (!Hls.isSupported()) {

        setStatus(
            "HLS não suportado"
        );

        return;

    }

    hls = new Hls({

        enableWorker: true,

        lowLatencyMode: false,

        backBufferLength: 20,

        maxBufferLength: 30,

        maxMaxBufferLength: 60,

        liveSyncDurationCount: 3,

        liveMaxLatencyDurationCount: 10,

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

            setStatus(
                "● AO VIVO"
            );

            video.play().catch(
                function(){}
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
                } catch(e) {}

                return;

            }


            if (
                data.type ===
                Hls.ErrorTypes.MEDIA_ERROR
            ) {

                try {
                    hls.recoverMediaError();
                } catch(e) {}

                return;

            }


            destroyHls();

            retry();

        }
    );

}


function loadHlsLibrary() {

    const script =
    document.createElement("script");

    script.src =
    "https://cdn.jsdelivr.net/npm/hls.js@latest";

    script.onload =
    function() {

        startHls();

    };

    script.onerror =
    function() {

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

    setStatus(
        "Conectando..."
    );


    if (
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ) {

        video.src =
        "/live.m3u8";

        video.play().catch(
            function(){}
        );

        setStatus(
            "● AO VIVO"
        );

        return;

    }


    startHls();

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

            self.send_bytes(
                html.encode("utf-8"),
                "text/html; charset=utf-8"
            )

            return


        # ----------------------------------------------------
        # HLS
        # ----------------------------------------------------

        if path == "/live.m3u8":

            file = STREAM_DIR / "live.m3u8"

            if not file.exists():

                self.send_response(503)

                self.common_headers()

                self.end_headers()

                return

            try:

                data = file.read_bytes()

            except Exception:

                self.send_response(503)

                self.common_headers()

                self.end_headers()

                return

            self.send_bytes(
                data,
                "application/vnd.apple.mpegurl"
            )

            return


        # ----------------------------------------------------
        # SEGMENTOS
        # ----------------------------------------------------

        if path.startswith("/segment_"):

            filename = os.path.basename(path)

            if not re.fullmatch(
                r"segment_\d+\.ts",
                filename
            ):

                self.send_response(400)

                self.common_headers()

                self.end_headers()

                return

            file = STREAM_DIR / filename

            if not file.exists():

                self.send_response(404)

                self.common_headers()

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

                self.common_headers()

                self.end_headers()

                with open(file, "rb") as stream:

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
                            ConnectionResetError
                        ):

                            break

            except Exception:
                pass

            return


        # ----------------------------------------------------
        # HEALTH
        # ----------------------------------------------------

        if path == "/health":

            self.send_bytes(
                b"OK\n",
                "text/plain; charset=utf-8"
            )

            return


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
        StreamHandler
    )

    thread = threading.Thread(
        target=http_server.serve_forever,
        daemon=True
    )

    thread.start()

    time.sleep(1)

    log(
        f"Servidor HTTP ativo na porta {PORT}"
    )


# ============================================================
# TESTAR HTTP
# ============================================================

def test_http():

    log(
        "[TESTE] Verificando servidor HTTP..."
    )

    for _ in range(20):

        result = run_command(
            [
                "curl",
                "-fsS",
                "--max-time",
                "5",
                f"http://127.0.0.1:{PORT}/health"
            ],
            timeout=10
        )

        if (
            result is not None
            and result.returncode == 0
            and result.stdout.strip() == "OK"
        ):

            log(
                "[TESTE] HTTP funcionando."
            )

            return True

        time.sleep(1)

    raise RuntimeError(
        "Servidor HTTP não respondeu."
    )


# ============================================================
# CHROMIUM
# ============================================================

def get_chromium():

    for name in [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable"
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
    log("[5] Iniciando Chromium...")

    browser = get_chromium()

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    profile = Path(
        f"/tmp/webtv-chromium-{os.getuid()}"
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

    time.sleep(6)

    if chromium.poll() is not None:

        raise RuntimeError(
            "Chromium encerrou durante a inicialização."
        )

    log("Chromium iniciado.")
    log("Página:")
    log(PAGE_URL)


# ============================================================
# FULLSCREEN
# ============================================================

def fullscreen():

    if not command_exists("xdotool"):

        log(
            "[TELA] xdotool não encontrado."
        )

        return

    try:

        result = subprocess.run(
            [
                "xdotool",
                "search",
                "--onlyvisible",
                "--class",
                "chromium"
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        windows = (
            result.stdout.strip()
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
            stderr=subprocess.DEVNULL
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
            stderr=subprocess.DEVNULL
        )

        log(
            "[TELA] Chromium em tela cheia."
        )

    except Exception as e:

        log(
            "[TELA] Falha: "
            + str(e)
        )


# ============================================================
# FFMPEG
# ============================================================

def build_ffmpeg_command():

    playlist = (
        STREAM_DIR / "live.m3u8"
    )

    return [

        "ffmpeg",

        "-hide_banner",

        "-loglevel",
        "warning",

        "-nostdin",

        "-y",

        # ----------------------------------------------------
        # VÍDEO X11
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
        # ÁUDIO PULSE
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
        "1500k",

        "-maxrate",
        "1800k",

        "-bufsize",
        "3600k",

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
        "delete_segments+append_list+independent_segments+program_date_time",

        "-hls_delete_threshold",
        "4",

        "-hls_segment_filename",

        str(
            STREAM_DIR /
            "segment_%06d.ts"
        ),

        str(playlist)
    ]


def start_ffmpeg():

    global ffmpeg

    sep()
    log("INICIANDO FFMPEG")

    playlist = (
        STREAM_DIR / "live.m3u8"
    )

    try:
        playlist.unlink()
    except FileNotFoundError:
        pass

    for file in STREAM_DIR.glob(
        "segment_*.ts"
    ):

        try:
            file.unlink()
        except Exception:
            pass

    command = build_ffmpeg_command()

    env = pulse_env()

    ffmpeg = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )

    def read_ffmpeg():

        try:

            for text in ffmpeg.stdout:

                text = text.strip()

                if text:

                    log(
                        "[FFMPEG] "
                        + text
                    )

        except Exception:
            pass

    threading.Thread(
        target=read_ffmpeg,
        daemon=True
    ).start()

    time.sleep(4)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou durante a inicialização."
        )

    log("FFmpeg funcionando.")


# ============================================================
# HLS
# ============================================================

def wait_hls(timeout=60):

    sep()
    log("[HLS] Aguardando playlist...")

    playlist = (
        STREAM_DIR / "live.m3u8"
    )

    start = time.time()

    while (
        time.time() - start
        < timeout
    ):

        if stop_event.is_set():
            return False

        if ffmpeg is not None:

            if ffmpeg.poll() is not None:

                raise RuntimeError(
                    "FFmpeg encerrou enquanto "
                    "o HLS estava sendo criado."
                )

        if playlist.exists():

            segments = list(
                STREAM_DIR.glob(
                    "segment_*.ts"
                )
            )

            if len(segments) >= 2:

                try:

                    text = playlist.read_text(
                        encoding="utf-8"
                    )

                    if (
                        "#EXTM3U" in text
                        and "#EXTINF" in text
                    ):

                        log(
                            "[HLS] Playlist pronta."
                        )

                        return True

                except Exception:
                    pass

        time.sleep(1)

    return False


# ============================================================
# CLOUDFLARE QUICK TUNNEL
# ============================================================

def extract_cloudflare_url(text):

    patterns = [

        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com",

        r"https://[a-zA-Z0-9-]+\.trycloudflare\.app"

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            return match.group(0)

    return None


def start_cloudflare():

    global cloudflared
    global tunnel_url

    executable = shutil.which(
        "cloudflared"
    )

    if not executable:

        raise RuntimeError(
            "cloudflared não encontrado."
        )

    sep()
    log(
        "[TUNEL] Iniciando Cloudflare Quick Tunnel..."
    )

    env = os.environ.copy()

    env.pop(
        "TUNNEL_TOKEN",
        None
    )

    env.pop(
        "CLOUDFLARE_TUNNEL_TOKEN",
        None
    )

    command = [

        executable,

        "tunnel",

        "--no-autoupdate",

        "--url",

        f"http://127.0.0.1:{PORT}"
    ]

    cloudflared = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )

    start = time.time()

    while (
        time.time() - start
        < 45
    ):

        if stop_event.is_set():
            return None

        if cloudflared.poll() is not None:

            log(
                "[TUNEL] cloudflared encerrou."
            )

            return None

        line_text = (
            cloudflared.stdout.readline()
        )

        if not line_text:

            time.sleep(0.2)

            continue

        line_text = line_text.strip()

        if line_text:

            log(
                "[CLOUDFLARE] "
                + line_text
            )

        found = extract_cloudflare_url(
            line_text
        )

        if found:

            tunnel_url = found

            sep()

            log(
                "TRANSMISSÃO PÚBLICA"
            )

            sep()

            log(
                "LINK PRINCIPAL:"
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

            sep()

            return tunnel_url

    log(
        "[TUNEL] Cloudflare não forneceu URL."
    )

    return None


# ============================================================
# TESTE DO TÚNEL
# ============================================================

def test_public_url():

    if not tunnel_url:

        return False

    log(
        "[TUNEL] Testando link público..."
    )

    for attempt in range(1, 11):

        if stop_event.is_set():
            return False

        result = run_command(
            [
                "curl",
                "-k",
                "-L",
                "-sS",
                "--max-time",
                "10",
                tunnel_url
                + "/health"
            ],
            timeout=15
        )

        if (
            result is not None
            and result.returncode == 0
            and result.stdout.strip() == "OK"
        ):

            log(
                "[TUNEL] Link público respondendo."
            )

            return True

        log(
            f"[TUNEL] Teste {attempt}/10 aguardando..."
        )

        time.sleep(2)

    log(
        "[TUNEL] O túnel existe, mas ainda "
        "não respondeu ao teste."
    )

    return False


# ============================================================
# MONITOR CLOUDFLARE
# ============================================================

def monitor_cloudflare():

    global cloudflared
    global tunnel_url

    while not stop_event.is_set():

        time.sleep(10)

        if stop_event.is_set():
            break

        if cloudflared is not None:

            if cloudflared.poll() is None:

                continue

        sep()

        log(
            "[TUNEL] Cloudflare Tunnel caiu."
        )

        log(
            "[TUNEL] FFmpeg continuará rodando."
        )

        log(
            "[TUNEL] Tentando reconectar..."
        )

        tunnel_url = None

        for attempt in range(1, 6):

            if stop_event.is_set():
                return

            log(
                f"[TUNEL] Tentativa {attempt}/5"
            )

            try:

                url = start_cloudflare()

                if url:

                    if test_public_url():

                        log(
                            "[TUNEL] Reconectado."
                        )

                        break

            except Exception as e:

                log(
                    "[TUNEL] Erro: "
                    + str(e)
                )

            time.sleep(
                min(
                    attempt * 3,
                    15
                )
            )

        else:

            log(
                "[TUNEL] Não foi possível "
                "reconectar agora."
            )

            log(
                "[TUNEL] Nova tentativa automática "
                "será feita."
            )


# ============================================================
# MONITOR FFMPEG
# ============================================================

def monitor_ffmpeg():

    global ffmpeg

    while not stop_event.is_set():

        time.sleep(5)

        if ffmpeg is None:
            continue

        if ffmpeg.poll() is None:
            continue

        sep()

        log(
            "[FFMPEG] FFmpeg parou."
        )

        log(
            "[FFMPEG] Reiniciando..."
        )

        try:

            start_ffmpeg()

            if wait_hls(60):

                log(
                    "[FFMPEG] Transmissão recuperada."
                )

            else:

                log(
                    "[FFMPEG] HLS não voltou."
                )

        except Exception as e:

            log(
                "[FFMPEG] Erro ao reiniciar: "
                + str(e)
            )

            time.sleep(5)


# ============================================================
# MONITOR CHROMIUM
# ============================================================

def monitor_chromium():

    global chromium

    while not stop_event.is_set():

        time.sleep(10)

        if chromium is None:
            continue

        if chromium.poll() is None:
            continue

        sep()

        log(
            "[CHROMIUM] Navegador encerrou."
        )

        log(
            "[CHROMIUM] Reiniciando..."
        )

        try:

            start_chromium()

            time.sleep(3)

            fullscreen()

        except Exception as e:

            log(
                "[CHROMIUM] Erro: "
                + str(e)
            )


# ============================================================
# MONITOR HLS
# ============================================================

def monitor_hls():

    playlist = (
        STREAM_DIR / "live.m3u8"
    )

    last_mtime = 0

    while not stop_event.is_set():

        time.sleep(15)

        if not playlist.exists():

            log(
                "[HLS] ALERTA: playlist ausente."
            )

            continue

        try:

            mtime = (
                playlist.stat().st_mtime_ns
            )

        except Exception:
            continue

        if (
            last_mtime != 0
            and mtime == last_mtime
        ):

            log(
                "[HLS] ALERTA: playlist "
                "não está atualizando."
            )

        last_mtime = mtime


# ============================================================
# MAIN
# ============================================================

def main():

    sep()
    log("INICIANDO WEBTV")
    sep()

    check_programs()

    clean_stream()

    start_xvfb()

    start_pulseaudio()

    start_http()

    test_http()

    start_chromium()

    time.sleep(5)

    fullscreen()

    time.sleep(2)

    start_ffmpeg()

    if not wait_hls(60):

        raise RuntimeError(
            "HLS não foi criado."
        )

    # --------------------------------------------------------
    # SOMENTE DEPOIS DO HLS ESTAR PRONTO
    # --------------------------------------------------------

    url = start_cloudflare()

    if url:

        test_public_url()

    else:

        log(
            "[TUNEL] Não foi possível criar "
            "o endereço público."
        )

    # --------------------------------------------------------
    # TRANSMISSÃO
    # --------------------------------------------------------

    sep()
    log("TRANSMISSÃO ATIVA")
    sep()

    log(
        "HTTP LOCAL:"
    )

    log(
        f"http://127.0.0.1:{PORT}/"
    )

    log("")

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
            "HLS PÚBLICO:"
        )

        log(
            tunnel_url
            + "/live.m3u8"
        )

    sep()

    # --------------------------------------------------------
    # MONITORES
    # --------------------------------------------------------

    threading.Thread(
        target=monitor_cloudflare,
        daemon=True
    ).start()

    threading.Thread(
        target=monitor_ffmpeg,
        daemon=True
    ).start()

    threading.Thread(
        target=monitor_chromium,
        daemon=True
    ).start()

    threading.Thread(
        target=monitor_hls,
        daemon=True
    ).start()

    # --------------------------------------------------------
    # LOOP
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

    except Exception as e:

        sep()

        log(
            "[ERRO FATAL]"
        )

        log(
            str(e)
        )

        sep()

        sys.exit(1)

    finally:

        cleanup()
