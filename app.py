import os
import time
import subprocess
import asyncio
import threading
from pyppeteer import launch


# ============================================================
# CONFIGURAÇÕES
# ============================================================

STREAM_DIR = "stream"
DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)


# ============================================================
# FUNÇÃO PRINCIPAL
# ============================================================

def iniciar():

    print("")
    print("==========================================================")
    print("              INICIANDO WEB TV")
    print("==========================================================")
    print("")

    os.makedirs(STREAM_DIR, exist_ok=True)

    # --------------------------------------------------------
    # 1. Limpa arquivos antigos do HLS
    # --------------------------------------------------------

    print("[1/7] Limpando arquivos antigos...")

    for arquivo in os.listdir(STREAM_DIR):
        caminho = os.path.join(STREAM_DIR, arquivo)

        try:
            if os.path.isfile(caminho):
                os.remove(caminho)
        except Exception:
            pass

    # --------------------------------------------------------
    # 2. Inicia Xvfb
    # --------------------------------------------------------

    print("[2/7] Iniciando tela virtual Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    xvfb = subprocess.Popen([
        "Xvfb",
        DISPLAY,
        "-screen",
        "0",
        f"{WIDTH}x{HEIGHT}x24",
        "-ac"
    ])

    time.sleep(3)

    print("Tela virtual iniciada.")


    # --------------------------------------------------------
    # 3. Inicia PulseAudio
    # --------------------------------------------------------

    print("[3/7] Iniciando sistema de áudio...")

    os.environ["PULSE_RUNTIME_PATH"] = "/tmp/pulse"

    os.makedirs("/tmp/pulse", exist_ok=True)

    pulseaudio = subprocess.Popen([
        "pulseaudio",
        "--start",
        "--exit-idle-time=-1"
    ])

    time.sleep(3)

    # Cria um dispositivo de áudio virtual
    resultado_audio = subprocess.run(
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

    if resultado_audio.returncode == 0:
        print("Áudio virtual WebTV criado.")
    else:
        print("Aviso: não foi possível criar o áudio virtual.")
        print(resultado_audio.stderr)


    # --------------------------------------------------------
    # 4. Servidor HTTP
    # --------------------------------------------------------

    print("[4/7] Iniciando servidor HTTP na porta 8080...")

    servidor_http = subprocess.Popen([
        "python3",
        "-m",
        "http.server",
        "8080",
        "--directory",
        STREAM_DIR
    ])

    time.sleep(3)

    print("Servidor HTTP iniciado.")


    # --------------------------------------------------------
    # 5. Túnel público
    # --------------------------------------------------------

    print("[5/7] Iniciando túnel público...")

    tunnel = subprocess.Popen(
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
            "nokey@localhost.run"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )


    # Mostra o endereço do túnel no log
    def ler_tunel():

        try:
            for linha in iter(tunnel.stdout.readline, ""):

                if linha:
                    print("[TUNEL]", linha.strip())

        except Exception as erro:
            print("Erro lendo túnel:", erro)


    threading.Thread(
        target=ler_tunel,
        daemon=True
    ).start()

    time.sleep(5)


    # --------------------------------------------------------
    # 6. Inicia FFmpeg
    # --------------------------------------------------------

    print("[6/7] Iniciando FFmpeg...")

    audio_device = "webtv.monitor"

    ffmpeg_cmd = [

        "ffmpeg",

        "-y",

        # ============================
        # ÁUDIO
        # ============================

        "-f",
        "pulse",

        "-i",
        audio_device,

        # ============================
        # VÍDEO
        # ============================

        "-f",
        "x11grab",

        "-draw_mouse",
        "0",

        "-video_size",
        f"{WIDTH}x{HEIGHT}",

        "-framerate",
        "30",

        "-i",
        f"{DISPLAY}.0",

        # ============================
        # CODEC DE VÍDEO
        # ============================

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

        # ============================
        # CODEC DE ÁUDIO
        # ============================

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        "-ac",
        "2",

        # ============================
        # HLS
        # ============================

        "-f",
        "hls",

        "-hls_time",
        "2",

        "-hls_list_size",
        "5",

        "-hls_flags",
        "delete_segments+append_list",

        "-hls_segment_filename",
        f"{STREAM_DIR}/segment_%05d.ts",

        f"{STREAM_DIR}/live.m3u8"
    ]


    print("")
    print("Executando FFmpeg:")
    print(" ".join(ffmpeg_cmd))
    print("")


    processo_ffmpeg = subprocess.Popen(
        ffmpeg_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )


    # Mostra o log do FFmpeg
    def ler_ffmpeg():

        try:

            for linha in iter(
                processo_ffmpeg.stdout.readline,
                ""
            ):

                if linha:
                    print("[FFMPEG]", linha.strip())

        except Exception:
            pass


    threading.Thread(
        target=ler_ffmpeg,
        daemon=True
    ).start()


    # Dá alguns segundos para o HLS começar
    print("Aguardando FFmpeg gerar o primeiro segmento...")

    time.sleep(8)


    # Verifica se FFmpeg continua funcionando
    if processo_ffmpeg.poll() is not None:

        print("")
        print("==========================================================")
        print("ERRO: O FFmpeg encerrou.")
        print("A transmissão não pôde ser iniciada.")
        print("==========================================================")
        print("")

        return


    print("")
    print("FFmpeg está funcionando.")
    print("Arquivo HLS: stream/live.m3u8")
    print("")


    # --------------------------------------------------------
    # 7. Inicia navegador
    # --------------------------------------------------------

    print("[7/7] Iniciando Chromium...")


    async def abrir_navegador():

        print("Abrindo Chromium...")

        browser = await launch(

            headless=False,

            # Chromium instalado pelo apt
            executablePath="/usr/bin/chromium",

            # Remove a mensagem:
            # "Chrome is being controlled by automated test software"
            ignoreDefaultArgs=[
                "--enable-automation"
            ],

            args=[

                # Segurança
                "--no-sandbox",
                "--disable-setuid-sandbox",

                # Memória
                "--disable-dev-shm-usage",

                # Reprodução automática
                "--autoplay-policy=no-user-gesture-required",

                # Evita indicação visual de automação
                "--disable-blink-features=AutomationControlled",

                # Tela cheia / quiosque
                "--kiosk",
                "--start-fullscreen",

                # Resolução
                "--window-size=1280,720",

                # Estabilidade
                "--disable-gpu",

                "--no-first-run",
                "--no-default-browser-check",

                # Permite áudio
                "--use-fake-ui-for-media-stream"
            ]
        )


        page = await browser.newPage()


        # Define resolução
        await page.setViewport({
            "width": WIDTH,
            "height": HEIGHT
        })


        print("")
        print("==========================================================")
        print("ABRINDO WEB TV")
        print("==========================================================")
        print(URL_ALVO)
        print("")


        try:

            await page.goto(
                URL_ALVO,
                {
                    "waitUntil": "networkidle2",
                    "timeout": 120000
                }
            )

            print("Site carregado com sucesso.")

        except Exception as erro:

            print("")
            print("AVISO AO ABRIR O SITE:")
            print(erro)
            print("")


        # ----------------------------------------------------
        # Aguarda o player carregar
        # ----------------------------------------------------

        print("Aguardando o player...")

        await asyncio.sleep(10)


        # ----------------------------------------------------
        # Tenta iniciar vídeos automaticamente
        # ----------------------------------------------------

        try:

            await page.evaluate("""
                () => {

                    const videos =
                        document.querySelectorAll("video");

                    videos.forEach(video => {

                        video.muted = false;

                        video.autoplay = true;

                        video.play().catch(() => {});

                    });

                }
            """)

            print("Comando de reprodução enviado.")

        except Exception as erro:

            print("Aviso no player:", erro)


        # ----------------------------------------------------
        # Mantém o navegador funcionando
        # ----------------------------------------------------

        print("")
        print("==========================================================")
        print("WEB TV ONLINE")
        print("==========================================================")
        print("")


        while True:

            await asyncio.sleep(10)

            try:

                # Verifica se existe vídeo na página
                quantidade_videos = await page.evaluate("""
                    () => document.querySelectorAll("video").length
                """)

                print(
                    f"Player monitorado. "
                    f"Vídeos encontrados: {quantidade_videos}"
                )


                # Tenta reproduzir novamente vídeos pausados
                await page.evaluate("""
                    () => {

                        document
                            .querySelectorAll("video")
                            .forEach(video => {

                                if (video.paused) {
                                    video.play().catch(() => {});
                                }

                            });

                    }
                """)


            except Exception as erro:

                print(
                    "Erro monitorando o player:",
                    erro
                )


    # --------------------------------------------------------
    # Executa navegador
    # --------------------------------------------------------

    try:

        asyncio.get_event_loop().run_until_complete(
            abrir_navegador()
        )

    except KeyboardInterrupt:

        print("")
        print("Encerrando transmissão...")
        print("")

    finally:

        try:
            processo_ffmpeg.terminate()
        except Exception:
            pass

        try:
            servidor_http.terminate()
        except Exception:
            pass

        try:
            tunnel.terminate()
        except Exception:
            pass

        try:
            xvfb.terminate()
        except Exception:
            pass

        try:
            pulseaudio.terminate()
        except Exception:
            pass


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    iniciar()
