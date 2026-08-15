import os
import time
import subprocess
import asyncio
from pyppeteer import launch

def iniciar():
    # 1. Prepara a pasta de streaming e o arquivo m3u8 inicial
    os.makedirs("stream", exist_ok=True)
    with open("stream/live.m3u8", "w") as f:
        f.write("#EXTM3U\n")

    # 2. Inicia o servidor HTTP em segundo plano imediatamente
    print("Iniciando servidor HTTP na porta 8080...")
    subprocess.Popen(["python3", "-m", "http.server", "8080", "--directory", "stream"])
    time.sleep(2)

    # 3. Liga a ponte de internet estável do sistema (.lhr.life)
    print("Iniciando tunel de rede seguro e estavel...")
    subprocess.Popen([
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=60",
        "-R", "80:localhost:8080", "nokey@localhost.run"
    ])
    time.sleep(5)

    print("\n==========================================================")
    print("======== SEU STREAMING FOI INICIADO COM SUCESSO ========")
    print("Suba a tela do log para copiar o seu endereço .lhr.life")
    print("==========================================================\n")

    # 4. Configura a tela virtual em alta definição
    os.system("Xvfb :99 -screen 0 1280x720x24 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(3) 

    # 5. FFmpeg captura a tela virtual :99.0 completa, com áudio nativo e SEM MOUSE
    ffmpeg_cmd = [
        "ffmpeg", "-f", "pulse", "-i", "auto_null.monitor",
        "-f", "x11grab", "-draw_mouse", "0", "-video_size", "1280x720", "-i", ":99.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-g", "60", "-hls_time", "2", 
        "-hls_list_size", "5", "-hls_flags", "delete_segments", 
        "stream/live.m3u8"
    ]
    print("FFmpeg iniciando gravacao continua em alta definicao...")
    processo_ffmpeg = subprocess.Popen(ffmpeg_cmd)

    # 6. Executa o navegador leve via Pyppeteer rodando na tela virtual
    async def abrir_navegador():
        print("Ligando navegador ultra leve em modo Quiosque...")
        browser = await launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--autoplay-policy=no-user-gesture-required",
                "--kiosk",
                "--start-fullscreen"
            ]
        )
        page = await browser.newPage()
        await page.setViewport({"width": 1280, "height": 720})
        
        url_alvo = "https://ais-pre-czbrtxxjttcqeqhdn3kw3n-102718744012.us-east5.run.app/watch"
        print(f"Acessando o site: {url_alvo}")
        
        try:
            await page.goto(url_alvo, timeout=0)
            print("Site conectado de fundo. Aguardando estabilizacao...")
            await asyncio.sleep(12)
            
            # === SIMULAÇÃO DE HARDWARE INDERRUBÁVEL ===
            print("Desferindo duplo clique físico no centro para forçar a tela cheia...")
            os.system("xdotool mousemove --display :99 640 360")
            await asyncio.sleep(0.5)
            os.system("xdotool dblclick --display :99 1")
            print("Comando de tela cheia enviado com sucesso.")
            
        except Exception as e:
            print(f"Aviso no navegador: {e}")

        # Mantém a sessão ativa de forma contínua vigiando o player
        while True:
            await asyncio.sleep(5)
            try:
                is_fullscreen = await page.evaluate("!!document.fullscreenElement")
                if not is_fullscreen:
                    os.system("xdotool mousemove --display :99 640 360")
                    os.system("xdotool dblclick --display :99 1")
            except:
                pass

    # Dispara a execução do loop assíncrono do navegador
    try:
        asyncio.get_event_loop().run_until_complete(abrir_navegador())
    except KeyboardInterrupt:
        processo_ffmpeg.terminate()

if __name__ == "__main__":
    iniciar()
