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
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

STREAM_DIR = Path("stream")

# O token NÃO fica gravado no código.
NGROK_AUTHTOKEN = os.environ.get(
    "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk",
    ""
).strip()

NGROK_BIN = shutil.which("ngrok")

stop_event = threading.Event()

xvfb = None
pulse = None
chromium = None
ffmpeg = None
ngrok_process = None
http_server = None

tunnel_url = None


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

    if stop_event.is_set():
        return

    stop_event.set()

    sep()
    log("ENCERRANDO WEBTV")
    sep()

    global http_server

    try:

        if http_server is not None:

            http_server.shutdown()
            http_server.server_close()

    except Exception:
        pass

    stop_process(
        ngrok_process,
        "ngrok"
    )

    stop_process(
        ffmpeg,
        "FFmpeg"
    )

    stop_process(
        chromium,
        "Chromium"
    )

    stop_process(
        pulse,
        "PulseAudio"
    )

    stop_process(
        xvfb,
        "Xvfb"
    )


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
# VERIFICAÇÃO
# ============================================================

def check_programs():

    programs = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg"
    ]

    missing = []

    for program in programs:

        if shutil.which(program) is None:
            missing.append(program)

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

            if item.is_file():
                item.unlink()

            elif item.is_dir():
                shutil.rmtree(item)

        except Exception:
            pass


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
            "-noreset"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env
    )

    time.sleep(2)

    if xvfb.poll() is not None:

        raise RuntimeError(
            "Xvfb não iniciou."
        )

    log("Xvfb pronto.")


# ============================================================
# PULSEAUDIO
# ============================================================

def start_pulseaudio():

    global pulse

    sep()

    log("[3] Iniciando PulseAudio...")

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    env["PULSE_RUNTIME_PATH"] = (
        f"/tmp/pulse-{os.getuid()}"
    )

    os.makedirs(
        env["PULSE_RUNTIME_PATH"],
        exist_ok=True
    )

    subprocess.run(
        [
            "pulseaudio",
            "--kill"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(1)

    pulse = subprocess.Popen(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1",
            "--daemonize=no"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env
    )

    time.sleep(2)

    subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            "sink_name=webtv",
            "sink_properties=device.description=WebTV"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(2)

    result = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sinks"
        ],
        capture_output=True,
        text=True
    )

    if "webtv" not in result.stdout:

        raise RuntimeError(
            "Não foi possível criar o dispositivo de áudio webtv."
        )

    log("Fontes de áudio:")

    result = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ],
        capture_output=True,
        text=True
    )

    log(result.stdout.strip())

    log("Áudio pronto.")


# ============================================================
# HTTP
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def add_headers(self):

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

    def do_GET(self):

        path = self.path.split("?")[0]

        # ====================================================
        # PLAYER
        # ====================================================

        if path == "/":

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
    z-index: 10;
    color: white;
    background: rgba(0,0,0,.75);
    padding: 8px 12px;
    border-radius: 5px;
    font-family: Arial,sans-serif;
}

</style>
</head>

<body>

<div id="status">Conectando...</div>

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


function setStatus(text) {
    status.textContent = text;
}


function retry() {

    if (retryTimer)
        return;

    retryTimer = setTimeout(() => {

        retryTimer = null;

        start();

    }, 3000);
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
            .then(() => {
                setStatus("● AO VIVO");
            })
            .catch(() => {});

        return;
    }


    if (
        window.Hls &&
        Hls.isSupported()
    ) {

        createHls();

        return;
    }


    const script =
        document.createElement("script");

    script.src =
        "https://cdn.jsdelivr.net/npm/hls.js@latest";

    script.onload = () => {

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

    script.onerror = retry;

    document.head.appendChild(script);
}


function createHls() {

    if (hls) {

        try {
            hls.destroy();
        } catch (e) {}

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
        () => {

            setStatus("● AO VIVO");

            video.play()
                .catch(() => {});
        }
    );


    hls.on(
        Hls.Events.ERROR,
        (event, data) => {

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


            try {
                hls.destroy();
            } catch (e) {}

            hls = null;

            retry();
        }
    );
}


video.addEventListener(
    "playing",
    () => setStatus("● AO VIVO")
);


video.addEventListener(
    "waiting",
    () => setStatus("Buffering...")
);


video.addEventListener(
    "stalled",
    () => setStatus("Buffering...")
);


start();

</script>

</body>
</html>
"""

            data = html.encode("utf-8")

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(data))
            )

            self.add_headers()

            self.end_headers()

            try:
                self.wfile.write(data)
            except BrokenPipeError:
                pass

            return


        # ====================================================
        # PLAYLIST
        # ====================================================

        if path == "/live.m3u8":

            file = STREAM_DIR / "live.m3u8"

            if not file.exists():

                self.send_response(503)

                self.add_headers()

                self.end_headers()

                return

            try:

                data = file.read_bytes()

            except Exception:

                self.send_response(503)

                self.add_headers()

                self.end_headers()

                return

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "application/vnd.apple.mpegurl"
            )

            self.send_header(
                "Content-Length",
                str(len(data))
            )

            self.add_headers()

            self.end_headers()

            try:
                self.wfile.write(data)
            except BrokenPipeError:
                pass

            return


        # ====================================================
        # SEGMENTOS
        # ====================================================

        if path.startswith("/segment_"):

            filename = os.path.basename(path)

            if (
                ".." in filename
                or "/" in filename
                or "\\" in filename
            ):

                self.send_response(400)

                self.end_headers()

                return

            file = STREAM_DIR / filename

            if not file.exists():

                self.send_response(404)

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

                self.add_headers()

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
                            self.wfile.write(chunk)
                        except BrokenPipeError:
                            break

            except Exception:
                pass

            return


        self.send_response(404)

        self.add_headers()

        self.end_headers()


def start_http():

    global http_server

    sep()

    log("[4] Iniciando servidor HTTP...")

    http_server = ThreadingHTTPServer(
        (HOST, PORT),
        StreamHandler
    )

    http_server.daemon_threads = True

    thread = threading.Thread(
        target=http_server.serve_forever,
        daemon=True
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
        "google-chrome-stable"
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

    profile = "/tmp/webtv-chromium"

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

    time.sleep(8)

    if chromium.poll() is not None:

        raise RuntimeError(
            "Chromium encerrou."
        )

    log("Chromium iniciado.")

    log("Abrindo página:")
    log(PAGE_URL)


# ============================================================
# FULLSCREEN
# ============================================================

def fullscreen():

    if not shutil.which("xdotool"):
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
            text=True
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

    segment_pattern = (
        STREAM_DIR /
        "segment_%06d.ts"
    )

    command = [

        "ffmpeg",

        "-hide_banner",

        "-loglevel",
        "warning",

        "-nostdin",

        # ====================================================
        # VÍDEO
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
        # ÁUDIO
        # ====================================================

        "-thread_queue_size",
        "1024",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ====================================================
        # MAP
        # ====================================================

        "-map",
        "0:v:0",

        "-map",
        "1:a:0",

        # ====================================================
        # VÍDEO
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

        "-fps_mode",
        "cfr",

        "-g",
        str(FPS * 2),

        "-keyint_min",
        str(FPS * 2),

        "-sc_threshold",
        "0",

        "-b:v",
        "1800k",

        "-maxrate",
        "2000k",

        "-bufsize",
        "3600k",

        # ====================================================
        # ÁUDIO
        # ====================================================

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "48000",

        "-ac",
        "2",

        "-af",
        "aresample=async=1:min_hard_comp=0.100:first_pts=0",

        # ====================================================
        # HLS
        # ====================================================

        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "10",

        "-hls_flags",
        "delete_segments+append_list+independent_segments+program_date_time",

        "-hls_delete_threshold",
        "5",

        "-start_number",
        "0",

        "-hls_segment_filename",
        str(segment_pattern),

        str(playlist)
    ]

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    log("FFmpeg iniciado.")

    ffmpeg = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )

    def read_output():

        try:

            for line in ffmpeg.stdout:

                line = line.strip()

                if line:
                    log(
                        "[FFMPEG] " + line
                    )

        except Exception:
            pass

    threading.Thread(
        target=read_output,
        daemon=True
    ).start()

    time.sleep(3)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log("FFmpeg funcionando.")


# ============================================================
# AGUARDAR HLS
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

    start = time.time()

    while (
        time.time() - start < 60
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
# NGROK
# ============================================================

def find_ngrok():

    global NGROK_BIN

    if NGROK_BIN:
        return NGROK_BIN

    possible = [

        shutil.which("ngrok"),

        "/usr/local/bin/ngrok",

        "/usr/bin/ngrok",

        str(
            Path.home() /
            ".local/bin/ngrok"
        ),

        str(
            Path.home() /
            "ngrok"
        )
    ]

    for path in possible:

        if path and os.path.isfile(path):

            if os.access(
                path,
                os.X_OK
            ):

                NGROK_BIN = path

                return path

    return None


def configure_ngrok():

    binary = find_ngrok()

    if not binary:

        log(
            "[NGROK] Executável não encontrado."
        )

        log(
            "[NGROK] Instale o ngrok antes de executar o app."
        )

        return False

    if not NGROK_AUTHTOKEN:

        log(
            "[NGROK] NGROK_AUTHTOKEN não configurado."
        )

        log(
            "[NGROK] Configure o secret NGROK_AUTHTOKEN no GitHub."
        )

        return False

    try:

        result = subprocess.run(
            [
                binary,
                "config",
                "add-authtoken",
                NGROK_AUTHTOKEN
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20
        )

        if result.returncode != 0:

            log(
                "[NGROK] Falha ao configurar autenticação."
            )

            if result.stderr:
                log(
                    result.stderr.strip()
                )

            return False

        log(
            "[NGROK] Autenticação configurada."
        )

        return True

    except Exception as e:

        log(
            "[NGROK] Erro ao configurar:"
        )

        log(str(e))

        return False


def extract_ngrok_url(text):

    patterns = [

        r"https://[a-zA-Z0-9-]+\.ngrok-free\.app",

        r"https://[a-zA-Z0-9-]+\.ngrok\.app",

        r"https://[a-zA-Z0-9-]+\.ngrok-free\.dev",

        r"https://[a-zA-Z0-9-]+\.ngrok\.io"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:
            return match.group(0)

    return None


def start_ngrok():

    global ngrok_process
    global tunnel_url

    binary = find_ngrok()

    if not binary:

        log(
            "[NGROK] Executável não encontrado."
        )

        return None

    if not NGROK_AUTHTOKEN:

        log(
            "[NGROK] NGROK_AUTHTOKEN não configurado."
        )

        log(
            "[NGROK] Configure o secret NGROK_AUTHTOKEN no GitHub."
        )

        return None

    if ngrok_process is not None:

        if ngrok_process.poll() is None:
            return tunnel_url

    if not configure_ngrok():
        return None

    sep()

    log(
        "[NGROK] Iniciando túnel público..."
    )

    command = [

        binary,

        "http",

        str(PORT),

        "--log=stdout",

        "--log-format=logfmt"
    ]

    try:

        ngrok_process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )

    except Exception as e:

        log(
            "[NGROK] Erro ao iniciar:"
        )

        log(str(e))

        ngrok_process = None

        return None

    start = time.time()

    while (
        time.time() - start < 30
    ):

        if stop_event.is_set():
            return None

        if ngrok_process.poll() is not None:

            log(
                "[NGROK] Processo encerrou."
            )

            ngrok_process = None

            return None

        try:

            line = ngrok_process.stdout.readline()

        except Exception:
            line = ""

        if line:

            line = line.strip()

            if line:
                log(
                    "[NGROK] " + line
                )

            url = extract_ngrok_url(
                line
            )

            if url:

                tunnel_url = url

                sep()

                log(
                    "LINK DA TRANSMISSÃO"
                )

                sep()

                log(
                    "LINK PRINCIPAL:"
                )

                log(
                    tunnel_url
                )

                log(
                    "LINK HLS:"
                )

                log(
                    tunnel_url +
                    "/live.m3u8"
                )

                sep()

                return tunnel_url

        time.sleep(.2)

    # ========================================================
    # FALLBACK: API LOCAL DO NGROK
    # ========================================================

    try:

        import urllib.request
        import json

        response = urllib.request.urlopen(
            "http://127.0.0.1:4040/api/tunnels",
            timeout=5
        )

        data = json.loads(
            response.read().decode()
        )

        for tunnel in data.get(
            "tunnels",
            []
        ):

            public_url = tunnel.get(
                "public_url",
                ""
            )

            if public_url.startswith(
                "https://"
            ):

                tunnel_url = public_url

                sep()

                log(
                    "LINK DA TRANSMISSÃO"
                )

                sep()

                log(
                    "LINK PRINCIPAL:"
                )

                log(
                    tunnel_url
                )

                log(
                    "LINK HLS:"
                )

                log(
                    tunnel_url +
                    "/live.m3u8"
                )

                sep()

                return tunnel_url

    except Exception:
        pass

    log(
        "[NGROK] Não foi possível obter o endereço público."
    )

    return None


# ============================================================
# MONITOR NGROK
# ============================================================

def ngrok_monitor():

    global tunnel_url
    global ngrok_process

    while not stop_event.is_set():

        time.sleep(10)

        if stop_event.is_set():
            return

        if not NGROK_AUTHTOKEN:

            # Não fica criando um loop infinito
            # se o secret não foi configurado.
            continue

        if ngrok_process is not None:

            if ngrok_process.poll() is None:
                continue

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

        ngrok_process = None
        tunnel_url = None

        delay = 2

        for attempt in range(1, 6):

            if stop_event.is_set():
                return

            log(
                f"[NGROK] Tentativa {attempt}/5"
            )

            url = start_ngrok()

            if url:

                log(
                    "[NGROK] Túnel reconectado."
                )

                break

            time.sleep(delay)

            delay = min(
                delay * 2,
                20
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
                "[ERRO] FFmpeg parou."
            )

            log(
                "[ERRO] Transmissão encerrada."
            )

            sep()

            stop_event.set()

            return


# ============================================================
# MONITOR HLS
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
                playlist.stat().st_mtime_ns
            )

        except Exception:
            continue

        if (
            previous != 0
            and current == previous
        ):

            log(
                "[HLS] ALERTA: playlist não atualizou."
            )

        previous = current


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
    # NÃO INSTALA PACOTES AQUI
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

    time.sleep(8)

    fullscreen()

    time.sleep(3)

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
    # 8
    # NGROK
    # ========================================================

    start_ngrok()

    # ========================================================
    # TRANSMISSÃO
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
            "LINK PRINCIPAL:"
        )

        log(
            tunnel_url
        )

        log(
            "LINK HLS:"
        )

        log(
            tunnel_url +
            "/live.m3u8"
        )

    else:

        log(
            "[AVISO] Túnel público não está ativo."
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

    # ========================================================
    # MANTER 24H
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
