import os
import time
import subprocess
import threading
import signal
import sys

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÃO
# ============================================================

TOKEN_NGROK = "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk"

# SUA PÁGINA /watch
URL_ALVO = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"

WIDTH = 1280
HEIGHT = 720
FPS = 30

DISPLAY = ":99"
PORTA = 8080
PASTA_STREAM = "stream"

processos = []


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(sig=None, frame=None):
    print("[MAIN] Encerrando...", flush=True)

    for p in processos:
        try:
            if p.poll() is None:
                p.terminate()
        except:
            pass

    time.sleep(2)

    for p in processos:
        try:
            if p.poll() is None:
                p.kill()
        except:
            pass

    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


# ============================================================
# LIMPAR STREAM
# ============================================================

def limpar_stream():

    os.makedirs(PASTA_STREAM, exist_ok=True)

    for arquivo in os.listdir(PASTA_STREAM):

        caminho = os.path.join(
            PASTA_STREAM,
            arquivo
        )

        try:
            if os.path.isfile(caminho):
                os.remove(caminho)
        except:
            pass


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    print("[X11] Iniciando Xvfb...", flush=True)

    os.environ["DISPLAY"] = DISPLAY

    xvfb = subprocess.Popen([
        "Xvfb",
        DISPLAY,
        "-screen",
        "0",
        f"{WIDTH}x{HEIGHT}x24",
        "-ac",
        "-nolisten",
        "tcp"
    ])

    processos.append(xvfb)

    time.sleep(3)

    if xvfb.poll() is not None:
        raise RuntimeError("Xvfb não iniciou.")

    print(
        f"[X11] DISPLAY={DISPLAY} OK",
        flush=True
    )


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    print("[AUDIO] Iniciando PulseAudio...", flush=True)

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

    resultado = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sinks"
        ],
        capture_output=True,
        text=True
    )

    if "webtv" not in resultado.stdout:

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

    print("[AUDIO] Áudio OK.", flush=True)


# ============================================================
# SERVIDOR HLS
# ============================================================

def iniciar_servidor():

    print("[HTTP] Iniciando servidor...", flush=True)

    servidor = subprocess.Popen([
        "python3",
        "-m",
        "http.server",
        str(PORTA),
        "--directory",
        PASTA_STREAM
    ])

    processos.append(servidor)

    time.sleep(2)


# ============================================================
# NGROK
# ============================================================

def iniciar_ngrok():

    print("[NGROK] Iniciando...", flush=True)

    from pyngrok import ngrok

    ngrok.set_auth_token(TOKEN_NGROK)

    url = ngrok.connect(PORTA).public_url

    print("")
    print("====================================================")
    print("              TRANSMISSÃO WEB TV")
    print("====================================================")
    print("URL:", url)
    print("HLS:", url + "/live.m3u8")
    print("====================================================")
    print("")


# ============================================================
# DIAGNÓSTICO DOS VÍDEOS
# ============================================================

def diagnosticar(page):

    try:

        dados = page.evaluate("""
        () => {

            return [...document.querySelectorAll("video")]
                .map((v, i) => ({

                    index: i,

                    src:
                        v.getAttribute("src"),

                    currentSrc:
                        v.currentSrc,

                    paused:
                        v.paused,

                    ended:
                        v.ended,

                    muted:
                        v.muted,

                    readyState:
                        v.readyState,

                    networkState:
                        v.networkState,

                    currentTime:
                        v.currentTime,

                    duration:
                        Number.isFinite(v.duration)
                            ? v.duration
                            : null,

                    width:
                        v.videoWidth,

                    height:
                        v.videoHeight,

                    error:
                        v.error
                        ? {
                            code: v.error.code,
                            message: v.error.message
                          }
                        : null,

                    sources:
                        [...v.querySelectorAll("source")]
                        .map(s => ({
                            src: s.src,
                            type: s.type
                        }))

                }));

        }
        """)

        print(
            "[VIDEO] DIAGNÓSTICO:",
            dados,
            flush=True
        )

        return dados

    except Exception as e:

        print(
            "[VIDEO] Erro:",
            e,
            flush=True
        )

        return []


# ============================================================
# TENTAR RECARREGAR PLAYER
# ============================================================

def recarregar_player(page):

    print(
        "[PLAYER] Procurando botão de recarregar...",
        flush=True
    )

    seletores = [
        "button",
        "[role='button']",
        "text=RECARREGAR PLAYER",
        "text=Recarregar player",
        "text=RECARREGAR",
        "text=Recarregar"
    ]

    for seletor in seletores:

        try:

            elementos = page.locator(seletor)

            quantidade = elementos.count()

            for i in range(quantidade):

                elemento = elementos.nth(i)

                try:

                    texto = elemento.inner_text(
                        timeout=1000
                    )

                except:

                    texto = ""

                if (
                    "RECARREGAR" in texto.upper()
                    or
                    "RECARREGAR PLAYER" in texto.upper()
                ):

                    print(
                        "[PLAYER] Botão encontrado:",
                        texto,
                        flush=True
                    )

                    elemento.click(
                        timeout=5000
                    )

                    time.sleep(5)

                    return True

        except:
            pass

    print(
        "[PLAYER] Botão não encontrado.",
        flush=True
    )

    return False


# ============================================================
# FORÇAR PLAY
# ============================================================

def reproduzir(page):

    print(
        "[PLAYER] Tentando reproduzir...",
        flush=True
    )

    try:

        resultado = page.evaluate("""
        async () => {

            const videos =
                [...document.querySelectorAll("video")];

            const resultado = [];

            for (
                let i = 0;
                i < videos.length;
                i++
            ) {

                const v = videos[i];

                try {

                    v.autoplay = true;
                    v.playsInline = true;

                    /*
                     * Primeiro tenta com áudio.
                     */
                    try {

                        v.muted = false;

                        const p = v.play();

                        if (p)
                            await p;

                    } catch {

                        /*
                         * Se autoplay com áudio for bloqueado,
                         * tenta silencioso.
                         */

                        v.muted = true;

                        const p = v.play();

                        if (p)
                            await p;
                    }

                    resultado.push({

                        index: i,
                        ok: true,
                        src: v.currentSrc,
                        paused: v.paused,
                        readyState: v.readyState,
                        currentTime: v.currentTime,
                        width: v.videoWidth,
                        height: v.videoHeight

                    });

                } catch (e) {

                    resultado.push({

                        index: i,
                        ok: false,
                        erro: String(e),
                        src: v.currentSrc,
                        readyState: v.readyState,
                        width: v.videoWidth,
                        height: v.videoHeight

                    });

                }
            }

            return resultado;
        }
        """)

        print(
            "[PLAYER] Resultado:",
            resultado,
            flush=True
        )

    except Exception as e:

        print(
            "[PLAYER] Erro:",
            e,
            flush=True
        )


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    print("[CHROMIUM] Iniciando...", flush=True)

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=False,

            args=[

                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",

                "--autoplay-policy=no-user-gesture-required",

                "--start-fullscreen",
                "--kiosk",

                "--window-size=1280,720",
                "--window-position=0,0",

                "--force-device-scale-factor=1",

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

            locale="pt-BR",

            timezone_id="America/Sao_Paulo",

            user_agent=(
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        # ----------------------------------------------------
        # CONSOLE
        # ----------------------------------------------------

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
            lambda err:
            print(
                "[BROWSER ERROR]",
                err,
                flush=True
            )
        )

        # ----------------------------------------------------
        # REQUISIÇÕES
        # ----------------------------------------------------

        def request(req):

            if req.resource_type in [
                "media",
                "xhr",
                "fetch"
            ]:

                print(
                    "[REQUEST]",
                    req.resource_type,
                    req.method,
                    req.url,
                    flush=True
                )

        page.on(
            "request",
            request
        )

        # ----------------------------------------------------
        # RESPOSTAS
        # ----------------------------------------------------

        def response(resp):

            if resp.request.resource_type in [
                "media",
                "xhr",
                "fetch"
            ]:

                print(
                    "[RESPONSE]",
                    resp.status,
                    resp.request.resource_type,
                    resp.url,
                    flush=True
                )

        page.on(
            "response",
            response
        )

        # ----------------------------------------------------
        # ERROS DE REDE
        # ----------------------------------------------------

        def failed(req):

            if req.resource_type in [
                "media",
                "xhr",
                "fetch"
            ]:

                print(
                    "[REQUEST FAILED]",
                    req.resource_type,
                    req.url,
                    "=>",
                    req.failure,
                    flush=True
                )

        page.on(
            "requestfailed",
            failed
        )

        # ----------------------------------------------------
        # ABRIR SITE
        # ----------------------------------------------------

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

        except Exception as e:

            print(
                "[CHROMIUM] Erro:",
                e,
                flush=True
            )

        print(
            "[CHROMIUM] URL:",
            page.url,
            flush=True
        )

        print(
            "[CHROMIUM] Aguardando player...",
            flush=True
        )

        time.sleep(10)

        # ----------------------------------------------------
        # DIAGNÓSTICO
        # ----------------------------------------------------

        diagnosticar(page)

        # ----------------------------------------------------
        # CLICAR NO PLAYER
        # ----------------------------------------------------

        try:

            page.mouse.click(
                WIDTH // 2,
                HEIGHT // 2
            )

        except:
            pass

        time.sleep(2)

        # ----------------------------------------------------
        # RECARREGAR PLAYER
        # ----------------------------------------------------

        recarregar_player(page)

        time.sleep(3)

        # ----------------------------------------------------
        # PLAY
        # ----------------------------------------------------

        reproduzir(page)

        time.sleep(5)

        # ----------------------------------------------------
        # SEGUNDA TENTATIVA
        # ----------------------------------------------------

        dados = diagnosticar(page)

        precisa_retry = False

        for video in dados:

            if (
                video.get("readyState", 0) == 0
                or
                video.get("width", 0) == 0
            ):

                precisa_retry = True

        if precisa_retry:

            print(
                "[PLAYER] Vídeo ainda não carregou.",
                flush=True
            )

            print(
                "[PLAYER] Tentando recarregar página...",
                flush=True
            )

            try:

                page.reload(
                    wait_until="domcontentloaded",
                    timeout=120000
                )

            except Exception as e:

                print(
                    "[PLAYER] Reload:",
                    e,
                    flush=True
                )

            time.sleep(10)

            recarregar_player(page)

            time.sleep(3)

            reproduzir(page)

            time.sleep(5)

            diagnosticar(page)

        # ----------------------------------------------------
        # SCREENSHOT
        # ----------------------------------------------------

        try:

            page.screenshot(
                path=os.path.join(
                    PASTA_STREAM,
                    "browser_debug.png"
                )
            )

            print(
                "[CHROMIUM] Screenshot salvo.",
                flush=True
            )

        except Exception as e:

            print(
                "[CHROMIUM] Screenshot:",
                e,
                flush=True
            )

        # ----------------------------------------------------
        # FICAR ABERTO
        # ----------------------------------------------------

        while True:

            time.sleep(30)

            try:

                dados = diagnosticar(page)

                print(
                    "[CHROMIUM] Página:",
                    page.url,
                    flush=True
                )

            except Exception as e:

                print(
                    "[CHROMIUM] Monitor:",
                    e,
                    flush=True
                )


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    print("[FFMPEG] Iniciando captura...", flush=True)

    comando = [

        "ffmpeg",
        "-y",

        # VÍDEO
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

        # ÁUDIO
        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # CODEC
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
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        "-ac",
        "2",

        # HLS
        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "5",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        f"{PASTA_STREAM}/segment_%05d.ts",

        f"{PASTA_STREAM}/live.m3u8"
    ]

    print(
        "[FFMPEG]",
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

    def log():

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
        target=log,
        daemon=True
    ).start()

    time.sleep(5)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    print(
        "[FFMPEG] Transmissão ativa.",
        flush=True
    )


# ============================================================
# MAIN
# ============================================================

def iniciar():

    print("")
    print("====================================================")
    print("                 WEB TV STREAM")
    print("====================================================")

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    iniciar_ngrok()

    # --------------------------------------------------------
    # PRIMEIRO navegador
    # --------------------------------------------------------

    navegador = threading.Thread(
        target=iniciar_navegador,
        daemon=True
    )

    navegador.start()

    print(
        "[MAIN] Aguardando navegador carregar...",
        flush=True
    )

    time.sleep(30)

    # --------------------------------------------------------
    # DEPOIS captura
    # --------------------------------------------------------

    iniciar_ffmpeg()

    print("")
    print("====================================================")
    print("              TRANSMISSÃO INICIADA")
    print("====================================================")
    print("")

    while True:
        time.sleep(30)


if __name__ == "__main__":
    iniciar()
