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
            log(f"[STOP] Parando {name}...")

            process.terminate()

            try:
                process.wait(timeout=5)

            except subprocess.TimeoutExpired:
                log(f"[STOP] Forçando encerramento de {name}...")
                process.kill()

                try:
                    process.wait(timeout=3)
                except Exception:
                    pass

    except Exception as e:
        log(f"[STOP] Erro ao parar {name}: {e}")


def cleanup():
    global http_server

    stop_event.set()

    line()
    log("ENCERRANDO WEBTV")

    if http_server:
        try:
            http_server.shutdown()
        except Exception:
            pass

    stop_process(ffmpeg, "FFmpeg")
    stop_process(chromium, "Chromium")
    stop_process(tunnel, "localhost.run")
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
            "Programas ausentes: "
            + ", ".join(missing)
        )

    for command in optional:
        if not check_command(command):
            log(
                f"[AVISO] {command} não encontrado."
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
                f"[AVISO] Não foi possível remover "
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
        env=env
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
        stderr=subprocess.DEVNULL
    )

    time.sleep(1)

    result = subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env
    )

    if result.returncode != 0:
        log("[AVISO] PulseAudio retornou código diferente de zero.")

    time.sleep(3)

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

        result = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV"
            ],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            log("[ERRO] Não foi possível criar sink webtv.")
            log(result.stderr.strip())

            raise RuntimeError(
                "Falha ao criar sink PulseAudio webtv."
            )

    time.sleep(2)

    # Define webtv como sink padrão.
    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

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

    log("Fontes de áudio:")

    if sources.stdout.strip():
        log(sources.stdout.strip())
    else:
        log("[AVISO] Nenhuma fonte de áudio encontrada.")

    monitor_check = subprocess.run(
        [
            "pactl",
            "get-source-volume",
            "webtv.monitor"
        ],
        capture_output=True,
        text=True
    )

    if monitor_check.returncode == 0:
        log("webtv.monitor encontrado.")

    else:
        raise RuntimeError(
            "webtv.monitor não foi encontrado."
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
            + (format % args)
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
            "Expires",
            "0"
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "*"
        )

        super().end_headers()

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

<title>WEBTV STREAM</title>

<style>

html,
body {

    width: 100%;
    height: 100%;

    margin: 0;
    padding: 0;

    background: #000;

    overflow: hidden;

}

video {

    width: 100%;
    height: 100%;

    object-fit: contain;

    background: #000;

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

let hls = null;

function startPlayer() {

    const source = "/live.m3u8";

    /*
     * Chrome/Chromium normalmente usa HLS
     * através do hls.js.
     */

    if (video.canPlayType("application/vnd.apple.mpegurl")) {

        video.src = source;

        video.play().catch(() => {});

        return;
    }

    const script = document.createElement("script");

    script.src =
        "https://cdn.jsdelivr.net/npm/hls.js@1.5.20/dist/hls.min.js";

    script.onload = function() {

        if (!window.Hls || !Hls.isSupported()) {

            console.error("HLS não suportado.");

            return;
        }

        hls = new Hls({

            /*
             * Mantém o player próximo do live edge
             * sem tentar fazer aceleração excessiva.
             */

            liveSyncDurationCount: 2,

            liveMaxLatencyDurationCount: 5,

            maxLiveSyncPlaybackRate: 1.15,

            lowLatencyMode: false,

            backBufferLength: 20,

            maxBufferLength: 10,

            maxMaxBufferLength: 15,

            enableWorker: true,

            capLevelToPlayerSize: true

        });

        hls.loadSource(source);

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

                console.log(
                    "Erro HLS:",
                    data.type
                );

                if (
                    data.type ===
                    Hls.ErrorTypes.NETWORK_ERROR
                ) {

                    setTimeout(
                        function() {

                            if (hls) {
                                hls.startLoad();
                            }

                        },
                        1000
                    );

                }

                else if (
                    data.type ===
                    Hls.ErrorTypes.MEDIA_ERROR
                ) {

                    try {

                        hls.recoverMediaError();

                    } catch (e) {

                        location.reload();

                    }

                }

                else {

                    location.reload();

                }

            }
        );

    };

    script.onerror = function() {

        console.error(
            "Não foi possível carregar hls.js."
        );

    };

    document.head.appendChild(script);
}

startPlayer();

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

        # ====================================================
        # HLS
        # ====================================================

        if path.endswith(".m3u8"):

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "application/vnd.apple.mpegurl"
            )

            self.send_header(
                "Cache-Control",
                "no-cache, no-store, must-revalidate"
            )

            self.end_headers()

            try:

                file_path = STREAM_DIR / path.lstrip("/")

                if not file_path.exists():
                    return

                with open(
                    file_path,
                    "rb"
                ) as file:

                    self.wfile.write(
                        file.read()
                    )

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

            try:
                super().do_GET()

            except (
                BrokenPipeError,
                ConnectionResetError
            ):
                pass

            return

        # ====================================================
        # OUTROS
        # ====================================================

        try:
            super().do_GET()

        except (
            BrokenPipeError,
            ConnectionResetError
        ):
            pass


def start_http():

    global http_server

    line()
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

    time.sleep(1)

    # Teste local
    test = subprocess.run(
        [
            "curl",
            "-fsS",
            f"http://127.0.0.1:{PORT}/"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if test.returncode != 0:

        raise RuntimeError(
            "Servidor HTTP local não respondeu."
        )

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
        "google-chrome-stable"
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
    log("[5] Iniciando Chromium...")

    browser = find_browser()

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["PULSE_SINK"] = "webtv"

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

        "--disable-software-rasterizer",

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

        PAGE_URL
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
                        "[CHROMIUM] "
                        + text
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
                "[AVISO] Janela Chromium não encontrada."
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
            "[AVISO] Falha no fullscreen: "
            + str(e)
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
                "[DIAGNÓSTICO] Captura X11 OK."
            )

            return True

        log(
            "[DIAGNÓSTICO] Falha na captura X11."
        )

        if result.stderr:
            log(result.stderr.strip())

    except Exception as e:

        log(
            "[DIAGNÓSTICO] Erro: "
            + str(e)
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

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

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
        # MAPA
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
        # ÁUDIO SINCRONIZADO
        # ====================================================

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "48000",

        "-ac",
        "2",

        # Corrige drift e pequenas diferenças
        # entre o relógio do áudio e vídeo.
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
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        str(
            STREAM_DIR /
            "segment_%05d.ts"
        ),

        str(playlist)
    ]

    log("Comando FFmpeg:")
    log(" ".join(command))

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    env["PULSE_SINK"] = "webtv"

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
                        "[FFMPEG] "
                        + text
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
    log("Sincronização de áudio/vídeo ativada.")


# ============================================================
# HLS
# ============================================================

def wait_hls(timeout=45):

    line()
    log("[HLS] Aguardando playlist...")

    playlist = STREAM_DIR / "live.m3u8"

    start = time.time()

    while (
        time.time() - start < timeout
    ):

        if stop_event.is_set():
            return False

        if playlist.exists():

            segments = list(
                STREAM_DIR.glob(
                    "segment_*.ts"
                )
            )

            if len(segments) >= 1:

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

    patterns = [

        r"https://[a-zA-Z0-9.-]+\.lhr\.life",

        r"https://[a-zA-Z0-9.-]+\.localhost\.run",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:
            return match.group(0)

    return None


def start_tunnel():

    global tunnel
    global tunnel_url

    line()
    log("[6] Iniciando túnel localhost.run...")

    # Se existir túnel anterior, encerra primeiro.
    if tunnel is not None:

        stop_process(
            tunnel,
            "localhost.run"
        )

    tunnel_url = None

    command = [

        "ssh",

        "-o",
        "StrictHostKeyChecking=no",

        "-o",
        "UserKnownHostsFile=/dev/null",

        "-o",
        "ServerAliveInterval=15",

        "-o",
        "ServerAliveCountMax=3",

        "-o",
        "ConnectTimeout=15",

        "-o",
        "ExitOnForwardFailure=yes",

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
        time.time() - start < 45
    ):

        if stop_event.is_set():
            return None

        if tunnel.poll() is not None:
            break

        try:

            text = tunnel.stdout.readline()

        except Exception:
            text = ""

        if not text:
            time.sleep(0.2)
            continue

        text = text.strip()

        if text:

            log(
                "[TUNEL] "
                + text
            )

        found = get_tunnel_url(text)

        if found:

            tunnel_url = found

            line()
            log("LINK DA TRANSMISSÃO")
            line()

            log(
                "LINK PRINCIPAL: "
                + tunnel_url
            )

            log(
                "LINK HLS: "
                + tunnel_url
                + "/live.m3u8"
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

    global tunnel_url

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

            if stop_event.is_set():
                break

            try:

                new_url = start_tunnel()

                if new_url:

                    line()
                    log(
                        "NOVO LINK DA TRANSMISSÃO"
                    )
                    line()

                    log(new_url)

                    log(
                        new_url
                        + "/live.m3u8"
                    )

                    line()

                else:

                    log(
                        "[TUNEL] Reconexão falhou."
                    )

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

        # ====================================================
        # 1 - LIMPEZA
        # ====================================================

        clean_stream()

        # ====================================================
        # 2 - DEPENDÊNCIAS
        # ====================================================

        check_dependencies()

        # ====================================================
        # 3 - XVFB
        # ====================================================

        start_xvfb()

        # ====================================================
        # 4 - PULSEAUDIO
        # ====================================================

        start_pulseaudio()

        # ====================================================
        # 5 - HTTP
        # ====================================================

        start_http()

        # ====================================================
        # 6 - CHROMIUM
        # ====================================================

        start_chromium()

        time.sleep(5)

        # ====================================================
        # 7 - TESTE X11
        # ====================================================

        test_x11()

        # ====================================================
        # 8 - TELA CHEIA
        # ====================================================

        fullscreen()

        time.sleep(3)

        # ====================================================
        # 9 - FFMPEG
        # ====================================================

        start_ffmpeg()

        # ====================================================
        # 10 - HLS
        # ====================================================

        if not wait_hls():

            raise RuntimeError(
                "A playlist HLS não foi criada."
            )

        # ====================================================
        # 11 - TÚNEL
        # ====================================================

        start_tunnel()

        # ====================================================
        # TRANSMISSÃO ATIVA
        # ====================================================

        line()
        log("TRANSMISSÃO ATIVA")
        line()

        log(
            "HTTP LOCAL:"
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

            log(
                "LINK EXTERNO:"
            )

            log(tunnel_url)

            log(
                "HLS EXTERNO:"
            )

            log(
                tunnel_url
                + "/live.m3u8"
            )

        else:

            log(
                "[AVISO] Túnel não foi obtido."
            )

        line()

        # ====================================================
        # MONITORES
        # ====================================================

        threading.Thread(
            target=monitor_tunnel,
            daemon=True
        ).start()

        threading.Thread(
            target=monitor_ffmpeg,
            daemon=True
        ).start()

        # ====================================================
        # LOOP PRINCIPAL
        # ====================================================

        while not stop_event.is_set():

            if chromium:

                if chromium.poll() is not None:

                    log(
                        "[ERRO] Chromium encerrou."
                    )

                    stop_event.set()
                    break

            if ffmpeg:

                if ffmpeg.poll() is not None:

                    log(
                        "[ERRO] FFmpeg encerrou."
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

        raise

    finally:

        cleanup()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
