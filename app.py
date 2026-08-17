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


    document.body.innerHTML =
        '<div style="' +
        'color:white;' +
        'font-family:Arial;' +
        'text-align:center;' +
        'padding:30px">' +
        'Seu navegador não suporta reprodução HLS.' +
        '</div>';
}


iniciarPlayer();

</script>

</body>

</html>
"""

    with open(
        os.path.join(
            STREAM_DIR,
            "index.html"
        ),
        "w",
        encoding="utf-8"
    ) as arquivo:

        arquivo.write(html)


    # --------------------------------------------------------
    # PLAYLIST INICIAL
    # --------------------------------------------------------

    with open(
        os.path.join(
            STREAM_DIR,
            "live.m3u8"
        ),
        "w",
        encoding="utf-8"
    ) as arquivo:

        arquivo.write(
            "#EXTM3U\n"
        )

    log("Stream preparado.")


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("")
    log("[2] Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    processo = subprocess.Popen(
        [
            "Xvfb",
            DISPLAY,
            "-screen",
            "0",
            f"{WIDTH}x{HEIGHT}x24",
            "-ac",
            "-nolisten",
            "tcp"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(processo)

    time.sleep(3)

    if processo.poll() is not None:

        raise RuntimeError(
            "Xvfb não iniciou."
        )

    log(
        "Xvfb iniciado:",
        DISPLAY,
        f"{WIDTH}x{HEIGHT}"
    )


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("")
    log("[3] Iniciando PulseAudio...")

    pulse_runtime = "/tmp/pulse"

    os.makedirs(
        pulse_runtime,
        exist_ok=True
    )

    os.environ["PULSE_RUNTIME_PATH"] = pulse_runtime

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        check=False
    )

    time.sleep(3)


    teste = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True
    )

    if teste.returncode != 0:

        log(teste.stderr)

        raise RuntimeError(
            "PulseAudio não iniciou."
        )


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

        log("Criando sink virtual WebTV...")

        criar = subprocess.run(
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

        if criar.returncode != 0:

            log(criar.stdout)
            log(criar.stderr)

            raise RuntimeError(
                "Não foi possível criar o áudio WebTV."
            )


    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        check=False
    )

    os.environ["PULSE_SINK"] = "webtv"

    time.sleep(2)


    fontes = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ],
        capture_output=True,
        text=True
    )

    log("")
    log("Fontes de áudio:")
    log(fontes.stdout)


    if "webtv.monitor" not in fontes.stdout:

        raise RuntimeError(
            "webtv.monitor não foi encontrado."
        )


    log("Áudio WebTV OK.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_http():

    log("")
    log("[4] Iniciando servidor HTTP...")

    servidor = subprocess.Popen(
        [
            "python3",
            "-m",
            "http.server",
            str(HTTP_PORT),
            "--directory",
            STREAM_DIR,
            "--bind",
            "0.0.0.0"
        ]
    )

    processos.append(servidor)

    time.sleep(2)

    if servidor.poll() is not None:

        raise RuntimeError(
            "Servidor HTTP encerrou."
        )

    log(
        "Servidor HTTP funcionando na porta",
        HTTP_PORT
    )


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_process

    log("")
    log("[5] Iniciando FFmpeg...")

    arquivo_m3u8 = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    comando = [

        "ffmpeg",

        "-y",

        # ----------------------------------------------------
        # ÁUDIO
        # ----------------------------------------------------

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ----------------------------------------------------
        # VÍDEO
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # VÍDEO ENCODE
        # ----------------------------------------------------

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-tune",
        "zerolatency",

        "-pix_fmt",
        "yuv420p",

        "-profile:v",
        "main",

        "-r",
        str(FPS),

        "-g",
        "60",

        "-keyint_min",
        "60",

        # ----------------------------------------------------
        # ÁUDIO ENCODE
        # ----------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        # ----------------------------------------------------
        # HLS
        # ----------------------------------------------------

        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "6",

        "-hls_flags",
        "delete_segments+append_list",

        "-hls_segment_filename",

        os.path.join(
            STREAM_DIR,
            "segment_%05d.ts"
        ),

        arquivo_m3u8
    ]


    ffmpeg_process = subprocess.Popen(
        comando,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    time.sleep(5)


    if ffmpeg_process.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou antes de iniciar o HLS."
        )


    log("FFmpeg funcionando.")
    log("HLS:", arquivo_m3u8)


# ============================================================
# TÚNEL LOCALHOST.RUN
# ============================================================

def iniciar_tunel():

    global tunnel_process
    global URL_PUBLICA

    log("")
    log("[6] Iniciando túnel público...")
    log("")


    comando = [

        "ssh",

        "-T",

        "-o",
        "StrictHostKeyChecking=no",

        "-o",
        "UserKnownHostsFile=/dev/null",

        "-o",
        "ServerAliveInterval=30",

        "-o",
        "ServerAliveCountMax=3",

        "-o",
        "ExitOnForwardFailure=yes",

        "-R",
        f"80:127.0.0.1:{HTTP_PORT}",

        "nokey@localhost.run"
    ]


    tunnel_process = subprocess.Popen(
        comando,

        stdout=subprocess.PIPE,

        stderr=subprocess.STDOUT,

        text=True,

        bufsize=1
    )

    processos.append(
        tunnel_process
    )


    def ler_tunel():

        global URL_PUBLICA

        try:

            for linha in iter(
                tunnel_process.stdout.readline,
                ""
            ):

                if not linha:
                    continue

                linha = linha.strip()

                log(
                    "[TUNEL]",
                    linha
                )


                urls = re.findall(
                    r"https://[A-Za-z0-9._-]+\.localhost\.run",
                    linha
                )


                if urls:

                    if URL_PUBLICA is None:

                        URL_PUBLICA = urls[0]

                        log("")
                        log("=" * 70)
                        log("             TRANSMISSÃO ONLINE")
                        log("=" * 70)
                        log("")
                        log("PLAYER:")
                        log(URL_PUBLICA)
                        log("")
                        log("HLS:")
                        log(
                            URL_PUBLICA.rstrip("/")
                            + "/live.m3u8"
                        )
                        log("")
                        log("=" * 70)
                        log("")

        except Exception as erro:

            log(
                "[TUNEL] Erro:",
                erro
            )


    threading.Thread(
        target=ler_tunel,
        daemon=True
    ).start()


    inicio = time.time()

    while (
        URL_PUBLICA is None
        and
        time.time() - inicio < 30
    ):

        if tunnel_process.poll() is not None:

            raise RuntimeError(
                "localhost.run encerrou antes de gerar o link."
            )

        time.sleep(1)


    if URL_PUBLICA is None:

        log("")
        log("=" * 70)
        log("ATENÇÃO")
        log("=" * 70)
        log(
            "O túnel iniciou, mas o endereço ainda não foi identificado."
        )
        log(
            "Confira as linhas [TUNEL] acima."
        )
        log("=" * 70)
        log("")


# ============================================================
# CHROMIUM
# ============================================================

async def iniciar_chromium():

    log("")
    log("[7] Iniciando Chromium...")


    ambiente = os.environ.copy()

    ambiente["DISPLAY"] = DISPLAY

    ambiente["PULSE_SINK"] = "webtv"


    browser = await launch(

        headless=False,

        executablePath="/usr/bin/chromium",

        env=ambiente,

        autoClose=False,

        handleSIGINT=False,

        handleSIGTERM=False,

        handleSIGHUP=False,

        args=[

            "--no-sandbox",

            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",

            "--ozone-platform=x11",

            # ------------------------------------------------
            # TELA CHEIA
            # ------------------------------------------------

            "--kiosk",

            "--start-fullscreen",

            "--start-maximized",

            f"--window-size={WIDTH},{HEIGHT}",

            "--window-position=0,0",

            "--force-device-scale-factor=1",

            # ------------------------------------------------
            # AUTOPLAY
            # ------------------------------------------------

            "--autoplay-policy=no-user-gesture-required",

            # ------------------------------------------------
            # ESTABILIDADE
            # ------------------------------------------------

            "--no-first-run",

            "--no-default-browser-check",

            "--disable-popup-blocking",

            "--disable-notifications",

            "--disable-infobars",

            "--use-gl=swiftshader"
        ]
    )


    log("Chromium iniciado.")

    return browser


# ============================================================
# NAVEGADOR
# ============================================================

async def navegador_async():

    browser = await iniciar_chromium()

    page = await browser.newPage()


    await page.setViewport(
        {
            "width": WIDTH,

            "height": HEIGHT,

            "deviceScaleFactor": 1
        }
    )


    # --------------------------------------------------------
    # LOG DO NAVEGADOR
    # --------------------------------------------------------

    page.on(
        "console",
        lambda mensagem:
        log(
            "[BROWSER]",
            mensagem.text
        )
    )


    page.on(
        "pageerror",
        lambda erro:
        log(
            "[PAGE ERROR]",
            erro
        )
    )


    # --------------------------------------------------------
    # ABRIR SITE
    # --------------------------------------------------------

    log("")
    log("Abrindo site:")
    log(URL_ALVO)
    log("")


    try:

        await page.goto(
            URL_ALVO,
            {
                "waitUntil": "domcontentloaded",
                "timeout": 60000
            }
        )

    except Exception as erro:

        log(
            "[BROWSER] Aviso:",
            erro
        )


    await asyncio.sleep(10)


    # --------------------------------------------------------
    # TENTAR FULLSCREEN
    # --------------------------------------------------------

    try:

        await page.evaluate(
            """
            () => {

                const elemento =
                    document.documentElement;

                if (
                    elemento.requestFullscreen
                ) {

                    elemento
                        .requestFullscreen()
                        .catch(() => {});

                }

            }
            """
        )

    except Exception:
        pass


    # --------------------------------------------------------
    # CLIQUE INICIAL
    # --------------------------------------------------------

    try:

        await page.mouse.click(
            WIDTH // 2,
            HEIGHT // 2
        )

    except Exception:
        pass


    await asyncio.sleep(3)


    # --------------------------------------------------------
    # INICIAR VÍDEOS
    # --------------------------------------------------------

    try:

        resultado = await page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll(
                            "video"
                        )
                    );

                const resposta = [];


                for (
                    const video of videos
                ) {

                    try {

                        video.autoplay = true;

                        video.playsInline = true;


                        const promessa =
                            video.play();


                        if (promessa) {

                            await promessa;

                        }


                        resposta.push({

                            ok: true,

                            paused:
                                video.paused,

                            readyState:
                                video.readyState,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight,

                            currentSrc:
                                video.currentSrc

                        });


                    } catch (erro) {

                        resposta.push({

                            ok: false,

                            erro:
                                String(erro),

                            paused:
                                video.paused,

                            readyState:
                                video.readyState,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight,

                            currentSrc:
                                video.currentSrc

                        });

                    }

                }


                return resposta;

            }
            """
        )


        log(
            "[PLAYER]",
            resultado
        )


    except Exception as erro:

        log(
            "[PLAYER] Erro:",
            erro
        )


    # --------------------------------------------------------
    # MONITOR CONTÍNUO
    # --------------------------------------------------------

    while True:

        await asyncio.sleep(5)


        try:

            await page.evaluate(
                """
                () => {

                    const videos =
                        document.querySelectorAll(
                            "video"
                        );


                    videos.forEach(
                        video => {

                            if (
                                video.paused &&
                                !video.ended
                            ) {

                                video
                                    .play()
                                    .catch(() => {});

                            }

                        }
                    );

                }
                """
            )

        except Exception:

            pass


# ============================================================
# INICIAR
# ============================================================

def iniciar():

    log("")
    log("=" * 70)
    log("                    WEBTV")
    log("=" * 70)
    log("")


    preparar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_http()

    iniciar_ffmpeg()

    iniciar_tunel()


    log("")
    log("=" * 70)


    if URL_PUBLICA:

        log("TRANSMISSÃO PRONTA!")
        log("")
        log("ABRA NO CELULAR:")
        log("")
        log(URL_PUBLICA)
        log("")
        log("HLS DIRETO:")
        log(
            URL_PUBLICA.rstrip("/")
            + "/live.m3u8"
        )

    else:

        log(
            "LINK PÚBLICO AINDA NÃO FOI IDENTIFICADO."
        )


    log("=" * 70)
    log("")


    # --------------------------------------------------------
    # EXECUTA O NAVEGADOR E NÃO DEIXA O JOB TERMINAR
    # --------------------------------------------------------

    try:

        asyncio.run(
            navegador_async()
        )

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("=" * 70)
        log("ERRO NO NAVEGADOR")
        log("=" * 70)
        log(
            repr(erro)
        )
        log("=" * 70)

        encerrar()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    iniciar()
