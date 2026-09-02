#!/usr/bin/env python3

import os
import re
import sys
import time
import signal
import shutil
import threading
import subprocess
import json
import urllib.request
import urllib.error
import queue

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

STREAM_DIR = Path("stream")

PAGE_URL = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

CLOUDFLARED = "cloudflared"


# ============================================================
# PERFIL PERSISTENTE DO CHROMIUM
# ============================================================
#
# IMPORTANTE:
#
# A versão anterior apagava o perfil do Chromium toda vez que
# o programa iniciava.
#
# Isso apagava cookies, sessões e outros dados do navegador.
#
# Agora o perfil NÃO é apagado.
#
# Se CHROMIUM_PROFILE estiver definido, ele será usado.
#
# Caso contrário:
#
#     ./chromium-profile
#
# será utilizado.
#
# O Chromium guarda cookies e dados do perfil no User Data Dir.
# ============================================================

DEFAULT_CHROMIUM_PROFILE = (
    Path.cwd() / "chromium-profile"
)

CHROMIUM_PROFILE = Path(
    os.environ.get(
        "CHROMIUM_PROFILE",
        str(DEFAULT_CHROMIUM_PROFILE)
    )
).expanduser().resolve()


# ============================================================
# WORKER
# ============================================================

WORKER_UPDATE_URL = os.environ.get(
    "WORKER_UPDATE_URL",
    ""
).strip().rstrip("/")

WORKER_SECRET = os.environ.get(
    "WORKER_SECRET",
    ""
).strip()


# ============================================================
# ESTADO GLOBAL
# ============================================================

stop_event = threading.Event()

xvfb = None
pulse = None
chromium = None
ffmpeg = None
tunnel = None
http_server = None

tunnel_url = None

state_lock = threading.Lock()
tunnel_lock = threading.Lock()
ffmpeg_lock = threading.Lock()
chromium_lock = threading.Lock()


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

            log(
                f"[STOP] Parando {name}..."
            )

            try:
                process.terminate()
            except Exception:
                pass

            try:
                process.wait(timeout=5)

            except subprocess.TimeoutExpired:

                try:
                    process.kill()
                except Exception:
                    pass

                try:
                    process.wait(timeout=3)
                except Exception:
                    pass

    except Exception as e:

        log(
            f"[STOP] Erro em {name}: {e}"
        )


def cleanup():

    global http_server

    stop_event.set()

    line()
    log("ENCERRANDO WEBTV")

    stop_process(
        ffmpeg,
        "FFmpeg"
    )

    stop_process(
        chromium,
        "Chromium"
    )

    stop_process(
        tunnel,
        "Cloudflare Tunnel"
    )

    stop_process(
        pulse,
        "PulseAudio"
    )

    stop_process(
        xvfb,
        "Xvfb"
    )

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


signal.signal(
    signal.SIGINT,
    signal_handler
)

signal.signal(
    signal.SIGTERM,
    signal_handler
)


# ============================================================
# UTILITÁRIOS
# ============================================================

def command_exists(command):

    return shutil.which(command) is not None


def run_command(
    command,
    timeout=30,
    env=None
):

    try:

        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env
        )

    except Exception as e:

        log(
            "[CMD] Erro executando "
            + " ".join(command)
            + ": "
            + str(e)
        )

        return None


# ============================================================
# WORKER - ATUALIZA TÚNEL
# ============================================================

def update_worker_url(url):

    if not WORKER_UPDATE_URL:

        log(
            "[WORKER] WORKER_UPDATE_URL não configurado."
        )

        return False

    if not WORKER_SECRET:

        log(
            "[WORKER] WORKER_SECRET não configurado."
        )

        return False

    url = url.strip().rstrip("/")

    if not re.fullmatch(
        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com",
        url
    ):

        log(
            "[WORKER] URL do túnel rejeitada por formato inválido."
        )

        log(
            "[WORKER] URL recebida: "
            + url
        )

        return False

    endpoint = WORKER_UPDATE_URL

    if not endpoint.endswith("/update"):
        endpoint += "/update"

    payload = json.dumps(
        {
            "url": url
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer " + WORKER_SECRET,
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
            "User-Agent": "WebTV-App/1.0"
        },
        method="POST"
    )

    log(
        "[WORKER] Atualizando túnel..."
    )

    log(
        "[WORKER] Endpoint: "
        + endpoint
    )

    log(
        "[WORKER] Novo túnel: "
        + url
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            body = response.read().decode(
                "utf-8",
                errors="ignore"
            )

            log(
                "[WORKER] HTTP "
                + str(response.status)
            )

            if body:
                log(
                    "[WORKER] "
                    + body
                )

            if 200 <= response.status < 300:

                log(
                    "[WORKER] Túnel registrado com sucesso."
                )

                with state_lock:

                    global tunnel_url

                    tunnel_url = url

                return True

    except urllib.error.HTTPError as e:

        try:

            body = e.read().decode(
                "utf-8",
                errors="ignore"
            )

        except Exception:

            body = ""

        log(
            "[WORKER] HTTP ERROR "
            + str(e.code)
        )

        if body:
            log(
                "[WORKER] "
                + body
            )

        if e.code == 401:

            log(
                "[WORKER] SECRET incorreto ou Authorization "
                "não aceito."
            )

        elif e.code == 403:

            log(
                "[WORKER] Requisição bloqueada com HTTP 403."
            )

        elif e.code == 404:

            log(
                "[WORKER] Endpoint /update não encontrado."
            )

    except Exception as e:

        log(
            "[WORKER] Erro atualizando endereço: "
            + str(e)
        )

    return False


# ============================================================
# TESTA WORKER
# ============================================================

def test_worker():

    if not WORKER_UPDATE_URL:
        return

    base = WORKER_UPDATE_URL

    if base.endswith("/update"):
        base = base[:-7].rstrip("/")

    log(
        "[WORKER] Testando endereço público..."
    )

    log(
        "[WORKER] URL: "
        + base
        + "/"
    )

    result = run_command(
        [
            "curl",
            "-sS",
            "-I",
            "--max-time",
            "15",
            base + "/"
        ],
        timeout=20
    )

    if result is None:
        return

    log(
        "[WORKER] Teste HTTP:"
    )

    if result.stdout.strip():
        log(
            result.stdout.strip()
        )

    if result.stderr.strip():
        log(
            result.stderr.strip()
        )


# ============================================================
# DEPENDÊNCIAS
# ============================================================

def check_dependencies():

    line()

    log(
        "VERIFICANDO DEPENDÊNCIAS"
    )

    required = [
        "Xvfb",
        "pulseaudio",
        "pactl",
        "ffmpeg",
        "curl",
        "cloudflared"
    ]

    missing = []

    for command in required:

        if not command_exists(command):
            missing.append(command)

    browser_found = False

    for browser in [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable"
    ]:

        if command_exists(browser):

            browser_found = True
            break

    if not browser_found:
        missing.append("chromium")

    if missing:

        raise RuntimeError(
            "Programas ausentes: "
            + ", ".join(missing)
        )

    log(
        "Todas as dependências estão instaladas."
    )


# ============================================================
# STREAM
# ============================================================

def clean_stream():

    line()

    log(
        "[1] Limpando stream antigo..."
    )

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
                "[AVISO] Não foi possível remover "
                + str(item)
                + ": "
                + str(e)
            )


# ============================================================
# XVFB
# ============================================================

def start_xvfb():

    global xvfb

    line()

    log(
        "[2] INICIANDO XVFB"
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
            "-noreset"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env
    )

    time.sleep(2)

    if xvfb.poll() is not None:

        raise RuntimeError(
            "Xvfb encerrou durante a inicialização."
        )

    log(
        "Xvfb funcionando."
    )


# ============================================================
# PULSEAUDIO
# ============================================================

def start_pulseaudio():

    global pulse

    line()

    log(
        "[3] INICIANDO PULSEAUDIO"
    )

    env = os.environ.copy()

    env["DISPLAY"] = DISPLAY

    run_command(
        [
            "pulseaudio",
            "--kill"
        ],
        timeout=10
    )

    time.sleep(1)

    run_command(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        timeout=20,
        env=env
    )

    time.sleep(3)

    sinks = run_command(
        [
            "pactl",
            "list",
            "short",
            "sinks"
        ],
        timeout=10
    )

    if sinks is None or "webtv" not in sinks.stdout:

        log(
            "[AUDIO] Criando sink webtv..."
        )

        result = run_command(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV"
            ],
            timeout=15
        )

        if (
            result is not None
            and result.returncode != 0
        ):

            log(
                "[AUDIO] Erro ao criar sink:"
            )

            log(
                result.stderr.strip()
            )

    time.sleep(2)

    sources = run_command(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ],
        timeout=10
    )

    if sources is not None:

        log(
            "[AUDIO] Fontes:"
        )

        if sources.stdout.strip():

            log(
                sources.stdout.strip()
            )

        else:

            log(
                "[AUDIO] Nenhuma fonte encontrada."
            )

    monitor = run_command(
        [
            "pactl",
            "get-source-volume",
            "webtv.monitor"
        ],
        timeout=10
    )

    if (
        monitor is None
        or monitor.returncode != 0
    ):

        raise RuntimeError(
            "webtv.monitor não foi criado."
        )

    log(
        "[AUDIO] webtv.monitor OK."
    )

    log(
        "Áudio pronto."
    )


# ============================================================
# HTML LOCAL
# ============================================================

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="pt-BR">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>WEBTV</title>

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

#status {

    position:fixed;

    left:10px;
    bottom:10px;

    padding:6px 10px;

    background:rgba(0,0,0,.65);

    color:white;

    font-family:Arial,sans-serif;

    font-size:13px;

    border-radius:4px;

    z-index:10;
}

</style>

</head>

<body>

<video
    id="player"
    autoplay
    muted
    playsinline
    controls>
</video>

<div id="status">
    Conectando...
</div>

<script>

const video =
    document.getElementById("player");

const status =
    document.getElementById("status");

let hls = null;
let retryTimer = null;

let retryDelay = 2000;


function statusText(text) {

    status.textContent = text;
}


function scheduleRestart(delay) {

    if (retryTimer !== null) {

        clearTimeout(retryTimer);
    }

    retryTimer = setTimeout(
        () => {

            retryTimer = null;

            startPlayer();

        },
        delay
    );
}


function destroyHls() {

    if (!hls) {
        return;
    }

    try {
        hls.destroy();
    } catch (e) {}

    hls = null;
}


function createHls(source) {

    try {

        destroyHls();

        hls = new Hls({

            liveSyncDurationCount:3,

            liveMaxLatencyDurationCount:6,

            maxLiveSyncPlaybackRate:1.2,

            enableWorker:true,

            lowLatencyMode:false,

            backBufferLength:30,

            manifestLoadingMaxRetry:6,

            levelLoadingMaxRetry:6,

            fragLoadingMaxRetry:6
        });


        hls.loadSource(source);

        hls.attachMedia(video);


        hls.on(
            Hls.Events.MANIFEST_PARSED,
            () => {

                retryDelay = 2000;

                statusText(
                    "Transmissão ativa"
                );

                video.play().catch(
                    () => {}
                );
            }
        );


        hls.on(
            Hls.Events.ERROR,
            (event, data) => {

                if (!data.fatal) {
                    return;
                }

                statusText(
                    "Reconectando..."
                );

                destroyHls();

                scheduleRestart(
                    retryDelay
                );

                retryDelay =
                    Math.min(
                        retryDelay * 2,
                        10000
                    );
            }
        );

    } catch (e) {

        destroyHls();

        statusText(
            "Reconectando..."
        );

        scheduleRestart(2000);
    }
}


function startPlayer() {

    const source =
        "/live.m3u8?v=" +
        Date.now();


    statusText(
        "Conectando..."
    );


    if (
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ) {

        video.src = source;

        video.play().catch(
            () => {}
        );

        statusText(
            "Transmissão ativa"
        );

        return;
    }


    if (window.Hls) {

        createHls(source);

        return;
    }


    const script =
        document.createElement("script");


    script.src =
        "https://cdn.jsdelivr.net/npm/hls.js@latest";


    script.onload = () => {

        if (window.Hls) {

            createHls(source);

        } else {

            scheduleRestart(3000);
        }
    };


    script.onerror = () => {

        statusText(
            "Falha carregando HLS.js"
        );

        scheduleRestart(3000);
    };


    document.head.appendChild(script);
}


video.addEventListener(
    "error",
    () => {

        statusText(
            "Reconectando..."
        );

        scheduleRestart(2000);
    }
);


startPlayer();

</script>

</body>

</html>
"""


# ============================================================
# HTTP LOCAL
# ============================================================

class StreamHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"


    def log_message(self, format, *args):

        log(
            "[HTTP] "
            + format % args
        )


    def common_headers(
        self,
        content_type,
        content_length=None
    ):

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

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, HEAD, OPTIONS"
        )

        self.send_header(
            "Content-Type",
            content_type
        )

        if content_length is not None:

            self.send_header(
                "Content-Length",
                str(content_length)
            )

        self.send_header(
            "Connection",
            "close"
        )


    def send_bytes(
        self,
        data,
        content_type,
        status=200,
        head_only=False
    ):

        try:

            self.send_response(status)

            self.common_headers(
                content_type,
                len(data)
            )

            self.end_headers()

            if data and not head_only:

                self.wfile.write(data)

                self.wfile.flush()

        except (
            BrokenPipeError,
            ConnectionResetError,
            ConnectionAbortedError
        ):

            pass

        except Exception as e:

            log(
                "[HTTP] Erro enviando resposta: "
                + str(e)
            )


    def do_OPTIONS(self):

        try:

            self.send_response(204)

            self.common_headers(
                "text/plain",
                0
            )

            self.end_headers()

        except Exception:
            pass


    def do_HEAD(self):

        path = self.path.split(
            "?",
            1
        )[0]


        if path == "/":

            data = HTML_PAGE.encode(
                "utf-8"
            )

            self.send_bytes(
                data,
                "text/html; charset=utf-8",
                200,
                head_only=True
            )

            return


        if path == "/health":

            playlist = (
                STREAM_DIR /
                "live.m3u8"
            )

            ok = (
                ffmpeg is not None
                and ffmpeg.poll() is None
                and playlist.exists()
            )

            data = (
                b"OK\n"
                if ok
                else
                b"STARTING\n"
            )

            self.send_bytes(
                data,
                "text/plain; charset=utf-8",
                200 if ok else 503,
                head_only=True
            )

            return


        if path == "/status":

            data = build_status().encode()

            self.send_bytes(
                data,
                "text/plain; charset=utf-8",
                200,
                head_only=True
            )

            return


        if path == "/live.m3u8":

            playlist = (
                STREAM_DIR /
                "live.m3u8"
            )

            if not playlist.exists():

                self.send_bytes(
                    b"#EXTM3U\n",
                    "application/vnd.apple.mpegurl",
                    503,
                    head_only=True
                )

                return

            try:

                data = playlist.read_bytes()

                self.send_bytes(
                    data,
                    "application/vnd.apple.mpegurl",
                    200,
                    head_only=True
                )

            except Exception:

                self.send_bytes(
                    b"",
                    "application/vnd.apple.mpegurl",
                    503,
                    head_only=True
                )

            return


        if (
            path.startswith("/segment_")
            and
            path.endswith(".ts")
        ):

            filename = Path(
                path.lstrip("/")
            ).name

            if not re.fullmatch(
                r"segment_\d+\.ts",
                filename
            ):

                self.send_bytes(
                    b"",
                    "text/plain",
                    404,
                    head_only=True
                )

                return

            file_path = (
                STREAM_DIR /
                filename
            )

            if not file_path.exists():

                self.send_bytes(
                    b"",
                    "video/mp2t",
                    404,
                    head_only=True
                )

                return

            try:

                size = file_path.stat().st_size

                self.send_bytes(
                    b"x" * size,
                    "video/mp2t",
                    200,
                    head_only=True
                )

            except Exception:

                self.send_bytes(
                    b"",
                    "video/mp2t",
                    404,
                    head_only=True
                )

            return


        if path == "/favicon.ico":

            self.send_bytes(
                b"",
                "image/x-icon",
                204,
                head_only=True
            )

            return


        self.send_bytes(
            b"",
            "text/plain; charset=utf-8",
            404,
            head_only=True
        )


    def do_GET(self):

        path = self.path.split(
            "?",
            1
        )[0]


        if path == "/health":

            playlist = (
                STREAM_DIR /
                "live.m3u8"
            )

            ok = (
                ffmpeg is not None
                and ffmpeg.poll() is None
                and playlist.exists()
            )

            self.send_bytes(
                b"OK\n"
                if ok
                else
                b"STARTING\n",
                "text/plain; charset=utf-8",
                200 if ok else 503
            )

            return


        if path == "/status":

            self.send_bytes(
                build_status().encode(),
                "text/plain; charset=utf-8"
            )

            return


        if path == "/":

            self.send_bytes(
                HTML_PAGE.encode("utf-8"),
                "text/html; charset=utf-8"
            )

            return


        if path == "/live.m3u8":

            playlist = (
                STREAM_DIR /
                "live.m3u8"
            )

            if not playlist.exists():

                self.send_bytes(
                    b"#EXTM3U\n",
                    "application/vnd.apple.mpegurl",
                    503
                )

                return

            try:

                data = playlist.read_bytes()

                self.send_bytes(
                    data,
                    "application/vnd.apple.mpegurl"
                )

            except Exception as e:

                log(
                    "[HTTP] Erro lendo playlist: "
                    + str(e)
                )

                self.send_bytes(
                    b"#EXTM3U\n",
                    "application/vnd.apple.mpegurl",
                    503
                )

            return


        if (
            path.startswith("/segment_")
            and
            path.endswith(".ts")
        ):

            filename = Path(
                path.lstrip("/")
            ).name

            if not re.fullmatch(
                r"segment_\d+\.ts",
                filename
            ):

                self.send_bytes(
                    b"Not Found",
                    "text/plain",
                    404
                )

                return

            file_path = (
                STREAM_DIR /
                filename
            )

            if not file_path.exists():

                self.send_bytes(
                    b"Not Found",
                    "text/plain",
                    404
                )

                return

            try:

                data = file_path.read_bytes()

                self.send_bytes(
                    data,
                    "video/mp2t"
                )

            except Exception as e:

                log(
                    "[HTTP] Erro lendo segmento: "
                    + str(e)
                )

            return


        if path == "/favicon.ico":

            self.send_bytes(
                b"",
                "image/x-icon",
                204
            )

            return


        self.send_bytes(
            b"Not Found",
            "text/plain; charset=utf-8",
            404
        )


# ============================================================
# STATUS
# ============================================================

def build_status():

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

    with state_lock:

        current_tunnel = (
            tunnel_url or ""
        )

    return (
        "FFmpeg: "
        + str(
            ffmpeg is not None
            and ffmpeg.poll() is None
        )
        + "\n"

        + "Chromium: "
        + str(
            chromium is not None
            and chromium.poll() is None
        )
        + "\n"

        + "HLS: "
        + str(
            playlist.exists()
        )
        + "\n"

        + "Tunnel: "
        + current_tunnel
        + "\n"

        + "Worker: "
        + str(
            bool(WORKER_UPDATE_URL)
        )
        + "\n"

        + "ChromiumProfile: "
        + str(
            CHROMIUM_PROFILE
        )
        + "\n"
    )


# ============================================================
# HTTP
# ============================================================

def start_http():

    global http_server

    line()

    log(
        "[4] INICIANDO SERVIDOR HTTP"
    )

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

    result = run_command(
        [
            "curl",
            "-sS",
            "--max-time",
            "3",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            f"http://127.0.0.1:{PORT}/health"
        ],
        timeout=5
    )

    if result is not None:

        log(
            "Servidor HTTP ativo na porta "
            + str(PORT)
            + "."
        )

        log(
            "[HTTP] Health local: "
            + result.stdout.strip()
        )


# ============================================================
# CHROMIUM
# ============================================================

def find_browser():

    for browser in [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable"
    ]:

        path = shutil.which(browser)

        if path:
            return path

    raise RuntimeError(
        "Chromium não encontrado."
    )


def prepare_chromium_profile():

    line()

    log(
        "[CHROMIUM] Preparando perfil persistente..."
    )

    try:

        CHROMIUM_PROFILE.mkdir(
            parents=True,
            exist_ok=True
        )

    except Exception as e:

        raise RuntimeError(
            "Não foi possível criar o perfil do Chromium: "
            + str(e)
        )

    log(
        "[CHROMIUM] Perfil:"
    )

    log(
        str(CHROMIUM_PROFILE)
    )

    log(
        "[CHROMIUM] O perfil NÃO será apagado."
    )


def start_chromium():

    global chromium

    with chromium_lock:

        line()

        log(
            "[5] INICIANDO CHROMIUM"
        )

        browser = find_browser()

        env = os.environ.copy()

        env["DISPLAY"] = DISPLAY
        env["PULSE_SINK"] = "webtv"

        prepare_chromium_profile()

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

            "--disable-notifications",
            "--disable-infobars",
            "--disable-popup-blocking",

            "--disable-session-crashed-bubble",

            "--autoplay-policy=no-user-gesture-required",

            "--start-fullscreen",
            "--kiosk",

            "--window-size=1280,720",
            "--window-position=0,0",

            # =================================================
            # PERFIL PERSISTENTE
            # =================================================

            "--user-data-dir="
            + str(CHROMIUM_PROFILE),

            PAGE_URL
        ]

        log(
            "[CHROMIUM] Perfil persistente:"
        )

        log(
            str(CHROMIUM_PROFILE)
        )

        log(
            "Abrindo página:"
        )

        log(
            PAGE_URL
        )

        chromium = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env
        )

        time.sleep(6)

        if chromium.poll() is not None:

            raise RuntimeError(
                "Chromium encerrou durante a inicialização."
            )

        log(
            "Chromium iniciado."
        )

        log(
            "Página carregada."
        )

        process_ref = chromium

        def read_logs():

            try:

                for text in process_ref.stderr:

                    text = text.strip()

                    if text:

                        log(
                            "[CHROMIUM] "
                            + text
                        )

            except Exception:
                pass

        threading.Thread(
            target=read_logs,
            daemon=True
        ).start()


# ============================================================
# X11
# ============================================================

def fullscreen():

    line()

    log(
        "[TELA] Ativando tela cheia..."
    )

    if not command_exists("xdotool"):

        log(
            "[TELA] xdotool não encontrado."
        )

        return

    time.sleep(2)

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

        windows = [
            x.strip()
            for x in result.stdout.splitlines()
            if x.strip()
        ]

        if not windows:

            log(
                "[TELA] Janela Chromium não encontrada."
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
            "[TELA] Erro: "
            + str(e)
        )


def test_x11():

    line()

    log(
        "[DIAGNÓSTICO] Testando X11..."
    )

    if not command_exists("import"):

        log(
            "[DIAGNÓSTICO] ImageMagick não instalado."
        )

        return True

    output = (
        STREAM_DIR /
        "debug_screen.png"
    )

    result = run_command(
        [
            "import",
            "-display",
            DISPLAY,
            "-window",
            "root",
            str(output)
        ],
        timeout=15
    )

    if (
        result is not None
        and result.returncode == 0
        and output.exists()
    ):

        log(
            "[DIAGNÓSTICO] Captura X11 OK."
        )

        return True

    log(
        "[DIAGNÓSTICO] Não foi possível capturar X11."
    )

    return False


# ============================================================
# FFMPEG
# ============================================================

def remove_old_hls():

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


def start_ffmpeg():

    global ffmpeg

    with ffmpeg_lock:

        line()

        log(
            "[6] INICIANDO FFMPEG"
        )

        remove_old_hls()

        playlist = (
            STREAM_DIR /
            "live.m3u8"
        )

        segment_pattern = (
            STREAM_DIR /
            "segment_%05d.ts"
        )

        command = [

            "ffmpeg",

            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostdin",
            "-y",

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

            "-thread_queue_size",
            "4096",

            "-f",
            "pulse",

            "-i",
            "webtv.monitor",

            "-map",
            "0:v:0",

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

            "-map",
            "1:a:0",

            "-c:a",
            "aac",

            "-b:a",
            "96k",

            "-ar",
            "44100",

            "-ac",
            "2",

            "-f",
            "hls",

            "-hls_time",
            "2",

            "-hls_list_size",
            "6",

            "-hls_flags",
            "delete_segments+append_list+independent_segments",

            "-hls_segment_filename",
            str(segment_pattern),

            str(playlist)
        ]

        log(
            "FFmpeg configurado."
        )

        env = os.environ.copy()

        env["DISPLAY"] = DISPLAY

        ffmpeg = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )

        process_ref = ffmpeg

        def ffmpeg_logs():

            try:

                for text in process_ref.stdout:

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
                "FFmpeg encerrou durante a inicialização."
            )

        log(
            "FFmpeg funcionando."
        )


def wait_hls(timeout=60):

    line()

    log(
        "[HLS] Aguardando playlist..."
    )

    playlist = (
        STREAM_DIR /
        "live.m3u8"
    )

    started = time.time()

    while (
        time.time() - started
        < timeout
    ):

        if stop_event.is_set():
            return False

        if (
            ffmpeg is not None
            and ffmpeg.poll() is not None
        ):

            return False

        if playlist.exists():

            segments = list(
                STREAM_DIR.glob(
                    "segment_*.ts"
                )
            )

            if segments:

                try:

                    text = playlist.read_text(
                        errors="ignore"
                    )

                    if (
                        "#EXTM3U" in text
                        and
                        "#EXTINF" in text
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
# CLOUDFLARE
# ============================================================

def extract_cloudflare_url(text):

    match = re.search(
        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com",
        text
    )

    if match:
        return match.group(0)

    return None


def read_tunnel_output(
    process,
    output_queue
):

    try:

        for line_text in process.stdout:

            if line_text:

                output_queue.put(
                    line_text.rstrip()
                )

    except Exception:
        pass

    finally:

        output_queue.put(
            None
        )


def start_tunnel():

    global tunnel
    global tunnel_url

    with tunnel_lock:

        line()

        log(
            "[TUNNEL] Iniciando Cloudflare Quick Tunnel..."
        )

        if not command_exists(
            CLOUDFLARED
        ):

            log(
                "[TUNNEL] cloudflared não encontrado."
            )

            return None

        if tunnel is not None:

            stop_process(
                tunnel,
                "Cloudflare Tunnel antigo"
            )

            tunnel = None

        command = [

            CLOUDFLARED,

            "tunnel",

            "--no-autoupdate",

            "--url",

            f"http://127.0.0.1:{PORT}"
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
                "[TUNNEL] Falha iniciando cloudflared: "
                + str(e)
            )

            return None

        output_queue = queue.Queue()

        threading.Thread(
            target=read_tunnel_output,
            args=(
                tunnel,
                output_queue
            ),
            daemon=True
        ).start()

        started = time.time()

        while (
            time.time() - started
            < 60
        ):

            if stop_event.is_set():
                return None

            if tunnel.poll() is not None:

                log(
                    "[TUNNEL] cloudflared encerrou."
                )

                return None

            try:

                line_text = output_queue.get(
                    timeout=1
                )

            except queue.Empty:

                continue

            if line_text is None:

                if tunnel.poll() is not None:
                    return None

                continue

            if line_text:

                log(
                    "[CLOUDFLARE] "
                    + line_text
                )

            found = extract_cloudflare_url(
                line_text
            )

            if found:

                with state_lock:

                    tunnel_url = found

                log(
                    "[TUNNEL] Novo endereço:"
                )

                log(found)

                worker_ok = (
                    update_worker_url(
                        found
                    )
                )

                if worker_ok:

                    log(
                        "[WORKER] Link fixo atualizado."
                    )

                else:

                    log(
                        "[WORKER] ATENÇÃO: túnel funcionando, "
                        "mas o Worker não confirmou a atualização."
                    )

                line()

                log(
                    "TÚNEL INTERNO:"
                )

                log(found)

                log(
                    "HLS DO TÚNEL:"
                )

                log(
                    found
                    + "/live.m3u8"
                )

                line()

                return found

        log(
            "[TUNNEL] URL não encontrada."
        )

        return None


# ============================================================
# MONITOR TÚNEL
# ============================================================

def monitor_tunnel():

    global tunnel_url

    failure_count = 0

    while not stop_event.is_set():

        time.sleep(10)

        if stop_event.is_set():
            break

        current_tunnel = tunnel

        if (
            current_tunnel is not None
            and current_tunnel.poll() is None
        ):

            failure_count = 0

            continue

        failure_count += 1

        line()

        log(
            "[TUNNEL] Cloudflare desconectado."
        )

        log(
            "[TUNNEL] A transmissão local continua."
        )

        log(
            "[TUNNEL] Reconexão "
            + str(failure_count)
        )

        time.sleep(
            min(
                5 * failure_count,
                30
            )
        )

        if stop_event.is_set():
            break

        try:

            new_url = start_tunnel()

            if new_url:

                failure_count = 0

                with state_lock:

                    tunnel_url = new_url

                log(
                    "[TUNNEL] Novo túnel conectado."
                )

        except Exception as e:

            log(
                "[TUNNEL] Erro na reconexão: "
                + str(e)
            )


# ============================================================
# MONITOR FFMPEG
# ============================================================

def monitor_ffmpeg():

    while not stop_event.is_set():

        time.sleep(5)

        current_ffmpeg = ffmpeg

        if current_ffmpeg is None:
            continue

        if current_ffmpeg.poll() is None:
            continue

        line()

        log(
            "[ERRO] FFmpeg encerrou."
        )

        log(
            "[FFMPEG] Tentando reconstruir a transmissão..."
        )

        try:

            start_ffmpeg()

            if wait_hls(60):

                log(
                    "[FFMPEG] Transmissão reconstruída."
                )

            else:

                log(
                    "[FFMPEG] HLS não ficou pronto."
                )

        except Exception as e:

            log(
                "[FFMPEG] Falha ao reiniciar: "
                + str(e)
            )

        time.sleep(3)


# ============================================================
# MONITOR CHROMIUM
# ============================================================

def monitor_chromium():

    global chromium

    while not stop_event.is_set():

        time.sleep(10)

        current_chromium = chromium

        if current_chromium is None:
            continue

        if current_chromium.poll() is None:
            continue

        line()

        log(
            "[AVISO] Chromium encerrou."
        )

        log(
            "[AVISO] Perfil persistente será mantido."
        )

        log(
            "[AVISO] Tentando reiniciar Chromium..."
        )

        try:

            start_chromium()

            time.sleep(3)

            fullscreen()

        except Exception as e:

            log(
                "[CHROMIUM] Falha ao reiniciar: "
                + str(e)
            )


# ============================================================
# MONITOR GERAL
# ============================================================

def monitor_general():

    while not stop_event.is_set():

        time.sleep(30)

        if stop_event.is_set():
            break

        playlist = (
            STREAM_DIR /
            "live.m3u8"
        )

        if not playlist.exists():

            log(
                "[WATCHDOG] Playlist desapareceu."
            )

            continue

        try:

            age = (
                time.time()
                -
                playlist.stat().st_mtime
            )

            if age > 15:

                log(
                    "[WATCHDOG] Playlist sem atualização "
                    + str(round(age))
                    + "s."
                )

        except Exception:
            pass


# ============================================================
# MAIN
# ============================================================

def main():

    line()

    log(
        "WEBTV STREAM"
    )

    log(
        "MODO: X11 + CHROMIUM + FFMPEG + HLS"
    )

    log(
        "TÚNEL: CLOUDFLARE QUICK TUNNEL"
    )

    log(
        "ENDEREÇO PÚBLICO: CLOUDFLARE WORKER"
    )

    line()

    log(
        "[CHROMIUM] Perfil persistente:"
    )

    log(
        str(CHROMIUM_PROFILE)
    )

    if WORKER_UPDATE_URL:

        log(
            "[WORKER] WORKER_UPDATE_URL:"
        )

        log(
            WORKER_UPDATE_URL
        )

    else:

        log(
            "[WORKER] AVISO: WORKER_UPDATE_URL "
            "não configurado."
        )

    if WORKER_SECRET:

        log(
            "[WORKER] Secret configurado."
        )

    else:

        log(
            "[WORKER] AVISO: WORKER_SECRET "
            "não configurado."
        )

    try:

        clean_stream()

        check_dependencies()

        start_xvfb()

        start_pulseaudio()

        start_http()

        start_chromium()

        time.sleep(5)

        test_x11()

        fullscreen()

        time.sleep(3)

        start_ffmpeg()

        if not wait_hls():

            raise RuntimeError(
                "A playlist HLS não foi criada."
            )

        test_worker()

        start_tunnel()

        line()

        log(
            "TRANSMISSÃO ATIVA"
        )

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
                "TÚNEL ATUAL:"
            )

            log(
                tunnel_url
            )

            log(
                "HLS DO TÚNEL:"
            )

            log(
                tunnel_url
                + "/live.m3u8"
            )

        if WORKER_UPDATE_URL:

            worker_public_url = (
                WORKER_UPDATE_URL
            )

            if worker_public_url.endswith(
                "/update"
            ):

                worker_public_url = (
                    worker_public_url[:-7]
                )

            worker_public_url = (
                worker_public_url.rstrip("/")
            )

            line()

            log(
                "LINK FIXO DA WEBTV:"
            )

            log(
                worker_public_url
            )

            log(
                "HLS FIXO:"
            )

            log(
                worker_public_url
                + "/live.m3u8"
            )

            log(
                "HEALTH FIXO:"
            )

            log(
                worker_public_url
                + "/health"
            )

            log(
                "STATUS FIXO:"
            )

            log(
                worker_public_url
                + "/status"
            )

        else:

            line()

            log(
                "[AVISO] Worker não configurado."
            )

        line()

        threading.Thread(
            target=monitor_tunnel,
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

        threading.Thread(
            target=monitor_general,
            daemon=True
        ).start()

        while not stop_event.is_set():

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
