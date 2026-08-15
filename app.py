import os
import time
import subprocess
import threading
import signal
import sys

from playwright.sync_api import sync_playwright


# ==========================================================
# CONFIGURAÇÃO
# ==========================================================

TOKEN_NGROK = "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk"

URL_ALVO = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"

DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720
FPS = 30

PORTA = 8080
PASTA_STREAM = "stream"

processos = []


# ==========================================================
# ENCERRAR
# ==========================================================

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


# ==========================================================
# LIMPAR
# ==========================================================

def limpar():

    os.makedirs(
        PASTA_STREAM,
        exist_ok=True
    )

    for nome in os.listdir(PASTA_STREAM):

        caminho = os.path.join(
            PASTA_STREAM,
            nome
        )

        try:

            if os.path.isfile(caminho):
                os.remove(caminho)

        except:
            pass


# ==========================================================
# XVFB
# ==========================================================

def iniciar_xvfb():

    print(
        "[X11] Iniciando Xvfb...",
        flush=True
    )

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

        raise RuntimeError(
            "Xvfb não iniciou."
        )

    print(
        "[X11] DISPLAY",
        DISPLAY,
        "OK",
        flush=True
    )


# ==========================================================
# AUDIO
# ==========================================================

def iniciar_audio():

    print(
        "[AUDIO] Iniciando...",
        flush=True
    )

    os.makedirs(
        "/tmp/pulse",
        exist_ok=True
    )

    os.environ[
        "PULSE_RUNTIME_PATH"
    ] = "/tmp/pulse"

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

    os.environ[
        "PULSE_SINK"
    ] = "webtv"

    time.sleep(2)

    sources = subprocess.run(
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
        "[AUDIO] Sources:",
        sources.stdout,
        flush=True
    )

    if "webtv.monitor" not in sources.stdout:

        raise RuntimeError(
            "webtv.monitor não existe."
        )

    print(
        "[AUDIO] OK",
        flush=True
    )


# ==========================================================
# HTTP
# ==========================================================

def iniciar_http():

    print(
        "[HTTP] Iniciando servidor...",
        flush=True
    )

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


# ==========================================================
# NGROK
# ==========================================================

def iniciar_ngrok():

    from pyngrok import ngrok

    print(
        "[NGROK] Iniciando...",
        flush=True
    )

    ngrok.set_auth_token(
        TOKEN_NGROK
    )

    url = ngrok.connect(
        PORTA
    ).public_url

    print("")
    print(
        "=========================================================="
    )
    print(
        "WEB TV"
    )
    print(
        "=========================================================="
    )
    print(
        "LINK HLS:"
    )
    print(
        url + "/live.m3u8"
    )
    print(
        "=========================================================="
    )
    print("")


# ==========================================================
# TESTAR VÍDEOS
# ==========================================================

def diagnostico(page):

    try:

        dados = page.evaluate("""
        () => {

            const videos =
                [...document.querySelectorAll("video")];

            return videos.map((video, index) => ({

                index: index,

                src:
                    video.getAttribute("src"),

                currentSrc:
                    video.currentSrc,

                paused:
                    video.paused,

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

                width:
                    video.videoWidth,

                height:
                    video.videoHeight,

                muted:
                    video.muted,

                error:
                    video.error
                    ? {
                        code: video.error.code,
                        message: video.error.message
                    }
                    : null

            }));

        }
        """)

        print(
            "[VIDEO]",
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


# ==========================================================
# PLAY
# ==========================================================

def tentar_play(page):

    print(
        "[PLAYER] Tentando reproduzir...",
        flush=True
    )

    try:

        resultado = page.evaluate("""
        async () => {

            const videos =
                [...document.querySelectorAll("video")];

            const saida = [];

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
                     * Primeiro tenta normalmente.
                     */

                    try {

                        const promessa = v.play();

                        if (promessa)
                            await promessa;

                    } catch {

                        /*
                         * Segunda tentativa sem áudio.
                         */

                        v.muted = true;

                        const promessa = v.play();

                        if (promessa)
                            await promessa;
                    }

                    saida.push({
                        index: i,
                        sucesso: true,
                        currentSrc: v.currentSrc,
                        paused: v.paused,
                        readyState: v.readyState,
                        currentTime: v.currentTime,
                        width: v.videoWidth,
                        height: v.videoHeight
                    });

                } catch (e) {

                    saida.push({
                        index: i,
                        sucesso: false,
                        erro: String(e),
                        currentSrc: v.currentSrc,
                        readyState: v.readyState,
                        width: v.videoWidth,
                        height: v.videoHeight
                    });

                }

            }

            return saida;
        }
        """)

        print(
            "[PLAYER]",
            resultado,
            flush=True
        )

    except Exception as e:

        print(
            "[PLAYER] Erro:",
            e,
            flush=True
        )


# ==========================================================
# NAVEGADOR
# ==========================================================

def iniciar_navegador():

    print(
        "[BROWSER] Iniciando Chromium do sistema...",
        flush=True
    )

    # ------------------------------------------------------
    # IMPORTANTE:
    # usamos o Chromium instalado pelo apt.
    # ------------------------------------------------------

    chromium = "/usr/bin/chromium"

    if not os.path.exists(chromium):

        raise RuntimeError(
            "Chromium não encontrado em /usr/bin/chromium"
        )

    print(
        "[BROWSER] Executável:",
        chromium,
        flush=True
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(

            executable_path=chromium,

            headless=False,

            args=[

                "--no-sandbox",

                "--disable-setuid-sandbox",

                "--disable-dev-shm-usage",

                "--disable-gpu",

                "--use-gl=swiftshader",

                "--autoplay-policy=no-user-gesture-required",

                "--start-fullscreen",

                "--window-size=1280,720",

                "--window-position=0,0",

                "--force-device-scale-factor=1",

                "--disable-background-timer-throttling",

                "--disable-backgrounding-occluded-windows",

                "--disable-renderer-backgrounding",

                "--no-first-run",

                "--no-default-browser-check",

                "--disable-notifications",

                "--disable-popup-blocking",

                "--disable-features=Translate",

                "--lang=pt-BR"
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

        # --------------------------------------------------
        # CONSOLE
        # --------------------------------------------------

        page.on(
            "console",
            lambda msg:
            print(
                "[CONSOLE]",
                msg.text,
                flush=True
            )
        )

        page.on(
            "pageerror",
            lambda error:
            print(
                "[PAGE ERROR]",
                error,
                flush=True
            )
        )

        # --------------------------------------------------
        # REQUISIÇÕES DE VÍDEO
        # --------------------------------------------------

        page.on(
            "request",
            lambda request:
            print(
                "[REQUEST]",
                request.resource_type,
                request.url,
                flush=True
            )
            if request.resource_type in [
                "media",
                "xhr",
                "fetch"
            ]
            else None
        )

        # --------------------------------------------------
        # RESPOSTAS
        # --------------------------------------------------

        page.on(
            "response",
            lambda response:
            print(
                "[RESPONSE]",
                response.status,
                response.request.resource_type,
                response.url,
                flush=True
            )
            if response.request.resource_type in [
                "media",
                "xhr",
                "fetch"
            ]
            else None
        )

        # --------------------------------------------------
        # FALHAS
        # --------------------------------------------------

        page.on(
            "requestfailed",
            lambda request:
            print(
                "[REQUEST FAILED]",
                request.resource_type,
                request.url,
                "=>",
                request.failure,
                flush=True
            )
            if request.resource_type in [
                "media",
                "xhr",
                "fetch"
            ]
            else None
        )

        # --------------------------------------------------
        # ABRIR
        # --------------------------------------------------

        print(
            "[BROWSER] Abrindo:",
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
                "[BROWSER] Erro ao abrir:",
                e,
                flush=True
            )

        print(
            "[BROWSER] URL:",
            page.url,
            flush=True
        )

        print(
            "[BROWSER] Aguardando aplicação...",
            flush=True
        )

        time.sleep(15)

        # --------------------------------------------------
        # PRIMEIRO DIAGNÓSTICO
        # --------------------------------------------------

        diagnostico(page)

        # --------------------------------------------------
        # CLIQUE
        # --------------------------------------------------

        try:

            page.mouse.click(
                WIDTH // 2,
                HEIGHT // 2
            )

        except:
            pass

        time.sleep(2)

        # --------------------------------------------------
        # PROCURAR RECARREGAR PLAYER
        # --------------------------------------------------

        try:

            botoes = page.get_by_role(
                "button"
            )

            quantidade = botoes.count()

            for i in range(quantidade):

                try:

                    texto = botoes.nth(i).inner_text()

                    if (
                        "RECARREGAR" in
                        texto.upper()
                    ):

                        print(
                            "[PLAYER] Clicando:",
                            texto,
                            flush=True
                        )

                        botoes.nth(i).click()

                        time.sleep(8)

                        break

                except:
                    pass

        except:
            pass

        # --------------------------------------------------
        # PLAY
        # --------------------------------------------------

        tentar_play(page)

        time.sleep(5)

        diagnostico(page)

        # --------------------------------------------------
        # SCREENSHOT
        # --------------------------------------------------

        try:

            page.screenshot(
                path=
                f"{PASTA_STREAM}/browser_debug.png"
            )

        except:
            pass

        # --------------------------------------------------
        # FICAR ABERTO
        # --------------------------------------------------

        while True:

            time.sleep(20)

            diagnostico(page)


# ==========================================================
# FFMPEG
# ==========================================================

def iniciar_ffmpeg():

    print(
        "[FFMPEG] Iniciando...",
        flush=True
    )

    comando = [

        "ffmpeg",

        "-y",

        # --------------------------------------------------
        # X11
        # --------------------------------------------------

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

        # --------------------------------------------------
        # ÁUDIO
        # --------------------------------------------------

        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

        # --------------------------------------------------
        # VÍDEO
        # --------------------------------------------------

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

        # --------------------------------------------------
        # ÁUDIO
        # --------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        "-ac",
        "2",

        # --------------------------------------------------
        # HLS
        # --------------------------------------------------

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

    def mostrar():

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
        target=mostrar,
        daemon=True
    ).start()

    time.sleep(5)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg parou."
        )

    print(
        "[FFMPEG] OK.",
        flush=True
    )


# ==========================================================
# MAIN
# ==========================================================

def iniciar():

    print("")
    print(
        "=========================================================="
    )
    print(
        "              WEB TV - STREAM"
    )
    print(
        "=========================================================="
    )

    limpar()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_http()

    iniciar_ngrok()

    # navegador primeiro
    thread = threading.Thread(
        target=iniciar_navegador,
        daemon=True
    )

    thread.start()

    print(
        "[MAIN] Esperando navegador...",
        flush=True
    )

    time.sleep(30)

    # captura depois
    iniciar_ffmpeg()

    print("")
    print(
        "=========================================================="
    )
    print(
        "              TRANSMISSÃO INICIADA"
    )
    print(
        "=========================================================="
    )
    print("")

    while True:

        time.sleep(30)


if __name__ == "__main__":
    iniciar()
