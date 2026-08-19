#!/usr/bin/env python3

import os
import re
import sys
import time
import signal
import shutil
import threading
import subprocess
import platform
import tarfile
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

NGROK_DIR = Path.home() / ".ngrok"
NGROK_BIN = NGROK_DIR / "ngrok"

stop_event = threading.Event()

xvfb = None
pulse = None
chromium = None
ffmpeg = None
ngrok_process = None
http_server = None

public_url = None


# ============================================================
# LOG
# ============================================================

def log(text=""):
    print(text, flush=True)


def sep():
    log("=" * 70)


# ============================================================
# LIMPEZA
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

    stop_process(ngrok_process, "ngrok")
    stop_process(ffmpeg, "FFmpeg")
    stop_process(chromium, "Chromium")
    stop_process(pulse, "PulseAudio")
    stop_process(xvfb, "Xvfb")

    if http_server:

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
        raise RuntimeError("Xvfb não iniciou.")

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
# HTTP
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    # IMPORTANTE:
    # Não usar self.headers() porque BaseHTTPRequestHandler
    # já possui self.headers como atributo HTTPMessage.

    def send_common_headers(self):

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

        # ----------------------------------------------------
        # PLAYER
        # ----------------------------------------------------

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

const video = document.getElementById("video");
const status = document.getElementById("status");

let hls = null;
let reconnectTimer = null;


function setStatus(text) {
    status.textContent = text;
}


function reconnect() {

    if (reconnectTimer)
        return;

    reconnectTimer = setTimeout(() => {

        reconnectTimer = null;

        start();

    }, 2000);
}


function start() {

    if (
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ) {

        video.src =
            "/live.m3u8?t=" +
            Date.now();

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
        "https://cdn.jsdelivr.net/npm/hls.js@1.6.2";

    script.onload = () => {

        if (
            window.Hls &&
            Hls.isSupported()
        ) {

            createHls();

        } else {

            setStatus("HLS não suportado");
        }
    };

    script.onerror = reconnect;

    document.head.appendChild(script);
}


function createHls() {

    if (hls) {

        try {
            hls.destroy();
        } catch (e) {}

        hls = null;
    }


    hls = new Hls({

        enableWorker: true,

        lowLatencyMode: false,

        backBufferLength: 30,

        maxBufferLength: 20,

        maxMaxBufferLength: 40,

        liveSyncDurationCount: 3,

        liveMaxLatencyDurationCount: 8,

        manifestLoadingMaxRetry: 30,

        manifestLoadingRetryDelay: 1000,

        levelLoadingMaxRetry: 30,

        levelLoadingRetryDelay: 1000,

        fragLoadingMaxRetry: 30,

        fragLoadingRetryDelay: 1000
    });


    hls.loadSource(
        "/live.m3u8?t=" +
        Date.now()
    );

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
        Hls.Events.ERROR,
        (event, data) => {

            if (!data.fatal)
                return;

            setStatus("Reconectando...");


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

            reconnect();
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
    () => setStatus("Reconectando...")
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

            self.send_common_headers()

            self.end_headers()

            try:
                self.wfile.write(data)
            except BrokenPipeError:
                pass

            return


        # ----------------------------------------------------
        # PLAYLIST
        # ----------------------------------------------------

        if path == "/live.m3u8":

            file = STREAM_DIR / "live.m3u8"

            if not file.exists():

                self.send_response(503)

                self.send_common_headers()

                self.end_headers()

                return


            try:
                data = file.read_bytes()

            except Exception:

                self.send_response(503)

                self.send_common_headers()

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

            try:
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

                self.send_common_headers()

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

        self.send_common_headers()

        self.end_headers()


# ============================================================
# SERVIDOR
# ============================================================

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

        log("[TELA] Chromium em tela cheia.")

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

    log("FFmpeg iniciado.")

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
                    log("[FFMPEG] " + line)

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

                log("[HLS] Playlist pronta.")

                return True

        time.sleep(1)

    return False


# ============================================================
# NGROK
# ============================================================

def get_ngrok_token():

    token = os.environ.get(
        "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk",
        ""
    ).strip()

    return token


def install_ngrok():

    if NGROK_BIN.exists():

        try:

            NGROK_BIN.chmod(0o755)

        except Exception:
            pass

        return True


    system = platform.system().lower()
    machine = platform.machine().lower()

    if system != "linux":

        log(
            "[NGROK] Sistema não suportado para "
            "instalação automática."
        )

        return False


    if machine in ("x86_64", "amd64"):

        filename = "ngrok-v3-stable-linux-amd64.tgz"

    elif machine in ("aarch64", "arm64"):

        filename = "ngrok-v3-stable-linux-arm64.tgz"

    else:

        log(
            "[NGROK] Arquitetura não suportada: "
            + machine
        )

        return False


    url = (
        "https://bin.equinox.io/c/"
        "bNyj1mQVY4c/"
        + filename
    )


    try:

        NGROK_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        archive = NGROK_DIR / "ngrok.tgz"

        log("[NGROK] Baixando agente...")

        urllib.request.urlretrieve(
            url,
            archive
        )

        log("[NGROK] Extraindo agente...")

        with tarfile.open(
            archive,
            "r:gz"
        ) as tar:

            member = None

            for item in tar.getmembers():

                if item.name.endswith("/ngrok") or item.name == "ngrok":

                    member = item
                    break

            if member is None:

                raise RuntimeError(
                    "Executável ngrok não encontrado no pacote."
                )

            member.name = "ngrok"

            tar.extract(
                member,
                NGROK_DIR
            )


        NGROK_BIN.chmod(0o755)

        try:
            archive.unlink()
        except Exception:
            pass

        log("[NGROK] Agente instalado.")

        return True

    except Exception as e:

        log(
            "[NGROK] Falha ao instalar:"
        )

        log(str(e))

        return False


def get_ngrok_binary():

    path = shutil.which("ngrok")

    if path:
        return path

    if NGROK_BIN.exists():

        try:
            NGROK_BIN.chmod(0o755)
        except Exception:
            pass

        return str(NGROK_BIN)

    if install_ngrok():

        return str(NGROK_BIN)

    return None


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


def ngrok_alive():

    return (
        ngrok_process is not None
        and ngrok_process.poll() is None
    )


def start_ngrok():

    global ngrok_process
    global public_url

    if ngrok_alive():
        return public_url


    token = get_ngrok_token()

    if not token:

        log(
            "[NGROK] NGROK_AUTHTOKEN não configurado."
        )

        log(
            "[NGROK] Configure o secret "
            "NGROK_AUTHTOKEN no GitHub."
        )

        return None


    binary = get_ngrok_binary()

    if not binary:

        log(
            "[NGROK] Não foi possível obter o executável."
        )

        return None


    sep()

    log("[NGROK] Iniciando túnel...")

    command = [

        binary,

        "http",

        str(PORT),

        "--authtoken",
        token,

        "--log",
        "stdout",

        "--log-format",
        "logfmt"
    ]


    try:

        ngrok_process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

    except Exception as e:

        log("[NGROK] Erro ao iniciar:")
        log(str(e))

        ngrok_process = None

        return None


    start = time.time()

    output = ""


    while time.time() - start < 30:

        if ngrok_process.poll() is not None:

            log(
                "[NGROK] Processo encerrou."
            )

            ngrok_process = None

            return None


        line = ngrok_process.stdout.readline()

        if not line:

            time.sleep(.2)
            continue


        line = line.strip()

        if not line:
            continue


        output += line + "\n"

        url = extract_ngrok_url(line)

        if url:

            public_url = url

            sep()

            log("NGROK ATIVO")

            log("LINK PRINCIPAL:")

            log(public_url)

            log("LINK HLS:")

            log(
                public_url +
                "/live.m3u8"
            )

            sep()

            return public_url


    log(
        "[NGROK] Não foi possível obter o endereço público."
    )

    if output:
        log(output[-2000:])

    stop_process(
        ngrok_process,
        "ngrok"
    )

    ngrok_process = None

    return None


# ============================================================
# MONITOR NGROK
# ============================================================

def ngrok_monitor():

    global ngrok_process

    while not stop_event.is_set():

        time.sleep(10)

        if ngrok_alive():
            continue


        if not get_ngrok_token():

            # Não fica martelando o log infinitamente.
            time.sleep(30)

            continue


        sep()

        log("[NGROK] Túnel desconectado.")
        log("[NGROK] FFmpeg continua funcionando.")
        log("[NGROK] Tentando reconectar...")

        ngrok_process = None

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

            time.sleep(
                min(
                    attempt * 3,
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

            log("[ERRO] FFmpeg parou.")

            log(
                "[ERRO] A transmissão foi encerrada."
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

    while not stop_event.is_set():

        time.sleep(10)

        if not playlist.exists():

            log(
                "[HLS] ALERTA: playlist ausente."
            )

            continue


        try:

            current = playlist.stat().st_mtime

        except Exception:

            continue


        if current == previous:

            log(
                "[HLS] ALERTA: playlist não atualizou."
            )

        previous = current


# ============================================================
# MAIN
# ============================================================

def main():

    global public_url

    sep()

    log("WEBTV STREAM 24H")

    sep()


    # Não instala apt/pip aqui.
    # O ambiente deve instalar os programas
    # antes de executar este arquivo.

    check_programs()


    clean_stream()

    start_xvfb()

    start_pulseaudio()

    start_http()

    start_chromium()

    time.sleep(6)

    fullscreen()

    time.sleep(2)

    start_ffmpeg()

    if not wait_hls():

        raise RuntimeError(
            "HLS não foi criado."
        )


    # --------------------------------------------------------
    # NGROK
    # --------------------------------------------------------

    public_url = start_ngrok()


    # --------------------------------------------------------
    # TRANSMISSÃO
    # --------------------------------------------------------

    sep()

    log("TRANSMISSÃO ATIVA")

    sep()

    log("HLS LOCAL:")

    log(
        f"http://127.0.0.1:{PORT}/live.m3u8"
    )


    if public_url:

        log("")

        log("LINK PÚBLICO:")

        log(public_url)

        log("")

        log("LINK HLS:")

        log(
            public_url +
            "/live.m3u8"
        )

    else:

        log("")

        log(
            "[AVISO] Túnel público não está ativo."
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

        log("[ERRO FATAL]")

        log(str(e))

        sep()

    finally:

        cleanup()
