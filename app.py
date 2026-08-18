#!/usr/bin/env python3

import os
import re
import sys
import time
import shutil
import signal
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
FPS = 25

STREAM_DIR = Path("stream")
STREAM_DIR.mkdir(exist_ok=True)

PAGE_URL = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

xvfb = None
pulse = None
chromium = None
ffmpeg = None
tunnel = None

tunnel_url = None

http_server = None

stop_event = threading.Event()


# ============================================================
# LOG
# ============================================================

def log(msg=""):
    print(msg, flush=True)


def separator():
    log("=" * 70)


# ============================================================
# ENCERRAMENTO
# ============================================================

def terminate_process(process, name):

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

    except Exception as e:

        log(f"[STOP] {name}: {e}")


def cleanup():

    stop_event.set()

    separator()
    log("ENCERRANDO WEBTV")

    terminate_process(ffmpeg, "FFmpeg")
    terminate_process(chromium, "Chromium")
    terminate_process(tunnel, "Túnel")
    terminate_process(pulse, "PulseAudio")
    terminate_process(xvfb, "Xvfb")

    if http_server:

        try:
            http_server.shutdown()
        except Exception:
            pass

    log("WEBTV encerrada.")


def signal_handler(signum, frame):

    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============================================================
# LIMPAR STREAM
# ============================================================

def clean_stream():

    separator()
    log("[1] Limpando stream antigo...")

    STREAM_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    for file in STREAM_DIR.iterdir():

        try:

            if file.is_file():
                file.unlink()

            elif file.is_dir():
                shutil.rmtree(file)

        except Exception:
            pass


# ============================================================
# XVFB
# ============================================================

def start_xvfb():

    global xvfb

    separator()

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

    separator()

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

        result = subprocess.run(
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

        if result.returncode != 0:

            log(
                "[ERRO] Não foi possível criar "
                "o sink webtv:"
            )

            log(result.stderr)

    time.sleep(2)

    sources = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ],
        capture_output=True,
        text=True
    )

    log("Fontes de áudio:")

    if sources.stdout.strip():
        log(sources.stdout.strip())

    log("Áudio pronto.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def send_common_headers(self):

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, HEAD, OPTIONS"
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

    def do_OPTIONS(self):

        self.send_response(204)
        self.send_common_headers()
        self.end_headers()

    def do_HEAD(self):

        self.handle_request(
            send_body=False
        )

    def do_GET(self):

        self.handle_request(
            send_body=True
        )

    def handle_request(self, send_body=True):

        path = self.path.split("?")[0]

        # ----------------------------------------------------
        # Página principal
        # ----------------------------------------------------

        if path in ("", "/"):

            html = """
<!DOCTYPE html>

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

    z-index: 9999;

    padding: 8px 12px;

    background: rgba(0,0,0,.7);

    color: white;

    font-family: Arial;

    font-size: 14px;

    border-radius: 5px;
}

</style>

</head>

<body>

<div id="status">
    Conectando ao vivo...
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

function statusText(text) {
    status.textContent = text;
}

function startPlayer() {

    statusText(
        "Conectando ao vivo..."
    );

    // ------------------------------------------------------
    // Safari / players nativos
    // ------------------------------------------------------

    if (
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ) {

        video.src =
            "/live.m3u8";

        video.addEventListener(
            "loadedmetadata",
            function() {

                video.play()
                    .then(function() {

                        statusText(
                            "● AO VIVO"
                        );

                    })
                    .catch(function() {});

            }
        );

        return;
    }

    // ------------------------------------------------------
    // HLS.js
    // ------------------------------------------------------

    const script =
        document.createElement("script");

    script.src =
        "https://cdn.jsdelivr.net/npm/hls.js@latest";

    script.onload = function() {

        if (
            !window.Hls ||
            !Hls.isSupported()
        ) {

            statusText(
                "Seu navegador não suporta HLS."
            );

            return;
        }

        hls = new Hls({

            lowLatencyMode: false,

            enableWorker: true,

            startLevel: -1,

            liveSyncDurationCount: 4,

            liveMaxLatencyDurationCount: 8,

            maxBufferLength: 30,

            maxMaxBufferLength: 60,

            backBufferLength: 20,

            startFragPrefetch: true,

            capLevelToPlayerSize: true,

            manifestLoadingMaxRetry: 10,

            manifestLoadingRetryDelay: 1000,

            levelLoadingMaxRetry: 10,

            levelLoadingRetryDelay: 1000,

            fragLoadingMaxRetry: 10,

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
                    .catch(function() {});

            }
        );

        hls.on(
            Hls.Events.ERROR,
            function(event, data) {

                if (!data.fatal) {
                    return;
                }

                statusText(
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

                setTimeout(
                    startPlayer,
                    2000
                );
            }
        );
    };

    script.onerror = function() {

        statusText(
            "Falha no player. Tentando novamente..."
        );

        setTimeout(
            startPlayer,
            3000
        );

    };

    document.head.appendChild(
        script
    );
}

startPlayer();

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

            self.send_common_headers()

            self.end_headers()

            if send_body:

                try:
                    self.wfile.write(data)
                except BrokenPipeError:
                    pass

            return

        # ----------------------------------------------------
        # HLS
        # ----------------------------------------------------

        if path == "/live.m3u8":

            playlist = (
                STREAM_DIR /
                "live.m3u8"
            )

            if not playlist.exists():

                self.send_response(503)

                self.send_header(
                    "Content-Type",
                    "text/plain"
                )

                self.send_common_headers()

                self.end_headers()

                if send_body:

                    self.wfile.write(
                        b"Stream ainda iniciando"
                    )

                return

            try:

                data = playlist.read_bytes()

            except Exception:

                self.send_response(503)
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

            self.send_common_headers()

            self.end_headers()

            if send_body:

                try:
                    self.wfile.write(data)
                except BrokenPipeError:
                    pass

            return

        # ----------------------------------------------------
        # SEGMENTOS TS
        # ----------------------------------------------------

        if path.startswith("/segment_"):

            filename = os.path.basename(path)

            # Segurança
            if (
                "/" in filename
                or "\\" in filename
                or ".." in filename
            ):

                self.send_response(400)
                self.end_headers()

                return

            file_path = (
                STREAM_DIR /
                filename
            )

            if not file_path.exists():

                self.send_response(404)

                self.send_header(
                    "Content-Type",
                    "text/plain"
                )

                self.send_common_headers()

                self.end_headers()

                return

            try:

                size = file_path.stat().st_size

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "video/mp2t"
                )

                self.send_header(
                    "Content-Length",
                    str(size)
                )

                self.send_common_headers()

                self.end_headers()

                if send_body:

                    with open(
                        file_path,
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

        # ----------------------------------------------------
        # 404
        # ----------------------------------------------------

        self.send_response(404)

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.send_common_headers()

        self.end_headers()

        if send_body:

            try:
                self.wfile.write(
                    b"Not Found"
                )
            except BrokenPipeError:
                pass


def start_http():

    global http_server

    separator()

    log(
        "[4] Iniciando servidor HTTP..."
    )

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

    time.sleep(1)

    log(
        f"Servidor HTTP ativo na porta {PORT}"
    )


# ============================================================
# CHROMIUM
# ============================================================

def find_chromium():

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

    separator()

    log("[6] Iniciando Chromium...")

    browser = find_chromium()

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    profile = Path(
        "/tmp/webtv-chromium"
    )

    if profile.exists():

        try:
            shutil.rmtree(profile)
        except Exception:
            pass

    profile.mkdir(
        parents=True,
        exist_ok=True
    )

    chromium = subprocess.Popen(
        [
            browser,

            "--no-sandbox",
            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",

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
        ],

        stdout=subprocess.DEVNULL,

        stderr=subprocess.DEVNULL,

        env=env
    )

    time.sleep(7)

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
            text=True,
            timeout=10
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

    separator()

    log("INICIANDO FFMPEG")

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

    # --------------------------------------------------------
    # Remove arquivos antigos
    # --------------------------------------------------------

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

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

        # ====================================================
        # VÍDEO
        # ====================================================

        "-thread_queue_size",
        "16384",

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
        "16384",

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
        "1400k",

        "-maxrate",
        "1600k",

        "-bufsize",
        "5000k",

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

        # Corrige diferenças de relógio
        # entre PulseAudio e X11.

        "-af",
        (
            "aresample="
            "async=1000:"
            "min_hard_comp=0.100:"
            "first_pts=0"
        ),

        # ====================================================
        # HLS
        # ====================================================

        "-f",
        "hls",

        "-hls_time",
        "4",

        "-hls_list_size",
        "10",

        "-hls_flags",
        (
            "delete_segments+"
            "append_list+"
            "independent_segments"
        ),

        "-hls_delete_threshold",
        "4",

        "-hls_segment_filename",

        str(
            STREAM_DIR /
            "segment_%05d.ts"
        ),

        str(playlist)
    ]

    log(
        " ".join(command)
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

    def read_logs():

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
        target=read_logs,
        daemon=True
    ).start()

    time.sleep(3)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log(
        "FFmpeg funcionando."
    )


# ============================================================
# ESPERAR HLS
# ============================================================

def wait_hls():

    separator()

    log(
        "[HLS] Aguardando playlist..."
    )

    playlist = (
        STREAM_DIR /
        "live.m3u8"
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
# TESTAR SERVIDOR LOCAL
# ============================================================

def test_local_stream():

    separator()

    log(
        "[TESTE] Verificando HLS local..."
    )

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

    if not playlist.exists():

        log(
            "[TESTE] Playlist não existe."
        )

        return False

    try:

        import urllib.request

        response = urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/live.m3u8",
            timeout=10
        )

        data = response.read()

        if (
            response.status == 200
            and b"#EXTM3U" in data
        ):

            log(
                "[TESTE] HLS local OK."
            )

            return True

    except Exception as e:

        log(
            "[TESTE] Falha local: "
            + str(e)
        )

    return False


# ============================================================
# TÚNEL
# ============================================================

def extract_url(text):

    match = re.search(
        r"https://[A-Za-z0-9.-]+\.lhr\.life",
        text
    )

    if match:
        return match.group(0)

    return None


def start_tunnel():

    global tunnel
    global tunnel_url

    separator()

    log(
        "[5] Iniciando túnel localhost.run..."
    )

    command = [

        "ssh",

        "-o",
        "StrictHostKeyChecking=no",

        "-o",
        "ServerAliveInterval=15",

        "-o",
        "ServerAliveCountMax=10",

        "-o",
        "TCPKeepAlive=yes",

        "-o",
        "ConnectTimeout=20",

        "-o",
        "ConnectionAttempts=3",

        "-o",
        "ExitOnForwardFailure=yes",

        "-R",
        "80:127.0.0.1:8080",

        "nokey@localhost.run"
    ]

    tunnel = subprocess.Popen(

        command,

        stdin=subprocess.DEVNULL,

        stdout=subprocess.PIPE,

        stderr=subprocess.STDOUT,

        text=True,

        bufsize=1
    )

    start = time.time()

    while time.time() - start < 40:

        if tunnel.poll() is not None:

            log(
                "[TUNEL] Processo encerrou."
            )

            return None

        line_data = tunnel.stdout.readline()

        if not line_data:

            time.sleep(0.2)
            continue

        line_data = line_data.strip()

        if line_data:

            log(
                "[TUNEL] "
                + line_data
            )

        url = extract_url(
            line_data
        )

        if url:

            tunnel_url = url

            separator()

            log(
                "LINK DA TRANSMISSÃO"
            )

            separator()

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
                tunnel_url
                + "/live.m3u8"
            )

            separator()

            return tunnel_url

    return None


# ============================================================
# MONITORAR TÚNEL
# ============================================================

def tunnel_monitor():

    global tunnel
    global tunnel_url

    while not stop_event.is_set():

        time.sleep(5)

        if tunnel is None:
            continue

        if tunnel.poll() is None:
            continue

        log("")
        separator()

        log(
            "[TUNEL] Conexão perdida."
        )

        log(
            "[TUNEL] Criando novo túnel..."
        )

        separator()

        tunnel = None

        new_url = None

        for attempt in range(1, 6):

            if stop_event.is_set():
                return

            log(
                f"[TUNEL] Tentativa {attempt}/5"
            )

            try:

                new_url = start_tunnel()

            except Exception as e:

                log(
                    "[TUNEL] "
                    + str(e)
                )

                new_url = None

            if new_url:
                break

            time.sleep(
                min(
                    attempt * 3,
                    15
                )
            )

        if new_url:

            log(
                "[TUNEL] Novo link:"
            )

            log(
                new_url
            )

        else:

            log(
                "[TUNEL] Não foi possível reconectar."
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

            separator()

            log(
                "[ERRO] FFmpeg parou."
            )

            separator()

            stop_event.set()

            return


# ============================================================
# MAIN
# ============================================================

def main():

    separator()

    log(
        "WEBTV STREAM"
    )

    separator()

    try:

        # ----------------------------------------------------
        # 1
        # ----------------------------------------------------

        clean_stream()

        # ----------------------------------------------------
        # 2
        # ----------------------------------------------------

        start_xvfb()

        # ----------------------------------------------------
        # 3
        # ----------------------------------------------------

        start_pulseaudio()

        # ----------------------------------------------------
        # 4
        # ----------------------------------------------------

        start_http()

        # ----------------------------------------------------
        # 5
        # ----------------------------------------------------

        start_tunnel()

        # ----------------------------------------------------
        # 6
        # ----------------------------------------------------

        start_chromium()

        time.sleep(8)

        fullscreen()

        time.sleep(3)

        # ----------------------------------------------------
        # FFmpeg
        # ----------------------------------------------------

        start_ffmpeg()

        # ----------------------------------------------------
        # HLS
        # ----------------------------------------------------

        if not wait_hls():

            raise RuntimeError(
                "HLS não foi criado."
            )

        # ----------------------------------------------------
        # Teste LOCAL antes de anunciar
        # ----------------------------------------------------

        if not test_local_stream():

            raise RuntimeError(
                "Servidor HTTP não está "
                "servindo o HLS corretamente."
            )

        # ----------------------------------------------------
        # TRANSMISSÃO ATIVA
        # ----------------------------------------------------

        separator()

        log(
            "TRANSMISSÃO ATIVA"
        )

        separator()

        if tunnel_url:

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
                tunnel_url
                + "/live.m3u8"
            )

        log("")

        log(
            "IMPORTANTE:"
        )

        log(
            "O link principal abre o player."
        )

        log(
            "O link /live.m3u8 é o HLS direto."
        )

        separator()

        # ----------------------------------------------------
        # MONITORES
        # ----------------------------------------------------

        threading.Thread(
            target=tunnel_monitor,
            daemon=True
        ).start()

        threading.Thread(
            target=ffmpeg_monitor,
            daemon=True
        ).start()

        # ----------------------------------------------------
        # LOOP PRINCIPAL
        # ----------------------------------------------------

        while not stop_event.is_set():

            time.sleep(5)

    except KeyboardInterrupt:

        pass

    except Exception as e:

        separator()

        log(
            "[ERRO FATAL]"
        )

        log(
            str(e)
        )

        separator()

    finally:

        cleanup()


# ============================================================
# EXECUTAR
# ============================================================

if __name__ == "__main__":
    main()
