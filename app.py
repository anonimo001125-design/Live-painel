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
PAGE_URL = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

# ============================================================
# PROCESSOS
# ============================================================

xvfb = None
pulse = None
chromium = None
ffmpeg = None
tunnel = None
http_server = None

stop_event = threading.Event()
tunnel_url = None


# ============================================================
# LOG
# ============================================================

def log(text=""):
    print(text, flush=True)


def line():
    log("=" * 70)


# ============================================================
# ENCERRAMENTO
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

    except Exception as e:
        log(f"[STOP] Erro ao encerrar {name}: {e}")


def cleanup():
    global http_server

    stop_event.set()

    line()
    log("ENCERRANDO WEBTV")

    stop_process(ffmpeg, "FFmpeg")
    stop_process(chromium, "Chromium")
    stop_process(tunnel, "localhost.run")
    stop_process(pulse, "PulseAudio")
    stop_process(xvfb, "Xvfb")

    if http_server:
        try:
            http_server.shutdown()
        except Exception:
            pass

    log("Processos encerrados.")


def signal_handler(signum, frame):
    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============================================================
# DEPENDÊNCIAS
# ============================================================

def check_command(name):
    return shutil.which(name) is not None


def check_dependencies():
    line()
    log("VERIFICANDO DEPENDÊNCIAS")

    required = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
        "ssh",
    ]

    optional = [
        "xdotool",
    ]

    missing = []

    for command in required:
        if not check_command(command):
            missing.append(command)

    if missing:
        raise RuntimeError(
            "Dependências obrigatórias ausentes: "
            + ", ".join(missing)
        )

    for command in optional:
        if not check_command(command):
            log(
                f"[AVISO] {command} não encontrado. "
                "Algumas funções podem ser limitadas."
            )

    log("Dependências OK.")


# ============================================================
# LIMPAR STREAM
# ============================================================

def clean_stream():
    line()
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
                f"[AVISO] Não consegui remover "
                f"{item}: {e}"
            )


# ============================================================
# XVFB
# ============================================================

def start_xvfb():
    global xvfb

    line()
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

    time.sleep(2)

    if xvfb.poll() is not None:
        raise RuntimeError(
            "Xvfb não conseguiu iniciar."
        )

    log("Xvfb pronto.")


# ============================================================
# PULSEAUDIO
# ============================================================

def start_pulseaudio():
    global pulse

    line()
    log("[3] Iniciando PulseAudio...")
    log("Criando sink virtual webtv...")

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    subprocess.run(
        ["pulseaudio", "--kill"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(1)

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    time.sleep(2)

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
            log(
                "[AVISO] Falha ao criar sink webtv:"
            )
            log(result.stderr.strip())

    # Deixa o PulseAudio estabilizar.
    time.sleep(2)

    # Confirma se o monitor existe.
    sources = subprocess.run(
        ["pactl", "list", "short", "sources"],
        capture_output=True,
        text=True,
    )

    log("Fontes de áudio:")

    if sources.stdout.strip():
        log(sources.stdout.strip())
    else:
        log("[AVISO] Nenhuma fonte encontrada.")

    monitor_check = subprocess.run(
        [
            "pactl",
            "get-source-volume",
            "webtv.monitor",
        ],
        capture_output=True,
        text=True,
    )

    if monitor_check.returncode == 0:
        log("webtv.monitor encontrado.")
    else:
        log(
            "[AVISO] webtv.monitor não foi encontrado."
        )

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
        log(
            "[HTTP] "
            + format % args
        )

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

        super().end_headers()

    def do_GET(self):

        # Página inicial.
        if self.path in ("/", ""):

            html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">
<title>WEBTV STREAM</title>

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
    controls
    autoplay
    muted
    playsinline
    preload="auto">
</video>

<script>
const video = document.getElementById("player");

function loadStream() {

    if (video.canPlayType("application/vnd.apple.mpegurl")) {

        video.src = "/live.m3u8";

        video.play().catch(() => {});

    } else {

        const script = document.createElement("script");

        script.src =
            "https://cdn.jsdelivr.net/npm/hls.js@latest";

        script.onload = function() {

            if (window.Hls && Hls.isSupported()) {

                const hls = new Hls({
                    liveSyncDurationCount: 3,
                    maxLiveSyncPlaybackRate: 1.5
                });

                hls.loadSource("/live.m3u8");
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

                        if (data.fatal) {

                            if (
                                data.type ===
                                Hls.ErrorTypes.NETWORK_ERROR
                            ) {
                                hls.startLoad();
                            }

                            else if (
                                data.type ===
                                Hls.ErrorTypes.MEDIA_ERROR
                            ) {
                                hls.recoverMediaError();
                            }
                        }
                    }
                );
            }
        };

        document.head.appendChild(script);
    }
}

loadStream();
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
            except BrokenPipeError:
                pass

            return

        super().do_GET()


def start_http():
    global http_server

    line()
    log("[4] Iniciando servidor HTTP...")

    http_server = ThreadingHTTPServer(
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

def find_browser():

    browsers = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]

    for browser in browsers:

        path = shutil.which(browser)

        if path:
            return path

    raise RuntimeError(
        "Chromium/Google Chrome não encontrado."
    )


def start_chromium():
    global chromium

    line()
    log("[6] Iniciando Chromium...")

    browser = find_browser()

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    profile = Path(
        "/tmp/webtv-chromium-profile"
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

    command = [
        browser,

        "--no-sandbox",
        "--disable-setuid-sandbox",

        "--disable-dev-shm-usage",

        "--disable-gpu",

        "--autoplay-policy=no-user-gesture-required",

        "--disable-background-networking",

        "--disable-background-timer-throttling",

        "--disable-renderer-backgrounding",

        "--disable-backgrounding-occluded-windows",

        "--disable-notifications",

        "--disable-infobars",

        "--disable-popup-blocking",

        "--start-fullscreen",

        "--kiosk",

        "--window-size=1280,720",

        "--window-position=0,0",

        "--user-data-dir="
        + str(profile),

        PAGE_URL,
    ]

    log("Abrindo página:")
    log(PAGE_URL)

    chromium = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    time.sleep(6)

    if chromium.poll() is not None:

        raise RuntimeError(
            "Chromium encerrou durante a inicialização."
        )

    log("Chromium iniciado.")
    log("Página carregada.")

    def chromium_logs():

        try:

            for text in chromium.stderr:

                text = text.strip()

                if text:
                    log(
                        f"[CHROMIUM] {text}"
                    )

        except Exception:
            pass

    threading.Thread(
        target=chromium_logs,
        daemon=True
    ).start()


# ============================================================
# TELA CHEIA
# ============================================================

def fullscreen():

    line()
    log("[TELA] Ativando tela cheia do Chromium")

    if not shutil.which("xdotool"):

        log(
            "[AVISO] xdotool não instalado."
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
            text=True,
            timeout=10
        )

        windows = (
            result.stdout.strip().splitlines()
        )

        if not windows:

            log(
                "[AVISO] Janela do Chromium não encontrada."
            )

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

    except Exception as e:

        log(
            f"[AVISO] Falha no fullscreen: {e}"
        )


# ============================================================
# TESTE X11
# ============================================================

def test_x11():

    line()
    log("[DIAGNÓSTICO] Testando X11...")

    output = STREAM_DIR / "debug_screen.png"

    try:

        result = subprocess.run(
            [
                "import",
                "-display",
                DISPLAY,
                "-window",
                "root",
                str(output)
            ],
            capture_output=True,
            text=True,
            timeout=15
        )

        if (
            result.returncode == 0
            and output.exists()
        ):

            log(
                "[DIAGNÓSTICO] Captura OK: "
                + str(output)
            )

            return True

        log(
            "[DIAGNÓSTICO] Falha na captura X11."
        )

        if result.stderr:
            log(result.stderr.strip())

    except Exception as e:

        log(
            f"[DIAGNÓSTICO] Erro: {e}"
        )

    return False


# ============================================================
# FFMPEG
# ============================================================

def start_ffmpeg():
    global ffmpeg

    line()
    log("INICIANDO FFMPEG")

    playlist = STREAM_DIR / "live.m3u8"

    # Remove playlist anterior.
    try:
        playlist.unlink()
    except FileNotFoundError:
        pass

    # Remove segmentos antigos.
    for file in STREAM_DIR.glob(
        "segment_*.ts"
    ):

        try:
            file.unlink()
        except Exception:
            pass

    command = [
        "ffmpeg",

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

        # ====================================================
        # X11
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
        # PULSE
        # ====================================================

        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

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

        "-hls_segment_filename",
        str(
            STREAM_DIR
            / "segment_%05d.ts"
        ),

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

    def ffmpeg_logs():

        try:

            for text in ffmpeg.stdout:

                text = text.strip()

                if text:
                    log(
                        f"[FFMPEG] {text}"
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
            "FFmpeg encerrou imediatamente."
        )

    log("FFmpeg funcionando.")


# ============================================================
# HLS
# ============================================================

def wait_hls(timeout=30):

    line()
    log("[HLS] Aguardando playlist...")

    playlist = STREAM_DIR / "live.m3u8"

    start = time.time()

    while (
        time.time() - start
        < timeout
    ):

        if stop_event.is_set():
            return False

        if playlist.exists():

            segments = list(
                STREAM_DIR.glob(
                    "segment_*.ts"
                )
            )

            if segments:

                log(
                    "[HLS] Playlist pronta."
                )

                return True

        time.sleep(1)

    log(
        "[HLS] ERRO: playlist não foi criada."
    )

    return False


# ============================================================
# TÚNEL LOCALHOST.RUN
# ============================================================

def get_tunnel_url(text):

    match = re.search(
        r"https://[a-zA-Z0-9.-]+\.lhr\.life",
        text
    )

    if match:
        return match.group(0)

    return None


def start_tunnel():
    global tunnel
    global tunnel_url

    line()
    log(
        "[5] Iniciando túnel localhost.run..."
    )

    command = [
        "ssh",

        "-o",
        "StrictHostKeyChecking=no",

        "-o",
        "ServerAliveInterval=15",

        "-o",
        "ServerAliveCountMax=3",

        "-o",
        "ConnectTimeout=15",

        "-R",
        "80:localhost:8080",

        "nokey@localhost.run"
    ]

    tunnel = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    start = time.time()

    while (
        time.time() - start
        < 30
    ):

        if tunnel.poll() is not None:
            break

        text = tunnel.stdout.readline()

        if not text:
            time.sleep(0.2)
            continue

        text = text.strip()

        if text:
            log(
                f"[TUNEL] {text}"
            )

        found = get_tunnel_url(text)

        if found:

            tunnel_url = found

            line()
            log(
                "LINK DA TRANSMISSÃO"
            )
            line()

            log(
                f"LINK PRINCIPAL: "
                f"{tunnel_url}"
            )

            log(
                f"LINK HLS: "
                f"{tunnel_url}/live.m3u8"
            )

            line()

            return tunnel_url

    log(
        "[TUNEL] Não foi possível obter o link."
    )

    return None


# ============================================================
# MONITOR DO TÚNEL
# ============================================================

def monitor_tunnel():

    while not stop_event.is_set():

        time.sleep(10)

        if stop_event.is_set():
            break

        if tunnel is None:
            continue

        if tunnel.poll() is not None:

            line()

            log(
                "[TUNEL] Túnel desconectado."
            )

            log(
                "[TUNEL] Tentando reconectar..."
            )

            time.sleep(3)

            if not stop_event.is_set():

                try:

                    new_url = start_tunnel()

                    if new_url:

                        line()
                        log(
                            "NOVO LINK DA TRANSMISSÃO"
                        )
                        line()

                        log(
                            new_url
                        )

                        log(
                            new_url
                            + "/live.m3u8"
                        )

                        line()

                except Exception as e:

                    log(
                        "[TUNEL] Erro ao reconectar: "
                        + str(e)
                    )


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

            log(
                "[ERRO] FFmpeg encerrou."
            )

            line()

            stop_event.set()

            break


# ============================================================
# MAIN
# ============================================================

def main():

    line()
    log("WEBTV STREAM")
    line()

    try:

        # 1
        clean_stream()

        # CHECK
        check_dependencies()

        # 2
        start_xvfb()

        # 3
        start_pulseaudio()

        # 4
        start_http()

        # 5
        start_tunnel()

        # 6
        start_chromium()

        time.sleep(5)

        # Diagnóstico X11.
        test_x11()

        # Fullscreen.
        fullscreen()

        time.sleep(3)

        # FFmpeg.
        start_ffmpeg()

        # HLS.
        if not wait_hls():

            raise RuntimeError(
                "A playlist HLS não foi criada."
            )

        # ====================================================
        # TRANSMISSÃO ATIVA
        # ====================================================

        line()
        log("TRANSMISSÃO ATIVA")
        line()

        if tunnel_url:

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

            log(
                "LINK LOCAL:"
            )

            log(
                f"http://localhost:{PORT}"
            )

        line()

        # Monitores.
        threading.Thread(
            target=monitor_tunnel,
            daemon=True
        ).start()

        threading.Thread(
            target=monitor_ffmpeg,
            daemon=True
        ).start()

        # ====================================================
        # LOOP
        # ====================================================

        while not stop_event.is_set():

            if chromium:

                if chromium.poll() is not None:

                    log(
                        "[AVISO] Chromium encerrou."
                    )

                    stop_event.set()
                    break

            time.sleep(5)

    except KeyboardInterrupt:

        log(
            "[INFO] Encerrado pelo usuário."
        )

    except Exception as e:

        line()
        log(
            "[ERRO FATAL]"
        )
        log(
            str(e)
        )
        line()

    finally:

        cleanup()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
