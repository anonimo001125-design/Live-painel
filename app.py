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

# Reduzimos para 20 FPS para aliviar X11 + Chromium + FFmpeg.
# O vídeo continua visualmente fluido para uma transmissão de TV.
FPS = 20

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

tunnel_url = None

stop_event = threading.Event()


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

        log(
            f"[STOP] Erro ao encerrar {name}: {e}"
        )


def cleanup():

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


signal.signal(
    signal.SIGINT,
    signal_handler
)

signal.signal(
    signal.SIGTERM,
    signal_handler
)


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

    missing = []

    for command in required:

        if not check_command(command):
            missing.append(command)

    if missing:

        raise RuntimeError(
            "Dependências ausentes: "
            + ", ".join(missing)
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

            log(
                "[AVISO] Falha ao criar sink webtv:"
            )

            log(
                result.stderr.strip()
            )

    time.sleep(2)

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

        super().end_headers()

    def do_GET(self):

        if self.path in ("/", ""):

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
    playsinline
    controls
    preload="auto">
</video>

<script>

const video =
    document.getElementById("player");

let hls = null;

function iniciarPlayer() {

    if (
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ) {

        video.src = "/live.m3u8";

        video.play().catch(() => {});

        return;
    }

    const script =
        document.createElement("script");

    script.src =
        "https://cdn.jsdelivr.net/npm/hls.js@latest";

    script.onload = function() {

        if (
            !window.Hls ||
            !Hls.isSupported()
        ) {
            return;
        }

        hls = new Hls({

            /*
             * Prioridade máxima:
             * estabilidade em vez de baixa latência.
             */

            lowLatencyMode: false,

            enableWorker: true,

            startLevel: -1,

            /*
             * Mantém vários segmentos
             * disponíveis no buffer.
             */

            liveSyncDurationCount: 5,

            liveMaxLatencyDurationCount: 10,

            maxBufferLength: 45,

            maxMaxBufferLength: 90,

            backBufferLength: 30,

            startFragPrefetch: true,

            capLevelToPlayerSize: true,

            testBandwidth: true
        });

        hls.loadSource(
            "/live.m3u8"
        );

        hls.attachMedia(video);

        hls.on(
            Hls.Events.MANIFEST_PARSED,
            function() {

                video
                    .play()
                    .catch(() => {});

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

                    setTimeout(
                        function() {

                            try {

                                hls.startLoad();

                            } catch(e) {}

                        },
                        1500
                    );

                }

                else if (
                    data.type ===
                    Hls.ErrorTypes.MEDIA_ERROR
                ) {

                    try {

                        hls.recoverMediaError();

                    } catch(e) {}

                }

                else {

                    try {

                        hls.destroy();

                    } catch(e) {}

                    setTimeout(
                        iniciarPlayer,
                        2000
                    );
                }
            }
        );
    };

    script.onerror = function() {

        setTimeout(
            iniciarPlayer,
            3000
        );

    };

    document.head.appendChild(script);
}

iniciarPlayer();

</script>

</body>

</html>
"""

            data = html.encode(
                "utf-8"
            )

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

    http_server.daemon_threads = True

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
        "google-chrome-stable"
    ]

    for browser in browsers:

        path = shutil.which(browser)

        if path:
            return path

    raise RuntimeError(
        "Chromium/Chrome não encontrado."
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

        "--disable-background-networking",

        "--disable-background-timer-throttling",

        "--disable-renderer-backgrounding",

        "--disable-backgrounding-occluded-windows",

        "--disable-notifications",

        "--disable-popup-blocking",

        "--disable-extensions",

        "--disable-sync",

        "--disable-translate",

        "--disable-default-apps",

        "--no-first-run",

        "--disable-session-crashed-bubble",

        "--autoplay-policy=no-user-gesture-required",

        "--start-fullscreen",

        "--kiosk",

        f"--window-size={WIDTH},{HEIGHT}",

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

    time.sleep(7)

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

                if not text:
                    continue

                # Esses erros são da página e não
                # precisam inundar o terminal.

                if "Firestore" in text:
                    continue

                if "requestFullscreen" in text:
                    continue

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
# FULLSCREEN
# ============================================================

def fullscreen():

    line()

    log(
        "[TELA] Ativando tela cheia do Chromium"
    )

    if not shutil.which("xdotool"):

        log(
            "[AVISO] xdotool não encontrado."
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
            result.stdout
            .strip()
            .splitlines()
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
            "[AVISO] Fullscreen: "
            + str(e)
        )


# ============================================================
# TESTE X11
# ============================================================

def test_x11():

    line()

    log(
        "[DIAGNÓSTICO] Testando X11..."
    )

    output = (
        STREAM_DIR /
        "debug_screen.png"
    )

    if not shutil.which("import"):

        log(
            "[AVISO] ImageMagick não encontrado."
        )

        return False

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

    playlist = (
        STREAM_DIR /
        "live.m3u8"
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

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

        # ====================================================
        # CONTROLE DE TIMESTAMP
        # ====================================================

        "-fflags",
        "+genpts",

        # ====================================================
        # X11
        # ====================================================

        "-thread_queue_size",
        "16384",

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
        # PULSE AUDIO
        # ====================================================

        "-thread_queue_size",
        "16384",

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

        "-pix_fmt",
        "yuv420p",

        # FPS CONSTANTE
        "-fps_mode",
        "cfr",

        "-r",
        str(FPS),

        # GOP
        "-g",
        str(FPS * 2),

        "-keyint_min",
        str(FPS * 2),

        "-sc_threshold",
        "0",

        # Bitrate
        "-b:v",
        "1200k",

        "-maxrate",
        "1400k",

        "-bufsize",
        "5000k",

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
        # CORREÇÃO DE CLOCK DO ÁUDIO
        # ====================================================

        "-af",
        (
            "aresample="
            "async=1000:"
            "min_hard_comp=0.100:"
            "first_pts=0"
        ),

        # ====================================================
        # HLS
        # ====================================================

        "-f",
        "hls",

        "-hls_time",
        "6",

        "-hls_list_size",
        "8",

        "-hls_flags",
        (
            "delete_segments+"
            "append_list+"
            "independent_segments"
        ),

        "-hls_delete_threshold",
        "3",

        "-hls_segment_filename",

        str(
            STREAM_DIR /
            "segment_%05d.ts"
        ),

        str(playlist)
    ]

    log("Comando FFmpeg:")

    log(
        " ".join(command)
    )

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

    log(
        "FFmpeg funcionando."
    )


# ============================================================
# HLS
# ============================================================

def wait_hls(timeout=50):

    line()

    log(
        "[HLS] Aguardando playlist..."
    )

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

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

            if len(segments) >= 2:

                log(
                    "[HLS] Playlist pronta."
                )

                return True

        time.sleep(1)

    log(
        "[HLS] Playlist não foi criada."
    )

    return False


# ============================================================
# TÚNEL
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

    if tunnel is not None:

        try:

            if tunnel.poll() is None:

                tunnel.terminate()

                try:
                    tunnel.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    tunnel.kill()

        except Exception:
            pass

        tunnel = None

    command = [

        "ssh",

        "-o",
        "StrictHostKeyChecking=no",

        "-o",
        "ServerAliveInterval=30",

        "-o",
        "ServerAliveCountMax=6",

        "-o",
        "TCPKeepAlive=yes",

        "-o",
        "ExitOnForwardFailure=yes",

        "-o",
        "ConnectTimeout=20",

        "-o",
        "ConnectionAttempts=3",

        "-R",
        "80:127.0.0.1:8080",

        "nokey@localhost.run"
    ]

    try:

        tunnel = subprocess.Popen(

            command,

            stdin=subprocess.DEVNULL,

            stdout=subprocess.PIPE,

            stderr=subprocess.STDOUT,

            text=True,

            bufsize=1
        )

    except Exception as e:

        log(
            "[TUNEL] Erro: "
            + str(e)
        )

        return None

    start = time.time()

    while (
        time.time() - start
        < 30
    ):

        if stop_event.is_set():
            return None

        if tunnel.poll() is not None:

            log(
                "[TUNEL] SSH encerrou."
            )

            return None

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

            log(
                "LINK DA TRANSMISSÃO"
            )

            line()

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

            line()

            return tunnel_url

    log(
        "[TUNEL] Timeout."
    )

    try:

        if tunnel.poll() is None:
            tunnel.terminate()

    except Exception:
        pass

    tunnel = None

    return None


# ============================================================
# MONITOR DO TÚNEL
# ============================================================

def monitor_tunnel():

    global tunnel
    global tunnel_url

    delay = 5

    while not stop_event.is_set():

        time.sleep(5)

        if stop_event.is_set():
            break

        if tunnel is not None:

            if tunnel.poll() is None:
                continue

            log("")
            line()

            log(
                "[TUNEL] Conexão perdida."
            )

            line()

        tunnel = None

        while (
            not stop_event.is_set()
            and tunnel is None
        ):

            log(
                f"[TUNEL] Reconectando em "
                f"{delay}s..."
            )

            time.sleep(delay)

            if stop_event.is_set():
                break

            try:

                new_url = start_tunnel()

                if new_url:

                    tunnel_url = new_url

                    delay = 5

                    line()

                    log(
                        "TÚNEL RESTABELECIDO"
                    )

                    line()

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

                    line()

                    break

                delay = min(
                    delay * 2,
                    30
                )

            except Exception as e:

                log(
                    "[TUNEL] Erro: "
                    + str(e)
                )

                delay = min(
                    delay * 2,
                    30
                )


# ============================================================
# MONITOR FFMPEG
# ============================================================

def monitor_ffmpeg():

    global ffmpeg

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

    log(
        "WEBTV STREAM"
    )

    line()

    try:

        # ----------------------------------------------------
        # 1
        # ----------------------------------------------------

        clean_stream()

        # ----------------------------------------------------
        # Dependências
        # ----------------------------------------------------

        check_dependencies()

        # ----------------------------------------------------
        # 2
        # ----------------------------------------------------

        start_xvfb()

        # ----------------------------------------------------
        # 3
        # ----------------------------------------------------

        start_pulseaudio()

        # ----------------------------------------------------
        # 4
        # ----------------------------------------------------

        start_http()

        # ----------------------------------------------------
        # 5
        # ----------------------------------------------------

        start_tunnel()

        # ----------------------------------------------------
        # 6
        # ----------------------------------------------------

        start_chromium()

        time.sleep(5)

        # ----------------------------------------------------
        # Diagnóstico
        # ----------------------------------------------------

        test_x11()

        # ----------------------------------------------------
        # Tela cheia
        # ----------------------------------------------------

        fullscreen()

        time.sleep(3)

        # ----------------------------------------------------
        # FFmpeg
        # ----------------------------------------------------

        start_ffmpeg()

        # ----------------------------------------------------
        # HLS
        # ----------------------------------------------------

        if not wait_hls():

            raise RuntimeError(
                "HLS não foi criado."
            )

        # ----------------------------------------------------
        # TRANSMISSÃO
        # ----------------------------------------------------

        line()

        log(
            "TRANSMISSÃO ATIVA"
        )

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

        # ----------------------------------------------------
        # MONITORES
        # ----------------------------------------------------

        threading.Thread(
            target=monitor_tunnel,
            daemon=True
        ).start()

        threading.Thread(
            target=monitor_ffmpeg,
            daemon=True
        ).start()

        # ----------------------------------------------------
        # LOOP
        # ----------------------------------------------------

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
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    main()
