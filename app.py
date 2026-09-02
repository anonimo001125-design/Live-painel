#!/usr/bin/env python3

import os
import re
import json
import time
import shutil
import signal
import threading
import subprocess

from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


# ============================================================
# CONFIGURAÇÃO
# ============================================================

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))

DISPLAY = os.environ.get("DISPLAY", ":99")

WIDTH = int(os.environ.get("WIDTH", "1280"))
HEIGHT = int(os.environ.get("HEIGHT", "720"))
FPS = int(os.environ.get("FPS", "30"))

TARGET_URL = os.environ.get(
    "TARGET_URL",
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch",
)

STREAM_DIR = Path(
    os.environ.get(
        "STREAM_DIR",
        str(Path.cwd() / "stream")
    )
)

# IMPORTANTE:
# O perfil NÃO é mais apagado a cada inicialização.
CHROMIUM_PROFILE = Path(
    os.environ.get(
        "CHROMIUM_PROFILE_DIR",
        str(Path.cwd() / ".chromium-profile")
    )
)

HLS_PLAYLIST = STREAM_DIR / "stream.m3u8"
HLS_SEGMENT = STREAM_DIR / "segment_%06d.ts"

FFMPEG_PRESET = os.environ.get("FFMPEG_PRESET", "veryfast")

VIDEO_BITRATE = os.environ.get("VIDEO_BITRATE", "2500k")
MAXRATE = os.environ.get("MAXRATE", "3000k")
BUFSIZE = os.environ.get("BUFSIZE", "6000k")
AUDIO_BITRATE = os.environ.get("AUDIO_BITRATE", "128k")


# ============================================================
# PROCESSOS / ESTADO
# ============================================================

BROWSER = None
XVFB = None
FFMPEG = None
TUNNEL = None
HTTP_SERVER = None

PULSE_STARTED = False
TUNNEL_URL = ""

stop_event = threading.Event()
state_lock = threading.RLock()
restart_lock = threading.Lock()


# ============================================================
# LOG
# ============================================================

def log(message):
    print(f"[WEBTV] {message}", flush=True)


# ============================================================
# UTILITÁRIOS
# ============================================================

def command_exists(name):
    return shutil.which(name) is not None


def find_browser():
    candidates = [
        os.environ.get("CHROMIUM_BIN"),
        os.environ.get("CHROME_BIN"),
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ]

    for item in candidates:
        if not item:
            continue

        if os.path.isabs(item):
            if os.path.exists(item):
                return item
        else:
            found = shutil.which(item)
            if found:
                return found

    return None


def run_quiet(cmd, timeout=10):
    try:
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return None


def stop_process(proc, name, timeout=5):
    if proc is None:
        return

    try:
        if proc.poll() is not None:
            return

        log(f"Parando {name}...")

        proc.terminate()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log(f"{name} não encerrou; usando kill.")
            proc.kill()
            proc.wait(timeout=3)

    except Exception as exc:
        log(f"Erro parando {name}: {exc}")


# ============================================================
# LIMPEZA HLS
# ============================================================

def clean_stream():
    STREAM_DIR.mkdir(parents=True, exist_ok=True)

    for item in STREAM_DIR.iterdir():

        if item.is_file() or item.is_symlink():
            try:
                item.unlink()
            except Exception:
                pass

        elif item.is_dir():
            try:
                shutil.rmtree(item)
            except Exception:
                pass


# ============================================================
# XVFB
# ============================================================

def start_xvfb():
    global XVFB

    if not command_exists("Xvfb"):
        raise RuntimeError("Xvfb não encontrado.")

    # Verifica se já existe um DISPLAY funcionando.
    if command_exists("xdpyinfo"):
        test = run_quiet(
            ["xdpyinfo", "-display", DISPLAY],
            timeout=3
        )

        if test and test.returncode == 0:
            log(f"DISPLAY {DISPLAY} já está disponível.")
            return

    XVFB = subprocess.Popen(
        [
            "Xvfb",
            DISPLAY,
            "-screen",
            "0",
            f"{WIDTH}x{HEIGHT}x24",
            "-ac",
            "+extension",
            "RANDR",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    for _ in range(50):

        if XVFB.poll() is not None:
            raise RuntimeError(
                "Xvfb encerrou durante a inicialização."
            )

        if command_exists("xdpyinfo"):

            test = run_quiet(
                ["xdpyinfo", "-display", DISPLAY],
                timeout=2
            )

            if test and test.returncode == 0:
                break

        else:
            time.sleep(0.2)
            break

        time.sleep(0.2)

    log(
        f"Xvfb iniciado em "
        f"{DISPLAY} "
        f"({WIDTH}x{HEIGHT})."
    )


# ============================================================
# PULSEAUDIO
# ============================================================

def start_pulseaudio():
    global PULSE_STARTED

    if not command_exists("pulseaudio"):
        raise RuntimeError(
            "PulseAudio não encontrado."
        )

    if not command_exists("pactl"):
        raise RuntimeError(
            "pactl não encontrado."
        )

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    result = subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1",
            "--daemonize=yes",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        log(
            "Aviso PulseAudio: "
            + result.stderr.strip()
        )

    time.sleep(1)

    sinks = run_quiet(
        [
            "pactl",
            "list",
            "short",
            "sinks"
        ],
        timeout=5
    )

    sink_exists = bool(
        sinks and
        "webtv" in sinks.stdout
    )

    if not sink_exists:

        load = run_quiet(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV",
            ],
            timeout=5
        )

        if not load or load.returncode != 0:
            log(
                "Aviso: não foi possível criar "
                "o sink PulseAudio webtv."
            )
        else:
            log(
                "Sink PulseAudio 'webtv' criado."
            )

    run_quiet(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        timeout=5
    )

    PULSE_STARTED = True

    log(
        "PulseAudio pronto; "
        "saída padrão = webtv."
    )


# ============================================================
# CORREÇÃO DO DIÁLOGO DO CHROMIUM
# ============================================================

def prepare_chromium_preferences():
    """
    Corrige o diálogo do Chromium:

        This Space Intentionally Blank

        In official builds this space will show
        the terms of service.

    Não simulamos o clique em Accept.
    A configuração é feita no master_preferences.
    """

    candidates = [
        Path("/etc/chromium/master_preferences"),
        Path("/etc/chromium/master_preferences.json"),
        Path("/etc/chromium-browser/master_preferences"),
        Path("/etc/chromium-browser/master_preferences.json"),
    ]

    browser = find_browser()

    if browser:

        browser_dir = Path(
            browser
        ).resolve().parent

        candidates.extend(
            [
                browser_dir / "master_preferences",
                browser_dir / "master_preferences.json",
            ]
        )

    seen = set()

    for path in candidates:

        path = Path(path)

        if str(path) in seen:
            continue

        seen.add(str(path))

        if not path.exists():
            continue

        try:

            raw = path.read_text(
                encoding="utf-8"
            )

            if raw.strip():

                try:
                    data = json.loads(raw)
                except Exception:
                    data = {}

            else:
                data = {}

            if not isinstance(data, dict):
                data = {}

            distribution = data.get(
                "distribution"
            )

            if not isinstance(
                distribution,
                dict
            ):
                distribution = {}
                data["distribution"] = distribution

            if distribution.get(
                "require_eula"
            ) is not False:

                distribution[
                    "require_eula"
                ] = False

                path.write_text(
                    json.dumps(
                        data,
                        indent=2,
                        ensure_ascii=False
                    ) + "\n",
                    encoding="utf-8"
                )

                log(
                    "Chromium: "
                    "require_eula=false "
                    f"aplicado em {path}"
                )

            else:

                log(
                    "Chromium: "
                    f"require_eula=false "
                    f"já configurado em {path}"
                )

            return True

        except PermissionError:

            log(
                f"Chromium: sem permissão "
                f"para alterar {path}."
            )

        except Exception as exc:

            log(
                f"Chromium: erro lendo "
                f"{path}: {exc}"
            )

    # Se o arquivo não existe, tenta criar.
    create_candidates = [
        Path(
            "/etc/chromium/master_preferences"
        ),
        Path(
            "/etc/chromium-browser/master_preferences"
        ),
    ]

    for path in create_candidates:

        try:

            path.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            if os.access(
                path.parent,
                os.W_OK
            ):

                data = {
                    "distribution": {
                        "require_eula": False
                    }
                }

                path.write_text(
                    json.dumps(
                        data,
                        indent=2
                    ) + "\n",
                    encoding="utf-8"
                )

                log(
                    "Chromium: "
                    f"master_preferences "
                    f"criado em {path}"
                )

                return True

        except PermissionError:
            continue

        except Exception as exc:

            log(
                "Chromium: erro criando "
                f"{path}: {exc}"
            )

    log(
        "Chromium: não foi possível "
        "alterar master_preferences."
    )

    log(
        "Os parâmetros "
        "--no-first-run e "
        "--no-default-browser-check "
        "também serão utilizados."
    )

    return False


# ============================================================
# PERFIL DO CHROMIUM
# ============================================================

def prepare_chromium_profile():

    CHROMIUM_PROFILE.mkdir(
        parents=True,
        exist_ok=True
    )

    # IMPORTANTE:
    # NÃO apagamos o perfil.
    #
    # Apenas removemos locks antigos caso
    # o Chromium tenha encerrado abruptamente.

    for lock_name in (
        "SingletonLock",
        "SingletonSocket",
        "SingletonCookie",
    ):

        lock = CHROMIUM_PROFILE / lock_name

        try:

            if (
                lock.exists()
                or lock.is_symlink()
            ):
                lock.unlink()

        except Exception:
            pass


# ============================================================
# CHROMIUM
# ============================================================

def start_chromium():
    global BROWSER

    browser = find_browser()

    if not browser:
        raise RuntimeError(
            "Chromium/Google Chrome não encontrado. "
            "Defina CHROMIUM_BIN ou CHROME_BIN."
        )

    # Corrige o diálogo de Terms of Service.
    prepare_chromium_preferences()

    # Cria o perfil sem apagar o anterior.
    prepare_chromium_profile()

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    args = [
        browser,

        # Segurança/ambiente de container.
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",

        # Renderização.
        "--disable-gpu",
        "--disable-software-rasterizer",

        # Evita processos/atividades desnecessárias.
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",

        # Notificações/popups.
        "--disable-notifications",
        "--disable-popup-blocking",
        "--disable-translate",
        "--disable-features=Translate",

        # ====================================================
        # CORREÇÃO PRINCIPAL
        # ====================================================

        "--no-first-run",
        "--no-default-browser-check",

        # Reprodução automática.
        "--autoplay-policy=no-user-gesture-required",

        # Tela.
        "--start-fullscreen",
        "--kiosk",
        f"--window-size={WIDTH},{HEIGHT}",
        "--window-position=0,0",

        # Perfil persistente.
        f"--user-data-dir={CHROMIUM_PROFILE}",

        # Página.
        TARGET_URL,
    ]

    log(
        f"Iniciando Chromium: {browser}"
    )

    log(
        "Perfil Chromium: "
        f"{CHROMIUM_PROFILE}"
    )

    log(
        "Abrindo: "
        f"{TARGET_URL}"
    )

    BROWSER = subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def browser_log_reader(proc):

        try:

            for line in proc.stderr:

                line = line.strip()

                if line:
                    log(
                        f"Chromium: {line}"
                    )

        except Exception:
            pass

    threading.Thread(
        target=browser_log_reader,
        args=(BROWSER,),
        daemon=True,
    ).start()

    time.sleep(3)

    if BROWSER.poll() is not None:

        raise RuntimeError(
            "Chromium encerrou imediatamente "
            f"com código {BROWSER.returncode}."
        )

    log("Chromium iniciado.")


# ============================================================
# PÁGINA HLS
# ============================================================

HTML_PAGE = """<!doctype html>
<html lang="pt-BR">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>WebTV</title>

<style>

html,
body {
    margin: 0;
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

#msg {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 10px;
    text-align: center;
    color: #fff;
    font: 14px Arial, sans-serif;
    text-shadow: 0 1px 3px #000;
    pointer-events: none;
}

</style>

</head>

<body>

<video
    id="video"
    controls
    autoplay
    muted
    playsinline
></video>

<div id="msg">
    Carregando transmissão...
</div>

<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>

<script>

const video = document.getElementById("video");
const msg = document.getElementById("msg");

const src = "/stream.m3u8";


function ready() {

    msg.textContent = "";

    video.muted = false;

    video.play().catch(() => {});

}


if (
    video.canPlayType(
        "application/vnd.apple.mpegurl"
    )
) {

    video.src = src;

    video.addEventListener(
        "loadedmetadata",
        ready,
        {once: true}
    );

    video.play().catch(() => {});

}


else if (
    window.Hls &&
    Hls.isSupported()
) {

    const hls = new Hls({

        liveSyncDurationCount: 3,

        maxLiveSyncPlaybackRate: 1.5,

        enableWorker: true

    });


    hls.loadSource(src);

    hls.attachMedia(video);


    hls.on(
        Hls.Events.MANIFEST_PARSED,
        () => {
            ready();
        }
    );


    hls.on(
        Hls.Events.ERROR,
        (_, data) => {

            if (!data.fatal)
                return;

            msg.textContent =
                "Reconectando transmissão...";


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
    );

}


else {

    msg.textContent =
        "Este navegador não suporta HLS.";

}

</script>

</body>

</html>
"""


# ============================================================
# HTTP SERVER
# ============================================================

def start_http():
    global HTTP_SERVER

    class StreamHandler(
        BaseHTTPRequestHandler
    ):

        server_version = "WebTV/1.0"

        def log_message(
            self,
            fmt,
            *args
        ):
            log(
                "HTTP: "
                + fmt % args
            )

        def _send_bytes(
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
                "Content-Length",
                str(len(data))
            )

            self.end_headers()

            if self.command != "HEAD":
                self.wfile.write(data)

        def _send_file(
            self,
            path,
            content_type
        ):

            try:

                data = path.read_bytes()

                self._send_bytes(
                    data,
                    content_type
                )

            except FileNotFoundError:

                self._send_bytes(
                    b"Not found",
                    "text/plain; charset=utf-8",
                    404
                )

            except Exception as exc:

                log(
                    f"HTTP erro lendo "
                    f"{path}: {exc}"
                )

                self._send_bytes(
                    b"Internal Server Error",
                    "text/plain; charset=utf-8",
                    500
                )

        def do_OPTIONS(self):

            self.send_response(204)

            self.send_header(
                "Access-Control-Allow-Origin",
                "*"
            )

            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, HEAD, OPTIONS"
            )

            self.send_header(
                "Access-Control-Allow-Headers",
                "*"
            )

            self.end_headers()

        def do_HEAD(self):
            self.handle_request()

        def do_GET(self):
            self.handle_request()

        def handle_request(self):

            parsed = urlparse(
                self.path
            )

            path = parsed.path


            # Página principal.
            if path in (
                "/",
                "/index.html"
            ):

                self._send_bytes(
                    HTML_PAGE.encode("utf-8"),
                    "text/html; charset=utf-8"
                )

                return


            # Health.
            if path in (
                "/health",
                "/healthz",
                "/status"
            ):

                payload = json.dumps(
                    get_status(),
                    ensure_ascii=False
                ).encode("utf-8")

                self._send_bytes(
                    payload,
                    "application/json; charset=utf-8"
                )

                return


            # Playlist.
            if path == "/stream.m3u8":

                self._send_file(
                    HLS_PLAYLIST,
                    "application/vnd.apple.mpegurl"
                )

                return


            # Segmentos.
            if (
                path.startswith("/segment_")
                and path.endswith(".ts")
            ):

                filename = Path(
                    path
                ).name

                segment = (
                    STREAM_DIR /
                    filename
                )

                if (
                    segment.exists()
                    and segment.is_file()
                ):

                    self._send_file(
                        segment,
                        "video/mp2t"
                    )

                else:

                    self._send_bytes(
                        b"Not found",
                        "text/plain; charset=utf-8",
                        404
                    )

                return


            self._send_bytes(
                b"Not found",
                "text/plain; charset=utf-8",
                404
            )


    HTTP_SERVER = ThreadingHTTPServer(
        (HOST, PORT),
        StreamHandler
    )

    thread = threading.Thread(
        target=HTTP_SERVER.serve_forever,
        kwargs={
            "poll_interval": 0.5
        },
        daemon=True
    )

    thread.start()

    log(
        f"Servidor HTTP em "
        f"http://{HOST}:{PORT}"
    )


# ============================================================
# FFMPEG
# ============================================================

def start_ffmpeg():
    global FFMPEG

    if not command_exists("ffmpeg"):
        raise RuntimeError(
            "FFmpeg não encontrado."
        )

    stop_process(
        FFMPEG,
        "FFmpeg"
    )

    FFMPEG = None

    clean_stream()

    cmd = [

        "ffmpeg",

        "-hide_banner",

        "-loglevel",
        "warning",

        "-nostdin",


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

        "-i",
        f"{DISPLAY}.0+0,0",


        # ====================================================
        # ÁUDIO
        # ====================================================

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
        FFMPEG_PRESET,

        "-tune",
        "zerolatency",

        "-pix_fmt",
        "yuv420p",

        "-r",
        str(FPS),

        "-b:v",
        VIDEO_BITRATE,

        "-maxrate",
        MAXRATE,

        "-bufsize",
        BUFSIZE,

        "-g",
        str(FPS * 2),

        "-keyint_min",
        str(FPS * 2),

        "-sc_threshold",
        "0",


        # ====================================================
        # ÁUDIO
        # ====================================================

        "-c:a",
        "aac",

        "-b:a",
        AUDIO_BITRATE,

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
        str(HLS_SEGMENT),

        str(HLS_PLAYLIST),
    ]

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    log("Iniciando FFmpeg...")

    FFMPEG = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def ffmpeg_reader(proc):

        try:

            for line in proc.stderr:

                line = line.strip()

                if line:
                    log(
                        f"FFmpeg: {line}"
                    )

        except Exception:
            pass

    threading.Thread(
        target=ffmpeg_reader,
        args=(FFMPEG,),
        daemon=True,
    ).start()

    log("FFmpeg iniciado.")


# ============================================================
# ESPERA HLS
# ============================================================

def wait_for_hls(timeout=30):

    deadline = time.time() + timeout

    while (
        time.time() < deadline
        and not stop_event.is_set()
    ):

        if (
            FFMPEG is not None
            and FFMPEG.poll() is not None
        ):

            return False

        if (
            HLS_PLAYLIST.exists()
            and HLS_PLAYLIST.stat().st_size > 0
        ):

            segments = list(
                STREAM_DIR.glob(
                    "segment_*.ts"
                )
            )

            if segments:

                log("HLS pronto.")

                return True

        time.sleep(0.5)

    log(
        "Timeout aguardando HLS."
    )

    return False


# ============================================================
# CLOUDFLARE TUNNEL
# ============================================================

def start_tunnel():
    global TUNNEL
    global TUNNEL_URL

    if not command_exists(
        "cloudflared"
    ):

        log(
            "cloudflared não encontrado; "
            "transmissão local continua disponível."
        )

        return

    stop_process(
        TUNNEL,
        "Cloudflare Tunnel"
    )

    TUNNEL = None

    TUNNEL_URL = ""

    cmd = [
        "cloudflared",
        "tunnel",
        "--url",
        f"http://127.0.0.1:{PORT}",
        "--no-autoupdate",
    ]

    log(
        "Iniciando Cloudflare Quick Tunnel..."
    )

    TUNNEL = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def tunnel_reader(proc):
        global TUNNEL_URL

        pattern = re.compile(
            r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com"
        )

        try:

            for line in proc.stdout:

                line = line.strip()

                if line:
                    log(
                        f"cloudflared: {line}"
                    )

                match = pattern.search(
                    line
                )

                if match:

                    with state_lock:

                        TUNNEL_URL = (
                            match.group(0)
                        )

                    log(
                        "URL pública: "
                        f"{TUNNEL_URL}"
                    )

        except Exception:
            pass

    threading.Thread(
        target=tunnel_reader,
        args=(TUNNEL,),
        daemon=True,
    ).start()


# ============================================================
# STATUS
# ============================================================

def get_status():

    browser_alive = (
        BROWSER is not None
        and BROWSER.poll() is None
    )

    ffmpeg_alive = (
        FFMPEG is not None
        and FFMPEG.poll() is None
    )

    tunnel_alive = (
        TUNNEL is not None
        and TUNNEL.poll() is None
    )

    return {

        "ok":
            browser_alive
            and ffmpeg_alive,

        "browser":
            browser_alive,

        "ffmpeg":
            ffmpeg_alive,

        "tunnel":
            tunnel_alive,

        "tunnel_url":
            TUNNEL_URL,

        "display":
            DISPLAY,

        "target_url":
            TARGET_URL,

        "playlist":
            HLS_PLAYLIST.exists(),

        "profile":
            str(CHROMIUM_PROFILE),

        "time":
            int(time.time()),
    }


# ============================================================
# REINICIAR CHROMIUM
# ============================================================

def restart_browser():

    global BROWSER

    with restart_lock:

        if stop_event.is_set():
            return

        log(
            "Reiniciando Chromium..."
        )

        stop_process(
            BROWSER,
            "Chromium"
        )

        BROWSER = None

        try:

            start_chromium()

        except Exception as exc:

            log(
                "Erro reiniciando Chromium: "
                f"{exc}"
            )


# ============================================================
# MONITOR CHROMIUM
# ============================================================

def monitor_chromium():

    while not stop_event.is_set():

        time.sleep(5)

        if BROWSER is None:
            continue

        if BROWSER.poll() is not None:

            log(
                "Chromium encerrou com "
                f"código {BROWSER.returncode}."
            )

            restart_browser()


# ============================================================
# MONITOR FFMPEG
# ============================================================

def monitor_ffmpeg():

    global FFMPEG

    while not stop_event.is_set():

        time.sleep(5)

        if FFMPEG is None:
            continue

        if FFMPEG.poll() is not None:

            log(
                "FFmpeg encerrou com "
                f"código {FFMPEG.returncode}."
            )

            if stop_event.is_set():
                break

            try:

                start_ffmpeg()

                wait_for_hls(30)

            except Exception as exc:

                log(
                    "Erro reiniciando FFmpeg: "
                    f"{exc}"
                )


# ============================================================
# MONITOR CLOUDFLARE
# ============================================================

def monitor_tunnel():

    global TUNNEL

    while not stop_event.is_set():

        time.sleep(10)

        if TUNNEL is None:
            continue

        if TUNNEL.poll() is not None:

            log(
                "Cloudflare Tunnel encerrou; "
                "reiniciando..."
            )

            start_tunnel()


# ============================================================
# MONITOR GERAL
# ============================================================

def monitor_general():

    while not stop_event.is_set():

        time.sleep(15)

        if not HLS_PLAYLIST.exists():
            continue

        try:

            age = (
                time.time()
                - HLS_PLAYLIST.stat().st_mtime
            )

            if (
                age > 20
                and FFMPEG is not None
                and FFMPEG.poll() is None
            ):

                log(
                    "Aviso: playlist HLS "
                    "parece estar sem atualização."
                )

        except Exception:
            pass


# ============================================================
# CLEANUP
# ============================================================

def cleanup(
    signum=None,
    frame=None
):

    global HTTP_SERVER
    global BROWSER
    global FFMPEG
    global TUNNEL
    global XVFB

    if stop_event.is_set():
        return

    log(
        "Encerrando WebTV..."
    )

    stop_event.set()

    try:

        if HTTP_SERVER:

            HTTP_SERVER.shutdown()

            HTTP_SERVER.server_close()

    except Exception:
        pass

    stop_process(
        TUNNEL,
        "Cloudflare Tunnel"
    )

    stop_process(
        FFMPEG,
        "FFmpeg"
    )

    stop_process(
        BROWSER,
        "Chromium"
    )

    stop_process(
        XVFB,
        "Xvfb"
    )

    log(
        "WebTV encerrada."
    )


# ============================================================
# SIGNALS
# ============================================================

def install_signal_handlers():

    for sig in (
        signal.SIGINT,
        signal.SIGTERM
    ):

        signal.signal(
            sig,
            cleanup
        )


# ============================================================
# INFORMAÇÕES INICIAIS
# ============================================================

def print_startup_info():

    log("=" * 60)

    log("WEBTV")

    log(
        f"TARGET_URL = {TARGET_URL}"
    )

    log(
        f"DISPLAY    = {DISPLAY}"
    )

    log(
        f"RESOLUTION = "
        f"{WIDTH}x{HEIGHT}@{FPS}"
    )

    log(
        f"HTTP       = "
        f"http://127.0.0.1:{PORT}"
    )

    log(
        f"PROFILE    = "
        f"{CHROMIUM_PROFILE}"
    )

    log("=" * 60)


# ============================================================
# MAIN
# ============================================================

def main():

    print_startup_info()

    install_signal_handlers()

    try:

        # Limpa somente os arquivos HLS.
        # O perfil do Chromium NÃO é apagado.
        clean_stream()

        # X11 virtual.
        start_xvfb()

        # Áudio virtual.
        start_pulseaudio()

        # Servidor local.
        start_http()

        # Chromium.
        start_chromium()

        # Dá tempo para a página carregar.
        time.sleep(5)

        # Captura.
        start_ffmpeg()

        # Aguarda primeira playlist.
        if not wait_for_hls(40):

            log(
                "HLS ainda não ficou pronto; "
                "continuando para os monitores."
            )

        # Tunnel.
        start_tunnel()

        # Monitores.
        threading.Thread(
            target=monitor_chromium,
            daemon=True
        ).start()

        threading.Thread(
            target=monitor_ffmpeg,
            daemon=True
        ).start()

        threading.Thread(
            target=monitor_tunnel,
            daemon=True
        ).start()

        threading.Thread(
            target=monitor_general,
            daemon=True
        ).start()

        log(
            "WebTV rodando."
        )

        log(
            "Player local: "
            f"http://127.0.0.1:{PORT}/"
        )

        log(
            "Health: "
            f"http://127.0.0.1:{PORT}/health"
        )

        while not stop_event.is_set():

            time.sleep(1)

    except KeyboardInterrupt:
        pass

    except Exception as exc:

        log(
            f"ERRO FATAL: {exc}"
        )

        cleanup()

        raise

    finally:

        cleanup()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    main()
