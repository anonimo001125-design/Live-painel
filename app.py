import os
import sys
import time
import signal
import subprocess
import threading

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÃO
# ============================================================

TOKEN_NGROK = "3Hp2YbxQ2bolHAikPRlZgIA4Rtr_71CZKugfEWPTKPS9LXXJk"

# URL DA SUA PÁGINA /watch
URL_ALVO = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"

DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720
FPS = 30

PORTA = 8080

STREAM_DIR = "stream"

processos = []


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(sig=None, frame=None):

    print("[MAIN] Encerrando...", flush=True)

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

    for nome in os.listdir(STREAM_DIR):

        caminho = os.path.join(
            STREAM_DIR,
            nome
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

    # Criar saída virtual
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

    os.environ["PULSE_SINK"] = "webtv"

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
        "[AUDIO] Fontes:",
        sources.stdout,
        flush=True
    )

    if "webtv.monitor" not in sources.stdout:

        raise RuntimeError(
            "A fonte webtv.monitor não foi criada."
        )

    print("[AUDIO] PulseAudio OK.", flush=True)


# ============================================================
# SERVIDOR HLS
# ============================================================

def iniciar_http():

    print("[HTTP] Iniciando servidor HLS...", flush=True)

    servidor = subprocess.Popen([
        "python3",
        "-m",
        "http.server",
        str(PORTA),
        "--directory",
        STREAM_DIR
    ])

    processos.append(servidor)

    time.sleep(2)

    print(
        f"[HTTP] Servidor ativo na porta {PORTA}",
        flush=True
    )


# ============================================================
# NGROK
# ============================================================

def iniciar_ngrok():

    print("[NGROK] Iniciando...", flush=True)

    from pyngrok import ngrok

    # Mata somente processos/túneis locais desta execução
    try:
        ngrok.kill()
    except Exception:
        pass

    time.sleep(2)

    ngrok.set_auth_token(
        TOKEN_NGROK
    )

    # NÃO especificamos domínio.
    # Isso evita ERR_NGROK_334.
    tunnel = ngrok.connect(
        PORTA,
        "http"
    )

    url = tunnel.public_url

    print("")
    print("==========================================================")
    print("                 WEB TV ONLINE")
    print("==========================================================")
    print("")
    print("SITE:")
    print(url)
    print("")
    print("PLAYLIST HLS:")
    print(url + "/live.m3u8")
    print("")
    print("==========================================================")
    print("")

    return tunnel


# ============================================================
# DIAGNÓSTICO DO VÍDEO
# ============================================================

def diagnosticar_video(page):

    try:

        dados = page.evaluate("""
        () => {

            const videos =
                [...document.querySelectorAll("video")];

            return videos.map((v, i) => ({

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

                autoplay:
                    v.autoplay,

                controls:
                    v.controls,

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
            "[VIDEO] Erro no diagnóstico:",
            e,
            flush=True
        )

        return []


# ============================================================
# FORÇAR PLAYER
# ============================================================

def forcar_player(page):

    print(
        "[PLAYER] Forçando reprodução...",
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
                     * Remove controles que possam
                     * impedir o layout do player.
                     */
                    v.style.display = "block";

                    /*
                     * Primeira tentativa:
                     * áudio ligado.
                     */
                    try {

                        v.muted = false;

                        const p = v.play();

                        if (p)
                            await p;

                    } catch (e1) {

                        /*
                         * Segunda tentativa:
                         * autoplay silencioso.
                         */
                        try {

                            v.muted = true;

                            const p = v.play();

                            if (p)
                                await p;

                        } catch (e2) {

                            resultado.push({
                                index: i,
                                sucesso: false,
                                erro1: String(e1),
                                erro2: String(e2),
                                src: v.currentSrc,
                                readyState: v.readyState
                            });

                            continue;
                        }
                    }

                    resultado.push({

                        index: i,

                        sucesso: true,

                        src:
                            v.currentSrc,

                        paused:
                            v.paused,

                        readyState:
                            v.readyState,

                        currentTime:
                            v.currentTime,

                        width:
                            v.videoWidth,

                        height:
                            v.videoHeight

                    });

                } catch (e) {

                    resultado.push({

                        index: i,

                        sucesso: false,

                        erro:
                            String(e)

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
# FULLSCREEN
# ============================================================

def colocar_fullscreen(page):

    print(
        "[PLAYER] Tentando fullscreen...",
        flush=True
    )

    try:

        page.evaluate("""
        async () => {

            const video =
                document.querySelector("video");

            if (!video)
                return;

            try {

                if (
                    !document.fullscreenElement &&
                    video.requestFullscreen
                ) {

                    await video.requestFullscreen();

                }

            } catch {}

        }
        """)

    except Exception:
        pass


# ============================================================
# CLICAR EM RECARREGAR
# ============================================================

def clicar_recarregar(page):

    print(
        "[PLAYER] Procurando botão de recarregar...",
        flush=True
    )

    try:

        elementos = page.locator(
            "button, [role='button']"
        )

        total = elementos.count()

        for i in range(total):

            try:

                texto = elementos.nth(i).inner_text(
                    timeout=1000
                )

                if (
                    "RECARREGAR" in
                    texto.upper()
                    or
                    "RECARREGAR PLAYER" in
                    texto.upper()
                ):

                    print(
                        "[PLAYER] Clicando:",
                        texto,
                        flush=True
                    )

                    elementos.nth(i).click(
                        timeout=5000
                    )

                    time.sleep(5)

                    return True

            except Exception:
                pass

    except Exception:
        pass

    return False


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    print(
        "[CHROMIUM] Iniciando navegador...",
        flush=True
    )

    chromium = "/usr/bin/chromium"

    if not os.path.exists(chromium):

        raise RuntimeError(
            "Chromium não encontrado em /usr/bin/chromium."
        )

    print(
        "[CHROMIUM] Executável:",
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

                "--disable-notifications",

                "--disable-popup-blocking",

                "--allow-running-insecure-content",

                "--disable-features=Translate",

                "--no-first-run",

                "--no-default-browser-check",

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

            ignore_https_errors=True,

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
        # CONSOLE DO SITE
        # ----------------------------------------------------

        page.on(
            "console",
            lambda msg:
            print(
                "[BROWSER]",
                msg.type,
                ":",
                msg.text,
                flush=True
            )
        )

        # ----------------------------------------------------
        # ERROS JAVASCRIPT
        # ----------------------------------------------------

        page.on(
            "pageerror",
            lambda error:
            print(
                "[JAVASCRIPT ERROR]",
                error,
                flush=True
            )
        )

        # ----------------------------------------------------
        # REQUISIÇÕES
        # ----------------------------------------------------

        def on_request(request):

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
            on_request
        )

        # ----------------------------------------------------
        # RESPOSTAS
        # ----------------------------------------------------

        def on_response(response):

            if response.request.resource_type in [
                "media",
                "xhr",
                "fetch"
            ]:

                print(
                    "[RESPONSE]",
                    response.status,
                    response.request.resource_type,
                    response.url,
                    flush=True
                )

        page.on(
            "response",
            on_response
        )

        # ----------------------------------------------------
        # FALHAS
        # ----------------------------------------------------

        def on_failed(request):

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
            on_failed
        )

        # ----------------------------------------------------
        # ABRIR
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
            "[CHROMIUM] Página:",
            page.url,
            flush=True
        )

        print(
            "[CHROMIUM] Esperando player...",
            flush=True
        )

        time.sleep(15)

        # ----------------------------------------------------
        # PRIMEIRO DIAGNÓSTICO
        # ----------------------------------------------------

        diagnosticar_video(page)

        # ----------------------------------------------------
        # CLIQUE NO CENTRO
        # ----------------------------------------------------

        try:

            page.mouse.click(
                WIDTH // 2,
                HEIGHT // 2
            )

        except Exception:
            pass

        time.sleep(2)

        # ----------------------------------------------------
        # RECARREGAR PLAYER
        # ----------------------------------------------------

        clicou = clicar_recarregar(page)

        if clicou:

            print(
                "[PLAYER] Player recarregado.",
                flush=True
            )

            time.sleep(5)

        # ----------------------------------------------------
        # FORÇAR PLAY
        # ----------------------------------------------------

        for tentativa in range(1, 4):

            print(
                f"[PLAYER] Tentativa {tentativa}/3",
                flush=True
            )

            forcar_player(page)

            time.sleep(5)

            dados = diagnosticar_video(page)

            funcionando = False

            for video in dados:

                if (
                    video.get("readyState", 0) >= 2
                    and
                    video.get("width", 0) > 0
                    and
                    video.get("height", 0) > 0
                ):

                    funcionando = True

            if funcionando:

                print(
                    "[PLAYER] VÍDEO ESTÁ SENDO REPRODUZIDO.",
                    flush=True
                )

                break

            if tentativa < 3:

                clicar_recarregar(page)

                time.sleep(5)

        # ----------------------------------------------------
        # FULLSCREEN
        # ----------------------------------------------------

        colocar_fullscreen(page)

        time.sleep(3)

        # ----------------------------------------------------
        # SCREENSHOT
        # ----------------------------------------------------

        try:

            page.screenshot(
                path=os.path.join(
                    STREAM_DIR,
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
        # MONITORAMENTO
        # ----------------------------------------------------

        ultimo_tempo = None

        while True:

            time.sleep(15)

            dados = diagnosticar_video(page)

            for video in dados:

                tempo = video.get(
                    "currentTime"
                )

                if (
                    ultimo_tempo is not None
                    and
                    tempo == ultimo_tempo
                ):

                    print(
                        "[PLAYER] AVISO: vídeo parece congelado.",
                        flush=True
                    )

                    forcar_player(page)

                ultimo_tempo = tempo

            # Se o player perdeu a reprodução,
            # tenta novamente.
            for video in dados:

                if video.get("paused"):

                    print(
                        "[PLAYER] Vídeo pausado. Tentando play...",
                        flush=True
                    )

                    forcar_player(page)


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    print(
        "[FFMPEG] Iniciando captura...",
        flush=True
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
        # CODEC
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

        "-r",
        str(FPS),

        "-g",
        "60",

        "-keyint_min",
        "60",

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
        "5",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        f"{STREAM_DIR}/segment_%05d.ts",

        f"{STREAM_DIR}/live.m3u8"
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

    def mostrar_log():

        for linha in iter(
            ffmpeg.stdout.readline,
            ""
        ):

            if linha:
                print(
                    "[FFMPEG]",
                    linha.rstrip(),
                    flush=True
                )

    threading.Thread(
        target=mostrar_log,
        daemon=True
    ).start()

    time.sleep(5)

    if ffmpeg.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou inesperadamente."
        )

    print(
        "[FFMPEG] Captura funcionando.",
        flush=True
    )


# ============================================================
# MAIN
# ============================================================

def iniciar():

    print("")
    print("==========================================================")
    print("                 WEB TV STREAM")
    print("==========================================================")

    limpar_stream()

    # 1
    iniciar_xvfb()

    # 2
    iniciar_audio()

    # 3
    iniciar_http()

    # 4
    iniciar_ngrok()

    # 5
    navegador = threading.Thread(
        target=iniciar_navegador,
        daemon=True
    )

    navegador.start()

    print(
        "[MAIN] Aguardando navegador carregar...",
        flush=True
    )

    # Dá tempo para o site e o vídeo iniciarem
    time.sleep(30)

    # 6
    iniciar_ffmpeg()

    print("")
    print("==========================================================")
    print("             TRANSMISSÃO INICIADA")
    print("==========================================================")
    print("")

    while True:

        time.sleep(30)


# ============================================================
# EXECUTAR
# ============================================================

if __name__ == "__main__":
    iniciar()
