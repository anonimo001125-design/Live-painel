import os
import re
import time
import signal
import subprocess
from pathlib import Path

# ============================================================
# CONFIGURAÇÕES
# ============================================================

LARGURA = 1280
ALTURA = 720
DISPLAY = ":99"
PORTA = 8080

# COLOQUE AQUI O ENDEREÇO DO SEU PAINEL
URL_ALVO = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"

STREAM_DIR = Path("stream")
PLAYLIST = STREAM_DIR / "live.m3u8"

processos = []


# ============================================================
# EXECUTAR COMANDO
# ============================================================

def executar(cmd, check=False):
    print("[CMD]", " ".join(str(x) for x in cmd))

    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check
    )


# ============================================================
# PREPARAR PASTA
# ============================================================

def preparar_stream():
    STREAM_DIR.mkdir(parents=True, exist_ok=True)

    # Remove segmentos antigos
    for arquivo in STREAM_DIR.glob("segment_*.ts"):
        try:
            arquivo.unlink()
        except Exception:
            pass

    if PLAYLIST.exists():
        try:
            PLAYLIST.unlink()
        except Exception:
            pass


# ============================================================
# Xvfb
# ============================================================

def iniciar_xvfb():

    print("Iniciando Xvfb...")

    # Mata eventual Xvfb antigo
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
        f"{LARGURA}x{ALTURA}x24",
        "-ac",
        "+extension",
        "RANDR"
    ])

    processos.append(xvfb)

    os.environ["DISPLAY"] = DISPLAY

    time.sleep(3)

    print(f"Xvfb ativo em {DISPLAY}")


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

    # Cria uma saída virtual para o áudio do Chromium
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

    print("[PULSEAUDIO]", resultado.stdout.strip())

    # Define WebTV como saída padrão
    subprocess.run(
        ["pactl", "set-default-sink", "webtv"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Verifica o monitor
    resultado = subprocess.run(
        ["pactl", "list", "short", "sources"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    print("[PULSEAUDIO SOURCES]")
    print(resultado.stdout)

    return "webtv.monitor"


# ============================================================
# SERVIDOR HTTP
# ============================================================

def iniciar_servidor():

    print(f"Iniciando servidor HTTP na porta {PORTA}...")

    servidor = subprocess.Popen([
        "python3",
        "-m",
        "http.server",
        str(PORTA),
        "--directory",
        str(STREAM_DIR)
    ])

    processos.append(servidor)

    time.sleep(3)

    print("Servidor HTTP iniciado.")


# ============================================================
# SERVEO
# ============================================================

def iniciar_serveo():

    print("Iniciando túnel Serveo...")

    comando = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "ExitOnForwardFailure=yes",
        "-R", f"80:localhost:{PORTA}",
        "serveo.net"
    ]

    processo = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    processos.append(processo)

    url_encontrada = None

    inicio = time.time()

    while time.time() - inicio < 20:

        linha = processo.stdout.readline()

        if not linha:
            if processo.poll() is not None:
                break

            time.sleep(0.2)
            continue

        linha = linha.strip()

        if linha:
            print("[SERVEO]", linha)

        # Procura o endereço público
        encontrado = re.search(
            r"https://[a-zA-Z0-9\-\.]+",
            linha
        )

        if encontrado:
            url_encontrada = encontrado.group(0)

            # Evita pegar endereços internos/irrelevantes
            if "serveo.net" in url_encontrada:
                break

    if url_encontrada:
        print("")
        print("=" * 60)
        print("             TRANSMISSÃO ONLINE")
        print("=" * 60)
        print("")
        print("SITE:")
        print(url_encontrada)
        print("")
        print("PLAYLIST HLS:")
        print(f"{url_encontrada}/live.m3u8")
        print("")
        print("=" * 60)
    else:
        print("")
        print("AVISO: não foi possível detectar automaticamente")
        print("o endereço do Serveo no log.")
        print("O túnel pode continuar ativo.")
        print("")

    return processo


# ============================================================
# NAVEGADOR
# ============================================================

def iniciar_navegador():

    print("")
    print("=" * 60)
    print("INICIANDO CHROMIUM")
    print("=" * 60)

    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()

    browser = playwright.chromium.launch(

        headless=False,

        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",

            # AUTOPLAY
            "--autoplay-policy=no-user-gesture-required",
            "--allow-running-insecure-content",

            # TELA
            "--kiosk",
            "--start-fullscreen",
            "--start-maximized",
            f"--window-size={LARGURA},{ALTURA}",

            # ESTABILIDADE
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",

            # GPU
            "--disable-gpu",
            "--disable-software-rasterizer",

            # ÁUDIO
            "--use-fake-ui-for-media-stream",
            "--enable-features=AudioServiceOutOfProcess",

            # EVITA PROBLEMAS DE MEMÓRIA
            "--disable-dev-shm-usage"
        ]
    )

    page = browser.new_page(
        viewport={
            "width": LARGURA,
            "height": ALTURA
        }
    )

    print(f"Abrindo painel:")
    print(URL_ALVO)

    try:

        page.goto(
            URL_ALVO,
            wait_until="domcontentloaded",
            timeout=120000
        )

        print("Painel carregado.")

    except Exception as erro:

        print("[NAVEGADOR] Erro ao abrir página:")
        print(erro)

    time.sleep(8)

    # ========================================================
    # FORÇA JANELA MAXIMIZADA / FULLSCREEN
    # ========================================================

    print("Forçando tela cheia...")

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

        print("[FULLSCREEN] Aviso:", erro)

    # Outra tentativa usando xdotool
    try:

        resultado = subprocess.run(
            [
                "xdotool",
                "search",
                "--onlyvisible",
                "--name",
                ".*"
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )

        janelas = resultado.stdout.strip().splitlines()

        if janelas:

            janela = janelas[-1]

            subprocess.run(
                [
                    "xdotool",
                    "windowactivate",
                    janela
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            subprocess.run(
                [
                    "xdotool",
                    "key",
                    "--window",
                    janela,
                    "F11"
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            time.sleep(2)

    except Exception as erro:

        print("[
