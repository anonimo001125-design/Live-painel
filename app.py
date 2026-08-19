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
            log(f"[STOP] Encerrando {name}...")

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

    if http_server is not None:
        try:
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
# DEPENDÊNCIAS
# ============================================================

def check_dependencies():

    sep()
    log("VERIFICANDO DEPENDÊNCIAS")

    required = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
        "cloudflared",
    ]

    browser_found = False

    for browser in [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]:
        if shutil.which(browser):
            browser_found = True
            break

    missing = []

    for program in required:
        if shutil.which(program) is None:
            missing.append(program)

    if not browser_found:
        missing.append("chromium")

    if missing:
        raise RuntimeError(
            "Programas ausentes: "
            + ", ".join(missing)
        )

    log("Todas as dependências estão instaladas.")


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
# PULSE AUDIO
# ============================================================

def pulse_env():

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    runtime = Path(
        "/tmp"
    ) / f"pulse-webtv-{os.getuid()}"

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
        env=pulse_env()
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
        env=env
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
        env=env
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

    result = pactl(
        ["list", "short", "sinks"]
    )

    sink_exists = False

    for line in result.stdout.splitlines():

        parts = line.split()

        if len(parts) >= 2:

            if parts[1] == "webtv":
                sink_exists = True
                break

    if not sink_exists:

        log("[ÁUDIO] Criando sink webtv...")

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
                "Falha ao criar sink webtv: "
                + result.stderr.strip()
            )

    time.sleep(1)

    pactl(
        ["set-default-sink", "webtv"]
    )

    monitor_ok = False

    for _ in range(20):

        result = pactl(
            ["list", "short", "sources"]
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
            "webtv.monitor não foi criado."
        )

    log("Fontes de áudio:")

    result = pactl(
        ["list", "short", "sources"]
    )

    log(result.stdout.strip())

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

    def headers(self, content_type=None, length=None):

        if content_type:
            self.send_header(
                "Content-Type",
                content_type
            )

        if length is not None:
            self.send_header(
                "Content-Length",
                str(length)
            )

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
        content_type
    ):

        self.send_response(200)

        self.headers(
            content_type,
            len(data)
        )

        self.end_headers()

        try:
            self.wfile.write(data)
        except Exception:
            pass

    def do_GET(self):

        path = self.path.split("?", 1)[0]

        # ====================================================
        # PLAYER
        # ====================================================

        if path in ["/", "/index.html"]:

            html = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>WEBTV AO VIVO</title>

<style>

html,
body {
    width:100%;
    height:100%;
    margin:0;
    padding:0;
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
    background:rgba(0,0,0,.7);

    padding:8px 12px;

    border-radius:5px;

    font-family:Arial,sans-serif;
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
let reconnectTimer = null;


function setStatus(text) {
    status.textContent = text;
}


function reconnect() {

    if (reconnectTimer)
        return;

    reconnectTimer = setTimeout(
        function() {

            reconnectTimer = null;

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
        } catch(e) {}

    }

    hls = new Hls({

        enableWorker:true,

        lowLatencyMode:false,

        backBufferLength:20,

        maxBufferLength:30,

        maxMaxBufferLength:60,

        liveSyncDurationCount:3,

        liveMaxLatencyDurationCount:8,

        manifestLoadingMaxRetry:20,

        manifestLoadingRetryDelay:1000,

        levelLoadingMaxRetry:20,

        levelLoadingRetryDelay:1000,

        fragLoadingMaxRetry:20,

        fragLoadingRetryDelay:1000
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


            try {
                hls.destroy();
            } catch(e) {}

            hls = null;

            reconnect();
        }
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
            function(){}
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


    const script =
        document.createElement(
            "script"
        );

    script.src =
        "https://cdn.jsdelivr.net/npm/hls.js@latest";


    script.onload = function() {

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


    script.onerror = function() {

        setStatus(
            "Erro carregando HLS"
        );

        reconnect();

    };


    document.head.appendChild(
        script
    );
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

        # ====================================================
        # HEALTH
        # ====================================================

        if path == "/health":

            self.send_bytes(
                b"OK\n",
                "text/plain; charset=utf-8"
            )

            return

        # ====================================================
        # PLAYLIST
        # ====================================================

        if path == "/live.m3u8":

            file = STREAM_DIR / "live.m3u8"

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

            self.send_bytes(
                data,
                "application/vnd.apple.mpegurl"
            )

            return

        # ====================================================
        # SEGMENTOS
        # ====================================================

        if path.startswith("/segment_"):

            filename = os.path.basename(path)

            if not re.fullmatch(
                r"segment_\d+\.ts",
                filename
            ):

                self.send_response(400)
                self.headers()
                self.end_headers()

                return

            file = STREAM_DIR / filename

            if not file.exists():

                self.send_response(404)
                self.headers()
                self.end_headers()

                return

            try:

                size = file.stat().st_size

                self.send_response(200)

                self.headers(
                    "video/mp2t",
                    size
                )

                self.end_headers()

                with open(file, "rb") as f:

                    while True:

                        chunk = f.read(
                            1024 * 1024
                        )

                        if not chunk:
                            break

                        try:
                            self.wfile.write(chunk)
                        except Exception:
                            break

            except Exception:
                pass

            return

        # ====================================================
        # 404
        # ====================================================

        self.send_response(404)
        self.headers()
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

        "--disable-features=Translate,BackForwardCache",

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
    log("[6] INICIANDO FFMPEG")

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

        # ====================================================
        # ÁUDIO
        # ====================================================

        "-thread_queue_size",
        "4096",

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
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        "-b:v",
        "1400k",

        "-maxrate",
        "1600k",

        "-bufsize",
        "3200k",

        # ====================================================
        # ÁUDIO
        # ====================================================

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

        # ====================================================
        # HLS
        # ====================================================

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
            "segment_%06d.ts"
        ),

        str(playlist)
    ]

    env = pulse_env()

    ffmpeg = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )

    def reader():

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
        target=reader,
        daemon=True
    ).start()

    time.sleep(4)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou durante a inicialização."
        )

    log("FFmpeg funcionando.")


# ============================================================
# ESPERAR HLS
# ============================================================

def wait_hls():

    sep()
    log("[HLS] Aguardando playlist...")

    playlist = (
        STREAM_DIR / "live.m3u8"
    )

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
# CLOUDFLARE
# ============================================================

def extract_cloudflare_url(text):

    patterns = [

        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com",

        r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com",

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

    sep()
    log(
        "[CLOUDFLARE] Iniciando Quick Tunnel..."
    )

    # Se existir processo antigo, encerra.
    stop_process(
        cloudflared,
        "Cloudflare antigo"
    )

    cloudflared = None

    command = [

        "cloudflared",

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
            bufsize=1
        )

    except Exception as e:

        log(
            "[CLOUDFLARE] Erro iniciando:"
        )

        log(str(e))

        return None

    start = time.time()

    while time.time() - start < 45:

        if stop_event.is_set():
            return None

        if cloudflared.poll() is not None:

            log(
                "[CLOUDFLARE] Processo encerrou."
            )

            return None

        try:

            line = cloudflared.stdout.readline()

        except Exception:
            line = ""

        if line:

            line = line.strip()

            if line:
                log(
                    "[CLOUDFLARE] "
                    + line
                )

            found = extract_cloudflare_url(
                line
            )

            if found:

                with tunnel_lock:
                    tunnel_url = found

                sep()
                log(
                    "TRANSMISSÃO PÚBLICA"
                )
                sep()

                log(
                    "LINK PRINCIPAL:"
                )

                log(found)

                log("")

                log(
                    "LINK HLS:"
                )

                log(
                    found
                    + "/live.m3u8"
                )

                sep()

                return found

        time.sleep(0.2)

    log(
        "[CLOUDFLARE] URL não encontrada."
    )

    return None


# ============================================================
# MONITOR CLOUDFLARE
# ============================================================

def cloudflare_monitor():

    global cloudflared

    while not stop_event.is_set():

        time.sleep(10)

        if stop_event.is_set():
            return

        if (
            cloudflared is not None
            and cloudflared.poll() is None
        ):
            continue

        sep()

        log(
            "[CLOUDFLARE] Túnel caiu."
        )

        log(
            "[CLOUDFLARE] FFmpeg/HLS continuam."
        )

        log(
            "[CLOUDFLARE] Reconectando túnel..."
        )

        sep()

        for attempt in range(1, 6):

            if stop_event.is_set():
                return

            log(
                f"[CLOUDFLARE] Tentativa "
                f"{attempt}/5"
            )

            url = start_cloudflare()

            if url:

                log(
                    "[CLOUDFLARE] Túnel reconectado."
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
                "[ERRO] FFmpeg encerrou."
            )

            log(
                "[ERRO] Transmissão interrompida."
            )

            sep()

            stop_event.set()

            return


# ============================================================
# MONITOR HLS
# ============================================================

def hls_monitor():

    playlist = (
        STREAM_DIR / "live.m3u8"
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

        if current == previous:

            log(
                "[HLS] ALERTA: playlist "
                "não atualizou."
            )

        previous = current


# ============================================================
# MONITOR CHROMIUM
# ============================================================

def chromium_monitor():

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
                "[CHROMIUM] Falha:"
            )

            log(str(e))


# ============================================================
# MAIN
# ============================================================

def main():

    sep()
    log("WEBTV STREAM")
    sep()

    check_dependencies()

    clean_stream()

    start_xvfb()

    start_pulseaudio()

    start_http()

    start_chromium()

    time.sleep(5)

    fullscreen()

    time.sleep(2)

    start_ffmpeg()

    if not wait_hls():

        raise RuntimeError(
            "HLS não foi criado."
        )

    # ========================================================
    # CLOUDFLARE
    # ========================================================

    start_cloudflare()

    # ========================================================
    # ATIVO
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

    with tunnel_lock:

        current_url = tunnel_url

    if current_url:

        log("")

        log(
            "LINK PÚBLICO:"
        )

        log(current_url)

        log("")

        log(
            "HLS PÚBLICO:"
        )

        log(
            current_url
            + "/live.m3u8"
        )

    else:

        log(
            "[AVISO] Cloudflare ainda não "
            "forneceu o link."
        )

    sep()

    # ========================================================
    # MONITORES
    # ========================================================

    threading.Thread(
        target=cloudflare_monitor,
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
    # LOOP
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
