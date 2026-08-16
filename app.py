import os
import re
import time
import signal
import subprocess
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURAÇÃO
# ============================================================

URL_ALVO = os.environ.get(
    "URL_ALVO",
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
)

LARGURA = 1280
ALTURA = 720
DISPLAY = ":99"
PORTA = 8080

STREAM_DIR = Path("stream")
PLAYLIST = STREAM_DIR / "live.m3u8"

NGROK_AUTHTOKEN = os.environ.get("NGROK_AUTHTOKEN", "").strip()


# ============================================================
# PROCESSOS
# ============================================================

processos = []


def executar(cmd, **kwargs):
    print("[EXEC]", " ".join(cmd))
    p = subprocess.Popen(cmd, **kwargs)
    processos.append(p)
    return p


def parar_tudo():
    print("\nEncerrando transmissão...")

    for p in reversed(processos):
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass


signal.signal(signal.SIGTERM, lambda s, f: parar_tudo())
signal.signal(signal.SIGINT, lambda s, f: parar_tudo())


# ============================================================
# X SERVER
# ============================================================

def iniciar_xvfb():

    print("Iniciando Xvfb...")

    subprocess.run(
        [
            "pkill",
            "-9",
            "Xvfb"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    subprocess.run(
        [
            "Xvfb",
            DISPLAY,
            "-screen",
            "0",
            f"{LARGURA}x{ALTURA}x24",
            "-ac",
            "+extension",
            "RANDR"
        ],
        check=True
    )

    os.environ["DISPLAY"] = DISPLAY

    time.sleep(2)

    print(f"DISPLAY configurado: {DISPLAY}")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    print("Iniciando PulseAudio...")

    subprocess.run(
        [
            "pulseaudio",
            "-k"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(1)

    subprocess.Popen(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ]
    )

    time.sleep(3)

    # Cria uma saída virtual exclusiva para o navegador
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

    print("PulseAudio:", resultado.stdout.strip())

    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ]
    )

    os.environ["PULSE_SINK"] = "webtv"

    print("Saída de áudio: webtv")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():

    STREAM_DIR.mkdir(exist_ok=True)

    print("Iniciando servidor HTTP na porta 8080...")

    servidor = subprocess.Popen(
        [
            "python",
            "-m",
            "http.server",
            str(PORTA),
            "--directory",
            str(STREAM_DIR)
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(servidor)

    time.sleep(2)

    print("Servidor HTTP ativo.")


# ============================================================
# NGROK
# ============================================================

def iniciar_ngrok():

    if not NGROK_AUTHTOKEN:
        raise RuntimeError(
            "NGROK_AUTHTOKEN não foi configurado nos Secrets do GitHub."
        )

    print("Iniciando túnel ngrok...")

    from pyngrok import ngrok

    ngrok.kill()

    ngrok.set_auth_token(NGROK_AUTHTOKEN)

    # IMPORTANTE:
    # não usamos domínio fixo.
    # Cada execução recebe um endereço novo.
    tunnel = ngrok.connect(
        PORTA,
        proto="http"
    )

    url = tunnel.public_url

    print("")
    print("==========================================================")
    print("             TRANSMISSÃO INICIADA")
    print("==========================================================")
    print("")
    print("LINK DO STREAM:")
    print(f"{url}/live.m3u8")
    print("")
    print("ENDEREÇO DO SERVIDOR:")
    print(url)
    print("")
    print("==========================================================")
    print("COPIE O LINK /live.m3u8 ACIMA")
    print("==========================================================")
    print("")

    return url


# ============================================================
# FFmpeg
# ============================================================

def iniciar_ffmpeg():

    print("Iniciando FFmpeg...")

    # Remove arquivos antigos
    for arquivo in STREAM_DIR.glob("segment_*.ts"):
        try:
            arquivo.unlink()
        except Exception:
            pass

    try:
        PLAYLIST.unlink()
    except Exception:
        pass

    ffmpeg_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",

        # VIDEO
        "-f",
        "x11grab",

        "-draw_mouse",
        "0",

        "-framerate",
        "30",

        "-video_size",
        f"{LARGURA}x{ALTURA}",

        "-i",
        f"{DISPLAY}.0",

        # AUDIO
        "-f",
        "pulse",

        "-i",
        "webtv.monitor",

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
    print(" ".join(ffmpeg_cmd))

    ffmpeg = subprocess.Popen(
        ffmpeg_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(ffmpeg)

    return ffmpeg


# ============================================================
# CONTROLE DO PLAYER
# ============================================================

def preparar_player(page):

    print("Preparando player...")

    # Permite autoplay e tenta reproduzir todos os vídeos.
    page.evaluate(
        """
        () => {

            const videos = Array.from(
                document.querySelectorAll("video")
            );

            videos.forEach((video) => {

                video.muted = false;
                video.autoplay = true;
                video.playsInline = true;
                video.preload = "auto";

                try {
                    video.load();
                } catch(e) {}

            });

            return videos.length;
        }
        """
    )

    time.sleep(3)

    # Primeiro clique para criar user gesture.
    try:
        page.mouse.click(
            LARGURA // 2,
            ALTURA // 2
        )
    except Exception:
        pass

    time.sleep(1)

    # Tenta fullscreen + play.
    resultado = page.evaluate(
        """
        async () => {

            const videos =
                Array.from(document.querySelectorAll("video"));

            const resultados = [];

            for (const video of videos) {

                video.muted = false;
                video.autoplay = true;
                video.playsInline = true;
                video.preload = "auto";

                try {
                    await video.play();
                } catch(e) {
                    try {
                        video.muted = true;
                        await video.play();
                    } catch(e2) {}
                }

                resultados.push({
                    paused: video.paused,
                    ended: video.ended,
                    muted: video.muted,
                    readyState: video.readyState,
                    currentTime: video.currentTime,
                    width: video.videoWidth,
                    height: video.videoHeight
                });
            }

            try {
                if (!document.fullscreenElement) {
                    await document.documentElement.requestFullscreen();
                }
            } catch(e) {}

            return resultados;
        }
        """
    )

    print("[PLAYER]", resultado)


# ============================================================
# MONITOR DO PLAYER
# ============================================================

def monitorar_player(page):

    ultimo_tempo = {}

    while True:

        try:

            estado = page.evaluate(
                """
                () => {

                    const videos =
                        Array.from(document.querySelectorAll("video"));

                    return videos.map((v, i) => ({
                        index: i,
                        paused: v.paused,
                        ended: v.ended,
                        muted: v.muted,
                        readyState: v.readyState,
                        currentTime: v.currentTime,
                        width: v.videoWidth,
                        height: v.videoHeight,
                        error: v.error ? {
                            code: v.error.code,
                            message: v.error.message
                        } : null
                    }));
                }
                """
            )

            print("[PLAYER]", estado)

            # Tenta reproduzir novamente vídeos parados.
            page.evaluate(
                """
                () => {

                    document
                        .querySelectorAll("video")
                        .forEach(async (video) => {

                            video.autoplay = true;
                            video.preload = "auto";

                            if (video.paused || video.ended) {

                                try {
                                    await video.play();
                                } catch(e) {

                                    try {
                                        video.muted = true;
                                        await video.play();
                                    } catch(e2) {}
                                }
                            }
                        });
                }
                """
            )

        except Exception as e:
            print("[MONITOR] erro:", e)
            return

       
