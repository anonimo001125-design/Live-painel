import os
import sys
import time
import signal
import threading
import subprocess

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÃO
# ============================================================

TOKEN_NGROK = "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk"

# COLOQUE A URL DA SUA PÁGINA DE TRANSMISSÃO
URL_ALVO = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"

WIDTH = 1280
HEIGHT = 720
FPS = 30

DISPLAY = ":99"
HTTP_PORT = 8080
STREAM_DIR = "stream"

processos = []


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    print("\n[MAIN] Encerrando...", flush=True)

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

    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


# ============================================================
# LIMPAR STREAM
# ============================================================

def limpar_stream():

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    for arquivo in os.listdir(STREAM_DIR):

        caminho = os.path.join(
            STREAM_DIR,
            arquivo
        )

        try:

            if os.path.isfile(caminho):
                os.remove(caminho)

        except Exception:
            pass


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    print(
        "[1] Iniciando Xvfb...",
        flush=True
    )

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

    print(
        f"[X11] DISPLAY={DISPLAY}",
        flush=True
    )

    print(
        f"[X11] Resolução: {WIDTH}x{HEIGHT}",
        flush=True
    )


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    print(
        "[2] Iniciando PulseAudio...",
        flush=True
    )

    os.makedirs(
        "/tmp/pulse",
        exist_ok=True
    )

    os.environ["PULSE_RUNTIME_PATH"] = "/tmp/pulse"

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        check=False
    )

    time.sleep(3)

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

        print(
            "[AUDIO] Criando sink webtv...",
            flush=True
        )

        subprocess.run(
            [
                "pactl",
                "load-module",
                "module-null-sink",
                "sink_name=webtv",
                "sink_properties=device.description=WebTV"
            ],
            check=False
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

    print(
        "[AUDIO] Fontes:",
        fontes.stdout,
        flush=True
    )

    if "webtv.monitor" not in fontes.stdout:

        raise RuntimeError(
            "webtv.monitor não foi criado."
        )

    print(
        "[AUDIO] PulseAudio pronto.",
        flush=True
    )


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():

    print(
        "[3] Iniciando servidor HTTP...",
        flush=True
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

    processos.append(servidor)

    time.sleep(2)

    print(
        f"[HTTP] Porta {HTTP_PORT}",
        flush=True
    )


# ============================================================
# NGROK
# ============================================================

def iniciar_ngrok():

    print(
        "[4] Iniciando NGROK...",
        flush=True
    )

    from pyngrok import ngrok

    ngrok.set_auth_token(
        TOKEN_NGROK
    )

    url_publica = ngrok.connect(
        HTTP_PORT
    ).public_url

    print("")
    print(
        "=========================================================="
    )
    print(
        "                 WEB TV ONLINE"
    )
    print(
        "=========================================================="
    )
    print(
        "URL pública:"
    )
    print(
        url_publica
    )
    print("")
    print(
        "LINK HLS:"
    )
    print(
        url_publica.rstrip("/") + "/live.m3u8"
    )
    print(
        "=========================================================="
    )
    print("")


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

                return videos.map((video, index) => ({

                    index: index,

                    src:
                        video.src || "",

                    currentSrc:
                        video.currentSrc || "",

                    paused:
                        video.paused,

                    ended:
                        video.ended,

                    muted:
                        video.muted,

                    autoplay:
                        video.autoplay,

                    readyState:
                        video.readyState,

                    networkState:
                        video.networkState,

                    currentTime:
                        video.currentTime,

                    duration:
                        Number.isFinite(video.duration)
                            ? video.duration
                            : null,

                    videoWidth:
                        video.videoWidth,

                    videoHeight:
                        video.videoHeight,

                    error:
                        video.error
                            ? {
                                code:
                                    video.error.code,

                                message:
                                    video.error.message
                            }
                            : null

                }));

            }
            """
        )

        print("")
        print(
            "================ DIAGNÓSTICO VIDEO ================",
            flush=True
        )

        if not resultado:

            print(
                "[VIDEO] Nenhum elemento <video> encontrado!",
                flush=True
            )

        for video in resultado:

            print(
                video,
                flush=True
            )

        print(
            "====================================================",
            flush=True
        )

        return resultado

    except Exception as erro:

        print(
            "[VIDEO] Erro diagnóstico:",
            erro,
            flush=True
        )

        return []


# ============================================================
# INICIAR REPRODUÇÃO
# ============================================================

def iniciar_reproducao(page):

    print(
        "[PLAYER] Tentando iniciar os vídeos...",
        flush=True
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
                    let i = 0;
                    i < videos.length;
                    i++
                ) {

                    const video = videos[i];

                    try {

                        video.playsInline = true;
                        video.autoplay = true;

                        let tocou = false;

                        // Primeira tentativa normal
                        try {

                            const promessa =
                                video.play();

                            if (promessa) {
                                await promessa;
                            }

                            tocou = true;

                        } catch (erro1) {

                            // Segunda tentativa sem áudio
                            try {

                                video.muted = true;

                                const promessa2 =
                                    video.play();

                                if (promessa2) {
                                    await promessa2;
                                }

                                tocou = true;

                            } catch (erro2) {

                                tocou = false;

                            }

                        }

                        resultado.push({

                            index: i,

                            tocou: tocou,

                            src:
                                video.src || "",

                            currentSrc:
                                video.currentSrc || "",

                            paused:
                                video.paused,

                            readyState:
                                video.readyState,

                            networkState:
                                video.networkState,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight

                        });

                    } catch (erro) {

                        resultado.push({

                            index: i,

                            tocou: false,

                            erro:
                                String(erro)

                        });

                    }

                }

                return resultado;
            }
            """
        )

        print(
            "[PLAYER] Resultado:",
            resultado,
            flush=True
        )

    except Exception as erro:

        print(
            "[PLAYER] Erro:",
            erro,
            flush=True
        )


# ============================================================
# MONITORAR VÍDEO
# ============================================================

def instalar_monitor_video(page):

    try:

        page.evaluate(
            """
            () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                videos.forEach((video, index) => {

                    const eventos = [
                        "loadstart",
                        "loadedmetadata",
                        "loadeddata",
                        "canplay",
                        "canplaythrough",
                        "playing",
                        "play",
                        "pause",
                        "waiting",
                        "stalled",
                        "suspend",
                        "ended",
                        "error"
                    ];

                    eventos.forEach(nome => {

                        video.addEventListener(
                            nome,
                            () => {

                                console.log(
                                    "[VIDEO EVENT]",
                                    index,
                                    nome,
                                    "time=" +
                                    video.currentTime,
                                    "ready=" +
                                    video.readyState,
                                    "network=" +
                                    video.networkState,
                                    "size=" +
                                    video.videoWidth +
                                    "x" +
                                    video.videoHeight
                                );

                            }
                        );

                    });

                });

            }
            """
        )

        print(
            "[PLAYER] Monitor de vídeo instalado.",
            flush=True
        )

    except Exception as erro:

        print(
            "[PLAYER] Não conseguiu instalar monitor:",
            erro,
            flush=True
        )


# ============================================================
# CHROMIUM
# ============================================================

def iniciar_navegador():

    print(
        "[5] Iniciando Chromium...",
        flush=True
    )

    with sync_playwright() as p:

        # ----------------------------------------------------
        # Usamos o Chromium do Playwright.
        # Não usamos executable_path.
        # ----------------------------------------------------

        browser = p.chromium.launch(

            headless=False,

            args=[

                "--no-sandbox",

                "--disable-setuid-sandbox",

                "--disable-dev-shm-usage",

                "--ozone-platform=x11",

                # FULLSCREEN REAL DA JANELA
                "--kiosk",

                "--start-fullscreen",

                "--window-size=1280,720",

                "--window-position=0,0",

                "--force-device-scale-factor=1",

                # AUTOPLAY
                "--autoplay-policy=no-user-gesture-required",

                # Não desativamos GPU.
                "--ignore-gpu-blocklist",

                "--no-first-run",

                "--no-default-browser-check",

                "--disable-notifications",

                "--disable-popup-blocking"
            ]
        )

        context = browser.new_context(

            viewport={
                "width": WIDTH,
                "height": HEIGHT
            },

            user_agent=(
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 "
                "Safari/537.36"
            ),

            locale="pt-BR",

            timezone_id="America/Sao_Paulo"
        )

        page = context.new_page()

        # ====================================================
        # LOG DO CONSOLE
        # ====================================================

        page.on(
            "console",
            lambda msg:
            print(
                "[BROWSER]",
                msg.text,
                flush=True
            )
        )

        page.on(
            "pageerror",
            lambda erro:
            print(
                "[BROWSER ERROR]",
                erro,
                flush=True
            )
        )

        # ====================================================
        # REQUISIÇÕES DE MÍDIA
        # ====================================================

        def request_handler(request):

            if request.resource_type in [
                "media",
                "xhr",
                "fetch"
            ]:

                print(
                    "[REQUEST]",
                    request.resource_type,
                    request.method,
                    request.url,
                    flush=True
                )

        page.on(
            "request",
            request_handler
        )

        # ====================================================
        # RESPOSTAS
        # ====================================================

        def response_handler(response):

            tipo = response.request.resource_type

            if tipo in [
                "media",
                "xhr",
                "fetch"
            ]:

                print(
                    "[RESPONSE]",
                    response.status,
                    tipo,
                    response.url,
                    flush=True
                )

        page.on(
            "response",
            response_handler
        )

        # ====================================================
        # REQUEST FAILED
        # ====================================================

        def failed_handler(request):

            if request.resource_type in [
                "media",
                "xhr",
                "fetch"
            ]:

                print(
                    "[REQUEST FAILED]",
                    request.resource_type,
                    request.url,
                    "=>",
                    request.failure,
                    flush=True
                )

        page.on(
            "requestfailed",
            failed_handler
        )

        # ====================================================
        # INFORMAÇÕES DO NAVEGADOR
        # ====================================================

        try:

            print(
                "[CHROMIUM] User-Agent:",
                page.evaluate(
                    "navigator.userAgent"
                ),
                flush=True
            )

            print(
                "[CHROMIUM] Online:",
                page.evaluate(
                    "navigator.onLine"
                ),
                flush=True
            )

        except Exception:
            pass

        # ====================================================
        # ABRIR SITE
        # ====================================================

        print(
            "[CHROMIUM] Abrindo:",
            URL_ALVO,
            flush=True
        )

        try:

            page.goto(
                URL_ALVO,

                wait_until="domcontentloaded",

                timeout=120000
            )

        except Exception as erro:

            print(
                "[CHROMIUM] Erro ao abrir página:",
                erro,
                flush=True
            )

        print(
            "[CHROMIUM] Página carregada:",
            page.url,
            flush=True
        )

        # ====================================================
        # AGUARDAR O JAVASCRIPT DO PAINEL
        # ====================================================

        print(
            "[CHROMIUM] Aguardando painel renderizar...",
            flush=True
        )

        time.sleep(10)

        # ====================================================
        # INSTALAR MONITOR
        # ====================================================

        instalar_monitor_video(page)

        # ====================================================
        # DIAGNÓSTICO INICIAL
        # ====================================================

        diagnosticar_videos(page)

        # ====================================================
        # INTERAÇÃO
        # ====================================================

        try:

            page.mouse.click(
                WIDTH // 2,
                HEIGHT // 2
            )

            print(
                "[PLAYER] Clique enviado.",
                flush=True
            )

        except Exception as erro:

            print(
                "[PLAYER] Clique falhou:",
                erro,
                flush=True
            )

        time.sleep(2)

        # ====================================================
        # REPRODUÇÃO
        # ====================================================

        iniciar_reproducao(page)

        # ====================================================
        # TENTAR FULLSCREEN DO PLAYER
        # ====================================================

        try:

            page.evaluate(
                """
                async () => {

                    const videos =
                        Array.from(
                            document.querySelectorAll("video")
                        );

                    for (const video of videos) {

                        try {

                            if (
                                video.requestFullscreen
                            ) {

                                await
                                video.requestFullscreen();

                                break;
                            }

                        } catch (e) {}

                    }

                }
                """
            )

            print(
                "[PLAYER] Solicitação de fullscreen enviada.",
                flush=True
            )

        except Exception as erro:

            print(
                "[PLAYER] Fullscreen do vídeo não disponível:",
                erro,
                flush=True
            )

        # ====================================================
        # MONITORAMENTO
        # ====================================================

        ultimo_tempo = {}

        for tentativa in range(1, 13):

            time.sleep(5)

            videos = diagnosticar_videos(page)

            for video in videos:

                indice = video.get(
                    "index"
                )

                tempo = video.get(
                    "currentTime",
                    0
                )

                anterior = ultimo_tempo.get(
                    indice
                )

                if anterior is not None:

                    if (
                        tempo == anterior
                        and
                        not video.get("paused", True)
                    ):

                        print(
                            "[ALERTA]",
                            f"Vídeo {indice} parece congelado.",
                            "currentTime=",
                            tempo,
                            flush=True
                        )

                ultimo_tempo[indice] = tempo

            print(
                f"[PLAYER] Monitoramento {tentativa}/12",
                flush=True
            )

        # ====================================================
        # SCREENSHOT
        # ====================================================

        try:

            page.screenshot(
                path=os.path.join(
                    STREAM_DIR,
                    "browser_debug.png"
                )
            )

            print(
                "[CHROMIUM] Screenshot salvo em",
                "stream/browser_debug.png",
                flush=True
            )

        except Exception as erro:

            print(
                "[CHROMIUM] Screenshot falhou:",
                erro,
                flush=True
            )

        # ====================================================
        # MANTER ABERTO
        # ====================================================

        while True:

            time.sleep(30)

            try:

                print(
                    "[CHROMIUM] Ativo:",
                    page.title(),
                    "| URL:",
                    page.url,
                    flush=True
                )

            except Exception:
                pass


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    print(
        "[6] Iniciando FFmpeg...",
        flush=True
    )

    comando = [

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
        # H264
        # ====================================================

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

        "-sc_threshold",
        "0",

        # ====================================================
        # AAC
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
        "2",

        "-hls_list_size",
        "5",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        f"{STREAM_DIR}/segment_%05d.ts",

        f"{STREAM_DIR}/live.m3u8"
    ]

    print(
        "[FFMPEG] Comando:",
        " ".join(comando),
        flush=True
    )

    ffmpeg = subprocess.Popen(

        comando,

        stdout=subprocess.PIPE,

        stderr=subprocess.STDOUT,

        text=True,

        bufsize=1
    )

    processos.append(ffmpeg)

    def acompanhar():

        for linha in iter(
            ffmpeg.stdout.readline,
            ""
        ):

            if linha:

                print(
                    "[FFMPEG]",
                    linha.strip(),
                    flush=True
                )

    threading.Thread(
        target=acompanhar,
        daemon=True
    ).start()

    time.sleep(5)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou imediatamente."
        )

    print(
        "[FFMPEG] Transmissão iniciada.",
        flush=True
    )


# ============================================================
# MAIN
# ============================================================

def iniciar():

    print("")
    print(
        "=========================================================="
    )
    print(
        "                  WEB TV STREAM"
    )
    print(
        "=========================================================="
    )
    print("")

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_ngrok()

    # ========================================================
    # NAVEGADOR
    # ========================================================

    navegador = threading.Thread(
        target=iniciar_navegador,
        daemon=True
    )

    navegador.start()

    print(
        "[MAIN] Aguardando navegador...",
        flush=True
    )

    time.sleep(30)

    # ========================================================
    # FFMPEG
    # ========================================================

    iniciar_ffmpeg()

    print("")
    print(
        "=========================================================="
    )
    print(
        "                 TRANSMISSÃO ATIVA"
    )
    print(
        "=========================================================="
    )
    print("")

    while True:

        time.sleep(30)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    iniciar()
