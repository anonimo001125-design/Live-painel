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
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

# ============================================================
# CONFIGURAÇÃO
# ============================================================

HOST = "0.0.0.0"
PORT = 8080

DISPLAY = ":99"
WIDTH = 1280
HEIGHT = 720
FPS = 30

STREAM_DIR = Path("stream")
STREAM_DIR.mkdir(parents=True, exist_ok=True)

PAGE_URL = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n3-102718744012"
    ".us-east5.run.app/watch"
)

# ============================================================
# PROCESSOS
# ============================================================

xvfb = None
pulse = None
chromium = None
ffmpeg = None
cloudflared = None
http_server = None

stop_event = threading.Event()

tunnel_url = None
tunnel_lock = threading.Lock()


# ============================================================
# LOG
# ============================================================

def log(text=""):
    print(text, flush=True)


def line():
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

    except Exception as e:
        log(f"[STOP] Erro ao parar {name}: {e}")


def cleanup():
    global http_server

    if stop_event.is_set():
        pass

    stop_event.set()

    line()
    log("ENCERRANDO WEBTV")

    stop_process(cloudflared, "Cloudflare Tunnel")
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

    log("WEBTV FINALIZADA")


def signal_handler(signum, frame):
    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============================================================
# DEPENDÊNCIAS
# ============================================================

def command_exists(name):
    return shutil.which(name) is not None


def check_dependencies():
    line()
    log("VERIFICANDO DEPENDÊNCIAS")

    required = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
        "chromium",
        "cloudflared",
    ]

    missing = []

    for command in required:
        if not command_exists(command):
            missing.append(command)

    if missing:
        raise RuntimeError(
            "Programas ausentes: " + ", ".join(missing)
        )

    log("Todas as dependências estão instaladas.")


# ============================================================
# LIMPAR STREAM
# ============================================================

def clean_stream():
    line()
    log("[1] Limpando arquivos antigos...")

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
            log(f"[AVISO] Não foi possível remover {item}: {e}")


# ============================================================
# XVFB
# ============================================================

def start_xvfb():
    global xvfb

    line()
    log("[2] INICIANDO XVFB")

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
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    time.sleep(2)

    if xvfb.poll() is not None:
        error = ""

        try:
            error = xvfb.stderr.read()
        except Exception:
            pass

        raise RuntimeError(
            "Xvfb não iniciou.\n" + error
        )

    log("Xvfb funcionando.")


# ============================================================
# PULSEAUDIO
# ============================================================

def start_pulseaudio():
    global pulse

    line()
    log("[3] INICIANDO PULSEAUDIO")

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["PULSE_SINK"] = "webtv"

    subprocess.run(
        ["pulseaudio", "--kill"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(1)

    pulse = subprocess.Popen(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    time.sleep(3)

    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        capture_output=True,
        text=True,
    )

    if "webtv" not in sinks.stdout:
        result = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Não foi possível criar o sink webtv: "
                + result.stderr
            )

    time.sleep(2)

    monitor = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources",
        ],
        capture_output=True,
        text=True,
    )

    log("Fontes PulseAudio:")

    if monitor.stdout.strip():
        log(monitor.stdout.strip())

    if "webtv.monitor" not in monitor.stdout:
        raise RuntimeError(
            "webtv.monitor não foi criado."
        )

    log("webtv.monitor encontrado.")
    log("Áudio pronto.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

class StreamHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            directory=str(STREAM_DIR),
            **kwargs
        )

    def log_message(self, format, *args):
        log("[HTTP] " + (format % args))

    def end_headers(self):
        self.send_header(
            "Cache-Control",
            "no-cache, no-store, must-revalidate"
        )

        self.send_header(
            "Pragma",
            "no-cache"
        )

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
            "GET, OPTIONS"
        )

        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):

        path = self.path.split("?", 1)[0]

        # ====================================================
        # PLAYER
        # ====================================================

        if path == "/":

            html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">
<title>WebTV</title>

<style>
html,body {
    width:100%;
    height:100%;
    margin:0;
    padding:0;
    background:#000;
    overflow:hidden;
}

video {
    width:100%;
    height:100%;
    object-fit:contain;
    background:#000;
}
</style>
</head>

<body>

<video
    id="player"
    autoplay
    muted
    controls
    playsinline>
</video>

<script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script>

<script>

const video = document.getElementById("player");

function iniciar() {

    const url = "/live.m3u8?cache=" + Date.now();

    if (video.canPlayType("application/vnd.apple.mpegurl")) {

        video.src = url;

        video.play().catch(() => {});

        return;
    }

    if (window.Hls && Hls.isSupported()) {

        const hls = new Hls({
            enableWorker: true,
            lowLatencyMode: false,
            liveSyncDurationCount: 3,
            liveMaxLatencyDurationCount: 8,
            maxLiveSyncPlaybackRate: 1.2,
            backBufferLength: 30,
            manifestLoadingMaxRetry: 10,
            levelLoadingMaxRetry: 10,
            fragLoadingMaxRetry: 10
        });

        hls.loadSource(url);
        hls.attachMedia(video);

        hls.on(
            Hls.Events.MANIFEST_PARSED,
            function() {
                video.play().catch(() => {});
            }
        );

        hls.on(
            Hls.Events.ERROR,
            function(event, data) {

                if (!data.fatal) {
                    return;
                }

                if (
                    data.type ===
                    Hls.ErrorTypes.NETWORK_ERROR
                ) {

                    hls.startLoad();
                    return;
                }

                if (
                    data.type ===
                    Hls.ErrorTypes.MEDIA_ERROR
                ) {

                    hls.recoverMediaError();
                    return;
                }

                setTimeout(
                    function() {
                        location.reload();
                    },
                    3000
                );
            }
        );

    } else {

        document.body.innerHTML =
            "<div style='color:white;font-family:Arial;text-align:center;padding:30px'>" +
            "Seu navegador não suporta reprodução HLS." +
            "</div>";
    }
}

iniciar();

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

            self.end_headers()

            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

            return

        # ====================================================
        # HLS
        # ====================================================

        if path.endswith(".m3u8"):

            file_path = STREAM_DIR / "live.m3u8"

            if not file_path.exists():

                self.send_response(503)

                self.send_header(
                    "Content-Type",
                    "text/plain; charset=utf-8"
                )

                self.end_headers()

                try:
                    self.wfile.write(
                        b"Stream ainda nao iniciou."
                    )
                except Exception:
                    pass

                return

            try:
                data = file_path.read_bytes()

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "application/vnd.apple.mpegurl"
                )

                self.send_header(
                    "Content-Length",
                    str(len(data))
                )

                self.end_headers()

                self.wfile.write(data)

            except (
                BrokenPipeError,
                ConnectionResetError
            ):
                pass

            return

        # ====================================================
        # SEGMENTOS TS
        # ====================================================

        if path.endswith(".ts"):

            filename = Path(path.lstrip("/")).name

            if not filename.startswith("segment_"):
                self.send_error(404)
                return

            file_path = STREAM_DIR / filename

            if not file_path.exists():
                self.send_error(404)
                return

            try:

                data = file_path.read_bytes()

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "video/mp2t"
                )

                self.send_header(
                    "Content-Length",
                    str(len(data))
                )

                self.send_header(
                    "Cache-Control",
                    "no-cache, no-store, must-revalidate"
                )

                self.end_headers()

                self.wfile.write(data)

            except (
                BrokenPipeError,
                ConnectionResetError
            ):
                pass

            return

        super().do_GET()


def start_http():
    global http_server

    line()
    log("[4] INICIANDO SERVIDOR HTTP")

    http_server = ThreadingHTTPServer(
        (HOST, PORT),
        StreamHandler
    )

    http_server.daemon_threads = True
    http_server.allow_reuse_address = True

    thread = threading.Thread(
        target=http_server.serve_forever,
        daemon=True
    )

    thread.start()

    time.sleep(2)

    # Teste interno.
    import urllib.request

    try:

        response = urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/",
            timeout=10
        )

        if response.status != 200:
            raise RuntimeError(
                f"HTTP retornou status {response.status}"
            )

    except Exception as e:

        raise RuntimeError(
            "Servidor HTTP local não respondeu: "
            + str(e)
        )

    log(f"Servidor HTTP ativo em {HOST}:{PORT}")
    log("Teste HTTP local OK.")


# ============================================================
# CHROMIUM
# ============================================================

def find_chromium():
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

    raise RuntimeError(
        "Chromium não encontrado."
    )


def start_chromium():
    global chromium

    line()
    log("[5] INICIANDO CHROMIUM")

    browser = find_chromium()

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY
    env["PULSE_SINK"] = "webtv"

    profile = Path("/tmp/webtv-chromium")

    if profile.exists():
        try:
            shutil.rmtree(profile)
        except Exception:
            pass

    profile.mkdir(
        parents=True,
        exist_ok=True
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

        "--disable-features=CalculateNativeWinOcclusion",

        "--autoplay-policy=no-user-gesture-required",

        "--no-first-run",
        "--no-default-browser-check",

        "--disable-notifications",
        "--disable-popup-blocking",

        "--start-maximized",

        "--window-size=1280,720",

        "--user-data-dir=" + str(profile),

        PAGE_URL,
    ]

    log("Abrindo:")
    log(PAGE_URL)

    chromium = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )

    time.sleep(8)

    if chromium.poll() is not None:
        raise RuntimeError(
            "Chromium encerrou durante a inicialização."
        )

    log("Chromium funcionando.")
    log("Página aberta.")


# ============================================================
# FFMPEG
# ============================================================

def start_ffmpeg():
    global ffmpeg

    line()
    log("[6] INICIANDO FFMPEG")

    playlist = STREAM_DIR / "live.m3u8"

    try:
        playlist.unlink()
    except FileNotFoundError:
        pass

    for file in STREAM_DIR.glob("segment_*.ts"):
        try:
            file.unlink()
        except Exception:
            pass

    command = [
        "ffmpeg",

        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",

        # X11
        "-thread_queue_size",
        "1024",

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

        # ÁUDIO
        "-thread_queue_size",
        "1024",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # VÍDEO
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

        "-g",
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        "-b:v",
        "1500k",

        "-maxrate",
        "1800k",

        "-bufsize",
        "3000k",

        # ÁUDIO
        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        "-ac",
        "2",

        # HLS
        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "8",

        "-hls_flags",
        "delete_segments+independent_segments",

        "-hls_segment_filename",
        str(
            STREAM_DIR /
            "segment_%05d.ts"
        ),

        str(playlist),
    ]

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    log("Executando FFmpeg...")

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
            for text in ffmpeg.stdout:

                text = text.strip()

                if text:
                    log("[FFMPEG] " + text)

        except Exception:
            pass

    threading.Thread(
        target=read_logs,
        daemon=True
    ).start()

    time.sleep(5)

    if ffmpeg.poll() is not None:
        raise RuntimeError(
            "FFmpeg encerrou durante a inicialização."
        )

    log("FFmpeg funcionando.")


# ============================================================
# AGUARDAR HLS
# ============================================================

def wait_hls(timeout=60):

    line()
    log("[HLS] Aguardando transmissão...")

    playlist = STREAM_DIR / "live.m3u8"

    deadline = time.time() + timeout

    while time.time() < deadline:

        if stop_event.is_set():
            return False

        if playlist.exists():

            segments = list(
                STREAM_DIR.glob("segment_*.ts")
            )

            if len(segments) > 0:

                log("[HLS] Playlist pronta.")
                log(
                    f"[HLS] Segmentos encontrados: {len(segments)}"
                )

                return True

        if ffmpeg is not None:
            if ffmpeg.poll() is not None:
                return False

        time.sleep(1)

    return False


# ============================================================
# CLOUDFLARE QUICK TUNNEL
# ============================================================

def extract_cloudflare_url(text):

    match = re.search(
        r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com",
        text
    )

    if match:
        return match.group(0)

    return None


def stop_cloudflare():

    global cloudflared

    if cloudflared is not None:

        stop_process(
            cloudflared,
            "Cloudflare Tunnel"
        )

        cloudflared = None


def start_cloudflare():
    global cloudflared
    global tunnel_url

    line()
    log("[7] INICIANDO CLOUDFLARE QUICK TUNNEL")

    stop_cloudflare()

    command = [
        "cloudflared",

        "tunnel",
        "--no-autoupdate",

        "--url",
        f"http://127.0.0.1:{PORT}",
    ]

    log("Criando túnel para:")
    log(f"http://127.0.0.1:{PORT}")

    cloudflared = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1
    )

    deadline = time.time() + 60

    found = None

    while time.time() < deadline:

        if cloudflared.poll() is not None:
            break

        line_text = cloudflared.stdout.readline()

        if not line_text:
            time.sleep(0.2)
            continue

        line_text = line_text.strip()

        if line_text:
            log("[CLOUDFLARE] " + line_text)

        url = extract_cloudflare_url(line_text)

        if url:
            found = url
            break

    if not found:

        raise RuntimeError(
            "Cloudflare não forneceu o endereço do túnel."
        )

    with tunnel_lock:
        tunnel_url = found

    line()
    log("TRANSMISSÃO EXTERNA DISPONÍVEL")
    line()
    log("LINK:")
    log(found)
    log("")
    log("HLS:")
    log(found + "/live.m3u8")
    line()

    return found


# ============================================================
# MONITOR CLOUDFLARE
# ============================================================

def monitor_cloudflare():

    global tunnel_url

    while not stop_event.is_set():

        time.sleep(10)

        if stop_event.is_set():
            break

        if cloudflared is None:
            continue

        if cloudflared.poll() is None:
            continue

        line()
        log("[CLOUDFLARE] Túnel caiu.")
        log("[CLOUDFLARE] Reconectando...")
        line()

        time.sleep(3)

        if stop_event.is_set():
            break

        try:

            new_url = start_cloudflare()

            if new_url:

                log(
                    "[CLOUDFLARE] Novo endereço:"
                )

                log(new_url)

        except Exception as e:

            log(
                "[CLOUDFLARE] Falha ao reconectar: "
                + str(e)
            )

            time.sleep(5)


# ============================================================
# MONITOR FFMPEG
# ============================================================

def monitor_ffmpeg():

    while not stop_event.is_set():

        time.sleep(5)

        if ffmpeg is None:
            continue

        if ffmpeg.poll() is not None:

            line()
            log("[ERRO] FFmpeg encerrou.")
            line()

            stop_event.set()

            break


# ============================================================
# MONITOR CHROMIUM
# ============================================================

def monitor_chromium():

    while not stop_event.is_set():

        time.sleep(10)

        if chromium is None:
            continue

        if chromium.poll() is not None:

            line()
            log("[ERRO] Chromium encerrou.")
            line()

            stop_event.set()

            break


# ============================================================
# MAIN
# ============================================================

def main():

    line()
    log("WEBTV STREAM")
    log("SEM NGROK")
    log("CLOUDFLARE QUICK TUNNEL")
    line()

    try:

        # 1
        clean_stream()

        # 2
        check_dependencies()

        # 3
        start_xvfb()

        # 4
        start_pulseaudio()

        # 5
        start_http()

        # 6
        start_chromium()

        # Aguarda página carregar.
        time.sleep(8)

        # 7
        start_ffmpeg()

        # 8
        if not wait_hls(60):

            raise RuntimeError(
                "FFmpeg não criou a playlist HLS."
            )

        # 9
        start_cloudflare()

        # ====================================================
        # ATIVO
        # ====================================================

        line()
        log("TRANSMISSÃO ATIVA")
        line()

        with tunnel_lock:
            current_url = tunnel_url

        if current_url:

            log("LINK DA TRANSMISSÃO:")
            log(current_url)

            log("")
            log("LINK HLS:")
            log(current_url + "/live.m3u8")

        log("")
        log("HTTP LOCAL:")
        log(f"http://127.0.0.1:{PORT}")

        line()

        # Monitores.
        threading.Thread(
            target=monitor_cloudflare,
            daemon=True
        ).start()

        threading.Thread(
            target=monitor_ffmpeg,
            daemon=True
        ).start()

        threading.Thread(
            target=monitor_chromium,
            daemon=True
        ).start()

        # ====================================================
        # LOOP PRINCIPAL
        # ====================================================

        while not stop_event.is_set():

            if ffmpeg is not None:

                if ffmpeg.poll() is not None:

                    log(
                        "[ERRO] FFmpeg parou."
                    )

                    break

            time.sleep(5)

    except KeyboardInterrupt:

        log("Encerrado pelo usuário.")

    except Exception as e:

        line()
        log("[ERRO FATAL]")
        log(str(e))
        line()

        sys.exit_code = 1

    finally:

        cleanup()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
