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

VIDEO_BITRATE = "1000k"
VIDEO_MAXRATE = "1200k"
VIDEO_BUFSIZE = "2400k"

AUDIO_BITRATE = "128k"

PAGE_URL = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

STREAM_DIR = Path("stream")

stop_event = threading.Event()

xvfb = None
pulse = None
chromium = None
ffmpeg = None
tunnel = None
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

    stop_process(tunnel, "túnel")
    stop_process(ffmpeg, "FFmpeg")
    stop_process(chromium, "Chromium")
    stop_process(pulse, "PulseAudio")
    stop_process(xvfb, "Xvfb")

    if http_server is not None:

        try:
            http_server.shutdown()
        except Exception:
            pass

        try:
            http_server.server_close()
        except Exception:
            pass


def signal_handler(signum, frame):

    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============================================================
# VERIFICAR PROGRAMAS
# ============================================================

def check_programs():

    programs = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
        "ssh"
    ]

    missing = []

    for program in programs:

        if shutil.which(program) is None:
            missing.append(program)

    if missing:

        raise RuntimeError(
            "Programas ausentes: " +
            ", ".join(missing)
        )


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

        subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV",
                "rate=48000",
                "channels=2"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    time.sleep(2)

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
# HEADERS HTTP
# ============================================================

def send_common_headers(handler):

    handler.send_header(
        "Access-Control-Allow-Origin",
        "*"
    )

    handler.send_header(
        "Access-Control-Allow-Headers",
        "*"
    )

    handler.send_header(
        "Cache-Control",
        "no-cache, no-store, must-revalidate"
    )

    handler.send_header(
        "Pragma",
        "no-cache"
    )

    handler.send_header(
        "Expires",
        "0"
    )


# ============================================================
# SERVIDOR HTTP
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):

        self.send_response(204)

        send_common_headers(self)

        self.send_header(
            "Content-Length",
            "0"
        )

        self.end_headers()

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
      content="width=device-width, initial-scale=1">

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

    color: #fff;
    background: rgba(0,0,0,.75);

    padding: 8px 12px;

    border-radius: 5px;

    font-family: Arial, sans-serif;
    font-size: 14px;
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

    if (retryTimer) {
        return;
    }

    retryTimer = setTimeout(() => {

        retryTimer = null;

        start();

    }, 1500);
}


function start() {

    setStatus("Conectando...");


    if (
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ) {

        video.src = "/live.m3u8";

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

        backBufferLength: 10,

        maxBufferLength: 20,

        maxMaxBufferLength: 30,

        liveSyncDurationCount: 3,

        liveMaxLatencyDurationCount: 7,

        startFragPrefetch: true,

        maxBufferHole: 0.5,

        manifestLoadingMaxRetry: 20,

        manifestLoadingRetryDelay: 500,

        levelLoadingMaxRetry: 20,

        levelLoadingRetryDelay: 500,

        fragLoadingMaxRetry: 20,

        fragLoadingRetryDelay: 500

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

            if (!data.fatal) {
                return;
            }


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
    () => {

        setStatus("● AO VIVO");

    }
);


video.addEventListener(
    "waiting",
    () => {

        setStatus("Buffering...");

    }
);


video.addEventListener(
    "stalled",
    () => {

        setStatus("Buffering...");

    }
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

            send_common_headers(self)

            self.end_headers()

            try:

                self.wfile.write(data)

            except (
                BrokenPipeError,
                ConnectionResetError
            ):

                pass

            return


        # ====================================================
        # PLAYLIST HLS
        # ====================================================

        if path == "/live.m3u8":

            file = (
                STREAM_DIR /
                "live.m3u8"
            )

            if not file.exists():

                self.send_response(503)

                send_common_headers(self)

                self.send_header(
                    "Retry-After",
                    "1"
                )

                self.send_header(
                    "Content-Length",
                    "0"
                )

                self.end_headers()

                return


            try:

                data = file.read_bytes()

            except Exception:

                self.send_response(503)

                send_common_headers(self)

                self.send_header(
                    "Content-Length",
                    "0"
                )

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

            send_common_headers(self)

            self.end_headers()

            try:

                self.wfile.write(data)

            except (
                BrokenPipeError,
                ConnectionResetError
            ):

                pass

            return


        # ====================================================
        # SEGMENTOS MPEG-TS
        # ====================================================

        if path.startswith("/segment_"):

            filename = os.path.basename(path)

            if (
                ".." in filename
                or "/" in filename
                or "\\" in filename
            ):

                self.send_response(400)

                send_common_headers(self)

                self.send_header(
                    "Content-Length",
                    "0"
                )

                self.end_headers()

                return


            file = (
                STREAM_DIR /
                filename
            )

            if not file.exists():

                self.send_response(404)

                send_common_headers(self)

                self.send_header(
                    "Content-Length",
                    "0"
                )

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

                self.send_header(
                    "Accept-Ranges",
                    "bytes"
                )

                send_common_headers(self)

                self.end_headers()


                with open(
                    file,
                    "rb"
                ) as stream_file:

                    while True:

                        chunk = stream_file.read(
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
        # 404
        # ====================================================

        self.send_response(404)

        send_common_headers(self)

        self.send_header(
            "Content-Length",
            "0"
        )

        self.end_headers()


def start_http():

    global http_server

    sep()

    log(
        "[4] Iniciando servidor HTTP..."
    )


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

    log(
        "[5] Iniciando Chromium..."
    )

    browser = get_chromium()

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    profile = (
        "/tmp/webtv-chromium"
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

        "--disable-features=Translate,MediaRouter",

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


    log(
        "Chromium iniciado."
    )

    log(
        "Abrindo página:"
    )

    log(
        PAGE_URL
    )


# ============================================================
# FULLSCREEN
# ============================================================

def fullscreen():

    if not shutil.which("xdotool"):

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

    log(
        "INICIANDO FFMPEG"
    )


    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )


    segment_pattern = (
        STREAM_DIR /
        "segment_%05d.ts"
    )


    command = [

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

        "-i",
        f"{DISPLAY}.0",

        # ----------------------------------------------------
        # ÁUDIO
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
        # TIMESTAMP
        # ----------------------------------------------------

        "-vsync",
        "cfr",

        "-fps_mode",
        "cfr",

        # ----------------------------------------------------
        # CODEC VIDEO
        # ----------------------------------------------------

        "-c:v",
        "libx264",

        "-preset",
        "ultrafast",

        "-tune",
        "zerolatency",

        "-pix_fmt",
        "yuv420p",

        "-r",
        str(FPS),

        "-g",
        str(FPS * 2),

        "-keyint_min",
        str(FPS * 2),

        "-sc_threshold",
        "0",

        "-b:v",
        VIDEO_BITRATE,

        "-maxrate",
        VIDEO_MAXRATE,

        "-bufsize",
        VIDEO_BUFSIZE,

        # ----------------------------------------------------
        # CODEC AUDIO
        # ----------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        AUDIO_BITRATE,

        "-ar",
        "48000",

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
        "5",

        "-hls_flags",
        (
            "delete_segments+"
            "append_list+"
            "independent_segments"
        ),

        "-hls_delete_threshold",
        "2",

        "-start_number",
        "0",

        "-hls_segment_filename",
        str(segment_pattern),

        str(playlist)
    ]


    log(
        "Comando FFmpeg:"
    )

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


    def read_output():

        try:

            for line in ffmpeg.stdout:

                line = line.strip()

                if line:

                    log(
                        "[FFMPEG] " +
                        line
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


    log(
        "FFmpeg funcionando."
    )


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


def tunnel_alive():

    return (
        tunnel is not None
        and tunnel.poll() is None
    )


def stop_tunnel():

    global tunnel

    if tunnel is None:
        return


    try:

        if tunnel.poll() is None:

            tunnel.terminate()

            try:
                tunnel.wait(timeout=3)
            except subprocess.TimeoutExpired:
                tunnel.kill()

    except Exception:

        pass


    tunnel = None


def start_tunnel():

    global tunnel
    global tunnel_url

    stop_tunnel()

    sep()

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
            "[TUNEL] Erro:"
        )

        log(
            str(e)
        )

        tunnel = None

        return None


    start = time.time()


    while (
        time.time() - start < 45
    ):

        if tunnel.poll() is not None:

            tunnel = None

            return None


        line = tunnel.stdout.readline()


        if not line:

            time.sleep(.2)

            continue


        line = line.strip()


        if line:

            log(
                "[TUNEL] " +
                line
            )


        url = extract_url(line)


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


    stop_tunnel()

    return None


# ============================================================
# MONITOR DO TÚNEL
# ============================================================

def tunnel_monitor():

    global tunnel_url

    while not stop_event.is_set():

        time.sleep(5)


        if tunnel_alive():

            continue


        sep()

        log(
            "[TUNEL] Túnel caiu."
        )

        log(
            "[TUNEL] FFmpeg continua ativo."
        )

        log(
            "[TUNEL] Reconectando..."
        )

        sep()


        for attempt in range(1, 11):

            if stop_event.is_set():
                return


            log(
                f"[TUNEL] Tentativa "
                f"{attempt}/10"
            )


            url = start_tunnel()


            if url:

                tunnel_url = url

                log(
                    "[TUNEL] Reconectado."
                )

                break


            time.sleep(
                min(
                    attempt * 2,
                    15
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

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

    previous = 0

    stalled_since = None


    while not stop_event.is_set():

        time.sleep(10)


        if not playlist.exists():

            log(
                "[HLS] Playlist ausente."
            )

            continue


        try:

            current = (
                playlist.stat().st_mtime
            )

        except Exception:

            continue


        if current == previous:

            if stalled_since is None:

                stalled_since = time.time()

            elif (
                time.time() -
                stalled_since > 30
            ):

                log(
                    "[HLS] ALERTA: playlist "
                    "parada há mais de "
                    "30 segundos."
                )

        else:

            stalled_since = None


        previous = current


# ============================================================
# MONITOR CHROMIUM
# ============================================================

def chromium_monitor():

    while not stop_event.is_set():

        time.sleep(10)


        if chromium is None:
            continue


        if chromium.poll() is not None:

            sep()

            log(
                "[ERRO] Chromium encerrou."
            )

            log(
                "[ERRO] A página da transmissão "
                "foi encerrada."
            )

            sep()


            stop_event.set()

            return


# ============================================================
# MAIN
# ============================================================

def main():

    global tunnel_url

    sep()

    log(
        "WEBTV STREAM 24H"
    )

    sep()


    # --------------------------------------------------------
    # VERIFICAR
    # --------------------------------------------------------

    check_programs()


    # --------------------------------------------------------
    # LIMPAR
    # --------------------------------------------------------

    clean_stream()


    # --------------------------------------------------------
    # XVFB
    # --------------------------------------------------------

    start_xvfb()


    # --------------------------------------------------------
    # PULSE
    # --------------------------------------------------------

    start_pulseaudio()


    # --------------------------------------------------------
    # HTTP
    # --------------------------------------------------------

    start_http()


    # --------------------------------------------------------
    # CHROMIUM
    # --------------------------------------------------------

    start_chromium()

    time.sleep(8)

    fullscreen()

    time.sleep(3)


    # --------------------------------------------------------
    # FFMPEG
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
    # TÚNEL
    # --------------------------------------------------------

    tunnel_url = start_tunnel()


    # --------------------------------------------------------
    # TRANSMISSÃO
    # --------------------------------------------------------

    sep()

    log(
        "TRANSMISSÃO ATIVA"
    )

    sep()


    log(
        "LINK LOCAL:"
    )

    log(
        f"http://127.0.0.1:{PORT}/"
    )


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

        log("")

        log(
            "[AVISO] Túnel não iniciou."
        )

        log(
            "[AVISO] A transmissão local "
            "continua funcionando."
        )


    sep()


    # --------------------------------------------------------
    # MONITORES
    # --------------------------------------------------------

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


    threading.Thread(
        target=chromium_monitor,
        daemon=True
    ).start()


    # --------------------------------------------------------
    # MANTER 24 HORAS
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
