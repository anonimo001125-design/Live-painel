import os
import re
import sys
import time
import signal
import threading
import subprocess
import asyncio

from pyppeteer import launch


# ============================================================
# CONFIGURAÇÕES
# ============================================================

STREAM_DIR = "stream"

DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720

FPS = 30

HTTP_PORT = 8080

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)


# ============================================================
# PROCESSOS
# ============================================================

processos = []

ffmpeg_process = None
tunnel_process = None

URL_PUBLICA = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    log("")
    log("=" * 70)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 70)

    todos = []

    if ffmpeg_process:
        todos.append(ffmpeg_process)

    if tunnel_process:
        todos.append(tunnel_process)

    todos.extend(processos)

    for processo in todos:

        try:
            if processo.poll() is None:
                processo.terminate()
        except Exception:
            pass

    time.sleep(2)

    for processo in todos:

        try:
            if processo.poll() is None:
                processo.kill()
        except Exception:
            pass

    log("Transmissão encerrada.")

    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


# ============================================================
# PREPARAR STREAM
# ============================================================

def preparar_stream():

    log("[1] Preparando pasta de transmissão...")

    os.makedirs(STREAM_DIR, exist_ok=True)

    for nome in os.listdir(STREAM_DIR):

        caminho = os.path.join(STREAM_DIR, nome)

        try:

            if os.path.isfile(caminho):
                os.remove(caminho)

        except Exception:
            pass

    # --------------------------------------------------------
    # PLAYER HTML
    # --------------------------------------------------------

    html = r"""<!DOCTYPE html>
<html lang="pt-BR">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width,
               initial-scale=1,
               maximum-scale=1,
               user-scalable=no">

<title>WebTV</title>

<style>

html,
body {

    margin: 0;
    padding: 0;

    width: 100%;
    height: 100%;

    background: #000;

    overflow: hidden;
}

body {

    display: flex;

    align-items: center;
    justify-content: center;
}

video {

    width: 100vw;
    height: 100vh;

    object-fit: contain;

    background: #000;
}

</style>

</head>

<body>

<video
    id="video"
    controls
    autoplay
    playsinline
    webkit-playsinline>
</video>

<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>

<script>

const video = document.getElementById("video");

const stream = "/live.m3u8";


function iniciarPlayer() {

    /*
     * Safari / navegadores com HLS nativo
     */

    if (
        video.canPlayType(
            "application/vnd.apple.mpegurl"
        )
    ) {

        video.src = stream;

        video.addEventListener(
            "loadedmetadata",
            function () {

                video.play().catch(function () {});

            }
        );

        return;
    }


    /*
     * Chrome / Android / Chromium
     */

    if (
        window.Hls &&
        Hls.isSupported()
    ) {

        const hls = new Hls({

            enableWorker: true,

            lowLatencyMode: false,

            backBufferLength: 30,

            maxBufferLength: 30,

            liveSyncDurationCount: 3

        });


        hls.loadSource(stream);

        hls.attachMedia(video);


        hls.on(
            Hls.Events.MANIFEST_PARSED,
            function () {

                video.play().catch(function () {});

            }
        );


        hls.on(
            Hls.Events.ERROR,
            function (event, data) {

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

            }
        );

        return;
    }


    document.body.innerHTML
