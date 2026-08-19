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

NGROK_AUTHTOKEN = os.environ.get("NGROK_AUTHTOKEN", "").strip()

stop_event = threading.Event()

xvfb = None
pulse = None
chromium = None
ffmpeg = None
ngrok = None
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

    try:
        if http_server:
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
        "ffmpeg",
        "ngrok"
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


def check_ngrok_auth():

    if not NGROK_AUTHTOKEN:

        raise RuntimeError(
            "NGROK_AUTHTOKEN não configurado. "
            "Configure a variável de ambiente antes de executar."
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

    # Define o sink virtual como padrão.
    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    log("Fontes de áudio:")

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

    log(sources.stdout.strip())

    log("Áudio pronto.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    # IMPORTANTE:
    # não chamar self.headers(), pois self.headers
    # já é um HTTPMessage interno do BaseHTTPRequestHandler.

    def add_common_headers(self):

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
            "Accept-Ranges",
            "bytes"
        )

    def do_OPTIONS(self):

        self.send_response(204)

        self.add_common_headers()

        self.end_headers()

    def do_GET(self):

        path = self.path.split("?")[0]

        # ====================================================
        # PLAYER
        # ====================================================

        if path == "/":

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
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    background: #000;
    overflow: hidden;
}

body {
    display: flex;
    align-items: center;
    justify-content: center;
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
    background: rgba(0,0,0,.72);

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
let starting = false;


function setStatus(text) {

    status.textContent = text;
}


function scheduleReconnect(delay = 2000) {

    if (retryTimer)
        return;

    retryTimer = setTimeout(() => {

        retryTimer = null;

        start();

    }, delay);
}


function destroyHls() {

    if (hls) {

        try {
            hls.destroy();
        } catch (e) {}

        hls = null;
    }
}


function startNativeHls() {

    video.src = "/live.m3u8";

    video.load();

    video.play()
        .then(() => {

            setStatus("● AO VIVO");

        })
        .catch(() => {

            setStatus("Clique para iniciar");

        });
}


function createHls() {

    destroyHls();

    hls = new Hls({

        enableWorker: true,

        lowLatencyMode: false,

        backBufferLength: 15,

        maxBufferLength: 20,

        maxMaxBufferLength: 40,

        liveSyncDurationCount: 3,

        liveMaxLatencyDurationCount: 7,

        startFragPrefetch: true,

        maxBufferHole: 0.5,

        maxStarvationDelay: 2,

        maxLoadingDelay: 2,

        manifestLoadingMaxRetry: 50,

        manifestLoadingRetryDelay: 1000,

        manifestLoadingMaxRetryTimeout: 5000,

        levelLoadingMaxRetry: 50,

        levelLoadingRetryDelay: 1000,

        fragLoadingMaxRetry: 50,

        fragLoadingRetryDelay: 1000
    });


    hls.loadSource("/live.m3u8");

    hls.attachMedia(video);


    hls.on(
        Hls.Events.MANIFEST_PARSED,
        () => {

            setStatus("● AO VIVO");

            video.play()
                .catch(() => {});

        }
    );


    hls.on(
        Hls.Events.FRAG_BUFFERED,
        () => {

            if (
                video.buffered.length > 0
            ) {

                const end =
                    video.buffered.end(
                        video.buffered.length - 1
                    );

                const latency =
                    end - video.currentTime;

                /*
                 * Se o player ficar muito atrás,
                 * retorna suavemente para perto
                 * do live edge.
                 */

                if (latency > 10) {

                    try {

                        video.currentTime =
                            Math.max(
                                0,
                                end - 4
                            );

                    } catch (e) {}
                }
            }
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


            destroyHls();

            scheduleReconnect(1500);
        }
    );
}


function start() {

    if (starting)
        return;

    starting = true;


    try {

        if (
            video.canPlayType(
                "application/vnd.apple.mpegurl"
            )
        ) {

            startNativeHls();

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
            "https://cdn.jsdelivr.net/npm/hls.js@1.6.13/dist/hls.min.js";


        script.onload = () => {

            starting = false;

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

            starting = false;

            setStatus(
                "Erro ao carregar player"
            );

            scheduleReconnect(3000);
        };


        document.head.appendChild(script);

    } catch (e) {

        starting = false;

        scheduleReconnect(2000);
    }
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
        setStatus("Reconectando...");
    }
);


video.addEventListener(
    "error",
    () => {
        scheduleReconnect(2000);
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

            self.add_common_headers()

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

                self.add_common_headers()

                self.end_headers()

                return


            try:

                data = file.read_bytes()

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

            self.add_common_headers()

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


            if not filename.endswith(".ts"):

                self.send_response(400)
                self.end_headers()

                return


            file = STREAM_DIR / filename

            if not file.exists():

                self.send_response(404)

                self.add_common_headers()

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

                self.add_common_headers()

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
                        except BrokenPipeError:
                            break

            except Exception:
                pass

            return


        self.send_response(404)

        self.add_common_headers()

        self.end_headers()


class ReusableHTTPServer(ThreadingHTTPServer):

    allow_reuse_address = True
    daemon_threads = True


def start_http():

    global http_server

    sep()

    log("[4] Iniciando servidor HTTP...")

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

        "--disable-features=Translate,BackForwardCache",

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

    playlist = STREAM_DIR / "live.m3u8"

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

        "-thread_queue_size",
        "4096",

        # ====================================================
        # VÍDEO
        # ====================================================

        "-f",
        "x11grab",

        "-draw_mouse",
        "0",

        "-framerate",
        str(FPS),

        "-video_size",
        f"{WIDTH}x{HEIGHT}",

        "-use_wallclock_as_timestamps",
        "1",

        "-i",
        f"{DISPLAY}.0",

        # ====================================================
        # ÁUDIO
        # ====================================================

        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-use_wallclock_as_timestamps",
        "1",

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
        "1600k",

        "-maxrate",
        "1800k",

        "-bufsize",
        "3600k",

        # ====================================================
        # AUDIO
        # ====================================================

        "-c:a",
        "aac",

        "-profile:a",
        "aac_low",

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

        "-hls_delete_threshold",
        "5",

        "-hls_flags",
        "delete_segments+append_list+independent_segments+temp_file",

        "-hls_segment_filename",
        str(segment_pattern),

        "-start_number",
        "0",

        str(playlist)
    ]

    log("Comando FFmpeg:")

    log(" ".join(command))

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
# AGUARDAR HLS
# ============================================================

def wait_hls():

    sep()

    log(
        "[HLS] Aguardando playlist..."
    )

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
# NGROK
# ============================================================

def extract_ngrok_url(text):

    patterns = [

        r"https://[A-Za-z0-9.-]+\.ngrok-free\.app",

        r"https://[A-Za-z0-9.-]+\.ngrok\.app",

        r"https://[A-Za-z0-9.-]+\.ngrok\.dev"
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

    if ngrok_alive():
        return tunnel_url

    sep()

    log("[TÚNEL] Iniciando ngrok...")

    env = os.environ.copy()

    env["NGROK_AUTHTOKEN"] = NGROK_AUTHTOKEN

    command = [

        "ngrok",

        "http",

        str(PORT),

        "--log",
        "stdout"
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
            "[TÚNEL] Erro ao iniciar ngrok:"
        )

        log(str(e))

        ngrok = None

        return None


    start = time.time()


    while time.time() - start < 30:

        if stop_event.is_set():
            return None

        if ngrok.poll() is not None:

            log(
                "[TÚNEL] ngrok encerrou."
            )

            ngrok = None

            return None


        try:

            line = ngrok.stdout.readline()

        except Exception:

            line = ""


        if not line:

            time.sleep(.2)
            continue


        line = line.strip()


        if line:

            log(
                "[TÚNEL] "
                + line
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

            return tunnel_url


    log(
        "[TÚNEL] URL não encontrada."
    )

    try:
        ngrok.terminate()
    except Exception:
        pass

    ngrok = None

    return None


# ============================================================
# MONITOR DO NGROK
# ============================================================

def ngrok_monitor():

    global ngrok

    while not stop_event.is_set():

        time.sleep(5)

        if ngrok_alive():
            continue

        if stop_event.is_set():
            return

        sep()

        log(
            "[TÚNEL] ngrok caiu."
        )

        log(
            "[TÚNEL] FFmpeg continuará ativo."
        )

        log(
            "[TÚNEL] Tentando reconectar..."
        )

        sep()

        ngrok = None


        for attempt in range(1, 11):

            if stop_event.is_set():
                return


            log(
                f"[TÚNEL] Reconexão "
                f"{attempt}/10"
            )


            url = start_ngrok()


            if url:

                log(
                    "[TÚNEL] ngrok reconectado."
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

    playlist = STREAM_DIR / "live.m3u8"

    previous_mtime = 0

    stalled_count = 0

    while not stop_event.is_set():

        time.sleep(10)

        if not playlist.exists():

            log(
                "[HLS] ALERTA: playlist ausente."
            )

            continue


        try:

            current_mtime = (
                playlist.stat().st_mtime
            )

        except Exception:

            continue


        if current_mtime == previous_mtime:

            stalled_count += 1

            log(
                "[HLS] ALERTA: playlist "
                f"sem atualização "
                f"({stalled_count})"
            )

        else:

            stalled_count = 0


        previous_mtime = current_mtime


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
                "[ERRO] Chromium parou."
            )

            log(
                "[ERRO] A fonte da transmissão "
                "foi encerrada."
            )

            stop_event.set()

            return


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
    # VERIFICAÇÕES
    # ========================================================

    check_programs()

    check_ngrok_auth()


    # ========================================================
    # STREAM ANTIGO
    # ========================================================

    clean_stream()


    # ========================================================
    # XVFB
    # ========================================================

    start_xvfb()


    # ========================================================
    # AUDIO
    # ========================================================

    start_pulseaudio()


    # ========================================================
    # HTTP
    # ========================================================

    start_http()


    # ========================================================
    # CHROMIUM
    # ========================================================

    start_chromium()

    time.sleep(8)

    fullscreen()

    time.sleep(3)


    # ========================================================
    # FFMPEG
    # ========================================================

    start_ffmpeg()


    # ========================================================
    # HLS
    # ========================================================

    if not wait_hls():

        raise RuntimeError(
            "HLS não foi criado."
        )


    # ========================================================
    # NGROK
    # ========================================================

    start_ngrok()


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
