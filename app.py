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
        stdout=subprocess
