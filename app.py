#!/usr/bin/env python3

import os
import re
import sys
import time
import json
import shutil
import signal
import threading
import subprocess
import urllib.request
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

NGROK_AUTHTOKEN = os.environ.get(
    "NGROK_AUTHTOKEN",
    ""
).strip()

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

    global http_server

    if stop_event.is_set():
        return

    stop_event.set()

    sep()
    log("ENCERRANDO WEBTV")
    sep()

    stop_process(tunnel, "ngrok")
    stop_process(ffmpeg, "FFmpeg")
    stop_process(chromium, "Chromium")
    stop_process(pulse, "PulseAudio")
    stop_process(xvfb, "Xvfb")

    try:

        if http_server:
            http_server.shutdown()
            http_server.server_close()

    except Exception:
        pass


def signal_handler(signum, frame):

    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


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

    chromium_found = False

    for name in [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable"
    ]:

        if shutil.which(name):
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

            if item.is_file():
                item.unlink()

            elif item.is_dir():
                shutil.rmtree(item)

        except Exception as e:

            log(
                f"[STREAM] Não foi possível remover "
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
                "sink_properties=device.description=WebTV"
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
# SERVIDOR HTTP
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    # IMPORTANTE:
    # não usar self.headers() porque BaseHTTPRequestHandler
    # já possui self.headers como HTTPMessage.
    def add_cache_headers(self):

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

    def send_error_response(self, code):

        try:

            self.send_response(code)
            self.add_cache_headers()
            self.send_header(
                "Content-Length",
                "0"
            )
            self.end_headers()

        except BrokenPipeError:
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

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

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

    background:
        rgba(0,0,0,.7);

    padding:
        8px 12px;

    border-radius: 5px;

    font-family:
        Arial,
        sans-serif;

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
let started = false;


function setStatus(text) {

    status.textContent = text;
}


function scheduleReconnect() {

    if (retryTimer)
        return;

    retryTimer = setTimeout(() => {

        retryTimer = null;

        startPlayer();

    }, 2000);
}


function startPlayer() {

    if (started)
        return;

    started = true;


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
        "https://cdn.jsdelivr.net/npm/hls.js@1.5.17";

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

    script.onerror = () => {

        started = false;

        setStatus(
            "Erro ao carregar HLS"
        );

        scheduleReconnect();
    };

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

        liveMaxLatencyDurationCount: 7,

        manifestLoadingMaxRetry: 10,

        manifestLoadingRetryDelay: 1000,

        levelLoadingMaxRetry: 10,

        levelLoadingRetryDelay: 1000,

        fragLoadingMaxRetry: 10,

        fragLoadingRetryDelay: 1000,

        startFragPrefetch: true
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

            started = false;

            scheduleReconnect();
        }
    );
}


video.addEventListener(
    "playing",
    () => {

        setStatus(
            "● AO VIVO"
        );
    }
);


video.addEventListener(
    "waiting",
    () => {

        setStatus(
            "Buffering..."
        );
    }
);


video.addEventListener(
    "stalled",
    () => {

        setStatus(
            "Reconectando..."
        );
    }
);


startPlayer();

</script>

</body>
</html>
"""

            data = html.encode(
                "utf-8"
            )

            try:

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8"
                )

                self.send_header(
                    "Content-Length",
                    str(len(data))
                )

                self.add_cache_headers()

                self.end_headers()

                self.wfile.write(data)

            except BrokenPipeError:
                pass

            return


        # ----------------------------------------------------
        # PLAYLIST
        # ----------------------------------------------------

        if path == "/live.m3u8":

            file = (
                STREAM_DIR /
                "live.m3u8"
            )

            if not file.exists():

                self.send_error_response(503)
                return

            try:

                data = file.read_bytes()

            except Exception:

                self.send_error_response(503)
                return

            try:

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "application/vnd.apple.mpegurl"
                )

                self.send_header(
                    "Content-Length",
                    str(len(data))
                )

                self.add_cache_headers()

                self.end_headers()

                self.wfile.write(data)

            except BrokenPipeError:
                pass

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

                self.send_error_response(400)
                return


            file = STREAM_DIR / filename

            if not file.exists():

                self.send_error_response(404)
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

                self.add_cache_headers()

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


        self.send_error_response(404)


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

    command = [

        "ffmpeg",

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

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
        "1800k",

        "-maxrate",
        "2000k",

        "-bufsize",
        "4000k",

        # ----------------------------------------------------
        # AUDIO
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # HLS
        # ----------------------------------------------------

        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "10",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_delete_threshold",
        "5",

        "-hls_segment_filename",

        str(
            STREAM_DIR /
            "segment_%06d.ts"
        ),

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
                        "[FFMPEG] "
                        + line
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

def ngrok_installed():

    return shutil.which("ngrok") is not None


def check_ngrok():

    if ngrok_installed():
        return True

    log(
        "[NGROK] Executável não encontrado."
    )

    log(
        "[NGROK] O workflow deve instalar o ngrok "
        "antes de executar o app."
    )

    return False


def configure_ngrok():

    if not NGROK_AUTHTOKEN:

        log(
            "[NGROK] ERRO: NGROK_AUTHTOKEN "
            "não configurado."
        )

        log(
            "[NGROK] A transmissão local "
            "continuará ativa."
        )

        return False

    try:

        result = subprocess.run(
            [
                "ngrok",
                "config",
                "add-authtoken",
                NGROK_AUTHTOKEN
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20
        )

        if result.returncode != 0:

            log(
                "[NGROK] Falha ao configurar "
                "authtoken."
            )

            if result.stdout:
                log(result.stdout.strip())

            return False

        log(
            "[NGROK] Authtoken configurado."
        )

        return True

    except Exception as e:

        log(
            f"[NGROK] Erro: {e}"
        )

        return False


def get_ngrok_url():

    try:

        with urllib.request.urlopen(
            "http://127.0.0.1:4040/api/tunnels",
            timeout=3
        ) as response:

            data = json.loads(
                response.read().decode()
            )

        for item in data.get(
            "tunnels",
            []
        ):

            url = item.get(
                "public_url",
                ""
            )

            if url.startswith(
                "https://"
            ):

                return url

    except Exception:
        pass

    return None


def start_ngrok():

    global tunnel
    global tunnel_url

    if not check_ngrok():
        return False

    if not configure_ngrok():
        return False

    stop_process(
        tunnel,
        "ngrok"
    )

    tunnel = None
    tunnel_url = None

    sep()

    log(
        "[NGROK] Iniciando túnel..."
    )

    try:

        tunnel = subprocess.Popen(
            [
                "ngrok",
                "http",
                str(PORT),
                "--log=stdout"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    except Exception as e:

        log(
            f"[NGROK] Erro ao iniciar: {e}"
        )

        tunnel = None

        return False


    for attempt in range(1, 31):

        if stop_event.is_set():
            return False

        if tunnel.poll() is not None:

            log(
                "[NGROK] Processo encerrou."
            )

            tunnel = None

            return False

        url = get_ngrok_url()

        if url:

            tunnel_url = url

            sep()

            log(
                "TRANSMISSÃO PÚBLICA ATIVA"
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
                tunnel_url
                + "/live.m3u8"
            )

            sep()

            return True

        if attempt % 5 == 0:

            log(
                f"[NGROK] Aguardando URL "
                f"({attempt}/30)..."
            )

        time.sleep(1)


    log(
        "[NGROK] Não foi possível "
        "obter a URL pública."
    )

    stop_process(
        tunnel,
        "ngrok"
    )

    tunnel = None

    return False


# ============================================================
# MONITOR NGROK
# ============================================================

def ngrok_monitor():

    global tunnel

    while not stop_event.is_set():

        time.sleep(10)

        if stop_event.is_set():
            return

        if tunnel is not None:

            if tunnel.poll() is None:

                url = get_ngrok_url()

                if url:

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

        for attempt in range(1, 11):

            if stop_event.is_set():
                return

            log(
                f"[NGROK] Tentativa "
                f"{attempt}/10"
            )

            if start_ngrok():

                log(
                    "[NGROK] Túnel reconectado."
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

    while not stop_event.is_set():

        time.sleep(15)

        if not playlist.exists():

            log(
                "[HLS] ALERTA: playlist ausente."
            )

            continue

        try:

            current = (
                playlist.stat().st_mtime
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
# MAIN
# ============================================================

def main():

    sep()

    log(
        "WEBTV STREAM 24H"
    )

    sep()

    # --------------------------------------------------------
    # VERIFICAÇÃO
    # --------------------------------------------------------

    check_programs()

    # --------------------------------------------------------
    # STREAM
    # --------------------------------------------------------

    clean_stream()

    # --------------------------------------------------------
    # XVFB
    # --------------------------------------------------------

    start_xvfb()

    # --------------------------------------------------------
    # AUDIO
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
    # NGROK
    # --------------------------------------------------------

    start_ngrok()

    # --------------------------------------------------------
    # STATUS
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

    else:

        log("")

        log(
            "[AVISO] Túnel público "
            "não está ativo."
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
