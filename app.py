import os
import sys
import time
import signal
import subprocess
import threading
import re

from pyppeteer import launch


# ============================================================
# CONFIGURAÇÕES
# ============================================================

STREAM_DIR = "stream"

DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720

FPS = 24

HTTP_PORT = 8080

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

processos = []

browser_global = None
page_global = None
ffmpeg_global = None
tunnel_global = None

encerrando = False


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global encerrando

    if encerrando:
        return

    encerrando = True

    log("")
    log("=" * 70)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 70)

    processos_todos = list(processos)

    if ffmpeg_global:
        processos_todos.append(ffmpeg_global)

    if tunnel_global:
        processos_todos.append(tunnel_global)

    for processo in processos_todos:

        try:
            if processo and processo.poll() is None:
                processo.terminate()
        except Exception:
            pass

    time.sleep(2)

    for processo in processos_todos:

        try:
            if processo and processo.poll() is None:
                processo.kill()
        except Exception:
            pass

    try:

        if browser_global:

            # Não esperamos o Chromium fechar
            # para evitar travar o encerramento.

            pass

    except Exception:
        pass

    log("Transmissão encerrada.")

    sys.exit(0)


signal.signal(
    signal.SIGTERM,
    encerrar
)

signal.signal(
    signal.SIGINT,
    encerrar
)


# ============================================================
# LIMPAR STREAM
# ============================================================

def limpar_stream():

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    log("[1] Limpando stream antigo...")

    for nome in os.listdir(STREAM_DIR):

        caminho = os.path.join(
            STREAM_DIR,
            nome
        )

        try:

            if os.path.isfile(caminho):
                os.remove(caminho)

        except Exception as erro:

            log(
                "[AVISO]",
                erro
            )


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("")
    log("[2] Iniciando Xvfb...")

    os.environ[
        "DISPLAY"
    ] = DISPLAY

    xvfb = subprocess.Popen(
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

    processos.append(
        xvfb
    )

    time.sleep(3)

    if xvfb.poll() is not None:

        raise RuntimeError(
            "Xvfb não conseguiu iniciar."
        )

    log(
        "DISPLAY:",
        DISPLAY
    )

    log(
        "Resolução:",
        f"{WIDTH}x{HEIGHT}"
    )


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("")
    log("[3] Iniciando PulseAudio...")

    runtime = "/tmp/pulse"

    os.makedirs(
        runtime,
        exist_ok=True
    )

    os.environ[
        "PULSE_RUNTIME_PATH"
    ] = runtime

    os.environ[
        "PULSE_SINK"
    ] = "webtv"

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
        [
            "pactl",
            "info"
        ],
        capture_output=True,
        text=True
    )

    if teste.returncode != 0:

        log(
            teste.stderr
        )

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

        log(
            "Criando sink virtual webtv..."
        )

        resultado = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",

                "sink_name=webtv",

                "sink_properties="
                "device.description=WebTV"
            ],

            capture_output=True,

            text=True
        )

        if resultado.returncode != 0:

            log(
                resultado.stderr
            )

            raise RuntimeError(
                "Não foi possível criar webtv."
            )

    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        check=False
    )

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

    log(
        "Áudio pronto."
    )


# ============================================================
# PLAYER PARA O ESPECTADOR
# ============================================================

def criar_player():

    log("")
    log("[4] Criando player HLS...")

    html = r"""
<!DOCTYPE html>

<html lang="pt-BR">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

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

#player {

    position: fixed;

    inset: 0;

    width: 100vw;
    height: 100vh;

    background: #000;
}

video {

    width: 100%;
    height: 100%;

    object-fit: contain;

    background: #000;
}

#fullscreen {

    position: fixed;

    right: 15px;
    bottom: 15px;

    z-index: 9999;

    padding: 12px 18px;

    border: 0;

    border-radius: 8px;

    background: rgba(0,0,0,.75);

    color: white;

    font-size: 15px;
}

#status {

    position: fixed;

    top: 12px;
    left: 12px;

    z-index: 9999;

    padding: 6px 10px;

    border-radius: 6px;

    background: rgba(0,0,0,.7);

    color: white;

    font: 13px Arial;
}

</style>

</head>

<body>

<div id="player">

    <video
        id="video"
        controls
        autoplay
        playsinline
    ></video>

</div>

<div id="status">
    Conectando...
</div>

<button id="fullscreen">
    ⛶ Tela cheia
</button>


<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>

<script>

const video =
    document.getElementById("video");

const player =
    document.getElementById("player");

const status =
    document.getElementById("status");

const button =
    document.getElementById("fullscreen");


function fullscreen() {

    if (
        document.fullscreenElement
    ) {

        document.exitFullscreen()
            .catch(() => {});

        return;
    }

    if (
        player.requestFullscreen
    ) {

        player.requestFullscreen()
            .catch(() => {});

    }

}


button.addEventListener(
    "click",
    fullscreen
);


video.addEventListener(
    "dblclick",
    fullscreen
);


if (
    video.canPlayType(
        "application/vnd.apple.mpegurl"
    )
) {

    video.src =
        "live.m3u8";

    video.play()
        .catch(() => {});

    status.textContent =
        "Ao vivo";

}

else if (
    Hls.isSupported()
) {

    const hls =
        new Hls({

            enableWorker: true,

            lowLatencyMode: false,

            maxBufferLength: 20,

            maxMaxBufferLength: 30,

            backBufferLength: 10,

            liveSyncDurationCount: 3,

            liveMaxLatencyDurationCount: 6,

            fragLoadingMaxRetry: 10,

            manifestLoadingMaxRetry: 10

        });


    hls.loadSource(
        "live.m3u8"
    );

    hls.attachMedia(
        video
    );


    hls.on(
        Hls.Events.MANIFEST_PARSED,
        function() {

            status.textContent =
                "Ao vivo";

            video.play()
                .catch(() => {});

        }
    );


    hls.on(
        Hls.Events.ERROR,
        function(
            event,
            data
        ) {

            console.log(
                "HLS ERROR",
                data
            );

            if (
                data.fatal
            ) {

                status.textContent =
                    "Reconectando...";

                if (
                    data.type ===
                    Hls.ErrorTypes.NETWORK_ERROR
                ) {

                    setTimeout(
                        () => {

                            hls.startLoad();

                        },
                        2000
                    );

                }

                else if (
                    data.type ===
                    Hls.ErrorTypes.MEDIA_ERROR
                ) {

                    hls.recoverMediaError();

                }

            }

        }
    );

}

else {

    status.textContent =
        "HLS não suportado.";

}


document.addEventListener(
    "fullscreenchange",
    function() {

        if (
            document.fullscreenElement
        ) {

            button.textContent =
                "⛶ Sair da tela cheia";

        }

        else {

            button.textContent =
                "⛶ Tela cheia";

        }

    }
);

</script>

</body>

</html>
"""

    caminho = os.path.join(
        STREAM_DIR,
        "index.html"
    )

    with open(
        caminho,
        "w",
        encoding="utf-8"
    ) as arquivo:

        arquivo.write(
            html
        )

    log(
        "Player criado."
    )


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():

    log("")
    log("[5] Iniciando servidor HTTP...")

    servidor = subprocess.Popen(
        [
            "python3",
            "-m",
            "http.server",

            str(HTTP_PORT),

            "--directory",
            STREAM_DIR
        ],

        stdout=subprocess.DEVNULL,

        stderr=subprocess.STDOUT
    )

    processos.append(
        servidor
    )

    time.sleep(2)

    if servidor.poll() is not None:

        raise RuntimeError(
            "Servidor HTTP encerrou."
        )

    log(
        "HTTP ativo na porta",
        HTTP_PORT
    )


# ============================================================
# TÚNEL
# ============================================================

def iniciar_tunel():

    global tunnel_global

    log("")
    log("[6] Iniciando túnel...")

    tunnel_global = subprocess.Popen(
        [
            "ssh",

            "-T",

            "-o",
            "StrictHostKeyChecking=no",

            "-o",
            "ServerAliveInterval=15",

            "-o",
            "ServerAliveCountMax=3",

            "-o",
            "TCPKeepAlive=yes",

            "-o",
            "ExitOnForwardFailure=yes",

            "-o",
            "ConnectTimeout=15",

            "-R",
            f"80:localhost:{HTTP_PORT}",

            "nokey@localhost.run"
        ],

        stdin=subprocess.DEVNULL,

        stdout=subprocess.PIPE,

        stderr=subprocess.STDOUT,

        text=True,

        bufsize=1
    )

    processos.append(
        tunnel_global
    )

    def ler():

        encontrado = False

        for linha in iter(
            tunnel_global.stdout.readline,
            ""
        ):

            if not linha:
                continue

            linha = linha.strip()

            log(
                "[TUNEL]",
                linha
            )

            # Pega somente o domínio lhr.life.
            dominios = re.findall(
                r"https://([A-Za-z0-9-]+\.lhr\.life)",
                linha
            )

            if dominios and not encontrado:

                encontrado = True

                dominio = dominios[0]

                url = (
                    "https://"
                    + dominio
                )

                log("")
                log("=" * 70)
                log("LINK DA TRANSMISSÃO")
                log("=" * 70)
                log("")
                log(
                    "LINK PRINCIPAL:"
                )
                log(
                    url + "/"
                )
                log("")
                log(
                    "LINK HLS:"
                )
                log(
                    url +
                    "/live.m3u8"
                )
                log("")
                log("=" * 70)
                log("")

    threading.Thread(
        target=ler,
        daemon=True
    ).start()

    time.sleep(5)


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_global

    log("")
    log("=" * 70)
    log("INICIANDO FFMPEG")
    log("=" * 70)

    saida = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    comando = [

        "ffmpeg",

        "-y",

        "-hide_banner",

        "-loglevel",
        "warning",

        # ----------------------------------------------------
        # X11
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # ÁUDIO
        # ----------------------------------------------------

        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ----------------------------------------------------
        # REDUÇÃO DE RESOLUÇÃO
        # ----------------------------------------------------

        "-vf",
        "scale=960:540:flags=fast_bilinear",

        # ----------------------------------------------------
        # VÍDEO
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

        "-level",
        "3.1",

        "-b:v",
        "1200k",

        "-maxrate",
        "1400k",

        "-bufsize",
        "2400k",

        "-r",
        str(FPS),

        "-g",
        "48",

        "-keyint_min",
        "48",

        "-sc_threshold",
        "0",

        # ----------------------------------------------------
        # ÁUDIO
        # ----------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        "96k",

        "-ar",
        "44100",

        "-ac",
        "2",

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
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",

        os.path.join(
            STREAM_DIR,
            "segment_%05d.ts"
        ),

        saida
    ]

    log(
        "Comando FFmpeg:"
    )

    log(
        " ".join(comando)
    )

    ffmpeg_global = subprocess.Popen(
        comando
    )

    time.sleep(5)

    if ffmpeg_global.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log(
        "FFmpeg funcionando."
    )


# ============================================================
# DIAGNÓSTICO
# ============================================================

async def diagnosticar_videos(page):

    try:

        resultado = await page.evaluate(
            """
            () => {

                return Array.from(
                    document.querySelectorAll("video")
                ).map(
                    (video, index) => ({

                        index: index,

                        paused:
                            video.paused,

                        muted:
                            video.muted,

                        readyState:
                            video.readyState,

                        networkState:
                            video.networkState,

                        currentTime:
                            video.currentTime,

                        duration:
                            video.duration,

                        width:
                            video.videoWidth,

                        height:
                            video.videoHeight,

                        currentSrc:
                            video.currentSrc || ""

                    })
                );

            }
            """
        )

        log(
            "[PLAYER] Vídeos:",
            resultado
        )

        return resultado

    except Exception as erro:

        log(
            "[PLAYER] Diagnóstico:",
            erro
        )

        return []


# ============================================================
# REPRODUÇÃO
# ============================================================

async def reproduzir_videos(page):

    log("")
    log(
        "[PLAYER] Inicializando reprodução..."
    )

    try:

        resultado = await page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                const saida = [];

                for (
                    const video of videos
                ) {

                    try {

                        video.autoplay = true;

                        video.playsInline = true;

                        video.setAttribute(
                            "playsinline",
                            ""
                        );

                        const promessa =
                            video.play();

                        if (promessa) {

                            await promessa;

                        }

                        saida.push({

                            paused:
                                video.paused,

                            muted:
                                video.muted,

                            readyState:
                                video.readyState,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight,

                            currentTime:
                                video.currentTime

                        });

                    }

                    catch (erro) {

                        saida.push({

                            erro:
                                String(erro)

                        });

                    }

                }

                return saida;
            }
            """
        )

        log(
            "[PLAYER] Resultado:",
            resultado
        )

        return resultado

    except Exception as erro:

        log(
            "[PLAYER] Erro:",
            erro
        )

        return []


# ============================================================
# PREPARAR PLAYER VISUAL
# ============================================================

async def preparar_visual(page):

    log("")
    log(
        "[PLAYER] Ajustando área visual..."
    )

    try:

        await page.addStyleTag(
            {
                "content": """

                html,
                body {

                    width: 100% !important;
                    height: 100% !important;

                    margin: 0 !important;
                    padding: 0 !important;

                    overflow: hidden !important;

                    background: #000 !important;
                }

                """

            }
        )

        log(
            "[PLAYER] Área visual preparada."
        )

    except Exception as erro:

        log(
            "[PLAYER] CSS:",
            erro
        )


# ============================================================
# CLIQUE FÍSICO
# ============================================================

async def clique_fisico_fullscreen(page):

    log("")
    log("=" * 70)
    log("TENTANDO ATIVAR FULLSCREEN PELO CLIQUE FÍSICO")
    log("=" * 70)

    # --------------------------------------------------------
    # IMPORTANTE:
    #
    # Não usamos:
    #
    # video.click()
    #
    # porque o overlay do site intercepta o clique.
    #
    # Usamos coordenadas da tela.
    # --------------------------------------------------------

    x = WIDTH // 2
    y = HEIGHT // 2

    log(
        "[PLAYER] Coordenada:",
        x,
        y
    )

    try:

        # Primeiro clique.
        await page.mouse.click(
            x,
            y
        )

        log(
            "[PLAYER] Primeiro clique realizado."
        )

    except Exception as erro:

        log(
            "[PLAYER] Primeiro clique:",
            erro
        )

    await asyncio.sleep(1)

    try:

        # Segundo clique.
        #
        # O site original aparenta responder melhor
        # quando recebe uma sequência real de interação.
        #

        await page.mouse.click(
            x,
            y
        )

        log(
            "[PLAYER] Segundo clique realizado."
        )

    except Exception as erro:

        log(
            "[PLAYER] Segundo clique:",
            erro
        )

    await asyncio.sleep(3)

    try:

        estado = await page.evaluate(
            """
            () => ({

                fullscreen:
                    !!document.fullscreenElement,

                width:
                    window.innerWidth,

                height:
                    window.innerHeight,

                video:
                    (() => {

                        const v =
                            document.querySelector(
                                "video"
                            );

                        if (!v)
                            return null;

                        const r =
                            v.getBoundingClientRect();

                        return {

                            paused:
                                v.paused,

                            currentTime:
                                v.currentTime,

                            videoWidth:
                                v.videoWidth,

                            videoHeight:
                                v.videoHeight,

                            x:
                                r.x,

                            y:
                                r.y,

                            width:
                                r.width,

                            height:
                                r.height
                        };

                    })()

            });
            """
        )

        log(
            "[PLAYER] Estado:",
            estado
        )

    except Exception as erro:

        log(
            "[PLAYER] Estado fullscreen:",
            erro
        )


# ============================================================
# NAVEGADOR
# ============================================================

async def iniciar_navegador():

    global browser_global
    global page_global

    log("")
    log("[7] Iniciando Chromium...")
    log("")

    browser = await launch(

        headless=False,

        executablePath="/usr/bin/chromium",

        env={
            **os.environ,

            "DISPLAY": DISPLAY,

            "PULSE_SINK": "webtv"
        },

        handleSIGINT=False,

        handleSIGTERM=False,

        handleSIGHUP=False,

        args=[

            "--no-sandbox",

            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",

            # -----------------------------------------------
            # X11
            # -----------------------------------------------

            "--ozone-platform=x11",

            # -----------------------------------------------
            # RENDERIZAÇÃO
            #
            # NÃO DESATIVAMOS GPU COM ARGUMENTOS
            # AGRESSIVOS.
            # -----------------------------------------------

            "--use-gl=swiftshader",

            # -----------------------------------------------
            # AUTOPLAY
            # -----------------------------------------------

            "--autoplay-policy=no-user-gesture-required",

            # -----------------------------------------------
            # JANELA
            # -----------------------------------------------

            "--window-size=1280,720",

            "--window-position=0,0",

            "--force-device-scale-factor=1",

            # -----------------------------------------------
            # ESTABILIDADE
            # -----------------------------------------------

            "--no-first-run",

            "--no-default-browser-check",

            "--disable-popup-blocking",

            "--disable-notifications",

            "--disable-infobars",

            "--disable-background-networking",

            "--disable-background-timer-throttling",

            "--disable-backgrounding-occluded-windows",

            "--disable-renderer-backgrounding"

        ]
    )

    browser_global = browser

    page = await browser.newPage()

    page_global = page

    await page.setViewport(
        {
            "width": WIDTH,

            "height": HEIGHT,

            "deviceScaleFactor": 1
        }
    )

    # ========================================================
    # LOGS
    # ========================================================

    page.on(
        "console",
        lambda mensagem:
            log(
                "[CONSOLE]",
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

    # ========================================================
    # ABRIR
    # ========================================================

    log(
        "Abrindo página:"
    )

    log(
        URL_ALVO
    )

    try:

        await page.goto(
            URL_ALVO,

            {
                "waitUntil": "domcontentloaded",

                "timeout": 120000
            }
        )

    except Exception as erro:

        log(
            "[AVISO] page.goto:",
            erro
        )

    log(
        "Aguardando página..."
    )

    await asyncio.sleep(10)

    # ========================================================
    # VÍDEO
    # ========================================================

    try:

        await page.waitForSelector(
            "video",
            {
                "timeout": 30000
            }
        )

        log(
            "[PLAYER] Elemento video encontrado."
        )

    except Exception as erro:

        log(
            "[PLAYER] video não encontrado:",
            erro
        )

    await diagnosticar_videos(
        page
    )

    await reproduzir_videos(
        page
    )

    await asyncio.sleep(5)

    await diagnosticar_videos(
        page
    )

    # ========================================================
    # VISUAL
    # ========================================================

    await preparar_visual(
        page
    )

    # ========================================================
    # CLIQUE FÍSICO
    # ========================================================

    await clique_fisico_fullscreen(
        page
    )

    # ========================================================
    # ESPERA
    # ========================================================

    await asyncio.sleep(3)

    # ========================================================
    # FFMPEG
    # ========================================================

    iniciar_ffmpeg()

    log("")
    log("=" * 70)
    log("TRANSMISSÃO ATIVA")
    log("=" * 70)
    log("")

    # ========================================================
    # LOOP
    # ========================================================

    ultimo_tempo = 0

    while True:

        await asyncio.sleep(5)

        # ----------------------------------------------------
        # Verifica navegador
        # ----------------------------------------------------

        try:

            paginas = await browser.pages()

            if not paginas:

                log(
                    "[CHROMIUM] Página desapareceu."
                )

                break

        except Exception as erro:

            log(
                "[CHROMIUM] Erro:",
                erro
            )

        # ----------------------------------------------------
        # Verifica vídeo
        # ----------------------------------------------------

        try:

            resultado = await diagnosticar_videos(
                page
            )

            for video in resultado:

                if (
                    not video["paused"]
                    and
                    video["currentTime"] > ultimo_tempo
                ):

                    ultimo_tempo = \
                        video["currentTime"]

                    break

        except Exception as erro:

            log(
                "[PLAYER] Monitor:",
                erro
            )

        # ----------------------------------------------------
        # Verifica FFmpeg
        # ----------------------------------------------------

        if ffmpeg_global:

            codigo = \
                ffmpeg_global.poll()

            if codigo is not None:

                log(
                    "[FFMPEG] Encerrou:",
                    codigo
                )

                log(
                    "[FFMPEG] Reiniciando..."
                )

                time.sleep(2)

                iniciar_ffmpeg()

        # ----------------------------------------------------
        # Verifica túnel
        # ----------------------------------------------------

        if tunnel_global:

            if tunnel_global.poll() is not None:

                log(
                    "[TUNEL] Túnel encerrou."
                )

                log(
                    "[TUNEL] A transmissão local continua."
                )


# ============================================================
# MAIN
# ============================================================

def main():

    log("")
    log("=" * 70)
    log("WEBTV STREAM")
    log("=" * 70)
    log("")

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    criar_player()

    iniciar_servidor()

    iniciar_tunel()

    asyncio.run(
        iniciar_navegador()
    )


if __name__ == "__main__":

    main()
