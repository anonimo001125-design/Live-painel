import os
import re
import time
import signal
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÕES
# ============================================================

WIDTH = 1280
HEIGHT = 720
DISPLAY = ":99"
PORT = 8080

# COLOQUE AQUI A URL REAL DO SEU PAINEL
URL_ALVO = os.environ.get(
    "URL_ALVO",
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
)

STREAM_DIR = Path("stream")
PLAYLIST = STREAM_DIR / "live.m3u8"

processos = []


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):
    print("\n[INFO] Encerrando processos...")

    for p in processos:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass

    time.sleep(2)

    for p in processos:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass


signal.signal(signal.SIGINT, encerrar)
signal.signal(signal.SIGTERM, encerrar)


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
    except FileNotFoundError:
        pass


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    print("==========================================================")
    print("[AUDIO] Iniciando PulseAudio")
    print("==========================================================")

    subprocess.run(
        [
            "pulseaudio",
            "-D",
            "--exit-idle-time=-1"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(3)

    # Verifica se o sink já existe
    sinks = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        capture_output=True,
        text=True
    )

    if "webtv" not in sinks.stdout:

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
            print("[AUDIO] Erro:", resultado.stderr)

    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    print("[AUDIO] Monitor: webtv.monitor")


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    print("==========================================================")
    print("[XVFB] Iniciando tela virtual")
    print("==========================================================")

    subprocess.run(
        ["pkill", "-f", "Xvfb :99"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(1)

    xvfb = subprocess.Popen(
        [
            "Xvfb",
            DISPLAY,
            "-screen",
            "0",
            f"{WIDTH}x{HEIGHT}x24",
            "-ac",
            "+extension",
            "RANDR"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    processos.append(xvfb)

    os.environ["DISPLAY"] = DISPLAY

    time.sleep(3)

    print(f"[XVFB] DISPLAY={DISPLAY}")
    print("[XVFB] Tela virtual pronta")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():

    print("==========================================================")
    print("[HTTP] Iniciando servidor")
    print("==========================================================")

    servidor = subprocess.Popen(
        [
            "python3",
            "-m",
            "http.server",
            str(PORT),
            "--directory",
            str(STREAM_DIR)
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    processos.append(servidor)

    time.sleep(2)

    print(f"[HTTP] Servidor ativo na porta {PORT}")


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    print("==========================================================")
    print("[FFMPEG] Iniciando transmissão")
    print("==========================================================")

    comando = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-y",

        # ÁUDIO
        "-f", "pulse",
        "-thread_queue_size", "4096",
        "-i", "webtv.monitor",

        # VÍDEO
        "-f", "x11grab",
        "-draw_mouse", "0",
        "-framerate", "30",
        "-video_size", f"{WIDTH}x{HEIGHT}",
        "-thread_queue_size", "4096",
        "-i", f"{DISPLAY}.0",

        # VÍDEO
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-profile:v", "main",
        "-level", "3.1",

        "-r", "30",
        "-g", "60",
        "-keyint_min", "60",
        "-sc_threshold", "0",

        # ÁUDIO
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-ac", "2",

        # HLS
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        str(STREAM_DIR / "segment_%05d.ts"),

        str(PLAYLIST)
    ]

    print("[FFMPEG] Captura:")
    print(f"[FFMPEG] Vídeo: {WIDTH}x{HEIGHT}")
    print("[FFMPEG] Áudio: webtv.monitor")
    print("[FFMPEG] Saída: stream/live.m3u8")

    ffmpeg = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(ffmpeg)

    return ffmpeg


# ============================================================
# SERVEO
# ============================================================

def iniciar_serveo():

    print()
    print("==========================================================")
    print("[REDE] INICIANDO TÚNEL SERVEO")
    print("==========================================================")

    comando = [
        "ssh",

        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=5",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "LogLevel=INFO",

        "-R",
        f"80:localhost:{PORT}",

        "serveo.net"
    ]

    serveo = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(serveo)

    url_publica = None

    # Aceita vários formatos possíveis do Serveo
    padroes = [
        r"https://[a-zA-Z0-9\-]+\.serveo\.net",
        r"http://[a-zA-Z0-9\-]+\.serveo\.net"
    ]

    inicio = time.time()

    print("[REDE] Aguardando endereço público...")

    while time.time() - inicio < 60:

        if serveo.poll() is not None:
            print("[REDE] Serveo encerrou antes de fornecer o link.")
            break

        linha = serveo.stdout.readline()

        if not linha:
            time.sleep(0.2)
            continue

        linha = linha.strip()

        if linha:
            print("[SERVEO]", linha)

        # Procura URL em qualquer parte da mensagem
        for padrao in padroes:

            encontrado = re.search(
                padrao,
                linha
            )

            if encontrado:

                url_publica = encontrado.group(0)

                break

        if url_publica:
            break

    if url_publica:

        url_publica = url_publica.rstrip("/")

        link_hls = url_publica + "/live.m3u8"

        print()
        print()
        print("##########################################################")
        print("#                                                        #")
        print("#              TRANSMISSÃO ONLINE                       #")
        print("#                                                        #")
        print("##########################################################")
        print()
        print("LINK PÚBLICO:")
        print(url_publica)
        print()
        print("LINK DA TRANSMISSÃO HLS:")
        print(link_hls)
        print()
        print("##########################################################")
        print()

        return url_publica

    print()
    print("##########################################################")
    print("# ERRO: O SERVEO NÃO FORNECEU UM LINK PÚBLICO           #")
    print("##########################################################")
    print()

    return None


# ============================================================
# JAVASCRIPT PARA REPRODUÇÃO
# ============================================================

SCRIPT_PLAY = """
() => {

    const videos = Array.from(
        document.querySelectorAll("video")
    );

    const resultado = [];

    videos.forEach((video, index) => {

        try {

            video.autoplay = true;
            video.playsInline = true;

            video.setAttribute(
                "autoplay",
                ""
            );

            video.setAttribute(
                "playsinline",
                ""
            );

            const promessa = video.play();

            if (promessa) {

                promessa.catch(
                    erro => console.log(
                        "WEBTV play:",
                        erro
                    )
                );
            }

            resultado.push({
                index: index,
                paused: video.paused,
                ended: video.ended,
                muted: video.muted,
                readyState: video.readyState,
                currentTime: video.currentTime,
                width: video.videoWidth,
                height: video.videoHeight,
                src: video.currentSrc || video.src
            });

        } catch (erro) {

            resultado.push({
                index: index,
                erro: String(erro)
            });
        }
    });

    return resultado;
}
"""


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador(ffmpeg):

    print()
    print("==========================================================")
    print("[CHROMIUM] INICIANDO NAVEGADOR")
    print("==========================================================")

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=False,

            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",

                "--no-first-run",
                "--no-default-browser-check",

                "--disable-notifications",
                "--disable-infobars",

                # Permite autoplay
                "--autoplay-policy=no-user-gesture-required",

                # Tela cheia
                "--kiosk",
                "--start-fullscreen",
                "--start-maximized",

                f"--window-size={WIDTH},{HEIGHT}",

                # X11
                "--ozone-platform=x11"
            ]
        )

        context = browser.new_context(
            viewport={
                "width": WIDTH,
                "height": HEIGHT
            }
        )

        page = context.new_page()

        # ----------------------------------------------------
        # LOGS
        # ----------------------------------------------------

        page.on(
            "console",
            lambda msg: print(
                f"[BROWSER] {msg.type}: {msg.text}"
            )
        )

        page.on(
            "pageerror",
            lambda erro: print(
                f"[BROWSER ERROR] {erro}"
            )
        )

        page.on(
            "requestfailed",
            lambda request: print(
                f"[REQUEST ERROR] {request.url}"
            )
        )

        # ----------------------------------------------------
        # ABRIR PAINEL
        # ----------------------------------------------------

        print(
            f"[CHROMIUM] Abrindo: {URL_ALVO}"
        )

        try:

            page.goto(
                URL_ALVO,
                wait_until="domcontentloaded",
                timeout=120000
            )

        except Exception as erro:

            print(
                "[CHROMIUM] Aviso:",
                erro
            )

        time.sleep(8)

        print("[CHROMIUM] Painel carregado.")

        # ----------------------------------------------------
        # TELA CHEIA
        # ----------------------------------------------------

        try:

            page.keyboard.press("F11")

            print(
                "[CHROMIUM] F11 enviado."
            )

        except Exception:
            pass

        time.sleep(2)

        # ----------------------------------------------------
        # REPRODUÇÃO
        # ----------------------------------------------------

        for tentativa in range(1, 11):

            print(
                f"[CHROMIUM] Reprodução "
                f"{tentativa}/10"
            )

            try:

                videos = page.evaluate(
                    SCRIPT_PLAY
                )

                print(
                    "[CHROMIUM] Vídeos:",
                    videos
                )

            except Exception as erro:

                print(
                    "[CHROMIUM] Erro:",
                    erro
                )

            # Clique para ativar o player
            try:

                page.mouse.click(
                    WIDTH // 2,
                    HEIGHT // 2
                )

            except Exception:
                pass

            time.sleep(3)

        # ----------------------------------------------------
        # SCREENSHOT
        # ----------------------------------------------------

        try:

            page.screenshot(
                path=str(
                    STREAM_DIR /
                    "browser_debug.png"
                )
            )

            print(
                "[CHROMIUM] Screenshot salvo."
            )

        except Exception:
            pass

        print()
        print("==========================================================")
        print("TRANSMISSÃO INICIADA")
        print("==========================================================")

        # ----------------------------------------------------
        # MONITOR
        # ----------------------------------------------------

        while True:

            time.sleep(5)

            # FFmpeg morreu?
            if ffmpeg.poll() is not None:

                print(
                    "[ERRO] FFmpeg encerrou."
                )

                break

            try:

                videos = page.evaluate(
                    """
                    () => Array.from(
                        document.querySelectorAll("video")
                    ).map((v, i) => ({
                        index: i,
                        paused: v.paused,
                        ended: v.ended,
                        readyState: v.readyState,
                        currentTime: v.currentTime,
                        width: v.videoWidth,
                        height: v.videoHeight
                    }))
                    """
                )

                print(
                    "[MONITOR]",
                    videos
                )

                # Se todos estiverem pausados,
                # tenta iniciar novamente.
                if videos:

                    reproduzindo = any(
                        (
                            not v["paused"]
                            and v["readyState"] >= 2
                            and v["width"] > 0
                            and v["height"] > 0
                        )
                        for v in videos
                    )

                    if not reproduzindo:

                        print(
                            "[MONITOR] Vídeo parado. "
                            "Tentando reproduzir..."
                        )

                        page.evaluate(
                            SCRIPT_PLAY
                        )

                        page.mouse.click(
                            WIDTH // 2,
                            HEIGHT // 2
                        )

            except Exception as erro:

                print(
                    "[MONITOR] Erro:",
                    erro
                )

                # Tenta recarregar o painel
                try:

                    print(
                        "[MONITOR] Recarregando painel..."
                    )

                    page.reload(
                        wait_until="domcontentloaded",
                        timeout=60000
                    )

                    time.sleep(5)

                    page.evaluate(
                        SCRIPT_PLAY
                    )

                except Exception as reload_erro:

                    print(
                        "[MONITOR] Erro ao recarregar:",
                        reload_erro
                    )

        try:
            browser.close()
        except Exception:
            pass


# ============================================================
# PRINCIPAL
# ============================================================

def iniciar():

    print()
    print("==========================================================")
    print("                 WEB TV STREAM")
    print("==========================================================")
    print()

    preparar_stream()

    # 1. Áudio
    iniciar_audio()

    # 2. Tela virtual
    iniciar_xvfb()

    # 3. Servidor HTTP
    iniciar_servidor()

    # 4. FFmpeg
    ffmpeg = iniciar_ffmpeg()

    time.sleep(4)

    # 5. Túnel público
    url_publica = iniciar_serveo()

    if url_publica:

        print()
        print("==========================================================")
        print("             LINK FINAL DA TRANSMISSÃO")
        print("==========================================================")
        print(
            url_publica.rstrip("/") +
            "/live.m3u8"
        )
        print("==========================================================")
        print()

    # 6. Navegador
    iniciar_navegador(ffmpeg)


if __name__ == "__main__":
    iniciar()
