import os
import time
import subprocess
import signal
import sys

# ============================================================
# CONFIGURAÇÃO
# ============================================================

WIDTH = 1280
HEIGHT = 720
DISPLAY = ":99"

URL_ALVO = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"

STREAM_DIR = "stream"

processo_ffmpeg = None
processo_http = None
processo_serveo = None
processo_xvfb = None


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(sig=None, frame=None):

    print("\nEncerrando transmissão...", flush=True)

    processos = [
        processo_ffmpeg,
        processo_http,
        processo_serveo,
        processo_xvfb
    ]

    for processo in processos:

        if processo:

            try:

                if processo.poll() is None:
                    processo.terminate()

            except Exception:
                pass

    time.sleep(2)

    for processo in processos:

        if processo:

            try:

                if processo.poll() is None:
                    processo.kill()

            except Exception:
                pass

    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


# ============================================================
# INICIAR
# ============================================================

def iniciar():

    global processo_ffmpeg
    global processo_http
    global processo_serveo
    global processo_xvfb

    print("")
    print("==========================================================")
    print("                 WEB TV AO VIVO")
    print("==========================================================")
    print("")

    # ========================================================
    # 1. PASTA DO STREAM
    # ========================================================

    os.makedirs(
        STREAM_DIR,
        exist_ok=True
    )

    # Remove segmentos antigos
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

    # Cria playlist inicial
    with open(
        os.path.join(
            STREAM_DIR,
            "live.m3u8"
        ),
        "w"
    ) as f:

        f.write(
            "#EXTM3U\n"
        )

    # ========================================================
    # 2. SERVIDOR HTTP
    # ========================================================

    print(
        "[HTTP] Iniciando servidor na porta 8080...",
        flush=True
    )

    processo_http = subprocess.Popen(
        [
            "python3",
            "-m",
            "http.server",
            "8080",
            "--directory",
            STREAM_DIR
        ]
    )

    time.sleep(2)

    # ========================================================
    # 3. SERVEO
    # ========================================================

    print(
        "[SERVEO] Iniciando túnel...",
        flush=True
    )

    processo_serveo = subprocess.Popen(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-R",
            "80:localhost:8080",
            "serveo.net"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    time.sleep(5)

    print(
        "[SERVEO] Túnel iniciado.",
        flush=True
    )

    # ========================================================
    # 4. XVFB
    # ========================================================

    print(
        "[XVFB] Criando tela virtual 1280x720...",
        flush=True
    )

    processo_xvfb = subprocess.Popen(
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
        stderr=subprocess.DEVNULL
    )

    os.environ["DISPLAY"] = DISPLAY

    time.sleep(3)

    print(
        "[XVFB] Tela virtual pronta:",
        DISPLAY,
        flush=True
    )

    # ========================================================
    # 5. PULSE AUDIO
    # ========================================================

    print(
        "[AUDIO] Verificando PulseAudio...",
        flush=True
    )

    # O workflow já inicia o PulseAudio.
    # Aqui apenas garantimos que está rodando.

    subprocess.run(
        [
            "pulseaudio",
            "-D",
            "--exit-idle-time=-1",
            "--system=false"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    time.sleep(2)

    # Verificar auto_null.monitor
    resultado_audio = subprocess.run(
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
        "[AUDIO] Fontes disponíveis:",
        flush=True
    )

    print(
        resultado_audio.stdout,
        flush=True
    )

    # ========================================================
    # 6. FFMPEG
    # ========================================================

    print(
        "[FFMPEG] Iniciando captura...",
        flush=True
    )

    ffmpeg_cmd = [

        "ffmpeg",

        "-y",

        # -------------------------
        # ÁUDIO
        # -------------------------

        "-f",
        "pulse",

        "-i",
        "auto_null.monitor",

        # -------------------------
        # VÍDEO
        # -------------------------

        "-f",
        "x11grab",

        "-draw_mouse",
        "0",

        "-framerate",
        "30",

        "-video_size",
        "1280x720",

        "-i",
        ":99.0",

        # -------------------------
        # VÍDEO
        # -------------------------

        "-c:v",
        "libx264",

        "-preset",
        "ultrafast",

        "-tune",
        "zerolatency",

        "-profile:v",
        "baseline",

        "-pix_fmt",
        "yuv420p",

        "-r",
        "30",

        "-g",
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        # -------------------------
        # ÁUDIO
        # -------------------------

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        "-ac",
        "2",

        # -------------------------
        # HLS
        # -------------------------

        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "5",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        "stream/segment_%05d.ts",

        "stream/live.m3u8"
    ]

    print(
        "[FFMPEG] Comando preparado.",
        flush=True
    )

    processo_ffmpeg = subprocess.Popen(
        ffmpeg_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    # Mostrar log do FFmpeg
    def monitorar_ffmpeg():

        for linha in iter(
            processo_ffmpeg.stdout.readline,
            ""
        ):

            if linha:
                print(
                    "[FFMPEG]",
                    linha.rstrip(),
                    flush=True
                )

    import threading

    threading.Thread(
        target=monitorar_ffmpeg,
        daemon=True
    ).start()

    time.sleep(5)

    # ========================================================
    # 7. PLAYWRIGHT
    # ========================================================

    from playwright.sync_api import sync_playwright

    print(
        "[CHROMIUM] Iniciando navegador...",
        flush=True
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=False,

            args=[

                "--no-sandbox",

                "--disable-setuid-sandbox",

                "--disable-dev-shm-usage",

                "--disable-gpu",

                "--disable-software-rasterizer",

                "--use-gl=swiftshader",

                "--ignore-gpu-blocklist",

                "--autoplay-policy=no-user-gesture-required",

                "--disable-background-timer-throttling",

                "--disable-backgrounding-occluded-windows",

                "--disable-renderer-backgrounding",

                "--disable-popup-blocking",

                "--disable-notifications",

                "--disable-infobars",

                "--no-first-run",

                "--no-default-browser-check",

                # -----------------------------
                # TELA CHEIA
                # -----------------------------

                "--kiosk",

                "--start-fullscreen",

                "--start-maximized",

                "--window-position=0,0",

                "--window-size=1280,720",

                "--force-device-scale-factor=1"
            ]
        )

        context = browser.new_context(

            viewport={
                "width": 1280,
                "height": 720
            },

            screen={
                "width": 1280,
                "height": 720
            },

            ignore_https_errors=True
        )

        page = context.new_page()

        # ====================================================
        # LOG DO NAVEGADOR
        # ====================================================

        page.on(
            "console",
            lambda msg:
            print(
                "[BROWSER]",
                msg.type,
                msg.text,
                flush=True
            )
        )

        page.on(
            "pageerror",
            lambda error:
            print(
                "[BROWSER ERROR]",
                error,
                flush=True
            )
        )

        # ====================================================
        # ABRIR SITE
        # ====================================================

        print(
            "[CHROMIUM] Acessando:",
            URL_ALVO,
            flush=True
        )

        try:

            page.goto(
                URL_ALVO,
                wait_until="commit",
                timeout=0
            )

        except Exception as e:

            print(
                "[CHROMIUM] Aviso:",
                e,
                flush=True
            )

        print(
            "[CHROMIUM] Página aberta.",
            flush=True
        )

        # ====================================================
        # ESPERAR PLAYER
        # ====================================================

        print(
            "[PLAYER] Aguardando player...",
            flush=True
        )

        time.sleep(8)

        # ====================================================
        # TENTAR ATIVAR VÍDEOS
        # ====================================================

        def ativar_videos():

            try:

                resultado = page.evaluate("""
                async () => {

                    const videos =
                        [...document.querySelectorAll("video")];

                    const resultados = [];

                    for (
                        let i = 0;
                        i < videos.length;
                        i++
                    ) {

                        const video = videos[i];

                        video.autoplay = true;
                        video.playsInline = true;

                        let tocou = false;

                        try {

                            video.muted = false;

                            await video.play();

                            tocou = true;

                        } catch (e) {

                            try {

                                video.muted = true;

                                await video.play();

                                tocou = true;

                            } catch (e2) {}

                        }

                        resultados.push({

                            index: i,

                            paused:
                                video.paused,

                            readyState:
                                video.readyState,

                            currentTime:
                                video.currentTime,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight,

                            playing:
                                tocou

                        });
                    }

                    return resultados;
                }
                """)

                print(
                    "[PLAYER] Vídeos:",
                    resultado,
                    flush=True
                )

            except Exception as e:

                print(
                    "[PLAYER] Erro:",
                    e,
                    flush=True
                )

        ativar_videos()

        # ====================================================
        # CLIQUE NO PLAYER
        # ====================================================

        try:

            page.mouse.click(
                640,
                360
            )

            print(
                "[PLAYER] Clique central executado.",
                flush=True
            )

        except Exception as e:

            print(
                "[PLAYER] Erro no clique:",
                e,
                flush=True
            )

        time.sleep(3)

        # ====================================================
        # FORÇAR FULLSCREEN DO DOCUMENTO
        # ====================================================

        try:

            page.evaluate("""
            async () => {

                if (
                    !document.fullscreenElement &&
                    document.documentElement.requestFullscreen
                ) {

                    try {

                        await document.documentElement.requestFullscreen();

                    } catch (e) {

                        console.log(
                            "Fullscreen API:",
                            e
                        );

                    }

                }
            }
            """)

            print(
                "[FULLSCREEN] Solicitação executada.",
                flush=True
            )

        except Exception as e:

            print(
                "[FULLSCREEN] API não disponível:",
                e,
                flush=True
            )

        # ====================================================
        # CSS DE SEGURANÇA
        # ====================================================
        #
        # Se o player do site não ocupar toda a área,
        # deixamos o conteúdo visual ocupar a janela.
        #

        try:

            page.add_style_tag(
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

                video {

                    max-width: 100% !important;
                    max-height: 100% !important;
                }

                """
            )

        except Exception:
            pass

        # ====================================================
        # SCREENSHOT DE DEBUG
        # ====================================================

        try:

            page.screenshot(
                path="stream/browser_debug.png"
            )

            print(
                "[DEBUG] Screenshot salvo.",
                flush=True
            )

        except Exception:
            pass

        # ====================================================
        # VIGIA
        # ====================================================

        print(
            "[STREAM] Transmissão funcionando.",
            flush=True
        )

        print(
            "[STREAM] Mantendo navegador aberto...",
            flush=True
        )

        try:

            while True:

                time.sleep(5)

                try:

                    ativar_videos()

                    # Clique periódico para manter
                    # o player ativo após troca de vídeo.

                    page.mouse.click(
                        640,
                        360
                    )

                except Exception:
                    pass

        except KeyboardInterrupt:

            encerrar()


if __name__ == "__main__":
    iniciar()
