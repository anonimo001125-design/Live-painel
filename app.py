#!/usr/bin/env python3

import os
import re
import sys
import time
import signal
import shutil
import tarfile
import urllib.request
import subprocess
import threading
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
NGROK_BIN = Path.home() / ".local" / "bin" / "ngrok"

NGROK_AUTHTOKEN = os.environ.get(
    "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk",
    ""
).strip()

stop_event = threading.Event()

xvfb = None
pulse = None
chromium = None
ffmpeg = None
ngrok = None
http_server = None

tunnel_url = None

tunnel_lock = threading.Lock()


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
                    process.wait(timeout=2)
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

    if http_server is not None:

        try:
            http_server.shutdown()
        except Exception:
            pass

        try:
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


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============================================================
# COMANDOS
# ============================================================

def command_exists(name):

    return shutil.which(name) is not None


def run_quiet(command, env=None):

    try:

        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=30
        )

    except Exception:

        return None


# ============================================================
# NGROK
# ============================================================

def find_ngrok():

    candidates = []

    found = shutil.which("ngrok")

    if found:
        candidates.append(Path(found))

    candidates.append(NGROK_BIN)

    candidates.append(
        Path.cwd() / "ngrok"
    )

    for path in candidates:

        try:

            if path.exists() and os.access(path, os.X_OK):
                return str(path)

        except Exception:
            pass

    return None


def install_ngrok():

    sep()
    log("[NGROK] Executável não encontrado.")
    log("[NGROK] Instalando agente automaticamente...")

    if find_ngrok():
        return find_ngrok()

    if not command_exists("curl") and not command_exists("wget"):

        raise RuntimeError(
            "curl ou wget é necessário para instalar o ngrok."
        )

    architecture = os.uname().machine.lower()

    if architecture in ("x86_64", "amd64"):
        package = "ngrok-v3-stable-linux-amd64.tgz"

    elif architecture in ("aarch64", "arm64"):
        package = "ngrok-v3-stable-linux-arm64.tgz"

    elif architecture.startswith("arm"):
        package = "ngrok-v3-stable-linux-arm.tgz"

    else:

        raise RuntimeError(
            f"Arquitetura não suportada pelo instalador: {architecture}"
        )

    url = (
        "https://bin.equinox.io/c/bNyj1mQVY4c/"
        + package
    )

    temp_dir = Path("/tmp/ngrok-install")

    shutil.rmtree(
        temp_dir,
        ignore_errors=True
    )

    temp_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    archive = temp_dir / package

    log("[NGROK] Baixando agente...")

    try:

        urllib.request.urlretrieve(
            url,
            archive
        )

    except Exception as e:

        raise RuntimeError(
            f"Falha ao baixar ngrok: {e}"
        )

    log("[NGROK] Extraindo agente...")

    try:

        with tarfile.open(
            archive,
            "r:gz"
        ) as tar:

            tar.extractall(
                temp_dir
            )

    except Exception as e:

        raise RuntimeError(
            f"Falha ao extrair ngrok: {e}"
        )

    binary = temp_dir / "ngrok"

    if not binary.exists():

        raise RuntimeError(
            "O arquivo ngrok não foi encontrado após a extração."
        )

    NGROK_BIN.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    shutil.copy2(
        binary,
        NGROK_BIN
    )

    NGROK_BIN.chmod(
        0o755
    )

    shutil.rmtree(
        temp_dir,
        ignore_errors=True
    )

    result = run_quiet(
        [
            str(NGROK_BIN),
            "version"
        ]
    )

    if result is None or result.returncode != 0:

        raise RuntimeError(
            "O ngrok foi instalado, mas não conseguiu iniciar."
        )

    log(
        "[NGROK] "
        + result.stdout.strip()
    )

    return str(NGROK_BIN)


def prepare_ngrok():

    global NGROK_AUTHTOKEN

    binary = find_ngrok()

    if not binary:
        binary = install_ngrok()

    if not binary:

        raise RuntimeError(
            "Não foi possível instalar/encontrar o ngrok."
        )

    if not NGROK_AUTHTOKEN:

        raise RuntimeError(
            "NGROK_AUTHTOKEN não configurado. "
            "Adicione o token como secret/variável de ambiente."
        )

    log("[NGROK] Configurando autenticação...")

    env = os.environ.copy()
    env["NGROK_AUTHTOKEN"] = NGROK_AUTHTOKEN

    result = run_quiet(
        [
            binary,
            "config",
            "add-authtoken",
            NGROK_AUTHTOKEN
        ],
        env=env
    )

    if result is None or result.returncode != 0:

        error = ""

        if result:
            error = result.stderr.strip()

        raise RuntimeError(
            "Falha ao configurar o authtoken do ngrok. "
            + error
        )

    log("[NGROK] Autenticação configurada.")

    return binary


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

        if not command_exists(program):
            missing.append(program)

    if missing:

        raise RuntimeError(
            "Programas ausentes: "
            + ", ".join(missing)
        )

    get_chromium()


# ============================================================
# LIMPAR STREAM
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

    subprocess.run(
        ["pulseaudio", "--kill"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(1)

    pulse = subprocess.Popen(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env
    )

    time.sleep(2)

    result = run_quiet(
        [
            "pactl",
            "list",
            "short",
            "sinks"
        ]
    )

    if result is None:
        raise RuntimeError("PulseAudio não respondeu.")

    if "webtv" not in result.stdout:

        result = run_quiet(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV"
            ]
        )

        if result is None or result.returncode != 0:

            raise RuntimeError(
                "Não foi possível criar o sink webtv."
            )

    time.sleep(2)

    log("Fontes de áudio:")

    result = run_quiet(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ]
    )

    if result:
        log(result.stdout.strip())

    log("Áudio pronto.")


# ============================================================
# HTTP
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def add_common_headers(self):

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

        self.add_common_headers()

        self.end_headers()

        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):

        path = self.path.split("?")[0]

        # ----------------------------------------------------
        # PLAYER
        # ----------------------------------------------------

        if path == "/":

            html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WEBTV AO VIVO</title>

<style>
html,body {
    margin:0;
    padding:0;
    width:100%;
    height:100%;
    background:#000;
    overflow:hidden;
}

video {
    width:100%;
    height:100%;
    object-fit:contain;
    background:#000;
}

#status {
    position:fixed;
    top:12px;
    left:12px;
    z-index:10;
    color:#fff;
    background:rgba(0,0,0,.75);
    padding:8px 12px;
    border-radius:5px;
    font-family:Arial,sans-serif;
    font-size:14px;
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
    playsinline
    preload="auto">
</video>

<script>

const video = document.getElementById("video");
const status = document.getElementById("status");

let hls = null;
let retryTimer = null;
let starting = false;

function setStatus(text) {
    status.textContent = text;
}

function scheduleRetry() {

    if (retryTimer)
        return;

    retryTimer = setTimeout(() => {

        retryTimer = null;

        startPlayer();

    }, 1500);
}

function createHls() {

    if (hls) {

        try {
            hls.destroy();
        } catch(e) {}

        hls = null;
    }

    hls = new Hls({

        enableWorker: true,

        lowLatencyMode: false,

        backBufferLength: 15,

        maxBufferLength: 20,

        maxMaxBufferLength: 40,

        liveSyncDurationCount: 3,

        liveMaxLatencyDurationCount: 7,

        startFragPrefetch: true,

        manifestLoadingMaxRetry: 50,

        manifestLoadingRetryDelay: 1000,

        levelLoadingMaxRetry: 50,

        levelLoadingRetryDelay: 1000,

        fragLoadingMaxRetry: 50,

        fragLoadingRetryDelay: 1000,

        capLevelToPlayerSize: true
    });

    hls.loadSource("/live.m3u8");

    hls.attachMedia(video);

    hls.on(
        Hls.Events.MANIFEST_PARSED,
        function() {

            setStatus("● AO VIVO");

            video.play().catch(function(){});

        }
    );

    hls.on(
        Hls.Events.ERROR,
        function(event, data) {

            if (!data.fatal)
                return;

            setStatus("Reconectando...");

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

            try {
                hls.destroy();
            } catch(e) {}

            hls = null;

            scheduleRetry();
        }
    );
}

function startPlayer() {

    if (starting)
        return;

    starting = true;

    if (
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ) {

        video.src = "/live.m3u8";

        video.play()
            .then(function() {
                setStatus("● AO VIVO");
            })
            .catch(function() {
                setStatus("Clique para reproduzir");
            });

        starting = false;

        return;
    }

    if (
        window.Hls &&
        Hls.isSupported()
    ) {

        createHls();

        starting = false;

        return;
    }

    const script =
        document.createElement("script");

    script.src =
        "https://cdn.jsdelivr.net/npm/hls.js@latest";

    script.onload = function() {

        starting = false;

        if (
            window.Hls &&
            Hls.isSupported()
        ) {

            createHls();

        } else {

            setStatus("HLS não suportado");
        }
    };

    script.onerror = function() {

        starting = false;

        setStatus("Falha ao carregar HLS");

        scheduleRetry();
    };

    document.head.appendChild(script);
}

video.addEventListener(
    "playing",
    function() {
        setStatus("● AO VIVO");
    }
);

video.addEventListener(
    "waiting",
    function() {
        setStatus("Buffering...");
    }
);

video.addEventListener(
    "stalled",
    function() {
        setStatus("Reconectando...");
        scheduleRetry();
    }
);

startPlayer();

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
                self.add_common_headers()
                self.end_headers()

                return

            try:

                data = file.read_bytes()

                self.send_bytes(
                    data,
                    "application/vnd.apple.mpegurl"
                )

            except Exception:

                self.send_response(503)
                self.add_common_headers()
                self.end_headers()

            return

        # ----------------------------------------------------
        # SEGMENTOS
        # ----------------------------------------------------

        if path.startswith("/segment_"):

            filename = os.path.basename(path)

            if (
                ".." in filename
                or "/" in filename
                or "\\" in filename
            ):

                self.send_response(400)
                self.add_common_headers()
                self.end_headers()

                return

            file = STREAM_DIR / filename

            if not file.exists():

                self.send_response(404)
                self.add_common_headers()
                self.end_headers()

                return

            try:

                data = file.read_bytes()

                self.send_bytes(
                    data,
                    "video/mp2t"
                )

            except (
                BrokenPipeError,
                ConnectionResetError
            ):
                pass

            except Exception:

                try:
                    self.send_response(500)
                    self.add_common_headers()
                    self.end_headers()
                except Exception:
                    pass

            return

        self.send_response(404)
        self.add_common_headers()
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

        "--window-size=1280,720",

        "--disable-features=CalculateNativeWinOcclusion",

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

    if not command_exists("xdotool"):
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

    playlist = STREAM_DIR / "live.m3u8"

    command = [

        "ffmpeg",

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

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

        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        "-map",
        "0:v:0",

        "-map",
        "1:a:0",

        # VIDEO
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
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        "-b:v",
        "1800k",

        "-maxrate",
        "2000k",

        "-bufsize",
        "4000k",

        # AUDIO
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

        # HLS
        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_delete_threshold",
        "3",

        "-hls_segment_filename",
        str(
            STREAM_DIR /
            "segment_%05d.ts"
        ),

        str(playlist)
    ]

    log(
        "FFmpeg iniciado."
    )

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

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

    time.sleep(4)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log("FFmpeg funcionando.")


# ============================================================
# HLS
# ============================================================

def wait_hls():

    sep()

    log("[HLS] Aguardando playlist...")

    playlist = STREAM_DIR / "live.m3u8"

    start = time.time()

    while time.time() - start < 60:

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
# NGROK TUNNEL
# ============================================================

def extract_ngrok_url(text):

    patterns = [

        r"https://[A-Za-z0-9.-]+\.ngrok-free\.app",

        r"https://[A-Za-z0-9.-]+\.ngrok\.app",

        r"https://[A-Za-z0-9.-]+\.ngrok\.dev",

        r"https://[A-Za-z0-9.-]+\.ngrok\.io"

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:
            return match.group(0)

    return None


def ngrok_alive():

    return (
        ngrok is not None
        and ngrok.poll() is None
    )


def start_ngrok():

    global ngrok
    global tunnel_url

    with tunnel_lock:

        if ngrok_alive():
            return tunnel_url

        binary = find_ngrok()

        if not binary:
            binary = prepare_ngrok()

        if not binary:
            return None

        sep()

        log(
            "[NGROK] Iniciando túnel..."
        )

        env = os.environ.copy()

        env["NGROK_AUTHTOKEN"] = (
            NGROK_AUTHTOKEN
        )

        command = [

            binary,

            "http",

            str(PORT),

            "--log=stdout",

            "--log-format=logfmt"
        ]

        try:

            ngrok = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )

        except Exception as e:

            log(
                "[NGROK] Falha ao iniciar:"
            )

            log(str(e))

            ngrok = None

            return None

        start = time.time()

        while time.time() - start < 30:

            if ngrok.poll() is not None:

                log(
                    "[NGROK] Processo encerrou."
                )

                ngrok = None

                return None

            line = ngrok.stdout.readline()

            if not line:

                time.sleep(.2)
                continue

            line = line.strip()

            if line:
                log(
                    "[NGROK] " + line
                )

            url = extract_ngrok_url(line)

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

                log(tunnel_url)

                log(
                    "LINK HLS:"
                )

                log(
                    tunnel_url +
                    "/live.m3u8"
                )

                sep()

                return tunnel_url

        try:
            ngrok.terminate()
        except Exception:
            pass

        ngrok = None

        return None


# ============================================================
# MONITOR NGROK
# ============================================================

def ngrok_monitor():

    global ngrok
    global tunnel_url

    while not stop_event.is_set():

        time.sleep(5)

        if ngrok_alive():
            continue

        if stop_event.is_set():
            return

        sep()

        log(
            "[NGROK] Túnel caiu."
        )

        log(
            "[NGROK] FFmpeg continuará rodando."
        )

        log(
            "[NGROK] Tentando reconectar..."
        )

        tunnel_url = None

        for attempt in range(1, 21):

            if stop_event.is_set():
                return

            log(
                f"[NGROK] Reconexão "
                f"{attempt}/20"
            )

            url = start_ngrok()

            if url:

                log(
                    "[NGROK] Túnel reconectado."
                )

                break

            time.sleep(
                min(
                    attempt * 2,
                    20
                )
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

    playlist = STREAM_DIR / "live.m3u8"

    previous = 0
    unchanged_count = 0

    while not stop_event.is_set():

        time.sleep(10)

        if not playlist.exists():

            log(
                "[HLS] Playlist ausente."
            )

            continue

        try:

            current = playlist.stat().st_mtime

        except Exception:
            continue

        if current == previous:

            unchanged_count += 1

        else:

            unchanged_count = 0

        previous = current

        if unchanged_count >= 3:

            log(
                "[HLS] ALERTA: playlist "
                "não está atualizando."
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

    check_programs()

    # --------------------------------------------------------
    # 1
    # --------------------------------------------------------

    clean_stream()

    # --------------------------------------------------------
    # 2
    # --------------------------------------------------------

    start_xvfb()

    # --------------------------------------------------------
    # 3
    # --------------------------------------------------------

    start_pulseaudio()

    # --------------------------------------------------------
    # 4
    # --------------------------------------------------------

    start_http()

    # --------------------------------------------------------
    # 5
    # --------------------------------------------------------

    start_chromium()

    time.sleep(8)

    fullscreen()

    time.sleep(3)

    # --------------------------------------------------------
    # 6
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
    # NGROK
    # --------------------------------------------------------

    prepare_ngrok()

    start_ngrok()

    # --------------------------------------------------------
    # ATIVO
    # --------------------------------------------------------

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

        log(tunnel_url)

        log(
            "LINK HLS:"
        )

        log(
            tunnel_url +
            "/live.m3u8"
        )

    else:

        log(
            "AVISO: túnel ainda não disponível."
        )

    sep()

    # --------------------------------------------------------
    # MONITORES
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 24 HORAS
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

    finally:

        cleanup()
