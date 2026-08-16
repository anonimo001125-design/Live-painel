import os
import re
import sys
import time
import signal
import asyncio
import threading
import subprocess

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

# ============================================================
# COLOQUE A URL DO SEU PAINEL AQUI
# ============================================================

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)


# ============================================================
# PROCESSOS
# ============================================================

processos = []

browser_global = None
ffmpeg_global = None

tunnel_url = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# PARAR PROCESSO
# ============================================================

def parar_processo(processo):

    if not processo:
        return

    try:

        if processo.poll() is None:

            processo.terminate()

            try:
                processo.wait(timeout=3)

            except subprocess.TimeoutExpired:

                processo.kill()

    except Exception:
        pass


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*_):

    log("")
    log("==========================================================")
    log("ENCERRANDO TRANSMISSÃO")
    log("==========================================================")

    parar_processo(ffmpeg_global)

    for processo in processos:
        parar_processo(processo)

    log("Transmissão encerrada.")

    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


# ============================================================
# LIMPAR STREAM
# ============================================================

def limpar_stream():

    os.makedirs(STREAM_DIR, exist_ok=True)

    log("[1] Limpando stream anterior...")

    for nome in os.listdir(STREAM_DIR):

        caminho = os.path.join(
            STREAM_DIR,
            nome
        )

        if os.path.isfile(caminho):

            try:
                os.remove(caminho)

            except OSError:
                pass


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("")
    log("[2] Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

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

    processos.append(xvfb)

    time.sleep(3)

    if xvfb.poll() is not None:

        raise RuntimeError(
            "Xvfb não iniciou."
        )

    log(
        f"[X11] Tela virtual pronta: {DISPLAY}"
    )

    log(
        f"[X11] Resolução: {WIDTH}x{HEIGHT}"
    )


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("")
    log("[3] Iniciando PulseAudio...")


    runtime = "/tmp/pulse-webtv"

    os.makedirs(
        runtime,
        exist_ok=True
    )

    os.environ["PULSE_RUNTIME_PATH"] = runtime

    os.environ["PULSE_SINK"] = "webtv"


    # Derruba uma sessão antiga, se existir

    subprocess.run(
        ["pulseaudio", "--kill"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        check=False
    )


    time.sleep(3)


    # Testa PulseAudio

    info = subprocess.run(
        ["pactl", "info"],
        capture_output=True,
        text=True
    )

    if info.returncode != 0:

        raise RuntimeError(
            "PulseAudio não iniciou:\n"
            + info.stderr[-2000:]
        )


    # Lista sinks

    sinks = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sinks"
        ],
        capture_output=True,
        text=True
    ).stdout


    # Cria sink virtual

    if not any(
        "webtv" in linha
        for linha in sinks.splitlines()
    ):

        log(
            "[AUDIO] Criando sink virtual WebTV..."
        )

        resultado = subprocess.run(
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

        if resultado.returncode != 0:

            raise RuntimeError(
                "Não foi possível criar o sink WebTV:\n"
                + resultado.stderr
            )


    # Define WebTV como saída padrão

    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        check=False
    )


    time.sleep(2)


    # Verifica monitor

    fontes = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ],
        capture_output=True,
        text=True
    ).stdout


    log("")
    log("[AUDIO] Fontes:")
    log(fontes)


    if "webtv.monitor" not in fontes:

        raise RuntimeError(
            "webtv.monitor não foi encontrado."
        )


    log(
        "[AUDIO] webtv.monitor pronto."
    )


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():

    log("")
    log("[4] Iniciando servidor HTTP...")


    servidor = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(HTTP_PORT),
            "--directory",
            STREAM_DIR
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(servidor)

    time.sleep(2)


    if servidor.poll() is not None:

        raise RuntimeError(
            "Servidor HTTP encerrou."
        )


    log(
        f"[HTTP] Servidor ativo na porta {HTTP_PORT}"
    )

    log(
        f"[HTTP] http://127.0.0.1:{HTTP_PORT}/live.m3u8"
    )


# ============================================================
# TÚNEL
# ============================================================

def iniciar_tunel():

    global tunnel_url

    log("")
    log(
        "[5] Iniciando túnel público..."
    )


    tunnel = subprocess.Popen(
        [
            "ssh",
            "-tt",

            "-o",
            "StrictHostKeyChecking=no",

            "-o",
            "ServerAliveInterval=30",

            "-o",
            "ServerAliveCountMax=3",

            "-o",
            "ExitOnForwardFailure=yes",

            "-R",
            f"80:localhost:{HTTP_PORT}",

            "nokey@localhost.run"
        ],

        stdout=subprocess.PIPE,

        stderr=subprocess.STDOUT,

        text=True,

        bufsize=1
    )


    processos.append(tunnel)


    def ler_tunel():

        global tunnel_url

        padrao = re.compile(
            r"https://[A-Za-z0-9.-]+(?:/)?"
        )


        try:

            for linha_bruta in iter(
                tunnel.stdout.readline,
                ""
            ):

                linha = linha_bruta.strip()


                if linha:

                    log(
                        "[TUNEL]",
                        linha
                    )


                resultado = padrao.search(
                    linha
                )


                if (
                    resultado
                    and
                    tunnel_url is None
                ):

                    tunnel_url = (
                        resultado.group(0)
                        .rstrip("/")
                    )


                    log("")
                    log(
                        "=========================================================="
                    )
                    log(
                        "         LINK DA TRANSMISSÃO"
                    )
                    log(
                        "=========================================================="
                    )
                    log(
                        tunnel_url
                    )
                    log("")
                    log(
                        "HLS:"
                    )
                    log(
                        tunnel_url
                        + "/live.m3u8"
                    )
                    log(
                        "=========================================================="
                    )
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


    time.sleep(5)


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_global


    log("")
    log(
        "[6] Iniciando FFmpeg..."
    )


    arquivo_saida = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )


    comando = [

        "ffmpeg",

        "-y",


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
        # ÁUDIO
        # ----------------------------------------------------

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",


        # ----------------------------------------------------
        # MAPA
        # ----------------------------------------------------

        "-map",
        "0:v:0",

        "-map",
        "1:a:0",


        # ----------------------------------------------------
        # CODEC VÍDEO
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


        # ----------------------------------------------------
        # FPS / GOP
        # ----------------------------------------------------

        "-r",
        str(FPS),

        "-g",
        str(FPS * 2),

        "-keyint_min",
        str(FPS * 2),

        "-sc_threshold",
        "0",


        # ----------------------------------------------------
        # ÁUDIO
        # ----------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        "128k",

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

        arquivo_saida
    ]


    log("")
    log(
        "[FFMPEG] Capturando:"
    )

    log(
        f"DISPLAY={DISPLAY}"
    )

    log(
        f"RESOLUÇÃO={WIDTH}x{HEIGHT}"
    )

    log(
        "ÁUDIO=webtv.monitor"
    )

    log("")


    ffmpeg_global = subprocess.Popen(
        comando,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )


    time.sleep(5)


    if ffmpeg_global.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou ao iniciar."
        )


    log(
        "[FFMPEG] Transmissão HLS iniciada."
    )


# ============================================================
# NAVEGADOR
# ============================================================

async def iniciar_navegador():

    global browser_global


    log("")
    log(
        "[7] Iniciando Chromium..."
    )


    ambiente = os.environ.copy()

    ambiente["DISPLAY"] = DISPLAY

    ambiente["PULSE_SINK"] = "webtv"


    browser = await launch(

        headless=False,

        executablePath="/usr/bin/chromium",

        env=ambiente,


        handleSIGINT=False,

        handleSIGTERM=False,

        handleSIGHUP=False,


        args=[

            "--no-sandbox",

            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",


            # X11

            "--ozone-platform=x11",


            # ------------------------------------------------
            # AUTOPLAY
            # ------------------------------------------------

            "--autoplay-policy=no-user-gesture-required",


            # ------------------------------------------------
            # TELA CHEIA
            # ------------------------------------------------

            "--kiosk",

            "--start-fullscreen",

            "--window-size=1280,720",

            "--window-position=0,0",

            "--force-device-scale-factor=1",


            # ------------------------------------------------
            # ESTABILIDADE
            # ------------------------------------------------

            "--no-first-run",

            "--no-default-browser-check",

            "--disable-popup-blocking",

            "--disable-notifications",

            "--disable-features=Translate",


            # Evita o Chromium colocar a página
            # em segundo plano.

            "--disable-background-timer-throttling",

            "--disable-backgrounding-occluded-windows",

            "--disable-renderer-backgrounding"
        ]
    )


    browser_global = browser


    log(
        "[BROWSER] Chromium iniciado."
    )


    page = await browser.newPage()


    await page.setViewport(
        {
            "width": WIDTH,
            "height": HEIGHT,
            "deviceScaleFactor": 1
        }
    )


    # ========================================================
    # LOGS DO NAVEGADOR
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
                "[PAGEERROR]",
                erro
            )
    )


    page.on(
        "requestfailed",
        lambda requisicao:
            log(
                "[REQUEST FAILED]",
                requisicao.url,
                requisicao.failure
            )
    )


    page.on(
        "response",

        lambda resposta:

            log(
                "[HTTP ERROR]",
                resposta.status,
                resposta.url
            )

            if resposta.status >= 400
            else None
    )


    # ========================================================
    # ABRIR PAINEL
    # ========================================================

    log("")
    log(
        "[BROWSER] Abrindo painel:"
    )

    log(
        URL_ALVO
    )


    try:

        await page.goto(
            URL_ALVO,
            waitUntil="domcontentloaded",
            timeout=120000
        )

    except Exception as erro:

        log(
            "[BROWSER] Aviso ao abrir:",
            erro
        )


    log(
        "[BROWSER] Aguardando painel carregar..."
    )


    await asyncio.sleep(10)


    # ========================================================
    # CSS PARA OCUPAR TODA A TELA
    # ========================================================

    try:

        await page.addStyleTag(
            content="""

            html,
            body {

                margin: 0 !important;

                padding: 0 !important;

                width: 100% !important;

                height: 100% !important;

                overflow: hidden !important;

                background: #000 !important;
            }

            """
        )

    except Exception:
        pass


    # ========================================================
    # F11
    # ========================================================

    log(
        "[BROWSER] Forçando tela cheia..."
    )


    subprocess.run(
        [
            "xdotool",
            "search",
            "--onlyvisible",
            "--class",
            "chromium",
            "windowactivate",
            "--sync"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


    subprocess.run(
        [
            "xdotool",
            "key",
            "F11"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


    await asyncio.sleep(3)


    # ========================================================
    # FUNÇÃO DE REPRODUÇÃO
    # ========================================================

    async def reproduzir_video():

        resultado = await page.evaluate(
            """

            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll(
                            "video"
                        )
                    );


                if (
                    videos.length === 0
                ) {

                    return {

                        videos: 0,

                        erro:
                            "Nenhum elemento <video> encontrado."
                    };

                }


                // --------------------------------------------
                // Encontrar vídeo VISÍVEL
                // --------------------------------------------

                const visiveis =
                    videos.filter(
                        video => {

                            const rect =
                                video.getBoundingClientRect();

                            const style =
                                getComputedStyle(
                                    video
                                );

                            return (

                                rect.width > 10

                                &&

                                rect.height > 10

                                &&

                                style.display !== "none"

                                &&

                                style.visibility !==
                                "hidden"

                            );

                        }
                    );


                // --------------------------------------------
                // Maior vídeo
                // --------------------------------------------

                visiveis.sort(
                    (a, b) => {

                        const ra =
                            a.getBoundingClientRect();

                        const rb =
                            b.getBoundingClientRect();


                        return (

                            (
                                rb.width *
                                rb.height
                            )

                            -

                            (
                                ra.width *
                                ra.height
                            )

                        );

                    }
                );


                const video =
                    visiveis[0]
                    ||
                    videos[0];


                // --------------------------------------------
                // Configuração
                // --------------------------------------------

                try {
                    video.autoplay = true;
                } catch(e) {}


                try {
                    video.playsInline = true;
                } catch(e) {}


                /*
                 * Primeiro usamos muted.
                 *
                 * Isso evita bloqueio de autoplay.
                 */

                try {
                    video.muted = true;
                } catch(e) {}


                // --------------------------------------------
                // Carregar
                // --------------------------------------------

                if (
                    video.readyState === 0
                ) {

                    try {
                        video.load();
                    } catch(e) {}

                }


                // --------------------------------------------
                // PLAY
                // --------------------------------------------

                let erroPlay = null;


                try {

                    const promessa =
                        video.play();


                    if (
                        promessa
                    ) {

                        await promessa;

                    }

                } catch(e) {

                    erroPlay =
                        String(e);

                }


                const rect =
                    video.getBoundingClientRect();


                return {

                    videos:
                        videos.length,

                    escolhido:
                        videos.indexOf(
                            video
                        ),

                    paused:
                        video.paused,

                    ended:
                        video.ended,

                    muted:
                        video.muted,

                    readyState:
                        video.readyState,

                    networkState:
                        video.networkState,

                    currentTime:
                        video.currentTime,

                    duration:
                        Number.isFinite(
                            video.duration
                        )
                        ?
                        video.duration
                        :
                        null,

                    currentSrc:
                        video.currentSrc
                        ||
                        video.src
                        ||
                        "",

                    videoWidth:
                        video.videoWidth,

                    videoHeight:
                        video.videoHeight,

                    tela: {

                        width:
                            rect.width,

                        height:
                            rect.height

                    },

                    erroVideo:

                        video.error
                        ?

                        {

                            code:
                                video.error.code,

                            message:
                                video.error.message
                                ||
                                ""

                        }

                        :

                        null,

                    erroPlay:
                        erroPlay
                };

            }

            """
        )


        log(
            "[PLAYER]",
            resultado
        )


        return resultado


    # ========================================================
    # TENTATIVAS INICIAIS
    # ========================================================

    for tentativa in range(1, 5):

        log("")
        log(
            f"[PLAYER] Tentativa {tentativa}/4"
        )


        # Clique real no centro da tela

        try:

            await page.mouse.click(
                WIDTH // 2,
                HEIGHT // 2
            )

        except Exception:
            pass


        # Tenta reprodução via JavaScript

        try:

            resultado =
                await reproduzir_video()

        except Exception as erro:

            log(
                "[PLAYER] Erro:",
                erro
            )


        await asyncio.sleep(5)


    # ========================================================
    # SCREENSHOT
    # ========================================================

    try:

        await page.screenshot(
            {
                "path":
                    os.path.join(
                        STREAM_DIR,
                        "browser_debug.png"
                    )
            }
        )

        log(
            "[DEBUG] Screenshot salvo."
        )

    except Exception as erro:

        log(
            "[DEBUG] Erro screenshot:",
            erro
        )


    # ========================================================
    # MONITOR CONTÍNUO
    # ========================================================

    log("")
    log(
        "[PLAYER] Monitor contínuo ativado."
    )


    while True:

        await asyncio.sleep(10)


        try:

            resultado =
                await reproduzir_video()


            # Se estiver reproduzindo,
            # não fazemos nada agressivo.

            if (
                resultado.get(
                    "readyState",
                    0
                ) >= 2

                and

                resultado.get(
                    "videoWidth",
                    0
                ) > 0
            ):

                log(
                    "[PLAYER] Vídeo possui imagem."
                )

        except Exception as erro:

            log(
                "[PLAYER] Monitor:",
                erro
            )


# ============================================================
# MAIN
# ============================================================

async def main():

    log("")
    log(
        "=========================================================="
    )
    log(
        "                 WEBTV INICIANDO"
    )
    log(
        "=========================================================="
    )


    limpar_stream()


    iniciar_xvfb()


    iniciar_audio()


    iniciar_servidor()


    iniciar_tunel()


    iniciar_ffmpeg()


    await iniciar_navegador()


# ============================================================
# EXECUTAR
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log(
            "=========================================================="
        )
        log(
            "ERRO FATAL"
        )
        log(
            "=========================================================="
        )

        log(
            repr(erro)
        )

        encerrar()
