#!/usr/bin/env python3

import os
import re
import sys
import time
import signal
import shutil
import threading
import subprocess
import urllib.request
import urllib.error

from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


# ============================================================
# CONFIGURAÇÃO
# ============================================================

HOST = "0.0.0.0"
LOCAL_HOST = "127.0.0.1"

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

public_url = None


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

    stop_process(cloudflared, "Cloudflare Tunnel")
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
# VERIFICAR PROGRAMAS
# ============================================================

def get_chromium():

    names = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]

    for name in names:

        path = shutil.which(name)

        if path:
            return path

    return None


def get_cloudflared():

    path = shutil.which("cloudflared")

    if path:
        return path

    candidates = [

        Path("/usr/local/bin/cloudflared"),

        Path("/usr/bin/cloudflared"),

        Path.home()
        / ".local"
        / "bin"
        / "cloudflared",

    ]

    for candidate in candidates:

        if candidate.exists():

            try:

                candidate.chmod(
                    candidate.stat().st_mode | 0o111
                )
            except Exception:
                pass

            return str(candidate)

    return None


def check_programs():

    programs = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
        "curl",
    ]

    missing = []

    for program in programs:

        if shutil.which(program) is None:
            missing.append(program)

    if get_chromium() is None:
        missing.append("chromium")

    if get_cloudflared() is None:
        missing.append("cloudflared")

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

            if item.is_file() or item.is_symlink():

                item.unlink()

            elif item.is_dir():

                shutil.rmtree(item)

        except Exception as e:

            log(
                "[STREAM] Erro removendo "
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

            "-noreset",
        ],

        stdout=subprocess.DEVNULL,

        stderr=subprocess.DEVNULL,

        env=env,
    )

    for _ in range(30):

        if xvfb.poll() is not None:

            raise RuntimeError(
                "Xvfb encerrou durante a inicialização."
            )

        time.sleep(0.2)

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


def pactl_command(args):

    return subprocess.run(

        ["pactl"] + args,

        capture_output=True,

        text=True,

        env=pulse_env(),

    )


def sink_exists():

    result = pactl_command(
        ["list", "short", "sinks"]
    )

    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():

        parts = line.split()

        if len(parts) >= 2:

            if parts[1] == "webtv":
                return True

    return False


def monitor_exists():

    result = pactl_command(
        ["list", "short", "sources"]
    )

    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():

        parts = line.split()

        if len(parts) >= 2:

            if parts[1] == "webtv.monitor":
                return True

    return False


def start_pulseaudio():

    global pulse

    sep()

    log("[3] Iniciando PulseAudio...")

    env = pulse_env()

    subprocess.run(

        [
            "pulseaudio",
            "--kill",
        ],

        stdout=subprocess.DEVNULL,

        stderr=subprocess.DEVNULL,

        env=env,
    )

    time.sleep(1)

    pulse = subprocess.Popen(

        [
            "pulseaudio",

            "--daemonize=no",

            "--system=false",

            "--exit-idle-time=-1",

            "--log-target=stderr",
        ],

        stdout=subprocess.DEVNULL,

        stderr=subprocess.DEVNULL,

        env=env,
    )

    ready = False

    for _ in range(40):

        result = pactl_command(["info"])

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

    # --------------------------------------------------------
    # REMOVE SINK ANTIGO
    # --------------------------------------------------------

    if sink_exists():

        log(
            "[ÁUDIO] Sink webtv já existe."
        )

    else:

        log(
            "[ÁUDIO] Criando sink webtv..."
        )

        result = pactl_command(

            [
                "load-module",

                "module-null-sink",

                "sink_name=webtv",

                "sink_properties="
                "device.description=WebTV",

                "rate=44100",

                "channels=2",

                "channel_map="
                "front-left,front-right",
            ]

        )

        if result.returncode != 0:

            raise RuntimeError(
                "Falha ao criar o sink webtv: "
                + result.stderr.strip()
            )

    # --------------------------------------------------------
    # ESPERA SINK
    # --------------------------------------------------------

    for _ in range(30):

        if sink_exists():
            break

        time.sleep(0.5)

    if not sink_exists():

        raise RuntimeError(
            "Não foi possível criar "
            "o dispositivo de áudio webtv."
        )

    # --------------------------------------------------------
    # DEFAULT SINK
    # --------------------------------------------------------

    pactl_command(
        [
            "set-default-sink",
            "webtv",
        ]
    )

    # --------------------------------------------------------
    # ESPERA MONITOR
    # --------------------------------------------------------

    for _ in range(30):

        if monitor_exists():
            break

        time.sleep(0.5)

    if not monitor_exists():

        raise RuntimeError(
            "O monitor webtv.monitor "
            "não foi criado."
        )

    result = pactl_command(
        ["list", "short", "sources"]
    )

    log("Fontes de áudio:")
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

    def headers(self):

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

    def send_data(
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

        self.headers()

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

    z-index: 100;

    color: white;

    background: rgba(0,0,0,.75);

    padding: 8px 12px;

    border-radius: 5px;

    font-family: Arial,sans-serif;
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

let reconnectTimer = null;


function statusText(text) {

    status.textContent = text;

}


function reconnect() {

    if (reconnectTimer)
        return;

    reconnectTimer =
        setTimeout(function() {

            reconnectTimer = null;

            start();

        }, 3000);

}


function destroyHls() {

    if (!hls)
        return;

    try {

        hls.destroy();

    } catch (e) {}

    hls = null;

}


function createHls() {

    if (!window.Hls)
        return;

    destroyHls();

    hls = new Hls({

        enableWorker: true,

        lowLatencyMode: false,

        backBufferLength: 20,

        maxBufferLength: 30,

        maxMaxBufferLength: 60,

        liveSyncDurationCount: 3,

        liveMaxLatencyDurationCount: 8,

        manifestLoadingMaxRetry: 10,

        manifestLoadingRetryDelay: 1500,

        levelLoadingMaxRetry: 10,

        levelLoadingRetryDelay: 1500,

        fragLoadingMaxRetry: 10,

        fragLoadingRetryDelay: 1500

    });


    hls.loadSource(
        "/live.m3u8"
    );


    hls.attachMedia(video);


    hls.on(
        Hls.Events.MANIFEST_PARSED,
        function() {

            statusText(
                "● AO VIVO"
            );

            video.play().catch(
                function() {}
            );

        }
    );


    hls.on(
        Hls.Events.ERROR,
        function(event, data) {

            if (!data.fatal)
                return;

            statusText(
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

            reconnect();

        }
    );

}


function start() {

    statusText(
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
            function() {}
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
        "https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js";


    script.onload =
        function() {

            if (
                window.Hls &&
                Hls.isSupported()
            ) {

                createHls();

            } else {

                statusText(
                    "HLS não suportado"
                );

            }

        };


    script.onerror =
        function() {

            statusText(
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

        statusText(
            "● AO VIVO"
        );

    }
);


video.addEventListener(
    "waiting",
    function() {

        statusText(
            "Buffering..."
        );

    }
);


video.addEventListener(
    "stalled",
    function() {

        statusText(
            "Buffering..."
        );

    }
);


start();

</script>

</body>

</html>
"""

            self.send_data(
                html.encode("utf-8"),
                "text/html; charset=utf-8"
            )

            return

        # ====================================================
        # HEALTH
        # ====================================================

        if path == "/health":

            self.send_data(
                b"OK\n",
                "text/plain; charset=utf-8"
            )

            return

        # ====================================================
        # HLS
        # ====================================================

        if path == "/live.m3u8":

            playlist =
                STREAM_DIR / "live.m3u8"

            if not playlist.exists():

                self.send_response(503)

                self.headers()

                self.end_headers()

                return

            try:

                data =
                    playlist.read_bytes()

                self.send_data(
                    data,
                    "application/vnd.apple.mpegurl"
                )

            except Exception:

                self.send_response(503)

                self.headers()

                self.end_headers()

            return

        # ====================================================
        # SEGMENTOS
        # ====================================================

        if path.startswith("/segment_"):

            filename =
                os.path.basename(path)

            if not re.fullmatch(
                r"segment_\d+\.ts",
                filename
            ):

                self.send_response(400)

                self.headers()

                self.end_headers()

                return

            file =
                STREAM_DIR / filename

            if not file.exists():

                self.send_response(404)

                self.headers()

                self.end_headers()

                return

            try:

                size =
                    file.stat().st_size

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "video/mp2t"
                )

                self.send_header(
                    "Content-Length",
                    str(size)
                )

                self.headers()

                self.end_headers()

                with open(
                    file,
                    "rb"
                ) as stream:

                    while True:

                        chunk =
                            stream.read(
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

        self.headers()

        self.end_headers()


def start_http():

    global http_server

    sep()

    log(
        "[4] Iniciando servidor HTTP..."
    )

    class Server(
        ThreadingHTTPServer
    ):

        allow_reuse_address = True

        daemon_threads = True


    http_server =
        Server(
            (HOST, PORT),
            StreamHandler
        )


    thread =
        threading.Thread(
            target=http_server.serve_forever,
            daemon=True
        )


    thread.start()


    log(
        f"Servidor HTTP ativo "
        f"na porta {PORT}"
    )


# ============================================================
# CHROMIUM
# ============================================================

def start_chromium():

    global chromium

    sep()

    log(
        "[5] Iniciando Chromium..."
    )

    browser =
        get_chromium()

    if not browser:

        raise RuntimeError(
            "Chromium não encontrado."
        )

    env =
        os.environ.copy()

    env["DISPLAY"] =
        DISPLAY

    env["PULSE_SINK"] =
        "webtv"

    env["PULSE_SOURCE"] =
        "webtv.monitor"

    profile = (
        f"/tmp/webtv-chromium-"
        f"{os.getuid()}"
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

        "--disable-extensions",

        "--disable-sync",

        "--disable-translate",

        "--disable-notifications",

        "--disable-popup-blocking",

        "--autoplay-policy="
        "no-user-gesture-required",

        "--no-first-run",

        "--no-default-browser-check",

        "--disable-background-networking",

        "--disable-background-timer-throttling",

        "--disable-renderer-backgrounding",

        "--disable-backgrounding-occluded-windows",

        "--disable-features="
        "Translate,"
        "BackForwardCache",

        "--kiosk",

        "--start-fullscreen",

        f"--window-size="
        f"{WIDTH},{HEIGHT}",

        f"--user-data-dir="
        f"{profile}",

        PAGE_URL
    ]

    chromium =
        subprocess.Popen(

            command,

            stdout=subprocess.DEVNULL,

            stderr=subprocess.DEVNULL,

            env=env
        )

    time.sleep(6)

    if chromium.poll() is not None:

        raise RuntimeError(
            "Chromium encerrou durante "
            "a inicialização."
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

        result =
            subprocess.run(

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

        windows =
            result.stdout.strip().splitlines()

        if not windows:
            return

        window =
            windows[-1]

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

    playlist =
        STREAM_DIR / "live.m3u8"

    segment_pattern =
        STREAM_DIR / "segment_%06d.ts"

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
        "8",

        "-hls_flags",
        "delete_segments+append_list"
        "+independent_segments"
        "+program_date_time",

        "-hls_delete_threshold",
        "4",

        "-hls_segment_filename",
        str(segment_pattern),

        str(playlist)
    ]

    env =
        pulse_env()

    ffmpeg =
        subprocess.Popen(

            command,

            stdout=subprocess.PIPE,

            stderr=subprocess.STDOUT,

            text=True,

            bufsize=1,

            env=env
        )

    log("FFmpeg iniciado.")

    def output_reader():

        try:

            for line in ffmpeg.stdout:

                line =
                    line.strip()

                if line:

                    log(
                        "[FFMPEG] "
                        + line
                    )

        except Exception:
            pass


    threading.Thread(
        target=output_reader,
        daemon=True
    ).start()


    time.sleep(4)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou durante "
            "a inicialização."
        )

    log("FFmpeg funcionando.")


# ============================================================
# ESPERAR HLS
# ============================================================

def wait_hls():

    sep()

    log(
        "[HLS] Aguardando playlist..."
    )

    playlist =
        STREAM_DIR / "live.m3u8"

    start =
        time.time()

    while (
        time.time() - start < 90
    ):

        if stop_event.is_set():
            return False

        if playlist.exists():

            try:

                content =
                    playlist.read_text(
                        errors="ignore"
                    )

                segments =
                    re.findall(
                        r"segment_\d+\.ts",
                        content
                    )

                files =
                    list(
                        STREAM_DIR.glob(
                            "segment_*.ts"
                        )
                    )

                if (
                    len(segments) >= 2
                    and len(files) >= 2
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
# TESTE HTTP LOCAL
# ============================================================

def local_http_test():

    try:

        response =
            urllib.request.urlopen(
                f"http://{LOCAL_HOST}:{PORT}/health",
                timeout=5
            )

        data =
            response.read().decode(
                "utf-8",
                errors="ignore"
            ).strip()

        return data == "OK"

    except Exception:

        return False


def local_hls_test():

    try:

        response =
            urllib.request.urlopen(
                f"http://{LOCAL_HOST}:{PORT}/live.m3u8",
                timeout=5
            )

        data =
            response.read().decode(
                "utf-8",
                errors="ignore"
            )

        return (
            "#EXTM3U" in data
            and "segment_" in data
        )

    except Exception:

        return False


# ============================================================
# CLOUDFLARE
# ============================================================

def extract_cloudflare_url(text):

    patterns = [

        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com",

        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com/",

    ]

    for pattern in patterns:

        match =
            re.search(
                pattern,
                text
            )

        if match:

            return (
                match.group(0)
                .rstrip("/")
            )

    return None


def start_cloudflare():

    global cloudflared
    global public_url

    executable =
        get_cloudflared()

    if not executable:

        raise RuntimeError(
            "cloudflared não encontrado."
        )

    # --------------------------------------------------------
    # REMOVE CONFIGURAÇÃO QUE PODE BLOQUEAR QUICK TUNNEL
    # --------------------------------------------------------

    cloudflare_dir =
        Path.home() / ".cloudflared"

    config_files = [

        cloudflare_dir / "config.yml",

        cloudflare_dir / "config.yaml",

    ]

    for config in config_files:

        if config.exists():

            backup =
                config.with_suffix(
                    config.suffix
                    + ".webtv-backup"
                )

            try:

                shutil.move(
                    str(config),
                    str(backup)
                )

                log(
                    "[CLOUDFLARE] Configuração "
                    "temporariamente movida:"
                )

                log(str(config))

            except Exception as e:

                log(
                    "[CLOUDFLARE] Não foi possível "
                    "mover configuração:"
                )

                log(str(e))

    sep()

    log(
        "[CLOUDFLARE] Iniciando "
        "Quick Tunnel..."
    )

    log(
        "[CLOUDFLARE] Origem:"
    )

    log(
        f"http://{LOCAL_HOST}:{PORT}"
    )

    try:

        cloudflared =
            subprocess.Popen(

                [
                    executable,

                    "tunnel",

                    "--no-autoupdate",

                    "--url",
                    f"http://{LOCAL_HOST}:{PORT}"
                ],

                stdout=subprocess.PIPE,

                stderr=subprocess.STDOUT,

                stdin=subprocess.DEVNULL,

                text=True,

                bufsize=1
            )

    except Exception as e:

        raise RuntimeError(
            "Erro iniciando cloudflared: "
            + str(e)
        )

    start =
        time.time()

    collected = ""

    while (
        time.time() - start < 60
    ):

        if stop_event.is_set():
            return None

        if cloudflared.poll() is not None:

            raise RuntimeError(
                "cloudflared encerrou "
                "durante a inicialização."
            )

        try:

            line =
                cloudflared.stdout.readline()

        except Exception:
            line = ""

        if line:

            line =
                line.strip()

            if line:

                log(
                    "[CLOUDFLARE] "
                    + line
                )

                collected += (
                    line + "\n"
                )

                url =
                    extract_cloudflare_url(
                        collected
                    )

                if url:

                    public_url =
                        url

                    break

        else:

            time.sleep(0.2)

    if not public_url:

        raise RuntimeError(
            "Cloudflare não forneceu "
            "um endereço trycloudflare.com."
        )

    sep()

    log(
        "[CLOUDFLARE] TÚNEL CRIADO"
    )

    log(
        "LINK WEBTV:"
    )

    log(public_url)

    log("")

    log(
        "LINK HLS:"
    )

    log(
        public_url
        + "/live.m3u8"
    )

    sep()

    return public_url


# ============================================================
# TESTAR TÚNEL
# ============================================================

def public_test(url):

    if not url:
        return False

    # --------------------------------------------------------
    # HEALTH
    # --------------------------------------------------------

    try:

        response =
            urllib.request.urlopen(
                url + "/health",
                timeout=15
            )

        data =
            response.read().decode(
                "utf-8",
                errors="ignore"
            ).strip()

        if data != "OK":

            return False

    except Exception as e:

        log(
            "[CLOUDFLARE] Falha no teste "
            "/health:"
        )

        log(str(e))

        return False

    # --------------------------------------------------------
    # HLS
    # --------------------------------------------------------

    try:

        response =
            urllib.request.urlopen(
                url + "/live.m3u8",
                timeout=15
            )

        data =
            response.read().decode(
                "utf-8",
                errors="ignore"
            )

        if (
            "#EXTM3U" not in data
            or "segment_" not in data
        ):

            return False

    except Exception as e:

        log(
            "[CLOUDFLARE] Falha no teste "
            "/live.m3u8:"
        )

        log(str(e))

        return False

    return True


def wait_public_tunnel():

    sep()

    log(
        "[CLOUDFLARE] Testando link público..."
    )

    for attempt in range(1, 11):

        if stop_event.is_set():
            return False

        log(
            f"[CLOUDFLARE] Teste "
            f"{attempt}/10"
        )

        if public_test(public_url):

            log(
                "[CLOUDFLARE] Link público "
                "respondendo corretamente."
            )

            return True

        time.sleep(3)

    return False


# ============================================================
# MONITOR CLOUDFLARE
# ============================================================

def cloudflare_alive():

    return (
        cloudflared is not None
        and cloudflared.poll() is None
    )


def restart_cloudflare():

    global cloudflared
    global public_url

    stop_process(
        cloudflared,
        "Cloudflare Tunnel"
    )

    cloudflared = None
    public_url = None

    for attempt in range(1, 6):

        if stop_event.is_set():
            return False

        log(
            f"[CLOUDFLARE] Reconexão "
            f"{attempt}/5"
        )

        try:

            url =
                start_cloudflare()

            if url and wait_public_tunnel():

                sep()

                log(
                    "[CLOUDFLARE] Túnel "
                    "reconectado."
                )

                log(
                    "NOVO LINK:"
                )

                log(url)

                log(
                    "NOVO HLS:"
                )

                log(
                    url
                    + "/live.m3u8"
                )

                sep()

                return True

        except Exception as e:

            log(
                "[CLOUDFLARE] Erro:"
            )

            log(str(e))

        time.sleep(
            min(attempt * 3, 15)
        )

    return False


def cloudflare_monitor():

    while not stop_event.is_set():

        time.sleep(10)

        if cloudflare_alive():
            continue

        if stop_event.is_set():
            return

        sep()

        log(
            "[CLOUDFLARE] Túnel caiu."
        )

        log(
            "[CLOUDFLARE] FFmpeg continua "
            "funcionando."
        )

        log(
            "[CLOUDFLARE] Tentando "
            "reconectar..."
        )

        sep()

        restart_cloudflare()


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

    playlist =
        STREAM_DIR / "live.m3u8"

    last_mtime = 0

    while not stop_event.is_set():

        time.sleep(10)

        if not playlist.exists():

            log(
                "[HLS] ALERTA: playlist "
                "ausente."
            )

            continue

        try:

            mtime =
                playlist.stat().st_mtime_ns

        except Exception:
            continue

        if (
            last_mtime != 0
            and mtime == last_mtime
        ):

            log(
                "[HLS] ALERTA: playlist "
                "não atualizou."
            )

        last_mtime = mtime


# ============================================================
# MONITOR CHROMIUM
# ============================================================

def chromium_monitor():

    global chromium

    while not stop_event.is_set():

        time.sleep(10)

        if chromium is None:
            continue

        if chromium.poll() is not None:

            sep()

            log(
                "[CHROMIUM] Navegador encerrou."
            )

            log(
                "[CHROMIUM] Reiniciando..."
            )

            try:

                start_chromium()

                time.sleep(4)

                fullscreen()

            except Exception as e:

                log(
                    "[CHROMIUM] Erro:"
                )

                log(str(e))


# ============================================================
# MAIN
# ============================================================

def main():

    sep()

    log(
        "WEBTV STREAM + CLOUDFLARE"
    )

    sep()

    # --------------------------------------------------------
    # VERIFICA
    # --------------------------------------------------------

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

    if not local_http_test():

        raise RuntimeError(
            "Servidor HTTP não respondeu."
        )

    log(
        "[HTTP] Servidor local funcionando."
    )

    # --------------------------------------------------------
    # 5
    # --------------------------------------------------------

    start_chromium()

    time.sleep(5)

    fullscreen()

    time.sleep(3)

    # --------------------------------------------------------
    # 6
    # --------------------------------------------------------

    start_ffmpeg()

    # --------------------------------------------------------
    # 7
    # --------------------------------------------------------

    if not wait_hls():

        raise RuntimeError(
            "HLS não foi criado."
        )

    # --------------------------------------------------------
    # TESTE LOCAL
    # --------------------------------------------------------

    if not local_hls_test():

        raise RuntimeError(
            "HLS local não está respondendo."
        )

    log(
        "[HLS] HLS local funcionando."
    )

    # --------------------------------------------------------
    # 8 CLOUDFLARE
    # --------------------------------------------------------

    url =
        start_cloudflare()

    if not url:

        raise RuntimeError(
            "Cloudflare não criou o túnel."
        )

    # --------------------------------------------------------
    # TESTE PÚBLICO
    # --------------------------------------------------------

    if not wait_public_tunnel():

        raise RuntimeError(
            "O link Cloudflare foi criado, "
            "mas não está respondendo."
        )

    # --------------------------------------------------------
    # TRANSMISSÃO ATIVA
    # --------------------------------------------------------

    sep()

    log(
        "TRANSMISSÃO ATIVA"
    )

    sep()

    log(
        "HTTP LOCAL:"
    )

    log(
        f"http://{LOCAL_HOST}:{PORT}/"
    )

    log("")

    log(
        "HLS LOCAL:"
    )

    log(
        f"http://{LOCAL_HOST}:{PORT}/live.m3u8"
    )

    log("")

    log(
        "LINK PÚBLICO:"
    )

    log(public_url)

    log("")

    log(
        "LINK HLS PÚBLICO:"
    )

    log(
        public_url
        + "/live.m3u8"
    )

    sep()

    # --------------------------------------------------------
    # MONITORES
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # EXECUÇÃO
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

        log(str(e))

        sep()

    finally:

        cleanup()
