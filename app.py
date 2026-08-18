#!/usr/bin/env python3

import os
import re
import sys
import time
import shutil
import signal
import socket
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

PAGE_URL = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n3"
    "-102718744012.us-east5.run.app/watch"
)

STREAM_DIR = Path("stream")
STREAM_DIR.mkdir(parents=True, exist_ok=True)

xvfb = None
pulse = None
chromium = None
ffmpeg = None
tunnel = None
http_server = None

tunnel_url = None

stop_event = threading.Event()

tunnel_lock = threading.Lock()


# ============================================================
# LOG
# ============================================================

def log(text=""):
    print(text, flush=True)


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

                log(f"[STOP] Forçando encerramento de {name}...")

                process.kill()

    except Exception as e:

        log(f"[STOP] Erro em {name}: {e}")


def cleanup():

    stop_event.set()

    separator()
    log("ENCERRANDO WEBTV")
    separator()

    terminate_process(tunnel, "túnel")
    terminate_process(ffmpeg, "FFmpeg")
    terminate_process(chromium, "Chromium")
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
# DEPENDÊNCIAS
# ============================================================

def check_dependencies():

    required = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
        "ssh"
    ]

    missing = []

    for program in required:

        if shutil.which(program) is None:
            missing.append(program)

    if missing:

        raise RuntimeError(
            "Programas ausentes: "
            + ", ".join(missing)
        )


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
# SERVIDOR HTTP / HLS
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def common_headers(self):

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

        self.send_header(
            "Connection",
            "keep-alive"
        )

    def do_OPTIONS(self):

        self.send_response(204)

        self.common_headers()

        self.end_headers()

    def do_HEAD(self):

        self.handle_request(False)

    def do_GET(self):

        self.handle_request(True)

    def handle_request(self, body=True):

        path = self.path.split("?")[0]

        # ====================================================
        # PLAYER
        # ====================================================

        if path == "/":

            html = """
<!DOCTYPE html>

<html lang="pt-BR">

<head>

<meta charset="UTF-8">

<meta
name="viewport"
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

    left: 12px;
    top: 12px;

    z-index: 9999;

    padding: 8px 12px;

    color: white;

    background: rgba(0,0,0,.7);

    border-radius: 6px;

    font-family: Arial,sans-serif;

    font-size: 14px;
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

let retryTimer = null;


function setStatus(text) {

    status.textContent = text;
}


function reconnect() {

    if (retryTimer)
        return;

    setStatus(
        "Reconectando ao vivo..."
    );

    retryTimer = setTimeout(
        function() {

            retryTimer = null;

            startPlayer();

        },
        2000
    );
}


function startPlayer() {

    // ------------------------------------------------------
    // HLS nativo
    // ------------------------------------------------------

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
            .catch(function() {});

        return;
    }


    // ------------------------------------------------------
    // HLS.JS
    // ------------------------------------------------------

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

    script.onload = function() {

        if (
            window.Hls &&
            Hls.isSupported()
        ) {

            createHls();

        } else {

            setStatus(
                "HLS não suportado."
            );
        }
    };

    script.onerror = function() {

        reconnect();

    };

    document.head.appendChild(
        script
    );
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

        backBufferLength: 20,

        maxBufferLength: 40,

        maxMaxBufferLength: 80,

        liveSyncDurationCount: 4,

        liveMaxLatencyDurationCount: 10,

        startFragPrefetch: true,

        capLevelToPlayerSize: true,

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

            setStatus("● AO VIVO");

            video.play()
                .catch(function() {});

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


video.addEventListener(
    "stalled",
    function() {

        setStatus(
            "Buffering..."
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
    "playing",
    function() {

        setStatus(
            "● AO VIVO"
        );
    }
);


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

            self.common_headers()

            self.end_headers()

            if body:

                try:
                    self.wfile.write(data)
                except BrokenPipeError:
                    pass

            return


        # ====================================================
        # PLAYLIST
        # ====================================================

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

                self.common_headers()

                self.end_headers()

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

            self.common_headers()

            self.end_headers()

            if body:

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

                self.common_headers()

                self.end_headers()


                if body:

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

                                self.wfile.write(
                                    chunk
                                )

                            except BrokenPipeError:
                                break

            except Exception:
                pass

            return


        # ====================================================
        # 404
        # ====================================================

        self.send_response(404)

        self.common_headers()

        self.end_headers()


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

    log(
        "Abrindo página:"
    )

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


    command = [

        "ffmpeg",

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

        # ====================================================
        # VIDEO
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
        # AUDIO
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
        # VIDEO
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
        # AUDIO
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
        "5",

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


    def ffmpeg_logs():

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
        target=ffmpeg_logs,
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
# HLS
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
# TESTE HTTP
# ============================================================

def test_local_http():

    separator()

    log(
        "[TESTE] Testando HLS local..."
    )

    try:

        import urllib.request

        url = (
            f"http://127.0.0.1:"
            f"{PORT}/live.m3u8"
        )

        response = urllib.request.urlopen(
            url,
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
            "[TESTE] Erro:"
        )

        log(str(e))


    return False


# ============================================================
# TÚNEL
# ============================================================

def extract_url(text):

    patterns = [

        r"https://[A-Za-z0-9.-]+\.lhr\.life",

        r"https://[A-Za-z0-9.-]+\.localhost\.run"
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:
            return match.group(0)


    return None


def tunnel_is_alive():

    global tunnel

    if tunnel is None:
        return False

    return tunnel.poll() is None


def start_tunnel():

    global tunnel
    global tunnel_url

    with tunnel_lock:

        # -----------------------------------------------
        # Não criar segundo túnel
        # -----------------------------------------------

        if tunnel_is_alive():

            return tunnel_url


        separator()

        log(
            "[TUNEL] Iniciando localhost.run..."
        )


        command = [

            "ssh",

            "-T",

            "-o",
            "StrictHostKeyChecking=no",

            "-o",
            "UserKnownHostsFile=/dev/null",

            "-o",
            "ServerAliveInterval=10",

            "-o",
            "ServerAliveCountMax=6",

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


        try:

            tunnel = subprocess.Popen(

                command,

                stdin=subprocess.DEVNULL,

                stdout=subprocess.PIPE,

                stderr=subprocess.STDOUT,

                text=True,

                bufsize=1
            )

        except Exception as e:

            log(
                "[TUNEL] Erro ao iniciar:"
            )

            log(str(e))

            tunnel = None

            return None


        start = time.time()


        while (
            time.time() - start < 45
            and not stop_event.is_set()
        ):

            if tunnel.poll() is not None:

                log(
                    "[TUNEL] Processo encerrou."
                )

                tunnel = None

                return None


            try:

                line = tunnel.stdout.readline()

            except Exception:

                line = ""


            if not line:

                time.sleep(0.2)

                continue


            line = line.strip()


            if line:

                log(
                    "[TUNEL] "
                    + line
                )


            url = extract_url(line)


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


        log(
            "[TUNEL] Timeout ao obter endereço."
        )


        try:

            tunnel.terminate()

        except Exception:
            pass


        tunnel = None

        return None


# ============================================================
# MONITOR DO TÚNEL
# ============================================================

def tunnel_monitor():

    global tunnel
    global tunnel_url

    while not stop_event.is_set():

        time.sleep(3)


        if tunnel_is_alive():
            continue


        separator()

        log(
            "[TUNEL] CONEXÃO PERDIDA."
        )

        log(
            "[TUNEL] A transmissão local "
            "CONTINUA funcionando."
        )

        log(
            "[TUNEL] Tentando reconectar..."
        )

        separator()


        tunnel = None


        for attempt in range(1, 11):

            if stop_event.is_set():
                return


            log(
                f"[TUNEL] Tentativa "
                f"{attempt}/10"
            )


            try:

                url = start_tunnel()

            except Exception as e:

                log(
                    "[TUNEL] "
                    + str(e)
                )

                url = None


            if url:

                log(
                    "[TUNEL] Reconectado."
                )

                log(
                    "[TUNEL] Novo endereço:"
                )

                log(url)

                break


            time.sleep(
                min(
                    attempt * 2,
                    15
                )
            )


        if not tunnel_is_alive():

            log(
                "[TUNEL] Ainda offline."
            )

            log(
                "[TUNEL] FFmpeg/HLS continuam "
                "rodando normalmente."
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
                "[ERRO] FFmpeg parou!"
            )

            log(
                "[ERRO] A transmissão local "
                "foi interrompida."
            )

            separator()

            stop_event.set()

            return


# ============================================================
# MONITOR DOS ARQUIVOS HLS
# ============================================================

def hls_monitor():

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

    last_mtime = 0

    while not stop_event.is_set():

        time.sleep(10)


        if not playlist.exists():

            log(
                "[HLS] ALERTA: playlist desapareceu."
            )

            continue


        try:

            mtime = (
                playlist.stat().st_mtime
            )

        except Exception:

            continue


        if mtime == last_mtime:

            log(
                "[HLS] ALERTA: playlist "
                "não está sendo atualizada."
            )

        else:

            last_mtime = mtime


# ============================================================
# MAIN
# ============================================================

def main():

    separator()

    log(
        "WEBTV STREAM 24H"
    )

    separator()


    try:

        # ----------------------------------------------------
        # DEPENDÊNCIAS
        # ----------------------------------------------------

        check_dependencies()


        # ----------------------------------------------------
        # STREAM
        # ----------------------------------------------------

        clean_stream()


        # ----------------------------------------------------
        # XVFB
        # ----------------------------------------------------

        start_xvfb()


        # ----------------------------------------------------
        # AUDIO
        # ----------------------------------------------------

        start_pulseaudio()


        # ----------------------------------------------------
        # HTTP
        # ----------------------------------------------------

        start_http()


        # ----------------------------------------------------
        # CHROMIUM
        # ----------------------------------------------------

        start_chromium()


        time.sleep(8)


        fullscreen()


        time.sleep(3)


        # ----------------------------------------------------
        # FFMPEG
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
        # TESTE
        # ----------------------------------------------------

        if not test_local_http():

            raise RuntimeError(
                "O servidor não está "
                "servindo o HLS."
            )


        # ----------------------------------------------------
        # TÚNEL
        # ----------------------------------------------------

        url = start_tunnel()


        if url is None:

            log(
                "[AVISO] Túnel não iniciou."
            )

            log(
                "[AVISO] A transmissão local "
                "continua ativa."
            )


        # ----------------------------------------------------
        # TRANSMISSÃO
        # ----------------------------------------------------

        separator()

        log(
            "TRANSMISSÃO ATIVA"
        )

        separator()


        log(
            "HLS LOCAL:"
        )

        log(
            f"http://127.0.0.1:"
            f"{PORT}/live.m3u8"
        )


        if tunnel_url:

            log("")

            log(
                "LINK PÚBLICO:"
            )

            log(
                tunnel_url
            )

            log(
                "HLS PÚBLICO:"
            )

            log(
                tunnel_url
                + "/live.m3u8"
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


        threading.Thread(
            target=hls_monitor,
            daemon=True
        ).start()


        # ----------------------------------------------------
        # LOOP 24H
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
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    main()
