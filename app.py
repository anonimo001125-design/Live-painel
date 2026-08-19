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

# Reinicia preventivamente antes de 5 horas.
MAX_RUNTIME = 4 * 60 * 60 + 50 * 60

stop_event = threading.Event()

xvfb = None
pulse = None
chromium = None
ffmpeg = None
http_server = None

process_lock = threading.Lock()


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


def get_chromium():
    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):
        path = shutil.which(name)

        if path:
            return path

    return None


def check_programs():
    required = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
    ]

    missing = []

    for program in required:
        if not command_exists(program):
            missing.append(program)

    if get_chromium() is None:
        missing.append("chromium")

    if not command_exists("curl"):
        log("[AVISO] curl não encontrado.")
        log("[AVISO] Não é obrigatório para o HLS.")

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
            log(f"[STREAM] Erro removendo {item}: {e}")


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

        if len(parts) >= 2 and parts[1] == "webtv":
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

        if (
            len(parts) >= 2
            and parts[1] == "webtv.monitor"
        ):
            return True

    return False


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
            "--system=false",
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

    if not sink_exists():
        log("[ÁUDIO] Criando sink webtv...")

        result = pactl_command(
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
                "Não foi possível criar o sink webtv: "
                + result.stderr.strip()
            )

    for _ in range(20):
        if sink_exists():
            break

        time.sleep(0.5)

    if not sink_exists():
        raise RuntimeError(
            "Sink webtv não apareceu."
        )

    pactl_command(
        ["set-default-sink", "webtv"]
    )

    for _ in range(20):
        if monitor_exists():
            break

        time.sleep(0.5)

    if not monitor_exists():
        raise RuntimeError(
            "Monitor webtv.monitor não apareceu."
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
        except Exception:
            pass

    def do_GET(self):

        path = self.path.split("?", 1)[0]

        # ====================================================
        # PLAYER
        # ====================================================

        if path in ("/", "/index.html"):

            html = """<!DOCTYPE html>
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
    top: 10px;
    left: 10px;
    z-index: 100;
    color: white;
    background: rgba(0,0,0,.7);
    padding: 8px 12px;
    border-radius: 5px;
    font-family: Arial,sans-serif;
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
let timer = null;


function setStatus(text) {
    status.textContent = text;
}


function reconnect() {

    if (timer)
        return;

    timer = setTimeout(
        function() {

            timer = null;
            start();

        },
        2000
    );
}


function startHls() {

    if (!window.Hls)
        return;

    try {

        if (hls)
            hls.destroy();

    } catch(e) {}

    hls = new Hls({

        enableWorker: true,

        lowLatencyMode: false,

        backBufferLength: 30,

        maxBufferLength: 30,

        maxMaxBufferLength: 60,

        liveSyncDurationCount: 3,

        liveMaxLatencyDurationCount: 10,

        manifestLoadingMaxRetry: 20,

        manifestLoadingRetryDelay: 1000,

        levelLoadingMaxRetry: 20,

        levelLoadingRetryDelay: 1000,

        fragLoadingMaxRetry: 20,

        fragLoadingRetryDelay: 1000

    });

    hls.loadSource("/live.m3u8");

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
        function(event,data) {

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

        video.src = "/live.m3u8";

        video.play().catch(
            function(){}
        );

        setStatus("● AO VIVO");

        return;
    }

    if (
        window.Hls &&
        Hls.isSupported()
    ) {

        startHls();
        return;

    }

    const script =
    document.createElement("script");

    script.src =
    "https://cdn.jsdelivr.net/npm/hls.js@latest";

    script.onload =
    function() {

        if (
            window.Hls &&
            Hls.isSupported()
        ) {

            startHls();

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

            self.send_data(
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
        # HEALTH
        # ====================================================

        if path == "/health":

            self.send_data(
                b"OK\n",
                "text/plain; charset=utf-8"
            )

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

    log(
        f"Servidor HTTP ativo na porta {PORT}"
    )


# ============================================================
# CHROMIUM
# ============================================================

def start_chromium():

    global chromium

    sep()
    log("[5] Iniciando Chromium...")

    browser = get_chromium()

    if not browser:
        raise RuntimeError(
            "Chromium não encontrado."
        )

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    profile = (
        Path("/tmp")
        / f"webtv-chromium-{os.getuid()}"
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

        "--kiosk",

        "--start-fullscreen",

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

    time.sleep(6)

    if chromium.poll() is not None:
        raise RuntimeError(
            "Chromium encerrou."
        )

    log("Chromium iniciado.")
    log("Abrindo página:")
    log(PAGE_URL)


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

    playlist = (
        STREAM_DIR / "live.m3u8"
    )

    command = [

        "ffmpeg",

        "-hide_banner",

        "-loglevel",
        "warning",

        "-nostdin",

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

        "-probesize",
        "32M",

        "-analyzeduration",
        "2M",

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

    def output_reader():

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
        target=output_reader,
        daemon=True
    ).start()

    time.sleep(5)

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
        STREAM_DIR / "live.m3u8"
    )

    deadline = time.time() + 60

    while time.time() < deadline:

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
# REINÍCIO DOS COMPONENTES
# ============================================================

def restart_chromium():

    global chromium

    log("[WATCHDOG] Reiniciando Chromium...")

    stop_process(
        chromium,
        "Chromium"
    )

    chromium = None

    try:

        start_chromium()

        time.sleep(3)

        fullscreen()

    except Exception as e:

        log(
            "[WATCHDOG] Erro no Chromium: "
            + str(e)
        )


def restart_ffmpeg():

    global ffmpeg

    log("[WATCHDOG] Reiniciando FFmpeg...")

    stop_process(
        ffmpeg,
        "FFmpeg"
    )

    ffmpeg = None

    try:

        start_ffmpeg()

        wait_hls()

    except Exception as e:

        log(
            "[WATCHDOG] Erro no FFmpeg: "
            + str(e)
        )


# ============================================================
# WATCHDOG
# ============================================================

def watchdog():

    playlist = (
        STREAM_DIR / "live.m3u8"
    )

    while not stop_event.is_set():

        time.sleep(15)

        # ----------------------------------------------------
        # Chromium
        # ----------------------------------------------------

        if chromium is not None:

            if chromium.poll() is not None:

                restart_chromium()

        # ----------------------------------------------------
        # FFmpeg
        # ----------------------------------------------------

        if ffmpeg is not None:

            if ffmpeg.poll() is not None:

                restart_ffmpeg()

        # ----------------------------------------------------
        # HLS
        # ----------------------------------------------------

        if playlist.exists():

            try:

                age = (
                    time.time()
                    - playlist.stat().st_mtime
                )

                if age > 30:

                    log(
                        "[WATCHDOG] HLS parado."
                    )

                    restart_ffmpeg()

            except Exception:
                pass


# ============================================================
# MAIN
# ============================================================

def main():

    sep()
    log("WEBTV STREAM")
    log("MODO SEM NGROK")
    sep()

    check_programs()

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

    log("")
    log(
        "O app não utiliza ngrok."
    )

    log(
        "O ambiente externo é responsável "
        "por expor a porta 8080."
    )

    sep()

    threading.Thread(
        target=watchdog,
        daemon=True
    ).start()

    start_time = time.time()

    while not stop_event.is_set():

        elapsed = (
            time.time() - start_time
        )

        # ----------------------------------------------------
        # Reinício preventivo.
        # ----------------------------------------------------

        if elapsed >= MAX_RUNTIME:

            sep()

            log(
                "[RESTART] Tempo máximo atingido."
            )

            log(
                "[RESTART] Encerrando ciclo."
            )

            sep()

            return 0

        time.sleep(10)

    return 0


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    try:

        result = main()

        cleanup()

        sys.exit(result)

    except KeyboardInterrupt:

        cleanup()

    except Exception as e:

        sep()
        log("[ERRO FATAL]")
        log(str(e))
        sep()

        cleanup()

        sys.exit(1)
