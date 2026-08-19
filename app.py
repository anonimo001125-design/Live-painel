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

BASE_DIR = Path(__file__).resolve().parent
STREAM_DIR = BASE_DIR / "stream"

CLOUDFLARED = os.environ.get(
    "CLOUDFLARED_BIN",
    "cloudflared"
)

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
# COMANDOS
# ============================================================

def command_exists(name):

    return shutil.which(name) is not None


def check_programs():

    programs = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
    ]

    missing = []

    for program in programs:

        if not command_exists(program):
            missing.append(program)

    chromium_found = False

    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):

        if command_exists(name):
            chromium_found = True
            break

    if not chromium_found:
        missing.append("chromium")

    if not command_exists(CLOUDFLARED):
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
                f"[STREAM] Falha removendo "
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
                "Xvfb encerrou."
            )

        time.sleep(0.2)

    log("Xvfb pronto.")


# ============================================================
# PULSEAUDIO
# ============================================================

def pulse_env():

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    runtime = Path(
        "/tmp",
        f"pulse-webtv-{os.getuid()}"
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


def find_webtv_sink():

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


def find_webtv_monitor():

    result = pactl_command(
        ["list", "short", "sources"]
    )

    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():

        parts = line.split()

        if len(parts) >= 2 and parts[1] == "webtv.monitor":
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

    # --------------------------------------------------------
    # CRIA O SINK
    # --------------------------------------------------------

    if not find_webtv_sink():

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
                "Falha criando sink webtv: "
                + result.stderr.strip()
            )

    sink_ok = False

    for _ in range(20):

        if find_webtv_sink():

            sink_ok = True
            break

        time.sleep(0.5)

    if not sink_ok:

        raise RuntimeError(
            "Sink webtv não foi criado."
        )

    # --------------------------------------------------------
    # SINK PADRÃO
    # --------------------------------------------------------

    result = pactl_command(
        ["set-default-sink", "webtv"]
    )

    if result.returncode != 0:

        log(
            "[ÁUDIO] Aviso ao definir sink padrão: "
            + result.stderr.strip()
        )

    # --------------------------------------------------------
    # MONITOR
    # --------------------------------------------------------

    monitor_ok = False

    for _ in range(20):

        if find_webtv_monitor():

            monitor_ok = True
            break

        time.sleep(0.5)

    if not monitor_ok:

        raise RuntimeError(
            "webtv.monitor não foi criado."
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

    def log_message(self, fmt, *args):
        pass

    def common_headers(self):

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

        self.common_headers()

        self.end_headers()

        try:
            self.wfile.write(data)
        except Exception:
            pass

    def do_GET(self):

        path = self.path.split("?", 1)[0]

        # ----------------------------------------------------
        # PLAYER
        # ----------------------------------------------------

        if path in ("/", "/index.html"):

            html = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>WEBTV AO VIVO</title>

<style>
html,body{
    margin:0;
    width:100%;
    height:100%;
    background:#000;
    overflow:hidden;
}

video{
    width:100%;
    height:100%;
    object-fit:contain;
    background:#000;
}

#status{
    position:fixed;
    top:12px;
    left:12px;
    z-index:10;
    padding:8px 12px;
    color:#fff;
    background:rgba(0,0,0,.75);
    border-radius:5px;
    font:14px Arial,sans-serif;
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


function setStatus(text){
    status.textContent = text;
}


function retry(){

    if(retryTimer)
        return;

    retryTimer = setTimeout(() => {

        retryTimer = null;

        start();

    }, 3000);
}


function startHLS(){

    if(!window.Hls)
        return;

    if(hls){

        try{
            hls.destroy();
        }catch(e){}

    }

    hls = new Hls({
        enableWorker:true,
        lowLatencyMode:false,

        backBufferLength:30,
        maxBufferLength:30,

        liveSyncDurationCount:3,
        liveMaxLatencyDurationCount:8,

        manifestLoadingMaxRetry:30,
        manifestLoadingRetryDelay:1000,

        levelLoadingMaxRetry:30,
        levelLoadingRetryDelay:1000,

        fragLoadingMaxRetry:30,
        fragLoadingRetryDelay:1000
    });

    hls.loadSource("/live.m3u8");

    hls.attachMedia(video);

    hls.on(
        Hls.Events.MANIFEST_PARSED,
        () => {

            setStatus("● AO VIVO");

            video.play().catch(
                () => {}
            );
        }
    );

    hls.on(
        Hls.Events.ERROR,
        (event,data) => {

            if(!data.fatal)
                return;

            setStatus("Reconectando...");

            if(
                data.type ===
                Hls.ErrorTypes.NETWORK_ERROR
            ){

                try{
                    hls.startLoad();
                }catch(e){}

                return;
            }

            if(
                data.type ===
                Hls.ErrorTypes.MEDIA_ERROR
            ){

                try{
                    hls.recoverMediaError();
                }catch(e){}

                return;
            }

            try{
                hls.destroy();
            }catch(e){}

            hls = null;

            retry();
        }
    );
}


function start(){

    if(
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ){

        video.src =
            "/live.m3u8";

        video.play().catch(
            () => {}
        );

        setStatus("● AO VIVO");

        return;
    }

    if(
        window.Hls &&
        Hls.isSupported()
    ){

        startHLS();

        return;
    }

    const script =
        document.createElement("script");

    script.src =
        "https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js";

    script.onload = () => {

        if(
            window.Hls &&
            Hls.isSupported()
        ){

            startHLS();

        }else{

            setStatus(
                "HLS não suportado"
            );

        }
    };

    script.onerror = () => {

        setStatus(
            "Erro carregando player"
        );

        retry();
    };

    document.head.appendChild(script);
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
    () => setStatus("Buffering...")
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

        # ----------------------------------------------------
        # HLS
        # ----------------------------------------------------

        if path == "/live.m3u8":

            playlist = STREAM_DIR / "live.m3u8"

            if not playlist.exists():

                self.send_response(503)
                self.common_headers()
                self.end_headers()

                return

            try:
                data = playlist.read_bytes()
            except Exception:

                self.send_response(503)
                self.common_headers()
                self.end_headers()

                return

            self.send_data(
                data,
                "application/vnd.apple.mpegurl"
            )

            return

        # ----------------------------------------------------
        # TS
        # ----------------------------------------------------

        if path.startswith("/segment_"):

            filename = os.path.basename(path)

            if not re.fullmatch(
                r"segment_\d+\.ts",
                filename
            ):

                self.send_response(400)
                self.common_headers()
                self.end_headers()

                return

            file = STREAM_DIR / filename

            if not file.exists():

                self.send_response(404)
                self.common_headers()
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

                self.common_headers()

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

        # ----------------------------------------------------
        # HEALTH
        # ----------------------------------------------------

        if path == "/health":

            self.send_data(
                b"OK\n",
                "text/plain; charset=utf-8"
            )

            return

        self.send_response(404)
        self.common_headers()
        self.end_headers()


def start_http():

    global http_server

    sep()
    log("[4] Iniciando servidor HTTP...")

    class Server(ThreadingHTTPServer):

        allow_reuse_address = True
        daemon_threads = True

    http_server = Server(
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

    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):

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

    env["PULSE_SINK"] = "webtv"
    env["PULSE_SOURCE"] = "webtv.monitor"

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

        "--no-first-run",
        "--no-default-browser-check",

        "--disable-extensions",
        "--disable-sync",
        "--disable-translate",
        "--disable-notifications",

        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",

        "--disable-popup-blocking",

        "--autoplay-policy=no-user-gesture-required",

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
        env=env,
    )

    time.sleep(6)

    if chromium.poll() is not None:

        raise RuntimeError(
            "Chromium encerrou durante inicialização."
        )

    log("Chromium iniciado.")
    log("Abrindo página:")
    log(PAGE_URL)


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

        "-hide_banner",
        "-loglevel", "warning",
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
        # VÍDEO
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
        "1400k",

        "-maxrate",
        "1600k",

        "-bufsize",
        "3200k",

        # ----------------------------------------------------
        # ÁUDIO
        # ----------------------------------------------------

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
            "segment_%06d.ts"
        ),

        str(playlist),
    ]

    ffmpeg = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=pulse_env(),
    )

    def reader():

        try:

            for line in ffmpeg.stderr:

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
            "FFmpeg encerrou durante inicialização."
        )

    log("FFmpeg funcionando.")


# ============================================================
# HLS
# ============================================================

def wait_hls():

    sep()
    log("[HLS] Aguardando playlist...")

    playlist = STREAM_DIR / "live.m3u8"

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

                log("[HLS] Playlist pronta.")

                return True

        time.sleep(1)

    return False


# ============================================================
# CLOUDFLARE
# ============================================================

def start_cloudflare():

    global cloudflared
    global tunnel_url

    sep()
    log("[CLOUDFLARE] Iniciando túnel...")

    try:

        cloudflared = subprocess.Popen(
            [
                CLOUDFLARED,
                "tunnel",
                "--no-autoupdate",
                "--url",
                f"http://127.0.0.1:{PORT}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    except Exception as e:

        log(
            "[CLOUDFLARE] Falha iniciando:"
        )

        log(str(e))

        cloudflared = None

        return None

    deadline = time.time() + 60

    pattern = re.compile(
        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com"
    )

    while time.time() < deadline:

        if cloudflared.poll() is not None:

            log(
                "[CLOUDFLARE] Processo encerrou."
            )

            return None

        line = cloudflared.stdout.readline()

        if line:

            line = line.strip()

            log(
                "[CLOUDFLARE] "
                + line
            )

            match = pattern.search(line)

            if match:

                tunnel_url = match.group(0)

                sep()

                log(
                    "LINK PÚBLICO:"
                )

                log(tunnel_url)

                log("")

                log(
                    "LINK HLS:"
                )

                log(
                    tunnel_url
                    + "/live.m3u8"
                )

                sep()

                return tunnel_url

        else:

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
    global tunnel_url

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
            "[CLOUDFLARE] FFmpeg continua."
        )

        log(
            "[CLOUDFLARE] Tentando reconectar..."
        )

        tunnel_url = None

        time.sleep(3)

        start_cloudflare()


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
                "[HLS] Playlist desapareceu."
            )

            continue

        try:

            current = (
                playlist.stat().st_mtime_ns
            )

        except Exception:
            continue

        if previous and current == previous:

            log(
                "[HLS] Playlist não atualizou."
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

        if chromium.poll() is not None:

            log(
                "[CHROMIUM] Navegador encerrou."
            )

            try:

                start_chromium()

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

    check_programs()

    clean_stream()

    start_xvfb()

    start_pulseaudio()

    start_http()

    start_chromium()

    time.sleep(5)

    start_ffmpeg()

    if not wait_hls():

        raise RuntimeError(
            "HLS não foi criado."
        )

    # --------------------------------------------------------
    # CLOUDFLARE
    # --------------------------------------------------------

    start_cloudflare()

    # --------------------------------------------------------
    # ATIVA
    # --------------------------------------------------------

    sep()
    log("TRANSMISSÃO ATIVA")
    sep()

    log(
        f"HTTP LOCAL: http://127.0.0.1:{PORT}/"
    )

    log(
        f"HLS LOCAL: http://127.0.0.1:{PORT}/live.m3u8"
    )

    if tunnel_url:

        log("")
        log("LINK PÚBLICO:")
        log(tunnel_url)

        log("")
        log("LINK HLS:")
        log(
            tunnel_url
            + "/live.m3u8"
        )

    else:

        log(
            "[AVISO] Cloudflare não forneceu URL."
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
        log("[ERRO FATAL]")
        log(str(e))
        sep()

    finally:

        cleanup()
