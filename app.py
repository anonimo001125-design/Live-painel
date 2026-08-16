import os
import time
import subprocess
import signal
import threading
from pathlib import Path

# ============================================================
# CONFIGURAÇÃO
# ============================================================

WIDTH = 1280
HEIGHT = 720
DISPLAY = ":99"
PORT = 8080

# COLOQUE A URL DO SEU PAINEL AQUI
URL_ALVO = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"

STREAM_DIR = Path("stream")
PLAYLIST = STREAM_DIR / "live.m3u8"

processos = []


# ============================================================
# LIMPEZA
# ============================================================

def limpar():
    print("Encerrando processos...")

    for processo in processos:
        try:
            if processo.poll() is None:
                processo.terminate()
        except Exception:
            pass


signal.signal(signal.SIGTERM, lambda s, f: limpar())
signal.signal(signal.SIGINT, lambda s, f: limpar())


# ============================================================
# PREPARAR STREAM
# ============================================================

def preparar_stream():
    STREAM_DIR.mkdir(parents=True, exist_ok=True)

    for arquivo in STREAM_DIR.glob("segment_*.ts"):
        try:
            arquivo.unlink()
        except Exception:
            pass

    try:
        PLAYLIST.unlink()
    except Exception:
        pass


# ============================================================
# Xvfb
# ============================================================

def iniciar_xvfb():
    print("Iniciando Xvfb...")

    subprocess.run(
        ["pkill", "-f", "Xvfb :99"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(1)

    xvfb = subprocess.Popen([
        "Xvfb",
        DISPLAY,
        "-screen",
        "0",
        f"{WIDTH}x{HEIGHT}x24",
        "-ac",
        "+extension",
        "RANDR"
    ])

    processos.append(xvfb)

    os.environ["DISPLAY"] = DISPLAY

    time.sleep(3)

    print("Xvfb iniciado em " + DISPLAY)


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():
    print("Iniciando PulseAudio...")

    subprocess.run(
        ["pulseaudio", "-k"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(1)

    subprocess.Popen([
        "pulseaudio",
        "--start",
        "--exit-idle-time=-1"
    ])

    time.sleep(3)

    # Cria saída virtual
    resultado = subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            "sink_name=webtv",
            "sink_properties=device.description=WebTV"
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    print("PulseAudio:", resultado.stdout.strip())

    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(2)

    return "webtv.monitor"


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():
    print("Iniciando servidor HTTP na porta 8080...")

    servidor = subprocess.Popen([
        "python3",
        "-m",
        "http.server",
        str(PORT),
        "--directory",
        str(STREAM_DIR)
    ])

    processos.append(servidor)

    time.sleep(3)

    print("Servidor HTTP ativo.")


# ============================================================
# SERVEO
# ============================================================

def iniciar_serveo():
    print("Iniciando túnel Serveo...")

    processo = subprocess.Popen(
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
            "80:localhost:8080",
            "serveo.net"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(processo)

    inicio = time.time()
    url = None

    while time.time() - inicio < 30:

        linha = processo.stdout.readline()

        if not linha:
            if processo.poll() is not None:
                break

            time.sleep(0.2)
            continue

        linha = linha.strip()

        if linha:
            print("[SERVEO] " + linha)

        if "https://" in linha:

            partes = linha.split()

            for parte in partes:

                if parte.startswith("https://"):

                    url = parte.strip()

                    if "serveo.net" in url:
                        break

        if url:
            break

    print("")
    print("============================================================")
    print("TRANSMISSAO")
    print("============================================================")

    if url:
        print("Link:")
        print(url)

        print("")
        print("Playlist HLS:")
        print(url.rstrip("/") + "/live.m3u8")
    else:
        print("O Serveo ainda nao mostrou o link.")
        print("Verifique o log acima.")

    print("============================================================")
    print("")

    return processo


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    from playwright.sync_api import sync_playwright

    print("Iniciando Chromium...")

    playwright = sync_playwright().start()

    browser = playwright.chromium.launch(
        headless=False,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",

            # AUTOPLAY
            "--autoplay-policy=no-user-gesture-required",

            # TELA CHEIA
            "--kiosk",
            "--start-fullscreen",
            "--start-maximized",
            "--window-size=1280,720",

            # ESTABILIDADE
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",

            # AUDIO
            "--use-fake-ui-for-media-stream",

            # Renderização
            "--disable-gpu"
        ]
    )

    page = browser.new_page(
        viewport={
            "width": WIDTH,
            "height": HEIGHT
        }
    )

    print("Abrindo painel:")
    print(URL_ALVO)

    try:
        page.goto(
            URL_ALVO,
            wait_until="domcontentloaded",
            timeout=120000
        )

        print("Painel carregado.")

    except Exception as erro:
        print("Erro ao abrir painel:")
        print(erro)

    time.sleep(8)

    # --------------------------------------------------------
    # FORCAR F11
    # --------------------------------------------------------

    print("Forcando tela cheia...")

    try:

        subprocess.run(
            [
                "xdotool",
                "search",
                "--onlyvisible",
                "--class",
                "chromium",
                "windowactivate",
                "--sync",
                "key",
                "F11"
            ],
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        time.sleep(3)

    except Exception as erro:
        print("Aviso fullscreen:")
        print(erro)

    # --------------------------------------------------------
    # CLICAR NO PLAYER
    # --------------------------------------------------------

    try:

        page.mouse.click(
            WIDTH // 2,
            HEIGHT // 2
        )

        print("Clique no centro do player executado.")

    except Exception as erro:

        print("Erro no clique:")
        print(erro)

    time.sleep(3)

    # --------------------------------------------------------
    # FORCAR PLAY DOS VIDEOS
    # --------------------------------------------------------

    try:

        resultado = page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(document.querySelectorAll("video"));

                const resultado = [];

                for (const video of videos) {

                    try {

                        video.autoplay = true;
                        video.playsInline = true;

                        if (video.paused) {
                            await video.play();
                        }

                        resultado.push({
                            paused: video.paused,
                            ended: video.ended,
                            readyState: video.readyState,
                            currentTime: video.currentTime,
                            width: video.videoWidth,
                            height: video.videoHeight
                        });

                    } catch (erro) {

                        resultado.push({
                            erro: String(erro),
                            paused: video.paused,
                            readyState: video.readyState
                        });
                    }
                }

                return {
                    quantidade: videos.length,
                    videos: resultado
                };
            }
            """
        )

        print("Diagnostico dos videos:")
        print(resultado)

    except Exception as erro:

        print("Erro ao executar play():")
        print(erro)

    # --------------------------------------------------------
    # SCREENSHOT
    # --------------------------------------------------------

    try:

        page.screenshot(
            path=str(STREAM_DIR / "browser_debug.png")
        )

        print("Screenshot salvo.")

    except Exception as erro:

        print("Erro screenshot:")
        print(erro)

    return playwright, browser, page


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg(audio_monitor):

    print("Iniciando FFmpeg...")

    try:
        PLAYLIST.unlink()
    except Exception:
        pass

    comando = [
        "ffmpeg",
        "-y",

        # VIDEO
        "-f",
        "x11grab",

        "-draw_mouse",
        "0",

        "-framerate",
        "30",

        "-video_size",
        f"{WIDTH}x{HEIGHT}",

        "-i",
        DISPLAY,

        # AUDIO
        "-f",
        "pulse",

        "-i",
        audio_monitor,

        # VIDEO CODEC
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
        "30",

        "-g",
        "60",

        "-keyint_min",
        "60",

        "-sc_threshold",
        "0",

        # AUDIO CODEC
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
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        str(STREAM_DIR / "segment_%05d.ts"),

        str(PLAYLIST)
    ]

    print("Comando FFmpeg:")
    print(" ".join(comando))

    ffmpeg = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(ffmpeg)

    def monitorar():

        try:

            for linha in ffmpeg.stdout:

                linha = linha.strip()

                if linha:
                    print("[FFMPEG] " + linha)

        except Exception:
            pass

    thread = threading.Thread(
        target=monitorar,
        daemon=True
    )

    thread.start()

    return ffmpeg


# ============================================================
# MONITOR DO PLAYER
# ============================================================

def monitorar_player(page):

    while True:

        time.sleep(10)

        try:

            if page.is_closed():
                print("Pagina fechada.")
                return

            dados = page.evaluate(
                """
                () => {

                    const videos =
                        Array.from(
                            document.querySelectorAll("video")
                        );

                    return videos.map(video => ({
                        paused: video.paused,
                        ended: video.ended,
                        readyState: video.readyState,
                        currentTime: video.currentTime,
                        width: video.videoWidth,
                        height: video.videoHeight
                    }));
                }
                """
            )

            print("Estado dos videos:")
            print(dados)

            # Se houver vídeos pausados,
            # tenta novamente reproduzir.
            for video in dados:

                if video["paused"]:

                    print(
                        "Video pausado. Tentando reproduzir novamente..."
                    )

                    try:

                        page.mouse.click(
                            WIDTH // 2,
                            HEIGHT // 2
                        )

                    except Exception:
                        pass

                    try:

                        page.evaluate(
                            """
                            () => {

                                document
                                    .querySelectorAll("video")
                                    .forEach(video => {

                                        video.autoplay = true;
                                        video.playsInline = true;

                                        video.play().catch(() => {});
                                    });
                            }
                            """
                        )

                    except Exception:
                        pass

                    break

        except Exception as erro:

            print("Erro no monitor:")
            print(erro)


# ============================================================
# PRINCIPAL
# ============================================================

def iniciar():

    print("============================================================")
    print("WEB TV - INICIANDO")
    print("============================================================")

    preparar_stream()

    # 1
    iniciar_xvfb()

    # 2
    audio_monitor = iniciar_audio()

    # 3
    iniciar_servidor()

    # 4
    iniciar_serveo()

    # 5
    playwright, browser, page = iniciar_navegador()

    # 6
    ffmpeg = iniciar_ffmpeg(audio_monitor)

    # 7
    print("")
    print("============================================================")
    print("TRANSMISSAO INICIADA")
    print("============================================================")
    print("Display:", DISPLAY)
    print("Resolucao:", str(WIDTH) + "x" + str(HEIGHT))
    print("Audio:", audio_monitor)
    print("Playlist:", str(PLAYLIST))
    print("============================================================")

    # Monitor
    try:

        monitorar_player(page)

    except KeyboardInterrupt:

        pass

    finally:

        limpar()

        try:
            browser.close()
        except Exception:
            pass

        try:
            playwright.stop()
        except Exception:
            pass


if __name__ == "__main__":
    iniciar()
