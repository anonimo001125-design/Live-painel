import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

STREAM_DIR = Path("stream")
DISPLAY = ":99"
WIDTH = 1280
HEIGHT = 720
FPS = 30
HTTP_PORT = 8080

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

processes = []
ffmpeg = None


def log(msg):
    print(msg, flush=True)


def stop_process(p):
    if p and p.poll() is None:
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def cleanup(*_):
    log("Encerrando transmissão...")

    for p in reversed(processes):
        stop_process(p)

    stop_process(ffmpeg)

    sys.exit(0)


signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)


def start(cmd, **kwargs):
    p = subprocess.Popen(cmd, **kwargs)
    processes.append(p)
    return p


def prepare():
    STREAM_DIR.mkdir(exist_ok=True)

    for item in STREAM_DIR.glob("*"):
        if item.is_file():
            item.unlink()

    (STREAM_DIR / "index.html").write_text(
        """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>WebTV</title>
</head>

<body style="margin:0;background:#000">

<video
    controls
    autoplay
    playsinline
    style="width:100vw;height:100vh"
    src="/live.m3u8">
</video>

</body>
</html>""",
        encoding="utf-8",
    )


def start_xvfb():

    os.environ["DISPLAY"] = DISPLAY

    p = start(
        [
            "Xvfb",
            DISPLAY,
            "-screen",
            "0",
            f"{WIDTH}x{HEIGHT}x24",
            "-ac",
            "-nolisten",
            "tcp",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    time.sleep(2)

    if p.poll() is not None:
        raise RuntimeError("Xvfb não iniciou.")


def start_pulse():

    runtime = "/tmp/pulse"

    os.makedirs(runtime, exist_ok=True)

    os.environ["PULSE_RUNTIME_PATH"] = runtime

    subprocess.run(
        ["pulseaudio", "--kill"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    time.sleep(2)

    sinks = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sinks",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout

    if "webtv" not in sinks:

        resultado = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if resultado.returncode != 0:

            raise RuntimeError(
                "Não foi possível criar o sink PulseAudio: "
                + resultado.stderr
            )

    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv",
        ],
        check=False,
    )

    os.environ["PULSE_SINK"] = "webtv"

    sources = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout

    if "webtv.monitor" not in sources:

        raise RuntimeError(
            "webtv.monitor não existe."
        )


def start_http():

    p = start(
        [
            sys.executable,
            "-m",
            "http.server",
            str(HTTP_PORT),
            "--directory",
            str(STREAM_DIR),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    time.sleep(1)

    if p.poll() is not None:

        raise RuntimeError(
            "Servidor HTTP não iniciou."
        )


def start_tunnel():

    log("Abrindo túnel público...")

    p = start(
        [
            "cloudflared",
            "tunnel",
            "--url",
            f"http://127.0.0.1:{HTTP_PORT}",
            "--no-autoupdate",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    deadline = time.time() + 40

    pattern = re.compile(
        r"https://[a-z0-9-]+\.trycloudflare\.com"
    )

    public = None

    while time.time() < deadline:

        line = p.stdout.readline()

        if not line:

            if p.poll() is not None:
                break

            time.sleep(0.2)
            continue

        line = line.strip()

        log("[TUNNEL] " + line)

        match = pattern.search(line)

        if match:

            public = match.group(0)

            break

    if not public:

        raise RuntimeError(
            "Cloudflare Tunnel não forneceu uma URL pública."
        )

    log("=" * 60)

    log("LINK DE TRANSMISSÃO:")

    log(
        public + "/live.m3u8"
    )

    log("LINK DO PLAYER:")

    log(
        public + "/"
    )

    log("=" * 60)


def start_ffmpeg():

    global ffmpeg

    ffmpeg = subprocess.Popen(
        [
            "ffmpeg",

            "-hide_banner",

            "-loglevel",
            "warning",

            "-y",

            "-f",
            "x11grab",

            "-framerate",
            str(FPS),

            "-video_size",
            f"{WIDTH}x{HEIGHT}",

            "-i",
            f"{DISPLAY}.0",

            "-f",
            "pulse",

            "-i",
            "webtv.monitor",

            "-c:v",
            "libx264",

            "-preset",
            "ultrafast",

            "-tune",
            "zerolatency",

            "-pix_fmt",
            "yuv420p",

            "-r",
            str(FPS),

            "-g",
            str(FPS * 2),

            "-keyint_min",
            str(FPS * 2),

            "-sc_threshold",
            "0",

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-ar",
            "44100",

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
                STREAM_DIR / "segment_%05d.ts"
            ),

            str(
                STREAM_DIR / "live.m3u8"
            ),
        ],

        stdout=subprocess.DEVNULL,

        stderr=None,
    )

    processes.append(ffmpeg)


def wait_for_playlist(timeout=20):

    playlist = STREAM_DIR / "live.m3u8"

    end = time.time() + timeout

    while time.time() < end:

        if (
            playlist.exists()
            and playlist.stat().st_size > 0
        ):
            return True

        if (
            ffmpeg
            and ffmpeg.poll() is not None
        ):
            return False

        time.sleep(0.5)

    return False


def run_browser():

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=False,

            executable_path="/usr/bin/chromium",

            args=[

                "--no-sandbox",

                "--disable-dev-shm-usage",

                "--ozone-platform=x11",

                "--window-size=1280,720",

                "--window-position=0,0",

                "--start-fullscreen",

                "--kiosk",

                "--autoplay-policy=no-user-gesture-required",

                "--no-first-run",

                "--no-default-browser-check",

                "--disable-notifications",

                "--disable-popup-blocking",

                "--force-device-scale-factor=1",
            ],
        )

        context = browser.new_context(

            viewport={
                "width": WIDTH,
                "height": HEIGHT,
            }
        )

        page = context.new_page()

        log("Abrindo site...")

        page.goto(

            URL_ALVO,

            wait_until="domcontentloaded",

            timeout=120000,
        )

        time.sleep(8)

        try:

            page.evaluate(
                """
                () => {

                    document
                        .querySelectorAll('video')
                        .forEach(v => {

                            v.playsInline = true;

                            v.autoplay = true;

                            v.play().catch(() => {});

                        });

                }
                """
            )

        except Exception:
            pass

        try:

            page.mouse.click(
                WIDTH // 2,
                HEIGHT // 2
            )

        except Exception:
            pass

        try:

            page.evaluate(
                """
                async () => {

                    const
