import os
import time
import subprocess
import asyncio
import threading
from pyppeteer import launch


STREAM_DIR = "stream"
DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)


def iniciar():

    print("")
    print("==========================================================")
    print("                 INICIANDO WEB TV")
    print("==========================================================")
    print("")

    os.makedirs(STREAM_DIR, exist_ok=True)

    # ========================================================
    # LIMPA STREAM ANTIGO
    # ========================================================

    print("[1] Limpando stream antigo...")

    for arquivo in os.listdir(STREAM_DIR):

        caminho = os.path.join(STREAM_DIR, arquivo)

        try:
            if os.path.isfile(caminho):
                os.remove(caminho)
        except:
            pass


    # ========================================================
    # Xvfb
    # ========================================================

    print("[2] Iniciando tela virtual...")

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

    print("Tela virtual pronta.")


    # ========================================================
    # PULSEAUDIO
    # ========================================================

    print("[3] Iniciando áudio...")

    os.environ["PULSE_RUNTIME_PATH"] = "/tmp/pulse"

    os.makedirs("/tmp/pulse", exist_ok=True)

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        check=False
    )

    time.sleep(3)

    subprocess.run(
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

    print("Áudio virtual pronto.")


    # ========================================================
    # SERVIDOR HTTP
    # ========================================================

    print("[4] Iniciando servidor HTTP...")

    servidor_http = subprocess.Popen([
        "python3",
        "-m",
        "http.server",
        "8080",
        "--directory",
        STREAM_DIR
    ])

    time.sleep(2)

    print("Servidor HTTP funcionando na porta 8080.")


    # ========================================================
    # TÚNEL
    # ========================================================

    print("[5] Iniciando túnel público...")

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


    def ler_tunel():

        try:

            for linha in iter(
                tunnel.stdout.readline,
                ""
            ):

                if linha:
                    print("[TUNEL]", linha.strip())

        except:
            pass


    threading.Thread(
        target=ler_tunel,
        daemon=True
    ).start()


    time.sleep(5)


    # ========================================================
    # NAVEGADOR
    # ========================================================

    async def abrir_navegador():

        print("")
        print("[6] Iniciando Chromium...")
        print("")


        browser = await launch(

            headless=False,

            executablePath="/usr/bin/chromium",

            # Remove a barra:
            # Chrome is being controlled by automated test software
            ignoreDefaultArgs=[
                "--enable-automation"
            ],

            args=[

                "--no-sandbox",
                "--disable-setuid-sandbox",

                "--disable-dev-shm-usage",

                "--autoplay-policy=no-user-gesture-required",

                "--kiosk",
                "--start-fullscreen",

                "--window-size=1280,720",

                "--force-device-scale-factor=1",

                "--no-first-run",
                "--no-default-browser-check"
            ]
        )


        page = await browser.newPage()


        await page.setViewport({
            "width": WIDTH,
            "height": HEIGHT
        })


        print("Abrindo painel da Web TV...")

        try:

            await page.goto(
                URL_ALVO,
                {
                    "waitUntil": "domcontentloaded",
                    "timeout": 120000
                }
            )

            print("Painel carregado.")

        except Exception as erro:

            print("")
            print("ERRO AO ABRIR O PAINEL:")
            print(erro)
            print("")


        print("Aguardando o painel carregar completamente...")

        await asyncio.sleep(15)


        # ====================================================
        # NÃO ALTERAMOS OS VÍDEOS
        # ====================================================

        print("")
        print("==========================================================")
        print("PAINEL CARREGADO")
        print("Chromium está sendo exibido no Xvfb.")
        print("Agora FFmpeg poderá capturar a tela.")
        print("==========================================================")
        print("")


        # ====================================================
        # Mantém navegador vivo
        # ====================================================

        while True:

            await asyncio.sleep(30)

            try:

                titulo = await page.title()

                print(
                    "[CHROMIUM] Página ativa:",
                    titulo
                )

            except Exception as erro:

                print(
                    "[CHROMIUM] Aviso:",
                    erro
                )


    # ========================================================
    # INICIA O NAVEGADOR
    # ========================================================

    try:

        loop = asyncio.new_event_loop()

        asyncio.set_event_loop(loop)

        navegador_task = loop.create_task(
            abrir_navegador()
        )

        # Dá tempo para o Chromium realmente abrir
        # e renderizar o painel.
        print("")
        print("Aguardando Chromium renderizar...")
        loop.run_until_complete(
            asyncio.sleep(20)
        )


        # ====================================================
        # FFmpeg começa SOMENTE AGORA
        # ====================================================

        print("")
        print("[7] Iniciando FFmpeg...")
        print("")


        ffmpeg_cmd = [

            "ffmpeg",

            "-y",

            # ================================
            # VÍDEO
            # ================================

            "-f",
            "x11grab",

            "-draw_mouse",
            "0",

            "-framerate",
            "30",

            "-video_size",
            f"{WIDTH}x{HEIGHT}",

            "-i",
            f"{DISPLAY}.0",

            # ================================
            # ÁUDIO
            # ================================

            "-f",
            "pulse",

            "-i",
            "webtv.monitor",

            # ================================
            # VÍDEO
            # ================================

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

            # ================================
            # ÁUDIO
            # ================================

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-ar",
            "44100",

            "-ac",
            "2",

            # ================================
            # HLS
            # ================================

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


        print("Comando FFmpeg:")
        print(" ".join(ffmpeg_cmd))
        print("")


        processo_ffmpeg = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )


        # ====================================================
        # LOG DO FFMPEG
        # ====================================================

        def ler_ffmpeg():

            try:

                for linha in iter(
                    processo_ffmpeg.stdout.readline,
                    ""
                ):

                    if linha:
                        print(
                            "[FFMPEG]",
                            linha.strip()
                        )

            except:
                pass


        threading.Thread(
            target=ler_ffmpeg,
            daemon=True
        ).start()


        print("")
        print("==========================================================")
        print("TRANSMISSÃO INICIADA")
        print("==========================================================")
        print("")


        # ====================================================
        # MANTÉM TUDO RODANDO
        # ====================================================

        loop.run_until_complete(
            navegador_task
        )


    except KeyboardInterrupt:

        print("")
        print("Encerrando transmissão...")


    except Exception as erro:

        print("")
        print("ERRO:")
        print(erro)


if __name__ == "__main__":
    iniciar()
