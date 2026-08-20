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
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n3"
    "-102718744012.us-east5.run.app/watch"
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

    log("WEBTV FINALIZADA")


def signal_handler(signum, frame):

    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============================================================
# DEPENDÊNCIAS
# ============================================================

def find_program(names):

    for name in names:

        path = shutil.which(name)

        if path:
            return path

    return None


def check_programs():

    sep()
    log("VERIFICANDO DEPENDÊNCIAS")

    required = {
        "Xvfb": ["Xvfb"],
        "PulseAudio": ["pulseaudio"],
        "pactl": ["pactl"],
        "FFmpeg": ["ffmpeg"],
        "Chromium": [
            "chromium",
            "chromium-browser",
            "google-chrome",
            "google-chrome-stable",
        ],
        "Cloudflare": ["cloudflared"],
    }

    missing = []

    for label, names in required.items():

        if not find_program(names):

            missing.append(label)

        else:

            path = find_program(names)

            log(
                f"[OK] {label}: {path}"
            )

    if missing:

        raise RuntimeError(
            "Programas ausentes: "
            + ", ".join(missing)
        )

    log("Todas as dependências estão disponíveis.")


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
                f"[AVISO] Não foi possível remover "
                f"{item}: {e}"
            )


# ============================================================
# XVFB
# ============================================================

def start_xvfb():

    global xvfb

    sep()

    log("[2] Iniciando Xvfb...")
    log(
        f"DISPLAY={DISPLAY} "
        f"{WIDTH}x{HEIGHT}"
    )

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


def pactl(args):

    return subprocess.run(
        ["pactl"] + args,
        capture_output=True,
        text=True,
        env=pulse_env(),
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
        env=env,
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
        env=env,
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

    sinks = pactl(
        ["list", "short", "sinks"]
    )

    exists = False

    for item in sinks.stdout.splitlines():

        parts = item.split()

        if len(parts) >= 2:

            if parts[1] == "webtv":

                exists = True
                break

    if not exists:

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

    pactl(
        ["set-default-sink", "webtv"]
    )

    monitor_ok = False

    for _ in range(20):

        sources = pactl(
            ["list", "short", "sources"]
        )

        for item in sources.stdout.splitlines():

            parts = item.split()

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
    log(sources.stdout.strip())

    log("Sink webtv criado com sucesso.")
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

        path = self.path.split(
            "?",
            1
        )[0]

        # ====================================================
        # PLAYER
        # ====================================================

        if path in ["/", "/index.html"]:

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

    top: 10px;
    left: 10px;

    z-index: 10;

    padding: 8px 12px;

    background:
        rgba(0,0,0,.75);

    color: #fff;

    font-family:
        Arial,
        sans-serif;

    border-radius: 5px;
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

        enableWorker: true,

        lowLatencyMode: false,

        backBufferLength: 10,

        maxBufferLength: 20,

        maxMaxBufferLength: 40,

        liveSyncDurationCount: 3,

        liveMaxLatencyDurationCount: 8,

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

    hls.attachMedia(video);


    hls.on(
        Hls.Events.MANIFEST_PARSED,
        function() {

            setStatus("● AO VIVO");

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
            function() {}
        );

        setStatus("● AO VIVO");

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


    script.onload =
        function() {

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


    script.onerror =
        function() {

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

        setStatus("Buffering...");
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
        # PLAYLIST
        # ====================================================

        if path == "/live.m3u8":

            file = (
                STREAM_DIR
                / "live.m3u8"
            )

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

            self.send_data(
                data,
                "application/vnd.apple.mpegurl"
            )

            return


        # ====================================================
        # SEGMENTOS
        # ====================================================

        if path.startswith(
            "/segment_"
        ):

            filename = os.path.basename(
                path
            )

            if not re.fullmatch(
                r"segment_\d+\.ts",
                filename
            ):

                self.send_response(400)
                self.headers()
                self.end_headers()

                return

            file = (
                STREAM_DIR
                / filename
            )

            if not file.exists():

                self.send_response(404)
                self.headers()
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

                self.headers()

                self.end_headers()

                with open(
                    file,
                    "rb"
                ) as stream:

                    while True:

                        chunk = stream.read(
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


        self.send_response(404)
        self.headers()
        self.end_headers()


def start_http():

    global http_server

    sep()
    log("[4] Iniciando servidor HTTP...")

    class ReusableServer(
        ThreadingHTTPServer
    ):

        allow_reuse_address = True
        daemon_threads = True


    http_server = ReusableServer(
        (HOST, PORT),
        StreamHandler
    )


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

def get_chromium():

    path = find_program(
        [
            "chromium",
            "chromium-browser",
            "google-chrome",
            "google-chrome-stable",
        ]
    )

    if not path:

        raise RuntimeError(
            "Chromium não encontrado."
        )

    return path


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

        "--disable-notifications",

        "--disable-popup-blocking",

        "--autoplay-policy=no-user-gesture-required",

        "--no-first-run",

        "--no-default-browser-check",

        "--disable-features=Translate,BackForwardCache",

        "--kiosk",

        "--start-fullscreen",

        f"--window-size={WIDTH},{HEIGHT}",

        f"--user-data-dir={profile}",

        PAGE_URL,
    ]


    log("Abrindo página:")
    log(PAGE_URL)


    chromium = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env
    )


    for _ in range(30):

        if chromium.poll() is not None:

            raise RuntimeError(
                "Chromium encerrou durante a inicialização."
            )

        time.sleep(0.2)


    log("Chromium iniciado.")


# ============================================================
# FULLSCREEN
# ============================================================

def fullscreen():

    if not shutil.which(
        "xdotool"
    ):

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

    sep()
    log("[6] INICIANDO FFMPEG")

    playlist = (
        STREAM_DIR
        / "live.m3u8"
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
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_delete_threshold",
        "3",

        "-hls_segment_filename",

        str(
            STREAM_DIR
            / "segment_%06d.ts"
        ),

        str(playlist),
    ]


    env = pulse_env()
    env["DISPLAY"] = DISPLAY


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

            for text in ffmpeg.stdout:

                text = text.strip()

                if text:

                    log(
                        "[FFMPEG] "
                        + text
                    )

        except Exception:
            pass


    threading.Thread(
        target=reader,
        daemon=True
    ).start()


    time.sleep(3)


    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou durante a inicialização."
        )


    log("FFmpeg funcionando.")


# ============================================================
# HLS
# ============================================================

def wait_hls():

    sep()
    log("[HLS] Aguardando playlist...")

    playlist = (
        STREAM_DIR
        / "live.m3u8"
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
# CLOUDFLARE QUICK TUNNEL
# ============================================================

def extract_cloudflare_url(text):

    patterns = [

        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com",

        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com/"
    ]


    for pattern in patterns:

        match = re.search(
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
    global tunnel_url

    sep()

    log(
        "[7] Iniciando Cloudflare Quick Tunnel..."
    )


    if cloudflared is not None:

        stop_process(
            cloudflared,
            "Cloudflare Tunnel"
        )

        cloudflared = None


    executable = find_program(
        ["cloudflared"]
    )


    if not executable:

        raise RuntimeError(
            "cloudflared não está instalado."
        )


    env = os.environ.copy()


    command = [

        executable,

        "tunnel",

        "--no-autoupdate",

        "--url",

        f"http://127.0.0.1:{PORT}",
    ]


    cloudflared = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=env
    )


    start = time.time()

    while time.time() - start < 60:

        if stop_event.is_set():
            return None


        if cloudflared.poll() is not None:

            raise RuntimeError(
                "Cloudflare Tunnel encerrou."
            )


        line_text = (
            cloudflared.stdout.readline()
        )


        if not line_text:

            time.sleep(0.2)
            continue


        line_text = line_text.strip()


        if line_text:

            log(
                "[CLOUDFLARE] "
                + line_text
            )


        found = extract_cloudflare_url(
            line_text
        )


        if found:

            tunnel_url = found

            sep()

            log(
                "LINK PÚBLICO DA TRANSMISSÃO"
            )

            sep()

            log(
                tunnel_url
            )

            log("")

            log(
                "PLAYER:"
            )

            log(
                tunnel_url
                + "/"
            )

            log("")

            log(
                "HLS:"
            )

            log(
                tunnel_url
                + "/live.m3u8"
            )

            sep()

            return tunnel_url


    raise RuntimeError(
        "Cloudflare não forneceu um endereço público."
    )


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


        if stop_event.is_set():
            return


        sep()

        log(
            "[CLOUDFLARE] Túnel desconectado."
        )

        log(
            "[CLOUDFLARE] Reiniciando..."
        )

        sep()


        cloudflared = None


        for attempt in range(1, 6):

            if stop_event.is_set():
                return


            try:

                log(
                    f"[CLOUDFLARE] "
                    f"Tentativa {attempt}/5"
                )


                url = start_cloudflare()


                if url:

                    log(
                        "[CLOUDFLARE] "
                        "Túnel reconectado."
                    )

                    break


            except Exception as e:

                log(
                    "[CLOUDFLARE] Erro: "
                    + str(e)
                )


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
                "[ERRO] FFmpeg parou."
            )

            log(
                "[ERRO] A transmissão foi encerrada."
            )

            stop_event.set()

            return


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


        if stop_event.is_set():
            return


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
                "[CHROMIUM] Falha: "
                + str(e)
            )


# ============================================================
# MONITOR HLS
# ============================================================

def hls_monitor():

    playlist = (
        STREAM_DIR
        / "live.m3u8"
    )

    previous_mtime = 0

    while not stop_event.is_set():

        time.sleep(10)

        if not playlist.exists():

            log(
                "[HLS] ALERTA: playlist ausente."
            )

            continue


        try:

            current = (
                playlist.stat()
                .st_mtime_ns
            )

        except Exception:
            continue


        if (
            previous_mtime
            and current == previous_mtime
        ):

            log(
                "[HLS] ALERTA: playlist "
                "não está atualizando."
            )


        previous_mtime = current


# ============================================================
# MAIN
# ============================================================

def main():

    sep()

    log("INICIANDO WEBTV")

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


    time.sleep(5)


    fullscreen()


    time.sleep(2)


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
    # 8
    # --------------------------------------------------------

    start_cloudflare()


    # --------------------------------------------------------
    # ATIVO
    # --------------------------------------------------------

    sep()

    log("TRANSMISSÃO ATIVA")

    sep()


    log(
        f"HTTP LOCAL: "
        f"http://127.0.0.1:{PORT}/"
    )


    log(
        f"HLS LOCAL: "
        f"http://127.0.0.1:{PORT}/live.m3u8"
    )


    if tunnel_url:

        log("")

        log(
            "LINK PÚBLICO:"
        )

        log(
            tunnel_url
        )

        log("")

        log(
            "LINK HLS:"
        )

        log(
            tunnel_url
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
        target=chromium_monitor,
        daemon=True
    ).start()


    threading.Thread(
        target=hls_monitor,
        daemon=True
    ).start()


    # --------------------------------------------------------
    # LOOP
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
