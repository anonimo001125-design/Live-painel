import os
import sys
import time
import signal
import asyncio
import threading
import subprocess

from pyppeteer import launch


# ============================================================
# CONFIGURAÇÕES
# ============================================================

STREAM_DIR = os.path.abspath("stream")

DISPLAY = ":99"

WIDTH = 1280
HEIGHT = 720

FPS = 30

HTTP_PORT = 8080

URL_ALVO = (
    "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012"
    ".us-east5.run.app/watch"
)

processos = []

browser_global = None
ffmpeg_global = None


# ============================================================
# LOG
# ============================================================

def log(*args):
    print(*args, flush=True)


# ============================================================
# ENCERRAMENTO
# ============================================================

def encerrar(*args):

    log("")
    log("==========================================================")
    log("ENCERRANDO TRANSMISSAO")
    log("==========================================================")

    global browser_global
    global ffmpeg_global

    try:
        if ffmpeg_global:
            if ffmpeg_global.poll() is None:
                ffmpeg_global.terminate()
    except Exception:
        pass

    try:
        if browser_global:
            # Não esperamos o navegador fechar aqui.
            pass
    except Exception:
        pass

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

    log("Transmissao encerrada.")

    sys.exit(0)


signal.signal(signal.SIGTERM, encerrar)
signal.signal(signal.SIGINT, encerrar)


# ============================================================
# LIMPAR STREAM
# ============================================================

def limpar_stream():

    os.makedirs(STREAM_DIR, exist_ok=True)

    log("[1] Limpando arquivos antigos...")

    for nome in os.listdir(STREAM_DIR):

        caminho = os.path.join(STREAM_DIR, nome)

        try:

            if os.path.isfile(caminho):
                os.remove(caminho)

        except Exception as erro:

            log(
                "[AVISO] Nao foi possivel remover",
                caminho,
                erro
            )


# ============================================================
# XVFB
# ============================================================

def iniciar_xvfb():

    log("")
    log("[2] Iniciando Xvfb...")

    os.environ["DISPLAY"] = DISPLAY

    xvfb = subprocess.Popen(
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
        stderr=subprocess.STDOUT
    )

    processos.append(xvfb)

    time.sleep(3)

    if xvfb.poll() is not None:
        raise RuntimeError(
            "Xvfb nao conseguiu iniciar."
        )

    log("Xvfb funcionando.")
    log(f"DISPLAY = {DISPLAY}")
    log(f"TELA = {WIDTH}x{HEIGHT}")


# ============================================================
# PULSEAUDIO
# ============================================================

def iniciar_audio():

    log("")
    log("[3] Iniciando PulseAudio...")

    runtime = "/tmp/pulse"

    os.makedirs(runtime, exist_ok=True)

    os.environ["PULSE_RUNTIME_PATH"] = runtime
    os.environ["DISPLAY"] = DISPLAY

    ambiente = os.environ.copy()

    # Tenta iniciar o PulseAudio.
    subprocess.run(
        [
            "pulseaudio",
            "--kill"
        ],
        env=ambiente,
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
        env=ambiente,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    time.sleep(3)

    # Verifica.
    teste = subprocess.run(
        [
            "pactl",
            "info"
        ],
        env=ambiente,
        capture_output=True,
        text=True,
        check=False
    )

    if teste.returncode != 0:

        log(teste.stderr)

        raise RuntimeError(
            "PulseAudio nao iniciou."
        )

    # Cria nosso dispositivo virtual.
    criar = subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            "sink_name=webtv",
            "sink_properties=device.description=WebTV"
        ],
        env=ambiente,
        capture_output=True,
        text=True,
        check=False
    )

    if criar.returncode != 0:

        log(
            "Sink WebTV ja pode existir."
        )

    subprocess.run(
        [
            "pactl",
            "set-default-sink",
            "webtv"
        ],
        env=ambiente,
        check=False
    )

    os.environ["PULSE_SINK"] = "webtv"

    fontes = subprocess.run(
        [
            "pactl",
            "list",
            "short",
            "sources"
        ],
        env=ambiente,
        capture_output=True,
        text=True,
        check=False
    )

    log("")
    log("Fontes de audio:")
    log(fontes.stdout)

    if "webtv.monitor" not in fontes.stdout:

        raise RuntimeError(
            "webtv.monitor nao foi encontrado."
        )

    log("PulseAudio WebTV pronto.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():

    log("")
    log("[4] Iniciando servidor HTTP...")

    servidor = subprocess.Popen(
        [
            "python3",
            "-m",
            "http.server",
            str(HTTP_PORT),
            "--directory",
            STREAM_DIR
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    processos.append(servidor)

    time.sleep(2)

    if servidor.poll() is not None:

        raise RuntimeError(
            "Servidor HTTP encerrou."
        )

    log(
        f"Servidor funcionando em http://127.0.0.1:{HTTP_PORT}"
    )


# ============================================================
# TUNEL CLOUDFLARE
# ============================================================

def iniciar_tunel():

    log("")
    log("[5] Iniciando tunel publico...")

    tunnel = subprocess.Popen(
        [
            "cloudflared",
            "tunnel",
            "--no-autoupdate",
            "--url",
            f"http://127.0.0.1:{HTTP_PORT}"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(tunnel)

    url_publica = None

    inicio = time.time()

    while time.time() - inicio < 60:

        linha = tunnel.stdout.readline()

        if not linha:
            continue

        linha = linha.strip()

        if linha:
            log("[TUNEL]", linha)

        if "trycloudflare.com" in linha:

            partes = linha.split()

            for parte in partes:

                if parte.startswith("https://") and \
                   "trycloudflare.com" in parte:

                    url_publica = parte.strip()

                    break

        if url_publica:
            break

    if not url_publica:

        raise RuntimeError(
            "Nao foi possivel obter o link publico."
        )

    log("")
    log("==========================================================")
    log("TRANSMISSAO ONLINE")
    log("==========================================================")
    log("")
    log("LINK DA TRANSMISSAO:")
    log(url_publica)
    log("")
    log("LINK HLS:")
    log(url_publica.rstrip("/") + "/live.m3u8")
    log("")
    log("==========================================================")
    log("")

    return url_publica


# ============================================================
# DIAGNÓSTICO
# ============================================================

async def diagnosticar_videos(page):

    try:

        resultado = await page.evaluate(
            """
            () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                return videos.map(
                    (video, index) => {

                        return {

                            index: index,

                            src:
                                video.src || "",

                            currentSrc:
                                video.currentSrc || "",

                            paused:
                                video.paused,

                            ended:
                                video.ended,

                            muted:
                                video.muted,

                            autoplay:
                                video.autoplay,

                            readyState:
                                video.readyState,

                            networkState:
                                video.networkState,

                            currentTime:
                                video.currentTime,

                            duration:
                                video.duration,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight,

                            error:
                                video.error
                                ? {
                                    code:
                                        video.error.code,

                                    message:
                                        video.error.message
                                }
                                : null
                        };
                    }
                );
            }
            """
        )

        log("")
        log("==========================================================")
        log("DIAGNOSTICO DOS VIDEOS")
        log("==========================================================")

        if not resultado:

            log("Nenhum elemento <video> encontrado.")

        else:

            for video in resultado:

                log(video)

        log("==========================================================")
        log("")

        return resultado

    except Exception as erro:

        log(
            "[DIAGNOSTICO] Erro:",
            erro
        )

        return []


# ============================================================
# INICIAR PLAYER
# ============================================================

async def iniciar_videos(page):

    log("")
    log("[PLAYER] Inicializando player...")

    try:

        resultado = await page.evaluate(
            """
            async () => {

                const videos =
                    Array.from(
                        document.querySelectorAll("video")
                    );

                const resultados = [];

                for (
                    let i = 0;
                    i < videos.length;
                    i++
                ) {

                    const video = videos[i];

                    try {

                        video.autoplay = true;
                        video.playsInline = true;

                        let resultadoPlay = "";

                        try {

                            const promessa =
                                video.play();

                            if (promessa) {
                                await promessa;
                            }

                            resultadoPlay = "OK";

                        } catch (erro) {

                            resultadoPlay =
                                String(erro);
                        }

                        resultados.push({

                            index: i,

                            play:
                                resultadoPlay,

                            src:
                                video.src || "",

                            currentSrc:
                                video.currentSrc || "",

                            readyState:
                                video.readyState,

                            networkState:
                                video.networkState,

                            paused:
                                video.paused,

                            width:
                                video.videoWidth,

                            height:
                                video.videoHeight
                        });

                    } catch (erro) {

                        resultados.push({

                            index: i,

                            erro:
                                String(erro)
                        });
                    }
                }

                return resultados;
            }
            """
        )

        log("[PLAYER] Resultado:")
        log(resultado)

        return resultado

    except Exception as erro:

        log(
            "[PLAYER] Erro:",
            erro
        )

        return []


# ============================================================
# MONITORAR PLAYER
# ============================================================

async def monitorar_player(page):

    while True:

        try:

            await asyncio.sleep(10)

            resultado = await diagnosticar_videos(page)

            # Procuramos um vídeo realmente carregado.
            carregado = False

            for video in resultado:

                if (
                    video.get("readyState", 0) >= 2
                    and
                    video.get("width", 0) > 0
                    and
                    video.get("height", 0) > 0
                ):

                    carregado = True

                    # Só tentamos play se estiver pausado.
                    if video.get("paused"):

                        await page.evaluate(
                            """
                            () => {

                                const videos =
                                    Array.from(
                                        document.querySelectorAll(
                                            "video"
                                        )
                                    );

                                for (
                                    const video of videos
                                ) {

                                    if (
                                        video.readyState >= 2 &&
                                        video.videoWidth > 0 &&
                                        video.videoHeight > 0 &&
                                        video.paused
                                    ) {

                                        video.play()
                                            .catch(() => {});
                                    }
                                }
                            }
                            """
                        )

                    break

            if not carregado:

                log(
                    "[PLAYER] Nenhum video recebeu imagem ainda."
                )

        except Exception as erro:

            log(
                "[PLAYER] Monitor:",
                erro
            )


# ============================================================
# NAVEGADOR
# ============================================================

async def iniciar_navegador():

    global browser_global

    log("")
    log("[6] Iniciando Chromium...")

    ambiente = os.environ.copy()

    ambiente["DISPLAY"] = DISPLAY
    ambiente["PULSE_SINK"] = "webtv"

    browser = await launch(

        headless=False,

        executablePath="/usr/bin/chromium",

        env=ambiente,

        handleSIGINT=False,

        handleSIGTERM=False,

        handleSIGHUP=False,

        # ====================================================
        # AQUI ESTÁ A PARTE DA TELA CHEIA
        # ====================================================

        args=[

            "--no-sandbox",

            "--disable-setuid-sandbox",

            "--disable-dev-shm-usage",

            "--autoplay-policy=no-user-gesture-required",

            "--no-first-run",

            "--no-default-browser-check",

            "--disable-popup-blocking",

            "--disable-notifications",

            "--window-size=1280,720",

            "--window-position=0,0",

            "--start-maximized",

            "--kiosk",

            "--start-fullscreen",

            "--force-device-scale-factor=1",

            # NÃO DESATIVAMOS GPU/VIDEO DECODE.
            #
            # Isso é proposital.
            #
            # Os códigos anteriores tinham:
            # --disable-gpu
            # --disable-accelerated-video-decode
            #
            # e isso pode prejudicar o player.
        ]
    )

    browser_global = browser

    log("Chromium iniciado.")

    page = await browser.newPage()

    await page.setViewport(
        {
            "width": WIDTH,
            "height": HEIGHT,
            "deviceScaleFactor": 1
        }
    )

    # ========================================================
    # LOGS
    # ========================================================

    page.on(
        "console",
        lambda mensagem:
        log(
            "[CONSOLE]",
            mensagem.text
        )
    )

    page.on(
        "pageerror",
        lambda erro:
        log(
            "[PAGE ERROR]",
            erro
        )
    )

    page.on(
        "requestfailed",
        lambda request:
        log(
            "[REQUEST FAILED]",
            request.url,
            request.failure
        )
    )

    # ========================================================
    # ABRIR SITE
    # ========================================================

    log("")
    log("==========================================================")
    log("ABRINDO PAINEL")
    log("==========================================================")
    log(URL_ALVO)
    log("")

    try:

        await page.goto(
            URL_ALVO,
            {
                "waitUntil": "domcontentloaded",
                "timeout": 60000
            }
        )

    except Exception as erro:

        log(
            "[AVISO] goto:",
            erro
        )

    # Importante:
    # Não usamos networkidle porque páginas com player
    # podem manter conexões abertas continuamente.

    await asyncio.sleep(8)

    log("Painel carregado.")

    try:

        titulo = await page.title()

        log(
            "[CHROMIUM] Titulo:",
            titulo
        )

    except Exception:
        pass

    # ========================================================
    # GARANTIR VISUAL DE TELA CHEIA
    # ========================================================

    try:

        await page.evaluate(
            """
            () => {

                document.documentElement.style.margin = "0";
                document.documentElement.style.padding = "0";

                document.body.style.margin = "0";
                document.body.style.padding = "0";

                document.body.style.width = "100vw";
                document.body.style.height = "100vh";

                document.body.style.overflow = "hidden";
            }
            """
        )

    except Exception:
        pass

    # ========================================================
    # PRIMEIRO DIAGNÓSTICO
    # ========================================================

    await diagnosticar_videos(page)

    # ========================================================
    # PRIMEIRA TENTATIVA DE PLAY
    # ========================================================

    await iniciar_videos(page)

    # ========================================================
    # CLIQUE ÚNICO
    #
    # Diferente do código antigo, NÃO vamos clicar
    # repetidamente, pois isso pode pausar o player.
    # ========================================================

    try:

        await page.mouse.click(
            WIDTH // 2,
            HEIGHT // 2
        )

        log(
            "[PLAYER] Clique inicial executado."
        )

        await asyncio.sleep(1)

        await iniciar_videos(page)

    except Exception as erro:

        log(
            "[PLAYER] Clique:",
            erro
        )

    # ========================================================
    # TENTAR FULLSCREEN DO DOCUMENTO
    # ========================================================

    try:

        await page.evaluate(
            """
            async () => {

                try {

                    if (
                        document.documentElement.requestFullscreen &&
                        !document.fullscreenElement
                    ) {

                        await document.documentElement
                            .requestFullscreen()
                            .catch(() => {});
                    }

                } catch (e) {}
            }
            """
        )

    except Exception:
        pass

    # ========================================================
    # MONITOR
    # ========================================================

    asyncio.create_task(
        monitorar_player(page)
    )

    return browser, page


# ============================================================
# ESPERAR HLS
# ============================================================

async def esperar_hls(ffmpeg):

    log("")
    log("[7] Aguardando FFmpeg criar HLS...")

    playlist = os.path.join(
        STREAM_DIR,
        "live.m3u8"
    )

    for tentativa in range(60):

        await asyncio.sleep(1)

        if ffmpeg.poll() is not None:

            raise RuntimeError(
                "FFmpeg encerrou antes de criar o HLS."
            )

        if os.path.exists(playlist):

            tamanho = os.path.getsize(
                playlist
            )

            if tamanho > 20:

                log("")
                log("HLS criado com sucesso.")
                log("")

                return

        if tentativa % 5 == 0:

            log(
                f"Aguardando HLS... {tentativa}/60"
            )

    raise RuntimeError(
        "FFmpeg nao criou live.m3u8."
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    global ffmpeg_global

    log("")
    log("==========================================================")
    log("WEBTV STREAM")
    log("==========================================================")

    limpar_stream()

    iniciar_xvfb()

    iniciar_audio()

    iniciar_servidor()

    # Primeiro liga o FFmpeg.
    ffmpeg_global = subprocess.Popen(
        [
            "ffmpeg",
            "-y",

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

            "-f",
            "pulse",

            "-i",
            "webtv.monitor",

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

            "-r",
            str(FPS),

            "-g",
            str(FPS * 2),

            "-keyint_min",
            str(FPS * 2),

            "-sc_threshold",
            "0",

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-ar",
            "44100",

            "-ac",
            "2",

            "-f",
            "hls",

            "-hls_time",
            "2",

            "-hls_list_size",
            "6",

            "-hls_flags",
            "delete_segments+append_list+independent_segments",

            "-hls_segment_filename",
            os.path.join(
                STREAM_DIR,
                "segment_%05d.ts"
            ),

            os.path.join(
                STREAM_DIR,
                "live.m3u8"
            )
        ],
        env=os.environ.copy()
    )

    log("[8] FFmpeg iniciado.")

    await asyncio.sleep(3)

    if ffmpeg_global.poll() is not None:

        raise RuntimeError(
            "FFmpeg encerrou."
        )

    # Abre navegador depois do FFmpeg.
    browser, page = await iniciar_navegador()

    await esperar_hls(ffmpeg_global)

    # Túnel só depois de HLS estar funcionando.
    url_publica = iniciar_tunel()

    log("")
    log("==========================================================")
    log("TRANSMISSAO PRONTA")
    log("==========================================================")
    log("")
    log("LINK DA TRANSMISSAO:")
    log(url_publica)
    log("")
    log("LINK HLS:")
    log(url_publica.rstrip("/") + "/live.m3u8")
    log("")
    log("==========================================================")
    log("")

    # Mantém tudo vivo.
    while True:

        await asyncio.sleep(10)

        if ffmpeg_global.poll() is not None:

            raise RuntimeError(
                "FFmpeg encerrou durante a transmissao."
            )


# ============================================================
# EXECUTAR
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        encerrar()

    except Exception as erro:

        log("")
        log("==========================================================")
        log("ERRO FATAL")
        log("==========================================================")
        log(erro)
        log("==========================================================")

        encerrar()
