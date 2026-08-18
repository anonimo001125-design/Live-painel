import os
import sys
import time
import signal
import subprocess
import threading
import re

from playwright.sync_api import sync_playwright


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

processos = []

ffmpeg_process = None
tunnel_process = None

ENCERRANDO = False


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global ENCERRANDO

    if ENCERRANDO:
        return

    ENCERRANDO = True

    log("")
    log("=" * 70)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 70)

    processos_para_encerrar = list(processos)

    if ffmpeg_process:
        processos_para_encerrar.append(
            ffmpeg_process
        )

    if tunnel_process:
        processos_para_encerrar.append(
            tunnel_process
        )

    for processo in processos_para_encerrar:

        try:

            if processo and processo.poll() is None:
                processo.terminate()

        except Exception:
            pass

    time.sleep(2)

    for processo in processos_para_encerrar:

        try:

            if processo and processo.poll() is None:
                processo.kill()

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
# PREPARAR STREAM
# ============================================================

def preparar_stream():

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    log("[1] Limpando stream antigo...")

    for nome in os.listdir(
        STREAM_DIR
    ):

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
        "Tela virtual:",
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
            "Criando áudio virtual webtv..."
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

            log(
                resultado.stdout
            )

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

    os.environ[
        "PULSE_SINK"
    ] = "webtv"

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
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():

    log("")
    log("[4] Iniciando servidor HTTP...")

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
        f"Servidor HTTP ativo na porta {HTTP_PORT}."
    )


# ============================================================
# TÚNEL
# ============================================================

def iniciar_tunel():

    global tunnel_process

    log("")
    log("[5] Iniciando túnel público...")
    log("")

    comando = [
        "ssh",

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
    ]

    tunnel_process = subprocess.Popen(
        comando,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(
        tunnel_process
    )

    def ler_tunel():

        encontrou = False

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

                # ------------------------------------------------
                # PEGAR SOMENTE O DOMÍNIO REAL DO TÚNEL
                # ------------------------------------------------

                encontrados = re.findall(
                    r"https://([a-zA-Z0-9-]+\.lhr\.life)",
                    linha
                )

                if encontrados and not encontrou:

                    dominio = encontrados[0]

                    encontrou = True

                    url = (
                        "https://"
                        + dominio
                    )

                    log("")
                    log("=" * 70)
                    log("        LINK DA TRANSMISSÃO")
                    log("=" * 70)
                    log("")
                    log("LINK PRINCIPAL:")
                    log(url)
                    log("")
                    log("LINK HLS:")
                    log(
                        url + "/live.m3u8"
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

    time.sleep(5)


# ============================================================
# REPRODUÇÃO
# ============================================================

def tentar_reproduzir(page):

    log("")
    log(
        "[PLAYER] Tentando reproduzir..."
    )

    try:

        resultado = page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                const resultado = [];

                for (const video of videos) {

                    try {

                        video.autoplay = true;

                        video.playsInline = true;

                        video.setAttribute(
                            "playsinline",
                            ""
                        );

                        let estado = "ok";

                        try {

                            const promessa =
                                video.play();

                            if (promessa) {
                                await promessa;
                            }

                        } catch (erro) {

                            estado = String(
                                erro
                            );
                        }

                        resultado.push({

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
                                video.currentTime,

                            estado:
                                estado
                        });

                    } catch (erro) {

                        resultado.push({
                            erro: String(
                                erro
                            )
                        });
                    }
                }

                return resultado;
            }
            """
        )

        log(
            "[PLAYER] Resultado:",
            resultado
        )

    except Exception as erro:

        log(
            "[PLAYER] Erro:",
            erro
        )


# ============================================================
# FULLSCREEN
# ============================================================

def ativar_tela_cheia(page):

    log("")
    log("=" * 70)
    log("[PLAYER] ATIVANDO FULLSCREEN")
    log("=" * 70)

    try:

        # ----------------------------------------------------
        # PEGAR O VÍDEO
        # ----------------------------------------------------

        video = page.locator(
            "video"
        ).first

        video.wait_for(
            state="visible",
            timeout=30000
        )

        log(
            "[PLAYER] Vídeo encontrado."
        )

        # ----------------------------------------------------
        # PEGAR ÁREA DO VÍDEO
        # ----------------------------------------------------

        box = video.bounding_box()

        if not box:

            raise RuntimeError(
                "Não foi possível obter posição do vídeo."
            )

        log(
            "[PLAYER] Área:",
            box
        )

        centro_x = (
            box["x"]
            +
            box["width"] / 2
        )

        centro_y = (
            box["y"]
            +
            box["height"] / 2
        )

        # ----------------------------------------------------
        # IMPORTANTE:
        #
        # NÃO usamos locator.click().
        #
        # O próprio log mostrou que existe um DIV
        # transparente por cima do vídeo:
        #
        # z-[5000]
        #
        # Então precisamos clicar na TELA,
        # não no elemento video.
        # ----------------------------------------------------

        log(
            "[PLAYER] Movendo mouse para:",
            centro_x,
            centro_y
        )

        page.mouse.move(
            centro_x,
            centro_y
        )

        time.sleep(1)

        # ----------------------------------------------------
        # PRIMEIRO CLIQUE
        # ----------------------------------------------------

        log(
            "[PLAYER] Clique 1..."
        )

        page.mouse.click(
            centro_x,
            centro_y
        )

        time.sleep(0.4)

        # ----------------------------------------------------
        # SEGUNDO CLIQUE
        # ----------------------------------------------------

        log(
            "[PLAYER] Clique 2..."
        )

        page.mouse.click(
            centro_x,
            centro_y
        )

        log(
            "[PLAYER] Dois cliques enviados."
        )

        time.sleep(3)

        # ----------------------------------------------------
        # VERIFICAR
        # ----------------------------------------------------

        estado = page.evaluate(
            """
            () => ({

                fullscreen:
                    !!document.fullscreenElement,

                fullscreenTag:
                    document.fullscreenElement
                        ? document.fullscreenElement.tagName
                        : null,

                width:
                    window.innerWidth,

                height:
                    window.innerHeight
            })
            """
        )

        log(
            "[PLAYER] Estado:",
            estado
        )

        if estado["fullscreen"]:

            log(
                "[PLAYER] ✓ FULLSCREEN ATIVADO"
            )

            return True

        # ----------------------------------------------------
        # TENTAR LOCALIZAR BOTÃO
        # ----------------------------------------------------

        log(
            "[PLAYER] Fullscreen não detectado."
        )

        log(
            "[PLAYER] Procurando controles..."
        )

        seletores = [

            'button[aria-label*="fullscreen" i]',

            'button[title*="fullscreen" i]',

            '[aria-label*="full screen" i]',

            '[title*="full screen" i]',

            '[data-testid*="fullscreen" i]',

            '[class*="fullscreen" i]'
        ]

        for seletor in seletores:

            try:

                botao = page.locator(
                    seletor
                ).first

                if botao.count() == 0:
                    continue

                if not botao.is_visible():
                    continue

                log(
                    "[PLAYER] Controle encontrado:",
                    seletor
                )

                caixa = botao.bounding_box()

                if not caixa:
                    continue

                bx = (
                    caixa["x"]
                    +
                    caixa["width"] / 2
                )

                by = (
                    caixa["y"]
                    +
                    caixa["height"] / 2
                )

                log(
                    "[PLAYER] Clicando controle:",
                    bx,
                    by
                )

                page.mouse.click(
                    bx,
                    by
                )

                time.sleep(3)

                estado = page.evaluate(
                    """
                    () => ({
                        fullscreen:
                            !!document.fullscreenElement,

                        width:
                            window.innerWidth,

                        height:
                            window.innerHeight
                    })
                    """
                )

                log(
                    "[PLAYER] Estado:",
                    estado
                )

                if estado["fullscreen"]:

                    log(
                        "[PLAYER] ✓ FULLSCREEN PELO CONTROLE"
                    )

                    return True

            except Exception as erro:

                log(
                    "[PLAYER] Controle falhou:",
                    erro
                )

        # ----------------------------------------------------
        # ÚLTIMA TENTATIVA: F11
        # ----------------------------------------------------

        log(
            "[PLAYER] Tentando F11..."
        )

        page.keyboard.press(
            "F11"
        )

        time.sleep(2)

        log(
            "[PLAYER] F11 enviado."
        )

        return False

    except Exception as erro:

        log(
            "[PLAYER] Erro fullscreen:",
            erro
        )

        return False


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    global ffmpeg_process

    saida = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    log("")
    log("=" * 70)
    log("INICIANDO FFMPEG")
    log("=" * 70)

    comando = [

        "ffmpeg",

        "-y",

        "-hide_banner",

        # ----------------------------------------------------
        # CAPTURA
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
        # AUDIO
        # ----------------------------------------------------

        "-thread_queue_size",
        "4096",

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ----------------------------------------------------
        # VIDEO
        # ----------------------------------------------------

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
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        # ----------------------------------------------------
        # AUDIO
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
        "5",

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
        "FFmpeg:"
    )

    log(
        " ".join(comando)
    )

    ffmpeg_process = subprocess.Popen(
        comando
    )

    time.sleep(5)

    if ffmpeg_process.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    log(
        "FFmpeg funcionando."
    )


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    log("")
    log("[7] Iniciando Chromium...")
    log("")

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=False,

            args=[

                "--no-sandbox",

                "--disable-setuid-sandbox",

                "--disable-dev-shm-usage",

                "--autoplay-policy=no-user-gesture-required",

                "--no-first-run",

                "--no-default-browser-check",

                "--disable-popup-blocking",

                "--disable-notifications",

                "--window-size=1280,720",

                "--window-position=0,0",

                "--force-device-scale-factor=1",

                "--ozone-platform=x11",

                "--use-gl=swiftshader",

                "--disable-gpu-compositing",

                "--disable-gpu-rasterization",

                "--disable-background-networking",

                "--disable-background-timer-throttling",

                "--disable-backgrounding-occluded-windows",

                "--disable-renderer-backgrounding",

                "--start-maximized",

                "--disable-features=CalculateNativeWinOcclusion"
            ]
        )

        page = browser.new_page(
            viewport={
                "width": WIDTH,
                "height": HEIGHT
            }
        )

        # ----------------------------------------------------
        # LOGS
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # ABRIR SITE
        # ----------------------------------------------------

        log(
            "Abrindo página:"
        )

        log(
            URL_ALVO
        )

        try:

            page.goto(
                URL_ALVO,
                wait_until="commit",
                timeout=120000
            )

        except Exception as erro:

            log(
                "[AVISO]",
                erro
            )

        log(
            "Aguardando página..."
        )

        time.sleep(10)

        # ----------------------------------------------------
        # REPRODUÇÃO
        # ----------------------------------------------------

        tentar_reproduzir(
            page
        )

        time.sleep(3)

        # ----------------------------------------------------
        # FULLSCREEN
        # ----------------------------------------------------

        ativar_tela_cheia(
            page
        )

        # ----------------------------------------------------
        # DIAGNÓSTICO
        # ----------------------------------------------------

        try:

            videos = page.evaluate(
                """
                () => {

                    return Array.from(
                        document.querySelectorAll("video")
                    ).map(v => ({

                        paused:
                            v.paused,

                        muted:
                            v.muted,

                        readyState:
                            v.readyState,

                        width:
                            v.videoWidth,

                        height:
                            v.videoHeight,

                        currentTime:
                            v.currentTime,

                        src:
                            v.currentSrc || ""
                    }));
                }
                """
            )

            log(
                "[PLAYER] Vídeos:",
                videos
            )

        except Exception:
            pass

        # ----------------------------------------------------
        # FFMPEG
        # ----------------------------------------------------

        iniciar_ffmpeg()

        log("")
        log("=" * 70)
        log("TRANSMISSÃO ATIVA")
        log("=" * 70)
        log("")

        # ----------------------------------------------------
        # MONITORAMENTO
        # ----------------------------------------------------

        ultimo_teste_tunel = 0

        while True:

            # ------------------------------------------------
            # FFMPEG
            # ------------------------------------------------

            if (
                ffmpeg_process
                and
                ffmpeg_process.poll()
                is not None
            ):

                log(
                    "[FFMPEG] Processo encerrou."
                )

                log(
                    "[FFMPEG] Reiniciando..."
                )

                time.sleep(2)

                iniciar_ffmpeg()

            # ------------------------------------------------
            # TÚNEL
            # ------------------------------------------------

            if (
                tunnel_process
                and
                tunnel_process.poll()
                is not None
            ):

                log("")
                log(
                    "[TUNEL] Túnel caiu!"
                )

                log(
                    "[TUNEL] A transmissão local continua."
                )

                log(
                    "[TUNEL] O túnel precisa ser reconectado."
                )

                # Não conseguimos substituir facilmente
                # o processo antigo sem duplicar threads.
                #
                # O GitHub Actions continuará registrando
                # o problema no log.

            time.sleep(5)


# ============================================================
# MAIN
# ============================================================

def main():

    log("")
    log("=" * 70)
    log("WEBTV STREAM")
    log("=" * 70)
    log("")

    preparar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_tunel()

    iniciar_navegador()


if __name__ == "__main__":
    main()
