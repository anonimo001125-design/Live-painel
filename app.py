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
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
)

# Pasta dos arquivos HLS
STREAM_DIR = Path(
    os.environ.get(
        "STREAM_DIR",
        str(Path.cwd() / "stream")
    )
)

# ============================================================
# IMPORTANTE:
# O perfil do Chromium NÃO é mais apagado.
# ============================================================

CHROMIUM_PROFILE = Path(
    os.environ.get(
        "CHROMIUM_PROFILE_DIR",
        str(Path.cwd() / ".chromium-profile")
    )
)

HLS_PLAYLIST = STREAM_DIR / "stream.m3u8"

HLS_SEGMENT_PATTERN = (
    STREAM_DIR / "segment_%06d.ts"
)

# ============================================================
# VÍDEO / ÁUDIO
# ============================================================

VIDEO_BITRATE = os.environ.get(
    "VIDEO_BITRATE",
    "2500k"
)

MAXRATE = os.environ.get(
    "MAXRATE",
    "3000k"
)

BUFSIZE = os.environ.get(
    "BUFSIZE",
    "6000k"
)

AUDIO_BITRATE = os.environ.get(
    "AUDIO_BITRATE",
    "128k"
)

FFMPEG_PRESET = os.environ.get(
    "FFMPEG_PRESET",
    "veryfast"
)

# ============================================================
# OPCIONAL: WORKER
#
# Se o seu Worker recebe uma URL pública, informe:
#
# WORKER_UPDATE_URL
# WORKER_TOKEN (opcional)
#
# O programa enviará a URL M3U8 pública em JSON.
# ============================================================

WORKER_UPDATE_URL = os.environ.get(
    "WORKER_UPDATE_URL",
    ""
).strip()

WORKER_TOKEN = os.environ.get(
    "WORKER_TOKEN",
    ""
).strip()


# ============================================================
# PROCESSOS
# ============================================================

BROWSER = None
XVFB = None
FFMPEG = None
TUNNEL = None
HTTP_SERVER = None

TUNNEL_URL = ""
PUBLIC_M3U8_URL = ""

stop_event = threading.Event()
state_lock = threading.RLock()
restart_lock = threading.Lock()


# ============================================================
# LOG
# ============================================================

def log(message):
    print(
        f"[WEBTV] {message}",
        flush=True
    )


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

    for candidate in candidates:

        if not candidate:
            continue

        if os.path.isabs(candidate):

            if os.path.exists(candidate):
                return candidate

        else:

            found = shutil.which(candidate)

            if found:
                return found

    return None


def run_quiet(
    command,
    timeout=10
):

    try:

        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False
        )

    except Exception:

        return None


def stop_process(
    process,
    name,
    timeout=5
):

    if process is None:
        return

    try:

        if process.poll() is not None:
            return

        log(
            f"Parando {name}..."
        )

        process.terminate()

        try:

            process.wait(
                timeout=timeout
            )

        except subprocess.TimeoutExpired:

            log(
                f"{name} não encerrou; "
                "forçando encerramento."
            )

            process.kill()

            process.wait(
                timeout=3
            )

    except Exception as exc:

        log(
            f"Erro parando {name}: {exc}"
        )


# ============================================================
# LIMPAR SOMENTE HLS
# ============================================================

def clean_stream():

    STREAM_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    for item in STREAM_DIR.iterdir():

        try:

            if (
                item.is_file()
                or item.is_symlink()
            ):

                item.unlink()

            elif item.is_dir():

                shutil.rmtree(item)

        except Exception:
            pass


# ============================================================
# XVFB
# ============================================================

def start_xvfb():

    global XVFB

    if not command_exists("Xvfb"):

        raise RuntimeError(
            "Xvfb não encontrado."
        )

    # Verifica se já existe DISPLAY.
    if command_exists("xdpyinfo"):

        test = run_quiet(
            [
                "xdpyinfo",
                "-display",
                DISPLAY
            ],
            timeout=3
        )

        if (
            test
            and test.returncode == 0
        ):

            log(
                f"DISPLAY {DISPLAY} "
                "já está disponível."
            )

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

    for _ in range(60):

        if XVFB.poll() is not None:

            raise RuntimeError(
                "Xvfb encerrou durante "
                "a inicialização."
            )

        if command_exists("xdpyinfo"):

            test = run_quiet(
                [
                    "xdpyinfo",
                    "-display",
                    DISPLAY
                ],
                timeout=2
            )

            if (
                test
                and test.returncode == 0
            ):
                log(
                    f"Xvfb pronto em {DISPLAY}."
                )
                return

        time.sleep(0.2)

    raise RuntimeError(
        "Timeout aguardando Xvfb."
    )


# ============================================================
# PULSEAUDIO
# ============================================================

def start_pulseaudio():

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

    webtv_exists = bool(
        sinks
        and "webtv" in sinks.stdout
    )

    if not webtv_exists:

        result = run_quiet(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV",
            ],
            timeout=5
        )

        if (
            not result
            or result.returncode != 0
        ):

            log(
                "Aviso: não foi possível "
                "criar sink webtv."
            )

        else:

            log(
                "Sink PulseAudio "
                "'webtv' criado."
            )

    run_quiet(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        timeout=5
    )

    log(
        "PulseAudio pronto."
    )


# ============================================================
# CORREÇÃO DO CHROMIUM
# ============================================================

def prepare_chromium_preferences():

    candidates = [
        Path(
            "/etc/chromium/master_preferences"
        ),
        Path(
            "/etc/chromium/master_preferences.json"
        ),
        Path(
            "/etc/chromium-browser/master_preferences"
        ),
        Path(
            "/etc/chromium-browser/master_preferences.json"
        ),
    ]

    browser = find_browser()

    if browser:

        browser_dir = Path(
            browser
        ).resolve().parent

        candidates.extend(
            [
                browser_dir /
                "master_preferences",

                browser_dir /
                "master_preferences.json",
            ]
        )

    seen = set()

    # Primeiro tenta arquivos existentes.
    for path in candidates:

        path = Path(path)

        if str(path) in seen:
            continue

        seen.add(str(path))

        if not path.exists():
            continue

        try:

            try:

                data = json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )

            except Exception:

                data = {}

            if not isinstance(
                data,
                dict
            ):

                data = {}

            distribution = data.get(
                "distribution"
            )

            if not isinstance(
                distribution,
                dict
            ):

                distribution = {}

                data["distribution"] = (
                    distribution
                )

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
                f"configurado em {path}"
            )

            return True

        except PermissionError:

            log(
                f"Chromium: sem permissão "
                f"para {path}."
            )

        except Exception as exc:

            log(
                f"Chromium: erro em "
                f"{path}: {exc}"
            )

    # Depois tenta criar.
    create_candidates = [
        Path(
            "/etc/chromium/master_preferences"
        ),
        Path(
            "/etc/chromium-browser/"
            "master_preferences"
        ),
    ]

    for path in create_candidates:

        try:

            path.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            if not os.access(
                path.parent,
                os.W_OK
            ):
                continue

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
                f"master_preferences criado "
                f"em {path}"
            )

            return True

        except PermissionError:
            continue

        except Exception as exc:

            log(
                f"Chromium: erro criando "
                f"{path}: {exc}"
            )

    log(
        "Chromium: não foi possível "
        "alterar master_preferences."
    )

    return False


# ============================================================
# PERFIL CHROMIUM
# ============================================================

def prepare_chromium_profile():

    CHROMIUM_PROFILE.mkdir(
        parents=True,
        exist_ok=True
    )

    # NÃO apagamos o perfil.
    #
    # Somente removemos locks antigos.
    #
    # Isso evita que uma execução anterior
    # impeça o Chromium de abrir.

    for name in (
        "SingletonLock",
        "SingletonSocket",
        "SingletonCookie",
    ):

        lock = (
            CHROMIUM_PROFILE /
            name
        )

        try:

            if (
                lock.exists()
                or lock.is_symlink()
            ):

                lock.unlink()

        except Exception:
            pass


# ============================================================
# START CHROMIUM
# ============================================================

def start_chromium():

    global BROWSER

    browser = find_browser()

    if not browser:

        raise RuntimeError(
            "Chromium/Chrome não encontrado."
        )

    # CORREÇÃO DA TELA:
    #
    # This Space Intentionally Blank
    #
    prepare_chromium_preferences()

    # NÃO apagar perfil.
    prepare_chromium_profile()

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    args = [

        browser,

        "--no-sandbox",

        "--disable-setuid-sandbox",

        "--disable-dev-shm-usage",

        "--disable-gpu",

        "--disable-software-rasterizer",

        "--disable-background-networking",

        "--disable-background-timer-throttling",

        "--disable-backgrounding-occluded-windows",

        "--disable-renderer-backgrounding",

        "--disable-notifications",

        "--disable-popup-blocking",

        "--disable-translate",

        "--disable-features=Translate",

        # ====================================================
        # CORREÇÃO PRINCIPAL
        # ====================================================

        "--no-first-run",

        "--no-default-browser-check",

        # ====================================================
        # AUTOPLAY
        # ====================================================

        "--autoplay-policy=no-user-gesture-required",

        # ====================================================
        # TELA
        # ====================================================

        "--start-fullscreen",

        "--kiosk",

        f"--window-size={WIDTH},{HEIGHT}",

        "--window-position=0,0",

        # ====================================================
        # PERFIL
        # ====================================================

        f"--user-data-dir={CHROMIUM_PROFILE}",

        # ====================================================
        # SITE
        # ====================================================

        TARGET_URL,
    ]

    log(
        f"Iniciando Chromium: {browser}"
    )

    log(
        f"Perfil: {CHROMIUM_PROFILE}"
    )

    log(
        f"Site: {TARGET_URL}"
    )

    BROWSER = subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def browser_reader(proc):

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
        target=browser_reader,
        args=(BROWSER,),
        daemon=True
    ).start()

    time.sleep(3)

    if BROWSER.poll() is not None:

        raise RuntimeError(
            "Chromium encerrou imediatamente. "
            f"Código: {BROWSER.returncode}"
        )

    log(
        "Chromium iniciado corretamente."
    )


# ============================================================
# HTML PLAYER
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
    width: 100%;
    height: 100%;
    margin: 0;
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
    color: white;
    font: 14px Arial, sans-serif;
    text-shadow: 0 1px 3px black;
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

const video =
    document.getElementById("video");

const msg =
    document.getElementById("msg");

const source =
    "/stream.m3u8";


function ready() {

    msg.textContent = "";

    video.play().catch(
        () => {}
    );
}


if (
    video.canPlayType(
        "application/vnd.apple.mpegurl"
    )
) {

    video.src = source;

    video.addEventListener(
        "loadedmetadata",
        ready,
        {once: true}
    );

    video.play().catch(
        () => {}
    );

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

    hls.loadSource(source);

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
                "Reconectando...";

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
        "HLS não é suportado.";

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

                try:
                    self.wfile.write(data)
                except Exception:
                    pass

        def send_file(
            self,
            path,
            content_type
        ):

            try:

                data = path.read_bytes()

                self.send_data(
                    data,
                    content_type
                )

            except FileNotFoundError:

                self.send_data(
                    b"Not found",
                    "text/plain; charset=utf-8",
                    404
                )

            except Exception as exc:

                log(
                    f"Erro HTTP: {exc}"
                )

                self.send_data(
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

        def do_GET(self):
            self.handle_request()

        def do_HEAD(self):
            self.handle_request()

        def handle_request(self):

            parsed = urlparse(
                self.path
            )

            path = parsed.path

            # =================================================
            # PLAYER
            # =================================================

            if path in (
                "/",
                "/index.html"
            ):

                self.send_data(
                    HTML_PAGE.encode(
                        "utf-8"
                    ),
                    "text/html; charset=utf-8"
                )

                return

            # =================================================
            # HEALTH / STATUS
            # =================================================

            if path in (
                "/health",
                "/healthz",
                "/status"
            ):

                payload = json.dumps(
                    get_status(),
                    ensure_ascii=False
                ).encode("utf-8")

                self.send_data(
                    payload,
                    "application/json; charset=utf-8"
                )

                return

            # =================================================
            # M3U8
            # =================================================

            if path == "/stream.m3u8":

                self.send_file(
                    HLS_PLAYLIST,
                    "application/vnd.apple.mpegurl"
                )

                return

            # =================================================
            # TS
            # =================================================

            if (
                path.startswith(
                    "/segment_"
                )
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

                    self.send_file(
                        segment,
                        "video/mp2t"
                    )

                else:

                    self.send_data(
                        b"Not found",
                        "text/plain; charset=utf-8",
                        404
                    )

                return

            self.send_data(
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
        f"Servidor HTTP iniciado "
        f"na porta {PORT}."
    )


# ============================================================
# FFMPEG / HLS
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

    # ========================================================
    # IMPORTANTE:
    # LIMPA OS ARQUIVOS ANTIGOS ANTES DE CRIAR O NOVO HLS.
    # ========================================================

    clean_stream()

    command = [

        "ffmpeg",

        "-hide_banner",

        "-loglevel",
        "warning",

        "-nostdin",

        # ====================================================
        # CAPTURA DA TELA
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
        # CAPTURA DO ÁUDIO
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
        str(
            HLS_SEGMENT_PATTERN
        ),

        # ====================================================
        # ESTE É O M3U8
        # ====================================================

        str(HLS_PLAYLIST),
    ]

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY

    log(
        "Iniciando FFmpeg/HLS..."
    )

    log(
        f"M3U8 local: {HLS_PLAYLIST}"
    )

    FFMPEG = subprocess.Popen(
        command,
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
        daemon=True
    ).start()

    time.sleep(1)

    if FFMPEG.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou imediatamente. "
            f"Código: {FFMPEG.returncode}"
        )

    log(
        "FFmpeg/HLS iniciado."
    )


# ============================================================
# AGUARDAR M3U8
# ============================================================

def wait_for_hls(
    timeout=40
):

    deadline = (
        time.time()
        + timeout
    )

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

                log(
                    "======================================"
                )

                log(
                    "M3U8 GERADO COM SUCESSO"
                )

                log(
                    f"Arquivo: {HLS_PLAYLIST}"
                )

                log(
                    "======================================"
                )

                return True

        time.sleep(0.5)

    log(
        "Timeout aguardando geração do M3U8."
    )

    return False


# ============================================================
# ATUALIZAR LINK DO WORKER
# ============================================================

def update_worker_url():

    global PUBLIC_M3U8_URL

    if not TUNNEL_URL:

        return False

    PUBLIC_M3U8_URL = (
        TUNNEL_URL.rstrip("/")
        + "/stream.m3u8"
    )

    # ========================================================
    # ESTE É O LINK M3U8 PÚBLICO
    # ========================================================

    log(
        "======================================"
    )

    log(
        "LINK M3U8 PÚBLICO:"
    )

    log(
        PUBLIC_M3U8_URL
    )

    log(
        "======================================"
    )

    # Se não houver Worker configurado,
    # o link público continua funcionando.
    if not WORKER_UPDATE_URL:

        log(
            "WORKER_UPDATE_URL não configurado."
        )

        return True

    try:

        import urllib.request

        payload = json.dumps(
            {
                "m3u8": PUBLIC_M3U8_URL,
                "url": PUBLIC_M3U8_URL,
                "stream_url": PUBLIC_M3U8_URL,
            }
        ).encode("utf-8")

        headers = {
            "Content-Type":
                "application/json",
        }

        if WORKER_TOKEN:

            headers[
                "Authorization"
            ] = (
                "Bearer "
                + WORKER_TOKEN
            )

        request = (
            urllib.request.Request(
                WORKER_UPDATE_URL,
                data=payload,
                headers=headers,
                method="POST",
            )
        )

        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            result = response.read(
                4096
            ).decode(
                "utf-8",
                errors="replace"
            )

            log(
                "Worker atualizado: "
                f"HTTP {response.status}"
            )

            if result:
                log(
                    f"Worker: {result}"
                )

        return True

    except Exception as exc:

        log(
            "Erro atualizando Worker: "
            f"{exc}"
        )

        return False


# ============================================================
# CLOUDFLARE QUICK TUNNEL
# ============================================================

def start_tunnel():

    global TUNNEL
    global TUNNEL_URL
    global PUBLIC_M3U8_URL

    if not command_exists(
        "cloudflared"
    ):

        log(
            "cloudflared não encontrado."
        )

        return

    stop_process(
        TUNNEL,
        "Cloudflare Tunnel"
    )

    TUNNEL = None
    TUNNEL_URL = ""
    PUBLIC_M3U8_URL = ""

    command = [
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
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def reader(proc):

        global TUNNEL_URL
        global PUBLIC_M3U8_URL

        pattern = re.compile(
            r"https://"
            r"[a-zA-Z0-9.-]+"
            r"\.trycloudflare\.com"
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

                    url = match.group(0)

                    with state_lock:

                        TUNNEL_URL = url

                        PUBLIC_M3U8_URL = (
                            url.rstrip("/")
                            + "/stream.m3u8"
                        )

                    log(
                        "======================================"
                    )

                    log(
                        "TUNNEL PÚBLICO:"
                    )

                    log(
                        TUNNEL_URL
                    )

                    log(
                        "M3U8 PÚBLICO:"
                    )

                    log(
                        PUBLIC_M3U8_URL
                    )

                    log(
                        "======================================"
                    )

                    # Atualiza Worker.
                    update_worker_url()

        except Exception:
            pass

    threading.Thread(
        target=reader,
        args=(TUNNEL,),
        daemon=True
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

    m3u8_exists = (
        HLS_PLAYLIST.exists()
        and HLS_PLAYLIST.stat().st_size > 0
    )

    return {

        "ok":
            browser_alive
            and ffmpeg_alive
            and m3u8_exists,

        "browser":
            browser_alive,

        "ffmpeg":
            ffmpeg_alive,

        "tunnel":
            tunnel_alive,

        "m3u8":
            m3u8_exists,

        "m3u8_local":
            f"http://127.0.0.1:{PORT}/stream.m3u8",

        "m3u8_public":
            PUBLIC_M3U8_URL,

        "tunnel_url":
            TUNNEL_URL,

        "display":
            DISPLAY,

        "target_url":
            TARGET_URL,

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
                "Chromium encerrou."
            )

            restart_browser()


# ============================================================
# MONITOR FFMPEG
# ============================================================

def monitor_ffmpeg():

    while not stop_event.is_set():

        time.sleep(5)

        if FFMPEG is None:
            continue

        if FFMPEG.poll() is not None:

            log(
                "FFmpeg encerrou."
            )

            if stop_event.is_set():
                break

            try:

                start_ffmpeg()

                if wait_for_hls(40):

                    update_worker_url()

            except Exception as exc:

                log(
                    "Erro reiniciando FFmpeg: "
                    f"{exc}"
                )


# ============================================================
# MONITOR TUNNEL
# ============================================================

def monitor_tunnel():

    while not stop_event.is_set():

        time.sleep(10)

        if TUNNEL is None:
            continue

        if TUNNEL.poll() is not None:

            log(
                "Cloudflare Tunnel encerrou."
            )

            start_tunnel()


# ============================================================
# MONITOR HLS
# ============================================================

def monitor_hls():

    while not stop_event.is_set():

        time.sleep(10)

        if not HLS_PLAYLIST.exists():
            continue

        try:

            age = (
                time.time()
                - HLS_PLAYLIST.stat().st_mtime
            )

            if age > 20:

                log(
                    "Aviso: M3U8 sem atualização "
                    f"há {int(age)} segundos."
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

    signal.signal(
        signal.SIGINT,
        cleanup
    )

    signal.signal(
        signal.SIGTERM,
        cleanup
    )


# ============================================================
# MAIN
# ============================================================

def main():

    log(
        "=================================================="
    )

    log(
        "WEBTV INICIANDO"
    )

    log(
        f"TARGET: {TARGET_URL}"
    )

    log(
        f"DISPLAY: {DISPLAY}"
    )

    log(
        f"RESOLUÇÃO: {WIDTH}x{HEIGHT}@{FPS}"
    )

    log(
        f"PORTA: {PORT}"
    )

    log(
        f"PERFIL: {CHROMIUM_PROFILE}"
    )

    log(
        "=================================================="
    )

    install_signal_handlers()

    try:

        # ====================================================
        # 1. Limpar SOMENTE HLS antigo
        # ====================================================

        clean_stream()

        # ====================================================
        # 2. Xvfb
        # ====================================================

        start_xvfb()

        # ====================================================
        # 3. PulseAudio
        # ====================================================

        start_pulseaudio()

        # ====================================================
        # 4. HTTP
        # ====================================================

        start_http()

        # ====================================================
        # 5. Chromium
        # ====================================================

        start_chromium()

        # Dá tempo para o site carregar.
        time.sleep(5)

        # ====================================================
        # 6. FFmpeg + M3U8
        # ====================================================

        start_ffmpeg()

        if not wait_for_hls(40):

            log(
                "ATENÇÃO: M3U8 ainda não foi criado."
            )

        # ====================================================
        # 7. CLOUDFLARE
        # ====================================================

        start_tunnel()

        # ====================================================
        # 8. MONITORES
        # ====================================================

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
            target=monitor_hls,
            daemon=True
        ).start()

        # ====================================================
        # 9. LOOP PRINCIPAL
        # ====================================================

        log(
            "=================================================="
        )

        log(
            "WEBTV RODANDO"
        )

        log(
            f"PLAYER: "
            f"http://127.0.0.1:{PORT}/"
        )

        log(
            f"M3U8 LOCAL: "
            f"http://127.0.0.1:{PORT}/stream.m3u8"
        )

        log(
            f"STATUS: "
            f"http://127.0.0.1:{PORT}/status"
        )

        log(
            "=================================================="
        )

        while not stop_event.is_set():

            time.sleep(1)

    except KeyboardInterrupt:

        pass

    except Exception as exc:

        log(
            "ERRO FATAL: "
            f"{exc}"
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
