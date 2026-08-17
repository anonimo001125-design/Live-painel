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
public_url = None


def log(msg):
    print(msg, flush=True)


def stop_process(process):
    if process and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def cleanup(*_):
    log("")
    log("=" * 60)
    log("ENCERRANDO TRANSMISSAO")
    log("=" * 60)

    stop_process(ffmpeg)

    for process in reversed(processes):
        stop_process(process)

    sys.exit(0)


signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)


def start_process(command, **kwargs):
    process = subprocess.Popen(command, **kwargs)
    processes.append(process)
    return process


def prepare_environment():
    STREAM_DIR.mkdir(exist_ok=True)

    for item in STREAM_DIR.glob("*"):
        if item.is_file():
            try:
                item.unlink()
            except Exception:
                pass

    log("Ambiente preparado.")


def start_xvfb():
    log("[1] Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    process = start_process(
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

    time.sleep(3)

    if process.poll() is not None:
        raise RuntimeError("Xvfb nao iniciou.")

    log("Xvfb OK.")


def start_pulseaudio():
    log("[2] Iniciando PulseAudio...")

    runtime = "/tmp/pulse"

    os.makedirs(runtime, exist_ok=True)

    os.environ["PULSE_RUNTIME_PATH"] = runtime

    subprocess.run(
        [
            "pulseaudio",
            "--kill",
        ],
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

    time.sleep(3)

    info = subprocess.run(
        [
            "pactl",
            "info",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if info.returncode != 0:
        raise RuntimeError(
            "PulseAudio nao iniciou: "
            + info.stderr
        )

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
        log("Criando sink de audio WebTV...")

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
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Nao foi possivel criar o sink WebTV: "
                + result.stderr
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
            "webtv.monitor nao foi encontrado."
        )

    log("PulseAudio OK.")


def start_http_server():
    log("[3] Iniciando servidor HTTP...")

    process = start_process(
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

    time.sleep(2)

    if process.poll() is not None:
        raise RuntimeError(
            "Servidor HTTP nao iniciou."
        )

    log(
        "Servidor HTTP ativo na porta "
        + str(HTTP_PORT)
    )


def start_cloudflare():
    global public_url

    log("[4] Iniciando Cloudflare Tunnel...")

    process = start_process(
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

    pattern = re.compile(
        r"https://[a-zA-Z0-9-]+\.trycloudflare\.com"
    )

    deadline = time.time() + 60

    while time.time() < deadline:

        if process.poll() is not None:
            break

        line = process.stdout.readline()

        if not line:
            time.sleep(0.2)
            continue

        line = line.strip()

        log("[CLOUDFLARE] " + line)

        match = pattern.search(line)

        if match:
            public_url = match.group(0)
            break

    if not public_url:
        raise RuntimeError(
            "Cloudflare nao forneceu o link publico."
        )

    player_url = public_url + "/"
    hls_url = public_url + "/live.m3u8"

    (STREAM_DIR / "PUBLIC_URL.txt").write_text(
        "LINK DO PLAYER:\n"
        + player_url
        + "\n\n"
        + "LINK HLS:\n"
        + hls_url
        + "\n",
        encoding="utf-8",
    )

    log("")
    log("=" * 60)
    log("TRANSMISSAO PUBLICA")
    log("=" * 60)
    log("PLAYER:")
    log(player_url)
    log("")
    log("HLS:")
    log(hls_url)
    log("=" * 60)
    log("")


def start_ffmpeg():
    global ffmpeg

    log("[5] Iniciando FFmpeg...")

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

            "-draw_mouse",
            "0",

            "-i",
            f"{DISPLAY}.0",

            "-f",
            "pulse",

            "-i",
            "webtv.monitor",

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
                STREAM_DIR
                / "segment_%05d.ts"
            ),

            str(
                STREAM_DIR
                / "live.m3u8"
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=None,
    )

    if ffmpeg.poll() is not None:
        raise RuntimeError(
            "FFmpeg encerrou imediatamente."
        )

    log("FFmpeg iniciado.")


def wait_for_stream():
    log("[6] Aguardando live.m3u8...")

    playlist = STREAM_DIR / "live.m3u8"

    deadline = time.time() + 30

    while time.time() < deadline:

        if playlist.exists():

            try:
                if playlist.stat().st_size > 0:

                    log("")
                    log("HLS CRIADO COM SUCESSO.")
                    log("")
                    return True

            except Exception:
                pass

        if ffmpeg and ffmpeg.poll() is not None:
            return False

        time.sleep(1)

    return False


def run_browser():
    from playwright.sync_api import sync_playwright

    log("[7] Abrindo Chromium...")

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
            headless=False,
            executable_path="/usr/bin/chromium",

            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
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

                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",

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

        log("Abrindo pagina da WebTV...")

        page.goto(
            URL_ALVO,
            wait_until="domcontentloaded",
            timeout=120000,
        )

        time.sleep(10)

        try:
            page.mouse.click(
                WIDTH // 2,
                HEIGHT // 2,
            )
        except Exception:
            pass

        try:
            page.evaluate(
                """
                () => {
                    const videos =
                        Array.from(
                            document.querySelectorAll("video")
                        );

                    for (const video of videos) {
                        video.autoplay = true;
                        video.playsInline = true;

                        try {
                            video.play();
                        } catch (e) {
                        }
                    }
                }
                """
            )
        except Exception:
            pass

        try:
            page.evaluate(
                """
                async () => {
                    try {
                        if (!document.fullscreenElement) {
                            await document.documentElement.requestFullscreen();
                        }
                    } catch (e) {
                    }
                }
                """
            )
        except Exception:
            pass

        log("")
        log("=" * 60)
        log("TRANSMISSAO ONLINE")
        log("=" * 60)

        if public_url:
            log("LINK DO PLAYER:")
            log(public_url + "/")
            log("")
            log("LINK HLS:")
            log(public_url + "/live.m3u8")

        log("=" * 60)
        log("")

        while True:

            time.sleep(5)

            if page.is_closed():
                raise RuntimeError(
                    "Pagina do Chromium foi fechada."
                )

            try:
                page.evaluate(
                    """
                    () => {
                        const videos =
                            Array.from(
                                document.querySelectorAll("video")
                            );

                        for (const video of videos) {
                            if (
                                video.paused &&
                                !video.ended
                            ) {
                                try {
                                    video.play();
                                } catch (e) {
                                }
                            }
                        }
                    }
                    """
                )
            except Exception:
                pass


def main():

    log("")
    log("=" * 60)
    log("INICIANDO WEBTV")
    log("=" * 60)
    log("")

    prepare_environment()

    start_xvfb()

    start_pulseaudio()

    start_http_server()

    start_cloudflare()

    start_ffmpeg()

    if not wait_for_stream():

        raise RuntimeError(
            "FFmpeg nao criou o arquivo live.m3u8."
        )

    run_browser()


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        cleanup()

    except Exception as error:

        log("")
        log("=" * 60)
        log("ERRO FATAL")
        log("=" * 60)
        log(repr(error))
        log("=" * 60)

        cleanup()
