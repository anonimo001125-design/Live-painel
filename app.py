import os
import sys
import time
import signal
import subprocess
import threading

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


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    global ffmpeg_process

    log("")
    log("=" * 60)
    log("ENCERRANDO TRANSMISSÃO")
    log("=" * 60)

    try:
        if ffmpeg_process and ffmpeg_process.poll() is None:
            ffmpeg_process.terminate()
    except Exception:
        pass

    for processo in processos:

        try:
            if processo.poll() is None:
                processo.terminate()
        except Exception:
            pass

    time.sleep(2)

    for processo in processos:

        try:
            if processo.poll() is None:
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

    log("")
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
    log(
        "[4] Iniciando servidor HTTP..."
    )

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

    log("")
    log(
        "[5] Iniciando túnel público..."
    )

    log("")

    tunnel = subprocess.Popen(
        [
            "ssh",
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

    processos.append(
        tunnel
    )

    def ler_tunel():

        encontrado = False

        try:

            for linha in iter(
                tunnel.stdout.readline,
                ""
            ):

                if not linha:
                    continue

                linha = linha.strip()

                log(
                    "[TUNEL]",
                    linha
                )

                if (
                    "https://" in linha
                    and not encontrado
                ):

                    partes = linha.split()

                    for parte in partes:

                        if parte.startswith(
                            "https://"
                        ):

                            url = parte.strip(
                                ".,;()[]{}<>\"'"
                            )

                            url = url.rstrip("/")

                            encontrado = True

                            log("")
                            log("=" * 60)
                            log(
                                "        LINK DA TRANSMISSÃO"
                            )
                            log("=" * 60)
                            log("")
                            log(
                                "LINK PRINCIPAL:"
                            )
                            log(url)
                            log("")
                            log(
                                "LINK HLS:"
                            )
                            log(
                                url +
                                "/live.m3u8"
                            )
                            log("")
                            log("=" * 60)
                            log("")

                            break

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

    global ffmpeg_process

    log("")
    log(
        "[6] Iniciando FFmpeg..."
    )

    log("")

    saida = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    ffmpeg_cmd = [

        "ffmpeg",
        "-y",

        # ====================================================
        # VÍDEO X11
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
        f"{DISPLAY}.0",

        # ====================================================
        # ÁUDIO PULSEAUDIO
        # ====================================================

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # ====================================================
        # VÍDEO
        # ====================================================

        "-c:v",
        "libx264",

        # Prioridade é fluidez no GitHub Actions.
        "-preset",
        "ultrafast",

        "-tune",
        "zerolatency",

        "-threads",
        "2",

        "-pix_fmt",
        "yuv420p",

        "-profile:v",
        "main",

        "-level",
        "3.1",

        "-r",
        str(FPS),

        "-g",
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        # ====================================================
        # ÁUDIO
        # ====================================================

        "-c:a",
        "aac",

        "-b:a",
        "128k",

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
        "1",

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
        "FFmpeg iniciando..."
    )

    ffmpeg_process = subprocess.Popen(
        ffmpeg_cmd
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
# DIAGNÓSTICO DOS VÍDEOS
# ============================================================

def diagnosticar_videos(page):

    try:

        resultado = page.evaluate(
            """
            () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                return videos.map(
                    (video, index) => ({

                        index: index,

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
                            video.duration,

                        width:
                            video.videoWidth,

                        height:
                            video.videoHeight,

                        currentSrc:
                            video.currentSrc || "",

                        error:
                            video.error
                                ? {
                                    code:
                                        video.error.code,

                                    message:
                                        video.error.message
                                }
                                : null
                    })
                );
            }
            """
        )

        log(
            "[CHROMIUM] Vídeos:",
            resultado
        )

        return resultado

    except Exception as erro:

        log(
            "[CHROMIUM] Diagnóstico:",
            erro
        )

        return []


# ============================================================
# REPRODUÇÃO
# ============================================================

def tentar_reproduzir(page):

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

                for (
                    const video of videos
                ) {

                    try {

                        video.playsInline =
                            true;

                        video.setAttribute(
                            "playsinline",
                            ""
                        );

                        video.autoplay =
                            true;

                        let estado =
                            "ok";

                        try {

                            const promessa =
                                video.play();

                            if (promessa) {
                                await promessa;
                            }

                        } catch (erro) {

                            estado =
                                String(erro);
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
                            erro:
                                String(erro)
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
# DETECTAR PLAYER E FULLSCREEN
# ============================================================

def ativar_tela_cheia(page):

    log("")
    log("=" * 70)
    log(
        "[PLAYER] DETECTANDO ELEMENTO DO PLAYER"
    )
    log("=" * 70)

    time.sleep(5)

    # ========================================================
    # ENCONTRAR VIDEO
    # ========================================================

    try:

        page.wait_for_selector(
            "video",
            state="visible",
            timeout=30000
        )

        log(
            "[PLAYER] <video> encontrado."
        )

    except Exception as erro:

        log(
            "[PLAYER] <video> não encontrado:",
            erro
        )

        return

    # ========================================================
    # DESCOBRIR O QUE ESTÁ SOBRE O VIDEO
    # ========================================================

    try:

        info = page.evaluate(
            """
            () => {

                const video =
                    document.querySelector("video");

                const rect =
                    video.getBoundingClientRect();

                const x =
                    rect.left +
                    rect.width / 2;

                const y =
                    rect.top +
                    rect.height / 2;

                const elementos =
                    document.elementsFromPoint(
                        x,
                        y
                    );

                return {

                    x,
                    y,

                    video: {
                        x: rect.left,
                        y: rect.top,
                        width: rect.width,
                        height: rect.height
                    },

                    elementos:
                        elementos
                            .slice(0, 10)
                            .map(
                                (el, index) => {

                                    const r =
                                        el.getBoundingClientRect();

                                    const estilo =
                                        getComputedStyle(el);

                                    return {

                                        index,

                                        tag:
                                            el.tagName,

                                        id:
                                            el.id || "",

                                        class:
                                            typeof el.className ===
                                            "string"
                                                ? el.className
                                                : "",

                                        width:
                                            r.width,

                                        height:
                                            r.height,

                                        pointerEvents:
                                            estilo.pointerEvents,

                                        cursor:
                                            estilo.cursor
                                    };
                                }
                            )
                };
            }
            """
        )

        log("")
        log(
            "[PLAYER] ELEMENTOS NO CENTRO DO VÍDEO:"
        )

        log(info)

        x = info["x"]
        y = info["y"]

    except Exception as erro:

        log(
            "[PLAYER] Erro descobrindo player:",
            erro
        )

        return

    # ========================================================
    # FOCO
    # ========================================================

    try:

        page.bring_to_front()

    except Exception:
        pass

    # ========================================================
    # DBLCLICK REAL
    # ========================================================

    try:

        log("")
        log(
            "[PLAYER] Executando duplo clique..."
        )

        page.mouse.move(
            x,
            y
        )

        time.sleep(0.5)

        page.mouse.dblclick(
            x,
            y,
            delay=120
        )

        log(
            "[PLAYER] Duplo clique enviado."
        )

    except Exception as erro:

        log(
            "[PLAYER] Erro no duplo clique:",
            erro
        )

    # ========================================================
    # ESPERAR
    # ========================================================

    time.sleep(4)

    # ========================================================
    # VERIFICAR FULLSCREEN
    # ========================================================

    try:

        estado = page.evaluate(
            """
            () => {

                const fs =
                    document.fullscreenElement;

                return {

                    fullscreen:
                        !!fs,

                    tag:
                        fs
                            ? fs.tagName
                            : null,

                    id:
                        fs
                            ? fs.id
                            : null,

                    class:
                        fs &&
                        typeof fs.className === "string"
                            ? fs.className
                            : "",

                    innerWidth:
                        window.innerWidth,

                    innerHeight:
                        window.innerHeight,

                    screenWidth:
                        screen.width,

                    screenHeight:
                        screen.height
                };
            }
            """
        )

        log("")
        log(
            "[PLAYER] ESTADO APÓS DBLCLICK:"
        )

        log(estado)

        if estado["fullscreen"]:

            log("")
            log("=" * 70)
            log(
                "[PLAYER] FULLSCREEN ATIVADO!"
            )
            log("=" * 70)

            return

    except Exception as erro:

        log(
            "[PLAYER] Erro verificando fullscreen:",
            erro
        )

    # ========================================================
    # TENTATIVA DIRETA NO VIDEO
    # ========================================================

    try:

        log("")
        log(
            "[PLAYER] Tentando requestFullscreen..."
        )

        resultado = page.locator(
            "video"
        ).first.evaluate(
            """
            async video => {

                try {

                    if (
                        document.fullscreenElement
                    ) {

                        return {
                            sucesso: true,
                            metodo: "já fullscreen"
                        };
                    }

                    if (
                        video.requestFullscreen
                    ) {

                        await video.requestFullscreen();

                        return {
                            sucesso: true,
                            metodo:
                                "video.requestFullscreen"
                        };
                    }

                    if (
                        video.webkitRequestFullscreen
                    ) {

                        video.webkitRequestFullscreen();

                        return {
                            sucesso: true,
                            metodo:
                                "webkitRequestFullscreen"
                        };
                    }

                    return {
                        sucesso: false,
                        motivo:
                            "API indisponível"
                    };

                } catch (erro) {

                    return {
                        sucesso: false,
                        erro:
                            String(erro)
                    };
                }
            }
            """
        )

        log(
            "[PLAYER] Resultado:",
            resultado
        )

    except Exception as erro:

        log(
            "[PLAYER] Erro requestFullscreen:",
            erro
        )

    time.sleep(3)

    # ========================================================
    # DIAGNÓSTICO FINAL
    # ========================================================

    try:

        final = page.evaluate(
            """
            () => {

                const fs =
                    document.fullscreenElement;

                const video =
                    document.querySelector("video");

                return {

                    fullscreen:
                        !!fs,

                    fullscreenElement:
                        fs
                            ? fs.tagName
                            : null,

                    window: {
                        width:
                            window.innerWidth,

                        height:
                            window.innerHeight
                    },

                    screen: {
                        width:
                            screen.width,

                        height:
                            screen.height
                    },

                    video: video
                        ? {

                            paused:
                                video.paused,

                            currentTime:
                                video.currentTime,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight
                        }
                        : null
                };
            }
            """
        )

        log("")
        log("=" * 70)
        log(
            "[PLAYER] DIAGNÓSTICO FINAL"
        )
        log("=" * 70)

        log(final)

    except Exception as erro:

        log(
            "[PLAYER] Erro diagnóstico:",
            erro
        )


# ============================================================
# MONITORAR PERFORMANCE DO FFmpeg
# ============================================================

def monitorar_ffmpeg():

    while True:

        try:

            if (
                ffmpeg_process
                and
                ffmpeg_process.poll() is not None
            ):

                log(
                    "[FFMPEG] PROCESSO ENCERROU!"
                )

                return

        except Exception:
            pass

        time.sleep(5)


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    log("")
    log(
        "[7] Iniciando Chromium..."
    )

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

                # ==================================================
                # JANELA
                # ==================================================

                "--window-size=1280,720",

                "--window-position=0,0",

                "--force-device-scale-factor=1",

                # ==================================================
                # X11 / RENDERIZAÇÃO
                # ==================================================

                "--ozone-platform=x11",

                "--use-gl=swiftshader",

                # ==================================================
                # EVITAR COISAS DESNECESSÁRIAS
                # ==================================================

                "--disable-background-networking",

                "--disable-background-timer-throttling",

                "--disable-backgrounding-occluded-windows",

                "--disable-renderer-backgrounding"
            ]
        )

        # ========================================================
        # NÃO FIXAR VIEWPORT
        # ========================================================

        page = browser.new_page(
            viewport=None
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

        page.on(
            "requestfailed",
            lambda request:
                log(
                    "[REQUEST FAILED]",
                    request.url,
                    request.failure
                )
        )

        # ========================================================
        # ABRIR SITE
        # ========================================================

        log(
            "Abrindo painel:"
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

        time.sleep(8)

        # ========================================================
        # REPRODUÇÃO
        # ========================================================

        tentar_reproduzir(
            page
        )

        time.sleep(3)

        diagnosticar_videos(
            page
        )

        # ========================================================
        # FULLSCREEN
        # ========================================================

        ativar_tela_cheia(
            page
        )

        # ========================================================
        # MONITORAMENTO
        # ========================================================

        threading.Thread(
            target=monitorar_ffmpeg,
            daemon=True
        ).start()

        log("")
        log("=" * 70)
        log(
            "CHROMIUM RODANDO"
        )
        log("=" * 70)
        log("")

        # ========================================================
        # MANTER TRANSMISSÃO
        # ========================================================

        while True:

            if page.is_closed():

                raise RuntimeError(
                    "Página do Chromium foi fechada."
                )

            time.sleep(10)


# ============================================================
# MAIN
# ============================================================

def main():

    log("")
    log("=" * 70)
    log(
        "WEBTV STREAM"
    )
    log("=" * 70)
    log("")

    try:

        preparar_stream()

        iniciar_xvfb()

        iniciar_audio()

        iniciar_servidor()

        iniciar_ffmpeg()

        iniciar_tunel()

        iniciar_navegador()

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("=" * 70)
        log(
            "ERRO FATAL"
        )
        log("=" * 70)

        log(
            repr(erro)
        )

        encerrar()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    main()
