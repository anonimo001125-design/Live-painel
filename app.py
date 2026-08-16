import os
import re
import time
import signal
import subprocess

# ============================================================
# CONFIGURAÇÕES
# ============================================================

LARGURA = 1280
ALTURA = 720
DISPLAY = ":99"
PORTA = 8080

# COLOQUE A URL DO SEU PAINEL AQUI
URL_PAINEL = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"

# ============================================================
# VARIÁVEIS GLOBAIS
# ============================================================

processos = []


# ============================================================
# FINALIZAÇÃO
# ============================================================

def finalizar(signum=None, frame=None):
    print("")
    print("Encerrando transmissão...")

    for processo in processos:
        try:
            if processo.poll() is None:
                processo.terminate()
        except Exception:
            pass

    time.sleep(2)


signal.signal(signal.SIGTERM, finalizar)
signal.signal(signal.SIGINT, finalizar)


# ============================================================
# EXECUTAR COMANDO
# ============================================================

def executar(comando):
    print("")
    print("COMANDO:")
    print(" ".join(comando))
    print("")

    processo = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(processo)
    return processo


# ============================================================
# PREPARAR PASTA
# ============================================================

def preparar_stream():
    os.makedirs("stream", exist_ok=True)

    # Remove arquivos HLS antigos
    for nome in os.listdir("stream"):
        caminho = os.path.join("stream", nome)

        if os.path.isfile(caminho):
            try:
                os.remove(caminho)
            except Exception:
                pass

    print("Pasta stream preparada.")


# ============================================================
# PULSEAUDIO
# ============================================================

def preparar_audio():
    print("")
    print("Preparando PulseAudio...")

    # Inicia PulseAudio do usuário
    subprocess.run(
        [
            "pulseaudio",
            "--start",
            "--exit-idle-time=-1"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(2)

    # Verifica se já existe o sink
    resultado = subprocess.run(
        ["pactl", "list", "short", "sinks"],
        capture_output=True,
        text=True
    )

    if "webtv" not in resultado.stdout:
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

    time.sleep(2)

    # Faz o WebTV ser a saída padrão
    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        check=False
    )

    # Descobre o monitor do sink
    resultado = subprocess.run(
        ["pactl", "list", "short", "sources"],
        capture_output=True,
        text=True
    )

    print("Fontes de áudio encontradas:")
    print(resultado.stdout)

    return "webtv.monitor"


# ============================================================
# Xvfb
# ============================================================

def preparar_tela():
    print("")
    print("Preparando Xvfb...")

    # Mata Xvfb antigo caso exista
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
            f"{LARGURA}x{ALTURA}x24",
            "-ac"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    processos.append(xvfb)

    os.environ["DISPLAY"] = DISPLAY

    time.sleep(3)

    print(f"Xvfb ativo em {DISPLAY}.")


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():
    print("")
    print(f"Iniciando servidor HTTP na porta {PORTA}...")

    servidor = subprocess.Popen(
        [
            "python3",
            "-m",
            "http.server",
            str(PORTA),
            "--directory",
            "stream"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    processos.append(servidor)

    time.sleep(3)

    print(f"Servidor HTTP ativo em http://127.0.0.1:{PORTA}")


# ============================================================
# SERVEO
# ============================================================

def iniciar_tunel():
    print("")
    print("Iniciando túnel público...")
    print("Aguardando endereço do Serveo...")

    processo = subprocess.Popen(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-R",
            f"80:localhost:{PORTA}",
            "serveo.net"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(processo)

    url_publica = None
    inicio = time.time()

    while time.time() - inicio < 30:
        linha = processo.stdout.readline()

        if not linha:
            time.sleep(0.2)
            continue

        linha = linha.strip()

        if linha:
            print("[SERVEO]", linha)

        # Procura https://xxxx.serveo.net
        encontrados = re.findall(
            r"https://[a-zA-Z0-9.-]+\.serveo\.net",
            linha
        )

        if encontrados:
            url_publica = encontrados[0]
            break

    print("")
    print("==========================================================")
    print("              TRANSMISSÃO WEBTV")
    print("==========================================================")

    if url_publica:
        print(f"LINK DO SERVIDOR: {url_publica}")
        print(f"LINK HLS:         {url_publica}/live.m3u8")
    else:
        print("O Serveo não retornou o link automaticamente.")
        print("Verifique as linhas [SERVEO] acima.")

    print("==========================================================")
    print("")

    return url_publica


# ============================================================
# FFmpeg
# ============================================================

def iniciar_ffmpeg(audio_monitor):
    print("")
    print("Iniciando FFmpeg...")

    comando = [
        "ffmpeg",
        "-y",

        # VÍDEO
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

        # ÁUDIO
        "-f",
        "pulse",
        "-i",
        audio_monitor,

        # VÍDEO
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

        # ÁUDIO
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
        "stream/segment_%05d.ts",

        "stream/live.m3u8"
    ]

    print("Comando FFmpeg:")
    print(" ".join(comando))
    print("")

    processo = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(processo)

    return processo


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():
    print("")
    print("Iniciando Chromium...")
    print(f"Abrindo: {URL_PAINEL}")

    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()

    browser = playwright.chromium.launch(
        headless=False,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",

            # AUTOPLAY
            "--autoplay-policy=no-user-gesture-required",
            "--allow-running-insecure-content",

            # TELA
            "--kiosk",
            "--start-fullscreen",
            "--start-maximized",
            "--window-size=1280,720",

            # EVITA ALGUNS PROBLEMAS DE PRIMEIRA EXECUÇÃO
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",

            # GPU
            "--disable-gpu",
            "--disable-software-rasterizer"
        ]
    )

    context = browser.new_context(
        viewport={
            "width": LARGURA,
            "height": ALTURA
        },
        screen={
            "width": LARGURA,
            "height": ALTURA
        }
    )

    page = context.new_page()

    # ========================================================
    # MONITORAMENTO DE ERROS DO NAVEGADOR
    # ========================================================

    page.on(
        "console",
        lambda mensagem: print(
            f"[CHROMIUM] console: {mensagem.text}"
        )
    )

    page.on(
        "pageerror",
        lambda erro: print(
            f"[CHROMIUM] pageerror: {erro}"
        )
    )

    # ========================================================
    # ABRIR PAINEL
    # ========================================================

    try:
        page.goto(
            URL_PAINEL,
            wait_until="domcontentloaded",
            timeout=120000
        )

        print("Painel carregado.")

    except Exception as erro:
        print(f"Erro ao abrir painel: {erro}")

    time.sleep(8)

    # ========================================================
    # TELA CHEIA
    # ========================================================

    try:
        page.keyboard.press("F11")
    except Exception:
        pass

    time.sleep(2)

    # ========================================================
    # ENCONTRAR VÍDEOS
    # ========================================================

    try:
        quantidade = page.locator("video").count()

        print("")
        print(f"[CHROMIUM] Vídeos encontrados: {quantidade}")

    except Exception as erro:
        print(f"Erro verificando vídeos: {erro}")

    # ========================================================
    # FORÇAR VÍDEO
    # ========================================================

    try:
        resultado = page.evaluate(
            """
            () => {
                const videos = Array.from(document.querySelectorAll("video"));

                let tentativas = 0;

                for (const video of videos) {
                    try {
                        video.muted = false;
                        video.volume = 1.0;
                        video.autoplay = true;
                        video.playsInline = true;

                        const promessa = video.play();

                        if (promessa) {
                            promessa.catch(() => {});
                        }

                        tentativas++;
                    } catch (e) {}
                }

                return {
                    videos: videos.length,
                    tentativas: tentativas
                };
            }
            """
        )

        print(
            "[CHROMIUM] Tentativa de reprodução:",
            resultado
        )

    except Exception as erro:
        print(
            f"[CHROMIUM] Erro tentando reproduzir vídeo: {erro}"
        )

    # ========================================================
    # CLIQUE NO PLAYER
    # ========================================================

    try:
        page.mouse.click(
            LARGURA // 2,
            ALTURA // 2
        )

        print("[CHROMIUM] Clique de ativação executado.")

    except Exception as erro:
        print(f"Erro no clique: {erro}")

    return playwright, browser, context, page


# ============================================================
# MONITOR DO PLAYER
# ============================================================

def monitorar_player(page):
    print("")
    print("Monitor do player iniciado.")
    print("A transmissão continuará ativa.")

    ultimo_estado = None

    while True:
        time.sleep(5)

        try:
            estado = page.evaluate(
                """
                () => {
                    const videos = Array.from(
                        document.querySelectorAll("video")
                    );

                    return videos.map((v, i) => ({
                        index: i,
                        paused: v.paused,
                        ended: v.ended,
                        muted: v.muted,
                        readyState: v.readyState,
                        currentTime: v.currentTime,
                        width: v.videoWidth,
                        height: v.videoHeight
                    }));
                }
                """
            )

            if estado != ultimo_estado:
                print(
                    "[CHROMIUM] Estado dos vídeos:",
                    estado
                )

                ultimo_estado = estado

            # Tenta reproduzir vídeos pausados
            page.evaluate(
                """
                () => {
                    const videos =
                        Array.from(document.querySelectorAll("video"));

                    for (const video of videos) {
                        if (video.paused && !video.ended) {
                            try {
                                video.play().catch(() => {});
                            } catch (e) {}
                        }
                    }
                }
                """
            )

        except Exception as erro:
            print(
                f"[CHROMIUM] Monitor temporariamente indisponível: {erro}"
            )


# ============================================================
# PRINCIPAL
# ============================================================

def iniciar():
    print("")
    print("==========================================================")
    print("                 INICIANDO WEBTV")
    print("==========================================================")

    preparar_stream()

    preparar_audio()

    preparar_tela()

    iniciar_servidor()

    # Túnel é iniciado antes do navegador
    # para o link aparecer logo no começo.
    iniciar_tunel()

    # FFmpeg começa a capturar a tela
    audio_monitor = "webtv.monitor"

    processo_ffmpeg = iniciar_ffmpeg(
        audio_monitor
    )

    # Aguarda FFmpeg começar a gerar HLS
    print("")
    print("Aguardando FFmpeg criar a transmissão...")

    for _ in range(15):
        if os.path.exists("stream/live.m3u8"):
            tamanho = os.path.getsize(
                "stream/live.m3u8"
            )

            if tamanho > 10:
                print("Playlist HLS criada.")
                break

        time.sleep(1)

    # Agora abre o painel
    playwright, browser, context, page = iniciar_navegador()

    print("")
    print("==========================================================")
    print("                 WEBTV INICIADA")
    print("==========================================================")
    print("Tela: 1280x720")
    print("Display: :99")
    print("FFmpeg: ativo")
    print("Chromium: ativo")
    print("HLS: stream/live.m3u8")
    print("==========================================================")
    print("")

    try:
        monitorar_player(page)

    finally:
        try:
            browser.close()
        except Exception:
            pass

        try:
            playwright.stop()
        except Exception:
            pass

        finalizar()


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    iniciar()
