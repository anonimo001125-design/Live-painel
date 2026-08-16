import os
import re
import time
import signal
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÃO
# ============================================================

WIDTH = 1280
HEIGHT = 720
PORT = 8080
DISPLAY = ":99"

STREAM_DIR = Path("stream")
M3U8 = STREAM_DIR / "live.m3u8"

# ============================================================
# COLOQUE A URL REAL DO SEU PAINEL AQUI
# ============================================================

URL_ALVO = os.getenv(
    "SITE_URL",
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
)

processos = []


# ============================================================
# PULSE AUDIO
# ============================================================

def preparar_pulse():
    print("[1] Preparando PulseAudio...")

    subprocess.run(
        ["pulseaudio", "--kill"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    time.sleep(3)

    # Cria uma saída virtual para o áudio do Chromium
    resultado = subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            "sink_name=webtv",
            "sink_properties=device.description=WebTV"
        ],
        capture_output=True,
        text=True,
        check=False
    )

    if resultado.returncode != 0:
        print(
            "[PULSE] Aviso:",
            resultado.stderr.strip()
        )

    # Faz o Chromium mandar o áudio para esse dispositivo
    os.environ["PULSE_SINK"] = "webtv"

    print("[PULSE] Saída do navegador: webtv")
    print("[PULSE] FFmpeg capturará: webtv.monitor")


# ============================================================
# XVFB
# ============================================================

def preparar_xvfb():
    print("[2] Iniciando Xvfb...")

    subprocess.run(
        ["pkill", "-f", "Xvfb :99"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    xvfb = subprocess.Popen(
        [
            "Xvfb",
            DISPLAY,
            "-screen",
            "0",
            f"{WIDTH}x{HEIGHT}x24",
            "-ac"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    processos.append(xvfb)

    os.environ["DISPLAY"] = DISPLAY

    time.sleep(3)

    teste = subprocess.run(
        [
            "xdpyinfo",
            "-display",
            DISPLAY
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    if teste.returncode != 0:
        raise RuntimeError(
            "Xvfb não conseguiu iniciar o display :99."
        )

    print(
        f"[X11] Display {DISPLAY} ativo "
        f"em {WIDTH}x{HEIGHT}"
    )


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_http():
    print("[3] Iniciando servidor HTTP...")

    STREAM_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    servidor = subprocess.Popen(
        [
            "python3",
            "-m",
            "http.server",
            str(PORT),
            "--bind",
            "0.0.0.0",
            "--directory",
            str(STREAM_DIR)
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    processos.append(servidor)

    time.sleep(2)

    teste = subprocess.run(
        [
            "curl",
            "-fsS",
            f"http://127.0.0.1:{PORT}/"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    if teste.returncode != 0:
        raise RuntimeError(
            "Servidor HTTP não iniciou."
        )

    print(
        f"[HTTP] Servidor ativo na porta {PORT}"
    )


# ============================================================
# SERVEO
# ============================================================

def iniciar_tunel():
    print("[4] Iniciando túnel Serveo...")

    comando = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "ExitOnForwardFailure=yes",
        "-N",
        "-R",
        f"80:localhost:{PORT}",
        "serveo.net"
    ]

    tunnel = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(tunnel)

    padrao = re.compile(
        r"https?://[A-Za-z0-9.-]+\.serveo\.net"
    )

    inicio = time.time()
    linhas = []

    while time.time() - inicio < 30:

        if tunnel.poll() is not None:

            restante = ""

            if tunnel.stdout:
                restante = tunnel.stdout.read()

            raise RuntimeError(
                "Serveo encerrou o túnel.\n\n"
                + "\n".join(linhas)
                + "\n"
                + restante
            )

        linha = ""

        if tunnel.stdout:
            linha = tunnel.stdout.readline()

        if linha:
            linha = linha.strip()

            linhas.append(linha)

            print(
                "[SERVEO]",
                linha
            )

            resultado = padrao.search(linha)

            if resultado:

                url = resultado.group(0).rstrip("/")

                print("")
                print("=" * 60)
                print("             LINK DA TRANSMISSÃO")
                print("=" * 60)
                print("")
                print(
                    f"{url}/live.m3u8"
                )
                print("")
                print("=" * 60)
                print("")

                return url

        time.sleep(0.2)

    # Tentativa adicional
    texto = "\n".join(linhas)

    resultado = re.search(
        r"([A-Za-z0-9-]+\.serveo\.net)",
        texto
    )

    if resultado:

        url = (
            "https://"
            + resultado.group(1)
        )

        print("")
        print("=" * 60)
        print("LINK DA TRANSMISSÃO")
        print("=" * 60)
        print(
            f"{url}/live.m3u8"
        )
        print("=" * 60)
        print("")

        return url

    raise RuntimeError(
        "Serveo não informou o endereço público.\n\n"
        + texto
    )


# ============================================================
# FFMPEG
# ============================================================

def iniciar_ffmpeg():

    print("[5] Iniciando FFmpeg...")

    STREAM_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # Remove segmentos antigos
    for arquivo in STREAM_DIR.glob(
        "segment_*.ts"
    ):
        try:
            arquivo.unlink()
        except Exception:
            pass

    try:
        M3U8.unlink()
    except FileNotFoundError:
        pass

    comando = [
        "ffmpeg",

        "-hide_banner",
        "-loglevel",
        "warning",

        "-y",

        # ====================================================
        # ÁUDIO
        # ====================================================

        "-f",
        "pulse",

        "-thread_queue_size",
        "1024",

        "-i",
        "webtv.monitor",

        # ====================================================
        # VÍDEO
        # ====================================================

        "-f",
        "x11grab",

        "-draw_mouse",
        "0",

        "-framerate",
        "30",

        "-video_size",
        f"{WIDTH}x{HEIGHT}",

        "-thread_queue_size",
        "1024",

        "-i",
        f"{DISPLAY}.0",

        # ====================================================
        # MAPA
        # ====================================================

        "-map",
        "1:v:0",

        "-map",
        "0:a:0",

        # ====================================================
        # VÍDEO H264
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

        # ====================================================
        # ÁUDIO AAC
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
        "6",

        "-hls_flags",
        "delete_segments+append_list+independent_segments",

        "-hls_segment_filename",
        str(
            STREAM_DIR /
            "segment_%05d.ts"
        ),

        str(M3U8)
    ]

    print("")
    print("FFmpeg:")
    print(" ".join(comando))
    print("")

    ffmpeg = subprocess.Popen(
        comando
    )

    processos.append(ffmpeg)

    # Espera o HLS realmente começar
    inicio = time.time()

    while time.time() - inicio < 40:

        if ffmpeg.poll() is not None:

            raise RuntimeError(
                "FFmpeg encerrou. "
                f"Código: {ffmpeg.returncode}"
            )

        if M3U8.exists():

            try:
                texto = M3U8.read_text(
                    errors="ignore"
                )

                if "#EXTINF:" in texto:

                    print(
                        "[FFMPEG] HLS está funcionando."
                    )

                    return

            except Exception:
                pass

        time.sleep(1)

    raise RuntimeError(
        "FFmpeg iniciou, mas "
        "live.m3u8 não recebeu segmentos."
    )


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    print("[6] Abrindo Chromium...")
    print("[BROWSER] Modo quiosque:")
    print("[BROWSER] 1280x720")
    print("[BROWSER] Tela cheia sem abas")

    with sync_playwright() as p:

        browser = p.chromium.launch(

            headless=False,

            args=[
                "--no-sandbox",

                "--disable-dev-shm-usage",

                "--disable-infobars",

                "--no-first-run",

                "--no-default-browser-check",

                "--autoplay-policy=no-user-gesture-required",

                # Tela cheia verdadeira
                "--kiosk",

                "--start-fullscreen",

                "--start-maximized",

                f"--window-size={WIDTH},{HEIGHT}",

                "--force-device-scale-factor=1"
            ]
        )

        # viewport=None é importante:
        # usa o tamanho real da janela Xvfb
        page = browser.new_page(
            viewport=None
        )

        page.on(
            "console",
            lambda msg:
            print(
                "[CHROMIUM]",
                msg.type,
                ":",
                msg.text
            )
        )

        page.on(
            "pageerror",
            lambda erro:
            print(
                "[CHROMIUM PAGE ERROR]",
                erro
            )
        )

        print("")
        print(
            "[BROWSER] Abrindo painel:"
        )
        print(URL_ALVO)
        print("")

        try:

            page.goto(
                URL_ALVO,
                wait_until="domcontentloaded",
                timeout=120000
            )

        except Exception as erro:

            print(
                "[BROWSER] Aviso:",
                erro
            )

        print(
            "[BROWSER] Aguardando painel..."
        )

        time.sleep(10)

        # ====================================================
        # FUNÇÃO DE REPRODUÇÃO
        # ====================================================

        def tentar_reproduzir():

            try:

                resultado = page.evaluate(
                    """
                    async () => {

                        const videos =
                            Array.from(
                                document.querySelectorAll(
                                    "video"
                                )
                            );

                        const dados = [];

                        for (const video of videos) {

                            try {

                                video.setAttribute(
                                    "playsinline",
                                    ""
                                );

                                video.setAttribute(
                                    "autoplay",
                                    ""
                                );

                                video.volume = 1.0;

                                /*
                                 * Não forçamos muted=true.
                                 * O Chromium está configurado
                                 * para permitir autoplay.
                                 */

                                if (
                                    video.readyState >= 1
                                ) {

                                    try {

                                        await video.play();

                                    } catch (e) {

                                        console.log(
                                            "play() bloqueado:",
                                            String(e)
                                        );

                                    }

                                }

                                dados.push({

                                    paused:
                                        video.paused,

                                    ended:
                                        video.ended,

                                    muted:
                                        video.muted,

                                    readyState:
                                        video.readyState,

                                    currentTime:
                                        video.currentTime,

                                    width:
                                        video.videoWidth,

                                    height:
                                        video.videoHeight
                                });

                            } catch (e) {

                                dados.push({
                                    erro: String(e)
                                });

                            }
                        }

                        return {

                            quantidade:
                                videos.length,

                            videos:
                                dados
                        };
                    }
                    """
                )

                print(
                    "[PLAYER]",
                    resultado
                )

                # Gesto físico no centro da tela.
                # Ajuda players que exigem interação.
                page.mouse.click(
                    WIDTH // 2,
                    HEIGHT // 2
                )

            except Exception as erro:

                print(
                    "[PLAYER] Erro:",
                    erro
                )

        # Primeira tentativa
        tentar_reproduzir()

        print("")
        print(
            "[7] Monitor do player ativado."
        )
        print("")

        ultimo_url = ""

        while True:

            time.sleep(5)

            if page.is_closed():

                print(
                    "[BROWSER] Página fechada."
                )

                break

            try:

                url_atual = page.url

                estado = page.evaluate(
                    """
                    () => {

                        return Array.from(
                            document.querySelectorAll(
                                "video"
                            )
                        ).map(video => ({

                            paused:
                                video.paused,

                            ended:
                                video.ended,

                            readyState:
                                video.readyState,

                            currentTime:
                                video.currentTime,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight
                        }));

                    }
                    """
                )

                print(
                    "[PLAYER CHECK]",
                    estado
                )

                mudou_pagina = (
                    url_atual != ultimo_url
                )

                algum_parado = any(
                    item.get("paused")
                    and not item.get("ended")
                    for item in estado
                    if isinstance(item, dict)
                )

                algum_sem_video = any(
                    item.get("readyState", 0) == 0
                    for item in estado
                    if isinstance(item, dict)
                )

                if (
                    mudou_pagina
                    or algum_parado
                    or algum_sem_video
                ):

                    print(
                        "[PLAYER] Tentando "
                        "reproduzir novamente..."
                    )

                    tentar_reproduzir()

                ultimo_url = url_atual

            except Exception as erro:

                print(
                    "[MONITOR] Aviso:",
                    erro
                )


# ============================================================
# LIMPEZA
# ============================================================

def limpar(*args):

    print("")
    print(
        "[FINAL] Encerrando processos..."
    )

    for processo in reversed(processos):

        try:

            if processo.poll() is None:

                processo.terminate()

        except Exception:
            pass

    time.sleep(2)

    for processo in reversed(processos):

        try:

            if processo.poll() is None:

                processo.kill()

        except Exception:
            pass


# ============================================================
# INICIAR
# ============================================================

def iniciar():

    signal.signal(
        signal.SIGTERM,
        limpar
    )

    signal.signal(
        signal.SIGINT,
        limpar
    )

    print("")
    print("=" * 60)
    print("                 INICIANDO WEBTV")
    print("=" * 60)
    print("")

    if "SEU-PAINEL-AQUI" in URL_ALVO:

        raise RuntimeError(
            "Você precisa colocar a URL real "
            "do seu painel em URL_ALVO."
        )

    STREAM_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    preparar_pulse()

    preparar_xvfb()

    iniciar_http()

    url_publica = iniciar_tunel()

    iniciar_ffmpeg()

    # Mostra novamente o link depois
    # que o HLS realmente começou.
    print("")
    print("=" * 70)
    print("                 TRANSMISSÃO ONLINE")
    print("=" * 70)
    print("")
    print(
        "LINK HLS:"
    )
    print(
        f"{url_publica}/live.m3u8"
    )
    print("")
    print(
        "O link acima é o que você deve colocar "
        "no seu player."
    )
    print("")
    print("=" * 70)
    print("")

    iniciar_navegador()


if __name__ == "__main__":
    iniciar()
