import os
import time
import subprocess
import asyncio
from pyppeteer import launch


STREAM_DIR = "stream"
DISPLAY = ":99"
WIDTH = 1280
HEIGHT = 720


def iniciar():

    os.makedirs(STREAM_DIR, exist_ok=True)

    # ---------------------------------------------------------
    # 1. Xvfb
    # ---------------------------------------------------------

    print("Iniciando Xvfb...")

    xvfb = subprocess.Popen([
        "Xvfb",
        DISPLAY,
        "-screen", "0",
        f"{WIDTH}x{HEIGHT}x24",
        "-ac"
    ])

    os.environ["DISPLAY"] = DISPLAY

    time.sleep(2)

    # ---------------------------------------------------------
    # 2. PulseAudio
    # ---------------------------------------------------------

    print("Iniciando PulseAudio...")

    os.environ["PULSE_RUNTIME_PATH"] = "/tmp/pulse"

    os.makedirs("/tmp/pulse", exist_ok=True)

    pulseaudio = subprocess.Popen([
        "pulseaudio",
        "--start",
        "--exit-idle-time=-1",
        "--system=false"
    ])

    time.sleep(3)

    # Descobre se o PulseAudio está funcionando
    subprocess.run([
        "pactl",
        "info"
    ], check=False)

    # Cria um sink virtual
    subprocess.run([
        "pactl",
        "load-module",
        "module-null-sink",
        "sink_name=webtv",
        "sink_properties=device.description=WebTV"
    ], check=False)

    time.sleep(2)

    AUDIO_DEVICE = "webtv.monitor"

    # ---------------------------------------------------------
    # 3. Servidor HTTP
    # ---------------------------------------------------------

    print("Iniciando servidor HTTP na porta 8080...")

    http = subprocess.Popen([
        "python3",
        "-m",
        "http.server",
        "8080",
        "--directory",
        STREAM_DIR
    ])

    time.sleep(2)

    # ---------------------------------------------------------
    # 4. Túnel
    # ---------------------------------------------------------

    print("Iniciando túnel...")

    tunnel = subprocess.Popen(
        [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-R", "80:localhost:8080",
            "nokey@localhost.run"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    # Mostra o endereço fornecido pelo túnel
    def mostrar_tunel():
        for linha in iter(tunnel.stdout.readline, ""):
            if linha:
                print("[TUNEL]", linha.strip())

    import threading

    threading.Thread(
        target=mostrar_tunel,
        daemon=True
    ).start()

    time.sleep(5)

    # ---------------------------------------------------------
    # 5. FFmpeg
    # ---------------------------------------------------------

    print("Iniciando FFmpeg...")

    ffmpeg_cmd = [
        "ffmpeg",

        "-y",

        # Áudio
        "-f", "pulse",
        "-i", AUDIO_DEVICE,

        # Vídeo
        "-f", "x11grab",
        "-draw_mouse", "0",
        "-video_size", f"{WIDTH}x{HEIGHT}",
        "-framerate", "30",
        "-i", f"{DISPLAY}.0",

        # Vídeo
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",

        # Áudio
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",

        # HLS
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments+append_list",
        "-hls_segment_filename",
        f"{STREAM_DIR}/segment_%03d.ts",

        f"{STREAM_DIR}/live.m3u8"
    ]

    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    time.sleep(5)

    # Verifica se FFmpeg morreu
    if processo_ffmpeg.poll() is not None:
        print("ERRO: FFmpeg encerrou imediatamente.")
        return

    print("FFmpeg está transmitindo.")

    # ---------------------------------------------------------
    # 6. Navegador
    # ---------------------------------------------------------

    async def abrir_navegador():

        print("Iniciando Chromium...")

        browser = await launch(
            headless=False,

            executablePath="/usr/bin/chromium",

            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",

                "--autoplay-policy=no-user-gesture-required",

                "--disable-gpu",
                "--disable-software-rasterizer",

                "--window-size=1280,720",
                "--start-maximized"
            ]
        )

        page = await browser.newPage()

        await page.setViewport({
            "width": WIDTH,
            "height": HEIGHT
        })

        url_alvo = (
            "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
            ".us-east5.run.app/watch"
        )

        print("Abrindo:")
        print(url_alvo)

        try:

            await page.goto(
                url_alvo,
                {
                    "waitUntil": "networkidle2",
                    "timeout": 120000
                }
            )

            print("Site carregado.")

            await asyncio.sleep(10)

            # Tenta iniciar vídeos da página
            await page.evaluate("""
                () => {
                    document.querySelectorAll('video').forEach(video => {
                        video.muted = false;
                        video.play().catch(() => {});
                    });
                }
            """)

            print("Player iniciado.")

        except Exception as e:
            print("Erro ao abrir site:", e)

        # Mantém navegador vivo
        while True:

            await asyncio.sleep(10)

            try:

                await page.evaluate("""
                    () => {
                        document.querySelectorAll('video').forEach(video => {
                            if (video.paused) {
                                video.play().catch(() => {});
                            }
                        });
                    }
                """)

            except Exception as e:
                print("Erro verificando player:", e)

    # ---------------------------------------------------------
    # 7. Executar
    # ---------------------------------------------------------

    try:

        asyncio.get_event_loop().run_until_complete(
            abrir_navegador()
        )

    except KeyboardInterrupt:

        print("Encerrando transmissão...")

        processo_ffmpeg.terminate()
        http.terminate()
        tunnel.terminate()
        xvfb.terminate()
        pulseaudio.terminate()


if __name__ == "__main__":
    iniciar()
